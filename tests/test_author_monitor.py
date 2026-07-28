import json
import sqlite3
import tempfile
import unittest
from datetime import date
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


def researchgate_profile(
    profile_url: str,
    name: str,
    *,
    openalex_author_id: str = "A123456789",
    semantic_scholar_author_id: str = "",
) -> dict:
    return {
        "source_type": "researchgate",
        "source_author_id": profile_url,
        "user_id": profile_url,
        "name": name,
        "url": profile_url,
        "affiliation": "Example University",
        "openalex_author_id": openalex_author_id,
        "semantic_scholar_author_id": semantic_scholar_author_id,
        "source_citation_total": 321,
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
    def test_existing_author_monitor_schema_migrates_before_source_index_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "monitor.sqlite"
            connection = sqlite3.connect(db_path)
            connection.executescript(
                """
                CREATE TABLE author_monitors (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  scholar_user_id TEXT NOT NULL UNIQUE,
                  name TEXT NOT NULL,
                  affiliation TEXT,
                  email TEXT,
                  cited_by TEXT,
                  interests_json TEXT,
                  profile_url TEXT NOT NULL,
                  homepage_url TEXT,
                  homepage_override_url TEXT,
                  scholar_citation_total INTEGER,
                  avatar_url TEXT,
                  sort_order INTEGER NOT NULL DEFAULT 0,
                  status TEXT NOT NULL DEFAULT 'idle',
                  message TEXT,
                  last_checked_at TEXT,
                  last_success_at TEXT,
                  cooldown_until TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                INSERT INTO author_monitors (
                  scholar_user_id, name, profile_url, created_at, updated_at
                ) VALUES (
                  'legacy-user', 'Legacy Author',
                  'https://scholar.google.com/citations?user=legacy-user',
                  '2026-07-26T00:00:00+08:00', '2026-07-26T00:00:00+08:00'
                );
                """
            )
            connection.commit()
            connection.close()

            storage = Storage(db_path)
            try:
                saved = storage.get_author_monitor(1)
                columns = {
                    row["name"]
                    for row in storage.conn.execute(
                        "PRAGMA table_info(author_monitors)"
                    ).fetchall()
                }
            finally:
                storage.close()

        self.assertEqual(saved["source_type"], "google_scholar")
        self.assertEqual(saved["source_author_id"], "legacy-user")
        self.assertIn("openalex_author_id", columns)
        self.assertIn("semantic_scholar_author_id", columns)
        self.assertIn("metadata_provider", columns)
        self.assertIn("source_citation_total", columns)
        self.assertIn("avatar_override_path", columns)

    def test_researchgate_monitor_uses_source_identity_without_scholar_collision(self):
        profile_url = "https://www.researchgate.net/profile/Ada-Lovelace-2"
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                first = storage.add_author_monitor(
                    researchgate_profile(profile_url, "Ada Lovelace")
                )
                duplicate = storage.add_author_monitor(
                    researchgate_profile(profile_url, "Different Name")
                )
                saved = ui_server.author_monitor_to_api(
                    storage.get_author_monitor(int(first["id"]))
                )
            finally:
                storage.close()

        self.assertEqual(first["id"], duplicate["id"])
        self.assertEqual(saved["source_type"], "researchgate")
        self.assertEqual(saved["source_author_id"], profile_url)
        self.assertEqual(saved["openalex_author_id"], "A123456789")
        self.assertEqual(saved["citation_total"], 321)
        self.assertEqual(saved["citation_source"], "OpenAlex")
        self.assertTrue(str(first["scholar_user_id"]).startswith("researchgate:"))

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

    def test_manual_homepage_override_survives_scholar_profile_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                profile = scholar_profile("homepage-override", "Homepage Override")
                profile["homepage_url"] = "https://scholar.example.edu/original"
                author = storage.add_author_monitor(profile)
                author_id = int(author["id"])
                storage.set_author_monitor_homepage_override(
                    author_id,
                    "https://custom.example.edu/home",
                )
                refreshed = dict(profile)
                refreshed["homepage_url"] = "https://scholar.example.edu/refreshed"
                storage.update_author_monitor(author_id, profile=refreshed)
                saved = storage.get_author_monitor(author_id)
                effective = ui_server.author_monitor_to_api(saved)
                storage.set_author_monitor_homepage_override(author_id, None)
                restored = ui_server.author_monitor_to_api(
                    storage.get_author_monitor(author_id)
                )
            finally:
                storage.close()

        self.assertEqual(
            saved["homepage_url"],
            "https://scholar.example.edu/refreshed",
        )
        self.assertEqual(
            saved["homepage_override_url"],
            "https://custom.example.edu/home",
        )
        self.assertEqual(
            effective["homepage_url"],
            "https://custom.example.edu/home",
        )
        self.assertEqual(
            effective["scholar_homepage_url"],
            "https://scholar.example.edu/refreshed",
        )
        self.assertEqual(restored["homepage_url"], "https://scholar.example.edu/refreshed")
        self.assertEqual(restored["homepage_override_url"], "")

    def test_manual_author_photo_survives_source_avatar_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "monitor.sqlite"
            photo_dir = Path(tmp) / "author_photos"
            photo_dir.mkdir()
            photo_path = photo_dir / "author-1.png"
            photo_path.write_bytes(b"\x89PNG\r\n\x1a\nexample")
            storage = Storage(db_path)
            try:
                profile = scholar_profile("photo-override", "Photo Override")
                profile["avatar_url"] = "https://scholar.example.edu/original.jpg"
                author = storage.add_author_monitor(profile)
                author_id = int(author["id"])
                storage.set_author_monitor_avatar_override(author_id, str(photo_path))
                refreshed = dict(profile)
                refreshed["avatar_url"] = "https://scholar.example.edu/refreshed.jpg"
                storage.update_author_monitor(author_id, profile=refreshed)
                saved = storage.get_author_monitor(author_id)
                effective = ui_server.author_monitor_to_api(saved)
            finally:
                storage.close()

        self.assertEqual(saved["avatar_url"], "https://scholar.example.edu/refreshed.jpg")
        self.assertEqual(saved["avatar_override_path"], str(photo_path))
        self.assertIn(
            f"/api/author-monitor/photo?author_id={author_id}",
            effective["avatar_url"],
        )
        self.assertEqual(
            effective["source_avatar_url"],
            "https://scholar.example.edu/refreshed.jpg",
        )

    def test_author_photo_upload_accepts_only_supported_image_content(self):
        self.assertEqual(
            ui_server.author_photo_type(b"\x89PNG\r\n\x1a\nexample"),
            ("png", "image/png"),
        )
        self.assertEqual(
            ui_server.author_photo_type(b"\xff\xd8\xffexample"),
            ("jpg", "image/jpeg"),
        )
        self.assertEqual(
            ui_server.author_photo_type(b"RIFF\x04\x00\x00\x00WEBPexample"),
            ("webp", "image/webp"),
        )
        with self.assertRaisesRegex(ValueError, "PNG, JPEG, or WebP"):
            ui_server.author_photo_type(b"not an image")

    def test_saving_author_photo_copies_it_to_managed_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "monitor.sqlite"
            storage = Storage(db_path)
            try:
                author = storage.add_author_monitor(
                    scholar_profile("managed-photo", "Managed Photo")
                )
                author_id = int(author["id"])
            finally:
                storage.close()

            updated = ui_server.save_author_monitor_photo(
                db_path,
                author_id,
                b"\x89PNG\r\n\x1a\nmanaged",
            )
            saved_path = Path(updated["avatar_override_path"])

            self.assertEqual(
                saved_path.parent.resolve(),
                (Path(tmp) / "author_photos").resolve(),
            )
            self.assertEqual(saved_path.name, f"author-{author_id}.png")
            self.assertEqual(saved_path.read_bytes(), b"\x89PNG\r\n\x1a\nmanaged")

    def test_author_citation_total_falls_back_to_saved_scholar_paper_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                author = storage.add_author_monitor(
                    scholar_profile("citation-total", "Citation Total")
                )
                candidate = paper("citation-paper", "Citation Paper", "2026-07-24")
                candidate["raw"] = {"google_scholar": {"citation_count": 1234}}
                storage.upsert_paper(candidate)
                storage.add_author_monitor_paper(
                    author_monitor_id=int(author["id"]),
                    paper_id="citation-paper",
                )
                saved = ui_server.author_monitor_to_api(
                    storage.get_author_monitor(int(author["id"]))
                )
            finally:
                storage.close()

        self.assertEqual(saved["scholar_citation_total"], 1234)

    def test_author_profile_citation_total_takes_priority_over_paper_sum(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                profile = scholar_profile("citation-priority", "Citation Priority")
                profile["scholar_citation_total"] = 5678
                author = storage.add_author_monitor(profile)
                candidate = paper("citation-priority-paper", "Citation Paper", "2026-07-24")
                candidate["raw"] = {"google_scholar": {"citation_count": 1234}}
                storage.upsert_paper(candidate)
                storage.add_author_monitor_paper(
                    author_monitor_id=int(author["id"]),
                    paper_id="citation-priority-paper",
                )
                saved = ui_server.author_monitor_to_api(
                    storage.get_author_monitor(int(author["id"]))
                )
            finally:
                storage.close()

        self.assertEqual(saved["scholar_citation_total"], 5678)

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

    def test_metadata_refresh_does_not_mark_existing_paper_new(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                author = storage.add_author_monitor(
                    scholar_profile("author-a", "Ada Author")
                )
                author_id = int(author["id"])
                original = paper("existing-paper", "Existing Paper", "2025-01-01")
                storage.upsert_paper(original)
                storage.add_author_monitor_paper(
                    author_monitor_id=author_id,
                    paper_id="existing-paper",
                    unread=False,
                )

                updated = dict(original)
                updated["journal"] = "Updated Journal"
                updated["doi"] = "10.1234/updated"
                storage.upsert_paper(updated)
                inserted = storage.add_author_monitor_paper(
                    author_monitor_id=author_id,
                    paper_id="existing-paper",
                    scholar_key="updated-scholar-key",
                    unread=True,
                )

                saved_author = storage.get_author_monitor(author_id)
                saved_paper = storage.list_author_monitor_papers(author_id)[0]
            finally:
                storage.close()

        self.assertFalse(inserted)
        self.assertEqual(saved_author["unread_count"], 0)
        self.assertFalse(saved_paper["author_unread"])

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

    def test_author_monitor_snapshot_loads_only_the_selected_author_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                first = storage.add_author_monitor(
                    scholar_profile("author-a", "Ada Author")
                )
                second = storage.add_author_monitor(
                    scholar_profile("author-b", "Ben Author")
                )
                storage.upsert_paper(
                    paper("ada-paper", "Ada Paper", "2026-07-24")
                )
                storage.upsert_paper(
                    paper("ben-paper", "Ben Paper", "2026-07-23")
                )
                storage.add_author_monitor_paper(
                    author_monitor_id=int(first["id"]),
                    paper_id="ada-paper",
                )
                storage.add_author_monitor_paper(
                    author_monitor_id=int(second["id"]),
                    paper_id="ben-paper",
                )

                initial = ui_server.author_monitor_snapshot(
                    storage,
                    author_monitor_id=-1,
                )
                selected = ui_server.author_monitor_snapshot(
                    storage,
                    author_monitor_id=int(second["id"]),
                )
                combined = ui_server.author_monitor_snapshot(
                    storage,
                    author_monitor_id=0,
                )
            finally:
                storage.close()

        self.assertEqual(initial["selectedAuthorId"], int(first["id"]))
        self.assertEqual(
            [item["paper_id"] for item in initial["papers"]],
            ["ada-paper"],
        )
        self.assertEqual(selected["selectedAuthorId"], int(second["id"]))
        self.assertEqual(
            [item["paper_id"] for item in selected["papers"]],
            ["ben-paper"],
        )
        self.assertEqual(
            {item["paper_id"] for item in combined["papers"]},
            {"ada-paper", "ben-paper"},
        )

    def test_author_monitor_card_index_is_persisted_and_incrementally_invalidated(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "monitor.sqlite"
            storage = Storage(db_path)
            try:
                first = storage.add_author_monitor(
                    scholar_profile("author-a", "Ada Author")
                )
                second = storage.add_author_monitor(
                    scholar_profile("author-b", "Ben Author")
                )
                storage.upsert_paper(
                    paper("shared-paper", "Original Title", "2026-07-24")
                )
                storage.add_author_monitor_paper(
                    author_monitor_id=int(first["id"]),
                    paper_id="shared-paper",
                    unread=True,
                )
                storage.add_author_monitor_paper(
                    author_monitor_id=int(second["id"]),
                    paper_id="shared-paper",
                )
                self.assertFalse(storage.author_monitor_card_cache_status()["ready"])

                rebuilt = ui_server.rebuild_author_monitor_card_cache(db_path)
                self.assertEqual(rebuilt, 1)
                index = ui_server.author_monitor_index_snapshot(storage)
                self.assertTrue(index["indexReady"])
                self.assertEqual(len(index["papers"]), 1)
                self.assertEqual(
                    set(index["papers"][0]["author_monitor_ids"]),
                    {int(first["id"]), int(second["id"])},
                )
                self.assertTrue(index["papers"][0]["author_unread"])
                self.assertNotIn("full_authors", index["papers"][0])

                storage.conn.execute(
                    "UPDATE papers SET title = ? WHERE paper_id = ?",
                    ("Updated Title", "shared-paper"),
                )
                storage.conn.commit()
                self.assertFalse(storage.author_monitor_card_cache_status()["ready"])
                self.assertEqual(
                    ui_server.author_monitor_index_snapshot(storage)["papers"],
                    [],
                )

                self.assertEqual(
                    ui_server.rebuild_author_monitor_card_cache(db_path),
                    1,
                )
                refreshed = ui_server.author_monitor_index_snapshot(storage)
                self.assertEqual(refreshed["papers"][0]["title"], "Updated Title")
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
            <table id="gsc_rsb_st"><tr><td class="gsc_rsb_std">12,345</td></tr></table>
            """,
            "html.parser",
        )
        profile = ui_server.google_scholar_profile_page_metadata(
            soup,
            "https://scholar.google.com/citations?user=ada",
            "ada",
        )

        self.assertEqual(profile["homepage_url"], "https://example.edu/ada")
        self.assertEqual(profile["scholar_citation_total"], 12345)

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

    def test_researchgate_url_search_matches_openalex_without_fetching_researchgate(self):
        search_text = (
            "https://www.researchgate.net/profile/Ada-Lovelace-2;"
            " Ada Lovelace; Example University"
        )
        with patch.object(
            ui_server,
            "openalex_api_key_param",
            return_value="test-key",
        ), patch.object(
            ui_server,
            "search_openalex_authors",
            return_value=[
                {
                    "openalex_author_id": "A123456789",
                    "name": "Ada Lovelace",
                    "affiliation": "Example University",
                    "orcid": "0000-0000-0000-0001",
                    "works_count": 42,
                    "cited_by_count": 1234,
                }
            ],
        ) as search:
            results = ui_server.researchgate_openalex_profiles(search_text)

        search.assert_called_once_with(
            "Ada Lovelace",
            affiliations=["Example University"],
            limit=12,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source_type"], "researchgate")
        self.assertEqual(results[0]["openalex_author_id"], "A123456789")
        self.assertEqual(results[0]["source_citation_total"], 1234)
        self.assertEqual(
            results[0]["url"],
            "https://www.researchgate.net/profile/Ada-Lovelace-2",
        )
        self.assertEqual(
            ui_server.normalize_researchgate_profile_url(
                "researchgate.net/profile/Ada-Lovelace-2?trackingId=ignored"
            ),
            "https://www.researchgate.net/profile/Ada-Lovelace-2",
        )

    def test_researchgate_url_search_falls_back_to_semantic_scholar_without_openalex_key(self):
        search_text = (
            "https://www.researchgate.net/scientific-contributions/"
            "Joseph-G-Checkelsky-13021838"
        )
        with patch.object(
            ui_server,
            "openalex_api_key_param",
            return_value=None,
        ), patch.object(
            ui_server,
            "search_openalex_authors",
            side_effect=AssertionError("OpenAlex must not be called without a key"),
        ), patch.object(
            ui_server,
            "search_semantic_scholar_authors",
            return_value=[
                {
                    "semantic_scholar_author_id": "47984093",
                    "name": "J. Checkelsky",
                    "affiliation": "MIT",
                    "works_count": 161,
                    "cited_by_count": 9973,
                }
            ],
        ) as search:
            results = ui_server.researchgate_openalex_profiles(search_text)

        search.assert_called_once_with(
            "Joseph G Checkelsky",
            affiliations=[],
            limit=12,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["semantic_scholar_author_id"], "47984093")
        self.assertEqual(results[0]["metadata_provider"], "Semantic Scholar")
        self.assertEqual(results[0]["source_citation_total"], 9973)
        self.assertEqual(
            results[0]["url"],
            "https://www.researchgate.net/scientific-contributions/"
            "Joseph-G-Checkelsky-13021838",
        )

    def test_researchgate_semantic_cross_match_requires_orcid_or_publication_overlap(self):
        profiles = [
            {
                "semantic_scholar_author_id": "47984093",
                "name": "J. Checkelsky",
                "affiliation": "MIT",
                "orcid": "",
            }
        ]
        with patch.object(
            ui_server,
            "search_semantic_scholar_authors",
            return_value=profiles,
        ), patch.object(
            ui_server,
            "fetch_semantic_scholar_author_publications",
        ) as publications:
            no_evidence = (
                ui_server.resolve_semantic_scholar_author_for_researchgate(
                    name="Joseph G. Checkelsky",
                    affiliation="MIT",
                    reference_papers=[],
                )
            )

        self.assertEqual(no_evidence, {})
        publications.assert_not_called()

        semantic_match = ui_server.normalize_semantic_scholar_item(
            {
                "paperId": "semantic-overlap",
                "externalIds": {"DOI": "10.1234/shared"},
                "title": "Shared publication",
                "venue": "Example Journal",
                "year": 2025,
            }
        )
        with patch.object(
            ui_server,
            "search_semantic_scholar_authors",
            return_value=profiles,
        ), patch.object(
            ui_server,
            "fetch_semantic_scholar_author_publications",
            return_value=[semantic_match],
        ):
            matched = (
                ui_server.resolve_semantic_scholar_author_for_researchgate(
                    name="Joseph G. Checkelsky",
                    affiliation="MIT",
                    reference_papers=[
                        {
                            "doi": "10.1234/shared",
                            "title": "Shared publication",
                            "publication_date": "2025",
                        }
                    ],
                )
            )

        self.assertEqual(
            matched["semantic_scholar_author_id"],
            "47984093",
        )
        self.assertEqual(matched["match_evidence"], "doi:1")

    def test_researchgate_semantic_cross_match_accepts_exact_orcid_without_paper_calls(self):
        with patch.object(
            ui_server,
            "search_semantic_scholar_authors",
            return_value=[
                {
                    "semantic_scholar_author_id": "47984093",
                    "name": "J. Checkelsky",
                    "affiliation": "",
                    "orcid": "0000-0002-1234-567X",
                }
            ],
        ), patch.object(
            ui_server,
            "fetch_semantic_scholar_author_publications",
        ) as publications:
            matched = (
                ui_server.resolve_semantic_scholar_author_for_researchgate(
                    name="Joseph G. Checkelsky",
                    orcid="https://orcid.org/0000-0002-1234-567X",
                    reference_papers=[],
                )
            )

        self.assertEqual(matched["match_evidence"], "orcid")
        publications.assert_not_called()

    def test_researchgate_semantic_backfill_persists_confirmed_id_and_attempt(self):
        profile_url = "https://www.researchgate.net/profile/Ada-Lovelace-2"
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                author = storage.add_author_monitor(
                    researchgate_profile(
                        profile_url,
                        "Ada Lovelace",
                        openalex_author_id="A123456789",
                    )
                )
                with patch.object(
                    ui_server,
                    "resolve_semantic_scholar_author_for_researchgate",
                    return_value={
                        "semantic_scholar_author_id": "987654321",
                        "match_evidence": "doi:2",
                    },
                ):
                    match = ui_server.backfill_researchgate_semantic_author(
                        storage,
                        author,
                        reference_papers=[
                            {
                                "doi": "10.1234/shared",
                                "title": "Shared publication",
                                "publication_date": "2025",
                            }
                        ],
                    )
                saved = storage.get_author_monitor(int(author["id"]))
                backfill_state = json.loads(
                    storage.get_setting(
                        ui_server.researchgate_semantic_backfill_setting(
                            int(author["id"])
                        ),
                        "",
                    )
                )
            finally:
                storage.close()

        self.assertEqual(match["semantic_scholar_author_id"], "987654321")
        self.assertEqual(saved["semantic_scholar_author_id"], "987654321")
        self.assertEqual(backfill_state["status"], "matched")
        self.assertEqual(backfill_state["evidence"], "doi:2")

    def test_researchgate_refresh_uses_openalex_during_scholar_cooldown(self):
        profile_url = "https://www.researchgate.net/profile/Ada-Lovelace-2"
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "monitor.sqlite"
            storage = Storage(db_path)
            try:
                author = storage.add_author_monitor(
                    researchgate_profile(profile_url, "Ada Lovelace")
                )
                author_id = int(author["id"])
                ui_server.start_google_scholar_global_cooldown(
                    storage,
                    message="Scholar unusual traffic",
                )
            finally:
                storage.close()

            first_paper = paper("oa-old", "OpenAlex Existing Paper", "2025-01-01")
            first_paper["source"] = "openalex"
            first_paper["raw"] = {
                "id": "https://openalex.org/W1",
                "cited_by_count": 17,
            }
            second_paper = paper("oa-new", "OpenAlex New Paper", "2026-07-26")
            second_paper["source"] = "openalex"
            second_paper["raw"] = {
                "id": "https://openalex.org/W2",
                "cited_by_count": 29,
            }
            publication_payloads = [[first_paper], [first_paper, second_paper]]

            with patch.object(
                ui_server,
                "fetch_google_scholar_profile_payload",
                side_effect=AssertionError("ResearchGate monitors must not request Scholar"),
            ), patch.object(
                ui_server,
                "backfill_researchgate_semantic_author",
                return_value={},
            ), patch.object(
                ui_server,
                "fetch_openalex_author_profile",
                return_value={
                    "openalex_author_id": "A123456789",
                    "name": "Ada Lovelace",
                    "affiliation": "Example University",
                    "orcid": "0000-0000-0000-0001",
                    "works_count": 2,
                    "cited_by_count": 456,
                },
            ) as fetch_profile, patch.object(
                ui_server,
                "fetch_openalex_author_publications",
                side_effect=lambda *_args, **_kwargs: publication_payloads.pop(0),
            ) as fetch_publications:
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

            storage = Storage(db_path)
            try:
                saved = ui_server.author_monitor_to_api(
                    storage.get_author_monitor(author_id)
                )
                rows = {
                    row["paper_id"]: row
                    for row in storage.list_author_monitor_papers(author_id)
                }
                paper_api = {
                    row["paper_id"]: ui_server.author_monitor_paper_to_api(row)
                    for row in storage.list_author_monitor_papers(author_id)
                }
            finally:
                storage.close()

        self.assertEqual(baseline["status"], "success")
        self.assertTrue(baseline["baseline"])
        self.assertEqual(update["status"], "success")
        self.assertEqual(update["added"], 1)
        self.assertEqual(fetch_profile.call_count, 2)
        self.assertEqual(fetch_publications.call_count, 2)
        self.assertEqual(saved["citation_total"], 456)
        self.assertEqual(saved["citation_source"], "OpenAlex")
        self.assertFalse(rows["oa-old"]["author_unread"])
        self.assertTrue(rows["oa-new"]["author_unread"])
        self.assertEqual(paper_api["oa-new"]["citation_count"], 29)
        self.assertEqual(paper_api["oa-new"]["citation_count_source"], "OpenAlex")

    def test_researchgate_refresh_uses_semantic_scholar_during_scholar_cooldown(self):
        profile_url = (
            "https://www.researchgate.net/scientific-contributions/"
            "Joseph-G-Checkelsky-13021838"
        )
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "monitor.sqlite"
            storage = Storage(db_path)
            try:
                author = storage.add_author_monitor(
                    researchgate_profile(
                        profile_url,
                        "J. Checkelsky",
                        openalex_author_id="",
                        semantic_scholar_author_id="47984093",
                    )
                )
                author_id = int(author["id"])
                ui_server.start_google_scholar_global_cooldown(
                    storage,
                    message="Scholar unusual traffic",
                )
            finally:
                storage.close()

            def semantic_paper(paper_id: str, title: str, year: int, citations: int):
                return ui_server.normalize_semantic_scholar_item(
                    {
                        "paperId": paper_id,
                        "title": title,
                        "venue": "Example Journal",
                        "year": year,
                        "citationCount": citations,
                        "url": f"https://www.semanticscholar.org/paper/{paper_id}",
                    }
                )

            first_paper = semantic_paper(
                "semantic-old",
                "Semantic Existing Paper",
                2025,
                17,
            )
            second_paper = semantic_paper(
                "semantic-new",
                "Semantic New Paper",
                2026,
                29,
            )
            publication_payloads = [[first_paper], [first_paper, second_paper]]

            with patch.object(
                ui_server,
                "fetch_google_scholar_profile_payload",
                side_effect=AssertionError("ResearchGate monitors must not request Scholar"),
            ), patch.object(
                ui_server,
                "fetch_semantic_scholar_author_profile",
                return_value={
                    "semantic_scholar_author_id": "47984093",
                    "name": "J. Checkelsky",
                    "works_count": 2,
                    "cited_by_count": 456,
                },
            ) as fetch_profile, patch.object(
                ui_server,
                "fetch_semantic_scholar_author_publications",
                side_effect=lambda *_args, **_kwargs: publication_payloads.pop(0),
            ) as fetch_publications:
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

            storage = Storage(db_path)
            try:
                saved = ui_server.author_monitor_to_api(
                    storage.get_author_monitor(author_id)
                )
                rows = {
                    row["paper_id"]: row
                    for row in storage.list_author_monitor_papers(author_id)
                }
                paper_api = {
                    row["paper_id"]: ui_server.author_monitor_paper_to_api(row)
                    for row in storage.list_author_monitor_papers(author_id)
                }
            finally:
                storage.close()

        self.assertEqual(baseline["status"], "success")
        self.assertTrue(baseline["baseline"])
        self.assertEqual(update["status"], "success")
        self.assertEqual(update["added"], 1)
        self.assertEqual(fetch_profile.call_count, 2)
        self.assertEqual(fetch_publications.call_count, 2)
        self.assertEqual(saved["citation_total"], 456)
        self.assertEqual(saved["citation_source"], "Semantic Scholar")
        self.assertFalse(rows["semantic_semantic-old"]["author_unread"])
        self.assertTrue(rows["semantic_semantic-new"]["author_unread"])
        self.assertEqual(paper_api["semantic_semantic-new"]["citation_count"], 29)
        self.assertEqual(
            paper_api["semantic_semantic-new"]["citation_count_source"],
            "Semantic Scholar",
        )

    def test_researchgate_openalex_refresh_falls_back_to_confirmed_semantic_author(self):
        profile_url = "https://www.researchgate.net/profile/Ada-Lovelace-2"
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "monitor.sqlite"
            storage = Storage(db_path)
            try:
                author = storage.add_author_monitor(
                    researchgate_profile(
                        profile_url,
                        "Ada Lovelace",
                        openalex_author_id="A123456789",
                        semantic_scholar_author_id="987654321",
                    )
                )
                author_id = int(author["id"])
            finally:
                storage.close()

            semantic_paper = ui_server.normalize_semantic_scholar_item(
                {
                    "paperId": "semantic-fallback",
                    "title": "Fallback publication",
                    "venue": "Example Journal",
                    "year": 2026,
                    "citationCount": 44,
                }
            )
            with patch.object(
                ui_server,
                "fetch_openalex_author_profile",
                return_value={
                    "openalex_author_id": "A123456789",
                    "name": "Ada Lovelace",
                },
            ), patch.object(
                ui_server,
                "fetch_openalex_author_publications",
                side_effect=ui_server.OpenAlexDailyLimitError(
                    "free limit reached"
                ),
            ), patch.object(
                ui_server,
                "fetch_semantic_scholar_author_profile",
                return_value={
                    "semantic_scholar_author_id": "987654321",
                    "name": "Ada Lovelace",
                    "cited_by_count": 777,
                },
            ), patch.object(
                ui_server,
                "fetch_semantic_scholar_author_publications",
                return_value=[semantic_paper],
            ):
                result = ui_server.refresh_author_monitor_for_db(
                    db_path,
                    author_id,
                    initial=True,
                    force=True,
                )

            storage = Storage(db_path)
            try:
                saved = ui_server.author_monitor_to_api(
                    storage.get_author_monitor(author_id)
                )
                rows = storage.list_author_monitor_papers(author_id)
                paper_api = ui_server.author_monitor_paper_to_api(rows[0])
            finally:
                storage.close()

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["metadata_provider"], "Semantic Scholar")
        self.assertIn("OpenAlex was unavailable", result["message"])
        self.assertEqual(saved["metadata_provider"], "Semantic Scholar")
        self.assertEqual(saved["citation_source"], "Semantic Scholar")
        self.assertEqual(saved["citation_total"], 777)
        self.assertEqual(paper_api["citation_count"], 44)
        self.assertEqual(
            paper_api["citation_count_source"],
            "Semantic Scholar",
        )

    def test_automatic_refresh_keeps_scholar_spacing_across_openalex_authors(self):
        profile_url = "https://www.researchgate.net/profile/Ada-Lovelace-2"
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "monitor.sqlite"
            storage = Storage(db_path)
            try:
                storage.add_author_monitor(scholar_profile("scholar-a", "Scholar A"))
                storage.add_author_monitor(
                    researchgate_profile(profile_url, "OpenAlex Author")
                )
                storage.add_author_monitor(scholar_profile("scholar-b", "Scholar B"))
            finally:
                storage.close()

            refreshed: list[int] = []
            with patch.object(
                ui_server,
                "refresh_author_monitor_for_db",
                side_effect=lambda _db, author_id, **_kwargs: (
                    refreshed.append(author_id)
                    or {"author_id": author_id, "status": "success", "added": 0}
                ),
            ), patch.object(
                ui_server.random,
                "uniform",
                return_value=52.0,
            ), patch.object(
                ui_server.time,
                "sleep",
            ) as sleep:
                result = ui_server.run_auto_author_monitor_once(
                    db_path,
                    date(2026, 7, 26),
                )

        self.assertEqual(len(refreshed), 3)
        self.assertEqual(len(result["results"]), 3)
        sleep.assert_called_once_with(52.0)

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

    def test_author_card_uses_the_most_recent_confirmed_metadata_provider(self):
        item = ui_server.author_monitor_paper_to_api(
            {
                "paper_id": "provider-paper",
                "title": "Provider fallback",
                "journal": "Example Journal",
                "publication_date": "2026",
                "raw_json": json.dumps(
                    {
                        "openalex_author_monitor": {
                            "cited_by_count": 11,
                            "checked_at": "2026-07-26T10:00:00+08:00",
                        },
                        "semantic_scholar_author_monitor": {
                            "citation_count": 14,
                            "checked_at": "2026-07-27T10:00:00+08:00",
                        },
                    }
                ),
            }
        )

        self.assertEqual(item["citation_count"], 14)
        self.assertEqual(item["citation_count_source"], "Semantic Scholar")

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
        self.assertIn("ResearchGate metadata sources remain available.", html)
        self.assertIn("authorMonitorQueryIsResearchGate", html)
        self.assertIn('data-action="refresh-author" ${refreshDisabled ? "disabled"', html)
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

    def test_conference_popover_is_compact_clipped_and_preserves_its_scroll(self):
        html = ui_server.INDEX_HTML
        popover_css = html.split(".author-monitor-conference-popover {", 1)[1].split(
            "}", 1
        )[0]
        cards_css = html.split(".author-monitor-conference-cards {", 1)[1].split(
            "}", 1
        )[0]
        conference_logic = html.split(
            "function authorMonitorPaperIsConferenceAbstract", 1
        )[1].split(
            "function authorMonitorPaperHasIdentifier", 1
        )[0]
        rendering = html.split("function renderAuthorMonitor(options = {})", 1)[1].split(
            "async function openAuthorMonitor()", 1
        )[0]
        self.assertIn("grid-template-rows: auto minmax(0, 1fr)", popover_css)
        self.assertIn("overflow: hidden", popover_css)
        self.assertIn("width: min(410px", popover_css)
        self.assertIn("min-height: 0", cards_css)
        self.assertIn("overflow-y: auto", cards_css)
        self.assertNotIn("100vh", cards_css)
        self.assertIn(".author-monitor-conference-cards .author-paper-title", html)
        conference_card_css = html.split(
            ".author-monitor-conference-cards .author-paper-card {", 1
        )[1].split("}", 1)[0]
        conference_title_css = html.split(
            ".author-monitor-conference-cards .author-paper-title {", 1
        )[1].split("}", 1)[0]
        self.assertIn("height: 76px", conference_card_css)
        self.assertIn("align-content: start", conference_card_css)
        self.assertIn("overflow: hidden", conference_card_css)
        self.assertIn("font-size: 13px", conference_title_css)
        self.assertIn("font-weight: 600", conference_title_css)
        self.assertIn("color: #596575", conference_title_css)
        self.assertIn("-webkit-line-clamp: 2", conference_title_css)
        self.assertIn('"meeting"', conference_logic)
        self.assertIn('"abstract"', conference_logic)
        self.assertIn('"conference"', conference_logic)
        self.assertIn("authorMonitorConferenceScrollTop", rendering)
        self.assertIn("conferenceCards.scrollTop", rendering)
        self.assertIn("previousConferenceScroll", rendering)
        outside_click = html.split(
            'if (state.mode !== "author" || !state.authorMonitorConferenceExpanded) return;',
            1,
        )[1].split('window.addEventListener("click"', 1)[0]
        self.assertIn('target.closest?.(".author-monitor-detail")', outside_click)
        self.assertIn('target.closest?.(".author-monitor-conference-popover")', outside_click)
        self.assertIn("event.stopImmediatePropagation()", outside_click)
        self.assertIn("state.authorMonitorConferenceExpanded = false", outside_click)

    def test_global_search_is_explicitly_clickable_after_commit(self):
        html = ui_server.INDEX_HTML
        self.assertIn("-webkit-app-region: no-drag;", html)
        self.assertIn('closest(".library-search-wrap")?.addEventListener("pointerdown"', html)
        search_pointer = html.split(
            '$("librarySearchBox").closest(".library-search-wrap")?.addEventListener("pointerdown"',
            1,
        )[1].split("}, {capture: true});", 1)[0]
        self.assertIn("event.preventDefault()", search_pointer)
        self.assertIn("event.stopPropagation()", search_pointer)
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
            "if (activeAuthorId === Number(authorId))",
            polling,
        )
        self.assertIn(
            "state.authorMonitors = Array.isArray(snapshot.authors)",
            polling,
        )
        self.assertNotIn("snapshot.selectedAuthorId =", polling)
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

    def test_author_monitor_new_filter_is_after_conferences(self):
        html = ui_server.INDEX_HTML
        rendering = html.split("function renderAuthorMonitor(options = {})", 1)[1].split(
            "async function openAuthorMonitor()", 1
        )[0]
        conference_position = rendering.index("author-monitor-conference-toggle")
        new_filter_position = rendering.index('data-action="filter-new-papers"')
        self.assertLess(conference_position, new_filter_position)
        self.assertIn(">New</button>", rendering)
        self.assertIn(
            "state.authorMonitorUnreadOnly = !state.authorMonitorUnreadOnly",
            rendering,
        )

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

    def test_author_monitor_distinguishes_researchgate_and_metadata_refresh(self):
        html = ui_server.INDEX_HTML
        dialog = html.split('id="authorMonitorBackdrop"', 1)[1].split("</div>", 8)[0]
        rendering = html.split("function renderAuthorMonitor(options = {})", 1)[1].split(
            "async function openAuthorMonitor()", 1
        )[0]
        context_menu = html.split("function showAuthorMonitorContextMenu", 1)[1].split(
            "function renderPaper", 1
        )[0]
        self.assertIn("ResearchGate profile URL", dialog)
        self.assertIn(
            "ResearchGate authors use OpenAlex when configured, with Semantic Scholar as the automatic fallback.",
            html,
        )
        self.assertIn('author-monitor-source-badge${authorMonitorIsScholar(author) ? "" : " researchgate"}', html)
        header_name = rendering.split(
            '<div class="author-monitor-list-head-name-row">', 1
        )[1].split("</div>", 1)[0]
        self.assertNotIn("author-monitor-source-badge", header_name)
        self.assertIn("authorMonitorMetadataProvider(selected)", rendering)
        self.assertIn('data-action="open-author-profile"', context_menu)
        self.assertIn('"Google Scholar" : "ResearchGate"', context_menu)
        self.assertIn("${scholarAuthor ?", context_menu)

    def test_author_homepage_editor_uses_exact_labels_without_ellipses(self):
        html = ui_server.INDEX_HTML
        editor = html.split("function openAuthorHomepageEditor", 1)[1].split(
            "function showAuthorMonitorContextMenu", 1
        )[0]
        context_menu = html.split("function showAuthorMonitorContextMenu", 1)[1].split(
            "function renderPaper", 1
        )[0]
        summary = html.split("function authorMonitorSummaryText()", 1)[1].split(
            "function selectedAuthorMonitorPaper", 1
        )[0]
        self.assertIn("/api/author-monitor/homepage", editor)
        self.assertIn(">Use Scholar Homepage</button>", editor)
        self.assertIn(">Cancel</button>", editor)
        self.assertIn(">Save Homepage</button>", editor)
        self.assertIn(">Edit Homepage</button>", context_menu)
        self.assertNotIn("Edit Homepage…", html)
        self.assertNotIn("Edit Homepage...", html)
        self.assertIn('toLocaleString("en-US")', summary)
        self.assertIn('citations (${author.citation_source || author.source_label || "Source"})', summary)
        self.assertIn("citationRaw === null", summary)

    def test_author_context_menu_can_upload_or_change_a_photo(self):
        html = ui_server.INDEX_HTML
        chooser = html.split("function chooseAuthorMonitorPhoto", 1)[1].split(
            "function showAuthorMonitorContextMenu", 1
        )[0]
        context_menu = html.split("function showAuthorMonitorContextMenu", 1)[1].split(
            "function renderPaper", 1
        )[0]
        self.assertIn("window.webkit?.messageHandlers?.authorPhotoChooser", chooser)
        self.assertIn("nativeChooser.postMessage", chooser)
        self.assertIn("window.handleNativeAuthorPhotoSelection", html)
        self.assertIn('fetch("/api/author-monitor/photo/path"', html)
        self.assertIn('fetch("/api/author-monitor/photo/choose"', chooser)
        self.assertIn("Choose a photo for", chooser)
        self.assertIn("Photo selection cancelled.", chooser)
        self.assertIn('"Change Photo" : "Add Photo"', context_menu)
        self.assertIn('data-action="edit-author-photo"', context_menu)
        self.assertNotIn("Add Photo...", html)
        self.assertNotIn("Change Photo...", html)

        native_app = (
            Path(__file__).resolve().parents[1] / "scripts" / "PaperMonitorApp.m"
        ).read_text(encoding="utf-8")
        self.assertIn('addScriptMessageHandler:self name:@"authorPhotoChooser"', native_app)
        self.assertIn("NSOpenPanel *panel", native_app)
        self.assertIn('panel.prompt = @"Choose Photo"', native_app)
        self.assertIn("handleNativeAuthorPhotoSelection", native_app)

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
        self.assertIn("height: 76px", html)
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

    def test_author_monitor_prefetches_a_persistent_full_card_index(self):
        html = ui_server.INDEX_HTML
        self.assertIn('AUTHOR_MONITOR_SELECTION_STORAGE_KEY = "daiqo-author-monitor-selected-id"', html)
        self.assertIn("async function loadAuthorMonitorScope", html)
        self.assertIn("function prefetchAuthorMonitorIndex", html)
        self.assertIn('fetchJson("/api/author-monitor?index=1"', html)
        self.assertIn("state.authorMonitorIndexLoaded", html)
        self.assertIn("applyAuthorMonitorIndex(data)", html)
        self.assertIn("authorMonitorSelectedPaperByAuthor: new Map()", html)
        snapshot_apply = html.split("function applyAuthorMonitorSnapshot", 1)[1].split(
            "function applyAuthorMonitorIndex", 1
        )[0]
        self.assertIn("preserveFullIndex", snapshot_apply)
        self.assertIn("state.authorMonitorPapers = [...merged.values()]", snapshot_apply)
        self.assertIn("rememberCurrentAuthorMonitorPapers()", html)
        self.assertIn("restoreCachedAuthorMonitorPapers(requestedId)", html)
        self.assertIn("state.authorMonitorViewCache?.key === cacheKey", html)
        self.assertIn("scheduleAuthorMonitorIdleEnrichment", html)
        self.assertIn("startAuthorMonitorEnrichment(targetAuthorId, {maxPapers: 80})", html)
        self.assertIn("max_papers: request.maxPapers", html)

    def test_author_monitor_empty_scope_restores_without_discarding_last_good_papers(self):
        html = ui_server.INDEX_HTML
        loader = html.split("async function loadAuthorMonitorScope", 1)[1].split(
            "function selectAuthorMonitorScope", 1
        )[0]
        self.assertNotIn("state.authorMonitorPapers = []", loader)
        self.assertIn("papers: state.authorMonitorPapers", loader)
        self.assertIn("state.authorMonitorPapers = previous.papers", loader)
        self.assertIn("authorMonitorScopeHasExpectedPapers(requestedId)", loader)
        self.assertIn("function scheduleAuthorMonitorEmptyViewRecovery()", html)
        self.assertIn("The local paper count is intact. Reloading this view from SQLite.", html)
        self.assertIn('document.documentElement.dataset.authorMonitorIndex = "stale"', html)

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
