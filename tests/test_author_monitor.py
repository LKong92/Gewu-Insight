import tempfile
import unittest
from pathlib import Path

from paper_monitor import ui_server
from paper_monitor.storage import Storage


def scholar_profile(user_id: str, name: str) -> dict:
    return {
        "user_id": user_id,
        "name": name,
        "url": f"https://scholar.google.com/citations?user={user_id}",
        "affiliation": "Example University",
        "interests": ["condensed matter"],
    }


def paper(paper_id: str, title: str, date: str) -> dict:
    return {
        "paper_id": paper_id,
        "title": title,
        "journal": "Example Journal",
        "publication_date": date,
        "source": "google-scholar",
        "url": f"https://example.org/{paper_id}",
    }


class AuthorMonitorStorageTests(unittest.TestCase):
    def test_shared_paper_is_deduplicated_and_monitor_delete_keeps_paper(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                first = storage.add_author_monitor(scholar_profile("author-a", "Ada Author"))
                second = storage.add_author_monitor(scholar_profile("author-b", "Ben Author"))
                storage.upsert_paper(paper("shared-paper", "Shared Paper", "2026-07-23"))
                storage.add_author_monitor_paper(
                    author_monitor_id=int(first["id"]),
                    paper_id="shared-paper",
                    unread=True,
                )
                storage.add_author_monitor_paper(
                    author_monitor_id=int(second["id"]),
                    paper_id="shared-paper",
                    unread=True,
                )

                rows = storage.list_author_monitor_papers()
                self.assertEqual(len(rows), 1)
                self.assertEqual(
                    set(rows[0]["author_monitor_ids"]),
                    {int(first["id"]), int(second["id"])},
                )
                self.assertEqual(
                    set(rows[0]["monitored_authors"]),
                    {"Ada Author", "Ben Author"},
                )

                storage.mark_author_monitor_papers_read(paper_ids=["shared-paper"])
                self.assertFalse(storage.list_author_monitor_papers()[0]["author_unread"])

                storage.delete_author_monitor(int(first["id"]))
                self.assertIsNotNone(storage.get_paper("shared-paper"))
                self.assertEqual(len(storage.list_author_monitor_papers()), 1)
            finally:
                storage.close()

    def test_empty_read_request_does_not_clear_all_unread_papers(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                author = storage.add_author_monitor(scholar_profile("author-a", "Ada Author"))
                storage.upsert_paper(paper("new-paper", "New Paper", "2026-07-24"))
                storage.add_author_monitor_paper(
                    author_monitor_id=int(author["id"]),
                    paper_id="new-paper",
                    unread=True,
                )
                storage.mark_author_monitor_papers_read()
                self.assertTrue(storage.list_author_monitor_papers()[0]["author_unread"])
            finally:
                storage.close()


class AuthorMonitorRefreshTests(unittest.TestCase):
    def test_initial_import_is_baseline_and_later_refresh_marks_only_new_papers(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "monitor.sqlite"
            storage = Storage(db_path)
            try:
                author = storage.add_author_monitor(scholar_profile("author-a", "Ada Author"))
                author_id = int(author["id"])
            finally:
                storage.close()

            calls = []
            payloads = [
                {
                    "profile": scholar_profile("author-a", "Ada Author"),
                    "candidates": [{"key": "old"}],
                },
                {
                    "profile": scholar_profile("author-a", "Ada Author"),
                    "candidates": [{"key": "old"}, {"key": "new"}],
                },
            ]
            original_fetch = ui_server.fetch_google_scholar_profile_payload
            original_normalize = ui_server.paper_from_publication_candidate
            original_key = ui_server.scholar_candidate_key
            try:
                def fake_fetch(_url, *, limit, sort_by_date=False):
                    calls.append((limit, sort_by_date))
                    return payloads.pop(0)

                def fake_normalize(candidate):
                    if candidate["key"] == "old":
                        return paper("old-paper", "Existing Paper", "2025-01-01")
                    return paper("new-paper", "New Paper", "2026-07-24")

                ui_server.fetch_google_scholar_profile_payload = fake_fetch
                ui_server.paper_from_publication_candidate = fake_normalize
                ui_server.scholar_candidate_key = lambda candidate, _paper: candidate["key"]

                baseline = ui_server.refresh_author_monitor_for_db(
                    db_path,
                    author_id,
                    initial=True,
                    force=True,
                )
                update = ui_server.refresh_author_monitor_for_db(
                    db_path,
                    author_id,
                    initial=False,
                    force=True,
                )
            finally:
                ui_server.fetch_google_scholar_profile_payload = original_fetch
                ui_server.paper_from_publication_candidate = original_normalize
                ui_server.scholar_candidate_key = original_key

            self.assertTrue(baseline["baseline"])
            self.assertEqual(baseline["added"], 1)
            self.assertFalse(update["baseline"])
            self.assertEqual(update["added"], 1)
            self.assertEqual(
                calls,
                [
                    (ui_server.AUTHOR_MONITOR_INITIAL_IMPORT_LIMIT, False),
                    (ui_server.AUTHOR_MONITOR_RECENT_CHECK_LIMIT, True),
                ],
            )

            storage = Storage(db_path)
            try:
                rows = {row["paper_id"]: row for row in storage.list_author_monitor_papers(author_id)}
                self.assertFalse(rows["old-paper"]["author_unread"])
                self.assertTrue(rows["new-paper"]["author_unread"])
            finally:
                storage.close()

    def test_background_enrichment_updates_scholar_only_paper_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "monitor.sqlite"
            storage = Storage(db_path)
            try:
                author = storage.add_author_monitor(scholar_profile("author-a", "Ada Author"))
                scholar_only = paper("scholar-only", "A Precise Paper Title", "2026-07-24")
                scholar_only["raw"] = {"authors": ["Ada Author"], "venue": "Example Journal"}
                storage.upsert_paper(scholar_only)
                storage.add_author_monitor_paper(
                    author_monitor_id=int(author["id"]),
                    paper_id="scholar-only",
                )
            finally:
                storage.close()

            resolved = {
                **paper("resolved-id", "A Precise Paper Title", "2026-07-24"),
                "doi": "10.1234/example.1",
                "abstract": "Resolved abstract.",
                "abstract_source": "crossref",
                "raw": {"author": [{"given": "Ada", "family": "Author"}]},
            }
            original_resolve = ui_server.resolve_google_scholar_candidate_to_identifier
            original_metrics = ui_server.publication_metrics_metadata_from_doi
            try:
                ui_server.resolve_google_scholar_candidate_to_identifier = lambda _candidate: dict(resolved)
                ui_server.publication_metrics_metadata_from_doi = (
                    lambda _doi, **_kwargs: dict(resolved)
                )
                job_id = ui_server.create_author_monitor_enrichment_job(
                    author_monitor_id=int(author["id"])
                )
                ui_server.run_author_monitor_enrichment_job(
                    job_id=job_id,
                    db_path=db_path,
                    author_monitor_id=int(author["id"]),
                )
            finally:
                ui_server.resolve_google_scholar_candidate_to_identifier = original_resolve
                ui_server.publication_metrics_metadata_from_doi = original_metrics

            storage = Storage(db_path)
            try:
                updated = storage.get_paper("scholar-only")
                self.assertEqual(updated["doi"], "10.1234/example.1")
                self.assertEqual(updated["abstract"], "Resolved abstract.")
                self.assertEqual(
                    ui_server.author_monitor_enrichment_marker(updated)["status"],
                    "complete",
                )
                self.assertEqual(
                    ui_server.get_author_monitor_enrichment_job(job_id)["status"],
                    "completed",
                )
            finally:
                storage.close()


class AuthorMonitorUiContractTests(unittest.TestCase):
    def test_author_monitor_has_fifth_view_and_independent_three_column_layout(self):
        html = ui_server.INDEX_HTML
        self.assertIn('id="authorMode"', html)
        self.assertNotIn('id="authorToolbarActions"', html)
        self.assertIn("function openAuthorMonitor()", html)
        self.assertIn("function renderAuthorMonitor(", html)
        self.assertIn("function renderAuthorMonitorPaperDetail()", html)
        self.assertIn("grid-template-columns: minmax(210px, 250px)", html)
        self.assertIn(".app.author-mode .sidebar", html)
        self.assertIn("display: none;", html)

    def test_author_monitor_uses_compact_cards_and_manual_keyboard_selection(self):
        html = ui_server.INDEX_HTML
        card = html.split("function renderAuthorMonitorPaperCard", 1)[1].split(
            "function authorMonitorActivityStatusClass", 1
        )[0]
        self.assertIn("author-paper-title", card)
        self.assertIn("author-paper-authors", card)
        self.assertIn("author-paper-citation", card)
        self.assertIn("paper.publication_date", card)
        self.assertNotIn("paper.abstract", card)
        self.assertNotIn("reportFigureMarkup", card)
        self.assertNotIn("paperFieldValues", card)
        self.assertNotIn("function scheduleCenteredAuthorMonitorSelection", html)
        self.assertNotIn("selectCenteredAuthorMonitorPaper(list)", html)
        self.assertIn('scrollIntoView({block: "nearest"})', html)
        self.assertIn("hideTitle: true", html)
        self.assertIn('id="authorMonitorActivityStatus"', html)
        self.assertIn("minmax(280px, 340px)", html)


if __name__ == "__main__":
    unittest.main()
