from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import USER_AGENT
from ..text import clean_text

import requests


def enrich_from_landing_page(paper: dict[str, Any], section_policy: dict[str, list[str]], keep_unknown: bool) -> dict[str, Any]:
    url = paper.get("landing_url") or paper.get("url")
    if not url:
        paper["section_allowed"] = keep_unknown
        return paper

    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=8,
            allow_redirects=True,
        )
        response.raise_for_status()
    except Exception as exc:
        if paper.get("section_allowed") is None:
            paper["section_allowed"] = keep_unknown
        paper["publisher_section"] = paper.get("publisher_section") or "unknown"
        paper["landing_fetch_error"] = str(exc)
        return paper

    soup = BeautifulSoup(response.text, "html.parser")
    section = extract_section(soup)
    abstract = extract_abstract(soup)
    pdf_url = extract_pdf_url(soup, url)
    supplement_urls = extract_supplement_urls(soup, url)
    image_url = extract_first_image_url(soup, url)

    if section:
        paper["publisher_section"] = section
        paper["section_allowed"] = classify_section(section, section_policy, keep_unknown)
    elif paper.get("section_allowed") is None:
        paper["publisher_section"] = paper.get("publisher_section") or "unknown"
        paper["section_allowed"] = keep_unknown

    if not paper.get("abstract") and abstract:
        paper["abstract"] = abstract
        paper["abstract_source"] = "landing_page"
    if pdf_url and not paper.get("pdf_url"):
        paper["pdf_url"] = pdf_url
    if supplement_urls:
        paper["supplement_urls"] = supplement_urls
    if image_url:
        paper["image_url"] = image_url
    return paper


def enrich_image_from_landing_page(paper: dict[str, Any]) -> dict[str, Any]:
    if paper.get("image_url"):
        return paper
    url = paper.get("landing_url") or paper.get("url")
    if not url:
        return paper
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=8,
            allow_redirects=True,
        )
        response.raise_for_status()
    except Exception as exc:
        paper["landing_fetch_error"] = str(exc)
        return paper
    soup = BeautifulSoup(response.text, "html.parser")
    image_url = ""
    if (paper.get("journal") or "").lower() == "arxiv":
        image_url = extract_arxiv_html_first_figure_url(soup, response.url or url)
    if not image_url:
        image_url = extract_first_image_url(soup, url)
    if image_url:
        paper["image_url"] = image_url
    return paper


def extract_arxiv_html_first_figure_url(abs_soup: BeautifulSoup, abs_url: str) -> str:
    html_url = extract_arxiv_html_url(abs_soup, abs_url)
    if not html_url:
        return ""
    try:
        response = requests.get(
            html_url,
            headers={"User-Agent": USER_AGENT},
            timeout=12,
            allow_redirects=True,
        )
        response.raise_for_status()
    except Exception:
        return ""
    return extract_first_image_url(BeautifulSoup(response.text, "html.parser"), response.url or html_url)


def extract_arxiv_html_url(soup: BeautifulSoup, base_url: str) -> str:
    for link in soup.find_all("a", href=True):
        label = clean_text(link.get_text(" ", strip=True)).lower()
        title = clean_text(link.get("title")).lower()
        marker = f"{label} {title}"
        href = clean_text(link.get("href"))
        if href and "html" in marker and "experimental" in marker:
            return urljoin(base_url, href)
    return ""


def extract_section(soup: BeautifulSoup) -> str:
    section = first_meta(
        soup,
        [
            {"name": "citation_article_type"},
            {"name": "dc.type"},
            {"name": "dc.Type"},
            {"name": "prism.section"},
            {"property": "article:section"},
            {"property": "og:type"},
        ],
    )
    return normalize_section(section)


def extract_abstract(soup: BeautifulSoup) -> str:
    return first_meta(
        soup,
        [
            {"name": "dc.description"},
            {"name": "dc.Description"},
            {"name": "description"},
            {"property": "og:description"},
            {"name": "twitter:description"},
        ],
    )


def extract_pdf_url(soup: BeautifulSoup, base_url: str) -> str:
    meta_url = first_meta(soup, [{"name": "citation_pdf_url"}])
    if meta_url:
        return urljoin(base_url, meta_url)
    for link in soup.find_all("a", href=True):
        href = clean_text(link.get("href"))
        label = clean_text(link.get_text(" ", strip=True)).lower()
        marker = f"{href} {label}".lower()
        if is_probable_non_article_pdf(marker):
            continue
        if href.lower().endswith(".pdf") or "download pdf" in label or label == "pdf":
            return urljoin(base_url, href)
    return ""


def extract_supplement_urls(soup: BeautifulSoup, base_url: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        href = clean_text(link.get("href"))
        label = clean_text(link.get_text(" ", strip=True)).lower()
        marker = f"{href} {label}".lower()
        if not any(
            token in marker
            for token in [
                "supplement",
                "supplementary",
                "appendix",
                "additional file",
                "peer review file",
                "peer-review file",
                "reporting summary",
            ]
        ):
            continue
        absolute = urljoin(base_url, href)
        if absolute not in seen:
            seen.add(absolute)
            urls.append(absolute)
    return urls


def extract_first_image_url(soup: BeautifulSoup, base_url: str) -> str:
    for selector in [
        "figure img",
        "article img",
        "[class*=figure] img",
        "[id*=figure] img",
    ]:
        for image in soup.select(selector):
            url = image_candidate_url(image)
            if url and not is_probable_non_figure_image(url, image):
                return urljoin(base_url, url)

    meta_url = first_meta(
        soup,
        [
            {"name": "citation_figure"},
            {"property": "og:image"},
            {"name": "twitter:image"},
            {"name": "twitter:image:src"},
        ],
    )
    return urljoin(base_url, meta_url) if meta_url else ""


def image_candidate_url(image: Any) -> str:
    for attr in ["src", "data-src", "data-original", "data-highres", "data-download-url"]:
        value = clean_text(image.get(attr))
        if value:
            return value
    srcset = clean_text(image.get("srcset") or image.get("data-srcset"))
    if srcset:
        candidates = [part.strip().split(" ", 1)[0] for part in srcset.split(",") if part.strip()]
        if candidates:
            return candidates[-1]
    return ""


def is_probable_non_figure_image(url: str, image: Any) -> bool:
    marker = " ".join(
        [
            url,
            clean_text(image.get("alt")),
            clean_text(image.get("class")),
            clean_text(image.get("id")),
        ]
    ).lower()
    if any(token in marker for token in ["logo", "icon", "avatar", "ad-", "advert", "spinner", "tracking", "pixel"]):
        return True
    try:
        width = int(str(image.get("width") or "0").strip() or 0)
        height = int(str(image.get("height") or "0").strip() or 0)
    except ValueError:
        width = height = 0
    return bool(width and height and (width < 120 or height < 90))


def first_meta(soup: BeautifulSoup, attrs_list: list[dict[str, str]]) -> str:
    for attrs in attrs_list:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            value = clean_text(tag.get("content"))
            if value:
                return value
    return ""


def normalize_section(section: str) -> str:
    section = clean_text(section).lower()
    section = section.replace("open access", "")
    section = re.sub(r"\s+", " ", section).strip()
    if "research article" in section:
        return "research article"
    if section in {"research", "report", "review", "analysis", "perspective", "letter"}:
        return section
    if "review" in section:
        return "review"
    if "analysis" in section:
        return "analysis"
    if "perspective" in section:
        return "perspective"
    if "article" in section:
        return "article"
    return section


def is_probable_non_article_pdf(marker: str) -> bool:
    non_article_tokens = [
        "peer review",
        "peer-review",
        "reporting summary",
        "source data",
        "supplement",
        "supplementary",
        "appendix",
        "additional",
    ]
    return any(token in marker for token in non_article_tokens)


def classify_section(section: str, policy: dict[str, list[str]], keep_unknown: bool) -> bool:
    normalized = normalize_section(section)
    if not normalized:
        return keep_unknown
    if any(blocked in normalized for blocked in policy.get("blocked", [])):
        return False
    allowed = policy.get("allowed", [])
    if not allowed:
        return True
    return normalized in allowed or any(item in normalized for item in allowed)
