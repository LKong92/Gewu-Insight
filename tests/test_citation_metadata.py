import json
import unittest

from paper_monitor.ui_server import (
    author_details_summary,
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
    def test_author_details_use_openalex_affiliations_when_pubmed_is_unavailable(self):
        paper = {
            "raw_json": json.dumps({
                "authorships": [
                    {
                        "author": {"display_name": "Ada Author"},
                        "raw_affiliation_strings": ["Quantum Institute"],
                        "institutions": [{"display_name": "Example University"}],
                    }
                ]
            }),
        }
        summary = author_details_summary(paper)
        self.assertEqual(summary["sources"], ["openalex"])
        self.assertEqual(
            summary["author_affiliations"][0]["affiliations"],
            ["Quantum Institute", "Example University"],
        )
        self.assertFalse(summary["author_affiliations"][0]["roles"]["corresponding_author"])

    def test_author_details_use_crossref_affiliations_when_available(self):
        paper = {
            "raw_json": json.dumps({
                "crossref": {
                    "author": [
                        {
                            "given": "Ada",
                            "family": "Author",
                            "affiliation": [{"name": "Crossref Laboratory"}],
                        }
                    ]
                }
            }),
        }
        summary = author_details_summary(paper)
        self.assertEqual(summary["sources"], ["crossref"])
        self.assertEqual(
            summary["author_affiliations"][0]["affiliations"],
            ["Crossref Laboratory"],
        )

    def test_author_details_keep_pubmed_roles_and_prefer_pubmed_affiliation(self):
        paper = {
            "raw_json": json.dumps({
                "authors": ["Ada Author"],
                "pubmed": {
                    "author_affiliations": [
                        {
                            "name": "Ada Author",
                            "affiliations": ["PubMed Institute"],
                            "roles": {
                                "co_first_author": True,
                                "corresponding_author": True,
                                "notes": ["equal contribution", "corresponding author"],
                            },
                        }
                    ]
                },
                "authorships": [
                    {
                        "author": {"display_name": "Ada Author"},
                        "raw_affiliation_strings": ["OpenAlex Institute"],
                    }
                ],
            }),
        }
        summary = author_details_summary(paper)
        detail = summary["author_affiliations"][0]
        self.assertEqual(detail["affiliations"], ["PubMed Institute", "OpenAlex Institute"])
        self.assertTrue(detail["roles"]["co_first_author"])
        self.assertTrue(detail["roles"]["corresponding_author"])

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
