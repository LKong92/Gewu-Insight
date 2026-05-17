from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from paper_monitor.importers.inventory import build_inventory_from_folder, import_library_inventory
from paper_monitor.storage import Storage


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

    def test_dry_run_updates_existing_doi(self) -> None:
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
        self.assertEqual(result["updated_papers"], 1)
        self.assertEqual(result["papers_to_update"][0]["paper_id"], "doi_existing")

    def test_dry_run_updates_existing_arxiv(self) -> None:
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
        self.assertEqual(result["updated_papers"], 1)
        self.assertEqual(result["papers_to_update"][0]["paper_id"], "arxiv_2301.00001")

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
        self.assertEqual(result["created_papers"], 1)
        self.assertEqual(result["created_resources"], 1)
        paper = self.storage.conn.execute("SELECT * FROM papers WHERE doi = ?", ("10.7777/import",)).fetchone()
        self.assertIsNotNone(paper)
        self.assertEqual(paper["source_path"], str(pdf))
        self.assertEqual(paper["original_relative_path"], "papers/import-me.pdf")
        self.assertTrue(Path(paper["merged_pdf_path"]).exists())
        resource_count = self.storage.conn.execute("SELECT COUNT(*) AS c FROM resources WHERE kind = 'presentation'").fetchone()["c"]
        self.assertEqual(resource_count, 1)

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


if __name__ == "__main__":
    unittest.main()
