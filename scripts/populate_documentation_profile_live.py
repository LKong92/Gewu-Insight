#!/usr/bin/env python3
"""Populate a disposable documentation profile through real product sources.

The production SQLite database is opened read-only and is used only to copy the
three citation-provider credentials and reusable public figure URLs into the
disposable profile.  Credential values are never printed and are removed from
the disposable database before the command exits.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import date
from pathlib import Path
from urllib.parse import quote, unquote, urlparse


CREDENTIAL_KEYS = (
    "openalex_api_key",
    "semantic_scholar_api_key",
    "ads_api_token",
)


def resolved_file(value: str, *, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    return path


def disposable_profile_root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if root in {Path("/").resolve(), Path.home().resolve()} or len(root.parts) < 4:
        raise ValueError("Choose a dedicated disposable profile directory")
    production_data = (Path(__file__).resolve().parents[1] / "data").resolve()
    if root == production_data or production_data in root.parents:
        raise ValueError("The documentation profile cannot use the production data directory")
    db_path = root / "data" / "paper_monitor.sqlite"
    if not db_path.is_file():
        raise ValueError(f"Build the isolated documentation profile first: {db_path}")
    return root


def copy_credentials_read_only(source_db: Path, target_storage) -> int:
    target_db = Path(target_storage.db_path).resolve()
    if source_db.resolve() == target_db:
        raise ValueError("Credential source and documentation database must be different")
    source_uri = f"file:{quote(str(source_db.resolve()))}?mode=ro"
    source = sqlite3.connect(source_uri, uri=True)
    try:
        placeholders = ", ".join("?" for _ in CREDENTIAL_KEYS)
        rows = source.execute(
            f"SELECT key, value FROM app_settings WHERE key IN ({placeholders})",
            CREDENTIAL_KEYS,
        ).fetchall()
    finally:
        source.close()
    copied = 0
    for key, value in rows:
        if str(value or "").strip():
            target_storage.set_setting(str(key), str(value))
            copied += 1
    return copied


def clear_live_monitor_surfaces(storage) -> None:
    """Remove only disposable demo monitor associations, never visible Library files."""
    with storage.conn:
        storage.conn.execute("DELETE FROM my_publications")
        storage.conn.execute("DELETE FROM author_monitor_papers")
        storage.conn.execute("DELETE FROM author_monitors")
        storage.conn.execute("DELETE FROM theme_results")
        storage.conn.execute("DELETE FROM theme_candidates")
        storage.conn.execute("DELETE FROM theme_source_tasks")
        storage.conn.execute("DELETE FROM theme_source_runs")
        storage.conn.execute("DELETE FROM journal_monitor_papers")
        storage.conn.execute("DELETE FROM fetch_runs WHERE monitor_type IN ('journal', 'theme')")
        storage.conn.execute("DELETE FROM journal_subscriptions")


def seed_all_product_journals(storage, config_path: Path) -> None:
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    storage.seed_journal_subscriptions(
        raw.get("journals", []),
        raw.get("journal_history", []),
    )


def add_real_my_publications(storage, profile_url: str, *, limit: int) -> tuple[str, int]:
    from paper_monitor.ui_server import (
        fetch_google_scholar_profile_payload,
        paper_from_publication_candidate,
        save_my_publications_scholar_profile,
    )

    payload = fetch_google_scholar_profile_payload(profile_url, limit=limit)
    profile = save_my_publications_scholar_profile(storage, payload.get("profile") or {})
    profile_name = str(profile.get("name") or "").strip()
    storage.set_setting("my_publications_name", profile_name)
    added = 0
    for candidate in payload.get("candidates") or []:
        paper = paper_from_publication_candidate(candidate)
        storage.upsert_paper(paper)
        storage.add_my_publication(paper_id=str(paper["paper_id"]))
        added += 1
    return profile_name, added


def enrich_real_my_publications(storage) -> dict[str, int]:
    """Resolve identifiers, then run the normal product metrics refresh path.

    Google Scholar describes author order, but it does not establish co-first or
    corresponding-author roles.  Those manual roles therefore remain unset in
    the disposable documentation profile.  The UI computes "listed first"
    independently from the resolved author list.
    """
    from paper_monitor.ui_server import (
        create_my_publication_metrics_job,
        get_my_publication_metrics_job,
        paper_from_publication_candidate,
        publication_to_reimport_candidate,
        resolve_google_scholar_candidate_to_identifier,
        run_my_publication_metrics_job,
    )

    resolved_doi = 0
    resolved_arxiv = 0
    unresolved = 0
    for publication in storage.list_my_publications():
        doi = str(publication.get("doi") or "").strip()
        raw_json = str(publication.get("raw_json") or "")
        if doi:
            resolved_doi += 1
            continue
        if "arxiv" in raw_json.casefold():
            # Let the metrics job validate and enrich an already identified arXiv record.
            resolved_arxiv += 1
            continue
        candidate = publication_to_reimport_candidate(publication)
        identifier_candidate = resolve_google_scholar_candidate_to_identifier(candidate)
        if not identifier_candidate:
            unresolved += 1
            continue
        normalized = paper_from_publication_candidate(identifier_candidate)
        storage.upsert_paper(normalized)
        storage.replace_my_publication_paper(
            publication_id=int(publication["id"]),
            paper_id=str(normalized["paper_id"]),
        )
        if str(normalized.get("doi") or "").strip():
            resolved_doi += 1
        else:
            resolved_arxiv += 1

    # Refresh bibliographic fields and citation metrics through the same code
    # path used by the My Publications "Refresh Metrics" command.
    job_id = create_my_publication_metrics_job()
    run_my_publication_metrics_job(job_id=job_id, db_path=Path(storage.db_path))
    job = get_my_publication_metrics_job(job_id) or {}
    return {
        "doi": resolved_doi,
        "arxiv": resolved_arxiv,
        "unresolved": unresolved,
        "refreshed": int(job.get("refreshed") or 0),
        "skipped": int(job.get("skipped") or 0),
    }


def curate_documentation_publications(storage) -> int:
    """Remove non-paper Scholar entries from the disposable manual example.

    Google Scholar profiles can contain conference schedules, meeting abstracts,
    repository mirrors, and placeholder records.  They remain valid candidates
    in the product, where the user decides what belongs in My Publications, but
    the documentation profile should demonstrate a curated publication list.
    DOI-bearing records and normal non-DOI publications are retained.
    """
    excluded_journals = {
        "aps global physics summit",
        "aps march meeting abstracts",
        "zenodo",
        "(no title)",
    }
    removed = 0
    for publication in storage.list_my_publications():
        doi = str(publication.get("doi") or "").strip()
        journal = str(publication.get("journal") or "").strip().casefold()
        if doi or journal not in excluded_journals:
            continue
        storage.delete_my_publication(publication_id=int(publication["id"]))
        removed += 1
    return removed


def copy_cached_publication_figure_read_only(source_db: Path, storage) -> str:
    """Reuse one public, DOI-matched figure URL without copying private data."""
    target_dois = {
        str(row.get("doi") or "").strip().casefold(): str(row.get("paper_id") or "")
        for row in storage.list_my_publications()
        if str(row.get("doi") or "").strip()
    }
    if not target_dois:
        return ""
    source_uri = f"file:{quote(str(source_db.resolve()))}?mode=ro"
    source = sqlite3.connect(source_uri, uri=True)
    try:
        rows = source.execute(
            """
            SELECT doi, image_url
            FROM papers
            WHERE COALESCE(doi, '') != '' AND COALESCE(image_url, '') != ''
            ORDER BY publication_date DESC, paper_id
            """
        ).fetchall()
    finally:
        source.close()
    for doi, image_url in rows:
        paper_id = target_dois.get(str(doi or "").strip().casefold())
        image_url = str(image_url or "").strip()
        parsed = urlparse(image_url)
        if not paper_id or parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        # Old caches may contain an unresolved arXiv-relative URL or, more
        # seriously, a Springer image copied from a different DOI.  Neither is
        # suitable for a documentation screenshot that is meant to demonstrate
        # real product provenance.
        decoded_url = unquote(image_url).casefold()
        normalized_doi = str(doi or "").strip().casefold()
        if parsed.netloc.casefold().endswith("arxiv.org") and parsed.path == "/html/x1.png":
            continue
        if "media.springernature.com" in parsed.netloc.casefold() and normalized_doi not in decoded_url:
            continue
        if paper_id:
            storage.update_image_url(paper_id, image_url)
            return paper_id
    return ""


def enrich_one_documentation_publication_figure(storage) -> str:
    """Use the product's normal single-paper landing-page figure discovery."""
    from paper_monitor.sources.publisher import enrich_image_from_landing_page

    publications = storage.list_my_publications()
    publications.sort(
        key=lambda row: (
            0 if str(row.get("journal") or "").casefold().startswith("nature") else 1,
            str(row.get("publication_date") or ""),
        )
    )
    for publication in publications[:6]:
        if publication.get("image_url"):
            return str(publication.get("paper_id") or "")
        enriched = enrich_image_from_landing_page(dict(publication))
        image_url = str(enriched.get("image_url") or "").strip()
        if image_url:
            paper_id = str(publication.get("paper_id") or "")
            storage.update_image_url(paper_id, image_url)
            return paper_id
    return ""


def add_real_author_monitors(storage, queries: list[str], *, papers_per_author: int) -> list[tuple[str, int]]:
    from paper_monitor.time_utils import now_iso
    from paper_monitor.ui_server import (
        cache_author_monitor_source_photo,
        fetch_google_scholar_profile_payload,
        paper_from_publication_candidate,
        search_google_scholar_profiles,
    )

    results: list[tuple[str, int]] = []
    for query in queries:
        if query.startswith(("https://scholar.google.com/", "http://scholar.google.com/")):
            profiles = [{"url": query}]
        else:
            profiles = search_google_scholar_profiles(query, limit=5)
            if not profiles:
                continue
        payload = fetch_google_scholar_profile_payload(
            str(profiles[0].get("url") or ""),
            limit=papers_per_author,
            sort_by_date=True,
        )
        profile = payload.get("profile") or profiles[0]
        monitor = storage.add_author_monitor(profile)
        added = 0
        for candidate in payload.get("candidates") or []:
            paper = paper_from_publication_candidate(candidate)
            storage.upsert_paper(paper)
            raw = candidate.get("raw") if isinstance(candidate.get("raw"), dict) else {}
            scholar = raw.get("google_scholar") if isinstance(raw.get("google_scholar"), dict) else {}
            storage.add_author_monitor_paper(
                author_monitor_id=int(monitor["id"]),
                paper_id=str(paper["paper_id"]),
                scholar_key=str(scholar.get("publication_url") or ""),
                scholar_title=str(paper.get("title") or ""),
            )
            added += 1
        storage.update_author_monitor(
            int(monitor["id"]),
            profile=profile,
            status="success",
            message="",
            last_checked_at=now_iso(),
            last_success_at=now_iso(),
        )
        cache_author_monitor_source_photo(Path(storage.db_path), int(monitor["id"]))
        results.append((str(profile.get("name") or query), added))
    return results


def journal_count_by_day(storage, start_date: date, end_date: date) -> list[tuple[str, int]]:
    rows = storage.conn.execute(
        """
        SELECT papers.publication_date AS day, COUNT(DISTINCT papers.paper_id) AS paper_count
        FROM journal_monitor_papers
        JOIN fetch_runs ON fetch_runs.id = journal_monitor_papers.fetch_run_id
        JOIN papers ON papers.paper_id = journal_monitor_papers.paper_id
        WHERE fetch_runs.monitor_type = 'journal'
          AND papers.publication_date BETWEEN ? AND ?
          AND COALESCE(papers.section_allowed, 1) != 0
        GROUP BY papers.publication_date
        ORDER BY paper_count DESC, day DESC
        """,
        (start_date.isoformat(), end_date.isoformat()),
    ).fetchall()
    return [(str(row["day"]), int(row["paper_count"] or 0)) for row in rows if str(row["day"] or "")]


def run_real_monitors(storage, start_date: date, end_date: date) -> tuple[str, int, int]:
    from paper_monitor.config import load_config
    from paper_monitor.monitor import fetch_one_arxiv_preprint_source, run_journal_monitor
    from paper_monitor.ui_server import load_theme_groups, run_theme_monitor

    config = load_config(db_path=Path(storage.db_path))
    journal_summary = run_journal_monitor(
        config=config,
        storage=storage,
        start_date=start_date,
        end_date=end_date,
        enrich=True,
    )
    fetch_one_arxiv_preprint_source(
        storage=storage,
        start_date=start_date,
        end_date=end_date,
    )
    counts = journal_count_by_day(storage, start_date, end_date)
    best_day, best_count = counts[0] if counts else (end_date.isoformat(), 0)
    groups = load_theme_groups(storage)
    group_keys = list(groups)
    theme_summary = run_theme_monitor(
        storage=storage,
        start_date=date.fromisoformat(best_day),
        end_date=date.fromisoformat(best_day),
        group_keys=group_keys,
        theme_groups=groups,
        trigger="documentation_profile",
        refresh_aps_rss=True,
    )
    return best_day, best_count, int(theme_summary.get("saved") or 0)


def link_visual_documentation_paper(storage) -> str:
    """Reuse one real, image-rich monitor paper in Library, Space, and Subject examples."""
    row = storage.conn.execute(
        """
        SELECT paper_id, publication_date, title
        FROM papers
        WHERE COALESCE(image_url, '') != ''
          AND (
            lower(title) LIKE '%topolog%'
            OR lower(title) LIKE '%twist%'
            OR lower(title) LIKE '%moir%'
            OR lower(title) LIKE '%quantum%'
          )
        ORDER BY publication_date DESC, paper_id
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return ""
    folders = storage.list_library_folders()
    folder_ids = {
        str(folder.get("name") or ""): int(folder["id"])
        for folder in folders
        if str(folder.get("name") or "") in {"Topological Phases", "Foundational Papers"}
    }
    for folder_id in folder_ids.values():
        storage.add_library_item(paper_id=str(row["paper_id"]), folder_id=folder_id)
    storage.record_theme_result(
        paper_id=str(row["paper_id"]),
        group_key="TOPOLOGICAL-MATTER",
        group_name="Topological Matter",
        query="topological moire quantum material",
        score=4,
        hits=["topological", "twisted", "moiré", "quantum"],
        window_start=str(row["publication_date"] or ""),
        window_end=str(row["publication_date"] or ""),
    )
    return str(row["paper_id"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-root", required=True)
    parser.add_argument("--credential-db", required=True)
    parser.add_argument("--scholar-profile-url", required=True)
    parser.add_argument("--from-date", required=True)
    parser.add_argument("--until-date", required=True)
    parser.add_argument("--publication-limit", type=int, default=200)
    parser.add_argument("--author-papers", type=int, default=40)
    parser.add_argument("--author", action="append", default=[])
    parser.add_argument("--author-profile", action="append", default=[])
    parser.add_argument(
        "--authors-only",
        action="store_true",
        help="Populate only Author Monitor without clearing an existing live documentation snapshot",
    )
    parser.add_argument(
        "--publications-only",
        action="store_true",
        help="Resolve and refresh the existing My Publications snapshot without clearing other surfaces",
    )
    args = parser.parse_args()

    root = disposable_profile_root(args.profile_root)
    credential_db = resolved_file(args.credential_db, label="Credential database")
    target_db = root / "data" / "paper_monitor.sqlite"
    start_date = date.fromisoformat(args.from_date)
    end_date = date.fromisoformat(args.until_date)
    if start_date > end_date:
        raise ValueError("From date must be on or before until date")

    os.environ["GEWU_DATA_ROOT"] = str(root / "data")
    os.environ["GEWU_DOCUMENTATION_MODE"] = "1"

    from paper_monitor.sources.openalex import configure_openalex_api_key
    from paper_monitor.sources.semantic_scholar import configure_semantic_scholar_api_key
    from paper_monitor.storage import Storage

    storage = Storage(target_db)
    copied_credentials = 0
    profile_name = ""
    publication_count = 0
    author_results: list[tuple[str, int]] = []
    best_day = end_date.isoformat()
    best_day_count = 0
    subject_count = 0
    publication_enrichment = {"doi": 0, "arxiv": 0, "unresolved": 0, "refreshed": 0, "skipped": 0}
    curated_publications = 0
    publication_figure_paper_id = ""
    try:
        if args.authors_only and args.publications_only:
            raise ValueError("Choose only one partial population mode")
        if args.publications_only:
            copied_credentials = copy_credentials_read_only(credential_db, storage)
            configure_openalex_api_key(storage.get_setting("openalex_api_key", ""))
            configure_semantic_scholar_api_key(storage.get_setting("semantic_scholar_api_key", ""))
            publication_enrichment = enrich_real_my_publications(storage)
            curated_publications = curate_documentation_publications(storage)
            publication_figure_paper_id = copy_cached_publication_figure_read_only(credential_db, storage)
            if not publication_figure_paper_id:
                publication_figure_paper_id = enrich_one_documentation_publication_figure(storage)
        elif not args.authors_only:
            clear_live_monitor_surfaces(storage)
            seed_all_product_journals(storage, Path(__file__).resolve().parents[1] / "config" / "journals.json")
            copied_credentials = copy_credentials_read_only(credential_db, storage)
            configure_openalex_api_key(storage.get_setting("openalex_api_key", ""))
            configure_semantic_scholar_api_key(storage.get_setting("semantic_scholar_api_key", ""))
            profile_name, publication_count = add_real_my_publications(
                storage,
                args.scholar_profile_url,
                limit=max(1, args.publication_limit),
            )
        if not args.publications_only:
            author_results = add_real_author_monitors(
                storage,
                [*args.author_profile, *args.author],
                papers_per_author=max(1, args.author_papers),
            )
        if not args.authors_only and not args.publications_only:
            best_day, best_day_count, subject_count = run_real_monitors(storage, start_date, end_date)
            link_visual_documentation_paper(storage)
        storage.set_setting("documentation_profile", "1")
        if not args.authors_only and not args.publications_only:
            storage.set_setting("documentation_profile_date", best_day)
    finally:
        # The documentation snapshot keeps fetched public metadata, never credentials.
        with storage.conn:
            placeholders = ", ".join("?" for _ in CREDENTIAL_KEYS)
            storage.conn.execute(
                f"DELETE FROM app_settings WHERE key IN ({placeholders})",
                CREDENTIAL_KEYS,
            )
        configure_openalex_api_key("")
        configure_semantic_scholar_api_key("")
        storage.close()

    print(f"Citation provider settings used transiently: {copied_credentials}")
    print(f"My Publications profile: {profile_name} ({publication_count} publications)")
    if args.publications_only:
        print(
            "My Publications identifier refresh: "
            f"{publication_enrichment['doi']} DOI, "
            f"{publication_enrichment['arxiv']} arXiv, "
            f"{publication_enrichment['unresolved']} unresolved"
        )
        print(
            "My Publications metrics refresh: "
            f"{publication_enrichment['refreshed']} refreshed, "
            f"{publication_enrichment['skipped']} skipped"
        )
        print(f"My Publications documentation-only candidates removed: {curated_publications}")
        print(f"My Publications cached figure ready: {'yes' if publication_figure_paper_id else 'no'}")
    for name, count in author_results:
        print(f"Author Monitor: {name} ({count} publications)")
    print(f"Journal snapshot: {best_day} ({best_day_count} papers)")
    print(f"Subject relationships saved: {subject_count}")
    print("Credential settings removed from disposable profile: yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
