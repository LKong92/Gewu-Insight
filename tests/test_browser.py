from __future__ import annotations

import http.client
import base64
import json
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from paper_monitor.browser_store import BrowserStore, browser_url, history_url
from paper_monitor.storage import Storage, STORAGE_SCHEMA_VERSION
from paper_monitor.ui_server import FastLocalThreadingHTTPServer, PaperMonitorUiHandler, INDEX_HTML

ROOT = Path(__file__).resolve().parents[1]


class BrowserStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "test.sqlite"
        self.storage = Storage(self.path)
        self.browser = BrowserStore(self.storage.conn)

    def tearDown(self):
        self.storage.close()
        self.temp.cleanup()

    def folder(self, title="Research", parent=None):
        return self.browser.save_bookmark({"title": title, "kind": "folder", "parent_id": parent})["bookmark"]

    def bookmark(self, title="Example", parent=None, url="https://example.org/paper"):
        return self.browser.save_bookmark({"title": title, "url": url, "parent_id": parent})

    def test_address_suggestions_rank_frequency_deduplicate_and_follow_clear(self):
        for host, count in [("news.example.org", 2), ("nature.example.org", 5), ("other.example.org", 8)]:
            for index in range(count):
                self.browser.record_visit({"url":f"https://{host}/", "title":f"Nature research {index}", "event_id":str(uuid.uuid4())})
        before = self.storage.conn.total_changes
        result = self.browser.suggestions("n")
        self.assertEqual([row["url"] for row in result], ["https://nature.example.org/", "https://news.example.org/", "https://other.example.org/"])
        self.assertEqual(result[0]["visits"], 5)
        self.assertEqual(result[0]["title"], "Nature research 4")
        self.assertEqual(self.storage.conn.total_changes, before)
        self.assertEqual(len(self.browser.suggestions("n", limit=1)), 1)
        for query in ["", " ", "%", "_", "no-match", "' OR 1=1 --"]:
            self.assertEqual(self.browser.suggestions(query), [])
        self.browser.clear_history({"range":"all"})
        self.assertEqual(self.browser.suggestions("n"), [])

    def test_address_suggestions_do_not_expose_legacy_sensitive_or_local_urls(self):
        for url in ["https://example.org/?token=synthetic", "https://example.org/?code=synthetic", "http://127.0.0.1/example", "file:///example"]:
            self.storage.conn.execute("INSERT INTO browser_history(event_id,url,title,visited_at) VALUES(?,?,?,?)", (str(uuid.uuid4()), url, "example", "2026-09-01"))
        self.storage.conn.commit()
        self.assertEqual(self.browser.suggestions("example"), [])

    def test_nested_bookmarks_edit_duplicate_and_restart(self):
        folder = self.folder()
        child = self.folder("Physics", folder["id"])
        saved = self.bookmark(parent=child["id"])["bookmark"]
        duplicate = self.bookmark(parent=child["id"])
        self.assertTrue(duplicate["already_saved"])
        self.assertEqual(duplicate["bookmark"]["id"], saved["id"])
        self.browser.save_bookmark({"id": saved["id"], "title": "Edited"})
        self.storage.close()
        self.storage = Storage(self.path)
        self.browser = BrowserStore(self.storage.conn)
        self.assertEqual(len(self.browser.bookmarks()), 3)
        self.assertEqual(self.browser._node(saved["id"])["title"], "Edited")

    def test_move_reorder_cycle_and_duplicate_rollback(self):
        one, two = self.folder("One"), self.folder("Two")
        child = self.folder("Child", one["id"])
        with self.assertRaises(ValueError):
            self.browser.move_bookmark(one["id"], child["id"])
        first = self.bookmark(parent=one["id"])["bookmark"]
        other = self.bookmark(parent=two["id"])["bookmark"]
        with self.assertRaises(ValueError):
            self.browser.move_bookmark(first["id"], two["id"])
        self.assertEqual(self.browser._node(first["id"])["parent_id"], one["id"])
        with self.assertRaises(ValueError):
            self.folder("Bad", first["id"])
        self.browser.move_bookmark(two["id"], None, one["id"])
        roots = [row["id"] for row in self.browser.bookmarks() if row["parent_id"] is None]
        self.assertEqual(roots, [two["id"], one["id"]])
        self.assertTrue(self.browser._node(other["id"]))

    def test_folder_cascade_does_not_delete_history_or_papers(self):
        folder = self.folder()
        child = self.folder("Child", folder["id"])
        self.bookmark(parent=child["id"])
        self.browser.record_visit({"url":"https://example.org/paper", "event_id":str(uuid.uuid4())})
        paper_count = self.storage.conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
        self.browser.delete_bookmark(folder["id"])
        self.assertEqual(self.browser.bookmarks(), [])
        self.assertEqual(len(self.browser.history()["history"]), 1)
        self.assertEqual(self.storage.conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0], paper_count)
        self.assertEqual(self.storage.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        with self.assertRaises(sqlite3.IntegrityError):
            self.storage.conn.execute("INSERT INTO browser_bookmarks(parent_id,kind,title,created_at,updated_at) VALUES(999,'folder','Orphan','now','now')")

    def test_history_idempotency_pagination_search_and_clear(self):
        event_id = str(uuid.uuid4())
        self.browser.record_visit({"url":"https://example.org/first", "event_id":event_id, "title":"First"})
        stamp = self.browser.history()["history"][0]["visited_at"]
        self.browser.record_visit({"url":"https://example.org/first", "event_id":event_id, "title":"Updated title"})
        self.assertEqual(len(self.browser.history()["history"]), 1)
        self.assertEqual(self.browser.history()["history"][0]["visited_at"], stamp)
        for index in range(4):
            self.browser.record_visit({"url":f"https://example.org/{index}", "event_id":str(uuid.uuid4()), "title":f"Item {index}"})
        page = self.browser.history(limit=2)
        self.assertTrue(page["history_more"])
        self.assertEqual(len(self.browser.history(offset=2, limit=2)["history"]), 2)
        self.assertEqual(len(self.browser.history("Updated")["history"]), 1)
        self.assertEqual(len(self.browser.history("%")["history"]), 0)
        self.bookmark()
        self.browser.clear_history({"id":page["history"][0]["id"]})
        self.assertEqual(len(self.browser.history()["history"]), 4)
        self.browser.clear_history({"range":"hour"})
        self.assertEqual(self.browser.history()["history"], [])
        self.assertEqual(len(self.browser.bookmarks()), 1)

    def test_history_clear_ranges_preserve_older_visits(self):
        for stamp in ["2000-01-01T00:00:00+00:00", "2001-01-01T00:00:00+00:00"]:
            self.storage.conn.execute("INSERT INTO browser_history(event_id,url,title,visited_at) VALUES(?,?,?,?)", (str(uuid.uuid4()), "https://example.org/", "Old", stamp))
        self.storage.conn.commit()
        self.browser.clear_history({"range":"week"})
        self.assertEqual(len(self.browser.history()["history"]), 2)
        with self.assertRaises(ValueError):
            self.browser.clear_history({"range":"invalid"})
        self.browser.clear_history({"range":"all"})
        self.assertEqual(self.browser.history()["history"], [])

    def test_preferences_persist_without_touching_other_settings(self):
        self.storage.set_setting("unrelated-product-setting", "preserve")
        self.browser.save_preferences({"sidebar_width":999, "tab":"history", "expanded":[1,2], "sidebar_hidden":True})
        values = self.browser.preferences()
        self.assertEqual(values["sidebar_width"], 420)
        self.assertEqual(values["tab"], "history")
        self.assertEqual(self.storage.get_setting("unrelated-product-setting"), "preserve")

    def test_deleted_destination_does_not_block_sidebar_preferences(self):
        folder = self.folder()
        self.browser.save_preferences({"last_folder":folder["id"]})
        self.browser.delete_bookmark(folder["id"])
        self.browser.save_preferences({"last_folder":folder["id"], "sidebar_width":280})
        self.assertIsNone(self.browser.preferences()["last_folder"])
        self.assertEqual(self.browser.preferences()["sidebar_width"], 280)

    def test_favorites_folder_is_persisted_identity_not_copied_bookmarks(self):
        folder = self.folder()
        before = self.browser.bookmarks()
        self.browser.save_preferences({"favorites_folder_id":folder["id"]})
        self.assertEqual(self.browser.preferences()["favorites_folder_id"], folder["id"])
        self.assertEqual(self.browser.bookmarks(), before)
        self.browser.delete_bookmark(folder["id"])
        self.browser.save_preferences({"favorites_folder_id":folder["id"], "sidebar_width":260})
        self.assertEqual(self.browser.preferences()["favorites_folder_id"], folder["id"])
        self.assertEqual(self.browser.preferences()["sidebar_width"], 260)
        for invalid in [True, -1, "1", 987654321]:
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                self.browser.save_preferences({"favorites_folder_id":invalid})

    def test_private_addresses_credentials_and_auth_history_rejected(self):
        for url in ["file:///tmp/a.pdf", "javascript:alert(1)", "http://127.0.0.1:8765/", "http://127.1/", "http://2130706433/", "http://0177.0.0.1/", "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://192.168.0.1/", "http://localhost./", "https://x.local/", "https://user:secret@example.org/"]:
            with self.subTest(url=url), self.assertRaises(ValueError): browser_url(url)
        self.assertEqual(browser_url("https://EXAMPLE.org:443"), "https://example.org/")
        self.assertEqual(history_url("https://www.google.com/search?q=quantum"), "https://www.google.com/search?q=quantum")
        for suffix in ["?code=synthetic", "#access_token=synthetic", "?X-Amz-Signature=synthetic", "?SAMLResponse=synthetic"]:
            self.assertIsNone(history_url("https://example.org/" + suffix))
            self.browser.record_visit({"url":"https://example.org/" + suffix, "event_id":str(uuid.uuid4())})
        self.assertEqual(self.browser.history()["history"], [])

    def test_schema_15_upgrade_only_adds_browser_structures(self):
        self.storage.set_setting("migration-preserve", "yes")
        self.storage.upsert_paper({"paper_id":"browser-migration-existing", "title":"Existing paper", "journal":"Example Journal", "publication_date":"2026-09-01", "abstract":"", "url":"https://example.org/paper", "source":"crossref", "doi":"10.1000/browser-migration", "type":"journal-article", "raw":{"audit":"preserve"}})
        paper_before = dict(self.storage.get_paper("browser-migration-existing"))
        observations_before = [tuple(row) for row in self.storage.conn.execute("SELECT * FROM paper_source_observations ORDER BY id")]
        self.storage.conn.execute("DROP TABLE browser_bookmarks")
        self.storage.conn.execute("DROP TABLE browser_history")
        self.storage.conn.execute("PRAGMA user_version=15")
        self.storage.conn.commit()
        before = self.storage.conn.execute("SELECT * FROM app_settings ORDER BY key").fetchall()
        self.storage.close()
        with patch.object(Storage, "_backfill_paper_source_observations", side_effect=AssertionError("Must not backfill")), patch.object(Storage, "_seed_library_from_existing_papers", side_effect=AssertionError("Must not seed")), patch.object(Storage, "_ensure_file_path_indexes", side_effect=AssertionError("v15 indexes already exist")):
            self.storage = Storage(self.path)
        self.assertEqual(self.storage.conn.execute("PRAGMA user_version").fetchone()[0], STORAGE_SCHEMA_VERSION)
        self.assertEqual(self.storage.conn.execute("SELECT * FROM app_settings ORDER BY key").fetchall(), before)
        self.assertEqual(BrowserStore(self.storage.conn).bookmarks(), [])
        self.assertEqual(dict(self.storage.get_paper("browser-migration-existing")), paper_before)
        self.assertEqual([tuple(row) for row in self.storage.conn.execute("SELECT * FROM paper_source_observations ORDER BY id")], observations_before)
        self.assertEqual(self.storage.conn.execute("PRAGMA foreign_key_check").fetchall(), [])


class BrowserApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / "api.sqlite"
        storage = Storage(path); storage.close()
        class Handler(PaperMonitorUiHandler):
            configured_db_path = path
            def log_message(self, *_args): pass
        self.server = FastLocalThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()

    def request(self, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        headers = {"X-Gewu-Workspace": self.server.workspace_access.token, **(headers or {})}
        connection.request("POST" if body is not None else "GET", path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse(); content = response.read(); connection.close()
        return response.status, content

    def test_real_api_roundtrip_and_assets(self):
        headers = {"Origin":f"http://127.0.0.1:{self.server.server_port}", "X-Gewu-Browser":"1", "Content-Type":"application/json"}
        status, content = self.request("/api/browser", {"action":"save_bookmark", "title":"Example", "url":"https://example.org/"}, headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(content)["bookmarks"][0]["title"], "Example")
        for asset in ["/browser-ui.js", "/browser-ui.css", "/browser-keyboard.js"]:
            self.assertEqual(self.request(asset)[0], 200)

    def test_selected_source_preview_and_sync_over_local_api(self):
        from tests.test_browser_sync import payload
        headers = {"Origin":f"http://127.0.0.1:{self.server.server_port}", "X-Gewu-Browser":"1", "Content-Type":"application/json"}
        status, content = self.request("/api/browser", {**payload(), "action":"preview_bookmark_source"}, headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(content)["folders"][1]["title"], "Bookmarks bar / Research")
        self.assertNotIn(b"https://", content)
        state_status, state_content = self.request("/api/browser", {"action":"state"}, headers)
        self.assertEqual(state_status, 200)
        self.assertEqual(json.loads(state_content)["bookmarks"], [])
        status, content = self.request("/api/browser", {**payload(), "action":"sync_bookmarks"}, headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(content)["sync_result"]["imported"], 1)
        self.assertEqual({row["title"] for row in json.loads(content)["bookmarks"]}, {"Research", "First", "Empty"})

    def test_cross_site_and_dns_rebinding_rejected_before_dispatch(self):
        for headers in [
            {"Origin":"https://example.org", "X-Gewu-Browser":"1"},
            {"Origin":"null", "X-Gewu-Browser":"1"},
            {"Sec-Fetch-Site":"cross-site"},
            {"Host":f"attacker.example:{self.server.server_port}"},
            {},
        ]:
            with self.subTest(headers=headers):
                self.assertEqual(self.request("/api/browser", {"action":"state"}, headers)[0], 403)
        self.assertEqual(self.request("/api/open-url", {"url":"https://example.org"}, {"Origin":"https://example.org"})[0], 403)
        self.assertEqual(self.request("/api/health", headers={"Sec-Fetch-Site":"cross-site"})[0], 403)
        self.assertEqual(self.request("/api/health")[0], 200)

    def test_website_preference_dispatch_initial_page_and_external_request(self):
        headers = {"Origin": f"http://127.0.0.1:{self.server.server_port}", "Content-Type": "application/json"}
        status, content = self.request("/api/settings/website-links")
        self.assertEqual((status, json.loads(content)), (200, {"browser": "builtin", "capture_details_expanded": False}))
        status, content = self.request("/api/settings/website-links", {"browser": "system", "capture_details_expanded": True}, headers)
        self.assertEqual((status, json.loads(content)), (200, {"browser": "system", "capture_details_expanded": True}))
        status, content = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn(b'websiteLinkBrowser: "system",', content)
        self.assertIn(b'browserCaptureDetailsExpanded: true,', content)
        bad_headers = {**headers, "Origin": "https://example.org"}
        self.assertEqual(self.request("/api/settings/website-links", {"browser": "builtin"}, bad_headers)[0], 403)
        self.assertEqual(self.request("/api/settings/website-links", {"browser": "system", "capture_details_expanded": False}, bad_headers)[0], 403)
        self.assertEqual(self.request("/api/settings/website-links", {"browser": "unknown"}, headers)[0], 400)
        with patch("paper_monitor.ui_server.subprocess.run") as launch:
            self.assertEqual(self.request("/api/open-url", {"url": "https://example.org/", "app": "default"}, bad_headers)[0], 403)
            launch.assert_not_called()
            with patch("paper_monitor.ui_server.sys.platform", "darwin"):
                self.assertEqual(self.request("/api/open-url", {"url": "https://example.org/", "app": "default"}, headers)[0], 200)
            launch.assert_called_once_with(["open", "https://example.org/"], check=True, timeout=15)
        self.assertEqual(self.request("/api/settings/website-links", {"browser": "builtin"}, headers)[0], 200)
        self.assertIn(b'websiteLinkBrowser: "builtin",', self.request("/")[1])

    def test_bookmark_interchange_api_roundtrip(self):
        headers = {"Origin":f"http://127.0.0.1:{self.server.server_port}", "X-Gewu-Browser":"1", "Content-Type":"application/json"}
        document = b'<DL><DT><H3>Folder</H3><DL><DT><A HREF="https://example.org/">Paper</A></DL></DL>'
        status, content = self.request("/api/browser", {"action":"import_bookmarks", "content_base64":base64.b64encode(document).decode()}, headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(content)["import_result"]["imported"], 1)
        status, content = self.request("/api/browser", {"action":"export_bookmarks"}, headers)
        self.assertEqual(status, 200)
        self.assertIn("<H3>Folder</H3>", json.loads(content)["html"])

    def test_address_suggestions_endpoint_is_scoped_read_only_and_not_cross_site(self):
        headers = {"Origin":f"http://127.0.0.1:{self.server.server_port}", "X-Gewu-Browser":"1", "Content-Type":"application/json"}
        self.request("/api/browser", {"action":"visit", "url":"https://nature.example.org/", "title":"Nature Example", "event_id":str(uuid.uuid4())}, headers)
        status, content = self.request("/api/browser", {"action":"suggestions", "query":"n"}, headers)
        self.assertEqual(status, 200)
        result = json.loads(content)
        self.assertEqual(set(result), {"ok", "suggestions"})
        self.assertEqual(result["suggestions"][0]["url"], "https://nature.example.org/")
        self.assertEqual(self.request("/api/browser", {"action":"suggestions", "query":"n"}, {**headers, "Origin":"https://example.org"})[0], 403)


class BrowserUiTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_home_is_local_and_favorites_use_canonical_folders(self):
        script = "const assert = require('node:assert/strict'); const model = require(" + json.dumps(str(ROOT / "paper_monitor/browser_ui.js")) + ");\n" + r'''
assert.equal(model.address(''), '');
assert.equal(model.address('https://www.google.com/'), 'https://www.google.com/');
assert.equal(model.address('quantum paper'), 'https://www.google.com/search?q=quantum%20paper');
const nodes = [
  {id:1,parent_id:null,kind:'folder',title:'Favorites'},
  {id:2,parent_id:1,kind:'bookmark',title:'Nature',url:'https://www.nature.com/'},
  {id:3,parent_id:1,kind:'folder',title:'Physics'},
  {id:4,parent_id:3,kind:'bookmark',title:'arXiv',url:'https://arxiv.org/'},
  {id:5,parent_id:null,kind:'folder',title:'Unrelated'}];
assert.equal(model.favoritesFolder(nodes, null).id, 1);
assert.equal(model.favoritesFolder(nodes, 5).id, 1);
assert.equal(model.favoritesFolder(nodes, 999).id, 1);
assert.equal(model.favoritesFolder(nodes.filter(n=>n.id!==1), 5), null);
assert.equal(model.favoritesFolder([{...nodes[0],title:'Personal'}],null), null);
assert.equal(model.favoritesFolder([{...nodes[0],title:'个人收藏'}],null).id, 1);
assert.equal(model.favoritesFolder([{...nodes[0],title:'Bookmarks Bar'}]), null);
assert.equal(model.favoritesFolder([{id:6,kind:'folder',title:'收藏夹'},...nodes]).id, 1);
assert.deepEqual(model.favoriteContents(nodes,nodes[0],null).items.map(n=>n.id),[2,3]);
assert.deepEqual(model.favoriteContents(nodes,nodes[0],3).trail.map(n=>n.id),[1,3]);
assert.deepEqual(model.favoriteContents(nodes,nodes[0],3).items.map(n=>n.id),[4]);
assert.equal(model.favoriteContents(nodes,nodes[0],5).folder.id,1);
assert.equal(model.favoriteContents(nodes.filter(n=>n.id!==3),nodes[0],3).folder.id,1);
assert.deepEqual(model.favoriteContents(nodes,null,3).items,[]);
'''
        result = subprocess.run([shutil.which("node"), "-"], input=script, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_home_layout_and_sidebar_controls_remain_separate_from_remote_content(self):
        ui = (ROOT / "paper_monitor/browser_ui.js").read_text()
        css = (ROOT / "paper_monitor/browser_ui.css").read_text()
        self.assertNotIn('browserBookmarkRoot', ui)
        footer = ui.split('<div class="browser-sidebar-footer">')[1].split('<div id="browserResize"')[0]
        self.assertNotIn('browserImportBookmarks', footer)
        self.assertNotIn('browserExportBookmarks', footer)
        self.assertLess(footer.index('browserBookmarkMenu'), footer.index('browserNewFolder'))
        for action in ['browserImportBookmarks', 'browserExportBookmarks', 'browserSyncSafari', 'browserSyncChrome']:
            self.assertIn(action, ui)
        self.assertLess(footer.index('browserNewFolder'), footer.index('browserSidebarSearch'))
        self.assertIn('$("browserCollection"), $("browserBookmarksTab")', ui)
        self.assertIn('root:$("browserFavorites")', ui)
        self.assertIn('if (!data.active || !data.home) return', ui)
        self.assertIn('root.querySelectorAll', ui)
        self.assertIn('.browser-at-home .browser-viewport', css)
        self.assertIn('$("browserFavorites").hidden = !home', ui)
        self.assertNotIn('browserFavoritesFolder', ui)
        self.assertNotIn('browser-favorites-heading', css)

    def test_webpage_tabs_are_square_contiguous_and_inside_main_column(self):
        ui = (ROOT / "paper_monitor/browser_ui.js").read_text()
        css = (ROOT / "paper_monitor/browser_ui.css").read_text()
        markup = ui.split('root.innerHTML = `', 1)[1].split('document.body.append(root)', 1)[0]
        self.assertLess(markup.index('</aside>'), markup.index('id="browserTabs"'))
        self.assertLess(markup.index('class="browser-page-column"'), markup.index('id="browserTabs"'))
        self.assertLess(markup.index('id="browserTabs"'), markup.index('id="browserViewport"'))
        bar = css.split('.browser-tabs {', 1)[1].split('}', 1)[0]
        tab = css.split('.browser-web-tab {', 1)[1].split('}', 1)[0]
        self.assertIn('padding: 0', bar)
        self.assertIn('gap: 0', bar)
        self.assertIn('border-radius: 0', tab)
        self.assertNotIn('max-width', tab)
        self.assertEqual(ui.count('column.clientHeight - $("browserTabs").offsetHeight'), 2)

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_home_geometry_fits_favorites_and_pages_without_losing_items(self):
        script = "const assert = require('node:assert/strict'); const model = require(" + json.dumps(str(ROOT / "paper_monitor/browser_ui.js")) + ");\n" + r'''
const regular = model.homeLayout(1200, 850, 26);
assert.equal(regular.pages, 1);
assert.equal(regular.height, 366);
assert.equal(model.homeLayout(1200, 850, 60).pages, 1, 'Favorites can use the entire Home height');
for (const width of [320, 650, 900, 1200, 1800]) {
  for (const height of [450, 600, 850, 1000]) {
    for (const count of [1, 26, 60, 501]) {
      for (const nested of [false, true]) {
        const fit = model.homeLayout(width, height, count, nested);
        assert.ok(fit.height < height && fit.columns >= 1);
        assert.ok(fit.pages * fit.capacity >= count);
        const source = Array.from({length:count}, (_, i) => i), visible = [];
        for (let page = 0; page < fit.pages; page++) visible.push(...source.slice(page*fit.capacity, (page+1)*fit.capacity));
        assert.deepEqual(visible, source, 'all favorites including Add Favorite remain reachable');
      }
    }
  }
}
assert.ok(model.homeLayout(650, 450, 26).pages > 1);
'''
        result = subprocess.run([shutil.which("node"), "-"], input=script, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_home_seam_and_footer_geometry_have_one_layout_authority(self):
        ui = (ROOT / "paper_monitor/browser_ui.js").read_text()
        css = (ROOT / "paper_monitor/browser_ui.css").read_text()
        favorites = css.split('.browser-favorites {', 1)[1].split('}', 1)[0]
        self.assertIn('overflow: hidden', favorites)
        self.assertIn('border: 0', favorites)
        self.assertIn('background: #fff', favorites)
        self.assertNotIn('42vh', css)
        self.assertIn('--browser-footer-height', css)
        self.assertIn('root.querySelector(".browser-sidebar-footer").offsetHeight', ui)
        self.assertIn('layoutObserver.observe(element)', ui)
        self.assertIn('aria-label="Favorites pages"', ui)

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_address_inline_completion_preserves_typed_prefix_and_search(self):
        script = "const assert = require('node:assert/strict'); const model = require(" + json.dumps(str(ROOT / "paper_monitor/browser_ui.js")) + ");\n" + r'''
assert.equal(model.inlineCompletion('N','https://www.nature.com/'),'Nature.com/');
assert.equal(model.inlineCompletion('www.n','https://www.nature.com/'),'www.nature.com/');
assert.equal(model.inlineCompletion('https://www.n','https://www.nature.com/'),'https://www.nature.com/');
assert.equal(model.inlineCompletion('Nature paper','https://www.nature.com/'),null);
assert.equal(model.inlineCompletion('art','https://www.nature.com/articles/test'),null);
assert.equal(model.inlineCompletion('','https://www.nature.com/'),null);
assert.equal(model.address('Nature paper'),'https://www.google.com/search?q=Nature%20paper');
'''
        result = subprocess.run([shutil.which("node"), "-"], input=script, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_address_suggestions_are_local_stale_safe_and_ime_aware(self):
        ui = (ROOT / "paper_monitor/browser_ui.js").read_text()
        for contract in ['api("suggestions", {query})', 'generation !== data.suggestionGeneration',
                         'document.activeElement !== field', 'oncompositionstart', 'oncompositionend',
                         'field.setSelectionRange(query.length, completion.length)',
                         '"suggestions-dismissed"', 'onblur = closeSuggestions']:
            self.assertIn(contract, ui)
        native = (ROOT / "scripts/GewuBrowserController.m").read_text()
        self.assertIn('accessibilityLabel = @"History suggestions"', native)
        self.assertIn('addSubview:self.suggestionsView positioned:NSWindowAbove relativeTo:self.webView', native)
        self.assertIn('- (BOOL)acceptsFirstResponder { return NO; }', native)

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_layout_scheduler_does_not_wait_for_workspace_animation_frames(self):
        script = "const assert = require('node:assert/strict'); const model = require(" + json.dumps(str(ROOT / "paper_monitor/browser_ui.js")) + ");\n" + r'''
global.requestAnimationFrame = () => { throw new Error('Occluded workspace frames never arrive'); };
(async () => {
  let calls = 0;
  const schedule = model.microtaskScheduler(() => { calls++; });
  schedule(); schedule(); schedule();
  assert.equal(calls, 0);
  await Promise.resolve();
  assert.equal(calls, 1);
  schedule(); await Promise.resolve();
  assert.equal(calls, 2);
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run([shutil.which("node"), "-"], input=script, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_ui_models_use_real_addresses_safe_text_and_nested_folders(self):
        script = "const assert = require('node:assert/strict'); const model = require(" + json.dumps(str(ROOT / "paper_monitor/browser_ui.js")) + ");\n" + r'''
assert.equal(model.address('quantum computing'), 'https://www.google.com/search?q=quantum%20computing');
assert.equal(model.address('example.org/paper'), 'https://example.org/paper');
assert.throws(() => model.address('javascript:alert(1)'));
assert.equal(model.droppedURL('# Link\nhttps://example.org/'), 'https://example.org/');
for (const text of ['', undefined, 'search words', 'file:///tmp/paper.pdf']) assert.throws(() => model.droppedURL(text));
assert.equal(model.escape('<script>'), '&lt;script&gt;');
const nodes = [{id:1,parent_id:null,kind:'folder',title:'Physics'}, {id:2,parent_id:1,kind:'folder',title:'Papers'}, {id:3,parent_id:2,kind:'bookmark',title:'Example',url:'https://example.org'}];
assert.equal(model.bookmarkTree(nodes,new Set()).length,1);
assert.deepEqual(model.bookmarkTree(nodes,new Set([1,2])).map(n=>n.depth),[0,1,2]);
assert.equal(model.bookmarkTree(nodes,new Set(),'example')[0].id,3);
assert.deepEqual(model.folderChoices(nodes).map(n=>n.title),['Physics','Physics / Papers']);
assert.deepEqual(model.folderChoices(nodes,1),[]);
assert.equal(model.dayLabel('2026-09-01T10:00:00',new Date('2026-09-01T18:00:00')),'Today');
'''
        result = subprocess.run([shutil.which("node"), "-"], input=script, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_native_separation_routing_download_and_layout_contracts(self):
        source = (ROOT / "scripts/GewuBrowserController.m").read_text()
        ui = (ROOT / "paper_monitor/browser_ui.js").read_text()
        self.assertIn('id="browserMode"', INDEX_HTML)
        self.assertIn('src="/browser-ui.js"', INDEX_HTML)
        self.assertNotIn("<iframe", ui)
        self.assertNotIn("page-proxy", ui)
        self.assertNotIn("addScriptMessageHandler:", source)
        self.assertNotIn("proxyConfigurations =", source)
        self.assertIn("dataStoreForIdentifier:profile", source)
        self.assertIn("startDownloadUsingRequest:", source)
        self.assertIn("response.canShowMIMEType", source)
        self.assertIn("GewuBrowserPublicURL(request.URL)", source)
        self.assertIn('webView !=', (ROOT / "scripts/PaperMonitorApp.m").read_text())
        self.assertIn("visibleDialog()", ui)
        self.assertIn("new ResizeObserver", ui)
        self.assertIn('if (!data.opened)', ui)
        self.assertIn('data.history.length', ui)
        self.assertIn('isKindOfClass:NSNumber.class] ? [command[@"id"] integerValue] : 0', source)
        self.assertIn('addButtonWithTitle:bookmarkID ? @"Save" : @"Add"', source)

    def test_guide_covers_browser_storage_network_and_workspace_link_routing(self):
        from bs4 import BeautifulSoup
        guide = BeautifulSoup((ROOT / "paper_monitor/user_guide.html").read_text(), "html.parser")
        article = guide.find(id="browser")
        self.assertIsNotNone(article)
        for phrase in ["Bookmarks", "History", "Clash", "PDF", "SQLite", "Open in Safari", "Google Scholar"]:
            self.assertIn(phrase, article.get_text())
        self.assertIn("opening a new webpage tab without replacing existing pages", article.get_text())
        self.assertIn("Local PDF/Preview and Finder actions stay native", article.get_text())
        self.assertNotIn("elsewhere still use external browsers", article.get_text())


if __name__ == "__main__":
    unittest.main()
