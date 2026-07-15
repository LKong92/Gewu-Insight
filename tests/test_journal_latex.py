from __future__ import annotations

import unittest

from paper_monitor.ui_server import INDEX_HTML


class JournalLatexRenderingTests(unittest.TestCase):
    def test_report_title_and_abstract_use_safe_inline_latex_renderer(self) -> None:
        self.assertIn("katex@0.16.11/dist/katex.min.css", INDEX_HTML)
        self.assertIn("katex@0.16.11/dist/katex.min.js", INDEX_HTML)
        head = INDEX_HTML.split("<style>", 1)[0]
        self.assertNotIn("katex@", head)
        self.assertIn("requestKatexForPapers(activePapers)", INDEX_HTML)
        self.assertIn('document.createElement("link")', INDEX_HTML)
        self.assertIn('document.createElement("script")', INDEX_HTML)
        self.assertIn('window.dispatchEvent(new Event("katex-ready"))', INDEX_HTML)
        self.assertIn('window.addEventListener("katex-ready"', INDEX_HTML)
        self.assertIn(
            'inlineLatexMarkup(paper.title || "(Untitled)", publicationTitleMarkup)',
            INDEX_HTML,
        )
        self.assertIn(
            'inlineLatexMarkup(paper.abstract || "No abstract available.")',
            INDEX_HTML,
        )
        self.assertIn("window.katex.renderToString", INDEX_HTML)
        self.assertIn("trust: false", INDEX_HTML)
        self.assertIn('text[cursor] === "\\\\"', INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
