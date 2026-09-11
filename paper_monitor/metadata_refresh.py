"""Paper-level metadata refresh and low-frequency publication checks.

Only bibliographic evidence changes. No file, placement, Default or identity merge
is performed here. Network work precedes writes and repeated requests coalesce.
"""
from __future__ import annotations

from concurrent.futures import Future
from datetime import datetime, timedelta
import copy
import json
import threading
from pathlib import Path
from contextlib import contextmanager
import itertools
from . import metadata_network

_ACTIVE = {}
_LOCK = threading.Lock()
_QUEUE = threading.Condition()
_WAITING = []
_RUNNING = set()
_SEQUENCE = itertools.count()
PRIORITY = {'single': 0, 'import': 10, 'batch': 20, 'automatic': 30}
FIELDS = 'paperId,externalIds,title,abstract,venue,year,publicationDate,journal,authors,citationCount,referenceCount,influentialCitationCount,isOpenAccess,openAccessPdf,fieldsOfStudy,s2FieldsOfStudy,publicationTypes,tldr'
MARKER = 'metadata_refresh'


def api():
    from . import ui_server
    return ui_server


def marker(paper):
    value = api().parse_raw_json(paper).get(MARKER)
    return value if isinstance(value, dict) else {}


def valid_doi(value):
    ui = api()
    value = ui.normalize_publication_doi(str(value or ''))
    return value if ui.looks_like_doi(value) else ''


def identifiers(paper):
    return valid_doi(paper.get('doi')), api().arxiv_identifier_for_paper(paper)


def linked_arxiv(record):
    """Inspect hosting locations and explicit preprint relations, never references."""
    ui = api()
    found = set()
    locations = list(record.get('locations') or [])
    locations += [record.get('primary_location') or {}, record.get('best_oa_location') or {}]
    for item in locations:
        for key in ('landing_page_url', 'pdf_url'):
            url = str(item.get(key) or '') if isinstance(item, dict) else ''
            if ui.urlparse(url).hostname in {'arxiv.org', 'www.arxiv.org', 'export.arxiv.org'}:
                value = ui.normalize_arxiv_identifier(url)
                if value:
                    found.add(value)
    relation = record.get('relation') or {}
    for item in relation.get('has-preprint', []) if isinstance(relation, dict) else []:
        value = str(item.get('id') or '')
        if item.get('id-type') in {'arxiv', 'arXiv'} or 'arxiv.org/' in value.lower() or ui.doi_is_arxiv_preprint_doi(value):
            value = ui.normalize_arxiv_identifier(value)
            if value:
                found.add(value)
    return found


def is_due(paper, now=None):
    now = now or datetime.now().astimezone()
    stamp = marker(paper).get('next_check_at')
    if not stamp:
        return True
    try:
        due = datetime.fromisoformat(stamp)
        if due.tzinfo is None:
            due = due.replace(tzinfo=now.tzinfo)
        return due <= now
    except ValueError:
        return True


def saved_candidates(storage):
    # Library, Spaces and shortcuts share library_items. Exclude every descendant
    # of Recycle, including older rows without an individual trashed_at marker.
    rows = storage.conn.execute('''
        WITH RECURSIVE recycled(id) AS (
          SELECT id FROM library_folders WHERE name = 'Recycle' AND parent_id = 1
          UNION SELECT f.id FROM library_folders f JOIN recycled r ON f.parent_id = r.id
        )
        SELECT p.* FROM papers p WHERE
          EXISTS (SELECT 1 FROM my_publications m WHERE m.paper_id = p.paper_id)
          OR EXISTS (SELECT 1 FROM library_items i JOIN library_folders f ON f.id = i.folder_id
            WHERE i.paper_id = p.paper_id AND COALESCE(i.trashed_at, '') = ''
              AND COALESCE(f.trashed_at, '') = '' AND f.id NOT IN (SELECT id FROM recycled))
    ''')
    # Keep only scheduling/identifier fields in memory. Full source payloads for
    # thousands of saved papers must not remain resident in the background queue.
    papers = []
    for row in rows:
        paper = dict(row)
        doi, arxiv = identifiers(paper)
        if doi or arxiv:
            papers.append({'paper_id': paper['paper_id'], 'doi': doi, 'preprint_id': arxiv,
                           'publication_date': paper.get('publication_date'),
                           'raw_json': json.dumps({MARKER: marker(paper)})})
    papers.sort(key=lambda p: (str(p.get('publication_date') or ''), p['paper_id']), reverse=True)
    return sorted(papers, key=lambda p: marker(p).get('checked_at', ''))


def recently_completed(storage, paper_id, mode, skip_days=3):
    if skip_days <= 0:
        return False
    modes = ('full',) if mode == 'full' else ('full', 'quick')
    cutoff = (datetime.now().astimezone() - timedelta(days=skip_days)).isoformat(timespec='seconds')
    paper = storage.get_paper(paper_id)
    if not paper:
        return False
    identity = list(identifiers(paper))
    rows = storage.conn.execute(
        'SELECT source_summary FROM paper_metadata_refreshes WHERE paper_id=? AND status="completed" '
        'AND mode IN (' + ','.join('?' for _ in modes) + ') AND finished_at >= ?',
        (paper_id, *modes, cutoff))
    for row in rows:
        try:
            saved = json.loads(row[0])
        except (ValueError, TypeError):
            # The former batch worker stored the checked primary identifier.
            # Retain its cooldown only while that same identifier is still saved.
            primary = identity[0] or identity[1]
            if primary and str(row[0] or '') == primary:
                return True
            continue
        if isinstance(saved, dict) and saved.get('identifiers') == identity:
            return True
    return False


@contextmanager
def queue_slot(key, pending):
    # The caller retains ownership of its SQLite connection. Priority applies at
    # paper boundaries; no remote request or database write is interrupted.
    db = key[0]
    with _QUEUE:
        ticket = [pending, next(_SEQUENCE), db]
        _WAITING.append(ticket)
        while db in _RUNNING or min((t for t in _WAITING if t[2] == db),
                                   key=lambda t: (t[0].priority, t[1])) is not ticket:
            _QUEUE.wait()
        _WAITING.remove(ticket)
        _RUNNING.add(db)
    try:
        yield
    finally:
        with _QUEUE:
            _RUNNING.remove(db)
            _QUEUE.notify_all()


def refresh(storage, paper_id, *, detailed=True, identifier='', mode=None,
            origin='single', skip_days=0):
    mode = mode or ('full' if detailed else 'automatic')
    if mode not in {'full', 'quick', 'automatic'}:
        raise ValueError('Unknown metadata refresh mode')
    detailed = mode == 'full'
    key = (str(Path(storage.db_path).resolve()), str(paper_id))
    with _LOCK:
        pending = _ACTIVE.get(key)
        if pending is None:
            pending = Future()
            pending.identifier = str(identifier or '')
            pending.priority = PRIORITY.get(origin, 20)
            _ACTIVE[key] = pending
            owner = True
        else:
            pending.priority = min(pending.priority, PRIORITY.get(origin, 20))
            owner = False
    if not owner:
        # Each caller owns its SQLite connection; only plain results cross threads.
        result = copy.deepcopy(pending.result())
        levels = {'automatic': 0, 'quick': 1, 'full': 2}
        if (levels[mode] > levels.get(result['metadata_refresh'].get('mode', 'automatic'), 0)
                or str(identifier or '') != pending.identifier
                or (skip_days <= 0 and result['metadata_refresh']['status'] == 'skipped_recent')):
            with _LOCK:
                if _ACTIVE.get(key) is pending:
                    _ACTIVE.pop(key, None)
            return refresh(storage, paper_id, mode=mode, identifier=identifier, origin=origin, skip_days=skip_days)
        return result
    try:
        with queue_slot(key, pending):
            if not identifier and mode != 'automatic' and recently_completed(storage, paper_id, mode, skip_days):
                paper = storage.get_paper(paper_id)
                result = {'paper': paper, 'metadata_refresh': {**marker(paper), 'mode': mode,
                          'status': 'skipped_recent', 'changed_fields': [], 'message': 'Checked recently; skipped.'}}
            else:
                ui = api()
                history = ui.record_metadata_refresh_start(storage, paper_id=paper_id, mode=mode, source_summary=origin)
                try:
                    with metadata_network.scope(storage) as network:
                        result = _refresh(storage, str(paper_id), detailed=detailed, identifier=identifier,
                                          mode=mode, reuse_days=skip_days, network=network)
                    report = result['metadata_refresh']
                    storage.conn.execute('UPDATE paper_metadata_refreshes SET source_summary=? WHERE id=?',
                        (json.dumps({'origin': origin, 'identifiers': list(identifiers(result['paper']))}), history))
                    ui.record_metadata_refresh_finish(storage, history,
                        status='completed' if report['status'] in {'updated', 'unchanged'} else report['status'],
                        error=report['message'] if report['status'] == 'partial' else '')
                except BaseException as exc:
                    ui.record_metadata_refresh_finish(storage, history, status='failed', error=str(exc))
                    raise
        pending.set_result(copy.deepcopy(result))
        return result
    except BaseException as exc:
        pending.set_exception(exc)
        raise
    finally:
        with _LOCK:
            if _ACTIVE.get(key) is pending:
                _ACTIVE.pop(key, None)


def _refresh(storage, paper_id, *, detailed, identifier, mode, reuse_days, network):
    ui = api()
    original = storage.get_paper(paper_id)
    if not original:
        raise KeyError('Paper not found')
    doi, arxiv = identifiers(original)
    if identifier:  # Compatibility for explicit identifier recovery callers.
        supplied_doi = valid_doi(identifier)
        supplied_arxiv = ui.normalize_arxiv_identifier(identifier) if not supplied_doi else ''
        if not supplied_doi and not supplied_arxiv:
            raise ValueError('A valid DOI or arXiv ID is required')
        if supplied_doi:
            if doi and doi != supplied_doi and ui.doi_is_likely_published_version(doi):
                raise ValueError('The recovered DOI differs from the saved DOI. Correct the DOI field explicitly before refreshing.')
            if storage.conn.execute('SELECT 1 FROM papers WHERE lower(doi) = ? AND paper_id <> ?', (supplied_doi, paper_id)).fetchone():
                raise ValueError('The recovered DOI belongs to another Gewu Key. Existing records were preserved.')
            doi = supplied_doi
        else:
            arxiv = supplied_arxiv
    if not doi and not arxiv:
        raise ValueError('Add a DOI or arXiv ID, or use Get Identifier from Files first.')
    raw = copy.deepcopy(ui.parse_raw_json(original))
    manual_doi = raw.get('manual_doi_identifier_override') is True
    manual_arxiv = raw.get('manual_preprint_identifier_override') is True
    working = dict(original)
    working['doi'] = doi
    working['raw'] = raw
    sources, conflicts = {}, []
    cache = copy.deepcopy(raw.get('metadata_source_cache') or {})
    reused = []
    fetched_dois, fetched_arxiv = set(), set()
    arxiv_record = None
    semantic = None

    def lookup(name, call):
        identity = json.dumps([doi, arxiv])
        # Successful basic records are usable by Full. Semantic Scholar requests
        # carry different field sets and therefore need a mode-specific cache.
        cache_key = name + (':' + mode if name.startswith('Semantic Scholar') else '')
        previous = cache.get(cache_key) or {}
        now = datetime.now().astimezone()
        try:
            fresh = datetime.fromisoformat(previous['checked_at']) >= now - timedelta(days=reuse_days)
        except (ValueError, KeyError, TypeError):
            fresh = False
        if reuse_days > 0 and name != 'Publication metadata' and fresh and previous.get('identity') == identity:
            sources[name] = previous['status']
            reused.append(name)
            return copy.deepcopy(previous.get('value'))
        try:
            result = call()
            sources[name] = 'found' if result else 'not_found'
            if name != 'Publication metadata':
                cache[cache_key] = {'checked_at': now.isoformat(), 'identity': identity,
                                    'value': result, 'status': sources[name]}
            return result
        except Exception as exc:
            code = getattr(getattr(exc, 'response', None), 'status_code', None)
            limited = isinstance(exc, metadata_network.SourceCoolingDown) or code == 429 or 'rate limit' in str(exc).lower() or 'HTTP 429' in str(exc)
            sources[name] = 'not_found' if code == 404 else ('rate_limited' if limited else 'unavailable')
            if code == 404:
                cache[cache_key] = {'checked_at': now.isoformat(), 'identity': identity, 'value': None, 'status': 'not_found'}
            else:
                cache.pop(cache_key, None)
            return None

    def accept_doi(candidate, evidence):
        nonlocal doi
        candidate = valid_doi(candidate)
        if not candidate or not ui.doi_is_likely_published_version(candidate) or candidate == doi:
            return
        if manual_doi or ui.doi_is_likely_published_version(doi):
            conflicts.append(f'{evidence}: candidate DOI {candidate} differs; existing value retained')
            return
        other = storage.conn.execute('SELECT paper_id FROM papers WHERE lower(doi) = ? AND paper_id <> ? LIMIT 1', (candidate, paper_id)).fetchone()
        if other:
            conflicts.append(f'{evidence}: candidate DOI {candidate} belongs to another Gewu Key; existing records retained')
            return
        doi = candidate
        working['doi'] = candidate
        raw['published_doi'] = candidate

    def accept_arxiv(values, evidence):
        nonlocal arxiv
        values = {ui.normalize_arxiv_identifier(str(v)) for v in values} - {''}
        if len(values) != 1:
            if len(values) > 1:
                conflicts.append(f'{evidence}: multiple arXiv candidates; existing value retained')
            return
        candidate = next(iter(values))
        if candidate == arxiv:
            return
        if manual_arxiv or arxiv:
            conflicts.append(f'{evidence}: candidate arXiv {candidate} differs; existing value retained')
            return
        arxiv = candidate
        raw.update(ui.ensure_raw_preprint_metadata(raw, arxiv))

    def fetch_preprint():
        nonlocal arxiv_record
        if not arxiv or arxiv in fetched_arxiv:
            return
        fetched_arxiv.add(arxiv)
        record = lookup('arXiv', lambda: ui.fetch_arxiv_by_id(arxiv, timeout=12, max_retries=1))
        if not record:
            return
        record_raw = record.get('raw') or {}
        returned_id = ui.normalize_arxiv_identifier(str(record_raw.get('arxiv_id') or record_raw.get('versioned_arxiv_id') or ''))
        if returned_id != arxiv:
            conflicts.append('arXiv returned a different identifier; result ignored')
            return
        arxiv_record = record
        raw.update(ui.attach_arxiv_preprint_metadata({'doi': doi, 'raw': raw}, record)['raw'])
        if not ui.doi_is_likely_published_version(doi):
            for field in ('title', 'journal', 'publication_date', 'abstract', 'abstract_source', 'url', 'landing_url', 'pdf_url', 'source', 'type'):
                if record.get(field):
                    working[field] = record[field]
        accept_doi(record.get('doi'), 'arXiv')

    def fetch_published():
        if not doi or doi in fetched_dois:
            return
        fetched_dois.add(doi)
        normalized = lookup('Publication metadata', lambda: ui.publication_metrics_metadata_from_doi(doi, timeout=12, max_retries=1, allow_data_repository=ui.doi_is_likely_data_repository(doi), source_status=sources, source_lookup=lookup))
        if not normalized:
            return
        if valid_doi(normalized.get('doi')) != doi:
            conflicts.append('Metadata service returned a different DOI; result ignored')
            return
        fresh_raw = normalized.get('raw') or {}
        accept_arxiv(linked_arxiv(fresh_raw) | linked_arxiv(fresh_raw.get('crossref') or {}), 'Crossref / OpenAlex')
        for field in ('title', 'journal', 'publication_date', 'abstract', 'abstract_source', 'url', 'landing_url', 'pdf_url', 'source', 'type', 'type_crossref', 'publisher_section', 'section_allowed', 'image_url'):
            if normalized.get(field) not in (None, '', [], {}):
                working[field] = normalized[field]
        raw.update(fresh_raw)
        if arxiv_record:
            raw.update(ui.attach_arxiv_preprint_metadata({'doi': doi, 'raw': raw}, arxiv_record)['raw'])

    fetch_preprint()
    initial_doi = identifiers(original)[0]
    # A periodic check only loads the full DOI record if a publication was found,
    # or if its other identifier is missing. Explicit Refresh always loads it.
    if mode != 'automatic' or doi != initial_doi or not arxiv:
        fetch_published()
    refs = ([f'DOI:{doi}'] if doi else []) + ([f'ARXIV:{arxiv}'] if arxiv else [])
    for ref in refs:
        if not detailed and doi and arxiv:
            break
        fields = FIELDS if detailed else 'paperId,externalIds,title,abstract,venue,year,publicationDate,authors'
        record = lookup('Semantic Scholar ' + ref.split(':')[0], lambda ref=ref: ui.semantic_scholar_request('GET', f'https://api.semanticscholar.org/graph/v1/paper/{ui.quote(ref, safe="")}', params={'fields': fields}, timeout=12, max_retries=1).json())
        if not record:
            continue
        external = record.get('externalIds') or {}
        rd = valid_doi(external.get('DOI'))
        ra = ui.normalize_arxiv_identifier(str(external.get('ArXiv') or external.get('arXiv') or ''))
        if not ((ref.startswith('DOI:') and rd == doi) or (ref.startswith('ARXIV:') and ra == arxiv)):
            conflicts.append('Semantic Scholar identifier mismatch; result ignored')
            continue
        if (doi and rd and rd != doi and ui.doi_is_likely_published_version(doi)) or (arxiv and ra and ra != arxiv):
            conflicts.append('Semantic Scholar identifiers disagree; existing values retained')
            continue
        semantic = record if detailed else None
        accept_doi(rd, 'Semantic Scholar')
        accept_arxiv([ra], 'Semantic Scholar')
        if not working.get('abstract') and record.get('abstract'):
            working.update(abstract=record['abstract'], abstract_source='semantic_scholar')

    # Title searches can propose candidates, but only an explicit hosting link to
    # this arXiv ID authorizes an automatic DOI fill.
    if arxiv and not ui.doi_is_likely_published_version(doi) and working.get('title'):
        result = lookup('OpenAlex linked publication', lambda: ui.openalex_request('GET', 'https://api.openalex.org/works', params={'search': working['title'], 'per-page': 5}, timeout=12, max_retries=1).json())
        choices = {valid_doi(r.get('doi')) for r in (result or {}).get('results', []) if arxiv in linked_arxiv(r)} - {''}
        if len(choices) == 1:
            accept_doi(next(iter(choices)), 'OpenAlex linked location')
        elif len(choices) > 1:
            conflicts.append('OpenAlex returned multiple publication DOIs; existing value retained')
    fetch_preprint()
    if mode != 'automatic' or doi != initial_doi:
        fetch_published()
    if detailed or (arxiv and not ui.doi_is_likely_published_version(doi)):
        token = ui.ads_api_token(storage)
        if token:
            query = doi or arxiv
            ads = lookup('ADS', lambda: ui.fetch_ads_record_by_identifier(query, token, timeout=12, max_retries=1))
            if ads:
                ads_dois = {valid_doi(v) for v in ads.get('doi', [])} - {''}
                ads_arxiv = {ui.normalize_arxiv_identifier(str(v)) for v in ads.get('identifier', []) if 'arxiv' in str(v).lower()} - {''}
                if (doi and doi in ads_dois) or (arxiv and arxiv in ads_arxiv):
                    raw['ads'] = ads
                    published_dois = {v for v in ads_dois if ui.doi_is_likely_published_version(v)}
                    if len(published_dois) == 1:
                        accept_doi(next(iter(published_dois)), 'ADS')
                    accept_arxiv(ads_arxiv, 'ADS')
                else:
                    conflicts.append('ADS identifiers disagree; result ignored')
        else:
            sources['ADS'] = 'not_configured'
    fetch_preprint()
    if mode != 'automatic' or doi != initial_doi:
        fetch_published()
    if detailed and doi:
        pubmed = lookup('PubMed', lambda: ui.pubmed_metadata_from_doi(doi, timeout=12, max_retries=1))
        if pubmed:
            raw['pubmed'] = pubmed
            for field in ('pmid', 'pmcid'):
                if pubmed.get(field):
                    raw[field] = pubmed[field]
            if not working.get('abstract') and pubmed.get('abstract'):
                working.update(abstract=pubmed['abstract'], abstract_source='pubmed')
    working['doi'] = doi
    if arxiv and not manual_arxiv:
        raw.update(ui.ensure_raw_preprint_metadata(raw, arxiv))
    working['raw'] = raw
    current = storage.get_paper(paper_id)
    if not current:
        raise KeyError('Paper was removed during refresh')
    manual_keys = ('manual_doi_identifier_updated_at', 'manual_preprint_identifier_updated_at')
    if identifiers(current) != identifiers(original) or any(ui.parse_raw_json(current).get(k) != ui.parse_raw_json(original).get(k) for k in manual_keys):
        raise ValueError('Identifiers changed during refresh. Refresh again with the saved values.')
    # Preserve concurrent notes/provenance and manual edits; remote payloads may
    # never replace the entire raw record or stored file ownership.
    working['raw'] = {**ui.parse_raw_json(current), **{k: v for k, v in raw.items() if ui.parse_raw_json(original).get(k) != v}}
    def projection(paper):
        fields = {k: paper.get(k) for k in ('doi', 'title', 'journal', 'publication_date', 'abstract')}
        record = ui.parse_raw_json(paper)
        fields.update(arxiv=identifiers(paper)[1], authors=ui.full_author_names(paper),
                      volume=ui.paper_volume(paper), pages=ui.paper_page(paper),
                      citations=[record.get('cited_by_count'), record.get('is-referenced-by-count'),
                                 ui.parse_semantic_scholar_json(paper).get('citationCount')])
        return fields
    before = projection(current)
    merged = ui.merge_refreshed_metadata(current, working)
    linked_preprint = arxiv if doi != initial_doi and arxiv and raw.get('published_doi') == doi else ''
    reference = storage.metadata_refresh_identity_reference(current, merged, linked_preprint_id=linked_preprint)
    reasons = storage.paper_identity_conflict_reasons(reference, merged)
    if reasons:
        conflicts.append('Metadata disagrees with existing identity (' + ', '.join(reasons) + '); existing values retained')
        updated = current
    else:
        updated = storage.refresh_paper_metadata(paper_id, merged, linked_preprint_id=linked_preprint) or current
        if semantic:
            updated = storage.update_semantic_scholar_enrichment(paper_id, semantic) or updated
    after = projection(updated)
    changed = [k for k in before if (before[k] or '') != (after[k] or '')]
    for name in network.get('errors', {}):
        sources[name] = 'unavailable'
    for name in network['blocked']:
        sources[name] = 'rate_limited'
    # Helpers may return a partial record after catching a transport failure.
    # Do not cache that as a complete successful source response.
    for name in set(network.get('errors', {})) | set(network['blocked']):
        cache = {key: value for key, value in cache.items() if not key.startswith(name)}
    failures = [name for name, status in sources.items() if status in {'unavailable', 'rate_limited'}]
    if mode != 'automatic' and doi and sources.get('Publication metadata') == 'not_found':
        failures.append('Publication metadata')
    if not any(status == 'found' for status in sources.values()):
        failures = failures or [name for name, status in sources.items() if status != 'not_configured']
    status = 'partial' if failures or conflicts else ('updated' if changed else 'unchanged')
    previous = marker(current)
    quiet = 0 if changed else int(previous.get('unchanged_checks', 0)) + 1
    now = datetime.now().astimezone()
    labels = {'doi': 'DOI', 'arxiv': 'arXiv', 'title': 'title', 'journal': 'journal', 'publication_date': 'publication date', 'abstract': 'abstract'}
    message = ('Updated ' + ', '.join(labels.get(k, k) for k in changed) + '.') if changed else 'No new metadata found.'
    if failures:
        message += ' Some sources were unavailable or returned no usable record.'
    if conflicts:
        message += ' Conflicting evidence was retained for review; existing identifiers were preserved.'
    report = {'status': status, 'message': message, 'changed_fields': changed, 'sources': sources,
              'conflicts': list(dict.fromkeys(conflicts)), 'checked_at': now.isoformat(timespec='microseconds'),
              'next_check_at': (now + timedelta(days=1 if failures else (30 if quiet >= 3 else 7))).isoformat(timespec='seconds'),
              'unchanged_checks': quiet, 'detailed': detailed, 'mode': mode,
              'reused_sources': sorted(set(reused)), 'source_retry_at': network['blocked']}
    final_raw = ui.parse_raw_json(updated)
    final_raw[MARKER] = report
    final_raw['metadata_source_cache'] = cache
    updated = storage.update_paper_raw_json(paper_id, final_raw) or updated
    return {'paper': updated, 'metadata_refresh': report}


def save_doi(storage, paper_id, value):
    ui = api()
    current = storage.get_paper(paper_id)
    if not current:
        raise KeyError('Paper not found')
    doi = valid_doi(value)
    if str(value or '').strip() and not doi:
        raise ValueError('Enter a valid DOI or DOI URL. Use the arXiv row for an arXiv ID.')
    if doi == valid_doi(current.get('doi')):
        return current
    if doi and storage.conn.execute('SELECT 1 FROM papers WHERE lower(doi) = ? AND paper_id <> ?', (doi, paper_id)).fetchone():
        raise ValueError('This DOI is already registered to another Gewu Key. Existing papers were not changed.')
    raw = ui.parse_raw_json(current)
    raw.update(manual_doi_identifier_override=True, manual_doi_identifier=doi,
               manual_doi_identifier_updated_at=ui.now_iso())
    # Retire URLs for the explicitly replaced DOI from the current projection,
    # while retaining them as history. Local file paths are never changed.
    old_doi = valid_doi(current.get('doi'))
    retired = {key: current[key] for key in ('url', 'landing_url', 'pdf_url')
               if old_doi and storage._identity_url_doi(current.get(key)) == old_doi}
    if retired:
        raw.setdefault('manual_identifier_history', []).append({'doi': old_doi, 'urls': retired, 'updated_at': ui.now_iso()})
    assignments = ', '.join(key + ' = NULL' for key in retired)
    with storage.conn:
        storage.conn.execute('UPDATE papers SET doi = ?, raw_json = ?, last_seen_at = ?' + (', ' + assignments if assignments else '') + ' WHERE paper_id = ?',
                             (doi or None, json.dumps(raw, ensure_ascii=False), ui.now_iso(), paper_id))
    return storage.get_paper(paper_id)
