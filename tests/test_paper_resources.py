from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link, Text

from paper_monitor import ui_server
from paper_monitor.storage import STORAGE_SCHEMA_VERSION, Storage


class PaperResourceStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "data" / "paper_monitor.sqlite"
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
        self.storage = Storage(self.db_path)

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

    def write_pdf(self, name: str) -> Path:
        path = self.root / "data" / "Library" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
        return path

    def valid_pdf_bytes(self, marker: str) -> bytes:
        output = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.add_metadata({"/Subject": marker})
        writer.write(output)
        return output.getvalue()

    def conversion_db_state(self) -> dict[str, list[dict[str, object]]]:
        return {
            "papers": [
                dict(row)
                for row in self.storage.conn.execute(
                    "SELECT * FROM papers ORDER BY paper_id"
                ).fetchall()
            ],
            "library_items": [
                dict(row)
                for row in self.storage.conn.execute(
                    "SELECT * FROM library_items ORDER BY id"
                ).fetchall()
            ],
            "resources": [
                dict(row)
                for row in self.storage.conn.execute(
                    "SELECT * FROM resources ORDER BY id"
                ).fetchall()
            ],
        }

    def test_new_paper_gets_stable_storage_key(self) -> None:
        self.add_paper("arxiv_2506.19903")
        paper = self.storage.get_paper("arxiv_2506.19903")
        self.assertRegex(str(paper["storage_key"]), r"^gw_[0-9a-f]{10}$")
        self.assertEqual(
            paper["storage_key"],
            self.storage.storage_key_for_paper_id("arxiv_2506.19903"),
        )

    def test_manual_preprint_identifier_override_can_replace_and_clear_source_value(self) -> None:
        self.add_paper("published-with-wrong-preprint")
        self.storage.update_paper_raw_json(
            "published-with-wrong-preprint",
            {"preprint": {"arxiv_id": "cond-mat/0604211"}},
        )
        paper = self.storage.get_paper("published-with-wrong-preprint")
        self.assertEqual(ui_server.preprint_identifier(paper), "cond-mat/0604211")

        updated = ui_server.update_manual_preprint_identifier(
            self.storage,
            "published-with-wrong-preprint",
            "https://arxiv.org/abs/2501.12345v2",
        )
        raw = json.loads(updated["raw_json"])
        self.assertEqual(ui_server.preprint_identifier(updated), "2501.12345")
        self.assertEqual(ui_server.arxiv_identifier_for_paper(updated), "2501.12345")
        self.assertEqual(raw["preprint"]["arxiv_id"], "cond-mat/0604211")
        self.assertTrue(raw["manual_preprint_identifier_override"])
        self.assertEqual(raw["manual_preprint_identifier"], "2501.12345")

        refreshed_payload = ui_server.merge_refreshed_metadata(
            updated,
            {
                "paper_id": updated["paper_id"],
                "title": updated["title"],
                "journal": updated["journal"],
                "raw": {"arxiv_id": "2601.99999"},
            },
        )
        refreshed = self.storage.refresh_paper_metadata(updated["paper_id"], refreshed_payload)
        self.assertEqual(ui_server.preprint_identifier(refreshed), "2501.12345")

        cleared = ui_server.update_manual_preprint_identifier(
            self.storage,
            "published-with-wrong-preprint",
            "",
        )
        self.assertEqual(ui_server.preprint_identifier(cleared), "")
        self.assertEqual(ui_server.arxiv_identifier_for_paper(cleared), "")

    def test_manual_preprint_identifier_rejects_invalid_value(self) -> None:
        self.add_paper("invalid-manual-preprint")
        with self.assertRaisesRegex(ValueError, "valid arXiv identifier"):
            ui_server.update_manual_preprint_identifier(
                self.storage,
                "invalid-manual-preprint",
                "not-an-arxiv-id",
            )

    def test_latest_arxiv_download_becomes_primary_when_no_better_pdf_exists(self) -> None:
        self.add_paper("latest-arxiv-version")
        self.storage.add_library_item(paper_id="latest-arxiv-version", folder_id=1)
        self.storage.update_paper_raw_json(
            "latest-arxiv-version",
            {"preprint": {"arxiv_id": "2501.12345"}},
        )
        record = {
            "raw": {
                "arxiv_id": "2501.12345",
                "versioned_arxiv_id": "2501.12345v3",
                "published": "2025-01-20T00:00:00Z",
                "updated": "2025-03-20T00:00:00Z",
            }
        }
        requested_urls: list[str] = []

        def fake_download(url: str, path: Path, _messages: list[str], **_options: object) -> bool:
            requested_urls.append(url)
            path.write_bytes(b"%PDF-1.4\n" + b"latest" * 300 + b"\n%%EOF\n")
            return True

        with (
            patch.object(ui_server, "fetch_arxiv_by_id", return_value=record),
            patch.object(ui_server, "wait_for_arxiv_rate_limit"),
            patch.object(ui_server, "try_download_pdf", side_effect=fake_download),
        ):
            result = ui_server.download_arxiv_preprint_versions(
                self.storage,
                "latest-arxiv-version",
            )

        self.assertEqual(result["downloaded_versions"], [3])
        self.assertEqual(requested_urls, ["https://arxiv.org/pdf/2501.12345v3"])
        resources = self.storage.list_paper_resources("latest-arxiv-version")
        self.assertEqual(len(resources), 1)
        self.assertTrue(resources[0]["is_primary"])
        self.assertEqual(resources[0]["version_role"], "preprint")
        self.assertEqual(resources[0]["version_number"], 3)
        self.assertEqual(resources[0]["version_label"], "Preprint v3")
        self.assertEqual(Path(resources[0]["stored_path"]).parent.resolve(), self.library_root.resolve())
        self.assertEqual(Path(resources[0]["stored_path"]).name, "2501.12345v3 [Preprint v3].pdf")

    def test_arxiv_download_reuses_identical_unversioned_preprint_by_sha256(self) -> None:
        self.add_paper("existing-unversioned-preprint")
        self.storage.add_library_item(paper_id="existing-unversioned-preprint", folder_id=1)
        self.storage.update_paper_raw_json(
            "existing-unversioned-preprint",
            {"preprint": {"arxiv_id": "2208.03628"}},
        )
        existing_path = self.write_pdf("2208.03628.pdf")
        self.storage.update_download_status(
            "existing-unversioned-preprint",
            status="success",
            main_pdf_path=str(existing_path),
            merged_pdf_path=str(existing_path),
        )
        existing = self.storage.ensure_primary_pdf_resource("existing-unversioned-preprint")
        self.storage.conn.execute(
            """
            UPDATE resources
            SET file_role = 'publication_version', version_role = 'preprint',
                version_label = 'Preprint', version_number = NULL, source_url = NULL,
                sha256 = NULL, content_sha256 = NULL
            WHERE id = ?
            """,
            (int(existing["id"]),),
        )
        self.storage.conn.commit()
        record = {
            "raw": {
                "arxiv_id": "2208.03628",
                "versioned_arxiv_id": "2208.03628v1",
                "published": "2022-08-07T03:43:33Z",
                "updated": "2022-08-07T03:43:33Z",
            }
        }

        def fake_download(_url: str, path: Path, _messages: list[str], **_options: object) -> bool:
            path.write_bytes(existing_path.read_bytes())
            return True

        with (
            patch.object(ui_server, "fetch_arxiv_by_id", return_value=record),
            patch.object(ui_server, "wait_for_arxiv_rate_limit"),
            patch.object(ui_server, "try_download_pdf", side_effect=fake_download),
        ):
            result = ui_server.download_arxiv_preprint_versions(
                self.storage,
                "existing-unversioned-preprint",
            )

        resources = self.storage.list_paper_resources("existing-unversioned-preprint")
        self.assertEqual(result["downloaded_versions"], [])
        self.assertEqual(result["existing_versions"], [1])
        self.assertEqual(len(resources), 1)
        self.assertEqual(int(resources[0]["id"]), int(existing["id"]))
        self.assertEqual(resources[0]["stored_path"], str(existing_path))
        self.assertEqual(resources[0]["version_number"], 1)
        self.assertEqual(resources[0]["version_label"], "Preprint v1")
        self.assertEqual(resources[0]["source_url"], "https://arxiv.org/pdf/2208.03628v1")
        self.assertTrue(resources[0]["sha256"])

    def test_arxiv_download_keeps_annotated_copy_and_links_it_by_content_fingerprint(self) -> None:
        self.add_paper("annotated-preprint-copy")
        self.storage.add_library_item(paper_id="annotated-preprint-copy", folder_id=1)
        self.storage.update_paper_raw_json(
            "annotated-preprint-copy",
            {"preprint": {"arxiv_id": "2401.01234"}},
        )
        clean = self.root / "clean-arxiv.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with clean.open("wb") as handle:
            writer.write(handle)
        annotated = self.library_root / "2401.01234.pdf"
        annotated.parent.mkdir(parents=True, exist_ok=True)
        annotated_writer = PdfWriter()
        annotated_writer.append_pages_from_reader(PdfReader(str(clean)))
        annotated_writer.add_annotation(
            page_number=0,
            annotation=Text(rect=(72, 700, 96, 724), text="keep this annotation"),
        )
        with annotated.open("wb") as handle:
            annotated_writer.write(handle)
        self.storage.update_download_status(
            "annotated-preprint-copy",
            status="success",
            main_pdf_path=str(annotated),
            merged_pdf_path=str(annotated),
        )
        existing = self.storage.ensure_primary_pdf_resource("annotated-preprint-copy")
        self.storage.conn.execute(
            """
            UPDATE resources
            SET file_role = 'publication_version', version_role = 'preprint',
                version_label = 'Preprint', version_number = NULL, source_url = NULL
            WHERE id = ?
            """,
            (int(existing["id"]),),
        )
        self.storage.conn.commit()
        record = {
            "raw": {
                "arxiv_id": "2401.01234",
                "versioned_arxiv_id": "2401.01234v1",
                "published": "2024-01-03T00:00:00Z",
                "updated": "2024-01-03T00:00:00Z",
            }
        }

        def fake_download(_url: str, path: Path, _messages: list[str], **_options: object) -> bool:
            path.write_bytes(clean.read_bytes())
            return True

        with (
            patch.object(ui_server, "fetch_arxiv_by_id", return_value=record),
            patch.object(ui_server, "wait_for_arxiv_rate_limit"),
            patch.object(ui_server, "try_download_pdf", side_effect=fake_download),
        ):
            ui_server.download_arxiv_preprint_versions(self.storage, "annotated-preprint-copy")

        resources = self.storage.list_paper_resources("annotated-preprint-copy")
        self.assertEqual(len(resources), 2)
        annotated_resource = next(resource for resource in resources if int(resource.get("is_annotated") or 0))
        clean_resource = next(resource for resource in resources if not int(resource.get("is_annotated") or 0))
        self.assertNotEqual(annotated_resource["sha256"], clean_resource["sha256"])
        self.assertEqual(annotated_resource["content_sha256"], clean_resource["content_sha256"])
        self.assertGreater(int(annotated_resource["annotation_count"] or 0), 0)
        self.assertEqual(clean_resource["version_label"], "Preprint v1")

    def test_arxiv_history_sync_keeps_version_of_record_primary_and_skips_existing_versions(self) -> None:
        self.add_paper("published-with-arxiv-history")
        self.storage.add_library_item(paper_id="published-with-arxiv-history", folder_id=1)
        self.storage.update_paper_raw_json(
            "published-with-arxiv-history",
            {
                "manual_preprint_identifier_override": True,
                "manual_preprint_identifier": "cond-mat/0604211",
                "preprint": {"arxiv_id": "wrong/0000000"},
            },
        )
        published = self.write_pdf("Published.pdf")
        self.storage.update_download_status(
            "published-with-arxiv-history",
            status="success",
            main_pdf_path=str(published),
            merged_pdf_path=str(published),
        )
        primary = self.storage.ensure_primary_pdf_resource("published-with-arxiv-history")
        self.storage.conn.execute(
            "UPDATE resources SET file_role = 'publication_version', version_role = 'version_of_record' WHERE id = ?",
            (int(primary["id"]),),
        )
        self.storage.conn.commit()
        record = {
            "raw": {
                "arxiv_id": "cond-mat/0604211",
                "versioned_arxiv_id": "cond-mat/0604211v3",
                "published": "2006-04-21T00:00:00Z",
                "updated": "2006-07-21T00:00:00Z",
            }
        }
        requested_urls: list[str] = []

        def fake_download(url: str, path: Path, _messages: list[str], **_options: object) -> bool:
            requested_urls.append(url)
            version = url.rsplit("v", 1)[-1].encode("ascii")
            path.write_bytes(b"%PDF-1.4\n" + version * 2048 + b"\n%%EOF\n")
            return True

        with (
            patch.object(ui_server, "fetch_arxiv_by_id", return_value=record) as fetch,
            patch.object(ui_server, "wait_for_arxiv_rate_limit"),
            patch.object(ui_server, "try_download_pdf", side_effect=fake_download),
        ):
            first = ui_server.download_arxiv_preprint_versions(
                self.storage,
                "published-with-arxiv-history",
                include_history=True,
            )
            second = ui_server.download_arxiv_preprint_versions(
                self.storage,
                "published-with-arxiv-history",
                include_history=True,
            )

        self.assertEqual(fetch.call_args.args[0], "cond-mat/0604211")
        self.assertEqual(first["downloaded_versions"], [1, 2, 3])
        self.assertEqual(second["downloaded_versions"], [])
        self.assertEqual(second["existing_versions"], [1, 2, 3])
        self.assertEqual(
            requested_urls,
            [
                "https://arxiv.org/pdf/cond-mat/0604211v1",
                "https://arxiv.org/pdf/cond-mat/0604211v2",
                "https://arxiv.org/pdf/cond-mat/0604211v3",
            ],
        )
        paper = self.storage.get_paper("published-with-arxiv-history")
        self.assertEqual(int(paper["primary_resource_id"]), int(primary["id"]))
        resources = self.storage.list_paper_resources("published-with-arxiv-history")
        preprints = [resource for resource in resources if resource["version_role"] == "preprint"]
        self.assertEqual([resource["version_number"] for resource in preprints], [1, 2, 3])
        self.assertTrue(all("Associated Files/Library" in resource["stored_path"] for resource in preprints))
        self.assertEqual(
            [resource["version_label"] for resource in preprints],
            ["Preprint v1", "Preprint v2", "Preprint v3"],
        )

    def test_arxiv_download_requires_a_library_or_my_publications_work(self) -> None:
        self.add_paper("discovery-only-arxiv")
        self.storage.update_paper_raw_json(
            "discovery-only-arxiv",
            {"preprint": {"arxiv_id": "2501.12345"}},
        )
        with self.assertRaisesRegex(ValueError, "Add this paper to Library"):
            ui_server.download_arxiv_preprint_versions(self.storage, "discovery-only-arxiv")

    def test_corrected_arxiv_identifier_does_not_reuse_or_prefer_old_synced_versions(self) -> None:
        self.add_paper("corrected-arxiv-download")
        self.storage.add_library_item(paper_id="corrected-arxiv-download", folder_id=1)

        def fake_download(url: str, path: Path, _messages: list[str], **_options: object) -> bool:
            payload = url.encode("utf-8")
            path.write_bytes(b"%PDF-1.4\n" + payload * 80 + b"\n%%EOF\n")
            return True

        with (
            patch.object(ui_server, "wait_for_arxiv_rate_limit"),
            patch.object(ui_server, "try_download_pdf", side_effect=fake_download),
        ):
            ui_server.update_manual_preprint_identifier(
                self.storage,
                "corrected-arxiv-download",
                "2501.12345",
            )
            with patch.object(
                ui_server,
                "fetch_arxiv_by_id",
                return_value={"raw": {"arxiv_id": "2501.12345", "versioned_arxiv_id": "2501.12345v1"}},
            ):
                ui_server.download_arxiv_preprint_versions(self.storage, "corrected-arxiv-download")

            ui_server.update_manual_preprint_identifier(
                self.storage,
                "corrected-arxiv-download",
                "2502.54321",
            )
            with patch.object(
                ui_server,
                "fetch_arxiv_by_id",
                return_value={"raw": {"arxiv_id": "2502.54321", "versioned_arxiv_id": "2502.54321v1"}},
            ):
                result = ui_server.download_arxiv_preprint_versions(self.storage, "corrected-arxiv-download")

        self.assertEqual(result["downloaded_versions"], [1])
        resources = self.storage.list_paper_resources("corrected-arxiv-download")
        current = next(resource for resource in resources if resource["is_primary"])
        previous = next(resource for resource in resources if not resource["is_primary"])
        self.assertIn("2502.54321v1", current["source_url"])
        self.assertEqual(current["version_role"], "preprint")
        self.assertIn("2501.12345v1", previous["source_url"])
        self.assertEqual(previous["version_role"], "other")
        self.assertEqual(previous["version_label"], "Previous arXiv PDF")

    def test_schema_upgrade_registers_existing_pdf_without_moving_it(self) -> None:
        self.add_paper("legacy-paper")
        pdf = self.write_pdf("Legacy.pdf")
        original_bytes = pdf.read_bytes()
        self.storage.conn.execute(
            """
            UPDATE papers
            SET main_pdf_path = ?, merged_pdf_path = ?, primary_resource_id = NULL
            WHERE paper_id = 'legacy-paper'
            """,
            (str(pdf), str(pdf)),
        )
        self.storage.conn.execute("DELETE FROM resources WHERE paper_id = 'legacy-paper'")
        self.storage.conn.execute("PRAGMA user_version = 5")
        self.storage.conn.commit()
        self.storage.close()

        self.storage = Storage(self.db_path)
        self.assertEqual(
            int(self.storage.conn.execute("PRAGMA user_version").fetchone()[0]),
            STORAGE_SCHEMA_VERSION,
        )
        resources = self.storage.list_paper_resources("legacy-paper")
        self.assertEqual(len(resources), 1)
        self.assertTrue(resources[0]["is_primary"])
        self.assertEqual(resources[0]["local_path"], str(pdf))
        self.assertEqual(resources[0]["added_via"], "legacy_backfill")
        self.assertEqual(resources[0]["version_role"], "other")
        self.assertEqual(resources[0]["version_label"], "Imported PDF")
        self.assertTrue(pdf.exists())
        self.assertEqual(pdf.read_bytes(), original_bytes)

    def test_schema_upgrade_recognizes_exact_arxiv_filename_as_preprint(self) -> None:
        self.add_paper("arxiv_1704.06287")
        self.storage.update_paper_raw_json(
            "arxiv_1704.06287",
            {"arxiv_id": "1704.06287"},
        )
        pdf = self.write_pdf("3.Superconductivity/1704.06287.pdf")
        original_bytes = pdf.read_bytes()
        self.storage.conn.execute(
            """
            UPDATE papers
            SET doi = ?, main_pdf_path = ?, merged_pdf_path = ?, primary_resource_id = NULL
            WHERE paper_id = 'arxiv_1704.06287'
            """,
            ("10.1007/example", str(pdf), str(pdf)),
        )
        self.storage.conn.execute("DELETE FROM resources WHERE paper_id = 'arxiv_1704.06287'")
        self.storage.conn.execute("PRAGMA user_version = 7")
        self.storage.conn.commit()
        self.storage.close()

        self.storage = Storage(self.db_path)
        resources = self.storage.list_paper_resources("arxiv_1704.06287")
        self.assertEqual(len(resources), 1)
        self.assertTrue(resources[0]["is_primary"])
        self.assertEqual(resources[0]["version_role"], "preprint")
        self.assertEqual(resources[0]["version_label"], "Preprint")
        self.assertEqual(resources[0]["source_url"], "https://arxiv.org/pdf/1704.06287")
        self.assertEqual(resources[0]["local_path"], str(pdf))
        self.assertEqual(pdf.read_bytes(), original_bytes)

    def test_manual_preference_overrides_automatic_version_rank(self) -> None:
        self.add_paper("versioned-paper")
        preprint = self.write_pdf("Preprint.pdf")
        published = self.write_pdf("Published.pdf")
        preprint_resource = self.storage.create_paper_resource(
            paper_id="versioned-paper",
            stored_path=str(preprint),
            file_role="publication_version",
            version_role="preprint",
            version_number=2,
        )
        published_resource = self.storage.create_paper_resource(
            paper_id="versioned-paper",
            stored_path=str(published),
            file_role="publication_version",
            version_role="version_of_record",
        )

        resolved = self.storage.resolve_primary_paper_resource("versioned-paper")
        self.assertEqual(int(resolved["id"]), int(published_resource["id"]))

        self.storage.set_preferred_paper_resource(
            "versioned-paper", int(preprint_resource["id"])
        )
        resolved = self.storage.resolve_primary_paper_resource("versioned-paper")
        self.assertEqual(int(resolved["id"]), int(preprint_resource["id"]))

        self.storage.set_preferred_paper_resource("versioned-paper", None)
        resolved = self.storage.resolve_primary_paper_resource("versioned-paper")
        self.assertEqual(int(resolved["id"]), int(published_resource["id"]))

    def test_paper_version_role_can_be_reclassified_without_moving_file(self) -> None:
        self.add_paper("manual-version-role")
        pdf = self.write_pdf("Topic/Imported.pdf")
        original_bytes = pdf.read_bytes()
        self.storage.update_download_status(
            "manual-version-role",
            status="success",
            main_pdf_path=str(pdf),
            merged_pdf_path=str(pdf),
        )
        resource = self.storage.ensure_primary_pdf_resource("manual-version-role")
        resource_id = int(resource["id"])

        expected_labels = {
            "version_of_record": "Published Version",
            "first_published": "Published Version",
            "accepted_manuscript": "Accepted Manuscript",
            "preprint": "Preprint",
            "other": "Imported PDF",
        }
        for version_role, label in expected_labels.items():
            updated = ui_server.update_paper_resource_role(
                self.storage,
                "manual-version-role",
                resource_id,
                "publication_version",
                version_role,
            )
            self.assertEqual(updated["version_role"], version_role)
            self.assertEqual(updated["version_label"], label)
            self.assertEqual(updated["stored_path"], str(pdf))
            self.assertEqual(updated["display_name"], "Imported.pdf")

        self.assertEqual(pdf.read_bytes(), original_bytes)

    def test_attachment_role_can_be_changed_without_moving_or_renaming_file(self) -> None:
        self.add_paper("editable-attachment-role")
        image = self.root / "data" / "Associated Files" / "figure with original name.jpg"
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(b"image bytes")
        resource = self.storage.create_paper_resource(
            paper_id="editable-attachment-role",
            stored_path=str(image),
            display_name=image.name,
            file_role="other",
            version_label="Other File",
            mime_type="image/jpeg",
            kind="jpg",
        )
        resource_id = int(resource["id"])
        original_bytes = image.read_bytes()

        expected_labels = {
            "figure": "Image",
            "supplement": "Supplement",
            "note": "Note",
            "presentation": "Presentation",
            "data": "Data",
            "code": "Code",
            "other": "Other File",
        }
        for file_role, label in expected_labels.items():
            updated = ui_server.update_paper_resource_role(
                self.storage,
                "editable-attachment-role",
                resource_id,
                file_role,
                "",
            )
            self.assertEqual(updated["file_role"], file_role)
            self.assertIsNone(updated["version_role"])
            self.assertEqual(updated["version_label"], label)
            self.assertEqual(updated["stored_path"], str(image))
            self.assertEqual(updated["display_name"], image.name)

        self.assertEqual(image.read_bytes(), original_bytes)
        with self.assertRaisesRegex(ValueError, "Only PDFs"):
            ui_server.update_paper_resource_role(
                self.storage,
                "editable-attachment-role",
                resource_id,
                "publication_version",
                "version_of_record",
            )

    def test_paper_version_can_be_marked_as_annotated_without_changing_the_file(self) -> None:
        self.add_paper("manual-annotated-version")
        pdf = self.write_pdf("Annotated.pdf")
        original_bytes = pdf.read_bytes()
        self.storage.update_download_status(
            "manual-annotated-version",
            status="success",
            main_pdf_path=str(pdf),
            merged_pdf_path=str(pdf),
        )
        resource = self.storage.ensure_primary_pdf_resource("manual-annotated-version")

        updated = ui_server.update_paper_resource_role(
            self.storage,
            "manual-annotated-version",
            int(resource["id"]),
            "publication_version",
            "version_of_record",
            is_annotated=True,
        )

        self.assertEqual(updated["version_label"], "Published Version")
        self.assertEqual(int(updated["is_annotated"] or 0), 1)
        self.assertEqual(pdf.read_bytes(), original_bytes)

    def test_fingerprint_refresh_clears_legacy_link_annotation_false_positive(self) -> None:
        self.add_paper("publisher-link-false-positive")
        pdf = self.root / "data" / "Library" / "Publisher.pdf"
        pdf.parent.mkdir(parents=True, exist_ok=True)
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.add_annotation(
            page_number=0,
            annotation=Link(rect=(72, 700, 180, 724), url="https://doi.org/10.1000/example"),
        )
        with pdf.open("wb") as handle:
            writer.write(handle)
        self.storage.update_download_status(
            "publisher-link-false-positive",
            status="success",
            main_pdf_path=str(pdf),
            merged_pdf_path=str(pdf),
        )
        resource = self.storage.ensure_primary_pdf_resource("publisher-link-false-positive")
        self.storage.conn.execute(
            "UPDATE resources SET annotation_count = 1, is_annotated = 1 WHERE id = ?",
            (int(resource["id"]),),
        )
        self.storage.conn.commit()

        refreshed = ui_server.refresh_paper_resource_fingerprints(
            self.storage,
            "publisher-link-false-positive",
        )

        self.assertEqual(len(refreshed), 1)
        self.assertEqual(int(refreshed[0]["annotation_count"] or 0), 0)
        self.assertEqual(int(refreshed[0]["is_annotated"] or 0), 0)

    def test_fingerprint_refresh_preserves_explicit_manual_annotated_mark(self) -> None:
        self.add_paper("manual-annotated-refresh")
        pdf = self.root / "data" / "Library" / "Manual.pdf"
        pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(self.valid_pdf_bytes("manual annotation classification"))
        self.storage.update_download_status(
            "manual-annotated-refresh",
            status="success",
            main_pdf_path=str(pdf),
            merged_pdf_path=str(pdf),
        )
        resource = self.storage.ensure_primary_pdf_resource("manual-annotated-refresh")
        ui_server.update_paper_resource_role(
            self.storage,
            "manual-annotated-refresh",
            int(resource["id"]),
            "publication_version",
            "version_of_record",
            is_annotated=True,
        )

        refreshed = ui_server.refresh_paper_resource_fingerprints(
            self.storage,
            "manual-annotated-refresh",
        )

        self.assertEqual(len(refreshed), 1)
        self.assertEqual(int(refreshed[0]["annotation_count"] or 0), 0)
        self.assertEqual(int(refreshed[0]["is_annotated"] or 0), 1)

    def test_current_default_pdf_cannot_be_reclassified_as_an_attachment(self) -> None:
        self.add_paper("primary-role-guard")
        pdf = self.write_pdf("Primary.pdf")
        self.storage.update_download_status(
            "primary-role-guard",
            status="success",
            main_pdf_path=str(pdf),
            merged_pdf_path=str(pdf),
        )
        resource = self.storage.ensure_primary_pdf_resource("primary-role-guard")

        with self.assertRaisesRegex(ValueError, "current default PDF"):
            ui_server.update_paper_resource_role(
                self.storage,
                "primary-role-guard",
                int(resource["id"]),
                "figure",
                "",
            )

    def test_non_pdf_cannot_be_selected_as_preferred_pdf(self) -> None:
        self.add_paper("paper-with-note")
        note = self.root / "data" / "Associated Files" / "note.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text("notes", encoding="utf-8")
        resource = self.storage.create_paper_resource(
            paper_id="paper-with-note",
            stored_path=str(note),
            file_role="note",
        )
        with self.assertRaisesRegex(ValueError, "Preferred file must be a PDF"):
            self.storage.set_preferred_paper_resource(
                "paper-with-note", int(resource["id"])
            )

    def test_attachment_pdfs_cannot_be_preferred_or_promoted_but_paper_version_can(self) -> None:
        self.add_paper("paper-current-role-guard")
        current_path = self.write_pdf("Role Guard/Published.pdf")
        self.storage.update_download_status(
            "paper-current-role-guard",
            status="success",
            main_pdf_path=str(current_path),
            merged_pdf_path=str(current_path),
        )
        current = self.storage.ensure_primary_pdf_resource("paper-current-role-guard")
        self.storage.conn.execute(
            "UPDATE resources SET file_role = 'publication_version', version_role = 'version_of_record' WHERE id = ?",
            (int(current["id"]),),
        )
        supplement_path = self.write_pdf("Role Guard/Supplement.pdf")
        other_path = self.write_pdf("Role Guard/Other.pdf")
        preprint_path = self.write_pdf("Role Guard/Preprint.pdf")
        supplement = self.storage.create_paper_resource(
            paper_id="paper-current-role-guard",
            stored_path=str(supplement_path),
            file_role="supplement",
            version_label="Supplement",
        )
        other = self.storage.create_paper_resource(
            paper_id="paper-current-role-guard",
            stored_path=str(other_path),
            file_role="other",
            version_label="Other File",
        )
        preprint = self.storage.create_paper_resource(
            paper_id="paper-current-role-guard",
            stored_path=str(preprint_path),
            file_role="publication_version",
            version_role="preprint",
            version_label="Preprint",
        )
        before_paper = dict(self.storage.get_paper("paper-current-role-guard"))
        before_resources = [
            dict(resource)
            for resource in self.storage.conn.execute(
                "SELECT * FROM resources WHERE paper_id = ? ORDER BY id",
                ("paper-current-role-guard",),
            ).fetchall()
        ]
        before_bytes = {
            path: path.read_bytes()
            for path in (current_path, supplement_path, other_path, preprint_path)
        }

        for attachment in (supplement, other):
            with self.assertRaisesRegex(ValueError, "paper-version PDFs"):
                self.storage.set_preferred_paper_resource(
                    "paper-current-role-guard", int(attachment["id"])
                )
            with self.assertRaisesRegex(ValueError, "paper-version PDFs"):
                ui_server.promote_paper_resource(
                    self.storage,
                    "paper-current-role-guard",
                    int(attachment["id"]),
                    manual_preferred=True,
                )

        self.assertEqual(
            dict(self.storage.get_paper("paper-current-role-guard")), before_paper
        )
        self.assertEqual(
            [
                dict(resource)
                for resource in self.storage.conn.execute(
                    "SELECT * FROM resources WHERE paper_id = ? ORDER BY id",
                    ("paper-current-role-guard",),
                ).fetchall()
            ],
            before_resources,
        )
        for path, content in before_bytes.items():
            self.assertTrue(path.exists())
            self.assertEqual(path.read_bytes(), content)

        self.storage.set_preferred_paper_resource(
            "paper-current-role-guard", int(preprint["id"])
        )
        self.assertEqual(
            int(
                self.storage.resolve_primary_paper_resource(
                    "paper-current-role-guard"
                )["id"]
            ),
            int(preprint["id"]),
        )
        promoted = ui_server.promote_paper_resource(
            self.storage,
            "paper-current-role-guard",
            int(preprint["id"]),
            manual_preferred=True,
        )
        paper = self.storage.get_paper("paper-current-role-guard")
        self.assertEqual(int(paper["primary_resource_id"]), int(preprint["id"]))
        self.assertEqual(int(paper["preferred_resource_id"]), int(preprint["id"]))
        self.assertEqual(int(promoted["id"]), int(preprint["id"]))

    def test_preferred_paper_file_http_handler_rejects_attachment_and_accepts_version(self) -> None:
        self.add_paper("paper-http-current-role")
        current_path = self.write_pdf("HTTP Role/Published.pdf")
        self.storage.update_download_status(
            "paper-http-current-role",
            status="success",
            main_pdf_path=str(current_path),
            merged_pdf_path=str(current_path),
        )
        current = self.storage.ensure_primary_pdf_resource("paper-http-current-role")
        self.storage.conn.execute(
            "UPDATE resources SET file_role = 'publication_version', version_role = 'version_of_record' WHERE id = ?",
            (int(current["id"]),),
        )
        attachment_path = self.write_pdf("HTTP Role/Supplement.pdf")
        preprint_path = self.write_pdf("HTTP Role/Preprint.pdf")
        attachment = self.storage.create_paper_resource(
            paper_id="paper-http-current-role",
            stored_path=str(attachment_path),
            file_role="supplement",
            version_label="Supplement",
        )
        preprint = self.storage.create_paper_resource(
            paper_id="paper-http-current-role",
            stored_path=str(preprint_path),
            file_role="publication_version",
            version_role="preprint",
            version_label="Preprint",
        )
        before = self.conversion_db_state()
        before_bytes = {
            path: path.read_bytes()
            for path in (current_path, attachment_path, preprint_path)
        }
        handler = object.__new__(ui_server.PaperMonitorUiHandler)
        handler.configured_db_path = self.db_path
        handler.send_json = MagicMock()
        handler.send_error_json = MagicMock()

        handler.handle_set_preferred_paper_file(
            {
                "paper_id": "paper-http-current-role",
                "resource_id": int(attachment["id"]),
            }
        )

        handler.send_error_json.assert_called_once()
        self.assertEqual(handler.send_error_json.call_args.args[0], HTTPStatus.BAD_REQUEST)
        handler.send_json.assert_not_called()
        self.assertEqual(self.conversion_db_state(), before)
        for path, content in before_bytes.items():
            self.assertTrue(path.exists())
            self.assertEqual(path.read_bytes(), content)

        handler.send_error_json.reset_mock()
        handler.send_json.reset_mock()
        handler.handle_set_preferred_paper_file(
            {
                "paper_id": "paper-http-current-role",
                "resource_id": int(preprint["id"]),
            }
        )

        handler.send_error_json.assert_not_called()
        handler.send_json.assert_called_once()
        response = handler.send_json.call_args.args[0]
        self.assertEqual(response["preferred_resource_id"], int(preprint["id"]))
        self.assertEqual(response["resolved_resource_id"], int(preprint["id"]))
        paper = self.storage.get_paper("paper-http-current-role")
        self.assertEqual(int(paper["primary_resource_id"]), int(preprint["id"]))
        self.assertEqual(int(paper["preferred_resource_id"]), int(preprint["id"]))

    def test_explicit_attachment_is_copied_to_mirrored_associated_files(self) -> None:
        self.add_paper("paper-with-files")
        primary = self.write_pdf("Topic/Primary.pdf")
        self.storage.update_download_status(
            "paper-with-files",
            status="success",
            main_pdf_path=str(primary),
            merged_pdf_path=str(primary),
        )
        self.storage.ensure_primary_pdf_resource("paper-with-files")

        resource = ui_server.attach_file_to_paper(
            self.storage,
            paper_id="paper-with-files",
            filename="Reading Notes.md",
            content=b"# Notes\n",
            file_role="note",
        )

        expected_parent = (
            self.associated_root
            / "Library"
            / "Topic"
            / f"Primary [{self.storage.storage_key_for_paper_id('paper-with-files')}]"
            / "Files"
        )
        stored = Path(str(resource["stored_path"]))
        self.assertEqual(stored.parent, expected_parent)
        self.assertEqual(stored.read_bytes(), b"# Notes\n")
        self.assertEqual(resource["file_role"], "note")
        self.assertTrue(primary.exists())

    def test_explicit_attachment_deduplicates_same_content(self) -> None:
        self.add_paper("paper-deduplicate")
        first = ui_server.attach_file_to_paper(
            self.storage,
            paper_id="paper-deduplicate",
            filename="Notes.md",
            content=b"same content",
            file_role="note",
        )
        second = ui_server.attach_file_to_paper(
            self.storage,
            paper_id="paper-deduplicate",
            filename="Renamed Notes.md",
            content=b"same content",
            file_role="note",
        )
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(int(first["id"]), int(second["id"]))
        self.assertEqual(len(self.storage.list_paper_resources("paper-deduplicate")), 1)

    def test_standalone_library_file_can_be_moved_into_another_paper_as_attachment(self) -> None:
        self.add_paper("target-work")
        self.add_paper("standalone-file")
        target_item = self.storage.add_library_item(paper_id="target-work", folder_id=1)
        source_folder = self.storage.create_library_folder(name="Data", parent_id=1)
        source_item = self.storage.add_library_item(
            paper_id="standalone-file",
            folder_id=int(source_folder["id"]),
        )
        source = self.library_root / "Data" / "analysis.pxp"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"processed data")
        source_resource = self.storage.create_paper_resource(
            paper_id="standalone-file",
            stored_path=str(source),
            display_name=source.name,
            file_role="other",
            added_via="loader",
            mime_type="application/octet-stream",
            kind="pxp",
        )

        result = ui_server.convert_library_item_to_paper_attachment(
            self.storage,
            source_item_id=int(source_item["id"]),
            target_paper_id="target-work",
        )

        self.assertEqual(result["attached_count"], 1)
        self.assertFalse(source.exists())
        self.assertIsNone(self.storage.get_library_item(int(source_item["id"])))
        self.assertIsNone(self.storage.get_paper("standalone-file"))
        self.assertIsNotNone(self.storage.get_library_item(int(target_item["id"])))
        attached = self.storage.get_paper_resource(int(source_resource["id"]))
        self.assertEqual(attached["paper_id"], "target-work")
        self.assertEqual(attached["file_role"], "other")
        self.assertEqual(attached["version_label"], "Other File")
        attached_path = Path(attached["stored_path"])
        self.assertTrue(attached_path.exists())
        self.assertEqual(attached_path.read_bytes(), b"processed data")
        self.assertIn("Associated Files/Library", str(attached_path))

    def test_two_resource_conversion_second_move_failure_restores_database_and_files_exactly(self) -> None:
        self.add_paper("conversion-rollback-target")
        self.add_paper("conversion-rollback-source")
        source_folder = self.storage.create_library_folder(
            name="Rollback Source", parent_id=1
        )
        source_item = self.storage.add_library_item(
            paper_id="conversion-rollback-source",
            folder_id=int(source_folder["id"]),
        )
        first_path = self.library_root / "Rollback Source" / "first-result.dat"
        second_path = self.library_root / "Rollback Source" / "second-result.dat"
        first_path.parent.mkdir(parents=True, exist_ok=True)
        first_path.write_bytes(b"first result")
        second_path.write_bytes(b"second result")
        first_resource = self.storage.create_paper_resource(
            paper_id="conversion-rollback-source",
            stored_path=str(first_path),
            display_name=first_path.name,
            file_role="other",
            sha256="",
            content_sha256="",
            added_via="loader",
        )
        second_resource = self.storage.create_paper_resource(
            paper_id="conversion-rollback-source",
            stored_path=str(second_path),
            display_name=second_path.name,
            file_role="other",
            sha256="",
            content_sha256="",
            added_via="loader",
        )
        before = self.conversion_db_state()
        original_files = {
            first_path: first_path.read_bytes(),
            second_path: second_path.read_bytes(),
        }
        real_move = shutil.move
        forward_move_count = 0

        def fail_second_managed_move(source: str, destination: str, *args: object, **kwargs: object) -> str:
            nonlocal forward_move_count
            destination_path = Path(destination).absolute()
            try:
                destination_path.relative_to(self.associated_root.absolute())
            except ValueError:
                return str(real_move(source, destination, *args, **kwargs))
            forward_move_count += 1
            if forward_move_count == 2:
                raise OSError("injected second managed move failure")
            return str(real_move(source, destination, *args, **kwargs))

        with (
            patch.object(ui_server.shutil, "move", side_effect=fail_second_managed_move),
            self.assertRaisesRegex(OSError, "second managed move failure"),
        ):
            ui_server.convert_library_item_to_paper_attachment(
                self.storage,
                source_item_id=int(source_item["id"]),
                target_paper_id="conversion-rollback-target",
            )

        self.assertEqual(forward_move_count, 2)
        self.assertEqual(self.conversion_db_state(), before)
        self.assertIsNotNone(self.storage.get_paper("conversion-rollback-source"))
        self.assertIsNotNone(self.storage.get_library_item(int(source_item["id"])))
        self.assertIsNotNone(self.storage.get_paper_resource(int(first_resource["id"])))
        self.assertIsNotNone(self.storage.get_paper_resource(int(second_resource["id"])))
        for path, content in original_files.items():
            self.assertTrue(path.exists())
            self.assertEqual(path.read_bytes(), content)
        if self.associated_root.exists():
            self.assertFalse(any(path.is_file() for path in self.associated_root.rglob("*")))
        self.assertEqual(self.storage.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_two_resource_conversion_moves_files_and_commits_fingerprints_atomically(self) -> None:
        self.add_paper("conversion-success-target")
        self.add_paper("conversion-success-source")
        source_folder = self.storage.create_library_folder(
            name="Success Source", parent_id=1
        )
        source_item = self.storage.add_library_item(
            paper_id="conversion-success-source",
            folder_id=int(source_folder["id"]),
        )
        first_path = self.library_root / "Success Source" / "first-result.dat"
        second_path = self.library_root / "Success Source" / "second-result.dat"
        first_path.parent.mkdir(parents=True, exist_ok=True)
        first_path.write_bytes(b"first result")
        second_path.write_bytes(b"second result")
        originals = {
            "first-result.dat": first_path.read_bytes(),
            "second-result.dat": second_path.read_bytes(),
        }
        first_resource = self.storage.create_paper_resource(
            paper_id="conversion-success-source",
            stored_path=str(first_path),
            display_name=first_path.name,
            file_role="other",
            sha256="",
            content_sha256="",
            added_via="loader",
        )
        second_resource = self.storage.create_paper_resource(
            paper_id="conversion-success-source",
            stored_path=str(second_path),
            display_name=second_path.name,
            file_role="other",
            sha256="",
            content_sha256="",
            added_via="loader",
        )

        result = ui_server.convert_library_item_to_paper_attachment(
            self.storage,
            source_item_id=int(source_item["id"]),
            target_paper_id="conversion-success-target",
        )

        self.assertEqual(result["attached_count"], 2)
        self.assertFalse(first_path.exists())
        self.assertFalse(second_path.exists())
        self.assertIsNone(self.storage.get_library_item(int(source_item["id"])))
        self.assertIsNone(self.storage.get_paper("conversion-success-source"))
        for resource_id in (int(first_resource["id"]), int(second_resource["id"])):
            attached = self.storage.get_paper_resource(resource_id)
            self.assertEqual(attached["paper_id"], "conversion-success-target")
            self.assertEqual(attached["file_role"], "other")
            self.assertEqual(attached["version_label"], "Other File")
            self.assertTrue(attached["sha256"])
            attached_path = Path(attached["stored_path"])
            self.assertTrue(attached_path.exists())
            self.assertEqual(attached_path.read_bytes(), originals[attached_path.name])
            self.assertIn("Associated Files/Library", str(attached_path))
        self.assertEqual(self.storage.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_shared_library_work_is_not_destructively_converted_to_attachment(self) -> None:
        self.add_paper("target-shared-guard")
        self.add_paper("source-shared-guard")
        first_folder = self.storage.create_library_folder(name="First", parent_id=1)
        second_folder = self.storage.create_library_folder(name="Second", parent_id=1)
        first_item = self.storage.add_library_item(
            paper_id="source-shared-guard",
            folder_id=int(first_folder["id"]),
        )
        self.storage.add_library_item(
            paper_id="source-shared-guard",
            folder_id=int(second_folder["id"]),
        )
        source = self.library_root / "First" / "shared.dat"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"shared")
        self.storage.create_paper_resource(
            paper_id="source-shared-guard",
            stored_path=str(source),
            display_name=source.name,
            file_role="other",
        )

        with self.assertRaisesRegex(ValueError, "other Library locations"):
            ui_server.convert_library_item_to_paper_attachment(
                self.storage,
                source_item_id=int(first_item["id"]),
                target_paper_id="target-shared-guard",
            )

        self.assertTrue(source.exists())
        self.assertIsNotNone(self.storage.get_paper("source-shared-guard"))

    def test_invalid_attached_pdf_creates_no_associated_folder(self) -> None:
        self.add_paper("paper-invalid-associated")
        with self.assertRaisesRegex(ValueError, "not a valid PDF"):
            ui_server.attach_file_to_paper(
                self.storage,
                paper_id="paper-invalid-associated",
                filename="Invalid.pdf",
                content=b"not a PDF",
                file_role="publication_version",
            )
        self.assertFalse(self.associated_root.exists())

    def test_version_of_record_promotes_and_archives_legacy_primary(self) -> None:
        self.add_paper("paper-promote")
        primary = self.write_pdf("Topic/Current.pdf")
        self.storage.update_download_status(
            "paper-promote",
            status="success",
            main_pdf_path=str(primary),
            merged_pdf_path=str(primary),
        )
        self.storage.ensure_primary_pdf_resource("paper-promote")
        old_bytes = primary.read_bytes()
        published_bytes = self.valid_pdf_bytes("published")

        promoted = ui_server.attach_file_to_paper(
            self.storage,
            paper_id="paper-promote",
            filename="Published.pdf",
            content=published_bytes,
            file_role="publication_version",
            version_role="version_of_record",
        )

        paper = self.storage.get_paper("paper-promote")
        promoted_path = Path(paper["merged_pdf_path"])
        self.assertEqual(promoted_path.name, "Published.pdf")
        self.assertEqual(promoted_path.read_bytes(), published_bytes)
        self.assertFalse(primary.exists())
        self.assertEqual(int(paper["primary_resource_id"]), int(promoted["id"]))
        resources = self.storage.list_paper_resources("paper-promote")
        archived = next(resource for resource in resources if int(resource["id"]) != int(promoted["id"]))
        archived_path = Path(archived["stored_path"])
        self.assertIn("Associated Files/Library/Topic", str(archived_path))
        self.assertEqual(archived_path.name, "Current [Imported PDF].pdf")
        self.assertEqual(archived["display_name"], "Current [Imported PDF].pdf")
        self.assertEqual(promoted["display_name"], "Published.pdf")
        self.assertEqual(archived_path.read_bytes(), old_bytes)

    def test_manual_preferred_pdf_swaps_main_file_and_auto_restores_best_version(self) -> None:
        self.add_paper("paper-manual-swap")
        primary = self.write_pdf("Topic/Published.pdf")
        self.storage.update_download_status(
            "paper-manual-swap",
            status="success",
            main_pdf_path=str(primary),
            merged_pdf_path=str(primary),
        )
        published = self.storage.ensure_primary_pdf_resource("paper-manual-swap")
        self.storage.conn.execute(
            "UPDATE resources SET version_role = 'version_of_record' WHERE id = ?",
            (int(published["id"]),),
        )
        self.storage.conn.commit()
        preprint_bytes = self.valid_pdf_bytes("preprint")
        preprint = ui_server.attach_file_to_paper(
            self.storage,
            paper_id="paper-manual-swap",
            filename="Preprint.pdf",
            content=preprint_bytes,
            file_role="publication_version",
            version_role="preprint",
        )

        ui_server.promote_paper_resource(
            self.storage,
            "paper-manual-swap",
            int(preprint["id"]),
            manual_preferred=True,
        )
        paper = self.storage.get_paper("paper-manual-swap")
        self.assertEqual(int(paper["preferred_resource_id"]), int(preprint["id"]))
        preprint_current = Path(paper["merged_pdf_path"])
        self.assertEqual(preprint_current.name, "Preprint.pdf")
        self.assertEqual(preprint_current.read_bytes(), preprint_bytes)
        self.assertFalse(primary.exists())

        self.storage.set_preferred_paper_resource("paper-manual-swap", None)
        resolved = self.storage.resolve_primary_paper_resource("paper-manual-swap")
        ui_server.promote_paper_resource(
            self.storage,
            "paper-manual-swap",
            int(resolved["id"]),
        )
        paper = self.storage.get_paper("paper-manual-swap")
        self.assertEqual(int(paper["primary_resource_id"]), int(published["id"]))
        self.assertFalse(int(paper["preferred_resource_id"] or 0))
        restored_published = Path(paper["merged_pdf_path"])
        self.assertEqual(restored_published.name, "Published.pdf")
        self.assertEqual(restored_published.read_bytes(), b"%PDF-1.4\nfixture\n%%EOF\n")
        refreshed_resources = self.storage.list_paper_resources("paper-manual-swap")
        refreshed_preprint = next(resource for resource in refreshed_resources if int(resource["id"]) == int(preprint["id"]))
        self.assertEqual(Path(refreshed_preprint["stored_path"]).name, "Preprint [Preprint].pdf")
        self.assertEqual(refreshed_preprint["display_name"], "Preprint [Preprint].pdf")

    def test_initial_publisher_download_stays_current_when_preprint_arrives_later(self) -> None:
        self.add_paper("publisher-first-late-preprint")
        publisher = self.write_pdf("Topic/publisher-first.pdf")
        publisher_bytes = self.valid_pdf_bytes("publisher version of record")
        publisher.write_bytes(publisher_bytes)
        publisher_url = "https://publisher.example/articles/10.1234/publisher-first.pdf"
        self.storage.conn.execute(
            "UPDATE papers SET doi = ?, pdf_url = ? WHERE paper_id = ?",
            ("10.1234/publisher-first", publisher_url, "publisher-first-late-preprint"),
        )
        self.storage.conn.commit()
        self.storage.update_download_status(
            "publisher-first-late-preprint",
            status="success",
            main_pdf_path=str(publisher),
            merged_pdf_path=str(publisher),
        )

        version_of_record = ui_server.register_downloaded_paper_resource(
            self.storage,
            "publisher-first-late-preprint",
            result={"status": "success", "main_pdf_url": publisher_url},
            snapshot=None,
        )

        self.assertIsNotNone(version_of_record)
        self.assertEqual(version_of_record["file_role"], "publication_version")
        self.assertEqual(version_of_record["version_role"], "version_of_record")
        self.assertEqual(version_of_record["version_label"], "Published Version")
        self.assertEqual(version_of_record["source_url"], publisher_url)
        late_preprint = ui_server.attach_file_to_paper(
            self.storage,
            paper_id="publisher-first-late-preprint",
            filename="publisher-first-preprint.pdf",
            content=self.valid_pdf_bytes("late preprint"),
            file_role="publication_version",
            version_role="preprint",
            version_label="Preprint",
        )

        paper = self.storage.get_paper("publisher-first-late-preprint")
        self.assertEqual(
            int(paper["primary_resource_id"]), int(version_of_record["id"])
        )
        self.assertFalse(int(paper["preferred_resource_id"] or 0))
        self.assertEqual(Path(paper["merged_pdf_path"]), publisher)
        self.assertEqual(publisher.read_bytes(), publisher_bytes)
        self.assertEqual(late_preprint["version_role"], "preprint")
        self.assertNotEqual(int(late_preprint["id"]), int(version_of_record["id"]))
        self.assertIn("Associated Files/Library/Topic", late_preprint["stored_path"])
        self.assertEqual(
            len(
                self.storage.list_paper_resources(
                    "publisher-first-late-preprint",
                    ensure_primary=False,
                )
            ),
            2,
        )

    def test_initial_publisher_download_stays_current_when_accepted_manuscript_arrives_later(self) -> None:
        self.add_paper("publisher-first-late-accepted")
        publisher = self.write_pdf("Topic/publisher-first-accepted.pdf")
        publisher_bytes = self.valid_pdf_bytes("publisher version of record")
        publisher.write_bytes(publisher_bytes)
        publisher_url = "https://publisher.example/articles/10.1234/publisher-accepted.pdf"
        self.storage.conn.execute(
            "UPDATE papers SET doi = ?, pdf_url = ? WHERE paper_id = ?",
            ("10.1234/publisher-accepted", publisher_url, "publisher-first-late-accepted"),
        )
        self.storage.conn.commit()
        self.storage.update_download_status(
            "publisher-first-late-accepted",
            status="success",
            main_pdf_path=str(publisher),
            merged_pdf_path=str(publisher),
        )

        version_of_record = ui_server.register_downloaded_paper_resource(
            self.storage,
            "publisher-first-late-accepted",
            result={"status": "success", "main_pdf_url": publisher_url},
            snapshot=None,
        )
        late_accepted = ui_server.attach_file_to_paper(
            self.storage,
            paper_id="publisher-first-late-accepted",
            filename="accepted-manuscript.pdf",
            content=self.valid_pdf_bytes("late accepted manuscript"),
            file_role="publication_version",
            version_role="accepted_manuscript",
            version_label="Accepted Manuscript",
        )

        paper = self.storage.get_paper("publisher-first-late-accepted")
        self.assertEqual(
            int(paper["primary_resource_id"]), int(version_of_record["id"])
        )
        self.assertFalse(int(paper["preferred_resource_id"] or 0))
        self.assertEqual(Path(paper["merged_pdf_path"]), publisher)
        self.assertEqual(publisher.read_bytes(), publisher_bytes)
        self.assertEqual(version_of_record["version_role"], "version_of_record")
        self.assertEqual(version_of_record["version_label"], "Published Version")
        self.assertEqual(version_of_record["source_url"], publisher_url)
        self.assertEqual(late_accepted["version_role"], "accepted_manuscript")
        self.assertNotEqual(int(late_accepted["id"]), int(version_of_record["id"]))
        self.assertIn("Associated Files/Library/Topic", late_accepted["stored_path"])
        self.assertEqual(
            len(
                self.storage.list_paper_resources(
                    "publisher-first-late-accepted",
                    ensure_primary=False,
                )
            ),
            2,
        )

    def test_nature_reference_is_accepted_until_version_of_record_arrives(self) -> None:
        self.add_paper("nature-accepted-first")
        accepted_path = self.write_pdf("Topic/nature-reference.pdf")
        accepted_bytes = self.valid_pdf_bytes("accepted manuscript")
        accepted_path.write_bytes(accepted_bytes)
        reference_url = (
            "https://media.springernature.com/full/springer-static/image/"
            "art%3A10.1038%2Fs41586-026-11037-x/MediaObjects/"
            "41586_2026_11037_MOESM1_ESM_reference.pdf"
        )
        self.storage.conn.execute(
            "UPDATE papers SET doi = ?, pdf_url = ? WHERE paper_id = ?",
            ("10.1038/s41586-026-11037-x", reference_url, "nature-accepted-first"),
        )
        self.storage.conn.commit()
        self.storage.update_download_status(
            "nature-accepted-first",
            status="success",
            main_pdf_path=str(accepted_path),
            merged_pdf_path=str(accepted_path),
        )

        accepted = ui_server.register_downloaded_paper_resource(
            self.storage,
            "nature-accepted-first",
            result={"status": "success", "main_pdf_url": reference_url},
            snapshot=None,
        )

        self.assertEqual(accepted["file_role"], "publication_version")
        self.assertEqual(accepted["version_role"], "accepted_manuscript")
        self.assertEqual(accepted["version_label"], "Accepted Manuscript")
        self.assertEqual(accepted["source_url"], reference_url)
        version_of_record = ui_server.attach_file_to_paper(
            self.storage,
            paper_id="nature-accepted-first",
            filename="nature-published.pdf",
            content=self.valid_pdf_bytes("version of record"),
            file_role="publication_version",
            version_role="version_of_record",
            version_label="Published Version",
        )

        paper = self.storage.get_paper("nature-accepted-first")
        self.assertEqual(int(paper["primary_resource_id"]), int(version_of_record["id"]))
        self.assertFalse(int(paper["preferred_resource_id"] or 0))
        self.assertEqual(Path(paper["merged_pdf_path"]).read_bytes(), self.valid_pdf_bytes("version of record"))
        archived_accepted = self.storage.get_paper_resource(int(accepted["id"]))
        self.assertEqual(archived_accepted["version_role"], "accepted_manuscript")
        self.assertEqual(Path(archived_accepted["stored_path"]).read_bytes(), accepted_bytes)
        self.assertEqual(
            len(self.storage.list_paper_resources("nature-accepted-first", ensure_primary=False)),
            2,
        )

    def test_skipped_download_does_not_relabel_existing_preprint_from_new_doi_metadata(self) -> None:
        self.add_paper("skipped-preprint-role")
        preprint_bytes = self.valid_pdf_bytes("preprint bytes")
        preprint = ui_server.attach_file_to_paper(
            self.storage,
            paper_id="skipped-preprint-role",
            filename="2608.12345v1.pdf",
            content=preprint_bytes,
            file_role="publication_version",
            version_role="preprint",
            version_label="Preprint v1",
        )
        before = self.storage.get_paper_resource(int(preprint["id"]))
        self.storage.conn.execute(
            """
            UPDATE papers
            SET doi = ?, pdf_url = ?, download_status = 'success'
            WHERE paper_id = ?
            """,
            (
                "10.1000/newly-discovered-doi",
                "https://publisher.example/articles/newly-discovered-doi.pdf",
                "skipped-preprint-role",
            ),
        )
        self.storage.conn.commit()

        refreshed = ui_server.register_downloaded_paper_resource(
            self.storage,
            "skipped-preprint-role",
            result={"status": "skipped", "message": "already downloaded"},
            snapshot=None,
        )

        paper = self.storage.get_paper("skipped-preprint-role")
        self.assertEqual(int(refreshed["id"]), int(preprint["id"]))
        self.assertEqual(refreshed["file_role"], "publication_version")
        self.assertEqual(refreshed["version_role"], "preprint")
        self.assertEqual(refreshed["version_label"], "Preprint v1")
        self.assertEqual(refreshed["added_via"], before["added_via"])
        self.assertEqual(int(paper["primary_resource_id"]), int(preprint["id"]))
        self.assertEqual(Path(paper["merged_pdf_path"]).read_bytes(), preprint_bytes)

    def test_forced_download_refresh_preserves_changed_previous_pdf(self) -> None:
        self.add_paper("paper-download-history")
        primary = self.write_pdf("Topic/Downloaded.pdf")
        self.storage.conn.execute(
            "UPDATE papers SET doi = ? WHERE paper_id = ?",
            ("10.1234/example", "paper-download-history"),
        )
        self.storage.update_download_status(
            "paper-download-history",
            status="success",
            main_pdf_path=str(primary),
            merged_pdf_path=str(primary),
        )
        snapshot = ui_server.snapshot_primary_resource_before_download(
            self.storage,
            "paper-download-history",
            force=True,
        )
        old_bytes = primary.read_bytes()
        downloaded = self.write_pdf("Topic/downloaded-refresh.pdf")
        downloaded.write_bytes(b"%PDF-1.4\nrefreshed published file\n%%EOF\n")
        self.storage.update_download_status(
            "paper-download-history",
            status="partial",
            main_pdf_path=str(downloaded),
            merged_pdf_path=str(downloaded),
        )

        current = ui_server.register_downloaded_paper_resource(
            self.storage,
            "paper-download-history",
            result={
                "status": "success",
                "main_pdf_url": "https://publisher.example/doi/pdf/10.1234/example",
            },
            snapshot=snapshot,
        )
        ui_server.cleanup_download_resource_snapshot(snapshot)

        self.assertEqual(current["version_role"], "version_of_record")
        paper = self.storage.get_paper("paper-download-history")
        self.assertEqual(int(paper["primary_resource_id"]), int(current["id"]))
        resources = self.storage.list_paper_resources("paper-download-history")
        previous = next(resource for resource in resources if int(resource["id"]) != int(current["id"]))
        previous_path = Path(previous["stored_path"])
        self.assertIn("Associated Files/Library/Topic", str(previous_path))
        self.assertEqual(previous_path.read_bytes(), old_bytes)
        current_path = Path(paper["merged_pdf_path"])
        self.assertEqual(current_path.name, "example [Published Version].pdf")
        self.assertEqual(current_path.read_bytes(), b"%PDF-1.4\nrefreshed published file\n%%EOF\n")
        self.assertFalse(primary.exists())
        self.assertFalse(downloaded.exists())

    def test_browser_downloaded_publisher_pdf_archives_preprint_instead_of_overwriting_it(self) -> None:
        self.add_paper("paper-browser-publisher-upgrade")
        preprint = self.write_pdf("Topic/1602.05061.pdf")
        preprint_bytes = preprint.read_bytes()
        publisher = self.write_pdf("Downloads/PhysRevB.93.235142.pdf")
        publisher.write_bytes(self.valid_pdf_bytes("published version"))
        self.storage.conn.execute(
            "UPDATE papers SET doi = ? WHERE paper_id = ?",
            ("10.1103/physrevb.93.235142", "paper-browser-publisher-upgrade"),
        )
        self.storage.update_paper_raw_json(
            "paper-browser-publisher-upgrade",
            {"arxiv_id": "1602.05061"},
        )
        self.storage.update_download_status(
            "paper-browser-publisher-upgrade",
            status="success",
            main_pdf_path=str(preprint),
            merged_pdf_path=str(preprint),
        )
        preprint_resource = self.storage.ensure_primary_pdf_resource(
            "paper-browser-publisher-upgrade"
        )
        self.storage.conn.execute(
            """
            UPDATE resources
            SET file_role = 'publication_version', version_role = 'preprint',
                version_label = 'Preprint'
            WHERE id = ?
            """,
            (int(preprint_resource["id"]),),
        )
        self.storage.conn.commit()

        self.storage.set_preferred_paper_resource(
            "paper-browser-publisher-upgrade",
            int(preprint_resource["id"]),
        )

        target, paper = ui_server.attach_downloaded_publisher_pdf_to_paper(
            self.storage,
            paper_id="paper-browser-publisher-upgrade",
            context={
                "publisher_download_kind": "publisher-main-pdf",
                "publisher_download_target_url": "https://link.aps.org/doi/pdf/10.1103/PhysRevB.93.235142",
            },
            source_path=publisher,
        )

        resources = self.storage.list_paper_resources("paper-browser-publisher-upgrade")
        self.assertEqual(len(resources), 2)
        current = next(resource for resource in resources if resource["is_primary"])
        archived = next(resource for resource in resources if not resource["is_primary"])
        self.assertEqual(current["version_role"], "version_of_record")
        self.assertEqual(current["version_label"], "Published Version")
        self.assertEqual(Path(current["stored_path"]).resolve(), target)
        self.assertEqual(target.parent.resolve(), preprint.parent.resolve())
        self.assertEqual(target.name, publisher.name)
        self.assertEqual(target.read_bytes(), publisher.read_bytes())
        self.assertEqual(archived["version_role"], "preprint")
        self.assertEqual(Path(archived["stored_path"]).read_bytes(), preprint_bytes)
        self.assertIn("Associated Files/Library/Topic", archived["stored_path"])
        self.assertEqual(int(paper["primary_resource_id"]), int(current["id"]))
        self.assertFalse(int(paper["preferred_resource_id"] or 0))
        self.assertEqual(Path(paper["merged_pdf_path"]).resolve(), target)

    def test_download_from_arxiv_is_preprint_even_when_paper_has_doi(self) -> None:
        self.add_paper("paper-doi-with-arxiv-pdf")
        primary = self.write_pdf("Topic/Existing.pdf")
        self.storage.conn.execute(
            "UPDATE papers SET doi = ? WHERE paper_id = ?",
            ("10.1234/published", "paper-doi-with-arxiv-pdf"),
        )
        self.storage.update_paper_raw_json(
            "paper-doi-with-arxiv-pdf",
            {"arxiv_id": "1704.06287"},
        )
        self.storage.update_download_status(
            "paper-doi-with-arxiv-pdf",
            status="success",
            main_pdf_path=str(primary),
            merged_pdf_path=str(primary),
        )
        snapshot = ui_server.snapshot_primary_resource_before_download(
            self.storage,
            "paper-doi-with-arxiv-pdf",
            force=True,
        )
        primary.write_bytes(b"%PDF-1.4\narxiv preprint\n%%EOF\n")

        current = ui_server.register_downloaded_paper_resource(
            self.storage,
            "paper-doi-with-arxiv-pdf",
            result={
                "status": "success",
                "main_pdf_url": "https://arxiv.org/pdf/1704.06287v2",
            },
            snapshot=snapshot,
        )
        ui_server.cleanup_download_resource_snapshot(snapshot)

        self.assertEqual(current["version_role"], "preprint")
        self.assertEqual(current["source_url"], "https://arxiv.org/pdf/1704.06287v2")

    def test_forced_download_refresh_does_not_duplicate_identical_pdf(self) -> None:
        self.add_paper("paper-download-identical")
        primary = self.write_pdf("Topic/Unchanged.pdf")
        self.storage.update_download_status(
            "paper-download-identical",
            status="success",
            main_pdf_path=str(primary),
            merged_pdf_path=str(primary),
        )
        snapshot = ui_server.snapshot_primary_resource_before_download(
            self.storage,
            "paper-download-identical",
            force=True,
        )
        current = ui_server.register_downloaded_paper_resource(
            self.storage,
            "paper-download-identical",
            result={"status": "partial"},
            snapshot=snapshot,
        )
        ui_server.cleanup_download_resource_snapshot(snapshot)

        self.assertTrue(current["sha256"])
        self.assertEqual(len(self.storage.list_paper_resources("paper-download-identical")), 1)
        self.assertFalse(self.associated_root.exists())

    def test_identical_publisher_refresh_repairs_preprint_label_and_filename(self) -> None:
        self.add_paper("paper-repair-publisher-refresh")
        current_path = self.write_pdf("Topic/1602.05061.pdf")
        self.storage.conn.execute(
            "UPDATE papers SET doi = ? WHERE paper_id = ?",
            ("10.1103/physrevb.93.235142", "paper-repair-publisher-refresh"),
        )
        self.storage.update_download_status(
            "paper-repair-publisher-refresh",
            status="success",
            main_pdf_path=str(current_path),
            merged_pdf_path=str(current_path),
        )
        resource = self.storage.ensure_primary_pdf_resource("paper-repair-publisher-refresh")
        self.storage.conn.execute(
            """
            UPDATE resources
            SET version_role = 'preprint', version_label = 'Preprint'
            WHERE id = ?
            """,
            (int(resource["id"]),),
        )
        self.storage.conn.commit()
        self.storage.set_preferred_paper_resource(
            "paper-repair-publisher-refresh",
            int(resource["id"]),
        )
        snapshot = ui_server.snapshot_primary_resource_before_download(
            self.storage,
            "paper-repair-publisher-refresh",
            force=True,
        )
        duplicate_download = self.write_pdf("Topic/duplicate-publisher-download.pdf")
        duplicate_download.write_bytes(current_path.read_bytes())
        self.storage.update_download_status(
            "paper-repair-publisher-refresh",
            status="partial",
            main_pdf_path=str(duplicate_download),
            merged_pdf_path=str(duplicate_download),
        )

        repaired = ui_server.register_downloaded_paper_resource(
            self.storage,
            "paper-repair-publisher-refresh",
            result={
                "status": "partial",
                "main_pdf_url": "https://harvest.aps.org/v2/journals/articles/10.1103/physrevb.93.235142/fulltext",
            },
            snapshot=snapshot,
        )
        ui_server.cleanup_download_resource_snapshot(snapshot)

        paper = self.storage.get_paper("paper-repair-publisher-refresh")
        repaired_path = Path(paper["merged_pdf_path"])
        self.assertEqual(repaired["version_role"], "version_of_record")
        self.assertEqual(repaired["version_label"], "Published Version")
        self.assertFalse(int(paper["preferred_resource_id"] or 0))
        self.assertEqual(repaired_path.name, "physrevb.93.235142 [Published Version].pdf")
        self.assertEqual(repaired_path.read_bytes(), b"%PDF-1.4\nfixture\n%%EOF\n")
        self.assertFalse(current_path.exists())
        self.assertFalse(duplicate_download.exists())
        self.assertEqual(len(self.storage.list_paper_resources("paper-repair-publisher-refresh")), 1)

    def test_complete_export_filter_is_used_only_for_verified_manifest(self) -> None:
        export_root = self.root / "Export"
        primary = export_root / "Paper.pdf"
        associated = export_root / "Associated Files" / "Paper" / "Files" / "Notes.md"
        manifest_path = export_root / "Gewu Insight Manifest.json"
        associated.parent.mkdir(parents=True)
        primary.write_bytes(b"%PDF-1.4\nprimary\n%%EOF\n")
        associated.write_text("notes", encoding="utf-8")
        manifest = {
            "format": "Gewu Insight Complete Folder Export",
            "format_version": 1,
            "items": [],
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        inventory_path = self.root / "inventory.json"
        inventory_path.write_text(
            json.dumps(
                {
                    "summary": {"root": str(export_root)},
                    "files": [
                        {"path": str(primary)},
                        {"path": str(associated)},
                        {"path": str(manifest_path)},
                    ],
                }
            ),
            encoding="utf-8",
        )

        verified = ui_server.read_gewu_complete_export_manifest(export_root)
        self.assertIsNotNone(verified)
        ui_server.filter_complete_export_inventory(
            inventory_path,
            source_root=export_root,
            manifest=verified,
        )
        filtered = json.loads(inventory_path.read_text(encoding="utf-8"))
        self.assertEqual([record["path"] for record in filtered["files"]], [str(primary)])

    def test_complete_export_manifest_restores_associated_file_to_imported_work(self) -> None:
        self.add_paper("restored-paper")
        imported_primary = self.write_pdf("Imported/Paper.pdf")
        source_root = self.root / "Complete Export"
        source_primary = source_root / "Paper.pdf"
        source_note = source_root / "Associated Files" / "Paper" / "Files" / "Notes.md"
        source_note.parent.mkdir(parents=True)
        source_primary.write_bytes(imported_primary.read_bytes())
        source_note.write_text("# Restored note\n", encoding="utf-8")
        self.storage.update_download_status(
            "restored-paper",
            status="success",
            main_pdf_path=str(imported_primary),
            merged_pdf_path=str(imported_primary),
        )
        primary_resource = self.storage.ensure_primary_pdf_resource("restored-paper")
        self.storage.conn.execute(
            "UPDATE resources SET source_path = ? WHERE id = ?",
            (str(source_primary.resolve()), int(primary_resource["id"])),
        )
        self.storage.conn.commit()
        manifest = {
            "format": "Gewu Insight Complete Folder Export",
            "format_version": 1,
            "items": [
                {
                    "paper_id": "original-paper-id",
                    "primary_file": "Paper.pdf",
                    "resources": [
                        {
                            "is_primary": True,
                            "file": "Paper.pdf",
                            "file_role": "publication_version",
                            "version_role": "version_of_record",
                        },
                        {
                            "is_primary": False,
                            "file": "Associated Files/Paper/Files/Notes.md",
                            "file_role": "note",
                            "version_role": "",
                            "version_label": "",
                        },
                    ],
                }
            ],
        }

        restored = ui_server.restore_complete_export_associations(
            self.storage,
            source_root=source_root,
            manifest=manifest,
        )

        self.assertEqual(restored, {"restored": 1, "reused": 0, "missing": 0})
        resources = self.storage.list_paper_resources("restored-paper")
        self.assertEqual(len(resources), 2)
        self.assertEqual(next(resource for resource in resources if resource["is_primary"])["version_role"], "version_of_record")
        note = next(resource for resource in resources if resource["file_role"] == "note")
        self.assertEqual(Path(note["stored_path"]).read_text(encoding="utf-8"), "# Restored note\n")

    def test_associated_bundle_follows_canonical_pdf_folder_move(self) -> None:
        self.add_paper("paper-move-bundle")
        primary = self.write_pdf("Old Folder/Paper.pdf")
        self.storage.update_download_status(
            "paper-move-bundle",
            status="success",
            main_pdf_path=str(primary),
            merged_pdf_path=str(primary),
        )
        self.storage.ensure_primary_pdf_resource("paper-move-bundle")
        attached = ui_server.attach_file_to_paper(
            self.storage,
            paper_id="paper-move-bundle",
            filename="Notes.md",
            content=b"move with work",
            file_role="note",
        )
        old_attached_path = Path(attached["stored_path"])
        target = self.library_root / "New Folder" / "Paper.pdf"
        target.parent.mkdir(parents=True)
        primary.replace(target)
        ui_server.update_paper_pdf_paths(self.storage, "paper-move-bundle", target)

        ui_server.sync_all_pdf_aliases_for_paper(self.storage, "paper-move-bundle")

        resources = self.storage.list_paper_resources("paper-move-bundle")
        moved_note = next(resource for resource in resources if resource["file_role"] == "note")
        moved_path = Path(moved_note["stored_path"])
        self.assertFalse(old_attached_path.exists())
        self.assertIn("Associated Files/Library/New Folder", str(moved_path))
        self.assertEqual(moved_path.read_bytes(), b"move with work")
        payload = ui_server.paper_files_state_payload(self.storage, "paper-move-bundle")
        payload_note = next(file for file in payload["files"] if file["file_role"] == "note")
        self.assertEqual(Path(payload_note["local_path"]).resolve(), moved_path.resolve())
        self.assertTrue(payload_note["exists"])

    def test_paper_files_hide_only_a_matching_stale_legacy_alias(self) -> None:
        resources = [
            {
                "id": 1,
                "original_filename": "science.ado7136.pdf",
                "stored_path": "/old/Space/science.ado7136.pdf",
                "file_role": "other",
                "size_bytes": 6908035,
                "exists": False,
                "is_primary": False,
                "is_preferred": False,
            },
            {
                "id": 2,
                "original_filename": "science.ado7136.pdf",
                "stored_path": "/new/Space/science.ado7136.pdf",
                "file_role": "publication_version",
                "size_bytes": 6908035,
                "exists": True,
                "is_primary": True,
                "is_preferred": False,
            },
            {
                "id": 3,
                "original_filename": "genuinely-missing-note.md",
                "stored_path": "/old/Space/genuinely-missing-note.md",
                "file_role": "note",
                "size_bytes": 120,
                "exists": False,
                "is_primary": False,
                "is_preferred": False,
            },
        ]

        visible = ui_server.visible_paper_resources(resources)

        self.assertEqual([resource["id"] for resource in visible], [2, 3])

    def test_paper_files_keep_a_missing_preferred_resource_for_recovery(self) -> None:
        missing = {
            "id": 1,
            "original_filename": "same.pdf",
            "file_role": "other",
            "size_bytes": 100,
            "exists": False,
            "is_primary": False,
            "is_preferred": True,
        }
        existing = {
            "id": 2,
            "original_filename": "same.pdf",
            "file_role": "publication_version",
            "size_bytes": 100,
            "exists": True,
            "is_primary": True,
            "is_preferred": False,
        }

        self.assertEqual(
            [resource["id"] for resource in ui_server.visible_paper_resources([missing, existing])],
            [1, 2],
        )

    def test_paper_files_hide_untyped_predecessor_of_legacy_backfill_after_rename(self) -> None:
        missing = {
            "id": 1,
            "original_filename": "2607.13933v1.pdf",
            "file_role": None,
            "version_role": None,
            "added_via": None,
            "size_bytes": 29_339_810,
            "exists": False,
            "is_primary": False,
            "is_preferred": False,
        }
        existing = {
            "id": 2,
            "original_filename": "Z.Review_2607.13933v1.pdf",
            "file_role": "publication_version",
            "version_role": "other",
            "added_via": "legacy_backfill",
            "size_bytes": 29_379_347,
            "exists": True,
            "is_primary": True,
            "is_preferred": False,
        }

        self.assertEqual(
            [resource["id"] for resource in ui_server.visible_paper_resources([missing, existing])],
            [2],
        )

    def test_paper_files_keep_typed_missing_attachment_next_to_legacy_backfill(self) -> None:
        missing = {
            "id": 1,
            "original_filename": "notes.md",
            "file_role": "note",
            "version_role": None,
            "added_via": None,
            "size_bytes": 120,
            "exists": False,
            "is_primary": False,
            "is_preferred": False,
        }
        existing = {
            "id": 2,
            "original_filename": "paper.pdf",
            "file_role": "publication_version",
            "version_role": "version_of_record",
            "added_via": "legacy_backfill",
            "size_bytes": 1000,
            "exists": True,
            "is_primary": True,
            "is_preferred": False,
        }

        self.assertEqual(
            [resource["id"] for resource in ui_server.visible_paper_resources([missing, existing])],
            [1, 2],
        )

    def test_existing_non_primary_resource_can_be_adopted_without_changing_primary(self) -> None:
        self.add_paper("paper-adopt-resource")
        primary = self.write_pdf("Topic/Published.pdf")
        imported = self.write_pdf("Imported/Preprint.pdf")
        self.storage.update_download_status(
            "paper-adopt-resource",
            status="success",
            main_pdf_path=str(primary),
            merged_pdf_path=str(primary),
        )
        primary_resource = self.storage.ensure_primary_pdf_resource("paper-adopt-resource")
        imported_resource = self.storage.create_paper_resource(
            paper_id="paper-adopt-resource",
            stored_path=str(imported),
            display_name=imported.name,
            file_role="other",
            added_via="loader",
            mime_type="application/pdf",
            kind="pdf",
        )

        adopted = ui_server.adopt_existing_paper_resource(
            self.storage,
            int(imported_resource["id"]),
            file_role="publication_version",
            version_role="preprint",
        )

        paper = self.storage.get_paper("paper-adopt-resource")
        self.assertEqual(int(paper["primary_resource_id"]), int(primary_resource["id"]))
        self.assertEqual(Path(paper["merged_pdf_path"]).resolve(), primary.resolve())
        self.assertFalse(imported.exists())
        self.assertEqual(adopted["version_role"], "preprint")
        self.assertIn("Associated Files/Library/Topic", adopted["stored_path"])
        self.assertEqual(Path(adopted["stored_path"]).read_bytes(), b"%PDF-1.4\nfixture\n%%EOF\n")

    def test_existing_resource_can_be_recovered_from_its_source_path(self) -> None:
        self.add_paper("paper-adopt-source")
        primary = self.write_pdf("Topic/Published.pdf")
        source = self.write_pdf("Downloads/Preprint.pdf")
        missing_copy = self.library_root / "Preprint.pdf"
        self.storage.update_download_status(
            "paper-adopt-source",
            status="success",
            main_pdf_path=str(primary),
            merged_pdf_path=str(primary),
        )
        primary_resource = self.storage.ensure_primary_pdf_resource("paper-adopt-source")
        imported_resource = self.storage.create_paper_resource(
            paper_id="paper-adopt-source",
            stored_path=str(missing_copy),
            source_path=str(source),
            display_name=source.name,
            file_role="other",
            added_via="loader",
            mime_type="application/pdf",
            kind="pdf",
        )

        adopted = ui_server.adopt_existing_paper_resource(
            self.storage,
            int(imported_resource["id"]),
            file_role="publication_version",
            version_role="preprint",
        )

        paper = self.storage.get_paper("paper-adopt-source")
        self.assertEqual(int(paper["primary_resource_id"]), int(primary_resource["id"]))
        self.assertTrue(source.exists())
        self.assertFalse(missing_copy.exists())
        self.assertEqual(adopted["version_role"], "preprint")
        self.assertEqual(Path(adopted["stored_path"]).read_bytes(), source.read_bytes())

    def test_non_primary_resource_delete_moves_managed_copy_to_trash(self) -> None:
        self.add_paper("paper-delete-resource")
        primary = self.write_pdf("Topic/Published.pdf")
        self.storage.update_download_status(
            "paper-delete-resource",
            status="success",
            main_pdf_path=str(primary),
            merged_pdf_path=str(primary),
        )
        primary_resource = self.storage.ensure_primary_pdf_resource("paper-delete-resource")
        attached = ui_server.attach_file_to_paper(
            self.storage,
            paper_id="paper-delete-resource",
            filename="Notes.md",
            content=b"notes",
            file_role="note",
        )
        attached_path = Path(attached["stored_path"])
        trash_path = self.root / "Trash" / attached_path.name

        def fake_trash(path: Path) -> Path:
            trash_path.parent.mkdir(parents=True, exist_ok=True)
            path.replace(trash_path)
            return trash_path

        with patch.object(ui_server, "move_path_to_macos_trash", side_effect=fake_trash):
            deleted = ui_server.delete_paper_resource(
                self.storage,
                "paper-delete-resource",
                int(attached["id"]),
            )

        self.assertTrue(deleted["trashed"])
        self.assertTrue(trash_path.exists())
        self.assertIsNone(self.storage.get_paper_resource(int(attached["id"])))
        self.assertIsNotNone(self.storage.get_paper_resource(int(primary_resource["id"])))
        self.assertTrue(primary.exists())

    def test_current_primary_resource_cannot_be_deleted(self) -> None:
        self.add_paper("paper-keep-primary")
        primary = self.write_pdf("Topic/Current.pdf")
        self.storage.update_download_status(
            "paper-keep-primary",
            status="success",
            main_pdf_path=str(primary),
            merged_pdf_path=str(primary),
        )
        primary_resource = self.storage.ensure_primary_pdf_resource("paper-keep-primary")

        with self.assertRaisesRegex(ValueError, "current default file"):
            ui_server.delete_paper_resource(
                self.storage,
                "paper-keep-primary",
                int(primary_resource["id"]),
            )

        self.assertTrue(primary.exists())
        self.assertIsNotNone(self.storage.get_paper_resource(int(primary_resource["id"])))


if __name__ == "__main__":
    unittest.main()
