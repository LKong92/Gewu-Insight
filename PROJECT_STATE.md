# PROJECT_STATE.md — Current handoff

Updated: October 10, 2026. Keep this file under 100 lines and focused on current state.

## Repository and delivery

- Work directly on `main`; commit/push only when explicitly requested. Follow `docs/COMMIT_GUIDELINES.md`; never rewrite history or publish benchmark work.
- GitHub must remain private. Current releases: `macos-1.0.0` and `windows-1.0.0-r2`; repository access is required for their GitHub downloads.
- This cleanup started from clean local `539d00d` and fast-forwarded to remote `13b6e2c` before editing. That remote update changed only README.
- The manuscript evaluation refers to fixed source snapshot `539d00d`; documentation cleanup does not change that reference or claim new evaluation results.
- October 10 cleanup: archive eight unused logo concepts and the prior handoff/agent rules locally; simplify README and contributor entry points; synchronize distribution/development/third-party documentation. LICENSE 1.1 and runtime code stay unchanged.
- Archive: ignored `local-development-archive/repository-cleanup-20261010/`, with verified SHA-256 manifest. Full earlier handoff is also recoverable from Git at `13b6e2c`; archived completion/commit claims are historical, not current instructions.
- This documentation cleanup does not rebuild installed Apps or replace existing release assets. Updated bundled notices take effect only in a subsequently built and validated package.
- User authorized publishing this cleanup to GitHub `main`, keeping the repository private. Five existing source-policy tests and 89 relative file/anchor checks passed; archive hashes, unchanged LICENSE and whitespace checks passed. App/bundled-resource tests were not run for this documentation-only change.
- GitHub topic correction `macros` to `macos` remains outstanding: API write returned 404; the current account has push permission but no admin/maintain permission. Repository visibility was verified private.

## Source and data separation

- Daily macOS App: `/Applications/Gewu Insight.app`. Discover the selected Gewu Database from the installed App; never copy another machine's formal data path.
- SQLite in the selected workspace is authoritative. Back up the entire database folder, additional managed roots and externally linked originals with the App/service stopped.
- Source development requires explicit `GEWU_WORKSPACE_ROOT` pointing to an isolated workspace; never implicitly recreate source-checkout user data.
- `assets/macos-app-template.zip` remains a required native build seed. The native builder extracts it temporarily; standalone packaging stages its own App and runtimes.
- A source pull does not update an installed standalone App. Use `docs/DEVELOPMENT.md`, `DISTRIBUTION.md` and `docs/MACOS_DMG_PREVIEW.md` for distinct build paths.
- Legacy migration instructions: `docs/SOURCE_DATA_MIGRATION.md`. Startup rejects missing/wrong/newer/busy databases and port conflicts rather than creating a replacement collection.

## Product contracts to retain

- Canonical paper identity and stable Gewu Keys connect metadata, versions, Paper Files, placements and provenance. Shared records survive reuse across Library, independent Spaces and My Publications.
- Preserve files, resource IDs, manual Default choices, classifications and provenance. Distinct versions/annotations may coexist; byte-identical files can be reused. File/SQL operations require rollback or recovery.
- Publication notices remain linked to the original paper and do not become automatic Default. Corrected full articles are versions. Explicit Crossref relations drive Refresh Info; saved papers are not periodically checked merely by being in Library.
- Browser capture keeps source/target identities distinct, reviews genuine notices against the original article, and retains manual Key resolution. Science PDF.js capture and the DOI ellipsis repair remain in the current code.
- Browser external views refuse persistent WebCrypto keys; ordinary cryptography, website storage and PDFs remain available. Do not restore discarded PDF-preview experiments or claim Safari performance parity.
- Journal/Subject unread acknowledgements follow explicit paper selection; tab dots count visible papers under current filters. Subject Monitor rejects Zenodo; calendar counts are numbers only.
- Author discovery and incomplete-metadata background work respect stored pacing, cooldowns and bounded retries. Explicit user refresh remains distinct.
- MCP is optional with explicit grants. Metadata-only imports can later receive a PDF under the same Key; imports do not automatically download or Resolve. Analysis saves append Markdown; organization/import permissions are separate and never broaden existing grants.
- Ordinary literature access uses configured MCP. Authorized Gewu development/debugging may inspect internals as needed; data changes remain scoped to the authorized task.

## Documentation and validation

- README introduces both platforms; macOS screenshots do not establish Windows feature parity. The Windows branch owns its native implementation and packaging instructions.
- `paper_monitor/user_guide.html` is the source for generated TeX/PDF. Keep Product Identity 4-1 through 4-4 continuous in the builder. Follow `docs/USER_GUIDE_SCREENSHOTS.md` for real-App captures.
- Current license: custom Academic and Non-Commercial Research License 1.1. Research sharing includes modified versions/patches; commercial use needs separate written authorization.
- Unresolved: font/branding artwork permission evidence and a finalized external-contributor commercial grant/signature process. Do not infer clearance from notices or a submitted PR.
- The September dependency audit is historical. Standalone distributions bundle runtimes; check each actual release manifest and shipped licenses before making package-wide claims.
- Use relevant existing checks and isolated data. Record actual validation; do not treat old test totals, PIDs, temporary paths or installed-state claims as current evidence.
