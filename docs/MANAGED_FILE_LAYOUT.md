# Managed Paper Files and Finder aliases

September 18, 2026 implementation. This describes managed originals; logical
Library placements continue to share one paper identity and Gewu Key.

## Default and physical placement

An existing valid manual Default wins. Otherwise the existing publication order
applies: Corrected Published Version, Published Version, Accepted Manuscript,
then Preprint, with version/date ordering within a type. If no recognized
version exists, Unknown/Other files use a stable fallback: an existing primary
or main file, then the earliest PDF, then the earliest remaining file.
Missing/Invalid files and unreviewed identifier-conflict imports are excluded.
Explicit supplements, peer review files, correction notices and other secondary
classifications do not automatically become the article's main file; users can
still select a valid file manually. Automatic choice does not set the manual
preference or infer a publication classification.

The Default's real file remains at its existing active canonical placement when
possible. If that placement has gone away, another active Library, Space or My
Publications location becomes canonical. Other private managed files move into
the paper's bundle under:

`Associated Files/<Library|Spaces|My Publications>/<mirrored parent>/<name> [Gewu Key]/`

Existing Versions, Supplements, Figures and Files subdivisions are preserved.
Different PDF contents are retained as separate resource rows and original
bytes, including edits and annotations. No DOI-based content deduplication is
performed. Resource IDs, classifications, provenance and logical folder
placements remain intact.

At secondary positions the main file is represented by a native macOS Finder
alias. The corresponding mirrored Associated Files path is a directory alias
to the one real bundle. No empty attachment bundle is manufactured. Existing
managed symlinks are recognized and converted on reconciliation. Other platforms
use filesystem symlinks. SQLite points to real resources, not alias contents.
PDF-specific download/merge code remains separate from non-PDF canonical files.

## Integration and boundaries

Folder Loader receipts now reconcile physical placement after registering a
file and its logical position. Re-imports continue to match the original source
registration even after a managed file has moved. Finder aliases are excluded
from document ingestion.

The common synchronization path also covers Default changes, attachments,
Browser saves, Library aliases, folder/Space movement, file reassignment and My
Publications placement. Existing export, recycle and deletion code recognizes
native aliases as shortcuts rather than document bytes or real directories.
MCP analysis saves remain append-only; they only update bundle projections and
do not relocate existing Paper Files.

External linked originals, files shared across paper identities, and works with
no active placement are not automatically reorganized. Ordinary files or
directories occupying an alias destination are never overwritten. Such layout
problems remain visible as errors/warnings for later review.

## Recovery and existing libraries

Normal UI startup does not run managed-library reconciliation or make a database
backup. Layout is maintained by the file operations described above. The earlier
historical repair remains available as an explicit development maintenance
routine; it backs up SQLite before reconciling saved works. A custom database
with mismatched managed roots is skipped. No database schema change is required.

Backups and a per-paper before/after path report are written beneath
`data/file-layout-backups/`. A backup database is not by itself a filesystem
rollback; consult the path report when reverting physical layout.

Each normalization holds SQLite's writer lock and rechecks resource paths and
preferences before moving files. A journal records each exclusive filesystem
move before it happens; failed transactions restore moved originals and displaced
aliases. Explicit recovery restores an uncommitted move or retains a committed
destination. Ambiguous external changes stop recovery for review instead of
overwriting bytes. Pending alias projections survive interruption and are
retried by later file operations or explicit maintenance, not by normal startup.
Interrupted move journals are retained for explicit maintenance recovery.
Saved attachments are not removed merely because a later alias operation failed.

## Validation

All 1,099 product unittest checks passed using disposable fixtures. Dedicated
checks exercise native file and directory aliases (including target rename),
legacy two-PDF placement, repeated real Loader imports with two different PDFs
sharing a DOI, Default changes, RTF/PDF transitions, folder moves, external/shared
file boundaries, failed transactions, interrupted-move recovery, migration backup
and idempotency, and alias-failure recovery. The existing drag test assertion was
aligned with the already-shipped typed native payload; drag runtime code was not
changed. Python compilation and diff checks also passed.

The agent did not click through or restart the original App for acceptance. The
user subsequently restarted it and checked the result, confirming it looks good.
The backed-up startup reconciliation handled 579 works and deferred four cases
where real directories occupied alias destinations, preserving those directories.
Read-only health and root-page checks passed after startup.
