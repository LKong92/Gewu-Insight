# User Guide audit — 1.0.0 / Build 1

Edition reviewed: September 22, 2026. Baseline audit: September 16, 2026. Scope: the installed macOS product and the
source on main. This is a current manual audit, not a chronological change log.

## September 22 write-permission presentation

Writable collections now show only Library and root Space names. Clicking a
row toggles its blue selection and includes all active subfolders. My Publications
write access is deferred. Saved, unsaved and failed states remain visible beside
the collapsible editor title; saved values survive reopening and page reload,
and failed requests preserve drafts. Earlier child-only grants remain partial
until the user explicitly selects their root; no grant migration is performed.

Validation: 86 scoped AI access, folders, writes and Guide checks pass. The
synthetic Chrome probe verifies independent multi-selection, three collapse
cycles, close/reopen, full reload from SQLite, failed-save draft retention,
unrelated permission updates, unchanged tokens/read scopes and legacy partial
grants. Six PDF structure checks pass; all nine changed PDF pages (8, 94–101)
were rendered and reviewed. The PDF remains 116 pages. Existing real-App
screenshots are retained; no real grants, files or live tasks were changed.

## September 21 MCP write-access follow-up

The AI Access topic now covers the twenty MCP tools, separate write operations
and writable roots, metadata-first PDF import, ordinary-file versus attachment
ownership, reuse of DOI/arXiv identities and existing Defaults, and standalone
Resolve jobs. Transfer guidance is explicitly per file: upload, register,
immediately reclaim that file's staging, then continue. Whole-collection size
does not count against the temporary quota. Earlier claims that analysis was
the only supported write operation were removed.

The existing real-App screenshots are retained as illustrations of basic
connection and directory access. They do not depict the newly added write
editor. New editor validation uses a disposable synthetic-library browser
probe, not a replacement User Guide screenshot or live-user permission edit.

Validation: 1,178 product tests, the synthetic AI Access UI probe and six PDF
structure checks pass. The 116-page PDF has 356 resolving internal links; 36
affected or repaginated pages were rendered and reviewed. The source and
signed App-bundle PDF match, and signature-stripped native code is unchanged.

## September 18 workflow audit

Reviewed the complete 49-topic inventory against the September 16 baseline and
the intervening product changes through `4000d98`, plus the pending Author
Monitor correction. Changed instructions were checked against runtime source;
unchanged feature explanations and illustrations retain the baseline evidence
below. This is a documentation pass, not another live-data functional test.

The concrete corrections are:

- Folder-drop background import, footer Details, reopening live results and
  saved reports, and clicking linked log rows to Show in Library. Navigation
  closes the task window without stopping work; unlinked messages remain text.
- Refresh Info Pause/Continue versus terminal Stop; import Stop Import and
  identifier Stop Search have different controls. Keep completed work and
  history, end the import's linked metadata queue, and distinguish Delete Import.
- Independent activity indicators, constrained width, horizontal overflow,
  truncation and full hover information. Details is a shared task entry point,
  not a clickable action on every progress chip or the Paper Details pane.
- Unknown/Other automatic Default fallback, non-PDF main files, canonical main
  placement, native macOS Finder aliases and secondary associated-directory
  aliases. External and shared files remain protected.
- Ownership transfer in both directions, single-file card commands versus
  whole-paper adoption, new independent Keys, empty-source removal, safe moves
  versus external drag copies, and removal of outdated menu ellipses.
- Exact-content reimport reuse without merging edited versions; direct startup
  without full-library normalization/backups; targeted interrupted-move recovery.
- Help > Contact Us and default email-client draft, MCP quota visibility and
  release workflow, APS textual journal labels, and bounded Author Monitor
  missing-data completion with separate profile discovery/citation refresh.

Runtime evidence: `ui_server.py` (Loader rendering/log navigation, footer routing
and activity styles, paper context menus); `metadata_jobs.py`; `file_reassignment.py`;
`storage.py`; managed-layout and resource-deduplication modules and their existing
contracts; `scripts/PaperMonitorApp.m` (Contact Us and native Loader bridge);
`mcp_server.py`; `author_metadata_work.py` and `author_profile_retry.py`.

Only `loader-metadata.png` is replaced in this pass. The user selected a completed
folder task and its visible log position in the original App. Core Graphics
captured the full standalone window without overlays or image alteration. The
earlier capture was discarded at the user's request. The replacement correctly
shows Pause, Stop, history and a paper log; partial results are described honestly
in its caption. No import, metadata refresh, Stop, Pause, log navigation or email
send was triggered for this audit. All other 34 illustrations are retained.

## September 18 validation

- 30 Guide/audit unit checks pass, including current controls, log navigation,
  file ownership, aliases, fallback, startup, contact and quota contracts. All six
  PDF structure checks pass. `git diff --check` passes.
- Generated PDF: 115 pages, 356 resolving internal links; all 49 HTML topic
  anchors and 35 figure registrations remain. HTML, generated TeX and the bundled
  PDF are synchronized. Version 1.0.0 / Build 1 is unchanged; guide edition is
  September 18.
- Compared PDF page bodies with the pre-audit 111-page edition; rendered and
  visually reviewed 45 changed/repaginated pages and the three Product Identity
  pages. Identity 4-1 is on page 102, 4-2 on 103, and 4-3/4-4 share 104. The
  builder retains continuous identity flow without introducing forced breaks.
- Source PDF and App resource match byte-for-byte; strict deep code-signature
  verification passes. Native executable copies are identical after stripping
  signatures, so documentation packaging does not change executable code.
- No live task was created, paused or stopped, no log row was clicked for
  acceptance, no email sent and no App restart performed. Screenshot capture
  only used the user's selected existing task and final log position. Earlier
  Author Monitor runtime changes are recorded separately in commit `6110a80`.

Evidence and the pre-update App/PDF are under
`/private/tmp/gewu-guide-sep18/`. No research database migration, repair, file
move or permission/grant change was performed.

## Baseline method and evidence (September 16)


All 49 registered topics were read against the installed macOS product, current
UI labels and feature contracts, with source checks for changed behavior. This
round changes documentation and illustrations only. Five changed captures were
replaced and two new illustrations added; the other 28 images were retained after
review. The screenshot inventory records actual capture dates and the limits.
No Settings page was recaptured merely because the edition date changed.

The subsequent MCP directory feature adds a focused AI Access follow-up: its two
changed Settings captures, permission controls, both directory tools, grant
boundaries, stable IDs and pagination are documented. Other topics and captures
retain the completed audit above. Runtime references for this follow-up are
`ai_folders.py`, `ai_service.py`, `ai_store.py` and `mcp_server.py`.

The name-and-mission follow-up places the user-approved English interpretation
at the start of Product Identity and aligns the short Welcome explanation.
It emphasizes experimental phenomena, physical pictures, intuition and
insightful guesses, then connects that outlook to revisiting papers, comparing
results and preserving research notes. The final English sentence is followed
by the approved Chinese sentence in parentheses. All screenshots and artwork
are retained; this follow-up makes no runtime or research-data change.

Primary implementation references: `paper_monitor/ui_server.py`,
`paper_monitor/storage.py`, `paper_monitor/metadata_refresh.py`,
`paper_monitor/library_destination.py`, `paper_monitor/file_placement.py`,
`paper_monitor/search_matching.py`, `paper_monitor/browser_capture.py`,
`scripts/PaperMonitorApp.m` and the native Browser controllers. Supporting
contracts: `ADD_TO_LIBRARY.md`, `RECYCLE_DELETION.md`, `PAPER_IDENTITY.md`,
`METADATA_REFRESH.md`, `MONITOR_DOWNLOADS.md` and `AI_ACCESS.md` in this directory.

The compiled universal launcher reports a macOS 14.0 deployment target. The
packaged minimum-system version and installation requirements remain consistent
with that target. This does not change the target or introduce a runtime feature.

## Structure and corrections

- Preserve the existing orientation, concepts, manual, identity and reference
  structure and all 49 topic anchors. Keep Product Identity chapters continuous.
- Document shared Title/Authors/Year/Journal sorting, direction arrows, retained
  selection, folders first and missing values last. Remove the unsupported
  table-column-resizing claim.
- Replace the old Space toolbar description with persistent source headings
  that stop before Details, nested headings underneath, and source menus for
  Rename/Move Space to Library. Explain full Shortcut ancestry in the footer;
  remove the incorrect claim that breadcrumb segments are clickable.
- Correct Add Paper to the shared single-submit inline workflow for Library,
  Shortcut and Space folders, with review of the resolved record afterward.
- Add Perspective, News and Views, Summary, Analysis, Source Data and Source
  Code. Distinguish resource classification from publication metadata and
  automatic Default priority. Remove the stale ten-type count. The MCP analysis
  writer still registers notes as Other; do not falsely describe automatic
  relabeling of existing notes or change that runtime behavior in a docs task.
- Explain full-column Paper Files drops, including cards and the empty gray
  area, without requiring an expanded card.
- Clarify Browser source-paper association, manual Gewu Key correction and the
  resulting active destination; loaded original PDF reuse, metadata parsing,
  explicit redownload, both native save arrows, and the meaning of Article only.
  Update the centered tab icon/title and both review screenshots.
- Explain Google Scholar temporarily unavailable and paced transport recovery
  separately from access cooldowns; align the scheduler description. Explain
  secure-connection/VPN failures without diagnosing a certificate from one code.

## Topic-by-topic coverage

Each registered topic appears exactly once below. “Retain” means the current
instruction was checked and did not need a substantive rewrite.

| Topic | Review result |
|---|---|
| [Welcome](../paper_monitor/user_guide.html#welcome) | Add Contact Us, default email client, recipient, subject and user-controlled sending; retain approved name/mission text and 1.0.0 / Build 1. |
| [Guided Tour](../paper_monitor/user_guide.html#guided-tour) | Retain six-tab visual grammar, selection, pane sizing, search and separate Help window. |
| [Your First Session](../paper_monitor/user_guide.html#first-session) | Align managed Default placement and unclassified fallback with non-PDF files; retain the complete research-to-writing route. |
| [System Architecture at a Glance](../paper_monitor/user_guide.html#system-overview) | Verify six workspaces, shared record, independent files and provider boundary. |
| [The Persistent Paper Object](../paper_monitor/user_guide.html#persistent-paper-object) | Separate guarded automatic metadata from non-discarding file-import reconciliation. |
| [Why SQLite Is the Core](../paper_monitor/user_guide.html#sqlite-core) | Retain SQLite authority, provenance, durable settings and coordinated file operations. |
| [Visible Research Files](../paper_monitor/user_guide.html#visible-research-files) | Correct Unknown/Other fallback and explicit secondary-type exclusions; preserve flat file properties and identity. |
| [The Personal Research Workspace](../paper_monitor/user_guide.html#personal-research-workspace) | Retain six-tab model; organization and discovery do not imply extra physical copies. |
| [From Discovery to Durable Memory](../paper_monitor/user_guide.html#research-loop) | Separate discovery of a published DOI from explicit acquisition of the PDF. |
| [State, Scope, and Safe Change](../paper_monitor/user_guide.html#state-and-scope) | Correct non-PDF Default placement; retain active-reference Recycle and shared-resource boundaries. |
| [Library Layout](../paper_monitor/user_guide.html#library-layout) | Add separate footer task indicators, truncation/hover/overflow and Details routing; retain full Shortcut ancestry. |
| [Navigate with Mouse and Keyboard](../paper_monitor/user_guide.html#navigation) | Verify independent saved selection, keyboard traversal and primary tab focus. |
| [Folders, Shortcuts, and Spaces](../paper_monitor/user_guide.html#organize) | Retain bounded source headings, shared table workflow and full Shortcut paths; replace symbolic-link-only wording with native Finder and associated-directory aliases. |
| [Search, List View, and Table View](../paper_monitor/user_guide.html#search-views) | Document all four table sort headers and both directions; add the real table illustration and correct search scope. |
| [Add Papers and Files](../paper_monitor/user_guide.html#import-files) | Correct the shared inline single-submit Add Paper workflow and post-add review. |
| [Use Paper Details](../paper_monitor/user_guide.html#paper-details) | Verify compact two-row actions, Get DOI / Refresh Info, citation evidence and files separation. |
| [Edit DOI and arXiv Identifiers](../paper_monitor/user_guide.html#identifiers) | Document Return, green saved/updated feedback, explicit correction and guarded refresh. |
| [Refresh Info: One Paper, a Folder, or the Library](../paper_monitor/user_guide.html#loader-maintenance) | Add linked-log Show in Library, close/return through Details, task history, terminal Stop and the distinct import/search controls; replace the changed screenshot. |
| [Understand Paper Files](../paper_monitor/user_guide.html#paper-files) | Correct main-file ownership, non-PDF Default and last-file removal; distinguish transfer versus independent creation and remove menu ellipses. |
| [Preview Files with Quick Look](../paper_monitor/user_guide.html#quick-look) | Document immediate selection updates, same-file reuse and hybrid Markdown handling. |
| [Choose File Types and the Default File](../paper_monitor/user_guide.html#versions-current) | Document automatic Unknown/Other fallback and non-PDF main placement while preserving manual choices and all classification labels. |
| [Add and Classify Attachments](../paper_monitor/user_guide.html#attachments) | Add exact-content reimport reuse and preservation of changed/annotated bytes; retain whole-column drops and classification controls. |
| [Download and Sync Versions](../paper_monitor/user_guide.html#download-sync) | Clarify independent background jobs, validation, Default placement and explicit Browser fallback. |
| [Move a Standalone File into Paper Files](../paper_monitor/user_guide.html#drag-attach) | Document both internal directions, new Key on separation, card versus whole-paper moves, and external Finder copy boundaries. |
| [Delete and Recover Items](../paper_monitor/user_guide.html#recycle) | Distinguish placement, resource and Empty Recycle actions; preserve active references and whole-folder Trash shape. |
| [Use Folder Loader](../paper_monitor/user_guide.html#folder-loader) | Document background folder drops, live Details return, clickable log entries, safe Stop Import and saved results; clarify identity-based layout and exact-content reuse. |
| [Make a Portable Desktop Copy](../paper_monitor/user_guide.html#desktop-copy) | Retain independent exported files, pointer resolution and no bidirectional desktop sync. |
| [Back Up or Move to Another Mac](../paper_monitor/user_guide.html#backup-migrate) | Verify consistent SQLite plus managed-file backup, WAL and separate Browser/credential lifecycle. |
| [My Publications](../paper_monitor/user_guide.html#my-publications) | Verify profile add/import/history, identifier resolver, citation comments and export. |
| [Journal Monitor](../paper_monitor/user_guide.html#journal-monitor) | Retain discovery/filter/add workflows; clarify readable APS text labels. |
| [Subject Monitor](../paper_monitor/user_guide.html#subject-monitor) | Verify subject matching, numeric counts, stored windows, exclusions and add destination. |
| [Author Monitor](../paper_monitor/user_guide.html#author-monitor) | Align daily discovery, profile citation arrow, cached papers on failed parsing, bounded retries, and Author-only missing-data completion; no periodic saved-paper refresh. |
| [Browse, Bookmark, and Revisit Websites](../paper_monitor/user_guide.html#browser) | Update centered icon/title and both save-review images; clarify loaded-PDF reuse, native save arrows, source Key association and manual target correction. |
| [Open Source Settings](../paper_monitor/user_guide.html#citation-settings) | Verify source controls, masked credential visibility and separate service tests. |
| [arXiv Scope Settings](../paper_monitor/user_guide.html#arxiv-scope-settings) | Verify future discovery scope and grouped archive settings. |
| [Field Settings](../paper_monitor/user_guide.html#field-settings) | Verify default fields, Other Fields grouping and unchanged records. |
| [Quick Look Settings](../paper_monitor/user_guide.html#quick-look-settings) | Use the current hybrid PDF-and-Markdown label; distinguish explicit all-native mode. |
| [Default Add to Library Folder](../paper_monitor/user_guide.html#add-to-library-settings) | Verify choose/save, initial unsorted, overrides, stable folder ID and fallback. |
| [Website Links](../paper_monitor/user_guide.html#website-link-settings) | Verify internal/system browser routing and Save Details preference. |
| [AI Access](../paper_monitor/user_guide.html#ai-access) | Verify all nine tools and scoped folder traversal; retain append-only analysis and temporary-copy release. Explain that remaining quota appears in tool results, not an App meter. |
| [Naming and PDF Rename Rules](../paper_monitor/user_guide.html#naming) | Verify rename templates, naming scope and explicit preferences. |
| [How Gewu Insight Stores Files](../paper_monitor/user_guide.html#storage-model) | Document canonical Default including non-PDFs, secondary native Finder aliases and associated-directory aliases, stable canonical selection and protected collisions. |
| [Local Data and Privacy](../paper_monitor/user_guide.html#privacy) | Retain local/private data boundary and external provider/AI client responsibility. |
| [Visual Identity and Cultural Elements](../paper_monitor/user_guide.html#visual-identity) | Add the approved name meaning and software-mission connection, ending with the exact English/parenthesized Chinese sentence. Preserve glyph provenance, artwork and continuous Product Identity PDF chapters. |
| [Keyboard Shortcuts](../paper_monitor/user_guide.html#keyboard) | Verify contextual shortcuts for workspace, Browser, Quick Look and editing. |
| [Publisher and Network Access](../paper_monitor/user_guide.html#network-access) | Distinguish transport/VPN/secure-connection failures from publisher restrictions; retain access protections. |
| [Startup, Monitor Cache, and Text Size](../paper_monitor/user_guide.html#startup) | Document direct startup without whole-library reorganization/backups, narrowly scoped interrupted-move recovery and bounded Author Monitor retries. |
| [Troubleshooting](../paper_monitor/user_guide.html#troubleshooting) | Add terminal Stop, same-file duplicate-card reporting and Contact Us; correct non-PDF protected-main-file advice. |
| [Storage Reference](../paper_monitor/user_guide.html#storage-reference) | Align main-root description with canonical files and Finder aliases; retain SQLite, managed roots and disposable caches. |

## Version and reproducibility

`paper_monitor/__init__.py` is the version/build source for both builders.
The icon checksum remains a cache key, separate from the product Build.
HTML is the editable manual; generated TeX and PDF come from it. App resources
contain the same PDF. Internal links and the complete screenshot inventory are
checked automatically. Product Identity chapters 4-1 through 4-4 keep their
numbering and continuous flow in the builder.

## Baseline validation (September 16)

- All 27 Guide/audit tests and six PDF structure checks pass after the
  name-and-mission follow-up. Python compilation and `git diff --check` pass. The existing
  49-topic anchors and 35-image inventory are preserved.
- The regenerated PDF has 111 pages. The original audit reviewed every page;
  the MCP follow-up renders and reviews pages 86–111, including the changed
  AI Access pages and the later pages whose numbering moved. The name-and-mission
  follow-up renders the full PDF and compares page bodies: only contents pages
  3/5, Welcome pages 8–10 and Identity pages 99–101 change. These pages were
  visually reviewed, with final Identity pages inspected at 120 dpi. The builder
  now reserves space for a chapter title and its following subsection to avoid
  an orphaned heading while preserving continuous chapter flow.
- All 343 internal PDF links resolve, including the new Welcome-to-Identity
  link. Product Identity chapter 4-1 is on page 99, 4-2 on page 100, and 4-3
  and 4-4 share page 101, without forced chapter breaks.
- The source PDF and `Gewu Insight.app/Contents/Resources/Gewu Insight User
  Guide.pdf` match byte-for-byte. The documentation package passes strict App
  signature verification. Executable program code and 1.0.0 / Build 1 identity
  are unchanged by the documentation packaging.
- The real in-app AI Access topic displays both new tools and directory-grant
  instructions. Help → User Guide → Print Guide opens the verified App resource
  in macOS Preview. The final name-and-mission text and bilingual ending are
  also verified in the live Guide and on page 99 of the bundled 111-page PDF;
  the version remains 1.0.0 (Build 1).
- MCP feature validation passed 1,053 product tests, 44 scoped MCP checks and
  the temporary-data AI Access UI probe. The user-authorized restart activated
  adapter 1.2.0. Read-only acceptance through the existing configured connection
  found seven tools and seven visible roots; traversing the AI Space found its
  one subfolder and 34 placements with 34 unique Gewu Keys. Direct/recursive
  results agreed, and `get_paper` verified one returned key. The current Codex
  tool catalog also exposes both new directory tools; connector calls pass.
  Executable comparison after stripping signatures from temporary copies
  confirms that documentation packaging changed signatures only, not code.

The earlier audit evidence is local under `/private/tmp/gewu-guide-sync-qa/`;
the MCP follow-up, native captures, live acceptance and App backup are under
`/private/tmp/gewu-mcp-folders-qa/`. Name-and-mission PDF checks and the
pre-update App backup are under `/private/tmp/gewu-identity-guide-qa/`. No collection import, deletion,
classification, token replacement or grant change was performed for this
verification. The existing connection was already enabled for directory
browsing when live acceptance ran.

## September 17 MCP temporary-copy lifecycle follow-up

AI Access now documents `release_paper_file`, `get_file_delivery_status`,
delivery IDs, remaining byte/file quotas, and the read–release–continue
workflow. Local copy cleanup never removes original Paper Files, saved notes
or derived outputs. Offline/expired cleanup, shared active handles, safe retry
and the one-time adapter reconnect after upgrading are explained. Existing
screenshots are retained. The short MCP configuration example stays together
in the PDF builder so the expanded instructions do not orphan its first line.

Validation uses temporary research data: all 52 AI/MCP tests, 27 Guide/audit
checks and six PDF structure checks pass, including quota exhaustion/recovery,
stale handles, failed cleanup, process isolation, scoped symlink handling and
real STDIO read–release–save. The PDF remains 111 pages with 343 resolving
internal links; changed contents and AI Access pages are visually reviewed.
The signed App contains the same PDF; no native code or real research records
are changed. Current AI clients require one MCP reconnect to load adapter
1.3.0; this follow-up does not stop their active sessions. Evidence and the
pre-update App backup are in `/private/tmp/gewu-mcp-release-qa/`.
