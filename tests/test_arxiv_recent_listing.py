import copy
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from paper_monitor.sources import arxiv
from paper_monitor.storage import Storage


def batch(day, identifier, *, shown=1, total=1, category="cond-mat.str-el"):
    return f'''<dl id="articles"><h3>{day} (showing {shown} of {total} entries )</h3>
      <dt><a href="/abs/{identifier}" title="Abstract">{identifier}</a></dt>
      <dd><div class="list-title">Title: Delayed announcement</div>
      <div class="list-subjects"><span class="primary-subject">Subject ({category})</span></div>
      </dd></dl>'''


RECENT = (batch("Thu, 10 Sep 2026", "2609.10001")
          + batch("Wed, 9 Sep 2026", "2609.06001")
          + batch("Mon, 7 Sep 2026", "2609.05001"))


class ArxivRecentListingTests(unittest.TestCase):
    def test_id_metadata_with_zero_retries_still_makes_one_attempt(self):
        with patch.object(arxiv, "wait_for_arxiv_rate_limit"), patch.object(
            arxiv, "request_with_retries", return_value=SimpleNamespace(
                content=b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>')
        ) as request:
            self.assertEqual(arxiv.fetch_arxiv_by_ids(["2609.06001"], max_retries=0), [])
        self.assertEqual(request.call_args.kwargs["max_retries"], 1)

    def test_dated_batches_and_holiday_gap_follow_official_listing(self):
        result = arxiv.parse_arxiv_recent_listing(RECENT, local_tz=ZoneInfo("Asia/Tokyo"))
        self.assertEqual(list(result), [date(2026, 9, 10), date(2026, 9, 9), date(2026, 9, 7)])
        paper = result[date(2026, 9, 9)][0]
        self.assertEqual(paper["publication_date"], "2026-09-09")
        self.assertEqual(paper["raw"]["announcement_at_utc"], "2026-09-09T00:00:00+00:00")
        self.assertEqual(paper["raw"]["announcement_source"], "arxiv_listing")

    def test_daily_batches_map_to_the_local_timezone(self):
        result = arxiv.parse_arxiv_recent_listing(RECENT, local_tz=ZoneInfo("America/New_York"))
        self.assertEqual(result[date(2026, 9, 8)][0]["publication_date"], "2026-09-08")

    def test_incomplete_or_unrecognized_batches_are_rejected(self):
        for html in (batch("Wed, 9 Sep 2026", "2609.06001", total=2),
                     batch("Wed, 9 Sep 2026", "2609.06001", shown=2, total=2),
                     RECENT.replace("Wed, 9 Sep 2026", "unknown date"), "<html></html>"):
            with self.subTest(html=html), self.assertRaises(ValueError):
                arxiv.parse_arxiv_recent_listing(html)

    def test_recent_window_uses_official_batches_including_empty_gap(self):
        with patch.object(arxiv, "datetime", wraps=datetime) as clock, patch.object(
            arxiv, "local_timezone", return_value=ZoneInfo("Asia/Tokyo")
        ), patch.object(arxiv, "request_with_retries", return_value=SimpleNamespace(text=RECENT)):
            clock.now.return_value = datetime(2026, 9, 11, tzinfo=ZoneInfo("Asia/Tokyo"))
            for day, count in ((9, 1), (8, 0)):
                result = arxiv.fetch_recent_arxiv_listing_for_window(
                    start_date=date(2026, 9, day), end_date=date(2026, 9, day), categories=["cond-mat.str-el"])
                self.assertEqual(len(result), count)
            self.assertIsNone(arxiv.fetch_recent_arxiv_listing_for_window(
                start_date=date(2026, 9, 6), end_date=date(2026, 9, 6), categories=["cond-mat.str-el"]))
            self.assertEqual(arxiv.fetch_recent_arxiv_listing_for_window(
                start_date=date(2026, 9, 9), end_date=date(2026, 9, 9), categories=["cond-mat.soft"]), [])

    def test_journal_backfill_does_not_use_submitted_date_search_when_recent_covers_it(self):
        papers = arxiv.parse_arxiv_recent_listing(RECENT)[date(2026, 9, 9)]
        with patch.object(arxiv, "fetch_latest_arxiv_listing_for_window", return_value=None), patch.object(
            arxiv, "fetch_recent_arxiv_listing_for_window", return_value=papers
        ), patch.object(arxiv, "fetch_arxiv_by_ids", return_value=[]), patch.object(
            arxiv, "request_with_retries", side_effect=AssertionError("No submitted-date query expected")
        ):
            result = arxiv.fetch_arxiv_condensed_matter(start_date=date(2026, 9, 9), end_date=date(2026, 9, 9))
        self.assertEqual(result[0]["paper_id"], "arxiv_2609.06001")

    def test_api_enrichment_keeps_delayed_listing_date_and_timestamp_together(self):
        papers = arxiv.parse_arxiv_recent_listing(RECENT)[date(2026, 9, 9)]
        detail = copy.deepcopy(papers[0])
        detail["publication_date"] = "2026-09-08"
        detail["raw"].update(published="2026-09-06T07:00:00Z", announcement_at_utc="2026-09-08T00:00:00+00:00")
        detail["raw"].pop("announcement_source")
        with patch.object(arxiv, "fetch_arxiv_by_ids", return_value=[detail]):
            result = arxiv.enrich_arxiv_listing_metadata(papers)[0]
        self.assertEqual(result["publication_date"], "2026-09-09")
        self.assertEqual(arxiv.arxiv_local_date_from_raw(result["raw"], local_tz=ZoneInfo("Asia/Tokyo")), "2026-09-09")

    def test_stored_official_date_survives_later_api_estimate_and_preserves_file_status(self):
        official = arxiv.parse_arxiv_recent_listing(RECENT)[date(2026, 9, 9)][0]
        estimate = copy.deepcopy(official)
        estimate["publication_date"] = "2026-09-08"
        estimate["raw"].pop("announcement_source")
        estimate["raw"].update(metadata_source="api", announcement_at_utc="2026-09-08T00:00:00+00:00")
        with tempfile.TemporaryDirectory() as directory:
            storage = Storage(Path(directory) / "papers.sqlite")
            try:
                storage.upsert_paper(estimate)
                storage.conn.execute("UPDATE papers SET download_status='downloaded', main_pdf_path='existing.pdf'")
                storage.conn.commit()
                storage.upsert_paper(official)
                storage.upsert_paper(estimate)
                result = storage.get_paper(official["paper_id"])
                self.assertEqual(result["publication_date"], "2026-09-09")
                raw = json.loads(result["raw_json"])
                self.assertEqual(raw["announcement_source"], "arxiv_listing")
                self.assertEqual(raw["announcement_at_utc"], "2026-09-09T00:00:00+00:00")
                self.assertEqual(result["download_status"], "downloaded")
                self.assertEqual(result["main_pdf_path"], "existing.pdf")
            finally:
                storage.close()
