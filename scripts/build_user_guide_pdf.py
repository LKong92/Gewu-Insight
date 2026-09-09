#!/usr/bin/env python3
"""Build the fixed-layout Gewu Insight manual from the in-app User Guide.

The HTML guide remains the interactive, searchable source.  This builder
extracts the same topics, converts their semantic content to LaTeX with
Pandoc, and compiles a publication-quality PDF with XeLaTeX.
"""

from __future__ import annotations

import argparse
import plistlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag


ROOT = Path(__file__).resolve().parents[1]
HTML_SOURCE = ROOT / "paper_monitor" / "user_guide.html"
TEX_OUTPUT = ROOT / "paper_monitor" / "user_guide.tex"
PDF_OUTPUT = ROOT / "paper_monitor" / "Gewu_Insight_User_Guide.pdf"
INFO_PLIST = ROOT / "Gewu Insight.app" / "Contents" / "Info.plist"

IMAGE_ROUTES = {
    "/api/about-calligraphy": ROOT / "assets" / "branding" / "GewuAboutCalligraphy.png",
    "/api/app-icon": ROOT / "assets" / "gewu-insight-app-icon.png",
    "/api/startup-brand-art": ROOT / "assets" / "branding" / "GewuSealGlyphs.png",
    "/user-guide-assets/library-paper-files.png": ROOT / "assets" / "user-guide" / "screenshots" / "library-paper-files.png",
    "/user-guide-assets/space-workspace.png": ROOT / "assets" / "user-guide" / "screenshots" / "space-workspace.png",
    "/user-guide-assets/my-publications.png": ROOT / "assets" / "user-guide" / "screenshots" / "my-publications.png",
    "/user-guide-assets/journal-monitor.png": ROOT / "assets" / "user-guide" / "screenshots" / "journal-monitor.png",
    "/user-guide-assets/subject-monitor.png": ROOT / "assets" / "user-guide" / "screenshots" / "subject-monitor.png",
    "/user-guide-assets/author-monitor.png": ROOT / "assets" / "user-guide" / "screenshots" / "author-monitor.png",
    "/user-guide-assets/browser.png": ROOT / "assets" / "user-guide" / "screenshots" / "browser.png",
    "/user-guide-assets/open-source.png": ROOT / "assets" / "user-guide" / "screenshots" / "open-source.png",
    "/user-guide-assets/arxiv-scope.png": ROOT / "assets" / "user-guide" / "screenshots" / "arxiv-scope.png",
    "/user-guide-assets/field-settings.png": ROOT / "assets" / "user-guide" / "screenshots" / "field-settings.png",
    "/user-guide-assets/quick-look-settings.png": ROOT / "assets" / "user-guide" / "screenshots" / "quick-look-settings.png",
    "/user-guide-assets/website-links.png": ROOT / "assets" / "user-guide" / "screenshots" / "website-links.png",
    "/user-guide-assets/ai-access.png": ROOT / "assets" / "user-guide" / "screenshots" / "ai-access.png",
    "/user-guide-assets/ai-new-connection.png": ROOT / "assets" / "user-guide" / "screenshots" / "ai-new-connection.png",
    "/user-guide-assets/pdf-rename-settings.png": ROOT / "assets" / "user-guide" / "screenshots" / "pdf-rename-settings.png",
    "/user-guide-assets/font-size.png": ROOT / "assets" / "user-guide" / "screenshots" / "font-size.png",
    "/user-guide-assets/folder-loader.png": ROOT / "assets" / "user-guide" / "screenshots" / "folder-loader.png",
    "/user-guide-assets/loader-metadata.png": ROOT / "assets" / "user-guide" / "screenshots" / "loader-metadata.png",
    "/user-guide-assets/loader-identifiers.png": ROOT / "assets" / "user-guide" / "screenshots" / "loader-identifiers.png",
    "/user-guide-assets/browser-home.png": ROOT / "assets" / "user-guide" / "screenshots" / "browser-home.png",
    "/user-guide-assets/save-gewu-compact.png": ROOT / "assets" / "user-guide" / "screenshots" / "save-gewu-compact.png",
    "/user-guide-assets/save-gewu-details.png": ROOT / "assets" / "user-guide" / "screenshots" / "save-gewu-details.png",
    "/user-guide-assets/library-destination-picker.png": ROOT / "assets" / "user-guide" / "screenshots" / "library-destination-picker.png",
    "/user-guide-assets/subject-editor.png": ROOT / "assets" / "user-guide" / "screenshots" / "subject-editor.png",
    "/user-guide-assets/add-shortcut.png": ROOT / "assets" / "user-guide" / "screenshots" / "add-shortcut.png",
    "/user-guide-assets/add-space.png": ROOT / "assets" / "user-guide" / "screenshots" / "add-space.png",
    "/user-guide-assets/library-search.png": ROOT / "assets" / "user-guide" / "screenshots" / "library-search.png",
    "/user-guide-assets/pdf-quick-look.png": ROOT / "assets" / "user-guide" / "screenshots" / "pdf-quick-look.png",
    "/user-guide-assets/markdown-quick-look.png": ROOT / "assets" / "user-guide" / "screenshots" / "markdown-quick-look.png",
    "/user-guide-assets/author-add.png": ROOT / "assets" / "user-guide" / "screenshots" / "author-add.png",
    "/user-guide-assets/about-window.png": ROOT / "assets" / "user-guide" / "screenshots" / "about-window.png",
    "/user-guide-assets/user-guide-window.png": ROOT / "assets" / "user-guide" / "screenshots" / "user-guide-window.png",
}

PART_BY_GROUP = {
    "Start Here": "Orientation",
    "Understand the System": "Product Concepts and Architecture",
    "Workspace Navigation": "User Manual",
    "Papers and Files": "User Manual",
    "Import and Transfer": "User Manual",
    "My Publications": "User Manual",
    "Journal Monitor": "User Manual",
    "Subject Monitor": "User Manual",
    "Author Monitor": "User Manual",
    "Browser": "User Manual",
    "Settings and Safety": "User Manual",
    "About Gewu Insight": "Product Identity",
    "Reference": "Technical and Operational Reference",
}

# The PDF deliberately has two complementary hierarchy patterns:
#
# * Parts I, II, IV, and V promote each top-level guide topic to a numbered
#   chapter (1-1, 2-1, 4-1, 5-1, ...).  Their internal headings become
#   sections (1-1.1, 2-1.1, ...).
# * Part III is the operational manual.  Its functional groups are numbered
#   chapters (3-1, 3-2, ...), and the individual guide topics inside each
#   group are numbered sections (3-1.1, 3-1.2, ...).
#
# Keep these rules here, rather than repairing the generated TeX by hand, so
# every future PDF rebuild preserves the same document logic.
# Product Identity keeps its 4-1 ... chapter numbering but flows continuously;
# its short chapters must not each force a new page (user layout rule).
TOPIC_AS_CHAPTER_GROUPS = {"Start Here", "Understand the System", "Reference"}
SPLIT_TOPIC_HEADING_GROUPS = {"About Gewu Insight"}


def app_version() -> tuple[str, str]:
    try:
        with INFO_PLIST.open("rb") as handle:
            values = plistlib.load(handle)
    except OSError:
        return "0.1", "development"
    return (
        str(values.get("CFBundleShortVersionString") or "0.1"),
        str(values.get("CFBundleVersion") or "development"),
    )


def _new_tag(soup: BeautifulSoup, name: str, text: str | None = None, **attrs: str) -> Tag:
    tag = soup.new_tag(name, **attrs)
    if text is not None:
        tag.string = text
    return tag


def _retarget_copied_headings(root: Tag, *, mode: str) -> None:
    headings: list[Tag] = []
    if root.name in {"h2", "h3", "h4", "h5", "h6"}:
        headings.append(root)
    headings.extend(root.find_all(["h2", "h3", "h4", "h5", "h6"]))

    for heading in headings:
        original = heading.name
        if mode == "topic-chapter":
            levels = {"h2": "h3", "h3": "h4", "h4": "h5", "h5": "h6"}
            heading.name = levels.get(original, original)
        elif mode == "manual-group":
            levels = {"h2": "h4", "h3": "h5", "h4": "h6"}
            heading.name = levels.get(original, original)
        elif mode == "split-topic":
            # The visual-identity article contains several genuine chapter
            # subjects in one in-app topic.  Preserve those h2 headings as
            # chapters, while keeping its final See also block subordinate.
            if original == "h2" and heading.get_text(" ", strip=True).casefold() == "see also":
                heading.name = "h3"


def _append_children(target: Tag, source: Tag) -> None:
    for child in list(source.contents):
        target.append(child.extract() if isinstance(child, Tag) else str(child))


def _semantic_table(
    soup: BeautifulSoup,
    headings: tuple[str, str],
    rows: list[tuple[Tag | str, Tag | str]],
) -> Tag:
    table = _new_tag(soup, "table")
    header = _new_tag(soup, "tr")
    for heading in headings:
        header.append(_new_tag(soup, "th", heading))
    table.append(header)
    for left, right in rows:
        row = _new_tag(soup, "tr")
        left_cell = _new_tag(soup, "td")
        right_cell = _new_tag(soup, "td")
        left_cell.append(left if isinstance(left, Tag) else str(left))
        right_cell.append(right if isinstance(right, Tag) else str(right))
        row.append(left_cell)
        row.append(right_cell)
        table.append(row)
    return table


def clean_guide_html() -> str:
    source = BeautifulSoup(HTML_SOURCE.read_text(encoding="utf-8"), "html.parser")
    output = BeautifulSoup("<!doctype html><html><head><meta charset='utf-8'></head><body></body></html>", "html.parser")
    body = output.body
    assert body is not None

    current_part: str | None = None
    current_group: str | None = None
    for article in source.select("article.guide-topic"):
        group = str(article.get("data-group") or "User Guide")
        part = PART_BY_GROUP.get(group, "User Manual")
        title = str(article.get("data-title") or article.get("id") or "Topic")
        if part != current_part:
            body.append(_new_tag(output, "h1", part, id=f"part-{len(body.find_all('h1')) + 1}"))
            current_part = part
            current_group = None
        if group in TOPIC_AS_CHAPTER_GROUPS:
            mode = "topic-chapter"
        elif group in SPLIT_TOPIC_HEADING_GROUPS:
            mode = "split-topic"
        else:
            mode = "manual-group"
            if group != current_group:
                body.append(_new_tag(output, "h2", group, id=f"chapter-{len(body.find_all('h2')) + 1}"))
        current_group = group

        topic_id = str(article.get("id") or "topic")
        section = _new_tag(output, "section")
        topic_heading = "h2" if mode in {"topic-chapter", "split-topic"} else "h3"
        section.append(_new_tag(output, topic_heading, title, id=topic_id))
        for child in list(article.children):
            if isinstance(child, NavigableString):
                if child.strip():
                    section.append(str(child))
                continue
            if not isinstance(child, Tag):
                continue
            classes = set(child.get("class") or [])
            if "topic-kicker" in classes or child.name == "h1":
                continue
            clone = BeautifulSoup(str(child), "html.parser").find()
            if clone is None:
                continue
            _retarget_copied_headings(clone, mode=mode)
            section.append(clone)
        body.append(section)

    for lead in body.select("p.lead"):
        lead.string = f"GEWULEADSTART{lead.get_text(' ', strip=True)}GEWULEADEND"

    for callout in body.select("div.note, div.important, div.credo"):
        quote = _new_tag(output, "blockquote")
        callout_title = callout.select_one(".callout-title")
        if callout_title is not None:
            title_paragraph = _new_tag(output, "p")
            title_strong = _new_tag(output, "strong", callout_title.get_text(" ", strip=True))
            title_paragraph.append(title_strong)
            quote.append(title_paragraph)
            callout_title.extract()
        for child in list(callout.contents):
            quote.append(child.extract() if isinstance(child, Tag) else str(child))
        callout.replace_with(quote)

    for ui_label in body.select("span.ui"):
        ui_label.name = "strong"

    for path_list in body.select("ul.path-list"):
        rows: list[tuple[Tag | str, Tag | str]] = []
        for item in path_list.find_all("li", recursive=False):
            key = item.find("code", recursive=False)
            value = item.find("span", recursive=False)
            if key is None or value is None:
                continue
            detail = _new_tag(output, "span")
            _append_children(detail, value)
            rows.append((key.extract(), detail))
        path_list.replace_with(_semantic_table(output, ("Location", "Purpose"), rows))

    for invariant_list in body.select("div.invariant-list"):
        rows = []
        for item in invariant_list.find_all("div", recursive=False):
            title = item.find("strong", recursive=False)
            description = item.find("span", recursive=False)
            if title is None or description is None:
                continue
            detail = _new_tag(output, "span")
            _append_children(detail, description)
            rows.append((title.extract(), detail))
        invariant_list.replace_with(_semantic_table(output, ("Principle", "What it means"), rows))

    for interface_map in body.select("div.interface-map"):
        rows = []
        for item in interface_map.find_all("div", recursive=False):
            title = item.find("strong", recursive=False)
            description = item.find("span", recursive=False)
            if title is None or description is None:
                continue
            detail = _new_tag(output, "span")
            _append_children(detail, description)
            rows.append((title.extract(), detail))
        interface_map.replace_with(_semantic_table(output, ("Area", "Purpose"), rows))

    for diagram in body.select("figure.architecture-map"):
        rows = []
        for node in diagram.select(".architecture-node"):
            title = node.find("strong", recursive=False)
            descriptions = node.find_all("span", recursive=False)
            if title is None or not descriptions:
                continue
            description = descriptions[-1]
            label = node.select_one(".sequence-label")
            left = _new_tag(output, "span")
            if label is not None:
                left.append(_new_tag(output, "small", label.get_text(" ", strip=True)))
                left.append(_new_tag(output, "br"))
            left.append(title.extract())
            detail = _new_tag(output, "span")
            _append_children(detail, description)
            rows.append((left, detail))
        replacement = _new_tag(output, "div")
        replacement.append(_semantic_table(output, ("Element", "Role"), rows))
        caption = diagram.find("figcaption")
        if caption is not None:
            caption_paragraph = _new_tag(output, "p")
            caption_paragraph.string = (
                "GEWUCAPTIONSTART" + caption.get_text(" ", strip=True) + "GEWUCAPTIONEND"
            )
            replacement.append(caption_paragraph)
        diagram.replace_with(replacement)

    for equation in body.select("div.architecture-equation"):
        quote = _new_tag(output, "blockquote")
        quote.append(_new_tag(output, "p", "System relationship"))
        quote.append(_new_tag(output, "p", equation.get_text(" ", strip=True)))
        equation.replace_with(quote)

    for figure in body.select("figure.wordmark-figure"):
        replacement = _new_tag(output, "div")
        image = figure.find("img")
        if image is not None:
            image_paragraph = _new_tag(output, "p")
            image_paragraph.append(image.extract())
            replacement.append(image_paragraph)
        caption = figure.find("figcaption")
        if caption is not None:
            caption_paragraph = _new_tag(output, "p")
            caption_paragraph.string = (
                "GEWUCAPTIONSTART" + caption.get_text(" ", strip=True) + "GEWUCAPTIONEND"
            )
            replacement.append(caption_paragraph)
        figure.replace_with(replacement)

    for figure in body.select("figure.guide-screenshot"):
        replacement = _new_tag(output, "div")
        replacement.append(_new_tag(output, "p", "GEWUFIGURESTART"))
        image = figure.find("img")
        if image is not None:
            image_paragraph = _new_tag(output, "p")
            image_paragraph.append(image.extract())
            replacement.append(image_paragraph)
        caption = figure.find("figcaption")
        if caption is not None:
            caption_paragraph = _new_tag(output, "p")
            caption_paragraph.string = (
                "GEWUCAPTIONSTART" + caption.get_text(" ", strip=True) + "GEWUCAPTIONEND"
            )
            replacement.append(caption_paragraph)
        replacement.append(_new_tag(output, "p", "GEWUFIGUREEND"))
        figure.replace_with(replacement)

    for symbol_group in body.select("div.identity-symbols"):
        replacement = _new_tag(output, "div")
        for figure in symbol_group.find_all("figure", recursive=False):
            heading = figure.find(["h3", "h4", "h5"])
            if heading is not None:
                replacement.append(heading.extract())
            image = figure.find("img")
            if image is not None:
                image_paragraph = _new_tag(output, "p")
                image_paragraph.append(image.extract())
                replacement.append(image_paragraph)
            description = figure.find("p")
            if description is not None:
                replacement.append(description.extract())
            caption = figure.find("figcaption")
            if caption is not None:
                caption_paragraph = _new_tag(output, "p")
                caption_paragraph.string = (
                    "GEWUCAPTIONSTART" + caption.get_text(" ", strip=True) + "GEWUCAPTIONEND"
                )
                replacement.append(caption_paragraph)
        symbol_group.replace_with(replacement)

    for identity_rules in body.select("div.identity-rules"):
        rows = []
        for item in identity_rules.find_all("div", recursive=False):
            title = item.find("strong", recursive=False)
            description = item.find("span", recursive=False)
            if title is None or description is None:
                continue
            detail = _new_tag(output, "span")
            _append_children(detail, description)
            rows.append((title.extract(), detail))
        identity_rules.replace_with(_semantic_table(output, ("Mark", "Role"), rows))

    for credo in body.select("div.credo"):
        quote = _new_tag(output, "blockquote")
        quote.append(_new_tag(output, "p", "Design principle"))
        main_text = " ".join(
            part.strip()
            for part in credo.find_all(string=True, recursive=False)
            if part.strip()
        )
        if main_text:
            quote.append(_new_tag(output, "p", main_text))
        translation = credo.find("small")
        if translation is not None:
            translated = _new_tag(output, "p")
            emphasis = _new_tag(output, "em", translation.get_text(" ", strip=True))
            translated.append(emphasis)
            quote.append(translated)
        credo.replace_with(quote)

    for result in body.select("p.result"):
        result.string = f"GEWURESULTSTART{result.get_text(' ', strip=True)}GEWURESULTEND"

    # Related-topic links are navigation, not numbered chapters/TOC entries.
    # Keep them compact and attached to the preceding content in the PDF.
    for related in body.select(".see-also"):
        paragraph = _new_tag(output, "p", "GEWURELATEDSTART")
        paragraph.append(_new_tag(output, "strong", "See also: "))
        for index, link in enumerate(related.select(".see-links a")):
            if index:
                paragraph.append(" · ")
            paragraph.append(link.extract())
        paragraph.append("GEWURELATEDEND")
        related.replace_with(paragraph)

    for image in body.select("img[src]"):
        source_path = IMAGE_ROUTES.get(str(image.get("src")))
        if source_path:
            image["src"] = str(source_path)

    for key in body.select("kbd"):
        key.name = "code"

    for tag in body.find_all(True):
        for attribute in ["class", "style", "lang", "data-group", "data-title", "data-keywords"]:
            tag.attrs.pop(attribute, None)

    return str(output)


def latex_preamble(version: str, build: str) -> str:
    icon = (ROOT / "assets" / "gewu-insight-app-icon.png").as_posix()
    calligraphy = (ROOT / "assets" / "branding" / "GewuAboutCalligraphy.png").as_posix()
    return rf"""\documentclass[10pt,letterpaper,oneside]{{scrreprt}}
\usepackage[letterpaper,top=19mm,bottom=19mm,left=23mm,right=23mm,headsep=5.5mm,footskip=9mm]{{geometry}}
\usepackage{{fontspec}}
\usepackage{{xeCJK}}
\setmainfont{{Palatino}}
\setsansfont{{Avenir Next}}
\setmonofont[Scale=0.82]{{Menlo}}
\setCJKmainfont{{Songti SC}}
\setCJKsansfont{{Hiragino Sans GB}}
\setCJKmonofont{{Songti SC}}
\newfontfamily\symbolfont{{Arial Unicode MS}}
\usepackage{{graphicx}}
\usepackage[table]{{xcolor}}
\usepackage{{booktabs,longtable,array,tabularx,colortbl}}
\usepackage{{calc}}
\usepackage{{enumitem}}
\usepackage{{fancyhdr}}
\usepackage{{microtype}}
\usepackage{{hyperref}}
\usepackage{{bookmark}}
\usepackage{{ragged2e}}
\usepackage{{setspace}}
\usepackage{{needspace}}
\usepackage{{etoolbox}}
\usepackage[most]{{tcolorbox}}

\definecolor{{GewuBlue}}{{HTML}}{{235EA7}}
\definecolor{{GewuInk}}{{HTML}}{{172033}}
\definecolor{{GewuMuted}}{{HTML}}{{68758B}}
\definecolor{{GewuPale}}{{HTML}}{{EDF4FC}}
\definecolor{{GewuRule}}{{HTML}}{{D7E1EC}}
\definecolor{{GewuTableHeader}}{{HTML}}{{E3EEF9}}
\definecolor{{GewuTableStripe}}{{HTML}}{{F5F8FC}}
\definecolor{{GewuSealPanel}}{{HTML}}{{526985}}

\hypersetup{{colorlinks=true,linkcolor=GewuBlue,urlcolor=GewuBlue,citecolor=GewuBlue,pdfauthor={{Lingyuan Kong and Zhengran Wu}},pdftitle={{Gewu Insight User Guide}}}}
\urlstyle{{same}}
\Urlmuskip=0mu plus 1mu
\setlength{{\parindent}}{{0pt}}
\setlength{{\parskip}}{{3pt plus .8pt minus .5pt}}
\setstretch{{1.01}}
\setlist{{topsep=2.5pt,itemsep=1.25pt,parsep=.5pt,leftmargin=5.5mm}}
% Number the reader-facing hierarchy, but stop before implementation-detail
% subsections.  Each part owns its chapter sequence, so the visible chapter
% labels are 1-1, 1-2, 2-1, 3-1, ... instead of one global counter.
\setcounter{{secnumdepth}}{{1}}
\setcounter{{tocdepth}}{{1}}
\makeatletter
\@addtoreset{{chapter}}{{part}}
\makeatother
\renewcommand{{\thechapter}}{{\arabic{{part}}-\arabic{{chapter}}}}
\renewcommand{{\thesection}}{{\thechapter.\arabic{{section}}}}
\renewcommand{{\thesubsection}}{{\thesection.\arabic{{subsection}}}}
\renewcommand{{\arraystretch}}{{1.16}}
\setlength{{\tabcolsep}}{{3.5pt}}
\setlength{{\LTpre}}{{4pt}}
\setlength{{\LTpost}}{{5pt}}
\setlength{{\heavyrulewidth}}{{0.55pt}}
\setlength{{\lightrulewidth}}{{0.3pt}}
\arrayrulecolor{{GewuRule}}
\setlength{{\emergencystretch}}{{3em}}
\hyphenpenalty=10000
\exhyphenpenalty=10000
\widowpenalty=10000
\clubpenalty=10000
\setlength{{\headheight}}{{16pt}}
\providecommand{{\tightlist}}{{\setlength{{\itemsep}}{{1pt}}\setlength{{\parskip}}{{0pt}}}}
\providecommand{{\pandocbounded}}[1]{{#1}}

\setkomafont{{part}}{{\sffamily\bfseries\color{{GewuInk}}\fontsize{{25}}{{29}}\selectfont}}
\setkomafont{{partnumber}}{{\sffamily\bfseries\color{{GewuBlue}}\fontsize{{11}}{{13}}\selectfont}}
\setkomafont{{chapter}}{{\sffamily\bfseries\color{{GewuInk}}\fontsize{{21}}{{24}}\selectfont}}
\setkomafont{{section}}{{\sffamily\bfseries\color{{GewuInk}}\fontsize{{15.5}}{{18.5}}\selectfont}}
\setkomafont{{subsection}}{{\sffamily\bfseries\color{{GewuInk}}\fontsize{{11.8}}{{14}}\selectfont}}
\setkomafont{{subsubsection}}{{\sffamily\bfseries\color{{GewuInk}}\fontsize{{10.5}}{{12.5}}\selectfont}}
\renewcommand*{{\partformat}}{{\partname~\thepart\autodot\enskip}}
\RedeclareSectionCommand[beforeskip=2.1ex plus .4ex minus .2ex,afterskip=.85ex,tocnumwidth=3.8em]{{chapter}}
\RedeclareSectionCommand[beforeskip=1.8ex plus .3ex minus .2ex,afterskip=.48ex,tocnumwidth=5.2em]{{section}}
\RedeclareSectionCommand[beforeskip=1.35ex plus .25ex minus .15ex,afterskip=.3ex]{{subsection}}
\renewcommand*{{\chapterformat}}{{\color{{GewuBlue}}\rule[-2pt]{{1.7mm}}{{23pt}}\hspace{{3mm}}\thechapter\enskip}}
\renewcommand*{{\sectionformat}}{{\thesection\enskip}}
\pretocmd{{\section}}{{\Needspace{{9\baselineskip}}}}{{}}{{}}
\pretocmd{{\subsection}}{{\Needspace{{6\baselineskip}}}}{{}}{{}}
\pretocmd{{\subsubsection}}{{\Needspace{{3\baselineskip}}}}{{}}{{}}
% Product Identity is one continuous reading sequence. Suppress only the
% chapter's forced break locally; normal page overflow, numbering, TOC entries
% and labels are still handled by KOMA-Script. Other parts remain unchanged.
\newcommand{{\GewuIdentityChapter}}[1]{{%
  \par\Needspace{{9\baselineskip}}%
  \let\GewuSavedClearPage\clearpage
  \let\GewuSavedClearDoublePage\cleardoublepage
  \let\clearpage\relax
  \let\cleardoublepage\relax
  \chapter{{#1}}%
  \let\clearpage\GewuSavedClearPage
  \let\cleardoublepage\GewuSavedClearDoublePage
}}
\raggedbottom
\newenvironment{{GewuRelated}}{{\par\nobreak\vspace{{3pt}}\nobreak\begingroup\small\sffamily\begin{{samepage}}\noindent}}{{\par\end{{samepage}}\endgroup}}

\pagestyle{{fancy}}
\fancyhf{{}}
\fancyhead[L]{{\footnotesize\sffamily\bfseries\color{{GewuInk}}Gewu Insight User Guide}}
\fancyhead[R]{{\footnotesize\sffamily\color{{GewuMuted}}\leftmark}}
\fancyfoot[L]{{\footnotesize\sffamily\color{{GewuMuted}}Gewu Insight}}
\fancyfoot[R]{{\footnotesize\sffamily\color{{GewuMuted}}\thepage}}
\renewcommand{{\headrulewidth}}{{0.35pt}}
\renewcommand{{\headrule}}{{\hbox to\headwidth{{\color{{GewuRule}}\leaders\hrule height \headrulewidth\hfill}}}}

\newenvironment{{GewuLead}}
  {{\begin{{list}}{{}}{{\leftmargin=0pt\rightmargin=0pt\topsep=0pt\partopsep=0pt\parsep=0pt}}\item\relax
    \sffamily\fontsize{{10.5}}{{13.2}}\selectfont\color{{GewuMuted}}}}
  {{\end{{list}}}}

\newenvironment{{GewuResult}}
  {{\begin{{tcolorbox}}[enhanced,breakable,colback=GewuPale,colframe=GewuPale,boxrule=0pt,
    borderline west={{1.6pt}}{{0pt}}{{GewuBlue}},arc=1.2mm,left=2.5mm,right=2.5mm,top=1.7mm,bottom=1.7mm,
    before skip=4pt,after skip=5pt,fontupper=\color{{GewuInk}}\small\sffamily]}}
  {{\end{{tcolorbox}}}}

\newenvironment{{GewuCaption}}
  {{\begin{{list}}{{}}{{\leftmargin=2.5mm\rightmargin=2.5mm\topsep=0pt}}\item\relax
    \footnotesize\itshape\color{{GewuMuted}}}}
  {{\end{{list}}}}

\renewenvironment{{quote}}
  {{\begin{{tcolorbox}}[enhanced,breakable,colback=GewuPale,colframe=GewuPale,boxrule=0pt,
    borderline west={{1.6pt}}{{0pt}}{{GewuBlue}},arc=1.2mm,left=2.5mm,right=2.5mm,top=1.7mm,bottom=1.7mm,
    before skip=4pt,after skip=5pt,fontupper=\color{{GewuInk}}\small]}}
  {{\end{{tcolorbox}}}}

\newcommand{{\GewuTableStart}}{{\begingroup\fontsize{{8.6}}{{10.6}}\selectfont\rowcolors{{2}}{{GewuTableStripe}}{{white}}}}
\newcommand{{\GewuTableEnd}}{{\endgroup}}

\begin{{document}}
\begin{{titlepage}}
  \centering
  \vspace*{{25mm}}
  \includegraphics[width=36mm]{{{icon}}}\\[8mm]
  {{\sffamily\bfseries\fontsize{{36}}{{40}}\selectfont\color{{GewuInk}} Gewu Insight}}\\[4mm]
  \includegraphics[width=57mm]{{{calligraphy}}}\\[5mm]
  {{\sffamily\color{{GewuMuted}}\fontsize{{15}}{{18}}\selectfont User Guide}}\\[2.5mm]
  {{\sffamily\small\color{{GewuMuted}} Version {version} (Build {build})}}\\[19mm]
  \begin{{minipage}}{{0.72\textwidth}}
    \centering\sffamily\fontsize{{13}}{{18}}\selectfont\color{{GewuInk}}
    Your personal research workspace, keeping papers, evidence, and files connected over time.
  \end{{minipage}}
  \vfill
  {{\color{{GewuRule}}\rule{{68mm}}{{0.45pt}}}}\\[7mm]
  {{\small\sffamily\color{{GewuMuted}}Designed and developed by Lingyuan Kong and Zhengran Wu,\\with coding assistance from OpenAI Codex.}}\\[4mm]
  {{\footnotesize\sffamily\color{{GewuMuted}}Copyright \textcopyright\ 2026 Lingyuan Kong and Zhengran Wu. All Rights Reserved.}}\\[10mm]
\end{{titlepage}}

\chapter*{{About this manual}}
\addcontentsline{{toc}}{{chapter}}{{About this manual}}
This PDF is the fixed-layout edition of the in-app Gewu Insight User Guide. It contains the same product guidance as the searchable Help window, arranged for comfortable reading, printing, and archival use. Interface names remain in English so that the manual matches the application.

\section*{{Three complementary reading paths}}
\begin{{description}}[style=nextline,leftmargin=0pt,labelindent=0pt,itemsep=3pt]
  \item[Operate the workspace] Parts I and III explain the interface and everyday workflows: navigation, papers and files, importing, monitors, settings, recovery, and transfer.
  \item[Understand the product] Parts II and IV explain the local-first philosophy, the visible-workspace model, SQLite's role as the source of truth, and the product's visual identity.
  \item[Inspect the technical contract] Part V documents storage, database relationships, network behavior, migration, troubleshooting, and other details needed for maintenance or development.
\end{{description}}

These paths intentionally share one manual. The user-facing behavior, the product model, and the implementation constraints can therefore be read independently without drifting into separate and contradictory documents.

\clearpage
\section*{{Contents}}
% Keep the complete navigation list compact without changing body typography.
\begingroup
\setstretch{{0.96}}
\setlength{{\parskip}}{{0pt}}
\makeatletter
\@starttoc{{toc}}
\makeatother
\endgroup
\clearpage
\RaggedRight
"""


LATEX_END = r"""
\Needspace{7\baselineskip}
\section*{Copyright and product notice}
\addcontentsline{toc}{section}{Copyright and product notice}
Gewu Insight is proprietary software. Copyright \textcopyright\ 2026 Lingyuan Kong and Zhengran Wu. All Rights Reserved.

This manual describes the product as shipped at the version printed on the title page. Online services, publisher access, and third-party metadata may change independently of the application.
\end{document}
"""


def run(command: list[str], *, cwd: Path) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if completed.returncode:
        tail = "\n".join(completed.stdout.splitlines()[-80:])
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(command)}\n{tail}")


def prepare_latex_body(source: str) -> str:
    # Scope the continuous-chapter rule by semantic part name, not page numbers
    # or individual chapter titles. Rebuilding or adding text must preserve it.
    parts = re.split(r"(\\part\{[^{}]*\})", source)
    continuous_identity = False
    for index, part in enumerate(parts):
        if part.startswith(r"\part{"):
            continuous_identity = part == r"\part{Product Identity}"
        elif continuous_identity:
            parts[index] = part.replace(r"\chapter{", r"\GewuIdentityChapter{")
    source = "".join(parts)

    table_widths = {
        2: [0.27, 0.63],
        3: [0.19, 0.29, 0.36],
        4: [0.14, 0.20, 0.22, 0.24],
    }

    def replace_table(match: re.Match[str]) -> str:
        count = len(match.group(1))
        widths = table_widths.get(count)
        if not widths:
            return match.group(0)
        columns = "".join(
            rf">{{\RaggedRight\arraybackslash}}p{{{width:.2f}\textwidth}}" for width in widths
        )
        return rf"\begin{{longtable}}[]{{@{{}}{columns}@{{}}}}"

    source = re.sub(r"\\begin\{longtable\}\[\]\{@\{\}(l+)@\{\}\}", replace_table, source)

    def make_path_breakable(match: re.Match[str]) -> str:
        path = match.group(1).replace(r"\_", "_").replace(r"\ ", " ")
        return rf"\nolinkurl{{{path}}}"

    source = re.sub(
        r"\\texttt\{((?:data|reports|logs)/[^}]*)\}",
        make_path_breakable,
        source,
    )

    source = source.replace(
        "GEWULEADSTART", "\\begin{GewuLead}\n"
    ).replace(
        "GEWULEADEND", "\n\\end{GewuLead}"
    )
    source = source.replace(
        "GEWURESULTSTART", "\\begin{GewuResult}\n\\textbf{Result.} "
    ).replace(
        "GEWURESULTEND", "\n\\end{GewuResult}"
    )
    # Keep each real UI capture with its explanation, including compact settings.
    source = source.replace(
        "GEWUFIGURESTART", r"\par\noindent\begin{minipage}{\linewidth}"
    ).replace(
        "GEWUFIGUREEND", r"\end{minipage}\par\medskip"
    )
    source = source.replace(
        "GEWUCAPTIONSTART", "\\begin{GewuCaption}\n"
    ).replace(
        "GEWUCAPTIONEND", "\n\\end{GewuCaption}"
    )
    source = source.replace(
        "GEWURELATEDSTART", "\\begin{GewuRelated}\n"
    ).replace(
        "GEWURELATEDEND", "\n\\end{GewuRelated}"
    )

    source = source.replace(
        "\\begin{longtable}", "\\GewuTableStart\n\\begin{longtable}"
    ).replace(
        "\\end{longtable}", "\\end{longtable}\n\\GewuTableEnd"
    )
    source = source.replace(
        "\\toprule\\noalign{}", "\\toprule\\noalign{}\n\\rowcolor{GewuTableHeader}"
    )

    image_widths = {
        "GewuAboutCalligraphy.png": "0.84\\linewidth",
        "gewu-insight-app-icon.png": "0.18\\linewidth",
        **{path.name: "0.96\\linewidth" for route, path in IMAGE_ROUTES.items()
           if route.startswith("/user-guide-assets/")},
        "about-window.png": "0.48\\linewidth",
    }
    for filename, width in image_widths.items():
        pattern = re.compile(
            rf"\\pandocbounded\{{\\includegraphics\[([^\]]*)\]\{{([^}}]*{re.escape(filename)})\}}\}}"
        )
        source = pattern.sub(
            lambda match: (
                "\\begin{center}\\includegraphics[width="
                + width
                + (",height=0.72\\textheight" if filename not in {"GewuAboutCalligraphy.png", "gewu-insight-app-icon.png"} else "")
                + ",keepaspectratio]{"
                + match.group(2)
                + "}\\end{center}"
            ),
            source,
        )

    seal_pattern = re.compile(
        r"\\pandocbounded\{\\includegraphics\[([^\]]*)\]\{([^}]*GewuSealGlyphs\.png)\}\}"
    )
    source = seal_pattern.sub(
        lambda match: (
            "\\begin{center}"
            "\\begin{tcolorbox}[enhanced,width=0.30\\linewidth,colback=GewuSealPanel,"
            "colframe=GewuSealPanel,boxrule=0pt,arc=3mm,boxsep=0pt,"
            "left=4mm,right=4mm,top=4mm,bottom=4mm]"
            "\\includegraphics[width=\\linewidth,keepaspectratio]{"
            + match.group(2)
            + "}\\end{tcolorbox}\\end{center}"
        ),
        source,
    )

    for symbol in ["↓", "↑", "→", "←", "↕", "↺", "⇧", "⌘", "≠"]:
        source = source.replace(symbol, rf"{{\symbolfont {symbol}}}")
    return source


def build(tex_output: Path, pdf_output: Path) -> None:
    pandoc = shutil.which("pandoc")
    xelatex = shutil.which("xelatex")
    if not pandoc or not xelatex:
        raise SystemExit("pandoc and xelatex are required to build the User Guide PDF")

    version, build_number = app_version()
    with tempfile.TemporaryDirectory(prefix="gewu-user-guide-") as temporary:
        workdir = Path(temporary)
        clean_html = workdir / "guide.html"
        body_tex = workdir / "guide-body.tex"
        clean_html.write_text(clean_guide_html(), encoding="utf-8")
        run(
            [
                pandoc,
                str(clean_html),
                "--from=html",
                "--to=latex",
                "--wrap=none",
                "--top-level-division=part",
                f"--resource-path={ROOT}",
                "--output",
                str(body_tex),
            ],
            cwd=ROOT,
        )
        body = prepare_latex_body(body_tex.read_text(encoding="utf-8"))
        source = latex_preamble(version, build_number) + body + LATEX_END
        tex_output.parent.mkdir(parents=True, exist_ok=True)
        tex_output.write_text(source, encoding="utf-8")

        compile_directory = workdir / "latex-build"
        compile_directory.mkdir()
        for _ in range(3):
            run(
                [
                    xelatex,
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    f"-output-directory={compile_directory}",
                    str(tex_output.resolve()),
                ],
                cwd=ROOT,
            )
        generated = compile_directory / f"{tex_output.stem}.pdf"
        pdf_output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(generated, pdf_output.resolve())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tex-output", type=Path, default=TEX_OUTPUT)
    parser.add_argument("--pdf-output", type=Path, default=PDF_OUTPUT)
    arguments = parser.parse_args()
    build(arguments.tex_output, arguments.pdf_output)
    print(arguments.pdf_output)


if __name__ == "__main__":
    main()
