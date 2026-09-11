"""One-shot bibliographic correction after an explicit identifier edit.

The old bibliography is retained as history. Files, user notes, classifications,
placements and canonical keys are outside this projection.
"""
import copy
import json

FIELDS = ('title', 'journal', 'publication_date', 'abstract', 'abstract_source',
          'url', 'landing_url', 'pdf_url', 'image_url', 'type', 'type_crossref',
          'publisher_section', 'section_allowed', 'semantic_scholar_json',
          'semantic_scholar_enriched_at')
RAW_FIELDS = set('''DOI doi id ids title display_name author authors authorships
    abstract abstract_inverted_index publisher container-title short-container-title
    volume issue page article-number biblio journal-issue published-print
    published-online published issued created deposited indexed ISBN ISSN type
    URL link resource reference references relation subject license funder
    crossref openalex openalex_id pubmed pmid pmcid ads google_scholar
    semantic_scholar citation_versions cited_by_count is-referenced-by-count
    counts_by_year referenced_works related_works concepts topics primary_topic
    primary_location best_oa_location locations open_access
    arxiv_id versioned_arxiv_id arxiv eprint preprint published_doi categories primary_category
    affiliations author_affiliations institutions publication_year publication_date
    metadata_source_cache metadata_refresh'''.split())


def pending(paper):
    from . import ui_server as ui
    raw = ui.parse_raw_json(paper)
    edit = raw.get('manual_identifier_correction')
    if isinstance(edit, dict):
        kind = edit.get('kind')
        prefix = 'doi' if kind == 'doi' else 'preprint'
        current = ui.normalize_publication_doi(paper.get('doi') or '') if kind == 'doi' else ui.arxiv_identifier_for_paper(paper)
        if (edit.get('status') == 'pending' and current and current == edit.get('identifier')
                and edit.get('updated_at') == raw.get('manual_' + prefix + '_identifier_updated_at')):
            return edit
        return None
    # Compatibility for an explicit DOI correction saved by the previous UI.
    # Require evidence that this saved edit replaced the bibliography's DOI;
    # an old manual flag alone must not disable later automatic conflict guards.
    doi = ui.normalize_publication_doi(paper.get('doi') or '')
    crossref = raw.get('crossref') if isinstance(raw.get('crossref'), dict) else {}
    previous = ui.normalize_publication_doi(raw.get('DOI') or raw.get('doi') or crossref.get('DOI') or '')
    history = raw.get('manual_identifier_history') or []
    last = history[-1] if isinstance(history, list) and history and isinstance(history[-1], dict) else {}
    replaced = (last.get('updated_at') == raw.get('manual_doi_identifier_updated_at')
                and ui.normalize_publication_doi(last.get('doi') or '') not in {'', doi})
    if (doi and raw.get('manual_doi_identifier_override') is True
            and raw.get('manual_doi_identifier_updated_at')
            and ((previous and previous != doi) or replaced)):
        return {'kind': 'doi', 'identifier': doi, 'previous_identifier': previous,
                'updated_at': raw['manual_doi_identifier_updated_at'], 'status': 'pending'}
    return None


def mark(raw, kind, identifier, previous, timestamp):
    last = raw.get('manual_identifier_correction') or {}
    if not previous and last.get('kind') == kind and last.get('status') == 'cleared':
        previous = last.get('previous_identifier') or ''
    raw['manual_identifier_correction'] = {
        'kind': kind, 'identifier': identifier, 'previous_identifier': previous,
        'updated_at': timestamp, 'status': ('pending' if previous else 'added') if identifier else 'cleared'}
    raw.pop('metadata_source_cache', None)


def baseline(paper, edit):
    from . import ui_server as ui
    result = copy.deepcopy(paper)
    raw = {k: v for k, v in ui.parse_raw_json(paper).items() if k not in RAW_FIELDS}
    for key in FIELDS:
        result[key] = None
    # An explicit identifier in the other row is retained. Automatic relationships
    # belonging to the old bibliography must be rediscovered from the new anchor.
    if edit['kind'] != 'doi':
        if not raw.get('manual_doi_identifier_override'):
            result['doi'] = None
        raw['arxiv_id'] = edit['identifier']
    raw['manual_identifier_correction'] = edit
    result['raw_json'] = json.dumps(raw, ensure_ascii=False)
    result['raw'] = raw
    return result


def with_history(current, incoming, edit):
    from . import ui_server as ui
    raw = copy.deepcopy(incoming.get('raw') if isinstance(incoming.get('raw'), dict) else ui.parse_raw_json(incoming))
    old_raw = copy.deepcopy(ui.parse_raw_json(current))
    history = old_raw.pop('manual_identifier_metadata_history', [])
    history.append({'edit': edit, 'metadata': {k: current.get(k) for k in ('doi', *FIELDS)},
                    'raw': old_raw})
    raw['manual_identifier_metadata_history'] = history
    raw['manual_identifier_correction'] = {**edit, 'status': 'applied', 'applied_at': ui.now_iso()}
    return {**incoming, 'raw': raw}
