from __future__ import annotations

import os
import random
import threading
import time
from typing import Any

import requests

from ..http import request_with_retries
from ..text import clean_text


SEMANTIC_SCHOLAR_API_KEY_SETTING = "semantic_scholar_api_key"
SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS = 1.1
_SEMANTIC_SCHOLAR_STATE_LOCK = threading.RLock()
_SEMANTIC_SCHOLAR_REQUEST_LOCK = threading.Lock()
_SEMANTIC_SCHOLAR_RUNTIME_API_KEY = ""
_SEMANTIC_SCHOLAR_LAST_REQUEST_AT = 0.0


def semantic_scholar_api_key() -> str | None:
    with _SEMANTIC_SCHOLAR_STATE_LOCK:
        runtime_key = _SEMANTIC_SCHOLAR_RUNTIME_API_KEY
    if runtime_key:
        return runtime_key
    environment_key = clean_text(os.getenv("SEMANTIC_SCHOLAR_API_KEY", ""))
    return environment_key or None


def configure_semantic_scholar_api_key(api_key: str | None) -> None:
    global _SEMANTIC_SCHOLAR_RUNTIME_API_KEY
    with _SEMANTIC_SCHOLAR_STATE_LOCK:
        _SEMANTIC_SCHOLAR_RUNTIME_API_KEY = clean_text(api_key or "")


def semantic_scholar_headers(
    headers: dict[str, str] | None = None,
    *,
    api_key: str | None = None,
) -> dict[str, str]:
    merged = dict(headers or {})
    key = clean_text(api_key or semantic_scholar_api_key() or "")
    if key:
        # Semantic Scholar documents this header name as case-sensitive.
        merged["x-api-key"] = key
    return merged


def _wait_for_semantic_scholar_slot() -> None:
    global _SEMANTIC_SCHOLAR_LAST_REQUEST_AT
    with _SEMANTIC_SCHOLAR_REQUEST_LOCK:
        elapsed = time.monotonic() - _SEMANTIC_SCHOLAR_LAST_REQUEST_AT
        wait_seconds = SEMANTIC_SCHOLAR_MIN_INTERVAL_SECONDS - elapsed
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        _SEMANTIC_SCHOLAR_LAST_REQUEST_AT = time.monotonic()


def _semantic_scholar_error_is_retryable(exc: Exception) -> bool:
    if isinstance(exc, RuntimeError) and "HTTP 429" in str(exc):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        status = int(exc.response.status_code or 0)
        return status == 429 or status >= 500
    return isinstance(exc, requests.RequestException)


def semantic_scholar_request(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    api_key: str | None = None,
    timeout: int = 30,
    max_retries: int = 3,
    stream: bool = False,
) -> requests.Response:
    attempts = max(1, int(max_retries or 1))
    request_headers = semantic_scholar_headers(headers, api_key=api_key)
    last_error: Exception | None = None
    for attempt in range(attempts):
        _wait_for_semantic_scholar_slot()
        try:
            return request_with_retries(
                method,
                url,
                params=params,
                data=data,
                headers=request_headers or None,
                timeout=timeout,
                max_retries=1,
                retry_on_429=False,
                stream=stream,
            )
        except Exception as exc:
            last_error = exc
            if attempt + 1 >= attempts or not _semantic_scholar_error_is_retryable(exc):
                raise
            # The application promised exponential backoff for 429 and temporary failures.
            time.sleep((2 ** attempt) + random.uniform(0.05, 0.25))
    if last_error:
        raise last_error
    raise RuntimeError("Semantic Scholar request failed unexpectedly")


def test_semantic_scholar_api_key(
    api_key: str,
    *,
    timeout: int = 12,
) -> dict[str, Any]:
    key = clean_text(api_key)
    if not key:
        return {"configured": False, "status": "not_configured", "ok": False}
    try:
        response = semantic_scholar_request(
            "GET",
            "https://api.semanticscholar.org/graph/v1/paper/649def34f8be52c8b66281af98ae884c09aef38b",
            params={"fields": "paperId,title"},
            api_key=key,
            timeout=timeout,
            max_retries=1,
        )
        payload = response.json()
        ok = isinstance(payload, dict) and bool(payload.get("paperId"))
    except Exception as exc:
        message = str(exc)
        status_code = (
            int(exc.response.status_code or 0)
            if isinstance(exc, requests.HTTPError) and exc.response is not None
            else 0
        )
        if status_code == 429 or "HTTP 429" in message:
            return {
                "configured": bool(semantic_scholar_api_key()),
                "status": "rate_limited",
                "ok": None,
            }
        if status_code in {401, 403}:
            return {
                "configured": bool(semantic_scholar_api_key()),
                "status": "invalid",
                "ok": False,
            }
        return {
            "configured": bool(semantic_scholar_api_key()),
            "status": "unavailable",
            "ok": None,
        }
    return {
        "configured": bool(semantic_scholar_api_key()),
        "status": "connected" if ok else "invalid",
        "ok": ok,
    }
