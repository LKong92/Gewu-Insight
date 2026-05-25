#!/usr/bin/env python3
"""Publisher-aware batch runner for the Chrome literature downloader.

The single-paper downloader owns browser interaction and file validation. This
runner keeps batch policy separate: strategy-specific time budgets, retries, and
timing logs. It runs serially by default so Chrome downloads into ~/Downloads
cannot be misattributed across simultaneous DOI jobs.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SINGLE_SCRIPT = SCRIPT_DIR / "download_literature_chrome.py"


def load_single_module():
    spec = importlib.util.spec_from_file_location("download_literature_chrome", SINGLE_SCRIPT)
    if spec is None or spec.loader is None:
        raise SystemExit(f"Could not load {SINGLE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


single = load_single_module()


@dataclasses.dataclass(frozen=True)
class AttemptProfile:
    timeout: int
    supplement_timeout: int
    settle_seconds: int
    max_chrome_candidates: int
    max_supplement_candidates: int

    def cli_args(self) -> list[str]:
        return [
            "--timeout",
            str(self.timeout),
            "--supplement-timeout",
            str(self.supplement_timeout),
            "--settle-seconds",
            str(self.settle_seconds),
            "--max-chrome-candidates",
            str(self.max_chrome_candidates),
            "--max-supplement-candidates",
            str(self.max_supplement_candidates),
        ]


@dataclasses.dataclass(frozen=True)
class BatchStrategy:
    first: AttemptProfile
    retry: AttemptProfile
    stop_batch_on_verification: bool = True
    retry_on_failure: bool = True
    inter_paper_delay_seconds: int = 0


BATCH_STRATEGIES: dict[str, BatchStrategy] = {
    "aps": BatchStrategy(
        first=AttemptProfile(timeout=16, supplement_timeout=6, settle_seconds=3, max_chrome_candidates=2, max_supplement_candidates=1),
        retry=AttemptProfile(timeout=35, supplement_timeout=10, settle_seconds=5, max_chrome_candidates=4, max_supplement_candidates=2),
    ),
    "science": BatchStrategy(
        first=AttemptProfile(timeout=35, supplement_timeout=18, settle_seconds=5, max_chrome_candidates=3, max_supplement_candidates=6),
        retry=AttemptProfile(timeout=60, supplement_timeout=25, settle_seconds=7, max_chrome_candidates=5, max_supplement_candidates=8),
    ),
    "scipost": BatchStrategy(
        first=AttemptProfile(timeout=25, supplement_timeout=8, settle_seconds=4, max_chrome_candidates=2, max_supplement_candidates=2),
        retry=AttemptProfile(timeout=45, supplement_timeout=12, settle_seconds=5, max_chrome_candidates=4, max_supplement_candidates=3),
    ),
    "wiley": BatchStrategy(
        first=AttemptProfile(timeout=45, supplement_timeout=22, settle_seconds=6, max_chrome_candidates=3, max_supplement_candidates=6),
        retry=AttemptProfile(timeout=75, supplement_timeout=30, settle_seconds=8, max_chrome_candidates=5, max_supplement_candidates=8),
    ),
    "acs": BatchStrategy(
        first=AttemptProfile(timeout=45, supplement_timeout=20, settle_seconds=6, max_chrome_candidates=3, max_supplement_candidates=6),
        retry=AttemptProfile(timeout=75, supplement_timeout=28, settle_seconds=8, max_chrome_candidates=5, max_supplement_candidates=8),
    ),
    "pnas": BatchStrategy(
        first=AttemptProfile(timeout=35, supplement_timeout=18, settle_seconds=5, max_chrome_candidates=3, max_supplement_candidates=6),
        retry=AttemptProfile(timeout=60, supplement_timeout=25, settle_seconds=7, max_chrome_candidates=5, max_supplement_candidates=8),
    ),
    "ieee": BatchStrategy(
        first=AttemptProfile(timeout=12, supplement_timeout=4, settle_seconds=4, max_chrome_candidates=1, max_supplement_candidates=0),
        retry=AttemptProfile(timeout=12, supplement_timeout=4, settle_seconds=4, max_chrome_candidates=1, max_supplement_candidates=0),
        retry_on_failure=False,
    ),
    "optica": BatchStrategy(
        first=AttemptProfile(timeout=35, supplement_timeout=4, settle_seconds=5, max_chrome_candidates=1, max_supplement_candidates=0),
        retry=AttemptProfile(timeout=35, supplement_timeout=4, settle_seconds=5, max_chrome_candidates=1, max_supplement_candidates=0),
        retry_on_failure=False,
        inter_paper_delay_seconds=180,
    ),
    "aip": BatchStrategy(
        first=AttemptProfile(timeout=40, supplement_timeout=14, settle_seconds=5, max_chrome_candidates=4, max_supplement_candidates=4),
        retry=AttemptProfile(timeout=70, supplement_timeout=22, settle_seconds=7, max_chrome_candidates=6, max_supplement_candidates=6),
    ),
    "generic": BatchStrategy(
        first=AttemptProfile(timeout=45, supplement_timeout=20, settle_seconds=6, max_chrome_candidates=3, max_supplement_candidates=6),
        retry=AttemptProfile(timeout=75, supplement_timeout=30, settle_seconds=8, max_chrome_candidates=5, max_supplement_candidates=8),
    ),
}


VERIFICATION_HINTS = tuple(getattr(single, "VERIFY_HINTS", ()))


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def unique_outdir(base: Path) -> Path:
    if not base.exists():
        return base
    for idx in range(2, 1000):
        candidate = base.with_name(f"{base.name}_{idx}")
        if not candidate.exists():
            return candidate
    raise SystemExit(f"Could not create unique output directory for {base}")


def read_inputs(args: argparse.Namespace) -> list[str]:
    items: list[str] = []
    if args.input_file:
        for line in Path(args.input_file).expanduser().read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            items.append(line)
    items.extend(args.inputs or [])
    if not items:
        raise SystemExit("Provide DOI/URL arguments or --input-file.")
    return items


def looks_like_verification_failure(data: dict) -> bool:
    text = " ".join(
        [
            " ".join(str(item) for item in data.get("errors", [])),
            " ".join(str(item) for item in data.get("log", [])),
        ]
    ).lower()
    return any(hint in text for hint in VERIFICATION_HINTS)


def triggers_publisher_cooldown(strategy_key: str, data: dict) -> bool:
    if strategy_key != "optica":
        return False
    text = " ".join(
        [
            " ".join(str(item) for item in data.get("errors", [])),
            " ".join(str(item) for item in data.get("log", [])),
            json.dumps(data.get("chrome_pages", []), ensure_ascii=False),
        ]
    ).lower()
    return any(
        hint in text
        for hint in (
            "downloading timeout",
            "heavy usage",
            "perfdrive",
            "botmanager",
            "validate.perfdrive.com",
            "suspiciously small optica pdf",
        )
    )


def run_attempt(
    doi_or_url: str,
    profile: AttemptProfile,
    attempt: int,
    index: int,
    outdir: Path,
    args: argparse.Namespace,
) -> dict:
    cmd = [
        sys.executable,
        str(SINGLE_SCRIPT),
        doi_or_url,
        "--downloads",
        str(Path(args.downloads).expanduser()),
        *profile.cli_args(),
    ]
    if args.unpaywall_email:
        cmd.extend(["--unpaywall-email", args.unpaywall_email])
    if args.foreground_chrome:
        cmd.append("--foreground-chrome")
    if args.focus_restore:
        cmd.extend(["--focus-restore", args.focus_restore])
    if args.allow_disruptive_browser_clicks:
        cmd.append("--allow-disruptive-browser-clicks")
    if args.keep_tabs:
        cmd.append("--keep-tabs")
    if args.keep_original_pdfs:
        cmd.append("--keep-original-pdfs")
    if args.use_existing_pdf:
        cmd.append("--use-existing-pdf")
    if args.dry_run:
        cmd.append("--dry-run")

    started_wall = now_iso()
    started = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    elapsed = round(time.monotonic() - started, 3)

    stdout_path = outdir / f"{index:03d}.attempt{attempt}.stdout.json"
    stderr_path = outdir / f"{index:03d}.attempt{attempt}.stderr.txt"
    stdout_path.write_text(proc.stdout, encoding="utf-8")
    stderr_path.write_text(proc.stderr, encoding="utf-8")

    try:
        data = json.loads(proc.stdout)
    except Exception:
        data = {
            "input": doi_or_url,
            "status": "non_json",
            "errors": ["Single-paper downloader did not emit JSON."],
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    data.update(
        {
            "attempt": attempt,
            "returncode": proc.returncode,
            "started_at": started_wall,
            "finished_at": now_iso(),
            "elapsed_seconds": elapsed,
            "attempt_profile": dataclasses.asdict(profile),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
        }
    )
    return data


def compact_record(data: dict, index: int, strategy_key: str) -> dict:
    return {
        "index": index,
        "doi": data.get("doi"),
        "input": data.get("input"),
        "publisher_strategy_key": strategy_key,
        "status": data.get("status"),
        "needs_user_action": data.get("needs_user_action"),
        "attempt": data.get("attempt"),
        "returncode": data.get("returncode"),
        "elapsed_seconds": data.get("elapsed_seconds"),
        "main_pdf": data.get("main_pdf"),
        "combined_pdf": data.get("combined_pdf"),
        "files": data.get("files", []),
        "deleted_files": data.get("deleted_files", []),
        "errors": data.get("errors", []),
        "stdout_path": data.get("stdout_path"),
        "stderr_path": data.get("stderr_path"),
    }


def print_progress(message: str, quiet: bool) -> None:
    if not quiet:
        print(message, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch-download DOI PDFs with publisher-aware Chrome settings.")
    parser.add_argument("inputs", nargs="*", help="DOIs, DOI URLs, or publisher URLs")
    parser.add_argument("--input-file", help="Text file containing one DOI/URL per line")
    parser.add_argument("--downloads", default="~/Downloads", help="Downloads directory; default: ~/Downloads")
    parser.add_argument("--outdir", help="Output log directory; default: /private/tmp/chrome_literature_batch_<timestamp>")
    parser.add_argument("--unpaywall-email", help="Email for Unpaywall API; optional")
    parser.add_argument("--foreground-chrome", action="store_true", help="Bring Chrome to foreground while testing")
    parser.add_argument(
        "--focus-restore",
        choices=("auto", "always", "never"),
        default="auto",
        help="Foreground restore policy passed to the single-paper downloader",
    )
    parser.add_argument(
        "--allow-disruptive-browser-clicks",
        action="store_true",
        help="Allow publisher clicks that may bring Chrome to foreground, such as Optica Get PDF",
    )
    parser.add_argument("--keep-tabs", action="store_true", help="Leave Chrome tabs open")
    parser.add_argument("--keep-original-pdfs", action="store_true", help="Keep article/SI PDFs after combined PDF is created")
    parser.add_argument("--use-existing-pdf", action="store_true", help="Allow existing matching PDFs to satisfy a DOI")
    parser.add_argument("--dry-run", action="store_true", help="Pass --dry-run to the single-paper downloader")
    parser.add_argument("--stop-on-failure", action="store_true", help="Stop the batch on any unresolved DOI")
    parser.add_argument(
        "--optica-delay-seconds",
        type=int,
        default=None,
        help="Minimum delay between Optica/OSA DOI attempts; default: 180 seconds",
    )
    parser.add_argument(
        "--stop-on-verification",
        action="store_true",
        help="Stop the batch after captcha/verification is detected. Default is to mark that DOI unresolved and continue.",
    )
    parser.add_argument(
        "--continue-after-verification",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress progress lines; summary JSON is still written")
    parser.add_argument("--self-test", action="store_true", help="Run offline self-tests")
    return parser.parse_args()


def self_test() -> int:
    assert BATCH_STRATEGIES["aps"].first.timeout < BATCH_STRATEGIES["science"].retry.timeout
    assert single.publisher_strategy_for("10.1126/science.aav3392", "").key == "science"
    assert single.publisher_strategy_for("10.1103/physrevb.61.10267", "").key == "aps"
    assert single.publisher_strategy_for("10.1109/3.53394", "").key == "ieee"
    assert single.publisher_strategy_for("10.1364/josab.9.000405", "").key == "optica"
    assert single.publisher_strategy_for("10.1063/5.0188658", "").key == "aip"
    assert BATCH_STRATEGIES["optica"].inter_paper_delay_seconds >= 180
    assert read_inputs(argparse.Namespace(input_file=None, inputs=["10.1103/physrevb.61.10267"])) == [
        "10.1103/physrevb.61.10267"
    ]
    print("batch self-test ok")
    return 0


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()

    inputs = read_inputs(args)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = unique_outdir(Path(args.outdir).expanduser() if args.outdir else Path(f"/private/tmp/chrome_literature_batch_{stamp}"))
    outdir.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    started = time.monotonic()
    batch_started_at = now_iso()
    publisher_cooldowns: dict[str, str] = {}
    last_publisher_attempt_finished: dict[str, float] = {}

    for index, item in enumerate(inputs, start=1):
        try:
            doi = single.normalize_doi(item)
            strategy = single.publisher_strategy_for(doi, item)
        except BaseException as exc:
            record = {
                "index": index,
                "input": item,
                "publisher_strategy_key": "unknown",
                "status": "invalid_input",
                "needs_user_action": False,
                "errors": [str(exc)],
                "elapsed_seconds": 0,
            }
            records.append(record)
            print_progress(f"INVALID {index}/{len(inputs)} {item}: {exc}", args.quiet)
            if args.stop_on_failure:
                break
            continue

        strategy_key = strategy.key
        batch_strategy = BATCH_STRATEGIES.get(strategy_key, BATCH_STRATEGIES["generic"])
        if strategy_key in publisher_cooldowns:
            record = {
                "index": index,
                "doi": doi,
                "input": item,
                "publisher_strategy_key": strategy_key,
                "status": "skipped_publisher_cooldown",
                "needs_user_action": True,
                "attempt": 0,
                "returncode": None,
                "elapsed_seconds": 0,
                "main_pdf": None,
                "combined_pdf": None,
                "files": [],
                "deleted_files": [],
                "errors": [publisher_cooldowns[strategy_key]],
            }
            records.append(record)
            print_progress(f"SKIP {doi} [{strategy_key}]: {publisher_cooldowns[strategy_key]}", args.quiet)
            continue
        delay_seconds = batch_strategy.inter_paper_delay_seconds
        if strategy_key == "optica" and args.optica_delay_seconds is not None:
            delay_seconds = max(0, args.optica_delay_seconds)
        previous_finished = last_publisher_attempt_finished.get(strategy_key)
        pre_attempt_delay = 0.0
        if delay_seconds > 0 and previous_finished is not None:
            remaining = delay_seconds - (time.monotonic() - previous_finished)
            if remaining > 0:
                pre_attempt_delay = round(remaining, 3)
                print_progress(
                    f"WAIT {strategy_key} {pre_attempt_delay}s before {doi} to reduce publisher rate-limit risk.",
                    args.quiet,
                )
                time.sleep(remaining)
        print_progress(f"START {index}/{len(inputs)} {doi} [{strategy_key}]", args.quiet)

        first = run_attempt(item, batch_strategy.first, 1, index, outdir, args)
        final = first
        if first.get("status") == "ok" and not first.get("needs_user_action"):
            print_progress(
                f"OK {doi} {first.get('elapsed_seconds')}s: {first.get('combined_pdf') or first.get('main_pdf')}",
                args.quiet,
            )
        elif batch_strategy.retry_on_failure:
            print_progress(f"RETRY {doi}: {first.get('status')} {first.get('errors')}", args.quiet)
            second = run_attempt(item, batch_strategy.retry, 2, index, outdir, args)
            final = second
            if second.get("status") == "ok" and not second.get("needs_user_action"):
                print_progress(
                    f"OK_AFTER_RETRY {doi} {second.get('elapsed_seconds')}s: {second.get('combined_pdf') or second.get('main_pdf')}",
                    args.quiet,
                )
            else:
                print_progress(f"UNRESOLVED {doi}: {second.get('status')} {second.get('errors')}", args.quiet)
        else:
            print_progress(f"UNRESOLVED {doi}: {first.get('status')} {first.get('errors')}", args.quiet)

        record = compact_record(final, index, strategy_key)
        record["pre_attempt_delay_seconds"] = pre_attempt_delay
        record["publisher_strategy"] = dataclasses.asdict(strategy)
        record["attempts"] = [compact_record(first, index, strategy_key)]
        if final is not first:
            record["attempts"].append(compact_record(final, index, strategy_key))
        records.append(record)
        last_publisher_attempt_finished[strategy_key] = time.monotonic()

        verification = looks_like_verification_failure(final)
        if triggers_publisher_cooldown(strategy_key, final):
            publisher_cooldowns[strategy_key] = (
                f"{strategy.name} cooling down after timeout/rate-limit/fake-PDF signal. Try again later."
            )
            record["batch_stop_reason"] = "publisher_cooldown"
            print_progress(f"COOLDOWN {strategy_key}: {publisher_cooldowns[strategy_key]}", args.quiet)
        if verification and args.stop_on_verification and batch_strategy.stop_batch_on_verification:
            record["batch_stop_reason"] = "verification_detected"
            print_progress(f"STOP {doi}: verification/captcha detected; batch stopped for safety.", args.quiet)
            break
        if args.stop_on_failure and not (final.get("status") == "ok" and not final.get("needs_user_action")):
            record["batch_stop_reason"] = "unresolved_failure"
            print_progress(f"STOP {doi}: unresolved failure.", args.quiet)
            break

    summary = {
        "started_at": batch_started_at,
        "finished_at": now_iso(),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "downloads_dir": str(Path(args.downloads).expanduser()),
        "outdir": str(outdir),
        "total_inputs": len(inputs),
        "completed_records": len(records),
        "ok_count": sum(1 for item in records if item.get("status") == "ok" and not item.get("needs_user_action")),
        "unresolved_count": sum(1 for item in records if not (item.get("status") == "ok" and not item.get("needs_user_action"))),
        "publisher_cooldowns": publisher_cooldowns,
        "publisher_delay_policy": {
            key: value.inter_paper_delay_seconds
            for key, value in BATCH_STRATEGIES.items()
            if value.inter_paper_delay_seconds
        },
        "records": records,
    }
    summary_path = outdir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print_progress(f"SUMMARY {summary_path}", args.quiet)
    if summary["unresolved_count"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
