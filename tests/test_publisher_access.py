from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests

from paper_monitor.http import (
    PUBLISHER_ACCESS_STATE_SETTING,
    PUBLISHER_AUTOMATION_USER_AGENT,
    PublisherAccessBlockedError,
    note_publisher_response,
    publisher_automation_headers,
    publisher_group_for_url,
    publisher_request_guard,
    request_with_local_proxy_fallback,
    reset_publisher_access_state,
)
from paper_monitor.ui_server import (
    discover_paper_figure_url,
    paper_figure_content_type,
    paper_image_proxy_url,
    resolve_arxiv_identifier_for_figure,
)
from paper_monitor.sources.publisher import fetch_arxiv_first_figure_url
from paper_monitor.storage import Storage


class PublisherAccessTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_publisher_access_state()

    def tearDown(self) -> None:
        reset_publisher_access_state()

    def test_curated_feed_publishers_share_host_level_groups(self) -> None:
        cases = {
            "https://www.nature.com/nphys.rss": "springer_nature",
            "https://media.springernature.com/example.png": "springer_nature",
            "https://www.science.org/action/showFeed": "aaas",
            "https://feeds.aps.org/rss/recent/prl.xml": "aps",
            "https://iopscience.iop.org/journal/rss/1367-2630": "iop",
            "https://pubs.aip.org/rss/example.xml": "aip",
            "https://pubs.acs.org/action/showFeed": "acs",
            "https://quantum-journal.org/feed/": "quantum",
            "https://doi.org/10.1038/example": "springer_nature",
            "https://doi.org/10.1126/example": "aaas",
            "https://doi.org/10.1103/example": "aps",
            "https://doi.org/10.1088/example": "iop",
            "https://doi.org/10.1063/example": "aip",
            "https://doi.org/10.1021/example": "acs",
            "https://doi.org/10.22331/example": "quantum",
        }
        self.assertEqual(
            {url: publisher_group_for_url(url) for url in cases},
            cases,
        )

    def test_publisher_requests_identify_text_data_mining(self) -> None:
        headers = publisher_automation_headers(
            "https://www.nature.com/nphys.rss",
            {"Accept": "application/xml"},
        )
        self.assertEqual(headers["User-Agent"], PUBLISHER_AUTOMATION_USER_AGENT)
        self.assertIn("TextDataMining", headers["User-Agent"])
        self.assertEqual(headers["Accept"], "application/xml")
        science_headers = publisher_automation_headers("https://www.science.org/action/showFeed")
        self.assertNotIn("TextDataMining", science_headers["User-Agent"])

    def test_406_persists_cooldown_across_process_state_reset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "paper_monitor.sqlite")
            try:
                response = SimpleNamespace(
                    status_code=406,
                    headers={"Content-Type": "text/html"},
                    text="Access Blocked due to suspicious activity",
                )
                with self.assertRaises(PublisherAccessBlockedError):
                    note_publisher_response(
                        response,
                        "https://www.nature.com/nphys.rss",
                        storage=storage,
                    )
                persisted = json.loads(storage.get_setting(PUBLISHER_ACCESS_STATE_SETTING, "{}"))
                self.assertEqual(persisted["springer_nature:page"]["last_status"], 406)
                self.assertTrue(persisted["springer_nature:page"]["blocked_until"])

                reset_publisher_access_state()
                with self.assertRaises(PublisherAccessBlockedError):
                    with publisher_request_guard(
                        "https://www.nature.com/another-feed.rss",
                        storage=storage,
                    ):
                        self.fail("persisted publisher cooldown should prevent another request")
                with publisher_request_guard(
                    "https://media.springernature.com/example.jpg",
                    storage=storage,
                    access_kind="image",
                ):
                    pass
                with publisher_request_guard(
                    "https://doi.org/10.1038/example",
                    storage=storage,
                    access_kind="figure",
                ):
                    pass
            finally:
                storage.close()

    def test_access_block_html_is_detected_even_with_http_200(self) -> None:
        response = SimpleNamespace(
            status_code=200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            text="<h1>Access Blocked</h1><p>Your IP was blocked due to suspicious activity.</p>",
        )
        with self.assertRaises(PublisherAccessBlockedError):
            note_publisher_response(response, "https://www.science.org/article/example")

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

    def test_paper_images_use_local_proxy_urls_and_validate_content(self) -> None:
        paper = {
            "paper_id": "doi_example",
            "image_url": "https://media.springernature.com/example.jpg",
        }
        self.assertEqual(paper_image_proxy_url(paper), "/api/paper-image?paper_id=doi_example")
        content_type, suffix = paper_figure_content_type(
            b"\xff\xd8\xffexample",
            {"content-type": "image/jpeg"},
            paper["image_url"],
        )
        self.assertEqual((content_type, suffix), ("image/jpeg", ".jpg"))
        with self.assertRaises(ValueError):
            paper_figure_content_type(
                b"<html>Access Blocked</html>",
                {"content-type": "text/html"},
                paper["image_url"],
            )

    def test_arxiv_html_first_figure_uses_article_image(self) -> None:
        response = SimpleNamespace(
            text='<html><figure><img src="x1.png" width="580" height="470"></figure></html>',
            url="https://arxiv.org/html/2505.20752",
            raise_for_status=lambda: None,
        )
        with patch("paper_monitor.sources.publisher.get_with_local_proxy_fallback", return_value=response):
            self.assertEqual(
                fetch_arxiv_first_figure_url("2505.20752"),
                "https://arxiv.org/html/2505.20752/x1.png",
            )

    def test_exact_arxiv_doi_lookup_resolves_arxiv_id(self) -> None:
        paper = {"doi": "10.1103/example", "title": "Example"}
        with patch(
            "paper_monitor.ui_server.fetch_arxiv_by_doi",
            return_value={"journal": "arXiv", "landing_url": "https://arxiv.org/abs/2505.20752v2"},
        ):
            self.assertEqual(resolve_arxiv_identifier_for_figure(paper), "2505.20752")

    def test_aps_figure_uses_arxiv_without_visiting_publisher_page(self) -> None:
        paper = {
            "paper_id": "doi_example",
            "doi": "10.1103/example",
            "journal": "Physical Review Letters",
            "landing_url": "https://doi.org/10.1103/example",
        }
        with patch(
            "paper_monitor.ui_server.resolve_arxiv_identifier_for_figure",
            return_value="2505.20752",
        ), patch(
            "paper_monitor.ui_server.fetch_arxiv_first_figure_url",
            return_value="https://arxiv.org/html/2505.20752/x1.png",
        ), patch("paper_monitor.ui_server.enrich_image_from_landing_page") as landing:
            self.assertEqual(
                discover_paper_figure_url(paper),
                "https://arxiv.org/html/2505.20752/x1.png",
            )
        landing.assert_not_called()


if __name__ == "__main__":
    unittest.main()
