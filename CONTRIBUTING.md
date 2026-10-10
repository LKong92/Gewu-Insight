# Contributing to Gewu Insight

## Report an issue or suggest a change

This repository is private. Collaborators with access can open an issue;
others can contact [info@gewu-insight.com](mailto:info@gewu-insight.com).
Include your operating system, Gewu version/build, steps to reproduce, expected
and actual behavior, and a small synthetic example when useful. Remove API keys,
tokens, personal paths and research content from logs and screenshots. Do not
attach a real database or papers without permission to share them.

## Prepare and submit a contribution

1. Discuss the intended change and acceptance requirements with a maintainer,
   especially for new features or changes to paper identity, storage or access.
2. Follow the [development guide](https://github.com/LKong92/Gewu-Insight/blob/Windows/docs/DEVELOPMENT.md#manual-setup). Use an
   isolated development database and synthetic fixtures; never test changes on
   a user's research collection. Read [AGENTS.md](https://github.com/LKong92/Gewu-Insight/blob/Windows/AGENTS.md) for product rules.
3. Keep the change focused, update affected documentation, and run the relevant
   existing checks. Describe actual validation and any unverified behavior.
   Follow the [commit guidelines](https://github.com/LKong92/Gewu-Insight/blob/Windows/docs/COMMIT_GUIDELINES.md).
4. Where your repository access permits, submit a PR describing the problem,
   resulting behavior, data or compatibility effects, and validation. Otherwise,
   arrange a patch with a maintainer. GitHub access and the license's permission
   to share research modifications are separate matters.
5. Maintainers review correctness, file/data safety, documentation and third-party
   provenance. External copyrightable contributions also require the written
   authorization described below before merging into the official product.

Windows maintainers work directly on `Windows` under this repository's existing rules;
external PRs do not change that local development policy. Keep benchmark-only
work and artifacts in isolated local worktrees and out of product submissions.

## Research sharing and upstream contributions are different

The [LICENSE](LICENSE) permits non-commercial research sharing of original and
modified versions, derivative works and patches, including public research forks
and pull requests, under its stated terms. You do not need a contributor license
agreement (CLA) or individual approval merely to exercise those permissions.

Submitting a pull request does not transfer your copyright or automatically grant
the project additional rights to license your contribution commercially. The
research-use license continues to apply unless a separate agreement provides
additional rights. Public availability is not a commercial authorization.

## Before an external contribution is merged

Gewu intends to retain the ability to offer separate commercial licenses. Until a
reviewed contributor agreement and acceptance process are in place, maintainers
must not merge external code or other copyrightable contributions intended for
inclusion in those releases without a separately agreed written authorization
covering the intended commercial rights. Receiving or discussing a PR does not
mean it has been accepted for that purpose.

The intended model lets contributors retain copyright while granting the project
only the additional rights actually agreed. A sign-off, Git author name or PR
submission must not be treated as evidence of commercial use and
sublicensing/relicensing permission.

**No finalized CLA or signature-collection process is currently provided.**
Maintainers should use the [contribution authorization checklist](docs/LICENSING.md#contribution-authorization-checklist)
to prepare a reviewed written agreement identifying the actual parties, rights
and contributions. This policy is not that agreement. Contributors can still
publish modifications under the research-sharing permission without upstream
acceptance.

Contact: [info@gewu-insight.com](mailto:info@gewu-insight.com).

## Third-party material

Do not submit code, fonts, figures, papers, data or other material that you cannot
license for the proposed contribution. Identify third-party material and retain
its notices. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and the
[dependency and asset audit](docs/DEPENDENCY_LICENSE_AUDIT.md). This policy does
not override their licenses or supply missing permission.
