from __future__ import annotations

from io import BytesIO
import inspect
import tempfile
import unittest
from pathlib import Path
from paper_monitor import finder_alias
from subprocess import CompletedProcess
from unittest.mock import patch

from pypdf import PdfWriter

from paper_monitor import ui_server
from paper_monitor.storage import Storage


class LibraryFileOperationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "paper_monitor.sqlite"
        self.storage = Storage(self.db_path)
        self.original_roots = {
            "LIBRARY_LOCAL_COPY_ROOT": ui_server.LIBRARY_LOCAL_COPY_ROOT,
            "MY_PUBLICATIONS_LOCAL_COPY_ROOT": ui_server.MY_PUBLICATIONS_LOCAL_COPY_ROOT,
            "SPACES_LOCAL_COPY_ROOT": ui_server.SPACES_LOCAL_COPY_ROOT,
            "ASSOCIATED_FILES_ROOT": ui_server.ASSOCIATED_FILES_ROOT,
            "DEFAULT_PDF_DIR": ui_server.DEFAULT_PDF_DIR,
        }
        ui_server.LIBRARY_LOCAL_COPY_ROOT = self.root / "Library"
        ui_server.MY_PUBLICATIONS_LOCAL_COPY_ROOT = self.root / "My Publications"
        ui_server.SPACES_LOCAL_COPY_ROOT = self.root / "Spaces"
        ui_server.ASSOCIATED_FILES_ROOT = self.root / "Associated Files"
        ui_server.DEFAULT_PDF_DIR = self.root / "pdfs"

    def tearDown(self) -> None:
        for name, value in self.original_roots.items():
            setattr(ui_server, name, value)
        self.storage.close()
        self.tmp.cleanup()

    def write_layout_pdf(self, filename: str, title_lines: list[str]) -> Path:
        path = self.root / filename
        commands = [
            "BT /F1 9 Tf 72 760 Td (PHYSICAL REVIEW LETTERS) Tj",
            "/F1 20 Tf 0 -80 Td",
        ]
        for index, line in enumerate(title_lines):
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            if index:
                commands.append("0 -25 Td")
            commands.append(f"({escaped}) Tj")
        commands.extend([
            "/F1 11 Tf 0 -35 Td (A. Example and B. Author) Tj",
            "/F1 10 Tf 0 -45 Td (Abstract) Tj ET",
        ])
        content = " ".join(commands).encode("latin-1")
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream",
        ]
        body = b"%PDF-1.4\n"
        offsets = [0]
        for index, obj in enumerate(objects, start=1):
            offsets.append(len(body))
            body += f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n"
        xref_offset = len(body)
        xref = f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii")
        xref += b"".join(
            f"{offset:010d} 00000 n \n".encode("ascii")
            for offset in offsets[1:]
        )
        trailer = (
            f"trailer << /Root 1 0 R /Size {len(objects) + 1} >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
        path.write_bytes(body + xref + trailer)
        return path

    def test_pdf_layout_title_candidates_use_large_front_page_text(self) -> None:
        pdf = self.write_layout_pdf(
            "opaque-file.pdf",
            [
                "Quantum vortex core and missing pseudogap",
                "in the multiband crossover superconductor FeSe",
            ],
        )

        candidates = ui_server.pdf_layout_title_candidates(pdf)

        self.assertTrue(candidates)
        self.assertEqual(
            ui_server.normalized_title_key(candidates[0]),
            ui_server.normalized_title_key(
                "Quantum vortex core and missing pseudogap "
                "in the multiband crossover superconductor FeSe"
            ),
        )

    def test_identifier_lookup_uses_title_extracted_from_pdf_layout(self) -> None:
        title = (
            "Quantum vortex core and missing pseudogap "
            "in the multiband crossover superconductor FeSe"
        )
        pdf = self.write_layout_pdf(
            "opaque-file.pdf",
            [
                "Quantum vortex core and missing pseudogap",
                "in the multiband crossover superconductor FeSe",
            ],
        )
        calls: list[str] = []

        def title_lookup(candidate: str) -> dict[str, str]:
            calls.append(candidate)
            if ui_server.normalized_title_key(candidate) == ui_server.normalized_title_key(title):
                return {
                    "kind": "doi",
                    "identifier": "10.1103/physrevlett.122.077001",
                    "source": "title_openalex",
                }
            return {"kind": "", "identifier": "", "source": ""}

        found = ui_server.extract_identifier_from_pdf_or_title(
            pdf,
            {"paper_id": "layout-paper", "title": "opaque-file.pdf"},
            title_lookup=title_lookup,
        )

        self.assertEqual(found["identifier"], "10.1103/physrevlett.122.077001")
        self.assertEqual(found["source"], "title_openalex")
        self.assertTrue(
            any(
                ui_server.normalized_title_key(candidate)
                == ui_server.normalized_title_key(title)
                for candidate in calls
            )
        )

    def test_import_identifier_recovery_records_source_and_counts(self) -> None:
        pdf = self.write_layout_pdf("unresolved.pdf", ["A recoverable imported paper title"])
        self.storage.upsert_paper(
            {
                "paper_id": "unresolved-paper",
                "doi": "",
                "title": "unresolved.pdf",
                "journal": "Imported Library",
                "publication_date": "",
                "abstract": "",
                "source": "inventory",
                "type": "imported_pdf",
            }
        )
        self.storage.update_download_status(
            "unresolved-paper",
            status="success",
            main_pdf_path=str(pdf),
            merged_pdf_path=str(pdf),
            supplement_pdf_paths=[],
        )
        result = {
            "metadata_refresh_candidates": [
                {
                    "paper_id": "unresolved-paper",
                    "doi": "",
                    "arxiv_id": "",
                }
            ]
        }
        found = {
            "kind": "doi",
            "identifier": "10.1234/recovered",
            "source": "title_openalex",
            "matched_title": "A recoverable imported paper title",
        }
        with patch.object(
            ui_server,
            "extract_identifier_from_pdf_or_title",
            return_value=found,
        ), patch.object(
            ui_server,
            "refresh_library_paper_metadata_for_identifier",
            side_effect=lambda storage, paper_id, identifier, **_kwargs: storage.get_paper(paper_id),
        ):
            recovered = ui_server.recover_imported_pdf_identifiers(
                self.storage,
                result,
            )

        paper = self.storage.get_paper("unresolved-paper") or {}
        self.assertEqual(recovered, {"unresolved-paper"})
        self.assertEqual(paper["doi"], "10.1234/recovered")
        self.assertEqual(paper["doi_source"], "title_openalex")
        self.assertEqual(result["identifier_recovery_attempted"], 1)
        self.assertEqual(result["identifiers_recovered"], 1)
        self.assertEqual(result["identifier_recovery_unresolved"], 0)
        self.assertEqual(result["identifier_recovery_sources"], {"title_openalex": 1})

    def test_full_library_identifier_recovery_uses_title_and_records_attempt(self) -> None:
        pdf = self.write_layout_pdf(
            "missing-identifier.pdf",
            ["A reliable title for identifier recovery"],
        )
        self.storage.upsert_paper(
            {
                "paper_id": "missing-identifier",
                "doi": "",
                "title": "A reliable title for identifier recovery",
                "journal": "Imported Library",
                "publication_date": "",
                "abstract": "",
                "source": "inventory",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "missing-identifier",
            status="success",
            main_pdf_path=str(pdf),
            merged_pdf_path=str(pdf),
            supplement_pdf_paths=[],
        )
        self.storage.add_library_item(paper_id="missing-identifier", folder_id=1)
        job_id = ui_server.create_library_identifier_recovery_job(skip_days=7)
        found = {
            "kind": "doi",
            "identifier": "10.1234/full-library-recovery",
            "source": "title_crossref",
        }

        with patch.object(
            ui_server,
            "identifier_from_title_lookup",
            return_value=found,
        ), patch.object(
            ui_server,
            "refresh_single_paper_metadata_for_mode",
            side_effect=lambda _storage, paper, **_kwargs: paper,
        ), patch.object(ui_server.time, "sleep"):
            ui_server.run_library_identifier_recovery_job(
                job_id=job_id,
                db_path=self.db_path,
                skip_days=7,
            )

        job = ui_server.get_library_import_job(job_id) or {}
        result = job.get("result") or {}
        paper = self.storage.get_paper("missing-identifier") or {}
        attempt = self.storage.conn.execute(
            """
            SELECT mode, status
            FROM paper_metadata_refreshes
            WHERE paper_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            ("missing-identifier",),
        ).fetchone()
        self.assertEqual(job["status"], "completed")
        self.assertEqual(result["identifiers_recovered"], 1)
        self.assertEqual(result["identifier_recovery_unresolved"], 0)
        self.assertEqual(paper["doi"], "10.1234/full-library-recovery")
        self.assertEqual(dict(attempt), {"mode": "identifier", "status": "recovered"})

    def test_full_library_identifier_recovery_skips_recent_attempt(self) -> None:
        pdf = self.write_layout_pdf(
            "recent-missing-identifier.pdf",
            ["Another reliable paper title for recovery"],
        )
        self.storage.upsert_paper(
            {
                "paper_id": "recent-missing-identifier",
                "doi": "",
                "title": "Another reliable paper title for recovery",
                "journal": "Imported Library",
                "publication_date": "",
                "abstract": "",
                "source": "inventory",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "recent-missing-identifier",
            status="success",
            main_pdf_path=str(pdf),
            merged_pdf_path=str(pdf),
            supplement_pdf_paths=[],
        )
        self.storage.add_library_item(paper_id="recent-missing-identifier", folder_id=1)
        refresh_id = ui_server.record_metadata_refresh_start(
            self.storage,
            paper_id="recent-missing-identifier",
            mode="identifier",
            source_summary="test",
        )
        ui_server.record_metadata_refresh_finish(
            self.storage,
            refresh_id,
            status="unresolved_checked",
        )
        job_id = ui_server.create_library_identifier_recovery_job(skip_days=7)

        with patch.object(ui_server, "identifier_from_title_lookup") as lookup:
            ui_server.run_library_identifier_recovery_job(
                job_id=job_id,
                db_path=self.db_path,
                skip_days=7,
            )

        result = (ui_server.get_library_import_job(job_id) or {}).get("result") or {}
        lookup.assert_not_called()
        self.assertEqual(result["skipped_recent"], 1)
        self.assertEqual(result["attempted"], 0)

    def test_full_library_identifier_recovery_retries_legacy_unresolved_attempt(self) -> None:
        pdf = self.write_layout_pdf(
            "legacy-unresolved.pdf",
            ["A legacy unresolved paper title for recovery"],
        )
        self.storage.upsert_paper(
            {
                "paper_id": "legacy-unresolved",
                "doi": "",
                "title": "A legacy unresolved paper title for recovery",
                "journal": "Imported Library",
                "publication_date": "",
                "abstract": "",
                "source": "inventory",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "legacy-unresolved",
            status="success",
            main_pdf_path=str(pdf),
            merged_pdf_path=str(pdf),
            supplement_pdf_paths=[],
        )
        self.storage.add_library_item(paper_id="legacy-unresolved", folder_id=1)
        refresh_id = ui_server.record_metadata_refresh_start(
            self.storage,
            paper_id="legacy-unresolved",
            mode="identifier",
            source_summary="legacy test",
        )
        ui_server.record_metadata_refresh_finish(
            self.storage,
            refresh_id,
            status="unresolved",
        )
        job_id = ui_server.create_library_identifier_recovery_job(skip_days=7)

        with patch.object(
            ui_server,
            "identifier_from_title_lookup",
            return_value={"kind": "", "identifier": "", "source": "", "lookup_status": "completed"},
        ) as lookup, patch.object(ui_server.time, "sleep"):
            ui_server.run_library_identifier_recovery_job(
                job_id=job_id,
                db_path=self.db_path,
                skip_days=7,
            )

        result = (ui_server.get_library_import_job(job_id) or {}).get("result") or {}
        self.assertTrue(lookup.called)
        self.assertEqual(result["skipped_recent"], 0)
        self.assertEqual(result["attempted"], 1)
        attempt = self.storage.conn.execute(
            """
            SELECT status
            FROM paper_metadata_refreshes
            WHERE paper_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            ("legacy-unresolved",),
        ).fetchone()
        self.assertEqual(attempt["status"], "unresolved_checked")

    def test_full_library_identifier_recovery_marks_all_service_failures_retryable(self) -> None:
        pdf = self.write_layout_pdf(
            "network-unavailable.pdf",
            ["A paper title whose identifier services are unavailable"],
        )
        self.storage.upsert_paper(
            {
                "paper_id": "network-unavailable",
                "doi": "",
                "title": "A paper title whose identifier services are unavailable",
                "journal": "Imported Library",
                "publication_date": "",
                "abstract": "",
                "source": "inventory",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "network-unavailable",
            status="success",
            main_pdf_path=str(pdf),
            merged_pdf_path=str(pdf),
            supplement_pdf_paths=[],
        )
        self.storage.add_library_item(paper_id="network-unavailable", folder_id=1)
        job_id = ui_server.create_library_identifier_recovery_job(skip_days=7)

        unavailable = {
            "kind": "",
            "identifier": "",
            "source": "",
            "lookup_status": "unavailable",
            "lookup_error": "All identifier services unavailable",
        }
        with patch.object(
            ui_server,
            "identifier_from_title_lookup",
            return_value=unavailable,
        ), patch.object(ui_server.time, "sleep"):
            ui_server.run_library_identifier_recovery_job(
                job_id=job_id,
                db_path=self.db_path,
                skip_days=7,
            )

        result = (ui_server.get_library_import_job(job_id) or {}).get("result") or {}
        attempt = self.storage.conn.execute(
            """
            SELECT status, error
            FROM paper_metadata_refreshes
            WHERE paper_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            ("network-unavailable",),
        ).fetchone()
        self.assertEqual(result["failed"], 1)
        self.assertEqual(attempt["status"], "retryable")
        self.assertIn("services unavailable", attempt["error"])

    def test_full_library_identifier_recovery_excludes_non_pdf_files(self) -> None:
        text_path = self.root / "Device_C_177_raw.txt"
        text_path.write_text("measurement data", encoding="utf-8")
        self.storage.upsert_paper(
            {
                "paper_id": "non-pdf-library-file",
                "doi": "",
                "title": "Device_C_177_raw.txt",
                "journal": "",
                "publication_date": "",
                "abstract": "",
                "source": "inventory",
                "type": "file",
            }
        )
        self.storage.update_download_status(
            "non-pdf-library-file",
            status="success",
            main_pdf_path=str(text_path),
            merged_pdf_path=str(text_path),
            supplement_pdf_paths=[],
        )
        self.storage.add_library_item(paper_id="non-pdf-library-file", folder_id=1)
        job_id = ui_server.create_library_identifier_recovery_job(skip_days=7)

        with patch.object(ui_server, "identifier_from_title_lookup") as lookup:
            ui_server.run_library_identifier_recovery_job(
                job_id=job_id,
                db_path=self.db_path,
                skip_days=7,
            )

        result = (ui_server.get_library_import_job(job_id) or {}).get("result") or {}
        lookup.assert_not_called()
        self.assertEqual(result["total_candidates"], 0)
        self.assertEqual(result["attempted"], 0)
        refresh_count = self.storage.conn.execute(
            """
            SELECT COUNT(*)
            FROM paper_metadata_refreshes
            WHERE paper_id = ?
            """,
            ("non-pdf-library-file",),
        ).fetchone()[0]
        self.assertEqual(refresh_count, 0)

    def test_library_metadata_refresh_job_starts_without_identifier_recovery_state(self) -> None:
        job_id = ui_server.create_library_metadata_refresh_job(
            metadata_mode="quick",
            skip_days=3,
        )

        ui_server.run_library_metadata_refresh_job(
            job_id=job_id,
            db_path=self.db_path,
            metadata_mode="quick",
            skip_days=3,
        )

        job = ui_server.get_library_import_job(job_id) or {}
        self.assertEqual(job["status"], "completed")
        self.assertEqual((job.get("result") or {}).get("total_candidates"), 0)

    def test_loader_exposes_full_library_missing_identifier_mode(self) -> None:
        html = ui_server.INDEX_HTML
        self.assertIn("/api/library/identifier-recovery/start", html)
        self.assertIn("function openIdentifierRecoveryWindow()", html)
        self.assertIn("All Library PDF files without DOI/arXiv", html)
        self.assertIn("Scans active Library and Space PDF files", html)
        self.assertIn("No Google Scholar requests.", html)

    def test_pdf_rename_filename_preserves_pdf_suffix_when_title_is_long(self) -> None:
        long_title = " ".join(["Very Long Electride Nonlinear Optical Response"] * 12)
        filename = ui_server.pdf_rename_filename_from_values(
            "{author}_{year}_{title}",
            {"author": "Dale", "year": "2026", "title": long_title, "journal": "", "doi": ""},
            ".pdf",
        )

        self.assertTrue(filename.endswith(".pdf"))
        self.assertLessEqual(len(filename), 120)

    def test_embedded_library_table_year_regex_keeps_js_word_boundaries(self) -> None:
        self.assertNotIn("\b", ui_server.INDEX_HTML)
        self.assertIn(r"\b(18|19|20|21)\d{2}\b", ui_server.INDEX_HTML)

    def test_move_library_item_api_uses_updated_pdf_path(self) -> None:
        source_folder = self.storage.create_library_folder(parent_id=1, name="Source")
        target_folder = self.storage.create_library_folder(parent_id=1, name="Target")
        source_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(source_folder["id"]))
        source_dir.mkdir(parents=True)
        source_pdf = source_dir / "paper.pdf"
        source_pdf.write_bytes(b"%PDF fixture")

        self.storage.upsert_paper(
            {
                "paper_id": "fixture-paper",
                "doi": "10.1234/fixture",
                "title": "Fixture Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "fixture-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        item = self.storage.add_library_item(paper_id="fixture-paper", folder_id=int(source_folder["id"]))

        ui_server.move_or_alias_library_item_pdf(
            self.storage,
            item=item,
            target_folder_id=int(target_folder["id"]),
        )
        moved = self.storage.move_library_item(item_id=int(item["id"]), folder_id=int(target_folder["id"]))
        paper = self.storage.get_paper("fixture-paper") or {}
        api_item = ui_server.library_item_to_api(moved, paper)
        moved_path = Path(api_item["paper"]["merged_pdf_path"])

        self.assertFalse(source_pdf.exists())
        self.assertTrue(moved_path.exists())
        self.assertEqual(
            moved_path.parent.resolve(),
            ui_server.local_copy_dir_for_library_folder(self.storage, int(target_folder["id"])).resolve(),
        )

    def test_copy_library_item_creates_only_the_target_alias(self) -> None:
        source_folder = self.storage.create_library_folder(parent_id=1, name="Source")
        target_folder = self.storage.create_library_folder(parent_id=1, name="Target")
        source_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(source_folder["id"]))
        source_dir.mkdir(parents=True)
        source_pdf = source_dir / "paper.pdf"
        source_pdf.write_bytes(b"%PDF fixture")
        self.storage.upsert_paper(
            {
                "paper_id": "copy-targeted-paper",
                "doi": "10.1234/copy-targeted",
                "title": "Copy Targeted Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "copy-targeted-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        item = self.storage.add_library_item(
            paper_id="copy-targeted-paper",
            folder_id=int(source_folder["id"]),
        )

        with patch.object(ui_server, "sync_all_pdf_aliases_for_paper") as full_sync:
            pasted = ui_server.PaperMonitorUiHandler.paste_library_entry_in_storage(
                None,
                self.storage,
                "item",
                int(item["id"]),
                int(target_folder["id"]),
            )

        target_path = ui_server.library_item_local_pdf_path(
            self.storage,
            pasted,
            self.storage.get_paper("copy-targeted-paper"),
        )
        full_sync.assert_not_called()
        self.assertTrue(source_pdf.exists())
        self.assertIsNotNone(target_path)
        self.assertTrue(finder_alias.is_alias(target_path))
        self.assertEqual(finder_alias.resolve(target_path), source_pdf.resolve())

    def test_alias_only_library_item_move_does_not_run_global_sync(self) -> None:
        owner_folder = self.storage.create_library_folder(parent_id=1, name="Owner")
        source_folder = self.storage.create_library_folder(parent_id=1, name="Source")
        target_folder = self.storage.create_library_folder(parent_id=1, name="Target")
        owner_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(owner_folder["id"]))
        owner_dir.mkdir(parents=True)
        source_pdf = owner_dir / "paper.pdf"
        source_pdf.write_bytes(b"%PDF fixture")
        self.storage.upsert_paper(
            {
                "paper_id": "alias-move-paper",
                "doi": "10.1234/alias-move",
                "title": "Alias Move Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "alias-move-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        self.storage.add_library_item(paper_id="alias-move-paper", folder_id=int(owner_folder["id"]))
        item = self.storage.add_library_item(paper_id="alias-move-paper", folder_id=int(source_folder["id"]))
        source_alias = ui_server.sync_alias_for_library_item(
            self.storage,
            "alias-move-paper",
            int(source_folder["id"]),
        )

        with patch.object(ui_server, "sync_all_pdf_aliases_for_paper") as full_sync:
            canonical_moved = ui_server.move_or_alias_library_item_pdf(
                self.storage,
                item=item,
                target_folder_id=int(target_folder["id"]),
            )
            moved = self.storage.move_library_item(item_id=int(item["id"]), folder_id=int(target_folder["id"]))
            target_alias = ui_server.sync_alias_for_library_item(
                self.storage,
                "alias-move-paper",
                int(target_folder["id"]),
            )

        full_sync.assert_not_called()
        self.assertFalse(canonical_moved)
        self.assertFalse(source_alias.exists())
        self.assertEqual(int(moved["folder_id"]), int(target_folder["id"]))
        self.assertTrue(finder_alias.is_alias(target_alias))
        self.assertEqual(finder_alias.resolve(target_alias), source_pdf.resolve())

    def test_canonical_item_move_relocates_the_associated_work_directory(self) -> None:
        source_folder = self.storage.create_library_folder(parent_id=1, name="Source")
        target_folder = self.storage.create_library_folder(parent_id=1, name="Target")
        source_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(source_folder["id"]))
        source_dir.mkdir(parents=True)
        source_pdf = source_dir / "paper.pdf"
        source_pdf.write_bytes(b"%PDF fixture")
        self.storage.upsert_paper(
            {
                "paper_id": "associated-move-paper",
                "doi": "10.1234/associated-move",
                "title": "Associated Move Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "associated-move-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        item = self.storage.add_library_item(
            paper_id="associated-move-paper",
            folder_id=int(source_folder["id"]),
        )
        storage_key = self.storage.storage_key_for_paper_id("associated-move-paper")
        old_work_dir = (
            ui_server.ASSOCIATED_FILES_ROOT
            / "Library"
            / "Source"
            / f"paper [{storage_key}]"
        )
        old_work_dir.mkdir(parents=True)
        attachment = old_work_dir / "notes.md"
        attachment.write_text("fixture notes", encoding="utf-8")
        resource = self.storage.create_paper_resource(
            paper_id="associated-move-paper",
            stored_path=str(attachment),
            file_role="other",
            added_via="test",
        )

        canonical_moved = ui_server.move_or_alias_library_item_pdf(
            self.storage,
            item=item,
            target_folder_id=int(target_folder["id"]),
        )
        moved = self.storage.move_library_item(
            item_id=int(item["id"]),
            folder_id=int(target_folder["id"]),
        )
        self.assertTrue(canonical_moved)
        ui_server.sync_all_pdf_aliases_for_paper(self.storage, "associated-move-paper")

        paper = self.storage.get_paper("associated-move-paper") or {}
        moved_pdf = Path(paper["merged_pdf_path"])
        new_work_dir = ui_server.existing_associated_work_dir(
            self.storage,
            "associated-move-paper",
        )
        moved_resource = self.storage.get_paper_resource(int(resource["id"])) or {}
        moved_attachment = Path(str(moved_resource.get("stored_path") or ""))
        self.assertEqual(int(moved["folder_id"]), int(target_folder["id"]))
        self.assertEqual(moved_pdf.parent.resolve(), ui_server.local_copy_dir_for_library_folder(
            self.storage,
            int(target_folder["id"]),
        ).resolve())
        self.assertFalse(old_work_dir.exists())
        self.assertIsNotNone(new_work_dir)
        self.assertEqual(
            new_work_dir.parent.resolve(),
            (ui_server.ASSOCIATED_FILES_ROOT / "Library" / "Target").resolve(),
        )
        self.assertTrue(moved_attachment.is_file())
        self.assertEqual(moved_attachment.parent.resolve(), new_work_dir.resolve())
        self.assertEqual(moved_attachment.read_text(encoding="utf-8"), "fixture notes")

    def test_folder_move_reconciles_a_canonical_pdf_only_once(self) -> None:
        source_folder = self.storage.create_library_folder(parent_id=1, name="Source")
        child_folder = self.storage.create_library_folder(parent_id=int(source_folder["id"]), name="Child")
        target_folder = self.storage.create_library_folder(parent_id=1, name="Target")
        child_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(child_folder["id"]))
        child_dir.mkdir(parents=True)
        source_pdf = child_dir / "paper.pdf"
        source_pdf.write_bytes(b"%PDF fixture")
        self.storage.upsert_paper(
            {
                "paper_id": "folder-move-paper",
                "doi": "10.1234/folder-move",
                "title": "Folder Move Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "folder-move-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        self.storage.add_library_item(paper_id="folder-move-paper", folder_id=int(child_folder["id"]))
        plan = ui_server.folder_tree_pdf_move_plan(self.storage, int(source_folder["id"]))
        self.storage.move_library_folder(folder_id=int(source_folder["id"]), parent_id=int(target_folder["id"]))

        original_sync = ui_server.sync_all_pdf_aliases_for_paper
        with patch.object(ui_server, "sync_all_pdf_aliases_for_paper", wraps=original_sync) as full_sync:
            ui_server.apply_folder_tree_pdf_move_plan(self.storage, plan)

        paper = self.storage.get_paper("folder-move-paper") or {}
        moved_pdf = Path(paper["merged_pdf_path"])
        full_sync.assert_called_once()
        self.assertFalse(source_pdf.exists())
        self.assertTrue(moved_pdf.exists())
        self.assertEqual(
            moved_pdf.parent.resolve(),
            ui_server.local_copy_dir_for_library_folder(self.storage, int(child_folder["id"])).resolve(),
        )

    def test_journal_download_infers_existing_space_as_real_pdf_target(self) -> None:
        space = self.storage.create_library_root_folder(name="Wigner Crystal")
        self.storage.upsert_paper(
            {
                "paper_id": "space-download-paper",
                "doi": "10.1234/space-download",
                "title": "Space Download Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-07-17",
                "abstract": "",
                "source": "arxiv",
                "type": "article",
            }
        )
        self.storage.add_library_item(paper_id="space-download-paper", folder_id=int(space["id"]))

        target = ui_server.preferred_local_pdf_dir_for_paper(self.storage, "space-download-paper")

        self.assertIsNotNone(target)
        self.assertEqual(
            target.resolve(),
            (ui_server.SPACES_LOCAL_COPY_ROOT / "Wigner Crystal").resolve(),
        )
        handler = inspect.getsource(ui_server.PaperMonitorUiHandler.handle_download)
        self.assertIn("preferred_local_pdf_dir_for_paper(storage, paper_id)", handler)
        self.assertIn("reconcile_paper_pdf_storage(storage, paper_id, target_dir=target_dir)", handler)

    def test_reconcile_moves_cache_pdf_into_space_and_replaces_alias_path(self) -> None:
        space = self.storage.create_library_root_folder(name="Wigner Crystal")
        self.storage.upsert_paper(
            {
                "paper_id": "cached-space-paper",
                "doi": "10.1234/cached-space",
                "title": "Cached Space Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-07-17",
                "abstract": "",
                "source": "arxiv",
                "type": "article",
            }
        )
        self.storage.add_library_item(paper_id="cached-space-paper", folder_id=int(space["id"]))
        cached_dir = ui_server.DEFAULT_PDF_DIR / "cached-space-paper"
        cached_dir.mkdir(parents=True)
        cached_pdf = cached_dir / "cached-space-paper.pdf"
        cached_pdf.write_bytes(b"%PDF fixture")
        stale_dir = ui_server.SPACES_LOCAL_COPY_ROOT / "Wigner C"
        stale_dir.mkdir(parents=True)
        stale_alias = stale_dir / cached_pdf.name
        stale_alias.symlink_to(cached_pdf)
        self.storage.update_download_status(
            "cached-space-paper",
            status="success",
            main_pdf_path=str(stale_alias),
            merged_pdf_path=str(stale_alias),
            supplement_pdf_paths=[],
        )

        changed = ui_server.reconcile_paper_pdf_storage(self.storage, "cached-space-paper")
        paper = self.storage.get_paper("cached-space-paper") or {}
        stored_pdf = Path(paper["merged_pdf_path"])

        self.assertTrue(changed)
        self.assertFalse(cached_pdf.exists())
        self.assertFalse(stale_alias.is_symlink(), list(stale_dir.iterdir()) if stale_dir.exists() else [])
        self.assertFalse(stale_dir.exists(), list(stale_dir.iterdir()) if stale_dir.exists() else [])
        self.assertTrue(stored_pdf.exists())
        self.assertFalse(stored_pdf.is_symlink())
        self.assertEqual(stored_pdf.parent.resolve(), (ui_server.SPACES_LOCAL_COPY_ROOT / "Wigner Crystal").resolve())
        self.assertEqual(paper["main_pdf_path"], paper["merged_pdf_path"])

    def test_library_display_names_drive_real_pdf_and_shortcut_names(self) -> None:
        real_folder = self.storage.create_library_folder(parent_id=1, name="Real")
        shortcut_folder = self.storage.create_library_root_folder(name="Space")
        real_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(real_folder["id"]))
        shortcut_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(shortcut_folder["id"]))
        real_dir.mkdir(parents=True)
        source_pdf = real_dir / "publisher-name.pdf"
        source_pdf.write_bytes(b"%PDF fixture")
        self.storage.upsert_paper(
            {
                "paper_id": "named-paper",
                "doi": "10.1234/named",
                "title": "Named Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "named-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        real_item = self.storage.add_library_item(
            paper_id="named-paper",
            folder_id=int(real_folder["id"]),
        )
        shortcut_item = self.storage.add_library_item(
            paper_id="named-paper",
            folder_id=int(shortcut_folder["id"]),
        )
        self.storage.rename_library_item(
            item_id=int(real_item["id"]),
            name="01.Primary Library Name.pdf",
        )
        self.storage.rename_library_item(
            item_id=int(shortcut_item["id"]),
            name="02.Space Shortcut Name.pdf",
        )

        result = ui_server.sync_all_pdf_aliases_for_paper(self.storage, "named-paper")
        paper = self.storage.get_paper("named-paper") or {}
        canonical = Path(paper["merged_pdf_path"])
        shortcut = shortcut_dir / "02.Space Shortcut Name.pdf"

        self.assertTrue(result["canonical_renamed"])
        self.assertEqual(
            canonical.resolve(),
            (real_dir / "01.Primary Library Name.pdf").resolve(),
        )
        self.assertTrue(canonical.exists())
        self.assertFalse(source_pdf.exists())
        self.assertTrue(finder_alias.is_alias(shortcut))
        self.assertEqual(finder_alias.resolve(shortcut), canonical.resolve())
        self.assertEqual(paper["main_pdf_path"], paper["merged_pdf_path"])
        audit = ui_server.audit_library_pdf_names(self.storage)
        self.assertEqual(audit["mismatched_real_files"], 0)
        self.assertEqual(audit["mismatched_shortcuts"], 0)
        self.assertEqual(audit["missing_shortcuts"], 0)

    def test_folder_real_file_export_uses_each_library_item_display_name(self) -> None:
        space = self.storage.create_library_root_folder(name="Tobit")
        folder = self.storage.create_library_folder(
            parent_id=int(space["id"]),
            name="Quantum Computation",
        )
        canonical_dir = ui_server.LIBRARY_LOCAL_COPY_ROOT / "Canonical"
        canonical_dir.mkdir(parents=True)
        source_pdf = canonical_dir / "19718.pdf"
        source_pdf.write_bytes(b"%PDF fixture")
        self.storage.upsert_paper(
            {
                "paper_id": "export-name-paper",
                "doi": "10.1038/19718",
                "title": "Coherent control of macroscopic quantum states",
                "journal": "Nature",
                "publication_date": "1999-04-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "export-name-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        item = self.storage.add_library_item(
            paper_id="export-name-paper",
            folder_id=int(folder["id"]),
        )
        self.storage.rename_library_item(
            item_id=int(item["id"]),
            name="01.Cooper pair box_19718.pdf",
        )
        destination = self.root / "Export"

        result = ui_server.copy_library_folder_real_files(
            self.storage,
            int(space["id"]),
            destination,
            unique_root=False,
        )

        exported = (
            destination
            / "Tobit"
            / "Quantum Computation"
            / "01.Cooper pair box_19718.pdf"
        )
        self.assertTrue(exported.is_file())
        self.assertFalse(exported.is_symlink())
        self.assertEqual(exported.read_bytes(), source_pdf.read_bytes())
        self.assertEqual(result["files_copied"], 1)
        self.assertTrue((destination / "Tobit" / "Gewu Insight Manifest.json").is_file())

    def test_folder_export_includes_associated_files_and_manifest(self) -> None:
        folder = self.storage.create_library_folder(parent_id=1, name="Versions")
        primary_dir = ui_server.LIBRARY_LOCAL_COPY_ROOT / "Versions"
        primary_dir.mkdir(parents=True)
        primary = primary_dir / "Paper.pdf"
        primary.write_bytes(b"%PDF-1.4\ncurrent\n%%EOF\n")
        self.storage.upsert_paper(
            {
                "paper_id": "complete-export-paper",
                "title": "Complete Export Paper",
                "journal": "Fixture Journal",
                "source": "test",
                "raw": {},
            }
        )
        self.storage.update_download_status(
            "complete-export-paper",
            status="success",
            main_pdf_path=str(primary),
            merged_pdf_path=str(primary),
        )
        self.storage.ensure_primary_pdf_resource("complete-export-paper")
        self.storage.conn.execute("UPDATE resources SET file_type='published_version',version_role='version_of_record' WHERE paper_id='complete-export-paper'")
        self.storage.conn.commit()
        self.storage.add_library_item(
            paper_id="complete-export-paper",
            folder_id=int(folder["id"]),
        )
        accepted_pdf = BytesIO()
        accepted_writer = PdfWriter()
        accepted_writer.add_blank_page(width=72, height=72)
        accepted_writer.write(accepted_pdf)
        ui_server.attach_file_to_paper(
            self.storage,
            paper_id="complete-export-paper",
            filename="Accepted.pdf",
            content=accepted_pdf.getvalue(),
            file_role="publication_version",
            version_role="accepted_manuscript",
        )
        ui_server.attach_file_to_paper(
            self.storage,
            paper_id="complete-export-paper",
            filename="Notes.md",
            content=b"# Notes\n",
            file_role="note",
        )

        destination = self.root / "Export Complete"
        result = ui_server.copy_library_folder_real_files(
            self.storage,
            int(folder["id"]),
            destination,
            unique_root=False,
        )

        exported_root = destination / "Versions"
        self.assertTrue((exported_root / "Paper.pdf").is_file())
        self.assertTrue((exported_root / "Gewu Insight Manifest.json").is_file())
        associated = list((exported_root / "Associated Files").rglob("*"))
        self.assertTrue(any(path.name == "Accepted.pdf" for path in associated))
        self.assertTrue(any(path.name == "Notes.md" for path in associated))
        self.assertEqual(result["associated_files_copied"], 2)

    def test_folder_export_appends_real_pdf_suffix_after_dotted_display_name(self) -> None:
        source = self.root / "source.pdf"
        source.write_bytes(b"%PDF fixture")

        filename = ui_server.library_item_export_filename(
            {
                "display_name": (
                    "04.Transmon02_Generating single microwave photons "
                    "in a circuit"
                )
            },
            source,
        )

        self.assertEqual(
            filename,
            "04.Transmon02_Generating single microwave photons in a circuit.pdf",
        )

    def test_inline_library_rename_updates_only_that_items_file_name(self) -> None:
        real_folder = self.storage.create_library_folder(parent_id=1, name="Real")
        shortcut_folder = self.storage.create_library_folder(parent_id=1, name="Shortcut")
        real_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(real_folder["id"]))
        shortcut_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(shortcut_folder["id"]))
        real_dir.mkdir(parents=True)
        source_pdf = real_dir / "source.pdf"
        source_pdf.write_bytes(b"%PDF fixture")
        self.storage.upsert_paper(
            {
                "paper_id": "inline-rename-paper",
                "doi": "10.1234/inline",
                "title": "Inline Rename Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "inline-rename-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        real_item = self.storage.add_library_item(
            paper_id="inline-rename-paper",
            folder_id=int(real_folder["id"]),
        )
        shortcut_item = self.storage.add_library_item(
            paper_id="inline-rename-paper",
            folder_id=int(shortcut_folder["id"]),
        )
        self.storage.rename_library_item(item_id=int(real_item["id"]), name="Real Name")
        self.storage.rename_library_item(item_id=int(shortcut_item["id"]), name="Old Shortcut")
        ui_server.sync_all_pdf_aliases_for_paper(self.storage, "inline-rename-paper")

        renamed, paper, _sync = ui_server.rename_library_item_and_sync_files(
            self.storage,
            item_id=int(shortcut_item["id"]),
            name="New Shortcut",
        )

        self.assertEqual(renamed["display_name"], "New Shortcut")
        self.assertEqual(Path(paper["merged_pdf_path"]).name, "Real Name.pdf")
        self.assertTrue((real_dir / "Real Name.pdf").exists())
        self.assertFalse((shortcut_dir / "Old Shortcut.pdf").exists())
        self.assertTrue(finder_alias.is_alias((shortcut_dir / "New Shortcut.pdf")))

    def test_shortcut_name_collision_is_numbered_without_overwrite(self) -> None:
        real_folder = self.storage.create_library_folder(parent_id=1, name="Real")
        shortcut_folder = self.storage.create_library_folder(parent_id=1, name="Shortcut")
        real_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(real_folder["id"]))
        shortcut_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(shortcut_folder["id"]))
        real_dir.mkdir(parents=True)
        shortcut_dir.mkdir(parents=True)
        occupied = shortcut_dir / "Shared Name.pdf"
        occupied.write_bytes(b"%PDF existing")
        source_pdf = real_dir / "source.pdf"
        source_pdf.write_bytes(b"%PDF fixture")
        self.storage.upsert_paper(
            {
                "paper_id": "collision-paper",
                "doi": "10.1234/collision",
                "title": "Collision Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "collision-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        real_item = self.storage.add_library_item(
            paper_id="collision-paper",
            folder_id=int(real_folder["id"]),
        )
        shortcut_item = self.storage.add_library_item(
            paper_id="collision-paper",
            folder_id=int(shortcut_folder["id"]),
        )
        self.storage.rename_library_item(item_id=int(real_item["id"]), name="Canonical")
        self.storage.rename_library_item(item_id=int(shortcut_item["id"]), name="Shared Name")

        ui_server.sync_all_pdf_aliases_for_paper(self.storage, "collision-paper")
        adjusted = self.storage.get_library_item(int(shortcut_item["id"])) or {}

        self.assertEqual(occupied.read_bytes(), b"%PDF existing")
        self.assertEqual(adjusted["display_name"], "Shared Name 2")
        self.assertTrue(finder_alias.is_alias((shortcut_dir / "Shared Name 2.pdf")))

    def test_shared_real_pdf_rename_updates_every_paper_path(self) -> None:
        folder = self.storage.create_library_folder(parent_id=1, name="Shared")
        target_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(folder["id"]))
        target_dir.mkdir(parents=True)
        source_pdf = target_dir / "old-shared.pdf"
        source_pdf.write_bytes(b"%PDF shared fixture")
        for paper_id in ("a-shared-paper", "b-shared-paper"):
            self.storage.upsert_paper(
                {
                    "paper_id": paper_id,
                    "doi": f"10.1234/{paper_id}",
                    "title": paper_id,
                    "journal": "Fixture Journal",
                    "publication_date": "2026-01-01",
                    "abstract": "",
                    "source": "test",
                    "type": "article",
                }
            )
            self.storage.update_download_status(
                paper_id,
                status="success",
                main_pdf_path=str(source_pdf),
                merged_pdf_path=str(source_pdf),
                supplement_pdf_paths=[],
            )
        owner = self.storage.add_library_item(
            paper_id="a-shared-paper",
            folder_id=int(folder["id"]),
        )
        self.storage.rename_library_item(item_id=int(owner["id"]), name="Shared Canonical Name")
        shortcut = self.storage.add_library_item(
            paper_id="b-shared-paper",
            folder_id=int(folder["id"]),
        )
        self.storage.rename_library_item(item_id=int(shortcut["id"]), name="Shared Shortcut Name")

        ui_server.sync_all_pdf_aliases_for_paper(self.storage, "a-shared-paper")
        first = self.storage.get_paper("a-shared-paper") or {}
        second = self.storage.get_paper("b-shared-paper") or {}
        renamed_path = target_dir / "Shared Canonical Name.pdf"
        shortcut_path = target_dir / "Shared Shortcut Name.pdf"

        self.assertTrue(renamed_path.exists())
        self.assertFalse(source_pdf.exists())
        self.assertTrue(finder_alias.is_alias(shortcut_path))
        self.assertEqual(finder_alias.resolve(shortcut_path), renamed_path.resolve())
        self.assertEqual(Path(first["merged_pdf_path"]).resolve(), renamed_path.resolve())
        self.assertEqual(Path(second["merged_pdf_path"]).resolve(), renamed_path.resolve())

    def test_delete_hands_pdf_to_earliest_remaining_non_recycle_link(self) -> None:
        folder_a = self.storage.create_library_folder(parent_id=1, name="A")
        folder_b = self.storage.create_library_folder(parent_id=1, name="B")
        folder_c = self.storage.create_library_folder(parent_id=1, name="C")
        dir_a = ui_server.local_copy_dir_for_library_folder(self.storage, int(folder_a["id"]))
        dir_b = ui_server.local_copy_dir_for_library_folder(self.storage, int(folder_b["id"]))
        dir_c = ui_server.local_copy_dir_for_library_folder(self.storage, int(folder_c["id"]))
        dir_a.mkdir(parents=True)
        source_pdf = dir_a / "paper.pdf"
        source_pdf.write_bytes(b"%PDF fixture")

        self.storage.upsert_paper(
            {
                "paper_id": "handoff-paper",
                "doi": "10.1234/handoff",
                "title": "Handoff Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "handoff-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        item_a = self.storage.add_library_item(paper_id="handoff-paper", folder_id=int(folder_a["id"]))
        item_b = self.storage.copy_library_item(item_id=int(item_a["id"]), folder_id=int(folder_b["id"]))
        item_c = self.storage.copy_library_item(item_id=int(item_a["id"]), folder_id=int(folder_c["id"]))
        ui_server.sync_alias_for_library_item(self.storage, "handoff-paper", int(folder_b["id"]))
        ui_server.sync_alias_for_library_item(self.storage, "handoff-paper", int(folder_c["id"]))

        result = ui_server.PaperMonitorUiHandler.delete_library_entry_in_storage(
            None,
            self.storage,
            "item",
            int(item_a["id"]),
        )
        paper = self.storage.get_paper("handoff-paper") or {}
        moved_path = Path(paper["merged_pdf_path"])

        self.assertEqual(result["mode"], "removed")
        self.assertEqual(int(result["moved"]["id"]), int(item_b["id"]))
        self.assertIsNone(self.storage.get_library_item(int(item_a["id"])))
        self.assertIsNotNone(self.storage.get_library_item(int(item_b["id"])))
        self.assertIsNotNone(self.storage.get_library_item(int(item_c["id"])))
        self.assertFalse(source_pdf.exists())
        self.assertEqual(moved_path.resolve(), (dir_b / "paper.pdf").resolve())
        self.assertTrue(moved_path.exists())
        self.assertFalse(moved_path.is_symlink())
        self.assertTrue(finder_alias.is_alias((dir_c / "paper.pdf")))

    def test_delete_moves_pdf_to_recycle_when_no_remaining_non_recycle_link(self) -> None:
        folder = self.storage.create_library_folder(parent_id=1, name="Only")
        source_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(folder["id"]))
        source_dir.mkdir(parents=True)
        source_pdf = source_dir / "paper.pdf"
        source_pdf.write_bytes(b"%PDF fixture")

        self.storage.upsert_paper(
            {
                "paper_id": "solo-paper",
                "doi": "10.1234/solo",
                "title": "Solo Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "solo-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        item = self.storage.add_library_item(paper_id="solo-paper", folder_id=int(folder["id"]))

        result = ui_server.PaperMonitorUiHandler.delete_library_entry_in_storage(
            None,
            self.storage,
            "item",
            int(item["id"]),
        )
        paper = self.storage.get_paper("solo-paper") or {}
        moved_path = Path(paper["merged_pdf_path"])

        self.assertEqual(result["mode"], "trashed")
        self.assertFalse(source_pdf.exists())
        self.assertTrue(moved_path.exists())
        self.assertIn("Recycle", moved_path.parts)
        self.assertEqual(
            Path(result["moved"]["paper"]["merged_pdf_path"]).resolve(),
            moved_path.resolve(),
        )

    def test_recover_moves_recycled_pdf_back_to_original_folder_and_returns_new_path(self) -> None:
        folder = self.storage.create_library_folder(parent_id=1, name="Original")
        source_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(folder["id"]))
        source_dir.mkdir(parents=True)
        source_pdf = source_dir / "recover.pdf"
        source_pdf.write_bytes(b"%PDF fixture")
        self.storage.upsert_paper(
            {
                "paper_id": "recover-paper",
                "doi": "10.1234/recover",
                "title": "Recover Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "recover-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        item = self.storage.add_library_item(paper_id="recover-paper", folder_id=int(folder["id"]))
        ui_server.PaperMonitorUiHandler.delete_library_entry_in_storage(
            None,
            self.storage,
            "item",
            int(item["id"]),
        )
        recycled_pdf = Path((self.storage.get_paper("recover-paper") or {})["merged_pdf_path"])
        self.assertTrue(recycled_pdf.exists())
        self.assertIn("Recycle", recycled_pdf.parts)

        recovered = ui_server.PaperMonitorUiHandler.recover_library_entry_in_storage(
            None,
            self.storage,
            "item",
            int(item["id"]),
        )
        restored_pdf = Path((self.storage.get_paper("recover-paper") or {})["merged_pdf_path"])

        self.assertEqual(int(recovered["folder_id"]), int(folder["id"]))
        self.assertEqual(Path(recovered["paper"]["merged_pdf_path"]).resolve(), restored_pdf.resolve())
        self.assertEqual(restored_pdf.parent.resolve(), source_dir.resolve())
        self.assertTrue(restored_pdf.exists())
        self.assertFalse(recycled_pdf.exists())

    def test_my_publication_counts_as_remaining_reference_on_library_delete(self) -> None:
        folder = self.storage.create_library_folder(parent_id=1, name="Library Only")
        source_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(folder["id"]))
        source_dir.mkdir(parents=True)
        source_pdf = source_dir / "publication.pdf"
        source_pdf.write_bytes(b"%PDF fixture")
        self.storage.upsert_paper(
            {
                "paper_id": "publication-paper",
                "doi": "10.1234/publication",
                "title": "Publication Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "publication-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        item = self.storage.add_library_item(paper_id="publication-paper", folder_id=int(folder["id"]))
        self.storage.add_my_publication(paper_id="publication-paper")

        result = ui_server.PaperMonitorUiHandler.delete_library_entry_in_storage(
            None,
            self.storage,
            "item",
            int(item["id"]),
        )
        paper = self.storage.get_paper("publication-paper") or {}
        retained_pdf = Path(paper["merged_pdf_path"])
        recycle_id = int(ui_server.ensure_library_special_folders(self.storage)["recycle"]["id"])

        self.assertEqual(result["mode"], "removed")
        self.assertTrue(result["retained_by_my_publications"])
        self.assertEqual(result["moved"], {})
        self.assertEqual(Path(result["paper"]["merged_pdf_path"]).resolve(), retained_pdf.resolve())
        self.assertIsNone(self.storage.get_library_item(int(item["id"])))
        self.assertEqual(
            self.storage.conn.execute(
                "SELECT COUNT(*) FROM library_items WHERE paper_id = ? AND folder_id = ?",
                ("publication-paper", recycle_id),
            ).fetchone()[0],
            0,
        )
        self.assertEqual(retained_pdf.parent.resolve(), ui_server.MY_PUBLICATIONS_LOCAL_COPY_ROOT.resolve())
        self.assertTrue(retained_pdf.exists())

    def test_permanent_recycle_delete_moves_pdf_before_removing_database_records(self) -> None:
        folder = self.storage.create_library_folder(parent_id=1, name="Only")
        source_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(folder["id"]))
        source_dir.mkdir(parents=True)
        source_pdf = source_dir / "permanent.pdf"
        source_pdf.write_bytes(b"%PDF fixture")
        self.storage.upsert_paper(
            {
                "paper_id": "permanent-paper",
                "doi": "10.1234/permanent",
                "title": "Permanent Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "permanent-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        item = self.storage.add_library_item(paper_id="permanent-paper", folder_id=int(folder["id"]))
        ui_server.PaperMonitorUiHandler.delete_library_entry_in_storage(
            None,
            self.storage,
            "item",
            int(item["id"]),
        )
        recycled_item = self.storage.get_library_item(int(item["id"])) or {}
        recycled_pdf = Path((self.storage.get_paper("permanent-paper") or {})["merged_pdf_path"])
        system_trash = self.root / "System Trash"
        system_trash.mkdir()

        def fake_system_trash(path: Path) -> Path:
            target = system_trash / path.name
            path.replace(target)
            return target

        with patch.object(ui_server, "move_path_to_macos_trash", side_effect=fake_system_trash):
            result = ui_server.PaperMonitorUiHandler.delete_library_entry_in_storage(
                None,
                self.storage,
                "item",
                int(recycled_item["id"]),
                confirmed=True,
            )

        self.assertEqual(result["mode"], "removed")
        self.assertEqual(result["cleanup"]["trashed_files"], [str(recycled_pdf.resolve())])
        self.assertFalse(recycled_pdf.exists())
        self.assertTrue((system_trash / recycled_pdf.name).exists())
        self.assertIsNone(self.storage.get_library_item(int(item["id"])))
        self.assertIsNone(self.storage.get_paper("permanent-paper"))

    def test_permanent_recycle_delete_keeps_records_when_macos_trash_fails(self) -> None:
        folder = self.storage.create_library_folder(parent_id=1, name="Only")
        source_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(folder["id"]))
        source_dir.mkdir(parents=True)
        source_pdf = source_dir / "protected.pdf"
        source_pdf.write_bytes(b"%PDF fixture")
        self.storage.upsert_paper(
            {
                "paper_id": "protected-paper",
                "doi": "10.1234/protected",
                "title": "Protected Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "protected-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        item = self.storage.add_library_item(paper_id="protected-paper", folder_id=int(folder["id"]))
        ui_server.PaperMonitorUiHandler.delete_library_entry_in_storage(
            None,
            self.storage,
            "item",
            int(item["id"]),
        )
        recycled_pdf = Path((self.storage.get_paper("protected-paper") or {})["merged_pdf_path"])

        with patch.object(
            ui_server,
            "move_path_to_macos_trash",
            side_effect=PermissionError("Finder Trash permission denied"),
        ):
            with self.assertRaises(PermissionError):
                ui_server.PaperMonitorUiHandler.delete_library_entry_in_storage(
                    None,
                    self.storage,
                    "item",
                    int(item["id"]),
                    confirmed=True,
                )

        self.assertIsNotNone(self.storage.get_library_item(int(item["id"])))
        self.assertIsNotNone(self.storage.get_paper("protected-paper"))
        self.assertTrue(recycled_pdf.exists())

    def test_recycle_orphan_detection_does_not_include_referenced_files(self) -> None:
        special = ui_server.ensure_library_special_folders(self.storage)
        recycle_id = int(special["recycle"]["id"])
        recycle_dir = ui_server.local_copy_dir_for_library_folder(self.storage, recycle_id)
        recycle_dir.mkdir(parents=True, exist_ok=True)
        referenced = recycle_dir / "referenced.pdf"
        orphan = recycle_dir / "orphan.pdf"
        referenced.write_bytes(b"%PDF referenced")
        orphan.write_bytes(b"%PDF orphan")
        self.storage.upsert_paper(
            {
                "paper_id": "referenced-paper",
                "doi": "10.1234/referenced",
                "title": "Referenced Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "referenced-paper",
            status="success",
            main_pdf_path=str(referenced),
            merged_pdf_path=str(referenced),
            supplement_pdf_paths=[],
        )

        paths = ui_server.library_recycle_orphan_paths(self.storage, recycle_id)

        self.assertEqual(paths, [orphan.resolve()])

    def test_macos_trash_uses_native_helper_and_returns_recoverable_destination(self) -> None:
        source = self.root / "system-trash.pdf"
        source.write_bytes(b"fixture")
        destination = self.root / "Finder Trash" / source.name
        def native_move(*args, **kwargs):
            destination.parent.mkdir()
            source.rename(destination)
            return CompletedProcess(args=args[0], returncode=0, stdout=f"{destination}\n", stderr="")
        with patch.object(ui_server.sys, "platform", "darwin"), patch.object(ui_server.subprocess, "run", side_effect=native_move) as run:
            result = ui_server.move_path_to_macos_trash(source)
        command = run.call_args.args[0]
        self.assertEqual(command[1:], ["--trash-item", str(source.resolve())])
        self.assertEqual(result, destination)
        self.assertEqual(result.read_bytes(), b"fixture")
        self.assertFalse(source.exists())

    def test_macos_trash_passes_dangling_link_without_following_it(self) -> None:
        source = self.root / "broken.pdf"
        source.symlink_to(self.root / "missing.pdf")
        destination = self.root / "trashed-link.pdf"
        def native_move(*args, **kwargs):
            source.rename(destination)
            return CompletedProcess(args=args[0], returncode=0, stdout=f"{destination}\n", stderr="")
        with patch.object(ui_server.sys, "platform", "darwin"), patch.object(ui_server.subprocess, "run", side_effect=native_move) as run:
            self.assertEqual(ui_server.move_path_to_macos_trash(source), destination)
        self.assertEqual(run.call_args.args[0][-1], str(source.parent.resolve() / source.name))
        self.assertTrue(destination.is_symlink())
        self.assertFalse(destination.exists())

    def test_macos_trash_still_raises_when_source_remains(self) -> None:
        source = self.root / "real-error.pdf"
        source.write_bytes(b"fixture")
        completed = CompletedProcess(args=[], returncode=1, stdout="", stderr="permission denied")
        with patch.object(ui_server.sys, "platform", "darwin"), patch.object(ui_server.subprocess, "run", return_value=completed):
            with self.assertRaises(PermissionError):
                ui_server.move_path_to_macos_trash(source)
        self.assertTrue(source.exists())

    def test_embedded_recycle_item_delete_uses_incremental_state_update(self) -> None:
        self.assertIn("function applyLocalLibraryDeleteResult(result)", ui_server.INDEX_HTML)
        self.assertIn("applyLocalLibraryDeleteResult(data.deleted);", ui_server.INDEX_HTML)
        self.assertIn('snapshot: false', ui_server.INDEX_HTML)
        self.assertIn("function updateLocalPaperReferences(paper)", ui_server.INDEX_HTML)
        self.assertIn("if (rawMoved?.paper) updateLocalPaperReferences(rawMoved.paper);", ui_server.INDEX_HTML)
        self.assertIn("else upsertLibraryFolderLocal(data.recovered);", ui_server.INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
