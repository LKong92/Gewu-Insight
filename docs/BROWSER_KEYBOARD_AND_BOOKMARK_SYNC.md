# Browser keyboard and bookmark-source synchronization

## Scope

This product follow-up extends Browser chrome navigation and adds an explicit,
one-way bookmark-source workflow. It does not change WebKit identity, networking,
cookies, persistent website storage, AutoFill or credential delivery.

## Keyboard boundary

`browser_keyboard.js` handles only trusted workspace controls. The primary
Browser tab enters the toolbar; Up returns to the primary row. Toolbar, webpage
tabs, Favorites and the visible collection sidebar have directional paths and
Enter activation. The existing Library root exception stays intact. Address
selection and address editing are separate, so ordinary editing keeps its keys.

The native controller lets the original page arrow run normally. Only an
eligible Up or Left press schedules a single isolated-world boundary check in
`GewuBrowserNavigationProbe.js`. It reads element semantics and scroll geometry,
not values, text, credentials or clipboard contents. Inputs, frames, PDFs and
custom/uncertain widgets retain their own keys. No page listeners, polling or
mutation observers are installed. Focus transfer checks input generation,
window/sheet, active tab, URL, responder and visibility again before returning
to trusted chrome. A hidden sidebar cannot receive focus.

Real WebKit can redispatch the same unhandled arrow through AppKit. Numeric
timestamp/key-code deduplication prevents that redispatch from cancelling its
own pending check; no event objects or typed characters are retained.

## Bookmark-source boundary

The bottom B menu contains Import, Export, Sync from Safari and Sync from Chrome.
Sync first uses an explicit native file picker, then a folder-path/count picker.
Only the selected subtree is synchronized. The source is read-only and manually
refreshed; this is not cloud sync, a background watcher or a two-way mirror.

The native picker reads only a selected `Bookmarks.plist` or `Bookmarks` file,
limited to 10 MB. It never scans profile directories or reads passwords, cookies
or history. Safari file-access denial retains the existing HTML Import fallback;
no privacy settings are changed. The Python parser receives a bounded snapshot,
not a filesystem path. It accepts Safari XML/binary plist and Chrome JSON.

SQLite stores the bookmarks and a source/folder ownership map in app_settings;
schema remains 16. Stable source identifiers permit updates to unchanged items
created by sync. Pre-existing matches and local edits, moves or reorders remain
local. Source deletions do not delete Gewu items. Legacy identifiers use additive
folder/URL matching. Same-folder URL collisions preserve existing local entries.
All mutations and ownership tracking share one savepoint, including rollback
when validation or final tracking limits fail. Preview/cancel writes no bookmarks.

Format references: Chromium's [Safari importer](https://chromium.googlesource.com/chromium/src/+/b8694d8e2ec7070ec6b31745f46f37c48c88392d/chrome/utility/importer/safari_importer.mm)
and [bookmark codec](https://chromium.googlesource.com/chromium/src/+/139.0.7258.138/components/bookmarks/browser/bookmark_codec.cc).

## Validation

- 727 product tests pass (33.053 seconds), using temporary databases and local
  test servers. This includes source selection, preview, repeated sync, source
  changes, local-edit preservation, collision, malformed input and rollback.
- An isolated headless Browser keyboard probe passes primary/toolbar/tab/sidebar/
  Favorites routes, editable-field boundaries and compact menu layout. Existing
  four-size Home/tab layout and workspace-return probes also pass.
- 18 real WebKit/AppKit checks pass on generated documents with an ephemeral
  store: actual native arrow dispatch, top/left handoff, hidden sidebar,
  modifiers, scrolling, input/textarea and widget exclusions. No live credential
  picker or website account is involved.
- The original App was rebuilt and restarted with saved-drafts approval. Live
  checks confirm toolbar Up to Browser, Down back into the toolbar, Down through
  the webpage tab into real Favorites, Left to Bookmarks, and the four B menu
  items. No personal source file was opened or synchronized for testing.
- During the subsequent real Nature screenshot, macOS WebCrypto keychain access
  blocked the App's main thread. A stack-only sample identifies WebKit's master-key
  lookup waiting in Security.framework, not a navigation-probe loop. The App
  later became responsive and real Space/Subject guide captures were completed
  without operating credentials. Further live webpage-boundary checks were not
  part of that documentation-only follow-up and are not claimed here.

This does not certify every publisher/widget or reliable system-password filling.
There are no benchmark operations or automatic commit/push actions.
