from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from paper_monitor.ui_server import MARKDOWN_PREVIEW_MAX_BYTES, markdown_preview_payload

ROOT = Path(__file__).resolve().parents[1]


class MarkdownPreviewTests(unittest.TestCase):
    def test_unicode_and_bom_files_keep_their_text_and_original_bytes(self):
        text = "# 分析\n\n**Result**\n\n| A | B |\n| - | - |\n| 1 | 2 |\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "note.md"
            for encoding in ("utf-8", "utf-8-sig", "utf-16"):
                original = text.encode(encoding)
                path.write_bytes(original)
                self.assertEqual(markdown_preview_payload(path), {"text": text, "truncated": False})
                self.assertEqual(path.read_bytes(), original)

    def test_large_file_read_is_bounded_and_reports_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "long.md"
            path.write_bytes(b"a" * (MARKDOWN_PREVIEW_MAX_BYTES * 3))
            result = markdown_preview_payload(path)
            self.assertEqual(len(result["text"]), MARKDOWN_PREVIEW_MAX_BYTES)
            self.assertTrue(result["truncated"])

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_renderer_and_obsolete_read_cancellation(self):
        result = subprocess.run([shutil.which("node"), str(ROOT / "tests/markdown_preview_probe.cjs")],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Markdown worker checks passed", result.stdout)
