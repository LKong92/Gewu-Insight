# Default Add to Library folder

Open **Setting > Add to Library**, click **Choose Folder**, select an existing Library or Space folder, confirm it, then click **Save**. Closing the settings window without saving discards the selection. **Restore Default** saves `Library / unsorted` as the default again.

Journal Monitor, Subject Monitor and Author Monitor preselect this folder in their shared Add to Library picker. An explicitly confirmed folder overrides the default for that operation. Calls to the shared add endpoint without a destination resolve the current default on the server.

Browser **Save to Gewu** uses this preference only when the identified paper has no active Library or Space placement. Existing papers still reuse their existing location, preferring the originating selected occurrence when it belongs to the same paper. Choosing and confirming another folder explicitly can add that location. Review remains read-only; Save rechecks the destination.

The preference stores a folder ID in SQLite, not a local filesystem path. Renaming or moving the folder preserves the choice. If it is deleted, moved inside Recycle, or otherwise unavailable, the default falls back to `Library / unsorted`. Recycle and its descendants cannot be selected. A stale explicitly chosen destination is rejected rather than silently changed.

Changing this setting affects future additions only. It does not relocate existing papers or files, change Gewu Keys, Paper Files classifications or Default, migrate the database schema, or change Loader's explicitly selected import destination. The legacy `unsorted: true` API option remains an explicit request for unsorted.

`paper_monitor/library_destination.py` provides the shared active-folder validation and default resolution for Monitor and Browser. Regression coverage includes persistence, rename/move, missing and recycled folders, explicit overrides, read-only review, existing-paper reuse with a PDF, settings cancel/save/failure/reset, and the full product picker/API on temporary data. Native builds add the menu entry; runtime settings remain local to each workspace database.
