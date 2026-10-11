locals {
  name       = var.name
  domain     = var.domain
  origin     = var.origin_domain
  parameters = var.parameter_prefix
  tags       = var.tags
}

data "aws_caller_identity" "current" {}

resource "aws_lightsail_key_pair" "admin" {
  name       = "${local.name}-admin"
  public_key = var.ssh_public_key
}

resource "aws_lightsail_instance" "comments" {
  name              = "${local.name}-host"
  availability_zone = "${var.region}a"
  blueprint_id      = "ubuntu_24_04"
  bundle_id         = "nano_3_0"
  ip_address_type   = "dualstack"
  key_pair_name     = aws_lightsail_key_pair.admin.name
  user_data         = templatefile("${path.module}/bootstrap.sh", { runtime_dir = var.runtime_dir, config_dir = var.config_dir })
  tags              = local.tags
  lifecycle {
    prevent_destroy = true
    # Bootstrap runs only on creation; update the persistent host via install.sh.
    ignore_changes = [user_data]
  }
}

resource "aws_lightsail_static_ip" "comments" { name = local.name }
resource "aws_lightsail_static_ip_attachment" "comments" {
  static_ip_name = aws_lightsail_static_ip.comments.name
  instance_name  = aws_lightsail_instance.comments.name
}

# The host's nftables set follows AWS's changing CloudFront origin ranges.
# Do not duplicate that changing set in Lightsail's 60-rule firewall.
resource "aws_lightsail_instance_public_ports" "comments" {
  instance_name = aws_lightsail_instance.comments.name
  port_info {
    protocol  = "tcp"
    from_port = 22
    to_port   = 22
    cidrs     = var.admin_cidrs
  }
  port_info {
    protocol  = "tcp"
    from_port = 80
    to_port   = 80
    cidrs     = ["0.0.0.0/0"]
  }
  port_info {
    protocol  = "tcp"
    from_port = 443
    to_port   = 443
    cidrs     = ["0.0.0.0/0"]
  }
}

resource "aws_route53_record" "origin" {
  zone_id = var.zone_id
  name    = local.origin
  type    = "A"
  ttl     = 300
  records = [aws_lightsail_static_ip.comments.ip_address]
}

resource "aws_acm_certificate" "comments" {
  provider          = aws.use1
  domain_name       = local.domain
  validation_method = "DNS"
  tags              = local.tags
  lifecycle { create_before_destroy = true }
}
resource "aws_route53_record" "certificate" {
  for_each = toset([local.domain])
  zone_id  = var.zone_id
  name     = one(aws_acm_certificate.comments.domain_validation_options).resource_record_name
  type     = one(aws_acm_certificate.comments.domain_validation_options).resource_record_type
  ttl      = 300
  records  = [one(aws_acm_certificate.comments.domain_validation_options).resource_record_value]
}
resource "aws_acm_certificate_validation" "comments" {
  provider                = aws.use1
  certificate_arn         = aws_acm_certificate.comments.arn
  validation_record_fqdns = [for record in aws_route53_record.certificate : record.fqdn]
}

data "aws_cloudfront_cache_policy" "disabled" { name = "Managed-CachingDisabled" }
data "aws_cloudfront_cache_policy" "static" { name = "Managed-CachingOptimized" }
data "aws_cloudfront_origin_request_policy" "dynamic" { name = "Managed-AllViewerExceptHostHeader" }

resource "aws_cloudfront_distribution" "comments" {
  enabled         = true
  is_ipv6_enabled = true
  aliases         = [local.domain]
  comment         = var.description
  price_class     = "PriceClass_100"
  http_version    = "http2and3"
  origin {
    domain_name = local.origin
    origin_id   = "lightsail"
    custom_header {
      name  = var.origin_header
      value = var.origin_secret
    }
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }
  default_cache_behavior {
    target_origin_id         = "lightsail"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.dynamic.id
    compress                 = true
  }
  ordered_cache_behavior {
    path_pattern           = "/web/*"
    target_origin_id       = "lightsail"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.static.id
    compress               = true
  }
  dynamic "custom_error_response" {
    for_each = toset([400, 403, 404, 405, 414, 416, 500, 501, 502, 503, 504])
    content {
      error_code            = custom_error_response.value
      error_caching_min_ttl = 0
    }
  }
  restrictions {
    geo_restriction { restriction_type = "none" }
  }
  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.comments.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
  tags = local.tags
}
resource "aws_route53_record" "comments" {
  for_each = toset(["A", "AAAA"])
  zone_id  = var.zone_id
  name     = local.domain
  type     = each.key
  alias {
    name                   = aws_cloudfront_distribution.comments.domain_name
    zone_id                = aws_cloudfront_distribution.comments.hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_s3_bucket" "backup" {
  bucket = "${local.name}-${data.aws_caller_identity.current.account_id}"
  tags   = local.tags
  lifecycle { prevent_destroy = true }
}
resource "aws_s3_bucket_public_access_block" "backup" {
  bucket                  = aws_s3_bucket.backup.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_lifecycle_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id
  rule {
    id     = "retention"
    status = "Enabled"
    filter { prefix = "" }
    expiration { days = 30 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}
resource "aws_s3_bucket_policy" "backup" {
  bucket = aws_s3_bucket.backup.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Sid       = "RequireTLS", Effect = "Deny", Principal = "*", Action = "s3:*",
    Resource  = [aws_s3_bucket.backup.arn, "${aws_s3_bucket.backup.arn}/*"],
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }] })
}

# Lightsail has no EC2 instance profile. Keys are created outside Terraform
# and transferred over SSH, never included in user_data or Terraform outputs.
resource "aws_iam_user" "host" { name = local.name }
resource "aws_iam_user_policy" "host" {
  user = aws_iam_user.host.name
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ssm:GetParameter"], Resource = "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter${local.parameters}/config" },
    { Effect = "Allow", Action = ["s3:PutObject", "s3:GetObject"], Resource = "${aws_s3_bucket.backup.arn}/*" },
    { Effect = "Allow", Action = ["cloudwatch:PutMetricData"], Resource = "*",
    Condition = { StringEquals = { "cloudwatch:namespace" = var.metric_namespace } } },
    # SES also authorizes the identity's default configuration set on SMTP sends.
    { Effect = "Allow", Action = ["ses:SendRawEmail"], Resource = [var.ses_identity_arn, var.ses_configuration_set_arn],
    Condition = { StringEquals = { "ses:FromAddress" = var.email_from } } }
  ] })
}

# Independent of the VM. Health transitions are formatted by Lambda/SES;
# the confirmed SNS email subscription is the SES-independent fallback.
resource "aws_sns_topic" "operations" {
  name = "${var.operations_prefix}-operations"
  tags = local.tags
}
resource "aws_sns_topic_subscription" "operations" {
  topic_arn           = aws_sns_topic.operations.arn
  protocol            = "email"
  endpoint            = var.owner_email
  filter_policy_scope = "MessageBody"
  filter_policy = jsonencode({ AlarmName = [
    "${var.operations_prefix}-alert-delivery-errors", "${var.operations_prefix}-alert-undelivered"
  ] })
  # Keep native health mail until the replacement subscription is ready.
  depends_on = [aws_sns_topic_subscription.alert_mail]
}
resource "aws_cloudwatch_metric_alarm" "health" {
  alarm_name          = "${var.operations_prefix}-health"
  alarm_description   = "Comments need attention: worker/host disk monitor stopped, disk or inodes >=80%, recovery paused, or sweep/backup overdue. Run sudo comments status."
  namespace           = var.metric_namespace
  metric_name         = "Healthy"
  dimensions          = { Site = var.site_id }
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.operations.arn]
  ok_actions          = [aws_sns_topic.operations.arn]
  tags                = local.tags
}
