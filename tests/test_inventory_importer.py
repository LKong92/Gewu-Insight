from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfWriter

from paper_monitor.importers.inventory import build_inventory_from_folder, build_inventory_from_paths, doi_from_text, import_library_inventory
from paper_monitor.storage import Storage
from paper_monitor.ui_server import default_library_item_display_name


class InventoryImporterDryRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "paper_monitor.sqlite"
        self.storage = Storage(self.db_path)

    def tearDown(self) -> None:
        self.storage.close()
        self.tmp.cleanup()

    def write_inventory(self, records: list[dict]) -> Path:
        path = self.root / "library_inventory.json"
        path.write_text(
            json.dumps(
                {
                    "summary": {"root": str(self.root), "file_count": len(records)},
                    "directories": [],
                    "files": records,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return path

    def touch(self, relative_path: str, content: bytes = b"data") -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def write_text_pdf(self, relative_path: str, text: str) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1")
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
        xref += b"".join(f"{offset:010d} 00000 n \n".encode("ascii") for offset in offsets[1:])
        trailer = (
            f"trailer << /Root 1 0 R /Size {len(objects) + 1} >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
        path.write_bytes(body + xref + trailer)
        return path

    def run_dry(self, records: list[dict]) -> dict:
        report_path = self.root / "report.json"
        return import_library_inventory(
            self.write_inventory(records),
            storage=self.storage,
            dry_run=True,
            copy_mode="copy",
            preserve_folders=True,
            dedupe_by=("doi", "arxiv", "path"),
            report_path=report_path,
            target_root=self.root / "copied",
        )

    def pdf_record(self, path: Path, **overrides) -> dict:
        record = {
            "path": str(path),
            "relative_path": path.relative_to(self.root).as_posix(),
            "parent_relative_path": path.parent.relative_to(self.root).as_posix() if path.parent != self.root else "",
            "filename": path.name,
            "extension": ".pdf",
            "kind": "pdf",
            "mime_type": "application/pdf",
            "import_as": "paper_candidate",
            "size_bytes": path.stat().st_size if path.exists() else 123,
            "modified_at": "2026-01-01T00:00:00+08:00",
            "doi": "",
            "doi_source": None,
            "arxiv_id": None,
            "title": "Fixture Paper",
            "authors": [],
            "page_count": 1,
            "parse_status": "parsed",
            "parse_error": None,
        }
        record.update(overrides)
        return record

    def test_dry_run_counts_created_and_doi_duplicates(self) -> None:
        first = self.touch("a/first.pdf")
        second = self.touch("b/second.pdf")
        result = self.run_dry(
            [
                self.pdf_record(first, doi="10.1234/example"),
                self.pdf_record(second, doi="https://doi.org/10.1234/example"),
            ]
        )

        self.assertEqual(result["created_papers"], 1)
        self.assertEqual(result["updated_papers"], 0)
        self.assertEqual(result["doi_duplicates"], 1)
        self.assertEqual(result["duplicate_paper_candidates"], 1)
        self.assertEqual(result["pdf_attachments_to_import"], 1)

    def test_dry_run_leaves_existing_doi_unchanged(self) -> None:
        self.storage.upsert_paper(
            {
                "paper_id": "doi_existing",
                "doi": "10.5555/existing",
                "title": "Existing",
                "journal": "Imported Library",
                "publication_date": "",
                "source": "inventory",
                "section_allowed": True,
                "raw": {},
            }
        )
        path = self.touch("existing.pdf")
        result = self.run_dry([self.pdf_record(path, doi="10.5555/existing")])

        self.assertEqual(result["created_papers"], 0)
        self.assertEqual(result["updated_papers"], 0)
        self.assertEqual(result["existing_papers"], 1)
        self.assertEqual(result["papers_existing"][0]["paper_id"], "doi_existing")

    def test_dry_run_leaves_existing_arxiv_unchanged(self) -> None:
        self.storage.upsert_paper(
            {
                "paper_id": "arxiv_2301.00001",
                "doi": "",
                "title": "Existing arXiv",
                "journal": "arXiv",
                "publication_date": "",
                "source": "arxiv",
                "section_allowed": True,
                "raw": {"arxiv_id": "2301.00001"},
            }
        )
        path = self.touch("arxiv.pdf")
        result = self.run_dry([self.pdf_record(path, arxiv_id="2301.00001v2")])

        self.assertEqual(result["created_papers"], 0)
        self.assertEqual(result["updated_papers"], 0)
        self.assertEqual(result["existing_papers"], 1)
        self.assertEqual(result["papers_existing"][0]["paper_id"], "arxiv_2301.00001")

    def test_pdf_without_doi_or_arxiv_uses_source_path_identity(self) -> None:
        path = self.touch("folder/plain-name.pdf", b"%PDF fixture")
        inventory_path = self.write_inventory([self.pdf_record(path, title="", doi="", arxiv_id=None)])
        result = import_library_inventory(
            inventory_path,
            storage=self.storage,
            dry_run=False,
            copy_mode="copy",
            preserve_folders=True,
            dedupe_by=("doi", "arxiv", "path"),
            report_path=self.root / "path-report.json",
            target_root=self.root / "copied",
            library_item_name="filename",
        )

        self.assertFalse(result["errors"])
        self.assertEqual(result["created_papers"], 1)
        row = self.storage.conn.execute(
            """
            SELECT papers.paper_id, library_items.display_name
            FROM papers
            JOIN library_items ON library_items.paper_id = papers.paper_id
            WHERE papers.source_path = ?
            """,
            (str(path),),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["display_name"], "plain-name.pdf")

    def test_placeholder_pdf_metadata_title_falls_back_to_filename(self) -> None:
        scan_root = self.root / "placeholder-metadata"
        pdf = scan_root / "topic" / "actual-paper-name.pdf"
        pdf.parent.mkdir(parents=True)
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        writer.add_metadata({"/Title": "Unknown Imported Library"})
        with pdf.open("wb") as handle:
            writer.write(handle)

        inventory = build_inventory_from_folder(scan_root)
        record = inventory["files"][0]

        self.assertEqual(record["title"], "actual-paper-name.pdf")
        result = import_library_inventory(
            self.write_inventory([record]),
            storage=self.storage,
            dry_run=False,
            copy_mode="copy",
            preserve_folders=True,
            dedupe_by=("doi", "arxiv", "path"),
            report_path=self.root / "placeholder-report.json",
            target_root=self.root / "copied",
            library_item_name="filename",
        )
        self.assertFalse(result["errors"])
        row = self.storage.conn.execute(
            """
            SELECT papers.title, library_items.display_name
            FROM papers
            JOIN library_items ON library_items.paper_id = papers.paper_id
            WHERE papers.source_path = ?
            """,
            (str(pdf.resolve()),),
        ).fetchone()
        self.assertEqual(row["title"], "Actual-paper-name.pdf")
        self.assertEqual(row["display_name"], "actual-paper-name.pdf")

    def test_metadata_refresh_does_not_replace_title_with_placeholder(self) -> None:
        self.storage.upsert_paper(
            {
                "paper_id": "local-file",
                "doi": "",
                "title": "meaningful-file-name.pdf",
                "journal": "Imported Library",
                "publication_date": "",
                "abstract": "",
                "abstract_source": "inventory",
                "url": "",
                "landing_url": "",
                "pdf_url": "",
                "source": "inventory",
                "type": "imported_pdf",
                "type_crossref": "",
                "publisher_section": "imported",
                "section_allowed": True,
                "raw": {},
            }
        )

        refreshed = self.storage.refresh_paper_metadata(
            "local-file",
            {
                "title": "Unknown Imported Library",
                "journal": "Imported Library",
                "raw": {},
            },
        )

        self.assertEqual(refreshed["title"], "Meaningful-file-name.pdf")

    def test_default_library_item_name_skips_generic_imported_citation(self) -> None:
        name = default_library_item_display_name(
            {
                "title": "Unknown Imported Library",
                "journal": "Imported Library",
                "original_filename": "real-file-name.pdf",
            }
        )

        self.assertEqual(name, "real-file-name.pdf")

    def test_repeated_real_import_leaves_existing_records_and_labels_unchanged(self) -> None:
        pdf = self.touch("repeat/reuse-me.pdf", b"%PDF fixture")
        inventory_path = self.write_inventory([self.pdf_record(pdf, doi="10.4242/reuse", title="Reuse Me")])
        copied_root = self.root / "copied"
        first = import_library_inventory(
            inventory_path,
            storage=self.storage,
            dry_run=False,
            copy_mode="copy",
            preserve_folders=True,
            dedupe_by=("doi", "arxiv", "path"),
            report_path=self.root / "first-report.json",
            target_root=copied_root,
            library_item_name="filename",
        )
        row = self.storage.conn.execute(
            """
            SELECT library_items.id
            FROM library_items
            JOIN papers ON papers.paper_id = library_items.paper_id
            WHERE papers.doi = ?
            """,
            ("10.4242/reuse",),
        ).fetchone()
        self.assertIsNotNone(row)
        self.storage.rename_library_item(item_id=int(row["id"]), name="Custom reuse label")
        second = import_library_inventory(
            inventory_path,
            storage=self.storage,
            dry_run=False,
            copy_mode="copy",
            preserve_folders=True,
            dedupe_by=("doi", "arxiv", "path"),
            report_path=self.root / "second-report.json",
            target_root=copied_root,
            library_item_name="filename",
        )

        self.assertFalse(first["errors"])
        self.assertFalse(second["errors"])
        self.assertEqual(second["updated_papers"], 0)
        self.assertEqual(second["existing_papers"], 1)
        self.assertEqual(len(first["metadata_refresh_candidates"]), 1)
        self.assertEqual(first["metadata_refresh_candidates"][0]["doi"], "10.4242/reuse")
        self.assertEqual(second["metadata_refresh_candidates"], [])
        self.assertEqual(second["reused_existing_files"], 1)
        self.assertEqual(len(list(copied_root.rglob("reuse-me.pdf"))), 1)
        label = self.storage.conn.execute("SELECT display_name FROM library_items WHERE id = ?", (int(row["id"]),)).fetchone()
        self.assertEqual(label["display_name"], "Custom reuse label")

    def test_real_import_preserves_path_whitespace(self) -> None:
        pdf = self.touch("topic  with  spaces/paper  double  space.pdf", b"%PDF fixture")
        result = import_library_inventory(
            self.write_inventory([self.pdf_record(pdf, doi="10.4242/path-space", title="Path Space")]),
            storage=self.storage,
            dry_run=False,
            copy_mode="copy",
            preserve_folders=True,
            dedupe_by=("doi", "arxiv", "path"),
            report_path=self.root / "space-report.json",
            target_root=self.root / "copied",
            library_item_name="filename",
        )

        self.assertFalse(result["errors"])
        self.assertEqual(result["missing_source_files"], 0)
        self.assertTrue((self.root / "copied/topic  with  spaces/paper  double  space.pdf").exists())
        paper = self.storage.conn.execute("SELECT * FROM papers WHERE doi = ?", ("10.4242/path-space",)).fetchone()
        self.assertIsNotNone(paper)
        self.assertEqual(paper["source_path"], str(pdf))
        self.assertEqual(paper["original_relative_path"], "topic  with  spaces/paper  double  space.pdf")

    def test_real_import_preserves_source_root_and_report_path_for_reuse(self) -> None:
        source_root = self.root / "source  folder"
        source_root.mkdir()
        pdf = source_root / "paper.pdf"
        pdf.write_bytes(b"%PDF fixture")
        inventory_path = self.root / "inventory-source-root.json"
        report_path = self.root / "report-source-root.json"
        inventory_path.write_text(
            json.dumps(
                {
                    "summary": {"root": str(source_root), "file_count": 1},
                    "directories": [],
                    "files": [self.pdf_record(pdf, doi="10.4242/source-root", title="Source Root")],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        result = import_library_inventory(
            inventory_path,
            storage=self.storage,
            dry_run=False,
            copy_mode="copy",
            preserve_folders=True,
            dedupe_by=("doi", "arxiv", "path"),
            report_path=report_path,
            target_root=self.root / "copied  root",
            library_item_name="filename",
        )

        self.assertFalse(result["errors"])
        batch = self.storage.conn.execute(
            "SELECT source_root, report_path FROM inventory_import_batches WHERE id = ?",
            (result["import_batch_id"],),
        ).fetchone()
        self.assertIsNotNone(batch)
        self.assertEqual(batch["source_root"], str(source_root))
        self.assertEqual(batch["report_path"], str(report_path))

    def test_repeated_import_adds_newly_seen_non_pdf_without_touching_existing_pdf(self) -> None:
        pdf = self.touch("topic/paper.pdf", b"%PDF fixture")
        slide = self.touch("topic/slides.pptx", b"ppt")
        copied_root = self.root / "copied"
        first_inventory = self.write_inventory([self.pdf_record(pdf, doi="10.4242/supplement", title="Existing PDF")])
        first = import_library_inventory(
            first_inventory,
            storage=self.storage,
            dry_run=False,
            copy_mode="copy",
            preserve_folders=True,
            dedupe_by=("doi", "arxiv", "path"),
            report_path=self.root / "first-non-pdf-report.json",
            target_root=copied_root,
            library_item_name="filename",
        )
        self.assertFalse(first["errors"])
        row = self.storage.conn.execute(
            """
            SELECT library_items.id
            FROM library_items
            JOIN papers ON papers.paper_id = library_items.paper_id
            WHERE papers.doi = ?
            """,
            ("10.4242/supplement",),
        ).fetchone()
        self.assertIsNotNone(row)
        self.storage.rename_library_item(item_id=int(row["id"]), name="Edited PDF label")

        second_inventory = self.write_inventory(
            [
                self.pdf_record(pdf, doi="10.4242/supplement", title="Existing PDF"),
                {
                    "path": str(slide),
                    "relative_path": "topic/slides.pptx",
                    "parent_relative_path": "topic",
                    "filename": "slides.pptx",
                    "extension": ".pptx",
                    "kind": "presentation",
                    "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    "import_as": "resource",
                    "size_bytes": slide.stat().st_size,
                    "modified_at": "2026-01-01T00:00:00+08:00",
                },
            ]
        )
        second = import_library_inventory(
            second_inventory,
            storage=self.storage,
            dry_run=False,
            copy_mode="copy",
            preserve_folders=True,
            dedupe_by=("doi", "arxiv", "path"),
            report_path=self.root / "second-non-pdf-report.json",
            target_root=copied_root,
            library_item_name="filename",
        )

        self.assertFalse(second["errors"])
        self.assertEqual(second["existing_papers"], 1)
        self.assertEqual(second["created_papers"], 1)
        self.assertEqual(second["created_resources"], 1)
        pdf_label = self.storage.conn.execute("SELECT display_name FROM library_items WHERE id = ?", (int(row["id"]),)).fetchone()
        self.assertEqual(pdf_label["display_name"], "Edited PDF label")
        resource = self.storage.conn.execute("SELECT * FROM papers WHERE original_filename = 'slides.pptx'").fetchone()
        self.assertIsNotNone(resource)

    def test_dry_run_counts_resource_import(self) -> None:
        resource = self.touch("slides/talk.pptx")
        result = self.run_dry(
            [
                {
                    "path": str(resource),
                    "relative_path": "slides/talk.pptx",
                    "parent_relative_path": "slides",
                    "filename": "talk.pptx",
                    "extension": ".pptx",
                    "kind": "presentation",
                    "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    "import_as": "resource",
                    "size_bytes": resource.stat().st_size,
                    "modified_at": "2026-01-01T00:00:00+08:00",
                }
            ]
        )

        self.assertEqual(result["created_resources"], 1)
        self.assertEqual(result["resources_or_attachments_to_import"], 1)

    def test_dry_run_skips_system_metadata_and_alias(self) -> None:
        ds_store = self.touch(".DS_Store")
        alias = self.touch("old paper alias")
        result = self.run_dry(
            [
                {
                    "path": str(ds_store),
                    "relative_path": ".DS_Store",
                    "parent_relative_path": "",
                    "filename": ".DS_Store",
                    "kind": "system_metadata",
                    "import_as": "ignore_candidate",
                    "size_bytes": ds_store.stat().st_size,
                },
                {
                    "path": str(alias),
                    "relative_path": "old paper alias",
                    "parent_relative_path": "",
                    "filename": "old paper alias",
                    "kind": "mac_alias",
                    "import_as": "alias_reference",
                    "size_bytes": alias.stat().st_size,
                },
            ]
        )

        self.assertEqual(result["skipped_system_metadata"], 1)
        self.assertEqual(result["mac_aliases_found"], 1)
        self.assertEqual(result["skipped"], 2)

    def test_dry_run_warns_missing_source_path(self) -> None:
        missing = self.root / "missing.pdf"
        result = self.run_dry([self.pdf_record(missing, doi="10.9999/missing")])

        self.assertEqual(result["missing_source_files"], 1)
        self.assertTrue(any("Missing source file" in warning for warning in result["warnings"]))
        self.assertEqual(result["pdf_attachments_to_import"], 0)

    def test_real_import_copies_pdf_and_resource_rows(self) -> None:
        pdf = self.touch("papers/import-me.pdf", b"%PDF fixture")
        slide = self.touch("slides/talk.pptx", b"ppt")
        inventory_path = self.write_inventory(
            [
                self.pdf_record(pdf, doi="10.7777/import", title="Import Me"),
                {
                    "path": str(slide),
                    "relative_path": "slides/talk.pptx",
                    "parent_relative_path": "slides",
                    "filename": "talk.pptx",
                    "extension": ".pptx",
                    "kind": "presentation",
                    "mime_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    "import_as": "resource",
                    "size_bytes": slide.stat().st_size,
                    "modified_at": "2026-01-01T00:00:00+08:00",
                },
            ]
        )
        result = import_library_inventory(
            inventory_path,
            storage=self.storage,
            dry_run=False,
            copy_mode="copy",
            preserve_folders=True,
            dedupe_by=("doi", "arxiv", "path"),
            report_path=self.root / "real-report.json",
            target_root=self.root / "copied",
        )

        self.assertFalse(result["errors"])
        self.assertEqual(result["created_papers"], 2)
        self.assertEqual(result["created_resources"], 1)
        paper = self.storage.conn.execute("SELECT * FROM papers WHERE doi = ?", ("10.7777/import",)).fetchone()
        self.assertIsNotNone(paper)
        self.assertEqual(paper["source_path"], str(pdf))
        self.assertEqual(paper["original_relative_path"], "papers/import-me.pdf")
        self.assertTrue(Path(paper["merged_pdf_path"]).exists())
        resource_count = self.storage.conn.execute("SELECT COUNT(*) AS c FROM resources WHERE kind = 'presentation'").fetchone()["c"]
        self.assertEqual(resource_count, 1)

    def test_loader_match_never_replaces_an_existing_primary_pdf(self) -> None:
        published = self.touch("library/Published.pdf", b"%PDF-1.4\npublished\n%%EOF\n")
        preprint = self.touch("incoming/2401.01234v1.pdf", b"%PDF-1.4\npreprint\n%%EOF\n")
        self.storage.upsert_paper(
            {
                "paper_id": "doi_loader_preserve_primary",
                "doi": "10.7777/preserve-primary",
                "title": "Preserve Published Version",
                "journal": "Fixture Journal",
                "source": "test",
                "raw": {},
            }
        )
        self.storage.update_download_status(
            "doi_loader_preserve_primary",
            status="success",
            main_pdf_path=str(published),
            merged_pdf_path=str(published),
        )
        result = import_library_inventory(
            self.write_inventory(
                [
                    self.pdf_record(
                        preprint,
                        doi="10.7777/preserve-primary",
                        arxiv_id="2401.01234",
                        title="Preserve Published Version",
                    )
                ]
            ),
            storage=self.storage,
            dry_run=False,
            copy_mode="copy",
            preserve_folders=True,
            dedupe_by=("doi", "arxiv", "path"),
            report_path=self.root / "preserve-report.json",
            target_root=self.root / "copied",
        )

        self.assertFalse(result["errors"])
        paper = self.storage.get_paper("doi_loader_preserve_primary")
        self.assertEqual(Path(paper["merged_pdf_path"]), published)
        self.assertEqual(published.read_bytes(), b"%PDF-1.4\npublished\n%%EOF\n")
        imported = self.storage.conn.execute(
            "SELECT stored_path FROM resources WHERE paper_id = ? AND source_path = ?",
            ("doi_loader_preserve_primary", str(preprint)),
        ).fetchone()
        self.assertIsNotNone(imported)
        self.assertEqual(Path(imported["stored_path"]).read_bytes(), b"%PDF-1.4\npreprint\n%%EOF\n")

    def test_build_inventory_from_folder_scans_pdf_resource_and_metadata(self) -> None:
        scan_root = self.root / "scan"
        scan_root.mkdir()
        pdf = scan_root / "topic/example.pdf"
        pdf.parent.mkdir()
        pdf.write_bytes(b"%PDF fixture")
        ppt = scan_root / "topic/slides.pptx"
        ppt.write_bytes(b"ppt")
        ds_store = scan_root / ".DS_Store"
        ds_store.write_bytes(b"meta")
        inventory = build_inventory_from_folder(scan_root, output_path=self.root / "built.json")

        records = {item["relative_path"]: item for item in inventory["files"]}
        self.assertEqual(records[pdf.relative_to(scan_root).as_posix()]["kind"], "pdf")
        self.assertEqual(records[pdf.relative_to(scan_root).as_posix()]["import_as"], "paper_candidate")
        self.assertEqual(records[ppt.relative_to(scan_root).as_posix()]["kind"], "presentation")
        self.assertEqual(records[ppt.relative_to(scan_root).as_posix()]["import_as"], "resource")
        self.assertEqual(records[ds_store.relative_to(scan_root).as_posix()]["kind"], "system_metadata")
        self.assertEqual(inventory["summary"]["file_count"], 3)

    def test_build_inventory_from_folder_can_skip_pdf_body_parsing(self) -> None:
        scan_root = self.root / "quick-scan"
        scan_root.mkdir()
        pdf = scan_root / "topic" / "10.1234_example.pdf"
        pdf.parent.mkdir()
        pdf.write_bytes(b"not actually a pdf")

        inventory = build_inventory_from_folder(scan_root, parse_pdfs=False)

        record = inventory["files"][0]
        self.assertEqual(record["kind"], "pdf")
        self.assertEqual(record["parse_status"], "not_parsed")
        self.assertEqual(record["doi"], "10.1234/example")

    def test_build_inventory_reads_pdf_front_matter_for_doi_by_default(self) -> None:
        scan_root = self.root / "front-matter-scan"
        pdf = self.write_text_pdf(
            "front-matter-scan/topic/title-page.pdf",
            "Title page DOI 10.1234/frontmatter.test",
        )
        events: list[dict] = []

        inventory = build_inventory_from_folder(scan_root, progress_callback=events.append)

        records = {item["relative_path"]: item for item in inventory["files"]}
        record = records[pdf.relative_to(scan_root).as_posix()]
        self.assertEqual(record["doi"], "10.1234/frontmatter.test")
        self.assertEqual(record["doi_source"], "pdf_text_pypdf")
        self.assertEqual(inventory["summary"]["pdf_doi_extracted_count"], 1)
        self.assertEqual(inventory["summary"]["pdf_doi_missing_count"], 0)
        self.assertTrue(
            any("Reading first PDF page for DOI" in str(event.get("message") or "") for event in events)
        )
        self.assertTrue(
            any("DOI extracted: 10.1234/frontmatter.test" in str(event.get("message") or "") for event in events)
        )

    def test_doi_extraction_removes_space_after_slash(self) -> None:
        self.assertEqual(
            doi_from_text("https://doi.org/10.1038/\ns42254-019-0038-2"),
            "10.1038/s42254-019-0038-2",
        )

    def test_build_inventory_reports_pdfs_without_doi(self) -> None:
        scan_root = self.root / "missing-doi-scan"
        pdf = self.write_text_pdf("missing-doi-scan/topic/no-doi.pdf", "Title page without identifier")
        inventory_path = self.root / "missing-doi-inventory.json"
        events: list[dict] = []

        inventory = build_inventory_from_folder(scan_root, output_path=inventory_path, progress_callback=events.append)

        self.assertEqual(inventory["summary"]["pdf_doi_extracted_count"], 0)
        self.assertEqual(inventory["summary"]["pdf_doi_missing_count"], 1)
        self.assertEqual(inventory["summary"]["pdfs_without_doi"][0]["relative_path"], pdf.relative_to(scan_root).as_posix())
        self.assertTrue(
            any("No DOI extracted from first PDF page" in str(event.get("message") or "") for event in events)
        )

        result = import_library_inventory(
            inventory_path,
            storage=self.storage,
            dry_run=False,
            copy_mode="copy",
            preserve_folders=True,
            dedupe_by=("doi", "arxiv", "path"),
            report_path=self.root / "missing-doi-report.json",
            target_root=self.root / "copied",
        )
        self.assertEqual(result["pdf_doi_extracted_count"], 0)
        self.assertEqual(result["pdf_doi_missing_count"], 1)
        self.assertEqual(result["pdfs_without_doi"][0]["relative_path"], pdf.relative_to(scan_root).as_posix())
        self.assertEqual(len(result["metadata_refresh_candidates"]), 1)
        self.assertEqual(result["metadata_refresh_candidates"][0]["doi"], "")
        self.assertEqual(
            Path(result["metadata_refresh_candidates"][0]["source_path"]).resolve(),
            pdf.resolve(),
        )

    def test_folder_import_can_name_library_shortcut_by_filename(self) -> None:
        pdf = self.touch("topic/original-name.pdf", b"%PDF fixture")
        inventory_path = self.write_inventory([self.pdf_record(pdf, doi="10.8888/name", title="Named Paper")])
        result = import_library_inventory(
            inventory_path,
            storage=self.storage,
            dry_run=False,
            copy_mode="copy",
            preserve_folders=True,
            dedupe_by=("doi", "arxiv", "path"),
            report_path=self.root / "filename-report.json",
            target_root=self.root / "copied",
            library_item_name="filename",
        )

        self.assertFalse(result["errors"])
        row = self.storage.conn.execute(
            """
            SELECT library_items.display_name
            FROM library_items
            JOIN papers ON papers.paper_id = library_items.paper_id
            WHERE papers.doi = ?
            """,
            ("10.8888/name",),
        ).fetchone()
        self.assertEqual(row["display_name"], "original-name.pdf")

    def test_dropped_folder_imports_under_selected_library_folder(self) -> None:
        target = self.storage.create_library_folder(parent_id=1, name="Target")
        pdf = self.touch("dropped-topic/inside.pdf", b"%PDF fixture")
        inventory_path = self.root / "dropped-inventory.json"
        build_inventory_from_paths([self.root / "dropped-topic"], output_path=inventory_path, parse_pdfs=False, preserve_top_level=True)

        result = import_library_inventory(
            inventory_path,
            storage=self.storage,
            dry_run=False,
            copy_mode="copy",
            preserve_folders=True,
            dedupe_by=("doi", "arxiv", "path"),
            report_path=self.root / "dropped-report.json",
            target_root=self.root / "copied",
            library_item_name="filename",
            library_root_folder_id=int(target["id"]),
        )

        self.assertFalse(result["errors"])
        row = self.storage.conn.execute(
            """
            SELECT parent.name AS parent_name, parent.parent_id AS parent_parent_id, library_items.display_name
            FROM library_items
            JOIN library_folders AS parent ON parent.id = library_items.folder_id
            JOIN papers ON papers.paper_id = library_items.paper_id
            WHERE papers.source_path = ?
            """,
            (str(pdf.resolve()),),
        ).fetchone()
        self.assertEqual(row["parent_name"], "dropped-topic")
        self.assertEqual(row["parent_parent_id"], int(target["id"]))
        self.assertEqual(row["display_name"], "inside.pdf")
        resource = self.storage.conn.execute(
            "SELECT stored_path FROM resources WHERE source_path = ?",
            (str(pdf.resolve()),),
        ).fetchone()
        self.assertEqual(Path(resource["stored_path"]), self.root / "copied" / "dropped-topic" / "inside.pdf")

    def test_dropped_file_import_uses_file_basename_under_target_root(self) -> None:
        pdf = self.touch("external-folder/solo.pdf", b"%PDF fixture")
        inventory_path = self.root / "dropped-file-inventory.json"
        build_inventory_from_paths([pdf], output_path=inventory_path, parse_pdfs=False, preserve_top_level=True)
        data = json.loads(inventory_path.read_text(encoding="utf-8"))

        self.assertEqual(data["files"][0]["relative_path"], "solo.pdf")

        result = import_library_inventory(
            inventory_path,
            storage=self.storage,
            dry_run=False,
            copy_mode="copy",
            preserve_folders=True,
            dedupe_by=("doi", "arxiv", "path"),
            report_path=self.root / "dropped-file-report.json",
            target_root=self.root / "copied-target",
            library_item_name="filename",
            library_root_folder_id=1,
        )

        self.assertFalse(result["errors"])
        resource = self.storage.conn.execute(
            "SELECT stored_path FROM resources WHERE source_path = ?",
            (str(pdf.resolve()),),
        ).fetchone()
        self.assertEqual(Path(resource["stored_path"]), self.root / "copied-target" / "solo.pdf")


if __name__ == "__main__":
    unittest.main()
