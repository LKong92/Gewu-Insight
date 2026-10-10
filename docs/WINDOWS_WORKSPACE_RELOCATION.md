# Windows database location and backups

Program, source and Gewu Database are independent. Setup defaults a new database
to `%USERPROFILE%\Gewu Database`; an existing collection is selected with
**Use existing Gewu Database**. **File → Open Gewu Database** opens its location.
`%USERPROFILE%\.gewu-insight\database-location.ini` stores the location and
expected identity. The database's SQLite file owns that identity and state.

Missing, wrong-identity, newer-schema or busy databases stop startup instead of
creating an empty substitute. Use the App's supported recovery selection when
the selected folder is unavailable. A source checkout is not a database backup.

Stop all processes using the collection before copying or restoring it. Back up
the complete database folder, additional managed roots and externally linked
originals together. Retain the locator and matching runtime profile separately
for same-machine recovery. Browser profiles, logs and cache live under
`%LOCALAPPDATA%\Gewu Insight\Databases\<identity>`.

A move to another absolute path or computer needs review of managed paths and
Windows shortcuts; copying files alone does not retarget every reference.
Keep the original and a verified recovery copy until identity, database integrity,
files and representative placements have been verified in the installed App.
Never overwrite newer research with an earlier backup without reconciliation.

`paper_monitor.windows_workspace_relocation` performs a conservative offline
copy to a new destination. It rewrites known operational paths, checks files,
shortcuts, database rows/schema and integrity, preserves provenance and retains
the source for rollback. Unknown paths or reparse points can stop the copy.
The CLI prepares the destination identity and preserves the browser profile;
it changes the current `database-location.ini` only with explicit `--select`,
after verification and the diagnostic report are written.

Use this Windows-only tool with reviewed absolute source/destination paths and
a fresh report path for an explicitly planned migration. Omit `--select` while
validating a copy. Check installed-app startup after an authorized selection
change. This does not establish cross-platform database migration support.
Development setup also omits `--select`; see [development](DEVELOPMENT.md#manual-setup).
