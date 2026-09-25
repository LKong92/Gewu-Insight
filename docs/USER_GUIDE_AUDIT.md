# User Guide audit — September 24, 2026

Reviewed the complete 49-topic manual against product commit `e3e0a81` and the
original running macOS App. The guide edition changes; product version remains
1.0.0 / Build 1. This update changes documentation and illustrations only.

September 25 naming follow-up: **Literature Data Source** is the current menu
and dialog name. Update all guide references and the one settings screenshot;
retain the `citation-settings` anchor, credential behavior, and all other images.
This follow-up includes the corresponding native menu/UI text change, alongside
the README reorganization and separate development guide.

## Scope and method

Read every registered topic and reviewed all 35 existing screenshots. Cross-check
changed instructions against current UI labels, runtime code and feature contracts;
retain accurate text and pictures rather than rewriting them for appearance.
The 49 topic anchors, navigation order and approved Product Identity text remain.

Primary evidence: `paper_monitor/ui_server.py`, `markdown_preview_worker.js`,
`science_pdf.py`, `mcp_server.py`, `ai_contract.py`, file organization modules,
`scripts/PaperMonitorApp.m`, and the current `AI_ACCESS.md`, `PAPER_IDENTITY.md`,
`MONITOR_DOWNLOADS.md`, `METADATA_REFRESH.md` and `RECYCLE_DELETION.md` contracts.
The Codex configuration example was checked against linked official OpenAI MCP
documentation on September 24. No external client settings were changed.

## Screenshots and operational boundaries

Replace only three outdated images: the four-column Table View, the old Markdown
preview, and the New Connection form predating optional writes. Add one image of
the saved write-permission editor; retain the other 32 images byte-for-byte.
All four new images come from the original App. Main-window captures retain all
six tabs; settings captures use the full visible dialog bounds, with normal
scrolling rather than stitched content. No control overlays or painted pixels.
See [the screenshot inventory](USER_GUIDE_SCREENSHOTS.md) for all 36 figures.

The retained Library illustration already has Published version and Preprint with
the real Default; Author Monitor uses Hong Ding; Journal Monitor shows Nature
figures; Add Monitored Author is empty without a stale red pause message. These
remain suitable and were not recaptured merely to change their date. Earlier
orientation/Space pictures illustrate the named controls, not current edition
dates or every table column; the dedicated updated table figure shows all five.

Capture used existing files and existing saved grants. No literature imports,
deletion, classification, provider refresh, task start/stop, token creation,
permission changes or App restart were performed. Preview and settings were
closed; Library List View, its selected folder and normal window mode were
restored. This is a documentation audit, not a new full product regression run.

## Topic-by-topic coverage

Each registered topic appears once. Retained instructions were checked against
current behavior; a source or UI check does not imply a destructive live test.

| Topic | Review result |
|---|---|
| [Welcome](../paper_monitor/user_guide.html#welcome) | Update edition to September 24; retain approved name/mission, support contact and version 1.0.0 / Build 1. |
| [Guided Tour](../paper_monitor/user_guide.html#guided-tour) | Add native blank-top dragging and macOS desktop-edge behavior; retain double-click and control boundaries. |
| [Your First Session](../paper_monitor/user_guide.html#first-session) | Distinguish cataloged/PDF papers with public Keys from ordinary non-PDF files with internal storage keys. |
| [System Architecture at a Glance](../paper_monitor/user_guide.html#system-overview) | Verify six workspaces, shared record, independent files and provider boundary. |
| [The Persistent Paper Object](../paper_monitor/user_guide.html#persistent-paper-object) | Clarify independent ordinary files versus unidentified PDF papers; retain shared identity and guarded reconciliation. |
| [Why SQLite Is the Core](../paper_monitor/user_guide.html#sqlite-core) | Retain SQLite authority, provenance, durable settings and coordinated file operations. |
| [Visible Research Files](../paper_monitor/user_guide.html#visible-research-files) | Qualify normal App fingerprinting and document the separate metadata-first MCP import boundary. |
| [The Personal Research Workspace](../paper_monitor/user_guide.html#personal-research-workspace) | Retain six-tab model; organization and discovery do not imply extra physical copies. |
| [From Discovery to Durable Memory](../paper_monitor/user_guide.html#research-loop) | Separate discovery of a published DOI from explicit acquisition of the PDF. |
| [State, Scope, and Safe Change](../paper_monitor/user_guide.html#state-and-scope) | Verify non-PDF Default placement; retain active-reference Recycle and shared-resource boundaries. |
| [Library Layout](../paper_monitor/user_guide.html#library-layout) | Verify separate footer task indicators, truncation/hover/overflow and Details routing; retain full Shortcut ancestry. |
| [Navigate with Mouse and Keyboard](../paper_monitor/user_guide.html#navigation) | Verify independent saved selection, keyboard traversal and primary tab focus. |
| [Folders, Shortcuts, and Spaces](../paper_monitor/user_guide.html#organize) | Clarify real folder/Space renames, mirrored file paths, busy-file retry and Shortcut label-only rename. |
| [Search, List View, and Table View](../paper_monitor/user_guide.html#search-views) | Document all five sort headers including Time added, placement-time semantics, local time, both directions and horizontal overflow. Replace obsolete four-column figure. |
| [Verify Papers and Files](../paper_monitor/user_guide.html#import-files) | Verify the shared inline single-submit Add Paper workflow and post-add review. |
| [Use Paper Details](../paper_monitor/user_guide.html#paper-details) | Verify compact two-row actions, Get DOI / Refresh Info, citation evidence and files separation. |
| [Edit DOI and arXiv Identifiers](../paper_monitor/user_guide.html#identifiers) | Verify Return, green saved/updated feedback, explicit correction and guarded refresh. |
| [Refresh Info: One Paper, a Folder, or the Library](../paper_monitor/user_guide.html#loader-maintenance) | Verify linked-log Show in Library, close/return through Details, task history, terminal Stop and the distinct import/search controls; replace the changed screenshot. |
| [Understand Paper Files](../paper_monitor/user_guide.html#paper-files) | Retain whole-column drops, shared deletion, ownership transfers and protected Default; clarify that detached non-PDFs have no public Key. |
| [Preview Files with Quick Look](../paper_monitor/user_guide.html#quick-look) | Add collapsible Source record/Properties, note-versus-catalog values, responsive width, cached reopen and retry. Replace the obsolete Markdown layout. |
| [Choose File Types and the Default File](../paper_monitor/user_guide.html#versions-current) | Verify automatic Unknown/Other fallback and non-PDF main placement while preserving manual choices and all classification labels. |
| [Verify and Classify Attachments](../paper_monitor/user_guide.html#attachments) | Add exact-content reimport reuse and preservation of changed/annotated bytes; retain whole-column drops and classification controls. |
| [Download and Sync Versions](../paper_monitor/user_guide.html#download-sync) | Add Science main-first validation, appended supplementary PDFs, First Release classification and publisher-derived filenames; retain duplicates and manual Default protections. |
| [Move a Standalone File into Paper Files](../paper_monitor/user_guide.html#drag-attach) | Verify internal moves, external copies, ownership and rollback; distinguish PDF new public Key from standalone ordinary-file storage key. |
| [Delete and Recover Items](../paper_monitor/user_guide.html#recycle) | Distinguish placement, resource and Empty Recycle actions; preserve active references and whole-folder Trash shape. |
| [Use Folder Loader](../paper_monitor/user_guide.html#folder-loader) | Verify background folder drops, live Details return, clickable log entries, safe Stop Import and saved results; clarify identity-based layout and exact-content reuse. |
| [Make a Portable Desktop Copy](../paper_monitor/user_guide.html#desktop-copy) | Retain independent exported files, pointer resolution and no bidirectional desktop sync. |
| [Back Up or Move to Another Mac](../paper_monitor/user_guide.html#backup-migrate) | Verify consistent SQLite plus managed-file backup, WAL and separate Browser/credential lifecycle. |
| [My Publications](../paper_monitor/user_guide.html#my-publications) | Add translucent drag preview and blue insertion marker; verify profile import, roles, citations and export. |
| [Journal Monitor](../paper_monitor/user_guide.html#journal-monitor) | Retain discovery/filter/add workflows; clarify readable APS text labels. |
| [Subject Monitor](../paper_monitor/user_guide.html#subject-monitor) | Verify subject matching, numeric counts, stored windows, exclusions and add destination. |
| [Author Monitor](../paper_monitor/user_guide.html#author-monitor) | Add reorder feedback, partial identity review and persisted status meaning; clarify global metadata counts and Scholar restriction/transport distinction without changing source routes. |
| [Browse, Bookmark, and Revisit Websites](../paper_monitor/user_guide.html#browser) | Retain current live Browser/Save captures and loaded-PDF workflow; qualify Science First Release file-type suggestions. |
| [Literature Data Source](../paper_monitor/user_guide.html#citation-settings) | Verify source controls, masked credential visibility and separate service tests. |
| [arXiv Scope Settings](../paper_monitor/user_guide.html#arxiv-scope-settings) | Verify future discovery scope and grouped archive settings. |
| [Field Settings](../paper_monitor/user_guide.html#field-settings) | Verify default fields, Other Fields grouping and unchanged records. |
| [Quick Look Settings](../paper_monitor/user_guide.html#quick-look-settings) | Use the current hybrid PDF-and-Markdown label; distinguish explicit all-native mode. |
| [Default Verify to Library Folder](../paper_monitor/user_guide.html#add-to-library-settings) | Verify choose/save, initial unsorted, overrides, stable folder ID and fallback. |
| [Website Links](../paper_monitor/user_guide.html#website-link-settings) | Verify internal/system browser routing and Save Details preference. |
| [AI Access](../paper_monitor/user_guide.html#ai-access) | Check all 24 MCP tools, permissions, stable IDs, ownership and local paths, metadata-first import, independent Resolve, per-file staging/release and My Publications write exclusion. Replace blank new-connection figure and add saved write editor. Recheck official Codex setup documentation. |
| [Naming and PDF Rename Rules](../paper_monitor/user_guide.html#naming) | Verify rename templates, naming scope and explicit preferences. |
| [How Gewu Insight Stores Files](../paper_monitor/user_guide.html#storage-model) | Verify canonical Default including non-PDFs, secondary native Finder aliases and associated-directory aliases, stable canonical selection and protected collisions. |
| [Local Data and Privacy](../paper_monitor/user_guide.html#privacy) | Retain local/private data boundary and external provider/AI client responsibility. |
| [Visual Identity and Cultural Elements](../paper_monitor/user_guide.html#visual-identity) | Retain approved mission and exact bilingual ending, glyph provenance and artwork. Preserve continuous Product Identity chapters 4-1 through 4-4. |
| [Keyboard Shortcuts](../paper_monitor/user_guide.html#keyboard) | Verify contextual shortcuts for workspace, Browser, Quick Look and editing. |
| [Publisher and Network Access](../paper_monitor/user_guide.html#network-access) | Distinguish transport/VPN/secure-connection failures from publisher restrictions; retain access protections. |
| [Startup, Monitor Cache, and Text Size](../paper_monitor/user_guide.html#startup) | Verify direct startup without whole-library reorganization/backups, narrowly scoped interrupted-move recovery and bounded Author Monitor retries. |
| [Troubleshooting](../paper_monitor/user_guide.html#troubleshooting) | Add Markdown loading/header recovery and Scholar cooldown versus completed identity-review messages; retain existing recovery and safety boundaries. |
| [Storage Reference](../paper_monitor/user_guide.html#storage-reference) | Align main-root description with canonical files and Finder aliases; retain SQLite, managed roots and disposable caches. |

## Reproducibility and validation

HTML is the editable source; the existing builder generates TeX and PDF and
registers the new image. The builder continues to enforce linked numbering and
continuous Product Identity chapters 4-1 through 4-4. Temporary captures, baseline
copies and QA are kept outside the repository in `/private/tmp/gewu-guide-sep24/`.

- Thirty guide/audit tests and six PDF structure checks pass. Exact-wording
  assertions were updated for the clarified cataloged-paper sentence; no runtime
  test or product behavior was changed. Builder Python compilation and diff
  whitespace checks pass.
- The rebuilt PDF has 118 pages. All pages were visually reviewed as contact
  sheets, with 27 changed or related pages inspected at reading resolution.
  All 913 named destinations resolve; 364 internal links have no missing target.
  All 49 topic anchors and all 24 current MCP tool names remain documented.
- Product Identity 4-1 through 4-4 flows on pages 105–107; 4-3 and 4-4 share
  page 107. No per-chapter forced breaks were introduced. Figure proportions,
  captions and the original image constraints remain in the builder.
- SHA-256 comparison confirms exactly three replacements and 32 byte-identical
  retained screenshots, plus the one new write-permission figure.
- Sixteen documentation/package files were synchronized to the original project
  with clean-HEAD/preimage checks, backups and post-copy hashes. Source and bundled
  PDFs match. Both App signatures verify; removing signatures from temporary
  before/after executable copies yields identical hashes, confirming unchanged
  native code. Only the embedded PDF and required signing data changed in the App.
- Final live verification in the original App passes: Help opens the September
  24, 2026 edition, the Time added instructions and updated Table View image
  render correctly, and searching “write permissions” finds AI Access. Print
  Guide opens the bundled PDF in macOS Preview, which reports Page 1 of 118 and
  the original App resource path. The guide was left on Welcome with its search
  cleared. No authentication setting, permission or literature data was changed;
  no App restart, commit or push was performed.

## Initial licensing follow-up — September 24, 2026 (v1.0, superseded)

The subsequent licensing-only revision adds the custom academic/non-commercial
grant to Welcome and a dedicated final copyright page, clarifies the role of scholarly-source
settings, and limits the artwork statement to rights the
project actually owns. Private research modifications are permitted; public
sharing is limited to unmodified official versions unless separately authorized.
Commercial uses require prior written authorization. See
[the licensing/dependency audit](DEPENDENCY_LICENSE_AUDIT.md) for the complete
change inventory and unresolved third-party permissions.

The manual now has 119 pages. All 49 topic anchors and 36 screenshot files remain;
no screenshot was replaced. All 913 earlier named PDF destinations resolve, with
only `page.119` added. Eleven changed pages (3, 6, 8–11, 82–83, 106, 118–119) were
rendered and reviewed. Product Identity's continuous chapter rules remain intact.
The 30 guide/audit tests, 16 macOS window/package checks and six PDF structure
checks pass. The final source and App-bundled PDFs and legal texts match; the
universal App signature verifies. At initial delivery, no live App restart was
performed. After the user authorized commit/push, the original App was normally
restarted once: one App/backend and healthy local service were confirmed, and
the actual About window displayed the new licensing summary before returning
to Library. No literature mutation or source refresh was requested.

## Research-sharing follow-up — September 24, 2026 (v1.1)

The user subsequently permitted non-commercial research sharing of modified
versions, derivative works and patches, including public research forks and PRs.
The former original-only restriction above is historical, not the current rule.
Welcome, the final copyright page, licensing guides and packaged LICENSE now
agree. CONTRIBUTING.md separately explains that research sharing needs no CLA,
whereas upstream commercial licensing of an external contribution requires a
separately agreed grant. No finalized CLA or signed contributor authorization is
claimed. The authors' institutional ownership questions are deferred at the
user's request.

The PDF remains 119 pages with all 914 named destinations. Only pages 8 and 119
have changed extracted text; both were rendered and visually checked. Screenshots,
product-operation descriptions and Product Identity chapter flow are unchanged.
The final 30 Guide/audit tests, six new licensing-consistency tests, 16 macOS
window/package tests and six PDF structure checks pass. An initial Guide test
ran before App packaging completed and detected the old bundled PDF; the final
post-build rerun passes with byte-identical source/bundled PDF and legal files.
Python syntax, shell syntax, diff checks and the App signature pass. At initial
delivery, no App restart, commit or push was performed. The user subsequently
authorized commit/push and explicitly approved a normal App restart. The original
App was restarted as one App/backend with a healthy local service; Help > User
Guide displayed the new modified-version research-sharing permissions. The guide
was then closed, leaving the Library interface available. No literature mutation,
contribution acceptance or repository-visibility change was requested or performed.
Consult Git history for delivery status. The earlier release-ZIP signing issue
and unresolved third-party asset rights remain outside this follow-up.
