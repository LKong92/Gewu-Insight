"""Nature fallback HTTP contract and file invariants, using temporary data only."""
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from pypdf import PdfReader

from paper_monitor import ui_server, download
from tests import test_ai_access
from tests.test_science_download_integrity import pdf_bytes


class NatureBrowserDownloadTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_ai_access.AIAccessTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.storage = self.fixture.storage
        self.root = self.fixture.root
        self.storage.upsert_paper({"paper_id": "nature", "doi": "10.1038/s41563-026-02522-9",
            "title": "Nature test article", "journal": "Nature Materials", "source": "fixture"})
        self.before = self.storage.get_paper("nature")

    def attach(self, kind="publisher-main-pdf", filename="s41563-026-02522-9.pdf", resource_id=0):
        source = self.root / filename
        source.write_bytes(pdf_bytes("Supplementary information" if "supplement" in kind else "Research article"))
        with patch.object(ui_server, "allowed_pdf_roots", return_value=[self.root]):
            return self.fixture.request("/api/manual-pdf-path", {
                "paper_id": "nature", "source_path": str(source),
                "publisher_download_kind": kind, "publisher_download_name": "nature",
                "publisher_download_filename": filename,
                "publisher_download_final_url": f"https://www.nature.com/articles/{filename}",
                "publisher_main_resource_id": resource_id,
            }, workspace=True)[:2]

    def test_failed_direct_download_returns_article_first_native_handoff(self):
        with patch.object(ui_server, "download_paper", return_value={"status": "failed", "message": "HTTP 403"}):
            status, result, _ = self.fixture.request("/api/download", {"paper_id": "nature"}, workspace=True)
        self.assertEqual(status, 200, result)
        self.assertEqual(result["browser_fallback"]["publisher"], "nature")
        self.assertEqual(result["browser_fallback"]["target_url"], "https://www.nature.com/articles/s41563-026-02522-9.pdf")
        self.assertEqual(self.storage.get_paper("nature")["storage_key"], self.before["storage_key"])
        self.assertEqual(self.storage.list_paper_resources("nature", ensure_primary=False), [])

    def test_direct_secondary_redirect_cannot_replace_main(self):
        target = self.root / 'main.pdf'
        original = pdf_bytes('Saved main article')
        target.write_bytes(original)
        response = SimpleNamespace(url='https://media.springernature.com/esm/MOESM1_ESM.pdf',
            headers={'content-type': 'application/pdf'}, close=lambda: None)
        with patch.object(download, 'request_with_retries', return_value=response):
            messages = []
            self.assertFalse(download.try_download_pdf('https://www.nature.com/articles/fixture.pdf', target, messages, nature_main=True))
        self.assertIn('secondary material', messages[0])
        self.assertEqual(target.read_bytes(), original)

    def test_native_main_and_supplement_preserve_manual_default_and_deduplicate(self):
        preprint = ui_server.attach_file_to_paper(self.storage, paper_id="nature", filename="preprint.pdf",
            content=pdf_bytes("User preferred preprint"), file_type="preprint", file_role="publication_version", version_role="preprint")
        self.storage.set_preferred_paper_resource("nature", preprint["id"])
        before = self.storage.get_paper("nature")
        preprint_path = Path(self.storage.resource_local_path(self.storage.get_paper_resource(preprint["id"])))
        original = preprint_path.read_bytes()
        status, main = self.attach()
        self.assertEqual(status, 200, main)
        resource_id = main["publisher_main_resource_id"]
        self.assertTrue(resource_id)
        self.assertNotEqual(resource_id, preprint["id"])
        status, merged = self.attach("publisher-supplement-file", "41563_2026_2522_MOESM1_ESM.pdf", resource_id)
        self.assertEqual(status, 200, merged)
        resource = self.storage.get_paper_resource(resource_id)
        merged_path = Path(self.storage.resource_local_path(resource))
        merged_bytes = merged_path.read_bytes()
        self.assertEqual(len(PdfReader(merged_path).pages), 2)
        self.assertEqual(resource["file_type"], "published_version")
        status, repeated = self.attach("publisher-supplement-file", "41563_2026_2522_MOESM1_ESM.pdf", resource_id)
        self.assertEqual(status, 200, repeated)
        self.assertEqual(merged_path.read_bytes(), merged_bytes)
        after = self.storage.get_paper("nature")
        for field in ("storage_key", "preferred_resource_id", "primary_resource_id", "main_pdf_path", "merged_pdf_path"):
            self.assertEqual(after[field], before[field], field)
        self.assertEqual(preprint_path.read_bytes(), original)
        self.assertEqual(len(self.storage.list_paper_resources("nature", ensure_primary=False)), 2)

    def test_secondary_response_cannot_become_main(self):
        for filename in ("41563_2026_2522_MOESM1_ESM.pdf", "peer-review-file.pdf", "reporting_summary.pdf"):
            with self.subTest(filename=filename):
                status, result = self.attach(filename=filename)
                self.assertEqual(status, 400, result)
                self.assertIn("instead of the main", result["error"])
        self.assertEqual(self.storage.list_paper_resources("nature", ensure_primary=False), [])

    def test_reference_pdf_retains_accepted_manuscript_classification(self):
        status, main = self.attach(filename="s41563-026-02522-9_reference.pdf")
        self.assertEqual(status, 200, main)
        resource = self.storage.get_paper_resource(main["publisher_main_resource_id"])
        self.assertEqual(resource["file_type"], "accepted_manuscript")

    def test_supplement_requires_the_exact_downloaded_main(self):
        status, main = self.attach()
        self.assertEqual(status, 200, main)
        path = Path(self.storage.resource_local_path(self.storage.get_paper_resource(main["publisher_main_resource_id"])))
        original = path.read_bytes()
        for resource_id in (0, 9999999):
            status, error = self.attach("publisher-supplement-file", "sm.pdf", resource_id)
            self.assertEqual(status, 400, error)
            self.assertEqual(path.read_bytes(), original)

    def test_partial_direct_download_supplies_resource_for_supplement_retry(self):
        def download_main(*, storage, paper_id, **kwargs):
            path = self.root / "direct-main.pdf"
            path.write_bytes(pdf_bytes("Research article"))
            storage.update_download_status(paper_id, status="partial", main_pdf_path=str(path), merged_pdf_path=str(path))
            return {"status": "partial", "message": "main PDF saved as merged PDF; no PDF supplement found",
                "main_pdf_url": "https://www.nature.com/articles/s41563-026-02522-9.pdf", "merged_pdf_path": str(path)}
        with patch.object(ui_server, "download_paper", side_effect=download_main):
            status, result, _ = self.fixture.request("/api/download", {"paper_id": "nature"}, workspace=True)
        self.assertEqual(status, 200, result)
        self.assertEqual(result["browser_fallback"]["kind"], "publisher-supplement-discovery")
        resource = self.storage.get_paper_resource(result["result"]["publisher_main_resource_id"])
        self.assertEqual(resource["paper_id"], "nature")
        self.assertEqual(resource["file_type"], "published_version")


if __name__ == "__main__":
    unittest.main()
