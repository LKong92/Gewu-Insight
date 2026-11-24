"""Subject status reads must not hold the writer lock across background work."""
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from paper_monitor import ui_server as ui
from paper_monitor.storage import Storage
from paper_monitor.time_utils import local_timezone


class SubjectDatabaseTransactionTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "test.sqlite"
        self.reader = Storage(self.path)
        self.addCleanup(self.reader.close)
        self.writer = Storage(self.path)
        self.addCleanup(self.writer.close)
        self.reader.conn.execute("PRAGMA busy_timeout=0")
        self.writer.conn.execute("PRAGMA busy_timeout=0")
        self.day = "2026-11-22"
        self.key = "LOCK_PROBE"
        self.reader.upsert_paper({
            "paper_id": "download-probe", "title": "Download fixture",
            "source": "fixture", "journal": "Fixture", "type": "article",
            "publication_date": self.day, "section_allowed": True,
        })
        ui.save_custom_theme_groups(self.reader, [{
            "key": self.key, "name": "Lock probe", "queries": ["physics"],
            "is_custom": True,
        }])

    def stale_run(self):
        return self.reader.start_fetch_run(
            monitor_type="theme", source="multi", journal="theme:" + self.key,
            window_start=self.day, window_end=self.day,
            started_at="2000-01-01T00:00:00+00:00",
        )

    def test_status_reads_allow_subject_add_and_pdf_status_write(self):
        readers = [
            lambda: ui.theme_counts_for_month(self.reader, prefix="2026-11", group_keys=[self.key]),
            lambda: ui.theme_fetch_completed_group_keys(self.reader, self.day, [self.key]),
            lambda: ui.missing_theme_group_keys_for_date(self.reader, self.day, [self.key]),
        ]
        for read in readers:
            read()
            self.assertFalse(self.reader.conn.in_transaction)
            ui.save_custom_theme_groups(self.writer, [{
                "key": self.key, "name": "Lock probe", "queries": ["physics"],
                "is_custom": True,
            }])
            self.writer.update_download_status("download-probe", status="partial", message="PDF saved")
        self.assertEqual(self.reader.get_paper("download-probe")["download_status"], "partial")

    def test_ordinary_calendar_read_does_not_wait_for_an_existing_writer(self):
        self.writer.conn.execute("INSERT INTO app_settings VALUES ('uncommitted', 'value', '')")
        ui.theme_counts_for_month(self.reader, prefix="2026-11", group_keys=[self.key])
        self.assertFalse(self.reader.conn.in_transaction)
        self.assertTrue(self.writer.conn.in_transaction)

    def test_stale_cleanup_persists_and_releases_its_transaction(self):
        run_id = self.stale_run()
        info = ui.theme_last_fetch_info(self.reader, self.day, [self.key])
        self.assertEqual(info["groups"][self.key]["status"], "error")
        self.assertFalse(self.reader.conn.in_transaction)
        row = self.writer.conn.execute("SELECT status, message FROM fetch_runs WHERE id=?", (run_id,)).fetchone()
        self.assertEqual(row["status"], "error")
        self.assertIn("interrupted", row["message"])
        self.writer.set_setting("after_cleanup", "ok")

    def test_stale_cleanup_does_not_commit_the_callers_changes(self):
        run_id = self.stale_run()
        self.reader.conn.execute("INSERT INTO app_settings VALUES ('uncommitted', 'value', '')")
        ui.mark_stale_theme_fetch_runs(self.reader)
        self.assertTrue(self.reader.conn.in_transaction)
        self.assertEqual(self.writer.get_setting("uncommitted"), "")
        self.reader.conn.rollback()
        self.assertEqual(self.reader.get_setting("uncommitted"), "")
        self.assertEqual(self.reader.conn.execute("SELECT status FROM fetch_runs WHERE id=?", (run_id,)).fetchone()[0], "running")

    def test_failed_cleanup_releases_writer_lock(self):
        self.stale_run()
        self.reader.conn.execute("""CREATE TEMP TRIGGER reject_cleanup BEFORE UPDATE ON fetch_runs
            BEGIN SELECT RAISE(ABORT, 'cleanup rejected'); END""")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "cleanup rejected"):
            ui.mark_stale_theme_fetch_runs(self.reader)
        self.assertFalse(self.reader.conn.in_transaction)
        self.writer.set_setting("after_failed_cleanup", "ok")

    def test_concurrent_cleanup_that_leaves_zero_rows_still_releases_transaction(self):
        self.stale_run()
        # Another connection finishes cleanup after the read found a stale row.
        def finish_first(statement):
            if statement.startswith("SAVEPOINT"):
                self.writer.conn.execute("UPDATE fetch_runs SET status='error'")
                self.writer.conn.commit()
        self.reader.conn.set_trace_callback(finish_first)
        try:
            ui.mark_stale_theme_fetch_runs(self.reader)
        finally:
            self.reader.conn.set_trace_callback(None)
        self.assertFalse(self.reader.conn.in_transaction)
        self.writer.set_setting("after_concurrent_cleanup", "ok")

    def seed_retry(self, current):
        item = {
            "date": self.day, "group_key": self.key, "group_name": "Lock probe",
            "failed_tasks": [{"query": "physics", "source": "probe_source"}],
            "retry_count": 0, "next_retry_at": (current - timedelta(minutes=1)).isoformat(),
        }
        ui.write_auto_subject_retry_state(self.reader, {"items": [item]})

    def test_retry_releases_status_read_before_network_work_and_completes(self):
        current = datetime.now(local_timezone())
        self.seed_retry(current)
        def fetch(query, start, end):
            self.writer.set_setting("write_during_network", "ok")
            return []
        with ExitStack() as stack:
            stack.enter_context(patch.object(ui, "theme_source_fetchers", return_value=[("probe_source", fetch)]))
            stack.enter_context(patch.object(ui, "local_arxiv_theme_candidates", return_value=([], "empty", "")))
            stack.enter_context(patch.object(ui, "local_aps_rss_theme_candidates", return_value=([], "empty", "")))
            result = ui.run_due_auto_subject_retries_once(self.path, current)
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(ui.read_auto_subject_retry_state(self.reader)["items"], [])
        self.assertEqual(self.reader.get_setting("write_during_network"), "ok")

    def test_retry_exceptions_back_off_and_stop_at_the_limit(self):
        current = datetime.now(local_timezone())
        self.seed_retry(current)
        with patch.object(ui, "run_theme_monitor", side_effect=sqlite3.OperationalError("database is locked")) as run:
            for attempt in range(1, ui.AUTO_SUBJECT_MONITOR_MAX_RETRIES + 1):
                result = ui.run_due_auto_subject_retries_once(self.path, current)
                self.assertEqual(result["attempted"], 1)
                item = ui.read_auto_subject_retry_state(self.reader)["items"][0]
                self.assertEqual(item["retry_count"], attempt)
                self.assertEqual(item["exhausted"], attempt == ui.AUTO_SUBJECT_MONITOR_MAX_RETRIES)
                self.assertGreater(datetime.fromisoformat(item["next_retry_at"]), current)
                ui.run_due_auto_subject_retries_once(self.path, current + timedelta(seconds=60))
                self.assertEqual(run.call_count, attempt)
                current += timedelta(seconds=ui.AUTO_SUBJECT_MONITOR_RETRY_SECONDS + 1)
            ui.run_due_auto_subject_retries_once(self.path, current + timedelta(days=1))
            self.assertEqual(run.call_count, ui.AUTO_SUBJECT_MONITOR_MAX_RETRIES)
        self.assertTrue(ui.try_start_theme_fetch(self.day))
        ui.finish_theme_fetch(self.day)

    def test_retry_connection_failure_releases_active_fetch_and_is_bounded(self):
        current = datetime.now(local_timezone())
        self.seed_retry(current)
        real_storage = ui.Storage
        calls = 0
        def fail_retry_connection(path):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise sqlite3.OperationalError("database is locked")
            return real_storage(path)
        with patch.object(ui, "Storage", side_effect=fail_retry_connection):
            ui.run_due_auto_subject_retries_once(self.path, current)
        item = ui.read_auto_subject_retry_state(self.reader)["items"][0]
        self.assertEqual(item["retry_count"], 1)
        self.assertGreater(datetime.fromisoformat(item["next_retry_at"]), current)
        self.assertTrue(ui.try_start_theme_fetch(self.day))
        ui.finish_theme_fetch(self.day)
