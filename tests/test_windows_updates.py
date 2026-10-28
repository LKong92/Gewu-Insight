"""Installation barriers protect admitted work and leave research data alone."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing
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
        with closing(sqlite3.connect(self.db)) as db, db:
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
        self.platform_patch = patch("paper_monitor.ui_server.sys.platform", "win32")
        self.platform_patch.start()
        self.barrier = updates.Barrier(enabled=True)
        self.patch = patch.object(updates, "barrier", self.barrier); self.patch.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.worker.join(2)
        self.platform_patch.stop(); self.patch.stop(); self.tmp.cleanup()

    def call(self, action, token="", *, credential=True, origin=None, path="/api/windows-update"):
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
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("CREATE TABLE zotero_import_jobs(state TEXT)")
            db.execute("INSERT INTO zotero_import_jobs VALUES('running')")
        self.assertEqual(self.call("prepare")[0],409)
        self.assertFalse(self.barrier.token)
        with closing(sqlite3.connect(self.db)) as db, db: db.execute("UPDATE zotero_import_jobs SET state='paused'")
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



if __name__ == "__main__": unittest.main()
