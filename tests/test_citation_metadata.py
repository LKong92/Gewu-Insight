import json
import unittest

from paper_monitor.ui_server import (
    authors_from_google_scholar,
    citation_label,
    full_author_names,
    google_scholar_author_names,
    merge_crossref_bibliographic_raw,
    paper_page,
    paper_volume,
    parse_manual_author_list,
)
from paper_monitor.sources.crossref import normalize_crossref_item


class CitationMetadataTest(unittest.TestCase):
    def test_aps_doi_fills_missing_volume_and_article_number(self):
        paper = {
            "doi": "10.1103/physrevb.94.094524",
            "journal": "Physical Review B",
            "publication_date": "2016-09-28",
            "raw_json": json.dumps({}),
        }
        self.assertEqual(paper_volume(paper), "94")
        self.assertEqual(paper_page(paper), "094524")
        self.assertIn("Physical Review B 94, 094524", citation_label(paper))

    def test_crossref_article_number_survives_openalex_metrics_refresh(self):
        raw = {"id": "https://openalex.org/W1", "biblio": {"volume": "1", "issue": "1"}}
        merge_crossref_bibliographic_raw(
            raw,
            {
                "volume": "1",
                "issue": "1",
                "article-number": "20",
                "container-title": ["Quantum Frontiers"],
            },
        )
        paper = {
            "doi": "10.1007/s44214-022-00022-w",
            "journal": "Quantum Frontiers",
            "publication_date": "2022-12-02",
            "raw_json": json.dumps(raw),
        }
        self.assertEqual(paper_volume(paper), "1")
        self.assertEqual(paper_page(paper), "20")
        self.assertIn("Quantum Frontiers 1, 20", citation_label(paper))

    def test_qeios_doi_prefix_sets_journal_name(self):
        paper = normalize_crossref_item(
            {
                "DOI": "10.32388/ABCDE1",
                "title": ["A Qeios paper"],
                "container-title": [],
                "issued": {"date-parts": [[2025]]},
                "type": "journal-article",
            },
            "[]",
        )
        self.assertEqual(paper["journal"], "Qeios")

    def test_chinese_google_scholar_authors_split(self):
        self.assertEqual(google_scholar_author_names("孔令元，丁洪"), ["孔令元", "丁洪"])
        self.assertEqual(authors_from_google_scholar({"authors": ["孔令元， 丁洪"]}), ["孔令元", "丁洪"])
        self.assertEqual(full_author_names({"raw_json": '{"source":"google-scholar","authors":["孔令元， 丁洪"]}'}), ["孔令元", "丁洪"])
        self.assertEqual(parse_manual_author_list("孔令元；丁洪"), ["孔令元", "丁洪"])


if __name__ == "__main__":
    unittest.main()
