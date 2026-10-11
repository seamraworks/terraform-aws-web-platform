# journal-comments

Dedicated Lightsail Remark42 hosting, CloudFront origin protection, S3 archives, restricted host IAM, health alarms and readable SES alerts with independent SNS fallback.

Use AWS provider 6.x; CloudFront certificates require the `aws.use1` alias in us-east-1.

## Inputs

| Input | Type | Default | Description |
| --- | --- | --- | --- |
| `region` | `string` | Required | AWS region for the dedicated comments host and its regional resources. |
| `zone_id` | `string` | Required | Existing Route 53 hosted zone ID for comment DNS records. |
| `ses_identity_arn` | `string` | Required | Verified identity managed by the independent Journal email module. |
| `ses_configuration_set_arn` | `string` | Required | Default configuration set used when sending from the verified identity. |
| `ssh_public_key` | `string` | Required | RSA administration public key; private keys stay with the operator. |
| `admin_cidrs` | `list(string)` | Required | Specific IPv4 administration networks permitted to reach SSH. |
| `origin_secret` | `string` | Required | Persistent random private-origin header secret; supply the identical value to runtime configuration. |
| `name` | `string` | Required | Stable deployment prefix used for the dedicated host and supporting resources. |
| `domain` | `string` | Required | Public comments domain served through CloudFront. |
| `origin_domain` | `string` | Required | Private host origin domain, distinct from the public comments domain. |
| `site_id` | `string` | Required | Stable Remark42 site identifier, also used in metrics and the runtime descriptor. |
| `owner_email` | `string` | Required | Real owner inbox for operational messages and fallback confirmations. |
| `email_from` | `string` | Required | Sender address on the independently verified SES domain. |
| `parameter_prefix` | `string` | Required | SSM prefix containing this deployment runtime configuration. |
| `operations_prefix` | `string` | Required | Stable alert and systemd service prefix; preserve it during adoption. |
| `tags` | `map(string)` | `{}` | Caller-supplied AWS resource tags. |
| `description` | `string` | `"Website comments"` | Deployment description used in AWS resources. |
| `metric_namespace` | `string` | `"WebPlatform/Comments"` | CloudWatch namespace for this comments deployment. |
| `origin_header` | `string` | `"X-Comments-Origin"` | Header name used by CloudFront and Caddy to authenticate origin requests. |
| `runtime_dir` | `string` | `"/opt/web-comments"` | Absolute runtime directory on the dedicated host; retain its existing data paths during upgrades. |
| `config_dir` | `string` | `"/etc/web-comments"` | Restricted host directory containing descriptor, configuration and dedicated credentials. |
| `brand_name` | `string` | `"Website"` | Website name used in owner alerts and runtime branding. |
| `timezone` | `string` | `"UTC"` | IANA timezone used for owner-facing alerts and the daily digest. |
| `nft_table` | `string` | `"web_comments"` | Stable host firewall table name; retain it during adoption. |

## Outputs

- `deployment`

See [examples](../../examples), [operations](../../docs/operations.md) and [migration](../../docs/migration.md).
