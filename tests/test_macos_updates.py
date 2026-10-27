"""Installation barriers protect admitted work and leave research data alone."""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from paper_monitor import update_runtime as updates


class BarrierTests(unittest.TestCase):
    def setUp(self):
        self.barrier = updates.Barrier(enabled=True)
        self.replacement = patch.object(updates, "barrier", self.barrier)
        self.replacement.start()

    def tearDown(self):
        self.replacement.stop()

    def test_busy_work_is_not_interrupted_and_failed_preparation_does_not_lock(self):
        with self.barrier.work("Copying a PDF"):
            with self.assertRaises(updates.UpdateBusy): self.barrier.prepare()
            self.assertFalse(self.barrier.token)
        token = self.barrier.prepare()
        self.barrier.cancel(token)
        with self.barrier.work("Another save"): pass

    def test_finite_thread_remains_admitted_after_request_returns(self):
        ready, finish = threading.Event(), threading.Event()
        def copy(): ready.set(); finish.wait(3)
        with self.barrier.work("Request"):
            worker = updates.Thread(target=copy)
            worker.start()
        self.assertTrue(ready.wait(1))
        with self.assertRaises(updates.UpdateBusy): self.barrier.prepare()
        finish.set(); worker.join(2)
        self.barrier.cancel(self.barrier.prepare())

    def test_prepared_service_blocks_new_requests_and_worker_launch(self):
        token = self.barrier.prepare()
        with self.assertRaises(updates.UpdateBusy): self.barrier.enter("Move")
        with self.assertRaises(updates.UpdateBusy): updates.Thread(target=lambda: None).start()
        self.assertFalse(self.barrier.active)
        self.barrier.cancel(token)

    def test_idle_scheduler_waits_without_losing_work_then_resumes(self):
        token = self.barrier.prepare()
        completed = threading.Event()
        def scheduled():
            with updates.work("Monitor iteration"): completed.set()
        scheduler = threading.Thread(target=scheduled, daemon=True)
        scheduler.start()
        self.assertFalse(completed.wait(.05))
        self.barrier.cancel(token)
        self.assertTrue(completed.wait(1)); scheduler.join(1)

    def test_expired_preparation_recovers_without_restart(self):
        self.barrier.prepare(); self.barrier.deadline = time.monotonic() - 1
        with self.barrier.work("Save"): pass
        self.assertFalse(self.barrier.token)

    def test_wrong_lease_cannot_cancel_or_stop_another_installation(self):
        token = self.barrier.prepare()
        with self.assertRaises(updates.UpdateBusy): self.barrier.cancel("other")
        with self.assertRaises(updates.UpdateBusy): self.barrier.commit("other")
        self.assertEqual(self.barrier.token, token)
        self.barrier.commit(token)
        self.barrier.deadline = 0
        with self.assertRaises(updates.UpdateBusy): self.barrier.enter("Save")

    def test_disabled_mode_preserves_existing_non_app_workflows(self):
        self.barrier.enabled = False
        with self.barrier.work("CLI task"):
            self.assertFalse(self.barrier.active)
        with self.assertRaises(updates.UpdateBusy): self.barrier.prepare()

    def test_worker_registration_is_released_when_start_fails(self):
        with patch.object(threading.Thread, "start", side_effect=RuntimeError("Cannot start")):
            with self.assertRaises(RuntimeError): updates.Thread(target=lambda: None).start()
        self.assertFalse(self.barrier.active)

    def test_operation_exception_does_not_leave_update_permanently_busy(self):
        with self.assertRaises(ValueError):
            with self.barrier.work("Failed import"): raise ValueError("fixture")
        self.assertFalse(self.barrier.active)


class UpdateApiTests(unittest.TestCase):
    def setUp(self):
        from paper_monitor.ui_server import FastLocalThreadingHTTPServer, PaperMonitorUiHandler
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "paper_monitor.sqlite"
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TABLE app_settings(key TEXT PRIMARY KEY, value TEXT)")
            db.execute("INSERT INTO app_settings VALUES('gewu_database_uuid','fixture-identity')")
        self.files = self.root / "paper.pdf"
        self.files.write_bytes(b"%PDF-1.4 synthetic untouched file")
        self.before = (self.db.read_bytes(), self.files.read_bytes())
        class Handler(PaperMonitorUiHandler):
            configured_db_path = self.db
            def log_message(self, *args): pass
        self.server = FastLocalThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.barrier = updates.Barrier(enabled=True)
        self.patch = patch.object(updates, "barrier", self.barrier); self.patch.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.worker.join(2)
        self.patch.stop(); self.tmp.cleanup()

    def call(self, action, token="", *, credential=True, origin=None, path="/api/macos-update"):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        headers = {"Content-Type":"application/json"}
        if credential: headers["X-Gewu-Workspace"] = self.server.workspace_access.token
        if origin: headers["Origin"] = origin
        conn.request("POST", path, json.dumps({"action": action, "token":token}), headers)
        response = conn.getresponse(); result = response.status, json.loads(response.read())
        conn.close(); return result

    def test_prepare_cancel_preserve_database_and_files_byte_for_byte(self):
        status, result = self.call("prepare")
        self.assertEqual(status, 200)
        self.assertEqual(self.call("cancel", result["token"])[0], 200)
        self.assertEqual((self.db.read_bytes(), self.files.read_bytes()), self.before)

    def test_missing_host_credentials_and_cross_origin_cannot_stop_service(self):
        self.assertIn(self.call("prepare", credential=False)[0], (401,403))
        self.assertEqual(self.call("prepare", origin="https://example.org")[0],403)
        self.assertFalse(self.barrier.token)

    def test_open_zotero_tab_defers_installation(self):
        self.server.zotero_sessions.update({"action":"heartbeat","session":"test-session-123"})
        self.assertEqual(self.call("prepare")[0],409)
        self.assertFalse(self.barrier.token)

    def test_import_between_files_requires_pause(self):
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TABLE zotero_import_jobs(state TEXT)")
            db.execute("INSERT INTO zotero_import_jobs VALUES('running')")
        self.assertEqual(self.call("prepare")[0],409)
        self.assertFalse(self.barrier.token)
        with sqlite3.connect(self.db) as db: db.execute("UPDATE zotero_import_jobs SET state='paused'")
        self.assertEqual(self.call("prepare")[0],200)

    def test_new_write_is_rejected_while_prepared(self):
        status, result = self.call("prepare")
        self.assertEqual(status,200)
        self.assertEqual(self.call("unexpected",path="/api/anything")[0],503)
        self.call("cancel",result["token"])

    def test_stop_shuts_down_only_after_preparation_and_retains_files(self):
        self.assertEqual(self.call("stop", "invalid")[0],409)
        status, result = self.call("prepare")
        self.assertEqual(self.call("stop", result["token"])[0],200)
        self.worker.join(2)
        self.assertFalse(self.worker.is_alive())
        self.assertEqual((self.db.read_bytes(),self.files.read_bytes()),self.before)


class HelperStartupTests(unittest.TestCase):
    def test_background_relaunch_cannot_race_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); app=root/"Gewu.app"; (app/"Contents").mkdir(parents=True)
            (app/"Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier":"com.gewu.updater-test"}))
            state=root/"updates"; state.mkdir()
            marker=state/"install.plist"; marker.write_bytes(plistlib.dumps({"app":str(app),"target":"11001"}))
            before=marker.read_bytes()
            with patch.dict(os.environ,GEWU_APP_PATH=str(app),GEWU_UPDATE_STATE_DIR=str(state)), patch.object(updates.sys,"platform","darwin"):
                with self.assertRaises(RuntimeError): updates.check_startup()
                self.assertEqual(marker.read_bytes(),before)
                marker.unlink(); updates.check_startup()




class MacFeedTests(unittest.TestCase):
    def setUp(self):
        from scripts.build_macos_appcast import make_feed
        self.make_feed = make_feed
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.installer = Path(self.tmp.name) / 'Gewu-Insight-macOS-1.1.0.dmg'
        self.installer.write_bytes(b'isolated installer fixture')
        self.manifest = dict(product='Gewu Insight', source_commit='a' * 40,
            architectures=['arm64', 'x86_64'], version='1.1.0', build='11001',
            minimum_macos='14.0', working_tree_files={},
            installer=dict(name=self.installer.name, sha256=hashlib.sha256(self.installer.read_bytes()).hexdigest()))

    def test_feed_uses_exact_mac_asset_and_escaped_notes(self):
        import xml.etree.ElementTree as ET
        x = ET.fromstring(self.make_feed(self.manifest, self.installer, 'fixture-signature', '<b>Notes & safety</b>'))
        enclosure = x.find('.//enclosure')
        self.assertEqual(enclosure.get('url'), 'https://github.com/LKong92/Gewu-Insight/releases/download/macos-1.1.0/Gewu-Insight-macOS-1.1.0.dmg')
        self.assertEqual(x.find('.//description').text, 'Official stable Mac updates')
        self.assertEqual(x.find('.//item/description').text, '<b>Notes & safety</b>')
        self.assertEqual(enclosure.get('{http://www.andymatuschak.org/xml-namespaces/sparkle}os'), 'macos')

    def test_changed_installer_cannot_be_announced(self):
        self.installer.write_bytes(b'changed bytes')
        with self.assertRaises(ValueError): self.make_feed(self.manifest, self.installer, 'sig', 'notes')

    def test_uncommitted_preview_cannot_be_announced(self):
        self.manifest['working_tree_files'] = {'paper_monitor/__init__.py': 'hash'}
        with self.assertRaises(ValueError): self.make_feed(self.manifest, self.installer, 'sig', 'notes')

    def test_wrong_platform_or_source_manifest_cannot_be_announced(self):
        for key, value in [('architectures', ['x86_64']), ('source_commit', 'HEAD'), ('product', 'Other')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.make_feed(dict(self.manifest, **{key:value}), self.installer, 'sig', 'notes')

    def test_windows_asset_and_prerelease_versions_are_rejected(self):
        for version in ['1.2.0-beta', '../../other']:
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.make_feed(dict(self.manifest, version=version), self.installer, 'sig', 'notes')
        self.manifest['installer']['name'] = 'Gewu-Insight-Windows-1.1.0.exe'
        with self.assertRaises(ValueError): self.make_feed(self.manifest, self.installer, 'sig', 'notes')


if __name__ == "__main__": unittest.main()
