from pathlib import Path
from io import BytesIO
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from paper_monitor import ui_server
from paper_monitor.ui_server import MARKDOWN_PREVIEW_MAX_BYTES, markdown_preview_payload

ROOT = Path(__file__).resolve().parents[1]


class MarkdownPreviewTests(unittest.TestCase):
    def request(self, path, etag=""):
        handler = object.__new__(ui_server.PaperMonitorUiHandler)
        handler.headers = {"If-None-Match": etag}
        handler.wfile = BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.send_error_json = MagicMock()
        handler.handle_markdown_preview({"path": [str(path)]})
        return handler, dict(call.args for call in handler.send_header.call_args_list)

    def test_unchanged_preview_revalidates_without_reading_file_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "note.md"
            path.write_text("# Current note")
            first, headers = self.request(path)
            self.assertEqual(json.loads(first.wfile.getvalue())["text"], "# Current note")
            with patch.object(ui_server, "markdown_preview_payload", side_effect=AssertionError("No reread")):
                repeated, repeated_headers = self.request(path, headers["ETag"])
            repeated.send_response.assert_called_once_with(304)
            self.assertEqual(repeated.wfile.getvalue(), b"")
            self.assertEqual(repeated_headers["ETag"], headers["ETag"])
            self.assertEqual(repeated_headers["Cache-Control"], "no-store")

    def test_file_edits_and_same_size_replacements_invalidate_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "note.md"
            path.write_text("# Old")
            before = path.stat()
            _, headers = self.request(path)
            path.write_text("# New")
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            changed, updated = self.request(path, headers["ETag"])
            changed.send_response.assert_called_once_with(200)
            self.assertEqual(json.loads(changed.wfile.getvalue())["text"], "# New")
            self.assertNotEqual(headers["ETag"], updated["ETag"])
            replacement = path.with_name("replacement.md")
            replacement.write_text("# Now")
            os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
            replacement.replace(path)
            replaced, _ = self.request(path, updated["ETag"])
            replaced.send_response.assert_called_once_with(200)
            self.assertEqual(json.loads(replaced.wfile.getvalue())["text"], "# Now")
            path.unlink()
            missing, _ = self.request(path, updated["ETag"])
            self.assertEqual(missing.send_error_json.call_args.args[0], 404)

    def test_concurrent_edit_is_not_cached_and_invalid_extension_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "note.md"
            path.write_text("# Before")
            def change_during_read(_path):
                content = markdown_preview_payload(_path)
                path.write_text("# Changed while reading")
                return content
            with patch.object(ui_server, "markdown_preview_payload", side_effect=change_during_read):
                _, headers = self.request(path)
            self.assertNotIn("ETag", headers)
            invalid, _ = self.request(path.with_suffix(".pdf"), 'W/"old"')
            self.assertEqual(invalid.send_error_json.call_args.args[0], 400)

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
    def test_renderer_and_front_matter(self):
        result = subprocess.run([shutil.which("node"), str(ROOT / "tests/markdown_preview_probe.cjs")],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Markdown worker checks passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_offline_math_and_literal_content(self):
        result = subprocess.run([shutil.which("node"), str(ROOT / "tests/markdown_math_probe.cjs")],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Markdown math checks passed", result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_preview_request_lifecycle(self):
        result = subprocess.run([shutil.which("node"), str(ROOT / "tests/markdown_preview_flow_probe.cjs")],
                                input=json.dumps(ui_server.INDEX_HTML), capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Markdown preview flow checks passed", result.stdout)
