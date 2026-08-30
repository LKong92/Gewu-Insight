from __future__ import annotations

import sqlite3
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Text

from paper_monitor import ui_server
from paper_monitor.storage import PAPER_FILE_TYPES, STORAGE_SCHEMA_VERSION, Storage


def pdf_bytes(*, annotation: bool = False) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    if annotation:
        writer.add_annotation(
            page_number=0,
            annotation=Text(rect=(72, 700, 96, 724), text="reader note"),
        )
    writer.write(output)
    return output.getvalue()


class PaperFilesVNextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "paper_monitor.sqlite"
        self.associated_root = self.root / "Associated Files"
        self.patches = [
            patch.object(ui_server, "ASSOCIATED_FILES_ROOT", self.associated_root),
            patch.object(ui_server, "LIBRARY_LOCAL_COPY_ROOT", self.root / "Library"),
            patch.object(ui_server, "SPACES_LOCAL_COPY_ROOT", self.root / "Spaces"),
            patch.object(ui_server, "MY_PUBLICATIONS_LOCAL_COPY_ROOT", self.root / "My Publications"),
        ]
        for active in self.patches:
            active.start()
        self.storage = Storage(self.db_path)

    def tearDown(self) -> None:
        self.storage.close()
        for active in reversed(self.patches):
            active.stop()
        self.tmp.cleanup()

    def add_paper(self, paper_id: str = "paper") -> None:
        self.storage.upsert_paper(
            {
                "paper_id": paper_id,
                "doi": "10.1000/example",
                "title": "A stable condensed matter paper",
                "journal": "Physical Review B",
                "source": "fixture",
                "raw": {"authors": ["A. Author"]},
            }
        )

    def add_resource(self, paper_id: str, name: str, file_type: str) -> dict:
        path = self.root / name
        path.write_bytes(pdf_bytes())
        return self.storage.create_paper_resource(
            paper_id=paper_id,
            stored_path=str(path),
            file_type=file_type,
            file_source="user_import",
            annotation_state="unannotated",
        )

    def test_schema14_backfills_flat_metadata_and_manual_default_without_moving_files(self) -> None:
        self.add_paper("migration")
        path = self.root / "legacy-preprint.pdf"
        path.write_bytes(pdf_bytes(annotation=True))
        resource = self.storage.create_paper_resource(
            paper_id="migration",
            stored_path=str(path),
            file_role="publication_version",
            version_role="preprint",
            source_url="https://arxiv.org/pdf/2401.00001",
            annotation_count=1,
            is_annotated=True,
        )
        self.storage.conn.execute(
            "UPDATE resources SET file_type='unknown', file_source='unknown', annotation_state='unknown' WHERE id=?",
            (int(resource["id"]),),
        )
        self.storage.conn.execute(
            "UPDATE papers SET preferred_resource_id=?, preferred_resource_manual=0 WHERE paper_id='migration'",
            (int(resource["id"]),),
        )
        self.storage.conn.execute("PRAGMA user_version = 13")
        before = path.read_bytes()
        self.storage.conn.commit()
        self.storage.close()

        self.storage = Storage(self.db_path)
        migrated = self.storage.list_paper_resources("migration")[0]
        paper = self.storage.get_paper("migration")
        self.assertEqual(STORAGE_SCHEMA_VERSION, 14)
        self.assertEqual(migrated["file_type"], "preprint")
        self.assertEqual(migrated["file_source"], "preprint_server")
        self.assertEqual(migrated["annotation_state"], "annotated")
        self.assertTrue(int(paper["preferred_resource_manual"] or 0))
        self.assertEqual(path.read_bytes(), before)

    def test_schema13_without_vnext_columns_adds_columns_before_dependent_indexes(self) -> None:
        self.storage.close()
        legacy = sqlite3.connect(self.db_path)
        try:
            legacy.execute("DROP INDEX idx_resources_paper_file_type")
            for column in (
                "file_type",
                "file_source",
                "source_detail",
                "annotation_state",
                "file_type_override",
                "annotation_override",
            ):
                legacy.execute(f"ALTER TABLE resources DROP COLUMN {column}")
            legacy.execute("ALTER TABLE papers DROP COLUMN preferred_resource_manual")
            legacy.execute("PRAGMA user_version = 13")
            legacy.commit()
        finally:
            legacy.close()

        self.storage = Storage(self.db_path)
        resource_columns = {
            row["name"] for row in self.storage.conn.execute("PRAGMA table_info(resources)")
        }
        paper_columns = {
            row["name"] for row in self.storage.conn.execute("PRAGMA table_info(papers)")
        }
        indexes = {
            row["name"]
            for row in self.storage.conn.execute("PRAGMA index_list(resources)")
        }
        self.assertEqual(int(self.storage.conn.execute("PRAGMA user_version").fetchone()[0]), 14)
        self.assertTrue(
            {
                "file_type",
                "file_source",
                "source_detail",
                "annotation_state",
                "file_type_override",
                "annotation_override",
            }.issubset(resource_columns)
        )
        self.assertIn("preferred_resource_manual", paper_columns)
        self.assertIn("idx_resources_paper_file_type", indexes)

    def test_automatic_priority_and_manual_default_are_independent_of_physical_primary(self) -> None:
        self.add_paper("priority")
        preprint = self.add_resource("priority", "preprint.pdf", "preprint")
        accepted = self.add_resource("priority", "accepted.pdf", "accepted_manuscript")
        published = self.add_resource("priority", "published.pdf", "published_version")
        corrected = self.add_resource("priority", "corrected.pdf", "corrected_published_version")
        correction = self.add_resource("priority", "correction.pdf", "correction_notice")

        self.assertEqual(
            int(self.storage.resolve_default_paper_resource("priority")["id"]),
            int(corrected["id"]),
        )
        self.storage.set_preferred_paper_resource("priority", int(preprint["id"]))
        self.assertEqual(
            int(self.storage.resolve_default_paper_resource("priority")["id"]),
            int(preprint["id"]),
        )
        self.storage.resolve_primary_paper_resource("priority")
        self.assertEqual(
            int(self.storage.resolve_default_paper_resource("priority")["id"]),
            int(preprint["id"]),
        )
        self.storage.set_preferred_paper_resource("priority", None)
        self.assertEqual(
            int(self.storage.resolve_default_paper_resource("priority")["id"]),
            int(corrected["id"]),
        )
        self.assertNotEqual(int(correction["id"]), int(corrected["id"]))
        self.assertEqual({preprint["file_type"], accepted["file_type"], published["file_type"], corrected["file_type"]}, {
            "preprint", "accepted_manuscript", "published_version", "corrected_published_version"
        })

    def test_type_annotation_and_source_metadata_are_independent_and_manual_overrides_survive_rescan(self) -> None:
        self.add_paper("independent")
        path = self.root / "annotated.pdf"
        path.write_bytes(pdf_bytes(annotation=True))
        resource = self.storage.create_paper_resource(
            paper_id="independent",
            stored_path=str(path),
            file_type="preprint",
            file_source="preprint_server",
            source_detail="arxiv.org",
        )
        updated = ui_server.update_paper_resource_role(
            self.storage,
            "independent",
            int(resource["id"]),
            "published_version",
            annotation_state="unannotated",
            file_source="publisher",
            source_detail="journals.example",
        )
        self.assertEqual(updated["file_type"], "published_version")
        self.assertEqual(updated["annotation_state"], "unannotated")
        self.assertEqual(updated["file_source"], "publisher")
        self.assertEqual(updated["source_detail"], "journals.example")

        refreshed = ui_server.refresh_paper_resource_fingerprints(self.storage, "independent")[0]
        self.assertGreater(int(refreshed["annotation_count"] or 0), 0)
        self.assertEqual(refreshed["annotation_state"], "unannotated")
        self.assertEqual(refreshed["file_type"], "published_version")

    def test_internal_backfill_detail_is_hidden_and_cleared_when_source_changes(self) -> None:
        self.assertEqual(
            ui_server.inferred_paper_file_source("", "legacy_backfill"),
            ("user_import", ""),
        )
        self.add_paper("legacy-source-detail")
        path = self.root / "legacy.pdf"
        path.write_bytes(pdf_bytes())
        resource = self.storage.create_paper_resource(
            paper_id="legacy-source-detail",
            stored_path=str(path),
            file_type="published_version",
            file_source="publisher",
            source_detail="legacy_backfill",
            added_via="legacy_backfill",
        )

        projected = ui_server.paper_resource_to_api(resource)
        self.assertEqual(projected["file_source"], "publisher")
        self.assertEqual(projected["source_detail"], "")

        updated = ui_server.update_paper_resource_role(
            self.storage,
            "legacy-source-detail",
            int(resource["id"]),
            "published_version",
            annotation_state="unannotated",
            file_source="other",
            source_detail="",
        )
        self.assertEqual(updated["file_source"], "other")
        self.assertIsNone(updated["source_detail"])

    def test_exact_duplicate_is_idempotent_but_annotated_peer_is_preserved(self) -> None:
        self.add_paper("dedupe")
        self.storage.add_library_item(paper_id="dedupe", folder_id=1)
        clean = pdf_bytes()
        first = ui_server.attach_file_to_paper(
            self.storage,
            paper_id="dedupe",
            filename="clean.pdf",
            content=clean,
            file_type="preprint",
        )
        duplicate = ui_server.attach_file_to_paper(
            self.storage,
            paper_id="dedupe",
            filename="same.pdf",
            content=clean,
            file_type="preprint",
        )
        annotated = pdf_bytes(annotation=True)
        peer = ui_server.attach_file_to_paper(
            self.storage,
            paper_id="dedupe",
            filename="annotated.pdf",
            content=annotated,
            file_type="preprint",
        )
        resources = self.storage.list_paper_resources("dedupe")
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(int(first["id"]), int(duplicate["id"]))
        self.assertNotEqual(int(first["id"]), int(peer["id"]))
        self.assertEqual(len(resources), 2)
        self.assertEqual({row["annotation_state"] for row in resources}, {"annotated", "unannotated"})

    def test_major_identity_conflict_is_quarantined_idempotently_and_cascades(self) -> None:
        self.add_paper("identity")
        incoming = {
            "paper_id": "identity",
            "doi": "10.1000/example",
            "title": "Unrelated cell biology result",
            "journal": "Nature Cell Biology",
            "source": "journal",
            "raw": {"authors": ["B. Biologist"]},
        }
        self.assertFalse(self.storage.upsert_paper(incoming))
        self.assertFalse(self.storage.upsert_paper(incoming))
        conflicts = self.storage.list_pending_paper_identity_conflicts()
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(int(conflicts[0]["occurrence_count"]), 2)
        self.assertEqual(self.storage.get_paper("identity")["title"], "A stable condensed matter paper")

        self.storage.conn.execute("DELETE FROM papers WHERE paper_id='identity'")
        self.storage.conn.commit()
        self.assertEqual(self.storage.conn.execute("SELECT COUNT(*) FROM paper_identity_conflicts").fetchone()[0], 0)
        self.assertEqual(self.storage.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_bibliographic_metadata_with_pdf_url_does_not_create_a_file_resource(self) -> None:
        self.add_paper("metadata-only")
        refreshed = self.storage.refresh_paper_metadata(
            "metadata-only",
            {
                "paper_id": "metadata-only",
                "doi": "10.1000/example",
                "title": "A stable condensed matter paper",
                "journal": "Physical Review B",
                "pdf_url": "https://publisher.example/paper.pdf",
                "source": "journal",
                "raw": {},
            },
        )
        self.assertEqual(refreshed["pdf_url"], "https://publisher.example/paper.pdf")
        self.assertEqual(self.storage.list_paper_resources("metadata-only", ensure_primary=False), [])

    def test_invalid_resource_record_is_visible_but_cannot_become_default(self) -> None:
        self.add_paper("invalid-record")
        path = self.root / "quarantined.pdf"
        path.write_bytes(b"not a PDF")
        resource = self.storage.create_paper_resource(
            paper_id="invalid-record",
            stored_path=str(path),
            file_type="invalid_file",
            file_source="user_import",
        )
        listed = self.storage.list_paper_resources("invalid-record")
        self.assertEqual(listed[0]["file_type"], "invalid_file")
        self.assertIsNone(self.storage.resolve_default_paper_resource("invalid-record"))
        with self.assertRaisesRegex(ValueError, "Invalid files"):
            self.storage.set_preferred_paper_resource("invalid-record", int(resource["id"]))

    def test_ui_exposes_only_flat_vnext_vocabulary(self) -> None:
        for label in (
            "Preprint",
            "Accepted manuscript",
            "Published version",
            "Corrected published version",
            "Correction notice",
            "Supplementary material",
            "Peer review file",
            "Invalid file",
            "Annotated",
            "Unannotated",
            "Publisher",
            "Preprint server",
            "Institutional repository",
            "User import",
            "Make Default",
        ):
            self.assertIn(label, ui_server.INDEX_HTML)
        for banned in (
            "Version of Record",
            "First Published Version",
            "Current Publication Record",
            "Combined Version",
            "File role",
            "Revision status",
            ">CURRENT<",
            ">VERSIONS<",
            ">SUPPLEMENTS<",
        ):
            self.assertNotIn(banned, ui_server.INDEX_HTML)
        self.assertEqual(
            set(PAPER_FILE_TYPES),
            {
                "preprint", "accepted_manuscript", "published_version",
                "corrected_published_version", "correction_notice",
                "supplementary_material", "peer_review_file", "other",
                "unknown", "invalid_file",
            },
        )

    def test_user_facing_product_docs_use_published_version_vocabulary(self) -> None:
        root = Path(__file__).resolve().parents[1]
        readme = (root / "README.md").read_text()
        profile_builder = (root / "scripts" / "build_documentation_profile.py").read_text()
        for product_text in (readme, profile_builder):
            self.assertIn("Published version", product_text)
            self.assertNotIn("Version of Record", product_text)
            self.assertNotIn("version of record", product_text)
        self.assertIn('role="version_of_record"', profile_builder)


if __name__ == "__main__":
    unittest.main()
