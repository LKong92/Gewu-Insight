from __future__ import annotations

import json
import html
from datetime import date
from pathlib import Path
from typing import Any

from .config import DEFAULT_DAILY_REPORT_DIR
from .storage import Storage
from .text import clean_text, safe_slug


def write_journal_markdown_report(
    *,
    storage: Storage,
    journals: list[str],
    start_date: date,
    end_date: date,
    output_dir: Path = DEFAULT_DAILY_REPORT_DIR,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    papers = storage.list_papers(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        journals=journals,
    )
    papers = [paper for paper in papers if paper.get("section_allowed") != 0]
    path = output_dir / f"journal_report_{start_date.isoformat()}_{end_date.isoformat()}.md"
    path.write_text(render_journal_markdown(papers, journals, start_date, end_date), encoding="utf-8")
    return path


def render_journal_markdown(
    papers: list[dict[str, Any]],
    journals: list[str],
    start_date: date,
    end_date: date,
) -> str:
    grouped: dict[str, list[dict[str, Any]]] = {journal: [] for journal in journals}
    for paper in papers:
        grouped.setdefault(paper["journal"], []).append(paper)

    lines = [
        "# Journal Monitor",
        "",
        f"- Report window: {start_date.isoformat()} to {end_date.isoformat()}",
        f"- Total papers: {len(papers)}",
        "",
        "Download status values: `not_attempted`, `success`, `partial`, `failed`, `skipped`.",
        "",
    ]

    for journal in journals:
        group = grouped.get(journal, [])
        lines.extend([f"## {journal} ({len(group)})", ""])
        if not group:
            lines.extend(["No papers in this report window.", ""])
            continue
        for paper in group:
            lines.extend(render_paper_block(paper))

    return "\n".join(lines).rstrip() + "\n"


def render_paper_block(paper: dict[str, Any]) -> list[str]:
    paper_id = paper["paper_id"]
    title = clean_text(paper.get("title")) or "(Untitled)"
    section = paper.get("publisher_section") or "unknown"
    abstract_source = paper.get("abstract_source") or "unavailable"
    download_status = paper.get("download_status") or "not_attempted"
    download_message = paper.get("download_message") or ""
    merged_pdf = paper.get("merged_pdf_path") or ""
    analysis_status = paper.get("analysis_status") or "not_started"
    analysis_path = paper.get("analysis_path") or ""

    title_line = render_title_line(title, section)

    lines = [
        title_line,
        "",
        f"- ID: `{paper_id}`",
        f"- Date: {paper.get('publication_date') or 'unknown'}",
        f"- DOI: {paper.get('doi') or 'unavailable'}",
        f"- Link: {render_markdown_link(paper.get('url') or paper.get('landing_url') or '')}",
        f"- Section: {section}",
        f"- Abstract source: {abstract_source}",
        f"- Download status: `{download_status}`{(' - ' + download_message) if download_message else ''}",
    ]
    if merged_pdf:
        lines.append(f"- Merged PDF: `{merged_pdf}`")
    lines.append(f"- Analysis status: `{analysis_status}`")
    if analysis_path:
        lines.append(f"- Analysis note: `{analysis_path}`")
    lines.extend(
        [
            "",
            "Actions:",
            f"- Download: `python -m paper_monitor download {paper_id}`",
            f"- Analyze: `python -m paper_monitor analyze {paper_id}`",
            "",
        ]
    )

    abstract = clean_text(paper.get("abstract"))
    lines.extend(["Abstract:", "", abstract or "No abstract available in the current metadata. Run `python -m paper_monitor journal` without `--no-enrich` to try landing-page enrichment.", ""])
    return lines


def render_title_line(title: str, section: str) -> str:
    color = section_color(section)
    badge_bg = section_badge_background(section)
    safe_title = html.escape(title)
    safe_section = html.escape(section)
    return (
        f'### <span style="color:{color};">{safe_title}</span> '
        f'<span style="font-size:0.72em; color:{color}; background:{badge_bg}; '
        f'border:1px solid {color}; border-radius:4px; padding:1px 6px;">{safe_section}</span>'
    )


def render_markdown_link(url: str) -> str:
    if not url:
        return "unavailable"
    return f"[Open paper]({url})"


def section_color(section: str) -> str:
    normalized = section.lower()
    if "perspective" in normalized:
        return "#8a4b00"
    if "review" in normalized:
        return "#7a1fa2"
    if "analysis" in normalized:
        return "#005f73"
    if "research" in normalized or normalized == "article":
        return "#17643b"
    if "news" in normalized or "comment" in normalized:
        return "#9b2226"
    return "#4b5563"


def section_badge_background(section: str) -> str:
    normalized = section.lower()
    if "perspective" in normalized:
        return "#fff4df"
    if "review" in normalized:
        return "#f5e8ff"
    if "analysis" in normalized:
        return "#e6f7fb"
    if "research" in normalized or normalized == "article":
        return "#e9f7ef"
    if "news" in normalized or "comment" in normalized:
        return "#ffe8e6"
    return "#f3f4f6"


def export_json(storage: Storage, output_path: Path, start_date: str | None = None, end_date: str | None = None) -> Path:
    papers = storage.list_papers(start_date=start_date, end_date=end_date)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(papers, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def analysis_filename(paper: dict[str, Any]) -> str:
    date_part = paper.get("publication_date") or "undated"
    title_part = safe_slug(paper.get("title") or paper["paper_id"], 70)
    return f"{date_part}_{title_part}.md"
