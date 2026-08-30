from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from paper_monitor import ui_server
from paper_monitor.config import load_config
from paper_monitor.storage import STORAGE_SCHEMA_VERSION, Storage


def journal(name: str, issn: str) -> dict:
    return {
        "name": name,
        "issns": [issn],
        "openalex_source_id": None,
        "section_policy": "science",
        "skip_landing_enrichment": True,
        "logo_url": "",
    }


def write_config(path: Path, journals: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "fetch_lookback_days": 14,
                "report_days": 14,
                "keep_unknown_sections": True,
                "journals": journals,
                "section_policies": {},
            }
        ),
        encoding="utf-8",
    )


class JournalSubscriptionStorageTests(unittest.TestCase):
    def test_schema10_migrates_to_current_subscription_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "monitor.sqlite"
            storage = Storage(db_path)
            storage.close()
            legacy = sqlite3.connect(db_path)
            try:
                legacy.execute("DROP TABLE journal_subscriptions")
                legacy.execute("PRAGMA user_version = 10")
                legacy.commit()
            finally:
                legacy.close()

            migrated = Storage(db_path)
            try:
                version = int(migrated.conn.execute("PRAGMA user_version").fetchone()[0])
                table = migrated.conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'journal_subscriptions'"
                ).fetchone()
            finally:
                migrated.close()

        self.assertEqual(STORAGE_SCHEMA_VERSION, 14)
        self.assertEqual(version, 14)
        self.assertIsNotNone(table)

    def test_seed_runs_once_and_disabled_journal_is_not_reenabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                self.assertTrue(
                    storage.seed_journal_subscriptions(
                        [journal("Nature", "0028-0836"), journal("Nano Letters", "1530-6984")],
                        [journal("Advanced Materials", "0935-9648")],
                    )
                )
                storage.disable_journal_subscription("Nano Letters")
                self.assertFalse(
                    storage.seed_journal_subscriptions(
                        [journal("Nature", "0028-0836"), journal("Nano Letters", "1530-6984")]
                    )
                )
                active = [item["name"] for item in storage.list_journal_subscriptions(enabled=True)]
                inactive = [item["name"] for item in storage.list_journal_subscriptions(enabled=False)]
            finally:
                storage.close()

        self.assertEqual(active, ["Nature"])
        self.assertEqual(inactive, ["Nano Letters", "Advanced Materials"])

    def test_sqlite_order_survives_source_config_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "monitor.sqlite"
            config_path = root / "journals.json"
            defaults = [journal("Nature", "0028-0836"), journal("Science", "0036-8075")]
            write_config(config_path, defaults)
            storage = Storage(db_path)
            try:
                storage.seed_journal_subscriptions(defaults)
                storage.upsert_journal_subscription(journal("Nano Letters", "1530-6984"))
                storage.reorder_journal_subscriptions(["Nano Letters", "Nature", "Science"])
            finally:
                storage.close()

            write_config(config_path, [journal("Replacement Default", "0000-0000")])
            config = load_config(config_path, db_path=db_path)

        self.assertEqual(
            [item.name for item in config.journals],
            ["Nano Letters", "Nature", "Science"],
        )

    def test_invalid_reorder_is_rejected_without_changing_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                storage.seed_journal_subscriptions(
                    [journal("Nature", "0028-0836"), journal("Science", "0036-8075")]
                )
                with self.assertRaises(ValueError):
                    storage.reorder_journal_subscriptions(["Science"])
                active = [item["name"] for item in storage.list_journal_subscriptions(enabled=True)]
            finally:
                storage.close()

        self.assertEqual(active, ["Nature", "Science"])

    def test_reorder_handler_returns_database_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "monitor.sqlite"
            storage = Storage(db_path)
            try:
                storage.seed_journal_subscriptions(
                    [journal("Nature", "0028-0836"), journal("Science", "0036-8075")]
                )
            finally:
                storage.close()

            handler = object.__new__(ui_server.PaperMonitorUiHandler)
            handler.configured_db_path = db_path
            handler.configured_journals = []
            response: dict = {}
            handler.send_json = lambda payload, status=None: response.update(payload)
            handler.send_error_json = lambda status, message: self.fail(message)
            handler.refresh_journals = lambda: None
            handler.handle_reorder_journals({"journals": ["Science", "Nature"]})

            reopened = Storage(db_path)
            try:
                active = [item["name"] for item in reopened.list_journal_subscriptions(enabled=True)]
            finally:
                reopened.close()

        self.assertEqual(active, ["Science", "Nature"])
        self.assertEqual([item["name"] for item in response["journals"]], active)

    def test_journal_filter_and_settings_expose_drag_order_contract(self) -> None:
        html = ui_server.INDEX_HTML
        self.assertIn('fetch("/api/journals/reorder"', html)
        self.assertIn("enableJournalOrderDrag(label, journal, root)", html)
        self.assertIn("enableJournalOrderDrag(row, journal.name, root)", html)
        self.assertIn('handle.addEventListener("mousedown"', html)
        self.assertIn("moveJournalOrderWithPointer", html)
        self.assertIn("finishJournalOrderPointerDrag", html)
        self.assertIn("state.journals = withPreprintJournals", html)


if __name__ == "__main__":
    unittest.main()
