"""Isolated Windows database lifecycle and refusal tests; no daily locator."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
from contextlib import contextmanager

from paper_monitor import windows_database as db
from paper_monitor.storage import Storage, STORAGE_SCHEMA_VERSION
from paper_monitor.windows_workspace_relocation import relocate


@contextmanager
def database(path):
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


@unittest.skipUnless(sys.platform == "win32", "Windows database lifecycle")
class WindowsDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "研究 data 空格" / "Gewu Database"
        self.home = patch("pathlib.Path.home", return_value=self.base)
        self.home.start(); self.addCleanup(self.home.stop)
        self.env = patch.dict(os.environ, {"LOCALAPPDATA": str(self.base / "AppData")})
        self.env.start(); self.addCleanup(self.env.stop)

    def create(self):
        return db.prepare(self.root, create=True, select=True)

    def test_create_restart_and_reselect_preserve_identity_and_state(self):
        first = self.create()
        storage = Storage(self.root / db.DB_RELATIVE)
        storage.set_setting("keep", "中文 setting")
        storage.close()
        for _ in range(3):
            saved = db.read_locator()
            reopened = db.prepare(saved["workspace"], expected_identity=saved["identity"])
            self.assertEqual(first, reopened)
        db.locator_path().unlink()
        reopened = db.prepare(self.root, select=True)
        self.assertEqual(first["identity"], reopened["identity"])
        with db.read_connection(self.root / db.DB_RELATIVE) as c:
            self.assertEqual(c.execute("SELECT value FROM app_settings WHERE key='keep'").fetchone()[0], "中文 setting")
        self.assertTrue((self.root / "config/journals.json").is_file())
        self.assertFalse((self.root / "webview").exists())

    def test_missing_disk_does_not_recreate_root(self):
        first = self.create()
        moved = self.root.with_name("offline")
        self.root.rename(moved)
        with self.assertRaises(FileNotFoundError):
            db.prepare(self.root, expected_identity=first["identity"])
        self.assertFalse(self.root.exists())
        self.assertEqual(db.read_locator()["identity"], first["identity"])

    def test_identity_mismatch_and_newer_version_do_not_change_locator(self):
        first = self.create()
        before = db.locator_path().read_bytes()
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            db.prepare(self.root, expected_identity=str(uuid.uuid4()), select=True)
        with database(self.root / db.DB_RELATIVE) as c:
            c.execute(f"PRAGMA user_version={STORAGE_SCHEMA_VERSION + 1}")
        with self.assertRaisesRegex(ValueError, "newer version"):
            db.prepare(self.root, select=True)
        with self.assertRaisesRegex(ValueError, "newer version"):
            Storage(self.root / db.DB_RELATIVE)
        self.assertEqual(before, db.locator_path().read_bytes())

    def test_readonly_database_is_rejected(self):
        self.create()
        path = self.root / db.DB_RELATIVE
        before = db.locator_path().read_bytes()
        path.chmod(0o444)
        try:
            with self.assertRaises(PermissionError):
                db.prepare(self.root, select=True)
        finally:
            path.chmod(0o666)
        self.assertEqual(before, db.locator_path().read_bytes())

    def test_both_desktop_and_service_locks_refuse_second_process(self):
        self.create()
        for name in (".workspace.lock", ".gewu-database.lock"):
            with db.FileLease(self.root / name):
                command = [sys.executable, "-m", "paper_monitor.windows_database", "prepare", "--workspace", str(self.root)]
                other = subprocess.run(command, capture_output=True, encoding="utf-8", timeout=15)
                self.assertNotEqual(other.returncode, 0)
                self.assertIn("already open", other.stderr)

    def test_schema_upgrade_makes_verified_backup(self):
        first = self.create()
        with database(self.root / db.DB_RELATIVE) as c:
            c.execute("PRAGMA user_version=21")
        db.prepare(self.root, expected_identity=first["identity"])
        copies = list((self.root / "backups").glob("before-schema-*.sqlite"))
        self.assertEqual(len(copies), 1)
        with db.read_connection(copies[0]) as c:
            self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 21)
            self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_copy_with_same_identity_cannot_start_while_original_is_open(self):
        import shutil
        first = self.create()
        clone = self.base / 'copied database'
        shutil.copytree(self.root, clone)
        with db.FileLease(Path(first['runtime']) / '.database-session.lock'):
            with self.assertRaisesRegex(RuntimeError, 'already open'):
                db.prepare(clone)

    def test_existing_new_target_never_overwritten(self):
        self.root.mkdir(parents=True)
        keep = self.root / "keep"
        keep.write_text("retained")
        with self.assertRaisesRegex(ValueError, "empty directory"):
            self.create()
        self.assertEqual(keep.read_text(), "retained")
        self.assertFalse(db.locator_path().exists())

    def test_browser_login_profile_copied_and_not_reset(self):
        first = self.create()
        legacy = self.root / "webview/browser/EBWebView/Default/Cookies"
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b"synthetic signed-in state")
        db.prepare(self.root)
        retained = Path(first["runtime"]) / "Browser/browser/EBWebView/Default/Cookies"
        self.assertEqual(retained.read_bytes(), legacy.read_bytes())
        retained.write_bytes(b"new browser state")
        db.prepare(self.root)
        self.assertEqual(retained.read_bytes(), b"new browser state")
        self.assertTrue(legacy.exists())

    def test_browser_profile_long_paths_survive_embedded_python_copy(self):
        def cleanup_long_fixture():
            import shutil
            assert self.base.parent == Path(tempfile.gettempdir()).resolve()
            assert self.base.name.startswith('tmp')
            shutil.rmtree('\\\\?\\' + str(self.base))
        self.addCleanup(cleanup_long_fixture)
        first = self.create()
        nested = self.root / 'webview/browser' / ('a' * 80) / ('b' * 80) / ('c' * 80)
        extended = Path('\\\\?\\' + str(nested))
        extended.mkdir(parents=True)
        (extended / 'login-state').write_bytes(b'preserved long-path state')
        db.prepare(self.root)
        copied = Path('\\\\?\\' + str(Path(first['runtime']) / 'Browser/browser' / ('a' * 80) / ('b' * 80) / ('c' * 80) / 'login-state'))
        self.assertEqual(copied.read_bytes(), b'preserved long-path state')

    def test_partial_migration_cannot_be_opened(self):
        first = self.create()
        (self.root / ".gewu-migration-incomplete").write_text("incomplete")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            db.prepare(self.root, expected_identity=first["identity"])

    def test_migration_preserves_provenance_permissions_analysis_and_relations(self):
        first = self.create()
        paper = self.root / "data/Library/论文.pdf"
        paper.parent.mkdir(); paper.write_bytes(b"research bytes")
        note = self.root / "data/Associated Files/analysis.md"
        note.parent.mkdir(); note.write_text("中文分析", encoding="utf-8")
        with database(self.root / db.DB_RELATIVE) as c:
            c.execute("INSERT INTO papers(paper_id,title,journal,source,main_pdf_path,analysis_path,raw_json,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,'2026-01-01','2026-01-01')",
                      ("stable", "Title", "Journal", "manual", str(paper), str(note), json.dumps({"import":{"source_path":str(paper),"stored_path":str(paper)}})))
            c.execute("INSERT INTO app_settings(key,value,updated_at) VALUES('read-state', 'read', '2026-01-01')")
        target = self.base / "迁移 destination"
        result = relocate(self.root, target)
        self.assertGreater(result["tables_compared"], 20)
        self.assertEqual(db.check_database(target)[1], first["identity"])
        with db.read_connection(target / db.DB_RELATIVE) as c:
            main, analysis, raw = c.execute("SELECT main_pdf_path,analysis_path,raw_json FROM papers WHERE paper_id='stable'").fetchone()
            self.assertEqual(Path(main).read_bytes(), paper.read_bytes())
            self.assertEqual(Path(analysis).read_bytes(), note.read_bytes())
            self.assertEqual(json.loads(raw)["import"]["source_path"], str(paper))
            self.assertEqual(json.loads(raw)["import"]["stored_path"], main)
            self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(db.read_locator()["workspace"], str(self.root))
        self.assertFalse(list((target / "reports").rglob("analysis.md")))


if __name__ == "__main__":
    unittest.main()
