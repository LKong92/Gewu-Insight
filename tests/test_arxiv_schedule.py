import unittest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from paper_monitor.sources.arxiv import arxiv_announcement_at, is_arxiv_announcement_day, latest_ready_arxiv_announcement, local_arxiv_announcement_days


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


if __name__ == "__main__":
    unittest.main()
