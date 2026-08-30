# PROJECT_STATE.md

## Current handoff

- Repo: `/Users/lingyuan/PaperMonitor-20260516`
- Product/launcher: `Gewu Insight`（格物洞见）, `Gewu Insight.app`
- Formal branch: `main`; GitHub product remote is `origin/main`.
- Main UI/API: `paper_monitor/ui_server.py`; native shell: `scripts/PaperMonitorApp.m`.
- SQLite is the only source of truth: `data/paper_monitor.sqlite`; JSON is export/diagnostic only.
- Product code, tests, docs, and required app artifacts stay on `main`. Benchmark code, data, instrumentation, results, seals, and reports stay in the isolated local benchmark worktree and must never be pushed.

## Current product model

- Library, Shortcut, Space, My Publications, Journal Monitor, Subject Monitor, and Author Monitor share canonical paper identities and stable Gewu Keys.
- Paper Files is one flat peer list. File type, annotation state, and file source are independent normalized properties.
- Supported file types are Preprint, Accepted manuscript, Published version, Corrected published version, Correction notice, Supplementary material, Peer review file, Other, Unknown, and Invalid file.
- Automatic Default priority is corrected published > published > accepted manuscript > preprint. Any existing valid file can be chosen manually; a manual Default is sticky until Use Automatic Selection is selected.
- Exact SHA-256 duplicates are reused. Clean and annotated peers may coexist even when their content fingerprints match.
- Invalid or unreadable PDFs are rejected at ingress. Migrated invalid audit records remain visible but cannot become Default.
- Physical primary paths remain a filesystem-compatibility detail; choosing Default does not move, rename, or rewrite a file.

## Provenance and identity

- Schema version is 14.
- `paper_source_observations` is the normalized paper-level provenance authority with `(paper_id, source_kind, source_name, source_key)` uniqueness, first/last seen timestamps, and `ON DELETE CASCADE`.
- `papers.source_count` and `raw_json._paper_monitor_sources` are maintained compatibility projections and cannot shrink during bibliographic refresh.
- Existing provenance is backfilled only from provable paper source fields and Journal/Subject/Author relationships.
- `paper_identity_conflicts` quarantines major DOI/title/author/venue contradictions instead of merging unrelated works. Repeated evidence is idempotent and conflict rows cascade with their paper.
- Paper merge and canonical-ID replacement migrate source observations before deleting the superseded paper.

## Ingestion and file safety

- Journal, Subject, Author, My Publications, and inventory ingestion all honor identity-conflict rejection before writing relationships.
- Publisher downloads classify the file actually returned. Correction notices stay peer files and never become automatic Default; First Release/reference-style publisher files map to Accepted manuscript.
- Metadata-only PDF URLs do not create local file records.
- Structural validation rejects zero-page, truncated, unreadable, and password-locked PDFs before registration or replacement.
- Subject Monitor rejects Zenodo at ingestion and cached display and has no Zenodo visibility control.

## Native app behavior

- The launcher allows slow first-run migrations, automatically restarts an unexpectedly terminated local server, and uses a nonblocking startup-failure sheet.
- If the server recovers after a failure sheet appears, the launcher rechecks health, dismisses the stale sheet, and reloads the app automatically.
- Build/relaunch verification must always use the original `Gewu Insight.app`, preserve its Dock identity, verify `/api/health`, and confirm the running page contains the new code.
- Only true blank title-bar regions can trigger window zoom/restore; app tabs and search controls do not.

## User Guide

- `paper_monitor/user_guide.html`, generated `paper_monitor/user_guide.tex`, and `paper_monitor/Gewu_Insight_User_Guide.pdf` describe the same flat Paper Files and Set as Default/Use Automatic Selection model.
- The guide also documents normalized cross-Monitor provenance, identity-conflict quarantine, the compact three-row Paper Files metadata layout, the adaptive Paper Details file-property grid, evidence-based source labels, ResearchGate publication-provider fallback, title-bar double-click boundaries, and launcher migration/recovery behavior.
- The fixed-layout guide currently has 74 visually checked pages with consistent numbering and section transitions.

## Verification

- Python compile check passes.
- Full product suite passes: 615 tests.
- A read-only backup of the formal database migrates to schema 14 with zero foreign-key errors.
- The formal App was rebuilt and reopened from the original path. Local health passed, the running Paper Details Files panel exposed the adaptive layout and clarified actions without overlap, the live Help route exposed the aligned guide, and the packaged fixed-layout PDF matches the generated product PDF.

## Current caveats

- Schema 14's first formal launch can take roughly 20 seconds while provenance and file metadata are backfilled; the native startup timeout remains 120 seconds.
- Legacy resources with insufficient evidence remain `Unknown`; migration does not invent a Published version or source.
- Publisher/network access remains dependent on remote availability and anti-bot limits; avoid overlapping broad refreshes.
