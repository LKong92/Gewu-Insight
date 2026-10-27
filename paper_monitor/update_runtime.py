"""Mac updater's temporary service barrier. No paper, file or schema operations.

Disabled for ordinary CLI/Windows use. Admission closes only for an explicit
installation; already admitted work (including its child threads) can finish.
Idle schedulers wait at their existing iteration boundary.
"""
from contextlib import contextmanager
from functools import wraps
import os
from pathlib import Path
import plistlib
import secrets
import sqlite3
import sys
import threading
import time
from urllib.parse import urlparse


class UpdateBusy(RuntimeError):
    pass


class Barrier:
    def __init__(self, enabled=False):
        self.enabled = enabled
        self.condition = threading.Condition(threading.RLock())
        self.local = threading.local()
        self.active = {}
        self.token = ""
        self.deadline = 0
        self.stopping = False

    def _expire(self):
        if self.token and not self.stopping and time.monotonic() > self.deadline:
            self.token = ""
            self.condition.notify_all()

    def enter(self, label, *, wait=False, inherited=False):
        if not self.enabled:
            return None
        with self.condition:
            self._expire()
            while self.token and not (inherited or getattr(self.local, "depth", 0)):
                if not wait:
                    raise UpdateBusy("Gewu is preparing an update. Try again after it restarts.")
                self.condition.wait(1)
                self._expire()
            key = secrets.token_hex(12)
            self.active[key] = label
            return key

    def leave(self, key):
        if key is not None:
            with self.condition:
                self.active.pop(key, None)
                self.condition.notify_all()

    @contextmanager
    def work(self, label, *, wait=False):
        key = self.enter(label, wait=wait)
        self.local.depth = getattr(self.local, "depth", 0) + 1
        try:
            yield
        finally:
            self.local.depth -= 1
            self.leave(key)

    def prepare(self):
        with self.condition:
            self._expire()
            if not self.enabled:
                raise UpdateBusy("This service does not support safe in-app installation. Restart Gewu first.")
            if self.token:
                raise UpdateBusy("Another update is already being prepared.")
            if self.active:
                raise UpdateBusy("Gewu is still working. Let imports, downloads and background tasks finish, then retry installation.")
            self.token = secrets.token_urlsafe(32)
            self.deadline = time.monotonic() + 45
            return self.token

    def cancel(self, token):
        with self.condition:
            if not self.token or not secrets.compare_digest(self.token, token):
                raise UpdateBusy("The update preparation expired. Retry installation.")
            if self.stopping:
                raise UpdateBusy("The service is already stopping for the update.")
            self.token = ""
            self.condition.notify_all()

    def commit(self, token):
        with self.condition:
            self._expire()
            if not self.token or not secrets.compare_digest(self.token, token) or self.active:
                raise UpdateBusy("The service is not ready. Retry installation.")
            self.stopping = True


barrier = Barrier()


def enable():
    barrier.enabled = sys.platform == "darwin" and bool(os.environ.get("GEWU_APP_PATH"))


def check_startup():
    """Zotero must not relaunch the old helper while Sparkle replaces its App."""
    app = os.environ.get("GEWU_APP_PATH")
    if sys.platform != "darwin" or not app:
        return
    root = Path.home() / "Library/Application Support/Gewu Insight/Updates"
    info = plistlib.loads((Path(app) / "Contents/Info.plist").read_bytes())
    if str(info.get("CFBundleIdentifier", "")).endswith(".updater-test") and os.environ.get("GEWU_UPDATE_STATE_DIR"):
        root = Path(os.environ["GEWU_UPDATE_STATE_DIR"])
    marker = root / "install.plist"
    if marker.exists():
        value = plistlib.loads(marker.read_bytes())
        if value.get("app") == app:
            raise RuntimeError("Gewu Insight is being updated. Wait for the App to reopen before reconnecting Zotero.")


def work(label):
    return barrier.work(label, wait=True)


class Thread(threading.Thread):
    """Track finite workers before start, so an installer cannot race launch."""
    def start(self):
        self._update_ticket = barrier.enter(self.name, inherited=bool(getattr(barrier.local, "depth", 0)))
        try:
            super().start()
        except BaseException:
            barrier.leave(self._update_ticket)
            raise

    def run(self):
        barrier.local.depth = getattr(barrier.local, "depth", 0) + 1
        try:
            super().run()
        finally:
            barrier.local.depth -= 1
            barrier.leave(self._update_ticket)


def request(function):
    @wraps(function)
    def guarded(handler):
        path = urlparse(handler.path).path
        if path in {"/api/health", "/api/macos-update"}:
            return function(handler)
        try:
            with barrier.work("Workspace request"):
                return function(handler)
        except UpdateBusy as error:
            handler.close_connection = True
            handler.send_error_json(503, str(error))
    return guarded


def handle(handler):
    # A browser cookie or an MCP grant never authorizes shutting down the host.
    if not handler.server.workspace_access.matches(handler.headers.get("X-Gewu-Workspace", "")):
        handler.send_error_json(403, "Native workspace authentication is required.")
        return
    payload = handler.read_json_body()
    try:
        if payload.get("action") == "prepare":
            if handler.server.zotero_sessions.status()["active"]:
                raise UpdateBusy("Close the Gewu Insight tab in Zotero before installing the update.")
            token = barrier.prepare()
            try:
                # A Zotero export spans separate HTTP requests. Do not install
                # in the gap between two files of an unpaused migration.
                with sqlite3.connect(Path(handler.configured_db_path).resolve().as_uri() + "?mode=ro", uri=True) as db:
                    exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='zotero_import_jobs'").fetchone()
                    if exists and db.execute("SELECT 1 FROM zotero_import_jobs WHERE state IN ('scan_requested','scanning','running') LIMIT 1").fetchone():
                        raise UpdateBusy("Pause the Zotero import or finish its preview before installing the update.")
            except BaseException:
                barrier.cancel(token)
                raise
            handler.send_json({"ok": True, "token": token, "pid": os.getpid()})
        elif payload.get("action") == "cancel":
            barrier.cancel(str(payload.get("token", "")))
            handler.send_json({"ok": True})
        elif payload.get("action") == "stop":
            barrier.commit(str(payload.get("token", "")))
            handler.send_json({"ok": True})
            # shutdown must be called outside serve_forever's main thread.
            threading.Thread(target=handler.server.shutdown, daemon=True).start()
        else:
            handler.send_error_json(400, "Unknown update action.")
    except UpdateBusy as error:
        handler.send_error_json(409, str(error))
