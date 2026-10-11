# Portable moderation

An independent Python component with no AWS, Terraform or Remark42 dependency.
The OpenAI provider and alternative HTTP adapter implement the same
`ModerationProvider.classify(ModerationRequest) -> ModerationResult` interface.

Install from a release wheel or this directory:

```sh
python -m pip install ./components/moderation
```

```python
import os
from web_platform_moderation import ModerationRequest, OpenAIProvider, Pricing, SQLiteLedger

provider = OpenAIProvider(
    api_key=os.environ["OPENAI_API_KEY"],
    model=os.environ["MODERATION_MODEL"],
    ledger=SQLiteLedger("moderation.sqlite", Pricing(
        float(os.environ["INPUT_USD_PER_MILLION"]),
        float(os.environ["OUTPUT_USD_PER_MILLION"]))),
    monthly_budget_usd=1,
    policy_id="my-policy-1",
)
result = provider.classify(ModerationRequest("A user message", {"page_title": "Discussion"}))
print(result.decision, result.reason)
```

Set prices for the chosen model explicitly. Reservations serialize concurrent
requests and persist across restarts. Missing or invalid usage retains the full
reservation. Accounting uses UTC calendar months and integer microdollars;
it is an application budget guard, not an invoice or account-wide spending cap.

The OpenAI provider uses the Responses API with strict structured outputs,
`store: false`, and no tools. Refusals, incomplete responses and transport errors
produce an error, never a spam decision. Requests exceeding 32 KiB require manual
review. Configure a policy appropriate to the application's content; policy and
model changes require evaluation with representative legitimate and spam cases.

CLI: submit the versioned request from [the contract](../../docs/moderation-contract.md)
on stdin, using `web-platform-moderate --config /private/moderation.json --database
/private/moderation.sqlite`. Errors exit nonzero and report `retain_content: true`
without printing input, credentials or remote response bodies.

Choose `moderation_provider: none`, `openai` or `http`. OpenAI requires `model`,
`monthly_budget_usd`, `input_usd_per_million` and `output_usd_per_million`; its
API key can be in `OPENAI_API_KEY`. Optional settings include `moderation_policy`,
`policy_id`, `max_output_tokens`, and `reasoning_effort`.

The HTTP provider requires `moderation_endpoint`; its bearer token can be supplied
as `moderation_token` or `MODERATION_HTTP_TOKEN`. Use HTTPS for remote services;
HTTP is useful on a trusted local network. Redirects are rejected. A custom
Python provider can implement the protocol directly, without an HTTP server.

See [the reference HTTP provider](../../examples/http-provider/server.py).
Applications decide what to do with classifications. This component has no
archive/delete/restore credentials or content-management operations.
