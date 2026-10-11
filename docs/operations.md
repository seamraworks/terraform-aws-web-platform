# Install, maintain and recover

Provision infrastructure from your environment repository. Create persistent
origin, signing, webhook and administration secrets in a restricted local
directory before applying; pass the same origin secret to Terraform and runtime.
Keep Terraform state encrypted and restrict access: the CloudFront origin secret
is a sensitive Terraform input and is present in state.

Export the `journal-comments` deployment output to `deployment.json`, including
`site_id`, `service_name`, paths, region and existing identity. Prepare configuration
from `runtime/comments/config.example.json`; default moderation is disabled and
report mode. Enable only the desired login providers. Set sender, certificate
contact, article allowlist, website/privacy URLs and optional logo.

```sh
python runtime/comments/provision.py prepare --deployment /private/deployment.json \
  --private-dir /private/comments --config /private/operator-config.json --profile YOUR_PROFILE
python runtime/comments/provision.py publish --deployment /private/deployment.json \
  --private-dir /private/comments --profile YOUR_PROFILE
```

The publisher preserves existing persistent secrets and refuses duplicate host
keys. Transfer only the dedicated restricted host credentials, deployment
descriptor and tested runtime archive over SSH. Keep the owner/root AWS credentials
off the VM. Install into the configured runtime directory and run, as root:

```sh
bash install.sh /etc/web-comments/deployment.json
```

For an adopted host, use its existing paths and service prefix instead. The
installer fetches SSM configuration, renders branding/Compose/Caddy/systemd,
builds the worker and restarts services. It leaves data directories intact.

## Routine verification

Run `sudo comments status`; check container state and systemd timers. Verify
public comment configuration and one consenting test login/post in a disposable
environment. Check that public Basic-auth and recovery requests return 403.
Never paste configuration or credentials into logs or issue reports.

Upgrade by backing up, transferring a tested release and rerunning the installer.
The internal webhook waits for Remark42's editing window; the hourly sweep repairs
missed events. Inspect `review`, `show` and `history` for failures or uncertainty.
Daily digests include original text and discussion links, and suppress routine
successful background work.

Before changing an OpenAI policy or model, run synthetic evaluation with a
separate persistent ledger and an explicit budget:

```sh
export PYTHONPATH=components/moderation/src:runtime/comments
python runtime/comments/evaluate.py --config /private/operator-config.json \
  --budget-usd YOUR_EVALUATION_CEILING --ledger /private/evaluation.sqlite
```

This classifies synthetic cases without changing comments. Follow it with a
report-mode review of representative real discussions before enabling removal.

## Backup and recovery

`sudo comments backup` creates a native off-host snapshot with media. Archives
created before spam deletion include original records and media. Both use a private,
encrypted S3 bucket with TLS enforcement and 30-day retention.

Use `sudo comments restore --archive KEY --confirm-site SITE` for one comment,
or `recover` for a full snapshot. The recovery flow pauses public traffic, takes a
rollback backup, imports/verifies native data and retains approved restored versions.
If verification fails, keep the maintenance gate closed and investigate before
`resume --confirm-site SITE`. See the CLI help for deliberate replacement options.

## Alerts and storage

The health alarm uses three five-minute periods and detects missing heartbeats.
Readable transitions are formatted by Lambda and sent through SES; delivery failures
use filtered native SNS email. You can test formatting with a clearly labelled
CloudWatch-shaped SNS event whose `Test` property is true. Do not fabricate a real
ALARM transition without that label.

Docker logs, host journal/file logs, local backups and cloud delivery records have
bounded retention. Disk/inode pressure closes public commenting and pauses the
worker; recovery requires sufficient free capacity. Storage scripts intentionally
manage the whole dedicated VM and must not be installed on a shared host.
