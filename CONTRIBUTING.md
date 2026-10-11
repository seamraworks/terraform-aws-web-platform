# Contributing

Run `python tools/check.py`, the disposable integration checks and package generation
before proposing a release. Tests use mock AWS/OpenAI responses and temporary
containers; never supply production credentials to public CI.

Use a virtual environment and install `runtime/comments/requirements.txt`,
`setuptools==80.9.0` and `wheel==0.45.1`. On Windows, install `tzdata` as well
for the runtime's IANA time-zone tests. The deployed Linux runtime uses its
system time-zone database.

Keep deployment identity out of library code. Add inputs with documented defaults
and compatibility behavior; preserve existing Terraform resource addresses or
provide migration guidance. Keep moderation providers independent of AWS/Remark42
and content actions. Changes to classifier policy need representative evaluations.

Pin images and release dependencies. Run `python tools/docs.py` after changing
Terraform inputs/outputs and commit the generated module reference tables.
Do not include state, plans, tfvars, credentials, private inventory or runtime data.
