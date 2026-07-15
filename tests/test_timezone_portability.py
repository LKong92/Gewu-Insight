import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from paper_monitor.storage import Storage
from paper_monitor.time_utils import local_timezone, system_timezone_name
from paper_monitor.ui_server import arxiv_auto_target


class TimezonePortabilityTests(unittest.TestCase):
    def test_environment_timezone_is_an_iana_zone(self):
        with patch.dict(os.environ, {"TZ": "America/New_York"}):
            self.assertEqual(system_timezone_name(), "America/New_York")
            self.assertEqual(getattr(local_timezone(), "key", ""), "America/New_York")

    def test_existing_arxiv_papers_move_when_system_timezone_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "monitor.sqlite"
            with patch.dict(os.environ, {"TZ": "Asia/Shanghai"}):
                storage = Storage(db_path)
                storage.upsert_paper(
                    {
                        "paper_id": "arxiv_timezone_test",
                        "title": "Timezone test",
                        "journal": "arXiv",
                        "publication_date": "2026-06-22",
                        "source": "arxiv",
                        "publisher_section": "preprint",
                        "section_allowed": True,
                        "raw": {"published": "2026-06-18T19:00:00Z"},
                    }
                )
                storage.close()

            with patch.dict(os.environ, {"TZ": "America/New_York"}):
                storage = Storage(db_path)
                self.assertEqual(storage.get_paper("arxiv_timezone_test")["publication_date"], "2026-06-21")
                self.assertEqual(storage.get_setting("arxiv_calendar_timezone"), "America/New_York")
                run_id = storage.start_fetch_run(
                    monitor_type="journal",
                    source="arxiv",
                    journal="arXiv",
                    window_start="2026-06-21",
                    window_end="2026-06-21",
                    started_at="2026-06-21T20:20:00-04:00",
                )
                row = storage.conn.execute("SELECT timezone_name FROM fetch_runs WHERE id = ?", (run_id,)).fetchone()
                self.assertEqual(row["timezone_name"], "America/New_York")
                storage.close()

    def test_auto_arxiv_target_uses_the_installations_local_date(self):
        instant = datetime(2026, 7, 20, 13, 0, tzinfo=ZoneInfo("UTC"))
        with patch.dict(os.environ, {"TZ": "America/New_York"}):
            announcement, target, ready_at = arxiv_auto_target(instant)
            self.assertEqual((announcement, target.isoformat()), ("2026-07-19", "2026-07-19"))
            self.assertEqual(ready_at.isoformat(), "2026-07-19T20:20:00-04:00")
        with patch.dict(os.environ, {"TZ": "Asia/Shanghai"}):
            announcement, target, ready_at = arxiv_auto_target(instant)
            self.assertEqual((announcement, target.isoformat()), ("2026-07-19", "2026-07-20"))
            self.assertEqual(ready_at.isoformat(), "2026-07-20T08:20:00+08:00")


if __name__ == "__main__":
    unittest.main()
