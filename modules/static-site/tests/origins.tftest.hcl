mock_provider "aws" {
  mock_resource "aws_cloudfront_distribution" {
    defaults = { arn = "arn:aws:cloudfront::123456789012:distribution/EXAMPLE", domain_name = "example.cloudfront.net", hosted_zone_id = "Z2FDTNDATAQYW2" }
  }
}
mock_provider "aws" {
  alias = "use1"
  mock_resource "aws_acm_certificate" {
    defaults = {
      arn = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-4000-8000-000000000000"
      domain_validation_options = [
        { domain_name = "example.com", resource_record_name = "_apex.example.com", resource_record_type = "CNAME", resource_record_value = "_apex.acm-validations.aws" },
        { domain_name = "www.example.com", resource_record_name = "_www.example.com", resource_record_type = "CNAME", resource_record_value = "_www.acm-validations.aws" }
      ]
    }
  }
}
variables {
  site_key        = "example"
  domain_name     = "example.com"
  aliases         = ["www.example.com"]
  hosted_zone_id  = "ZEXAMPLE"
  enable_pipeline = false
}
run "private_by_default" {
  command = apply
  assert {
    condition     = aws_s3_bucket_public_access_block.site.block_public_policy && aws_s3_bucket_public_access_block.site.restrict_public_buckets
    error_message = "Fresh origins must block public bucket access."
  }
  assert {
    condition     = length(jsondecode(aws_s3_bucket_policy.site.policy).Statement) == 1 && jsondecode(aws_s3_bucket_policy.site.policy).Statement[0].Principal.Service == "cloudfront.amazonaws.com"
    error_message = "Only this CloudFront service origin may read the bucket."
  }
}
run "legacy_parity" {
  command = apply
  variables { origin_access_mode = "legacy_public" }
  assert {
    condition     = !aws_s3_bucket_public_access_block.site.block_public_policy && length(aws_cloudfront_origin_access_control.this) == 0
    error_message = "Legacy adoption must preserve public access until migration."
  }
}
run "prepare_before_attachment" {
  command = apply
  variables { origin_access_mode = "oac_prepare" }
  assert {
    condition     = length(jsondecode(aws_s3_bucket_policy.site.policy).Statement) == 2 && (one(aws_cloudfront_distribution.this.origin).origin_access_control_id == null || one(aws_cloudfront_distribution.this.origin).origin_access_control_id == "")
    error_message = "Prepare permissions before switching request signing."
  }
}
run "signed_before_private" {
  command = apply
  variables { origin_access_mode = "oac_transition" }
  assert {
    condition     = length(jsondecode(aws_s3_bucket_policy.site.policy).Statement) == 2 && !aws_s3_bucket_public_access_block.site.block_public_policy
    error_message = "Keep public permission while verifying OAC signing."
  }
}
