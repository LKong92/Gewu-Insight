"""Bundled Zotero companion setup. Never modifies Zotero preferences or databases."""
from __future__ import annotations
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from zipfile import ZipFile

PLUGIN_ID = "gewu-monitor@gewu-insight"
SUPPORT = Path.home() / "Library/Application Support/Gewu Insight"


def package_path() -> Path:
    app = os.environ.get("GEWU_APP_PATH")
    if app:
        path = Path(app) / "Contents/Resources/Gewu Insight for Zotero.xpi"
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


def status():
    path, manifest = package_info()
    return {"ok": True, "version": manifest["version"], "zotero_installed": Path("/Applications/Zotero.app").is_dir(),
            "package_name": path.name, "platform": sys.platform}


def configure(workspace: Path, origin: str, action: str, support: Path = SUPPORT):
    if action not in {"prepare", "open", "update"}:
        raise ValueError("Unknown Zotero integration action.")
    if sys.platform != "darwin":
        raise ValueError("Automatic setup is currently supported on macOS. Download the plugin and install it in Zotero.")
    from .workspace import database_identity
    folder = Path(workspace).resolve()
    identity = database_identity(folder / "data/paper_monitor.sqlite")
    if not identity:
        raise ValueError("Open a valid Gewu database before connecting Zotero.")
    app = os.environ.get("GEWU_APP_PATH", "")
    path, manifest = package_info()
    request_id = secrets.token_urlsafe(24)
    value = {"workspace": str(folder), "database_uuid": identity, "origin": origin,
             "app_path": app, "request_id": request_id, "requested_at": time.time(), "action": action}
    support.mkdir(parents=True, exist_ok=True)
    temporary = support / ("zotero-connection." + secrets.token_hex(8))
    try:
        with temporary.open("x") as stream:
            os.chmod(temporary, 0o600)
            json.dump(value, stream)
        temporary.replace(support / "zotero-connection.json")
    finally:
        temporary.unlink(missing_ok=True)
    if action == "prepare":
        # First installation uses Zotero's supported XPI installation UI.
        subprocess.run(["/usr/bin/open", "-R", str(path)], check=True)
        subprocess.run(["/usr/bin/open", "-a", "/Applications/Zotero.app"], check=True)
        return {"ok": True, "message": "In Zotero, choose Tools → Plugins, then drag the highlighted plugin into that window. After installation, choose Tools → Gewu Insight. Your database connection is ready."}
    subprocess.run(["/usr/bin/open", "-a", "/Applications/Zotero.app", "zotero://gewu-insight/" + action + "?request=" + request_id], check=True)
    return {"ok": True, "message": "Request sent to Zotero. The Gewu Insight plugin must already be installed."}
