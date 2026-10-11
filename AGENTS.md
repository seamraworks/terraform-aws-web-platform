# Library maintenance

This is a public reusable library. Keep actual deployment accounts, domains,
credentials, inventory and private environment history outside this repository.
Examples use reserved domains and synthetic identities.

Preserve caller resource names/addresses during upgrades. Moderation is portable;
AWS/Remark42 integration and content actions belong in the runtime adapter.
Run tools/check.py and disposable integration tests; regenerate module references
and deterministic artifacts when interfaces change. Never apply production
Terraform or send real email from public CI.
