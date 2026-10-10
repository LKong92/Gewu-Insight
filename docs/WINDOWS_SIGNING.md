# Windows package trust and validation

Windows packaging is intentionally unsigned. Setup, shortcut and product names
remain Gewu Insight. No publisher certificate enrollment or Windows security
setting change is part of the current workflow.

The builder verifies official CPython and Microsoft WebView2 inputs and retains
their original notices. It also checks native version consistency, complete
payload hashes and installer metadata. These static checks are distinct from
actual isolated startup and installed-app acceptance.

Use [development](DEVELOPMENT.md#builds-and-verification) for current build and
validation steps and [distribution](../DISTRIBUTION.md) for user requirements.
Record publisher warnings or execution failures as observed; do not infer that
one successful Windows 11 run verifies every Windows version or security policy.

The superseded certificate/signing proposals and machine-specific recovery logs
are preserved in Git history and the ignored local development archive. They
are not current signing requirements or instructions to weaken system security.
