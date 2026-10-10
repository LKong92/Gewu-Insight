# User Guide coverage and provenance

The current manual is the October 6, 2026 edition for macOS 1.0.0 / Build 1.
The coverage table records that edition's 49 topics. This page summarizes its
sources and maintenance requirements; it is not a new App or installer audit.
Windows has its own bundled User Guide.

## Sources and screenshots

- Editable source: `paper_monitor/user_guide.html`; PDF builder:
  `scripts/build_user_guide_pdf.py`.
- The manual uses 38 original-App screenshots. The Guide window and Database
  Location images were updated for the October 6 edition. See
  [the screenshot inventory and capture rules](USER_GUIDE_SCREENSHOTS.md).
- Preserve all six tabs, the clean empty Add Monitored Author form without
  cooldown text, Hong Ding in Author Monitor, Nature with figures in Journal
  Monitor, and classified multiple Paper Files in Library. Do not synthesize,
  overlay or retouch controls to create those states.
- Check descriptions against the relevant identity/storage, Browser, Monitor,
  metadata and AI Access modules and their companion documentation. Publisher
  content in a screenshot does not establish access for every user.

## Topic-by-topic coverage

Each existing topic and anchor appears exactly once below. Accurate material is retained; review does not mean every paragraph needs rewriting.

| Topic | Review result |
|---|---|
| [Welcome](../paper_monitor/user_guide.html#welcome) | Update edition to October 6; retain product version/build and mission; local ownership now names the selected research folder. |
| [Guided Tour](../paper_monitor/user_guide.html#guided-tour) | Check Help navigation, search, Print Guide and six main tabs; replace the opening screenshot with the actual October 6 window. |
| [Your First Session](../paper_monitor/user_guide.html#first-session) | Add first-launch database choices, whole-workspace selection, remembered locations and the old-installation migration link; retain paper import instructions. |
| [System Architecture at a Glance](../paper_monitor/user_guide.html#system-overview) | Verify six workspaces, canonical paper identity, independent resources, SQLite and external provider boundaries. |
| [The Persistent Paper Object](../paper_monitor/user_guide.html#persistent-paper-object) | Add explicit distinction between a research-paper identity, a linked publication notice and a corrected full article. |
| [Why SQLite Is the Core](../paper_monitor/user_guide.html#sqlite-core) | Retain SQLite authority, provenance, durable settings and coordinated file operations. |
| [Visible Research Files](../paper_monitor/user_guide.html#visible-research-files) | Name the managed research workspace rather than the source project; retain normal import, canonical/associated storage and metadata-first MCP boundaries. |
| [The Personal Research Workspace](../paper_monitor/user_guide.html#personal-research-workspace) | Verify shared records across six tabs, multiple placements, Spaces and scope-specific removal. |
| [From Discovery to Durable Memory](../paper_monitor/user_guide.html#research-loop) | Retain separate steps for discovery, organization, PDF acquisition, reading and saved analysis. |
| [State, Scope, and Safe Change](../paper_monitor/user_guide.html#state-and-scope) | Align the closed backup baseline with the selected workspace and external linked originals; keep scoped operation boundaries. |
| [Library Layout](../paper_monitor/user_guide.html#library-layout) | Verify independent Paper Files/Details columns, footer activity indicators, search and navigation. |
| [Navigate with Mouse and Keyboard](../paper_monitor/user_guide.html#navigation) | Verify keyboard focus, traversal, saved selection and tab transitions; read acknowledgement is documented separately. |
| [Folders, Shortcuts, and Spaces](../paper_monitor/user_guide.html#organize) | Verify real folder/Space versus shortcut renames, mirrored paths, busy-file retry and complete ancestry. |
| [Search, List View, and Table View](../paper_monitor/user_guide.html#search-views) | Retain five sortable columns including Time added, placement-time semantics and horizontal overflow. |
| [Add Papers and Files](../paper_monitor/user_guide.html#import-files) | Verify Add Paper, identifier/title entry, metadata-only catalog records and ordinary standalone files. |
| [Use Paper Details](../paper_monitor/user_guide.html#paper-details) | Add Refresh Info publication-update lookup, Paper Files notice summaries, explicit relations and coverage/timing limits. |
| [Edit DOI and arXiv Identifiers](../paper_monitor/user_guide.html#identifiers) | Verify Return/save before refresh, manual identifier protection and no automatic periodic refresh of saved papers. |
| [Refresh Info: One Paper, a Folder, or the Library](../paper_monitor/user_guide.html#loader-maintenance) | Add Quick/Full DOI-based update discovery; retain folder/all-Library scope, cooldowns, logs, Pause/Stop and restart boundaries. |
| [Understand Paper Files](../paper_monitor/user_guide.html#paper-files) | Add notice metadata versus local notice file distinction and the same display in My Publications; retain file controls and protected Default. |
| [Preview Files with Quick Look](../paper_monitor/user_guide.html#quick-look) | Add local inline/display Markdown math, literal code and bounded fallback; retain properties, source record and preview limits. |
| [Choose File Types and the Default File](../paper_monitor/user_guide.html#versions-current) | Verify all 21 file types, notice exclusion from automatic Default, corrected-article priority, manual Default and Unknown/Other fallback. |
| [Add and Classify Attachments](../paper_monitor/user_guide.html#attachments) | Verify exact-content reuse, file type/source/annotation and preservation of distinct annotated copies. |
| [Download and Sync Versions](../paper_monitor/user_guide.html#download-sync) | Replace obsolete manual-only fallback wording with native APS Harvest/ACS/Science/Nature routes, PDF-only supplements and main-PDF failure diagnosis. |
| [Move a Standalone File into Paper Files](../paper_monitor/user_guide.html#drag-attach) | Verify internal ownership moves, external copies, detaching into independent items and alias/busy-state safeguards. |
| [Delete and Recover Items](../paper_monitor/user_guide.html#recycle) | Verify recoverable placement removal, permanent emptying scope, shared-reference preservation and native Trash boundaries. |
| [Use Folder Loader](../paper_monitor/user_guide.html#folder-loader) | Verify recursive imports, metadata modes, background progress, source identity handling and completed-operation boundaries. |
| [Make a Portable Desktop Copy](../paper_monitor/user_guide.html#desktop-copy) | Verify portable paper/folder copies, associated file bundle and no implied whole-library backup. |
| [Back Up or Move to Another Mac](../paper_monitor/user_guide.html#backup-migrate) | Rewrite App/data/source separation, coherent complete-workspace backups, old-source migration, path-aware transfers, startup verification and preserving newer writes before recovery. |
| [My Publications](../paper_monitor/user_guide.html#my-publications) | Verify profile import/resume, identifier completion, manual roles, metrics, shared Files and filtered export scope; linked notice workflow cross-referenced. |
| [Journal Monitor](../paper_monitor/user_guide.html#journal-monitor) | Update Sunday calendar, visible tab counts versus stored sidebar counts, per-paper unread state and filtered left-sidebar Publication updates. |
| [Subject Monitor](../paper_monitor/user_guide.html#subject-monitor) | Update Sunday calendar and shared filtered unread semantics; document notice ingestion separately from the Journal-only notice panel. |
| [Author Monitor](../paper_monitor/user_guide.html#author-monitor) | Verify Hong Ding illustration, New/Read All, Scholar pause, source retries, shared identities and distinct Author read state. |
| [Browse, Bookmark, and Revisit Websites](../paper_monitor/user_guide.html#browser) | Add Browser notice-to-original review/save and manual Key confirmation; retain loaded PDF, Science ePDF, network/access, placement and exact-content reuse behavior. |
| [Literature Data Source](../paper_monitor/user_guide.html#citation-settings) | Verify current Literature Data Source name, optional provider keys, masked credentials and service-specific limits. |
| [arXiv Scope Settings](../paper_monitor/user_guide.html#arxiv-scope-settings) | Verify saved discovery archive scopes are distinct from current report filters. |
| [Field Settings](../paper_monitor/user_guide.html#field-settings) | Add effect of visible fields on tab unread dots and Publication updates, distinct from standalone-field grouping and full journal totals. |
| [Quick Look Settings](../paper_monitor/user_guide.html#quick-look-settings) | Verify three modes and local PDF/Markdown behavior versus all-native Quick Look. |
| [Default Add to Library Folder](../paper_monitor/user_guide.html#add-to-library-settings) | Verify default folder, one-time override, stable folder ID and unsorted fallback. |
| [Website Links](../paper_monitor/user_guide.html#website-link-settings) | Verify native/system website routing and default Save Details preference. |
| [AI Access](../paper_monitor/user_guide.html#ai-access) | Retain Codex/DeepSeek/Claude Code examples; clarify generated paths for source-backed versus standalone installations and existing-connection continuity after migration. |
| [Naming and PDF Rename Rules](../paper_monitor/user_guide.html#naming) | Add extension preservation when long basenames are shortened; retain templates and separate logical identity. |
| [How Gewu Insight Stores Files](../paper_monitor/user_guide.html#storage-model) | Verify canonical main file, Associated Files, Finder aliases, stable identity and collision protection. |
| [Local Data and Privacy](../paper_monitor/user_guide.html#privacy) | Replace project-local file claims with selected workspace storage; preserve API, local access and browser-profile boundaries. |
| [Visual Identity and Cultural Elements](../paper_monitor/user_guide.html#visual-identity) | Retain approved branding, mission, glyph provenance and wording. Preserve continuous Product Identity chapters 4-1 through 4-4. |
| [Keyboard Shortcuts](../paper_monitor/user_guide.html#keyboard) | Add per-paper acknowledgement and visible-only tab indicators; retain contextual Browser, Quick Look and edit shortcuts. |
| [Publisher and Network Access](../paper_monitor/user_guide.html#network-access) | Add off-campus direct-route limits, abstract versus actual PDF entitlement, PDF/CDN routing and native fallback limits. |
| [Startup, Monitor Cache, and Text Size](../paper_monitor/user_guide.html#startup) | Document Applications, first database choice, Database Location, real dialog screenshot, Dock replacement, missing/identity/version/busy checks, pre-schema snapshot and installed log path. |
| [Troubleshooting](../paper_monitor/user_guide.html#troubleshooting) | Add wrong/empty collection diagnosis and explicit database startup failures; correct App entry, log and HTML/PDF edition mismatch advice. |
| [Storage Reference](../paper_monitor/user_guide.html#storage-reference) | Define relative paths under Gewu Database; add config/backups, locator/App/log/default cache paths and distinguish saved AI analyses from legacy reports. |

## Rebuilding and checking the manual

The builder reads the HTML, generates fresh TeX and compiles the PDF with
Pandoc and XeLaTeX. The generated `paper_monitor/user_guide.tex` is an ignored
intermediate, not a required repository input. Do not edit it as a second source.
See [the development guide](DEVELOPMENT.md#builds-and-verification)
for build and verification instructions.

Preserve topic order, numbering, links and approved Product Identity wording.
Chapters 4-1 through 4-4 must flow continuously; that rule belongs in the builder.
Keep the AI Access opening heading, lead, overview image and caption together.
After manual changes, inspect affected PDF pages and check links, destinations,
screenshot fit and the PDF included in the resulting App.

Existing guide, audit, navigation and PDF-structure tests cover these contracts.
Run the checks relevant to the change and report actual results; source tests
do not establish that a rebuilt or installed App was validated. Detailed past
installation logs and superseded validation runs are retained in Git history
and a local development archive, rather than treated as current product state.
