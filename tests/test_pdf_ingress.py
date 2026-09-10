from __future__ import annotations

import hashlib
from io import BytesIO
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Text

from paper_monitor import download, pdf_utils, ui_server
from paper_monitor.storage import Storage


def make_clean_pdf() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(output)
    return output.getvalue()


def make_annotated_copy(clean_pdf: bytes) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.append_pages_from_reader(PdfReader(BytesIO(clean_pdf)))
    writer.add_annotation(
        page_number=0,
        annotation=Text(rect=(72, 700, 96, 724), text="personal note"),
    )
    writer.write(output)
    return output.getvalue()


class PdfIngressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.library_root = self.root / "data" / "Library"
        self.spaces_root = self.root / "data" / "Spaces"
        self.publications_root = self.root / "data" / "My Publications"
        self.associated_root = self.root / "data" / "Associated Files"
        self.patches = [
            patch.object(ui_server, "LIBRARY_LOCAL_COPY_ROOT", self.library_root),
            patch.object(ui_server, "SPACES_LOCAL_COPY_ROOT", self.spaces_root),
            patch.object(ui_server, "MY_PUBLICATIONS_LOCAL_COPY_ROOT", self.publications_root),
            patch.object(ui_server, "ASSOCIATED_FILES_ROOT", self.associated_root),
        ]
        for active_patch in self.patches:
            active_patch.start()
        self.storage = Storage(self.root / "data" / "paper_monitor.sqlite")

    def tearDown(self) -> None:
        self.storage.close()
        for active_patch in reversed(self.patches):
            active_patch.stop()
        self.tmp.cleanup()

    def add_paper(self, paper_id: str) -> None:
        self.storage.upsert_paper(
            {
                "paper_id": paper_id,
                "title": f"Paper {paper_id}",
                "journal": "Fixture Journal",
                "source": "fixture",
                "raw": {},
            }
        )

    def assert_no_managed_files(self) -> None:
        for root in (
            self.library_root,
            self.spaces_root,
            self.publications_root,
            self.associated_root,
        ):
            if root.exists():
                self.assertFalse(
                    any(path.is_file() for path in root.rglob("*")),
                    f"unexpected managed file under {root}",
                )

    def test_central_pdf_validator_rejects_incomplete_or_non_pdf_payloads(self) -> None:
        invalid_payloads = {
            "truncated": b"%PDF-1.7\ntruncated",
            "header-only": b"%PDF-1.7\n",
            "forged-eof": b"%PDF-1.7\n1 0 obj <<>> endobj\n%%EOF\n",
            "html": b"<!doctype html><title>Access blocked</title>",
            "empty": b"",
        }
        for name, payload in invalid_payloads.items():
            with self.subTest(name=name, api="bytes"):
                self.assertFalse(pdf_utils.is_valid_pdf_bytes(payload))
            path = self.root / f"{name}.pdf"
            path.write_bytes(payload)
            with self.subTest(name=name, api="file"):
                self.assertFalse(pdf_utils.is_valid_pdf_file(path))

    def test_central_pdf_validator_accepts_pypdf_one_page_document(self) -> None:
        content = make_clean_pdf()
        self.assertTrue(pdf_utils.is_valid_pdf_bytes(content))

        path = self.root / "valid.pdf"
        path.write_bytes(content)
        self.assertTrue(pdf_utils.is_valid_pdf_file(path))

    def test_central_pdf_validator_rejects_zero_page_and_password_locked_documents(self) -> None:
        empty_output = BytesIO()
        empty_writer = PdfWriter()
        empty_writer.write(empty_output)
        self.assertFalse(pdf_utils.is_valid_pdf_bytes(empty_output.getvalue()))

        locked_output = BytesIO()
        locked_writer = PdfWriter()
        locked_writer.add_blank_page(width=612, height=792)
        locked_writer.encrypt("secret")
        locked_writer.write(locked_output)
        self.assertFalse(pdf_utils.is_valid_pdf_bytes(locked_output.getvalue()))

    def test_central_pdf_validator_accepts_empty_password_encrypted_document(self) -> None:
        output = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.encrypt("")
        writer.write(output)
        self.assertTrue(pdf_utils.is_valid_pdf_bytes(output.getvalue()))

    def test_pdf_downloader_rejects_truncated_payload_and_accepts_real_pdf(self) -> None:
        messages: list[str] = []

        def response_for(payload: bytes) -> SimpleNamespace:
            return SimpleNamespace(
                status_code=200, close=lambda: None,
                headers={"content-type": "application/pdf"},
                url="https://www.w3.org/paper.pdf",
                iter_content=lambda chunk_size: [payload],
            )

        invalid_target = self.root / "downloaded-truncated.pdf"
        with patch.object(
            download,
            "request_with_retries",
            return_value=response_for(b"%PDF-1.7\ntruncated"),
        ):
            self.assertFalse(
                download.try_download_pdf(
                    "https://www.w3.org/paper.pdf",
                    invalid_target,
                    messages,
                )
            )
        self.assertFalse(invalid_target.exists())
        self.assertTrue(any("invalid or incomplete" in message for message in messages))

        valid_target = self.root / "downloaded-valid.pdf"
        with patch.object(
            download,
            "request_with_retries",
            return_value=response_for(make_clean_pdf()),
        ):
            self.assertTrue(
                download.try_download_pdf(
                    "https://www.w3.org/paper.pdf",
                    valid_target,
                    messages,
                )
            )
        self.assertTrue(pdf_utils.is_valid_pdf_file(valid_target))

    def test_pdf_downloader_removes_partial_file_when_stream_breaks(self) -> None:
        messages: list[str] = []

        def interrupted_stream(chunk_size: int):
            del chunk_size
            yield b"%PDF-1.7\npartial"
            raise OSError("connection interrupted")

        response = SimpleNamespace(
            status_code=200, close=lambda: None,
                headers={"content-type": "application/pdf"},
            url="https://www.w3.org/interrupted.pdf",
            iter_content=interrupted_stream,
        )
        target = self.root / "interrupted.pdf"
        with patch.object(download, "request_with_retries", return_value=response):
            self.assertFalse(
                download.try_download_pdf(
                    "https://www.w3.org/interrupted.pdf",
                    target,
                    messages,
                )
            )

        self.assertFalse(target.exists())
        self.assertEqual(list(self.root.glob(".*.part")), [])
        self.assertTrue(any("connection interrupted" in message for message in messages))

    def test_pdf_downloader_preserves_existing_target_when_request_fails_before_write(self) -> None:
        messages: list[str] = []
        target = self.root / "existing.pdf"
        original = make_clean_pdf()
        target.write_bytes(original)

        with patch.object(
            download,
            "request_with_retries",
            side_effect=OSError("network unavailable"),
        ):
            self.assertFalse(
                download.try_download_pdf(
                    "https://www.w3.org/existing.pdf",
                    target,
                    messages,
                )
            )

        self.assertTrue(target.exists())
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(list(self.root.glob(".*.part")), [])
        self.assertTrue(any("network unavailable" in message for message in messages))

    def assert_clean_and_annotated_are_fingerprinted_immediately(
        self,
        *,
        paper_id: str,
        first_content: bytes,
        first_name: str,
        second_content: bytes,
        second_name: str,
    ) -> None:
        self.add_paper(paper_id)
        first = ui_server.attach_file_to_paper(
            self.storage,
            paper_id=paper_id,
            filename=first_name,
            content=first_content,
            file_role="supplement",
        )
        second = ui_server.attach_file_to_paper(
            self.storage,
            paper_id=paper_id,
            filename=second_name,
            content=second_content,
            file_role="supplement",
        )

        resources = self.storage.list_paper_resources(paper_id, ensure_primary=False)
        self.assertEqual(len(resources), 2)
        by_id = {int(resource["id"]): resource for resource in resources}
        first = by_id[int(first["id"])]
        second = by_id[int(second["id"])]

        self.assertEqual(first["sha256"], hashlib.sha256(first_content).hexdigest())
        self.assertEqual(second["sha256"], hashlib.sha256(second_content).hexdigest())
        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertRegex(str(first["content_sha256"] or ""), r"^[0-9a-f]{64}$")
        self.assertEqual(first["content_sha256"], second["content_sha256"])
        self.assertEqual(
            sorted(int(resource["annotation_count"] or 0) for resource in resources)[0],
            0,
        )
        self.assertGreater(
            sorted(int(resource["annotation_count"] or 0) for resource in resources)[1],
            0,
        )
        self.assertEqual(
            sum(bool(int(resource["is_annotated"] or 0)) for resource in resources),
            1,
        )

    def test_attach_file_fingerprints_clean_then_annotated_pdf_immediately(self) -> None:
        clean = make_clean_pdf()
        annotated = make_annotated_copy(clean)
        self.assert_clean_and_annotated_are_fingerprinted_immediately(
            paper_id="clean-then-annotated",
            first_content=clean,
            first_name="clean.pdf",
            second_content=annotated,
            second_name="annotated.pdf",
        )

    def test_attach_file_fingerprints_annotated_then_clean_pdf_immediately(self) -> None:
        clean = make_clean_pdf()
        annotated = make_annotated_copy(clean)
        self.assert_clean_and_annotated_are_fingerprinted_immediately(
            paper_id="annotated-then-clean",
            first_content=annotated,
            first_name="annotated.pdf",
            second_content=clean,
            second_name="clean.pdf",
        )

    def test_invalid_generic_pdf_attach_leaves_no_database_or_filesystem_state(self) -> None:
        invalid_payloads = {
            "truncated": b"%PDF-1.7\ntruncated",
            "header-only": b"%PDF-1.7\n",
            "forged-eof": b"%PDF-1.7\n1 0 obj <<>> endobj\n%%EOF\n",
            "html": b"<!doctype html><title>Access blocked</title>",
            "empty": b"",
        }
        for index, (name, payload) in enumerate(invalid_payloads.items()):
            paper_id = f"invalid-generic-{index}"
            self.add_paper(paper_id)
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    ui_server.attach_file_to_paper(
                        self.storage,
                        paper_id=paper_id,
                        filename=f"{name}.pdf",
                        content=payload,
                        file_role="other",
                    )
                self.assertEqual(
                    self.storage.list_paper_resources(paper_id, ensure_primary=False),
                    [],
                )
                paper = self.storage.get_paper(paper_id)
                self.assertIsNone(paper["primary_resource_id"])
                self.assertFalse(paper["main_pdf_path"])
                self.assertFalse(paper["merged_pdf_path"])
                self.assert_no_managed_files()


if __name__ == "__main__":
    unittest.main()
