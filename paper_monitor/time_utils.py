from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


JST = timezone(timedelta(hours=9))


def today_jst() -> date:
    return datetime.now(JST).date()


def now_iso() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def parse_date(value: str) -> date:
    return date.fromisoformat(value)
