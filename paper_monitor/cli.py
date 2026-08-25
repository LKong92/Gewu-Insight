from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

from .analysis import mark_job_done, pending_analysis_jobs, queue_codex_analysis, read_job
from .config import DEFAULT_CONFIG_PATH, DEFAULT_DB_PATH, load_config
from .download import download_paper
from .importers.inventory import import_library_inventory
from .monitor import apply_fast_section_hints, default_windows, run_journal_monitor
from .reporting import export_json, write_journal_markdown_report
from .sources.openalex import OPENALEX_API_KEY_SETTING, configure_openalex_api_key
from .storage import Storage
from .time_utils import parse_date, today_local
from .ui_server import cleanup_monitor_pdf_cache, run_ui_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monitor papers and manage reading actions.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="SQLite database path.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    journal = subparsers.add_parser("journal", help="Fetch journals and generate a Markdown report.")
    journal.add_argument("--from-date", type=str, help="Fetch start date, YYYY-MM-DD.")
    journal.add_argument("--until-date", type=str, help="Fetch/report end date, YYYY-MM-DD.")
    journal.add_argument("--lookback-days", type=int, help="Fetch this many days ending at --until-date.")
    journal.add_argument("--report-days", type=int, help="Report this many days ending at --until-date.")
    journal.add_argument("--no-enrich", action="store_true", help="Skip landing-page abstract/section enrichment.")

    report = subparsers.add_parser("report", help="Regenerate Markdown report from the database.")
    report.add_argument("--from-date", type=str, required=True)
    report.add_argument("--until-date", type=str, required=True)

    download = subparsers.add_parser("download", help="Download main PDF and PDF supplements for one paper.")
    download.add_argument("paper_id")
    download.add_argument("--force", action="store_true", help="Retry even if download already succeeded.")

    analyze = subparsers.add_parser("analyze", help="Queue a Codex analysis job.")
    analyze.add_argument("paper_id")
    analyze.add_argument("--no-download", action="store_true", help="Deprecated; analysis queueing never downloads automatically.")

    queue = subparsers.add_parser("analysis-queue", help="List queued Codex analysis jobs that still need notes.")
    queue.add_argument("--jobs-dir", type=Path, help="Analysis jobs directory.")

    complete = subparsers.add_parser("complete-analysis-job", help="Mark one Codex analysis job done after its note has been written.")
    complete.add_argument("job_path", type=Path)
    complete.add_argument("--note-path", type=Path, help="Override the note path stored in the job file.")

    status = subparsers.add_parser("status", help="Show one paper's stored status.")
    status.add_argument("paper_id")

    subparsers.add_parser("refresh-sections", help="Reapply local section filters to stored papers.")

    export = subparsers.add_parser("export-json", help="Optional JSON export from SQLite.")
    export.add_argument("output", type=Path)
    export.add_argument("--from-date", type=str)
    export.add_argument("--until-date", type=str)

    importer = subparsers.add_parser("import-inventory", help="Dry-run an external library_inventory.json import.")
    importer.add_argument("inventory_path", type=Path)
    importer.add_argument("--copy-mode", choices=["copy", "link", "move"], default="copy")
    importer.add_argument("--preserve-folders", action="store_true")
    importer.add_argument("--dedupe-by", default="doi,arxiv,path", help="Comma-separated keys: doi, arxiv, path.")
    importer.add_argument("--dry-run", action="store_true", help="Inspect only; do not copy files or write papers.")
    importer.add_argument("--report-output", type=Path, help="Write the import report JSON to this path.")

    ui = subparsers.add_parser("ui", help="Start the local browser UI.")
    ui.add_argument("--host", default="127.0.0.1", help="Host for the local UI server.")
    ui.add_argument("--port", type=int, default=8765, help="Port for the local UI server.")
    ui.add_argument("--open", action="store_true", help="Open the UI in the default browser.")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    storage = Storage(args.db)
    raw_config = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    storage.seed_journal_subscriptions(
        raw_config.get("journals", []),
        raw_config.get("journal_history", []),
    )
    config = load_config(db_path=args.db)
    configure_openalex_api_key(
        storage.get_setting(OPENALEX_API_KEY_SETTING, "")
    )
    try:
        if args.command == "journal":
            return handle_journal(args, config, storage)
        if args.command == "report":
            return handle_report(args, config, storage)
        if args.command == "download":
            result = download_paper(storage=storage, paper_id=args.paper_id, force=args.force)
            print_result(result)
            return 0 if result["status"] in {"success", "partial", "skipped"} else 1
        if args.command == "analyze":
            path = queue_codex_analysis(storage=storage, paper_id=args.paper_id)
            print(f"Codex analysis job: {path}")
            return 0
        if args.command == "analysis-queue":
            jobs = pending_analysis_jobs(args.jobs_dir) if args.jobs_dir else pending_analysis_jobs()
            if not jobs:
                print("No pending Codex analysis jobs.")
                return 0
            for job in jobs:
                print(job)
            return 0
        if args.command == "complete-analysis-job":
            return handle_complete_analysis_job(args, storage)
        if args.command == "status":
            paper = storage.get_paper(args.paper_id)
            if not paper:
                print(f"Unknown paper id: {args.paper_id}", file=sys.stderr)
                return 1
            for key in [
                "paper_id",
                "title",
                "journal",
                "publication_date",
                "doi",
                "download_status",
                "download_message",
                "main_pdf_path",
                "merged_pdf_path",
                "analysis_status",
                "analysis_path",
            ]:
                print(f"{key}: {paper.get(key) or ''}")
            return 0
        if args.command == "export-json":
            path = export_json(storage, args.output, args.from_date, args.until_date)
            print(f"Exported: {path}")
            return 0
        if args.command == "import-inventory":
            result = import_library_inventory(
                args.inventory_path,
                copy_mode=args.copy_mode,
                preserve_folders=args.preserve_folders,
                dedupe_by=args.dedupe_by.split(","),
                dry_run=args.dry_run,
                storage=storage,
                report_path=args.report_output,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if not result.get("errors") else 1
        if args.command == "refresh-sections":
            return handle_refresh_sections(config, storage)
        if args.command == "ui":
            storage.close()
            run_ui_server(host=args.host, port=args.port, db_path=args.db, open_browser=args.open)
            return 0
    finally:
        try:
            storage.close()
        except Exception:
            pass
    return 1


def handle_complete_analysis_job(args: argparse.Namespace, storage: Storage) -> int:
    job_path = args.job_path
    job = read_job(job_path)
    if not job:
        print(f"Could not read analysis job: {job_path}", file=sys.stderr)
        return 1

    note_path = args.note_path or Path(str(job.get("analysis_path") or ""))
    if not note_path.exists():
        print(f"Analysis note does not exist: {note_path}", file=sys.stderr)
        return 1

    paper_id = ((job.get("paper") or {}).get("paper_id") or "").strip()
    if not paper_id:
        print(f"Analysis job has no paper_id: {job_path}", file=sys.stderr)
        return 1

    storage.update_analysis_status(paper_id, status="done", path=str(note_path), message="codex analysis complete")
    done_path = mark_job_done(job_path, note_path=note_path)
    print(f"Analysis note: {note_path}")
    print(f"Completed job: {done_path}")
    return 0


def handle_journal(args: argparse.Namespace, config, storage: Storage) -> int:
    until = parse_date(args.until_date) if args.until_date else today_local()
    lookback_days = args.lookback_days or config.fetch_lookback_days

    if args.from_date:
        fetch_start = parse_date(args.from_date)
        if args.report_days:
            report_start = until - timedelta(days=max(args.report_days - 1, 0))
        else:
            report_start = fetch_start
    else:
        report_days = args.report_days or config.report_days
        fetch_start, report_start, until = default_windows(until, lookback_days, report_days)

    summary = run_journal_monitor(
        config=config,
        storage=storage,
        start_date=fetch_start,
        end_date=until,
        enrich=not args.no_enrich,
    )
    report_path = write_journal_markdown_report(
        storage=storage,
        journals=[journal.name for journal in config.journals],
        start_date=report_start,
        end_date=until,
    )
    print(f"Fetched window: {summary['window_start']} to {summary['window_end']}")
    for journal, item in summary["journals"].items():
        print(
            f"{journal}: saved={item['saved']} "
            f"sources={item['source_counts']} statuses={item['source_statuses']} "
            f"blocked={item['blocked_by_section']}"
        )
    print(f"Report: {report_path}")
    cleanup = cleanup_monitor_pdf_cache(storage)
    if cleanup.get("deleted"):
        print(f"Cleaned monitor PDF cache: {len(cleanup['deleted'])} old file(s)")
    if summary["source_attempts"] and summary["source_errors"] == summary["source_attempts"]:
        print("All source fetches failed. The report was generated from existing database records only.", file=sys.stderr)
        return 1
    return 0


def handle_report(args: argparse.Namespace, config, storage: Storage) -> int:
    path = write_journal_markdown_report(
        storage=storage,
        journals=[journal.name for journal in config.journals],
        start_date=parse_date(args.from_date),
        end_date=parse_date(args.until_date),
    )
    print(f"Report: {path}")
    return 0


def handle_refresh_sections(config, storage: Storage) -> int:
    journals = {journal.name: journal for journal in config.journals}
    changed = 0
    for paper in storage.list_papers():
        journal = journals.get(paper.get("journal"))
        if not journal:
            continue
        updated = dict(paper)
        before = (updated.get("publisher_section") or "", updated.get("section_allowed"))
        apply_fast_section_hints(updated, journal)
        after = (updated.get("publisher_section") or "", updated.get("section_allowed"))
        if after != before:
            storage.update_section_status(
                updated["paper_id"],
                publisher_section=updated.get("publisher_section") or "",
                section_allowed=updated.get("section_allowed"),
            )
            changed += 1
    print(f"Updated section status for {changed} papers.")
    return 0


def print_result(result: dict) -> None:
    for key, value in result.items():
        print(f"{key}: {value}")
