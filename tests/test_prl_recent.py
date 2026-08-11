from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from requests import HTTPError

from paper_monitor.aps import aps_journal_slug, is_aps_lifecycle_journal
from paper_monitor.config import AppConfig, JournalConfig
from paper_monitor.monitor import apply_fast_section_hints, dedup_by_id, fetch_one_journal
from paper_monitor.reporting import section_badge_background, section_color
from paper_monitor.sources.crossref import fetch_crossref_journal, normalize_crossref_item
from paper_monitor.sources.openalex import fetch_openalex_work_by_doi, normalize_openalex_item
from paper_monitor.sources.publisher import (
    JournalFeedDefinition,
    enrich_aps_abstract_from_rss,
    enrich_rmp_abstract_from_aps,
    enrich_rmp_abstract_from_rss,
    journal_feed_definitions,
    parse_aps_rss_entries,
    parse_journal_feed_entries,
    parse_rmp_rss_abstracts,
    reset_aps_abstract_fetch_state,
    sync_aps_rss_feeds,
    sync_journal_feeds,
)
from paper_monitor.storage import Storage
from paper_monitor.ui_server import (
    JOURNAL_PRESETS,
    canonical_journal_name_for_add,
    classify_fields,
    journal_issns_for_add,
)


def crossref_item(
    *,
    formal: bool,
    published: tuple[int, int, int],
    doi: str = "10.1103/3gg8-wgdr",
    journal: str = "Physical Review Letters",
) -> dict:
    item = {
        "DOI": doi,
        "URL": f"https://doi.org/{doi}",
        "title": ["Volume-Law Protection of Metrological Advantage"],
        "container-title": [journal],
        "published-online": {"date-parts": [list(published)]},
        "issued": {"date-parts": [list(published)]},
        "type": "journal-article",
    }
    if formal:
        item.update(
            {"volume": "16", "issue": "3", "article-number": "031006"}
            if journal == "Physical Review X"
            else {"volume": "137", "issue": "3", "article-number": "030801"}
        )
    return item


def openalex_item(
    *,
    formal: bool,
    published: str,
    doi: str = "10.1103/g565-3dyn",
    journal: str = "Physical Review X",
) -> dict:
    return {
        "id": "https://openalex.org/W123",
        "doi": f"https://doi.org/{doi}",
        "title": "Topological defect propagation to classify knitted fabrics",
        "publication_date": published,
        "type": "article",
        "biblio": {"volume": "16" if formal else None, "issue": "3" if formal else None},
        "primary_location": {
            "landing_page_url": f"https://doi.org/{doi}",
            "pdf_url": "",
            "version": "publishedVersion" if formal else "acceptedVersion",
            "source": {"display_name": journal},
        },
    }


class PrlRecentTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_aps_abstract_fetch_state()

    def tearDown(self) -> None:
        reset_aps_abstract_fetch_state()

    def test_published_and_preprint_titles_use_normal_article_green(self) -> None:
        for section in ("article", "research article", "published", "preprint"):
            self.assertEqual(section_color(section), "#17643b")
            self.assertEqual(section_badge_background(section), "#e9f7ef")

    def test_crossref_cursor_can_be_reused_for_the_next_page(self) -> None:
        class Response:
            def __init__(self, payload: dict) -> None:
                self.payload = payload

            def json(self) -> dict:
                return self.payload

        pages = [
            Response(
                {
                    "message": {
                        "items": [
                            {
                                **crossref_item(formal=True, published=(2026, 7, 13)),
                                "DOI": "10.1103/first-page",
                            }
                        ],
                        "next-cursor": "reused-scroll-cursor",
                    }
                }
            ),
            Response(
                {
                    "message": {
                        "items": [
                            {
                                **crossref_item(formal=True, published=(2026, 7, 13)),
                                "DOI": "10.1103/second-page",
                            }
                        ],
                        "next-cursor": "reused-scroll-cursor",
                    }
                }
            ),
            Response({"message": {"items": [], "next-cursor": "reused-scroll-cursor"}}),
        ]
        with patch("paper_monitor.sources.crossref.request_with_retries", side_effect=pages) as request:
            papers = fetch_crossref_journal(
                journal_name="Physical Review Letters",
                issns=["1079-7114"],
                start_date=date(2026, 7, 13),
                end_date=date(2026, 7, 13),
                rows=1,
                max_pages=3,
            )

        self.assertEqual([paper["doi"] for paper in papers], ["10.1103/first-page", "10.1103/second-page"])
        self.assertEqual(request.call_count, 3)

    def test_crossref_preserves_good_issn_results_when_an_alternate_issn_fails(self) -> None:
        class Response:
            def json(self) -> dict:
                return {
                    "message": {
                        "items": [
                            crossref_item(
                                formal=True,
                                published=(2026, 7, 13),
                                doi="10.1103/wd4f-q7kv",
                                journal="Reviews of Modern Physics",
                            )
                        ]
                    }
                }

        with patch(
            "paper_monitor.sources.crossref.request_with_retries",
            side_effect=[Response(), HTTPError("unsupported alternate ISSN")],
        ):
            papers = fetch_crossref_journal(
                journal_name="Reviews of Modern Physics",
                issns=["0034-6861", "unsupported"],
                start_date=date(2026, 7, 13),
                end_date=date(2026, 7, 13),
            )

        self.assertEqual([paper["doi"] for paper in papers], ["10.1103/wd4f-q7kv"])
        self.assertTrue(papers[0]["section_allowed"])

    def test_crossref_raises_when_every_issn_request_fails(self) -> None:
        with patch(
            "paper_monitor.sources.crossref.request_with_retries",
            side_effect=[HTTPError("first failed"), HTTPError("second failed")],
        ):
            with self.assertRaisesRegex(HTTPError, "first failed"):
                fetch_crossref_journal(
                    journal_name="Reviews of Modern Physics",
                    issns=["first", "second"],
                    start_date=date(2026, 7, 13),
                    end_date=date(2026, 7, 13),
                )

    def test_rmp_preset_uses_only_crossref_supported_issns(self) -> None:
        for name in ("reviews of modern physics", "review of modern physics", "rmp"):
            preset = JOURNAL_PRESETS[name]
            self.assertEqual(preset["canonical_name"], "Reviews of Modern Physics")
            self.assertEqual(preset["issns"], ["0034-6861", "1539-0756"])
            self.assertTrue(preset["authoritative_issns"])
            self.assertEqual(canonical_journal_name_for_add(name), "Reviews of Modern Physics")
            self.assertEqual(
                journal_issns_for_add(name, ["0034-6861", "1538-4527", "1539-0756"]),
                ["0034-6861", "1539-0756"],
            )

    def test_all_current_aps_journals_have_rss_slugs_and_lifecycle_handling(self) -> None:
        expected = {
            "APS Open Science": "apsos",
            "Physical Review A": "pra",
            "Physical Review B": "prb",
            "Physical Review C": "prc",
            "Physical Review D": "prd",
            "Physical Review E": "pre",
            "Physical Review Accelerators and Beams": "prstab",
            "Physical Review Applied": "prapplied",
            "Physical Review Fluids": "prfluids",
            "Physical Review Letters": "prl",
            "Physical Review Materials": "prmaterials",
            "Physical Review Physics Education Research": "prstper",
            "Physical Review Research": "prresearch",
            "Physical Review X": "prx",
            "PRX Energy": "prxenergy",
            "PRX Intelligence": "prxintelligence",
            "PRX Life": "prxlife",
            "PRX Quantum": "prxquantum",
            "Reviews of Modern Physics": "rmp",
        }
        for journal, slug in expected.items():
            self.assertEqual(aps_journal_slug(journal), slug)
            self.assertTrue(is_aps_lifecycle_journal(journal))

    def test_rmp_articles_are_visible_under_the_default_physics_filter(self) -> None:
        self.assertEqual(
            classify_fields(
                {
                    "journal": "Reviews of Modern Physics",
                    "title": "Colloquium: what do we mean by ‘active matter’?",
                    "abstract": "",
                }
            ),
            ["physics"],
        )

    def test_openalex_exact_doi_lookup_can_supply_rmp_abstract_without_search(self) -> None:
        item = openalex_item(
            formal=True,
            published="2026-07-13",
            doi="10.1103/wd4f-q7kv",
        )
        item["abstract_inverted_index"] = {
            "This": [0],
            "abstract": [1],
            "came": [2],
            "from": [3],
            "OpenAlex.": [4],
        }

        class Response:
            @staticmethod
            def json() -> dict:
                return item

        with patch(
            "paper_monitor.sources.openalex.openalex_request",
            return_value=Response(),
        ) as request:
            paper = fetch_openalex_work_by_doi(
                "https://doi.org/10.1103/wd4f-q7kv",
                journal_name="Reviews of Modern Physics",
            )

        self.assertEqual(paper["abstract"], "This abstract came from OpenAlex.")
        self.assertIn("works/https%3A%2F%2Fdoi.org%2F10.1103%2Fwd4f-q7kv", request.call_args.args[1])
        self.assertEqual(request.call_args.kwargs["max_retries"], 1)

    def test_rmp_formal_abstract_is_fetched_once_and_then_cached(self) -> None:
        class Response:
            status_code = 200
            text = """
                <html><body><section class="abstract"><h2>Abstract</h2>
                <p>This is a sufficiently long APS abstract that describes the formal published
                article and is deliberately longer than the parser minimum.</p></section></body></html>
            """

        paper = {
            "journal": "Reviews of Modern Physics",
            "doi": "10.1103/wd4f-q7kv",
            "abstract": "",
            "publisher_section": "published",
            "section_allowed": True,
        }
        with patch("paper_monitor.sources.publisher.requests.get", return_value=Response()) as request:
            first = enrich_rmp_abstract_from_aps(dict(paper))
            second = enrich_rmp_abstract_from_aps(dict(paper))

        self.assertIn("sufficiently long APS abstract", first["abstract"])
        self.assertEqual(first["abstract_source"], "aps")
        self.assertEqual(second["abstract"], first["abstract"])
        self.assertEqual(request.call_count, 1)

    def test_rmp_official_rss_summary_is_parsed_and_cached_by_doi(self) -> None:
        payload = b"""<?xml version='1.0'?>
        <rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'
          xmlns='http://purl.org/rss/1.0/'
          xmlns:prism='http://prismstandard.org/namespaces/basic/2.0/'
          xmlns:content='http://purl.org/rss/1.0/modules/content/'>
          <item rdf:about='https://link.aps.org/doi/10.1103/wd4f-q7kv'>
            <description>Author(s): Example&lt;p&gt;An official publisher summary long enough to be used as the safe abstract fallback for this formal RMP article.&lt;/p&gt;</description>
            <content:encoded><![CDATA[<p>Author(s): Example</p><p>An official publisher summary long enough to be used as the safe abstract fallback for this formal RMP article.</p>]]></content:encoded>
            <prism:doi>10.1103/wd4f-q7kv</prism:doi>
          </item>
        </rdf:RDF>"""
        parsed = parse_rmp_rss_abstracts(payload)
        self.assertIn("official publisher summary", parsed["10.1103/wd4f-q7kv"])

        class Response:
            content = payload

            @staticmethod
            def raise_for_status() -> None:
                return None

        paper = {
            "journal": "Reviews of Modern Physics",
            "doi": "10.1103/wd4f-q7kv",
            "abstract": "",
            "publisher_section": "published",
            "section_allowed": True,
        }
        with patch("paper_monitor.sources.publisher.requests.get", return_value=Response()) as request:
            first = enrich_rmp_abstract_from_rss(dict(paper))
            second = enrich_rmp_abstract_from_rss(dict(paper))

        self.assertEqual(first["abstract_source"], "aps_rss")
        self.assertEqual(second["abstract"], first["abstract"])
        self.assertEqual(request.call_count, 1)

    def test_prl_uses_its_own_official_rss_feed_for_missing_abstract(self) -> None:
        payload = b"""<?xml version='1.0'?>
        <rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'
          xmlns='http://purl.org/rss/1.0/'
          xmlns:prism='http://prismstandard.org/namespaces/basic/2.0/'
          xmlns:content='http://purl.org/rss/1.0/modules/content/'>
          <item rdf:about='https://link.aps.org/doi/10.1103/example-prl'>
            <content:encoded><![CDATA[<p>Author(s): Example</p><p>This official PRL publisher summary is intentionally long enough to provide a safe RSS abstract fallback without loading an article page.</p>]]></content:encoded>
            <prism:doi>10.1103/example-prl</prism:doi>
          </item>
        </rdf:RDF>"""

        class Response:
            content = payload

            @staticmethod
            def raise_for_status() -> None:
                return None

        paper = {
            "journal": "Physical Review Letters",
            "doi": "10.1103/example-prl",
            "abstract": "",
            "publisher_section": "published",
            "section_allowed": True,
        }
        with patch("paper_monitor.sources.publisher.requests.get", return_value=Response()) as request:
            result = enrich_aps_abstract_from_rss(paper)

        self.assertEqual(result["abstract_source"], "aps_rss")
        self.assertIn("official PRL publisher summary", result["abstract"])
        self.assertTrue(request.call_args.args[0].endswith("/recent/prl.xml"))

    def test_persistent_aps_rss_cache_is_shared_by_subject_and_journal_paths(self) -> None:
        payload = b"""<?xml version='1.0'?>
        <rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'
          xmlns='http://purl.org/rss/1.0/'
          xmlns:dc='http://purl.org/dc/elements/1.1/'
          xmlns:prism='http://prismstandard.org/namespaces/basic/2.0/'
          xmlns:content='http://purl.org/rss/1.0/modules/content/'>
          <item rdf:about='https://link.aps.org/doi/10.1103/example-materials'>
            <title>A persistent APS RSS paper about quantum materials</title>
            <link>https://link.aps.org/doi/10.1103/example-materials</link>
            <content:encoded><![CDATA[<p>Author(s): Ada Example and Ben Example</p><p>This official APS RSS abstract is intentionally long enough to support local Subject Monitor keyword matching without opening an article page.</p>]]></content:encoded>
            <dc:title>A persistent APS RSS paper about quantum materials</dc:title>
            <dc:creator>Ada Example and Ben Example</dc:creator>
            <dc:date>2026-08-01T10:00:00+00:00</dc:date>
            <prism:doi>10.1103/example-materials</prism:doi>
            <prism:publicationName>Physical Review Materials</prism:publicationName>
            <prism:volume>10</prism:volume>
            <prism:number>8</prism:number>
            <prism:publicationDate>2026-08-01T10:00:00+00:00</prism:publicationDate>
            <prism:url>https://link.aps.org/doi/10.1103/example-materials</prism:url>
            <prism:startingPage>081001</prism:startingPage>
          </item>
        </rdf:RDF>"""

        class Response:
            status_code = 200
            content = payload
            headers: dict[str, str] = {}

            @staticmethod
            def raise_for_status() -> None:
                return None

        parsed = parse_aps_rss_entries(
            payload,
            journal_slug="prmaterials",
            journal_name="Physical Review Materials",
        )
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["publication_date"], "2026-08-01")
        self.assertEqual(parsed[0]["publisher_section"], "published")

        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "paper_monitor.sqlite")
            try:
                with patch("paper_monitor.sources.publisher.requests.get", return_value=Response()) as request:
                    first = sync_aps_rss_feeds(storage, journal_slugs=["prmaterials"])
                    second = sync_aps_rss_feeds(storage, journal_slugs=["prmaterials"])
                    journal_paper = enrich_aps_abstract_from_rss(
                        {
                            "journal": "Physical Review Materials",
                            "doi": "10.1103/example-materials",
                            "abstract": "",
                            "publisher_section": "published",
                            "section_allowed": True,
                        },
                        storage=storage,
                    )

                self.assertEqual(request.call_count, 1)
                self.assertEqual(first["created"], 1)
                self.assertEqual(second["feeds"]["prmaterials"]["status"], "cached")
                self.assertIn("official APS RSS abstract", journal_paper["abstract"])
                subject_papers = storage.list_aps_rss_papers(
                    start_date="2026-08-01",
                    end_date="2026-08-01",
                )
                self.assertEqual([paper["doi"] for paper in subject_papers], ["10.1103/example-materials"])
            finally:
                storage.close()

    def test_standard_journal_feed_keeps_research_items_and_exact_dates(self) -> None:
        payload = b"""<?xml version='1.0'?>
        <rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'
          xmlns='http://purl.org/rss/1.0/'
          xmlns:dc='http://purl.org/dc/elements/1.1/'
          xmlns:prism='http://prismstandard.org/namespaces/basic/2.0/'
          xmlns:media='http://search.yahoo.com/mrss/'>
          <item rdf:about='https://www.science.org/doi/abs/10.1126/science.example'>
            <title>A quantum materials result from an official feed</title>
            <link>https://www.science.org/doi/abs/10.1126/science.example</link>
            <dc:date>2026-08-06T07:00:00Z</dc:date>
            <dc:type>Research Article</dc:type>
            <prism:doi>10.1126/science.example</prism:doi>
            <prism:publicationName>Science</prism:publicationName>
            <media:thumbnail url='https://www.science.org/cms/asset/example.jpg'/>
          </item>
          <item rdf:about='https://www.science.org/doi/abs/10.1126/science.book'>
            <title>A book notice that must not enter Subject Monitor</title>
            <dc:date>2026-08-06T07:00:00Z</dc:date>
            <dc:type>Books et al.</dc:type>
            <prism:doi>10.1126/science.book</prism:doi>
          </item>
        </rdf:RDF>"""
        definition = JournalFeedDefinition(
            key="aaas:science",
            publisher="AAAS",
            journal_name="Science",
            url="https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science",
            doi_prefixes=("10.1126/",),
            allowed_item_types=("research article",),
            include_abstract=False,
        )

        papers = parse_journal_feed_entries(payload, definition)

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["doi"], "10.1126/science.example")
        self.assertEqual(papers[0]["publication_date"], "2026-08-06")
        self.assertEqual(papers[0]["journal"], "Science")
        self.assertEqual(papers[0]["abstract"], "")
        self.assertEqual(papers[0]["image_url"], "https://www.science.org/cms/asset/example.jpg")

    def test_curated_physics_feed_registry_contains_both_expansion_batches(self) -> None:
        definitions = journal_feed_definitions()
        expected = {
            "nature:nature-physics",
            "nature:communications-physics",
            "iop:new-journal-of-physics",
            "iop:reports-on-progress-in-physics",
            "nature:nature-reviews-physics",
            "nature:npj-quantum-materials",
            "iop:journal-of-physics-condensed-matter",
            "nature:npj-quantum-information",
            "iop:quantum-science-and-technology",
            "aip:applied-physics-letters",
            "nature:nature-materials",
            "nature:nature-nanotechnology",
            "iop:2d-materials",
            "aip:avs-quantum-science",
            "aip:journal-of-applied-physics",
            "acs:nano-letters",
            "quantum:quantum",
            "aip:review-of-scientific-instruments",
        }

        self.assertTrue(expected.issubset(definitions))
        self.assertEqual(definitions["quantum:quantum"].required_item_categories, ("paper",))
        self.assertEqual(definitions["acs:nano-letters"].fallback_issns, ("1530-6992",))

    def test_quantum_feed_extracts_doi_from_description_and_rejects_news(self) -> None:
        payload = b"""<?xml version='1.0'?><rss version='2.0'><channel>
          <item><title>A research result</title><link>https://quantum-journal.org/papers/example/</link>
            <pubDate>Fri, 07 Aug 2026 14:10:44 +0000</pubDate><category>Paper</category>
            <description><![CDATA[<a href='https://doi.org/10.22331/q-example'>DOI</a><p class='abstract'>A sufficiently long abstract describing a quantum information research result for feed parsing.</p>]]></description>
          </item>
          <item><title>Journal announcement</title><link>https://quantum-journal.org/news/example/</link>
            <pubDate>Fri, 07 Aug 2026 14:10:44 +0000</pubDate><category>News</category>
            <description>https://doi.org/10.22331/q-news</description>
          </item>
        </channel></rss>"""
        definition = journal_feed_definitions()["quantum:quantum"]

        papers = parse_journal_feed_entries(payload, definition)

        self.assertEqual([paper["doi"] for paper in papers], ["10.22331/q-example"])
        self.assertIn("quantum information", papers[0]["abstract"])

    def test_standard_feed_repairs_bare_ampersand_and_filters_corrections(self) -> None:
        payload = b"""<rss><channel>
          <item><title>Quantum A & B coupling</title><link>https://doi.org/10.2000/research</link>
            <pubDate>Thu, 06 Aug 2026 07:00:00 GMT</pubDate><doi>10.2000/research</doi></item>
          <item><title>Publisher Correction: Quantum result</title><link>https://doi.org/10.2000/correction</link>
            <pubDate>Thu, 06 Aug 2026 07:00:00 GMT</pubDate><doi>10.2000/correction</doi></item>
        </channel></rss>"""
        definition = JournalFeedDefinition(
            key="publisher:journal",
            publisher="Publisher",
            journal_name="Journal",
            url="https://example.test/rss",
            doi_prefixes=("10.2000/",),
        )

        papers = parse_journal_feed_entries(payload, definition)

        self.assertEqual([paper["doi"] for paper in papers], ["10.2000/research"])
        self.assertIn("& B coupling", papers[0]["title"])

    def test_blocked_official_feed_uses_issn_fallback(self) -> None:
        class BlockedResponse:
            status_code = 403
            content = b""
            headers: dict[str, str] = {}

            @staticmethod
            def raise_for_status() -> None:
                raise HTTPError("blocked")

        definition = JournalFeedDefinition(
            key="acs:nano-letters-test",
            publisher="American Chemical Society Test",
            journal_name="Nano Letters",
            url="https://pubs.acs.org/example.xml",
            doi_prefixes=("10.1021/",),
            fallback_issns=("1530-6992",),
        )
        fallback_paper = normalize_crossref_item(
            {
                "DOI": "10.1021/acs.nanolett.example",
                "URL": "https://doi.org/10.1021/acs.nanolett.example",
                "title": ["A nanoscale quantum materials result"],
                "container-title": ["Nano Letters"],
                "published-online": {"date-parts": [[2026, 8, 6]]},
                "type": "journal-article",
            },
            "Nano Letters",
        )
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "paper_monitor.sqlite")
            try:
                with patch(
                    "paper_monitor.sources.publisher.requests.get",
                    return_value=BlockedResponse(),
                ), patch(
                    "paper_monitor.sources.publisher.fetch_crossref_journal",
                    return_value=[fallback_paper],
                ):
                    summary = sync_journal_feeds(
                        storage,
                        definitions={definition.key: definition},
                        force=True,
                    )

                self.assertEqual(summary["status"], "success")
                self.assertEqual(summary["feeds"][definition.key]["status"], "fallback")
                saved = storage.list_journal_feed_papers(
                    start_date="2026-08-06",
                    end_date="2026-08-06",
                )
                self.assertEqual([paper["doi"] for paper in saved], ["10.1021/acs.nanolett.example"])
            finally:
                storage.close()

    def test_journal_feed_failures_are_isolated_by_publisher(self) -> None:
        payload = b"""<rss><channel><item>
          <title>A valid quantum materials research article</title>
          <link>https://doi.org/10.2000/example</link>
          <pubDate>Thu, 06 Aug 2026 07:00:00 GMT</pubDate>
          <type>Research Article</type>
          <doi>10.2000/example</doi>
        </item></channel></rss>"""

        class BlockedResponse:
            status_code = 429
            content = b""
            headers: dict[str, str] = {}

            @staticmethod
            def raise_for_status() -> None:
                raise HTTPError("rate limited")

        class SuccessResponse:
            status_code = 200
            content = payload
            headers: dict[str, str] = {}

            @staticmethod
            def raise_for_status() -> None:
                return None

        definitions = {
            "blocked:one": JournalFeedDefinition(
                key="blocked:one",
                publisher="Blocked Publisher",
                journal_name="Blocked Journal",
                url="https://blocked.example/feed",
            ),
            "healthy:one": JournalFeedDefinition(
                key="healthy:one",
                publisher="Healthy Publisher",
                journal_name="Healthy Journal",
                url="https://healthy.example/feed",
            ),
        }
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "paper_monitor.sqlite")
            try:
                with patch(
                    "paper_monitor.sources.publisher.requests.get",
                    side_effect=[BlockedResponse(), SuccessResponse()],
                ) as request:
                    summary = sync_journal_feeds(storage, definitions=definitions, force=True)

                self.assertEqual(request.call_count, 2)
                self.assertEqual(summary["status"], "partial")
                self.assertEqual(summary["feeds"]["blocked:one"]["status"], "error")
                self.assertEqual(summary["feeds"]["healthy:one"]["status"], "success")
                papers = storage.list_journal_feed_papers(
                    start_date="2026-08-06",
                    end_date="2026-08-06",
                )
                self.assertEqual([paper["doi"] for paper in papers], ["10.2000/example"])
            finally:
                storage.close()

    def test_legacy_aps_feed_cache_migrates_without_removing_legacy_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "paper_monitor.sqlite")
            try:
                paper = {
                    "paper_id": "doi_legacy_aps_feed",
                    "doi": "10.1103/legacy-feed",
                    "title": "A legacy APS feed record",
                    "journal": "Physical Review Materials",
                    "publication_date": "2026-08-01",
                    "abstract": "",
                    "url": "https://doi.org/10.1103/legacy-feed",
                    "source": "aps_rss",
                    "type": "journal-article",
                    "type_crossref": "journal-article",
                    "publisher_section": "published",
                    "section_allowed": True,
                    "raw": {"type": "journal-article"},
                }
                storage.upsert_paper(paper)
                storage.conn.execute(
                    """
                    INSERT INTO aps_rss_feeds (
                      journal_slug, journal_name, status, entry_count, checked_at, success_at
                    ) VALUES ('prmaterials', 'Physical Review Materials', 'success', 1, '2026-08-01T00:00:00+00:00', '2026-08-01T00:00:00+00:00')
                    """
                )
                storage.conn.execute(
                    """
                    INSERT INTO aps_rss_entries (
                      journal_slug, paper_id, publication_date, first_seen_at, last_seen_at
                    ) VALUES ('prmaterials', 'doi_legacy_aps_feed', '2026-08-01', '2026-08-01T00:00:00+00:00', '2026-08-01T00:00:00+00:00')
                    """
                )
                storage.conn.execute("DELETE FROM journal_feed_entries")
                storage.conn.execute("DELETE FROM journal_feeds")
                storage.conn.commit()

                storage._migrate_aps_rss_to_journal_feeds()

                self.assertIsNotNone(storage.get_journal_feed("aps:prmaterials"))
                papers = storage.list_journal_feed_papers(
                    start_date="2026-08-01",
                    end_date="2026-08-01",
                )
                self.assertEqual([item["paper_id"] for item in papers], ["doi_legacy_aps_feed"])
                legacy_count = storage.conn.execute(
                    "SELECT COUNT(*) FROM aps_rss_entries WHERE journal_slug = 'prmaterials'"
                ).fetchone()[0]
                self.assertEqual(legacy_count, 1)
            finally:
                storage.close()

    def test_aps_rss_fills_blanks_without_overwriting_or_recounting_existing_doi(self) -> None:
        payload = b"""<?xml version='1.0'?>
        <rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'
          xmlns='http://purl.org/rss/1.0/'
          xmlns:dc='http://purl.org/dc/elements/1.1/'
          xmlns:prism='http://prismstandard.org/namespaces/basic/2.0/'
          xmlns:content='http://purl.org/rss/1.0/modules/content/'>
          <item rdf:about='https://link.aps.org/doi/10.1103/existing-doi'>
            <title>RSS title must not replace trusted metadata</title>
            <link>https://link.aps.org/doi/10.1103/existing-doi</link>
            <content:encoded><![CDATA[<p>An APS RSS abstract that is deliberately long enough to fill an empty abstract while preserving all trusted bibliographic metadata already stored for the DOI.</p>]]></content:encoded>
            <dc:date>2026-08-01T10:00:00+00:00</dc:date>
            <prism:doi>10.1103/existing-doi</prism:doi>
            <prism:publicationName>Physical Review Materials</prism:publicationName>
            <prism:publicationDate>2026-08-01T10:00:00+00:00</prism:publicationDate>
          </item>
        </rdf:RDF>"""

        class Response:
            status_code = 200
            content = payload
            headers: dict[str, str] = {}

            @staticmethod
            def raise_for_status() -> None:
                return None

        rss_paper = parse_aps_rss_entries(
            payload,
            journal_slug="prmaterials",
            journal_name="Physical Review Materials",
        )[0]
        existing = {
            **rss_paper,
            "title": "Trusted Crossref title",
            "abstract": "",
            "abstract_source": "",
            "source": "crossref",
            "raw": {"source": "crossref"},
        }

        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "paper_monitor.sqlite")
            try:
                storage.upsert_paper(existing)
                with patch("paper_monitor.sources.publisher.requests.get", return_value=Response()) as request:
                    first = sync_aps_rss_feeds(storage, journal_slugs=["prmaterials"], force=True)
                    second = sync_aps_rss_feeds(storage, journal_slugs=["prmaterials"], force=True)

                saved = storage.get_paper(rss_paper["paper_id"])
                self.assertEqual(request.call_count, 2)
                self.assertEqual(first["created"], 0)
                self.assertEqual(second["created"], 0)
                self.assertEqual(saved["title"], "Trusted crossref title")
                self.assertIn("APS RSS abstract", saved["abstract"])
                self.assertEqual(saved["source_count"], 2)
            finally:
                storage.close()

    def test_rmp_accepted_records_never_request_an_aps_page(self) -> None:
        paper = {
            "journal": "Reviews of Modern Physics",
            "doi": "10.1103/j9ly-b6q3",
            "abstract": "",
            "publisher_section": "accepted",
            "section_allowed": False,
        }
        with patch("paper_monitor.sources.publisher.requests.get") as request:
            result = enrich_rmp_abstract_from_aps(dict(paper))

        self.assertFalse(result["abstract"])
        request.assert_not_called()

    def test_rmp_aps_block_response_starts_global_cooldown_without_retry(self) -> None:
        class Response:
            status_code = 429
            text = ""

        first = {
            "journal": "Reviews of Modern Physics",
            "doi": "10.1103/first",
            "abstract": "",
            "publisher_section": "published",
            "section_allowed": True,
        }
        second = {**first, "doi": "10.1103/second"}
        with patch("paper_monitor.sources.publisher.requests.get", return_value=Response()) as request:
            enrich_rmp_abstract_from_aps(first)
            enrich_rmp_abstract_from_aps(second)

        self.assertEqual(request.call_count, 1)

    def test_crossref_normalization_hides_accepted_and_allows_formal_prl(self) -> None:
        accepted = normalize_crossref_item(
            crossref_item(formal=False, published=(2026, 6, 8)),
            "Physical Review Letters",
        )
        formal = normalize_crossref_item(
            crossref_item(formal=True, published=(2026, 7, 13)),
            "Physical Review Letters",
        )

        self.assertEqual(accepted["publisher_section"], "accepted")
        self.assertFalse(accepted["section_allowed"])
        self.assertEqual(formal["publisher_section"], "published")
        self.assertTrue(formal["section_allowed"])

    def test_crossref_normalization_hides_accepted_and_allows_formal_prx(self) -> None:
        accepted = normalize_crossref_item(
            crossref_item(
                formal=False,
                published=(2026, 7, 8),
                doi="10.1103/cbrd-ssnm",
                journal="Physical Review X",
            ),
            "Physical Review X",
        )
        formal = normalize_crossref_item(
            crossref_item(
                formal=True,
                published=(2026, 7, 14),
                doi="10.1103/g565-3dyn",
                journal="Physical Review X",
            ),
            "Physical Review X",
        )

        self.assertEqual(accepted["publisher_section"], "accepted")
        self.assertFalse(accepted["section_allowed"])
        self.assertEqual(formal["publisher_section"], "published")
        self.assertTrue(formal["section_allowed"])

    def test_rmp_uses_the_same_accepted_and_published_lifecycle(self) -> None:
        journal = "Reviews of Modern Physics"
        accepted = normalize_crossref_item(
            crossref_item(
                formal=False,
                published=(2026, 7, 14),
                doi="10.1103/j9ly-b6q3",
                journal=journal,
            ),
            journal,
        )
        formal_crossref_raw = crossref_item(
            formal=True,
            published=(2026, 8, 3),
            doi="10.1103/revmodphys.98.031001",
            journal=journal,
        )
        formal_crossref_raw.update(
            {"volume": "98", "issue": "3", "article-number": "031001"}
        )
        formal = normalize_crossref_item(formal_crossref_raw, journal)
        openalex_accepted = normalize_openalex_item(
            openalex_item(
                formal=False,
                published="2026-07-14",
                doi="10.1103/j9ly-b6q3",
                journal=journal,
            ),
            journal,
        )

        self.assertTrue(is_aps_lifecycle_journal(journal))
        self.assertEqual(accepted["publisher_section"], "accepted")
        self.assertFalse(accepted["section_allowed"])
        self.assertEqual(openalex_accepted["publisher_section"], "accepted")
        self.assertFalse(openalex_accepted["section_allowed"])
        self.assertEqual(formal["publisher_section"], "published")
        self.assertTrue(formal["section_allowed"])

    def test_openalex_prx_status_and_dedup_prefer_formal_version(self) -> None:
        accepted = normalize_crossref_item(
            crossref_item(
                formal=False,
                published=(2026, 6, 20),
                doi="10.1103/g565-3dyn",
                journal="Physical Review X",
            ),
            "Physical Review X",
        )
        formal = normalize_openalex_item(
            openalex_item(formal=True, published="2026-07-14"),
            "Physical Review X",
        )
        openalex_accepted = normalize_openalex_item(
            openalex_item(formal=False, published="2026-07-08", doi="10.1103/cbrd-ssnm"),
            "Physical Review X",
        )

        merged = dedup_by_id([accepted, formal])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["publisher_section"], "published")
        self.assertTrue(merged[0]["section_allowed"])
        self.assertEqual(merged[0]["publication_date"], "2026-07-14")
        self.assertEqual(merged[0]["source"], "crossref+openalex")
        self.assertEqual(openalex_accepted["publisher_section"], "accepted")
        self.assertFalse(openalex_accepted["section_allowed"])

    def test_science_title_heuristics_do_not_hide_formal_aps_research(self) -> None:
        formal = normalize_crossref_item(
            {
                **crossref_item(
                    formal=True,
                    published=(2026, 5, 22),
                    doi="10.1103/nvbm-97vs",
                    journal="Physical Review X",
                ),
                "title": ["Passive quantum error correction of photon loss at breakeven"],
            },
            "Physical Review X",
        )
        journal = JournalConfig(
            name="Physical Review X",
            issns=["2160-3308"],
            openalex_source_id="S137042341",
            section_policy="science",
            skip_landing_enrichment=True,
        )

        apply_fast_section_hints(formal, journal)

        self.assertEqual(formal["publisher_section"], "published")
        self.assertTrue(formal["section_allowed"])

    def test_skip_landing_enrichment_never_fetches_science_article_pages(self) -> None:
        journal = JournalConfig(
            name="Science",
            issns=["0036-8075"],
            openalex_source_id=None,
            section_policy="science",
            skip_landing_enrichment=True,
        )
        config = AppConfig(
            fetch_lookback_days=2,
            report_days=2,
            keep_unknown_sections=True,
            journals=[journal],
            section_policies={"science": {}},
        )
        paper = normalize_crossref_item(
            {
                "DOI": "10.1126/science.example",
                "URL": "https://www.science.org/doi/10.1126/science.example",
                "title": ["A condensed-matter research result"],
                "container-title": ["Science"],
                "published-online": {"date-parts": [[2026, 8, 11]]},
                "type": "journal-article",
            },
            "Science",
        )
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "papers.sqlite")
            try:
                with patch("paper_monitor.monitor.fetch_crossref_journal", return_value=[paper]), patch(
                    "paper_monitor.monitor.enrich_from_landing_page"
                ) as landing_fetch:
                    result = fetch_one_journal(
                        config=config,
                        storage=storage,
                        journal=journal,
                        start_date=date(2026, 8, 11),
                        end_date=date(2026, 8, 11),
                        enrich=True,
                    )
                landing_fetch.assert_not_called()
                self.assertEqual(result["saved"], 1)
            finally:
                storage.close()

    def test_formal_record_replaces_same_doi_accepted_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "papers.sqlite")
            accepted = normalize_crossref_item(
                crossref_item(formal=False, published=(2026, 6, 8)),
                "Physical Review Letters",
            )
            storage.upsert_paper(accepted)
            storage.update_download_status(
                accepted["paper_id"],
                status="success",
                main_pdf_path="data/pdfs/existing.pdf",
            )

            formal = normalize_crossref_item(
                crossref_item(formal=True, published=(2026, 7, 13)),
                "Physical Review Letters",
            )
            storage.upsert_paper(formal, replace_bibliographic_metadata=True)
            updated = storage.get_paper(accepted["paper_id"])

            self.assertIsNotNone(updated)
            self.assertEqual(updated["publication_date"], "2026-07-13")
            self.assertEqual(updated["publisher_section"], "published")
            self.assertEqual(updated["section_allowed"], 1)
            self.assertEqual(updated["download_status"], "success")
            self.assertEqual(updated["main_pdf_path"], "data/pdfs/existing.pdf")
            raw = json.loads(updated["raw_json"])
            self.assertEqual(raw["volume"], "137")
            self.assertEqual(raw["issue"], "3")
            self.assertEqual(raw["article-number"], "030801")
            storage.close()

    def test_opening_legacy_database_hides_accepted_prl_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "papers.sqlite"
            storage = Storage(path)
            accepted = normalize_crossref_item(
                crossref_item(formal=False, published=(2026, 6, 8)),
                "Physical Review Letters",
            )
            storage.upsert_paper(accepted)
            storage.conn.execute(
                "UPDATE papers SET publisher_section = 'research article', section_allowed = 1 WHERE paper_id = ?",
                (accepted["paper_id"],),
            )
            storage.conn.commit()
            storage.close()

            reopened = Storage(path)
            migrated = reopened.get_paper(accepted["paper_id"])
            self.assertEqual(migrated["publisher_section"], "accepted")
            self.assertEqual(migrated["section_allowed"], 0)
            reopened.close()

    def test_opening_legacy_database_hides_accepted_prx_rows(self) -> None:
        self.assertTrue(is_aps_lifecycle_journal("Physical Review X"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "papers.sqlite"
            storage = Storage(path)
            accepted = normalize_crossref_item(
                crossref_item(
                    formal=False,
                    published=(2026, 7, 8),
                    doi="10.1103/cbrd-ssnm",
                    journal="Physical Review X",
                ),
                "Physical Review X",
            )
            storage.upsert_paper(accepted)
            storage.conn.execute(
                "UPDATE papers SET publisher_section = 'research article', section_allowed = 1 WHERE paper_id = ?",
                (accepted["paper_id"],),
            )
            storage.conn.commit()
            storage.close()

            reopened = Storage(path)
            migrated = reopened.get_paper(accepted["paper_id"])
            self.assertEqual(migrated["publisher_section"], "accepted")
            self.assertEqual(migrated["section_allowed"], 0)
            reopened.close()

    def test_opening_legacy_database_hides_openalex_only_accepted_rmp_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "papers.sqlite"
            storage = Storage(path)
            accepted = normalize_openalex_item(
                openalex_item(
                    formal=False,
                    published="2026-07-14",
                    doi="10.1103/j9ly-b6q3",
                    journal="Reviews of Modern Physics",
                ),
                "Reviews of Modern Physics",
            )
            storage.upsert_paper(accepted)
            storage.conn.execute(
                """
                UPDATE papers
                SET publisher_section = 'research article', section_allowed = 1
                WHERE paper_id = ?
                """,
                (accepted["paper_id"],),
            )
            storage.conn.commit()
            storage.close()

            reopened = Storage(path)
            migrated = reopened.get_paper(accepted["paper_id"])
            self.assertEqual(migrated["publisher_section"], "accepted")
            self.assertEqual(migrated["section_allowed"], 0)
            reopened.close()


if __name__ == "__main__":
    unittest.main()
