from __future__ import annotations

import unittest

from paper_monitor.ui_server import published_pdf_browser_fallback


class PublishedPdfBrowserFallbackTests(unittest.TestCase):
    def test_aaas_failure_offers_only_official_published_pdf(self):
        fallback = published_pdf_browser_fallback(
            {"doi": "https://doi.org/10.1126/sciadv.adw9449"},
            {"status": "failed"},
        )

        self.assertEqual(
            fallback,
            {
                "kind": "aaas-published-pdf",
                "publisher": "aaas",
                "url": "https://www.science.org/doi/10.1126/sciadv.adw9449",
                "target_url": "https://www.science.org/doi/pdf/10.1126/sciadv.adw9449?download=true",
                "referer": "https://www.science.org/doi/10.1126/sciadv.adw9449",
                "followup": {
                    "kind": "aaas-supplement-discovery",
                    "url": "https://www.science.org/doi/10.1126/sciadv.adw9449",
                    "fallback_urls": [
                        "https://www.science.org/doi/suppl/10.1126/sciadv.adw9449/"
                        "suppl_file/sciadv.adw9449_sm.pdf"
                    ],
                },
            },
        )

    def test_partial_aaas_download_offers_supplement_browser_fallback(self):
        fallback = published_pdf_browser_fallback(
            {"doi": "10.1126/science.aao1797"},
            {
                "status": "partial",
                "message": "main PDF saved as merged PDF; no PDF supplement found",
            },
        )

        self.assertEqual(
            fallback,
            {
                "kind": "aaas-supplement-discovery",
                "url": "https://www.science.org/doi/10.1126/science.aao1797",
                "fallback_urls": [
                    "https://www.science.org/doi/suppl/10.1126/science.aao1797/"
                    "suppl_file/science.aao1797_sm.pdf"
                ],
            },
        )

    def test_success_or_unsupported_paper_has_no_browser_fallback(self):
        self.assertIsNone(
            published_pdf_browser_fallback(
                {"doi": "10.1126/sciadv.adw9449"},
                {"status": "partial"},
            )
        )
        self.assertIsNone(
            published_pdf_browser_fallback(
                {
                    "doi": "10.1103/PhysRevLett.1.1",
                    "journal": "Physical Review Letters",
                },
                {"status": "success"},
            )
        )
        self.assertIsNone(
            published_pdf_browser_fallback(
                {
                    "doi": "10.5555/example",
                    "journal": "Unsupported Journal",
                },
                {"status": "failed"},
            )
        )

    def test_acs_failure_uses_the_generic_publisher_browser(self):
        self.assertEqual(
            published_pdf_browser_fallback(
                {
                    "doi": "10.1021/acs.nanolett.6c02635",
                    "journal": "Nano Letters",
                },
                {"status": "failed"},
            ),
            {
                "kind": "publisher-main-pdf",
                "publisher": "acs",
                "url": "https://pubs.acs.org/doi/pdf/10.1021/acs.nanolett.6c02635",
                "referer": "https://pubs.acs.org/doi/10.1021/acs.nanolett.6c02635",
                "followup": {
                    "kind": "publisher-supplement-discovery",
                    "publisher": "acs",
                    "url": "https://pubs.acs.org/doi/10.1021/acs.nanolett.6c02635",
                    "referer": "https://pubs.acs.org/doi/10.1021/acs.nanolett.6c02635",
                    "fallback_urls": [],
                },
            },
        )

    def test_aps_partial_download_checks_for_supplementary_files(self):
        self.assertEqual(
            published_pdf_browser_fallback(
                {
                    "doi": "10.1103/PhysRevLett.1.1",
                    "journal": "Physical Review Letters",
                },
                {
                    "status": "partial",
                    "message": "main PDF saved as merged PDF; no PDF supplement found",
                },
            ),
            {
                "kind": "publisher-supplement-discovery",
                "publisher": "aps",
                "url": "https://journals.aps.org/prl/abstract/10.1103/physrevlett.1.1",
                "referer": "https://journals.aps.org/prl/abstract/10.1103/physrevlett.1.1",
                "fallback_urls": [],
            },
        )


if __name__ == "__main__":
    unittest.main()
