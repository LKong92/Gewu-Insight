import json
import unittest

from paper_monitor.ui_server import (
    INDEX_HTML,
    MY_PUBLICATIONS_SCHOLAR_PROFILE_SETTING,
    effective_my_publication_name,
)


class FakeSettings:
    def __init__(self, values):
        self.values = values

    def get_setting(self, key, default=""):
        return self.values.get(key, default)


class MyPublicationIdentityTests(unittest.TestCase):
    def test_saved_name_takes_priority_over_scholar_profile(self):
        settings = FakeSettings({
            "my_publications_name": "L. Kong",
            MY_PUBLICATIONS_SCHOLAR_PROFILE_SETTING: json.dumps({"name": "Lingyuan Kong"}),
        })

        self.assertEqual(effective_my_publication_name(settings), "L. Kong")

    def test_scholar_profile_name_is_used_when_saved_name_is_blank(self):
        settings = FakeSettings({
            "my_publications_name": "",
            MY_PUBLICATIONS_SCHOLAR_PROFILE_SETTING: json.dumps({"name": "Lingyuan Kong"}),
        })

        self.assertEqual(effective_my_publication_name(settings), "Lingyuan Kong")

    def test_scholar_profile_name_is_used_when_saved_name_is_a_scholar_url(self):
        settings = FakeSettings({
            "my_publications_name": "https://scholar.google.com/citations?user=5uWv_XgAAAAJ&hl=en",
            MY_PUBLICATIONS_SCHOLAR_PROFILE_SETTING: json.dumps({"name": "Lingyuan Kong"}),
        })

        self.assertEqual(effective_my_publication_name(settings), "Lingyuan Kong")

    def test_browser_matching_uses_scholar_profile_as_fallback(self):
        self.assertIn(
            'const profileName = state.myPublicationScholarProfile?.name || "";',
            INDEX_HTML,
        )
        self.assertIn('usableInputValue || state.myPublicationName || profileName', INDEX_HTML)

    def test_browser_does_not_treat_a_scholar_url_as_the_author_name(self):
        self.assertIn(
            'const usableInputValue = myPublicationQueryIsScholarUrl(inputValue) ? "" : inputValue;',
            INDEX_HTML,
        )
        self.assertIn(
            'if (myPublicationQueryIsScholarUrl(value)) return state.myPublicationName || "";',
            INDEX_HTML,
        )

    def test_browser_matching_reaches_chinese_name_signatures(self):
        function_body = INDEX_HTML.split("function authorNameSignatures", 1)[1].split(
            "const CHINESE_PINYIN", 1
        )[0]

        self.assertNotIn("if (!parts.length) return [];", function_body)
        self.assertIn("addChineseAuthorSignatures(value, addVariant);", function_body)


if __name__ == "__main__":
    unittest.main()
