# Publication notices and article identity

Corrections, errata, corrigenda, retraction notices, expressions of concern,
withdrawal notices and addenda describe an existing work. Their own DOI is
retained as **notice metadata**, not registered as the original article's DOI
or assigned a separate research-paper Gewu Key. A corrected full article remains
a publication version; an ordinary commentary or reply remains a distinct work.
The word “correction” inside a research title is not sufficient for classification.

## Import and discovery

The shared storage entry points guard against creating a research paper from
an explicit notice title/type or an outgoing Crossref `update-to` relation.
`is_retracted` and `update-by` describe the original work and do not turn it into
a notice. No title similarity matching is used to find the original.

Browser and Loader attach notices when an explicit original DOI resolves to one
existing article. Otherwise evidence is retained with `needs_relation` status;
Loader also retains the file and reports a relation-review warning instead of
creating a paper. The source file is preserved. A subsequent local Loader import
with the verified relation can associate the retained file with the original.
This is not a background cleanup or an automatic network lookup.

MCP imports continue to require AI-supplied metadata. In addition, notices need:

```json
"publication_notice": {
  "kind": "correction_notice",
  "related_dois": ["10.5555/original-article"],
  "evidence_url": "https://publisher.example/notice"
}
```

The surrounding `metadata.doi`, `title` and `publication_date` describe the
notice itself. The original article must already exist in a writable collection.
Missing, ambiguous, self-referential or unauthorized targets fail with an
actionable error and leave the upload available for retry. Import never invokes
Resolve, PDF identifier extraction or network enrichment. For multi-article
notices, review the relation explicitly; import does not guess a single target.

The result uses the **original** Gewu Key and includes `publication_notice_id`.
Notice PDFs use their notice classification even if the caller requests
`published_version`. They go in Associated Files and do not become an automatic
Default, including when the original has no local article PDF. Existing article
bytes cannot be reclassified as a notice by importing the same bytes again.
Ordinary attachment APIs still accept a notice already assigned to an explicit
paper, using the corresponding notice file type.

`get_paper.publication_notices` and the Paper Files panel expose the notice's
title, DOI, date, kind and associated files. A retraction notice stays attached
to the original; the original article, its bibliography and files are retained.
The notice is evidence of the reported publication event, not a deletion command.

## Storage and historical compatibility

Schema 22 adds `publication_notices` and `publication_notice_files`. It does not
scan, merge, delete or reclassify historical records on startup. Notice metadata
and relationship evidence are separate from canonical paper identifiers.

`publication_notices.rehome_legacy` is an explicit maintenance operation for a
verified erroneous notice object. It requires the original DOI, exact notice
PDF IDs, a database backup and rehearsal before applying it to a real library.
It preserves resource IDs and bytes, saved analysis provenance, article metadata
and Default; placements remain on the original article. The retired paper ID
and Gewu Key become aliases, so saved notes and authorized old-Key requests
remain resolvable. A snapshot in `paper_identity_history` retains the source
record, relation state and placement mapping. Unknown relationships stop repair.
Managed file layout must then be reconciled through the existing layout service.

No bulk historical repair is part of installation. Independent research
installations receive software only unless their owner separately authorizes
a specific data repair.

The relationship model follows [Crossref's update metadata](https://www.crossref.org/documentation/register-maintain-records/maintaining-your-metadata/registering-updates/):
a notice has its own DOI and explicitly identifies the work it updates.
