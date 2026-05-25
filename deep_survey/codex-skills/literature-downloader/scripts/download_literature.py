#!/usr/bin/env python3
"""Download a paper and supplements by DOI into ~/Downloads.

The script is intentionally conservative:
- direct HTTP/API retrieval is attempted first;
- Safari is used only as a browser-session fallback;
- all final files stay in the Downloads directory;
- PDF supplements are merged with the main PDF when present.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import html
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


SCRIPT_DIR = Path(__file__).resolve().parent
MERGE_SCRIPT = SCRIPT_DIR / "merge_pdf_supplements.py"
PDF_MAGIC = b"%PDF-"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
MAIN_KEYWORDS = ("pdf", "full text", "fulltext", "download pdf", "article pdf")
SUPP_KEYWORDS = (
    "supporting information",
    "supplementary",
    "supplemental",
    "supplement",
    "appendix",
    "additional file",
    "additional information",
    "esm",
    "moesm",
    "suppl",
    "supinfo",
    "si_",
    "dataset",
)
HTML_HINTS = (
    "text/html",
    "<html",
    "<!doctype html",
    "enable javascript",
    "access denied",
    "sign in",
    "login",
)


@dataclasses.dataclass
class Candidate:
    url: str
    kind: str
    source: str
    label: str = ""


@dataclasses.dataclass
class Downloaded:
    path: Path
    kind: str
    source_url: str
    method: str


def log(result: dict, message: str) -> None:
    result.setdefault("log", []).append(message)


def normalize_doi(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^(doi:\s*)", "", value, flags=re.I)
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value, flags=re.I)
    value = value.strip().strip(".")
    match = re.search(r"10\.\d{4,9}/\S+", value, flags=re.I)
    if not match:
        raise SystemExit(f"Could not find a DOI in: {value}")
    doi = match.group(0).rstrip(").,;]")
    return unquote(doi)


def safe_filename(value: str, max_len: int = 120) -> str:
    value = html.unescape(value)
    value = re.sub(r"[\s_]+", "_", value.strip())
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._-")
    return (value or "article")[:max_len].strip("._-") or "article"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for idx in range(2, 1000):
        candidate = path.with_name(f"{stem}_{idx}{suffix}")
        if not candidate.exists():
            return candidate
    raise SystemExit(f"Could not create unique filename for {path}")


def is_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(5) == PDF_MAGIC
    except OSError:
        return False


def looks_like_html(path: Path) -> bool:
    try:
        sample = path.read_bytes()[:4096].lower()
    except OSError:
        return False
    return any(hint.encode("utf-8") in sample for hint in HTML_HINTS if hint.startswith("<"))


def extension_from_headers(url: str, content_type: str, content_disposition: str = "") -> str:
    if content_disposition:
        match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', content_disposition, flags=re.I)
        if match:
            suffix = Path(unquote(match.group(1))).suffix
            if suffix:
                return suffix[:16]
    path_suffix = Path(urlparse(url).path).suffix
    if path_suffix and len(path_suffix) <= 12:
        return path_suffix
    guessed = mimetypes.guess_extension(content_type.split(";")[0].strip())
    return guessed or ".bin"


def classify_file(path: Path, content_type: str = "") -> str:
    if is_pdf(path):
        return "pdf"
    ctype = content_type.lower()
    suffix = path.suffix.lower()
    if "zip" in ctype or suffix == ".zip":
        return "zip"
    if "word" in ctype or suffix in {".doc", ".docx"}:
        return "docx"
    if "excel" in ctype or "spreadsheet" in ctype or suffix in {".xls", ".xlsx", ".csv", ".tsv"}:
        return "spreadsheet"
    if ctype.startswith("image/") or suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".gif"}:
        return "image"
    if "html" in ctype or looks_like_html(path):
        return "html"
    return suffix.lstrip(".") or "file"


def make_session(timeout: int) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf;q=0.8,*/*;q=0.7",
        }
    )
    session.request_timeout = timeout  # type: ignore[attr-defined]
    return session


def get_json(session: requests.Session, url: str, result: dict) -> dict | None:
    try:
        response = session.get(url, timeout=session.request_timeout)  # type: ignore[attr-defined]
        if response.status_code >= 400:
            log(result, f"GET JSON {url} returned HTTP {response.status_code}")
            return None
        return response.json()
    except Exception as exc:
        log(result, f"GET JSON {url} failed: {exc}")
        return None


def get_crossref(session: requests.Session, doi: str, result: dict) -> dict:
    url = f"https://api.crossref.org/works/{quote(doi, safe='')}"
    data = get_json(session, url, result)
    if not data:
        return {}
    return data.get("message", {}) if isinstance(data, dict) else {}


def get_unpaywall(session: requests.Session, doi: str, email: str | None, result: dict) -> dict:
    if not email:
        return {}
    url = f"https://api.unpaywall.org/v2/{quote(doi, safe='')}?email={quote(email)}"
    data = get_json(session, url, result)
    return data if isinstance(data, dict) else {}


def resolve_landing(session: requests.Session, doi: str, result: dict) -> tuple[str, str, str]:
    doi_url = f"https://doi.org/{doi}"
    try:
        response = session.get(doi_url, timeout=session.request_timeout, allow_redirects=True)  # type: ignore[attr-defined]
        content_type = response.headers.get("Content-Type", "")
        text = response.text if "html" in content_type.lower() else ""
        log(result, f"Resolved DOI to {response.url} ({response.status_code}, {content_type})")
        return response.url, content_type, text
    except Exception as exc:
        log(result, f"DOI resolution failed: {exc}")
        return doi_url, "", ""


def metadata_stem(doi: str, crossref: dict, landing_html: str) -> str:
    title = ""
    year = ""
    if crossref:
        titles = crossref.get("title") or []
        if titles:
            title = str(titles[0])
        for key in ("published-print", "published-online", "published", "issued", "created"):
            parts = (crossref.get(key) or {}).get("date-parts") or []
            if parts and parts[0]:
                year = str(parts[0][0])
                break
    if landing_html and (not title or not year):
        soup = BeautifulSoup(landing_html, "html.parser")
        if not title:
            tag = soup.find("meta", attrs={"name": "citation_title"})
            if tag and tag.get("content"):
                title = str(tag["content"])
        if not year:
            for meta_name in ("citation_publication_date", "citation_online_date"):
                tag = soup.find("meta", attrs={"name": meta_name})
                if tag and tag.get("content"):
                    match = re.search(r"(19|20)\d{2}", str(tag["content"]))
                    if match:
                        year = match.group(0)
                        break
    if title:
        stem = safe_filename("_".join(filter(None, [year, title])), max_len=120)
    else:
        stem = safe_filename(doi.replace("/", "_"), max_len=120)
    return stem


def add_candidate(candidates: list[Candidate], seen: set[str], url: str, kind: str, source: str, label: str = "") -> None:
    if not url or url.startswith(("mailto:", "javascript:", "#")):
        return
    if url in seen:
        return
    seen.add(url)
    candidates.append(Candidate(url=url, kind=kind, source=source, label=label))


def candidates_from_crossref(crossref: dict) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for item in crossref.get("link") or []:
        url = item.get("URL") or item.get("url")
        ctype = (item.get("content-type") or "").lower()
        intended = (item.get("intended-application") or "").lower()
        label = " ".join(filter(None, [ctype, intended]))
        lower_url = (url or "").lower()
        looks_main_pdf = (
            "pdf" in ctype
            or "/doi/pdf/" in lower_url
            or lower_url.endswith(".pdf")
            or "viewmedia.cfm" in lower_url
        )
        looks_supplement = any(word in (lower_url + " " + label) for word in SUPP_KEYWORDS)
        kind = "supplement" if looks_supplement and not looks_main_pdf else "main" if looks_main_pdf else "supplement"
        add_candidate(candidates, seen, url, kind, "crossref", label)
    return candidates


def candidates_from_unpaywall(unpaywall: dict) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[str] = set()
    locations = []
    best = unpaywall.get("best_oa_location")
    if isinstance(best, dict):
        locations.append(best)
    locations.extend([x for x in unpaywall.get("oa_locations") or [] if isinstance(x, dict)])
    for loc in locations:
        for key in ("url_for_pdf", "url"):
            if loc.get(key):
                add_candidate(candidates, seen, loc[key], "main", "unpaywall", key)
    return candidates


def candidates_from_html(page_url: str, page_html: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[str] = set()
    if not page_html:
        return candidates
    soup = BeautifulSoup(page_html, "html.parser")
    for meta_name in ("citation_pdf_url", "bepress_citation_pdf_url"):
        for tag in soup.find_all("meta", attrs={"name": meta_name}):
            if tag.get("content"):
                add_candidate(candidates, seen, urljoin(page_url, tag["content"]), "main", f"meta:{meta_name}")
    for meta_name in ("citation_supplementary_material", "citation_supplemental_material"):
        for tag in soup.find_all("meta", attrs={"name": meta_name}):
            if tag.get("content"):
                add_candidate(candidates, seen, urljoin(page_url, tag["content"]), "supplement", f"meta:{meta_name}")

    for anchor in soup.find_all("a", href=True):
        href = urljoin(page_url, anchor["href"])
        label = " ".join(
            filter(
                None,
                [
                    anchor.get_text(" ", strip=True),
                    anchor.get("title", ""),
                    anchor.get("aria-label", ""),
                    anchor.get("class") and " ".join(anchor.get("class", [])),
                    href,
                ],
            )
        )
        lower = label.lower()
        if any(word in lower for word in SUPP_KEYWORDS):
            add_candidate(candidates, seen, href, "supplement", "html", label[:160])
        elif any(word in lower for word in MAIN_KEYWORDS) and "pdf" in lower:
            add_candidate(candidates, seen, href, "main", "html", label[:160])
    return candidates


def publisher_guesses(doi: str, landing_url: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[str] = set()
    lower = doi.lower()
    if lower.startswith("10.1021/"):
        add_candidate(candidates, seen, f"https://pubs.acs.org/doi/pdf/{doi}?download=true", "main", "publisher-guess", "ACS PDF")
        add_candidate(candidates, seen, f"https://pubs.acs.org/doi/pdf/{doi}?ref=article_openPDF", "main", "publisher-guess", "ACS PDF viewer")
    if lower.startswith("10.1038/"):
        suffix = doi.split("/", 1)[1]
        add_candidate(candidates, seen, f"https://www.nature.com/articles/{suffix}.pdf", "main", "publisher-guess", "Nature PDF")
    if lower.startswith("10.1007/"):
        quoted = quote(doi, safe="/")
        add_candidate(candidates, seen, f"https://link.springer.com/content/pdf/{quoted}.pdf", "main", "publisher-guess", "Springer PDF")
    if lower.startswith("10.48550/arxiv."):
        arxiv_id = doi.split(".", 1)[1]
        add_candidate(candidates, seen, f"https://arxiv.org/pdf/{arxiv_id}.pdf", "main", "publisher-guess", "arXiv PDF")
    if lower.startswith("10.1364/"):
        # Optica/OSA often exposes a viewmedia page that Safari resolves to a
        # temporary directpdfaccess PDF URL after cookie/access handling.
        if "viewmedia.cfm" in landing_url:
            add_candidate(candidates, seen, landing_url, "main", "publisher-guess", "Optica viewmedia")
            parsed = urlparse(landing_url)
            query = parsed.query
            if "html=true" in query:
                add_candidate(
                    candidates,
                    seen,
                    landing_url.replace("html=true", "html=false"),
                    "main",
                    "publisher-guess",
                    "Optica PDF viewmedia",
                )
    if "pubs.acs.org/doi/" in landing_url and "/doi/pdf/" not in landing_url:
        parsed = urlparse(landing_url)
        suffix = parsed.path.split("/doi/", 1)[1] if "/doi/" in parsed.path else doi
        add_candidate(candidates, seen, f"https://pubs.acs.org/doi/pdf/{suffix}?download=true", "main", "publisher-guess", "ACS landing-derived PDF")
    return candidates


def cleanup_tokens_for_doi(doi: str, landing_url: str, candidates: Iterable[Candidate]) -> list[str]:
    tokens: list[str] = []

    def add(value: str) -> None:
        value = value.strip()
        if value and len(value) >= 4 and value not in tokens:
            tokens.append(value)

    add(doi)
    add(doi.lower())
    parsed = urlparse(landing_url)
    for part in re.split(r"[^A-Za-z0-9.-]+", parsed.path + "&" + parsed.query):
        if re.search(r"\d", part) and ("-" in part or "." in part):
            add(part)
    for candidate in candidates:
        parsed_candidate = urlparse(candidate.url)
        for part in re.split(r"[^A-Za-z0-9.-]+", parsed_candidate.path + "&" + parsed_candidate.query):
            if re.search(r"\d", part) and ("-" in part or "." in part):
                add(part)
    return tokens


def order_candidates(candidates: Iterable[Candidate], wanted: str) -> list[Candidate]:
    filtered = [c for c in candidates if c.kind == wanted]
    if wanted == "supplement":
        return filtered
    def score(candidate: Candidate) -> tuple[int, str]:
        url = candidate.url.lower()
        label = candidate.label.lower()
        value = url + " " + label
        points = 0
        if candidate.source.startswith("meta"):
            points -= 30
        if candidate.source == "unpaywall":
            points -= 20
        if candidate.source == "publisher-guess":
            points -= 10
        if "download=true" in value:
            points -= 5
        if wanted == "main" and "supp" in value:
            points += 30
        return (points, candidate.url)
    return sorted(filtered, key=score)


def download_url(
    session: requests.Session,
    url: str,
    output_path: Path,
    kind: str,
    result: dict,
    accept_supplement: bool = False,
) -> Downloaded | None:
    temp_name = output_path.with_name(f".{output_path.name}.{hashlib.sha1(url.encode()).hexdigest()[:8]}.part")
    with contextlib.suppress(FileNotFoundError):
        temp_name.unlink()
    try:
        response = session.get(url, timeout=session.request_timeout, allow_redirects=True, stream=True)  # type: ignore[attr-defined]
    except Exception as exc:
        log(result, f"Direct download failed for {url}: {exc}")
        return None

    ctype = response.headers.get("Content-Type", "")
    if response.status_code >= 400:
        log(result, f"Direct download {url} returned HTTP {response.status_code}")
        return None
    try:
        with temp_name.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=128 * 1024):
                if chunk:
                    handle.write(chunk)
    except Exception as exc:
        log(result, f"Could not write {temp_name}: {exc}")
        with contextlib.suppress(FileNotFoundError):
            temp_name.unlink()
        return None

    detected = classify_file(temp_name, ctype)
    if kind == "main" and detected != "pdf":
        log(result, f"Rejected main candidate {url}: got {detected} ({ctype})")
        with contextlib.suppress(FileNotFoundError):
            temp_name.unlink()
        return None
    if kind == "supplement" and detected == "html":
        log(result, f"Rejected supplement candidate {url}: got HTML ({ctype})")
        with contextlib.suppress(FileNotFoundError):
            temp_name.unlink()
        return None
    if kind == "supplement" and not accept_supplement:
        with contextlib.suppress(FileNotFoundError):
            temp_name.unlink()
        return None

    final_path = output_path
    if kind == "supplement":
        suffix = output_path.suffix
        if not suffix or suffix == ".bin":
            suffix = extension_from_headers(response.url, ctype, response.headers.get("Content-Disposition", ""))
            final_path = output_path.with_suffix(suffix)
    final_path = unique_path(final_path)
    temp_name.replace(final_path)
    return Downloaded(path=final_path, kind=classify_file(final_path, ctype), source_url=response.url, method="direct")


def snapshot_downloads(downloads_dir: Path) -> dict[Path, float]:
    downloads_dir.mkdir(parents=True, exist_ok=True)
    return {path: path.stat().st_mtime for path in downloads_dir.iterdir() if path.is_file()}


def new_downloads(downloads_dir: Path, before: dict[Path, float]) -> list[Path]:
    found = []
    for path in downloads_dir.iterdir():
        if not path.is_file():
            continue
        if path.suffix == ".download" or ".download" in path.name:
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if path not in before or mtime > before.get(path, 0) + 0.5:
            found.append(path)
    return sorted(found, key=lambda p: p.stat().st_mtime)


def wait_for_downloads(downloads_dir: Path, before: dict[Path, float], timeout: int) -> list[Path]:
    deadline = time.time() + timeout
    last_new: list[Path] = []
    while time.time() < deadline:
        active = list(downloads_dir.glob("*.download"))
        current_new = new_downloads(downloads_dir, before)
        if current_new:
            last_new = current_new
        if last_new and not active:
            time.sleep(1)
            if not list(downloads_dir.glob("*.download")):
                return new_downloads(downloads_dir, before)
        time.sleep(1)
    return last_new


def run_osascript(script: str, timeout: int = 60) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def applescript_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def safari_open(url: str, *, foreground: bool = False) -> tuple[bool, str]:
    activate_line = "activate" if foreground else ""
    script = f'''
tell application id "com.apple.Safari"
    {activate_line}
    if not (exists window 1) then
        make new document with properties {{URL:{applescript_string(url)}}}
    else
        tell window 1
            set current tab to (make new tab with properties {{URL:{applescript_string(url)}}})
        end tell
    end if
end tell
'''
    code, out, err = run_osascript(script, timeout=30)
    return code == 0, out or err


def safari_current_url() -> str:
    script = 'tell application id "com.apple.Safari" to return URL of front document'
    code, out, _ = run_osascript(script, timeout=10)
    return out if code == 0 else ""


def safari_eval(js: str, result: dict, timeout: int = 20) -> str | None:
    script = f'tell application id "com.apple.Safari" to do JavaScript {applescript_string(js)} in front document'
    code, out, err = run_osascript(script, timeout=timeout)
    if code != 0:
        message = out or err
        if "Allow JavaScript from Apple Events" in message:
            result["needs_safari_javascript_setting"] = True
            log(
                result,
                "Safari JavaScript needs Safari Settings > Advanced/Developer > Allow JavaScript from Apple Events.",
            )
        else:
            log(result, f"Safari JavaScript failed: {message}")
        return None
    return out


def looks_like_pdf_url(url: str) -> bool:
    lower = url.lower()
    parsed = urlparse(lower)
    return (
        parsed.path.endswith(".pdf")
        or "/directpdfaccess/" in lower
        or "pdfaccess" in lower
        or "/doi/pdf/" in lower
    )


def safari_dismiss_common_prompts(result: dict) -> None:
    # Cookie banners vary wildly. Use page JS first so Safari can stay in the
    # background. This only clicks common consent/close buttons on the page.
    js = r"""
(() => {
  const labels = [
    'accept all', 'accept', 'i accept', 'agree', 'i agree', 'allow all',
    'continue', 'close', 'got it', 'ok', 'okay',
    '关闭', '關閉', '接受', '全部接受', '同意'
  ];
  let clicked = [];
  const candidates = Array.from(document.querySelectorAll(
    'button, input[type=button], input[type=submit], a[role=button], [role=button]'
  ));
  for (const el of candidates) {
    const text = ((el.innerText || el.value || el.getAttribute('aria-label') || el.title || '') + '').trim().toLowerCase();
    if (!text) continue;
    if (labels.some(label => text === label || text.includes(label))) {
      try { el.click(); clicked.push(text); } catch (_) {}
    }
  }
  return JSON.stringify(clicked.slice(0, 10));
})()
"""
    out = safari_eval(js, result, timeout=10)
    if out:
        with contextlib.suppress(Exception):
            clicked = json.loads(out)
            if clicked:
                log(result, f"Safari dismissed page prompts via JavaScript: {clicked}")


def safari_extract_page_candidates(page_url: str, result: dict) -> list[Candidate]:
    result.setdefault("safari_opened_urls", []).append(page_url)
    ok, message = safari_open(page_url)
    if not ok:
        log(result, f"Safari could not open page for link extraction: {message}")
        return []
    time.sleep(5)
    js = r"""
JSON.stringify(Array.from(document.querySelectorAll('a[href]')).map((el) => ({
  href: el.href || el.getAttribute('href') || '',
  text: (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' '),
  title: el.getAttribute('title') || '',
  aria: el.getAttribute('aria-label') || '',
  cls: Array.from(el.classList || []).join(' ')
})).filter((x) => x.href))
"""
    out = safari_eval(js, result, timeout=20)
    if out is None:
        return []
    try:
        links = json.loads(out)
    except Exception as exc:
        log(result, f"Could not parse Safari link extraction output: {exc}")
        return []

    candidates: list[Candidate] = []
    seen: set[str] = set()
    for item in links:
        href = item.get("href") or ""
        label = " ".join(
            filter(None, [item.get("text", ""), item.get("title", ""), item.get("aria", ""), item.get("cls", ""), href])
        )
        lower = label.lower()
        parsed_href = urlparse(href.lower())
        query = parsed_href.query
        is_figure_or_inline_asset = (
            "figure=" in query
            or "imagetype=" in query
            or "inline-graphic" in lower
            or "thumbnail" in lower
        )
        if is_figure_or_inline_asset:
            continue
        if any(word in lower for word in SUPP_KEYWORDS):
            add_candidate(candidates, seen, href, "supplement", "safari-page", label[:160])
        elif "pdf" in lower and any(word in lower for word in MAIN_KEYWORDS):
            add_candidate(candidates, seen, href, "main", "safari-page", label[:160])
    if candidates:
        log(result, f"Safari extracted {len(candidates)} PDF/supplement candidate links.")
    return candidates


def safari_save_as(filename: str, downloads_dir: Path, timeout: int, result: dict) -> Path | None:
    # Prefer the save sheet's current location if it is already Downloads. If not,
    # try the location popup with English and Chinese labels.
    filename = filename.replace('"', '\\"')
    downloads_name_candidates = ["Downloads", "下载", "下載"]
    save_labels = ["Save", "存储", "儲存"]
    save_as_labels = ["Save As…", "Save As...", "存储为…", "存储为...", "另存为…", "另存为...", "儲存為…"]

    open_save_lines = [
        'tell application "System Events"',
        'set frontmost of process "Safari" to true',
        'delay 0.3',
        'tell process "Safari"',
        'set opened to false',
    ]
    for label in save_as_labels:
        open_save_lines.append(
            f'try\nclick menu item "{label}" of menu 1 of menu bar item 3 of menu bar 1\nset opened to true\nend try'
        )
    open_save_lines.extend(
        [
            'if opened is false then error "Could not open Safari Save As menu"',
            'end tell',
            'delay 0.8',
            'end tell',
        ]
    )
    code, out, err = run_osascript("\n".join(open_save_lines), timeout=20)
    if code != 0:
        log(result, f"Safari Save As menu failed: {out or err}")
        return None

    inspect_script = '''
tell application "System Events"
    tell process "Safari"
        if (count of windows) is 0 then return "no_window"
        if (count of sheets of window 1) is 0 then return "no_sheet"
        tell sheet 1 of window 1
            set locationValue to ""
            try
                set locationValue to value of pop up button 1
            end try
            return "sheet\t" & locationValue
        end tell
    end tell
end tell
'''
    code, out, err = run_osascript(inspect_script, timeout=10)
    if code != 0 or not out.startswith("sheet"):
        log(result, f"Safari save sheet not available: {out or err}")
        return None

    choose_downloads = ""
    if not any(name in out for name in downloads_name_candidates):
        choose_downloads = "\n".join(
            [
                'try',
                'click pop up button 1',
                'delay 0.2',
                *[
                    f'try\nclick menu item "{label}" of menu 1 of pop up button 1\nend try'
                    for label in downloads_name_candidates
                ],
                'end try',
                'delay 0.2',
            ]
        )

    click_save = "\n".join(
        [f'try\nclick button "{label}"\nend try' for label in save_labels]
    )
    save_script = f'''
tell application "System Events"
    tell process "Safari"
        tell sheet 1 of window 1
            set value of text field 1 to "{filename}"
            {choose_downloads}
            {click_save}
        end tell
    end tell
end tell
'''
    expected = downloads_dir / filename
    before = snapshot_downloads(downloads_dir)
    code, out, err = run_osascript(save_script, timeout=20)
    if code != 0:
        log(result, f"Safari save click failed: {out or err}")
        return None
    deadline = time.time() + timeout
    while time.time() < deadline:
        if expected.exists() and expected.stat().st_size > 0 and not (downloads_dir / f"{filename}.download").exists():
            return expected
        newer = new_downloads(downloads_dir, before)
        for path in newer:
            if path.name == filename or path.stat().st_size > 0:
                return path
        time.sleep(1)
    return expected if expected.exists() else None


def safari_download_url(
    session: requests.Session,
    url: str,
    filename: str,
    downloads_dir: Path,
    timeout: int,
    result: dict,
    kind: str,
    allow_foreground: bool = False,
) -> Path | None:
    before = snapshot_downloads(downloads_dir)
    result.setdefault("safari_opened_urls", []).append(url)
    ok, message = safari_open(url)
    if not ok:
        log(result, f"Safari open failed for {url}: {message}")
        return None
    time.sleep(3)
    safari_dismiss_common_prompts(result)
    time.sleep(3)
    downloaded = wait_for_downloads(downloads_dir, before, timeout=8)
    if downloaded:
        return downloaded[-1]
    current = safari_current_url()
    if current:
        log(result, f"Safari currently at {current}")
        result.setdefault("safari_opened_urls", []).append(current)
    if current and looks_like_pdf_url(current):
        direct = download_url(
            session,
            current,
            downloads_dir / filename,
            kind,
            result,
            accept_supplement=(kind == "supplement"),
        )
        if direct and direct.path.exists():
            log(result, f"Downloaded Safari-resolved PDF URL directly: {direct.path}")
            return direct.path
        if allow_foreground:
            log(result, "Safari resolved a PDF URL, but direct retrieval of that URL failed; trying foreground Safari Save As.")
            saved = safari_save_as(filename, downloads_dir, timeout=timeout, result=result)
            if saved and saved.exists():
                return saved
        else:
            log(result, "Safari resolved a PDF URL, but direct retrieval failed; foreground Save As is disabled by default.")
    else:
        log(result, "Safari did not reach a PDF URL; skipping Save As to avoid saving an HTML page.")
    return None


def safari_close_related(urls: Iterable[str], tokens: Iterable[str], result: dict) -> None:
    patterns = [url for url in urls if url]
    patterns.extend(token for token in tokens if token)
    if not patterns:
        return
    # Close tabs/documents opened for this DOI/PDF. Collect matching tab indexes
    # first, then close in reverse order so Safari does not skip tabs while the
    # tab collection is mutating.
    pattern_items = ", ".join(applescript_string(item) for item in patterns)
    script = f'''
tell application id "com.apple.Safari"
    set closePatterns to {{{pattern_items}}}
    repeat with w in windows
        set closeIndexes to {{}}
        repeat with i from 1 to count of tabs of w
            set t to tab i of w
            set tabURL to ""
            try
                set tabURL to URL of t
            end try
            if tabURL is not "" then
                set shouldClose to false
                repeat with p in closePatterns
                    if p is not "" and tabURL contains p then set shouldClose to true
                end repeat
                if tabURL contains "/directpdfaccess/" or tabURL contains "pdfaccess" then set shouldClose to true
                if shouldClose then
                    set end of closeIndexes to i
                end if
            end if
        end repeat
        repeat with idxRef in reverse of closeIndexes
            try
                close tab (contents of idxRef) of w
            end try
        end repeat
    end repeat
end tell
'''
    code, out, err = run_osascript(script, timeout=15)
    if code != 0:
        log(result, f"Could not close Safari tabs: {out or err}")
    else:
        log(result, "Attempted to close related Safari tabs.")


def rename_downloaded(path: Path, target: Path) -> Path:
    if path.resolve() == target.resolve():
        return path
    target = unique_path(target)
    path.rename(target)
    return target


def merge_pdf_supplements(main_pdf: Path, pdf_supplements: list[Path], output: Path, result: dict) -> Path | None:
    if not pdf_supplements:
        return None
    cmd = [sys.executable, str(MERGE_SCRIPT), "--main", str(main_pdf), "--output", str(output)]
    for supp in pdf_supplements:
        cmd.extend(["--supplement", str(supp)])
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        log(result, f"Merge failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return None
    return output if output.exists() and is_pdf(output) else None


def run_self_test() -> int:
    assert normalize_doi("https://doi.org/10.1021/acs.accounts.8b00173") == "10.1021/acs.accounts.8b00173"
    assert safe_filename("2020: A/B test?") == "2020_A_B_test"
    assert extension_from_headers("https://x/y.pdf?z=1", "application/pdf") == ".pdf"
    print("self-test ok")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download article PDF and supplements by DOI into Downloads.")
    parser.add_argument("doi", nargs="?", help="DOI or DOI URL")
    parser.add_argument("--downloads", default="~/Downloads", help="Downloads directory; default: ~/Downloads")
    parser.add_argument("--unpaywall-email", help="Email for Unpaywall API; optional")
    parser.add_argument("--safari", choices=["auto", "never", "always"], default="auto", help="Safari fallback mode")
    parser.add_argument(
        "--foreground-safari",
        action="store_true",
        help="Allow Safari fallback to activate Safari and use Save As if background URL resolution is insufficient",
    )
    parser.add_argument("--timeout", type=int, default=45, help="Network/Safari wait timeout in seconds")
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    parser.add_argument("--dry-run", action="store_true", help="Resolve metadata and candidates without downloading")
    parser.add_argument("--self-test", action="store_true", help="Run offline self-tests")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()
    if not args.doi:
        raise SystemExit("DOI is required unless --self-test is used.")

    downloads_dir = Path(args.downloads).expanduser().resolve()
    downloads_dir.mkdir(parents=True, exist_ok=True)
    doi = normalize_doi(args.doi)
    session = make_session(args.timeout)
    result: dict = {
        "doi": doi,
        "downloads_dir": str(downloads_dir),
        "status": "started",
        "files": [],
        "combined_pdf": None,
        "needs_user_action": False,
        "errors": [],
    }

    crossref = get_crossref(session, doi, result)
    landing_url, landing_type, landing_html = resolve_landing(session, doi, result)
    unpaywall = get_unpaywall(session, doi, args.unpaywall_email, result)
    stem = metadata_stem(doi, crossref, landing_html)
    result["stem"] = stem
    result["title"] = (crossref.get("title") or [""])[0] if crossref else ""
    result["landing_url"] = landing_url

    all_candidates: list[Candidate] = []
    all_candidates.extend(candidates_from_crossref(crossref))
    all_candidates.extend(candidates_from_unpaywall(unpaywall))
    all_candidates.extend(candidates_from_html(landing_url, landing_html))
    all_candidates.extend(publisher_guesses(doi, landing_url))
    # Deduplicate while preserving order.
    seen: set[tuple[str, str]] = set()
    unique_candidates: list[Candidate] = []
    for candidate in all_candidates:
        key = (candidate.kind, candidate.url)
        if key not in seen:
            seen.add(key)
            unique_candidates.append(candidate)
    result["candidates"] = [dataclasses.asdict(c) for c in unique_candidates]
    result["safari_cleanup_tokens"] = cleanup_tokens_for_doi(doi, landing_url, unique_candidates)

    if args.dry_run:
        result["status"] = "dry_run"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    downloaded: list[Downloaded] = []
    main_pdf: Path | None = None

    main_target = downloads_dir / f"{stem}.pdf"
    if args.safari != "always":
        for candidate in order_candidates(unique_candidates, "main"):
            item = download_url(session, candidate.url, main_target, "main", result)
            if item and item.kind == "pdf":
                main_pdf = item.path
                downloaded.append(item)
                log(result, f"Downloaded main PDF directly: {item.path}")
                break

    if main_pdf is None and args.safari != "never":
        safari_candidates = order_candidates(unique_candidates, "main") or [Candidate(f"https://doi.org/{doi}", "main", "doi", "DOI")]
        for candidate in safari_candidates:
            path = safari_download_url(
                session,
                candidate.url,
                f"{stem}.pdf",
                downloads_dir,
                args.timeout,
                result,
                "main",
                args.foreground_safari,
            )
            if path and path.exists() and is_pdf(path):
                path = rename_downloaded(path, main_target)
                main_pdf = path
                downloaded.append(Downloaded(path=path, kind="pdf", source_url=candidate.url, method="safari"))
                log(result, f"Downloaded main PDF via Safari: {path}")
                break
            if path and path.exists():
                log(result, f"Safari produced non-PDF for main candidate: {path}")

    if args.safari != "never" and not order_candidates(unique_candidates, "supplement"):
        safari_page_candidates = safari_extract_page_candidates(landing_url, result)
        if safari_page_candidates:
            existing = {(c.kind, c.url) for c in unique_candidates}
            for candidate in safari_page_candidates:
                key = (candidate.kind, candidate.url)
                if key not in existing:
                    unique_candidates.append(candidate)
                    existing.add(key)
            result["candidates"] = [dataclasses.asdict(c) for c in unique_candidates]

    supplement_downloads: list[Downloaded] = []
    supp_candidates = order_candidates(unique_candidates, "supplement")
    for idx, candidate in enumerate(supp_candidates, start=1):
        base_target = downloads_dir / f"{stem}_si_{idx}.bin"
        item = None
        if args.safari != "always":
            item = download_url(session, candidate.url, base_target, "supplement", result, accept_supplement=True)
        if item is None and args.safari != "never":
            suffix = Path(urlparse(candidate.url).path).suffix or ".bin"
            path = safari_download_url(
                session,
                candidate.url,
                f"{stem}_si_{idx}{suffix}",
                downloads_dir,
                args.timeout,
                result,
                "supplement",
                args.foreground_safari,
            )
            if path and path.exists():
                detected = classify_file(path)
                target = downloads_dir / f"{stem}_si_{idx}{path.suffix or suffix}"
                path = rename_downloaded(path, target)
                item = Downloaded(path=path, kind=detected, source_url=candidate.url, method="safari")
        if item:
            supplement_downloads.append(item)
            downloaded.append(item)

    pdf_supplements = [item.path for item in supplement_downloads if is_pdf(item.path)]
    combined = None
    if main_pdf and pdf_supplements:
        combined = merge_pdf_supplements(main_pdf, pdf_supplements, downloads_dir / f"{stem}_combined.pdf", result)
        if combined:
            result["combined_pdf"] = str(combined)

    result["files"] = [
        {
            "path": str(item.path),
            "kind": item.kind,
            "method": item.method,
            "source_url": item.source_url,
        }
        for item in downloaded
    ]
    if main_pdf:
        result["main_pdf"] = str(main_pdf)
    if not main_pdf:
        result["status"] = "needs_user_action" if args.safari != "never" else "failed"
        result["needs_user_action"] = True
        result["errors"].append(
            "Main PDF was not downloaded. Open the DOI in Safari, complete login/access if needed, then rerun or save the PDF to Downloads."
        )
    else:
        result["status"] = "ok"

    if result["status"] == "ok" and result.get("safari_opened_urls"):
        safari_close_related(
            result.get("safari_opened_urls", []),
            result.get("safari_cleanup_tokens", []),
            result,
        )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if main_pdf else 2


if __name__ == "__main__":
    sys.exit(main())
