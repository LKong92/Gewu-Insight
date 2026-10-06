"""Metadata-only transport policy; ordinary downloads and Scholar are unchanged."""
from contextlib import contextmanager
from contextvars import ContextVar
from email.utils import parsedate_to_datetime
import json
import threading
import time
from urllib.parse import urlsplit

_CONTEXT = ContextVar('gewu_metadata_network', default=None)
_LOCK = threading.Lock()
_NEXT = {}
_BLOCKED = {}
SETTING = 'metadata_source_cooldowns'
INTERVALS = {'Crossref': 1.0, 'OpenAlex': 1.0, 'Semantic Scholar': 1.1,
             'arXiv': 3.2, 'PubMed': .35, 'ADS': 1.0, 'DataCite': 1.0}


class SourceCoolingDown(RuntimeError):
    def __init__(self, source, retry_at, response=None):
        super().__init__(f'{source} is cooling down; retry after {time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(retry_at))}.')
        self.source, self.retry_at, self.response = source, retry_at, response


def provider(url):
    host = (urlsplit(url).hostname or '').lower()
    for domain, name in [('crossref.org', 'Crossref'), ('openalex.org', 'OpenAlex'),
                         ('semanticscholar.org', 'Semantic Scholar'), ('arxiv.org', 'arXiv'),
                         ('ncbi.nlm.nih.gov', 'PubMed'), ('adsabs.harvard.edu', 'ADS'),
                         ('datacite.org', 'DataCite')]:
        if host == domain or host.endswith('.' + domain):
            return name
    return ''


@contextmanager
def scope(storage):
    token = _CONTEXT.set({'storage': storage, 'blocked': {}, 'errors': {}})
    try:
        yield _CONTEXT.get()
    finally:
        _CONTEXT.reset(token)


def before_request(url):
    context = _CONTEXT.get()
    if context is None:
        return
    name = provider(url)
    if not name:
        return
    try:
        saved = json.loads(context['storage'].get_setting(SETTING, '{}'))
    except (ValueError, TypeError):
        saved = {}
    with _LOCK:
        now = time.time()
        until = max(float(saved.get(name, 0)), _BLOCKED.get(name, 0))
        if until > now:
            context['blocked'][name] = until
            raise SourceCoolingDown(name, until)
        wait = max(0, _NEXT.get(name, 0) - time.monotonic())
        _NEXT[name] = time.monotonic() + wait + INTERVALS[name]
    if wait:
        time.sleep(wait)


def after_response(response):
    context = _CONTEXT.get()
    if context is None:
        return
    name = provider(response.url)
    if not name or response.status_code not in (429, 503):
        return
    header = response.headers.get('Retry-After', '')
    if response.status_code == 503 and not header:
        return
    now = time.time()
    try:
        until = now + max(0, float(header))
    except (ValueError, TypeError):
        try:
            until = parsedate_to_datetime(header).timestamp()
        except (ValueError, TypeError, OverflowError):
            until = now + 300  # Local fallback, not a claimed provider quota.
    until = max(now + 1, until)
    with _LOCK:
        _BLOCKED[name] = max(_BLOCKED.get(name, 0), until)
        storage = context['storage']
        try:
            saved = json.loads(storage.get_setting(SETTING, '{}'))
        except (ValueError, TypeError):
            saved = {}
        saved[name] = max(float(saved.get(name, 0)), until)
        storage.set_setting(SETTING, json.dumps(saved))
    context['blocked'][name] = until
    raise SourceCoolingDown(name, until, response)


def after_error(url, error):
    context = _CONTEXT.get()
    if context is None:
        return
    name = provider(url)
    if name and getattr(getattr(error, 'response', None), 'status_code', None) != 404:
        context['errors'][name] = True
