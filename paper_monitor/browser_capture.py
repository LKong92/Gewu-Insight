"""Explicit, reviewable Browser-to-Library capture. No remote fetching or SQL schema.

The trusted workspace creates short-lived tickets. Native WebKit uploads PDF
bytes with a one-purpose token; remote pages never receive it. Only save() adds
papers, placements or resources. Browser adapters can share these same rules.
"""
from __future__ import annotations

import re
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .browser_store import browser_url, history_url
from .pdf_utils import is_valid_pdf_bytes
from .text import clean_text, make_paper_id, normalize_doi
from .storage import PAPER_FILE_TYPES, AUTOMATIC_DEFAULT_FILE_TYPE_RANK, legacy_role_projection

MAX_PDF_BYTES = 64 * 1024 * 1024
CAPTURE_TTL = 20 * 60
FILE_TYPES = set(PAPER_FILE_TYPES) - {"invalid_file"}


def identifier(value: str) -> tuple[str, str]:
    text = unquote(clean_text(str(value or "")))[:8192]
    doi = re.search(r"10\.\d{4,9}/[^\s<>\"?#]+", text, re.I)
    if doi:
        return "doi", normalize_doi(doi.group().rstrip(".,;"))
    arxiv = re.search(r"(?:arxiv[:_]|arxiv\.org/(?:abs|pdf)/)?((?:\d{4}\.\d{4,5}|[a-z-]+/\d{7}))(?:v\d+)?(?:\.pdf)?(?:$|[?#\s])", text, re.I)
    return ("arxiv", arxiv.group(1).lower()) if arxiv else ("", "")


def persistent_url(value: str) -> str:
    try:
        return history_url(value) or ""
    except ValueError:
        return ""


def normalize_snapshot(payload: dict) -> dict:
    url = browser_url(payload.get("url"))
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    cleaned = {key: clean_text(str(metadata.get(key) or ""))[:limit] for key, limit in
               [("title", 1000), ("doi", 512), ("arxiv", 100), ("journal", 300), ("date", 40)]}
    authors = metadata.get("authors", [])
    cleaned["authors"] = [clean_text(x)[:200] for x in authors[:100] if isinstance(x, str) and clean_text(x)] if isinstance(authors, list) else []
    candidates = []
    for value in payload.get("pdf_urls", [])[:8] if isinstance(payload.get("pdf_urls"), list) else []:
        try:
            candidate = browser_url(value)
            if candidate not in candidates:
                candidates.append(candidate)
        except ValueError:
            continue
    if payload.get("is_pdf") is True and url not in candidates:
        candidates.insert(0, url)
    return {"url": url, "metadata": cleaned, "pdf_urls": candidates[:8], "is_pdf": payload.get("is_pdf") is True,
            "origin_paper_id": clean_text(str(payload.get("origin_paper_id") or ""))[:512],
            "tab_id": clean_text(str(payload.get("tab_id") or ""))[:100],
            "snapshot_id": clean_text(str(payload.get("snapshot_id") or ""))[:100],
            "origin_url": persistent_url(str(payload.get("origin_url") or ""))}


@dataclass
class Capture:
    db: str
    snapshot: dict
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    upload_token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    directory: object = field(default_factory=lambda: tempfile.TemporaryDirectory(prefix="gewu-capture-"))
    touched: float = field(default_factory=time.monotonic)
    lock: object = field(default_factory=threading.RLock)
    pdf_ready: bool = False
    pdf_name: str = "Article.pdf"
    pdf_identifier: tuple = ("", "")
    pdf_title: str = ""
    pdf_source_url: str = ""
    pdf_heading: str = ""
    pdf_metadata_title: str = ""
    paper: dict | None = None
    conflict: str = ""
    result: dict | None = None
    resolved: dict = field(default_factory=dict)

    @property
    def path(self) -> Path:
        return Path(self.directory.name) / "capture.pdf"


class BrowserCaptureService:
    def __init__(self):
        self.captures = {}
        self.lock = threading.RLock()

    def begin(self, db: Path, payload: dict) -> Capture:
        snapshot = normalize_snapshot(payload)
        with self.lock:
            self._expire()
            if len(self.captures) >= 16:
                raise ValueError("Close a pending Save to Gewu panel before starting another capture.")
            capture = Capture(str(Path(db).resolve()), snapshot)
            self.captures[capture.token] = capture
            return capture

    def _expire(self):
        for key, value in list(self.captures.items()):
            if time.monotonic() - value.touched > CAPTURE_TTL:
                if value.lock.acquire(blocking=False):
                    try:
                        value.directory.cleanup()
                        del self.captures[key]
                    finally:
                        value.lock.release()

    def get(self, db: Path, token: str, *, upload=False) -> Capture:
        with self.lock:
            self._expire()
            capture = next((c for c in self.captures.values() if secrets.compare_digest(c.upload_token, str(token))), None) if upload else self.captures.get(str(token))
            if not capture or capture.db != str(Path(db).resolve()):
                raise ValueError("This capture expired. Click Save to Gewu again.")
            capture.touched = time.monotonic()
            return capture

    def cancel(self, db: Path, token: str):
        capture = self.get(db, token)
        with capture.lock, self.lock:
            self.captures.pop(capture.token, None)
            capture.directory.cleanup()

    def upload(self, capture: Capture, content: bytes, filename="Article.pdf", source_url=""):
        from . import ui_server as ui
        with capture.lock:
            if capture.result:
                raise ValueError("This capture was already saved.")
            if not content or len(content) > MAX_PDF_BYTES:
                raise ValueError("Choose a PDF up to 64 MB.")
            if not is_valid_pdf_bytes(content):
                raise ValueError("The downloaded file is not a readable PDF. It may be a sign-in page.")
            # Native WebKit supplies the requested candidate, not a URL guessed
            # from the open page. A local file has no asserted download origin.
            if source_url and source_url not in capture.snapshot["pdf_urls"]:
                raise ValueError("The PDF source is not part of this capture. Open Save to Gewu again.")
            capture.path.write_bytes(content)
            capture.pdf_name = Path(filename).name[:200] or "Article.pdf"
            if not capture.pdf_name.lower().endswith(".pdf"):
                capture.pdf_name += ".pdf"
            # Examine title-page evidence only. No reference-list DOI guessing or
            # unbounded network title search during file transfer.
            found = ui.extract_identifier_from_pdf_or_title(capture.path, {}, title_lookup=lambda _: {})
            capture.pdf_identifier = (found.get("kind", ""), found.get("identifier", ""))
            titles = ui.pdf_layout_title_candidates(capture.path, page_limit=1)
            metadata_title, pages = ui.pdf_identifier_page_texts(capture.path, page_limit=1)
            capture.pdf_metadata_title = metadata_title[:1000]
            capture.pdf_heading = clean_text(pages[0] if pages else "")[:350]
            capture.pdf_source_url = source_url
            # Publisher PDFs can place a large DOI heading above the title, and
            # layout extraction may split a multiline title. Prefer a plausible
            # embedded title, then exclude URL headings from layout candidates.
            capture.pdf_title = next((text for text in [metadata_title, *titles]
                                      if ui.plausible_pdf_title_text(text)
                                      and not re.search(r"https?://|\bdoi\.org/", text, re.I)), "")[:1000]
            capture.pdf_ready = True
            capture.paper = None

    @staticmethod
    def suggested_file_type(capture: Capture) -> tuple[str, str]:
        """Suggest only from this file's evidence; never from DOI presence alone."""
        if not capture.pdf_ready:
            return "unknown", ""
        from . import ui_server as ui
        text = " ".join([capture.pdf_name, capture.pdf_metadata_title, capture.pdf_title, capture.pdf_heading]).casefold()
        if re.search(r"supplement(?:ary|al)?[\s_-]*(?:information|material|data|appendix)|supporting[\s_-]*information|\b\w+_moesm\d+_esm\b", text):
            return "supplementary_material", "Supplementary material identified in this PDF."
        if re.search(r"peer[\s_-]*review[\s_-]*(?:file|report)|reviewer[\s_-]*reports?", text):
            return "peer_review_file", "Peer review file identified in this PDF."
        title = " ".join([capture.pdf_metadata_title, capture.pdf_title, (capture.paper or {}).get("title") or ""])
        if re.search(r"(?:^|\s)(?:author correction|publisher correction|correction to|erratum|corrigendum)\b", title, re.I):
            return "correction_notice", "Correction notice identified in the title."
        source = urlsplit(capture.pdf_source_url)
        host, path = (source.hostname or "").lower(), unquote(source.path).lower()
        kind, value = capture.pdf_identifier
        if host in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}:
            source_kind, source_id = identifier(capture.pdf_source_url)
            if source_kind == "arxiv" and re.fullmatch(r"/pdf/" + re.escape(source_id) + r"(?:v\d+)?(?:\.pdf)?", path):
                # The native transfer binds this exact arXiv PDF route. Text
                # extraction may fail or prefer a later publication's DOI.
                return "preprint", "Preprint downloaded from arXiv."
        # A preprint can have its own DOI and a later journal citation. Neither
        # makes this downloaded copy the publisher's version of record.
        pdf_doi = normalize_doi(value) if kind == "doi" else ""
        preprint_server = ""
        if (host in {"biorxiv.org", "www.biorxiv.org", "medrxiv.org", "www.medrxiv.org"}
                and path.startswith("/content/") and path.endswith(".full.pdf")
                and pdf_doi.startswith("10.1101/") and pdf_doi in path):
            preprint_server = "bioRxiv" if "biorxiv" in host else "medRxiv"
        elif (host == "chemrxiv.org" and path.startswith("/engage/api-gateway/chemrxiv/assets/")
                and "/original/" in path and pdf_doi.startswith("10.26434/chemrxiv")):
            preprint_server = "ChemRxiv"
        elif host == "researchsquare.com" or host.endswith(".researchsquare.com"):
            record = re.match(r"10\.21203/rs\.\d+\.rs-(\d+)(?:/|$)", pdf_doi)
            if record and re.search(r"/(?:article|files)/rs-" + record.group(1) + r"/v\d", path):
                preprint_server = "Research Square"
        if preprint_server:
            return "preprint", f"Preprint from {preprint_server}; the PDF has a preprint identifier."
        doi = normalize_doi((capture.paper or {}).get("doi"))
        if not doi or kind != "doi" or normalize_doi(value) != doi:
            return "unknown", "Choose the file type if known."
        if host in {"nature.com", "www.nature.com"} and ui.is_nature_reference_pdf_url(capture.pdf_source_url):
            return "accepted_manuscript", "Nature accepted-manuscript PDF; the DOI matches."
        if re.search(r"\b(?:author[\s_-]*)?accepted[\s_-]*manuscript\b", text):
            return "accepted_manuscript", "Accepted manuscript identified in this PDF."
        main = (
            (host in {"nature.com", "www.nature.com"} and path == "/articles/" + doi.removeprefix("10.1038/") + ".pdf" and doi.startswith("10.1038/"))
            or (host in {"pubs.acs.org", "www.science.org", "science.org", "onlinelibrary.wiley.com", "advanced.onlinelibrary.wiley.com"}
                and path.endswith(tuple("/doi/" + mode + "/" + doi for mode in ("pdf", "epdf", "pdfdirect"))))
            or (host == "journals.aps.org" and re.fullmatch(r"/[^/]+/pdf/" + re.escape(doi), path))
            or (host == "link.aps.org" and path == "/pdf/" + doi)
            or (host == "iopscience.iop.org" and path == "/article/" + doi + "/pdf")
            or (host == "link.springer.com" and path == "/content/pdf/" + doi + ".pdf")
        )
        if main:
            return "published_version", "Publisher article PDF; the PDF DOI matches."
        return "unknown", "Choose the file type if known."

    @staticmethod
    def existing(storage, kind, value, title=""):
        if kind == "doi" and value:
            rows = storage.conn.execute("SELECT * FROM papers WHERE lower(doi)=? LIMIT 2", (value.lower(),)).fetchall()
        elif kind == "arxiv" and value:
            rows = storage.conn.execute("SELECT * FROM papers WHERE paper_id=? OR raw_json LIKE ? LIMIT 100", ("arxiv_" + value, "%" + value + "%")).fetchall()
            rows = [r for r in rows if value in storage._paper_arxiv_identifiers(dict(r))]
        elif title:
            rows = storage.conn.execute("SELECT * FROM papers WHERE lower(title)=lower(?) LIMIT 2", (title,)).fetchall()
        else:
            rows = []
        if len(rows) > 1:
            raise ValueError("More than one existing article matches. Resolve the duplicate records in Library first.")
        return dict(rows[0]) if rows else None

    @classmethod
    def same_identity(cls, storage, left, right):
        if left == right:
            return True
        a = cls.existing(storage, *left)
        b = cls.existing(storage, *right)
        return bool(a and b and a["paper_id"] == b["paper_id"])

    @staticmethod
    def resolve(kind, value):
        from . import ui_server as ui
        if kind == "arxiv":
            return ui.fetch_arxiv_by_id(value, timeout=8, max_retries=1)
        candidates = ui.search_crossref_publications(value, kind="doi", timeout=8, max_retries=1)
        return ui.paper_from_publication_candidate(candidates[0]) if candidates else None

    def review(self, capture: Capture, storage, payload: dict) -> dict:
        from . import ui_server as ui
        with capture.lock:
            meta = capture.snapshot["metadata"]
            explicit = clean_text(str(payload.get("identifier") or ""))[:512]
            page_id = identifier(meta["doi"] or meta["arxiv"] or capture.snapshot["url"])
            # PDF URL suffixes and tracking routes are not stronger evidence
            # than the file's title-page identifier.
            if capture.snapshot["is_pdf"] and capture.pdf_identifier[1] and not (meta["doi"] or meta["arxiv"]):
                page_id = ("", "")
            detected = capture.pdf_identifier if capture.pdf_identifier[1] else page_id
            kind, value = identifier(explicit) if explicit else detected
            title = capture.pdf_title if capture.snapshot["is_pdf"] else meta["title"]
            origin = storage.get_paper(capture.snapshot["origin_paper_id"]) if capture.snapshot["origin_paper_id"] else None
            if not origin and capture.snapshot["origin_url"]:
                rows = storage.conn.execute("SELECT * FROM papers WHERE url=? OR landing_url=? LIMIT 2", (capture.snapshot["origin_url"], capture.snapshot["origin_url"])).fetchall()
                if len(rows) == 1:
                    origin = dict(rows[0])
            capture.conflict = ""
            if explicit and not value:
                raise ValueError("Enter a DOI or arXiv ID.")
            if explicit and detected[1] and not self.same_identity(storage, (kind, value), detected):
                capture.conflict = "The entered identifier differs from the current article or PDF. Save the matching file instead."
            if capture.pdf_ready and capture.pdf_identifier[1] and page_id[1] and not self.same_identity(storage, capture.pdf_identifier, page_id):
                capture.conflict = "The PDF identifier differs from the article page. Review the PDF as a separate article."
            existing = self.existing(storage, kind, value)
            candidate = None
            warning = ""
            if existing:
                candidate = existing
                if title and not ui.title_match_is_confident(title, existing.get("title") or ""):
                    warning = "The extracted title differs from the existing article. Check the title and identifier before saving."
            elif value:
                cache_key = kind + ":" + value
                if cache_key not in capture.resolved and payload.get("resolve", True):
                    try:
                        capture.resolved[cache_key] = self.resolve(kind, value)
                    except Exception:
                        capture.resolved[cache_key] = None
                candidate = capture.resolved.get(cache_key)
                if candidate:
                    candidate = dict(candidate)
                    canonical = self.existing(storage, "doi", normalize_doi(candidate.get("doi"))) if candidate.get("doi") else None
                    existing = canonical or storage.get_paper(candidate["paper_id"])
                    if existing:
                        if storage.paper_identity_conflict_reasons(existing, candidate):
                            capture.conflict = "The discovered metadata conflicts with an existing article. Resolve its identity in Library first."
                        candidate = existing
                elif meta["title"] and kind == "doi" and not capture.snapshot["is_pdf"]:
                    candidate = {"paper_id": make_paper_id(value, meta["title"], meta["journal"], meta["date"]),
                                 "doi": value, "title": meta["title"], "journal": meta["journal"], "publication_date": meta["date"],
                                 "raw": {"authors": meta["authors"]}, "source": "browser", "section_allowed": True}
                    warning = ("Using metadata supplied by this article page. Identify can check the DOI online."
                               if payload.get("resolve") is False else
                               "Online metadata lookup was unavailable. Review the information supplied by this article page.")
            if not candidate and origin and payload.get("use_origin") is True:
                origin_ids = {identifier(origin.get("doi") or ""), *(('arxiv', x) for x in storage._paper_arxiv_identifiers(origin))}
                if detected[1] and detected not in origin_ids:
                    capture.conflict = "This PDF belongs to a different article from the Open Website source."
                else:
                    candidate = existing = origin
            if not candidate and payload.get("manual") is True:
                manual_title = clean_text(str(payload.get("title") or ""))[:1000]
                if len(manual_title) < 5:
                    raise ValueError("Enter the article title before creating a record.")
                candidate = self.existing(storage, "", "", manual_title) if not value else None
                existing = candidate
                if not candidate:
                    candidate = {"paper_id": make_paper_id(value if kind == "doi" else "", manual_title, "", ""),
                                 "doi": value if kind == "doi" else "", "title": manual_title, "journal": "", "publication_date": "",
                                 "source": "browser", "section_allowed": True, "raw": {"metadata_pending": True}}
                    if kind == "arxiv":
                        candidate["paper_id"] = "arxiv_" + value
                        candidate["raw"]["arxiv_id"] = value
            capture.paper = dict(candidate) if candidate else None
            if capture.paper and not existing:
                source_url = persistent_url(capture.snapshot["url"])
                source_doi = identifier(source_url)
                if capture.paper.get("doi") and source_doi[0] == "doi" and source_doi[1] != normalize_doi(capture.paper["doi"]):
                    source_url = "https://doi.org/" + normalize_doi(capture.paper["doi"])
                capture.paper.setdefault("url", source_url)
                capture.paper.setdefault("landing_url", source_url)
            summary = None
            if capture.paper:
                p = capture.paper
                summary = {"paper_id": p["paper_id"], "title": p.get("title") or "", "doi": p.get("doi") or "", "journal": p.get("journal") or "",
                           "date": p.get("publication_date") or "", "gewu_key": p.get("storage_key") or storage.storage_key_for_paper_id(p["paper_id"]),
                           "existing": bool(existing)}
            folders = self.folders(storage)
            suggested_type, type_reason = self.suggested_file_type(capture)
            return {"token": capture.token, "upload_token": capture.upload_token, "snapshot": capture.snapshot, "paper": summary,
                    "identifier": value, "suggested_title": title, "pdf_ready": capture.pdf_ready, "pdf_name": capture.pdf_name,
                    "origin": {"title": origin["title"], "gewu_key": origin.get("storage_key")} if origin else None,
                    "conflict": capture.conflict, "warning": warning, "folders": folders,
                    "suggested_file_type": suggested_type, "file_type_reason": type_reason,
                    "can_save": bool(summary) and not capture.conflict}

    @staticmethod
    def folders(storage):
        nodes = {int(n["id"]): n for n in storage.list_library_folders()}
        result = []
        def walk(node_id, prefix, seen):
            if node_id in seen or node_id not in nodes:
                return
            node = nodes[node_id]
            if node.get("trashed_at") or (node.get("parent_id") == 1 and node.get("name") == "Recycle"):
                return
            name = "Library" if node_id == 1 else (prefix + " / " if prefix else "") + node["name"]
            result.append({"id": node_id, "title": name})
            for child in nodes.values():
                if child.get("parent_id") == node_id:
                    walk(int(child["id"]), name, seen | {node_id})
        walk(1, "", set())
        # The shared Monitor picker also offers Space roots, which are separate
        # top-level folders in the same Library placement model.
        for node in nodes.values():
            if int(node["id"]) != 1 and node.get("parent_id") is None:
                walk(int(node["id"]), "", set())
        return result

    def save(self, capture: Capture, storage, payload: dict) -> dict:
        from . import ui_server as ui
        with capture.lock:
            if capture.result:
                return capture.result
            if not capture.paper or capture.conflict:
                raise ValueError(capture.conflict or "Identify and review the article before saving.")
            folder_id = int(payload.get("folder_id") or 1)
            if folder_id not in {n["id"] for n in self.folders(storage)}:
                raise ValueError("Choose an active Library folder.")
            include_pdf = payload.get("include_pdf") is True
            if include_pdf and not capture.pdf_ready:
                raise ValueError("The PDF has not been received. Retry, choose a local PDF, or save the article only.")
            file_type = str(payload.get("file_type") or self.suggested_file_type(capture)[0])
            if file_type not in FILE_TYPES:
                raise ValueError("Choose a supported PDF file type.")
            paper = dict(capture.paper)
            # Recheck canonical identity immediately before writing: another
            # capture may have saved it while this review panel was open.
            matched = self.existing(storage, "doi", normalize_doi(paper.get("doi"))) if paper.get("doi") else None
            matched = matched or storage.get_paper(paper["paper_id"])
            if matched:
                if storage.paper_identity_conflict_reasons(matched, paper):
                    raise ValueError("This article now conflicts with an existing record. Review again.")
                paper = matched
            elif not storage.upsert_paper(paper):
                raise ValueError("The article identity conflicts with an existing record.")
            paper_id = paper["paper_id"]
            item = storage.add_library_item(paper_id=paper_id, folder_id=folder_id)
            source = persistent_url(capture.snapshot["url"])
            if source:
                storage.record_paper_source_observation(paper_id, source_kind="browser", source_name=urlsplit(source).hostname or "browser", source_key=source)
            resource = None
            if include_pdf:
                try:
                    resource = ui.attach_file_to_paper(storage, paper_id=paper_id, filename=capture.pdf_name,
                        content=capture.path.read_bytes(), file_type=file_type, file_source="user_import",
                        source_detail=urlsplit(capture.snapshot["url"]).hostname or "", added_via="browser_capture")
                    duplicate = bool(resource.get("duplicate"))
                    # Repair only unclassified Browser captures on an explicit
                    # re-save. Keep the same resource/key, all known peer types,
                    # and any classification edited in Paper Files.
                    if (duplicate and file_type != "unknown" and resource.get("added_via") == "browser_capture"
                            and resource.get("file_type") == "unknown" and not resource.get("file_type_override")):
                        role, version, label = legacy_role_projection(file_type)
                        storage.conn.execute("UPDATE resources SET file_type=?,file_role=?,version_role=?,version_label=? WHERE id=?",
                                             (file_type, role, version, label, resource["id"]))
                    if not duplicate or (resource.get("file_type") == "unknown" and not resource.get("file_type_override")):
                        storage.conn.execute("UPDATE resources SET file_type_override=? WHERE id=?",
                                             (int(payload.get("file_type_manual") is True), resource["id"]))
                    pdf_source = persistent_url(capture.pdf_source_url) or source
                    if pdf_source:
                        storage.conn.execute("UPDATE resources SET source_url=COALESCE(NULLIF(source_url,''),?) WHERE id=?", (pdf_source, resource["id"]))
                    storage.conn.commit()
                    resource = storage.get_paper_resource(resource["id"])
                    if (resource.get("file_type") in AUTOMATIC_DEFAULT_FILE_TYPE_RANK
                            and ui.should_promote_new_paper_version(storage, paper_id, resource)):
                        resource = ui.promote_paper_resource(storage, paper_id, resource["id"])
                    resource["duplicate"] = duplicate
                except Exception as exc:
                    return {"ok": False, "metadata_saved": True, "paper_id": paper_id,
                            "error": "Article saved to Library, but the PDF could not be attached: " + str(exc)}
            # Use the existing folder/alias workflow, preserving every peer file
            # and the user's selected Default. Failure remains explicit/retryable.
            try:
                ui.reconcile_paper_pdf_storage(storage, paper_id)
            except Exception as exc:
                return {"ok": False, "metadata_saved": True, "paper_id": paper_id,
                        "error": "Article saved, but Library file placement could not finish: " + str(exc)}
            stored = storage.get_paper(paper_id)
            capture.result = {"ok": True, "paper_id": paper_id, "gewu_key": stored["storage_key"], "title": stored["title"],
                              "item_id": item["id"], "folder_id": folder_id, "pdf_saved": bool(resource),
                              "duplicate_file": bool(resource and resource.get("duplicate"))}
            return capture.result


CAPTURES = BrowserCaptureService()
