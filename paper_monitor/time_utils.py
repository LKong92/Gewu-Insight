from __future__ import annotations

import os
from datetime import date, datetime, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def system_timezone_name() -> str:
    """Return the host's IANA timezone name when the OS exposes one."""
    candidates: list[str] = []
    env_name = str(os.environ.get("TZ") or "").strip().lstrip(":")
    if env_name:
        candidates.append(env_name)
    for path in (Path("/etc/localtime"), Path("/var/db/timezone/localtime")):
        try:
            resolved = str(path.resolve())
        except OSError:
            continue
        marker = "/zoneinfo/"
        if marker in resolved:
            candidates.append(resolved.split(marker, 1)[1])
    current = datetime.now().astimezone().tzinfo
    zone_key = str(getattr(current, "key", "") or "").strip()
    if zone_key:
        candidates.append(zone_key)
    for candidate in candidates:
        try:
            ZoneInfo(candidate)
        except (ValueError, ZoneInfoNotFoundError):
            continue
        return candidate
    return "UTC"


def local_timezone(name: str | None = None) -> tzinfo:
    zone_name = str(name or system_timezone_name()).strip()
    try:
        return ZoneInfo(zone_name)
    except (ValueError, ZoneInfoNotFoundError):
        return datetime.now().astimezone().tzinfo or timezone.utc


def today_local() -> date:
    return datetime.now(local_timezone()).date()


def now_iso() -> str:
    return datetime.now(local_timezone()).isoformat(timespec="seconds")


def today_jst() -> date:
    """Backward-compatible alias; dates now follow the host system timezone."""
    return today_local()


def parse_date(value: str) -> date:
    return date.fromisoformat(value)
