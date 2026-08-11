from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests

from paper_monitor.http import request_with_local_proxy_fallback


class LocalProxyFallbackTests(unittest.TestCase):
    def test_dead_loopback_proxy_falls_back_to_direct_connection(self) -> None:
        response = SimpleNamespace(status_code=200)
        session = MagicMock()
        session.__enter__.return_value = session
        session.request.return_value = response
        with patch(
            "paper_monitor.http.requests.request",
            side_effect=requests.exceptions.ProxyError("127.0.0.1 refused"),
        ), patch(
            "paper_monitor.http.environment_uses_loopback_proxy",
            return_value=True,
        ), patch(
            "paper_monitor.http.requests.Session",
            return_value=session,
        ):
            result = request_with_local_proxy_fallback("GET", "https://api.crossref.org/works")

        self.assertIs(result, response)
        self.assertFalse(session.trust_env)
        session.request.assert_called_once_with("GET", "https://api.crossref.org/works")

    def test_nonlocal_proxy_error_is_not_bypassed(self) -> None:
        with patch(
            "paper_monitor.http.requests.request",
            side_effect=requests.exceptions.ProxyError("remote proxy refused"),
        ), patch(
            "paper_monitor.http.environment_uses_loopback_proxy",
            return_value=False,
        ):
            with self.assertRaises(requests.exceptions.ProxyError):
                request_with_local_proxy_fallback("GET", "https://api.crossref.org/works")


if __name__ == "__main__":
    unittest.main()
