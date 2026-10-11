# External authorizations

Terraform manages resource configuration. Some external parties require an
interactive identity/authorization step:

| Step | Automated configuration | Interactive action |
| --- | --- | --- |
| GitHub source connection | AWS connection resource and pipeline ARN | Approve the GitHub installation and repositories; connection must become AVAILABLE |
| Domain | Existing hosted-zone reference and resource records | Registrar delegation if using a new zone |
| SES | Identity, DKIM, MAIL FROM, feedback topic and subscription | Confirm inbox identity/subscription and request regional production access |
| Google/GitHub login | Runtime callback/configuration | Register OAuth application, authorize audience and store client credentials privately |
| CircleCI | Versioned configuration and project setup | Grant repository access if the organization's integration does not already include it |

Google callback: `https://COMMENTS_DOMAIN/auth/google/callback`.
GitHub callback: `https://COMMENTS_DOMAIN/auth/github/callback`.
Publish a suitable website/privacy page before opening Google authentication to
the public. Each provider is optional. Email login needs SES approval for sending
to unverified recipients outside the sandbox.

Use a sending address on the verified SES domain. It does not require a mailbox.
The custom MAIL FROM subdomain receives SES bounce handling; the owner recipient
is a separate real inbox. Enable regional bounce/complaint suppression once in
the environment root and monitor the confirmed feedback subscription.
