import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
    def test_author_homepage_is_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                profile = scholar_profile("homepage-user", "Homepage Author")
                profile["homepage_url"] = "https://example.edu/author"
                author = storage.add_author_monitor(profile)
                saved = storage.get_author_monitor(int(author["id"]))
            finally:
                storage.close()

        self.assertEqual(saved["homepage_url"], "https://example.edu/author")

    def test_duplicate_scholar_id_does_not_overwrite_existing_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                original = scholar_profile("same-user", "Leo Kouwenhoven")
                original["affiliation"] = "Delft University of Technology"
                first = storage.add_author_monitor(original)
                conflicting = scholar_profile("same-user", "Stevan Nadj-Perge")
                second = storage.add_author_monitor(conflicting)
                saved = storage.get_author_monitor(int(first["id"]))
            finally:
                storage.close()

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(saved["name"], "Leo Kouwenhoven")
        self.assertEqual(saved["affiliation"], "Delft University of Technology")

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
                storage.add_library_item(paper_id="shared-paper", folder_id=1)
                storage.add_my_publication(paper_id="shared-paper")
                timestamp = ui_server.now_iso()
                storage.conn.execute(
                    """
                    INSERT INTO resources (
                      paper_id, source_path, stored_path, original_filename,
                      kind, mime_type, size_bytes, status, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'imported', ?, ?)
                    """,
                    (
                        "shared-paper",
                        "/tmp/shared-paper-source.pdf",
                        "/tmp/shared-paper.pdf",
                        "shared-paper.pdf",
                        "pdf",
                        "application/pdf",
                        123,
                        timestamp,
                        timestamp,
                    ),
                )
                storage.conn.commit()

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
                self.assertEqual(
                    storage.conn.execute(
                        "SELECT COUNT(*) FROM library_items WHERE paper_id = ?",
                        ("shared-paper",),
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    storage.conn.execute(
                        "SELECT COUNT(*) FROM resources WHERE paper_id = ?",
                        ("shared-paper",),
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    storage.conn.execute(
                        "SELECT COUNT(*) FROM my_publications WHERE paper_id = ?",
                        ("shared-paper",),
                    ).fetchone()[0],
                    1,
                )
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
    def test_scholar_row_parses_citation_count_without_another_request(self):
        soup = ui_server.BeautifulSoup(
            """
            <table><tr class="gsc_a_tr">
              <td><a class="gsc_a_at" href="/citations?view_op=view_citation">Paper</a>
              <div class="gs_gray">Ada Author</div><div class="gs_gray">Nature 1, 2</div></td>
              <td class="gsc_a_c"><a>1,234</a></td>
              <td class="gsc_a_y"><span>2026</span></td>
            </tr></table>
            """,
            "html.parser",
        )
        candidate = ui_server.google_scholar_row_to_publication(soup.select_one("tr"))

        self.assertEqual(candidate["raw"]["google_scholar"]["citation_count"], 1234)
        self.assertIn("checked_at", candidate["raw"]["google_scholar"])

    def test_scholar_profile_parses_external_homepage(self):
        soup = ui_server.BeautifulSoup(
            """
            <div id="gsc_prf_in">Ada Author</div>
            <div id="gsc_prf_ivh"><a class="gsc_prf_ila" href="https://example.edu/ada">Homepage</a></div>
            <div id="gsc_prf_int"><a href="/citations?view_op=search_authors">Quantum</a></div>
            """,
            "html.parser",
        )
        profile = ui_server.google_scholar_profile_page_metadata(
            soup,
            "https://scholar.google.com/citations?user=ada",
            "ada",
        )

        self.assertEqual(profile["homepage_url"], "https://example.edu/ada")

    def test_google_scholar_count_participates_in_merged_citations(self):
        candidate = paper("scholar-count", "Scholar Count", "2026-07-24")
        candidate["raw_json"] = json.dumps(
            {
                "cited_by_count": 8,
                "google_scholar": {
                    "citation_count": 21,
                    "publication_url": "https://scholar.google.com/example",
                },
            }
        )

        metrics = ui_server.citation_metrics(candidate)

        self.assertEqual(metrics["count"], 21)
        self.assertEqual(metrics["sources"]["google_scholar"]["count"], 21)
        self.assertEqual(metrics["source"], "Merged")

    def test_existing_paper_receives_scholar_observation_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                storage.upsert_paper(paper("existing-paper", "Existing", "2026-01-01"))
                ui_server.save_google_scholar_publication_observation(
                    storage,
                    "existing-paper",
                    {
                        "raw": {
                            "google_scholar": {
                                "citation_count": 17,
                                "publication_url": "https://scholar.google.com/existing",
                                "checked_at": "2026-07-26T12:00:00+08:00",
                            }
                        }
                    },
                )
                saved = storage.get_paper("existing-paper")
            finally:
                storage.close()

        self.assertEqual(
            ui_server.parse_raw_json(saved)["google_scholar"]["citation_count"],
            17,
        )

    def test_manual_identifier_request_can_enter_active_job_priority_queue(self):
        job_id = ui_server.create_author_monitor_enrichment_job()
        ui_server.update_author_monitor_enrichment_job(job_id, status="running")

        queued = ui_server.queue_author_monitor_enrichment_priority(job_id, "paper-priority")

        self.assertTrue(queued)
        self.assertEqual(
            ui_server.take_author_monitor_enrichment_priorities(job_id),
            ["paper-priority"],
        )

    def test_local_profile_search_never_assigns_a_monitored_id_to_a_coauthor(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                storage.add_author_monitor(
                    scholar_profile("leo-profile", "L. P. Kouwenhoven")
                )
                coauthored = paper("coauthored", "Shared Paper", "2026-07-24")
                coauthored["url"] = (
                    "https://scholar.google.com/citations?view_op=view_citation"
                    "&user=leo-profile&citation_for_view=leo-profile:abc"
                )
                coauthored["raw"] = {
                    "authors": ["L. P. Kouwenhoven", "Stevan Nadj-Perge"],
                    "url": coauthored["url"],
                }
                storage.upsert_paper(coauthored)

                wrong = ui_server.local_google_scholar_profiles(
                    storage,
                    "Stevan Nadj-Perge",
                )
                correct = ui_server.local_google_scholar_profiles(
                    storage,
                    "Leo Kouwenhoven",
                )
            finally:
                storage.close()

        self.assertEqual(wrong, [])
        self.assertEqual(len(correct), 1)
        self.assertEqual(correct[0]["user_id"], "leo-profile")
        self.assertTrue(correct[0]["already_monitored"])

    def test_global_scholar_cooldown_stops_every_author_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "monitor.sqlite"
            storage = Storage(db_path)
            try:
                author = storage.add_author_monitor(scholar_profile("author-a", "Ada Author"))
                cooldown = ui_server.start_google_scholar_global_cooldown(
                    storage,
                    message="unusual traffic",
                )
                snapshot = ui_server.author_monitor_snapshot(storage)
            finally:
                storage.close()

            with patch.object(
                ui_server,
                "fetch_google_scholar_profile_payload",
                side_effect=AssertionError("Scholar must not be requested during global cooldown"),
            ):
                result = ui_server.refresh_author_monitor_for_db(
                    db_path,
                    int(author["id"]),
                    initial=False,
                    force=True,
                )

            self.assertTrue(cooldown["active"])
            self.assertTrue(snapshot["scholarCooldown"]["active"])
            self.assertEqual(result["status"], "global-cooldown")
            self.assertIn("all authors", result["message"])

    def test_scholar_block_starts_global_24_hour_circuit_breaker(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "monitor.sqlite"
            storage = Storage(db_path)
            try:
                author = storage.add_author_monitor(scholar_profile("author-a", "Ada Author"))
            finally:
                storage.close()

            with patch.object(
                ui_server,
                "fetch_google_scholar_profile_payload",
                side_effect=ui_server.GoogleScholarBlockedError("unusual traffic"),
            ):
                result = ui_server.refresh_author_monitor_for_db(
                    db_path,
                    int(author["id"]),
                    initial=True,
                    force=True,
                )

            storage = Storage(db_path)
            try:
                cooldown = ui_server.google_scholar_global_cooldown(storage)
            finally:
                storage.close()
            self.assertEqual(result["status"], "cooldown")
            self.assertTrue(cooldown["active"])
            self.assertEqual(ui_server.GOOGLE_SCHOLAR_GLOBAL_COOLDOWN_SECONDS, 24 * 60 * 60)

    def test_name_profile_search_uses_one_network_query(self):
        profile = scholar_profile("author-a", "Ada Author")
        with patch.object(
            ui_server,
            "fetch_google_scholar_profiles_from_search",
            return_value=[profile],
        ) as fetch:
            results = ui_server.search_google_scholar_profiles(
                "Ada Author; Example University",
                limit=20,
            )

        fetch.assert_called_once()
        self.assertEqual(results, [profile])
        self.assertIn("Ada Author Example University", fetch.call_args.args[0])

    def test_all_scholar_requests_share_a_random_minimum_interval(self):
        previous = ui_server.GOOGLE_SCHOLAR_LAST_REQUEST_AT
        ui_server.GOOGLE_SCHOLAR_LAST_REQUEST_AT = 10.0
        response = object()
        try:
            with patch.object(ui_server.random, "uniform", return_value=6.0), patch.object(
                ui_server.time,
                "monotonic",
                side_effect=[12.0, 13.0],
            ), patch.object(ui_server.time, "sleep") as sleep, patch.object(
                ui_server,
                "request_with_retries",
                return_value=response,
            ) as request:
                result = ui_server.google_scholar_request_with_spacing(
                    "GET",
                    "https://scholar.google.com/citations",
                    max_retries=1,
                )
        finally:
            ui_server.GOOGLE_SCHOLAR_LAST_REQUEST_AT = previous

        self.assertIs(result, response)
        sleep.assert_called_once_with(4.0)
        request.assert_called_once()

    def test_scholar_http_403_is_treated_as_an_ip_block(self):
        self.assertTrue(
            ui_server.is_google_scholar_block_error(
                RuntimeError("403 Client Error: Forbidden for url: https://scholar.google.com/")
            )
        )

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

    def test_full_citation_update_reads_whole_profile_and_marks_new_papers_unread(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "monitor.sqlite"
            storage = Storage(db_path)
            try:
                author = storage.add_author_monitor(scholar_profile("author-a", "Ada Author"))
                author_id = int(author["id"])
                storage.upsert_paper(paper("existing-paper", "Existing Paper", "2025-01-01"))
                storage.add_author_monitor_paper(
                    author_monitor_id=author_id,
                    paper_id="existing-paper",
                    unread=False,
                )
            finally:
                storage.close()

            calls = []

            def fake_fetch(_url, *, limit, sort_by_date=False):
                calls.append((limit, sort_by_date))
                profile = scholar_profile("author-a", "Ada Author")
                profile["homepage_url"] = "https://example.edu/ada"
                return {
                    "profile": profile,
                    "candidates": [{"key": "existing"}, {"key": "new"}],
                }

            def fake_normalize(candidate):
                if candidate["key"] == "existing":
                    return paper("existing-paper", "Existing Paper", "2025-01-01")
                return paper("backfilled-paper", "Backfilled Paper", "2024-01-01")

            with patch.object(
                ui_server,
                "fetch_google_scholar_profile_payload",
                side_effect=fake_fetch,
            ), patch.object(
                ui_server,
                "paper_from_publication_candidate",
                side_effect=fake_normalize,
            ), patch.object(
                ui_server,
                "scholar_candidate_key",
                side_effect=lambda candidate, _paper: candidate["key"],
            ):
                result = ui_server.refresh_author_monitor_for_db(
                    db_path,
                    author_id,
                    initial=False,
                    force=True,
                    full_metadata=True,
                )

            storage = Storage(db_path)
            try:
                saved_author = storage.get_author_monitor(author_id)
                rows = {
                    row["paper_id"]: row
                    for row in storage.list_author_monitor_papers(author_id)
                }
            finally:
                storage.close()

        self.assertTrue(result["full_metadata"])
        self.assertEqual(
            calls,
            [(ui_server.AUTHOR_MONITOR_INITIAL_IMPORT_LIMIT, False)],
        )
        self.assertEqual(saved_author["homepage_url"], "https://example.edu/ada")
        self.assertFalse(rows["existing-paper"]["author_unread"])
        self.assertTrue(rows["backfilled-paper"]["author_unread"])
        self.assertIn("1 new publication", result["message"])

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
        self.assertIn("google_scholar_citation_count", author_item)

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

    def test_author_monitor_exposes_global_scholar_safety_controls(self):
        html = ui_server.INDEX_HTML
        self.assertIn("scholarGlobalCooldown", html)
        self.assertIn("scholarGlobalCooldownActive()", html)
        self.assertIn("Profile URL or name and affiliations", html)
        self.assertIn("publisher", html.lower())
        self.assertIn("Profile search, add, and refresh are disabled.", html)
        self.assertIn('data-action="refresh-author" ${scholarGlobalCooldownActive() ? "disabled"', html)
        self.assertIn('data-action="update-all-scholar-citations"', html)
        self.assertIn("No other author will be refreshed automatically.", html)
        self.assertIn("full_metadata: true", html)
        self.assertIn("Update All Scholar Citations</button>", html)
        self.assertNotIn("Backfill Scholar Metadata", html)
        self.assertEqual(ui_server.AUTHOR_MONITOR_INITIAL_PAGE_PAUSE_MIN_SECONDS, 12.0)
        self.assertEqual(ui_server.AUTHOR_MONITOR_INITIAL_PAGE_PAUSE_MAX_SECONDS, 24.0)
        self.assertEqual(ui_server.AUTO_AUTHOR_MONITOR_STAGGER_MIN_SECONDS, 45.0)
        self.assertEqual(ui_server.AUTO_AUTHOR_MONITOR_STAGGER_MAX_SECONDS, 90.0)

    def test_author_monitor_restores_list_position_and_uses_conference_popover(self):
        html = ui_server.INDEX_HTML
        self.assertIn("authorMonitorListScrollTop", html)
        self.assertIn('article.closest(".author-monitor-paper-list")', html)
        self.assertIn("restoreStoredScroll", html)
        self.assertIn("author-monitor-conference-popover", html)
        self.assertIn("Conference publications", html)
        self.assertNotIn("author-monitor-conference-group", html)

    def test_global_search_is_explicitly_clickable_after_commit(self):
        html = ui_server.INDEX_HTML
        self.assertIn("-webkit-app-region: no-drag;", html)
        self.assertIn('closest(".library-search-wrap")?.addEventListener("pointerdown"', html)
        self.assertIn('input.focus({preventScroll: true})', html)
        self.assertIn("function searchInputCaretIndexFromPoint", html)
        self.assertIn("input.setSelectionRange?.(caret, caret)", html)

    def test_author_paper_card_content_is_vertically_centered_without_paint_clipping(self):
        html = ui_server.INDEX_HTML
        card_css = html.split(".author-paper-card {", 1)[1].split("}", 1)[0]
        scholar_css = html.split(".author-paper-scholar-citations {", 1)[1].split("}", 1)[0]
        citation_row_markup = html.split('<div class="author-paper-citation-row">', 1)[1].split("</div>", 1)[0]
        self.assertIn("align-content: center;", card_css)
        self.assertIn("padding: 11px 50px 11px 12px;", card_css)
        self.assertNotIn("content-visibility", card_css)
        self.assertNotIn("contain:", card_css)
        self.assertIn("justify-self: end;", scholar_css)
        self.assertNotIn("position: absolute", scholar_css)
        self.assertIn("author-paper-scholar-citations", citation_row_markup)

    def test_window_drag_region_never_covers_the_search_input(self):
        html = ui_server.INDEX_HTML
        drag_css = html.split(".window-drag-region {", 1)[1].split("}", 1)[0]
        self.assertIn("right: 430px;", drag_css)

    def test_author_profile_search_does_not_leave_stale_candidates_after_failure(self):
        html = ui_server.INDEX_HTML
        search = html.split("async function searchAuthorMonitorProfiles()", 1)[1].split(
            "async function addAuthorMonitorProfile", 1
        )[0]
        self.assertGreaterEqual(search.count("state.authorMonitorProfileResults = [];"), 2)
        self.assertIn("authorMonitorProfileSearchErrorMessage(error)", search)
        self.assertIn(
            "Profile search was interrupted before a new result arrived. Please try again.",
            html,
        )

    def test_author_add_and_delete_reconcile_interrupted_responses(self):
        html = ui_server.INDEX_HTML
        self.assertIn('result = {"status": "queued", "added": 0}', Path(ui_server.__file__).read_text())
        self.assertIn("pollAuthorMonitorInitialImport", html)
        self.assertIn("reconcileAddedAuthorMonitor(profile)", html)
        self.assertIn("SQLite confirms the deletion", html)
        self.assertIn('${alreadyMonitored ? "Monitored" : "Monitor"}', html)
        summary = html.split("async function refreshAuthorMonitorSummary()", 1)[1].split(
            "function startAuthorMonitorSummaryPolling", 1
        )[0]
        self.assertIn("previousSignature !== nextSignature", summary)
        self.assertIn("renderAuthorMonitor({preserveScroll: true})", summary)
        self.assertIn("pollAuthorMonitorInitialImport(Number(pendingImport.id))", summary)

    def test_author_remove_uses_an_in_app_safety_confirmation(self):
        html = ui_server.INDEX_HTML
        confirm = html.split("function confirmAuthorMonitorRemoval(author)", 1)[1].split(
            "async function deleteAuthorMonitor", 1
        )[0]
        remove = html.split("async function deleteAuthorMonitor(author)", 1)[1].split(
            "function showAuthorMonitorContextMenu", 1
        )[0]
        self.assertIn("Papers, PDFs, Library items, My Publications, analysis files", confirm)
        self.assertIn('data-confirm="remove"', confirm)
        self.assertIn("if (event.key === \"Escape\") finish(false)", confirm)
        self.assertNotIn("event.key === \"Enter\"", confirm)
        self.assertIn("await confirmAuthorMonitorRemoval(author)", remove)
        self.assertNotIn("window.confirm", remove)

    def test_author_status_bar_is_fixed_height_and_supports_two_channels(self):
        html = ui_server.INDEX_HTML
        css = html.split(
            ".author-monitor-status-bar .library-activity-status {", 1
        )[1].split("}", 1)[0]
        self.assertIn("width: fit-content", css)
        self.assertIn("white-space: nowrap", css)
        self.assertIn("text-overflow: ellipsis", css)
        self.assertIn('id="authorMonitorSecondaryActivityStatus"', html)
        self.assertIn("syncAuthorMonitorBackgroundScholarStatus", html)
        self.assertIn('"scholar-background"', html)
        self.assertIn('data-keyboard-pane=', html)

    def test_author_import_polling_preserves_the_users_current_selection(self):
        html = ui_server.INDEX_HTML
        polling = html.split(
            "async function pollAuthorMonitorInitialImport", 1
        )[1].split(
            "async function addAuthorMonitorProfile", 1
        )[0]
        self.assertIn(
            "snapshot.selectedAuthorId = Number(state.authorMonitorSelectedId || 0)",
            polling,
        )
        self.assertNotIn("snapshot.selectedAuthorId = Number(authorId)", polling)
        self.assertIn('channel: "secondary"', polling)
        self.assertIn('kind: "scholar-background"', polling)

    def test_author_importing_empty_state_explains_background_work(self):
        html = ui_server.INDEX_HTML
        rendering = html.split("function renderAuthorMonitor(options = {})", 1)[1].split(
            "async function openAuthorMonitor()", 1
        )[0]
        self.assertIn("authorMonitorIsBackgroundScholarJob(selected)", rendering)
        self.assertIn("author-monitor-importing-empty", rendering)
        self.assertIn("Importing ${escapeHtml(selected.name", rendering)
        self.assertIn("This import continues in the background.", rendering)

    def test_author_avatars_link_to_homepage_with_scholar_fallback(self):
        html = ui_server.INDEX_HTML
        avatar_links = html.split(
            "function authorMonitorAvatarDestination", 1
        )[1].split(
            "function renderAuthorMonitorRail", 1
        )[0]
        rendering = html.split("function renderAuthorMonitor(options = {})", 1)[1].split(
            "async function openAuthorMonitor()", 1
        )[0]
        self.assertIn("author?.homepage_url || author?.url", avatar_links)
        self.assertIn('data-author-avatar-link="', avatar_links)
        self.assertIn("wireAuthorMonitorAvatarLinks", avatar_links)
        self.assertIn('authorMonitorLinkedAvatarMarkup(selected, "header")', rendering)
        self.assertIn("wireAuthorMonitorAvatarLinks(root)", rendering)
        self.assertIn("Open Homepage", html)
        self.assertIn("Open Google Scholar", html)

    def test_full_scholar_citation_update_has_confirmed_and_direct_entry_points(self):
        html = ui_server.INDEX_HTML
        updating = html.split(
            "async function updateAllAuthorScholarCitations", 1
        )[1].split(
            "function confirmAuthorMonitorRemoval", 1
        )[0]
        rendering = html.split("function renderAuthorMonitor(options = {})", 1)[1].split(
            "async function openAuthorMonitor()", 1
        )[0]
        context_menu = html.split("function showAuthorMonitorContextMenu", 1)[1].split(
            "function renderPaper", 1
        )[0]
        self.assertIn("options.confirm !== false", updating)
        self.assertIn("confirmUpdateAllScholarCitations(author)", updating)
        self.assertIn("full_metadata: true", updating)
        self.assertIn('data-action="update-all-scholar-citations"', rendering)
        self.assertIn("updateAllAuthorScholarCitations(selected, {confirm: false})", rendering)
        self.assertIn('class="author-monitor-scholar-update-icon"', rendering)
        self.assertIn(">↻</span></button>", rendering)
        update_button_css = html.split(
            ".author-monitor-scholar-update-button {", 1
        )[1].split("}", 1)[0]
        self.assertIn("width: 18px", update_button_css)
        self.assertIn("border: 0", update_button_css)
        self.assertIn("background: transparent", update_button_css)
        self.assertIn("font-size: 10px", update_button_css)
        self.assertNotIn("author-paper-mini-button author-monitor-scholar-update-button", rendering)
        self.assertIn("setAuthorMonitorScholarUpdateButtonBusy(true)", updating)
        self.assertLess(
            updating.index("setAuthorMonitorScholarUpdateButtonBusy(true)"),
            updating.index('fetch("/api/author-monitor/refresh"'),
        )
        self.assertIn('channel: "secondary"', updating)
        self.assertIn("transform: translateY(1px)", html)
        self.assertIn("height: 54px", html)
        self.assertIn("height: 55px", html)
        self.assertIn("Update All Scholar Citations</button>", context_menu)
        self.assertIn("updateAllAuthorScholarCitations(author, {confirm: true})", context_menu)
        self.assertIn("newly discovered publications are marked as new", html)

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
