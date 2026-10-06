# User Guide audit — October 6, 2026

## October 6: independent database and current Browser workflow

Audit the existing 49-topic manual against main `31abeec` and this Mac's installed
Applications App after the verified database migration. The current edition is
October 6; the product remains Version 1.0.0 / Build 1. Changes are confined to
manual content, its screenshot/PDF generation, companion documentation and the
existing guide checks. The package builder's Read Me text is updated to stop
calling this the old source-folder manual; its packaging behavior is unchanged.

Corrections:

- Replace the old claim that research data belongs inside the source project.
  Explain the separate App, chosen Gewu Database and optional source checkout.
- Cover Open Existing Database/Create New Database, choosing the enclosing
  workspace, unavailable locations, identity/version/process checks, Database
  Location and Show in Finder. State that this dialog does not move/switch data.
- Explain Applications and Options > Keep in Dock / Remove from Dock. Removing a
  Dock shortcut does not remove the database.
- Rewrite full backup, upgrades, one-time source migration, cross-Mac/path moves
  and recovery. Retain external-link originals and Mac file attributes; distinguish
  a pre-schema SQLite snapshot from a full backup. Preserve new writes before
  rollback, and do not suggest that selecting a moved folder rewrites its paths.
- Correct machine log/cache/locator paths and the role of reports versus AI
  analysis files. Keep source-backed and standalone installation requirements
  explicit without forcing either installation's runtime layout on the other.
- Keep Codex and DeepSeek Harness as examples of one MCP interface, including
  Claude Code and other compatible clients. Clarify generated runtime paths,
  connection retention through migration and read-only reconnection checks.
- Add the existing Browser-only notice workflow: review the resolved original,
  attach the notice under that paper, or select and confirm its existing Gewu Key.
  Normal matching article PDFs can save to their existing paper and placement.
  Shared MCP/Monitor notice rules are not changed by this documentation.
- Retain the accurate APS Harvest/background fallback, publisher access limits,
  PDF-only supplement policy, Refresh Info notices, field-filtered updates and
  visible-only per-paper unread rules from the previous edition.

Evidence includes `workspace.py`, `database_migration.py`, `config.py`,
`GewuDatabaseLocation.h`, native Database Location/startup handlers,
`macos_standalone_entry.py`, `ai_http.py`, and Browser review/save code. The new
Database Location illustration is captured from the installed original App's
actual dialog. The opening Guide is recaptured from its actual separate window.
The other 36 screenshots, including the clean empty Add Monitored Author form,
are retained. No screenshot is painted, synthesized or cropped to hide controls.

Validation completed for the source, installed App and PDF:

- Reviewed all 49 existing topics; changed 11 text topics while preserving their
  anchors and navigation. HTML and generated PDF include the same 38 real-App
  screenshot assets. No new synthetic screenshot replaces a real workflow.
- Generated 132 pages, 1,009 named destinations, 400 internal links and 13
  external links. Every internal target resolves. Visually reviewed all pages
  and 17 affected pages at reading resolution. Found two truncated machine paths
  in the PDF table; replaced that small table with a full-width list and rechecked
  page 130. Only page 130's extracted text changed in the final rebuild.
  Product Identity 4-3 and 4-4 still share page 115.
- All 31 existing Guide/audit/navigation tests and seven PDF structure checks
  pass. The old repository-bundle test uses a temporary fixture pointing to the
  staged Applications App; no App or test data was created inside the checkout.
  Python compilation and `git diff --check` pass.
- Native Help search, first-session instructions, the migration link and Dock
  subsection navigation were checked in the original installed App. The actual
  Database Location dialog shows the selected desktop research folder.
- A staged copy preserves the installed App's private source startup adapter.
  Strict signature verification passes. Only the PDF and signing-related file
  contents change; unsigned native executable bytes match the installed App.
  After normal menu Quit, installed that checked bundle at the existing
  `/Applications/Gewu Insight.app` path and retained the previous App in QA.
- Relaunch reached Library with one healthy backend/listener (48822), unchanged
  database UUID and unchanged location preference. The first startup exceeded
  the native readiness timeout and displayed its existing failure sheet; the
  same backend subsequently became ready and the sheet dismissed automatically.
  This transient startup delay is recorded, not attributed to a confirmed cause
  or claimed repaired. No startup/runtime code was changed for this update.
- The installed App's Help opens the October 6 edition. Native Print Guide opens
  its bundled PDF in Preview, showing Page 1 of 132; native page navigation and
  visual inspection confirm the new Database Location illustration on page 122.
  Installed/built PDF bytes match, all three private startup adapter files are
  unchanged and the running App passes strict signature verification.
- Final PDF SHA-256:
  `85159deb25515da1aa96b7413cd75e69b40bf0ee61ec6a7534011f9edf812812`.
  Working evidence is in `/private/tmp/gewu-guide-oct06/`.
No paper import, classification change, new grant/token, database relocation or
product business-logic change is part of this guide update.

## Previous October 5 evidence

Rechecked all 49 topics against product commit `befa09909e701dcb00acf8fd93b1587f406e934d`, the preserved October 2 guide revision and current runtime source/feature contracts. Checked the original macOS App and the October 4 Science ePDF, WebCrypto and safe-build changes. The manual edition changes; product version remains 1.0.0 / Build 1. This October 5 pass changes documentation and its illustrations/generated resources only. It retains the previous guide navigation and PDF mapping fixes; it does not alter publisher downloads, metadata schedules, MCP permissions or research data.

## AI Access client examples follow-up

After Browser fix commit `50ed1a3`, update only the AI Access topic and its
technical companion, `AI_ACCESS.md`. Present one MCP interface for compatible
local stdio clients, with Codex and DeepSeek Harness as worked examples and
positive configuration guidance for Claude Code and other compatible clients.
Add client-assisted setup, the Desktop Cordis patch, separate connections,
shared read/analysis checks, and an explicitly requested Space/import example.
Keep existing permissions, file-content boundaries and optional-PDF import rules.

Evidence: the user supplied `gewu-mcp-playbook.md`, recording an October 5
DeepSeek Harness connection and read/write workflow. Cross-check the setup
against DeepSeek's official MCP client, Desktop profile and patch-example
references linked in the guide, and Claude Code's official local stdio reference.
Do not publish the playbook's private keys, record IDs, local installation paths
or test data. The guide describes usable workflows rather than test-status labels.
No client configuration, token, permission grant or literature data was changed
for this documentation update.

Validation completed for this follow-up:

- All 48 other HTML topics and all screenshot assets remain unchanged. The
  original App's Help search finds DeepSeek and opens the updated AI Access topic.
- The HTML and Markdown YAML examples are identical; Ruby's YAML parser verifies
  the insertion wrapper, stdio configuration, argument list and token placeholder.
  No new dependency was installed for these checks.
- HTML-derived TeX/PDF builds successfully: 128 pages, 982 destinations, 391
  internal links and 13 external links. Every internal destination resolves.
  Reviewed contents pages 2-6 and affected/repaginated pages 95-128 visually;
  inspected pages 96 and 104-107 at reading resolution. No clipping, overlap or
  malformed configuration indentation found. Identity chapters 4-3 and 4-4
  remain together on page 113.
- All 31 existing Guide/audit/navigation tests and seven PDF structure checks
  pass. The original App's bundled PDF equals the generated source PDF.
- Built and verified a staged universal App; after the user approved restarting,
  installed through the stopped-App build workflow with a recoverable backup.
  An initial quit shortcut did not exit; the installer correctly refused to
  replace the running App. Normal menu Quit then allowed installation. Original
  App relaunched with one backend/listener (4018), health HTTP 200 and a valid
  strict signature. Unsigned executable bytes match the previous App; only the
  PDF and signing-related file contents changed in the bundle.
- Native Print Guide opens the original App's resource PDF in Preview, showing
  Page 1 of 128; native page navigation confirms the DeepSeek example on page 105.
- PDF SHA-256: `72c5c10c4351a9ee1dab7d2758ac9d5c1b0c8cc494bced57c70ead71f71394ca`.
  Backups, build/test logs and rendered checks: `/private/tmp/gewu-guide-mcp-oct05/`.
  The user requested committing and pushing this documentation after validation,
  together with the preceding Browser fix. Unrelated `metadata/` is untouched.

## Earlier October 5 corrections

- Explain Science ePDF original-file capture, Use Loaded PDF, exact-content reuse, the 128 MB limit, stale/incomplete source recovery and fresh-download versus already-loaded access. Distinguish Save Download, Save to Gewu and the research-card Download action.
- Replace obsolete advice to renew permission for the WebCrypto Master Key. Current Browser/background views decline persistent webpage keys; ordinary cryptography, cookies and local storage remain, while older persisted keys are unreadable. Separate this from Passwords/AutoFill and avoid key deletion or profile reset. Align development/distribution documentation with this behavior.
- Expand first-launch requirements, complete-folder installation, coherent backup, source-update versus built-App delivery, stopped-App safe ad-hoc build, verification and rollback. No Apple developer certificate or keychain password is needed for this build.
- Correct the obsolete periodic-refresh claim in `PUBLICATION_UPDATES.md`: saved papers have no active periodic metadata schedule. Manual paper/folder/Library refresh and Journal discovery can find explicit updates; absence of an event does not prove no notice exists.

The following October 2 corrections remain valid after the source audit:

- Document the native background download fallback for APS, ACS, Science and Nature, including the APS Harvest first route, shared Gewu Browser session and unchanged system/VPN routing.
- Separate main-PDF availability from optional supplements. Skip non-PDF material; report access/verification errors without suggesting that videos must become PDFs.
- Explain how Refresh Info finds explicit Crossref notices, how Journal Monitor associates a discovered notice with its original, and why notice metadata need not have a local file. Do not claim continuous retraction monitoring or complete provider coverage.
- Explain per-paper read acknowledgement, visible-only journal/subject dots, hidden unread state, Sunday-first calendars, and filtered Publication updates in the left sidebar.
- Add locally rendered Markdown math, preserved filename extensions and updated troubleshooting. Retain verified metadata-only MCP imports, notice ownership, Default selection and app refresh after external writes.
- Correct the distinction between left Journal Filter totals and filtered top-tab counts, verified in the original App (Nature: 25 total / 6 shown).

- Repair in-guide subsection links: activate their owning topic, keep the correct navigation highlight, clear a hiding search filter and scroll to the requested heading below the sticky toolbar. Cold links and Back/Forward use the same behavior.

## Evidence and boundaries

Read `paper_monitor/user_guide.html`, current `ui_server.py`, `notice_discovery.py`, `metadata_refresh.py`, `markdown_preview_worker.js`, publisher download modules and native App code as needed. Cross-check `MONITOR_DOWNLOADS.md`, `MONITOR_READ_STATE.md`, `METADATA_REFRESH.md`, `AI_ACCESS.md`, identity/storage and browser contracts. The October 2 audit visually reviewed all 36 earlier images. This pass retains 36 accurate illustrations and replaces only the Guide opening with the real October 5 edition. The user explicitly requested retaining the original clean Add Monitored Author form, without the currently active red Scholar cooldown message; no replacement or image retouching is used. Screenshots are real original-App captures with all six main tabs, no generated UI or painted-out controls. See [the screenshot inventory](USER_GUIDE_SCREENSHOTS.md).

The Codex STDIO command/args/env example was checked against [OpenAI's official MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=app) on October 5. No client configuration, access grant or token was changed. No explicit provider refresh, import, download, file classification or literature repair was triggered for this documentation work; existing results and ordinary navigation supply illustrations. Browser website content is illustrative, not evidence that every subscription article is accessible off campus.

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

## Reproducibility and validation

The HTML is the editable source. Build the TeX and fixed-layout PDF with `scripts/build_user_guide_pdf.py`; package that same PDF into the original App. Do not hand-edit generated TeX or create a separate manual text source. Preserve existing topic order, numbering, approved Product Identity wording and its continuous chapter flow. Keep the AI Access opening heading, lead, overview image and caption together.

Earlier October 5 validation, before the AI Access follow-up above. The previous
October 2 work remains included; the checks below describe that 127-page edition.

- Built HTML-derived TeX/PDF successfully: 127 pages, 975 valid destinations, 391 internal links and nine external link annotations. Every internal target resolves; HTML has 49 topics, no duplicate IDs and no broken nonempty fragment links.
- Visually reviewed all 127 pages in contact sheets and 15 pages at reading resolution: 14, 61, 62, 74, 81, 82, 85, 86, 95, 104, 108, 112, 118, 124 and 125. No clipping, overlap or missing text found in this review. Product Identity 4-3 and 4-4 still share page 112; the AI Access heading, lead, overview and caption remain together on page 95.
- All 31 existing Guide/audit/navigation unittest checks passed (30 before installation and the bundle/source equality check afterward); seven PDF builder structure checks passed. Navigation checks execute the shipped JavaScript against all real topics and links. Python compilation and whitespace checks passed. No runtime benchmark was changed or run.
- Original clean Add Monitored Author PNG is byte-identical to the pre-edit backup, as explicitly requested. PDF page 74 confirms the ordinary empty form without a red Scholar message. Only the Guide opening was recaptured in this pass, from the original App in native fullscreen without an overlay.
- Built and strictly verified a staged universal App, then installed through the stopped-App build workflow after the user explicitly approved restarting. Initial installed-build preflight could not read process state in the sandbox; the authorized rerun completed. The regenerated iconset was rejected in the isolated stage, so the builder retained the existing icon; the installed build completed with its normal deprecated WebKit enum warning. No source workaround or certificate change was made.
- Original App reopened as PID 31583 with one local listener (31585). Help > User Guide displays October 5; native search for Science ePDF finds Browser and Troubleshooting, and the new repeated-keychain subsection link opens the expected section. Print Guide opens the exact bundled PDF in macOS Preview, visibly showing Page 1 of 127 and its original-App resource path. The PDF source and bundle match. Strict signature verification passes after launch; unsigned executable payloads match the pre-edit App.
- PDF SHA-256: `9a8fc570261d380d7f9f0771187307fee055c3031968d68c17389fa1eb179f75`. Reversible pre-edit App/guide backups, build/test logs, rendered pages and package checks: `/private/tmp/gewu-guide-oct05-zb6szif9/`.
- No direct literature edits, imports, provider refreshes, classification changes or data migration were performed for the manual; normal App startup/background operation is separate from this documentation check. No commit, push, branch or PR; unrelated `metadata/` remains untouched.
