import tempfile
import unittest
from pathlib import Path

from paper_monitor.storage import Storage
from paper_monitor.ui_server import INDEX_HTML, annotate_papers_with_library_status


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


if __name__ == "__main__":
    unittest.main()
