"""Private workspace sessions, separate from revocable AI credentials."""
from __future__ import annotations

import hashlib
import os
import secrets
import stat
import threading
import time
from http.cookies import SimpleCookie
from pathlib import Path


class WorkspaceAccess:
    def __init__(self, db_path: Path):
        self.path = Path(db_path).parent / '.gewu-workspace-token'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        try:
            fd = os.open(str(self.path), flags, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'w') as stream:
                stream.write(secrets.token_hex(32))
        fd = os.open(str(self.path), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'r') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or (hasattr(os, 'getuid') and info.st_uid != os.getuid()):
                raise PermissionError('Workspace credential must be a private, owned file.')
            if info.st_mode & 0o077:
                os.fchmod(stream.fileno(), 0o600)
            self.token = stream.read(128).strip()
        if len(self.token) != 64 or any(c not in '0123456789abcdef' for c in self.token):
            raise ValueError('Workspace credential is invalid. Restore its private backup before starting.')
        self.cookie_name = 'gewu_workspace_' + hashlib.sha256(str(Path(db_path).resolve()).encode()).hexdigest()[:12]
        self.bootstraps = {}
        self.lock = threading.Lock()

    def matches(self, value):
        return bool(value) and secrets.compare_digest(str(value), self.token)

    def accepts(self, headers):
        # An AI Bearer token must never gain the workspace's broader authority,
        # even if a client inadvertently sends a browser cookie alongside it.
        if headers.get('Authorization'):
            return False
        if self.matches(headers.get('X-Gewu-Workspace', '')):
            return True
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get('Cookie', ''))
            value = cookie.get(self.cookie_name)
            return bool(value and self.matches(value.value))
        except Exception:
            return False

    def cookie(self):
        return f'{self.cookie_name}={self.token}; HttpOnly; SameSite=Strict; Path=/'

    def bootstrap(self):
        with self.lock:
            self.bootstraps = {key: expiry for key, expiry in self.bootstraps.items() if expiry > time.monotonic()}
            token = secrets.token_urlsafe(32)
            self.bootstraps[token] = time.monotonic() + 60
            return token

    def consume_bootstrap(self, token):
        with self.lock:
            return self.bootstraps.pop(str(token), 0) > time.monotonic()


LOCKED_WORKSPACE_HTML = '''<!doctype html><meta charset="utf-8"><title>Gewu Insight</title>
<p id="status">Open Gewu Insight to access this workspace.</p><script>
const ticket = location.hash.startsWith('#workspace=') ? location.hash.slice(11) : '';
history.replaceState(null, '', location.pathname);
if(ticket) fetch('/api/workspace-session', {method:'POST', headers:{'X-Gewu-Bootstrap':ticket}})
 .then(r => {if(r.ok) location.reload(); else document.getElementById('status').textContent='This launch link expired. Open Gewu Insight again.';});
</script>'''
