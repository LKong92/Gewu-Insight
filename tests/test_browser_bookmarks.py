import base64
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import zipfile

from paper_monitor.browser_bookmarks import decode_bookmark_file, export_bookmarks, import_bookmarks
from paper_monitor.browser_store import BrowserStore
from paper_monitor.storage import Storage


CHROME = '''<!DOCTYPE NETSCAPE-Bookmark-file-1><META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE><H1>Bookmarks</H1><DL><p><DT><H3 PERSONAL_TOOLBAR_FOLDER="true">Bookmarks bar</H3><DL><p>
<DT><H3>研究 &amp; Notes</H3><DL><p><DT><A HREF="https://example.org/paper?a=1&amp;b=2" ICON="data:image/png;base64,not-executed">Paper &lt;one&gt;</A>
<DT><A HREF="https://example.net/">第二条</A></DL><p><DT><H3>Empty folder</H3><DL><p></DL><p></DL><p></DL><p>'''
SAFARI = '''<!DOCTYPE NETSCAPE-Bookmark-file-1><HTML><HEAD><TITLE>Bookmarks</TITLE></HEAD><BODY><H1>Bookmarks</H1><DL>
<DT><H3 FOLDED>Favorites</H3><DL><DT><A HREF="https://example.com/">Safari bookmark</A></DL>
<DT><H3>Reading List</H3><DL><DT><A HREF="https://example.org/read">Read later</A></DL></DL></BODY></HTML>'''


def payload(text, **kwargs):
    return {"content_base64": base64.b64encode(text.encode("utf-8")).decode(), **kwargs}


class BrowserBookmarkInterchangeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.temp.name) / "bookmarks.sqlite")
        self.store = BrowserStore(self.storage.conn)

    def tearDown(self):
        self.storage.close(); self.temp.cleanup()

    def test_chrome_hierarchy_unicode_entities_order_and_empty_folder(self):
        result = import_bookmarks(self.store, payload(CHROME))
        self.assertEqual(result["imported"], 2)
        rows = self.store.bookmarks()
        names = {r["title"]: r for r in rows}
        self.assertEqual(names["Paper <one>"]["parent_id"], names["研究 & Notes"]["id"])
        self.assertEqual(names["Paper <one>"]["url"], "https://example.org/paper?a=1&b=2")
        self.assertLess(names["Paper <one>"]["position"], names["第二条"]["position"])
        self.assertEqual(names["Empty folder"]["kind"], "folder")
        self.assertEqual(self.storage.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_safari_roundtrip_and_selected_folder_export(self):
        import_bookmarks(self.store, payload(SAFARI))
        exported = export_bookmarks(self.store)
        self.assertIn("NETSCAPE-Bookmark-file-1", exported)
        self.assertNotIn("password", exported.lower())
        favorites = next(n for n in self.store.bookmarks() if n["title"] == "Favorites")
        selected = export_bookmarks(self.store, favorites["id"])
        self.assertIn("Safari bookmark", selected)
        self.assertNotIn("Read later", selected)
        result = import_bookmarks(self.store, payload(exported, folder_name="Roundtrip"))
        self.assertEqual(result["imported"], 2)

    def test_repeat_import_reuses_duplicates_without_changing_existing_bookmarks(self):
        original = self.store.save_bookmark({"title":"Keep me", "url":"https://keep.example/"})["bookmark"]
        first = import_bookmarks(self.store, payload(CHROME))
        before = self.store.bookmarks()
        second = import_bookmarks(self.store, payload(CHROME))
        self.assertEqual(second["folder_id"], first["folder_id"])
        self.assertEqual((second["imported"], second["folders_created"], second["duplicates"]), (0, 0, 2))
        self.assertEqual(self.store.bookmarks(), before)
        self.assertEqual(self.store._node(original["id"]), original)

    def test_skips_unsupported_private_and_sensitive_links_without_running_markup(self):
        links = ["javascript:alert(1)", "file:///private/file", "http://127.0.0.1:8765", "https://example.com/?access_token=private"]
        source = '<DL><script><A HREF="https://ignored.example/">Script</A></script>'
        source += ''.join(f'<DT><A HREF="{url}">Skip</A>' for url in links)
        source += '<DT><A HREF="https://safe.example/">Safe</A></DL>'
        result = import_bookmarks(self.store, payload(source))
        self.assertEqual((result["imported"], result["skipped"]), (1, 4))
        self.assertNotIn("ignored.example", export_bookmarks(self.store))

    def test_zip_reads_only_bookmark_html_and_never_extracts_other_members(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("profile/Bookmarks.html", SAFARI)
            archive.writestr("Passwords.csv", "private placeholder,never read")
            archive.writestr("../../History.html", "never extract")
        original = zipfile.ZipFile.open
        accessed = []
        def tracked(archive, name, *args, **kwargs):
            accessed.append(name.filename if isinstance(name, zipfile.ZipInfo) else name)
            return original(archive, name, *args, **kwargs)
        with patch.object(zipfile.ZipFile, "open", tracked):
            result = import_bookmarks(self.store, {"content_base64":base64.b64encode(buf.getvalue()).decode()})
        self.assertEqual(result["imported"], 2)
        self.assertEqual(accessed, ["profile/Bookmarks.html"])

    def test_invalid_oversize_and_ambiguous_files_make_no_changes(self):
        for content in ["not base64!", base64.b64encode(b"<HTML><BODY>No bookmarks</BODY></HTML>").decode(), "A" * (14 * 1024 * 1024)]:
            with self.assertRaises(ValueError):
                import_bookmarks(self.store, {"content_base64":content})
            self.assertEqual(self.store.bookmarks(), [])
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr("one/Bookmarks.html", SAFARI); archive.writestr("two/Bookmarks.html", SAFARI)
        with self.assertRaises(ValueError):
            decode_bookmark_file(base64.b64encode(buf.getvalue()).decode())

    def test_import_transaction_rolls_back_on_mid_import_storage_failure(self):
        self.storage.conn.execute("CREATE TRIGGER stop_import BEFORE INSERT ON browser_bookmarks WHEN NEW.title='第二条' BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        self.storage.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            import_bookmarks(self.store, payload(CHROME))
        self.assertEqual(self.store.bookmarks(), [])

    def test_export_escapes_markup_and_has_no_history_or_credentials(self):
        self.store.save_bookmark({"title":'<img src=x onerror="alert(1)">', "url":"https://example.org/?a=1&b=2"})
        exported = export_bookmarks(self.store)
        self.assertNotIn("<img", exported)
        self.assertIn("&lt;img", exported)
        self.assertIn("a=1&amp;b=2", exported)

    def test_depth_and_node_limits_reject_without_mutation(self):
        deep = '<DL>' + '<DT><H3>Nested</H3><DL>' * 66 + '</DL>' * 67
        with self.assertRaises(ValueError): import_bookmarks(self.store, payload(deep))
        with patch("paper_monitor.browser_bookmarks.MAX_NODES", 1):
            with self.assertRaises(ValueError): import_bookmarks(self.store, payload(SAFARI))
        self.assertEqual(self.store.bookmarks(), [])

    def test_utf16_html_is_supported(self):
        self.assertIn("Safari bookmark", decode_bookmark_file(base64.b64encode(SAFARI.encode("utf-16")).decode()))

    def test_empty_folder_at_export_depth_limit_is_preserved(self):
        source = '<DL>' + '<DT><H3>Nested</H3><DL>' * 63 + '</DL>' * 64
        result = import_bookmarks(self.store, payload(source))
        self.assertEqual(result["folders_created"], 64)
        self.assertEqual(export_bookmarks(self.store).count('<DT><H3>'), 64)


if __name__ == "__main__":
    unittest.main()
