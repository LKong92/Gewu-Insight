# Commit Message Guidelines

Every future commit must have a specific English subject and a readable English
body, separated by a blank line. Match the detail to the scope of the change;
explain the work rather than repeating the title or filling out a generic template.

## Content

The body should explain:

- Purpose: the problem or motivation and the affected workflow.
- Changes: concrete behavior, structure, or rules that changed. Distinguish fixes,
  refactoring, documentation updates, and removals.
- Impact: relevant migration, compatibility, file safety, permissions, network,
  or UI considerations and remaining limitations. State when a documentation-only
  change has no runtime effect.
- Validation: checks actually run and their results, including failures and
  checks not run. Never infer a passing result merely from the presence of tests.

Small changes may use a few concise paragraphs; larger changes may use bullets.
The following is a structure to adapt, not text to copy without evidence:

```text
fix <specific user-visible problem>

Explain the failure or motivation and the affected workflow.

Describe the concrete changes and the behavior or data invariants preserved.
Mention migration, compatibility, or remaining limitations when applicable.

Validation: list checks actually run and their results; explicitly note any
checks not run and why.
```

## Commit and Push Checks

- Commit or push only when explicitly requested; this policy is not authorization.
- Review the worktree and staged diff, preserve existing user changes, and stage
  related files by name. Never use `git add -A`.
- Keep `main` product-only: product code, tests, documentation, and required app
  artifacts. Never include or push benchmark code, data, artifacts, or branches.
- Never include API keys, tokens, private database contents, or sensitive logs in
  commit messages, including validation descriptions.
- UI/App changes still require the original App build, single-instance relaunch
  at the original path, health check, and verification of the code actually loaded.
- Inspect the completed message with `git log -1 --format=%B`. Before a push,
  inspect the full messages of every outgoing commit, not just the latest one,
  against the verified destination branch. Confirm that new commits comply with
  this policy and contain no placeholder descriptions or unsupported claims.

## Preserve Existing History

This policy is prospective. Leave existing commit messages, objects, and hashes
unchanged, including old commits without bodies. Do not amend, rebase, filter, or
force-push existing history to add descriptions. Historical-description work is
cancelled; no retrospective history log is required.

New commit bodies travel with ordinary pushes and appear in GitHub's expandable
commit descriptions. They require no separate GitHub edit or history rewrite.
