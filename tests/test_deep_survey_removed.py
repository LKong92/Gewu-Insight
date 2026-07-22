from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeepSurveyRemovalTests(unittest.TestCase):
    def test_deep_survey_program_directory_is_removed(self) -> None:
        self.assertFalse((ROOT / "deep_survey").exists())

    def test_main_application_has_no_deep_survey_entry_points(self) -> None:
        checked_files = (
            ROOT / "paper_monitor" / "ui_server.py",
            ROOT / "scripts" / "PaperMonitorApp.m",
            ROOT / "scripts" / "make_release.sh",
            ROOT / "README.md",
        )
        forbidden = ("deep survey", "deep-survey", "deep_survey", "deepsurvey")

        for path in checked_files:
            content = path.read_text(encoding="utf-8").lower()
            for marker in forbidden:
                self.assertNotIn(marker, content, f"{marker!r} remains in {path}")


if __name__ == "__main__":
    unittest.main()
