import json
import unittest

from paper_monitor import ai_writes, ui_server as ui
from paper_monitor.paper_website import save_website_url, website_url
from tests import test_paper_resources as fixtures


class PaperWebsiteTests(unittest.TestCase):
    setUp = fixtures.PaperResourceStorageTests.setUp
    tearDown = fixtures.PaperResourceStorageTests.tearDown
    add_paper = fixtures.PaperResourceStorageTests.add_paper

    def test_metadata_api_is_evidence_and_doi_is_website(self):
        source = 'https://api.crossref.org/works/10.1103/physrevb.80.174420'
        payload = ai_writes.metadata_payload({'doi': '10.1103/physrevb.80.174420',
            'source_url': source, 'title': 'A paper'}, 'test', {'id': 1})
        self.assertEqual(payload['raw']['ai_metadata']['source_url'], source)
        self.assertEqual(payload['url'], 'https://doi.org/10.1103/physrevb.80.174420')
        legacy = {**payload, 'url': source, 'landing_url': source}
        self.assertEqual(ui.paper_to_api(legacy)['url'], payload['url'])
        self.assertEqual(legacy['url'], source)

    def test_publisher_urls_remain_unchanged_and_missing_url_uses_identifier(self):
        paper = {'doi': '10.1234/test', 'url': 'https://example.org/paper', 'raw': {}}
        self.assertEqual(website_url(paper), paper['url'])
        self.assertEqual(website_url({**paper, 'url': ''}), 'https://doi.org/10.1234/test')
        self.assertEqual(website_url({'doi': '10.1234/test', 'raw_json': 'invalid'}), 'https://doi.org/10.1234/test')
        self.assertEqual(website_url({'raw': {'arxiv_id': '1111.4815'}}), 'https://arxiv.org/abs/1111.4815')

    def test_manual_link_survives_refresh_and_automatic_reset(self):
        self.add_paper('manual')
        before = self.storage.get_paper('manual')
        saved = save_website_url(self.storage, 'manual', 'https://example.org/manual')
        refreshed = self.storage.refresh_paper_metadata('manual', {
            'title': before['title'], 'url': 'https://example.org/automatic', 'raw': {'volume': '12'}})
        self.assertEqual(ui.paper_to_api(refreshed)['url'], 'https://example.org/manual')
        self.assertEqual(saved['storage_key'], before['storage_key'])
        reset = save_website_url(self.storage, 'manual', '')
        self.assertEqual(ui.paper_to_api(reset)['url'], 'https://example.org/automatic')
        # A response begun before reset cannot reintroduce the old override.
        late = self.storage.refresh_paper_metadata('manual', {'title': before['title'],
            'raw': json.loads(saved['raw_json']), 'url': 'https://example.org/automatic'})
        self.assertEqual(ui.paper_to_api(late)['url'], 'https://example.org/automatic')

    def test_invalid_links_do_not_change_saved_record(self):
        self.add_paper('invalid')
        before = self.storage.get_paper('invalid')
        for url in ('javascript:alert(1)', 'file:///tmp/a', 'https://u:p@example.org',
                    'https://api.crossref.org/works/10.1234/test', 'https://example.org/a b'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                save_website_url(self.storage, 'invalid', url)
        self.assertEqual(self.storage.get_paper('invalid'), before)


if __name__ == '__main__':
    unittest.main()
