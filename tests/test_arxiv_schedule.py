import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from paper_monitor.sources import arxiv
from paper_monitor.sources.arxiv import arxiv_announcement_at, is_arxiv_announcement_day, latest_ready_arxiv_announcement, local_arxiv_announcement_days


LATEST_LISTING_HTML = """
<html><body>
  <h3>Showing new listings for Thursday, 23 July 2026</h3>
  <dl id="articles">
    <h3>New submissions (showing 1 of 1 entries)</h3>
    <dt><a href="/abs/2607.19458" title="Abstract">arXiv:2607.19458</a></dt>
    <dd><div class="meta">
      <div class="list-title"><span class="descriptor">Title:</span> Quantum geometry in MgB2</div>
      <div class="list-authors"><a>Yi Jiang</a><a>Haoyu Hu</a></div>
      <div class="list-comments"><span class="descriptor">Comments:</span> 12 pages</div>
      <div class="list-subjects"><span class="descriptor">Subjects:</span>
        <span class="primary-subject">Superconductivity (cond-mat.supr-con)</span>;
        Mesoscale and Nanoscale Physics (cond-mat.mes-hall)
      </div>
      <p class="mathjax">Quantum geometry enhances superconductivity.</p>
    </div></dd>
    <h3>Cross-lists (showing 1 of 1 entries)</h3>
    <dt><a href="/abs/2607.19999" title="Abstract">arXiv:2607.19999</a></dt>
    <dd><div class="meta">
      <div class="list-title"><span class="descriptor">Title:</span> Cross-listed material</div>
      <div class="list-authors"><a>Example Author</a></div>
      <div class="list-subjects"><span class="descriptor">Subjects:</span>
        <span class="primary-subject">Quantum Physics (quant-ph)</span>;
        Materials Science (cond-mat.mtrl-sci)
      </div>
      <p class="mathjax">A material cross-list.</p>
    </div></dd>
    <h3>Replacements (showing 1 of 1 entries)</h3>
    <dt><a href="/abs/2501.00001" title="Abstract">arXiv:2501.00001</a></dt>
    <dd><div class="meta">
      <div class="list-title"><span class="descriptor">Title:</span> Old replacement</div>
      <div class="list-subjects"><span class="descriptor">Subjects:</span>
        <span class="primary-subject">Materials Science (cond-mat.mtrl-sci)</span>
      </div>
      <p class="mathjax">Replacement.</p>
    </div></dd>
  </dl>
</body></html>
"""


class ArxivScheduleTests(unittest.TestCase):
    def test_sunday_is_an_arxiv_announcement_day(self):
        self.assertTrue(is_arxiv_announcement_day(date(2026, 6, 21)))

    def test_friday_and_saturday_are_not_announcement_days(self):
        self.assertFalse(is_arxiv_announcement_day(date(2026, 6, 19)))
        self.assertFalse(is_arxiv_announcement_day(date(2026, 6, 20)))

    def test_eastern_announcements_map_to_each_users_local_calendar(self):
        shanghai = ZoneInfo("Asia/Shanghai")
        new_york = ZoneInfo("America/New_York")
        self.assertEqual(
            local_arxiv_announcement_days(date(2026, 6, 22), date(2026, 6, 22), local_tz=shanghai),
            [date(2026, 6, 21)],
        )
        self.assertEqual(
            local_arxiv_announcement_days(date(2026, 6, 21), date(2026, 6, 21), local_tz=new_york),
            [date(2026, 6, 21)],
        )

    def test_timezone_and_daylight_saving_conversion(self):
        shanghai = ZoneInfo("Asia/Shanghai")
        london = ZoneInfo("Europe/London")
        los_angeles = ZoneInfo("America/Los_Angeles")
        summer = arxiv_announcement_at(date(2026, 7, 19))
        winter = arxiv_announcement_at(date(2026, 1, 11))
        self.assertEqual(summer.astimezone(shanghai).strftime("%Y-%m-%d %H:%M"), "2026-07-20 08:00")
        self.assertEqual(winter.astimezone(shanghai).strftime("%Y-%m-%d %H:%M"), "2026-01-12 09:00")
        self.assertEqual(summer.astimezone(london).strftime("%Y-%m-%d %H:%M"), "2026-07-20 01:00")
        self.assertEqual(summer.astimezone(los_angeles).strftime("%Y-%m-%d %H:%M"), "2026-07-19 17:00")

    def test_latest_ready_announcement_honors_buffer(self):
        eastern = ZoneInfo("America/New_York")
        before_buffer = datetime(2026, 7, 19, 20, 19, tzinfo=eastern)
        at_buffer = datetime(2026, 7, 19, 20, 20, tzinfo=eastern)
        self.assertEqual(
            latest_ready_arxiv_announcement(before_buffer, buffer=timedelta(minutes=20)).date(),
            date(2026, 7, 16),
        )
        self.assertEqual(
            latest_ready_arxiv_announcement(at_buffer, buffer=timedelta(minutes=20)).date(),
            date(2026, 7, 19),
        )

    def test_latest_listing_parser_includes_new_and_cross_lists_but_not_replacements(self):
        listing_date, papers = arxiv.parse_arxiv_latest_listing(
            LATEST_LISTING_HTML,
            local_tz=ZoneInfo("Asia/Shanghai"),
        )

        self.assertEqual(listing_date, date(2026, 7, 23))
        self.assertEqual([paper["paper_id"] for paper in papers], ["arxiv_2607.19458", "arxiv_2607.19999"])
        self.assertEqual(papers[0]["publication_date"], "2026-07-23")
        self.assertEqual(papers[0]["raw"]["authors"], ["Yi Jiang", "Haoyu Hu"])
        self.assertEqual(papers[0]["raw"]["primary_category"], "cond-mat.supr-con")
        self.assertEqual(papers[0]["raw"]["metadata_source"], "arxiv_latest_listing")

    def test_latest_listing_maps_the_same_announcement_to_each_users_calendar(self):
        _listing_date, shanghai = arxiv.parse_arxiv_latest_listing(
            LATEST_LISTING_HTML,
            local_tz=ZoneInfo("Asia/Shanghai"),
        )
        _listing_date, new_york = arxiv.parse_arxiv_latest_listing(
            LATEST_LISTING_HTML,
            local_tz=ZoneInfo("America/New_York"),
        )

        self.assertEqual(shanghai[0]["publication_date"], "2026-07-23")
        self.assertEqual(new_york[0]["publication_date"], "2026-07-22")

    def test_latest_listing_cache_is_shared_across_callers(self):
        arxiv.ARXIV_LATEST_LISTING_CACHE.clear()
        response = SimpleNamespace(text=LATEST_LISTING_HTML)
        with patch.object(arxiv, "request_with_retries", return_value=response) as request:
            first = arxiv.fetch_latest_arxiv_listing(local_tz=ZoneInfo("Asia/Shanghai"))
            second = arxiv.fetch_latest_arxiv_listing(local_tz=ZoneInfo("Asia/Shanghai"))

        self.assertEqual(request.call_count, 1)
        self.assertEqual(first[0], second[0])
        self.assertEqual(len(first[1]), 2)

    def test_manual_latest_refresh_bypasses_the_listing_cache(self):
        arxiv.ARXIV_LATEST_LISTING_CACHE.clear()
        response = SimpleNamespace(text=LATEST_LISTING_HTML)
        with patch.object(arxiv, "request_with_retries", return_value=response) as request:
            arxiv.fetch_latest_arxiv_listing(local_tz=ZoneInfo("Asia/Shanghai"))
            arxiv.fetch_latest_arxiv_listing(local_tz=ZoneInfo("Asia/Shanghai"), force=True)

        self.assertEqual(request.call_count, 2)

    def test_subject_query_filters_the_shared_latest_listing_without_export_api(self):
        _listing_date, papers = arxiv.parse_arxiv_latest_listing(
            LATEST_LISTING_HTML,
            local_tz=ZoneInfo("Asia/Shanghai"),
        )
        with patch.object(arxiv, "fetch_latest_arxiv_listing_for_window", return_value=papers), patch.object(
            arxiv,
            "request_with_retries",
            side_effect=AssertionError("Export API should not be called for the current listing"),
        ):
            result = arxiv.search_arxiv_works(
                query="quantum geometry",
                start_date=date(2026, 7, 23),
                end_date=date(2026, 7, 23),
            )

        self.assertEqual([paper["paper_id"] for paper in result], ["arxiv_2607.19458"])

    def test_journal_fetch_uses_latest_listing_without_export_api(self):
        _listing_date, papers = arxiv.parse_arxiv_latest_listing(
            LATEST_LISTING_HTML,
            local_tz=ZoneInfo("Asia/Shanghai"),
        )
        with patch.object(arxiv, "fetch_latest_arxiv_listing_for_window", return_value=papers), patch.object(
            arxiv,
            "request_with_retries",
            side_effect=AssertionError("Export API should not be called for the current listing"),
        ):
            result = arxiv.fetch_arxiv_condensed_matter(
                start_date=date(2026, 7, 23),
                end_date=date(2026, 7, 23),
            )

        self.assertEqual(len(result), 2)

    def test_failed_listing_plus_empty_export_response_is_an_error_not_false_empty(self):
        empty_feed = SimpleNamespace(content=b'<feed xmlns="http://www.w3.org/2005/Atom"></feed>')
        with patch.object(
            arxiv,
            "fetch_latest_arxiv_listing_for_window",
            side_effect=RuntimeError("latest listing unavailable"),
        ), patch.object(arxiv, "request_with_retries", return_value=empty_feed):
            with self.assertRaisesRegex(RuntimeError, "latest listing failed and Export API returned no papers"):
                arxiv.fetch_arxiv_condensed_matter(
                    start_date=date(2026, 7, 23),
                    end_date=date(2026, 7, 23),
                    max_pages=1,
                )

    def test_expected_latest_batch_never_falls_back_to_date_search_before_listing_advances(self):
        with patch.object(
            arxiv,
            "fetch_latest_arxiv_listing_for_window",
            return_value=None,
        ), patch.object(
            arxiv,
            "request_with_retries",
            side_effect=AssertionError("Date search API must not run before the listing advances"),
        ):
            with self.assertRaisesRegex(RuntimeError, "has not advanced"):
                arxiv.fetch_arxiv_condensed_matter(
                    start_date=date(2026, 7, 23),
                    end_date=date(2026, 7, 23),
                    require_latest_listing=True,
                )


if __name__ == "__main__":
    unittest.main()
