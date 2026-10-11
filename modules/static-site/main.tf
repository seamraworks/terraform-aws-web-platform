locals {
  all_aliases                = distinct(concat([var.domain_name], var.aliases))
  site_bucket_name           = var.aliases[0]
  build_artifact_bucket_name = "${local.site_bucket_name}-build-artifact"
  origin_id                  = "S3-${local.site_bucket_name}"
  codebuild_project_name     = lookup(var.resource_names, "codebuild_project_name", "${var.site_key}Website")
  codepipeline_name          = lookup(var.resource_names, "codepipeline_name", "${var.site_key}WebsitePipeline")
  lambda_function_name       = lookup(var.resource_names, "lambda_function_name", "${var.site_key}InvalidateCloudFront")
  codebuild_role_name        = lookup(var.resource_names, "codebuild_role_name", "${var.site_key}-website-codebuild-role")
  codepipeline_role_name     = lookup(var.resource_names, "codepipeline_role_name", "${var.site_key}-website-codepipeline-role")
  lambda_role_name           = lookup(var.resource_names, "lambda_role_name", "${var.site_key}-website-invalidation-role")
  codebuild_policy_name      = lookup(var.resource_names, "codebuild_policy_name", "${var.site_key}-website-codebuild-policy")
  codepipeline_policy_name   = lookup(var.resource_names, "codepipeline_policy_name", "${var.site_key}-website-codepipeline-policy")
  lambda_policy_name         = lookup(var.resource_names, "lambda_policy_name", "${var.site_key}-website-invalidation-policy")
  clean_url_function_name    = lookup(var.resource_names, "clean_url_function_name", "${var.site_key}-clean-url-rewrite")
  lambda_zip_path            = coalesce(var.lambda_zip_path, "${path.root}/.build/${var.site_key}-invalidation.zip")
  certificate_domain_names   = toset(local.all_aliases)
  validation_options_by_name = { for dvo in aws_acm_certificate.this.domain_validation_options : dvo.domain_name => dvo }
  pipeline_enabled_and_wired = var.enable_pipeline && var.github_connection_arn != null && var.github_full_repository_id != null
}

resource "aws_s3_bucket" "apex" {
  bucket = var.domain_name
}

resource "aws_s3_bucket" "site" {
  bucket = local.site_bucket_name
}

resource "aws_s3_bucket_website_configuration" "apex" {
  bucket = aws_s3_bucket.apex.id

  redirect_all_requests_to {
    host_name = local.site_bucket_name
  }
}

resource "aws_cloudfront_origin_access_control" "this" {
  count                             = var.origin_access_mode == "legacy_public" ? 0 : 1
  name                              = "${var.site_key}-s3-origin"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = jsonencode(merge({
    Version = "2012-10-17"
    Statement = concat(
      var.origin_access_mode != "private" ? [merge({
        Effect   = "Allow", Principal = "*", Action = "s3:GetObject",
        Resource = "${aws_s3_bucket.site.arn}/*"
      }, var.legacy_bucket_policy_sid == null ? {} : { Sid = var.legacy_bucket_policy_sid })] : [],
      var.origin_access_mode != "legacy_public" ? [{
        Sid       = "CloudFrontRead", Effect = "Allow", Principal = { Service = "cloudfront.amazonaws.com" },
        Action    = "s3:GetObject", Resource = "${aws_s3_bucket.site.arn}/*",
        Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.this.arn } }
      }] : []
    )
  }, var.legacy_bucket_policy_id == null ? {} : { Id = var.legacy_bucket_policy_id }))
  depends_on = [aws_s3_bucket_public_access_block.site]
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = var.origin_access_mode == "private"
  block_public_policy     = var.origin_access_mode == "private"
  ignore_public_acls      = var.origin_access_mode == "private"
  restrict_public_buckets = var.origin_access_mode == "private"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "apex" {
  bucket = aws_s3_bucket.apex.id

  rule {
    blocked_encryption_types = ["SSE-C"]
    bucket_key_enabled       = false

    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id

  rule {
    blocked_encryption_types = ["SSE-C"]
    bucket_key_enabled       = false

    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket" "build_artifact" {
  count  = local.pipeline_enabled_and_wired ? 1 : 0
  bucket = local.build_artifact_bucket_name
}

resource "aws_s3_bucket_public_access_block" "build_artifact" {
  count                   = local.pipeline_enabled_and_wired ? 1 : 0
  bucket                  = aws_s3_bucket.build_artifact[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "build_artifact" {
  count  = local.pipeline_enabled_and_wired ? 1 : 0
  bucket = aws_s3_bucket.build_artifact[0].id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "build_artifact" {
  count  = local.pipeline_enabled_and_wired ? 1 : 0
  bucket = aws_s3_bucket.build_artifact[0].id

  rule {
    blocked_encryption_types = ["SSE-C"]
    bucket_key_enabled       = false

    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_acm_certificate" "this" {
  provider = aws.use1

  domain_name               = var.domain_name
  subject_alternative_names = var.certificate_sans == null ? var.aliases : var.certificate_sans
  validation_method         = "DNS"
  key_algorithm             = "RSA_2048"

  options {
    certificate_transparency_logging_preference = "ENABLED"
    export                                      = "DISABLED"
  }
}

resource "aws_route53_record" "certificate_validation" {
  for_each = local.certificate_domain_names

  zone_id = var.hosted_zone_id
  name    = local.validation_options_by_name[each.value].resource_record_name
  type    = local.validation_options_by_name[each.value].resource_record_type
  records = [local.validation_options_by_name[each.value].resource_record_value]
  ttl     = 300
}

resource "aws_acm_certificate_validation" "this" {
  count    = var.wait_for_certificate_validation ? 1 : 0
  provider = aws.use1

  certificate_arn         = aws_acm_certificate.this.arn
  validation_record_fqdns = [for record in aws_route53_record.certificate_validation : record.fqdn]
}

resource "aws_cloudfront_function" "clean_urls" {
  count = var.enable_clean_url_rewrite ? 1 : 0

  name    = local.clean_url_function_name
  runtime = "cloudfront-js-2.0"
  comment = "Rewrite extensionless clean URLs to index.html before S3 origin lookup."
  publish = true
  code    = <<-JS
    function handler(event) {
      var request = event.request;
      var uri = request.uri;

      if (uri.length === 0 || uri.charAt(uri.length - 1) === '/') {
        request.uri = uri + 'index.html';
        return request;
      }

      var lastSegment = uri.substring(uri.lastIndexOf('/') + 1);
      if (lastSegment.indexOf('.') === -1) {
        request.uri = uri + '/index.html';
      }

      return request;
    }
  JS
}

resource "aws_cloudfront_distribution" "this" {
  enabled             = true
  aliases             = local.all_aliases
  default_root_object = "index.html"
  http_version        = "http2and3"
  is_ipv6_enabled     = false
  price_class         = var.cloudfront_price_class
  retain_on_delete    = false
  wait_for_deployment = true

  origin {
    origin_id                = local.origin_id
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_access_control_id = contains(["oac_transition", "private"], var.origin_access_mode) ? aws_cloudfront_origin_access_control.this[0].id : null
    connection_attempts      = 3
    connection_timeout       = 10
  }

  default_cache_behavior {
    target_origin_id       = local.origin_id
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    min_ttl                = 0
    default_ttl            = 86400
    max_ttl                = 31536000

    forwarded_values {
      query_string = true

      cookies {
        forward = "none"
      }
    }

    grpc_config {
      enabled = false
    }

    dynamic "function_association" {
      for_each = aws_cloudfront_function.clean_urls

      content {
        event_type   = "viewer-request"
        function_arn = function_association.value.arn
      }
    }
  }

  custom_error_response {
    error_code            = 403
    response_code         = 403
    response_page_path    = "/redirect.html"
    error_caching_min_ttl = 300
  }

  custom_error_response {
    error_code            = 404
    response_code         = 404
    response_page_path    = "/redirect.html"
    error_caching_min_ttl = 300
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = var.wait_for_certificate_validation ? aws_acm_certificate_validation.this[0].certificate_arn : aws_acm_certificate.this.arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

resource "aws_route53_record" "apex_a" {
  zone_id = var.hosted_zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.this.domain_name
    zone_id                = aws_cloudfront_distribution.this.hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "www_a" {
  for_each = toset(var.aliases)

  zone_id = var.hosted_zone_id
  name    = each.value
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.this.domain_name
    zone_id                = aws_cloudfront_distribution.this.hosted_zone_id
    evaluate_target_health = false
  }
}

resource "aws_iam_role" "codebuild" {
  count = local.pipeline_enabled_and_wired ? 1 : 0
  name  = local.codebuild_role_name
  path  = "/service-role/"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          Service = "codebuild.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_policy" "codebuild" {
  count = local.pipeline_enabled_and_wired && var.manage_role_policies ? 1 : 0
  name  = local.codebuild_policy_name
  path  = "/service-role/"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = [
          "arn:aws:logs:*:*:log-group:/aws/codebuild/${local.codebuild_project_name}",
          "arn:aws:logs:*:*:log-group:/aws/codebuild/${local.codebuild_project_name}:*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:GetBucketAcl",
          "s3:GetBucketLocation",
        ]
        Resource = [
          "arn:aws:s3:::codepipeline-*",
          "arn:aws:s3:::codepipeline-*/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:GetBucketAcl",
          "s3:GetBucketLocation",
          "s3:ListBucket",
        ]
        Resource = [
          aws_s3_bucket.build_artifact[0].arn,
          "${aws_s3_bucket.build_artifact[0].arn}/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "codebuild:CreateReportGroup",
          "codebuild:CreateReport",
          "codebuild:UpdateReport",
          "codebuild:BatchPutTestCases",
          "codebuild:BatchPutCodeCoverages",
        ]
        Resource = [
          "arn:aws:codebuild:*:*:report-group/${local.codebuild_project_name}-*",
        ]
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "codebuild" {
  count      = local.pipeline_enabled_and_wired && var.manage_role_policies ? 1 : 0
  role       = aws_iam_role.codebuild[0].name
  policy_arn = aws_iam_policy.codebuild[0].arn
}

resource "aws_codebuild_project" "this" {
  count          = local.pipeline_enabled_and_wired ? 1 : 0
  name           = local.codebuild_project_name
  service_role   = aws_iam_role.codebuild[0].arn
  build_timeout  = var.codebuild_build_timeout
  queued_timeout = var.codebuild_queued_timeout
  source_version = var.branch
  encryption_key = var.codebuild_encryption_key

  artifacts {
    type                   = "S3"
    location               = aws_s3_bucket.build_artifact[0].bucket
    name                   = local.codebuild_project_name
    namespace_type         = "NONE"
    packaging              = "NONE"
    override_artifact_name = false
    encryption_disabled    = true
  }

  cache {
    type = "NO_CACHE"
  }

  environment {
    type                        = "LINUX_CONTAINER"
    image                       = "aws/codebuild/standard:8.0"
    compute_type                = "BUILD_GENERAL1_SMALL"
    privileged_mode             = false
    image_pull_credentials_type = "CODEBUILD"
  }

  source {
    type                = "GITHUB"
    location            = "https://github.com/${var.github_full_repository_id}.git"
    git_clone_depth     = 1
    insecure_ssl        = false
    report_build_status = false
    buildspec           = var.buildspec

    git_submodules_config {
      fetch_submodules = false
    }
  }

  logs_config {
    cloudwatch_logs {
      status = "ENABLED"
    }

    s3_logs {
      status              = "DISABLED"
      encryption_disabled = false
    }
  }
}

resource "aws_iam_role" "lambda_invalidation" {
  count = local.pipeline_enabled_and_wired ? 1 : 0
  name  = local.lambda_role_name
  path  = "/service-role/"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_policy" "lambda_invalidation" {
  count = local.pipeline_enabled_and_wired && var.manage_role_policies ? 1 : 0
  name  = local.lambda_policy_name
  path  = "/service-role/"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "arn:aws:logs:*:*:log-group:/aws/lambda/${local.lambda_function_name}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "codepipeline:PutJobFailureResult",
          "codepipeline:PutJobSuccessResult",
          "cloudfront:CreateInvalidation",
        ]
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_invalidation" {
  count      = local.pipeline_enabled_and_wired && var.manage_role_policies ? 1 : 0
  role       = aws_iam_role.lambda_invalidation[0].name
  policy_arn = aws_iam_policy.lambda_invalidation[0].arn
}

resource "aws_lambda_function" "invalidate_cloudfront" {
  count = local.pipeline_enabled_and_wired ? 1 : 0

  function_name    = local.lambda_function_name
  description      = ""
  role             = aws_iam_role.lambda_invalidation[0].arn
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.13"
  architectures    = ["x86_64"]
  filename         = local.lambda_zip_path
  source_code_hash = var.lambda_source_code_hash != null ? var.lambda_source_code_hash : (var.lambda_zip_path != null ? filebase64sha256(var.lambda_zip_path) : data.archive_file.invalidation[0].output_base64sha256)
  memory_size      = 128
  timeout          = 3
  package_type     = "Zip"

  ephemeral_storage {
    size = 512
  }

  logging_config {
    log_format = "Text"
    log_group  = "/aws/lambda/${local.lambda_function_name}"
  }

  tracing_config {
    mode = "PassThrough"
  }
}

resource "aws_iam_role" "codepipeline" {
  count = local.pipeline_enabled_and_wired ? 1 : 0
  name  = local.codepipeline_role_name
  path  = "/service-role/"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          Service = "codepipeline.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_policy" "codepipeline" {
  count = local.pipeline_enabled_and_wired && var.manage_role_policies ? 1 : 0
  name  = local.codepipeline_policy_name
  path  = "/service-role/"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "codestar-connections:UseConnection",
          "codeconnections:UseConnection",
        ]
        Resource = var.github_connection_arn
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:GetBucketVersioning",
          "s3:GetBucketLocation",
          "s3:PutObject",
        ]
        Resource = [
          "arn:aws:s3:::${var.codepipeline_artifact_bucket}",
          "arn:aws:s3:::${var.codepipeline_artifact_bucket}/*",
          aws_s3_bucket.site.arn,
          "${aws_s3_bucket.site.arn}/*",
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "codebuild:BatchGetBuilds",
          "codebuild:StartBuild",
        ]
        Resource = aws_codebuild_project.this[0].arn
      },
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction",
          "lambda:ListFunctions",
        ]
        Resource = [
          aws_lambda_function.invalidate_cloudfront[0].arn,
          "${aws_lambda_function.invalidate_cloudfront[0].arn}:*",
        ]
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "codepipeline" {
  count      = local.pipeline_enabled_and_wired && var.manage_role_policies ? 1 : 0
  role       = aws_iam_role.codepipeline[0].name
  policy_arn = aws_iam_policy.codepipeline[0].arn
}

resource "aws_codepipeline" "this" {
  count          = local.pipeline_enabled_and_wired ? 1 : 0
  name           = local.codepipeline_name
  role_arn       = aws_iam_role.codepipeline[0].arn
  pipeline_type  = "V1"
  execution_mode = "SUPERSEDED"

  artifact_store {
    type     = "S3"
    location = var.codepipeline_artifact_bucket
  }

  stage {
    name = "Source"

    action {
      name             = coalesce(var.source_action_name, "github_${replace(var.github_full_repository_id, "/", "_")}")
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeStarSourceConnection"
      version          = "1"
      region           = var.pipeline_action_region
      run_order        = 1
      namespace        = "SourceVariables"
      output_artifacts = ["SourceArtifact"]

      configuration = {
        BranchName           = var.branch
        ConnectionArn        = var.github_connection_arn
        FullRepositoryId     = var.github_full_repository_id
        OutputArtifactFormat = "CODE_ZIP"
      }
    }
  }

  stage {
    name = "Build"

    action {
      name             = "Build"
      category         = "Build"
      owner            = "AWS"
      provider         = "CodeBuild"
      version          = "1"
      region           = var.pipeline_action_region
      run_order        = 1
      namespace        = "BuildVariables"
      input_artifacts  = ["SourceArtifact"]
      output_artifacts = ["BuildArtifact"]

      configuration = {
        ProjectName = aws_codebuild_project.this[0].name
      }
    }
  }

  stage {
    name = "Deploy"

    action {
      name            = "Deploy"
      category        = "Deploy"
      owner           = "AWS"
      provider        = "S3"
      version         = "1"
      run_order       = 1
      namespace       = "DeployVariables"
      input_artifacts = ["BuildArtifact"]

      configuration = {
        BucketName = aws_s3_bucket.site.bucket
        Extract    = "true"
      }
    }
  }

  stage {
    name = "InvalidateCloudfront"

    action {
      name      = "InvalidateCloudfront"
      category  = "Invoke"
      owner     = "AWS"
      provider  = "Lambda"
      version   = "1"
      region    = var.pipeline_action_region
      run_order = 1

      configuration = {
        FunctionName   = aws_lambda_function.invalidate_cloudfront[0].function_name
        UserParameters = var.invalidation_user_parameters != null ? var.invalidation_user_parameters : jsonencode({ distributionId = aws_cloudfront_distribution.this.id, objectPaths = ["/*"] })
      }
    }
  }
}

data "archive_file" "invalidation" {
  count            = local.pipeline_enabled_and_wired ? 1 : 0
  type             = "zip"
  source_file      = "${path.module}/lambda/lambda_function.py"
  output_path      = "${path.root}/.build/${var.site_key}-invalidation.zip"
  output_file_mode = "0644"
}

resource "aws_iam_role_policy_attachment" "codebuild_existing" {
  for_each   = local.pipeline_enabled_and_wired ? var.codebuild_existing_policies : {}
  role       = aws_iam_role.codebuild[0].name
  policy_arn = each.value
}

resource "aws_iam_role_policy_attachment" "codepipeline_existing" {
  for_each   = local.pipeline_enabled_and_wired ? var.codepipeline_existing_policies : {}
  role       = aws_iam_role.codepipeline[0].name
  policy_arn = each.value
}

resource "aws_iam_role_policy_attachment" "lambda_existing" {
  for_each   = local.pipeline_enabled_and_wired ? var.lambda_existing_policies : {}
  role       = aws_iam_role.lambda_invalidation[0].name
  policy_arn = each.value
}
