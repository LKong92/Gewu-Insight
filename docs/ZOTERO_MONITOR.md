# Gewu Insight for Zotero

**Local preview 0.4.0 · Zotero 10 · macOS companion to Gewu Insight.**

Use Library, My Publications, Journal Monitor, Subject Monitor, Author Monitor
and Browser inside a Zotero tab. Both interfaces use the same local Gewu service
and selected Gewu Database. Saved papers, Paper Files, subscriptions, resource
API settings and AI/MCP grants remain in Gewu; opening or refreshing a view reads
that shared state. Browser page tabs and website sign-in sessions are local to
each interface and are not synchronized.

The plugin lives in this product repository and is bundled with macOS App builds.
It does not contain a second discovery engine, database or Python runtime.
A plugin update may be necessary when its host contract or Gewu UI changes;
compatibility is checked when connecting.

## Install and connect

1. In the updated Gewu App, choose **Plugin → Zotero Integration**.
2. For the first installation, click **Install in Zotero**. The persistent
   three-step guide shows **Tools → Plugins** and opens Finder with
   **Gewu Insight for Zotero.xpi** selected. Drag that file into the **Plugins
   Manager window**, not the literature list, and confirm Zotero's prompt.
   **Installation Guide** remains available afterwards. The dialog reports
   detection of the Zotero app separately from installation of the Gewu plugin.
3. Choose **Open in Zotero** in Gewu, or **Tools → Gewu Insight** in Zotero.
   Gewu prepares the connection to its existing database. For a manual setup,
   choose that database's root folder, not its `data` subfolder.
4. In Zotero, the six Gewu tabs occupy the workspace directly. The **…** menu at
   the upper right contains View, Loader, Settings, Help and **Connection Settings**.
   Plugin installation and updates stay in the standalone Gewu App's **Plugin**
   menu; the embedded Zotero interface does not repeat that menu or its integration dialog.
   Connection settings are a dialog; there are no extra permanent toolbar or
   status rows.
5. **Save to Gewu** uses the existing Gewu Library/Space workflow. **Save to
   Zotero** beside a paper opens a destination dialog, with an optional PDF copy.
   A brief notification offers **Show in Zotero** after saving.

The folder and local address are remembered. On macOS, the plugin can start the
installed Gewu service in the background without opening its App window. Opening
the App afterwards reuses that service when its authenticated database matches.
While a connected Gewu tab is open in Zotero, the standalone App pauses its main
window and editing menus. Closing that tab refreshes the App from the shared
database before restoring interaction. Merely running Zotero does not pause Gewu.
This is an interface guard, not a database lock; monitoring and background jobs
continue. It does not synchronize Zotero's own library back into Gewu.

Choosing **Open in Zotero** waits for that workspace to acknowledge the request,
then quits the standalone App while retaining the shared background service.
If Zotero does not confirm, the App stays running. Closing a Zotero tab clears its
browser session, but does not stop the shared service or monitoring jobs. Opening
the App is still useful for native platform operations and checking startup
problems. A failed connection never creates an
empty replacement database. Use **Connection Settings** only to reconnect or change the
selected database; use **Open in Zotero** again after changing databases in Gewu.

The dialog offers one primary action: **Install in Zotero** when absent,
**Open in Zotero** when installed, or **Update Plugin** when the App includes a
newer version. Installation state comes from the local Zotero addon registry and
package; disabled plugins and ambiguous profiles are reported separately.

For an installed 0.2 or later plugin, **Update Plugin** replaces it with the XPI
bundled with the current Gewu App, without dragging a file again. This is needed
only when a newer bundled plugin is available; it does not download an update
from the Internet. Updating the earlier 0.1 preview, or reinstalling after
uninstalling, requires the plugin manager. Uninstall through that manager;
previously saved Zotero items remain.

To build from source, run `python3 scripts/build_zotero_plugin.py`; the output is
`dist/gewu-insight-zotero-0.4.0.xpi`. This preview has not been published as a
GitHub Release. The update manifest currently lists no public updates.

## Plugin windows

Save to Zotero, Connection Settings and Browser's bookmark, page-action and
confirmation dialogs use one plugin-local utility-window style matching Gewu's
centered title bars, close controls, compact text, inset groups and equal-width
action buttons. Notifications wrap their detail beneath a short title, with
Show in Zotero on its own row. These styles do not modify standalone App windows
or Zotero's other plugins.

Connection Settings shows the current **Gewu Database** folder and connection
state. This selects which Gewu papers, files and settings the plugin uses.
**Local address**, under **Advanced**, is the loopback address of Gewu's service
on this computer. Open in Zotero configures the connection automatically; normal
use does not require editing it. **Reconnect** retries the selected connection;
**Start Gewu in the background** starts the existing service if needed. It does
not create or migrate a database.

## Preview PDFs

PDF Quick Look opens with **Space** and closes with **Space** or **Escape**.
The plugin renders PDF pages using the PDF.js components already installed with
Zotero, inside the existing Gewu preview window. Scroll through pages, click a
thumbnail to jump, select text, or use **Open in Preview** for the macOS reader.
Only nearby pages keep rendered canvases; closing or switching files cancels the
previous document. This adapter does not import a Zotero item or write a PDF copy,
change Zotero's global PDF/download preferences, or change the standalone Gewu
App's preview implementation. Unavailable files show an inline retry message.

## What saving does

- Copies title, full author names, abstract, identifiers, date and available
  journal/volume/issue/pages metadata. Names remain in Zotero's single-field
  format because Gewu's display names do not reliably identify family names.
- Saves to the selected writable personal or group library and collection.
  Normal Zotero synchronization rules apply to items saved there.
- Matches existing items within that library by Gewu workspace/key provenance,
  canonical DOI, or its normalized arXiv provenance line. Repeated saves add the
  destination collection and preserve existing metadata and user edits.
  Conflicting matches stop with a message; there is no automatic merging.
  Items without shared identifiers may still need Zotero's duplicate review.
- With **Copy the available Default PDF** checked, copies the existing local **Default**
  PDF into Zotero's attachment storage. It does not move the Gewu original or
  copy every Paper File. An existing Zotero PDF is retained. A missing PDF leaves
  a metadata-only item; a failed copy is reported and can be retried.
- Download remains a Gewu action. To obtain a missing PDF, use the monitor's
  Download control and save again after it finishes. Publisher restrictions and
  Gewu's normal download limits still apply.

Saving is a one-way, explicit action. Subsequent Zotero edits, annotations,
notes and attachment changes do not synchronize back to Gewu. Full Zotero
migration is a separate, unfinished task.

## Connection and implementation

Source lives in [`integrations/zotero/`](../integrations/zotero/). The XPI contains
only plugin source, the Gewu App icon and the repository license. It includes no database,
credentials, test harness or third-party extension code. The historical addon ID
is retained so existing installations update in place.

The native Zotero host handles tabs, collections, items and attachment copies.
A window actor connects only the owned, authenticated Gewu workspace to a small
versioned UI contract. The full interface and normal operations come from Gewu.
Privileged Zotero objects are never exposed to page scripts; metadata is fetched
again before a Zotero save. Settings are normal Gewu settings, not separate
plugin copies. Existing MCP grants are neither replaced nor broadened.

The chosen folder's private workspace credential is used only with the configured
loopback origin, with redirects refused. The workspace receives an HttpOnly
session in an isolated cookie context, cleared when the tab closes. Credentials
are not saved in plugin preferences, URLs, setup links or webpage JavaScript.
App setup stores the database location and an expiring, single-use request ID;
it does not copy the workspace credential.

The plugin sends authenticated, process-local presence heartbeats. Closing a tab
clears its presence; an abnormal exit expires after 12 seconds. Presence writes
require the private host credential, not just a webpage's workspace cookie. App
handoff requires acknowledgement of the matching setup request. Presence does
not modify the database or MCP permissions.

Browser uses separate Gecko content views for public websites, with no workspace
credential or privileged Gewu bridge. It adapts the existing Gewu bookmark,
history and Save to Gewu review workflows. Publisher cookies are separate from
both the workspace session and the standalone App's WebKit browser. Website
sign-in may therefore need to be repeated. PDF capture still requires a valid
PDF from a candidate on the reviewed page and respects normal access controls.

## Validation and limits

Validated on macOS with Zotero **10.0.6** and isolated synthetic data:

- All six tabs, Library Paper Files, monitor Save to Gewu, Library Save to Zotero,
  destination dialog, compact menu and connection dialog/reopening.
- Native item/PDF save, collection assignment, repeated-save identity, edited
  metadata preservation, canonical DOI matching and ambiguous-match rejection.
- Workspace session cleanup, background helper startup, and standalone App reuse
  of that helper. A font setting was changed in each interface and read from the
  other; the test setting was restored.
- Browser website loading, metadata capture review and bookmark save. The native
  harness also checks browser visit identifiers and repeated connection layout.
- 0.2.1: a three-page synthetic PDF in the native Zotero browser covered rendered
  text/graphics, thumbnail navigation, resize, close/reopen and rapid file changes.
  Actual Space open/close/reopen and Escape were checked; no Save As dialog appeared.
  Renderer asset requests are restricted to Zotero's own PDF data resources.
- 93 scoped Python integration/link/capture checks, five Node mapping/URL tests,
  syntax/compilation checks, native universal build and strict signature checks.
- 0.3.0: seven Python setup/package/presence checks and six Node core/PDF checks
  passed. The daily App and Zotero verified the persistent guide, Finder file
  selection, in-place 0.2.3 → 0.3.0 update, acknowledged App quit with the backend
  retained, reopening into the paused window, disabled editing menus, and
  closing the Zotero tab to refresh and unlock the App. Both universal native
  compilation and strict App signature verification passed. Missing/disabled
  installation states and heartbeat expiry were checked with synthetic fixtures;
  the daily addon was not uninstalled for this validation.
- 0.3.1: seven Python and six Node checks passed; JavaScript syntax, package and
  App signature checks passed. Daily Zotero visually verified both connection
  settings states, the save dialog, bookmark-folder editor and notification
  presentation with synthetic result text. Cancel and Escape closed the dialogs;
  no formal items were saved during these UI checks. The standalone App's shared
  window styles and native executable were not changed.

Zotero 7/8 and Windows have not been validated; the manifest accepts Zotero 10.
Group-library sync, large-library performance, publisher login/PDF behavior and
all native drag/password/file-dialog edge cases are not covered by these checks.
The Zotero Browser does not share WebKit cookies or implement Safari password
autofill. Use the standalone App for unsupported native operations.

Run pure checks with `node --test tests/test_zotero_core.cjs`. Native checks must
use a separate Zotero profile **and an existing, separate data directory**.
Never switch a test instance to the user's real data when prompted. Test
workspaces and logs stay ignored.

Zotero-to-Gewu migration is available as an explicit **Loader → Import from Zotero** operation; see [the migration guide](ZOTERO_MIGRATION.md). Save to Zotero
is an explicit copy, not bidirectional synchronization of Zotero edits or files.

API references: [Zotero plugin development](https://www.zotero.org/support/dev/zotero_10_for_developers)
and [Zotero JavaScript API](https://www.zotero.org/support/dev/client_coding/javascript_api).
The installed Zotero implementation was inspected to verify current API behavior.
