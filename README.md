# Terraform AWS Web Platform

Reusable AWS hosting for static websites and Remark42 comments, with portable,
optional content moderation. Maintained by Seamra Works.

| Component | Provides |
| --- | --- |
| [Static site](modules/static-site/README.md) | S3, CloudFront, ACM, DNS, optional GitHub build/deploy pipeline |
| [Journal comments](modules/journal-comments/README.md) | Lightsail host, private origin, backups, health monitoring and readable alerts |
| [Comments email](modules/journal-comments-email/README.md) | SES identity, DKIM, MAIL FROM and bounce/complaint notifications |
| [Moderation](components/moderation/README.md) | Independent Python/JSON API; OpenAI and alternative HTTP providers |
| [Comments runtime](runtime/comments/README.md) | Remark42 integration, moderation queue, recovery and owner digest |

Start with [static hosting](examples/static-site/main.tf) or
[hosting with comments](examples/with-comments/main.tf). Examples use reserved
domains and require your own Route 53 zone and deployment inputs. Terraform
1.15+, AWS provider 6.54+ (6.x) and archive provider 2.8.x are supported. Runtime:
Python 3.13, Ubuntu 24.04, Docker Compose v2 with raw env-file support.

## Deployment ownership

Keep a small environment repository with provider configuration, backend,
domains, GitHub repositories/branches, account settings and module calls. This
library owns reusable implementation. Hosted zones, registrar delegation,
shared GitHub connections, budgets and account-wide SES suppression remain
environment responsibilities. The comments-email example manages suppression
once at its root.

Pin a release to its immutable commit:

```hcl
module "website" {
  source = "git::https://github.com/seamraworks/terraform-aws-web-platform.git//modules/static-site?ref=RELEASE_COMMIT_SHA"
  providers = { aws = aws, aws.use1 = aws.use1 }
  site_key = "example"
  domain_name = "example.com"
  aliases = ["www.example.com"]
  hosted_zone_id = var.hosted_zone_id
  enable_pipeline = false
}
```

CloudFront certificates use the `aws.use1` provider in `us-east-1`; other
resources use your primary regional provider. New static origins are private
through OAC. Existing public origins have a staged [migration](docs/migration.md).

Optional pipelines require an existing AVAILABLE GitHub connection, repository,
branch and shared artifact bucket. `buildspec` can be supplied or read from the
repository. Each module bundles its Lambda source and packages it during
planning. Preserve `.build/` ZIP artifacts between a saved plan and apply.

## Comments and moderation

Comments can run without an OpenAI key. Anonymous login is enabled by default;
Google, GitHub and email login are configured independently. The AWS comments
hosting recipe includes SES-backed operations alerts even when email login is
disabled. The standalone local recipe needs no AWS account.

The portable moderation component can be used without Terraform, AWS or
Remark42. Applications submit content/context and receive `keep`, `spam` or
`review`. Providers cannot delete content. The Remark42 worker applies decisions,
archives verified originals before removal and retains uncertain or failed
checks. Alternative services implement the [HTTP contract](docs/moderation-contract.md).

Operator policy, model, prices and budget are configuration. New deployments
default to report mode. Owner approvals survive unchanged restored comments;
edits queue another review. There are no automatic account bans.

## Operations and costs

See [architecture](docs/architecture.md), [installation and recovery](docs/operations.md),
[external authorizations](docs/authorizations.md), and [privacy](docs/privacy.md).

The comments recipe uses a dedicated Lightsail VM, CloudFront, S3, SES, SNS,
Lambda, DynamoDB, SQS, CloudWatch and SSM. Lightsail has a recurring baseline;
the other services and OpenAI add usage charges. Review your region's AWS pricing
and configure an account budget. The $1 moderation budget in examples is an
application operating choice, not a provider allowance or price guarantee.

Docker logs rotate at 5 MiB with two files per container; host logs and journals
are capped. Disk/inode monitoring pauses public commenting before exhaustion.
S3 backups expire after 30 days, formatter logs after 14 days, delivery records
after seven days and failed delivery events after one day.

## Development and releases

Run `python tools/check.py` with Terraform and Python available. Run
`python runtime/comments/tests/integration.py` for disposable real Remark42/Caddy
checks. `python tools/package.py` creates runtime, wheel and Lambda artifacts
with SHA-256 checksums. CircleCI runs these checks without production credentials.

Release tags version modules, runtime and moderation together. Review
[CONTRIBUTING.md](CONTRIBUTING.md), [CHANGELOG.md](CHANGELOG.md) and
[SECURITY.md](SECURITY.md). Own source is Apache-2.0; external dependencies retain
their licenses, listed in [NOTICE](NOTICE).
