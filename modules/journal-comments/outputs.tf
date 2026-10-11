output "deployment" {
  value = {
    public_url       = "https://${local.domain}"
    origin_hostname  = local.origin
    static_ip        = aws_lightsail_static_ip.comments.ip_address
    distribution_id  = aws_cloudfront_distribution.comments.id
    backup_bucket    = aws_s3_bucket.backup.id
    config_parameter = "${local.parameters}/config"
    host_iam_user    = aws_iam_user.host.name
    region           = var.region
    nft_table        = var.nft_table
    site_id          = var.site_id
    runtime_dir      = var.runtime_dir
    config_dir       = var.config_dir
    service_name     = var.operations_prefix
    origin_header    = var.origin_header
    brand_name       = var.brand_name
    timezone         = var.timezone
  }
}
