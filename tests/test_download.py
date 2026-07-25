from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from paper_monitor import download


class DownloadCandidateTests(unittest.TestCase):
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
        with patch.object(download, "request_with_retries", return_value=response):
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

    def test_science_supplement_uses_aaas_sm_pdf_url(self):
        self.assertEqual(
            download.science_supplement_pdf_candidates("https://doi.org/10.1126/sciadv.adw9449"),
            [
                "https://www.science.org/doi/suppl/10.1126/sciadv.adw9449/"
                "suppl_file/sciadv.adw9449_sm.pdf",
            ],
        )

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
