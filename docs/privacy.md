# Data flow and privacy

Remark42 stores comments and authentication identities on the host. The moderator
stores queue, decisions, owner approvals and spending reservations in SQLite.
Native exports and removed-comment archives, including relevant media, are stored
privately in S3 with retention limits. Owner digests include comment text; SES/SNS
deliver operational and authentication email.

The moderation adapter sends comment text and relevant discussion context to the
selected provider. It does not send raw IP addresses, account IDs, email addresses,
OAuth credentials or administration secrets. OpenAI response storage is disabled
with `store: false`; this does not promise zero retention across all provider systems.
An alternative provider may have different processing and retention terms.

Configure and publish a privacy notice appropriate to the actual deployment,
including authentication providers, moderation and backup retention. The library's
example pages and documentation are not a deployment-specific legal notice.
