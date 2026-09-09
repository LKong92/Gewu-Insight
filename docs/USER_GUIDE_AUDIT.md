# User Guide audit — September 6, 2026

## Scope and method

Re-audited all 47 registered in-app topics against product checkpoint
`f3fe6fc` (retained startup fix) and `7a6f703` (Website Links and the restored
PDF preview). Read the complete topic contents and compared them with native
menus, the actual UI handlers, settings persistence, file-resource controls,
publication export selection, citation aggregation, and the HTML-to-PDF builder.
The original App's Setting/PDF Rename and Author Monitor menus were also checked.
The seven existing illustrations remain real original-App captures; the discarded
iframe-transition and PDF.js experiments are not part of this guide or product.

This is a documentation audit, not a new end-to-end certification of every
publisher, account, downloader, or migration. A reviewed topic without a text
change means its documented contract still matches the inspected code/tests;
it does not mean a live network operation was repeated on personal data.

## September 7 Browser capture update

The Browser chapter now covers Save to Gewu, the Monitor-style hierarchical
destination picker, Show in Library, main-PDF placement and preview, and
publisher versus preprint file-type suggestions. Source follows the bound PDF
host independently of File type; local imports borrow no webpage provenance.
Duplicate resources retain their existing source and manual settings. Safari
extension packaging remains explicitly outside the implemented feature.
Both Guide editions share the revised HTML and show the September 7 revision.
The compact-dialog follow-up adds collapsed Details, the Website Links default,
and visible failure/identity-repair behavior; existing classification, destination
selection and Show in Library instructions remain current.
The earlier full 47-topic audit below remains the baseline; this follow-up is
scoped to the Browser workflow, not another complete live feature audit.

## September 6 re-audit corrections

- Make Journal, My Publications, Browser, Overleaf and Website Links agree on
  built-in versus system-default routing; direct Browser navigation is separate.
- Correct startup order: the opaque branded native view is installed before the
  window is shown, then fades when Library is ready.
- Remove unverified PDF speed claims. Document the existing switching flash,
  native Quick Look choice, Save/Restore Default behavior, reader controls,
  200-page button/160-image limits, other formats and truncated text previews.
- Explain Library's folder Color, Add to My Publications, Remove Shortcut,
  Remove Empty Space and Table View's unavailability during active search.
- Identify blank-space Paper Files menus for Add File/Sync Versions separately
  from card menus. Distinguish Library's expandable card footer from the always
  visible metadata controls inside My Publications' expanded Files panel.
- Document My Publications' Manual Metadata/Save Metadata and per-author marks.
  Exports follow visible filtered/sorted rows and omit Hide entries; Overleaf ZIP
  is copied to Desktop and uploaded manually by the user.
- Correct citation sources: saved Google Scholar counts are supported; PubMed
  is indexing data. Source buttons select saved totals, while the histogram
  remains OpenAlex. Explain that merged totals are estimates across versions,
  not a proven globally deduplicated citing-paper count.
- Add Author Monitor's Date/Citations sorting, Conferences popover, single-author
  refresh, single-paper/author missing-identifier lookups, exact full-Scholar
  refresh entry point and Remove from Monitor label.
- Describe Note's independent scroll, divider, Hide list/Show list and the
  difference between closing a drawer and deleting its saved note.
- Clarify settings persistence individually: Field/Quick Look/PDF Rename defaults
  save immediately; Font Size defaults are preview-only until Save; arXiv defaults
  also still require Save. Naming Rule affects new unnamed placements and does
  not bulk-rename existing PDFs; PDF template Save and batch application differ.
- Explain Print Guide: the complete packaged PDF opens in Preview, not just the
  current topic; the browser-hosted guide opens the PDF in a browser tab.

The 47-topic anchors and seven original screenshots are preserved. Product
Identity chapters 4-1 through 4-4 retain their continuous flow in the builder.
This audit changes documentation only and does not attempt another PDF renderer.

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
| [Folders, Shortcuts, Spaces](../paper_monitor/user_guide.html#organize) | Add folder Color, Remove Shortcut/Empty Space and Add to My Publications; shared placement/file-operation handlers. |
| [Search and Views](../paper_monitor/user_guide.html#search-views) | Clarify that active Library search disables Table View; `currentSurfaceSearchScope`, search/view handlers. |
| [Add Papers and Files](../paper_monitor/user_guide.html#import-files) | Retain metadata-only and file-backed routes; `test_library_add_targets.py`, ingress tests. |
| [Paper Details](../paper_monitor/user_guide.html#paper-details) | Correct citation sources, version-aware estimate and OpenAlex histogram; `citation_metrics`, `wireCitationSourceSelector`. Retain metadata/key/file distinctions and Website Links routing. |
| [Identifiers](../paper_monitor/user_guide.html#identifiers) | Retain explicit DOI/arXiv editing, refresh and source actions; metadata tests, identifier-control handlers. |
| [Paper Files](../paper_monitor/user_guide.html#paper-files) | Retain independently collapsed metadata, size-footer edge, default/physical-primary guard and native local-file opening. |
| [Quick Look](../paper_monitor/user_guide.html#quick-look) | Restored embedded viewer, real load/paint distinction, native alternative, controls and bounded thumbnail/text display; `renderLibraryQuickLookPages`, `renderLibraryQuickLookThumbs`, native magnification. |
| [File Types and Default](../paper_monitor/user_guide.html#versions-current) | Explain footer expansion; all ten labels checked against `paperFileRoleOptions` and `PAPER_FILE_TYPES`. |
| [Attachments](../paper_monitor/user_guide.html#attachments) | Retain import-first/classify-later, independent metadata and add-file flow; resource/ingress tests. |
| [Download and Sync](../paper_monitor/user_guide.html#download-sync) | Retain arXiv revisions, PDF validation, atomic saves and duplicate/annotation boundaries; PDF ingress/fingerprint tests. |
| [Standalone File Adoption](../paper_monitor/user_guide.html#drag-attach) | Remove retired Image/Data/Code role choices; use Other/Supplementary material. Adoption rollback tests. |
| [Delete and Recover](../paper_monitor/user_guide.html#recycle) | Retain reference-aware Recycle and macOS Trash behavior; file-operation and resource tests. |
| [Folder Loader](../paper_monitor/user_guide.html#folder-loader) | Qualify Command-L outside Browser; retain source, metadata modes and resumable/logged import. Inventory importer tests. |
| [Loader Maintenance](../paper_monitor/user_guide.html#loader-maintenance) | Retain refresh/identifier retry and stop/log semantics; Loader handlers and importer tests. |
| [Desktop Copy](../paper_monitor/user_guide.html#desktop-copy) | Retain real-file export and verified manifest; desktop-copy/file-operation tests. |
| [Backup and Migration](../paper_monitor/user_guide.html#backup-migrate) | Clarify quit versus close, database/file consistency, Browser profile exclusion and API-key sensitivity. |
| [My Publications](../paper_monitor/user_guide.html#my-publications) | Find Profile, Manual Metadata, individual author marks, Files controls, Library add, visible-row export scope and Desktop Overleaf ZIP; publication/render/export handlers. |
| [Journal Monitor](../paper_monitor/user_guide.html#journal-monitor) | Retain Nature example, counts, subscriptions and provenance; clarify Website Links, Refresh This Journal and Note drawer controls. |
| [Subject Monitor](../paper_monitor/user_guide.html#subject-monitor) | Retain keyword groups, matching scores, saved results after Library add, numeric calendar counts and Zenodo exclusion; theme/UI tests. |
| [Author Monitor](../paper_monitor/user_guide.html#author-monitor) | Retain Hong Ding, profile matching and New/Read All; add Date/Citations, Conferences, author/identifier refresh and exact profile menu labels. |
| [Browser](../paper_monitor/user_guide.html#browser) | Expand current navigation, tabs, history suggestions, lifecycle and credential limits; Browser store/native/policy/layout tests. |
| [Open Source Settings](../paper_monitor/user_guide.html#citation-settings) | Preserve old anchor for links; complete Save/Test/Clear, masks/Show, status and free-only budget behavior. Source settings tests. |
| [arXiv Scopes](../paper_monitor/user_guide.html#arxiv-scope-settings) | Retain multi-archive discovery versus display filters, defaults and saved-paper preservation; arXiv scope/schedule tests. |
| [Field Settings](../paper_monitor/user_guide.html#field-settings) | Clarify Save, unsaved close and immediate Restore Defaults; preserve canonical classification versus visible grouping. |
| [Quick Look Settings](../paper_monitor/user_guide.html#quick-look-settings) | Three mode labels, Save/unsaved-close and immediate Restore Default; `saveQuickLookSettings`, `resetQuickLookSettings`, shared preview routing. |
| [Website Links](../paper_monitor/user_guide.html#website-link-settings) | Built-in default or macOS default browser; Save, unsaved close, Restore Default, persistence, research-link scope, Preview/Finder and Browser exceptions. |
| [AI Access](../paper_monitor/user_guide.html#ai-access) | Default-off local API and MCP; Codex STDIO fields, explicit environment rows, path placeholders, TOML and verification prompts; connection collection, permissions, expiry and revoke; file reads, append-only Markdown analysis, provenance, limits and the filesystem permission boundary. |
| [Naming](../paper_monitor/user_guide.html#naming) | New unnamed placements versus explicit file rename; tokens, sample, Save/Default and batch rename checked against native menu, settings and rename handlers. |
| [Storage Model](../paper_monitor/user_guide.html#storage-model) | Retain managed roots, associated bundles and identity independent of filenames; storage/file-operation tests. |
| [Privacy](../paper_monitor/user_guide.html#privacy) | Retain local-first, network access, private exports and credentials; Browser/profile details cross-referenced. |
| [Visual Identity](../paper_monitor/user_guide.html#visual-identity) | Retain supplied branding, cultural interpretation and exact provenance links; identity/asset guide tests. No new licensing assertion. |
| [Keyboard](../paper_monitor/user_guide.html#keyboard) | Correct Browser/window/Quick Look contexts; add tab and monitor navigation. Native key monitor and UI keyboard handlers. |
| [Network Access](../paper_monitor/user_guide.html#network-access) | Retain direct WebKit versus Python requests, actual Clash routing verification and access-control limits. No speed/parity guarantee. |
| [Startup and Cache](../paper_monitor/user_guide.html#startup) | Correct native first-frame startup order and Font Size Restore Default/Save; retain schedule, recovery and cache/history distinctions. |
| [Troubleshooting](../paper_monitor/user_guide.html#troubleshooting) | Correct deletion and retry advice; add Browser routing/Home/sign-in/AutoFill cases without causal overclaims. |
| [Storage Reference](../paper_monitor/user_guide.html#storage-reference) | Add Browser SQLite state, external OS profile/cache and backup sensitivity; storage/browser store/controller. |

## Illustration provenance

The user's latest screenshot requirements supersede the initial synthetic
Browser illustration. All User Guide images must be real original-App captures,
without Computer Use pointers or other overlay windows. Never invent bookmark
collections or change paper-file classifications just to stage an illustration.
The synthetic layout renderer now writes only to a temporary example file, not
to the guide assets. Counts and remote metrics remain dated examples.

Current refresh status:

| Image | Real source and review status |
|---|---|
| Browser | Original App showing Nature research articles with the actual bookmark tree filtered to Nature and real site icons. Native window-only capture excludes the Computer Use pointer. Replaces the rejected synthetic image. |
| Library | Fermi-level flat band in a Kagome magnet, arxiv_1906.07140. Two existing files are Preprint and Published version; the latter is Default. No types were changed. Native window-only capture is pointer-free. |
| Author Monitor | Newly captured with Hong Ding selected. Reviewed without pointer overlay. |
| Journal Monitor | Newly captured on August 12, 2026 with Nature selected and article figures visible. Reviewed without pointer overlay. |
| My Publications | Existing real App capture reviewed; no pointer found. |
| Subject Monitor | Recaptured September 9, 2026 from the original App, matching the user's view: August 2026 calendar, September 2 results, Superconductivity selected (16 shown / 40 visible), beginning with the Ising-superconductor diode paper. Numeric counts, with no asterisk or legend. Native window-content capture excludes the title bar and contains no pointer, Computer Use badge, or sharing overlay. |
| Space | Newly captured from the original Tobit Space with Single-shot parity readout of a minimal Kitaev chain selected and Paper Files visible. Window-only capture is pointer-free. |

The original App became responsive after the intervening system WebCrypto
keychain wait. Both remaining photos were recaptured and reviewed, and final
packaging is complete. No keychain authorization or credential was operated;
only ordinary workspace selection was used to frame the screenshots.

## September 6 functional re-audit verification

- All 26 existing User Guide unit tests pass; six PDF hierarchy/identity/link
  structure checks pass. The PDF builder compiles and `git diff --check` passes.
- An isolated browser opened every one of the 47 topics at 1280 and 800 px,
  with one active topic, no horizontal overflow, no missing images and no script
  errors. Five newly documented operations are searchable. Native whole-guide
  PDF dispatch and the browser-hosted PDF link both pass. No external requests
  or formal profile/database operations were used for this probe.
- The generated PDF contains 77 pages, 711 named destinations and 314 links,
  with no broken internal targets or text outside the checked page margins.
  All 77 pages were rendered with system Poppler and visually reviewed; Chinese
  glyphs, screenshots, tables and links are present. The initial bundled Poppler
  lacked Chinese CMaps; system Poppler rendered without warnings.
- Compact TOC spacing is scoped to the contents list in the builder. Author
  prose and the keyboard reference were tightened to remove short tail pages;
  Field Settings' related links now stay with its explanation. Product Identity
  4-1/4-2 share page 67 and 4-3/4-4 share page 68, with numbering preserved.
- PDF SHA-256: `1e422c74d133b9331420201f0857d0f3e07afa8aeaf6fc78538bb56eb0b81747`.
- Original and worktree universal App bundles were rebuilt and pass strict
  signature verification. The source, HTTP-served and both bundled PDFs have
  the SHA-256 above; the served HTML matches the edited source byte for byte.
  The original App's Help > User Guide displays the September 6 Functional
  review edition. The service reports healthy; no restart was performed for
  this documentation update.
- Live native Print Guide clicking could not be completed: Computer Use
  returned `AXError.apiDisabled` after the guide window opened. The actual
  guide was visually inspected, and the isolated native-dispatch/browser-link
  checks pass, but opening this edition in Preview through the live button is
  not claimed. No accessibility/security setting was changed.
- The startup-only commit `f3fe6fc` was created before this audit as requested.
  The user subsequently requested committing these guide/build/package changes
  and pushing both this revision and the startup commit to `origin/main`.
  Prior guide/App backup: `/private/tmp/gewu-guide-reaudit/before-original-guide-and-app.tgz`.

The sections below document prior editions; their page counts and hashes are
historical, not claims about the current re-audit output.

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

## Compact search and localized shortcut follow-up

The Guided Tour now explains the compact, flat top-right search field and
per-workspace queries. Browser documents the physical left-bracket key under
Chinese input methods. HTML, generated LaTeX, and the 78-page PDF are aligned;
pages 11-13 and 55-58 were rendered and inspected with no clipping or unwanted
extra tail page. The rebuilt original App's PDF matches the source (SHA-256
`83f4cc2d145f6ea40a1fa95d55699fdc253f48c0d9a252c2b6a9a65d880ab8f8`).

The pre-fix original App was already running the previous shortcut build
(PID 30014, started 07:17 on 2026-09-06). An Author Monitor public article link
and Command-left bracket reproduced the non-return; the selected input method
was Chinese Pinyin. The ASCII-only matcher had no physical-key fallback. It now
accepts that key without weakening modifier, sheet, window or source checks.
The exact cause of that live failure and the final original-App outcome still
require the user-approved restart/retest; the input-method fix alone is not
presented as proof that the reported failure is resolved.

All 714 final product tests pass (31.539 seconds), after updating the legacy
Guided Tour phrase assertions to the equivalent compact wording. Isolated
five-workspace DOM return checks and 25 real WebKit/
AppKit checks pass. The latter include English and full-width bracket events
dispatched through the installed monitor from both webpage and workspace focus.
Search layout checks cover five surfaces, three widths and five font scales.
The final six guide-audit tests and four PDF structure checks pass. No credential
operation, direct research-data change, benchmark work, commit or push is part
of this follow-up. The original App has been rebuilt but not restarted while
the user's save-drafts confirmation is pending.

## Favorites-only local Home follow-up

The user's subsequent Home request supersedes the Google-Home descriptions and
illustration in the earlier audit stages above. Home now renders the canonical
Favorites folder in the entire local main column. It does not load a Google
document, including on first use or after restarting; the address field retains
Google search and local history completion. Reload on Home refreshes bookmarks.
Favicons can still need bounded network requests and have local fallback initials.
Explicit google.com navigation remains an ordinary webpage, with no Home-specific
style injection or zoom. Existing password, profile and network behavior is unchanged.

README, Browser instructions, troubleshooting, the public synthetic illustration,
generated LaTeX and the 78-page PDF are synchronized. Revised PDF pages 55-58 and
76 were rendered and inspected. Source and packaged PDF SHA-256 both equal
`dcd7dbcd31892ff3df4b45ad2531d2cef2838316ec1e2d8a7cbc9db568ec91dc`.

All 714 final product tests pass (32.228 seconds); an earlier run failed two
obsolete Google-Home documentation assertions, which now guard the new behavior.
The four PDF structure checks pass. The independent real WebKit fixtures pass
12 Home-transition checks and 25 tab/shortcut checks, with zero live website or
credential requests. The headless layout fixture covers four window sizes,
complete Favorites paging, aligned footers, ordinary Google pages, address search,
and local-Home chrome. Five-workspace retained-DOM return checks also pass.

The original universal App is rebuilt and its signature verifies. Live relaunch
and the reported source-return shortcut remain pending saved-drafts approval;
the synthetic shortcut checks do not establish the original-App result. No
credentials, direct formal database changes, benchmark work, commit or push.

## Embedded child-document compatibility follow-up

Checkpoint `8adfec8` committed and pushed the preceding Home/search/guide work
before the APS fix. The next guide revision adds the standard child-document
security boundary and publisher verification-loop troubleshooting, without
promising universal browser acceptance or credential filling.

HTML, generated LaTeX and the 78-page PDF are synchronized. Pages 57-58 and
76-78 were rendered and visually checked. Four PDF structure checks and all
714 product tests pass (31.667 seconds). Source and packaged PDF SHA-256:
`29d9db9e40b26b76267d65292850288b8fa28c023c4c99c0f0800b55dde74457`.
The original universal App was rebuilt and restarted with saved-drafts approval;
health and signature checks pass. The user's exact PRX recent-articles URL
opened successfully without operating the verification widget or credentials.
No private screenshot was saved or used for the guide. The user authorized
publication after validation. See `BROWSER_EMBEDDED_COMPATIBILITY.md` for evidence
and limits.

## Browser controls and real-image refresh

The guide now documents the compact B menu, manual one-way selected-folder
Safari/Chrome sync, and directional Browser navigation with input/widget and
hidden-sidebar boundaries. The original App is rebuilt and running the feature
code; 727 product tests and 18 isolated real-WebKit arrow checks pass. Live
toolbar/Favorites/sidebar and B-menu checks succeeded before the unrelated
system keychain wait. See `BROWSER_KEYBOARD_AND_BOOKMARK_SYNC.md` for scope and
validation limits.

HTML, LaTeX and the final 77-page PDF include all six replacement images; the
clean real My Publications capture is retained. Revised Library page 31,
Space page 33, Subject page 51 and Browser page 55 were rendered and visually
checked. All guide images are original-App captures without Computer Use
overlays. No commit or push.

## Continuous Product Identity layout

The user's standing layout rule is now recorded in AGENTS.md and implemented
in the PDF builder: short Product Identity chapters 4-1 through 4-4 flow in
sequence rather than each forcing a new page. Chapters 4-1 and 4-2 share page
66; 4-3 and 4-4 share page 67. Natural page overflow is allowed. Numbering,
contents entries, bookmarks and cross-reference labels remain unchanged, and
other parts retain their existing chapter breaks.

The final pages were rendered and inspected under the PDF skill workflow.
Six PDF structure checks and Python compile checks passed. All 699 named
destinations and 295 internal links were inspected with no broken targets;
the four chapter labels retain their own chapter destinations. The universal
original App was rebuilt without restarting it, and code-signature verification
passed. Source, served and bundled PDFs are identical (SHA-256
`95555aeb67bdf1a8905c54e84166b0e6f0315f578784747cadb96b5078dd598f`).
The running service serves the current HTML and both final screenshot assets
byte-for-byte, and its health check is OK. Existing deprecation warnings and
the existing-icon fallback were non-failing build output. This follow-up did
not change Browser behavior, operate passwords, import bookmarks or modify
research data directly.

Pre-commit verification, after explicit commit/push authorization: all 727
product tests pass again (31.875 seconds). The first rerun found two obsolete
guide assertions requiring a synthetic Browser caption and the old chapter
command. Those assertions now enforce real-App provenance, a temporary-only
demo renderer, and all four continuous Identity chapters; no runtime or PDF
change was needed. Six PDF structure checks, Python compilation, JavaScript
syntax, App signature, packaged-resource comparisons and whitespace checks
also pass. Earlier live/native and headless results above are not fresh reruns
of credential or publisher workflows.

## Keeping the next edition aligned

For a future feature change, check the matching topic and its cross-links as
well as visible labels, shortcuts, persistence/deletion behavior, and failure
states. Update relevant illustrations only with explicitly safe example data.
Regenerate the PDF from HTML, inspect changed pages, run guide tests and PDF
structure checks, then package and compare the App's PDF with the source PDF.
Do not describe a planned or unverified integration as a supported feature.

## Website link destination preference (017)

Added Setting > Website Links and a guide topic with Save, unsaved close,
Restore Default and restart persistence. Updated Paper Details, Browser and
Troubleshooting cross-links to describe the built-in default and macOS default
browser option. Existing real-App illustrations are retained unchanged.

All 733 product tests pass (35.467 seconds); six PDF structure functions also
pass when executed directly (pytest is not installed in the project venv).
The 77-page PDF has 701 named destinations and 301 valid internal links. Pages
35, 55, 62, 63 and 75 were rendered and inspected; Product Identity still flows
on pages 66–67. The worktree App was rebuilt and packaged without launching it.
Initial tests needed the project venv and scoped escalation for loopback sockets
and an ephemeral headless Chrome process. Synthetic DOM checks cover both
routing choices, all five workspaces and modified clicks; the actual dialog
HTML/CSS fits three viewport sizes. No synthetic capture replaces a guide image.
The 11 named product files have now been synchronized to the original project
and its universal App rebuilt/signed in place. With fresh user saved-drafts
approval, the original App was restarted at 14:12:58 (App 55381, sole UI 55389).
Live checks confirmed Website Links below Quick Look Settings, system Save and
reopen, and Restore Default. Library Open Website for the public Preskill paper
(Quantum 2, 79, 2018) opened Safari in system mode, then the same webpage loaded
in the built-in Browser after restoring default. Command-[ returned to the
selected paper. The external test tab was closed; builtin is saved and the
settings dialog is left open. Health, served HTML/PDF and resource hashes pass.
Only normal UI preference/history/selection changes occurred; no direct research
data, credential or benchmark operations. These validation runs did not commit or push;
subsequent commit/push was explicitly requested by the user.


## Numeric Subject calendar (September 9)

The Subject calendar now shows stored numbers without the completeness asterisk,
its tooltip or its sidebar legend. Fetch status, retry behavior and stored
results are unchanged. The in-app text and generated manual describe the numeric
counts and distinguish retrieval completion from exhaustive literature coverage.
The Subject illustration is retained and replaced with a fresh original-App
capture matching the user's date and subject selection. The August 2026 calendar
is visible beside September 2 results for Superconductivity, starting with the
Ising-superconductor diode paper (16 shown / 40 visible). A native Core Graphics
window-content capture frames the full calendar, summary and result area below
the title bar, excluding the Computer Use sharing badge without retouching the
image. No pointer or control overlay is included. All seven original-App
illustrations remain in both the interactive and fixed-layout guides.

Validation: 52 focused Subject/history/Guide tests and six PDF structure checks
pass, along with Python compilation and diff checks. The regenerated PDF has
79 pages; pages 54–55 were rendered and visually checked. All seven screenshot
figures remain, and Product Identity 4-1–4-4 flows continuously on pages 69–70.
Original and worktree source/Guide assets and signed bundles are synchronized.
The disabled isolated App is not updated. No direct database or fetch changes.


## September 9 AI Access update

Added the AI Access settings chapter and navigation entry to the shared HTML/PDF
source. The API v1 developer reference is `docs/AI_ACCESS.md`; generated OpenAPI
is `paper_monitor/ai_openapi.json`. This is opt-in access, not automatic analysis.
The guide distinguishes normal App sessions from scoped AI tokens and direct
filesystem permission. Both editions document the four implemented MCP tools,
file/analysis permission choices, expiry, revocation, provenance and retry rules.
All seven existing screenshots are preserved. The new PDF section on pages 66–67
was rendered and inspected; Product Identity chapters still flow continuously.


## September 9 Codex connection example

Both Guide editions and `docs/AI_ACCESS.md` now explain API, MCP, the private
access token and the Gewu Key, followed by an end-to-end Codex example. The
example separates Command/Arguments from the two Environment variables rows,
identifies the left Key and right Value boxes, explains Add environment variable,
and explicitly leaves Environment variable passthrough empty.

`<GEWU_ROOT>` denotes the actual absolute program folder containing
`scripts/gewu_mcp.py`; it is neither the Library nor the App bundle. No fixed
installation location is assumed. The project-local Python path is only an
example: the generated configuration supplies the installation's real interpreter,
script and port. Placeholders must be replaced, paths with spaces stay in one
field, and moving the installation requires updating the paths. Only placeholder
tokens are printed. The generic copied JSON is distinguished from Codex's TOML,
with a matching TOML block, metadata/PDF validation prompt and optional analysis
save prompt. Local desktop configuration follows the
[official OpenAI MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli),
checked September 9, 2026.

Validation: all 26 existing Guide/audit tests and six PDF structure checks pass.
The HTML and Markdown TOML examples parse and match, with the expected two
environment keys. The 82-page PDF was rendered and pages 66–69 visually reviewed;
the final example pages 66–68 are pixel-identical to that review. All seven
original-App illustrations remain, and Product Identity chapters 4-1–4-4 still
flow continuously on pages 72–73. The interactive Guide fits 1280, 900 and 640 px
windows; environment names remain unbroken and no page overflow occurs. The
initial sandbox browser launch was denied; an authorized temporary headless
browser completed the layout checks. No new illustration is used.

The original source and both signed App bundles contain the same PDF; the live
original service serves matching HTML/PDF bytes and remains healthy with the
same UI process (78889). No App restart, AI connection creation, client
configuration change or research-data modification was performed during this
documentation update. Commit and push were requested afterward.
The documentation/App backup and installation verification are retained at
`/private/tmp/gewu-codex-guide-before-2eow2ja4/`.
