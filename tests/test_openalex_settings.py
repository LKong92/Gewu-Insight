import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from paper_monitor import ui_server
from paper_monitor.sources import openalex
from paper_monitor.storage import Storage


class OpenAlexCredentialTests(unittest.TestCase):
    def tearDown(self):
        openalex.configure_openalex_api_key("")

    def test_saved_key_is_loaded_from_sqlite_without_being_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                storage.set_setting(openalex.OPENALEX_API_KEY_SETTING, "local-secret")
                with patch.object(
                    ui_server,
                    "refresh_openalex_rate_limit_status",
                    return_value={
                        "configured": True,
                        "status": "connected",
                        "ok": True,
                        "paused": False,
                        "daily_budget_usd": 1,
                        "daily_remaining_usd": 0.75,
                    },
                ):
                    payload = ui_server.openalex_settings_payload(
                        storage,
                        refresh=True,
                    )
            finally:
                storage.close()

        self.assertTrue(payload["configured"])
        self.assertEqual(payload["source"], "sqlite")
        self.assertEqual(payload["daily_remaining_usd"], 0.75)
        self.assertNotIn("key", payload)
        self.assertNotIn("local-secret", repr(payload))

    def test_all_openalex_requests_receive_the_configured_key(self):
        openalex.configure_openalex_api_key("configured-key")
        rate_response = Mock()
        rate_response.json.return_value = {
            "rate_limit": {
                "daily_budget_usd": 1,
                "daily_used_usd": 0,
                "daily_remaining_usd": 1,
                "prepaid_balance_usd": 0,
                "prepaid_remaining_usd": 0,
                "resets_at": "2026-07-28T00:00:00Z",
                "endpoint_costs_usd": {"list": 0.0001, "search": 0.001},
            }
        }
        work_response = Mock()
        work_response.json.return_value = {"results": []}
        with patch.object(
            openalex,
            "request_with_retries",
            side_effect=[rate_response, work_response],
        ) as request:
            openalex.openalex_request(
                "GET",
                "https://api.openalex.org/works",
                params={"search": "quantum", "per-page": 100},
            )

        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[0].kwargs["params"]["api_key"], "configured-key")
        self.assertEqual(request.call_args_list[1].kwargs["params"]["api_key"], "configured-key")

    def test_free_limit_stops_requests_instead_of_retrying_anonymously(self):
        openalex.configure_openalex_api_key("configured-key")
        rate_response = Mock()
        rate_response.json.return_value = {
            "rate_limit": {
                "daily_budget_usd": 1,
                "daily_used_usd": 1,
                "daily_remaining_usd": 0,
                "prepaid_balance_usd": 10,
                "prepaid_remaining_usd": 10,
                "resets_at": "2026-07-28T00:00:00Z",
                "endpoint_costs_usd": {"list": 0.0001, "search": 0.001},
            }
        }
        with patch.object(
            openalex,
            "request_with_retries",
            return_value=rate_response,
        ) as request:
            with self.assertRaises(openalex.OpenAlexDailyLimitError):
                openalex.openalex_request(
                    "GET",
                    "https://api.openalex.org/works",
                    params={"search": "quantum"},
                )

        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs["params"]["api_key"], "configured-key")

    def test_anonymous_requests_remain_available_only_when_no_key_is_configured(self):
        openalex.configure_openalex_api_key("")
        response = Mock()
        with patch.dict(os.environ, {}, clear=True), patch.object(
            openalex,
            "request_with_retries",
            return_value=response,
        ) as request:
            self.assertIs(
                openalex.openalex_request(
                    "GET",
                    "https://api.openalex.org/works/https://doi.org/10.1/example",
                ),
                response,
            )

        self.assertNotIn("api_key", request.call_args.kwargs["params"] or {})


class OpenAlexSettingsUiContractTests(unittest.TestCase):
    def test_citation_settings_exposes_openalex_save_test_clear_and_free_limit_copy(self):
        html = ui_server.INDEX_HTML
        self.assertIn('id="openalexKeyInput"', html)
        self.assertIn('id="saveOpenalexKey"', html)
        self.assertIn('id="testOpenalexKey"', html)
        self.assertIn('id="clearOpenalexKey"', html)
        self.assertIn("daily free allowance", html)
        self.assertIn("Paid credits are not used by Gewu Insight.", html)
        self.assertIn('provider: "openalex"', html)
        self.assertNotIn("OpenAlex...</button>", html)

    def test_every_openalex_http_call_uses_the_shared_request_wrapper(self):
        root = Path(ui_server.__file__).parent
        relevant = [
            root / "ui_server.py",
            root / "download.py",
            root / "sources" / "openalex.py",
        ]
        for path in relevant:
            source = path.read_text(encoding="utf-8")
            for line_number, line in enumerate(source.splitlines(), start=1):
                if "api.openalex.org" not in line:
                    continue
                nearby = "\n".join(
                    source.splitlines()[max(0, line_number - 4):line_number]
                )
                if "/rate-limit" in line:
                    self.assertIn("request_with_retries(", nearby)
                else:
                    self.assertIn(
                        "openalex_request(",
                        nearby,
                        f"{path.name}:{line_number}",
                    )


if __name__ == "__main__":
    unittest.main()
