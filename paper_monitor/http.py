from __future__ import annotations

import time
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


def environment_uses_loopback_proxy(url: str) -> bool:
    try:
        proxies = requests.utils.get_environ_proxies(url)
    except Exception:
        return False
    return any(
        (urlparse(str(value or "")).hostname or "").casefold()
        in {"127.0.0.1", "localhost", "::1"}
        for value in proxies.values()
    )


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
    return request_with_local_proxy_fallback("GET", url, **kwargs)


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
    allow_redirects: bool = True,
) -> requests.Response:
    merged_headers = {"User-Agent": USER_AGENT}
    if headers:
        merged_headers.update(headers)

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = request_with_local_proxy_fallback(
                method,
                url,
                params=params,
                data=data,
                headers=merged_headers,
                timeout=timeout,
                stream=stream,
                allow_redirects=allow_redirects,
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
