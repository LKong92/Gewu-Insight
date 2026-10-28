"""Read-only discovery of an authenticated service for the selected Windows DB."""
from __future__ import annotations
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def live_status(root, expected_identity):
    """Never start a service, create data, repair paths, or follow redirects."""
    root = Path(root).resolve()
    try:
        address = (root / 'data/.gewu-api-url').read_text(encoding='utf-8').strip()
        url = urlsplit(address)
        if (url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port
                or url.username or url.password or url.path not in {'', '/'} or url.query or url.fragment):
            return None
        token = (root / 'data/.gewu-workspace-token').read_text(encoding='ascii').strip()
        if not re.fullmatch('[a-f0-9]{64}', token):
            return None
        request = Request(address.rstrip('/') + '/api/health', headers={'X-Gewu-Workspace': token})
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=2) as response:
            data = json.loads(response.read(65537))
        if (not isinstance(data, dict) or not isinstance(data.get('integrations'), dict)
                or not data.get('ok') or not expected_identity or data.get('database_uuid') != expected_identity
                or Path(data.get('database_path', '')).resolve() != root / 'data/paper_monitor.sqlite'
                or data.get('integrations', {}).get('zotero') != 1):
            return None
        return dict(data, origin=address.rstrip('/'))
    except (OSError, ValueError, TypeError):
        return None
