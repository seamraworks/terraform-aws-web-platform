variable "site_key" {
  description = "Short stable identifier used in resource names."
  type        = string
}

variable "domain_name" {
  description = "Apex domain name, for example example.com."
  type        = string
}

variable "aliases" {
  description = "Additional CloudFront aliases. The common case is the www host."
  type        = list(string)

  validation {
    condition     = length(var.aliases) > 0
    error_message = "At least one alias is required; use the www host for the current static-site pattern."
  }
}

variable "hosted_zone_id" {
  description = "Existing Route 53 hosted zone ID. The module never creates hosted zones because newly created zones receive new nameservers."
  type        = string
}

variable "github_connection_arn" {
  description = "Existing AVAILABLE CodeConnections/CodeStar connection ARN for the pipeline source stage; GitHub application approval is a manual prerequisite."
  type        = string
  default     = null
}

variable "github_full_repository_id" {
  description = "GitHub owner/repo value used by the CodePipeline source action."
  type        = string
  default     = null
}

variable "branch" {
  description = "Git branch used by the pipeline."
  type        = string
  default     = "main"
}

variable "enable_pipeline" {
  description = "Whether to create CodeBuild, CodePipeline, and the invalidation Lambda."
  type        = bool
  default     = true
}

variable "enable_clean_url_rewrite" {
  description = "Whether to attach a CloudFront Function that rewrites extensionless clean URLs to index.html objects."
  type        = bool
  default     = false
}

variable "viewer_request_function_code" {
  description = "Optional CloudFront viewer-request JavaScript instead of the built-in clean URL rewrite; null preserves existing behavior."
  type        = string
  default     = null

  validation {
    condition     = var.viewer_request_function_code == null || !var.enable_clean_url_rewrite
    error_message = "Choose custom viewer-request code or the built-in clean URL rewrite."
  }
}

variable "error_page_path" {
  description = "Root-relative page served for origin 403 and 404 errors; defaults retain the legacy redirect page."
  type        = string
  default     = "/redirect.html"

  validation {
    condition     = startswith(var.error_page_path, "/")
    error_message = "The error page must use a root-relative path."
  }
}

variable "forbidden_response_code" {
  description = "Viewer status for origin 403 errors; use 404 for private static origins that return 403 for missing objects."
  type        = number
  default     = 403

  validation {
    condition     = contains([403, 404], var.forbidden_response_code)
    error_message = "Origin 403 errors must remain forbidden or be classified as missing objects."
  }
}

variable "error_caching_min_ttl" {
  description = "Minimum cache time in seconds for origin 403 and 404 responses."
  type        = number
  default     = 300
}

variable "buildspec" {
  description = "Optional CodeBuild buildspec content; null reads buildspec.yml from the repository."
  type        = string
  default     = null
}

variable "codepipeline_artifact_bucket" {
  description = "Existing shared CodePipeline artifact bucket."
  type        = string
  default     = null
}

variable "cloudfront_price_class" {
  description = "CloudFront edge-location price class. PriceClass_100 keeps new experimental sites to US, Canada, Europe, and Israel."
  type        = string
  default     = "PriceClass_100"
}

variable "codebuild_build_timeout" {
  description = "Maximum CodeBuild build duration in minutes."
  type        = number
  default     = 20
}

variable "codebuild_queued_timeout" {
  description = "Maximum CodeBuild queue wait in minutes."
  type        = number
  default     = 60
}

variable "lambda_zip_path" {
  description = "Local zip package for the CloudFront invalidation Lambda."
  type        = string
  default     = null
}

variable "resource_names" {
  description = "Override established AWS resource names when adopting an existing deployment."
  type        = map(string)
  default     = {}
}

variable "certificate_sans" {
  description = "Override certificate SANs exactly during adoption; null uses the aliases."
  type        = list(string)
  default     = null
}

variable "wait_for_certificate_validation" {
  description = "Wait for DNS certificate verification; false adopts a certificate already verified outside this module."
  type        = bool
  default     = true
}

variable "manage_role_policies" {
  description = "Create the bundled role policies; false retains existing policy attachments supplied below."
  type        = bool
  default     = true
}

variable "codebuild_existing_policies" {
  description = "Stable attachment keys mapped to existing IAM policy ARNs for the build role."
  type        = map(string)
  default     = {}
}

variable "codepipeline_existing_policies" {
  description = "Stable attachment keys mapped to existing IAM policy ARNs for the pipeline role."
  type        = map(string)
  default     = {}
}

variable "lambda_existing_policies" {
  description = "Stable attachment keys mapped to existing IAM policy ARNs for the invalidation role."
  type        = map(string)
  default     = {}
}

variable "codebuild_encryption_key" {
  description = "Existing CodeBuild KMS key ARN; null keeps the service default."
  type        = string
  default     = null
}

variable "source_action_name" {
  description = "Override the existing GitHub source action name."
  type        = string
  default     = null
}

variable "invalidation_user_parameters" {
  description = "Override the existing JSON invalidation action parameters during adoption."
  type        = string
  default     = null
}

variable "lambda_source_code_hash" {
  description = "Optional existing package hash; otherwise hash the supplied ZIP or bundled source."
  type        = string
  default     = null
}

variable "legacy_bucket_policy_id" {
  description = "Preserve the optional policy Id of an existing public origin."
  type        = string
  default     = null
}

variable "legacy_bucket_policy_sid" {
  description = "Preserve the optional statement Sid of an existing public origin."
  type        = string
  default     = null
}

variable "origin_access_mode" {
  type        = string
  default     = "private"
  description = "Use legacy_public, oac_prepare, oac_transition, private in order when adopting public origins."
  validation {
    condition     = contains(["legacy_public", "oac_prepare", "oac_transition", "private"], var.origin_access_mode)
    error_message = "Unknown origin access mode."
  }
}

variable "pipeline_action_region" {
  description = "Preserve an explicit region on existing pipeline actions; null omits it."
  type        = string
  default     = null
}
