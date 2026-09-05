"""Local browser organization, independent of papers and publisher ingestion.

Only explicit bookmarks and successful top-level visits are stored here. Website
cookies/cache belong to WebKit's isolated persistent website data store.
"""
from __future__ import annotations

import ipaddress
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit


BROWSER_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS browser_bookmarks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        parent_id INTEGER REFERENCES browser_bookmarks(id) ON DELETE CASCADE,
        kind TEXT NOT NULL CHECK(kind IN ('folder', 'bookmark')),
        title TEXT NOT NULL,
        url TEXT,
        position INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        CHECK((kind = 'folder' AND url IS NULL) OR (kind = 'bookmark' AND url IS NOT NULL)),
        CHECK(parent_id IS NULL OR parent_id != id)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_browser_bookmarks_parent ON browser_bookmarks(parent_id, position, id)",
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_browser_bookmarks_unique_url
        ON browser_bookmarks(COALESCE(parent_id, 0), url) WHERE kind = 'bookmark'""",
    """CREATE TABLE IF NOT EXISTS browser_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL UNIQUE,
        url TEXT NOT NULL, title TEXT NOT NULL, visited_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_browser_history_date ON browser_history(visited_at DESC, id DESC)",
)


def ensure_browser_schema(conn: sqlite3.Connection) -> None:
    # execute(), not executescript(): do not implicitly commit the caller's migration.
    for statement in BROWSER_SCHEMA:
        conn.execute(statement)


def browser_url(value: Any) -> str:
    """Validate a public HTTP(S) address without making DNS/network requests."""
    text = str(value or "").strip()
    if not text or len(text) > 8192 or any(ord(c) < 32 for c in text) or "\\" in text:
        raise ValueError("Enter a valid public HTTP or HTTPS address.")
    try:
        parsed = urlsplit(text)
        host = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port
        if parsed.scheme not in {"http", "https"} or not host or parsed.username is not None or parsed.password is not None:
            raise ValueError()
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")) or "." not in host and ":" not in host:
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            host = host.encode("idna").decode("ascii")
            # Reject legacy numeric IPv4 spellings (e.g. 127.1 / 0177.0.0.1).
            if all(part.isdigit() or part.startswith("0x") for part in host.split(".")):
                raise ValueError()
        else:
            if not address.is_global:
                raise ValueError()
            host = f"[{host}]" if address.version == 6 else host
        authority = host + (f":{port}" if port and (parsed.scheme, port) not in {("https", 443), ("http", 80)} else "")
        return urlunsplit((parsed.scheme, authority, parsed.path or "/", parsed.query, parsed.fragment))
    except (ValueError, UnicodeError):
        raise ValueError("Enter a valid public HTTP or HTTPS address.") from None


def history_url(value: Any) -> str | None:
    url = browser_url(value)
    parsed = urlsplit(url)
    # Do not persist OAuth callbacks, signed downloads, or credentials in URLs.
    sensitive = {"code", "state", "token", "access_token", "id_token", "refresh_token", "api_key", "apikey", "key", "password", "signature", "sig", "ticket", "samlresponse", "samlrequest"}
    for key, _ in parse_qsl(parsed.query) + parse_qsl(parsed.fragment):
        key = key.casefold()
        if key in sensitive or key.startswith(("x-amz-", "x-goog-")) or key.endswith(("_token", "_secret")):
            return None
    return url


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class BrowserStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def bookmarks(self) -> list[dict]:
        return [dict(row) for row in self.conn.execute("SELECT * FROM browser_bookmarks ORDER BY position, id")]

    def _node(self, node_id: Any) -> dict:
        row = self.conn.execute("SELECT * FROM browser_bookmarks WHERE id = ?", (int(node_id),)).fetchone()
        if not row:
            raise ValueError("This bookmark or folder no longer exists.")
        return dict(row)

    def _parent(self, parent_id: Any, node_id: int | None = None) -> int | None:
        if parent_id in (None, "", 0, "0"):
            return None
        parent_id = int(parent_id)
        current = parent_id
        seen = {node_id} if node_id else set()
        while current is not None:
            if current in seen:
                raise ValueError("A folder cannot be moved inside itself or its descendants.")
            seen.add(current)
            row = self._node(current)
            if row["kind"] != "folder":
                raise ValueError("Choose a folder as the destination.")
            current = row["parent_id"]
        return parent_id

    def save_bookmark(self, payload: dict) -> dict:
        existing = self._node(payload["id"]) if payload.get("id") else None
        kind = existing["kind"] if existing else payload.get("kind", "bookmark")
        if kind not in {"folder", "bookmark"}:
            raise ValueError("Unknown bookmark type.")
        parent = self._parent(payload.get("parent_id", existing["parent_id"] if existing else None), existing["id"] if existing else None)
        title = str(payload.get("title", existing["title"] if existing else "") or "").strip()[:1000]
        if not title:
            raise ValueError("Enter a name.")
        url = browser_url(payload.get("url", existing["url"] if existing else "")) if kind == "bookmark" else None
        if url and history_url(url) is None:
            raise ValueError("Save the website's regular address, not a temporary authorization or signed-download link.")
        with self.conn:
            duplicate = self.conn.execute("SELECT * FROM browser_bookmarks WHERE parent_id IS ? AND url = ? AND kind = 'bookmark'", (parent, url)).fetchone() if url else None
            if duplicate and (not existing or duplicate["id"] != existing["id"]):
                if existing:
                    raise ValueError("This address is already bookmarked in that folder.")
                return {"bookmark": dict(duplicate), "already_saved": True}
            stamp = _now()
            last = self.conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM browser_bookmarks WHERE parent_id IS ?", (parent,)).fetchone()[0]
            if existing:
                position = existing["position"] if parent == existing["parent_id"] else last
                self.conn.execute("UPDATE browser_bookmarks SET title=?, url=?, parent_id=?, position=?, updated_at=? WHERE id=?", (title, url, parent, position, stamp, existing["id"]))
                node_id = existing["id"]
            else:
                cursor = self.conn.execute("INSERT INTO browser_bookmarks(parent_id,kind,title,url,position,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (parent, kind, title, url, last, stamp, stamp))
                node_id = cursor.lastrowid
        return {"bookmark": self._node(node_id), "already_saved": False}

    def move_bookmark(self, node_id: Any, parent_id: Any, before_id: Any = None) -> None:
        node = self._node(node_id)
        parent = self._parent(parent_id, node["id"])
        siblings = [int(row[0]) for row in self.conn.execute("SELECT id FROM browser_bookmarks WHERE parent_id IS ? AND id != ? ORDER BY position,id", (parent, node["id"]))]
        if before_id is not None and int(before_id) not in siblings:
            raise ValueError("The destination changed. Try moving the bookmark again.")
        siblings.insert(siblings.index(int(before_id)) if before_id is not None else len(siblings), node["id"])
        try:
            with self.conn:
                self.conn.execute("UPDATE browser_bookmarks SET parent_id=?, updated_at=? WHERE id=?", (parent, _now(), node["id"]))
                self.conn.executemany("UPDATE browser_bookmarks SET position=? WHERE id=?", enumerate(siblings))
        except sqlite3.IntegrityError:
            raise ValueError("This address is already bookmarked in that folder.") from None

    def delete_bookmark(self, node_id: Any) -> None:
        node = self._node(node_id)
        with self.conn:
            self.conn.execute("DELETE FROM browser_bookmarks WHERE id=?", (node["id"],))

    def record_visit(self, payload: dict) -> None:
        url = history_url(payload.get("url"))
        if url is None:
            return
        try:
            event_id = str(uuid.UUID(str(payload.get("event_id", ""))))
        except ValueError:
            raise ValueError("Invalid browser visit identifier.") from None
        title = str(payload.get("title") or urlsplit(url).hostname)[:1000]
        with self.conn:
            self.conn.execute("INSERT INTO browser_history(event_id,url,title,visited_at) VALUES(?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET title=excluded.title", (event_id, url, title, _now()))

    def history(self, query: str = "", offset: int = 0, limit: int = 100) -> dict:
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        search = "%" + str(query)[:500].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = self.conn.execute("SELECT * FROM browser_history WHERE title LIKE ? ESCAPE '\\' OR url LIKE ? ESCAPE '\\' ORDER BY visited_at DESC,id DESC LIMIT ? OFFSET ?", (search, search, limit + 1, offset)).fetchall()
        return {"history": [dict(row) for row in rows[:limit]], "history_more": len(rows) > limit}

    def clear_history(self, payload: dict) -> None:
        with self.conn:
            if payload.get("id"):
                self.conn.execute("DELETE FROM browser_history WHERE id=?", (int(payload["id"]),))
            elif payload.get("range") == "all":
                self.conn.execute("DELETE FROM browser_history")
            elif payload.get("range") in {"hour", "day", "week"}:
                since = datetime.now(timezone.utc) - timedelta(hours={"hour": 1, "day": 24, "week": 168}[payload["range"]])
                self.conn.execute("DELETE FROM browser_history WHERE visited_at >= ?", (since.isoformat(),))
            else:
                raise ValueError("Choose a history range to clear.")

    def suggestions(self, query: str, limit: int = 8) -> list[dict]:
        """Rank local visits without contacting search engines or changing history."""
        needle = str(query or "").strip()[:256].casefold()
        if not needle:
            return []
        limit = max(1, min(int(limit), 12))
        search = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = self.conn.execute("""WITH matches AS (SELECT url, COUNT(*) AS visits, MAX(id) AS latest_id,
                MAX(visited_at) AS last_visit FROM browser_history
            GROUP BY url HAVING url LIKE ? ESCAPE '\\' OR
                SUM(CASE WHEN title LIKE ? ESCAPE '\\' THEN 1 ELSE 0 END) > 0
            ORDER BY visits DESC, last_visit DESC, latest_id DESC LIMIT 1000)
            SELECT matches.*, latest.title FROM matches
            JOIN browser_history AS latest ON latest.id=matches.latest_id""", (search, search)).fetchall()
        candidates = []
        for row in rows:
            try:
                url = history_url(row["url"])
            except ValueError:
                continue
            if not url:
                continue
            title = row["title"]
            host = urlsplit(url).netloc.casefold()
            host = host[4:] if host.startswith("www.") else host
            display = url.split("://", 1)[1]
            prefix = host.startswith(needle) or display.casefold().startswith(needle) or url.casefold().startswith(needle)
            rank = 2 if prefix else 1 if title.casefold().startswith(needle) else 0
            candidates.append((rank, row["visits"], row["last_visit"], row["latest_id"],
                               {"url": url, "title": title, "visits": row["visits"]}))
        candidates.sort(key=lambda item: item[:4], reverse=True)
        return [item[4] for item in candidates[:limit]]

    def preferences(self) -> dict:
        row = self.conn.execute("SELECT value FROM app_settings WHERE key='browser_preferences'").fetchone()
        try:
            return json.loads(row[0]) if row else {}
        except (TypeError, ValueError):
            return {}

    def save_preferences(self, payload: dict) -> None:
        values = self.preferences()
        if "sidebar_width" in payload:
            values["sidebar_width"] = max(190, min(420, int(payload["sidebar_width"])))
        if "sidebar_hidden" in payload:
            values["sidebar_hidden"] = bool(payload["sidebar_hidden"])
        if payload.get("tab") in {"bookmarks", "history"}:
            values["tab"] = payload["tab"]
        if "expanded" in payload:
            values["expanded"] = [int(x) for x in payload["expanded"][:2000] if str(x).isdigit()]
        if "last_folder" in payload:
            # A folder may have been deleted since the UI last loaded its preferences.
            try:
                values["last_folder"] = self._parent(payload["last_folder"])
            except ValueError:
                values["last_folder"] = None
        if "favorites_folder_id" in payload:
            # A stable folder identity, never a second copy of its bookmarks.
            # Preserve a deleted ID so the UI asks for a new folder instead of
            # unexpectedly displaying another folder's potentially private links.
            folder_id = payload["favorites_folder_id"]
            if folder_id is None:
                values["favorites_folder_id"] = None
            elif isinstance(folder_id, int) and not isinstance(folder_id, bool) and folder_id > 0:
                if folder_id != values.get("favorites_folder_id"):
                    self._parent(folder_id)
                values["favorites_folder_id"] = folder_id
            else:
                raise ValueError("Choose a Favorites folder.")
        with self.conn:
            self.conn.execute("INSERT INTO app_settings(key,value,updated_at) VALUES('browser_preferences',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at", (json.dumps(values), _now()))
