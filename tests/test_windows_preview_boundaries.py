"""Platform boundary behavior with disposable files; no app or reader is opened."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from paper_monitor import desktop_files, ui_server


@unittest.skipUnless(sys.platform == "win32", "Windows Preview boundaries")
class WindowsPreviewBoundariesTests(unittest.TestCase):
    def test_unverified_permanent_removal_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "研究 #1.txt"
            source.write_text("synthetic contents", encoding="utf-8")
            with self.assertRaisesRegex(OSError, "file has been preserved"):
                ui_server.move_path_to_macos_trash(source)
            self.assertEqual(source.read_text(encoding="utf-8"), "synthetic contents")

    def test_open_placement_resolves_to_one_real_file_without_shell_command(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "研究 #1.txt"
            source.write_text("synthetic contents", encoding="utf-8")
            entry = desktop_files.create_placement(source, Path(directory) / "Other Space" / source.name)
            with patch("os.startfile") as start:
                desktop_files.open_file(entry)
            start.assert_called_once_with(str(source.resolve()))

    def test_missing_file_does_not_invoke_default_application(self):
        with tempfile.TemporaryDirectory() as directory, patch("os.startfile") as start:
            with self.assertRaises(FileNotFoundError):
                desktop_files.open_file(Path(directory) / "missing.pdf")
            start.assert_not_called()
