# Import a Zotero library into Gewu

Local preview: macOS, Zotero 10 and Gewu's Zotero companion **0.4.0 or later**.
This is an explicit copy into the selected Gewu Database. It is separate from
displaying the existing Gewu workspace inside Zotero, and is not ongoing sync.

## Use the importer

1. Update Gewu and its bundled companion through **Plugin → Zotero Integration →
   Update Plugin**. First-time users follow the installation guide in that window.
2. Choose **Loader → Import from Zotero** in Gewu, then **Connect Zotero**.
   The same entry is available under the **… → Loader** menu in Gewu's Zotero tab.
3. Choose the Zotero library, all items or selected collections, and a Gewu
   destination. Selecting a collection includes its subcollections. Unfiled items
   are included when importing the whole library.
4. Choose **Preview Import**. Review item counts, available attachments and any
   missing files or identity conflicts. Preparing this preview does not import
   papers into Gewu or change Zotero.
5. Choose **Import into Gewu**. Keep Zotero running until completion. You may close
   the import window; open it again to inspect the current or previous session.

**Pause Import** keeps completed copies. **Resume Import** continues that session;
**Retry Unfinished** retries incomplete entries. If either app or its service was
restarted, use **Reconnect Zotero**, then resume. A changed Zotero record/file needs
a **New import** and fresh preview. Previously imported identities and unchanged
files are recognized across sessions; a second import is not a second full copy.

## What maps into Gewu

| Zotero content | Gewu result |
| --- | --- |
| Collections and subcollections | Folder hierarchy under the chosen import folder, including empty collections |
| One item in several collections | One Gewu paper/Key with several folder memberships |
| Bibliographic item with no local PDF | Metadata record; no fabricated DOI or automatic download |
| Stored files and externally linked files | Verified, independent managed copies in Paper Files |
| Multiple attachments or supplements | Separate Paper Files; unknown versions are not automatically classified as published articles |
| Native Zotero PDF annotations | Original PDF, separate annotated PDF export when available, and readable annotation text |
| Annotations already embedded in a PDF | Retained in the unchanged PDF copy |
| Child and standalone notes | Readable Markdown plus an archive of original HTML/metadata and embedded images |
| Legacy HTML snapshots with sibling assets | HTML copy and an archive preserving the snapshot's relative file structure |
| Tags, citation keys, extra fields and relationships | Original fields retained in Zotero Metadata and the migration record; no new native tag/citation-key UI is implied |

The original note archive preserves richer formatting than the readable Markdown.
Images are included separately in that archive and embedded in the readable note
when supported. Zotero-specific interactive annotation links and note navigation
are not recreated as Gewu controls. An annotated export failure is reported;
it does not remove the source annotations or discard the original PDF copy.

Existing Gewu bibliography, manual Default choices and classifications are kept.
Matching source identities/verified identifiers may reuse an existing paper;
conflicting identities require review. New file revisions can coexist with older
copies. Files or papers deliberately removed from Gewu are not silently restored.
Renaming/deleting Zotero collections later does not rename/delete Gewu folders.

## File-management plugins

The adapter resolves the attachment recorded by Zotero, rather than scanning an
arbitrary storage folder or depending on a particular file-manager plugin.
Stored paths, absolute linked paths and paths relative to Zotero's **Linked
Attachment Base Directory** are supported. This covers the corresponding file
arrangements used by tools such as ZotFile, ZotMoov and Attanger, provided the
current attachment is registered in Zotero and available on this computer.
It is not a claim that every release/configuration of those plugins was tested.

External tablet/backup copies not registered as attachments are not searched for.
Better Notes content saved as ordinary Zotero notes follows the note mapping;
external synchronized Markdown files and custom plugin state are not reconstructed.
Trash, saved-search definitions, sync credentials and plugin settings are excluded.

If files are only in Zotero's cloud/WebDAV storage, download them in Zotero first.
Missing links and legacy Mac aliases are reported for repair in Zotero; this
importer neither downloads source attachments nor rewrites their links. After
repairing them, prepare a new preview. Group libraries can be selected when the
local Zotero profile exposes them; group permissions and cloud-only files do not
become extra migration privileges.

## Safety and implementation boundaries

- The source adapter uses Zotero's loaded item APIs. It does not open or edit
  `zotero.sqlite`, save/delete items, relocate attachments or run synchronization.
  It writes only its own connection identity preference and new export copies in
  Gewu's staging directory. PDF export explicitly disables annotation transfer.
- Original files are read-only inputs. New managed copies are checked against
  source size/time and file fingerprints, then verified by SHA-256 against both
  a fresh source read and the destination. A changed file is rejected for review.
- The database manifest, source mappings and per-file receipts are persisted in
  dedicated `zotero_import_*` tables in Gewu. JSON is a transport/export format,
  not a second source of truth. Resume never deletes registered copies.
- Normal cleanup removes only newly created temporary copies. After a crash,
  a partial file that cannot be proved safe to delete is retained in staging;
  an interrupted PDF export may also remain there. No source cleanup is attempted.
- Privileged source paths are accepted only from the authenticated Zotero
  adapter. A page session or an AI/MCP token cannot submit migration manifests.
  Workspace credentials stay on this computer and are not placed in the page.
- Existing Folder Loader, Storage, file-layout, download and MCP implementations
  are reused through their interfaces and remain unchanged. New adapter code is
  under `paper_monitor/zotero_import/`, with a small UI entry and plugin bridge.

Validation uses synthetic libraries and separate Gewu/Zotero profiles. The preview
has been exercised with Zotero 10.0.6 on macOS; Windows, older Zotero versions,
large production libraries and every third-party plugin configuration remain
outside the current validation claim.
