locals {
  domain    = var.domain
  mail_from = "${var.mail_from_subdomain}.${local.domain}"
}

data "aws_caller_identity" "current" {}

resource "aws_sesv2_configuration_set" "comments" {
  configuration_set_name = var.configuration_set_name
  reputation_options { reputation_metrics_enabled = true }
  sending_options { sending_enabled = true }
}

resource "aws_sesv2_email_identity" "comments" {
  email_identity         = local.domain
  configuration_set_name = aws_sesv2_configuration_set.comments.configuration_set_name
  dkim_signing_attributes {
    next_signing_key_length = "RSA_2048_BIT"
  }
  lifecycle { prevent_destroy = true }
}

# The setup contact is also a verified recipient for sandbox delivery tests.
resource "aws_sesv2_email_identity" "owner" {
  email_identity         = var.owner_email
  configuration_set_name = aws_sesv2_configuration_set.comments.configuration_set_name
  lifecycle { prevent_destroy = true }
}

# Easy DKIM proves ownership without the legacy _amazonses TXT record.
resource "aws_route53_record" "dkim" {
  count   = 3
  zone_id = var.zone_id
  name    = "${aws_sesv2_email_identity.comments.dkim_signing_attributes[0].tokens[count.index]}._domainkey.${local.domain}"
  type    = "CNAME"
  ttl     = 1800
  records = ["${aws_sesv2_email_identity.comments.dkim_signing_attributes[0].tokens[count.index]}.dkim.amazonses.com"]
}

resource "aws_sesv2_email_identity_mail_from_attributes" "comments" {
  email_identity         = aws_sesv2_email_identity.comments.email_identity
  mail_from_domain       = local.mail_from
  behavior_on_mx_failure = "USE_DEFAULT_VALUE"
}

resource "aws_route53_record" "mail_from_mx" {
  zone_id = var.zone_id
  name    = local.mail_from
  type    = "MX"
  ttl     = 300
  records = ["10 feedback-smtp.${var.region}.amazonses.com"]
}

resource "aws_route53_record" "mail_from_spf" {
  zone_id = var.zone_id
  name    = local.mail_from
  type    = "TXT"
  ttl     = 300
  records = ["v=spf1 include:amazonses.com ~all"]
}

resource "aws_sns_topic" "feedback" {
  name = var.feedback_topic_name
  lifecycle { prevent_destroy = true }
}

resource "aws_sns_topic_policy" "feedback" {
  arn = aws_sns_topic.feedback.arn
  # Preserve the existing account-owner permissions while granting this SES
  # identity explicit publication rights. Policy and topic have separate owners.
  policy = jsonencode({
    Version = "2008-10-17"
    Id      = "__default_policy_ID"
    Statement = [
      {
        Sid       = "__default_statement_ID"
        Effect    = "Allow"
        Principal = { AWS = "*" }
        Action = [
          "SNS:Publish", "SNS:RemovePermission", "SNS:SetTopicAttributes",
          "SNS:DeleteTopic", "SNS:ListSubscriptionsByTopic",
          "SNS:GetTopicAttributes", "SNS:AddPermission", "SNS:Subscribe"
        ]
        Resource  = aws_sns_topic.feedback.arn
        Condition = { StringEquals = { "AWS:SourceAccount" = data.aws_caller_identity.current.account_id } }
      },
      {
        Sid       = var.feedback_policy_sid
        Effect    = "Allow"
        Principal = { Service = "ses.amazonaws.com" }
        Action    = "sns:Publish"
        Resource  = aws_sns_topic.feedback.arn
        Condition = { StringEquals = {
          "AWS:SourceAccount" = data.aws_caller_identity.current.account_id
          "AWS:SourceArn"     = aws_sesv2_email_identity.comments.arn
        } }
      }
    ]
  })
}

resource "aws_sns_topic_subscription" "feedback" {
  topic_arn = aws_sns_topic.feedback.arn
  protocol  = "email"
  endpoint  = var.owner_email
  lifecycle {
    # These are Terraform's create-time controls, not remote subscription
    # attributes. Imported, already-confirmed subscriptions have null values.
    ignore_changes = [confirmation_timeout_in_minutes, endpoint_auto_confirms]
  }
}

resource "aws_ses_identity_notification_topic" "feedback" {
  for_each                 = toset(["Bounce", "Complaint"])
  identity                 = aws_sesv2_email_identity.comments.email_identity
  notification_type        = each.key
  topic_arn                = aws_sns_topic.feedback.arn
  include_original_headers = false
  depends_on               = [aws_sns_topic_policy.feedback, aws_sns_topic_subscription.feedback]
}

resource "aws_sesv2_email_identity_feedback_attributes" "comments" {
  email_identity           = aws_sesv2_email_identity.comments.email_identity
  email_forwarding_enabled = false
  depends_on               = [aws_ses_identity_notification_topic.feedback]
}
