import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from paper_monitor.storage import Storage
from paper_monitor import ui_server


class AutoMonitorUpdateTest(unittest.TestCase):
    def test_arxiv_automatic_import_runs_once_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "paper_monitor.sqlite"
            current = datetime.now().astimezone()
            target = current.date()
            calls = []
            original_target = ui_server.arxiv_auto_target
            original_fetch = ui_server.fetch_one_arxiv_preprint_source
            original_match = ui_server.match_local_arxiv_for_all_subjects
            original_schedule = ui_server.schedule_pending_arxiv_metadata_retry
            original_retry = ui_server.retry_pending_arxiv_metadata
            try:
                ui_server.arxiv_auto_target = lambda _now: ("2026-07-22", target, current)

                def successful_fetch(**_kwargs):
                    calls.append("fetch")
                    return {
                        "source_statuses": {"arxiv": "success"},
                        "saved": 12,
                        "message": "",
                    }

                ui_server.fetch_one_arxiv_preprint_source = successful_fetch
                ui_server.match_local_arxiv_for_all_subjects = lambda *_args: {}
                ui_server.schedule_pending_arxiv_metadata_retry = lambda *_args: 0
                ui_server.retry_pending_arxiv_metadata = lambda *_args: {"status": "complete", "pending": 0}
                first = ui_server.run_auto_arxiv_monitor_once(db_path, current)
                second = ui_server.run_auto_arxiv_monitor_once(db_path, current)
            finally:
                ui_server.arxiv_auto_target = original_target
                ui_server.fetch_one_arxiv_preprint_source = original_fetch
                ui_server.match_local_arxiv_for_all_subjects = original_match
                ui_server.schedule_pending_arxiv_metadata_retry = original_schedule
                ui_server.retry_pending_arxiv_metadata = original_retry

            self.assertEqual(first["status"], "fetched")
            self.assertEqual(second["reason"], "already complete")
            self.assertEqual(calls, ["fetch"])

    def test_arxiv_stale_listing_respects_retry_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "paper_monitor.sqlite"
            current = datetime.now().astimezone()
            target = current.date()
            calls = []
            original_target = ui_server.arxiv_auto_target
            original_fetch = ui_server.fetch_one_arxiv_preprint_source
            try:
                ui_server.arxiv_auto_target = lambda _now: ("2026-07-22", target, current)

                def waiting_fetch(**_kwargs):
                    calls.append("fetch")
                    return {
                        "source_statuses": {"arxiv": "error"},
                        "saved": 0,
                        "message": "arXiv latest listing has not advanced to the expected announcement yet",
                    }

                ui_server.fetch_one_arxiv_preprint_source = waiting_fetch
                first = ui_server.run_auto_arxiv_monitor_once(db_path, current)
                second = ui_server.run_auto_arxiv_monitor_once(db_path, current + timedelta(minutes=1))
            finally:
                ui_server.arxiv_auto_target = original_target
                ui_server.fetch_one_arxiv_preprint_source = original_fetch

            self.assertEqual(first["status"], "waiting")
            self.assertEqual(second["reason"], "retry cooldown")
            self.assertEqual(calls, ["fetch"])

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
