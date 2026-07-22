import unittest

from paper_monitor.ui_server import INDEX_HTML


class MyPublicationAuthorScrollTests(unittest.TestCase):
    def test_author_mark_update_preserves_loaded_detail_and_scroll_position(self):
        update = INDEX_HTML.split("async function updateSelectedMyPublicationAuthorMark", 1)[1].split(
            "async function deleteMyPublication", 1
        )[0]

        self.assertIn('const detailScrollTop = detailRoot?.scrollTop || 0;', update)
        self.assertIn('const cachedPaperDetail = publication?.paper?.full_detail ? publication.paper : null;', update)
        self.assertIn('updatedPublication.paper = {...(updatedPublication.paper || {}), ...cachedPaperDetail, full_detail: true};', update)
        self.assertIn('renderMyPublications({detailScrollTop});', update)
        self.assertIn('window.requestAnimationFrame(() =>', update)
        self.assertIn('restoredDetail.scrollTop = detailScrollTop', update)


if __name__ == "__main__":
    unittest.main()
