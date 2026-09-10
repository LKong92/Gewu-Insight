"""Import targets must stay managed, including Windows-origin inventories."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from paper_monitor.importers.inventory import copy_record


class InventoryPathSafetyTests(unittest.TestCase):
    def test_cross_platform_absolute_and_parent_paths_never_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            source.write_text("original", encoding="utf-8")
            target = root / "managed"
            for value in (str(root / "outside.txt"), "/outside.txt", "C:/outside.txt",
                          "C:outside.txt", r"\\server\share\outside.txt", r"\outside.txt",
                          "../outside.txt", r"folder\..\outside.txt", "folder/../outside.txt"):
                with self.subTest(value=value), patch("paper_monitor.importers.inventory.shutil.copy2") as copy:
                    with self.assertRaises(ValueError):
                        copy_record({"source_path": str(source), "relative_path": value}, target_root=target)
                    copy.assert_not_called()
            self.assertFalse(target.exists())
            self.assertEqual(source.read_text(encoding="utf-8"), "original")

    def test_valid_unicode_path_and_collision_preserve_both_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.txt"
            source.write_text("original", encoding="utf-8")
            target = root / "managed"
            record = {"source_path": str(source), "relative_path": "研究 papers/note #1.txt"}
            first = Path(copy_record(record, target_root=target))
            source.write_text("new content", encoding="utf-8")
            second = Path(copy_record(record, target_root=target))
            self.assertNotEqual(first, second)
            self.assertTrue(first.is_relative_to(target))
            self.assertTrue(second.is_relative_to(target))
            self.assertEqual(first.read_text(encoding="utf-8"), "original")
            self.assertEqual(second.read_text(encoding="utf-8"), "new content")
