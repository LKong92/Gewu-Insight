import tempfile
import unittest
from pathlib import Path

from paper_monitor.storage import Storage
from paper_monitor.ui_server import (
    INDEX_HTML,
    annotate_papers_with_library_status,
    journal_counts_for_month,
)


class JournalLibraryStatusTests(unittest.TestCase):
    def test_status_counts_library_and_space_but_excludes_recycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                paper_ids = ["paper-library", "paper-space", "paper-recycle"]
                for paper_id in paper_ids:
                    storage.upsert_paper(
                        {
                            "paper_id": paper_id,
                            "title": paper_id,
                            "journal": "Example Journal",
                            "publication_date": "2026-07-16",
                            "source": "test",
                        }
                    )

                storage.add_library_item(paper_id="paper-library", folder_id=1)
                space = storage.create_library_root_folder(name="Research Space")
                storage.add_library_item(paper_id="paper-space", folder_id=int(space["id"]))
                recycle = storage.ensure_library_folder(parent_id=1, name="Recycle")
                storage.add_library_item(paper_id="paper-recycle", folder_id=int(recycle["id"]))

                annotated = annotate_papers_with_library_status(
                    storage,
                    [{"paper_id": paper_id} for paper_id in paper_ids],
                )
                by_id = {paper["paper_id"]: paper for paper in annotated}
                self.assertTrue(by_id["paper-library"]["in_library"])
                self.assertTrue(by_id["paper-space"]["in_library"])
                self.assertFalse(by_id["paper-recycle"]["in_library"])
            finally:
                storage.close()

    def test_report_card_uses_persistent_in_library_visual_class(self):
        self.assertIn('${inLibrary ? " in-library" : ""}', INDEX_HTML)
        self.assertIn(".paper.in-library {", INDEX_HTML)
        self.assertIn(".paper.in-library:hover {", INDEX_HTML)
        self.assertIn(".paper.in-library.report-selected {", INDEX_HTML)

    def test_calendar_counts_only_configured_journal_monitor_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                for paper_id, journal, section_allowed in (
                    ("nature-paper", "Nature", True),
                    ("arxiv-paper", "arXiv", True),
                    ("subject-only-paper", "Unmonitored Journal", True),
                    ("blocked-section-paper", "Nature", False),
                ):
                    storage.upsert_paper(
                        {
                            "paper_id": paper_id,
                            "title": paper_id,
                            "journal": journal,
                            "publication_date": "2026-07-15",
                            "source": "test",
                            "section_allowed": section_allowed,
                        }
                    )

                counts = journal_counts_for_month(
                    storage,
                    prefix="2026-07-",
                    journals=["Nature", "arXiv"],
                )
            finally:
                storage.close()

        self.assertEqual(
            counts,
            {"2026-07-15": {"Nature": 1, "arXiv": 1}},
        )

    def test_arxiv_category_defaults_and_user_selection_are_persistent(self):
        self.assertIn('"cond-mat.mes-hall",', INDEX_HTML)
        self.assertIn('"cond-mat.str-el",', INDEX_HTML)
        self.assertIn('"cond-mat.supr-con"', INDEX_HTML)
        self.assertIn('const ARXIV_SELECTED_CATEGORIES_STORAGE_KEY = "daiqo-arxiv-selected-categories";', INDEX_HTML)
        self.assertIn("new Set(loadStoredPreprintCategories() ?? DEFAULT_ARXIV_CATEGORIES)", INDEX_HTML)
        self.assertIn("saveSelectedPreprintCategories();", INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
