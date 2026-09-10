"""Real Windows Shell shortcuts, with disposable files and no symlink privilege."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from paper_monitor import desktop_files as desktop
from paper_monitor.importers.inventory import file_kind, import_as_for_kind


@unittest.skipUnless(sys.platform == "win32", "Windows Shell integration")
class WindowsPlacementsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "研究 original.pdf"
        self.source.write_bytes(b"synthetic original")

    def test_multiple_entries_follow_atomic_replacement_and_do_not_become_resources(self):
        a = desktop.create_placement(self.source, self.root / "Library" / "Paper #1.pdf")
        b = desktop.create_placement(self.source, self.root / "Space" / "Paper, two.pdf")
        replacement = self.root / "replacement.pdf"
        replacement.write_bytes(b"synthetic annotated")
        os.replace(replacement, self.source)
        for entry in (a, b):
            self.assertTrue(desktop.is_placement(entry))
            self.assertEqual(desktop.resolve_placement(entry).read_bytes(), b"synthetic annotated")
            self.assertEqual(import_as_for_kind(file_kind(entry)), "alias_reference")
        a.unlink()
        self.assertTrue(b.exists())
        self.assertTrue(self.source.exists())

    def test_collision_reuse_and_missing_target_preserve_reference(self):
        logical = self.root / "Space" / "Paper.pdf"
        logical.parent.mkdir()
        logical.write_bytes(b"unrelated real file")
        link = desktop.create_placement(self.source, logical)
        self.assertEqual(link.name, "Paper 2.pdf.lnk")
        self.assertEqual(desktop.create_placement(self.source, logical), link)
        self.source.rename(self.root / "renamed.pdf")
        self.assertTrue(desktop.is_placement(link))
        self.assertEqual(desktop.resolve_placement(link), self.source)
        self.assertFalse(desktop.resolve_placement(link).exists())
        self.assertEqual(logical.read_bytes(), b"unrelated real file")

    def test_unmanaged_shortcut_is_not_a_managed_placement(self):
        import pythoncom
        with desktop.shell_link() as shortcut:
            shortcut.SetPath(str(self.source))
            path = self.root / "User shortcut.lnk"
            shortcut.QueryInterface(pythoncom.IID_IPersistFile).Save(str(path), 1)
        self.assertFalse(desktop.is_placement(path))
        self.assertEqual(desktop.resolve_placement(path), path)

    def test_failed_link_save_does_not_leave_an_entry_or_touch_pdf(self):
        logical = self.root / "Space" / "Paper.pdf"
        with patch.object(desktop, "shell_link", side_effect=OSError("synthetic save failure")):
            with self.assertRaises(OSError):
                desktop.create_placement(self.source, logical)
        self.assertEqual(list(logical.parent.iterdir()), [])
        self.assertEqual(self.source.read_bytes(), b"synthetic original")

    def test_windows_reserved_names_and_characters_are_safe(self):
        for name in ("CON.pdf", "aux", "COM1.txt", "LPT9", "nul.pdf"):
            self.assertTrue(desktop.safe_filename(name).startswith("_"))
        self.assertEqual(desktop.safe_filename('研究: a?b|c*.pdf'), '研究- a-b-c-.pdf')
