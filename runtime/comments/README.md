# Remark42 runtime

Install this runtime archive on a dedicated Ubuntu 24.04 comments host provisioned
by `journal-comments`. It renders host configuration from a non-secret deployment
descriptor and a private SSM configuration. See [operations](../../docs/operations.md).

Native Remark42 data stays in `data/remark`; the durable SQLite queue, audit,
approvals and spending ledger stay in `data/state`. The portable moderation
package is bundled in the runtime archive and worker image.

Internal authenticated webhooks queue comments after the five-minute editing
window. An hourly sweep catches missed webhooks and edited comments. The daily
digest defaults to 09:00 in the configured timezone and is quiet when nothing
needs attention. Report mode retains spam; automatic mode verifies an off-host
archive before deleting. Unknown decisions or errors retain the comment.

On the host, `sudo comments status`, `review`, `show --id ID`, `keep --id ID`,
`remove --id ID`, `history --id ID` and `backup` provide owner operations.
`restore --archive KEY --confirm-site SITE` restores one archived comment;
`recover --archive KEY --confirm-site SITE` restores a whole native snapshot.
Recovery pauses public requests, backs up the current state and verifies records
before reopening. Restoration records an approval for the unchanged content.

All deployment paths, service names, allowed article hosts, branding, email and
provider credentials are configuration. Preserve persistent identity secrets,
data paths and service names when adopting an existing host.

## Local anonymous demonstration

Create `.runtime/local/remark.env` containing a persistent random `SECRET`, then:

```sh
docker compose -f compose.local.yaml up -d
```

This binds Remark42 to localhost:8082 with site ID `example`, bounded logs and
persistent local data. It needs no AWS, external login credentials or OpenAI.
Stop it with `docker compose -f compose.local.yaml down`; data is retained.
