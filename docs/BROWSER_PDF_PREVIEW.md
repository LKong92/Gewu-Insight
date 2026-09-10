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

Retained PDF bytes are associated with the actual history item/document, not just
its URL. Save to Gewu uses its existing snapshot/candidate checks and one-purpose
upload capability, sending the received bytes to the workspace without another
publisher request. Saving/refreshing a cached PDF reuses those bytes. The ordinary
Download / Share > Save Download action still explicitly asks for a destination.
No browsing operation automatically creates Library items or changes Paper Files,
classification, Default, canonical Keys or existing placement reuse rules.

Preview transfers are capped at 128 MiB and 120 seconds, checked during transfer
and after completion. The native reuse cache is capped at eight documents and
256 MiB, pruning documents no longer in history and the oldest entries first.
Closing Browser clears it. WebKit manages its own rendering/history memory. Save
to Gewu retains its existing 64 MiB file limit. Evicted files may need retrieval
again; the cache is not a permanent download or research-data store.

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

These checks establish the application-side behavior, not universal publisher
compatibility. The supplied PNAS URL returned 403 to a separate unauthenticated
header-only request during investigation. No authenticated PNAS, Science, Wiley
or ACS download is claimed as verified by the synthetic tests.
