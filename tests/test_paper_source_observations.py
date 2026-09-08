from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from paper_monitor import ui_server
from paper_monitor.storage import STORAGE_SCHEMA_VERSION, Storage


PAPER_ID = "doi_10.1000/product-provenance"
WINDOW_START = "2026-08-20"
WINDOW_END = "2026-08-21"


def paper_payload(source: str, *, paper_id: str = PAPER_ID, title: str = "Canonical work") -> dict:
    return {
        "paper_id": paper_id,
        "doi": "10.1000/product-provenance",
        "title": title,
        "journal": "Example Physics",
        "publication_date": WINDOW_END,
        "abstract": "",
        "url": "https://example.org/product-provenance",
        "source": source,
        "type": "journal-article",
        "type_crossref": "journal-article",
        "section_allowed": True,
        "raw": {"_paper_monitor_sources": [source]},
    }


def raw_sources(paper: dict) -> list[str]:
    raw = json.loads(str(paper.get("raw_json") or "{}"))
    return list(raw.get("_paper_monitor_sources") or [])


class PaperSourceObservationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.temporary.name) / "paper_monitor.sqlite")
        self.author_id: int | None = None

    def tearDown(self) -> None:
        self.storage.close()
        self.temporary.cleanup()

    def ensure_paper(self, source: str) -> None:
        if not self.storage.get_paper(PAPER_ID):
            self.storage.upsert_paper(paper_payload(source))

    def observe_subject(self) -> None:
        self.ensure_paper("subject")
        self.storage.record_theme_candidate(
            paper_id=PAPER_ID,
            source="product_test_source",
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            query_plan_hash="product-provenance-plan",
        )

    def refresh_from_journal(self) -> None:
        self.ensure_paper("journal")
        existing = self.storage.get_paper(PAPER_ID)
        refreshed = paper_payload("journal", title="Canonical work refreshed by Journal Monitor")
        refreshed["raw"] = {
            "volume": "42",
            "_paper_monitor_sources": ["journal"],
        }
        merged = ui_server.merge_refreshed_metadata(existing, refreshed)
        self.storage.refresh_paper_metadata(PAPER_ID, merged)
        run_id = self.storage.start_fetch_run(
            monitor_type="journal",
            source="journal",
            journal="Example Physics",
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            started_at="2026-08-21T10:00:00+08:00",
        )
        self.storage.record_journal_monitor_paper(
            fetch_run_id=run_id,
            paper_id=PAPER_ID,
            source="crossref",
        )

    def observe_author(self) -> None:
        self.ensure_paper("author")
        if self.author_id is None:
            author = self.storage.add_author_monitor(
                {
                    "user_id": "product-provenance-author",
                    "name": "Product Test Author",
                    "url": "https://scholar.google.com/citations?user=product-provenance-author",
                }
            )
            self.author_id = int(author["id"])
        self.storage.add_author_monitor_paper(
            author_monitor_id=self.author_id,
            paper_id=PAPER_ID,
            scholar_key="product-provenance-paper",
        )

    def assert_three_monitor_sources(self, expected_order: list[str]) -> None:
        paper = self.storage.get_paper(PAPER_ID)
        observations = self.storage.list_paper_source_observations(PAPER_ID)
        monitor_names = [
            row["source_name"]
            for row in observations
            if row["source_kind"] == "monitor"
        ]
        self.assertEqual(monitor_names, expected_order)
        self.assertEqual(raw_sources(paper), expected_order)
        self.assertEqual(paper["source_count"], 3)
        self.assertEqual(
            self.storage.conn.execute(
                "SELECT COUNT(*) FROM papers WHERE paper_id = ?", (PAPER_ID,)
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.storage.conn.execute(
                "SELECT COUNT(*) FROM journal_monitor_papers WHERE paper_id = ?", (PAPER_ID,)
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.storage.conn.execute(
                "SELECT COUNT(*) FROM theme_candidates WHERE paper_id = ?", (PAPER_ID,)
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            self.storage.conn.execute(
                "SELECT COUNT(*) FROM author_monitor_papers WHERE paper_id = ?", (PAPER_ID,)
            ).fetchone()[0],
            1,
        )

    def test_subject_then_journal_refresh_then_author_preserves_all_provenance(self) -> None:
        self.observe_subject()
        self.refresh_from_journal()
        self.observe_author()
        self.assert_three_monitor_sources(["subject", "journal", "author"])

    def test_author_then_journal_refresh_then_subject_preserves_all_provenance(self) -> None:
        self.observe_author()
        self.refresh_from_journal()
        self.observe_subject()
        self.assert_three_monitor_sources(["author", "journal", "subject"])

    def test_other_product_arrival_orders_preserve_all_provenance(self) -> None:
        for order in [
            ("journal", "subject", "author"),
            ("journal", "author", "subject"),
        ]:
            with self.subTest(order=order):
                self.storage.close()
                self.temporary.cleanup()
                self.temporary = tempfile.TemporaryDirectory()
                self.storage = Storage(Path(self.temporary.name) / "paper_monitor.sqlite")
                self.author_id = None
                actions = {
                    "journal": self.refresh_from_journal,
                    "subject": self.observe_subject,
                    "author": self.observe_author,
                }
                for source in order:
                    actions[source]()
                self.assert_three_monitor_sources(list(order))

    def test_repeated_source_refresh_is_idempotent_but_new_source_increases_count(self) -> None:
        self.refresh_from_journal()
        initial = self.storage.get_paper(PAPER_ID)
        initial_observations = self.storage.list_paper_source_observations(PAPER_ID)
        self.refresh_from_journal()
        repeated = self.storage.get_paper(PAPER_ID)
        repeated_observations = self.storage.list_paper_source_observations(PAPER_ID)

        self.assertEqual(initial["source_count"], 1)
        self.assertEqual(repeated["source_count"], 1)
        self.assertEqual(len(initial_observations), 1)
        self.assertEqual(len(repeated_observations), 1)

        self.observe_author()
        added = self.storage.get_paper(PAPER_ID)
        self.assertEqual(added["source_count"], 2)
        self.assertEqual(raw_sources(added), ["journal", "author"])

    def test_refresh_and_raw_update_keep_compatibility_projection(self) -> None:
        self.observe_subject()
        existing = self.storage.get_paper(PAPER_ID)
        refreshed = paper_payload("journal")
        refreshed["raw"] = {"volume": "7", "_paper_monitor_sources": ["journal", "journal"]}
        merged = ui_server.merge_refreshed_metadata(existing, refreshed)
        updated = self.storage.refresh_paper_metadata(PAPER_ID, merged)
        updated = self.storage.update_paper_raw_json(PAPER_ID, {"issue": "3"})

        self.assertEqual(raw_sources(updated), ["subject", "journal"])
        self.assertEqual(
            [row["source_name"] for row in self.storage.list_paper_source_observations(PAPER_ID)],
            ["subject", "journal"],
        )

    def test_source_key_uniqueness_and_transaction_rollback(self) -> None:
        self.storage.upsert_paper(paper_payload("crossref"))
        before = self.storage.get_paper(PAPER_ID)["source_count"]
        created = self.storage.record_paper_source_observation(
            PAPER_ID,
            source_kind="provider",
            source_name="publisher_feed",
            source_key="feed-a",
        )
        repeated = self.storage.record_paper_source_observation(
            PAPER_ID,
            source_kind="provider",
            source_name="publisher_feed",
            source_key="feed-a",
        )
        distinct = self.storage.record_paper_source_observation(
            PAPER_ID,
            source_kind="provider",
            source_name="publisher_feed",
            source_key="feed-b",
        )
        self.assertTrue(created)
        self.assertFalse(repeated)
        self.assertTrue(distinct)
        self.assertEqual(self.storage.get_paper(PAPER_ID)["source_count"], before + 2)

        self.storage.conn.execute("BEGIN IMMEDIATE")
        self.storage.record_paper_source_observation(
            PAPER_ID,
            source_kind="provider",
            source_name="rolled_back_source",
            commit=False,
        )
        self.storage.conn.rollback()
        self.assertNotIn(
            "rolled_back_source",
            [row["source_name"] for row in self.storage.list_paper_source_observations(PAPER_ID)],
        )

    def test_repointed_publication_and_canonical_merge_keep_provenance(self) -> None:
        source_id = "legacy-title-identity"
        target_id = "doi_10.1000/product-provenance"
        self.storage.upsert_paper(paper_payload("subject", paper_id=source_id))
        self.storage.record_theme_candidate(
            paper_id=source_id,
            source="openalex",
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            query_plan_hash="legacy-plan",
        )
        self.storage.upsert_paper(paper_payload("journal", paper_id=target_id))
        publication = self.storage.add_my_publication(paper_id=source_id)

        replaced = self.storage.replace_my_publication_paper(
            publication_id=int(publication["id"]),
            paper_id=target_id,
        )
        self.storage.conn.execute("DELETE FROM papers WHERE paper_id = ?", (source_id,))
        self.storage.conn.commit()

        target = self.storage.get_paper(target_id)
        self.assertEqual(replaced["paper_id"], target_id)
        self.assertEqual(raw_sources(target), ["journal", "subject"])
        self.assertEqual(
            [row["source_name"] for row in self.storage.list_paper_source_observations(target_id)],
            ["journal", "subject"],
        )
        self.assertEqual(
            self.storage.conn.execute(
                "SELECT COUNT(*) FROM paper_source_observations WHERE paper_id = ?", (source_id,)
            ).fetchone()[0],
            0,
        )

    def test_foreign_key_delete_cascades(self) -> None:
        self.observe_subject()
        foreign_keys = {
            (row[2], row[3], row[4], row[6])
            for row in self.storage.conn.execute(
                "PRAGMA foreign_key_list(paper_source_observations)"
            ).fetchall()
        }
        self.storage.conn.execute("DELETE FROM papers WHERE paper_id = ?", (PAPER_ID,))
        self.storage.conn.commit()
        remaining = self.storage.conn.execute(
            "SELECT COUNT(*) FROM paper_source_observations WHERE paper_id = ?", (PAPER_ID,)
        ).fetchone()[0]

        self.assertIn(("papers", "paper_id", "paper_id", "CASCADE"), foreign_keys)
        self.assertEqual(remaining, 0)


class PaperSourceObservationMigrationTests(unittest.TestCase):
    def test_schema12_backfills_only_provable_sources_and_monitor_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "paper_monitor.sqlite"
            storage = Storage(db_path)
            try:
                storage.upsert_paper(paper_payload("crossref"))
                run_id = storage.start_fetch_run(
                    monitor_type="journal",
                    source="journal",
                    journal="Example Physics",
                    window_start=WINDOW_START,
                    window_end=WINDOW_END,
                    started_at="2026-08-21T08:00:00+08:00",
                )
                storage.record_journal_monitor_paper(
                    fetch_run_id=run_id,
                    paper_id=PAPER_ID,
                    source="crossref",
                )
                storage.record_theme_candidate(
                    paper_id=PAPER_ID,
                    source="openalex",
                    window_start=WINDOW_START,
                    window_end=WINDOW_END,
                    query_plan_hash="migration-plan",
                )
                author = storage.add_author_monitor(
                    {
                        "user_id": "migration-author",
                        "name": "Migration Author",
                        "url": "https://scholar.google.com/citations?user=migration-author",
                    }
                )
                storage.add_author_monitor_paper(
                    author_monitor_id=int(author["id"]),
                    paper_id=PAPER_ID,
                )
                storage.upsert_paper(paper_payload("", paper_id="unproven-paper", title="Unproven work"))
            finally:
                storage.close()

            legacy = sqlite3.connect(db_path)
            try:
                legacy.execute("DROP TABLE paper_source_observations")
                legacy.execute(
                    "UPDATE papers SET source = 'crossref', source_count = 1, raw_json = ? WHERE paper_id = ?",
                    (
                        json.dumps(
                            {"_paper_monitor_sources": ["legacy-feed", {"invalid": "source"}]}
                        ),
                        PAPER_ID,
                    ),
                )
                legacy.execute("UPDATE papers SET source = '', source_count = 1, raw_json = '{}' WHERE paper_id = 'unproven-paper'")
                legacy.execute("PRAGMA user_version = 12")
                legacy.commit()
            finally:
                legacy.close()

            migrated = Storage(db_path)
            try:
                version = int(migrated.conn.execute("PRAGMA user_version").fetchone()[0])
                observations = migrated.list_paper_source_observations(PAPER_ID)
                unproven = migrated.list_paper_source_observations("unproven-paper")
                paper = migrated.get_paper(PAPER_ID)
            finally:
                migrated.close()

        self.assertEqual(STORAGE_SCHEMA_VERSION, 17)
        self.assertEqual(version, STORAGE_SCHEMA_VERSION)
        self.assertEqual(
            {(row["source_kind"], row["source_name"]) for row in observations},
            {
                ("provider", "crossref"),
                ("source", "legacy-feed"),
                ("monitor", "journal"),
                ("monitor", "subject"),
                ("monitor", "author"),
            },
        )
        self.assertEqual(unproven, [])
        self.assertGreaterEqual(paper["source_count"], len(observations))
        self.assertEqual(
            raw_sources(paper),
            ["legacy-feed", "crossref", "journal", "subject", "author"],
        )


if __name__ == "__main__":
    unittest.main()
