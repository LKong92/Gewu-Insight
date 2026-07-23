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
                "url": "https://www.science.org/doi/pdf/10.1126/sciadv.adw9449?download=true",
            },
        )

    def test_success_or_non_aaas_paper_has_no_browser_fallback(self):
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
                {"status": "failed"},
            )
        )


if __name__ == "__main__":
    unittest.main()
