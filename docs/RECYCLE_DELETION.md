# Recycle deletion

## Moving a placement into or out of Recycle

An original may live in the local Recycle directory only while no active Library, Space or My Publications placement uses it. Deleting or dragging a folder applies this rule to each paper in its entire subtree. A surviving normal placement retains the original, or receives it if the owning placement moves away; recycled placements keep shortcuts to that original. Different paper records sharing the same registered bytes are protected too.

Restoring, copying or adding a recycled paper to an active location moves its original back out of Recycle and rebuilds the shortcuts. This includes Monitor Add to Library, Browser Save to Gewu and My Publications additions. Recovery falls back to an active folder if the original parent was also recycled. The common placement check runs during these operations; it does not perform a startup sweep or alter unrelated historical records.

Moves update the existing SQLite file pointers and Associated Files paths, including analysis and supplemental-file projections. They retain Gewu Key, resource IDs, classifications, manual Default and file contents. Filesystem/path-update failures restore the moved original and any replaced destination shortcut. Unrelated files with the same name are never overwritten. Ordinary copies whose original already resides outside Recycle retain the lightweight alias-only path.

These placement operations differ from deleting one attachment inside Paper Files: that explicit action removes the attachment registration and sends its private managed copy directly to macOS Trash. Shared bytes and external originals are retained; the current Default cannot be deleted until another Default is selected. Because placements share one Paper Object, deleting an attachment affects that object's Paper Files at every location.

Regression coverage in `tests/test_file_placement.py` uses temporary SQLite, nested Library/Space folders, synthetic files and real handler calls for deletion, drag, recovery, copying, Monitor additions and Browser captures. It also checks shared primary/resource/supplement references, target-name collisions, failure rollback, attached Markdown/multiple PDF versions and unchanged classification/Default.

## Emptying Recycle and permanent deletion

`Empty Recycle` appears only on the Recycle root folder or blank space directly inside that root. It is hidden on every child file/folder and on blank space inside a nested folder. `Delete` applies to the selected entries.

Emptying clears all Recycle placements and child folders from SQLite and moves every direct child of the corresponding local Recycle directory to macOS Trash. This includes unregistered files, hidden entries, empty directories and dangling symlinks. The Recycle root remains. Deleting an individual folder moves that entire directory with its contents and hierarchy intact; it does not unpack its PDFs into Trash.

References are checked against the actual selection. A paper is removed only after its last Library/Space/Shortcut/Recycle placement and My Publications reference are gone. Retained papers keep their Keys, resource IDs, classification and Default. Bytes shared with another paper are also protected. When a retained file physically lives inside a directory being trashed, a copy is first secured at a surviving location and its file pointers/remaining aliases are updated; the directory sent to Trash retains its original contents. External import originals remain outside the cleanup scope.

File moves, retained-file copies and SQLite changes form one operation. Failures roll back SQL and restore completed moves, copies and alias changes. An all-Recycle batch uses the same transaction. The response refreshes retained Paper Files and paper paths without resource creation or classification changes. Failure text remains visible in the Library status area for retry.

The original macOS launcher exposes a short-lived `--trash-item` operation using `NSFileManager`, returning the actual Trash destination without creating a window or UI server. Paths preserve their final symlink, including broken links. This replaces the JXA bridge whose out-parameter conversion could fail after moving a file. Non-macOS fallback behavior is unchanged.

Verification uses temporary SQLite and synthetic files. `tests/test_recycle_deletion.py` covers directory integrity, disk-only remnants, empty roots, last references, surviving Library/Space/My Publications/Recycle references, shared resources, external symlink targets, SQL/Trash failure rollback, batch API errors, retained snapshots, menu contexts and UI retry behavior. Native checks separately exercise real macOS Trash with temporary files, nested folders and live/broken symlinks, restoring the fixtures afterward. Development verification does not automatically empty the user's real Recycle.
