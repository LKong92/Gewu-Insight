# Browser article capture

Save to Gewu joins the built-in Browser to the existing paper, Library and Paper Files model. The toolbar opens a trusted workspace review panel. It does not change the ordinary Save Download action. Safari extension packaging and native messaging are future adapters, not part of this implementation.

## Flow and boundaries

1. An explicit toolbar command snapshots the current native tab, document generation, URL, Open Website context and bounded article metadata/PDF candidates. The one-shot collector runs in an isolated WebKit content world. It reads publication meta tags, scholarly JSON-LD and PDF links; it does not read inputs, credentials or the whole document body.
2. `capture_begin` creates a short-lived memory ticket and returns a review without writing papers/files/placements. Known DOI/arXiv aliases reuse canonical records. Identify can resolve an identifier through the existing bounded Crossref/arXiv clients. A title-only record requires explicit confirmation.
3. A PDF can be retrieved through the source WKWebView's session into a temporary native file, or chosen by the user. Native retrieval is bound to the snapshotted document and allowed candidate. Public-URL rules, MIME/size checks, a transfer timeout and backend readable-PDF validation apply. The native helper uploads bytes only to the workspace's loopback endpoint with a separate, one-purpose capability. Upload redirects are refused and no capability is sent to publishers. Remote pages receive no bridge or API access.
4. The destination reuses the Monitor Add to Library column picker: My Library/Spaces, successive folder columns and a full selected path. Confirm updates the capture destination only; Cancel preserves it, and Save to Library performs the import. Recycle and trashed folders are excluded. The reviewed server-side candidate is checked against PDF/page evidence and rechecked against canonical identity immediately before Save. Open Website context is a hint only. Save adds/reuses the paper and selected active Library or Space placement, records sanitized source provenance, and uses `attach_file_to_paper` plus the existing Library file reconciliation. SHA-256 duplicates reuse existing resources. File type is user-selected (Unknown initially), file source is User import with host detail, and manual Default remains sticky.
5. Tickets are DB-scoped, limited to 16 and expire after 20 minutes. Cancellation cleans staging; native cancellation also releases the retained snapshot. Repeated Save returns the same result. File failure after metadata commit is explicitly reported as partial success and remains retryable. No schema migration, JSON authority or automatic monitor classification is introduced.

## Adapter API

The trusted same-origin `/api/browser` actions are `capture_begin`, `capture_review`, `capture_save`, and `capture_cancel`. PDF bytes go to `/api/browser-capture-file` with `X-Gewu-Capture-Token`; browser-origin uploads must still pass the existing same-origin/Host checks. This endpoint does not accept arbitrary local paths or fetch a URL. A future Safari adapter must use an authenticated native handoff; it must not relax these origin/host requirements.

Recognized signed/authorization URLs are excluded from persisted source fields. Metadata services receive the requested scholarly identifier only. Temporary files are not research-library records or exports. A successfully saved ordinary source URL is retained as provenance; opening a page by itself does not import it.

## Validation

`tests/test_browser_capture.py` covers SQLite/file behavior and real local API upload/permission checks using temporary roots, plus the inert native lifecycle probe in `tests/browser_capture_native_probe.m`. `tests/browser_capture_ui_probe.cjs` exercises the real collector and review UI with generated DOM and in-memory API responses: no user profile or real website traffic. The native probe checks staging cleanup, redirect rejection, native URL authority, document changes, candidate binding and late cancellation callbacks. These tests do not establish universal publisher or institutional-download compatibility.
