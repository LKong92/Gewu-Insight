import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from paper_monitor import ui_server
from paper_monitor.sources import semantic_scholar
from paper_monitor.storage import Storage


class SemanticScholarCredentialTests(unittest.TestCase):
    def tearDown(self):
        semantic_scholar.configure_semantic_scholar_api_key("")

    def test_saved_key_status_does_not_expose_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                storage.set_setting(
                    semantic_scholar.SEMANTIC_SCHOLAR_API_KEY_SETTING,
                    "local-semantic-secret",
                )
                payload = ui_server.semantic_scholar_settings_payload(storage)
            finally:
                storage.close()

        self.assertTrue(payload["configured"])
        self.assertEqual(payload["source"], "sqlite")
        self.assertEqual(payload["rate_limit_rps"], 1)
        self.assertNotIn("key", payload)
        self.assertNotIn("local-semantic-secret", repr(payload))

    def test_configured_key_is_sent_in_documented_header(self):
        semantic_scholar.configure_semantic_scholar_api_key("configured-key")
        response = Mock()
        with patch.object(
            semantic_scholar,
            "_wait_for_semantic_scholar_slot",
        ), patch.object(
            semantic_scholar,
            "request_with_retries",
            return_value=response,
        ) as request:
            result = semantic_scholar.semantic_scholar_request(
                "GET",
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={"query": "quantum"},
            )

        self.assertIs(result, response)
        self.assertEqual(request.call_args.kwargs["headers"]["x-api-key"], "configured-key")
        self.assertEqual(request.call_args.kwargs["max_retries"], 1)
        self.assertFalse(request.call_args.kwargs["retry_on_429"])

    def test_anonymous_requests_remain_available_without_key(self):
        semantic_scholar.configure_semantic_scholar_api_key("")
        response = Mock()
        with patch.dict(os.environ, {}, clear=True), patch.object(
            semantic_scholar,
            "_wait_for_semantic_scholar_slot",
        ), patch.object(
            semantic_scholar,
            "request_with_retries",
            return_value=response,
        ) as request:
            semantic_scholar.semantic_scholar_request(
                "GET",
                "https://api.semanticscholar.org/graph/v1/paper/search",
            )

        self.assertNotIn("x-api-key", request.call_args.kwargs.get("headers") or {})

    def test_temporary_errors_use_exponential_retry_path(self):
        response = Mock()
        with patch.object(
            semantic_scholar,
            "_wait_for_semantic_scholar_slot",
        ) as slot, patch.object(
            semantic_scholar,
            "request_with_retries",
            side_effect=[RuntimeError("HTTP 429 Too Many Requests"), response],
        ) as request, patch.object(semantic_scholar.time, "sleep") as sleep:
            result = semantic_scholar.semantic_scholar_request(
                "GET",
                "https://api.semanticscholar.org/graph/v1/paper/search",
                max_retries=2,
            )

        self.assertIs(result, response)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(slot.call_count, 2)
        self.assertEqual(sleep.call_count, 1)
        self.assertGreaterEqual(sleep.call_args.args[0], 1)

    def test_key_test_reports_rate_limit_without_calling_key_invalid(self):
        semantic_scholar.configure_semantic_scholar_api_key("configured-key")
        with patch.object(
            semantic_scholar,
            "semantic_scholar_request",
            side_effect=RuntimeError("HTTP 429 Too Many Requests"),
        ):
            result = semantic_scholar.test_semantic_scholar_api_key("configured-key")

        self.assertEqual(result["status"], "rate_limited")
        self.assertIsNone(result["ok"])
        self.assertTrue(result["configured"])


class SemanticScholarSettingsUiContractTests(unittest.TestCase):
    def test_citation_settings_exposes_semantic_scholar_controls(self):
        html = ui_server.INDEX_HTML
        self.assertIn('id="semanticScholarKeyInput"', html)
        self.assertIn('id="saveSemanticScholarKey"', html)
        self.assertIn('id="testSemanticScholarKey"', html)
        self.assertIn('id="clearSemanticScholarKey"', html)
        self.assertIn('provider: "semantic_scholar"', html)
        self.assertIn("x-api-key", html)
        self.assertIn("1 request-per-second", html)
        self.assertIn("NASA ADS can use an optional API token below", html)

    def test_every_semantic_scholar_http_call_uses_shared_wrapper(self):
        source = Path(ui_server.__file__).read_text(encoding="utf-8")
        lines = source.splitlines()
        for line_number, line in enumerate(lines, start=1):
            if "api.semanticscholar.org" not in line:
                continue
            nearby = "\n".join(lines[max(0, line_number - 4):line_number])
            self.assertIn(
                "semantic_scholar_request(",
                nearby,
                f"ui_server.py:{line_number}",
            )


if __name__ == "__main__":
    unittest.main()
