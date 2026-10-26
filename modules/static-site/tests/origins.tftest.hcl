mock_provider "aws" {
  mock_resource "aws_cloudfront_function" {
    defaults = { arn = "arn:aws:cloudfront::123456789012:function/example-routing" }
  }
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

run "legacy_error_response_defaults" {
  command = apply
  assert {
    condition = alltrue([for response in aws_cloudfront_distribution.this.custom_error_response :
      response.error_code == response.response_code && response.response_page_path == "/redirect.html" && response.error_caching_min_ttl == 300
    ]) && length(aws_cloudfront_distribution.this.custom_error_response) == 2
    error_message = "Existing sites must retain their error pages and HTTP statuses by default."
  }
  assert {
    condition     = length(aws_cloudfront_function.clean_urls) == 0
    error_message = "Default upgrades must not attach new request routing."
  }
}

run "custom_routing_and_missing_pages" {
  command = apply
  variables {
    viewer_request_function_code = "function handler(event) { return event.request; }"
    error_page_path              = "/404.html"
    forbidden_response_code      = 404
    error_caching_min_ttl        = 30
  }
  assert {
    condition     = length(one(aws_cloudfront_distribution.this.default_cache_behavior).function_association) == 1
    error_message = "Custom routing must be attached to the existing distribution."
  }
  assert {
    condition = alltrue([for response in aws_cloudfront_distribution.this.custom_error_response :
      response.response_code == 404 && response.response_page_path == "/404.html" && response.error_caching_min_ttl == 30
    ])
    error_message = "Missing private-origin objects must use the configured HTTP status and error page."
  }
}

run "built_in_clean_urls_still_available" {
  command = apply
  variables {
    enable_clean_url_rewrite = true
  }
  assert {
    condition     = strcontains(aws_cloudfront_function.clean_urls[0].code, "request.uri = uri + 'index.html'")
    error_message = "Existing clean URL callers must retain their built-in function."
  }
}

run "reject_conflicting_request_handlers" {
  command = plan
  variables {
    enable_clean_url_rewrite     = true
    viewer_request_function_code = "function handler(event) { return event.request; }"
  }
  expect_failures = [var.viewer_request_function_code]
}
