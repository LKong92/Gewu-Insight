"""Durable, provider-wide backoff for interrupted author-profile checks."""
from datetime import datetime, timedelta
import json
import threading

import requests


SETTING = "author_profile_network_retry_v1"
BACKOFF_SECONDS = (5 * 60, 15 * 60, 60 * 60)
BATCH_SIZE = 3
_LOCK = threading.RLock()


def network_failure(error):
    """Recognize transport failures, including errors saved by older releases.

    Access restrictions, certificate validation and identity conflicts must not
    enter this queue. Scholar's separate access cooldown always takes priority.
    """
    text = str(error or "").lower()
    if any(word in text for word in (
        "certificate_verify_failed", "certificate verify failed", "hostname mismatch",
        "certificate has expired", "self-signed certificate",
        "captcha", "unusual traffic", "too many requests", "http 429", "http 403",
    )):
        return False
    if isinstance(error, requests.exceptions.SSLError):
        return "ssleoferror" in text or "wrong_version_number" in text
    if isinstance(error, (requests.ConnectionError, requests.Timeout)):
        return True
    return any(word in text for word in (
        "nameresolutionerror", "failed to resolve", "temporary failure in name resolution",
        "network is unreachable", "network is down", "connection refused",
        "connection reset", "connection aborted", "connecttimeout", "readtimeout",
        "connection timed out", "read timed out", "ssleoferror", "wrong_version_number",
        "remotedisconnected", "failed to establish a new connection",
        "network connection interrupted",
    ))


def provider(author):
    source = str(author.get("source_type") or "google_scholar").strip().lower()
    return "google_scholar" if source == "google_scholar" else "researchgate"


def read(storage):
    try:
        value = json.loads(storage.get_setting(SETTING, "{}"))
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def _time(value, now):
    try:
        stamp = datetime.fromisoformat(str(value))
        return stamp.replace(tzinfo=now.tzinfo) if stamp.tzinfo is None else stamp
    except (ValueError, TypeError):
        return None


def retryable(author):
    return author.get("status") == "error" and network_failure(author.get("message"))


def provider_ready(state, author, now):
    entry = state.get(provider(author)) or {}
    if not isinstance(entry, dict):
        return True
    until = _time(entry.get("retry_at"), now)
    return until is None or now >= until


def due(state, author, now):
    checked = _time(author.get("last_checked_at"), now)
    return retryable(author) and provider_ready(state, author, now) and (
        checked is None or now >= checked + timedelta(seconds=BACKOFF_SECONDS[0])
    )


def failed(storage, author, now):
    with _LOCK:
        state = read(storage)
        key = provider(author)
        entry = state.get(key)
        try:
            failures = int(entry.get("failures", 0)) if isinstance(entry, dict) else 0
        except (ValueError, TypeError):
            failures = 0
        count = min(max(0, failures) + 1, len(BACKOFF_SECONDS))
        state[key] = {"failures": count, "retry_at": (
            now + timedelta(seconds=BACKOFF_SECONDS[count - 1])
        ).isoformat(timespec="seconds")}
        storage.set_setting(SETTING, json.dumps(state, sort_keys=True))


def succeeded(storage, author):
    with _LOCK:
        state = read(storage)
        if state.pop(provider(author), None) is not None:
            storage.set_setting(SETTING, json.dumps(state, sort_keys=True))
