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
