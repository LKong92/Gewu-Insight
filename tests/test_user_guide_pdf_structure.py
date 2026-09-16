from __future__ import annotations

import importlib.util
from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts" / "build_user_guide_pdf.py"


def _builder_module():
    spec = importlib.util.spec_from_file_location("build_user_guide_pdf", BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _headings_between(part_heading, next_part_heading):
    headings = []
    node = part_heading.find_next_sibling()
    while node is not None and (next_part_heading is None or node is not next_part_heading):
        if getattr(node, "name", None) in {"h2", "h3", "h4"}:
            headings.append((node.name, node.get_text(" ", strip=True)))
        else:
            for heading in getattr(node, "find_all", lambda *_args, **_kwargs: [])(
                ["h2", "h3", "h4"]
            ):
                headings.append((heading.name, heading.get_text(" ", strip=True)))
        node = node.find_next_sibling()
    return headings


def test_pdf_html_uses_part_local_chapter_hierarchy():
    builder = _builder_module()
    soup = BeautifulSoup(builder.clean_guide_html(), "html.parser")
    parts = soup.find_all("h1")
    by_name = {part.get_text(" ", strip=True): part for part in parts}

    orientation = _headings_between(by_name["Orientation"], by_name["Product Concepts and Architecture"])
    assert [text for level, text in orientation if level == "h2"][:3] == [
        "Welcome",
        "Guided Tour",
        "Your First Session",
    ]
    assert not any(text == "Start Here" for _level, text in orientation)

    concepts = _headings_between(by_name["Product Concepts and Architecture"], by_name["User Manual"])
    assert [text for level, text in concepts if level == "h2"][:2] == [
        "System Architecture at a Glance",
        "The Persistent Paper Object",
    ]
    assert not any(text == "Understand the System" for _level, text in concepts)

    manual = _headings_between(by_name["User Manual"], by_name["Product Identity"])
    assert [text for level, text in manual if level == "h2"][:3] == [
        "Workspace Navigation",
        "Papers and Files",
        "Import and Transfer",
    ]
    assert ("h3", "Library Layout") in manual
    assert ("h3", "Add Papers and Files") in manual
    assert ("h2", "Browser") in manual
    assert ("h3", "Browse, Bookmark, and Revisit Websites") in manual

    identity = _headings_between(by_name["Product Identity"], by_name["Technical and Operational Reference"])
    assert [text for level, text in identity if level == "h2"][:4] == [
        "Visual Identity and Cultural Elements",
        "The calligraphic name",
        "The app icon and the seal-script watermark",
        "Why the three marks are used differently",
    ]

    reference = _headings_between(by_name["Technical and Operational Reference"], None)
    assert [text for level, text in reference if level == "h2"][:3] == [
        "Keyboard Shortcuts",
        "Publisher and Network Access",
        "Startup, Monitor Cache, and Text Size",
    ]
    assert not any(text == "Reference" for _level, text in reference)


def test_pdf_preamble_numbers_chapters_within_each_part():
    builder = _builder_module()
    preamble = builder.latex_preamble("0.1", "test")
    assert r"\setcounter{secnumdepth}{1}" in preamble
    assert r"\setcounter{tocdepth}{1}" in preamble
    assert r"\@addtoreset{chapter}{part}" in preamble
    assert r"\renewcommand{\thechapter}{\arabic{part}-\arabic{chapter}}" in preamble


def test_product_identity_chapters_flow_without_changing_other_parts():
    builder = _builder_module()
    identity_titles = ["Visual Identity and Cultural Elements", "The calligraphic name",
                       "The app icon and the seal-script watermark", "Why the three marks are used differently"]
    identity = "\n".join(r"\chapter{" + title + r"}\label{identity-" + str(i) + "}\nBody."
                         for i, title in enumerate(identity_titles, 1))
    before = r"\part{User Manual}\label{part-3}\chapter{Browser}\label{browser}"
    after = r"\part{Technical and Operational Reference}\label{part-5}\chapter{Keyboard Shortcuts}"
    result = builder.prepare_latex_body(before + r"\part{Product Identity}\label{part-4}" + identity + after)
    assert before in result and after in result
    assert result.count(r"\GewuIdentityChapter{") == 4
    for i, title in enumerate(identity_titles, 1):
        assert r"\GewuIdentityChapter{" + title + r"}\label{identity-" + str(i) + "}" in result
    assert builder.prepare_latex_body(result) == result


def test_identity_chapter_break_suppression_is_local_and_keeps_chapter_semantics():
    preamble = _builder_module().latex_preamble("0.1", "test")
    start = preamble.index(r"\newcommand{\GewuIdentityChapter}")
    command = preamble[start:preamble.index(r"\raggedbottom", start)]
    assert r"\Needspace{13\baselineskip}" in command
    assert command.index(r"\let\GewuSavedClearPage\clearpage") < command.index(r"\let\clearpage\relax")
    assert command.index(r"\let\GewuSavedClearDoublePage\cleardoublepage") < command.index(r"\let\cleardoublepage\relax")
    assert command.index(r"\chapter{#1}") < command.index(r"\let\clearpage\GewuSavedClearPage")
    assert command.index(r"\chapter{#1}") < command.index(r"\let\cleardoublepage\GewuSavedClearDoublePage")
    # A group around chapter would lose currentlabel/currentHref before the
    # following Pandoc label, silently sending cross-references to the old part.
    assert r"\begingroup" not in command


def test_every_registered_screenshot_is_constrained_to_page_width_and_height():
    builder = _builder_module()
    for route, path in builder.IMAGE_ROUTES.items():
        if not route.startswith('/user-guide-assets/'):
            continue
        source = r'\pandocbounded{\includegraphics[keepaspectratio,alt={Screenshot}]{' + str(path) + '}}'
        result = builder.prepare_latex_body(source)
        width = '0.48' if path.name == 'about-window.png' else '0.96'
        assert r'\includegraphics[width=' + width + r'\linewidth,height=0.72\textheight,keepaspectratio]' in result
        assert r'\pandocbounded' not in result


def test_related_links_are_preserved_without_numbered_see_also_sections():
    builder = _builder_module()
    original = BeautifulSoup(builder.HTML_SOURCE.read_text(), "html.parser")
    cleaned = BeautifulSoup(builder.clean_guide_html(), "html.parser")
    assert not any(h.get_text(" ", strip=True).casefold() == "see also"
                   for h in cleaned.find_all(["h1", "h2", "h3", "h4", "h5"]))
    paragraphs = [p for p in cleaned.find_all("p") if "GEWURELATEDSTART" in p.get_text()]
    assert len(paragraphs) == len(original.select(".see-also"))
    assert [a["href"] for p in paragraphs for a in p.find_all("a")] == [
        a["href"] for a in original.select(".see-also .see-links a")]
    source = builder.prepare_latex_body("GEWURELATEDSTARTlinksGEWURELATEDEND")
    assert r"\begin{GewuRelated}" in source
    assert r"\end{GewuRelated}" in source
    assert "GEWURELATED" not in source
    preamble = builder.latex_preamble("0.1", "test")
    assert r"\par\nobreak\vspace{3pt}\nobreak" in preamble
    assert r"\Needspace{9\baselineskip}" in preamble
