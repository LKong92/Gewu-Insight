# Folder import recovery and file reassignment

Finder folder drops and Folder Loader use the same inventory importer. A matched
identity with contradictory DOI, title or other evidence no longer aborts the
batch: the incoming file is copied or reused, registered in the matched paper's
Paper Files, and placed in the selected Library folder. Existing bibliographic
metadata and Default remain unchanged. Different source PDFs sharing an identity
are retained; repeated records for the same source path and size are reused.

This is a file-preservation policy, not a claim that an extracted DOI is correct.
The ordinary Storage identity guard still rejects conflicting metadata updates.
Import diagnostics record the filename, relative path, incoming/existing DOI,
Gewu Key and guard reasons with conflict status `attached`. The log and Result
Guide explain where the file went. A conflict attachment cannot become automatic
Default until the user explicitly classifies or selects it. Prefix-only
`10.1073/pnas` is not treated as a DOI; supported PNAS line breaks and filenames
can provide a complete identifier.

## Visible import status

Background drops retain their bottom-bar status and Details/Dismiss controls.
Failed and stopped batches refresh Library, including completed placements.
Transient progress-request errors reconnect with bounded backoff while retaining
the last job; an unavailable/unauthorized job is reported as unknown rather than
as a proven worker failure. Details opens the current job without resetting it.
Non-identity failures can still stop a batch, with the failing file and partial
progress recorded. Saved Loader reports remain available after the window closes;
this change does not implement durable worker resume after an App restart.

## Correcting an assignment

Paper Files has two explicit user commands:

- **Move to Another Paper…** searches Library by title, DOI or Gewu Key and moves
  the selected resource to that paper.
- **Create Paper from File…** creates an independent paper in the current folder,
  with an editable title, a new Gewu Key and no inferred DOI.

One SQLite transaction changes ownership and folder placement, repairs old
Default/primary/analysis pointers, and records the from/to keys and original
import provenance. The resource ID, stored bytes, path, filename and classification
are retained. Existing destination metadata and a manual Default are preserved;
a new independent paper uses the selected file as Default. Historical Markdown
and source-file references are not rewritten. Errors roll back the transaction.

Reimporting the same source path/size respects explicit reassignment. A reassigned
resource leaves its former import batch; deleting that batch preserves surviving
destination papers and never trashes their referenced file or containing directory.
Files still owned by the deleted batch retain the existing rollback behavior.

The reassignment endpoint requires the private workspace session. No MCP mutation
tool was added. AI Access continues to read authorized files and append classified
Markdown only. Retrying a saved-analysis request after its file was moved returns
an unavailable-file error instead of exposing a file under a different paper.

## Validation and delivery

The full product suite passed 862 tests in 110.720 seconds using temporary data.
Focused coverage includes both import entry points, multiple same-DOI PDFs,
continued import after a collision, bytes/metadata/Default preservation, SQL
rollback, reassignment and repeat import, import-batch deletion, and MCP denial.
A final focused pass checks that removing a primary file cannot promote a
mismatched attachment through the legacy fallback path.

Headless installed Chrome exercised the real UI against temporary SQLite:
persistent partial-failure status, current-job Details, new-paper creation and
moving to an existing paper, plus narrow-width controls and Guide layout. The
first UI run exposed a missing Gewu Key in search results; the projection and
key search were corrected and the rerun passed. Six PDF structure checks ran
directly because pytest is not installed. The 103-page Guide retains all 32 real
App screenshots; changed pages and continuous Product Identity were rendered
and visually reviewed.

The original App and bundled Guide are rebuilt and signature-verified. After Mac unlock, the original App was normally relaunched and the old orphaned
backend was terminated. The new single service is healthy; the native UI shows
both reassignment commands and the imported folder. No correction command or
real import was executed during this verification. No real research
import, database repair, migration, connection change or Windows branch change
was performed. Local QA and backups remain outside Git.
