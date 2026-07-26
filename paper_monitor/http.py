from __future__ import annotations

import time
from typing import Any

import requests


TIMEOUT = 30
MAX_RETRIES = 3
RETRY_SLEEP = 2.0
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
)


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
) -> requests.Response:
    merged_headers = {"User-Agent": USER_AGENT}
    if headers:
        merged_headers.update(headers)

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.request(
                method,
                url,
                params=params,
                data=data,
                headers=merged_headers,
                timeout=timeout,
                stream=stream,
                allow_redirects=True,
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
