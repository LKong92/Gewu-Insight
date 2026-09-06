import base64
import copy
import json
import plistlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_monitor.browser_store import BrowserStore
from paper_monitor.browser_sync import source_tree, source_folders, sync_bookmarks
from paper_monitor.storage import Storage


def chrome():
    return {"version":1, "roots":{"bookmark_bar":{"type":"folder", "guid":"bar", "name":"Bookmarks bar", "children":[
        {"type":"folder", "guid":"research", "name":"Research", "children":[
            {"type":"url", "guid":"one", "name":"First", "url":"https://example.org/one"},
            {"type":"folder", "guid":"empty", "name":"Empty", "children":[]}]},
        {"type":"folder", "guid":"personal", "name":"Unselected", "children":[
            {"type":"url", "guid":"private", "name":"Not imported", "url":"https://example.net/"}]}]}}}


def payload(tree=None, source="chrome", **kwargs):
    raw = plistlib.dumps(tree) if source == "safari" else json.dumps(tree or chrome()).encode()
    return {"source":source, "content_base64":base64.b64encode(raw).decode(), "source_id":"a" * 64, "folder_id":"research", **kwargs}


class BrowserSourceSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.temp.name) / "test.sqlite")
        self.store = BrowserStore(self.storage.conn)

    def tearDown(self):
        self.storage.close()
        self.temp.cleanup()

    def test_preview_has_hierarchy_counts_only_and_no_writes(self):
        folders = source_folders(source_tree(payload()))
        self.assertEqual(folders[1], {"id":"research", "title":"Bookmarks bar / Research", "count":1})
        self.assertNotIn("https://", json.dumps(folders))
        self.assertEqual(self.store.bookmarks(), [])
        self.assertEqual(self.storage.conn.execute("SELECT COUNT(*) FROM app_settings WHERE key LIKE 'browser_sync_%'").fetchone()[0], 0)

    def test_only_chosen_subtree_and_empty_folders_imported(self):
        result = sync_bookmarks(self.store, payload())
        self.assertEqual((result["imported"], result["folders_created"]), (1, 2))
        self.assertEqual({n["title"] for n in self.store.bookmarks()}, {"Research", "First", "Empty"})
        self.assertEqual(self.storage.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_repeated_sync_is_idempotent(self):
        sync_bookmarks(self.store, payload())
        before = self.store.bookmarks()
        result = sync_bookmarks(self.store, payload())
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(self.store.bookmarks(), before)

    def test_source_changes_update_owned_entries_add_new_and_keep_deletions(self):
        sync_bookmarks(self.store, payload())
        tree = chrome(); children = tree["roots"]["bookmark_bar"]["children"][0]["children"]
        children[0].update(name="Updated", url="https://example.org/two")
        children.pop()
        children.append({"type":"url", "guid":"new", "name":"New", "url":"https://example.com/new"})
        result = sync_bookmarks(self.store, payload(tree))
        self.assertEqual((result["updated"], result["imported"]), (1, 1))
        self.assertIn("Empty", {n["title"] for n in self.store.bookmarks()})
        self.assertIn("https://example.org/two", {n["url"] for n in self.store.bookmarks()})

    def test_local_edits_and_preexisting_duplicate_titles_not_overwritten(self):
        root = self.store.save_bookmark({"kind":"folder", "title":"Research"})["bookmark"]
        local = self.store.save_bookmark({"kind":"bookmark", "title":"My title", "url":"https://example.org/one", "parent_id":root["id"]})["bookmark"]
        sync_bookmarks(self.store, payload())
        self.assertEqual(self.store._node(local["id"]), local)
        tree = chrome(); tree["roots"]["bookmark_bar"]["children"][0]["children"][0]["name"] = "Source changed"
        result = sync_bookmarks(self.store, payload(tree))
        self.assertGreater(result["kept_local"], 0)
        self.assertEqual(self.store._node(local["id"]), local)

    def test_editing_source_owned_node_in_gewu_protects_it(self):
        sync_bookmarks(self.store, payload())
        node = next(n for n in self.store.bookmarks() if n["kind"] == "bookmark")
        self.store.save_bookmark({**node, "title":"Local edit"})
        tree = chrome(); tree["roots"]["bookmark_bar"]["children"][0]["children"][0]["name"] = "Changed source"
        self.assertEqual(sync_bookmarks(self.store, payload(tree))["kept_local"], 1)
        self.assertEqual(self.store._node(node["id"])["title"], "Local edit")

    def test_url_collision_keeps_both_existing_nodes(self):
        sync_bookmarks(self.store, payload())
        root = next(n for n in self.store.bookmarks() if n["title"] == "Research")
        self.store.save_bookmark({"title":"Existing", "url":"https://example.net/collision", "parent_id":root["id"]})
        before = self.store.bookmarks()
        tree = chrome(); tree["roots"]["bookmark_bar"]["children"][0]["children"][0]["url"] = "https://example.net/collision"
        self.assertEqual(sync_bookmarks(self.store, payload(tree))["kept_local"], 1)
        self.assertEqual(self.store.bookmarks(), before)

    def test_safari_binary_and_xml_plists_preserve_selected_hierarchy(self):
        tree = {"WebBookmarkFileVersion":1, "Children":[{"WebBookmarkType":"WebBookmarkTypeList", "Title":"BookmarksBar", "WebBookmarkUUID":"favorites", "Children":[
            {"WebBookmarkType":"WebBookmarkTypeLeaf", "WebBookmarkUUID":"url1", "URLString":"https://example.org/", "URIDictionary":{"title":"研究"}}]}]}
        for fmt in (plistlib.FMT_XML, plistlib.FMT_BINARY):
            p = payload(tree, "safari", folder_id="favorites")
            p["content_base64"] = base64.b64encode(plistlib.dumps(tree, fmt=fmt)).decode()
            self.assertEqual(source_folders(source_tree(p))[0]["title"], "Favorites")
            sync_bookmarks(self.store, p)
        self.assertEqual({n["title"] for n in self.store.bookmarks()}, {"Favorites", "研究"})

    def test_unsafe_links_skipped_without_touching_other_sources(self):
        tree = chrome(); children = tree["roots"]["bookmark_bar"]["children"][0]["children"]
        for i, url in enumerate(["file:///private/test", "http://localhost:8765/", "javascript:alert(1)", "https://example.org/?token=secret"]):
            children.append({"guid":f"unsafe{i}", "type":"url", "name":"Skip", "url":url})
        result = sync_bookmarks(self.store, payload(tree))
        self.assertEqual((result["skipped"], result["imported"]), (4, 1))

    def test_validation_rejects_wrong_formats_ids_depth_and_malformed_nodes(self):
        for p in [payload(folder_id="missing"), payload(source_id="not-a-source"), payload(source="other"), {**payload(), "content_base64":"not base64"}, {**payload(), "content_base64":base64.b64encode(b"[]").decode()}]:
            with self.assertRaises(ValueError): sync_bookmarks(self.store, p)
        tree = chrome(); tree["roots"]["other"] = copy.deepcopy(tree["roots"]["bookmark_bar"])
        with self.assertRaises(ValueError): source_tree(payload(tree))
        tree = chrome(); nested = tree["roots"]["bookmark_bar"]
        for i in range(70):
            node = {"type":"folder", "guid":f"deep{i}", "name":"Deep", "children":[]}
            nested["children"] = [node]; nested = node
        with self.assertRaises(ValueError): source_tree(payload(tree))
        self.assertEqual(self.store.bookmarks(), [])

    def test_write_failure_rolls_back_entries_and_tracking(self):
        self.storage.conn.execute("CREATE TRIGGER fail_sync_tracking BEFORE INSERT ON app_settings WHEN NEW.key LIKE 'browser_sync_%' BEGIN SELECT RAISE(ABORT, 'test write failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): sync_bookmarks(self.store, payload())
        self.assertEqual(self.store.bookmarks(), [])
        self.assertEqual(self.storage.conn.execute("SELECT COUNT(*) FROM app_settings WHERE key LIKE 'browser_sync_%'").fetchone()[0], 0)


if __name__ == "__main__": unittest.main()
