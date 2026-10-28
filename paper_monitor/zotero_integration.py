"""Bundled Zotero companion setup. Never modifies Zotero preferences or databases."""
from __future__ import annotations
import json
import configparser
from contextlib import closing
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import threading
import sqlite3
import re
from zipfile import ZipFile

PLUGIN_ID = "gewu-monitor@gewu-insight"
SUPPORT = ((Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "Gewu Insight")
           if sys.platform == "win32" else Path.home() / "Library/Application Support/Gewu Insight")


def database_identity(db):
    """Read the shared identity without creating a database or changing its schema."""
    if not Path(db).is_file():
        return ""
    with closing(sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='app_settings'").fetchone():
            return ""
        row = connection.execute("SELECT value FROM app_settings WHERE key='gewu_database_uuid'").fetchone()
        return str(row[0]) if row else ""


def profile_directory():
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming"))) / "Zotero/Zotero"
    return Path.home() / "Library/Application Support/Zotero"


def zotero_application():
    if sys.platform != "win32":
        path = Path("/Applications/Zotero.app")
        return path if path.is_dir() else None
    candidates = []
    # Standard installer registration also covers a custom installation folder.
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\zotero.exe", 0, winreg.KEY_READ | view) as key:
                    candidates.append(Path(winreg.QueryValueEx(key, "")[0].strip('"')))
            except OSError:
                pass
    for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(variable):
            candidates.append(Path(os.environ[variable]) / "Zotero/zotero.exe")
    if os.environ.get("LOCALAPPDATA"):
        candidates.append(Path(os.environ["LOCALAPPDATA"]) / "Programs/Zotero/zotero.exe")
    return next((path for path in candidates if path.is_file()), None)


def launch_zotero(url=None, *, background=False):
    app = zotero_application()
    if app is None:
        raise FileNotFoundError("Zotero was not found. Install Zotero, then reopen Gewu Insight.")
    if sys.platform == "win32":
        # Zotero consumes protocol links through its explicit command-line URL
        # handler. A bare URL only activates the existing Windows window.
        subprocess.Popen([str(app), *(["-url", url] if url else [])], close_fds=True)
    else:
        subprocess.run(["/usr/bin/open", *(["-g"] if background else []), "-a", str(app), *([url] if url else [])], check=True)


def write_connection(path, value):
    """Publish a private, complete setup request; no credentials in command arguments."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + secrets.token_hex(12))
    try:
        if sys.platform == "win32":
            from .local_access import _create_windows_token_stream
            stream = _create_windows_token_stream(temporary)
        else:
            stream = os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8")
        with stream:
            json.dump(value, stream)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def package_path() -> Path:
    app = os.environ.get("GEWU_APP_PATH")
    if app:
        path = ((Path(app).parent / "Gewu Insight for Zotero.xpi") if sys.platform == "win32"
                else Path(app) / "Contents/Resources/Gewu Insight for Zotero.xpi")
        if path.is_file():
            return path
    root = Path(__file__).resolve().parents[1]
    candidates = sorted((root / "dist").glob("gewu-insight-zotero-*.xpi"))
    if candidates:
        return candidates[-1]
    raise FileNotFoundError("This Gewu build does not include its Zotero plugin. Install a complete Gewu release.")


def package_info():
    path = package_path()
    with ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    if manifest["applications"]["zotero"]["id"] != PLUGIN_ID:
        raise ValueError("The bundled plugin has an unexpected identity.")
    return path, manifest


def installed_plugin(profile_root: Path | None = None):
    """Read only Zotero's addon registry, never its library or preferences."""
    root = profile_root or profile_directory()
    try:
        profiles = configparser.ConfigParser()
        profiles.read(root / "profiles.ini", encoding="utf-8")
        candidates = []
        for section in profiles.sections():
            if not section.startswith("Profile") or not profiles.has_option(section, "Path"):
                continue
            folder = Path(profiles[section]["Path"])
            if profiles[section].get("IsRelative", "1") == "1":
                folder = root / folder
            candidates.append((profiles[section].get("Default") == "1", folder))
        defaults = [folder for default, folder in candidates if default]
        folders = defaults or [folder for _, folder in candidates]
        if len(folders) > 1:
            return {"state": "unknown", "version": "", "message": "Multiple Zotero profiles found. Open the intended profile to check the plugin."}
        if not folders:
            return {"state": "not_installed", "version": ""}
        registry = folders[0] / "extensions.json"
        if not registry.exists():
            return {"state": "not_installed", "version": ""}
        addons = json.loads(registry.read_text(encoding="utf-8")).get("addons", [])
        addon = next((a for a in addons if a.get("id") == PLUGIN_ID), None)
        package = folders[0] / "extensions" / (PLUGIN_ID + ".xpi")
        unpacked = folders[0] / "extensions" / PLUGIN_ID / "manifest.json"
        if not addon or not (package.is_file() or unpacked.is_file()):
            return {"state": "not_installed", "version": ""}
        disabled = addon.get("userDisabled") or addon.get("appDisabled") or addon.get("softDisabled")
        return {"state": "disabled" if disabled else "installed", "version": str(addon.get("version", ""))}
    except (OSError, ValueError, KeyError, configparser.Error):
        return {"state": "unknown", "version": "", "message": "Could not check the Zotero plugin. Open Tools → Plugins to verify it."}


def newer_version(bundled: str, installed: str) -> bool:
    def parts(value):
        return tuple(map(int, value.split("."))) if re.fullmatch(r"\d+(?:\.\d+)*", value) else ()
    left, right = parts(bundled), parts(installed)
    size = max(len(left), len(right))
    return bool(left and right) and left + (0,) * (size-len(left)) > right + (0,) * (size-len(right))


class ZoteroSessions:
    """Short-lived, process-local presence; never a database lock or MCP grant."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.sessions = {}
        self.closed = {}

    def update(self, payload):
        session = str(payload.get("session", ""))
        if not re.fullmatch(r"[A-Za-z0-9-]{8,80}", session):
            raise ValueError("Invalid Zotero session.")
        with self.lock:
            self.closed = {key: expiry for key, expiry in self.closed.items() if expiry > self.clock()}
            if payload.get("action") == "close":
                self.sessions.pop(session, None)
                self.closed[session] = self.clock() + 30
            elif payload.get("action") == "heartbeat":
                request = str(payload.get("handoff_request", ""))
                if request and not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", request):
                    raise ValueError("Invalid handoff request.")
                if session not in self.closed:
                    self.sessions[session] = {"expires": self.clock() + 12, "handoff_request": request,
                                              "version": str(payload.get("version", ""))[:40]}
            else:
                raise ValueError("Unknown Zotero session action.")
        return self.status()

    def status(self):
        with self.lock:
            now = self.clock()
            self.sessions = {key: value for key, value in self.sessions.items() if value["expires"] > now}
            return {"ok": True, "active": bool(self.sessions),
                    "handoff_requests": [s["handoff_request"] for s in self.sessions.values() if s["handoff_request"]]}


def status():
    path, manifest = package_info()
    plugin = installed_plugin()
    return {"ok": True, "version": manifest["version"], "zotero_installed": zotero_application() is not None,
            "plugin": plugin, "update_available": plugin["state"] == "installed" and newer_version(manifest["version"], plugin["version"]),
            "package_name": path.name, "platform": sys.platform}


def configure(workspace: Path, origin: str, action: str, support: Path = SUPPORT):
    if action not in {"prepare", "open", "update"}:
        raise ValueError("Unknown Zotero integration action.")
    if sys.platform not in {"darwin", "win32"}:
        raise ValueError("Zotero setup is supported on macOS and Windows.")
    folder = Path(workspace).resolve()
    identity = database_identity(folder / "data/paper_monitor.sqlite")
    if not identity:
        raise ValueError("Open a valid Gewu database before connecting Zotero.")
    app = os.environ.get("GEWU_APP_PATH", "")
    path, manifest = package_info()
    request_id = secrets.token_urlsafe(24)
    value = {"workspace": str(folder), "database_uuid": identity, "origin": origin,
             "app_path": app, "request_id": request_id, "requested_at": time.time(), "action": action}
    write_connection(support / "zotero-connection.json", value)
    if action == "prepare":
        # First installation uses Zotero's supported XPI installation UI.
        if sys.platform == "win32":
            from .desktop_files import reveal_windows_file
            reveal_windows_file(path)
        else:
            subprocess.run(["/usr/bin/open", "-R", str(path)], check=True)
        launch_zotero()
        return {"ok": True, "message": "In Zotero, choose Tools → Plugins, then drag the highlighted plugin into that window. After installation, choose Tools → Gewu Insight. Your database connection is ready."}
    launch_zotero("zotero://gewu-insight/" + action + "?request=" + request_id)
    return {"ok": True, "request_id": request_id, "message": "Waiting for Zotero…"}
