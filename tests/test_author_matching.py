import unittest

from paper_monitor.ui_server import author_matches_name


class AuthorMatchingTest(unittest.TestCase):
    def test_chinese_author_matches_english_pinyin_name(self):
        self.assertTrue(author_matches_name("孔令元", "Lingyuan Kong"))
        self.assertTrue(author_matches_name("孔令元", "Kong Lingyuan"))
        self.assertTrue(author_matches_name("丁洪", "Hong Ding"))
        self.assertTrue(author_matches_name("Jun 钧 Hou 侯", "Jun Hou"))

    def test_generic_chinese_author_words_do_not_match(self):
        self.assertFalse(author_matches_name("作者", "Zhe Zuo"))


if __name__ == "__main__":
    unittest.main()
