# PROJECT_STATE.md

## Current handoff

- Repo: `/Users/lingyuan/PaperMonitor-20260516`
- Product/launcher: `Gewu Insight`（格物洞见）, `Gewu Insight.app`
- Formal branch: `main`; GitHub product remote is `origin/main`.
- Main UI/API: `paper_monitor/ui_server.py`; native shell: `scripts/PaperMonitorApp.m`.
- Active user-requested rollback target: 2026-09-05 21:13:01.970 Asia/Shanghai, the moment the assistant ASKED for the username/password fill test (call_j3iLRNT0FsrfLdy625bkUH9b), not the later 21:24 task completion. Recorded edits were inverted and forward-replayed in memory to verify exact source reconstruction. Runtime/test sources and historical guide text match this earlier checkpoint; only current handoff notices are newer. Pre-correction files are archived at `/private/tmp/gewu-before-question-checkpoint.laY5Bv/uncommitted-product-files.tgz`. Do not resume AutoFill experiments or guide alignment without a new request. No database, bookmarks/history, WebKit profile or password-store rollback.
- Future commits require English subjects and readable English bodies under `docs/COMMIT_GUIDELINES.md`; inspect all outgoing messages before pushing. Historical-description work is cancelled: leave existing history/hashes unchanged. These rules do not authorize automatic commit/push.
- SQLite is the only source of truth: `data/paper_monitor.sqlite`; JSON is export/diagnostic only.
- Product code, tests, docs, and required app artifacts stay on `main`. Benchmark code, data, instrumentation, results, seals, and reports stay in the isolated local benchmark worktree and must never be pushed.

## Current product model

- Library, Shortcut, Space, My Publications, Journal Monitor, Subject Monitor, and Author Monitor share canonical paper identities and stable Gewu Keys.
- Browser is the sixth main tab, after Author Monitor. Home shows the real Google homepage (including its own search/sign-in session) above a local Favorites grid. The independent visible WKWebView stays full-height off Home, retains its back stack across workspaces, and never preloads websites during startup.
- At the restored question checkpoint, compact fixed-Favorites Home and local address-history suggestions were already implemented. Two later address-focus assignments (21:16:03) are withdrawn as requested. The native WebKit code was unchanged between the question and 21:24 completion; it retains its original native menu focus handling. The restored historical manual/README had not yet caught up with compact Favorites or suggestions; that known documentation gap remains paused, not silently repaired during rollback.
- Browser sidebar keeps only Bookmarks/History tabs at the top; Import, Export, New Folder, and Search sit at the bottom. At widths below 231 px, Search takes a second bottom row to avoid clipping. The Bookmarks top tab remains the root-folder drop target.
- Browser has a resizable Bookmarks/History sidebar, nested bookmark folders, native add/edit sheets, search, drag/reordering, paginated local history, inline PDFs, and session-aware WKDownload saves. Layout is microtask-coalesced, not dependent on animation frames from the partially occluded workspace WebView. Existing paper external-link actions and Library PDF-to-Preview behavior are unchanged in this first release.
- Browser follows system networking without changing Clash/proxy settings. It has an isolated persistent WebKit profile with no workspace file/credential bridges; local APIs reject cross-site and DNS-rebound requests. Public HTTP(S) navigation excludes local/private destinations. Per-domain DIRECT routing and embedded sign-in compatibility still need site-specific verification.
- Browser compatibility: viewable PDF attachments/download links use native inline rendering. The original Download PDF button on Nature article s41586-026-10987-6 was verified to display its PDF in Browser, without a save sheet. Blocked same-host HTTP GET hops retry once over HTTPS without relaxing ATS/certificates or replaying forms; Nature's manuscript portal was verified after recovery. Do not access the WebCrypto Master Key or enter the user's keychain password.
- Bookmarks Import/Export supports Safari/Chrome HTML and Safari ZIP containing exactly one bookmark HTML member. Imports preserve hierarchy/order, are additive and transactional, reuse same-folder URLs, and skip unsupported/private/recognized authorization links. Export all or one folder as HTML; never include history, cookies, or passwords. Personal one-time Safari migration files remain outside the repository.
- Visible bookmarks request website icons directly with at most two bounded requests, no cookie/credential sharing or third-party favicon service, and disposable local cache. Missing icons use sidebar globes/Home monograms. Open Passwords opens Apple's app only. Safari-style password AutoFill is NOT implemented on tested macOS 15.1.1: ordinary password-provider APIs require trusted App/website association, and password extensions are not inherited by WKWebView. Do not claim that the launcher button solves AutoFill or add false associated domains/private keychain enumeration.
- AutoFill work is stopped. The user requested the native-menu version present when asked to test filling and subsequently reported username success once; restoring its code does not prove current OS credential delivery. Do not revisit passkey selection, request another password test, upgrade OS/SDK/signing, or contact Apple. The historical research note `docs/BROWSER_PASSWORD_AUTOFILL.md` is retained with a notice; its proposed future work is not authorization.
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

- Schema version is 16. The v15-to-v16 upgrade adds only browser_bookmarks (self-referencing folder cascade, sibling URL uniqueness) and browser_history (idempotent navigation events) plus indexes; preferences use app_settings. It does not rerun provenance backfill or Library seeding. Import/export, icons, and compatibility fixes require no further migration. The v14-to-v15 upgrade remains file-path-index-only.
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
- The fixed-layout guide has 77 pages. Browser's three-page chapter includes the new real-App Google/Favorites screenshot with a public Journals folder and Nature-filtered sidebar; it covers folder selection, bottom controls, migration/privacy, inline PDFs, HTTPS recovery, and the explicit unresolved Password AutoFill boundary. All six earlier workspace screenshots were refreshed, using the user's August 12 Nature page with visible figures for Journal Monitor and Hong Ding for Author Monitor. Registered screenshots are constrained to page width.

## Verification

- Python compile check passes.
- Latest question-checkpoint validation: JavaScript syntax, Python compile and all 688 product tests pass (26.242 s); databases are temporary. Restored source hashes were verified before adding current handoff notices; unrelated product files match the pre-correction archive. The original App was rebuilt/reopened: Library UI, single App/server, health, signature and served Browser assets pass; served JS has question-time SHA-256 `bbea622ba58cf08a47afdceae325106b72de6624dbdad8375e1461bacfcb0fef`. The restored 77-page PDF and bundled copy match; three Browser pages were rendered and visually checked. No commit/push, benchmark or direct formal DB write.
- New Home verified in the original App: real Google logo/search/sign-in, local site-icon grid, compact footer and narrow-width Search wrapping. Address-bar Google search hides Favorites; Back restores Home and Favorites. Public screenshot contains only Journals tiles and Nature results. Tests use temporary SQLite; only normal UI preferences were changed for verification, not paper data or credentials. No commit/push or benchmark run.
- Browser v15-to-v16 launch upgrade was preceded by an online SQLite backup at `/private/tmp/gewu-browser-db-backup.mJZUUc/before-browser.sqlite`. Read-only comparisons preserved 47,196 papers, 8,860 resources, 76,009 provenance observations, and 8,545 Library items; foreign-key errors remain zero. Product tests use temporary databases only.
- Browser verified in the original App: Google desktop homepage, native bookmark sheet/Command-D, retained page across workspace changes, saved history, inline public test PDF and a successful WKDownload to Downloads. No Clash rules or credentials were changed. Safari/system-browser speed parity and publisher institutional routes were not measured.
- Final Browser build/reopen passes health and code-signature checks; served JS/screenshot hashes match source and bundled PDF matches the 77-page manual. Native import picker and real favicons were checked live; HTML import/export roundtrips use temporary SQLite. No production test imports or private-bookmark exports were made. Changes are uncommitted; no push or benchmark run was performed.
- Schema 15 index-only upgrade verified on a formal DB backup: paper/resource/provenance/placement counts unchanged, zero foreign-key errors. The former full-table shared-path guard took 4.611 s; indexed lookup is below 1 ms. Real Trash + full deletion on the upgraded copy took 0.073 s.
- Earlier schema-15 snapshot retained at `/private/tmp/gewu-file-index-check.Vg9HL9/before-indexes.sqlite`. No product test modified the formal DB; normal App startup installed the indexes. Library row double-click was verified in Preview; compact cards and removal of the Library Details Files box were checked live, while My Publications keeps its only file panel.
- Subject calendar verified live against cached August 31 Quantum Sensing (zero with asterisk), August 29 (plain zero), and Quantum Computing (independent count/marker). No manual online refresh or schema migration was needed.
- Subject Add to Library regression tests exercise real API-shaped responses from temporary SQLite and the real frontend updater, including aliased lists, detached caches, and later image updates. Live App confirms the asterisk legend is the last summary item; the guide screenshot and fixed-layout exports are synchronized.
- Credential reveal and scoped Read All regressions use synthetic credentials and temporary SQLite only; no real credential was revealed and no formal unread history was cleared for verification.
- Author details verified in the rebuilt original App using the user's already-read nickelate PDF: no redundant heading, unbroken action labels, visible key, compact filename. Health and single-instance checks pass. No schema migration or direct formal DB edits were needed; guide HTML, Hong Ding screenshot (user-specified), LaTeX, and PDF are synchronized.

## Current caveats

- Schema 14's first formal launch can take roughly 20 seconds while provenance and file metadata are backfilled; the native startup timeout remains 120 seconds.
- Legacy resources with insufficient evidence remain `Unknown`; migration does not invent a Published version or source.
- Publisher/network access remains dependent on remote availability and anti-bot limits; avoid overlapping broad refreshes.
