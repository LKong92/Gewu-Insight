from __future__ import annotations

from io import BytesIO
from http import HTTPStatus
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from pypdf import PdfWriter

from paper_monitor import ui_server


class PdfQuickLookPerformanceTests(unittest.TestCase):
    @staticmethod
    def js_function(name: str) -> str:
        marker = f"function {name}"
        start = ui_server.INDEX_HTML.index(marker)
        candidates = [
            position
            for position in (
                ui_server.INDEX_HTML.find("\n    function ", start + len(marker)),
                ui_server.INDEX_HTML.find("\n    async function ", start + len(marker)),
            )
            if position >= 0
        ]
        end = min(candidates) if candidates else len(ui_server.INDEX_HTML)
        return ui_server.INDEX_HTML[start:end]

    def make_handler(self, *, range_header: str = "", extra_headers: dict[str, str] | None = None):
        handler = object.__new__(ui_server.PaperMonitorUiHandler)
        handler.headers = {"Range": range_header, **(extra_headers or {})}
        handler.wfile = BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        return handler

    @staticmethod
    def response_headers(handler) -> dict[str, str]:
        return {call.args[0]: call.args[1] for call in handler.send_header.call_args_list}

    def test_single_byte_range_parser_supports_standard_forms(self) -> None:
        self.assertEqual(ui_server.parse_single_byte_range("bytes=0-9", 100), (0, 9))
        self.assertEqual(ui_server.parse_single_byte_range("bytes=90-", 100), (90, 99))
        self.assertEqual(ui_server.parse_single_byte_range("bytes=-10", 100), (90, 99))
        self.assertEqual(ui_server.parse_single_byte_range("bytes=0-999", 100), (0, 99))
        self.assertIsNone(ui_server.parse_single_byte_range("", 100))
        with self.assertRaises(ValueError):
            ui_server.parse_single_byte_range("bytes=100-101", 100)
        with self.assertRaises(ValueError):
            ui_server.parse_single_byte_range("bytes=0-1,5-6", 100)

    def test_local_file_response_streams_only_the_requested_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.pdf"
            path.write_bytes(b"0123456789")
            handler = self.make_handler(range_header="bytes=2-5")

            handler.send_local_file(path, "application/pdf")

        handler.send_response.assert_called_once_with(HTTPStatus.PARTIAL_CONTENT)
        headers = self.response_headers(handler)
        self.assertEqual(headers["Accept-Ranges"], "bytes")
        self.assertEqual(headers["Content-Range"], "bytes 2-5/10")
        self.assertEqual(headers["Content-Length"], "4")
        self.assertEqual(handler.wfile.getvalue(), b"2345")

    def test_local_file_response_revalidates_unchanged_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.pdf"
            path.write_bytes(b"0123456789")
            _stat, etag, _modified = ui_server.local_file_response_metadata(path)
            handler = self.make_handler(extra_headers={"If-None-Match": etag})

            handler.send_local_file(path, "application/pdf")

        handler.send_response.assert_called_once_with(HTTPStatus.NOT_MODIFIED)
        self.assertEqual(handler.wfile.getvalue(), b"")
        self.assertEqual(self.response_headers(handler)["ETag"], etag)

    def test_invalid_range_does_not_send_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.pdf"
            path.write_bytes(b"0123456789")
            handler = self.make_handler(range_header="bytes=20-30")

            handler.send_local_file(path, "application/pdf")

        handler.send_response.assert_called_once_with(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
        self.assertEqual(self.response_headers(handler)["Content-Range"], "bytes */10")
        self.assertEqual(handler.wfile.getvalue(), b"")

    def test_pdf_page_count_cache_invalidates_when_the_file_changes(self) -> None:
        ui_server.cached_pdf_page_count.cache_clear()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            with path.open("wb") as handle:
                writer.write(handle)
            first = path.stat()
            self.assertEqual(
                ui_server.cached_pdf_page_count(str(path), first.st_size, first.st_mtime_ns),
                1,
            )

            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            writer.add_blank_page(width=100, height=100)
            with path.open("wb") as handle:
                writer.write(handle)
            os.utime(path, ns=(first.st_atime_ns, first.st_mtime_ns + 1_000_000))
            second = path.stat()
            self.assertEqual(
                ui_server.cached_pdf_page_count(str(path), second.st_size, second.st_mtime_ns),
                2,
            )

    def test_quicklook_starts_native_pdf_before_loading_page_metadata(self) -> None:
        quicklook = self.js_function("quickLookLibraryPdf")
        info_loader = self.js_function("loadLibraryQuickLookInfo")
        frame_url = self.js_function("libraryPdfFrameUrl")
        scheduler = self.js_function("scheduleLibraryQuickLookThumbs")

        self.assertLess(quicklook.index("renderLibraryQuickLookPages(0)"), quicklook.index("loadLibraryQuickLookInfo"))
        self.assertIn("scheduleLibraryQuickLookThumbs(path", info_loader)
        self.assertNotIn("pm_nonce", frame_url)
        self.assertIn('frame.addEventListener("load", renderWhenIdle', scheduler)
        self.assertIn("requestIdleCallback", scheduler)

    def test_quicklook_reuses_only_the_same_pdf_and_replaces_the_frame_for_a_new_path(self) -> None:
        renderer = self.js_function("renderLibraryQuickLookPages")

        self.assertIn(
            "existingFrame?.dataset.pdfPath === state.libraryQuickLookPath",
            renderer,
        )
        self.assertIn("root.innerHTML = `<iframe", renderer)
        self.assertIn("frame.dataset.pdfPath = state.libraryQuickLookPath", renderer)
        self.assertLess(
            renderer.index("existingFrame?.dataset.pdfPath"),
            renderer.index("root.innerHTML = `<iframe"),
        )

    def test_startup_retains_bounded_thumbnail_cache(self) -> None:
        source = ui_server.run_ui_server.__code__.co_names
        self.assertIn("trim_pdf_thumbnail_cache_if_needed", source)
        self.assertNotIn("clear_pdf_thumbnail_cache", source)


if __name__ == "__main__":
    unittest.main()
