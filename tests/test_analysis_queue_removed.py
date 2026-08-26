from pathlib import Path
import contextlib
import io
import unittest

from paper_monitor import ui_server
from paper_monitor.cli import build_parser


class AnalysisQueueRemovalTests(unittest.TestCase):
    def test_legacy_analysis_queue_commands_are_not_exposed(self) -> None:
        parser = build_parser()

        for argv in (
            ["analyze", "paper-1"],
            ["analysis-queue"],
            ["complete-analysis-job", "job.md"],
        ):
            with self.subTest(argv=argv):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        parser.parse_args(argv)

        self.assertEqual(parser.parse_args(["download", "paper-1"]).command, "download")

    def test_note_compatibility_remains_without_queue_creation_api(self) -> None:
        source = Path(ui_server.__file__).read_text(encoding="utf-8")

        self.assertNotIn('"/api/analyze"', source)
        self.assertNotIn("Queueing Codex analysis", source)
        self.assertIn('"/api/analysis"', source)
        self.assertIn('"/api/delete-analysis"', source)
