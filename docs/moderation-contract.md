# Moderation contract v1

The caller sends one JSON object to its configured HTTP endpoint:

```json
{"schema_version":1,"text":"The user message","context":{"page_title":"An article","page_url":"https://www.example.com/journal/article.html","parent_text":"Optional parent"}}
```

`text` is required. `context` is optional, with string keys and values. All fields
are untrusted content; they must never override provider policy or instructions.
The Remark42 adapter sends only text, title, URL and parent text. User email,
account IDs, IP addresses and authentication credentials do not cross this boundary.

Return HTTP 200 with:

```json
{"schema_version":1,"decision":"review","reason":"Context requires owner judgment","provider":"custom-service","model":"","policy_id":"custom-policy-1"}
```

`decision` must be `keep`, `spam` or `review`; `reason` contains 1–1000 characters.
Provider/model/policy strings are optional metadata, each up to 256 characters.
Other fields and incompatible schema versions are rejected. There is no confidence
threshold, deletion command or account-blocking field.

Requests are limited to 32 KiB; responses to 128 KiB. Default timeout is 60 seconds.
HTTP redirects, non-success responses, invalid JSON and contract violations
produce no usable decision. The caller retains content and records/retries errors.
Oversized input receives a local `review` result without invoking a provider.

Bearer authentication is optional for the operator-controlled endpoint. Use TLS
for a remote service. The library provides a client adapter and a local reference
server; operating a third-party service remains the deployment's responsibility.

Python extensions implement `ModerationProvider.classify(ModerationRequest)` and
return `ModerationResult`; scheduling, storage and content actions stay with the
application. Provider-specific requirements such as additional author metadata
need an explicitly designed adapter rather than silently forwarding private data.
