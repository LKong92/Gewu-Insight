import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from paper_monitor.storage import Storage
from paper_monitor import ui_server


class AutoMonitorUpdateTest(unittest.TestCase):
    def test_journal_waiting_target_is_filled_after_active_fetch_finishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "paper_monitor.sqlite"
            ui_server.write_auto_journal_monitor_status(
                db_path,
                {
                    "run_date": "2026-07-23",
                    "targets": [
                        {
                            "date": "2026-07-23",
                            "status": "waiting",
                            "reason": "fetch already active",
                            "pending": True,
                        }
                    ],
                },
            )
            missing_calls = iter([["Nature"], []])
            original_load_config = ui_server.load_config
            original_configured_names = ui_server.configured_source_names
            original_missing = ui_server.missing_fetch_journals_for_date
            original_fetch = ui_server.fetch_missing_sources_for_date
            try:
                ui_server.load_config = lambda: object()
                ui_server.configured_source_names = lambda _config: ["Nature"]
                ui_server.missing_fetch_journals_for_date = lambda *_args: next(missing_calls)
                ui_server.fetch_missing_sources_for_date = lambda **_kwargs: None
                self.assertTrue(ui_server.run_pending_auto_journal_monitor_once(db_path))
            finally:
                ui_server.load_config = original_load_config
                ui_server.configured_source_names = original_configured_names
                ui_server.missing_fetch_journals_for_date = original_missing
                ui_server.fetch_missing_sources_for_date = original_fetch

            storage = Storage(db_path)
            try:
                status = json.loads(storage.get_setting(ui_server.AUTO_JOURNAL_MONITOR_STATUS_SETTING, "{}"))
            finally:
                storage.close()
            target = status["targets"][0]
            self.assertEqual(target["status"], "fetched")
            self.assertFalse(target["pending"])
            self.assertEqual(target["remaining_sources"], [])

    def test_due_subject_retry_uses_persisted_failed_tasks_and_clears_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "paper_monitor.sqlite"
            selected = "2026-07-22"
            groups = {"test_subject": {"name": "Test Subject", "queries": ["alpha"]}}
            storage = Storage(db_path)
            try:
                storage.set_setting(
                    ui_server.AUTO_SUBJECT_MONITOR_RETRY_SETTING,
                    json.dumps(
                        {
                            "items": [
                                {
                                    "date": selected,
                                    "group_key": "test_subject",
                                    "group_name": "Test Subject",
                                    "failed_tasks": [{"query": "alpha", "source": "temporary_source"}],
                                    "retry_count": 0,
                                    "next_retry_at": (datetime.now().astimezone() - timedelta(minutes=1)).isoformat(),
                                }
                            ]
                        }
                    ),
                )
            finally:
                storage.close()

            calls = []

            def recovered_source(query, start_date, end_date):
                calls.append((query, start_date.isoformat(), end_date.isoformat()))
                return []

            original_groups = ui_server.load_theme_groups
            original_fetchers = ui_server.theme_source_fetchers
            try:
                ui_server.load_theme_groups = lambda _storage: groups
                ui_server.theme_source_fetchers = lambda: [("temporary_source", recovered_source)]
                result = ui_server.run_due_auto_subject_retries_once(db_path)
            finally:
                ui_server.load_theme_groups = original_groups
                ui_server.theme_source_fetchers = original_fetchers

            self.assertEqual(calls, [("alpha", selected, selected)])
            self.assertEqual(result["attempted"], 1)
            self.assertEqual(result["succeeded"], 1)
            self.assertEqual(result["remaining"], 0)
            storage = Storage(db_path)
            try:
                retry_state = json.loads(storage.get_setting(ui_server.AUTO_SUBJECT_MONITOR_RETRY_SETTING, "{}"))
            finally:
                storage.close()
            self.assertEqual(retry_state["items"], [])


if __name__ == "__main__":
    unittest.main()
