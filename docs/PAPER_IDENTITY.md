# Canonical paper identity and Author Monitor deduplication

Author Monitor could previously create separate papers when a Scholar title or
pagination URL changed. Later identifier enrichment wrote the same DOI into both
records. Since each internal paper ID received its own Gewu Key, the duplicate
identities appeared as separate cards even after their metadata agreed.

All public Storage creation and metadata writers now resolve identities inside
SQLite write transactions. DOI normalization and version-independent arXiv IDs
are shared with a registry of stable Scholar `citation_for_view` identities;
pagination, sorting and page-size query parameters are not identities. Concurrent
writers recheck after obtaining the write lock. Database triggers reject new
duplicate DOI inserts or changed DOI assignments that bypass resolution.

New observations reuse an existing identity. If later enrichment connects two
existing records, reconciliation also requires positive same-work evidence and
passes the established bibliographic conflict checks. Shared source/preprint
identities, or matching normalized titles with author agreement, can establish
the relationship. A shared DOI alone does not authorize a sweep of historical
records. Different manual identifiers or competing manual Default files remain
separate for review.

The survivor prefers a record already used in Library or My Publications, then
a manual Default, then the earliest record. Old internal IDs and Gewu Keys become
aliases, including in grant-checked MCP lookup. This does not change connection
scopes, revocation, expiry or append-only file permissions. Existing analysis
receipts keep their request hash and recorded Key; identical retries still reuse
the same file after reconciliation.

Author Monitor keeps one association per author and canonical paper. Unread
state is preserved if either duplicate is unread. The same paper remains visible
under every associated author. Journal/Subject provenance, Library placements,
My Publications flags, identifier tasks, refresh histories and resources are
repointed in the same transaction. Duplicate relationships combine their flags,
timestamps and source evidence. Cached cards are invalidated. File IDs, paths,
bytes, classification and manual Default are preserved; reconciliation performs
no file I/O. Legacy file paths without resource registrations block a merge.
Older installations may retain `journal_feed_entries`; its feed membership and
first/last-seen history are included in review fingerprints and preserved too.

Schema 19 adds identifier ownership, aliases and an identity history containing
the original records and relationships. Startup does not merge legacy records.
Unknown foreign-key relationships abort reconciliation rather than cascade-delete
unreviewed data. Historical reconciliation is explicitly planned, backed up and
applied; each group is fingerprinted, revalidated under a write lock and rolled
back on any failure. Database backup remains the recovery baseline; history is
an audit record, not a promise of an automatic undo UI.

For authorized maintenance, stop the original App and use
`scripts/reconcile_paper_identities.py`: `--db PATH --plan NEW_PLAN` is read-only;
`--db PATH --apply REVIEWED_PLAN --backup NEW_PRIVATE_BACKUP` performs the
transaction. The plan includes DOI groups involving Author Monitor and may reuse
their existing Library/My Publications identity. Blocked groups remain unchanged.
Neither mode reads paper contents or contacts Scholar. Backups may contain private
database information and must remain local, outside Git and shared artifacts.

Regression coverage includes repeated Scholar pagination/typography, later DOI
and arXiv completion, concurrent writers, source conflicts, old-ID bulk operations,
all Monitor relationships, file/default preservation, stale-plan/unknown-FK
rollback, migration without a sweep and MCP scope/idempotency.
