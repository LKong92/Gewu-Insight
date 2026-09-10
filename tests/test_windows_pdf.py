from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from pypdf import PdfWriter

from paper_monitor import ui_server


@unittest.skipUnless(sys.platform == "win32", "Windows PDF renderer")
class WindowsPdfTests(unittest.TestCase):
    def test_real_png_concurrent_requests_and_original_unchanged(self):
        from PIL import Image
        from paper_monitor.windows_pdf import render_page_png

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf = root / "研究 #1.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=450)
            writer.write(pdf)
            before = pdf.read_bytes()
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(lambda n: render_page_png(pdf, n, 240), [1, 2, 0, 1]))
            for data in results:
                self.assertTrue(data.startswith(b"\x89PNG"))
                with Image.open(BytesIO(data)) as image:
                    self.assertEqual(image.size, (160, 240))
            with patch.object(ui_server, "PDF_THUMB_CACHE_DIR", root / "cache"):
                first = ui_server.pdf_page_thumbnail(pdf, 1)
                with patch("paper_monitor.windows_pdf.render_page_png", side_effect=AssertionError("cache miss")):
                    self.assertEqual(ui_server.pdf_page_thumbnail(pdf, 1), first)
            self.assertEqual(pdf.read_bytes(), before)

    def test_windows_settings_remove_unsupported_native_modes(self):
        from paper_monitor.storage import Storage
        with tempfile.TemporaryDirectory() as temporary:
            storage = Storage(Path(temporary) / "test.sqlite")
            try:
                html = ui_server.workspace_html(storage)
                self.assertNotIn('name="quick-look-mode" value="hybrid"', html)
                self.assertNotIn('name="quick-look-mode" value="native_all"', html)
                self.assertIn("Preview Settings", html)
            finally:
                storage.close()

    def test_page_count_refreshes_after_external_save_and_text_is_bounded(self):
        from paper_monitor.windows_pdf import page_count, page_text, page_sizes
        with tempfile.TemporaryDirectory() as temporary:
            pdf = Path(temporary) / "changed.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=450)
            writer.write(pdf)
            before = pdf.stat()
            self.assertEqual(page_count(str(pdf), before.st_size, before.st_mtime_ns), 1)
            self.assertEqual(page_sizes(str(pdf), before.st_size, before.st_mtime_ns), ((300.0, 450.0),))
            self.assertEqual(page_text(pdf, 1), "")
            writer.add_blank_page(width=450, height=300)
            writer.write(pdf)
            after = pdf.stat()
            self.assertEqual(page_count(str(pdf), after.st_size, after.st_mtime_ns), 2)
            self.assertEqual(page_sizes(str(pdf), after.st_size, after.st_mtime_ns), ((300.0, 450.0), (450.0, 300.0)))
            with self.assertRaisesRegex(ValueError, "page not found"):
                page_text(pdf, 3)
