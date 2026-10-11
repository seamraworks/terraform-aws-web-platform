# journal-comments-email

SES identity, configuration set, DKIM, MAIL FROM and confirmed bounce/complaint notifications. Regional suppression belongs to the environment root.

Use AWS provider 6.x; CloudFront certificates require the `aws.use1` alias in us-east-1.

## Inputs

| Input | Type | Default | Description |
| --- | --- | --- | --- |
| `region` | `string` | Required | AWS region where the SES identity and feedback topic are managed. |
| `zone_id` | `string` | Required | Existing Route 53 hosted zone ID for DKIM and MAIL FROM records. |
| `owner_email` | `string` | Required | Real owner inbox for bounce and complaint notifications and sandbox verification. |
| `domain` | `string` | Required | Domain identity authorized to send comment email. |
| `configuration_set_name` | `string` | Required | Stable SES configuration set name; preserve it during adoption. |
| `feedback_topic_name` | `string` | Required | Stable SNS topic name for SES bounce and complaint feedback. |
| `mail_from_subdomain` | `string` | `"comment-mail"` | Subdomain beneath the verified domain used for the envelope MAIL FROM. |
| `feedback_policy_sid` | `string` | `"AllowSESIdentity"` | Stable SES publication policy statement ID; preserve it during adoption. |

## Outputs

- `identity_arn`
- `configuration_set_arn`

See [examples](../../examples), [operations](../../docs/operations.md) and [migration](../../docs/migration.md).
