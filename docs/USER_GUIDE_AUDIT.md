# User Guide audit — September 6, 2026

## Scope and method

Reviewed all 46 registered in-app topics, their navigation and cross-links,
the seven existing workspace illustrations, the PDF builder, and the guide's
packaging/serving paths. Compared the current implementation and product tests
with the comprehensive-guide baseline `23768f0`, the subsequent file/settings/
monitor/startup changes, and Browser commits `6ce13bc` and `0fd77e9`. This edition
also describes the uncommitted five-workspace website-routing change documented
in [Workspace Browser links](WORKSPACE_BROWSER_LINKS.md).

This is a documentation audit, not a new end-to-end certification of every
publisher, account, downloader, or migration. A reviewed topic without a text
change means its documented contract still matches the inspected code/tests;
it does not mean a live network operation was repeated on personal data.

## Corrections and additions

- Distinguish five research views from the sixth Browser workspace and its
  isolated WebKit session; visits/downloads are not automatic paper imports.
- Replace retired attachment roles with the actual File type choices; explain
  the compact card footer before Annotation/Source edits.
- Correct My Publications' **Find Profile**, its Files panel location, and the
  Overleaf ZIP/manual-import boundary.
- Explain the protected physical primary file separately from the preferred
  Default. Changing a reading preference is not a deletion bypass.
- Complete Browser coverage: warm versus cold Home, transition behavior,
  right-column rectangular tabs, local address-history suggestions, bookmark
  transfer, inline PDF/download boundaries, and explicit Safari fallback.
- Correct context-dependent Command-W/Command-L/Command-F and add Command-T,
  quit/draft warnings, and monitor keyboard navigation.
- Add local automatic-update timing, recovery limitations, cache distinctions,
  and Browser-specific troubleshooting without promising credential filling.
- Explain SQLite/API-key backup sensitivity, Browser profile versus project
  backup, and Apple Passwords/passkey ownership.
- Document per-service Save/Test/Clear and the implemented OpenAlex free-only
  policy; do not hard-code transient remaining quotas or service guarantees.
- In the PDF, present related-topic links as compact navigation instead of
  numbered sections/TOC entries. Reserve more space for headings and their
  opening text; tighten the repetitive Guided Tour state paragraph to avoid
  a page containing only its related links. All link targets remain intact.

## Complete topic inventory

Evidence names below refer to the current implementation or product tests;
`ui_server.py` and `storage.py` are under `paper_monitor/`, native sources under
`scripts/`. Each entry links to the preserved topic anchor in the HTML source.

| Topic | Audit result / implementation evidence |
|---|---|
| [Welcome](../paper_monitor/user_guide.html#welcome) | Correct research-view count; add edition date. Main view switcher and guide routes. |
| [Guided Tour](../paper_monitor/user_guide.html#guided-tour) | Add Browser to six-mode orientation; retain independent-pane grammar. `browser_ui.css`, navigation tests. |
| [Your First Session](../paper_monitor/user_guide.html#first-session) | Retain import, placement, evidence, classification, and shared-key walkthrough; `test_library_add_targets.py`, resource tests. |
| [System Architecture](../paper_monitor/user_guide.html#system-overview) | Add direct WebKit surface, isolated bridge, SQLite/profile boundaries; `GewuBrowserController.m`, native navigation guards. |
| [Persistent Paper Object](../paper_monitor/user_guide.html#persistent-paper-object) | Retain canonical identities, metadata-only records and provenance; `storage.py`, identity/provenance tests. |
| [SQLite Core](../paper_monitor/user_guide.html#sqlite-core) | Include Browser bookmarks/history in operational memory; `browser_store.py`. |
| [Visible Research Files](../paper_monitor/user_guide.html#visible-research-files) | Retain physical-primary versus preferred resource, fingerprints, metadata-only changes; resource and file-operation tests. |
| [Personal Research Workspace](../paper_monitor/user_guide.html#personal-research-workspace) | Replace obsolete five-top-level claim with five research views plus Browser. |
| [Research Loop](../paper_monitor/user_guide.html#research-loop) | Retain discovery/import/resolve/read/revisit lifecycle; model and provenance tests. |
| [State and Scope](../paper_monitor/user_guide.html#state-and-scope) | Retain distinct successful-empty, incomplete and failed states; monitor state tests. |
| [Library Layout](../paper_monitor/user_guide.html#library-layout) | Existing compact Paper Files/current details image remains applicable; layout/navigation tests. |
| [Navigation](../paper_monitor/user_guide.html#navigation) | Retain row/default double-click, rail focus, Quick Look and independent scroll; navigation/interactions tests. |
| [Folders, Shortcuts, Spaces](../paper_monitor/user_guide.html#organize) | Retain shared placement, copies/moves, independent Space roots and protected relationships; file-operation tests. |
| [Search and Views](../paper_monitor/user_guide.html#search-views) | Retain scoped search and List/Table behavior; `currentSurfaceSearchScope`, search/view handlers. |
| [Add Papers and Files](../paper_monitor/user_guide.html#import-files) | Retain metadata-only and file-backed routes; `test_library_add_targets.py`, ingress tests. |
| [Paper Details](../paper_monitor/user_guide.html#paper-details) | Retain aligned author details, visible undefined key, Library's removed duplicate Files panel; details tests. Web links now Browser. |
| [Identifiers](../paper_monitor/user_guide.html#identifiers) | Retain explicit DOI/arXiv editing, refresh and source actions; metadata tests, identifier-control handlers. |
| [Paper Files](../paper_monitor/user_guide.html#paper-files) | Retain independently collapsed metadata, size-footer edge, default/physical-primary guard and native local-file opening. |
| [Quick Look](../paper_monitor/user_guide.html#quick-look) | Retain on-demand native preview and temporary thumbnails; Quick Look settings/performance tests. |
| [File Types and Default](../paper_monitor/user_guide.html#versions-current) | Explain footer expansion; all ten labels checked against `paperFileRoleOptions` and `PAPER_FILE_TYPES`. |
| [Attachments](../paper_monitor/user_guide.html#attachments) | Retain import-first/classify-later, independent metadata and add-file flow; resource/ingress tests. |
| [Download and Sync](../paper_monitor/user_guide.html#download-sync) | Retain arXiv revisions, PDF validation, atomic saves and duplicate/annotation boundaries; PDF ingress/fingerprint tests. |
| [Standalone File Adoption](../paper_monitor/user_guide.html#drag-attach) | Remove retired Image/Data/Code role choices; use Other/Supplementary material. Adoption rollback tests. |
| [Delete and Recover](../paper_monitor/user_guide.html#recycle) | Retain reference-aware Recycle and macOS Trash behavior; file-operation and resource tests. |
| [Folder Loader](../paper_monitor/user_guide.html#folder-loader) | Qualify Command-L outside Browser; retain source, metadata modes and resumable/logged import. Inventory importer tests. |
| [Loader Maintenance](../paper_monitor/user_guide.html#loader-maintenance) | Retain refresh/identifier retry and stop/log semantics; Loader handlers and importer tests. |
| [Desktop Copy](../paper_monitor/user_guide.html#desktop-copy) | Retain real-file export and verified manifest; desktop-copy/file-operation tests. |
| [Backup and Migration](../paper_monitor/user_guide.html#backup-migrate) | Clarify quit versus close, database/file consistency, Browser profile exclusion and API-key sensitivity. |
| [My Publications](../paper_monitor/user_guide.html#my-publications) | Fix Find Profile; describe Files · n, Browser profile link and manual Overleaf ZIP upload. Publication/export handlers. |
| [Journal Monitor](../paper_monitor/user_guide.html#journal-monitor) | Retain Nature example, counts independent of filters, subscriptions, provenance, figures and Add/Show Library; add scheduler boundary. |
| [Subject Monitor](../paper_monitor/user_guide.html#subject-monitor) | Retain keyword groups, matching scores, saved results after Library add, superscript incomplete marker and Zenodo exclusion; theme/UI tests. |
| [Author Monitor](../paper_monitor/user_guide.html#author-monitor) | Retain Hong Ding example, profile matching, New/Read All scope and aligned details; author/read-all/details tests. |
| [Browser](../paper_monitor/user_guide.html#browser) | Expand current navigation, tabs, history suggestions, lifecycle and credential limits; Browser store/native/policy/layout tests. |
| [Open Source Settings](../paper_monitor/user_guide.html#citation-settings) | Preserve old anchor for links; complete Save/Test/Clear, masks/Show, status and free-only budget behavior. Source settings tests. |
| [arXiv Scopes](../paper_monitor/user_guide.html#arxiv-scope-settings) | Retain multi-archive discovery versus display filters, defaults and saved-paper preservation; arXiv scope/schedule tests. |
| [Field Settings](../paper_monitor/user_guide.html#field-settings) | Retain canonical fields versus visible grouping and Restore Defaults; field settings tests. |
| [Quick Look Settings](../paper_monitor/user_guide.html#quick-look-settings) | Retain page width/actual size/fit behavior; native PDF preview/settings tests. |
| [Naming](../paper_monitor/user_guide.html#naming) | Token list checked against `PDF_RENAME_TEMPLATE_TOKENS`; display rule and PDF template remain distinct. Rename UI tests. |
| [Storage Model](../paper_monitor/user_guide.html#storage-model) | Retain managed roots, associated bundles and identity independent of filenames; storage/file-operation tests. |
| [Privacy](../paper_monitor/user_guide.html#privacy) | Retain local-first, network access, private exports and credentials; Browser/profile details cross-referenced. |
| [Visual Identity](../paper_monitor/user_guide.html#visual-identity) | Retain supplied branding, cultural interpretation and exact provenance links; identity/asset guide tests. No new licensing assertion. |
| [Keyboard](../paper_monitor/user_guide.html#keyboard) | Correct Browser/window/Quick Look contexts; add tab and monitor navigation. Native key monitor and UI keyboard handlers. |
| [Network Access](../paper_monitor/user_guide.html#network-access) | Retain direct WebKit versus Python requests, actual Clash routing verification and access-control limits. No speed/parity guarantee. |
| [Startup and Cache](../paper_monitor/user_guide.html#startup) | Add local schedule, memory-only Browser recovery loss and Monitor Cache versus history distinction; scheduler/native recovery tests. |
| [Troubleshooting](../paper_monitor/user_guide.html#troubleshooting) | Correct deletion and retry advice; add Browser routing/Home/sign-in/AutoFill cases without causal overclaims. |
| [Storage Reference](../paper_monitor/user_guide.html#storage-reference) | Add Browser SQLite state, external OS profile/cache and backup sensitivity; storage/browser store/controller. |

## Illustration provenance

Inspected all seven existing workspace images. Library, Space, My Publications,
Journal Monitor, Subject Monitor, and Author Monitor remain useful as examples
of the current layout. Counts, dates, and remote metrics are historical examples,
not current service statistics. Journal Monitor deliberately retains the user's
Nature page dated August 12, 2026; Author Monitor retains Hong Ding.

Replaced the obsolete Browser image (old Favorites heading/folder selector,
no webpage tabs) using `scripts/render_browser_guide_example.cjs`. It renders
the actual current `browser_ui.css` and `browser_ui.js` with generated public
bookmarks in a fresh headless profile, blocking all network requests. The native
webpage area is explicitly a labeled placeholder, not a live Google screenshot.
No personal bookmarks, history, credentials, or live App window were read for
this replacement. The guide caption and alt text preserve that distinction.

## Edition and verification

HTML is the single source; `scripts/build_user_guide_pdf.py` regenerates both
LaTeX and PDF. The App packages the same PDF; `/user-guide` reads current HTML
without requiring an App rebuild. The audit adds regression tests tied to actual
file-type values, UI button labels, shortcut contexts, schedule constants, and
privacy boundaries. Final build/render/packaging results are recorded below.

Comprehensive-audit baseline validation on September 6, 2026 (before the
workspace-return shortcut follow-up below):

- All **711 product tests passed** (31.422 seconds), including six new audit
  regressions. Four PDF structure checks passed separately. Tests used temporary
  data; no formal research database was changed. Malformed-PDF fixture diagnostics
  and the existing LibreSSL warning were non-failing test output.
- All 46 HTML topics passed interactive navigation and horizontal-overflow checks
  at 1280- and 800-pixel widths; guide search and representative page layouts were
  checked in an isolated headless browser with nonlocal network access blocked.
- The regenerated PDF has **77 pages**. Every page was rendered and visually
  reviewed, with closer checks of revised Browser and keyboard pages. Compact
  related-topic links no longer create numbered contents entries or a standalone
  Guided Tour tail page. All 690 named destinations and 299 link annotations were
  inspected: no broken internal targets or text outside printable margins.
- The universal original App was rebuilt without launching it. Signature
  verification passed, and its bundled PDF is byte-identical to the source PDF
  (SHA-256 `f83e786702f8cfb0be32445278714fb5005755c4d3e6043d1fac9c2f5dda3f0a`).
  Existing deprecated-AppKit/WebKit warnings and the existing-icon fallback were
  non-failing build output.
- The running local service returned the current HTML and PDF with matching
  hashes; `/api/health` returned `{"ok": true}`. Reopening Help > User Guide reads
  the revised guide without restarting the App. Python compile, JavaScript syntax
  and `git diff --check` passed.

This documentation audit did not restart the App, operate accounts or Passwords,
read a live private Browser window, change the formal database, commit, or push.
Earlier uncommitted workspace-to-Browser routing changes were preserved; their
native runtime activation still requires the separately pending safe restart.
Document checks do not certify current publisher access, institutional routing,
or successful credential filling.

## Workspace-return shortcut follow-up

The Browser instructions and keyboard table now document **Command-left bracket
(⌘[)**: return from a research-workspace website link to its source, retaining
selection, viewport, and Browser tabs. The detailed instructions distinguish
this from webpage Back, direct Browser entry, and manual workspace changes.

All 713 product tests passed (31.755 seconds), including native key-boundary
checks and source-return state regressions; four PDF structure checks passed.
The isolated headless probe executes the actual Browser chrome and primary-view
switcher: all five source views return, original DOM survives, focus and both
scroll axes are restored, and no webpage load/close/history traversal is issued.
All 46 HTML topics passed navigation/layout checks at two widths. After the final
shortcut-table wording adjustment, all six guide-audit tests passed again.

HTML, generated LaTeX, and the **78-page PDF** are synchronized. Revised Browser
and keyboard pages were rendered and visually checked; all 299 PDF links and
691 named destinations were checked, with no broken internal links. The rebuilt
original universal App's bundled PDF matches the source (SHA-256
`8eb854a0013dffc53f825f4487aa8f838f87c041a492e09db108c9f3a0a358cc`).
The App has not been restarted; safe restart approval is pending. No live account,
Password, research database, or benchmark operation was used to test the shortcut.
There was no commit or push. The native keyboard shortcut is not claimed active
in the older running App process.

## Keeping the next edition aligned

For a future feature change, check the matching topic and its cross-links as
well as visible labels, shortcuts, persistence/deletion behavior, and failure
states. Update relevant illustrations only with explicitly safe example data.
Regenerate the PDF from HTML, inspect changed pages, run guide tests and PDF
structure checks, then package and compare the App's PDF with the source PDF.
Do not describe a planned or unverified integration as a supported feature.
