"""Netscape bookmark HTML interchange, shared by Safari/Chrome and Gewu.

Imports never execute HTML, fetch icons, or read password/history members of a
browser archive. SQLite writes are one additive, rollback-safe transaction.
"""
from __future__ import annotations

import base64
import binascii
import html
from html.parser import HTMLParser
import io
import zipfile

from .browser_store import BrowserStore, _now, browser_url, history_url

MAX_BYTES = 10 * 1024 * 1024
MAX_NODES = 20000
MAX_DEPTH = 64


class BookmarkHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes = []
        self.stack = [self.nodes]
        self.pending = None
        self.item = None
        self.text = []
        self.tag = None
        self.ignored = 0
        self.count = 0
        self.saw_list = False

    def finish_item(self):
        if self.item is not None:
            self.item["title"] = "".join(self.text).strip()[:1000]
            self.stack[-1].append(self.item)
            self.pending = self.item if self.tag == "h3" else None
            self.count += 1
            if self.count > MAX_NODES:
                raise ValueError("The bookmark file contains too many entries (maximum 20,000).")
        self.item = None
        self.text = []
        self.tag = None

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignored += 1
            return
        if self.ignored:
            return
        if tag in {"h3", "a"}:
            self.finish_item()
            self.pending = None
            self.tag = tag
            self.item = {"kind": "folder", "children": []} if tag == "h3" else {"kind": "bookmark", "url": dict(attrs).get("href", "")}
        elif tag == "dl":
            self.finish_item()
            self.saw_list = True
            if len(self.stack) > MAX_DEPTH:
                raise ValueError("Bookmark folders are nested too deeply (maximum 64 levels).")
            self.stack.append(self.pending["children"] if self.pending else self.stack[-1])
            self.pending = None

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.ignored = max(0, self.ignored - 1)
            return
        if self.ignored:
            return
        if tag == self.tag:
            self.finish_item()
        elif tag == "dl":
            self.finish_item()
            self.pending = None
            if len(self.stack) > 1:
                self.stack.pop()

    def handle_data(self, data):
        if self.item is not None and not self.ignored:
            self.text.append(data)


def decode_bookmark_file(encoded: str) -> str:
    if not isinstance(encoded, str) or len(encoded) > (MAX_BYTES * 4 // 3 + 8):
        raise ValueError("Choose a bookmark export no larger than 10 MB.")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("The bookmark file could not be read.") from None
    if len(content) > MAX_BYTES:
        raise ValueError("Choose a bookmark export no larger than 10 MB.")
    if content.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if len(archive.infolist()) > 1000:
                    raise ValueError("This ZIP contains too many members. Choose the Bookmarks HTML file instead.")
                choices = [entry for entry in archive.infolist() if not entry.is_dir()
                           and "bookmark" in entry.filename.rsplit("/", 1)[-1].casefold()
                           and entry.filename.casefold().endswith((".html", ".htm"))]
                if len(choices) != 1:
                    raise ValueError("Choose the exported Bookmarks HTML file; this ZIP must contain exactly one bookmark HTML file.")
                entry = choices[0]
                if entry.flag_bits & 1 or entry.file_size > MAX_BYTES:
                    raise ValueError("The bookmark HTML is encrypted or larger than 10 MB.")
                with archive.open(entry) as stream:
                    content = stream.read(MAX_BYTES + 1)
                if len(content) > MAX_BYTES:
                    raise ValueError("The bookmark HTML is larger than 10 MB.")
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
            raise ValueError("The bookmark archive could not be read. Choose its Bookmarks HTML file instead.") from None
    for encoding in (["utf-16"] if content.startswith((b"\xff\xfe", b"\xfe\xff")) else ["utf-8-sig", "cp1252"]):
        try:
            return content.decode(encoding)
        except UnicodeError:
            continue
    raise ValueError("The bookmark HTML text encoding is not supported.")


def import_bookmarks(store: BrowserStore, payload: dict) -> dict:
    text = decode_bookmark_file(payload.get("content_base64", ""))
    parser = BookmarkHTMLParser()
    parser.feed(text)
    parser.close()
    parser.finish_item()
    if not parser.saw_list or not parser.nodes:
        raise ValueError("No bookmark list was found. Choose a Safari or Chrome bookmark HTML export.")
    parent = store._parent(payload.get("parent_id"))
    label = str(payload.get("folder_name") or "Imported Bookmarks").strip()[:1000] or "Imported Bookmarks"
    result = {"imported": 0, "folders_created": 0, "duplicates": 0, "skipped": 0}
    conn = store.conn
    stamp = _now()

    def insert(kind, title, url, parent_id):
        position = conn.execute("SELECT COALESCE(MAX(position), -1)+1 FROM browser_bookmarks WHERE parent_id IS ?", (parent_id,)).fetchone()[0]
        return conn.execute("INSERT INTO browser_bookmarks(parent_id,kind,title,url,position,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (parent_id, kind, title, url, position, stamp, stamp)).lastrowid

    def folder(title, parent_id):
        row = conn.execute("SELECT id FROM browser_bookmarks WHERE parent_id IS ? AND kind='folder' AND title=? ORDER BY position,id LIMIT 1", (parent_id, title)).fetchone()
        if row:
            return row[0]
        result["folders_created"] += 1
        return insert("folder", title, None, parent_id)

    def visit(nodes, parent_id):
        for node in nodes:
            if node["kind"] == "folder":
                visit(node["children"], folder(node["title"] or "Untitled Folder", parent_id))
                continue
            try:
                url = browser_url(node["url"])
                if history_url(url) is None:
                    raise ValueError()
            except ValueError:
                result["skipped"] += 1
                continue
            if conn.execute("SELECT 1 FROM browser_bookmarks WHERE parent_id IS ? AND kind='bookmark' AND url=?", (parent_id, url)).fetchone():
                result["duplicates"] += 1
            else:
                insert("bookmark", node["title"] or url, url, parent_id)
                result["imported"] += 1

    conn.execute("SAVEPOINT browser_bookmark_import")
    try:
        result["folder_id"] = folder(label, parent)
        visit(parser.nodes, result["folder_id"])
        conn.execute("RELEASE SAVEPOINT browser_bookmark_import")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT browser_bookmark_import")
        conn.execute("RELEASE SAVEPOINT browser_bookmark_import")
        raise
    return result


def export_bookmarks(store: BrowserStore, root_id=None) -> str:
    nodes = store.bookmarks()
    by_parent = {}
    for node in nodes:
        by_parent.setdefault(node["parent_id"], []).append(node)
    roots = [store._node(root_id)] if root_id else by_parent.get(None, [])
    lines = ['<!DOCTYPE NETSCAPE-Bookmark-file-1>', '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">', '<TITLE>Gewu Insight Bookmarks</TITLE>', '<H1>Gewu Insight Bookmarks</H1>', '<DL><p>']

    def visit(rows, depth, seen):
        # An empty deepest folder has no child level to validate.
        if not rows:
            return
        if depth > MAX_DEPTH:
            raise ValueError("Bookmark folders are nested too deeply to export.")
        for row in rows:
            if row["id"] in seen:
                raise ValueError("The bookmark tree contains a cycle.")
            title = html.escape(row["title"], quote=True)
            indent = "    " * depth
            if row["kind"] == "folder":
                lines.extend([f"{indent}<DT><H3>{title}</H3>", f"{indent}<DL><p>"])
                visit(by_parent.get(row["id"], []), depth + 1, seen | {row["id"]})
                lines.append(f"{indent}</DL><p>")
            else:
                url = browser_url(row["url"])
                lines.append(f'{indent}<DT><A HREF="{html.escape(url, quote=True)}">{title}</A>')
    visit(roots, 1, set())
    lines.append("</DL><p>")
    output = "\n".join(lines) + "\n"
    if len(output.encode("utf-8")) > MAX_BYTES:
        raise ValueError("The export exceeds 10 MB. Export individual folders instead.")
    return output
