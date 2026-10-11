# Architecture and ownership

```mermaid
flowchart LR
  Environment[Private environment repository] --> Modules[Versioned Terraform modules]
  Environment --> Config[Private runtime configuration]
  Modules --> AWS[AWS resources]
  Release[Versioned runtime archive] --> Host[Comments host]
  Config --> Host
  Host --> Portable[Portable moderation component]
  Portable --> OpenAI[OpenAI provider]
  Portable --> HTTP[Alternative HTTP provider]
```

```mermaid
flowchart TB
  Visitors[Visitors] --> DNS[Route 53 and ACM]
  DNS --> WebCDN[Website CloudFront]
  WebCDN --> OAC[Origin access control]
  OAC --> SiteBucket[Private S3 content bucket]
  GitHub[GitHub authorized connection] --> Pipeline[CodePipeline]
  Pipeline --> Build[CodeBuild and artifact buckets]
  Build --> SiteBucket
  Pipeline --> Invalidate[Invalidation Lambda]
  Invalidate --> WebCDN
  DNS --> CommentsCDN[Comments CloudFront]
  CommentsCDN --> Caddy[Caddy on Lightsail]
  Caddy --> Remark[Remark42 and native data]
  Remark --> Queue[Worker and SQLite state]
  Queue --> Provider[Optional moderation provider]
  Queue --> Backups[Private S3 backups and archives]
  Queue --> SES[SES login mail and owner digest]
  SSM[SSM configuration and restricted host IAM user] --> Queue
  Guard[Host storage guard and timers] --> Health[CloudWatch health]
  Queue --> Health
  Health --> SNS[SNS operations topic]
  SNS --> Formatter[Alert formatter Lambda]
  Formatter --> Dedup[DynamoDB delivery records]
  Formatter --> SES
  Formatter --> Failure[SQS failure queue and delivery alarms]
  Failure --> SNS
  SNS --> Fallback[Filtered direct SNS email fallback]
  SES --> Feedback[SNS bounce and complaint notifications]
```

```mermaid
sequenceDiagram
  participant R as Remark42
  participant W as Comments worker
  participant P as Moderation provider
  participant S as S3 archive
  R->>W: Authenticated internal webhook
  W->>W: Durable queue, editing window, owner exemptions
  W->>P: Content and relevant context
  P-->>W: keep, spam, review or error
  alt Clear spam and automatic mode
    W->>S: Archive original and media
    S-->>W: Archive verification
    W->>R: Recheck unchanged content, then delete
    W->>R: Verify removal
  else Review, failure or report mode
    W->>W: Retain comment and audit decision
  end
  W->>W: Daily digest when activity needs attention
```

CloudFront checks an origin credential; Caddy blocks public automation/recovery
access and trusts only current CloudFront peers. The moderator has internal
Remark42 administration access. Providers receive content but no admin credentials.
Alert formatting runs independently of the host, and direct SNS fallback bypasses
both SES and Lambda.
