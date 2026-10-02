from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfWriter

from paper_monitor import download
from paper_monitor.storage import Storage


class DownloadCandidateTests(unittest.TestCase):
    def test_acs_uses_pdf_and_epdf_routes(self):
        self.assertEqual(
            download.journal_pdf_candidates(
                {
                    "doi": "10.1021/acs.nanolett.6c02635",
                    "journal": "Nano Letters",
                }
            ),
            [
                "https://pubs.acs.org/doi/pdf/10.1021/acs.nanolett.6c02635",
                "https://pubs.acs.org/doi/epdf/10.1021/acs.nanolett.6c02635",
            ],
        )

    def test_advanced_materials_prefers_journal_specific_wiley_route(self):
        self.assertEqual(
            download.journal_pdf_candidates(
                {
                    "doi": "10.1002/adma.202300582",
                    "journal": "Advanced Materials",
                }
            )[0],
            "https://advanced.onlinelibrary.wiley.com/doi/pdf/"
            "10.1002/adma.202300582",
        )

    def test_wiley_browser_candidate_establishes_article_session_before_pdf(self):
        self.assertEqual(
            download.publisher_browser_candidate(
                {
                    "doi": "10.1002/adma.202300582",
                    "journal": "Advanced Materials",
                }
            ),
            {
                "publisher": "wiley",
                "url": "https://advanced.onlinelibrary.wiley.com/doi/10.1002/adma.202300582",
                "referer": "https://advanced.onlinelibrary.wiley.com/doi/10.1002/adma.202300582",
                "target_url": (
                    "https://advanced.onlinelibrary.wiley.com/doi/pdfdirect/"
                    "10.1002/adma.202300582"
                ),
            },
        )

    def test_cpl_prefers_the_official_chinese_pdf_mirror(self):
        self.assertEqual(
            download.journal_pdf_candidates(
                {
                    "doi": "10.1088/0256-307X/41/11/117401",
                    "journal": "Chinese Physics Letters",
                }
            )[0],
            "https://cpl.iphy.ac.cn/en/article/pdf/preview/"
            "10.1088/0256-307x/41/11/117401.pdf",
        )

    def test_cpb_extracts_the_internal_pdf_identifier(self):
        response = SimpleNamespace(
            text=(
                "DOI: 10.1088/1674-1056/ae1c24 "
                "onclick=\"lsdy1('PDF','128369','https://cpb.iphy.ac.cn')\""
            )
        )
        with patch.object(download, "request_with_retries", return_value=response):
            self.assertEqual(
                download.cpb_pdf_candidates("10.1088/1674-1056/ae1c24"),
                [
                    "https://cpb.iphy.ac.cn/EN/article/"
                    "downloadArticleFile.do?attachType=PDF&id=128369"
                ],
            )

    def test_elsevier_linkinghub_candidate_becomes_sciencedirect_pdf(self):
        self.assertEqual(
            download.science_direct_pdf_candidates(
                ["https://linkinghub.elsevier.com/retrieve/pii/S2095927319304165"]
            ),
            [
                "https://www.sciencedirect.com/science/article/pii/"
                "S2095927319304165/pdfft?isDTMRedir=true&download=true"
            ],
        )

    def test_elsevier_browser_candidate_establishes_article_session_before_pdf(self):
        direct_url = (
            "https://www.sciencedirect.com/science/article/pii/"
            "S2095927319304165/pdfft?isDTMRedir=true&download=true"
        )
        with patch.object(
            download,
            "crossref_pdf_candidates",
            return_value=["https://linkinghub.elsevier.com/retrieve/pii/S2095927319304165"],
        ):
            self.assertEqual(
                download.publisher_browser_candidate(
                    {
                        "doi": "10.1016/j.scib.2019.07.019",
                        "journal": "Science Bulletin",
                    }
                ),
                {
                    "publisher": "elsevier",
                    "url": (
                        "https://www.sciencedirect.com/science/article/pii/"
                        "S2095927319304165"
                    ),
                    "referer": (
                        "https://www.sciencedirect.com/science/article/pii/"
                        "S2095927319304165"
                    ),
                    "target_url": direct_url,
                },
            )

    def test_nsr_browser_candidate_uses_oxford_pdf_from_crossref(self):
        pdf_url = (
            "https://academic.oup.com/nsr/advance-article-pdf/doi/"
            "10.1093/nsr/nwaf253/63552132/nwaf253.pdf"
        )
        with patch.object(download, "crossref_pdf_candidates", return_value=[pdf_url]):
            self.assertEqual(
                download.publisher_browser_candidate(
                    {
                        "doi": "10.1093/nsr/nwaf253",
                        "journal": "National Science Review",
                    }
                ),
                {
                    "publisher": "oup",
                    "url": pdf_url,
                    "referer": (
                        "https://academic.oup.com/nsr/advance-article/doi/"
                        "10.1093/nsr/nwaf253"
                    ),
                },
            )

    def test_word_supplements_are_detected_but_presentation_files_are_ignored(self):
        self.assertTrue(
            download.is_probable_word_supplement(
                "https://example.org/files/supporting-information.docx supporting information"
            )
        )
        self.assertFalse(
            download.is_probable_word_supplement(
                "https://example.org/files/supporting-information.pptx supporting information"
            )
        )
        self.assertFalse(
            download.is_probable_supplement(
                "https://example.org/files/supporting-information.mp4 supporting information"
            )
        )

    def test_doc_supplement_can_be_converted_with_macos_text_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "supplement.doc"
            target = Path(tmp) / "supplement.pdf"
            source.write_text(r"{\rtf1\ansi Supplementary text}", encoding="ascii")
            with patch.object(download.shutil, "which", return_value=None):
                download.convert_word_document_to_pdf(source, target)

            self.assertTrue(download.is_valid_pdf_file(target))

    def test_reviews_of_modern_physics_uses_the_aps_pdf_routes(self):
        candidates = download.journal_pdf_candidates(
            {
                "doi": "10.1103/RevModPhys.98.031001",
                "journal": "Reviews of Modern Physics",
            }
        )

        self.assertEqual(
            candidates,
            [
                "https://harvest.aps.org/v2/journals/articles/"
                "10.1103/revmodphys.98.031001/fulltext",
                "https://journals.aps.org/rmp/pdf/"
                "10.1103/revmodphys.98.031001",
                "https://link.aps.org/pdf/10.1103/revmodphys.98.031001",
            ],
        )

    def test_physical_review_materials_uses_its_aps_pdf_routes(self):
        candidates = download.journal_pdf_candidates(
            {
                "doi": "10.1103/example-token",
                "journal": "Physical Review Materials",
            }
        )

        self.assertEqual(
            candidates,
            [
                "https://harvest.aps.org/v2/journals/articles/10.1103/example-token/fulltext",
                "https://journals.aps.org/prmaterials/pdf/10.1103/example-token",
                "https://link.aps.org/pdf/10.1103/example-token",
            ],
        )

    def test_europe_pmc_returns_only_exact_open_pdf_match(self):
        response = SimpleNamespace(
            json=lambda: {
                "resultList": {
                    "result": [
                        {
                            "doi": "10.1126/sciadv.1602415",
                            "pmcid": "PMC5419706",
                            "isOpenAccess": "Y",
                            "hasPDF": "Y",
                        },
                        {
                            "doi": "10.1126/sciadv.other",
                            "pmcid": "PMC0000001",
                            "isOpenAccess": "Y",
                            "hasPDF": "Y",
                        },
                    ]
                }
            }
        )
        with patch.object(download, "request_with_retries", return_value=response):
            candidates = download.europe_pmc_pdf_candidates("10.1126/sciadv.1602415")

        self.assertEqual(
            candidates,
            ["https://europepmc.org/api/getPdf?pmcid=PMC5419706"],
        )

    def test_openalex_published_only_excludes_arxiv_submitted_version(self):
        response = SimpleNamespace(
            json=lambda: {
                "best_oa_location": {
                    "is_oa": True,
                    "pdf_url": "https://www.science.org/doi/pdf/10.1126/science.example",
                    "source": {"type": "journal"},
                    "version": "publishedVersion",
                },
                "locations": [
                    {
                        "is_oa": False,
                        "pdf_url": "https://closed.example/article.pdf",
                        "source": {"type": "journal"},
                        "version": "publishedVersion",
                    },
                    {
                        "is_oa": True,
                        "pdf_url": "https://arxiv.org/pdf/1706.06074",
                        "source": {"type": "repository"},
                        "version": "submittedVersion",
                    },
                ],
            }
        )
        with patch.object(download, "openalex_request", return_value=response):
            candidates = download.openalex_open_pdf_candidates(
                "10.1126/science.aao1797",
                published_only=True,
            )

        self.assertEqual(
            candidates,
            [
                "https://www.science.org/doi/pdf/10.1126/science.example",
            ],
        )

    def test_science_open_fallback_requests_published_versions_only(self):
        with patch.object(download, "europe_pmc_pdf_candidates", return_value=[]), patch.object(
            download,
            "openalex_open_pdf_candidates",
            return_value=[],
        ) as openalex:
            download.science_open_access_pdf_candidates("10.1126/science.aao1797")

        openalex.assert_called_once_with(
            "10.1126/science.aao1797",
            published_only=True,
        )

    def test_science_open_candidates_precede_stale_publisher_pdf(self):
        paper = {
            "paper_id": "science-example",
            "doi": "https://doi.org/10.1126/sciadv.1602415",
            "journal": "Science Advances",
            "pdf_url": "https://advances.sciencemag.org/content/example.full.pdf",
            "landing_url": "",
            "url": "",
        }
        with patch.object(
            download,
            "science_open_access_pdf_candidates",
            return_value=["https://europepmc.org/api/getPdf?pmcid=PMC5419706"],
        ), patch.object(download, "crossref_pdf_candidates", return_value=[]):
            candidates = download.collect_pdf_candidates(paper)["main"]

        self.assertEqual(
            candidates[0],
            "https://europepmc.org/api/getPdf?pmcid=PMC5419706",
        )
        self.assertIn(paper["pdf_url"], candidates)

    def test_nature_version_of_record_precedes_stale_reference_pdf(self):
        paper = {
            "paper_id": "nature-example",
            "doi": "10.1038/s41467-026-74221-7",
            "journal": "Nature Communications",
            "pdf_url": (
                "https://www.nature.com/articles/"
                "s41467-026-74221-7_reference.pdf"
            ),
            "landing_url": "",
            "url": "",
        }
        with patch.object(download, "crossref_pdf_candidates", return_value=[]):
            candidates = download.collect_pdf_candidates(paper)["main"]

        self.assertEqual(
            candidates[0],
            "https://www.nature.com/articles/s41467-026-74221-7.pdf",
        )
        self.assertEqual(candidates[-1], paper["pdf_url"])

    def test_nature_reference_url_detection_ignores_query_string(self):
        self.assertTrue(
            download.is_nature_reference_pdf_url(
                "https://www.nature.com/articles/example_reference.pdf?download=1"
            )
        )
        self.assertFalse(
            download.is_nature_reference_pdf_url(
                "https://www.nature.com/articles/example.pdf"
            )
        )

    def test_refresh_reuses_current_numbered_pdf_in_target_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            target_dir = Path(tmp)
            desired = target_dir / "paper_merged.pdf"
            desired.write_bytes(b"old")
            current = target_dir / "paper_merged 2.pdf"
            current.write_bytes(b"current")

            self.assertEqual(
                download.unique_download_path(desired, current_path=str(current)),
                current.resolve(),
            )

    def test_successful_pdf_url_is_synced_across_matching_doi_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "paper_monitor.sqlite")
            try:
                for paper_id in ("arxiv_example", "doi_example"):
                    storage.upsert_paper(
                        {
                            "paper_id": paper_id,
                            "doi": "10.1038/example",
                            "title": "Example",
                            "journal": "Nature Communications",
                            "pdf_url": "https://www.nature.com/articles/example_reference.pdf",
                        }
                    )
                canonical_url = "https://www.nature.com/articles/example.pdf"
                storage.update_download_status(
                    "arxiv_example",
                    status="success",
                    pdf_url=canonical_url,
                )

                self.assertEqual(storage.get_paper("arxiv_example")["pdf_url"], canonical_url)
                self.assertEqual(storage.get_paper("doi_example")["pdf_url"], canonical_url)
            finally:
                storage.close()

    def test_science_supplement_uses_aaas_sm_pdf_url(self):
        self.assertEqual(
            download.science_supplement_pdf_candidates("https://doi.org/10.1126/sciadv.adw9449"),
            [
                "https://www.science.org/doi/suppl/10.1126/sciadv.adw9449/"
                "suppl_file/sciadv.adw9449_sm.pdf",
            ],
        )

    def test_non_pdf_supplements_are_ignored_even_with_a_pdf_label(self):
        response = SimpleNamespace(url="https://www.nature.com/articles/fixture", text="""
            <meta name="citation_pdf_url" content="/articles/fixture.pdf">
            <a href="/esm/MOESM1_ESM.pdf">Supplementary information PDF</a>
            <a href="/esm/MOESM2_ESM.mp4">Supplementary movie PDF</a>
            <a href="/esm/MOESM3_ESM.zip">Supplementary data PDF</a>
            <a href="/esm/MOESM4_ESM.docx">Supplementary Word</a>
        """)
        with patch.object(download, "crossref_pdf_candidates", return_value=[]), patch.object(
            download, "request_with_retries", return_value=response):
            result = download.collect_pdf_candidates({"doi": "10.1038/fixture", "url": response.url})
        self.assertEqual(result["supplements"], ["https://www.nature.com/esm/MOESM1_ESM.pdf"])
        self.assertEqual(result["supplement_documents"], [])
        self.assertEqual(result["main"][0], "https://www.nature.com/articles/fixture.pdf")

    def test_science_supplement_is_collected_without_landing_page_access(self):
        paper = {
            "paper_id": "science-example",
            "doi": "10.1126/science.aao1797",
            "journal": "Science",
            "landing_url": "",
            "url": "",
        }
        with patch.object(download, "science_open_access_pdf_candidates", return_value=[]), patch.object(
            download,
            "crossref_pdf_candidates",
            return_value=[],
        ):
            candidates = download.collect_pdf_candidates(paper)

        self.assertEqual(
            candidates["supplements"],
            [
                "https://www.science.org/doi/suppl/10.1126/science.aao1797/"
                "suppl_file/science.aao1797_sm.pdf",
            ],
        )

    def test_existing_unmerged_science_pdf_is_reused_for_supplement_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            writer.write(str(path))
            paper = {
                "doi": "10.1126/science.aao1797",
                "download_message": "manual PDF replaced: old.pdf",
                "merged_pdf_path": str(path),
            }

            self.assertEqual(
                download.existing_science_main_only_pdf_path(paper),
                path.resolve(),
            )

    def test_existing_science_pdf_already_merged_is_not_reused_as_main_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "merged.pdf"
            path.write_bytes(b"%PDF-1.4\n" + b"x" * 2048)
            paper = {
                "doi": "10.1126/science.aao1797",
                "download_message": "downloaded and merged Science supplementary PDF; temporary PDF removed",
                "merged_pdf_path": str(path),
            }

            self.assertIsNone(download.existing_science_main_only_pdf_path(paper))

    def test_non_science_doi_does_not_trigger_science_fallback(self):
        paper = {
            "paper_id": "other-example",
            "doi": "10.1103/PhysRevLett.1.1",
            "journal": "Physical Review Letters",
            "landing_url": "",
            "url": "",
        }
        with patch.object(download, "science_open_access_pdf_candidates") as fallback, patch.object(
            download,
            "crossref_pdf_candidates",
            return_value=[],
        ):
            download.collect_pdf_candidates(paper)

        fallback.assert_not_called()

if __name__ == "__main__":
    unittest.main()
