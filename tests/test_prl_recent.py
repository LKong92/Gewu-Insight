from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from paper_monitor.aps import is_aps_lifecycle_journal
from paper_monitor.config import JournalConfig
from paper_monitor.monitor import apply_fast_section_hints, dedup_by_id
from paper_monitor.reporting import section_badge_background, section_color
from paper_monitor.sources.crossref import fetch_crossref_journal, normalize_crossref_item
from paper_monitor.sources.openalex import normalize_openalex_item
from paper_monitor.storage import Storage


def crossref_item(
    *,
    formal: bool,
    published: tuple[int, int, int],
    doi: str = "10.1103/3gg8-wgdr",
    journal: str = "Physical Review Letters",
) -> dict:
    item = {
        "DOI": doi,
        "URL": f"https://doi.org/{doi}",
        "title": ["Volume-Law Protection of Metrological Advantage"],
        "container-title": [journal],
        "published-online": {"date-parts": [list(published)]},
        "issued": {"date-parts": [list(published)]},
        "type": "journal-article",
    }
    if formal:
        item.update(
            {"volume": "16", "issue": "3", "article-number": "031006"}
            if journal == "Physical Review X"
            else {"volume": "137", "issue": "3", "article-number": "030801"}
        )
    return item


def openalex_item(
    *,
    formal: bool,
    published: str,
    doi: str = "10.1103/g565-3dyn",
    journal: str = "Physical Review X",
) -> dict:
    return {
        "id": "https://openalex.org/W123",
        "doi": f"https://doi.org/{doi}",
        "title": "Topological defect propagation to classify knitted fabrics",
        "publication_date": published,
        "type": "article",
        "biblio": {"volume": "16" if formal else None, "issue": "3" if formal else None},
        "primary_location": {
            "landing_page_url": f"https://doi.org/{doi}",
            "pdf_url": "",
            "version": "publishedVersion" if formal else "acceptedVersion",
            "source": {"display_name": journal},
        },
    }


class PrlRecentTests(unittest.TestCase):
    def test_published_and_preprint_titles_use_normal_article_green(self) -> None:
        for section in ("article", "research article", "published", "preprint"):
            self.assertEqual(section_color(section), "#17643b")
            self.assertEqual(section_badge_background(section), "#e9f7ef")

    def test_crossref_cursor_can_be_reused_for_the_next_page(self) -> None:
        class Response:
            def __init__(self, payload: dict) -> None:
                self.payload = payload

            def json(self) -> dict:
                return self.payload

        pages = [
            Response(
                {
                    "message": {
                        "items": [
                            {
                                **crossref_item(formal=True, published=(2026, 7, 13)),
                                "DOI": "10.1103/first-page",
                            }
                        ],
                        "next-cursor": "reused-scroll-cursor",
                    }
                }
            ),
            Response(
                {
                    "message": {
                        "items": [
                            {
                                **crossref_item(formal=True, published=(2026, 7, 13)),
                                "DOI": "10.1103/second-page",
                            }
                        ],
                        "next-cursor": "reused-scroll-cursor",
                    }
                }
            ),
            Response({"message": {"items": [], "next-cursor": "reused-scroll-cursor"}}),
        ]
        with patch("paper_monitor.sources.crossref.request_with_retries", side_effect=pages) as request:
            papers = fetch_crossref_journal(
                journal_name="Physical Review Letters",
                issns=["1079-7114"],
                start_date=date(2026, 7, 13),
                end_date=date(2026, 7, 13),
                rows=1,
                max_pages=3,
            )

        self.assertEqual([paper["doi"] for paper in papers], ["10.1103/first-page", "10.1103/second-page"])
        self.assertEqual(request.call_count, 3)

    def test_crossref_normalization_hides_accepted_and_allows_formal_prl(self) -> None:
        accepted = normalize_crossref_item(
            crossref_item(formal=False, published=(2026, 6, 8)),
            "Physical Review Letters",
        )
        formal = normalize_crossref_item(
            crossref_item(formal=True, published=(2026, 7, 13)),
            "Physical Review Letters",
        )

        self.assertEqual(accepted["publisher_section"], "accepted")
        self.assertFalse(accepted["section_allowed"])
        self.assertEqual(formal["publisher_section"], "published")
        self.assertTrue(formal["section_allowed"])

    def test_crossref_normalization_hides_accepted_and_allows_formal_prx(self) -> None:
        accepted = normalize_crossref_item(
            crossref_item(
                formal=False,
                published=(2026, 7, 8),
                doi="10.1103/cbrd-ssnm",
                journal="Physical Review X",
            ),
            "Physical Review X",
        )
        formal = normalize_crossref_item(
            crossref_item(
                formal=True,
                published=(2026, 7, 14),
                doi="10.1103/g565-3dyn",
                journal="Physical Review X",
            ),
            "Physical Review X",
        )

        self.assertEqual(accepted["publisher_section"], "accepted")
        self.assertFalse(accepted["section_allowed"])
        self.assertEqual(formal["publisher_section"], "published")
        self.assertTrue(formal["section_allowed"])

    def test_rmp_uses_the_same_accepted_and_published_lifecycle(self) -> None:
        journal = "Reviews of Modern Physics"
        accepted = normalize_crossref_item(
            crossref_item(
                formal=False,
                published=(2026, 7, 14),
                doi="10.1103/j9ly-b6q3",
                journal=journal,
            ),
            journal,
        )
        formal_crossref_raw = crossref_item(
            formal=True,
            published=(2026, 8, 3),
            doi="10.1103/revmodphys.98.031001",
            journal=journal,
        )
        formal_crossref_raw.update(
            {"volume": "98", "issue": "3", "article-number": "031001"}
        )
        formal = normalize_crossref_item(formal_crossref_raw, journal)
        openalex_accepted = normalize_openalex_item(
            openalex_item(
                formal=False,
                published="2026-07-14",
                doi="10.1103/j9ly-b6q3",
                journal=journal,
            ),
            journal,
        )

        self.assertTrue(is_aps_lifecycle_journal(journal))
        self.assertEqual(accepted["publisher_section"], "accepted")
        self.assertFalse(accepted["section_allowed"])
        self.assertEqual(openalex_accepted["publisher_section"], "accepted")
        self.assertFalse(openalex_accepted["section_allowed"])
        self.assertEqual(formal["publisher_section"], "published")
        self.assertTrue(formal["section_allowed"])

    def test_openalex_prx_status_and_dedup_prefer_formal_version(self) -> None:
        accepted = normalize_crossref_item(
            crossref_item(
                formal=False,
                published=(2026, 6, 20),
                doi="10.1103/g565-3dyn",
                journal="Physical Review X",
            ),
            "Physical Review X",
        )
        formal = normalize_openalex_item(
            openalex_item(formal=True, published="2026-07-14"),
            "Physical Review X",
        )
        openalex_accepted = normalize_openalex_item(
            openalex_item(formal=False, published="2026-07-08", doi="10.1103/cbrd-ssnm"),
            "Physical Review X",
        )

        merged = dedup_by_id([accepted, formal])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["publisher_section"], "published")
        self.assertTrue(merged[0]["section_allowed"])
        self.assertEqual(merged[0]["publication_date"], "2026-07-14")
        self.assertEqual(merged[0]["source"], "crossref+openalex")
        self.assertEqual(openalex_accepted["publisher_section"], "accepted")
        self.assertFalse(openalex_accepted["section_allowed"])

    def test_science_title_heuristics_do_not_hide_formal_aps_research(self) -> None:
        formal = normalize_crossref_item(
            {
                **crossref_item(
                    formal=True,
                    published=(2026, 5, 22),
                    doi="10.1103/nvbm-97vs",
                    journal="Physical Review X",
                ),
                "title": ["Passive quantum error correction of photon loss at breakeven"],
            },
            "Physical Review X",
        )
        journal = JournalConfig(
            name="Physical Review X",
            issns=["2160-3308"],
            openalex_source_id="S137042341",
            section_policy="science",
            skip_landing_enrichment=True,
        )

        apply_fast_section_hints(formal, journal)

        self.assertEqual(formal["publisher_section"], "published")
        self.assertTrue(formal["section_allowed"])

    def test_formal_record_replaces_same_doi_accepted_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "papers.sqlite")
            accepted = normalize_crossref_item(
                crossref_item(formal=False, published=(2026, 6, 8)),
                "Physical Review Letters",
            )
            storage.upsert_paper(accepted)
            storage.update_download_status(
                accepted["paper_id"],
                status="success",
                main_pdf_path="data/pdfs/existing.pdf",
            )

            formal = normalize_crossref_item(
                crossref_item(formal=True, published=(2026, 7, 13)),
                "Physical Review Letters",
            )
            storage.upsert_paper(formal, replace_bibliographic_metadata=True)
            updated = storage.get_paper(accepted["paper_id"])

            self.assertIsNotNone(updated)
            self.assertEqual(updated["publication_date"], "2026-07-13")
            self.assertEqual(updated["publisher_section"], "published")
            self.assertEqual(updated["section_allowed"], 1)
            self.assertEqual(updated["download_status"], "success")
            self.assertEqual(updated["main_pdf_path"], "data/pdfs/existing.pdf")
            raw = json.loads(updated["raw_json"])
            self.assertEqual(raw["volume"], "137")
            self.assertEqual(raw["issue"], "3")
            self.assertEqual(raw["article-number"], "030801")
            storage.close()

    def test_opening_legacy_database_hides_accepted_prl_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "papers.sqlite"
            storage = Storage(path)
            accepted = normalize_crossref_item(
                crossref_item(formal=False, published=(2026, 6, 8)),
                "Physical Review Letters",
            )
            storage.upsert_paper(accepted)
            storage.conn.execute(
                "UPDATE papers SET publisher_section = 'research article', section_allowed = 1 WHERE paper_id = ?",
                (accepted["paper_id"],),
            )
            storage.conn.commit()
            storage.close()

            reopened = Storage(path)
            migrated = reopened.get_paper(accepted["paper_id"])
            self.assertEqual(migrated["publisher_section"], "accepted")
            self.assertEqual(migrated["section_allowed"], 0)
            reopened.close()

    def test_opening_legacy_database_hides_accepted_prx_rows(self) -> None:
        self.assertTrue(is_aps_lifecycle_journal("Physical Review X"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "papers.sqlite"
            storage = Storage(path)
            accepted = normalize_crossref_item(
                crossref_item(
                    formal=False,
                    published=(2026, 7, 8),
                    doi="10.1103/cbrd-ssnm",
                    journal="Physical Review X",
                ),
                "Physical Review X",
            )
            storage.upsert_paper(accepted)
            storage.conn.execute(
                "UPDATE papers SET publisher_section = 'research article', section_allowed = 1 WHERE paper_id = ?",
                (accepted["paper_id"],),
            )
            storage.conn.commit()
            storage.close()

            reopened = Storage(path)
            migrated = reopened.get_paper(accepted["paper_id"])
            self.assertEqual(migrated["publisher_section"], "accepted")
            self.assertEqual(migrated["section_allowed"], 0)
            reopened.close()

    def test_opening_legacy_database_hides_openalex_only_accepted_rmp_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "papers.sqlite"
            storage = Storage(path)
            accepted = normalize_openalex_item(
                openalex_item(
                    formal=False,
                    published="2026-07-14",
                    doi="10.1103/j9ly-b6q3",
                    journal="Reviews of Modern Physics",
                ),
                "Reviews of Modern Physics",
            )
            storage.upsert_paper(accepted)
            storage.conn.execute(
                """
                UPDATE papers
                SET publisher_section = 'research article', section_allowed = 1
                WHERE paper_id = ?
                """,
                (accepted["paper_id"],),
            )
            storage.conn.commit()
            storage.close()

            reopened = Storage(path)
            migrated = reopened.get_paper(accepted["paper_id"])
            self.assertEqual(migrated["publisher_section"], "accepted")
            self.assertEqual(migrated["section_allowed"], 0)
            reopened.close()


if __name__ == "__main__":
    unittest.main()
