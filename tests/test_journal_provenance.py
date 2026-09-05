import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from paper_monitor.config import AppConfig, JournalConfig
from paper_monitor.monitor import fetch_one_journal
from paper_monitor.storage import STORAGE_SCHEMA_VERSION, Storage


WINDOW_START = "2026-08-20"
WINDOW_END = "2026-08-21"


def canonical_paper(
    *,
    paper_id: str = "doi_10.1000/journal-provenance",
    source: str = "crossref",
) -> dict:
    return {
        "paper_id": paper_id,
        "doi": "10.1000/journal-provenance",
        "title": "A canonical paper observed by three monitors",
        "journal": "Example Physics",
        "publication_date": WINDOW_END,
        "source": source,
        "type": "article",
        "type_crossref": "journal-article",
        "url": "https://example.org/articles/journal-provenance",
        "section_allowed": True,
    }


def start_journal_run(storage: Storage, *, started_at: str, journal: str = "Example Physics") -> int:
    return storage.start_fetch_run(
        monitor_type="journal",
        source="journal",
        journal=journal,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        started_at=started_at,
    )


class JournalMonitorProvenanceStorageTests(unittest.TestCase):
    def test_v9_database_migrates_losslessly_to_normalized_journal_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "paper_monitor.sqlite"
            storage = Storage(db_path)
            try:
                storage.upsert_paper(canonical_paper())
                storage.record_theme_candidate(
                    paper_id="doi_10.1000/journal-provenance",
                    source="openalex",
                    window_start=WINDOW_START,
                    window_end=WINDOW_END,
                    query_plan_hash="pre-migration-plan",
                )
            finally:
                storage.close()

            legacy = sqlite3.connect(db_path)
            try:
                legacy.execute("DROP TABLE journal_monitor_papers")
                legacy.execute("PRAGMA user_version = 9")
                legacy.commit()
            finally:
                legacy.close()

            migrated = Storage(db_path)
            try:
                schema_version = int(migrated.conn.execute("PRAGMA user_version").fetchone()[0])
                table_exists = migrated.conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'journal_monitor_papers'"
                ).fetchone()
                paper = migrated.get_paper("doi_10.1000/journal-provenance")
                theme_count = int(
                    migrated.conn.execute(
                        "SELECT COUNT(*) FROM theme_candidates WHERE paper_id = ?",
                        ("doi_10.1000/journal-provenance",),
                    ).fetchone()[0]
                )
                foreign_keys = {
                    (row[2], row[3], row[4], row[6])
                    for row in migrated.conn.execute(
                        "PRAGMA foreign_key_list(journal_monitor_papers)"
                    ).fetchall()
                }
            finally:
                migrated.close()

        self.assertEqual(schema_version, STORAGE_SCHEMA_VERSION)
        self.assertEqual(STORAGE_SCHEMA_VERSION, 16)
        self.assertIsNotNone(table_exists)
        self.assertIsNotNone(paper)
        self.assertEqual(paper["title"], "A canonical paper observed by three monitors")
        self.assertEqual(theme_count, 1)
        self.assertIn(("papers", "paper_id", "paper_id", "CASCADE"), foreign_keys)
        self.assertIn(("fetch_runs", "fetch_run_id", "id", "CASCADE"), foreign_keys)

    def test_repeated_observation_in_one_run_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "paper_monitor.sqlite")
            try:
                paper_id = "doi_10.1000/journal-provenance"
                storage.upsert_paper(canonical_paper(paper_id=paper_id))
                fetch_run_id = start_journal_run(storage, started_at="2026-08-21T09:00:00+08:00")
                with patch("paper_monitor.storage.now_iso", return_value="2026-08-21T09:01:00+08:00"):
                    storage.record_journal_monitor_papers(
                        fetch_run_id=fetch_run_id,
                        observations=[
                            {"paper_id": paper_id, "source": "crossref"},
                            {"paper_id": paper_id, "source": "crossref"},
                        ],
                    )
                with patch("paper_monitor.storage.now_iso", return_value="2026-08-21T09:02:00+08:00"):
                    storage.record_journal_monitor_paper(
                        fetch_run_id=fetch_run_id,
                        paper_id=paper_id,
                        source="crossref",
                    )
                rows = storage.list_journal_monitor_papers(fetch_run_id=fetch_run_id)
            finally:
                storage.close()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["paper_id"], paper_id)
        self.assertEqual(rows[0]["source"], "crossref")
        self.assertEqual(rows[0]["first_seen_at"], "2026-08-21T09:01:00+08:00")
        self.assertEqual(rows[0]["last_seen_at"], "2026-08-21T09:02:00+08:00")
        self.assertEqual(rows[0]["journal"], "Example Physics")
        self.assertEqual(rows[0]["window_start"], WINDOW_START)
        self.assertEqual(rows[0]["window_end"], WINDOW_END)

    def test_one_canonical_paper_can_be_linked_by_journal_subject_and_author(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "paper_monitor.sqlite")
            try:
                paper_id = "doi_10.1000/journal-provenance"
                storage.upsert_paper(canonical_paper(paper_id=paper_id))

                fetch_run_id = start_journal_run(storage, started_at="2026-08-21T10:00:00+08:00")
                storage.record_journal_monitor_paper(
                    fetch_run_id=fetch_run_id,
                    paper_id=paper_id,
                    source="crossref",
                )
                storage.record_theme_candidate(
                    paper_id=paper_id,
                    source="openalex",
                    window_start=WINDOW_START,
                    window_end=WINDOW_END,
                    query_plan_hash="three-axis-plan",
                )
                author = storage.add_author_monitor(
                    {
                        "user_id": "three-axis-author",
                        "name": "Example Author",
                        "url": "https://scholar.google.com/citations?user=three-axis-author",
                    }
                )
                storage.add_author_monitor_paper(
                    author_monitor_id=int(author["id"]),
                    paper_id=paper_id,
                    scholar_key="three-axis-paper",
                )

                joined = storage.conn.execute(
                    """
                    SELECT papers.paper_id
                    FROM papers
                    JOIN journal_monitor_papers AS journal_axis
                      ON journal_axis.paper_id = papers.paper_id
                    JOIN theme_candidates AS subject_axis
                      ON subject_axis.paper_id = papers.paper_id
                    JOIN author_monitor_papers AS author_axis
                      ON author_axis.paper_id = papers.paper_id
                    WHERE papers.paper_id = ?
                    """,
                    (paper_id,),
                ).fetchall()
            finally:
                storage.close()

        self.assertEqual([row["paper_id"] for row in joined], [paper_id])

    def test_multiple_runs_remain_distinct_and_foreign_key_deletes_cascade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "paper_monitor.sqlite")
            try:
                paper_id = "doi_10.1000/journal-provenance"
                storage.upsert_paper(canonical_paper(paper_id=paper_id))
                run_one = start_journal_run(storage, started_at="2026-08-21T11:00:00+08:00")
                run_two = start_journal_run(storage, started_at="2026-08-21T12:00:00+08:00")
                storage.record_journal_monitor_paper(
                    fetch_run_id=run_one,
                    paper_id=paper_id,
                    source="crossref",
                )
                storage.record_journal_monitor_paper(
                    fetch_run_id=run_two,
                    paper_id=paper_id,
                    source="crossref",
                )
                self.assertEqual(len(storage.list_journal_monitor_papers(paper_id=paper_id)), 2)

                storage.conn.execute("DELETE FROM fetch_runs WHERE id = ?", (run_one,))
                storage.conn.commit()
                after_run_delete = storage.list_journal_monitor_papers(paper_id=paper_id)

                storage.conn.execute("DELETE FROM papers WHERE paper_id = ?", (paper_id,))
                storage.conn.commit()
                after_paper_delete = storage.list_journal_monitor_papers(paper_id=paper_id)
                surviving_run_count = int(
                    storage.conn.execute(
                        "SELECT COUNT(*) FROM fetch_runs WHERE id = ?",
                        (run_two,),
                    ).fetchone()[0]
                )
            finally:
                storage.close()

        self.assertEqual([row["fetch_run_id"] for row in after_run_delete], [run_two])
        self.assertEqual(after_paper_delete, [])
        self.assertEqual(surviving_run_count, 1)


class JournalMonitorProvenanceIntegrationTests(unittest.TestCase):
    def test_fetch_one_journal_persists_crossref_and_openalex_paper_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "paper_monitor.sqlite")
            journal = JournalConfig(
                name="Example Physics",
                issns=["1234-5678"],
                openalex_source_id="S123456",
                section_policy="science",
                skip_landing_enrichment=True,
            )
            config = AppConfig(
                fetch_lookback_days=7,
                report_days=7,
                keep_unknown_sections=True,
                journals=[journal],
                section_policies={"science": {}},
            )
            crossref = canonical_paper(source="crossref")
            openalex = canonical_paper(source="openalex")
            openalex["abstract"] = "Metadata merged from OpenAlex."

            try:
                with (
                    patch("paper_monitor.monitor.fetch_crossref_journal", return_value=[crossref]) as crossref_fetch,
                    patch("paper_monitor.monitor.fetch_openalex_journal", return_value=[openalex]) as openalex_fetch,
                ):
                    summary = fetch_one_journal(
                        config=config,
                        storage=storage,
                        journal=journal,
                        start_date=date.fromisoformat(WINDOW_START),
                        end_date=date.fromisoformat(WINDOW_END),
                        enrich=False,
                    )

                run = storage.conn.execute(
                    "SELECT * FROM fetch_runs WHERE monitor_type = 'journal' ORDER BY id DESC LIMIT 1"
                ).fetchone()
                rows = storage.list_journal_monitor_papers(fetch_run_id=int(run["id"]))
                saved_paper = storage.get_paper("doi_10.1000/journal-provenance")
            finally:
                storage.close()

        self.assertEqual(summary["saved"], 1)
        self.assertEqual(summary["source_counts"], {"crossref": 1, "openalex": 1})
        self.assertEqual(summary["source_statuses"], {"crossref": "success", "openalex": "success"})
        self.assertEqual(run["source"], "journal")
        self.assertEqual(run["journal"], "Example Physics")
        self.assertEqual(run["window_start"], WINDOW_START)
        self.assertEqual(run["window_end"], WINDOW_END)
        self.assertEqual(run["status"], "success")
        self.assertEqual(run["records_found"], 1)
        self.assertEqual([row["source"] for row in rows], ["crossref", "openalex"])
        self.assertTrue(all(row["paper_id"] == saved_paper["paper_id"] for row in rows))
        crossref_fetch.assert_called_once()
        openalex_fetch.assert_called_once()

    def test_partial_failed_fetch_keeps_provenance_for_each_committed_paper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "paper_monitor.sqlite")
            journal = JournalConfig(
                name="Example Physics",
                issns=["1234-5678"],
                openalex_source_id=None,
                section_policy="science",
                skip_landing_enrichment=True,
            )
            config = AppConfig(
                fetch_lookback_days=7,
                report_days=7,
                keep_unknown_sections=True,
                journals=[journal],
                section_policies={"science": {}},
            )
            first = canonical_paper(paper_id="doi_10.1000/first-committed")
            first["doi"] = "10.1000/first-committed"
            second = canonical_paper(paper_id="doi_10.1000/second-fails")
            second["doi"] = "10.1000/second-fails"
            real_upsert = storage.upsert_paper

            def fail_second_upsert(paper: dict, **kwargs) -> None:
                if paper["paper_id"] == "doi_10.1000/second-fails":
                    raise RuntimeError("injected second-paper failure")
                real_upsert(paper, **kwargs)

            try:
                with (
                    patch(
                        "paper_monitor.monitor.fetch_crossref_journal",
                        return_value=[first, second],
                    ),
                    patch.object(storage, "upsert_paper", side_effect=fail_second_upsert),
                    self.assertRaisesRegex(RuntimeError, "second-paper failure"),
                ):
                    fetch_one_journal(
                        config=config,
                        storage=storage,
                        journal=journal,
                        start_date=date.fromisoformat(WINDOW_START),
                        end_date=date.fromisoformat(WINDOW_END),
                        enrich=False,
                    )

                run = storage.conn.execute(
                    "SELECT * FROM fetch_runs WHERE monitor_type = 'journal' ORDER BY id DESC LIMIT 1"
                ).fetchone()
                rows = storage.list_journal_monitor_papers(fetch_run_id=int(run["id"]))
                first_saved = storage.get_paper("doi_10.1000/first-committed")
                second_saved = storage.get_paper("doi_10.1000/second-fails")
            finally:
                storage.close()

        self.assertEqual(run["status"], "error")
        self.assertEqual(run["records_found"], 1)
        self.assertEqual(
            [(row["paper_id"], row["source"]) for row in rows],
            [("doi_10.1000/first-committed", "crossref")],
        )
        self.assertIsNotNone(first_saved)
        self.assertIsNone(second_saved)


if __name__ == "__main__":
    unittest.main()
