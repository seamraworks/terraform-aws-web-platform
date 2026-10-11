# Adoption and upgrades

1. Back up Terraform state, host data, moderation SQLite, runtime configuration
   and the currently installed release. Refresh the existing plan before changing
   module sources.
2. Replace local sources with a pinned library commit. Supply existing names,
   certificates, IAM attachments, build settings and paths through compatibility
   inputs. Keep existing module names. Use explicit `moved` blocks for resources
   entering a module, and update historical import targets.
3. Move account-wide SES suppression to the environment root. Do not give each
   email module ownership of this regional singleton.
4. Review a saved plan. Reject unintended resource creation, deletion or
   replacement. Lambda packaging/configuration updates may be intentional;
   compare source and test before applying. Preserve ZIP artifacts through apply.
5. Update the runtime in place, keeping data paths, queue, approvals, spending
   ledger, identity secrets and systemd names. Register the deployment descriptor
   at the existing configuration directory before installation.
6. Verify login settings, service health, comment records, recovery and
   notification configuration. Keep website branch and release timing intact.

## Moving a public S3 origin to OAC

Apply these `origin_access_mode` values individually, checking each saved plan:

| Stage | Bucket permissions | CloudFront origin |
| --- | --- | --- |
| `legacy_public` | Existing public read | Existing unsigned origin |
| `oac_prepare` | Public read plus restricted CloudFront read | Unsigned |
| `oac_transition` | Both permissions | Signed OAC requests |
| `private` | Restricted CloudFront read; public access blocked | Signed OAC requests |

Wait for CloudFront deployment and verify pages, assets and clean routes before
removing public access. After the final stage, direct S3 reads must return 403
while CloudFront content works. Website publishing still uses its existing IAM
write permissions. Bucket names and objects are retained.

Rollback reverses these stages: restore public permission before removing OAC
from the distribution. Do not disable OAC first against a private bucket.

Runtime rollback restores the previous application files/image and configuration
while retaining live data. Recover a data snapshot only when data actually needs
restoration; the runtime update itself does not change native comment storage.
