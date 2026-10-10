# PROJECT_STATE.md — Current handoff

Updated: October 10, 2026. Keep this file under 100 lines and focused on current state.

## Repository and delivery

- Work directly on `main`; commit/push only when explicitly requested. Follow `docs/COMMIT_GUIDELINES.md`; never rewrite history or publish benchmark work.
- GitHub must remain private. Current releases: `macos-1.0.0` and `windows-1.0.0`; repository access is required for their GitHub downloads.
- The manuscript evaluation refers to fixed source snapshot `539d00d`; documentation cleanup does not change that reference or claim new evaluation results.
- First October 10 cleanup was published as `d993bb4`: updated installer/contributor guidance and archived unused logo concepts and old handoff history. Archive: ignored `local-development-archive/repository-cleanup-20261010/`.
- Second October 10 cleanup: shorten the README, move the maintainer contribution checklist into `docs/LICENSING.md`, retain concise guide/dependency evidence, clarify historical release notes, and remove the generated TeX from Git. Earlier audit documents and TeX are hash-verified in ignored `local-development-archive/repository-review-20261010/` and recoverable from `d993bb4`.
- User explicitly authorized publishing this second cleanup to GitHub `main`. LICENSE 1.1, runtime code, PDF/HTML manual, installed Apps and existing release assets remain unchanged. Validation: 42 source/guide/PDF checks, 143 relative links, archive hashes, Python compilation and whitespace checks passed. Two App-bundle comparison tests were excluded; no PDF or App rebuild was performed.
- October 10 follow-up: an account with admin permission corrected topic `macros` to `macos`, preserving all other topics and private visibility. Reviewed `d993bb4` and fast-forwarded through `a6a586c`, preserving its documentation cleanup. Runtime code, installed Apps and release assets remain unchanged.
- October 10 seal replacement: user requested the larger, slightly angular refinement of the accepted AI-generated compact motif; pale-gray App and black transparent PDF variants share identical glyph alpha. HTML/PDF manual now shows the black motif without a background panel. Source, provenance and native build seed match the installed original `/Applications` App; its source adapter and data location are preserved. Image URLs carry the asset hash, and two Library watermark offsets prevent clipping after the whitespace reduction. Startup and main-window artwork were visually verified. Two guide screenshots were recaptured from the original App without control overlays or a visible pointer, and the 132-page PDF and build seed were refreshed. All 33 guide/native checks passed after synchronizing the rebuilt PDF; compilation, signing and App health checks passed. Paper/database/download/MCP logic is untouched. User authorized saving and pushing this revision. Git history, published installers and the Windows branch are unchanged; rollback material stays in ignored local storage.

- October 10 Windows repository cleanup uses a separate `Windows` worktree, based on `dc2f84f`; the user authorized committing and publishing both scoped change sets. Main corrects release links and separates current metadata from the historical package audit. Current package sources: macOS `eb8714d`, Windows `725ae8f`; the Windows tag now matches `725ae8f` after a separate authorized correction, while the macOS tag retains its historical revision. Installer rebuilding and Release asset changes are outside this cleanup.

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
- `paper_monitor/user_guide.html` is the source for generated TeX/PDF. The builder recreates the ignored `paper_monitor/user_guide.tex` before compilation; the previous TeX is not required. Tests inspect the shipped PDF and builder rules. Keep Product Identity 4-1 through 4-4 continuous in the builder. Follow `docs/USER_GUIDE_SCREENSHOTS.md` for real-App captures.
- Current license: custom Academic and Non-Commercial Research License 1.1. Research sharing includes modified versions/patches; commercial use needs separate written authorization.
- Unresolved: embedded-font and About-calligraphy image reuse evidence, and a finalized external-contributor commercial grant/signature process. The AI-generated seal provenance is not legal clearance. Do not infer clearance from notices or a submitted PR.
- Actual release inventory and proposed packaging corrections: `docs/RELEASE_COMPONENT_AUDIT.md`. The earlier inspected installers had stale summary notices and Windows lacked CONTRIBUTING.md; those findings apply to the old hashes. Current release metadata was rechecked after asset replacement, without re-extracting the new installers. Static package checks do not close font/artwork or contributor authorization gaps. The September dependency audit remains historical.
- Use relevant existing checks and isolated data. Record actual validation; do not treat old test totals, PIDs, temporary paths or installed-state claims as current evidence.
- October 10 cleanup validation: all 193 main-document relative link paths exist and whitespace checks pass. The Windows worktree separately passed 40 scoped checks, synthetic service/notice staging, guide edition check, compilation and shell syntax. No native Windows build/install or PowerShell preflight was run; no current installer was re-extracted.
