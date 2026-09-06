"""Explicit, folder-scoped Safari/Chrome -> Gewu bookmark synchronization.

Only caller-supplied bookmark snapshots are parsed: no filesystem, browser
profile, network, credentials, or export/write-back access in this module.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import plistlib
import re
from xml.parsers.expat import ExpatError

from .browser_bookmarks import MAX_BYTES, MAX_DEPTH, MAX_NODES
from .browser_store import BrowserStore, _now, history_url


def source_tree(payload: dict) -> list[dict]:
    source = payload.get("source")
    if source not in {"safari", "chrome"}:
        raise ValueError("Choose Safari or Chrome.")
    encoded = payload.get("content_base64", "")
    if not isinstance(encoded, str) or len(encoded) > (MAX_BYTES + 2) // 3 * 4:
        raise ValueError("Choose a bookmark file no larger than 10 MB.")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if not raw or len(raw) > MAX_BYTES:
            raise ValueError()
        tree = plistlib.loads(raw) if source == "safari" else json.loads(raw)
    except (ValueError, TypeError, binascii.Error, plistlib.InvalidFileException, ExpatError, OverflowError, RecursionError):
        raise ValueError("The selected file is not a readable bookmark snapshot.") from None
    if not isinstance(tree, dict):
        raise ValueError("The selected file is not a bookmark snapshot.")
    if source == "safari":
        if tree.get("WebBookmarkFileVersion") != 1 or not isinstance(tree.get("Children"), list):
            raise ValueError("Choose Safari's Bookmarks.plist file.")
        roots = tree["Children"]
    else:
        if tree.get("version") != 1 or not isinstance(tree.get("roots"), dict):
            raise ValueError("Choose Chrome's Bookmarks file from the intended profile.")
        roots = [tree["roots"][key] for key in ("bookmark_bar", "other", "synced") if key in tree["roots"]]
    count, seen = 0, set()

    def visit(node, path, depth):
        nonlocal count
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            raise ValueError("The bookmark snapshot has too many entries or nested folders.")
        if not isinstance(node, dict):
            raise ValueError("A bookmark entry is malformed.")
        kind = node.get("WebBookmarkType") if source == "safari" else node.get("type")
        folder = kind in {"WebBookmarkTypeList", "folder"}
        if not folder and kind not in {"WebBookmarkTypeLeaf", "url"}:
            return None  # Safari proxy/Reading List metadata is not a website.
        identity = node.get("WebBookmarkUUID") if source == "safari" else node.get("guid") or node.get("id")
        # Legacy nodes without IDs can be merged by path/URL, not falsely
        # identified as source-owned entries across renames/reordering.
        identity = str(identity or "path:" + path)[:256]
        if identity in seen:
            raise ValueError("The source has duplicate bookmark identifiers. Export HTML instead.")
        seen.add(identity)
        uri = node.get("URIDictionary", {})
        if not isinstance(uri, dict):
            raise ValueError("A bookmark entry is malformed.")
        title = node.get("Title") if folder and source == "safari" else uri.get("title") if source == "safari" else node.get("name")
        title = str(title or ("Untitled Folder" if folder else "Untitled Bookmark"))[:1000]
        if source == "safari" and depth == 0:
            title = {"BookmarksBar":"Favorites", "BookmarksMenu":"Bookmarks"}.get(title, title)
        result = {"id":identity, "kind":"folder" if folder else "bookmark", "title":title}
        if folder:
            children = node.get("Children" if source == "safari" else "children", [])
            if not isinstance(children, list):
                raise ValueError("A bookmark folder is malformed.")
            result["children"] = [child for i, item in enumerate(children) if (child := visit(item, f"{path}/{i}", depth + 1)) is not None]
        else:
            result["url"] = node.get("URLString" if source == "safari" else "url", "")
        return result

    return [node for i, item in enumerate(roots) if (node := visit(item, str(i), 0)) is not None]


def source_folders(nodes: list[dict]) -> list[dict]:
    result = []
    def visit(items, prefix):
        total = 0
        for node in items:
            if node["kind"] == "bookmark":
                total += 1
                continue
            label = f'{prefix} / {node["title"]}' if prefix else node["title"]
            entry = {"id":node["id"], "title":label, "count":0}
            result.append(entry)
            entry["count"] = visit(node["children"], label)
            total += entry["count"]
        return total
    visit(nodes, "")
    if len(result) > 2000:
        raise ValueError("Too many folders to choose safely. Export one source folder as HTML instead.")
    return result


def sync_bookmarks(store: BrowserStore, payload: dict) -> dict:
    nodes = source_tree(payload)
    selected = payload.get("folder_id")
    def find(items):
        for node in items:
            if node["kind"] == "folder":
                if node["id"] == selected:
                    return node
                child = find(node["children"])
                if child:
                    return child
        return None
    folder = find(nodes)
    if not folder:
        raise ValueError("Choose a folder from this bookmark snapshot.")
    source_id = payload.get("source_id", "")
    if not isinstance(source_id, str) or not re.fullmatch(r"[a-f0-9]{64}", source_id):
        raise ValueError("Choose the source bookmark file again.")
    key = "browser_sync_" + hashlib.sha256(f'{payload["source"]}:{source_id}:{selected}'.encode()).hexdigest()
    conn, stamp = store.conn, _now()
    result = {"imported":0, "folders_created":0, "updated":0, "reused":0, "kept_local":0, "skipped":0}
    conn.execute("SAVEPOINT browser_source_sync")
    try:
        row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
        mapping = json.loads(row[0]) if row else {}
        def visit(node, parent):
            url = None
            if node["kind"] == "bookmark":
                try:
                    url = history_url(node["url"])
                except ValueError:
                    pass
                if not url:
                    result["skipped"] += 1
                    return None
            previous = mapping.get(node["id"], {}) if not node["id"].startswith("path:") else {}
            row = conn.execute("SELECT * FROM browser_bookmarks WHERE id=?", (previous.get("id"),)).fetchone()
            current = dict(row) if row else None
            desired = {"kind":node["kind"], "title":node["title"], "url":url, "parent_id":parent}
            if current and current["kind"] == node["kind"]:
                intact = all(current[field] == value for field, value in previous.get("snapshot", {}).items())
                changed = any(current[field] != value for field, value in desired.items())
                duplicate = url and conn.execute("SELECT id FROM browser_bookmarks WHERE parent_id IS ? AND url=? AND id!=?", (parent, url, current["id"])).fetchone()
                if previous.get("owned") and intact and changed and not duplicate:
                    store._parent(parent, current["id"])
                    conn.execute("UPDATE browser_bookmarks SET title=?,url=?,parent_id=?,updated_at=? WHERE id=?", (node["title"], url, parent, stamp, current["id"]))
                    result["updated"] += 1
                    previous["snapshot"] = {**desired, "position":current["position"]}
                elif changed:
                    result["kept_local"] += 1
                else:
                    result["reused"] += 1
                local_id = current["id"]
            else:
                if url:
                    row = conn.execute("SELECT * FROM browser_bookmarks WHERE parent_id IS ? AND url=?", (parent, url)).fetchone()
                else:
                    row = conn.execute("SELECT * FROM browser_bookmarks WHERE parent_id IS ? AND kind='folder' AND title=? ORDER BY position,id LIMIT 1", (parent, node["title"])).fetchone()
                if row:
                    local_id = row["id"]
                    mapping[node["id"]] = {"id":local_id, "owned":False}
                    result["reused"] += 1
                else:
                    position = conn.execute("SELECT COALESCE(MAX(position),-1)+1 FROM browser_bookmarks WHERE parent_id IS ?", (parent,)).fetchone()[0]
                    local_id = conn.execute("INSERT INTO browser_bookmarks(parent_id,kind,title,url,position,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (parent, node["kind"], node["title"], url, position, stamp, stamp)).lastrowid
                    mapping[node["id"]] = {"id":local_id, "owned":True, "snapshot":{**desired, "position":position}}
                    result["folders_created" if node["kind"] == "folder" else "imported"] += 1
            if node["kind"] == "folder":
                for child in node["children"]:
                    visit(child, local_id)
            return local_id
        # One explicitly chosen subtree, no implicit whole-profile import and
        # no propagation of source deletions. Reused local entries stay local.
        result["folder_id"] = visit(folder, None)
        serialized = json.dumps(mapping, ensure_ascii=False)
        if len(serialized.encode()) > MAX_BYTES:
            raise ValueError("Sync tracking is too large. Choose a smaller folder.")
        conn.execute("INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at", (key, serialized, stamp))
        conn.execute("RELEASE SAVEPOINT browser_source_sync")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT browser_source_sync")
        conn.execute("RELEASE SAVEPOINT browser_source_sync")
        raise
    return result
