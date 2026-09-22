from __future__ import annotations

import sqlite3
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from paper_monitor import download, ui_server
from paper_monitor.resource_fingerprint import sha256_for_file
from paper_monitor.science_pdf import is_science_first_release_pdf, is_science_supplement_reference, science_main_pdf_rejection
from tests import test_paper_resources as resource_fixture


FIRST_RELEASE = "First release: 17 September 2026 science.org (Page numbers not final at time of first release) 1"


def pdf_bytes(text: str) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class ScienceDownloadIntegrityTests(unittest.TestCase):
    setUp = resource_fixture.PaperResourceStorageTests.setUp
    tearDown = resource_fixture.PaperResourceStorageTests.tearDown
    add_paper = resource_fixture.PaperResourceStorageTests.add_paper

    def write_pdf(self, name: str, text: str = "Research article") -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pdf_bytes(text))
        return path

    def science_paper(self, paper_id="science"):
        self.add_paper(paper_id)
        self.storage.conn.execute("UPDATE papers SET doi = ? WHERE paper_id = ?", ("10.1126/science.fixture", paper_id))
        self.storage.conn.commit()
        return paper_id

    def attach_main(self, paper_id="science", name="science.fixture.pdf", text="Research article"):
        source = self.write_pdf("native/gewu-publisher-fixture.pdf", text)
        return ui_server.attach_downloaded_publisher_pdf_to_paper(
            self.storage, paper_id=paper_id, source_path=source,
            context={"publisher_download_kind": "aaas-published-pdf",
                     "publisher_download_final_url": "https://www.science.org/doi/pdf/10.1126/science.fixture",
                     "publisher_download_filename": name},
        )

    def test_first_release_requires_the_provisional_footer_on_the_first_page(self):
        for text, expected in [
            (FIRST_RELEASE, True),
            (FIRST_RELEASE.replace(" ", "  "), True),
            ("Science: First release of a new dataset", False),
            ("First release: 17 September 2026 science.org", False),
            ("Published online 17 September 2026 science.org", False),
            (FIRST_RELEASE.replace("science.org", "example.org"), False),
        ]:
            with self.subTest(text=text):
                self.assertEqual(is_science_first_release_pdf(self.write_pdf("main.pdf", text)), expected)
        writer = PdfWriter()
        writer.append(BytesIO(pdf_bytes("Final published article")))
        writer.append(BytesIO(pdf_bytes(FIRST_RELEASE)))
        merged = self.root / "merged.pdf"
        with merged.open("wb") as handle:
            writer.write(handle)
        self.assertFalse(is_science_first_release_pdf(merged))
        self.assertFalse(is_science_first_release_pdf(self.root / "missing.pdf"))

    def test_first_release_classification_keeps_main_and_supplement_merge(self):
        self.science_paper()
        main, paper = self.attach_main(text=FIRST_RELEASE)
        resource_id = paper["primary_resource_id"]
        resource = self.storage.get_paper_resource(resource_id)
        self.assertEqual(resource["file_type"], "accepted_manuscript")
        self.assertEqual(resource["version_role"], "accepted_manuscript")
        self.assertEqual(resource["file_type_override"], 0)
        supplement = self.write_pdf("native/sm.pdf", "Supplementary Materials for")
        context = {"publisher_download_kind": "aaas-supplement-pdf", "publisher_main_resource_id": resource_id}
        with patch.object(ui_server, "allowed_pdf_roots", return_value=[self.root]):
            target, after = ui_server.attach_publisher_supplement_pdf_to_paper(
                self.storage, paper_id="science", context=context, source_path=supplement)
            merged_bytes = target.read_bytes()
            ui_server.attach_publisher_supplement_pdf_to_paper(
                self.storage, paper_id="science", context=context, source_path=supplement)
        self.assertEqual(main, target)
        self.assertEqual(len(PdfReader(str(target)).pages), 2)
        self.assertEqual(target.read_bytes(), merged_bytes)
        self.assertEqual(after["primary_resource_id"], resource_id)
        self.assertEqual(after["storage_key"], paper["storage_key"])
        self.assertEqual(after["download_status"], "success")
        self.assertEqual(self.storage.get_paper_resource(resource_id)["file_type"], "accepted_manuscript")

    def test_first_release_duplicate_repairs_only_automatic_classification(self):
        self.science_paper()
        main, paper = self.attach_main(text=FIRST_RELEASE)
        resource_id = paper["primary_resource_id"]
        before = main.read_bytes()
        for manual in (0, 1):
            with self.subTest(manual=manual):
                self.storage.conn.execute("""UPDATE resources SET file_type = 'published_version',
                    version_role = 'version_of_record', version_label = 'Published Version',
                    file_type_override = ? WHERE id = ?""", (manual, resource_id))
                self.storage.conn.commit()
                target, after = self.attach_main(text=FIRST_RELEASE)
                resource = self.storage.get_paper_resource(resource_id)
                self.assertEqual(resource["file_type"], "published_version" if manual else "accepted_manuscript")
                self.assertEqual(resource["version_role"], "version_of_record" if manual else "accepted_manuscript")
                self.assertEqual(after["primary_resource_id"], resource_id)
                self.assertEqual(target.read_bytes(), before)
                self.assertEqual(len(self.storage.list_paper_resources("science")), 1)

    def test_later_final_publisher_pdf_keeps_first_release_as_a_separate_file(self):
        self.science_paper()
        first, before = self.attach_main(text=FIRST_RELEASE)
        first_id = before["primary_resource_id"]
        first_bytes = first.read_bytes()
        final, after = self.attach_main(text="Final published article with final page numbers")
        self.assertNotEqual(after["primary_resource_id"], first_id)
        accepted = self.storage.get_paper_resource(first_id)
        published = self.storage.get_paper_resource(after["primary_resource_id"])
        self.assertEqual(accepted["file_type"], "accepted_manuscript")
        self.assertEqual(published["file_type"], "published_version")
        self.assertEqual(Path(accepted["stored_path"]).read_bytes(), first_bytes)
        self.assertTrue(final.is_file())
        self.assertEqual(after["storage_key"], before["storage_key"])
        self.assertEqual(len(self.storage.list_paper_resources("science")), 2)

    def test_direct_download_classifies_the_main_page_of_the_merged_pdf(self):
        paper_id = self.science_paper()
        contents = {"main": pdf_bytes(FIRST_RELEASE), "sm": pdf_bytes("Supplementary Materials for")}
        def request(_method, url, **_kwargs):
            return SimpleNamespace(url=url, headers={"content-type": "application/pdf"},
                                   iter_content=lambda **_: [contents[url]])
        with patch.object(download, "collect_pdf_candidates", return_value={"main": ["main"], "supplements": ["sm"]}), \
             patch.object(download, "request_with_retries", side_effect=request):
            result = download.download_paper(storage=self.storage, paper_id=paper_id, pdf_dir=self.root / "downloads")
        resource = ui_server.register_downloaded_paper_resource(self.storage, paper_id, result=result, snapshot=None)
        self.assertEqual(result["status"], "success")
        self.assertEqual(resource["file_type"], "accepted_manuscript")
        self.assertEqual(len(PdfReader(result["merged_pdf_path"]).pages), 2)

    def test_first_release_rule_does_not_reclassify_other_publishers_or_preprints(self):
        path = self.write_pdf("main.pdf", FIRST_RELEASE)
        self.assertEqual(ui_server.downloaded_version_role(
            {"doi": "10.1234/other"}, "https://example.org/doi/pdf/10.1234/other", pdf_path=path), "version_of_record")
        self.assertEqual(ui_server.downloaded_version_role(
            {"doi": "10.1126/science.fixture"}, "https://arxiv.org/pdf/2609.00001", pdf_path=path), "preprint")

    def test_supplement_resource_binding_still_rejects_other_papers_and_non_main_files(self):
        self.science_paper()
        _, paper = self.attach_main(text=FIRST_RELEASE)
        resource_id = paper["primary_resource_id"]
        self.add_paper("other")
        supplement = self.write_pdf("sm.pdf", "Supplementary Materials for")
        context = {"publisher_download_kind": "aaas-supplement-pdf", "publisher_main_resource_id": resource_id}
        with self.assertRaisesRegex(ValueError, "no longer available"):
            ui_server.attach_publisher_supplement_pdf_to_paper(
                self.storage, paper_id="other", context=context, source_path=supplement)
        self.storage.conn.execute("UPDATE resources SET file_type = 'supplementary_material' WHERE id = ?", (resource_id,))
        self.storage.conn.commit()
        with self.assertRaisesRegex(ValueError, "no longer available"):
            ui_server.attach_publisher_supplement_pdf_to_paper(
                self.storage, paper_id="science", context=context, source_path=supplement)

    def test_supplement_reference_variants_and_cover_heading(self):
        for reference in ["/doi/suppl/10.1126/science.fixture/suppl_file/x.pdf",
                          "science.fixture_sm.pdf?download=1", "/x/science.fixture_mdar_reproducibility_checklist.pdf",
                          "/doi/%73uppl/x", "attachment; filename=science.fixture_sm.pdf", 'attachment; filename="science.fixture_sm.pdf"']:
            with self.subTest(reference=reference):
                self.assertTrue(is_science_supplement_reference(reference))
        self.assertFalse(is_science_supplement_reference("https://www.science.org/doi/pdf/10.1126/science.fixture"))
        for heading in ["Supplementary Materials for", "Materials Design Analysis Reporting"]:
            source = self.write_pdf("cover.pdf", heading)
            self.assertTrue(science_main_pdf_rejection(source))
        source = self.write_pdf("main.pdf", "Our supplementary materials describe the methods.")
        self.assertFalse(science_main_pdf_rejection(source))

    def test_discovery_filters_supplemental_metadata_and_saved_pdf_url(self):
        sm = "https://www.science.org/doi/suppl/10.1126/science.fixture/suppl_file/science.fixture_sm.pdf"
        response = SimpleNamespace(url="https://www.science.org/doi/10.1126/science.fixture",
                                   text=f'<meta name="citation_pdf_url" content="{sm}"><a href="{sm}">PDF</a>')
        with patch.object(download, "science_open_access_pdf_candidates", return_value=[]), \
             patch.object(download, "crossref_pdf_candidates", return_value=[sm]), \
             patch.object(download, "request_with_retries", return_value=response):
            candidates = download.collect_pdf_candidates({"doi": "10.1126/science.fixture", "pdf_url": sm, "landing_url": response.url})
        self.assertNotIn(sm, candidates["main"])
        self.assertEqual(candidates["supplements"], [sm])

    def test_main_request_rejects_supplement_redirect_and_cover(self):
        url = "https://www.science.org/doi/pdf/10.1126/science.fixture"
        for final_url, content in [(url + "/suppl/sm.pdf", pdf_bytes("Supplementary Materials for")),
                                   (url, pdf_bytes("Supplementary Materials for"))]:
            with self.subTest(final_url=final_url):
                response = SimpleNamespace(url=final_url, headers={"content-type": "application/pdf"},
                                           iter_content=lambda **_: [content], close=lambda: None)
                target = self.root / "main.pdf"
                messages = []
                with patch.object(download, "request_with_retries", return_value=response):
                    self.assertFalse(download.try_download_pdf(url, target, messages, science_main=True))
                self.assertFalse(target.exists())
                self.assertIn("supplement", messages[-1].lower())

    def test_direct_route_tries_next_real_main_and_merges_once(self):
        paper_id = self.science_paper()
        contents = {"bad": pdf_bytes("Supplementary Materials for"), "main": pdf_bytes("Main paper"),
                    "sm": pdf_bytes("Supplementary Materials for"), "alias": pdf_bytes("Supplementary Materials for")}
        def request(_method, url, **_kwargs):
            return SimpleNamespace(url=url, headers={"content-type": "application/pdf"},
                                   iter_content=lambda **_: [contents[url]])
        with patch.object(download, "collect_pdf_candidates", return_value={"main": ["bad", "main"], "supplements": ["sm", "alias"]}), \
             patch.object(download, "request_with_retries", side_effect=request):
            result = download.download_paper(storage=self.storage, paper_id=paper_id, pdf_dir=self.root / "downloads")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["main_pdf_url"], "main")
        reader = PdfReader(result["merged_pdf_path"])
        self.assertEqual(len(reader.pages), 2)
        self.assertIn("Main paper", reader.pages[0].extract_text())

    def test_native_cover_rejection_changes_no_saved_record_or_file(self):
        paper_id = self.science_paper()
        source = self.write_pdf("native/gewu-publisher-fixture.pdf", "Supplementary Materials for")
        before = self.storage.get_paper(paper_id)
        with self.assertRaisesRegex(ValueError, "main article was not saved"):
            ui_server.attach_downloaded_publisher_pdf_to_paper(
                self.storage, paper_id=paper_id, source_path=source,
                context={"publisher_download_kind": "aaas-published-pdf"})
        self.assertEqual(self.storage.get_paper(paper_id), before)
        self.assertEqual(self.storage.list_paper_resources(paper_id), [])
        self.assertTrue(source.exists())

    def test_missing_main_never_saves_supplement_as_success(self):
        self.science_paper()
        content = pdf_bytes("Supplementary Materials for")
        response = SimpleNamespace(url="https://www.science.org/doi/pdf/10.1126/science.fixture",
                                   headers={"content-type": "application/pdf"}, iter_content=lambda **_: [content])
        with patch.object(download, "collect_pdf_candidates", return_value={"main": ["main"], "supplements": ["sm"]}), \
             patch.object(download, "request_with_retries", return_value=response):
            result = download.download_paper(storage=self.storage, paper_id="science", pdf_dir=self.root / "downloads")
        self.assertEqual(result["status"], "failed")
        self.assertIn("main PDF unavailable", result["message"])
        self.assertFalse(self.storage.get_paper("science")["merged_pdf_path"])
        self.assertEqual(list((self.root / "downloads").rglob("*.pdf")), [])

    def test_publisher_name_and_final_url_replace_staging_name(self):
        paper_id = self.science_paper()
        target, paper = self.attach_main()
        resource = self.storage.get_paper_resource(paper["primary_resource_id"])
        self.assertEqual(resource["original_filename"], "science.fixture.pdf")
        self.assertEqual(target.name, "science.fixture.pdf")
        self.assertEqual(resource["source_url"], "https://www.science.org/doi/pdf/10.1126/science.fixture")
        self.assertEqual(paper["pdf_url"], resource["source_url"])
        self.assertEqual(resource["file_type"], "published_version")

    def test_missing_publisher_name_uses_metadata_filename(self):
        self.science_paper()
        target, paper = self.attach_main(name="")
        resource = self.storage.get_paper_resource(paper["primary_resource_id"])
        self.assertNotIn("gewu-publisher", target.name)
        self.assertNotIn("daiqo", resource["original_filename"])
        self.assertIn("Paper science", resource["original_filename"])

    def test_legacy_placement_name_cannot_rename_download_back_after_merge(self):
        self.science_paper()
        folder = self.storage.create_library_folder(name="AI", parent_id=1)
        item = self.storage.add_library_item(paper_id="science", folder_id=folder["id"])
        legacy_name = "daiqo-published-B654FF34-B161-4E61-BAAE-6F2D258E4E3B.pdf"
        self.storage.rename_library_item(item_id=item["id"], name=legacy_name)
        self.add_paper("unrelated")
        unrelated = self.storage.add_library_item(paper_id="unrelated", folder_id=folder["id"])
        unrelated = self.storage.rename_library_item(item_id=unrelated["id"], name=legacy_name)
        supplement = self.write_pdf("native/sm.pdf", "Supplementary Materials for")
        with patch.object(ui_server, "allowed_pdf_roots", return_value=[self.root]):
            main, paper = self.attach_main()
            resource_id = paper["primary_resource_id"]
            self.assertEqual(self.storage.get_library_item(item["id"])["display_name"], "science.fixture.pdf")
            target, _ = ui_server.attach_publisher_supplement_pdf_to_paper(
                self.storage, paper_id="science", source_path=supplement,
                context={"publisher_download_kind": "aaas-supplement-pdf", "publisher_main_resource_id": resource_id},
            )
            before = target.read_bytes()
            ui_server.sync_all_pdf_aliases_for_paper(self.storage, "science")
        resource = self.storage.get_paper_resource(resource_id)
        self.assertEqual(target, main)
        self.assertEqual(target.name, "science.fixture.pdf")
        self.assertEqual(resource["display_name"], target.name)
        self.assertEqual(resource["stored_path"], str(target))
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(len(PdfReader(str(target)).pages), 2)
        self.assertEqual(self.storage.get_library_item(unrelated["id"]), unrelated)

    def test_publisher_download_preserves_custom_placement_names(self):
        paper_id = self.science_paper()
        item = self.storage.add_library_item(paper_id=paper_id, folder_id=1)
        for name in ("My chosen title.pdf", "daiqo-published-my-notes.pdf"):
            with self.subTest(name=name):
                item = self.storage.rename_library_item(item_id=item["id"], name=name)
                with patch.object(ui_server, "allowed_pdf_roots", return_value=[self.root]):
                    self.attach_main(paper_id=paper_id)
                self.assertEqual(self.storage.get_library_item(item["id"]), item)

    def test_supplement_retry_keeps_exact_bytes_and_resource_fingerprints(self):
        self.science_paper()
        main, _ = self.attach_main()
        supplement = self.write_pdf("native/sm.pdf", "Supplementary Materials for")
        context = {"publisher_download_kind": "aaas-supplement-pdf"}
        with patch.object(ui_server, "allowed_pdf_roots", return_value=[self.root]):
            target, paper = ui_server.attach_publisher_supplement_pdf_to_paper(self.storage, paper_id="science", context=context, source_path=supplement)
            before = target.read_bytes()
            resource = self.storage.get_paper_resource(paper["primary_resource_id"])
            self.assertEqual(resource["sha256"], sha256_for_file(target))
            self.assertEqual(resource["size_bytes"], len(before))
            self.assertEqual(resource["page_count"], 2)
            self.assertEqual(target, main)
            target2, _ = ui_server.attach_publisher_supplement_pdf_to_paper(self.storage, paper_id="science", context=context, source_path=supplement)
        self.assertEqual(target2.read_bytes(), before)
        self.assertEqual(self.storage.get_paper_resource(paper["primary_resource_id"]), resource)
        self.assertTrue(supplement.exists())

    def test_main_only_and_merge_errors_preserve_existing_bytes(self):
        self.science_paper()
        main, paper = self.attach_main()
        supplement = self.write_pdf("native/sm.pdf", "Supplementary Materials for")
        original = main.read_bytes()
        before = self.storage.get_paper_resource(paper["primary_resource_id"])
        self.storage.conn.execute("CREATE TEMP TRIGGER fail_merge BEFORE UPDATE OF page_count ON resources BEGIN SELECT RAISE(ABORT, 'fixture update failure'); END")
        with patch.object(ui_server, "allowed_pdf_roots", return_value=[self.root]), self.assertRaisesRegex(sqlite3.Error, "fixture update failure"):
            ui_server.attach_publisher_supplement_pdf_to_paper(self.storage, paper_id="science", context={"publisher_download_kind": "aaas-supplement-pdf"}, source_path=supplement)
        self.assertEqual(main.read_bytes(), original)
        self.assertEqual(self.storage.get_paper("science"), paper)
        self.assertEqual(self.storage.get_paper_resource(paper["primary_resource_id"]), before)
        self.assertEqual(list(main.parent.glob(".*-supplement-*")), [])

    def test_manual_preprint_default_is_not_the_supplement_target(self):
        self.science_paper()
        preprint = ui_server.attach_file_to_paper(self.storage, paper_id="science", filename="preprint.pdf", content=pdf_bytes("Preprint"), file_type="preprint", file_role="publication_version", version_role="preprint")
        self.storage.set_preferred_paper_resource("science", preprint["id"])
        item = self.storage.add_library_item(paper_id="science", folder_id=1)
        item = self.storage.rename_library_item(item_id=item["id"], name="daiqo-published-B654FF34-B161-4E61-BAAE-6F2D258E4E3B.pdf")
        from paper_monitor.file_layout import reconcile
        reconcile(self.storage, "science")
        before = self.storage.get_paper("science")
        preprint_path = Path(before["merged_pdf_path"])
        original = preprint_path.read_bytes()
        main, _ = self.attach_main()
        resource = next(item for item in self.storage.list_paper_resources("science") if item["file_type"] == "published_version")
        supplement = self.write_pdf("native/sm.pdf", "Supplementary Materials for")
        with patch.object(ui_server, "allowed_pdf_roots", return_value=[self.root]):
            target, paper = ui_server.attach_publisher_supplement_pdf_to_paper(self.storage, paper_id="science", context={"publisher_download_kind": "aaas-supplement-pdf", "publisher_main_resource_id": resource["id"]}, source_path=supplement)
        self.assertEqual(target, main)
        self.assertEqual(len(PdfReader(str(target)).pages), 2)
        self.assertEqual(paper["primary_resource_id"], before["primary_resource_id"])
        self.assertEqual(paper["preferred_resource_id"], before["preferred_resource_id"])
        self.assertEqual(paper["merged_pdf_path"], before["merged_pdf_path"])
        self.assertEqual(preprint_path.read_bytes(), original)
        self.assertEqual(self.storage.get_library_item(item["id"]), item)

    def test_existing_supplement_only_file_is_not_a_merge_base(self):
        self.science_paper()
        main = self.write_pdf("bad.pdf", "Supplementary Materials for")
        supplement = self.write_pdf("sm.pdf", "Supplementary Materials for")
        self.storage.update_download_status("science", status="success", main_pdf_path=str(main), merged_pdf_path=str(main))
        before = main.read_bytes()
        with self.assertRaisesRegex(ValueError, "without the Science main article"):
            ui_server.attach_publisher_supplement_pdf_to_paper(self.storage, paper_id="science", context={"publisher_download_kind": "aaas-supplement-pdf"}, source_path=supplement)
        self.assertEqual(main.read_bytes(), before)

    def test_shared_main_is_copied_and_other_paper_stays_unchanged(self):
        self.science_paper()
        main, _ = self.attach_main()
        self.add_paper("other")
        self.storage.update_download_status("other", status="success", main_pdf_path=str(main), merged_pdf_path=str(main))
        original = main.read_bytes()
        other = self.storage.get_paper("other")
        supplement = self.write_pdf("sm.pdf", "Supplementary Materials for")
        with patch.object(ui_server, "allowed_pdf_roots", return_value=[self.root]):
            target, paper = ui_server.attach_publisher_supplement_pdf_to_paper(self.storage, paper_id="science", context={"publisher_download_kind": "aaas-supplement-pdf"}, source_path=supplement)
        self.assertNotEqual(target, main)
        self.assertEqual(len(PdfReader(str(target)).pages), 2)
        self.assertEqual(main.read_bytes(), original)
        self.assertEqual(self.storage.get_paper("other"), other)
        self.assertEqual(self.storage.get_paper_resource(paper["primary_resource_id"])["stored_path"], str(target))


class ScienceDownloadApiTests(unittest.TestCase):
    def test_native_attachment_response_binds_followup_to_downloaded_resource(self):
        from tests import test_ai_access
        fixture = test_ai_access.AIAccessTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        storage = fixture.storage
        storage.upsert_paper({"paper_id": "science-api", "doi": "10.1126/science.fixture",
                              "title": "Science fixture", "journal": "Science", "source": "fixture"})
        preprint = ui_server.attach_file_to_paper(storage, paper_id="science-api", filename="preprint.pdf", content=pdf_bytes("Preprint"), file_type="preprint", file_role="publication_version", version_role="preprint")
        storage.set_preferred_paper_resource("science-api", preprint["id"])
        before = storage.get_paper("science-api")
        source = fixture.root / "gewu-publisher-fixture.pdf"
        source.write_bytes(pdf_bytes(FIRST_RELEASE))
        status, main, _ = fixture.request("/api/manual-pdf-path", {
            "paper_id": "science-api", "source_path": str(source),
            "publisher_download_kind": "aaas-published-pdf", "publisher_download_filename": "science.fixture.pdf",
            "publisher_download_final_url": "https://www.science.org/doi/pdf/10.1126/science.fixture",
        }, workspace=True)
        self.assertEqual(status, 200, main)
        self.assertTrue(main["publisher_main_resource_id"])
        self.assertNotEqual(main["publisher_main_resource_id"], preprint["id"])
        supplement = fixture.root / "sm.pdf"
        supplement.write_bytes(pdf_bytes("Supplementary Materials for"))
        with patch.object(ui_server, "allowed_pdf_roots", return_value=[fixture.root]):
            status, result, _ = fixture.request("/api/manual-pdf-path", {
                "paper_id": "science-api", "source_path": str(supplement),
                "publisher_download_kind": "aaas-supplement-pdf",
                "publisher_main_resource_id": main["publisher_main_resource_id"],
            }, workspace=True)
        self.assertEqual(status, 200, result)
        self.assertEqual(storage.get_paper("science-api")["merged_pdf_path"], before["merged_pdf_path"])
        resource = storage.get_paper_resource(main["publisher_main_resource_id"])
        self.assertEqual(resource["file_type"], "accepted_manuscript")
        self.assertEqual(storage.get_paper("science-api")["preferred_resource_id"], preprint["id"])
        self.assertEqual(len(PdfReader(resource["stored_path"]).pages), 2, str(resource))


if __name__ == "__main__":
    unittest.main()
