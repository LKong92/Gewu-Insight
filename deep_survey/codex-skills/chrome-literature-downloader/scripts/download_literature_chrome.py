#!/usr/bin/env python3
"""Download literature by DOI with direct retrieval first, then Google Chrome.

This wrapper keeps the original literature-downloader as the direct/API layer
and uses the user's real Chrome session only as an authorized browser fallback.
It never reads Chrome cookies or profile data.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
from urllib.parse import parse_qs
from urllib.request import Request, urlopen


BASE_SKILL_DIR = Path(
    os.environ.get(
        "CODEX_LITERATURE_DOWNLOADER_SKILL",
        Path.home() / ".codex" / "skills" / "literature-downloader",
    )
).expanduser()
BASE_DOWNLOADER = BASE_SKILL_DIR / "scripts" / "download_literature.py"
MERGE_SCRIPT = BASE_SKILL_DIR / "scripts" / "merge_pdf_supplements.py"
PDF_MAGIC = b"%PDF-"
VERIFY_HINTS = (
    "cloudflare",
    "captcha",
    "verify you are human",
    "verify that you are human",
    "checking your browser",
    "just a moment",
    "security check",
    "human verification",
    "making sure you're not a bot",
    "anubis",
    "downloading timeout",
    "heavy usage",
    "perfdrive",
    "botmanager",
    "validate.perfdrive.com",
    "安全验证",
    "验证您是真人",
)
PDF_ERROR_HINTS = (
    b"downloading timeout",
    b"heavy usage",
    b"validate.perfdrive.com",
    b"botmanager",
    b"access denied",
)
SUPPLEMENT_HINTS = (
    "supporting information",
    "supplementary",
    "supplemental",
    "supplement",
    "supplementary materials",
    "supporting materials",
    "materials and methods",
    "appendix",
    "additional file",
    "additional information",
    "suppl",
    "suppinfo",
    "si_",
    "_si",
    "_sm",
)


@dataclasses.dataclass
class ChromeCandidate:
    url: str
    kind: str
    label: str
    source_tab: str = ""


@dataclasses.dataclass(frozen=True)
class PublisherStrategy:
    key: str
    name: str
    main_pdf_method: str
    supplement_method: str
    failure_signals: tuple[str, ...]
    tested_dois: tuple[str, ...]


PUBLISHER_STRATEGIES: dict[str, PublisherStrategy] = {
    "aps": PublisherStrategy(
        key="aps",
        name="American Physical Society / Physical Review",
        main_pdf_method=(
            "Prefer direct/API harvest. If browser fallback is needed, open the APS abstract page, "
            "then use the same-origin page to fetch the official APS /pdf/ DOI URL before raw PDF navigation."
        ),
        supplement_method="Usually no supplement; inspect the abstract/landing page for visible supporting-material links.",
        failure_signals=("APS /pdf/ navigation may show verification", "Direct harvest can be mislabeled as supplement"),
        tested_dois=(
            "10.1103/physrevb.61.10267",
            "10.1103/physrevlett.86.268",
            "10.1103/physrevresearch.2.013377",
        ),
    ),
    "science": PublisherStrategy(
        key="science",
        name="Science / AAAS",
        main_pdf_method="Use Chrome-authorized official /doi/pdf/<doi>?download=true; direct HTTP often returns 403.",
        supplement_method=(
            "Open the article page, extract visible DOWNLOAD supplement links, download them through Chrome, "
            "and merge PDF supplements with the article PDF."
        ),
        failure_signals=("Direct PDF 403", "Supplement links may include versioned _sm.vN.pdf files or zip archives"),
        tested_dois=("10.1126/science.1222360", "10.1126/science.aav3392", "10.1126/science.aao1797"),
    ),
    "scipost": PublisherStrategy(
        key="scipost",
        name="SciPost",
        main_pdf_method=(
            "Open the SciPost article page in real Chrome, click/read the visible pdf control, then same-origin "
            "fetch the official /pdf URL from that page."
        ),
        supplement_method="Usually no supplement; inspect visible links on the article page.",
        failure_signals=("Raw HTTP may show Anubis bot check", "Chrome PDF viewer may open without saving"),
        tested_dois=("10.21468/scipostphys.7.5.061",),
    ),
    "wiley": PublisherStrategy(
        key="wiley",
        name="Wiley Online Library",
        main_pdf_method=(
            "Open the article page first and click PDF/Download PDF. If a reader opens without saving, "
            "same-origin fetch the /doi/pdfdirect/<doi> URL from the authorized Wiley page."
        ),
        supplement_method="Use visible downloadSupplement links; for PDF supplements, fetch from the same authorized page and merge.",
        failure_signals=("Direct PDF/XML 403", "Reader opens but no new download", "Existing same-title PDF must not count unless requested"),
        tested_dois=("10.1002/anie.202101120", "10.1002/anie.200805257"),
    ),
    "acs": PublisherStrategy(
        key="acs",
        name="American Chemical Society",
        main_pdf_method="Try official /doi/pdf/<doi>?download=true through Chrome authorization, then the article page PDF control.",
        supplement_method="Extract Supporting Information links from the article page; merge PDF SI and keep non-PDF SI.",
        failure_signals=("Cloudflare or browser verification can appear", "Stop immediately on captcha/verification"),
        tested_dois=("10.1021/jacs.0c02808",),
    ),
    "pnas": PublisherStrategy(
        key="pnas",
        name="PNAS",
        main_pdf_method="Try official /doi/pdf/<doi> and the landing-page PDF control through Chrome authorization.",
        supplement_method="Extract Supporting Information links from the article page; merge PDF SI and keep non-PDF SI.",
        failure_signals=("Browser may open a PDF without creating a download",),
        tested_dois=("10.1073/pnas.0504892102",),
    ),
    "ieee": PublisherStrategy(
        key="ieee",
        name="IEEE Xplore",
        main_pdf_method=(
            "Open only the DOI landing page in Chrome, click the visible PDF control, extract the official "
            "stampPDF/getPDF.jsp URL from stamp.jsp, then navigate Chrome to that URL and validate the download."
        ),
        supplement_method="Skip supplement discovery by default for IEEE journal articles.",
        failure_signals=(
            "Institutional login",
            "stamp.jsp opens without exposing getPDF.jsp",
            "Raw HTTP/script fetch returns HTML",
            "Browser getPDF navigation creates an HTML fake PDF",
        ),
        tested_dois=("10.1109/3.53394", "10.1109/3.89946", "10.1109/3.511545"),
    ),
    "optica": PublisherStrategy(
        key="optica",
        name="Optica Publishing Group / OSA",
        main_pdf_method=(
            "Open only the DOI landing page, extract the actual uri= from the resolved Optica URL, then use visible "
            "Get PDF/PDF Article controls or that exact uri for one PDF attempt. Do not infer viewmedia paths from DOI alone."
        ),
        supplement_method="Inspect article page links for supplemental materials; merge PDF supplements and keep non-PDF supplements.",
        failure_signals=("Access/login page", "PDF viewer opens without download", "heavy usage/downloading timeout", "PerfDrive/BotManager", "suspiciously small PDF"),
        tested_dois=("10.1364/josab.9.000405", "10.1364/ol.41.003936", "10.1364/oe.23.015616"),
    ),
    "aip": PublisherStrategy(
        key="aip",
        name="AIP Publishing",
        main_pdf_method=(
            "Open DOI landing page, extract the visible article-pdf link, and save the Chrome PDF viewer token URL when available."
        ),
        supplement_method="AIP supplementary material can be zip; keep non-PDF supplements and merge PDF supplements if present.",
        failure_signals=("Access/login page", "Cloudflare/browser verification", "PDF viewer opens without download"),
        tested_dois=("10.1063/5.0188658", "10.1063/1.1848192", "10.1063/5.0089925", "10.1063/1.5085504"),
    ),
    "generic": PublisherStrategy(
        key="generic",
        name="Generic DOI / Publisher",
        main_pdf_method="Prefer direct/API retrieval, then DOI resolver and visible PDF controls in Chrome.",
        supplement_method="Inspect visible supplement/supporting-material links and download legal, accessible files.",
        failure_signals=("Login", "captcha", "Cloudflare", "human verification"),
        tested_dois=(),
    ),
}


def publisher_strategy_for(doi: str, original: str) -> PublisherStrategy:
    lower_doi = doi.lower()
    lower_original = original.lower()
    if lower_doi.startswith("10.1103/") or "journals.aps.org" in lower_original:
        return PUBLISHER_STRATEGIES["aps"]
    if lower_doi.startswith("10.1126/") or "science.org/doi/" in lower_original:
        return PUBLISHER_STRATEGIES["science"]
    if lower_doi.startswith("10.21468/scipostphys.") or "scipost.org" in lower_original:
        return PUBLISHER_STRATEGIES["scipost"]
    if lower_doi.startswith("10.1002/") or "onlinelibrary.wiley.com" in lower_original:
        return PUBLISHER_STRATEGIES["wiley"]
    if lower_doi.startswith("10.1021/") or "pubs.acs.org" in lower_original:
        return PUBLISHER_STRATEGIES["acs"]
    if lower_doi.startswith("10.1073/") or "pnas.org/doi/" in lower_original:
        return PUBLISHER_STRATEGIES["pnas"]
    if lower_doi.startswith("10.1109/") or "ieeexplore.ieee.org" in lower_original:
        return PUBLISHER_STRATEGIES["ieee"]
    if lower_doi.startswith("10.1364/") or "opg.optica.org" in lower_original or "optica.org" in lower_original:
        return PUBLISHER_STRATEGIES["optica"]
    if lower_doi.startswith("10.1063/") or "pubs.aip.org" in lower_original:
        return PUBLISHER_STRATEGIES["aip"]
    return PUBLISHER_STRATEGIES["generic"]


def normalize_doi(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^(doi:\s*)", "", value, flags=re.I)
    value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value, flags=re.I)
    match = re.search(r"10\.\d{4,9}/\S+", value, flags=re.I)
    if not match:
        raise SystemExit(f"Could not find a DOI in: {value}")
    return unquote(match.group(0).rstrip(").,;]"))


def safe_filename(value: str, max_len: int = 120) -> str:
    value = re.sub(r"[\s_]+", "_", value.strip())
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._-")
    return (value or "article")[:max_len].strip("._-") or "article"


def is_pdf(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(5) == PDF_MAGIC
    except OSError:
        return False


def classify_file(path: Path) -> str:
    if is_pdf(path):
        return "pdf"
    suffix = path.suffix.lower().lstrip(".")
    if suffix in {"doc", "docx"}:
        return "docx"
    if suffix in {"xls", "xlsx", "csv", "tsv"}:
        return "spreadsheet"
    if suffix == "zip":
        return "zip"
    if suffix in {"png", "jpg", "jpeg", "tif", "tiff", "gif"}:
        return "image"
    return suffix or "file"


def looks_like_verification(text: str) -> bool:
    lower = text.lower()
    return any(hint in lower for hint in VERIFY_HINTS)


def significant_words(value: str) -> set[str]:
    stop = {
        "the", "and", "with", "from", "into", "onto", "this", "that", "these", "those",
        "using", "based", "study", "article", "report", "communication", "review",
        "angew", "chem", "international", "edition", "journal",
    }
    words = set()
    for token in re.findall(r"[A-Za-z0-9]+", value.lower()):
        if len(token) < 4 or token in stop:
            continue
        words.add(token)
    return words


def find_existing_pdf(downloads_dir: Path, doi: str, title: str, stem: str, result: dict) -> Path | None:
    title_words = significant_words(title)
    stem_words = significant_words(stem.replace("_", " "))
    wanted_words = title_words or stem_words
    doi_token = safe_filename(doi.replace("/", "_")).lower()
    if not wanted_words and not doi_token:
        return None

    best: tuple[float, Path] | None = None
    for path in downloads_dir.glob("*.pdf"):
        if not path.is_file() or not is_pdf(path):
            continue
        name = path.stem.lower()
        if "combined" in name:
            continue
        if doi_token and doi_token in safe_filename(path.stem).lower():
            best = (1.0, path)
            break
        candidate_words = significant_words(path.stem)
        overlap = len(wanted_words & candidate_words)
        if not wanted_words:
            continue
        ratio = overlap / max(1, len(wanted_words))
        if overlap >= 4 and ratio >= 0.45:
            score = ratio + min(overlap, 10) / 100
            if best is None or score > best[0] or (score == best[0] and path.stat().st_mtime > best[1].stat().st_mtime):
                best = (score, path)
    if best:
        result.setdefault("log", []).append(f"Matched existing PDF in Downloads by DOI/title: {best[1]}")
        return best[1]
    return None


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for idx in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{idx}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise SystemExit(f"Could not create unique filename for {path}")


def snapshot_downloads(downloads_dir: Path) -> dict[Path, tuple[float, int]]:
    downloads_dir.mkdir(parents=True, exist_ok=True)
    items: dict[Path, tuple[float, int]] = {}
    for path in downloads_dir.iterdir():
        if path.is_file():
            stat = path.stat()
            items[path] = (stat.st_mtime, stat.st_size)
    return items


def new_downloads(downloads_dir: Path, before: dict[Path, tuple[float, int]]) -> list[Path]:
    found = []
    for path in downloads_dir.iterdir():
        if not path.is_file():
            continue
        if path.name.endswith(".crdownload") or path.name.endswith(".download") or ".crdownload" in path.name:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        old = before.get(path)
        if old is None or stat.st_mtime > old[0] + 0.5 or stat.st_size != old[1]:
            found.append(path)
    return sorted(found, key=lambda item: item.stat().st_mtime)


def wait_for_download(downloads_dir: Path, before: dict[Path, tuple[float, int]], timeout: int) -> list[Path]:
    deadline = time.time() + timeout
    last_new: list[Path] = []
    while time.time() < deadline:
        active = list(downloads_dir.glob("*.crdownload")) + list(downloads_dir.glob("*.download"))
        current = new_downloads(downloads_dir, before)
        if current:
            last_new = current
        if last_new and not active:
            time.sleep(1)
            if not list(downloads_dir.glob("*.crdownload")) and not list(downloads_dir.glob("*.download")):
                return new_downloads(downloads_dir, before)
        time.sleep(1)
    return last_new


def newest_pdf(paths: list[Path]) -> Path | None:
    pdfs = [path for path in paths if path.exists() and is_pdf(path)]
    return pdfs[-1] if pdfs else None


def is_acceptable_main_pdf(path: Path, doi: str, result: dict) -> bool:
    if not path.exists() or not is_pdf(path):
        return False
    try:
        data = path.read_bytes()
    except OSError as exc:
        result.setdefault("log", []).append(f"Could not read downloaded PDF for validation {path}: {exc}")
        return False
    lower = data[:200000].lower()
    if any(hint in lower for hint in PDF_ERROR_HINTS):
        result.setdefault("errors", []).append(f"Rejected downloaded PDF-like error page: {path}")
        return False
    if doi.lower().startswith("10.1364/") and len(data) < 120_000:
        result.setdefault("errors", []).append(
            f"Rejected suspiciously small Optica PDF ({len(data)} bytes): {path}"
        )
        return False
    if len(data) < 8_000:
        result.setdefault("errors", []).append(
            f"Rejected suspiciously small PDF ({len(data)} bytes): {path}"
        )
        return False
    return True


def run_osascript(script: str, timeout: int = 60) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return 124, stdout.strip(), (stderr.strip() or f"osascript timed out after {timeout}s")
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def applescript_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def frontmost_app() -> str:
    script = '''
tell application "System Events"
    return name of first application process whose frontmost is true
end tell
'''
    code, out, _ = run_osascript(script, timeout=5)
    return out.strip() if code == 0 else ""


def restore_frontmost_app(app_name: str, result: dict, mode: str = "auto") -> None:
    if mode == "never":
        return
    if not app_name or app_name == "Google Chrome":
        return
    if mode == "auto":
        current = frontmost_app()
        if current != "Google Chrome":
            return
    script = f'''
try
    tell application {applescript_string(app_name)} to activate
end try
'''
    code, out, err = run_osascript(script, timeout=5)
    if code == 0:
        result.setdefault("log", []).append(f"Restored foreground app: {app_name}")
    else:
        result.setdefault("log", []).append(f"Could not restore foreground app {app_name}: {out or err}")


def restore_background_focus(args: argparse.Namespace, previous_app: str, result: dict) -> None:
    if not getattr(args, "foreground_chrome", False):
        restore_frontmost_app(previous_app, result, getattr(args, "focus_restore", "auto"))


def chrome_open(url: str, foreground: bool) -> tuple[bool, str, str]:
    if foreground:
        script = f'''
tell application "Google Chrome"
    activate
    if not (exists window 1) then
        make new window
    end if
    tell window 1
        set newTab to make new tab at end of tabs
        set URL of newTab to {applescript_string(url)}
        set active tab index to (count of tabs)
        return id of newTab
    end tell
end tell
'''
    else:
        script = f'''
set previousApp to ""
try
    tell application "System Events"
        set previousApp to name of first application process whose frontmost is true
    end tell
end try

tell application "Google Chrome"
    if not (exists window 1) then
        make new window
    end if
    tell window 1
        set previousTabIndex to active tab index
        set newTab to make new tab at end of tabs
        set URL of newTab to {applescript_string(url)}
        set newTabId to id of newTab
        try
            set active tab index to previousTabIndex
        end try
        set resultId to newTabId
    end tell
end tell

if previousApp is not "" and previousApp is not "Google Chrome" then
    try
        tell application "System Events"
            set currentApp to name of first application process whose frontmost is true
        end tell
        if currentApp is "Google Chrome" then
            tell application previousApp to activate
        end if
    end try
end if
return resultId
'''
    code, out, err = run_osascript(script, timeout=30)
    return code == 0, out or err, out if code == 0 else ""


def chrome_eval(js: str, result: dict, timeout: int = 20, tab_id: str = "") -> str:
    if tab_id:
        script = f'''
tell application "Google Chrome"
    repeat with w in windows
        repeat with t in tabs of w
            if (id of t as string) is {applescript_string(tab_id)} then
                return execute t javascript {applescript_string(js)}
            end if
        end repeat
    end repeat
end tell
'''
    else:
        script = f'tell application "Google Chrome" to execute active tab of front window javascript {applescript_string(js)}'
    code, out, err = run_osascript(script, timeout=timeout)
    if code != 0:
        result.setdefault("log", []).append(f"Chrome JavaScript failed: {out or err}")
        return ""
    return out


def chrome_set_tab_url(tab_id: str, url: str, result: dict) -> bool:
    script = f'''
tell application "Google Chrome"
    repeat with w in windows
        repeat with t in tabs of w
            if (id of t as string) is {applescript_string(tab_id)} then
                set URL of t to {applescript_string(url)}
                return "ok"
            end if
        end repeat
    end repeat
end tell
'''
    code, out, err = run_osascript(script, timeout=10)
    if code == 0 and out == "ok":
        result.setdefault("log", []).append(f"Navigated Chrome tab to {url}")
        return True
    result.setdefault("log", []).append(f"Could not navigate Chrome tab to {url}: {out or err}")
    return False


def chrome_status(result: dict, tab_id: str = "") -> dict:
    js = r"""
JSON.stringify({
  url: location.href,
  title: document.title || '',
  text: (document.body && document.body.innerText || '').slice(0, 4000)
})
"""
    out = chrome_eval(js, result, timeout=10, tab_id=tab_id)
    if not out:
        return {"url": "", "title": "", "text": ""}
    try:
        return json.loads(out)
    except Exception:
        return {"url": "", "title": "", "text": out}


def chrome_wait_for_status(result: dict, tab_id: str = "", timeout: int = 15) -> dict:
    deadline = time.time() + timeout
    last = {"url": "", "title": "", "text": ""}
    while time.time() < deadline:
        last = chrome_status(result, tab_id=tab_id)
        url = str(last.get("url") or "")
        title = str(last.get("title") or "")
        text = str(last.get("text") or "")
        if url and url != "about:blank" and (title or text):
            return last
        time.sleep(1)
    return last


def chrome_wait_for_pdf_viewer(result: dict, tab_id: str = "", timeout: int = 15) -> dict:
    deadline = time.time() + timeout
    last = {"url": "", "title": "", "text": ""}
    while time.time() < deadline:
        last = chrome_status(result, tab_id=tab_id)
        combined = "\n".join(str(last.get(key, "")) for key in ("url", "title", "text")).lower()
        if "stamp.jsp" in combined or "full-text pdf" in combined or "google scholar reader" in combined:
            return last
        time.sleep(1)
    return last


def chrome_wait_for_pdf_control(result: dict, tab_id: str = "", timeout: int = 30) -> dict:
    js = r"""
(() => {
  const visibleText = (el) => ((el.innerText || el.textContent || el.getAttribute('aria-label') || el.title || '') + '').trim();
  const candidates = Array.from(document.querySelectorAll('a[href], button, [role="button"]'));
  const scored = candidates.map((el) => {
    const href = el.href || el.getAttribute('href') || '';
    const text = visibleText(el);
    const combo = (href + ' ' + text).toLowerCase();
    let score = 0;
    if (combo.match(/(^|\s)pdf($|\s)/)) score += 80;
    if (combo.includes('/pdf')) score += 70;
    if (combo.includes('get pdf')) score += 100;
    if (combo.includes('download pdf')) score += 90;
    if (combo.includes('pdf article')) score += 85;
    if (combo.includes('view pdf')) score += 40;
    if (combo.includes('supplement') || combo.includes('supporting') || combo.includes('citation') || combo.includes('figure')) score -= 100;
    return { href, text, score };
  }).filter((item) => item.score > 0).sort((a, b) => b.score - a.score);
  return JSON.stringify({
    url: location.href,
    title: document.title || '',
    text: (document.body && document.body.innerText || '').slice(0, 4000),
    pdfControlFound: scored.length > 0,
    pdfControl: scored.length ? scored[0] : null
  });
})()
"""
    deadline = time.time() + timeout
    last: dict = {"url": "", "title": "", "text": "", "pdfControlFound": False}
    while time.time() < deadline:
        out = chrome_eval(js, result, timeout=10, tab_id=tab_id)
        if out:
            try:
                last = json.loads(out)
            except Exception:
                last = {"url": "", "title": "", "text": out, "pdfControlFound": False}
        combined = "\n".join(str(last.get(key, "")) for key in ("url", "title", "text")).lower()
        if looks_like_verification(combined) or last.get("pdfControlFound"):
            return last
        if "please wait" not in combined and "chrome-extension://" not in combined and str(last.get("url") or "") not in {"", "about:blank"}:
            return last
        time.sleep(1)
    return last


def ieee_getpdf_url_from_stamp(tab_id: str, doi: str, result: dict) -> str:
    arnumber = ieee_article_number(doi)
    fallback = ""
    if arnumber:
        fallback = f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={arnumber}"
    js = f"""
(() => {{
  const urls = [];
  const add = (value) => {{
    if (!value) return;
    try {{ urls.push(new URL(value, location.href).href); }} catch (_) {{}}
  }};
  document.querySelectorAll('iframe[src], frame[src], embed[src], object[data], a[href]').forEach((el) => {{
    add(el.getAttribute('src') || el.getAttribute('data') || el.getAttribute('href'));
  }});
  const found = urls.find((url) => url.includes('/stampPDF/getPDF.jsp'));
  return found || {json.dumps(fallback)};
}})()
"""
    out = chrome_eval(js, result, timeout=10, tab_id=tab_id).strip()
    if out:
        result.setdefault("log", []).append(f"IEEE getPDF URL discovered: {out}")
    else:
        result.setdefault("log", []).append("IEEE getPDF URL was not found on stamp page.")
    return out


def chrome_extract_links(result: dict, tab_id: str = "") -> list[dict]:
    js = r"""
JSON.stringify([
  ...Array.from(document.querySelectorAll('meta[name="citation_supplementary_material"], meta[name="citation_supplemental_material"]')).map((el) => ({
    href: el.content || '',
    text: 'citation supplementary material',
    title: '',
    aria: '',
    cls: ''
  })),
  ...Array.from(document.querySelectorAll('a[href]')).map((el) => ({
    href: el.href || el.getAttribute('href') || '',
    text: (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' '),
    title: el.getAttribute('title') || '',
    aria: el.getAttribute('aria-label') || '',
    cls: Array.from(el.classList || []).join(' ')
  }))
].filter((x) => x.href))
"""
    out = chrome_eval(js, result, timeout=20, tab_id=tab_id)
    if not out:
        return []
    try:
        links = json.loads(out)
    except Exception as exc:
        result.setdefault("log", []).append(f"Could not parse Chrome link extraction output: {exc}")
        return []
    return links if isinstance(links, list) else []


def chrome_click_link(tab_id: str, href: str, result: dict) -> bool:
    js = f"""
(() => {{
  const target = {json.dumps(href)};
  const withoutQuery = target.split('?')[0];
  const link = Array.from(document.querySelectorAll('a[href]')).find((a) => {{
    const value = a.href || '';
    return value === target || value.split('?')[0] === withoutQuery;
  }});
  if (!link) return 'not-found';
  link.scrollIntoView({{block: 'center'}});
  link.click();
  return 'clicked';
}})()
"""
    out = chrome_eval(js, result, timeout=20, tab_id=tab_id)
    if out == "clicked":
        return True
    result.setdefault("log", []).append(f"Chrome could not click supplement link {href}: {out}")
    return False


def chrome_click_wiley_pdf(tab_id: str, result: dict) -> bool:
    js = r"""
(() => {
  const visibleText = (el) => ((el.innerText || el.textContent || el.getAttribute('aria-label') || el.title || '') + '').trim();
  const candidates = Array.from(document.querySelectorAll('a[href], button, [role="button"]'));
  const scored = candidates.map((el) => {
    const href = el.href || el.getAttribute('href') || '';
    const text = visibleText(el);
    const combo = (href + ' ' + text).toLowerCase();
    let score = 0;
    if (href.includes('/doi/pdf/')) score += 100;
    if (href.includes('/doi/epdf/')) score += 60;
    if (combo.includes('download pdf')) score += 80;
    if (combo.includes('pdf')) score += 30;
    if (combo.includes('view pdf')) score += 20;
    if (combo.includes('figure') || combo.includes('citation') || combo.includes('permissions')) score -= 80;
    return { el, href, text, score };
  }).filter((item) => item.score > 0).sort((a, b) => b.score - a.score);
  if (!scored.length) return JSON.stringify({ clicked: false, reason: 'no-pdf-control' });
  const chosen = scored[0];
  chosen.el.scrollIntoView({ block: 'center' });
  chosen.el.click();
  return JSON.stringify({ clicked: true, href: chosen.href, text: chosen.text, score: chosen.score });
})()
"""
    out = chrome_eval(js, result, timeout=20, tab_id=tab_id)
    try:
        data = json.loads(out) if out else {}
    except Exception:
        data = {"raw": out}
    if data.get("clicked"):
        result.setdefault("log", []).append(f"Clicked Wiley PDF control: {data}")
        return True
    result.setdefault("log", []).append(f"No Wiley PDF control clicked: {data}")
    return False


def chrome_click_main_pdf_control(tab_id: str, result: dict) -> bool:
    js = r"""
(() => {
  const visibleText = (el) => ((el.innerText || el.textContent || el.getAttribute('aria-label') || el.title || '') + '').trim();
  const candidates = Array.from(document.querySelectorAll('a[href], button, [role="button"]'));
  const scored = candidates.map((el) => {
    const href = el.href || el.getAttribute('href') || '';
    const text = visibleText(el);
    const combo = (href + ' ' + text).toLowerCase();
    let score = 0;
    if (combo.match(/(^|\s)pdf($|\s)/)) score += 80;
    if (combo.includes('/pdf')) score += 70;
    if (combo.includes('download pdf')) score += 90;
    if (combo.includes('view pdf')) score += 40;
    if (combo.includes('supplement') || combo.includes('supporting') || combo.includes('citation') || combo.includes('figure')) score -= 100;
    return { el, href, text, score };
  }).filter((item) => item.score > 0).sort((a, b) => b.score - a.score);
  if (!scored.length) return JSON.stringify({ clicked: false, reason: 'no-pdf-control' });
  const chosen = scored[0];
  chosen.el.scrollIntoView({ block: 'center' });
  chosen.el.click();
  return JSON.stringify({ clicked: true, href: chosen.href, text: chosen.text, score: chosen.score });
})()
"""
    out = chrome_eval(js, result, timeout=20, tab_id=tab_id)
    try:
        data = json.loads(out) if out else {}
    except Exception:
        data = {"raw": out}
    if data.get("clicked"):
        result.setdefault("log", []).append(f"Clicked main PDF control: {data}")
        return True
    result.setdefault("log", []).append(f"No main PDF control clicked: {data}")
    return False


def chrome_fetch_best_pdf_link(tab_id: str, stem: str, result: dict, hints: tuple[str, ...]) -> bool:
    scored: list[tuple[int, str, str]] = []
    for item in chrome_extract_links(result, tab_id=tab_id):
        href = str(item.get("href") or "")
        label = " ".join(str(item.get(key) or "") for key in ("text", "title", "aria", "cls", "href"))
        lower = (href + " " + label).lower()
        score = 0
        for hint in hints:
            if hint in lower:
                score += 40
        if "pdf" in lower:
            score += 30
        if "download" in lower:
            score += 20
        if any(bad in lower for bad in ("citation", "figure", "metrics", "email", "share")):
            score -= 80
        if href and score > 0:
            scored.append((score, href, label[:160]))
    if not scored:
        result.setdefault("log", []).append("No PDF-like page link found for same-origin fetch.")
        return False
    scored.sort(reverse=True, key=lambda item: item[0])
    _, href, label = scored[0]
    result.setdefault("log", []).append(f"Fetching best PDF-like link from page: {href} ({label})")
    chrome_fetch_pdf_to_download(tab_id, href, f"{stem}.pdf", result)
    return True


def wiley_pdfdirect_url(doi: str) -> str:
    return f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}"


def scipost_pdf_url(doi: str) -> str | None:
    lower = doi.lower()
    if not lower.startswith("10.21468/scipostphys."):
        return None
    suffix = doi.split("/", 1)[1]
    canonical = re.sub(r"^scipostphys\.", "SciPostPhys.", suffix, flags=re.I)
    return f"https://scipost.org/10.21468/{canonical}/pdf"


def ieee_article_number(doi: str) -> str | None:
    if not doi.lower().startswith("10.1109/"):
        return None
    suffix = doi.split("/", 1)[1]
    match = re.search(r"(\d+)$", suffix)
    return match.group(1) if match else None


def optica_article_parts(doi: str) -> tuple[str, str, str] | None:
    if not doi.lower().startswith("10.1364/"):
        return None
    suffix = doi.split("/", 1)[1]
    parts = suffix.split(".")
    if len(parts) < 3:
        return None
    journal = parts[0].lower()
    volume = str(int(parts[1])) if parts[1].isdigit() else parts[1].lower()
    page = str(int(parts[2])) if parts[2].isdigit() else parts[2].lower()
    return journal, volume, page


def optica_uri(doi: str) -> str | None:
    parts = optica_article_parts(doi)
    if not parts:
        return None
    journal, volume, page = parts
    return f"{journal}-{volume}-{page}"


def optica_uri_from_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    if "optica.org" not in parsed.netloc.lower() and "osapublishing.org" not in parsed.netloc.lower():
        return None
    values = parse_qs(parsed.query).get("uri") or parse_qs(parsed.query).get("URI")
    if values and values[0]:
        return values[0]
    match = re.search(r"([a-z]+-\d+(?:-\d+)+)", parsed.path + "?" + parsed.query, flags=re.I)
    return match.group(1) if match else None


def chrome_fetch_pdf_to_download(tab_id: str, url: str, filename: str, result: dict) -> None:
    js = f"""
(async () => {{
  const url = {json.dumps(url)};
  const filename = {json.dumps(filename)};
  const response = await fetch(url, {{ credentials: 'include' }});
  const contentType = response.headers.get('content-type') || '';
  const blob = await response.blob();
  if (!response.ok || blob.size < 1024) {{
    return JSON.stringify({{ ok: response.ok, status: response.status, contentType, size: blob.size }});
  }}
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 30000);
  return JSON.stringify({{ ok: response.ok, status: response.status, contentType, size: blob.size, download: filename }});
}})()
"""
    out = chrome_eval(js, result, timeout=60, tab_id=tab_id)
    if out:
        result.setdefault("log", []).append(f"Chrome fetch-to-download result: {out}")
    else:
        result.setdefault("log", []).append(f"Chrome fetch-to-download issued for {url}")


def chrome_pdf_viewer_urls(result: dict) -> set[str]:
    script = '''
tell application "Google Chrome"
    set xs to {}
    repeat with w in windows
        repeat with t in tabs of w
            set u to URL of t
            if u contains "chrome-extension://" and u contains "http" then set end of xs to u
        end repeat
    end repeat
    set AppleScript's text item delimiters to "\\n"
    set joined to xs as text
    set AppleScript's text item delimiters to ""
    return joined
end tell
'''
    code, out, err = run_osascript(script, timeout=10)
    if code != 0:
        result.setdefault("log", []).append(f"Could not list Chrome PDF viewer URLs: {out or err}")
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def underlying_pdf_url_from_viewer(viewer_url: str) -> str | None:
    match = re.search(r"https?://.+", viewer_url)
    if not match:
        return None
    url = unquote(match.group(0))
    if ".pdf" not in url.lower():
        return None
    return url


def download_pdf_url(url: str, target: Path, result: dict) -> Path | None:
    final_path = target if not target.exists() else unique_path(target)
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/pdf,*/*;q=0.8",
    }
    parsed = urlparse(url)
    if parsed.netloc.endswith("opg.optica.org") and "/directpdfaccess/" in parsed.path.lower():
        match = re.search(r"/([^/]+)\.pdf$", parsed.path, flags=re.I)
        if match:
            uri = match.group(1)
            journal = uri.split("-", 1)[0]
            headers["Referer"] = f"https://opg.optica.org/{journal}/fulltext.cfm?uri={uri}"
    request = Request(
        url,
        headers=headers,
    )
    try:
        with urlopen(request, timeout=60) as response:
            data = response.read()
            content_type = response.headers.get("content-type", "")
    except Exception as exc:
        result.setdefault("log", []).append(f"Could not download PDF viewer URL {url}: {exc}")
        return None
    if len(data) < 1024 or not data.startswith(PDF_MAGIC):
        result.setdefault("log", []).append(
            f"Rejected PDF viewer URL {url}: content_type={content_type!r}, size={len(data)}"
        )
        return None
    lower = data[:200000].lower()
    if any(hint in lower for hint in PDF_ERROR_HINTS):
        result.setdefault("log", []).append(f"Rejected PDF viewer URL error page {url}: size={len(data)}")
        return None
    parsed = urlparse(url)
    if parsed.netloc.endswith("opg.optica.org") and "/directpdfaccess/" in parsed.path.lower() and len(data) < 120_000:
        result.setdefault("log", []).append(f"Rejected suspiciously small Optica PDF viewer URL {url}: size={len(data)}")
        return None
    final_path.write_bytes(data)
    result.setdefault("log", []).append(f"Downloaded PDF from Chrome PDF viewer URL: {final_path}")
    return final_path


def download_from_new_pdf_viewer_urls(
    before_urls: set[str],
    target: Path,
    result: dict,
    timeout: int = 12,
) -> Path | None:
    deadline = time.time() + timeout
    seen = set(before_urls)
    while time.time() < deadline:
        after_urls = chrome_pdf_viewer_urls(result)
        for viewer_url in sorted(after_urls - seen):
            seen.add(viewer_url)
            pdf_url = underlying_pdf_url_from_viewer(viewer_url)
            if not pdf_url:
                continue
            result.setdefault("chrome_opened_urls", []).append(viewer_url)
            path = download_pdf_url(pdf_url, target, result)
            if path:
                return path
        time.sleep(1)
    return None


def chrome_click_pdf_viewer_download_button(tab_id: str, result: dict) -> bool:
    """Click the visible PDF-reader download button when publisher JS cannot save it.

    IEEE Xplore can render the real PDF inside Chrome/Google Scholar Reader while
    returning HTML to same-origin fetches. This UI click is a last-resort action:
    it briefly focuses Chrome, clicks the reader's top-right download control by
    window-relative coordinates, then restores the prior foreground app.
    """
    script = '''
set previousApp to ""
try
    tell application "System Events"
        set previousApp to name of first application process whose frontmost is true
    end tell
end try

set targetTabId to __TAB_ID__

tell application "Google Chrome"
    repeat with w in windows
        set tabIndex to 0
        repeat with t in tabs of w
            set tabIndex to tabIndex + 1
            if (id of t as string) is targetTabId then
                set index of w to 1
                set active tab index of w to tabIndex
                exit repeat
            end if
        end repeat
    end repeat
end tell

tell application "Google Chrome" to activate
delay 0.3

tell application "System Events"
    tell process "Google Chrome"
        set frontmost to true
        set windowPos to position of front window
        set windowSize to size of front window
        set buttonX to (item 1 of windowPos) + (item 1 of windowSize) - 126
        set buttonY to (item 2 of windowPos) + 94
        click at {buttonX, buttonY}
    end tell
end tell

delay 0.2
if previousApp is not "" and previousApp is not "Google Chrome" then
    try
        tell application previousApp to activate
    end try
end if
return "clicked"
'''
    script = script.replace("__TAB_ID__", applescript_string(tab_id))
    code, out, err = run_osascript(script, timeout=10)
    if code == 0:
        result.setdefault("log", []).append("Clicked Chrome/Google Scholar PDF viewer download button.")
        return True
    result.setdefault("log", []).append(f"Could not click PDF viewer download button: {out or err}")
    return False


def accept_new_main_pdf(paths: list[Path], target: Path, doi: str, result: dict) -> Path | None:
    for path in paths:
        if path.exists() and path.suffix.lower() == ".pdf" and not is_pdf(path):
            try:
                path.unlink()
                result.setdefault("deleted_files", []).append(str(path))
                result.setdefault("log", []).append(f"Deleted rejected non-PDF download: {path}")
            except OSError as exc:
                result.setdefault("log", []).append(f"Could not delete rejected non-PDF download {path}: {exc}")
    for path in reversed([p for p in paths if p.exists() and is_pdf(p)]):
        if not is_acceptable_main_pdf(path, doi, result):
            try:
                path.unlink()
                result.setdefault("deleted_files", []).append(str(path))
            except OSError as exc:
                result.setdefault("log", []).append(f"Could not delete rejected PDF {path}: {exc}")
            continue
        final_path = target if not target.exists() else unique_path(target)
        if path.resolve() != final_path.resolve():
            path.rename(final_path)
        result.setdefault("log", []).append(f"Chrome downloaded main PDF: {final_path}")
        return final_path
    return None


def chrome_matching_tab_ids(url_patterns: tuple[str, ...], result: dict) -> list[str]:
    pattern_items = ", ".join(applescript_string(item) for item in url_patterns)
    script = f'''
tell application "Google Chrome"
    set urlPatterns to {{{pattern_items}}}
    set xs to {{}}
    repeat with w in windows
        repeat with t in tabs of w
            set u to URL of t
            set matched to false
            repeat with p in urlPatterns
                if p is not "" and u contains p then set matched to true
            end repeat
            if matched then
                try
                    set end of xs to id of t as string
                end try
            end if
        end repeat
    end repeat
    set AppleScript's text item delimiters to "\\n"
    set joined to xs as text
    set AppleScript's text item delimiters to ""
    return joined
end tell
'''
    code, out, err = run_osascript(script, timeout=10)
    if code != 0:
        result.setdefault("log", []).append(f"Could not list matching Chrome tabs: {out or err}")
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def collect_optica_download_page_statuses(result: dict) -> None:
    for tab_id in chrome_matching_tab_ids(("opg.optica.org", "osapublishing.org"), result):
        status = chrome_status(result, tab_id=tab_id)
        url = str(status.get("url") or "")
        if "viewmedia.cfm" not in url and "directpdfaccess" not in url:
            continue
        result.setdefault("chrome_optica_download_pages", []).append(status)
        combined = "\n".join(str(status.get(key, "")) for key in ("url", "title", "text"))
        if looks_like_verification(combined):
            result["needs_user_action"] = True
            result.setdefault("errors", []).append(
                f"Optica download page reported timeout/verification at {url}; stopping Optica attempts."
            )


def chrome_close_related(urls: list[str], doi: str, result: dict) -> None:
    patterns = [doi, doi.lower(), quote(doi, safe=""), quote(doi, safe="/").replace("/", "%2F")]
    patterns.extend(url for url in urls if url)
    for page_key in ("chrome_pages", "chrome_supplement_pages"):
        for page in result.get(page_key, []) or []:
            if isinstance(page, dict) and page.get("url"):
                patterns.append(str(page["url"]))
    arnumber = ieee_article_number(doi)
    if arnumber:
        patterns.extend([f"arnumber={arnumber}", f"/document/{arnumber}", f"arnumber%3D{arnumber}"])
    uri = optica_uri(doi)
    if uri:
        patterns.extend([uri, quote(uri, safe="")])
    if doi.lower().startswith("10.1063/"):
        patterns.extend(["pubs.aip.org/aip/article-pdf/doi/" + doi, "pubs.aip.org/aip/article/doi/" + doi])
    pattern_items = ", ".join(applescript_string(item) for item in patterns)
    tab_id_items = ", ".join(applescript_string(str(item)) for item in result.get("chrome_opened_tab_ids", []) if item)
    script = f'''
tell application "Google Chrome"
    set closePatterns to {{{pattern_items}}}
    set closeTabIds to {{{tab_id_items}}}
    repeat with w in windows
        set closeIndexes to {{}}
        repeat with i from 1 to count of tabs of w
            set t to tab i of w
            set tabURL to URL of t
            set tabIdText to ""
            try
                set tabIdText to id of t as string
            end try
            set shouldClose to false
            repeat with tabIdPattern in closeTabIds
                if tabIdPattern is not "" and tabIdText is tabIdPattern then set shouldClose to true
            end repeat
            repeat with p in closePatterns
                if p is not "" and tabURL contains p then set shouldClose to true
            end repeat
            if shouldClose then set end of closeIndexes to i
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
        result.setdefault("log", []).append(f"Could not close Chrome tabs: {out or err}")


def supplement_guesses(doi: str, original: str) -> list[ChromeCandidate]:
    candidates: list[ChromeCandidate] = []
    seen: set[str] = set()

    def add(url: str, label: str) -> None:
        if url and url not in seen:
            seen.add(url)
            candidates.append(ChromeCandidate(url=url, kind="supplement", label=label))

    lower = doi.lower()
    if "science.org/doi/" in original.lower() or lower.startswith("10.1126/"):
        article_code = doi.rsplit(".", 1)[-1].rsplit("/", 1)[-1]
        add(f"https://www.science.org/doi/suppl/{doi}/suppl_file/{article_code}_SM.pdf?download=true", "Science supplementary materials PDF")
        add(f"https://www.science.org/doi/suppl/{doi}/suppl_file/{article_code}_SM.pdf", "Science supplementary materials PDF")
    return candidates


def aps_journal_slug_and_doi(doi: str) -> tuple[str, str] | None:
    lower = doi.lower()
    journal_map = {
        "physrevb.": ("prb", "PhysRevB."),
        "physrevlett.": ("prl", "PhysRevLett."),
        "physrevx.": ("prx", "PhysRevX."),
        "physrevresearch.": ("prresearch", "PhysRevResearch."),
    }
    if not lower.startswith("10.1103/"):
        return None
    suffix = doi.split("/", 1)[1]
    suffix_lower = suffix.lower()
    for prefix, (slug, canonical_prefix) in journal_map.items():
        if suffix_lower.startswith(prefix):
            rest = suffix[len(prefix):]
            return slug, f"10.1103/{canonical_prefix}{rest}"
    return None


def aps_pdf_url(doi: str) -> str | None:
    aps = aps_journal_slug_and_doi(doi)
    if not aps:
        return None
    slug, aps_doi = aps
    return f"https://journals.aps.org/{slug}/pdf/{aps_doi}"


def publisher_candidates(doi: str, original: str) -> list[ChromeCandidate]:
    candidates: list[ChromeCandidate] = []
    seen: set[str] = set()

    def add(url: str, kind: str, label: str) -> None:
        if url and url not in seen:
            seen.add(url)
            candidates.append(ChromeCandidate(url=url, kind=kind, label=label))

    lower = doi.lower()
    if "science.org/doi/" in original.lower() or lower.startswith("10.1126/"):
        add(f"https://www.science.org/doi/pdf/{doi}?download=true", "main", "Science PDF download")
        add(f"https://www.science.org/doi/epdf/{doi}", "main", "Science ePDF")
        add(f"https://www.science.org/doi/{doi}", "main", "Science landing")
    if lower.startswith("10.1021/"):
        add(f"https://pubs.acs.org/doi/pdf/{doi}?download=true", "main", "ACS PDF download")
        add(f"https://pubs.acs.org/doi/{doi}", "main", "ACS landing")
    if lower.startswith("10.1002/"):
        add(f"https://onlinelibrary.wiley.com/doi/{doi}", "main", "Wiley landing")
        add(f"https://onlinelibrary.wiley.com/doi/pdf/{doi}", "main", "Wiley PDF")
    if lower.startswith("10.1073/"):
        add(f"https://www.pnas.org/doi/pdf/{doi}", "main", "PNAS PDF")
        add(f"https://www.pnas.org/doi/{doi}", "main", "PNAS landing")
    if lower.startswith("10.1109/"):
        add(f"https://doi.org/{doi}", "main", "IEEE DOI landing")
    if lower.startswith("10.1364/"):
        add(f"https://doi.org/{doi}", "main", "Optica DOI landing")
    if lower.startswith("10.1063/"):
        add(f"https://doi.org/{doi}", "main", "AIP DOI landing")
        add(f"https://pubs.aip.org/aip/article-pdf/doi/{doi}", "main", "AIP article PDF")
        add(f"https://pubs.aip.org/aip/article/doi/{doi}", "main", "AIP landing")
    if lower.startswith("10.21468/scipostphys."):
        suffix = doi.split("/", 1)[1]
        canonical = re.sub(r"^scipostphys\.", "SciPostPhys.", suffix, flags=re.I)
        # SciPost DOI URLs are case-sensitive in practice; the DOI resolver
        # lands on the canonical mixed-case page, while the page's own PDF link
        # is the most reliable browser-triggered route.
        add(f"https://scipost.org/10.21468/{canonical}", "main", "SciPost landing")
        add(f"https://scipost.org/10.21468/{canonical}/pdf", "main", "SciPost PDF")
    aps = aps_journal_slug_and_doi(doi)
    if aps:
        slug, aps_doi = aps
        add(f"https://journals.aps.org/{slug}/abstract/{aps_doi}", "main", "APS landing")
        add(f"https://journals.aps.org/{slug}/pdf/{aps_doi}", "main", "APS PDF")
    if original.startswith("http"):
        add(original, "main", "Original URL")
    add(f"https://doi.org/{doi}", "main", "DOI")
    return candidates


def landing_candidates(doi: str, original: str) -> list[str]:
    urls: list[str] = []
    if original.startswith("http"):
        urls.append(original)
    for candidate in publisher_candidates(doi, original):
        if "landing" in candidate.label.lower() or candidate.url.startswith("https://doi.org/"):
            urls.append(candidate.url)
    seen: set[str] = set()
    deduped = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def run_direct_downloader(args: argparse.Namespace, result: dict) -> dict | None:
    cmd = [
        sys.executable,
        str(BASE_DOWNLOADER),
        args.input,
        "--downloads",
        str(Path(args.downloads).expanduser()),
        "--safari",
        "never",
    ]
    if args.unpaywall_email:
        cmd.extend(["--unpaywall-email", args.unpaywall_email])
    if args.dry_run:
        cmd.append("--dry-run")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.stdout.strip():
        try:
            data = json.loads(proc.stdout)
            result["direct_result"] = data
            return data
        except Exception:
            result.setdefault("log", []).append(f"Direct downloader emitted non-JSON output: {proc.stdout[:500]}")
    if proc.stderr.strip():
        result.setdefault("log", []).append(proc.stderr.strip())
    return None


def promote_direct_pdf_to_main(direct: dict | None, downloads_dir: Path, result: dict) -> Path | None:
    if not direct or direct.get("main_pdf"):
        return None
    stem = direct.get("stem")
    files = direct.get("files") or []
    for item in files:
        if not isinstance(item, dict):
            continue
        path_value = item.get("path")
        source_url = str(item.get("source_url") or "").lower()
        if not path_value:
            continue
        path = Path(path_value).expanduser()
        if not path.exists() or not is_pdf(path):
            continue
        high_confidence_main = (
            "fulltext" in source_url
            or "/pdf/" in source_url
            or source_url.endswith(".pdf")
            or "journals/articles" in source_url
            or item.get("kind") == "pdf"
        )
        if not high_confidence_main:
            continue
        target = downloads_dir / f"{safe_filename(str(stem))}.pdf" if stem else path
        if path.resolve() != target.resolve():
            target = unique_path(target)
            path.rename(target)
            path = target
            item["path"] = str(path)
        direct["main_pdf"] = str(path)
        direct["status"] = "ok"
        direct["needs_user_action"] = False
        direct["errors"] = []
        result.setdefault("log", []).append(f"Promoted direct/API PDF to main article PDF: {path}")
        return path
    return None


def stem_from_direct(direct: dict | None, doi: str) -> str:
    if direct and direct.get("stem"):
        return safe_filename(str(direct["stem"]))
    return safe_filename(doi.replace("/", "_"))


def chrome_download_main(args: argparse.Namespace, doi: str, stem: str, result: dict) -> Path | None:
    downloads_dir = Path(args.downloads).expanduser().resolve()
    target = downloads_dir / f"{stem}.pdf"
    opened: list[str] = []
    for candidate in publisher_candidates(doi, args.input)[: max(1, args.max_chrome_candidates)]:
        previous_app = frontmost_app() if not args.foreground_chrome else ""
        before = snapshot_downloads(downloads_dir)
        before_viewer_urls = chrome_pdf_viewer_urls(result)
        opened.append(candidate.url)
        result.setdefault("chrome_opened_urls", []).append(candidate.url)
        result.setdefault("chrome_attempts", []).append(dataclasses.asdict(candidate))
        ok, message, tab_id = chrome_open(candidate.url, foreground=args.foreground_chrome)
        restore_background_focus(args, previous_app, result)
        if tab_id:
            result.setdefault("chrome_opened_tab_ids", []).append(tab_id)
        if not ok:
            result.setdefault("log", []).append(f"Chrome open failed for {candidate.url}: {message}")
            downloaded_after_open = wait_for_download(downloads_dir, before, min(args.timeout, 20))
            restore_background_focus(args, previous_app, result)
            path_after_open = newest_pdf(downloaded_after_open)
            if path_after_open:
                final_path = target if not target.exists() else unique_path(target)
                if path_after_open.resolve() != final_path.resolve():
                    path_after_open.rename(final_path)
                result.setdefault("log", []).append(
                    f"Chrome downloaded main PDF despite tab-id error: {final_path}"
                )
                restore_background_focus(args, previous_app, result)
                return final_path
            continue
        time.sleep(min(args.settle_seconds, 2))
        status = chrome_wait_for_status(result, tab_id=tab_id, timeout=max(args.settle_seconds, 15))
        result.setdefault("chrome_pages", []).append(status)
        combined = "\n".join(str(status.get(key, "")) for key in ("url", "title", "text"))
        if looks_like_verification(combined):
            result["needs_user_action"] = True
            result.setdefault("errors", []).append(
                f"Chrome encountered verification/captcha at {status.get('url') or candidate.url}; stopping."
            )
            break
        if doi.lower().startswith("10.1002/") and "landing" in candidate.label.lower():
            if chrome_click_wiley_pdf(tab_id, result):
                time.sleep(2)
            chrome_fetch_pdf_to_download(tab_id, wiley_pdfdirect_url(doi), f"{stem}.pdf", result)
        if doi.lower().startswith("10.1103/") and "landing" in candidate.label.lower():
            pdf_url = aps_pdf_url(doi)
            if pdf_url:
                chrome_fetch_pdf_to_download(tab_id, pdf_url, f"{stem}.pdf", result)
        if doi.lower().startswith("10.1109/") and "landing" in candidate.label.lower():
            result.setdefault("log", []).append(
                "IEEE: skipping same-origin stamp.jsp fetch because it can save HTML fake PDFs."
            )
        if doi.lower().startswith("10.1364/") and "landing" in candidate.label.lower():
            status = chrome_wait_for_pdf_control(result, tab_id=tab_id, timeout=max(args.timeout, 30))
            result.setdefault("chrome_optica_pages", []).append(status)
            combined = "\n".join(str(status.get(key, "")) for key in ("url", "title", "text"))
            if looks_like_verification(combined):
                result["needs_user_action"] = True
                result.setdefault("errors", []).append(
                    f"Chrome encountered verification/captcha at {status.get('url') or candidate.url}; stopping."
                )
                break
            if not args.allow_disruptive_browser_clicks:
                result["needs_user_action"] = True
                result.setdefault("errors", []).append(
                    "Optica Get PDF requires a site-initiated browser click that can bring Chrome to the foreground; "
                    "rerun with --allow-disruptive-browser-clicks when the computer is idle, or download manually."
                )
                result.setdefault("log", []).append(
                    "Skipped Optica Get PDF click because disruptive browser clicks are disabled by default."
                )
                break
            before_optica_click = snapshot_downloads(downloads_dir)
            if chrome_click_main_pdf_control(tab_id, result):
                restore_background_focus(args, previous_app, result)
                downloaded = wait_for_download(downloads_dir, before_optica_click, max(args.timeout, 25))
                restore_background_focus(args, previous_app, result)
                accepted = accept_new_main_pdf(downloaded, target, doi, result)
                if accepted:
                    restore_background_focus(args, previous_app, result)
                    return accepted
                result.setdefault("log", []).append("Optica Get PDF click did not create a valid PDF download.")
            else:
                result.setdefault("log", []).append("Optica: no visible Get PDF/PDF Article control after waiting.")
            direct_landing_url = str((result.get("direct_result") or {}).get("landing_url") or "")
            uri = optica_uri_from_url(str(status.get("url") or "")) or optica_uri_from_url(direct_landing_url)
            if uri:
                journal = uri.split("-", 1)[0]
                chrome_fetch_pdf_to_download(
                    tab_id,
                    f"https://opg.optica.org/{journal}/viewmedia.cfm?uri={uri}&seq=0",
                    f"{stem}.pdf",
                    result,
                )
                restore_background_focus(args, previous_app, result)
            else:
                result.setdefault("log", []).append("Optica: could not extract resolved uri=; not guessing viewmedia URL from DOI.")
            collect_optica_download_page_statuses(result)
            if result.get("needs_user_action"):
                break
            continue
        if doi.lower().startswith("10.1063/") and "landing" in candidate.label.lower():
            chrome_fetch_best_pdf_link(tab_id, stem, result, ("article-pdf", "download pdf", "pdf"))
            chrome_fetch_pdf_to_download(
                tab_id,
                f"https://pubs.aip.org/aip/article-pdf/doi/{doi}",
                f"{stem}.pdf",
                result,
            )
        clicked_main_pdf_control = False
        if "landing" in candidate.label.lower() or "doi" in candidate.label.lower():
            clicked_main_pdf_control = chrome_click_main_pdf_control(tab_id, result)
        if doi.lower().startswith("10.1109/") and clicked_main_pdf_control:
            viewer_status = chrome_wait_for_pdf_viewer(result, tab_id=tab_id, timeout=max(args.settle_seconds, 15))
            result.setdefault("chrome_pdf_viewer_pages", []).append(viewer_status)
            getpdf_url = ieee_getpdf_url_from_stamp(tab_id, doi, result)
            if getpdf_url:
                before_getpdf = snapshot_downloads(downloads_dir)
                result.setdefault("chrome_opened_urls", []).append(getpdf_url)
                if chrome_set_tab_url(tab_id, getpdf_url, result):
                    downloaded = wait_for_download(downloads_dir, before_getpdf, max(args.timeout, 20))
                    restore_background_focus(args, previous_app, result)
                    accepted = accept_new_main_pdf(downloaded, target, doi, result)
                    if accepted:
                        restore_background_focus(args, previous_app, result)
                        return accepted
                    result.setdefault("log", []).append("IEEE getPDF navigation did not create a valid PDF download.")
            if args.allow_active_window_click and chrome_click_pdf_viewer_download_button(tab_id, result):
                downloaded = wait_for_download(downloads_dir, before, max(args.timeout, 15))
                restore_background_focus(args, previous_app, result)
                accepted = accept_new_main_pdf(downloaded, target, doi, result)
                if accepted:
                    restore_background_focus(args, previous_app, result)
                    return accepted
            elif not args.allow_active_window_click:
                result.setdefault("log", []).append(
                    "PDF viewer is open, but active-window mouse clicking is disabled; returning needs_user_action."
                )
        if doi.lower().startswith("10.21468/scipostphys.") and "landing" in candidate.label.lower():
            pdf_url = scipost_pdf_url(doi)
            if pdf_url:
                chrome_fetch_pdf_to_download(tab_id, pdf_url, f"{stem}.pdf", result)
        viewer_path = download_from_new_pdf_viewer_urls(before_viewer_urls, target, result)
        if viewer_path:
            restore_background_focus(args, previous_app, result)
            return viewer_path
        if doi.lower().startswith("10.1364/"):
            collect_optica_download_page_statuses(result)
            if result.get("needs_user_action"):
                break
        downloaded = wait_for_download(downloads_dir, before, args.timeout)
        restore_background_focus(args, previous_app, result)
        accepted = accept_new_main_pdf(downloaded, target, doi, result)
        if accepted:
            restore_background_focus(args, previous_app, result)
            return accepted
        restore_background_focus(args, previous_app, result)
    return None


def chrome_find_supplements(args: argparse.Namespace, doi: str, result: dict) -> list[ChromeCandidate]:
    candidates: list[ChromeCandidate] = []
    seen: set[str] = set()
    for landing_url in landing_candidates(doi, args.input):
        result.setdefault("chrome_opened_urls", []).append(landing_url)
        ok, message, tab_id = chrome_open(landing_url, foreground=args.foreground_chrome)
        if tab_id:
            result.setdefault("chrome_opened_tab_ids", []).append(tab_id)
        if not ok:
            result.setdefault("log", []).append(f"Chrome open failed for supplement extraction {landing_url}: {message}")
            continue
        time.sleep(args.settle_seconds)
        status = chrome_status(result, tab_id=tab_id)
        result.setdefault("chrome_supplement_pages", []).append(status)
        combined = "\n".join(str(status.get(key, "")) for key in ("url", "title", "text"))
        if looks_like_verification(combined):
            result["needs_user_action"] = True
            result.setdefault("errors", []).append(
                f"Chrome encountered verification/captcha while finding supplements at {status.get('url') or landing_url}; stopping."
            )
            return candidates
        for item in chrome_extract_links(result, tab_id=tab_id):
            href = str(item.get("href") or "")
            parsed = urlparse(href)
            if parsed.fragment and not parsed.path.lower().endswith((".pdf", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".csv")):
                continue
            label = " ".join(
                str(item.get(key) or "") for key in ("text", "title", "aria", "cls", "href")
            )
            lower_label = label.lower()
            parsed_path = parsed.path.lower()
            is_figure_or_inline = "figure" in lower_label or "thumbnail" in lower_label or "inline-graphic" in lower_label
            if is_figure_or_inline:
                continue
            if href and href not in seen and any(hint in lower_label or hint in parsed_path for hint in SUPPLEMENT_HINTS):
                seen.add(href)
                candidates.append(ChromeCandidate(url=href, kind="supplement", label=label[:180], source_tab=tab_id))
        if candidates:
            break
    if not candidates:
        for candidate in supplement_guesses(doi, args.input):
            if candidate.url not in seen:
                seen.add(candidate.url)
                candidates.append(candidate)
    result["chrome_supplement_candidates"] = [dataclasses.asdict(candidate) for candidate in candidates]
    return candidates


def chrome_download_supplements(args: argparse.Namespace, doi: str, stem: str, result: dict) -> list[Path]:
    downloads_dir = Path(args.downloads).expanduser().resolve()
    downloaded: list[Path] = []
    if args.max_supplement_candidates <= 0:
        result["chrome_supplement_candidates"] = []
        result.setdefault("log", []).append("Supplement discovery skipped because max_supplement_candidates <= 0.")
        return downloaded
    candidates = chrome_find_supplements(args, doi, result)
    for idx, candidate in enumerate(candidates[: args.max_supplement_candidates], start=1):
        if result.get("needs_user_action"):
            break
        before = snapshot_downloads(downloads_dir)
        result.setdefault("chrome_opened_urls", []).append(candidate.url)
        result.setdefault("chrome_supplement_attempts", []).append(dataclasses.asdict(candidate))
        if candidate.source_tab and chrome_click_link(candidate.source_tab, candidate.url, result):
            found = wait_for_download(downloads_dir, before, args.supplement_timeout)
            if found:
                path = found[-1]
                suffix = path.suffix or Path(urlparse(candidate.url).path).suffix or ".bin"
                target = unique_path(downloads_dir / f"{stem}_si_{idx}{suffix}")
                if path.resolve() != target.resolve():
                    path.rename(target)
                    path = target
                downloaded.append(path)
                result.setdefault("log", []).append(f"Chrome downloaded supplement by clicking page link: {path}")
                continue
            parsed_candidate = urlparse(candidate.url)
            if parsed_candidate.netloc.endswith("wiley.com"):
                suffix = Path(parsed_candidate.path).suffix or ".pdf"
                if "downloadSupplement" in parsed_candidate.path and "file=" in parsed_candidate.query:
                    match = re.search(r"(?:^|&)file=([^&]+)", parsed_candidate.query)
                    if match:
                        suffix = Path(unquote(match.group(1))).suffix or suffix
                chrome_fetch_pdf_to_download(
                    candidate.source_tab,
                    candidate.url,
                    f"{stem}_si_{idx}{suffix}",
                    result,
                )
                found = wait_for_download(downloads_dir, before, args.supplement_timeout)
                if found:
                    path = found[-1]
                    target = unique_path(downloads_dir / f"{stem}_si_{idx}{path.suffix or suffix}")
                    if path.resolve() != target.resolve():
                        path.rename(target)
                        path = target
                    downloaded.append(path)
                    result.setdefault("log", []).append(f"Chrome downloaded Wiley supplement via same-origin fetch: {path}")
                    continue
        ok, message, tab_id = chrome_open(candidate.url, foreground=args.foreground_chrome)
        if tab_id:
            result.setdefault("chrome_opened_tab_ids", []).append(tab_id)
        if not ok:
            result.setdefault("log", []).append(f"Chrome open failed for supplement {candidate.url}: {message}")
            found_after_open = wait_for_download(downloads_dir, before, min(args.supplement_timeout, 20))
            if found_after_open:
                path = found_after_open[-1]
                suffix = path.suffix or Path(urlparse(candidate.url).path).suffix or ".bin"
                target = unique_path(downloads_dir / f"{stem}_si_{idx}{suffix}")
                if path.resolve() != target.resolve():
                    path.rename(target)
                    path = target
                downloaded.append(path)
                result.setdefault("log", []).append(f"Chrome downloaded supplement despite tab-id error: {path}")
                continue
            continue
        time.sleep(args.settle_seconds)
        status = chrome_status(result, tab_id=tab_id)
        combined = "\n".join(str(status.get(key, "")) for key in ("url", "title", "text"))
        if looks_like_verification(combined):
            result["needs_user_action"] = True
            result.setdefault("errors", []).append(
                f"Chrome encountered verification/captcha while downloading supplement at {status.get('url') or candidate.url}; stopping."
            )
            break
        found = wait_for_download(downloads_dir, before, args.supplement_timeout)
        for path in found:
            if not path.exists() or path in downloaded:
                continue
            suffix = path.suffix or Path(urlparse(candidate.url).path).suffix or ".bin"
            target = unique_path(downloads_dir / f"{stem}_si_{idx}{suffix}")
            if path.resolve() != target.resolve():
                path.rename(target)
                path = target
            downloaded.append(path)
            result.setdefault("log", []).append(f"Chrome downloaded supplement: {path}")
            break
    return downloaded


def merge_pdf_supplements(main_pdf: Path, pdf_supplements: list[Path], output: Path, result: dict) -> Path | None:
    if not pdf_supplements:
        return None
    cmd = [sys.executable, str(MERGE_SCRIPT), "--main", str(main_pdf), "--output", str(output)]
    for supplement in pdf_supplements:
        cmd.extend(["--supplement", str(supplement)])
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        result.setdefault("log", []).append(f"Merge failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return None
    return output if output.exists() and is_pdf(output) else None


def delete_pdf_originals_after_merge(main_pdf: Path, pdf_supplements: list[Path], combined: Path | None, result: dict) -> None:
    if not combined or not combined.exists() or not is_pdf(combined):
        return
    deleted: list[str] = []
    for path in [main_pdf, *pdf_supplements]:
        if not path.exists() or path.resolve() == combined.resolve():
            continue
        if not is_pdf(path):
            continue
        try:
            path.unlink()
        except OSError as exc:
            result.setdefault("log", []).append(f"Could not delete original PDF {path}: {exc}")
            continue
        deleted.append(str(path))
    if deleted:
        result.setdefault("deleted_files", []).extend(deleted)
        result.setdefault("log", []).append("Deleted original main/supplement PDFs after combined PDF was created.")


def cleanup_direct_result_original_pdfs(direct: dict, result: dict, keep_original_pdfs: bool) -> None:
    if keep_original_pdfs:
        return
    combined_value = direct.get("combined_pdf")
    if not combined_value:
        return
    combined = Path(combined_value).expanduser()
    if not combined.exists() or not is_pdf(combined):
        return
    deleted: list[str] = []
    kept_files = []
    for item in direct.get("files", []):
        path_value = item.get("path") if isinstance(item, dict) else None
        if not path_value:
            kept_files.append(item)
            continue
        path = Path(path_value).expanduser()
        if path.resolve() == combined.resolve() or not path.exists() or not is_pdf(path):
            kept_files.append(item)
            continue
        try:
            path.unlink()
        except OSError as exc:
            result.setdefault("log", []).append(f"Could not delete original PDF {path}: {exc}")
            kept_files.append(item)
            continue
        deleted.append(str(path))
    if deleted:
        direct["files"] = kept_files
        direct["main_pdf_deleted"] = direct.get("main_pdf") in deleted
        result.setdefault("deleted_files", []).extend(deleted)
        result.setdefault("log", []).append("Deleted direct-download original PDFs after combined PDF was created.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download literature with direct/API first, then Chrome fallback.")
    parser.add_argument("input", nargs="?", help="DOI, DOI URL, or publisher URL")
    parser.add_argument("--downloads", default="~/Downloads", help="Downloads directory; default: ~/Downloads")
    parser.add_argument("--unpaywall-email", help="Email for Unpaywall API; optional")
    parser.add_argument("--timeout", type=int, default=45, help="Chrome download wait timeout in seconds")
    parser.add_argument("--settle-seconds", type=int, default=7, help="Seconds to wait after opening Chrome URL")
    parser.add_argument("--max-chrome-candidates", type=int, default=3, help="Maximum Chrome URLs to try")
    parser.add_argument("--max-supplement-candidates", type=int, default=8, help="Maximum Chrome supplement URLs to try")
    parser.add_argument("--supplement-timeout", type=int, default=20, help="Chrome supplement download wait timeout in seconds")
    parser.add_argument("--foreground-chrome", action="store_true", help="Bring Chrome to the foreground")
    parser.add_argument(
        "--focus-restore",
        choices=("auto", "always", "never"),
        default="auto",
        help="Foreground restore policy after Chrome automation; auto restores only if Chrome is actually frontmost",
    )
    parser.add_argument(
        "--allow-disruptive-browser-clicks",
        action="store_true",
        help="Allow publisher clicks that may bring Chrome to the foreground, such as Optica Get PDF; off by default",
    )
    parser.add_argument(
        "--allow-active-window-click",
        action="store_true",
        help="Allow an unsafe last-resort GUI coordinate click in the active Chrome PDF viewer; off by default",
    )
    parser.add_argument("--keep-tabs", dest="close_tabs", action="store_false", help="Keep Chrome tabs open")
    parser.add_argument("--keep-original-pdfs", action="store_true", help="Keep main/supplement PDFs even after a combined PDF is created")
    parser.add_argument(
        "--use-existing-pdf",
        action="store_true",
        help="Allow a high-confidence existing PDF in Downloads to satisfy the main PDF when no new download occurs",
    )
    parser.add_argument("--dry-run", action="store_true", help="Inspect direct candidates only; do not download")
    parser.add_argument("--self-test", action="store_true", help="Run offline self-tests")
    parser.set_defaults(close_tabs=True)
    return parser.parse_args()


def self_test() -> int:
    assert normalize_doi("https://dx.doi.org/10.1021/jacs.0c02808") == "10.1021/jacs.0c02808"
    assert normalize_doi("https://www.science.org/doi/10.1126/science.aao1797") == "10.1126/science.aao1797"
    assert significant_words("Perovskite Oxide Halide Solid Solutions: A Platform for Electrocatalysts")
    assert publisher_strategy_for("10.1126/science.aav3392", "").key == "science"
    assert publisher_strategy_for("10.21468/scipostphys.7.5.061", "").key == "scipost"
    assert publisher_strategy_for("10.1109/3.53394", "").key == "ieee"
    assert publisher_strategy_for("10.1364/josab.9.000405", "").key == "optica"
    assert publisher_strategy_for("10.1063/5.0188658", "").key == "aip"
    assert ieee_article_number("10.1109/3.53394") == "53394"
    assert optica_uri("10.1364/josab.9.000405") == "josab-9-405"
    assert optica_uri_from_url("https://opg.optica.org/josab/viewmedia.cfm?uri=josab-15-2-817&html=true") == "josab-15-2-817"
    assert aps_journal_slug_and_doi("10.1103/physrevlett.114.017001") == (
        "prl",
        "10.1103/PhysRevLett.114.017001",
    )
    assert is_pdf(Path(__file__)) is False
    print("self-test ok")
    return 0


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()
    if not args.input:
        raise SystemExit("DOI or publisher URL is required unless --self-test is used.")

    downloads_dir = Path(args.downloads).expanduser().resolve()
    downloads_dir.mkdir(parents=True, exist_ok=True)
    doi = normalize_doi(args.input)
    strategy = publisher_strategy_for(doi, args.input)
    result: dict = {
        "doi": doi,
        "downloads_dir": str(downloads_dir),
        "publisher_strategy": dataclasses.asdict(strategy),
        "status": "started",
        "files": [],
        "main_pdf": None,
        "needs_user_action": False,
        "errors": [],
        "log": [f"Using publisher strategy: {strategy.key} ({strategy.name})"],
    }

    direct = run_direct_downloader(args, result)
    promote_direct_pdf_to_main(direct, downloads_dir, result)
    if direct and direct.get("status") == "ok" and direct.get("main_pdf"):
        cleanup_direct_result_original_pdfs(direct, result, args.keep_original_pdfs)
        result["status"] = "ok"
        result["main_pdf"] = direct.get("main_pdf")
        result["main_pdf_deleted"] = direct.get("main_pdf_deleted", False)
        result["combined_pdf"] = direct.get("combined_pdf")
        result["files"] = direct.get("files", [])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.dry_run:
        result["status"] = "dry_run"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    stem = stem_from_direct(direct, doi)
    result["stem"] = stem
    title = str((direct or {}).get("title") or "")
    main_pdf = chrome_download_main(args, doi, stem, result)
    if main_pdf is None and args.use_existing_pdf:
        main_pdf = find_existing_pdf(downloads_dir, doi, title, stem, result)
        if main_pdf:
            result["main_pdf_existing_match"] = True
            target = downloads_dir / f"{stem}.pdf"
            if main_pdf.resolve() != target.resolve():
                target = unique_path(target)
                main_pdf.rename(target)
                main_pdf = target
                result.setdefault("log", []).append(f"Renamed existing matched PDF to standard stem: {main_pdf}")
    if main_pdf and main_pdf.exists() and is_pdf(main_pdf):
        if doi.lower().startswith("10.1109/"):
            supplement_paths = []
            result.setdefault("log", []).append("IEEE: skipping supplement discovery by publisher rule.")
        else:
            supplement_paths = chrome_download_supplements(args, doi, stem, result)
        pdf_supplements = [path for path in supplement_paths if is_pdf(path)]
        combined = None
        if pdf_supplements:
            combined = merge_pdf_supplements(
                main_pdf,
                pdf_supplements,
                unique_path(downloads_dir / f"{stem}_combined.pdf"),
                result,
            )
            if combined and not args.keep_original_pdfs:
                delete_pdf_originals_after_merge(main_pdf, pdf_supplements, combined, result)
        result["status"] = "ok"
        result["main_pdf"] = str(main_pdf)
        result["main_pdf_deleted"] = bool(combined and not args.keep_original_pdfs)
        result["combined_pdf"] = str(combined) if combined else None
        deleted_paths = set(result.get("deleted_files", []))
        if str(main_pdf) not in deleted_paths:
            result["files"].append({"path": str(main_pdf), "kind": "pdf", "method": "chrome"})
        for path in supplement_paths:
            if str(path) in deleted_paths:
                continue
            result["files"].append(
                {"path": str(path), "kind": classify_file(path), "method": "chrome", "role": "supplement"}
            )
        if combined:
            result["files"].append({"path": str(combined), "kind": "pdf", "method": "merge", "role": "combined"})
        if args.close_tabs and result.get("chrome_opened_urls") and not result.get("needs_user_action"):
            chrome_close_related(result.get("chrome_opened_urls", []), doi, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    result["status"] = "needs_user_action"
    result["needs_user_action"] = True
    if not result["errors"]:
        result["errors"].append(
            "Main PDF was not downloaded. Check Chrome access/login or manually save the PDF to Downloads."
        )
    if args.close_tabs and result.get("chrome_opened_urls"):
        chrome_close_related(result.get("chrome_opened_urls", []), doi, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2


if __name__ == "__main__":
    sys.exit(main())
