# Paper Files duplicate prevention and repair

Loader now separates a paper's identity, its exact file bytes and the file's
import origins. Matching a DOI alone does not establish that two files are the
same version. Conversely, a changed source directory or filename must not create
another attachment when the same paper already contains exactly those bytes.

The shared resource lookup checks current physical files and full SHA-256 values.
It does not rely on cached hashes after an external edit, and never uses the
annotation-insensitive PDF content hash to discard files. An edited file remains
a separate version even when its filename and byte count have not changed.
The ordinary attachment entry point uses the same verified-content rule.

Loader checks before copying and again while serializing resource registration.
Concurrent registrations reuse the winning record and remove only the unused
copy created by that invocation. File creation is exclusive, so concurrent
copies cannot overwrite one another. App attachment writes share the per-paper
lock used by Loader. SQLite guards reject new identical stored-path registrations;
the storage API also recognizes alternate paths to the same physical file.

Schema 20 adds `resource_import_sources` and `resource_duplicate_archive`.
Additional import origins retain their batch and source metadata independently
of the surviving resource. Repeated imports can find those origins after a file
has moved or been reassigned. Schema upgrade alone does not merge or remove files.
The repair keeps Gewu Keys and Library placements unchanged and never merges
separate paper identities by hash. MCP analysis permissions are unchanged.

## Existing duplicate repair

Normal App startup checks legacy duplicates before starting background workers.
Documentation mode and mismatched custom database roots skip repair. Existing
interrupted file-layout moves are recovered first. The check runs once; protected
or conflicting cases are recorded for review rather than repeatedly scanned.

Each duplicate group is verified again under SQLite's writer lock. The repair
keeps a manual Default where present, otherwise the existing primary resource,
then the oldest record. It retargets Default/primary and supersession references,
preserves source provenance, fills unknown metadata, and archives the complete
removed rows. Explicitly conflicting classifications and saved AI analyses or
their recorded sources are retained for review. Different file bytes are never
merged, including differences confined to PDF annotations.

Before changes, the database is backed up under
`data/resource-dedup-backups/<timestamp>/before.sqlite`. Private managed redundant
files are copied into that backup directory and verified before their records
are merged. Original external linked files and files referenced by another paper
are not removed. The surviving physical file is always retained. Per-group JSON
reports and archived rows support recovery; interruption before commit keeps the
originals, while interruption after commit resumes only the verified cleanup.
Changed files are retained and reported. File and Associated Files aliases are
then synchronized by the existing layout repair.

Do not restore the database alone as a filesystem rollback. Use its matching
per-group reports and saved file copies. No backup bytes are deleted by this
repair. This is unrelated to clearing metadata refresh or Loader task history.

## Validation

Disposable fixtures cover changed source paths/names, source provenance,
same-size different versions, concurrent registration, direct-path guards,
manual Default and annotation overrides, conflicting classifications, external
originals, same-path legacy duplicates, backup failure, SQL rollback, restart
recovery and schema-19 upgrade. Manual App acceptance remains with the user.
