# Publisher PDF downloads in Browser

September 11, 2026. Website PDF downloads display inside their originating Browser
surface. Ordinary inline PDF responses continue streaming through WebKit. PDF
attachments, HTML download links and non-displayable PDF responses become a
WKDownload using the original request, including POST bodies and the website's
current WebKit session. No URL rewrite, separate publisher GET, cookie export,
Safari-profile access or authentication bypass is introduced.

The native delegate receives bytes into a private temporary directory and loads
them with `loadData:MIMEType:characterEncodingName:baseURL:` using the public source
URL. It removes the temporary file after reading. Actual PDF bytes are checked
before display; a wrongly labelled HTML response produces a visible error.
Generic binary non-PDF files retain a save-sheet path. Navigation to a normal HTML
sign-in or consent page remains visible even when a download link initiated it.

Exact `blob:` files from the known public creating origin are supported. The
address bar, opaque origins, unrelated origins and private destinations do not
gain a blob exception. WebKit continues to enforce its own blob access checks.
Blob previews use the public creator page for their visible source and provenance;
the nonpersistent blob identifier is not treated as a scholarly identity or saved
source URL. Popups retain WebKit's supplied configuration and tab choice.

Transfers belong to a page/document generation. Switching tabs does not cancel
them or focus the completed PDF. Navigating away in that surface, Stop, closing
the tab or invalidating Browser cancels the pending preview and cleans staging.
WebKit's download-transition cancellation is not reported as a navigation failure.
New popup data documents can temporarily lack a back/forward item; their bytes
are bound to the document generation until a history item is available.

Retained preview bytes are associated with the actual history item/document, not
just its URL. Save to Gewu and the footer Save Download action now also read
ordinary inline PDFs from WebKit's loaded main resource. They never silently
replay the PDF request. The optional `_getMainResourceDataWithCompletionHandler:`
SPI is checked at runtime; unsupported, incomplete or timed-out extraction shows
an explicit error. HTML viewer archives, generated/printed PDFs and private
WebKit cache files are not substitutes for the original. The native PDF HUD's
optional save-data callback feeds its supplied bytes into the same save dialog.
Both download arrows use a native save sheet, initially in Downloads, with
preparing/cancelled/saved/error feedback. Initial inline PDF streaming is unchanged.

Embedded PDF frames are discovered only on explicit capture/export. The bounded
frame-tree probe reads MIME, URL and a document nonce in a retained isolated
content world; it does not inspect frame text or forms. Optional WebKit frame
symbols are resolved at runtime. Main-resource bytes come from the bound frame,
including a cross-origin frame with no `.pdf` suffix, never an HTML web archive.
The nonce is checked around extraction and on cached reuse; independent frame
navigation invalidates old bytes even when the outer page and URL stay unchanged.
Ambiguous same-URL frames are not selected automatically. Multiple loaded PDFs
require choosing one in Details. Unsupported extraction stays explicit.

A scoped disk copy survives capture cancellation and repeated review while its
source document remains open. Navigation, including the same URL loading a new
document, invalidates that copy. Copies are bounded to eight current documents
and 256 MiB, and removed on eviction/tab disposal when the last transfer releases
them. WebKit retains control of its own rendering/history memory. Save to Gewu
uploads the original through the existing one-purpose loopback capability and
parses its metadata afresh using one validated PDF reader; PDF title/DOI evidence
rules continue to protect automatic attachment. An explicit existing-Key selection
can acknowledge conflicting evidence without overwriting the target bibliography. No browsing operation automatically
creates Library items or changes classification, Default, Keys or placements.

Preview attachment transfers retain their 128 MiB / 120-second limits and their
separate eight-document, 256 MiB memory cache. Capture and loaded-original export
now accept up to 128 MiB as well. Loaded-resource extraction has a 30-second
bound. Only an explicit Details action (Get PDF on an article page, or Download
PDF Again on an inline PDF) starts a capture network download. That download
stops after 90 seconds without byte progress or 15 minutes total, and its timer
ends before local parsing begins. Loopback delivery/parsing has separate
180-second request / 300-second resource limits. Status distinguishes reading
the loaded file, explicit network transfer and reading PDF information.

Safari's per-site Allow dialog is Safari's Downloads preference, not a publisher
verification mechanism. Browser preview does not add an imitation of that dialog.
Actual website login/consent UI remains owned by the website and WebKit.
[Apple's Safari settings documentation](https://support.apple.com/en-gb/guide/safari/ibrwe2159f50/mac).

## Validation

`tests/browser_navigation_probe.m` checks response policy and public-creator blob
boundaries. `tests/browser_pdf_webkit_probe.m`, driven by
`tests/browser_pdf_webkit_fixture.py`, exercises the product controller with real
ephemeral WebKit and generated localhost PDFs. Its loopback exception is compiled
only into this test; production public-URL checks are unchanged. It covers PDF
attachments, binary MIME, popup and blob paths, single POST submission, retained
bytes on reload and Save to Gewu, progress, focus retention, stale-navigation
cancellation, tab-close cleanup and a false-PDF response. Its upload fixture
compares bytes and checks that the POST download was never replayed as a GET.
The inline fixture uses Cache-Control: no-store, verifies exact original bytes,
reuses the same copy on retry, covers both export routes, and counts requests to
prove no extra GET is made. The native lifecycle probe rejects HTML wrappers and
late same-URL document results; UI checks cover explicit redownload permission,
progress and cancellation. The HUD delegate is exercised with generated data;
after the authorized original-App restart, the footer arrow was also clicked on
an already loaded arXiv PDF and opened Save Download at Downloads. The HUD
on-screen click and full capture-panel smoke were not repeated because the user
continued operating the App; the fixture results above cover their code paths.

These checks establish the application-side behavior, not universal publisher
compatibility. The supplied PNAS URL returned 403 to a separate unauthenticated
header-only request during investigation. No authenticated PNAS, Science, Wiley
or ACS download is claimed as verified by the synthetic tests.

September 16 embedded-frame regression verification: the real WebKit fixture
passes 75 checks, including production capture snapshot, source/placement
inheritance, cross-origin frame read, exact original upload, footer export and
stale-frame rejection. Request counters show one initial embedded PDF GET and no
additional GET for capture/export. The fixture bundles the actual metadata probe
and uses a nonpersistent profile; no live Library save or publisher login is used.
