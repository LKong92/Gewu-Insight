# User Guide audit — 1.0.0 / Build 1

Edition reviewed: September 13, 2026. Scope: the installed macOS product and the
source on main. This is a current manual audit, not a chronological change log.

## Method and evidence

All 49 registered topics were read and compared against the current native menus,
UI labels, routing and feature contracts. All Settings screenshots and changed workspace/form views were recaptured
from the original App. Four unchanged September 9 illustrations remain after
visual and behavior review. The screenshot inventory records the final assets,
individual capture dates and limits.

Primary implementation references: `paper_monitor/ui_server.py`,
`paper_monitor/storage.py`, `paper_monitor/metadata_refresh.py`,
`paper_monitor/library_destination.py`, `paper_monitor/file_placement.py`,
`paper_monitor/search_matching.py`, `paper_monitor/browser_capture.py`,
`scripts/PaperMonitorApp.m` and the native Browser controllers. Supporting
contracts: `ADD_TO_LIBRARY.md`, `RECYCLE_DELETION.md`, `PAPER_IDENTITY.md`,
`METADATA_REFRESH.md`, `MONITOR_DOWNLOADS.md` and `AI_ACCESS.md` in this directory.

The compiled universal launcher reports a macOS 14.0 deployment target. The
packaged minimum-system version and installation requirements now agree with
that target. This does not change the target or introduce a runtime feature.

## Structure and corrections

- Keep orientation, product concepts, operating instructions, product identity
  and technical reference as separate parts. Add a practical writing workflow
  to Your First Session.
- Move general metadata maintenance out of the imported-library-only context.
  One chapter explains Details, folders, all-Library, Loader and automatic checks;
  the old topic anchor remains valid. Folder menu text is Refresh Info.
- Add the missing Add to Library setting, including the existing-paper Browser
  exception and manual destination precedence.
- Remove contradictory Default-file and Recycle explanations. A Default PDF
  can change the primary physical location; a file with an active reference
  must stay in active storage. Resource deletion has a different scope from
  placement deletion or Empty Recycle.
- Explain manual identifier save versus Refresh Info; partial completion is
  green in the footer and source details remain in the button hover.
- Describe actual fuzzy text matching and Markdown preview behavior without
  promising concept/synonym search or universal publisher download success.
- Keep automatic source limits and Google Scholar protection distinct from
  user-initiated operations. No refresh, import, deletion or credential change
  is needed just to illustrate this manual.

The user additionally approved a presentation-only adjustment to Save to Gewu:
14 px panel title, compact spacing, neutral surfaces and the existing blue
primary-button style. Identity, PDF, destination and save/cancel logic are unchanged.

## Topic-by-topic coverage

Each registered topic appears exactly once below. “Retain” means the current
instruction was checked and did not need a substantive rewrite.

| Topic | Review result |
|---|---|
| [Welcome](../paper_monitor/user_guide.html#welcome) | Set 1.0.0 / Build 1 edition; distinguish macOS baseline from experimental Windows work. |
| [Guided Tour](../paper_monitor/user_guide.html#guided-tour) | Retain six-tab visual grammar, selection, pane sizing, search and separate Help window. |
| [Your First Session](../paper_monitor/user_guide.html#first-session) | Add a research-to-writing route; save identifiers explicitly; explain PDF Default placement. |
| [System Architecture at a Glance](../paper_monitor/user_guide.html#system-overview) | Verify six workspaces, shared record, independent files and provider boundary. |
| [The Persistent Paper Object](../paper_monitor/user_guide.html#persistent-paper-object) | Separate guarded automatic metadata from non-discarding file-import reconciliation. |
| [Why SQLite Is the Core](../paper_monitor/user_guide.html#sqlite-core) | Retain SQLite authority, provenance, durable settings and coordinated file operations. |
| [Visible Research Files](../paper_monitor/user_guide.html#visible-research-files) | Verify resource roles, fingerprints, annotation detection and physical storage explanation. |
| [The Personal Research Workspace](../paper_monitor/user_guide.html#personal-research-workspace) | Retain six-tab model; organization and discovery do not imply extra physical copies. |
| [From Discovery to Durable Memory](../paper_monitor/user_guide.html#research-loop) | Separate discovery of a published DOI from explicit acquisition of the PDF. |
| [State, Scope, and Safe Change](../paper_monitor/user_guide.html#state-and-scope) | Correct Default physical placement and active-reference Recycle rules. |
| [Library Layout](../paper_monitor/user_guide.html#library-layout) | Verify column/flat Paper Files layout; update existing classified-file illustration. |
| [Navigate with Mouse and Keyboard](../paper_monitor/user_guide.html#navigation) | Verify independent saved selection, keyboard traversal and primary tab focus. |
| [Folders, Shortcuts, and Spaces](../paper_monitor/user_guide.html#organize) | Add folder Refresh Info link; retain Shortcut, Space and shared-placement distinctions. |
| [Search, List View, and Table View](../paper_monitor/user_guide.html#search-views) | Document normal text selection and shared fuzzy matching; state semantic-search limits. |
| [Add Papers and Files](../paper_monitor/user_guide.html#import-files) | Verify identifier/title add, target-folder import and duplicate identity reuse. |
| [Use Paper Details](../paper_monitor/user_guide.html#paper-details) | Verify compact two-row actions, Get DOI / Refresh Info, citation evidence and files separation. |
| [Edit DOI and arXiv Identifiers](../paper_monitor/user_guide.html#identifiers) | Document Return, green saved/updated feedback, explicit correction and guarded refresh. |
| [Refresh Info: One Paper, a Folder, or the Library](../paper_monitor/user_guide.html#loader-maintenance) | Move to Papers and Files; unify single/folder/all/import/automatic entry comparison, cooldowns, source retry and Pause/Continue. |
| [Understand Paper Files](../paper_monitor/user_guide.html#paper-files) | Clarify Default placement, peer navigation and shared-resource deletion/protection. |
| [Preview Files with Quick Look](../paper_monitor/user_guide.html#quick-look) | Document immediate selection updates, same-file reuse and hybrid Markdown handling. |
| [Choose File Types and the Default File](../paper_monitor/user_guide.html#versions-current) | Verify all current File type/Annotation/Source choices and sticky manual Default. |
| [Add and Classify Attachments](../paper_monitor/user_guide.html#attachments) | Verify classified resources, note creation and user-driven attachment workflow. |
| [Download and Sync Versions](../paper_monitor/user_guide.html#download-sync) | Clarify independent background jobs, validation, Default placement and explicit Browser fallback. |
| [Move a Standalone File into Paper Files](../paper_monitor/user_guide.html#drag-attach) | Verify destination context, file reassignment and rollback if conversion fails. |
| [Delete and Recover Items](../paper_monitor/user_guide.html#recycle) | Distinguish placement, resource and Empty Recycle actions; preserve active references and whole-folder Trash shape. |
| [Use Folder Loader](../paper_monitor/user_guide.html#folder-loader) | Retain import settings, staged results and filename/content identifier discovery. |
| [Make a Portable Desktop Copy](../paper_monitor/user_guide.html#desktop-copy) | Retain independent exported files, pointer resolution and no bidirectional desktop sync. |
| [Back Up or Move to Another Mac](../paper_monitor/user_guide.html#backup-migrate) | Verify consistent SQLite plus managed-file backup, WAL and separate Browser/credential lifecycle. |
| [My Publications](../paper_monitor/user_guide.html#my-publications) | Verify profile add/import/history, identifier resolver, citation comments and export. |
| [Journal Monitor](../paper_monitor/user_guide.html#journal-monitor) | Verify Nature figures, calendar, field filters, provenance and configurable add destination. |
| [Subject Monitor](../paper_monitor/user_guide.html#subject-monitor) | Verify subject matching, numeric counts, stored windows, exclusions and add destination. |
| [Author Monitor](../paper_monitor/user_guide.html#author-monitor) | Add canonical per-author deduplication; retain Hong Ding example, unread scope and Scholar cooldown protections. |
| [Browse, Bookmark, and Revisit Websites](../paper_monitor/user_guide.html#browser) | Document left tab close, captured-PDF preview, existing-placement reuse and configured new-paper destination. |
| [Open Source Settings](../paper_monitor/user_guide.html#citation-settings) | Verify source controls, masked credential visibility and separate service tests. |
| [arXiv Scope Settings](../paper_monitor/user_guide.html#arxiv-scope-settings) | Verify future discovery scope and grouped archive settings. |
| [Field Settings](../paper_monitor/user_guide.html#field-settings) | Verify default fields, Other Fields grouping and unchanged records. |
| [Quick Look Settings](../paper_monitor/user_guide.html#quick-look-settings) | Use the current hybrid PDF-and-Markdown label; distinguish explicit all-native mode. |
| [Default Add to Library Folder](../paper_monitor/user_guide.html#add-to-library-settings) | New standalone settings chapter: choose/save, initial unsorted, overrides, stable folder ID and fallback. |
| [Website Links](../paper_monitor/user_guide.html#website-link-settings) | Verify internal/system browser routing and Save Details preference. |
| [AI Access](../paper_monitor/user_guide.html#ai-access) | Clarify revoked connection removal and scrolling activity; retain scoped read-only delivery and append-only analysis. |
| [Naming and PDF Rename Rules](../paper_monitor/user_guide.html#naming) | Verify rename templates, naming scope and explicit preferences. |
| [How Gewu Insight Stores Files](../paper_monitor/user_guide.html#storage-model) | Align Default physical promotion and shared active-reference ownership with filesystem/SQLite behavior. |
| [Local Data and Privacy](../paper_monitor/user_guide.html#privacy) | Retain local/private data boundary and external provider/AI client responsibility. |
| [Visual Identity and Cultural Elements](../paper_monitor/user_guide.html#visual-identity) | Preserve glyph provenance, cultural explanation and continuous Product Identity PDF chapters. |
| [Keyboard Shortcuts](../paper_monitor/user_guide.html#keyboard) | Verify contextual shortcuts for workspace, Browser, Quick Look and editing. |
| [Publisher and Network Access](../paper_monitor/user_guide.html#network-access) | Retain access/verification boundaries and independent provider cooldowns. |
| [Startup, Monitor Cache, and Text Size](../paper_monitor/user_guide.html#startup) | Explain bounded private-session recovery separately from server recovery; preserve queued/paused work. |
| [Troubleshooting](../paper_monitor/user_guide.html#troubleshooting) | Add identifier correction, partial refresh, active file in Recycle and search limitations. |
| [Storage Reference](../paper_monitor/user_guide.html#storage-reference) | Verify physical folders, SQLite and caches without introducing private paths into the manual. |

## Version and reproducibility

`paper_monitor/__init__.py` is the version/build source for both builders.
The icon checksum remains a cache key, separate from the product Build.
HTML is the editable manual; generated TeX and PDF come from it. App resources
contain the same PDF. Internal links and the complete screenshot inventory are
checked automatically. Product Identity chapters 4-1 through 4-4 keep their
numbering and continuous flow in the builder.

## Validation

- All 27 Guide/audit checks pass, including topic coverage, screenshot routes,
  release identity and source/bundled-PDF byte equality. One outdated Browser
  caption assertion was aligned with the new open-sidebar illustration before
  the final passing run.
- All six PDF structure checks pass. The final 104-page PDF was rendered and
  visually reviewed, including the rebuilt Browser ending; 340 named internal
  link references resolve. Product Identity chapters 4-1 through 4-4 flow
  continuously across pages 92–94.
- All 33 packaged illustrations were visually reviewed. Twenty-nine are new
  original-App captures; four unchanged September 9 illustrations were retained.
  Main views preserve all six tabs without Computer Use overlays. All Settings
  panels, the versioned About panel and both new Save to Gewu states are included.
- All 51 Browser capture tests and the existing browser UI probe pass. The probe
  exercises review, save/cancel, retries, stale responses, cache refresh, exact
  Library/Space navigation and three viewport sizes with temporary data. The
  first sandbox attempts could not bind temporary servers or launch Chrome;
  reruns with the required local process access passed.
- Changed Python files compile, the macOS build script passes syntax checking,
  and the final diff passes whitespace checks. The universal arm64/x86_64 App
  was built, signed and verified. Its 14.0 deployment target is unchanged.
- The original App was normally restarted with permission. About reports
  1.0.0 / Build 1; the real Library and Help UI load, the single local service is
  healthy, and the existing refresh remains paused at 1809/8834. The final App
  resource is byte-identical to the repository PDF.

The full product test suite was not repeated for this manual, version/build and
CSS-only presentation change. No paper import, deletion, classification,
preference, credential or grant change was performed for the audit. Screenshots
and native review dialogs were canceled without saving papers.
