import unittest
import tempfile
from datetime import date
from pathlib import Path

from paper_monitor.storage import Storage
from paper_monitor.ui_server import (
    ELECTRIDE_RECOMMENDED_KEYWORDS,
    missing_theme_group_keys_for_date,
    recommend_theme_keywords,
    theme_candidate_in_window,
    theme_candidate_is_literature_like,
    theme_counts_for_month,
    theme_paper_to_api,
)


class ThemeMonitorTest(unittest.TestCase):
    def test_zenodo_dataset_is_not_literature_like(self):
        paper = {
            "doi": "10.5281/zenodo.14503029",
            "journal": "Zenodo",
            "url": "https://doi.org/10.5281/zenodo.14503029",
            "type": "dataset",
            "raw": {
                "type": "dataset",
                "primary_location": {
                    "source": {
                        "display_name": "Zenodo (CERN European Organization for Nuclear Research)",
                        "type": "repository",
                    }
                },
            },
        }
        self.assertFalse(theme_candidate_is_literature_like(paper))

    def test_journal_article_is_literature_like(self):
        paper = {
            "doi": "10.1000/example",
            "journal": "Journal of Example Materials",
            "type_crossref": "journal-article",
            "raw": {"type": "article"},
        }
        self.assertTrue(theme_candidate_is_literature_like(paper))

    def test_single_day_window_requires_exact_publication_date(self):
        selected = date(2026, 6, 2)
        self.assertTrue(theme_candidate_in_window({"publication_date": "2026-06-02"}, selected, selected))
        self.assertFalse(theme_candidate_in_window({"publication_date": "2026-06"}, selected, selected))
        self.assertFalse(theme_candidate_in_window({"publication_date": "2026"}, selected, selected))
        self.assertFalse(theme_candidate_in_window({"publication_date": ""}, selected, selected))

    def test_month_count_and_list_ignore_year_only_cached_theme_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "paper_monitor.sqlite")
            try:
                year_only = {
                    "paper_id": "doi_year_only",
                    "doi": "10.1000/year-only",
                    "title": "Towards intermediate band solar cells based on example",
                    "journal": "Example Journal",
                    "publication_date": "2026",
                    "abstract": "",
                    "url": "https://doi.org/10.1000/year-only",
                    "source": "crossref",
                    "type_crossref": "journal-article",
                    "section_allowed": True,
                }
                exact = {
                    **year_only,
                    "paper_id": "doi_exact",
                    "doi": "10.1000/exact",
                    "title": "Intermediate band solar cell with exact date",
                    "publication_date": "2026-06-02",
                    "url": "https://doi.org/10.1000/exact",
                }
                storage.upsert_paper(year_only)
                storage.upsert_paper(exact)
                for paper_id in ["doi_year_only", "doi_exact"]:
                    storage.record_theme_result(
                        paper_id=paper_id,
                        group_key="ibsc",
                        group_name="Intermediate band solar cell",
                        query="intermediate band solar cell",
                        score=2,
                        hits=["intermediate band solar cell"],
                        window_start="2026-06-02",
                        window_end="2026-06-02",
                    )
                papers = storage.list_theme_papers(
                    window_start="2026-06-02",
                    window_end="2026-06-02",
                    group_keys=["ibsc"],
                )
                self.assertEqual([paper["paper_id"] for paper in papers], ["doi_exact"])
                counts = theme_counts_for_month(storage, prefix="2026-06-", group_keys=["ibsc"])
                self.assertEqual(counts.get("2026-06-02", {}).get("ibsc"), 1)
            finally:
                storage.close()

    def test_month_count_matches_deduplicated_theme_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "paper_monitor.sqlite")
            try:
                first = {
                    "paper_id": "doi_first",
                    "doi": "10.1000/first",
                    "title": "Duplicate electride title",
                    "journal": "Example Journal",
                    "publication_date": "2026-05-29",
                    "abstract": "Electride example.",
                    "url": "https://doi.org/10.1000/first",
                    "source": "crossref",
                    "type_crossref": "journal-article",
                    "section_allowed": True,
                }
                second = {
                    **first,
                    "paper_id": "doi_second",
                    "doi": "10.1000/second",
                    "url": "https://doi.org/10.1000/second",
                }
                storage.upsert_paper(first)
                storage.upsert_paper(second)
                for paper_id in ["doi_first", "doi_second"]:
                    storage.record_theme_result(
                        paper_id=paper_id,
                        group_key="electride",
                        group_name="Electride",
                        query="electride",
                        score=2,
                        hits=["electride"],
                        window_start="2026-05-29",
                        window_end="2026-05-29",
                    )
                papers = storage.list_theme_papers(
                    window_start="2026-05-29",
                    window_end="2026-05-29",
                    group_keys=["electride"],
                )
                self.assertEqual(len(papers), 1)
                counts = theme_counts_for_month(storage, prefix="2026-05-", group_keys=["electride"])
                self.assertEqual(counts.get("2026-05-29", {}).get("electride"), 1)
            finally:
                storage.close()

    def test_missing_theme_group_keys_skip_completed_and_present_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "paper_monitor.sqlite")
            try:
                storage.record_fetch_run(
                    monitor_type="theme",
                    source="multi",
                    journal="theme:electride",
                    window_start="2026-06-02",
                    window_end="2026-06-02",
                    status="empty",
                    records_found=0,
                    started_at="2026-06-02T09:00:00+09:00",
                )
                storage.upsert_paper(
                    {
                        "paper_id": "doi_ibsc",
                        "doi": "10.1000/ibsc",
                        "title": "Intermediate band solar cell with exact date",
                        "journal": "Example Journal",
                        "publication_date": "2026-06-02",
                        "abstract": "",
                        "url": "https://doi.org/10.1000/ibsc",
                        "source": "crossref",
                        "type_crossref": "journal-article",
                        "section_allowed": True,
                    }
                )
                storage.record_theme_result(
                    paper_id="doi_ibsc",
                    group_key="ibsc",
                    group_name="Intermediate band solar cell",
                    query="intermediate band solar cell",
                    score=2,
                    hits=["intermediate band solar cell"],
                    window_start="2026-06-02",
                    window_end="2026-06-02",
                )
                missing = missing_theme_group_keys_for_date(
                    storage,
                    "2026-06-02",
                    ["electride", "ibsc", "perovskite"],
                )
                self.assertEqual(missing, ["perovskite"])
            finally:
                storage.close()

    def test_theme_hit_chips_omit_group_name_duplicates(self):
        paper = {
            "paper_id": "p1",
            "title": "Example",
            "journal": "Example Journal",
            "theme_score": 2,
            "theme_groups": [{"key": "ibsc", "name": "Intermediate band solar cell"}],
            "theme_hits": ["intermediate band solar cell", "quantum dot intermediate band"],
        }
        item = theme_paper_to_api(paper)
        self.assertEqual(item["theme_hits"], ["quantum dot intermediate band"])

    def test_theme_hit_chips_convert_legacy_regex_hits(self):
        paper = {
            "paper_id": "p1",
            "title": "Example",
            "journal": "Example Journal",
            "theme_score": 6,
            "theme_groups": [{"key": "electride", "name": "Electride"}],
            "theme_hits": [
                r"(?<![A-Za-z0-9])(?:electride|electrides)(?![A-Za-z0-9])",
                r"(?<![A-Za-z0-9])anionic\s+(?:electrons|electron)(?![A-Za-z0-9])",
            ],
        }
        item = theme_paper_to_api(paper)
        self.assertEqual(item["theme_hits"], ["anionic electrons"])

    def test_curated_electride_recommendations_show_existing_keywords_too(self):
        result = recommend_theme_keywords(
            "Electride",
            existing_keywords=[
                "electride",
                "interstitial electron",
                "C12A7:e",
                "anionic electrons",
                "cage electron",
                "electrene",
            ],
        )
        keywords = [item["keyword"] for item in result["recommendations"]]
        self.assertEqual(keywords, ELECTRIDE_RECOMMENDED_KEYWORDS)


if __name__ == "__main__":
    unittest.main()
