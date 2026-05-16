from __future__ import annotations

import time
from typing import Any

import requests


TIMEOUT = 30
MAX_RETRIES = 3
RETRY_SLEEP = 2.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/123.0 Safari/537.36 paper-monitor/0.1"
)


def request_with_retries(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = TIMEOUT,
    stream: bool = False,
) -> requests.Response:
    merged_headers = {"User-Agent": USER_AGENT}
    if headers:
        merged_headers.update(headers)

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = requests.request(
                method,
                url,
                params=params,
                headers=merged_headers,
                timeout=timeout,
                stream=stream,
                allow_redirects=True,
            )
            if response.status_code == 429:
                time.sleep(RETRY_SLEEP * attempt)
                continue
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt == MAX_RETRIES:
                raise
            time.sleep(RETRY_SLEEP * attempt)
    if last_error:
        raise last_error
    raise RuntimeError("request_with_retries failed unexpectedly")
