import json
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
            original_pubmed = ui_server.refresh_pubmed_if_possible
            pubmed_calls = []
            try:
                ui_server.resolve_google_scholar_candidate_to_identifier = lambda _candidate: dict(resolved)
                ui_server.publication_metrics_metadata_from_doi = (
                    lambda _doi, **_kwargs: dict(resolved)
                )
                def fake_pubmed(_storage, updated, *, doi, **_kwargs):
                    pubmed_calls.append(doi)
                    return updated

                ui_server.refresh_pubmed_if_possible = fake_pubmed
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
                ui_server.refresh_pubmed_if_possible = original_pubmed

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
                self.assertEqual(pubmed_calls, ["10.1234/example.1"])
            finally:
                storage.close()

    def test_forced_identifier_lookup_can_target_one_paper_and_bypass_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "monitor.sqlite"
            storage = Storage(db_path)
            try:
                author = storage.add_author_monitor(scholar_profile("author-a", "Ada Author"))
                author_id = int(author["id"])
                for paper_id, title in (
                    ("target-paper", "Target Paper"),
                    ("other-paper", "Other Paper"),
                ):
                    candidate = paper(paper_id, title, "2026-07-24")
                    candidate["raw"] = {
                        "authors": ["Ada Author"],
                        "author_monitor_enrichment": {
                            "status": "unresolved",
                            "attempted_at": ui_server.now_iso(),
                        },
                    }
                    storage.upsert_paper(candidate)
                    storage.add_author_monitor_paper(
                        author_monitor_id=author_id,
                        paper_id=paper_id,
                    )
            finally:
                storage.close()

            resolved = {
                **paper("resolved-id", "Target Paper", "2026-07-24"),
                "doi": "10.1234/target.1",
                "abstract": "Resolved abstract.",
            }
            original_resolve = ui_server.resolve_google_scholar_candidate_to_identifier
            original_metrics = ui_server.publication_metrics_metadata_from_doi
            original_pubmed = ui_server.refresh_pubmed_if_possible
            try:
                ui_server.resolve_google_scholar_candidate_to_identifier = (
                    lambda candidate: dict(resolved)
                    if candidate["paper"]["paper_id"] == "target-paper"
                    else None
                )
                ui_server.publication_metrics_metadata_from_doi = (
                    lambda _doi, **_kwargs: dict(resolved)
                )
                ui_server.refresh_pubmed_if_possible = lambda _storage, updated, **_kwargs: updated
                job_id = ui_server.create_author_monitor_enrichment_job(
                    author_monitor_id=author_id,
                    paper_id="target-paper",
                    force=True,
                    identifiers_only=True,
                )
                ui_server.run_author_monitor_enrichment_job(
                    job_id=job_id,
                    db_path=db_path,
                    author_monitor_id=author_id,
                    paper_id="target-paper",
                    force=True,
                    identifiers_only=True,
                )
            finally:
                ui_server.resolve_google_scholar_candidate_to_identifier = original_resolve
                ui_server.publication_metrics_metadata_from_doi = original_metrics
                ui_server.refresh_pubmed_if_possible = original_pubmed

            storage = Storage(db_path)
            try:
                self.assertEqual(storage.get_paper("target-paper")["doi"], "10.1234/target.1")
                self.assertFalse(storage.get_paper("other-paper").get("doi"))
                job = ui_server.get_author_monitor_enrichment_job(job_id)
                self.assertEqual(job["paper_id"], "target-paper")
                self.assertTrue(job["force"])
                self.assertTrue(job["identifiers_only"])
                self.assertEqual(job["total"], 1)
            finally:
                storage.close()

    def test_pubmed_auto_marks_fill_unmarked_authors_without_overwriting_manual_marks(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                candidate = paper("publication-paper", "Publication Paper", "2026-07-24")
                candidate["raw"] = {"authors": ["Ada Author", "Ben Author"]}
                storage.upsert_paper(candidate)
                publication = storage.add_my_publication(paper_id="publication-paper")
                publication_id = int(publication["id"])
                storage.set_my_publication_author_mark(
                    publication_id=publication_id,
                    author_index=0,
                    author_name="Ada Author",
                    first_author=False,
                    co_first_author=False,
                    corresponding_author=True,
                )
                ui_server.sync_my_publication_pubmed_author_marks(
                    storage,
                    paper_id="publication-paper",
                    pubmed={
                        "author_affiliations": [
                            {
                                "name": "Ada Author",
                                "roles": {"co_first_author": True},
                            },
                            {
                                "name": "Ben Author",
                                "roles": {"corresponding_author": True},
                            },
                        ]
                    },
                )
                updated = storage.get_my_publication(publication_id=publication_id)
                marks = json.loads(updated["author_marks"])
                self.assertTrue(marks["0"]["corresponding_author"])
                self.assertFalse(marks["0"]["co_first_author"])
                self.assertNotIn("source", marks["0"])
                self.assertTrue(marks["1"]["corresponding_author"])
                self.assertEqual(marks["1"]["source"], "pubmed_auto")
            finally:
                storage.close()


class AuthorMonitorUiContractTests(unittest.TestCase):
    def test_monitor_list_payloads_omit_heavy_detail_only_fields(self):
        paper = {
            "paper_id": "compact-paper",
            "title": "Compact payload",
            "journal": "Example Journal",
            "publication_date": "2026-07-24",
            "authors": '["Ada Author", "Ben Author"]',
            "abstract": "Needed by Journal Monitor cards.",
            "bibtex": "large bibtex",
            "nature_reference": "large reference",
            "raw_json": json.dumps(
                {
                    "authors": ["Ada Author", "Ben Author"],
                    "author_details": {"author_affiliations": [{"name": "Ada Author"}]},
                    "citation_metrics": {"counts_by_year": {"2026": 10}},
                }
            ),
        }

        journal_item = ui_server.monitor_paper_to_api(paper)
        self.assertEqual(journal_item["abstract"], "Needed by Journal Monitor cards.")
        self.assertFalse(journal_item["full_detail"])
        self.assertNotIn("bibtex", journal_item)
        self.assertNotIn("nature_reference", journal_item)
        self.assertNotIn("citation_metrics", journal_item)
        self.assertNotIn("author_details", journal_item)

        author_item = ui_server.author_monitor_paper_to_api(paper)
        self.assertFalse(author_item["full_detail"])
        self.assertFalse(author_item["author_details_loaded"])
        self.assertTrue(author_item["citation_label"].startswith("Ada Author et al."))
        self.assertNotIn("abstract", author_item)
        self.assertNotIn("bibtex", author_item)
        self.assertNotIn("citation_metrics", author_item)

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
        self.assertIn("author-paper-citation", card)
        self.assertNotIn("author-paper-authors", card)
        self.assertNotIn("authorMonitorAuthorsMarkup", card)
        self.assertNotIn("author-paper-date", card)
        self.assertNotIn("paper.publication_date", card)
        self.assertNotIn("paper.abstract", card)
        self.assertNotIn("reportFigureMarkup", card)
        self.assertNotIn("paperFieldValues", card)
        self.assertNotIn("function scheduleCenteredAuthorMonitorSelection", html)
        self.assertNotIn("selectCenteredAuthorMonitorPaper(list)", html)
        self.assertIn('scrollIntoView({block: "nearest"})', html)
        self.assertIn("hideTitle: true", html)
        self.assertIn('id="authorMonitorActivityStatus"', html)
        self.assertIn("minmax(280px, 340px)", html)

    def test_author_monitor_supports_manual_identifier_retries(self):
        html = ui_server.INDEX_HTML
        self.assertIn("Find Missing Identifiers", html)
        self.assertIn("author-paper-identifier-button", html)
        self.assertIn('data-action="find-paper-identifier"', html)
        self.assertIn("identifiers_only: request.identifiersOnly", html)
        self.assertIn("refreshAuthorMonitorMetadataFromIdentifier(paper)", html)
        self.assertIn("paper?.author_details?.author_affiliations", html)
        self.assertIn("scheduleAuthorMonitorPaperDetails(paperId)", html)
        self.assertIn("loadAuthorMonitorPaperDetailsIfNeeded(paperId, token", html)
        self.assertIn("/api/paper?paper_id=", html)
        detail = html.split("function renderAuthorMonitorPaperDetail()", 1)[1].split(
            "async function downloadAuthorMonitorPdf", 1
        )[0]
        self.assertIn('data-action="refresh-library-metadata"', detail)

    def test_author_monitor_card_owns_compact_library_action(self):
        html = ui_server.INDEX_HTML
        card = html.split("function renderAuthorMonitorPaperCard", 1)[1].split(
            "function authorMonitorActivityStatusClass", 1
        )[0]
        detail = html.split("function renderAuthorMonitorPaperDetail()", 1)[1].split(
            "async function downloadAuthorMonitorPdf", 1
        )[0]
        self.assertIn("author-paper-action-stack", card)
        self.assertIn("author-paper-mini-button author-paper-identifier-button", card)
        self.assertIn("author-paper-mini-button author-paper-library-button", card)
        self.assertIn('data-action="add-library"', card)
        self.assertIn('>${inLibrary ? "✓" : "+"}</button>', card)
        self.assertLess(
            card.index("author-paper-library-button"),
            card.index("author-paper-identifier-button"),
        )
        self.assertIn("toggleLibraryAddMenu(event, article, paper.paper_id)", card)
        self.assertNotIn('addEventListener("contextmenu"', card)
        self.assertNotIn('data-action="add-library"', detail)
        self.assertNotIn("showAuthorMonitorPaperContextMenu", html)
        self.assertIn("AUTHOR_MONITOR_INITIAL_CARD_COUNT", html)
        self.assertIn("appendAuthorMonitorPaperCards", html)
        self.assertIn("authorMonitorDetailController.abort()", html)
        self.assertIn('fetchJson("/api/author-monitor?summary=1"', html)
        card_css = html.split(".author-paper-card {", 1)[1].split("}", 1)[0]
        self.assertIn("min-height: 68px", card_css)
        self.assertIn("align-content: center", card_css)
        title_css = html.split(".author-paper-title {", 1)[1].split("}", 1)[0]
        self.assertIn("color: var(--ink)", title_css)
        action_css = html.split(".author-paper-action-stack {", 1)[1].split("}", 1)[0]
        self.assertIn("position: absolute", action_css)
        self.assertIn("top: 9px", action_css)
        detail_title_css = html.split(
            ".author-monitor-detail-body.library-detail h3 {", 1
        )[1].split("}", 1)[0]
        self.assertIn("font-size: 17px", detail_title_css)
        self.assertIn("authorMonitorPaperIsConferenceAbstract(paper)", html)
        self.assertIn("aps global physics summit", html)
        self.assertIn(".author-paper-card.conference-abstract", html)
        author_list_css = html.split(".author-monitor-paper-list {", 1)[1].split("}", 1)[0]
        self.assertNotIn("scroll-padding-block", author_list_css)

    def test_author_monitor_cards_do_not_open_pdf_on_double_click(self):
        html = ui_server.INDEX_HTML
        card = html.split("function renderAuthorMonitorPaperCard", 1)[1].split(
            "function authorMonitorActivityStatusClass", 1
        )[0]
        self.assertNotIn('article.addEventListener("dblclick"', card)
        self.assertNotIn("openAuthorMonitorPdfInPreview", html)

    def test_copy_buttons_and_search_are_scoped_to_the_active_surface(self):
        html = ui_server.INDEX_HTML
        self.assertIn('button.closest(".library-detail")', html)
        self.assertIn('myPublicationQuery: ""', html)
        self.assertIn('reportQuery: ""', html)
        self.assertIn('themeQuery: ""', html)
        self.assertIn('authorPaperQuery: ""', html)
        self.assertIn('"my-publications": "Search My Publications"', html)
        self.assertIn('"report": "Search Journal Monitor"', html)
        self.assertIn('"theme": "Search Subject Monitor"', html)
        self.assertIn('"author": "Search Author Monitor"', html)
        self.assertNotIn('id="searchBox"', html)


if __name__ == "__main__":
    unittest.main()
