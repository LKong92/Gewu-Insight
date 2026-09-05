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
- Paper Files' clickable size footer meets the card's bottom edge without extra outer padding; its hover/focus surface follows the lower corners. Expanded and collapsed metadata use the same footer geometry.
- Supported file types are Preprint, Accepted manuscript, Published version, Corrected published version, Correction notice, Supplementary material, Peer review file, Other, Unknown, and Invalid file.
- Automatic Default priority is corrected published > published > accepted manuscript > preprint. Any existing valid file can be chosen manually; a manual Default is sticky until Use Automatic Selection is selected.
- Exact SHA-256 duplicates are reused. Clean and annotated peers may coexist even when their content fingerprints match.
- Invalid or unreadable PDFs are rejected at ingress. Migrated invalid audit records remain visible but cannot become Default.
- Physical primary paths remain a filesystem-compatibility detail; choosing Default does not move, rename, or rewrite a file.
- Open Source Settings (formerly Citation Settings) shows fixed compact password-style dots by default, with explicit Show/Hide and unchanged detailed status. Only Show retrieves the secret through a same-origin, loopback-only, no-store endpoint; Hide/close clears revealed values.
- Author Monitor's New context menu provides Read All for the selected author or All Authors. Unread state remains per author-paper relationship, including shared papers; cached cards and badges update without deleting papers or Library placements.
- Author Monitor details now start directly with the paper title. Compact actions wrap whole buttons, not their labels; Get Identifier from Files shares the Library/My Publications workflow. Local filenames stay compact with full paths on hover.
- Gewu Key is always shown in shared details and Author Monitor's loading state; missing values use `(undefined)`. Keys are assigned when cataloged, before Library placement. Compact API rows and legacy card-cache reads include the canonical key without reindexing or a migration.

## Provenance and identity

- Schema version is 15. The v14 upgrade only adds indexes on papers.main_pdf_path, papers.merged_pdf_path, and resources.stored_path; it does not rerun provenance backfill or Library seeding.
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
- Subject calendar counts and Discovery status follow the active subject. Recorded incomplete attempts retain numeric counts (including zero) with a superscript asterisk; its legend sits last in Monitor Summary, below Updates and Errors. Successful completion clears the marker. Unfetched dates stay blank and active fetches retain their progress indicator.
- Generic paper updates merge into each Monitor view and cached row without discarding Subject groups, scores, or matches. Add to Library keeps the Subject card, selection, and viewport in place and changes its action to Show in Library.

## Native app behavior

- The launcher allows slow first-run migrations, automatically restarts an unexpectedly terminated local server, and uses a nonblocking startup-failure sheet.
- If the server recovers after a failure sheet appears, the launcher rechecks health, dismisses the stale sheet, and reloads the app automatically.
- Build/relaunch verification must always use the original `Gewu Insight.app`, preserve its Dock identity, verify `/api/health`, and confirm the running page contains the new code.
- Only true blank title-bar regions can trigger window zoom/restore; app tabs and search controls do not.

## User Guide

- `paper_monitor/user_guide.html`, generated `paper_monitor/user_guide.tex`, and `paper_monitor/Gewu_Insight_User_Guide.pdf` describe the same flat Paper Files and Set as Default/Use Automatic Selection model.
- Paper Files cards default to File type plus a clickable size footer; Annotation/Source expand per card. Library paper-row double-click resolves Default (legacy current-file fallback), opening PDFs in Preview. Its row DOM survives selection/file loading; deletion refreshes only adjacent content. Library Details no longer duplicates Files; My Publications retains its only file panel. HTML/LaTeX/PDF document these behaviors.
- The fixed-layout guide currently has 74 visually checked pages with consistent numbering and section transitions.

## Verification

- Python compile check passes.
- Full product suite passes: 649 tests, including edge-aligned file footers, Author details rendering/identifier actions, stable keys before/after Library placement and restart, legacy cache key projection, default-file opening, preserved row DOM, card disclosure, indexed migration, shared/external file protection, and delete rollback.
- Schema 15 index-only upgrade verified on a formal DB backup: paper/resource/provenance/placement counts unchanged, zero foreign-key errors. The former full-table shared-path guard took 4.611 s; indexed lookup is below 1 ms. Real Trash + full deletion on the upgraded copy took 0.073 s.
- Pre-upgrade snapshot retained at `/private/tmp/gewu-file-index-check.Vg9HL9/before-indexes.sqlite`. No product test modified the formal DB; normal App startup installed the indexes. The original App was rebuilt/reopened, health/signature checked, and Library row double-click verified in Preview. Compact cards and removal of the Library Details Files box were checked live; My Publications keeps its only file panel. Packaged PDF matches the generated 74-page guide.
- Subject calendar verified live against cached August 31 Quantum Sensing (zero with asterisk), August 29 (plain zero), and Quantum Computing (independent count/marker). No manual online refresh or schema migration was needed.
- Subject Add to Library regression tests exercise real API-shaped responses from temporary SQLite and the real frontend updater, including aliased lists, detached caches, and later image updates. Live App confirms the asterisk legend is the last summary item; the guide screenshot and fixed-layout exports are synchronized.
- Credential reveal and scoped Read All regressions use synthetic credentials and temporary SQLite only; no real credential was revealed and no formal unread history was cleared for verification.
- Author details verified in the rebuilt original App using the user's already-read nickelate PDF: no redundant heading, unbroken action labels, visible key, compact filename. Health and single-instance checks pass. No schema migration or direct formal DB edits were needed; guide HTML, Hong Ding screenshot (user-specified), LaTeX, and PDF are synchronized.

## Current caveats

- Schema 14's first formal launch can take roughly 20 seconds while provenance and file metadata are backfilled; the native startup timeout remains 120 seconds.
- Legacy resources with insufficient evidence remain `Unknown`; migration does not invent a Published version or source.
- Publisher/network access remains dependent on remote availability and anti-bot limits; avoid overlapping broad refreshes.
