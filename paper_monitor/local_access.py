"""Private workspace sessions, separate from revocable AI credentials."""
from __future__ import annotations

import hashlib
import os
import secrets
import stat
import threading
import time
import sys
from http.cookies import SimpleCookie
from pathlib import Path


def _windows_user():
    import win32api, win32con, win32security
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        return win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()


def _create_windows_token_stream(path):
    """Create with an explicit user owner/DACL, before any secret is written."""
    import msvcrt
    import pywintypes, win32con, win32file, win32security, ntsecuritycon
    user = _windows_user()
    acl = win32security.ACL()
    acl.AddAccessAllowedAce(win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, user)
    descriptor = win32security.SECURITY_DESCRIPTOR()
    descriptor.SetSecurityDescriptorOwner(user, False)
    descriptor.SetSecurityDescriptorDacl(True, acl, False)
    descriptor.SetSecurityDescriptorControl(win32security.SE_DACL_PROTECTED, win32security.SE_DACL_PROTECTED)
    attributes = pywintypes.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = descriptor
    handle = win32file.CreateFile(str(path), ntsecuritycon.FILE_ALL_ACCESS, 0, attributes,
        win32con.CREATE_NEW, win32con.FILE_ATTRIBUTE_NORMAL, None)
    try:
        fd = msvcrt.open_osfhandle(int(handle), os.O_RDWR)
    except BaseException:
        handle.Close()
        raise
    handle.Detach()  # The Python stream now owns the Win32 handle.
    return os.fdopen(fd, 'w', encoding='ascii')


def _windows_workspace_token(path):
    """One fresh local session per start; old file ownership is irrelevant."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise PermissionError('Workspace credential must be a regular private file.')
    temporary = path.with_name(path.name + '.' + secrets.token_hex(12) + '.tmp')
    created = False
    try:
        stream = _create_windows_token_stream(temporary)
        created = True
        with stream:
            token = secrets.token_hex(32)
            stream.write(token)
            stream.flush()
            os.fsync(stream.fileno())
        # Publish complete private bytes. Replacing only the session file
        # changes no SQLite identity, research files or AI connection grants.
        os.replace(temporary, path)
        return token
    finally:
        if created:
            temporary.unlink(missing_ok=True)


def protect_token_file(stream, path):
    if sys.platform == 'win32':
        import win32security
        import ntsecuritycon
        info = os.fstat(stream.fileno())
        if info.st_nlink != 1 or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise PermissionError('Workspace credential must be a regular private file.')
        user = _windows_user()
        acl = win32security.ACL()
        acl.AddAccessAllowedAce(win32security.ACL_REVISION, ntsecuritycon.FILE_ALL_ACCESS, user)
        win32security.SetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT,
            win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, acl, None)
    elif os.fstat(stream.fileno()).st_mode & 0o077:
        os.fchmod(stream.fileno(), 0o600)


class WorkspaceAccess:
    def __init__(self, db_path: Path):
        self.path = Path(db_path).parent / '.gewu-workspace-token'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform == 'win32':
            self.token = _windows_workspace_token(self.path)
        else:
            self.token = self._posix_token()
        if len(self.token) != 64 or any(c not in '0123456789abcdef' for c in self.token):
            raise ValueError('Workspace credential is invalid. Restore its private backup before starting.')
        self.cookie_name = 'gewu_workspace_' + hashlib.sha256(str(Path(db_path).resolve()).encode()).hexdigest()[:12]
        self.bootstraps = {}
        self.lock = threading.Lock()

    def _posix_token(self):
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        try:
            fd = os.open(str(self.path), flags, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'w') as stream:
                protect_token_file(stream, self.path)
                stream.write(secrets.token_hex(32))
        fd = os.open(str(self.path), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'r') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or (hasattr(os, 'getuid') and info.st_uid != os.getuid()):
                raise PermissionError('Workspace credential must be a private, owned file.')
            protect_token_file(stream, self.path)
            return stream.read(128).strip()

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


def protect_directory(path):
    path = Path(path)
    if path.is_symlink() or (sys.platform == 'win32' and path.is_junction()):
        raise PermissionError('Private staging must not be a filesystem link.')
    if sys.platform != 'win32':
        path.chmod(0o700)
        return
    import win32con, win32security, ntsecuritycon
    user = _windows_user()
    acl = win32security.ACL()
    acl.AddAccessAllowedAceEx(win32security.ACL_REVISION, win32con.OBJECT_INHERIT_ACE | win32con.CONTAINER_INHERIT_ACE, ntsecuritycon.FILE_ALL_ACCESS, user)
    win32security.SetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION, None, None, acl, None)
