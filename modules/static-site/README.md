# static-site

S3/CloudFront static hosting with private OAC origins and an optional GitHub pipeline. Existing hosted zones and GitHub connection authorization belong to the caller.

Use AWS provider 6.x; CloudFront certificates require the `aws.use1` alias in us-east-1.

## Inputs

| Input | Type | Default | Description |
| --- | --- | --- | --- |
| `site_key` | `string` | Required | Short stable identifier used in resource names. |
| `domain_name` | `string` | Required | Apex domain name, for example example.com. |
| `aliases` | `list(string)` | Required | Additional CloudFront aliases. The common case is the www host. |
| `hosted_zone_id` | `string` | Required | Existing Route 53 hosted zone ID. The module never creates hosted zones because newly created zones receive new nameservers. |
| `github_connection_arn` | `string` | `null` | Existing AVAILABLE CodeConnections/CodeStar connection ARN for the pipeline source stage; GitHub application approval is a manual prerequisite. |
| `github_full_repository_id` | `string` | `null` | GitHub owner/repo value used by the CodePipeline source action. |
| `branch` | `string` | `"main"` | Git branch used by the pipeline. |
| `enable_pipeline` | `bool` | `true` | Whether to create CodeBuild, CodePipeline, and the invalidation Lambda. |
| `enable_clean_url_rewrite` | `bool` | `false` | Whether to attach a CloudFront Function that rewrites extensionless clean URLs to index.html objects. |
| `buildspec` | `string` | `null` | Optional CodeBuild buildspec content; null reads buildspec.yml from the repository. |
| `codepipeline_artifact_bucket` | `string` | `null` | Existing shared CodePipeline artifact bucket. |
| `cloudfront_price_class` | `string` | `"PriceClass_100"` | CloudFront edge-location price class. PriceClass_100 keeps new experimental sites to US, Canada, Europe, and Israel. |
| `codebuild_build_timeout` | `number` | `20` | Maximum CodeBuild build duration in minutes. |
| `codebuild_queued_timeout` | `number` | `60` | Maximum CodeBuild queue wait in minutes. |
| `lambda_zip_path` | `string` | `null` | Local zip package for the CloudFront invalidation Lambda. |
| `resource_names` | `map(string)` | `{}` | Override established AWS resource names when adopting an existing deployment. |
| `certificate_sans` | `list(string)` | `null` | Override certificate SANs exactly during adoption; null uses the aliases. |
| `wait_for_certificate_validation` | `bool` | `true` | Wait for DNS certificate verification; false adopts a certificate already verified outside this module. |
| `manage_role_policies` | `bool` | `true` | Create the bundled role policies; false retains existing policy attachments supplied below. |
| `codebuild_existing_policies` | `map(string)` | `{}` | Stable attachment keys mapped to existing IAM policy ARNs for the build role. |
| `codepipeline_existing_policies` | `map(string)` | `{}` | Stable attachment keys mapped to existing IAM policy ARNs for the pipeline role. |
| `lambda_existing_policies` | `map(string)` | `{}` | Stable attachment keys mapped to existing IAM policy ARNs for the invalidation role. |
| `codebuild_encryption_key` | `string` | `null` | Existing CodeBuild KMS key ARN; null keeps the service default. |
| `source_action_name` | `string` | `null` | Override the existing GitHub source action name. |
| `invalidation_user_parameters` | `string` | `null` | Override the existing JSON invalidation action parameters during adoption. |
| `lambda_source_code_hash` | `string` | `null` | Optional existing package hash; otherwise hash the supplied ZIP or bundled source. |
| `legacy_bucket_policy_id` | `string` | `null` | Preserve the optional policy Id of an existing public origin. |
| `legacy_bucket_policy_sid` | `string` | `null` | Preserve the optional statement Sid of an existing public origin. |
| `origin_access_mode` | `string` | `"private"` | Use legacy_public, oac_prepare, oac_transition, private in order when adopting public origins. |
| `pipeline_action_region` | `string` | `null` | Preserve an explicit region on existing pipeline actions; null omits it. |

## Outputs

- `cloudfront_distribution_id`
- `cloudfront_domain_name`
- `site_bucket_name`
- `pipeline_name`

See [examples](../../examples), [operations](../../docs/operations.md) and [migration](../../docs/migration.md).
