import unittest
import tempfile
import time
from datetime import date
from pathlib import Path

from paper_monitor.storage import Storage
from paper_monitor.ui_server import (
    ELECTRIDE_RECOMMENDED_KEYWORDS,
    add_theme_candidate,
    get_fetch_progress,
    missing_fetch_journals_for_date,
    missing_theme_group_keys_for_date,
    recommend_theme_keywords,
    theme_keyword_recommendation_response,
    run_theme_monitor,
    sanitize_theme_status_message,
    start_fetch_progress,
    start_theme_fetch_progress,
    theme_candidate_in_window,
    theme_candidate_is_literature_like,
    theme_counts_for_month,
    theme_fetch_error_message,
    theme_online_discovery_from_last_fetch,
    theme_paper_to_api,
)


def mock_theme_keyword_records(query):
    return [
        {
            "title": "Majorana zero modes for topological quantum computation",
            "abstract": "Non-Abelian anyon braiding enables fault tolerant quantum computation.",
            "keywords": ["Majorana zero mode", "non-Abelian anyon"],
        }
    ]


def slow_theme_keyword_records(query):
    time.sleep(5)
    return [{"title": "slow source result", "abstract": "", "keywords": ["slow keyword"]}]


def empty_theme_source_records(query, start_date, end_date):
    return []


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

    def test_zenodo_article_is_never_accepted_as_a_subject_candidate(self):
        paper = {
            "paper_id": "doi_zenodo_article",
            "doi": "10.5281/zenodo.14503029",
            "title": "Repository record presented as an article",
            "journal": "Example Journal",
            "url": "https://doi.org/10.5281/zenodo.14503029",
            "type": "article",
            "raw": {},
        }
        candidates = {}
        candidate_sources = {}
        candidate_queries = {}

        self.assertFalse(theme_candidate_is_literature_like(paper))
        add_theme_candidate(
            candidates,
            candidate_sources,
            candidate_queries,
            paper,
            source_name="openalex",
            query="repository record",
        )
        self.assertEqual(candidates, {})

    def test_cached_zenodo_subject_results_are_not_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "paper_monitor.sqlite")
            try:
                paper = {
                    "paper_id": "doi_cached_zenodo",
                    "doi": "10.5281/zenodo.14503029",
                    "title": "Cached Zenodo record",
                    "journal": "Zenodo",
                    "publication_date": "2026-06-02",
                    "url": "https://zenodo.org/records/14503029",
                    "source": "openalex",
                    "type": "article",
                    "section_allowed": True,
                }
                storage.upsert_paper(paper)
                storage.record_theme_result(
                    paper_id=paper["paper_id"],
                    group_key="electride",
                    group_name="Electride",
                    query="electride",
                    score=1,
                    hits=["electride"],
                    window_start="2026-06-02",
                    window_end="2026-06-02",
                )

                self.assertEqual(
                    storage.list_theme_papers(
                        window_start="2026-06-02",
                        window_end="2026-06-02",
                        group_keys=["electride"],
                    ),
                    [],
                )
            finally:
                storage.close()

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

    def test_missing_theme_group_keys_are_scoped_to_selected_subjects(self):
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
                missing = missing_theme_group_keys_for_date(
                    storage,
                    "2026-06-02",
                    ["nri"],
                )
                self.assertEqual(missing, ["nri"])
            finally:
                storage.close()

    def test_latest_theme_error_remains_missing_even_with_saved_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "paper_monitor.sqlite")
            try:
                storage.upsert_paper(
                    {
                        "paper_id": "doi_partial",
                        "doi": "10.1000/partial",
                        "title": "Partially fetched subject result",
                        "journal": "Example Journal",
                        "publication_date": "2026-06-02",
                        "abstract": "alpha",
                        "url": "https://doi.org/10.1000/partial",
                        "source": "crossref",
                        "type_crossref": "journal-article",
                        "section_allowed": True,
                    }
                )
                storage.record_theme_result(
                    paper_id="doi_partial",
                    group_key="partial",
                    group_name="Partial",
                    query="alpha",
                    score=2,
                    hits=["alpha"],
                    window_start="2026-06-02",
                    window_end="2026-06-02",
                )
                storage.record_fetch_run(
                    monitor_type="theme",
                    source="multi",
                    journal="theme:partial",
                    window_start="2026-06-02",
                    window_end="2026-06-02",
                    status="success",
                    records_found=1,
                    started_at="2026-06-02T09:00:00+09:00",
                )
                storage.record_fetch_run(
                    monitor_type="theme",
                    source="multi",
                    journal="theme:partial",
                    window_start="2026-06-02",
                    window_end="2026-06-02",
                    status="error",
                    records_found=1,
                    message="one source failed",
                    started_at="2026-06-02T10:00:00+09:00",
                )
                self.assertEqual(
                    missing_theme_group_keys_for_date(storage, "2026-06-02", ["partial"]),
                    ["partial"],
                )
            finally:
                storage.close()

    def test_theme_retry_runs_only_failed_query_source_tasks(self):
        import paper_monitor.ui_server as ui_server

        selected = date(2026, 6, 2)
        groups = {"partial": {"name": "Partial", "queries": ["alpha"]}}
        calls = []

        def successful_source(query, start_date, end_date):
            calls.append(("successful", query))
            return []

        def failing_source(query, start_date, end_date):
            calls.append(("failing", query))
            raise RuntimeError("temporary failure")

        original_fetchers = ui_server.theme_source_fetchers
        try:
            ui_server.theme_source_fetchers = lambda: [
                ("successful", successful_source),
                ("failing", failing_source),
            ]
            with tempfile.TemporaryDirectory() as tmp:
                storage = Storage(Path(tmp) / "paper_monitor.sqlite")
                try:
                    first = run_theme_monitor(
                        storage=storage,
                        start_date=selected,
                        end_date=selected,
                        group_keys=["partial"],
                        theme_groups=groups,
                    )
                    self.assertIn(
                        {"query": "alpha", "source": "failing"},
                        first["groups"]["partial"]["failed_tasks"],
                    )
                    storage.conn.execute(
                        "UPDATE theme_source_runs SET retry_after = ? WHERE source = ?",
                        ("2026-06-02T00:00:00+00:00", "failing"),
                    )
                    storage.conn.commit()
                    calls.clear()
                    ui_server.theme_source_fetchers = lambda: [
                        ("successful", successful_source),
                        ("failing", successful_source),
                    ]
                    second = run_theme_monitor(
                        storage=storage,
                        start_date=selected,
                        end_date=selected,
                        group_keys=["partial"],
                        theme_groups=groups,
                        retry_tasks_by_group={
                            "partial": [{"query": "alpha", "source": "failing"}],
                        },
                    )
                    self.assertEqual(calls, [("successful", "alpha")])
                    self.assertEqual(second["groups"]["partial"]["failed_tasks"], [])
                    self.assertEqual(missing_theme_group_keys_for_date(storage, selected.isoformat(), ["partial"]), [])
                finally:
                    storage.close()
        finally:
            ui_server.theme_source_fetchers = original_fetchers

    def test_subject_monitor_never_registers_arxiv_as_a_network_source(self):
        import paper_monitor.ui_server as ui_server

        self.assertNotIn("arxiv", [name for name, _fetcher in ui_server.theme_source_fetchers()])

    def test_zenodo_records_are_removed_at_the_network_source_boundary(self):
        import paper_monitor.ui_server as ui_server

        selected = date(2026, 6, 2)
        groups = {"quantum": {"name": "Quantum", "queries": ["quantum materials"]}}

        def zenodo_source(query, start_date, end_date):
            return [
                {
                    "paper_id": "doi_network_zenodo",
                    "doi": "10.5281/zenodo.14503029",
                    "title": "Zenodo record presented as an article",
                    "journal": "Example Journal",
                    "publication_date": selected.isoformat(),
                    "abstract": "Quantum materials repository record.",
                    "url": "https://doi.org/10.5281/zenodo.14503029",
                    "source": "mock_source",
                    "type": "journal-article",
                    "type_crossref": "journal-article",
                    "section_allowed": True,
                    "raw": {"type": "journal-article"},
                }
            ]

        original_fetchers = ui_server.theme_source_fetchers
        try:
            ui_server.theme_source_fetchers = lambda: [("mock_source", zenodo_source)]
            with tempfile.TemporaryDirectory() as tmp:
                storage = Storage(Path(tmp) / "paper_monitor.sqlite")
                try:
                    result = run_theme_monitor(
                        storage=storage,
                        start_date=selected,
                        end_date=selected,
                        group_keys=["quantum"],
                        theme_groups=groups,
                    )

                    self.assertEqual(result["source_counts"]["mock_source"], 0)
                    self.assertEqual(result["raw_results"], 0)
                    self.assertEqual(result["saved"], 0)
                    self.assertEqual(
                        storage.list_theme_papers(
                            window_start=selected.isoformat(),
                            window_end=selected.isoformat(),
                            group_keys=["quantum"],
                        ),
                        [],
                    )
                finally:
                    storage.close()
        finally:
            ui_server.theme_source_fetchers = original_fetchers

    def test_local_arxiv_is_matched_without_network_and_keeps_its_source(self):
        import paper_monitor.ui_server as ui_server

        selected = date(2026, 6, 2)
        groups = {"alpha": {"name": "Alpha", "queries": ["alpha phase"]}}
        original_fetchers = ui_server.theme_source_fetchers
        try:
            ui_server.theme_source_fetchers = lambda: []
            with tempfile.TemporaryDirectory() as tmp:
                storage = Storage(Path(tmp) / "paper_monitor.sqlite")
                try:
                    storage.upsert_paper(
                        {
                            "paper_id": "arxiv_local_alpha",
                            "doi": "",
                            "title": "Alpha phase in a local arXiv preprint",
                            "journal": "arXiv",
                            "publication_date": selected.isoformat(),
                            "abstract": "A local candidate.",
                            "url": "https://arxiv.org/abs/2606.00001",
                            "source": "arxiv",
                            "type": "preprint",
                            "section_allowed": True,
                            "raw": {"arxiv_id": "2606.00001"},
                        }
                    )
                    result = run_theme_monitor(
                        storage=storage,
                        start_date=selected,
                        end_date=selected,
                        group_keys=["alpha"],
                        theme_groups=groups,
                    )
                    self.assertEqual(result["groups"]["alpha"]["saved"], 1)
                    self.assertEqual(result["groups"]["alpha"]["status"], "success")
                    self.assertEqual(storage.get_paper("arxiv_local_alpha")["source"], "arxiv")
                finally:
                    storage.close()
        finally:
            ui_server.theme_source_fetchers = original_fetchers

    def test_remote_theme_winner_is_persisted_when_merged_with_local_arxiv(self):
        import paper_monitor.ui_server as ui_server

        selected = date(2026, 6, 2)
        title = "Quantum transport in a shared candidate"
        groups = {"quantum": {"name": "Quantum", "queries": ["quantum transport"]}}

        def openalex_source(query, start_date, end_date):
            return [
                {
                    "paper_id": "openalex_remote_winner",
                    "doi": "",
                    "title": title,
                    "journal": "Remote Journal",
                    "publication_date": selected.isoformat(),
                    "abstract": "A detailed abstract makes the remote candidate preferable.",
                    "url": "https://openalex.org/W123",
                    "source": "openalex",
                    "type": "journal-article",
                    "type_crossref": "journal-article",
                    "section_allowed": True,
                    "raw": {},
                }
            ]

        original_fetchers = ui_server.theme_source_fetchers
        try:
            ui_server.theme_source_fetchers = lambda: [("openalex", openalex_source)]
            with tempfile.TemporaryDirectory() as tmp:
                storage = Storage(Path(tmp) / "paper_monitor.sqlite")
                try:
                    storage.upsert_paper(
                        {
                            "paper_id": "arxiv_local_candidate",
                            "doi": "",
                            "title": title,
                            "journal": "arXiv",
                            "publication_date": selected.isoformat(),
                            "abstract": "",
                            "url": "https://arxiv.org/abs/2606.00001",
                            "source": "arxiv",
                            "type": "preprint",
                            "section_allowed": True,
                            "raw": {},
                        }
                    )

                    result = run_theme_monitor(
                        storage=storage,
                        start_date=selected,
                        end_date=selected,
                        group_keys=["quantum"],
                        theme_groups=groups,
                    )

                    self.assertEqual(result["groups"]["quantum"]["saved"], 1)
                    self.assertIsNotNone(storage.get_paper("openalex_remote_winner"))
                    self.assertIsNotNone(storage.get_paper("arxiv_local_candidate"))
                    rows = storage.conn.execute(
                        """
                        SELECT paper_id, source
                        FROM theme_candidates
                        WHERE window_start = ? AND window_end = ?
                        ORDER BY source
                        """,
                        (selected.isoformat(), selected.isoformat()),
                    ).fetchall()
                    self.assertEqual(
                        [(row["paper_id"], row["source"]) for row in rows],
                        [
                            ("openalex_remote_winner", "local_arxiv"),
                            ("openalex_remote_winner", "openalex"),
                        ],
                    )
                    orphan_count = storage.conn.execute(
                        """
                        SELECT COUNT(*) AS count
                        FROM theme_candidates
                        LEFT JOIN papers ON papers.paper_id = theme_candidates.paper_id
                        WHERE papers.paper_id IS NULL
                        """
                    ).fetchone()["count"]
                    self.assertEqual(orphan_count, 0)
                finally:
                    storage.close()
        finally:
            ui_server.theme_source_fetchers = original_fetchers

    def test_existing_local_theme_winner_does_not_add_a_duplicate_sighting(self):
        import paper_monitor.ui_server as ui_server

        selected = date(2026, 6, 2)
        title = "Quantum transport with a complete local record"
        groups = {"quantum": {"name": "Quantum", "queries": ["quantum transport"]}}

        def openalex_source(query, start_date, end_date):
            return [
                {
                    "paper_id": "openalex_lower_quality",
                    "doi": "",
                    "title": title,
                    "journal": "Remote Journal",
                    "publication_date": selected.isoformat(),
                    "abstract": "",
                    "url": "https://openalex.org/W456",
                    "source": "openalex",
                    "type": "journal-article",
                    "type_crossref": "journal-article",
                    "section_allowed": True,
                    "raw": {},
                }
            ]

        original_fetchers = ui_server.theme_source_fetchers
        try:
            ui_server.theme_source_fetchers = lambda: [("openalex", openalex_source)]
            with tempfile.TemporaryDirectory() as tmp:
                storage = Storage(Path(tmp) / "paper_monitor.sqlite")
                try:
                    storage.upsert_paper(
                        {
                            "paper_id": "arxiv_local_winner",
                            "doi": "",
                            "title": title,
                            "journal": "arXiv",
                            "publication_date": selected.isoformat(),
                            "abstract": "The complete local abstract keeps this candidate preferred.",
                            "url": "https://arxiv.org/abs/2606.00002",
                            "pdf_url": "https://arxiv.org/pdf/2606.00002",
                            "source": "arxiv",
                            "type": "preprint",
                            "section_allowed": True,
                            "raw": {},
                        }
                    )
                    self.assertEqual(storage.get_paper("arxiv_local_winner")["source_count"], 1)

                    run_theme_monitor(
                        storage=storage,
                        start_date=selected,
                        end_date=selected,
                        group_keys=["quantum"],
                        theme_groups=groups,
                    )

                    self.assertEqual(storage.get_paper("arxiv_local_winner")["source_count"], 1)
                    self.assertIsNone(storage.get_paper("openalex_lower_quality"))
                    rows = storage.conn.execute(
                        """
                        SELECT DISTINCT paper_id, source
                        FROM theme_candidates
                        WHERE window_start = ? AND window_end = ?
                        ORDER BY source
                        """,
                        (selected.isoformat(), selected.isoformat()),
                    ).fetchall()
                    self.assertEqual(
                        [(row["paper_id"], row["source"]) for row in rows],
                        [
                            ("arxiv_local_winner", "local_arxiv"),
                            ("arxiv_local_winner", "openalex"),
                        ],
                    )
                finally:
                    storage.close()
        finally:
            ui_server.theme_source_fetchers = original_fetchers

    def test_local_aps_rss_augments_existing_online_subject_sources(self):
        import paper_monitor.ui_server as ui_server

        selected = date(2026, 8, 1)
        groups = {"quantum": {"name": "Quantum Materials", "queries": ["quantum materials"]}}
        calls = []

        def online_source(query, start_date, end_date):
            calls.append(query)
            return [
                {
                    "paper_id": "doi_online_subject",
                    "doi": "10.1000/online-subject",
                    "title": "An online quantum materials result",
                    "journal": "Online Journal",
                    "publication_date": selected.isoformat(),
                    "abstract": "Quantum materials from the existing online source.",
                    "url": "https://doi.org/10.1000/online-subject",
                    "source": "online_source",
                    "type": "journal-article",
                    "type_crossref": "journal-article",
                    "section_allowed": True,
                    "raw": {"type": "journal-article"},
                }
            ]

        original_fetchers = ui_server.theme_source_fetchers
        try:
            ui_server.theme_source_fetchers = lambda: [("online_source", online_source)]
            with tempfile.TemporaryDirectory() as tmp:
                storage = Storage(Path(tmp) / "paper_monitor.sqlite")
                try:
                    local = {
                        "paper_id": "doi_aps_subject",
                        "doi": "10.1103/aps-subject",
                        "title": "A local APS RSS quantum materials result",
                        "journal": "Physical Review Materials",
                        "publication_date": selected.isoformat(),
                        "abstract": "Quantum materials from the shared APS RSS cache.",
                        "url": "https://doi.org/10.1103/aps-subject",
                        "source": "aps_rss",
                        "type": "journal-article",
                        "type_crossref": "journal-article",
                        "publisher_section": "published",
                        "section_allowed": True,
                        "raw": {"type": "journal-article", "_paper_monitor_sources": ["aps_rss"]},
                    }
                    storage.record_aps_rss_feed(
                        journal_slug="prmaterials",
                        journal_name="Physical Review Materials",
                        status="success",
                        entry_count=1,
                        success=True,
                    )
                    storage.upsert_paper(local)
                    storage.record_aps_rss_entries("prmaterials", [local])

                    result = run_theme_monitor(
                        storage=storage,
                        start_date=selected,
                        end_date=selected,
                        group_keys=["quantum"],
                        theme_groups=groups,
                    )

                    self.assertEqual(calls, ["quantum materials"])
                    self.assertEqual(result["source_counts"]["local_aps_rss"], 1)
                    self.assertEqual(result["source_counts"]["online_source"], 1)
                    papers = storage.list_theme_papers(
                        window_start=selected.isoformat(),
                        window_end=selected.isoformat(),
                        group_keys=["quantum"],
                    )
                    self.assertEqual({paper["paper_id"] for paper in papers}, {"doi_aps_subject", "doi_online_subject"})
                finally:
                    storage.close()
        finally:
            ui_server.theme_source_fetchers = original_fetchers

    def test_network_query_plan_is_bounded_and_does_not_expand_surface_variants(self):
        import paper_monitor.ui_server as ui_server

        selected = date(2026, 6, 2)
        groups = {
            f"group_{index}": {
                "name": f"Group {index}",
                "queries": [f"topic {index} keyword {variant}" for variant in range(14)],
            }
            for index in range(5)
        }
        calls = []

        def empty_source(query, start_date, end_date):
            calls.append(query)
            return []

        original_fetchers = ui_server.theme_source_fetchers
        try:
            ui_server.theme_source_fetchers = lambda: [("bounded_source", empty_source)]
            with tempfile.TemporaryDirectory() as tmp:
                storage = Storage(Path(tmp) / "paper_monitor.sqlite")
                try:
                    run_theme_monitor(
                        storage=storage,
                        start_date=selected,
                        end_date=selected,
                        group_keys=list(groups),
                        theme_groups=groups,
                    )
                finally:
                    storage.close()
        finally:
            ui_server.theme_source_fetchers = original_fetchers
        self.assertLessEqual(len(calls), ui_server.THEME_NETWORK_QUERIES_PER_SOURCE_RUN)
        self.assertEqual(len(calls), len(set(calls)))

    def test_partial_source_failure_keeps_saved_papers_and_reports_partial(self):
        import paper_monitor.ui_server as ui_server

        selected = date(2026, 6, 2)
        groups = {"alpha": {"name": "Alpha", "queries": ["alpha"]}}

        def successful_source(query, start_date, end_date):
            return [
                {
                    "paper_id": "doi_alpha_partial",
                    "doi": "10.1000/alpha-partial",
                    "title": "Alpha candidate",
                    "journal": "Example Journal",
                    "publication_date": selected.isoformat(),
                    "abstract": "alpha",
                    "url": "https://doi.org/10.1000/alpha-partial",
                    "source": "successful_source",
                    "type_crossref": "journal-article",
                    "section_allowed": True,
                }
            ]

        calls = []

        def limited_source(query, start_date, end_date):
            calls.append(query)
            raise RuntimeError("429 Too Many Requests")

        original_fetchers = ui_server.theme_source_fetchers
        try:
            ui_server.theme_source_fetchers = lambda: [
                ("successful_source", successful_source),
                ("limited_source", limited_source),
            ]
            with tempfile.TemporaryDirectory() as tmp:
                storage = Storage(Path(tmp) / "paper_monitor.sqlite")
                try:
                    first = run_theme_monitor(
                        storage=storage,
                        start_date=selected,
                        end_date=selected,
                        group_keys=["alpha"],
                        theme_groups=groups,
                    )
                    second = run_theme_monitor(
                        storage=storage,
                        start_date=selected,
                        end_date=selected,
                        group_keys=["alpha"],
                        theme_groups=groups,
                    )
                    self.assertEqual(first["groups"]["alpha"]["status"], "partial")
                    self.assertEqual(first["groups"]["alpha"]["saved"], 1)
                    self.assertEqual(second["groups"]["alpha"]["source_statuses"]["limited_source"], "cooldown")
                    self.assertEqual(calls, ["alpha"])
                finally:
                    storage.close()
        finally:
            ui_server.theme_source_fetchers = original_fetchers

    def test_all_online_sources_in_cooldown_are_deferred_not_completed(self):
        import paper_monitor.ui_server as ui_server

        selected = date(2026, 6, 2)
        groups = {"alpha": {"name": "Alpha", "queries": ["alpha"]}}
        calls = []

        def limited_source(query, start_date, end_date):
            calls.append(query)
            raise RuntimeError("429 Too Many Requests")

        original_fetchers = ui_server.theme_source_fetchers
        try:
            ui_server.theme_source_fetchers = lambda: [("limited_source", limited_source)]
            with tempfile.TemporaryDirectory() as tmp:
                storage = Storage(Path(tmp) / "paper_monitor.sqlite")
                try:
                    run_theme_monitor(
                        storage=storage,
                        start_date=selected,
                        end_date=selected,
                        group_keys=["alpha"],
                        theme_groups=groups,
                        trigger="manual",
                    )
                    second = run_theme_monitor(
                        storage=storage,
                        start_date=selected,
                        end_date=selected,
                        group_keys=["alpha"],
                        theme_groups=groups,
                        trigger="manual",
                    )

                    self.assertEqual(calls, ["alpha"])
                    self.assertEqual(second["groups"]["alpha"]["status"], "deferred")
                    self.assertEqual(second["online_discovery"]["status"], "deferred")
                    self.assertEqual(second["online_discovery"]["queries_attempted"], 0)
                    self.assertIn("local cached papers", second["online_discovery"]["message"])
                    self.assertEqual(
                        missing_theme_group_keys_for_date(storage, selected.isoformat(), ["alpha"]),
                        ["alpha"],
                    )
                finally:
                    storage.close()
        finally:
            ui_server.theme_source_fetchers = original_fetchers

    def test_deferred_discovery_survives_cached_report_reload(self):
        discovery = theme_online_discovery_from_last_fetch(
            {
                "groups": {
                    "alpha": {"status": "deferred"},
                    "beta": {"status": "deferred"},
                }
            }
        )

        self.assertEqual(discovery["status"], "deferred")
        self.assertEqual(discovery["queries_attempted"], 0)

    def test_theme_fetch_errors_do_not_persist_request_credentials(self):
        message = theme_fetch_error_message(
            "Subject Monitor",
            RuntimeError("connection failed for https://example.test/?api_key=do-not-store-this"),
            source_name="openalex",
        )

        self.assertEqual(message, "Subject Monitor/openalex: network connection failed.")
        self.assertNotIn("do-not-store-this", message)
        self.assertEqual(
            sanitize_theme_status_message("request failed: api_key=do-not-show-this&query=alpha"),
            "request failed: api_key=[redacted]&query=alpha",
        )

    def test_on_demand_refresh_reuses_completed_source_plan(self):
        import paper_monitor.ui_server as ui_server

        selected = date(2026, 6, 2)
        groups = {"alpha": {"name": "Alpha", "queries": ["alpha"]}}
        calls = []

        def successful_source(query, start_date, end_date):
            calls.append(query)
            return []

        original_fetchers = ui_server.theme_source_fetchers
        try:
            ui_server.theme_source_fetchers = lambda: [("cached_source", successful_source)]
            with tempfile.TemporaryDirectory() as tmp:
                storage = Storage(Path(tmp) / "paper_monitor.sqlite")
                try:
                    run_theme_monitor(
                        storage=storage,
                        start_date=selected,
                        end_date=selected,
                        group_keys=["alpha"],
                        theme_groups=groups,
                        trigger="on_demand",
                    )
                    run_theme_monitor(
                        storage=storage,
                        start_date=selected,
                        end_date=selected,
                        group_keys=["alpha"],
                        theme_groups=groups,
                        trigger="on_demand",
                    )
                finally:
                    storage.close()
        finally:
            ui_server.theme_source_fetchers = original_fetchers
        self.assertEqual(calls, ["alpha"])

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

    def test_theme_fetch_progress_tracks_each_subject(self):
        import paper_monitor.ui_server as ui_server

        selected = date(2026, 1, 3)
        groups = {
            "one": {"name": "Subject One", "queries": ["alpha"]},
            "two": {"name": "Subject Two", "queries": ["beta"]},
        }
        original_fetchers = ui_server.theme_source_fetchers
        try:
            ui_server.theme_source_fetchers = lambda: [("mock_source", empty_theme_source_records)]
            with tempfile.TemporaryDirectory() as tmp:
                storage = Storage(Path(tmp) / "paper_monitor.sqlite")
                try:
                    run_theme_monitor(storage=storage, start_date=selected, end_date=selected, group_keys=["one", "two"], theme_groups=groups)
                finally:
                    storage.close()
        finally:
            ui_server.theme_source_fetchers = original_fetchers
        progress = get_fetch_progress(selected.isoformat())
        self.assertEqual(progress["kind"], "theme")
        self.assertFalse(progress["active"])
        self.assertEqual(progress["completed"], 2)
        self.assertEqual(progress["total"], 2)
        statuses = {item["key"]: item["status"] for item in progress["subjects"]}
        self.assertEqual(statuses, {"one": "empty", "two": "empty"})

    def test_fetch_progress_keeps_journal_and_theme_separate(self):
        selected = "2026-01-04"
        start_fetch_progress(selected, ["Nature"])
        start_theme_fetch_progress(selected, ["one"], {"one": {"name": "Subject One"}})

        journal_progress = get_fetch_progress(selected, kind="journal")
        theme_progress = get_fetch_progress(selected, kind="theme")

        self.assertEqual(journal_progress["kind"], "journal")
        self.assertEqual(journal_progress["total"], 1)
        self.assertEqual(theme_progress["kind"], "theme")
        self.assertEqual(theme_progress["total"], 1)
        self.assertEqual(theme_progress["subjects"][0]["name"], "Subject One")

    def test_journal_fetch_error_is_still_missing(self):
        selected = "2026-01-05"
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "paper_monitor.sqlite")
            try:
                run_id = storage.start_fetch_run(
                    monitor_type="journal",
                    source="journal",
                    journal="Nature",
                    window_start=selected,
                    window_end=selected,
                    started_at="2026-01-05T09:00:00+09:00",
                )
                storage.finish_fetch_run(run_id, status="error", records_found=0, message="network failed")
                self.assertEqual(missing_fetch_journals_for_date(storage, selected, ["Nature"]), ["Nature"])
            finally:
                storage.close()

    def test_keyword_recommendations_come_from_external_fetchers(self):
        import paper_monitor.ui_server as ui_server

        original_fetchers = ui_server.theme_keyword_recommendation_fetchers
        try:
            ui_server.theme_keyword_recommendation_fetchers = lambda: [("mock_source", mock_theme_keyword_records)]
            result = recommend_theme_keywords("Topological quantum computing", existing_keywords=[])
        finally:
            ui_server.theme_keyword_recommendation_fetchers = original_fetchers
        keywords = [item["keyword"] for item in result["recommendations"]]
        self.assertIn("non-Abelian anyon", keywords)
        self.assertTrue(all("mock_source" in item["sources"] for item in result["recommendations"]))

    def test_slow_keyword_recommendation_source_times_out(self):
        import paper_monitor.ui_server as ui_server

        original_fetchers = ui_server.theme_keyword_recommendation_fetchers
        original_timeout = ui_server.THEME_KEYWORD_RECOMMENDATION_TIMEOUT_SECONDS
        try:
            ui_server.theme_keyword_recommendation_fetchers = lambda: [("slow_source", slow_theme_keyword_records)]
            ui_server.THEME_KEYWORD_RECOMMENDATION_TIMEOUT_SECONDS = 0.2
            start = time.monotonic()
            result = recommend_theme_keywords("Topological quantum computing", existing_keywords=[])
        finally:
            ui_server.theme_keyword_recommendation_fetchers = original_fetchers
            ui_server.THEME_KEYWORD_RECOMMENDATION_TIMEOUT_SECONDS = original_timeout
        self.assertLess(time.monotonic() - start, 2.0)
        self.assertEqual(result["recommendations"], [])
        self.assertIn("slow_source: timed out", result["errors"])

    def test_large_keyword_candidate_set_is_bounded_before_deduplication(self):
        candidates = {
            f"candidate material phase {index}": {
                "keyword": f"candidate material phase {index}",
                "score": float(10000 - index),
                "sources": {"mock_source"},
            }
            for index in range(10000)
        }

        start = time.monotonic()
        result = theme_keyword_recommendation_response(
            "Example material",
            ["Example material"],
            {"mock_source": 10000},
            candidates,
            [],
            [],
            24,
        )

        self.assertLess(time.monotonic() - start, 2.0)
        self.assertLessEqual(len(result["recommendations"]), 24)


if __name__ == "__main__":
    unittest.main()
