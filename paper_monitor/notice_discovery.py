"""Network discovery for the desktop UI; never used by scoped MCP imports.

Crossref's `updates` filter finds notices issued after the original publication.
Only explicit outgoing DOI relations authorize linking. No title matching,
identity sweep, file replacement or automatic Default selection takes place.
"""
from __future__ import annotations

import json
from urllib.parse import quote

from . import paper_identity, publication_notices as notices
from .http import request_with_retries
from .sources.crossref import normalize_crossref_item


def normalized(item):
    if not isinstance(item, dict) or not item.get('DOI'):
        raise ValueError('Publication update service returned an invalid record')
    titles = item.get('container-title') or []
    return normalize_crossref_item(item, titles[0] if titles else '')


def fetch_record(doi):
    response = request_with_retries('GET', 'https://api.crossref.org/works/' + quote(doi, safe=''),
                                    timeout=12, max_retries=1)
    result = normalized(response.json().get('message'))
    if paper_identity.doi(result.get('doi')) != doi:
        raise ValueError('Publication update service returned a different DOI')
    return result


def fetch_updates(doi):
    """Bounded, exact-DOI lookup; incomplete pagination is reported as failure."""
    doi = paper_identity.doi(doi)
    if not doi:
        return []
    response = request_with_retries('GET', 'https://api.crossref.org/works',
        params={'filter': 'updates:' + doi, 'rows': 100}, timeout=12, max_retries=1)
    message = response.json().get('message')
    if not isinstance(message, dict) or not isinstance(message.get('items'), list):
        raise ValueError('Publication update service returned an invalid response')
    if int(message.get('total-results', len(message['items']))) > len(message['items']):
        raise ValueError('Publication updates are incomplete; retry or review the publisher record')
    result = []
    for item in message['items']:
        paper = normalized(item)
        notice = notices.describe(paper)
        # Filter results are hints, not permission to associate unrelated DOIs.
        if notice and doi in notice['related_dois'] and notice['doi'] != doi:
            result.append(paper)
    return result


def retain_updates(storage, parent, updates):
    added, conflicts = [], []
    doi = paper_identity.doi(parent.get('doi'))
    for paper in updates:
        notice = notices.describe(paper)
        if not notice or doi not in notice['related_dois'] or notice['doi'] == doi:
            continue
        try:
            with paper_identity.transaction(storage):
                if notice['related_dois'] != [doi]:
                    notices.record(storage, paper, notice)
                    conflicts.append('A publication notice names multiple originals; relation review is required.')
                    continue
                current = storage.get_paper(parent['paper_id'])
                if not current or paper_identity.doi(current.get('doi')) != doi:
                    raise notices.NoticeReviewRequired('Original DOI changed during publication update discovery.')
                existing = storage.conn.execute('SELECT id,paper_id FROM publication_notices WHERE identity=?',
                                                 ('doi:' + notice['doi'],)).fetchone()
                event_id = notices.record(storage, paper, notice, current)
                if not existing or not existing['paper_id']:
                    added.append(event_id)
        except notices.NoticeReviewRequired as exc:
            conflicts.append(str(exc))
    return added, conflicts


def resolve_for_library(storage, *, event_id=None, paper=None):
    """Explicit desktop Add: resolve the notice and save only its original work."""
    if event_id is not None:
        row = storage.conn.execute('SELECT * FROM publication_notices WHERE id=?', (event_id,)).fetchone()
        if not row:
            raise ValueError('Publication notice not found')
        paper = json.loads(row['metadata_json'])
        paper['publication_notice'] = json.loads(row['evidence_json'])
    notice = notices.describe_known(storage, paper or {})
    if not notice:
        return paper, None
    if len(notice['related_dois']) != 1 and notice['doi']:
        fresh = fetch_record(notice['doi'])
        fresh_notice = notices.describe(fresh)
        if fresh_notice:
            paper, notice = fresh, fresh_notice
    if len(notice['related_dois']) != 1 or notice['related_dois'][0] == notice['doi']:
        raise notices.NoticeReviewRequired('The notice has no unambiguous original DOI. Review its publisher relation; no independent Gewu Key was created.')
    parent = notices.target(storage, notice)
    original = None
    if parent is None:
        related = notice['related_dois'][0]
        if storage.conn.execute('SELECT 1 FROM papers WHERE lower(doi)=?', (related,)).fetchone():
            raise notices.NoticeReviewRequired('The original DOI is ambiguous or belongs to another notice; review is required.')
        original = fetch_record(related)
        if notices.describe(original):
            raise notices.NoticeReviewRequired('The supplied original DOI identifies another notice.')
    with paper_identity.transaction(storage):
        if original:
            if not storage.upsert_paper(original, commit=False):
                raise notices.NoticeReviewRequired('The original article identity requires review.')
            parent = notices.target(storage, notice)
        if not parent:
            raise notices.NoticeReviewRequired('The original article could not be identified.')
        event_id = notices.record(storage, paper, notice, parent)
    return parent, event_id


def for_monitor_date(storage, day, journals, *, field_classifier):
    """Notice events have their own display rows, never a paper ID or Gewu Key."""
    result = []
    for row in storage.conn.execute('SELECT * FROM publication_notices WHERE publication_date=? ORDER BY id', (day,)):
        metadata = json.loads(row['metadata_json'])
        if metadata.get('journal') not in journals:
            continue
        result.append({key: row[key] for key in ('id', 'kind', 'title', 'doi', 'publication_date', 'source_url', 'paper_id', 'status')})
        result[-1]['journal'] = metadata.get('journal') or ''
        # Use the original's classification once linked. Unresolved events use
        # their retained evidence without creating an identity or doing a lookup.
        parent = storage.get_paper(row['paper_id']) if row['paper_id'] else None
        result[-1]['fields'] = field_classifier(parent or metadata)
    return result
