"""User-facing article links, separate from metadata source evidence."""
import json
from urllib.parse import urlparse

from .text import normalize_doi, normalize_arxiv_identifier


METADATA_HOSTS = {'api.crossref.org', 'api.openalex.org', 'api.semanticscholar.org',
                  'api.datacite.org'}


def valid_url(value):
    value = str(value or '').strip()
    try:
        parsed = urlparse(value)
        if (parsed.scheme in {'http', 'https'} and parsed.hostname
                and not parsed.username and not parsed.password
                and not any(c.isspace() or ord(c) < 32 for c in value)):
            return value
    except ValueError:
        pass
    return ''


def website_url(paper, *, use_override=True):
    raw = paper.get('raw')
    if not isinstance(raw, dict):
        try:
            raw = json.loads(paper.get('raw_json') or '{}')
        except (TypeError, ValueError):
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    if use_override and valid_url(raw.get('website_url_override')):
        return raw['website_url_override']
    for field in ('url', 'landing_url'):
        url = valid_url(paper.get(field))
        if url and urlparse(url).hostname.lower() not in METADATA_HOSTS:
            return url
    doi = normalize_doi(paper.get('doi'))
    if doi:
        return f'https://doi.org/{doi}'
    arxiv = normalize_arxiv_identifier(raw.get('arxiv_id'))
    return f'https://arxiv.org/abs/{arxiv}' if arxiv else ''


def save_website_url(storage, paper_id, value):
    from .paper_identity import transaction
    paper_id = storage.resolve_paper_id(paper_id)
    value = str(value or '').strip()
    if value and not valid_url(value):
        raise ValueError('Enter an HTTP(S) website URL without spaces or credentials.')
    if value and urlparse(value).hostname.lower() in METADATA_HOSTS:
        raise ValueError('Use the article website or DOI link, not a metadata API URL.')
    with transaction(storage):
        paper = storage.get_paper(paper_id)
        if not paper:
            raise KeyError(paper_id)
        raw = json.loads(paper.get('raw_json') or '{}')
        if value:
            raw['website_url_override'] = value
        else:
            raw.pop('website_url_override', None)
        storage.conn.execute('UPDATE papers SET raw_json=? WHERE paper_id=?',
                             (json.dumps(raw, ensure_ascii=False), paper_id))
    return storage.get_paper(paper_id)
