from __future__ import annotations

import json
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import requests


TIMEOUT = 30
MAX_RETRIES = 3
RETRY_SLEEP = 2.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
)
PUBLISHER_AUTOMATION_USER_AGENT = "GewuInsight/1.0 TextDataMining"
PUBLISHER_ACCESS_STATE_SETTING = "publisher_access_state_v1"
PUBLISHER_REQUEST_INTERVAL_SECONDS = 3.0
PUBLISHER_FIGURE_REQUEST_INTERVAL_SECONDS = 1.25
PUBLISHER_IMAGE_REQUEST_INTERVAL_SECONDS = 0.2
PUBLISHER_INITIAL_BLOCK_HOURS = 12
PUBLISHER_REPEAT_BLOCK_HOURS = 24

_PUBLISHER_HOST_GROUPS = {
    "nature.com": "springer_nature",
    "springernature.com": "springer_nature",
    "science.org": "aaas",
    "aps.org": "aps",
    "iopscience.iop.org": "iop",
    "pubs.aip.org": "aip",
    "pubs.acs.org": "acs",
    "quantum-journal.org": "quantum",
}
_PUBLISHER_DOI_PREFIX_GROUPS = {
    "10.1038/": "springer_nature",
    "10.1126/": "aaas",
    "10.1103/": "aps",
    "10.1088/": "iop",
    "10.1063/": "aip",
    "10.1021/": "acs",
    "10.22331/": "quantum",
}
_PUBLISHER_REQUEST_LOCKS: dict[str, threading.RLock] = {}
_PUBLISHER_REQUEST_LOCKS_GUARD = threading.Lock()
_PUBLISHER_LAST_REQUEST_AT: dict[str, float] = {}
_PUBLISHER_BLOCKED_UNTIL: dict[str, float] = {}
_PUBLISHER_BACKGROUND_BATCH_LOCK = threading.RLock()


class PublisherAccessBlockedError(RuntimeError):
    """Raised when automated publisher access is paused after a block response."""


def publisher_group_for_url(url: str) -> str:
    normalized_url = str(url or "").casefold()
    host = (urlparse(normalized_url).hostname or "").casefold()
    for suffix, group in _PUBLISHER_HOST_GROUPS.items():
        if host == suffix or host.endswith(f".{suffix}"):
            return group
    for doi_prefix, group in _PUBLISHER_DOI_PREFIX_GROUPS.items():
        if doi_prefix in normalized_url:
            return group
    return ""


def publisher_access_group(url: str, access_kind: str = "page") -> str:
    group = publisher_group_for_url(url)
    return f"{group}:{clean_publisher_access_kind(access_kind)}" if group else ""


def clean_publisher_access_kind(value: str) -> str:
    return value if value in {"page", "feed", "figure", "image"} else "page"


def publisher_automation_headers(
    url: str,
    headers: dict[str, str] | None = None,
    *,
    access_kind: str = "page",
) -> dict[str, str]:
    merged = dict(headers or {})
    if publisher_group_for_url(url) == "springer_nature":
        merged["User-Agent"] = PUBLISHER_AUTOMATION_USER_AGENT
    else:
        merged.setdefault("User-Agent", USER_AGENT)
    return merged


def _publisher_request_lock(group: str) -> threading.RLock:
    with _PUBLISHER_REQUEST_LOCKS_GUARD:
        return _PUBLISHER_REQUEST_LOCKS.setdefault(group, threading.RLock())


def _publisher_persisted_state(storage: Any, group: str) -> dict[str, Any]:
    if storage is None or not hasattr(storage, "get_setting"):
        return {}
    try:
        payload = json.loads(storage.get_setting(PUBLISHER_ACCESS_STATE_SETTING, "{}") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    state = payload.get(group)
    return dict(state) if isinstance(state, dict) else {}


def _publisher_blocked_until_timestamp(storage: Any, group: str) -> float:
    blocked_until = _PUBLISHER_BLOCKED_UNTIL.get(group, 0.0)
    state = _publisher_persisted_state(storage, group)
    try:
        persisted = datetime.fromisoformat(str(state.get("blocked_until") or "")).timestamp()
    except (TypeError, ValueError):
        persisted = 0.0
    blocked_until = max(blocked_until, persisted)
    _PUBLISHER_BLOCKED_UNTIL[group] = blocked_until
    return blocked_until


def _persist_publisher_block(
    storage: Any,
    group: str,
    *,
    status: int,
    reason: str,
    access_kind: str,
) -> float:
    now = datetime.now().astimezone()
    state = _publisher_persisted_state(storage, group)
    failure_count = int(state.get("failure_count") or 0) + 1
    access_kind = clean_publisher_access_kind(access_kind)
    if access_kind == "image":
        seconds = 10 * 60 if failure_count == 1 else 60 * 60
    elif access_kind == "figure":
        seconds = 30 * 60 if failure_count == 1 else 2 * 60 * 60
    elif access_kind == "feed":
        seconds = 60 * 60 if failure_count == 1 else 6 * 60 * 60
    else:
        hours = PUBLISHER_INITIAL_BLOCK_HOURS if failure_count == 1 else PUBLISHER_REPEAT_BLOCK_HOURS
        seconds = hours * 60 * 60
    blocked_until = now + timedelta(seconds=seconds)
    _PUBLISHER_BLOCKED_UNTIL[group] = blocked_until.timestamp()
    if storage is not None and hasattr(storage, "set_setting"):
        try:
            raw = json.loads(storage.get_setting(PUBLISHER_ACCESS_STATE_SETTING, "{}") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            raw = {}
        raw[group] = {
            "blocked_until": blocked_until.isoformat(),
            "failure_count": failure_count,
            "last_status": int(status or 0),
            "last_reason": str(reason or "")[:240],
            "updated_at": now.isoformat(),
        }
        storage.set_setting(PUBLISHER_ACCESS_STATE_SETTING, json.dumps(raw, ensure_ascii=False, sort_keys=True))
    return blocked_until.timestamp()


def publisher_response_is_blocked(response: requests.Response) -> bool:
    if int(getattr(response, "status_code", 0) or 0) in {403, 406, 429}:
        return True
    headers = getattr(response, "headers", {}) or {}
    content_type = str(
        headers.get("Content-Type")
        or headers.get("content-type")
        or ""
    ).casefold()
    if "html" not in content_type:
        return False
    try:
        sample = str(getattr(response, "text", "") or "")[:8000].casefold()
    except Exception:
        return False
    return "access blocked" in sample and "suspicious activity" in sample


def note_publisher_response(
    response: requests.Response,
    url: str,
    *,
    storage: Any = None,
    access_kind: str = "page",
) -> None:
    response_url = str(getattr(response, "url", "") or "")
    base_group = publisher_group_for_url(response_url) or publisher_group_for_url(url)
    access_kind = clean_publisher_access_kind(access_kind)
    group = f"{base_group}:{access_kind}" if base_group else ""
    if not group or not publisher_response_is_blocked(response):
        return
    status = int(getattr(response, "status_code", 0) or 0)
    blocked_until = _persist_publisher_block(
        storage,
        group,
        status=status,
        reason=f"Publisher access blocked for {group}",
        access_kind=access_kind,
    )
    until_text = datetime.fromtimestamp(blocked_until).astimezone().isoformat(timespec="minutes")
    raise PublisherAccessBlockedError(f"Publisher access paused until {until_text}")


@contextmanager
def publisher_request_guard(url: str, *, storage: Any = None, access_kind: str = "page"):
    access_kind = clean_publisher_access_kind(access_kind)
    group = publisher_access_group(url, access_kind)
    if not group:
        yield
        return
    lock = _publisher_request_lock(group)
    if access_kind in {"figure", "image"}:
        with lock:
            blocked_until = _publisher_blocked_until_timestamp(storage, group)
            now_timestamp = datetime.now().astimezone().timestamp()
            if blocked_until > now_timestamp:
                until_text = datetime.fromtimestamp(blocked_until).astimezone().isoformat(timespec="minutes")
                raise PublisherAccessBlockedError(f"Publisher access paused until {until_text}")
            interval = (
                PUBLISHER_FIGURE_REQUEST_INTERVAL_SECONDS
                if access_kind == "figure"
                else PUBLISHER_IMAGE_REQUEST_INTERVAL_SECONDS
            )
            last_request_at = _PUBLISHER_LAST_REQUEST_AT.get(group, 0.0)
            wait_seconds = interval - (time.monotonic() - last_request_at)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            _PUBLISHER_LAST_REQUEST_AT[group] = time.monotonic()
        yield
        return
    with lock:
        blocked_until = _publisher_blocked_until_timestamp(storage, group)
        now_timestamp = datetime.now().astimezone().timestamp()
        if blocked_until > now_timestamp:
            until_text = datetime.fromtimestamp(blocked_until).astimezone().isoformat(timespec="minutes")
            raise PublisherAccessBlockedError(f"Publisher access paused until {until_text}")
        last_request_at = _PUBLISHER_LAST_REQUEST_AT.get(group, 0.0)
        wait_seconds = PUBLISHER_REQUEST_INTERVAL_SECONDS - (time.monotonic() - last_request_at)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        try:
            yield
        finally:
            _PUBLISHER_LAST_REQUEST_AT[group] = time.monotonic()


@contextmanager
def publisher_background_batch(*, blocking: bool = True):
    acquired = _PUBLISHER_BACKGROUND_BATCH_LOCK.acquire(blocking=blocking)
    try:
        yield acquired
    finally:
        if acquired:
            _PUBLISHER_BACKGROUND_BATCH_LOCK.release()


def reset_publisher_access_state() -> None:
    """Reset process-local access state for deterministic tests."""
    with _PUBLISHER_REQUEST_LOCKS_GUARD:
        _PUBLISHER_REQUEST_LOCKS.clear()
    _PUBLISHER_LAST_REQUEST_AT.clear()
    _PUBLISHER_BLOCKED_UNTIL.clear()


def environment_uses_loopback_proxy(url: str) -> bool:
    try:
        proxies = requests.utils.get_environ_proxies(url)
    except Exception:
        return False
    for value in proxies.values():
        host = (urlparse(str(value or "")).hostname or "").casefold()
        if host in {"127.0.0.1", "localhost", "::1"}:
            return True
    return False


def _request_without_environment_proxy(method: str, url: str, **kwargs: Any) -> requests.Response:
    with requests.Session() as session:
        session.trust_env = False
        return session.request(method, url, **kwargs)


def request_with_local_proxy_fallback(method: str, url: str, **kwargs: Any) -> requests.Response:
    try:
        return requests.request(method, url, **kwargs)
    except requests.exceptions.ProxyError:
        if "proxies" in kwargs or not environment_uses_loopback_proxy(url):
            raise
        return _request_without_environment_proxy(method, url, **kwargs)


def get_with_local_proxy_fallback(url: str, **kwargs: Any) -> requests.Response:
    try:
        return requests.get(url, **kwargs)
    except requests.exceptions.ProxyError:
        if "proxies" in kwargs or not environment_uses_loopback_proxy(url):
            raise
        return _request_without_environment_proxy("GET", url, **kwargs)


def request_with_retries(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = TIMEOUT,
    max_retries: int = MAX_RETRIES,
    retry_sleep: float = RETRY_SLEEP,
    retry_on_429: bool = True,
    stream: bool = False,
    publisher_storage: Any = None,
    publisher_access_kind: str = "page",
) -> requests.Response:
    merged_headers = publisher_automation_headers(url, headers, access_kind=publisher_access_kind)

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            with publisher_request_guard(
                url,
                storage=publisher_storage,
                access_kind=publisher_access_kind,
            ):
                response = request_with_local_proxy_fallback(
                    method,
                    url,
                    params=params,
                    data=data,
                    headers=merged_headers,
                    timeout=timeout,
                    stream=stream,
                    allow_redirects=True,
                )
                note_publisher_response(
                    response,
                    url,
                    storage=publisher_storage,
                    access_kind=publisher_access_kind,
                )
            if response.status_code == 429:
                last_error = RuntimeError(f"HTTP 429 Too Many Requests for {response.url}")
                if not retry_on_429 or attempt == max_retries:
                    raise last_error
                time.sleep(retry_sleep * attempt)
                continue
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if isinstance(exc, requests.HTTPError) and exc.response is not None:
                status = exc.response.status_code
                if status != 429 and status < 500:
                    raise
            if attempt == max_retries:
                raise
            time.sleep(retry_sleep * attempt)
    if last_error:
        raise last_error
    raise RuntimeError("request_with_retries failed unexpectedly")
