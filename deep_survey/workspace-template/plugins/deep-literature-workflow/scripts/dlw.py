#!/usr/bin/env python3
"""State helper for the Deep Literature Workflow Codex plugin.

This script does not perform the whole literature review by itself. It gives
Codex a stable project state machine so short plugin prompts can resume a
multi-stage review without copying long instructions.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATE_DIR = Path(".deep-literature-workflow")
STATE_PATH = STATE_DIR / "state.json"
WORKSPACE_PROJECT_STATE_PATH = Path("PROJECT_STATE.md")
TOPIC_PROJECT_STATE_REL = Path("08_Project_Workflow") / "PROJECT_STATE.md"
MANAGED_HANDOFF_MARKER = "<!-- dlw-managed-project-state -->"

STAGES = [
    "stage_1_discovery",
    "stage_2_screening",
    "stage_3_pdf_acquisition",
    "stage_4_paper_deep_reading",
    "stage_5a_concept_notes",
    "stage_5b_review_synthesis",
    "stage_5c_evidence_matrices",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(value: str) -> str:
    asciiish = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return asciiish or "literature-review"


def default_vault_name(topic: str, slug: str | None) -> str:
    base = slug or slugify(topic)
    return f"{base}_survay"


def topic_project_state_path(vault_root: str) -> Path:
    return Path(vault_root) / TOPIC_PROJECT_STATE_REL


def load_state(path: Path = STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stage_status_template() -> dict[str, str]:
    return {stage: "pending" for stage in STAGES}


def infer_next_stage(stage_status: dict[str, str]) -> str | None:
    for stage in STAGES:
        if stage_status.get(stage) != "done":
            return stage
    return None


def stage_label(stage: str | None) -> str:
    if not stage:
        return "complete"
    return stage.replace("_", " ")


def topic_status_summary(state: dict[str, Any]) -> str:
    stage_status = state.get("stage_status", {})
    done_count = sum(1 for stage in STAGES if stage_status.get(stage) == "done")
    for stage in STAGES:
        if stage_status.get(stage) == "blocked":
            return f"{done_count} stage(s) done; blocked at {stage_label(stage)}"
    next_stage = infer_next_stage(stage_status)
    if not next_stage:
        return "All stages complete"
    return f"{done_count} stage(s) done; {stage_label(next_stage)} next"


def table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def normalize_vault_root(value: str) -> str:
    return value.strip().strip("`").rstrip("/")


def topic_handoff_markdown(state: dict[str, Any]) -> str:
    stage_status = state.get("stage_status", {})
    next_stage = infer_next_stage(stage_status)
    stage_lines = "\n".join(
        f"- `{stage}`: {stage_status.get(stage, 'pending')}" for stage in STAGES
    )
    note_lines = "\n".join(f"- {note}" for note in state.get("notes", [])[-6:])
    manual_queue = state.get("manual_pdf_queue", [])
    manual_line = f"{len(manual_queue)} queued item(s)" if manual_queue else "empty"
    manual_items = "\n".join(
        f"- {item.get('title', '')} ({item.get('doi') or item.get('expected_filename') or 'no id'}): {item.get('status', 'needed')}"
        for item in manual_queue[:12]
    )
    if len(manual_queue) > 12:
        manual_items += f"\n- ... {len(manual_queue) - 12} more item(s)"
    return f"""# PROJECT_STATE.md
{MANAGED_HANDOFF_MARKER}

## Current Scope

- Topic: {state.get("topic", "")}
- Vault root: `{state.get("vault_root", "")}`
- Current stage: `{state.get("current_stage", "")}`
- Next stage: `{next_stage or "complete"}`
- Updated at: {state.get("updated_at", "")}

## Stage Status

{stage_lines}

## Manual PDF Queue

- {manual_line}
{manual_items}

## Recent Notes

{note_lines or "- No notes yet."}

## Next Step

- Continue with `{next_stage or "complete"}`.
"""


def write_topic_handoff(state: dict[str, Any]) -> Path:
    path = topic_project_state_path(state["vault_root"])
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        if MANAGED_HANDOFF_MARKER not in existing:
            return path
    path.write_text(topic_handoff_markdown(state), encoding="utf-8")
    return path


def read_existing_topic_rows(path: Path) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("|---"):
            continue
        cells = [cell.strip().strip("`") for cell in stripped.strip("|").split("|")]
        if len(cells) < 4 or cells[0].lower() == "topic":
            continue
        vault = normalize_vault_root(cells[1])
        if vault:
            cells[1] = vault
            rows[vault] = cells[:4]
    return rows


def write_workspace_index(state: dict[str, Any]) -> Path:
    rows = read_existing_topic_rows(WORKSPACE_PROJECT_STATE_PATH)
    vault_root = normalize_vault_root(state.get("vault_root", ""))
    handoff = str(topic_project_state_path(vault_root))
    state_topic = state.get("topic", "")
    existing_row = rows.get(vault_root)
    topic_display = state_topic
    if existing_row and state_topic and state_topic in existing_row[0]:
        topic_display = existing_row[0]
    rows[vault_root] = [
        topic_display,
        vault_root,
        topic_status_summary(state),
        handoff,
    ]
    ordered_rows = sorted(
        rows.values(),
        key=lambda row: (0 if row[1] == vault_root else 1, row[0].lower()),
    )
    table = "\n".join(
        f"| {table_cell(topic)} | `{table_cell(vault)}` | {table_cell(status)} | `{table_cell(handoff_path)}` |"
        for topic, vault, status, handoff_path in ordered_rows
    )
    WORKSPACE_PROJECT_STATE_PATH.write_text(
        f"""# PROJECT_STATE.md

## Workspace Role

- This file is a multi-topic index for the literature-review workspace.
- It should not contain a full single-topic handoff.
- Before continuing a specific topic, read the topic handoff path listed in the table below.
- Current active topic: {state.get("topic", "")}

## Topics

| Topic | Vault | Status | Topic Handoff |
|---|---|---|---|
{table}

## Shared Rules

- Do not delete or rewrite another topic vault unless explicitly asked.
- Use legal metadata and PDF sources only; do not use Sci-Hub or unauthorized sources.
- Stage 3 is manual-download only: create linked download queues, wait for user-provided PDFs, then validate and import them.
- Do not start automatic PDF downloaders or browser download scripts unless the user explicitly asks outside the Stage 3 app workflow.
- Do not commit automatically after small edits; commit only when asked or at a meaningful milestone.

## Current Plugin State

- `.deep-literature-workflow/state.json` currently points to {state.get("topic", "")}.
- If switching topics, confirm which topic is active and update/read the corresponding topic handoff.

## Current Next Step

- Continue `{stage_label(infer_next_stage(state.get("stage_status", {})))}` for `{state.get("vault_root", "")}`.
""",
        encoding="utf-8",
    )
    return WORKSPACE_PROJECT_STATE_PATH


def sync_project_state_files(state: dict[str, Any]) -> dict[str, str]:
    topic_path = write_topic_handoff(state)
    index_path = write_workspace_index(state)
    return {
        "topic_handoff": str(topic_path),
        "workspace_index": str(index_path),
    }


def cmd_init(args: argparse.Namespace) -> None:
    topic = args.topic
    if not topic:
        topic = input("Research topic: ").strip()
    if not topic:
        raise SystemExit("A research topic is required.")

    slug = args.slug or slugify(topic)
    vault = args.vault or default_vault_name(topic, slug)

    state = {
        "schema_version": 1,
        "topic": topic,
        "slug": slug,
        "vault_root": vault,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "current_stage": "stage_1_discovery",
        "stage_status": stage_status_template(),
        "manual_pdf_queue": [],
        "notes": [
            "Initialized by deep-literature-workflow. Stage 1 should discover and score candidate papers."
        ],
    }
    save_state(state, args.state)
    project_state_paths = sync_project_state_files(state)
    state["project_state_files"] = project_state_paths
    print(json.dumps(state, ensure_ascii=False, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    if not state:
        print("No workflow state found. Run: dlw.py init --topic \"<research topic>\"")
        return
    next_stage = infer_next_stage(state.get("stage_status", {}))
    state["next_stage"] = next_stage or "complete"
    print(json.dumps(state, ensure_ascii=False, indent=2))


def cmd_next(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    if not state:
        print("No workflow state found. Initialize a topic first.")
        return
    stage = infer_next_stage(state.get("stage_status", {}))
    if not stage:
        print("All stages are marked done.")
        return
    guidance = {
        "stage_1_discovery": "Discover 200-500 candidates from OpenAlex/Semantic Scholar, dedupe, and score to 40-80 core candidates.",
        "stage_2_screening": "Audit core candidates, remove broad background papers, and choose 15-25 deep-reading papers.",
        "stage_3_pdf_acquisition": "Use the manual download queue, import user-provided PDFs, validate them, and update inventory.",
        "stage_4_paper_deep_reading": "Use paper-broad-reading-analysis to rebuild PDF-backed paper notes.",
        "stage_5a_concept_notes": "Write numbered concept knowledge notes under 03_Concepts, using 01_Concept_Index.md and 02_... onward for the recommended reading order.",
        "stage_5b_review_synthesis": "Write a domain review covering field structure, directions, methods, controversies, and expansion route. Store the reader-facing note as 02_Review.md; numbering follows reading order, not generation stage.",
        "stage_5c_evidence_matrices": "Build focused controversy matrices, method-comparability tables, and quantitative anchor CSVs.",
    }
    print(json.dumps({"next_stage": stage, "guidance": guidance[stage]}, ensure_ascii=False, indent=2))


def cmd_mark(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    if not state:
        raise SystemExit("No workflow state found.")
    if args.stage not in STAGES:
        raise SystemExit(f"Unknown stage: {args.stage}")
    state.setdefault("stage_status", stage_status_template())[args.stage] = args.status
    state["current_stage"] = infer_next_stage(state["stage_status"]) or "complete"
    state["updated_at"] = utc_now()
    if args.note:
        state.setdefault("notes", []).append(args.note)
    save_state(state, args.state)
    project_state_paths = sync_project_state_files(state)
    state["project_state_files"] = project_state_paths
    print(json.dumps(state, ensure_ascii=False, indent=2))


def cmd_manual_pdf(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    if not state:
        raise SystemExit("No workflow state found.")
    queue = state.setdefault("manual_pdf_queue", [])
    doi_url = args.doi_url or (f"https://doi.org/{args.doi}" if args.doi else None)
    entry = {
        "title": args.title,
        "doi": args.doi,
        "doi_url": doi_url,
        "landing_page_url": args.landing_page_url,
        "oa_url": args.oa_url,
        "expected_filename": args.expected_filename,
        "status": args.status,
        "reason": args.reason,
        "updated_at": utc_now(),
    }
    entry_key = (args.doi or args.expected_filename or args.title).strip().lower()
    updated = False
    for index, existing in enumerate(queue):
        existing_key = (
            existing.get("doi")
            or existing.get("expected_filename")
            or existing.get("title")
            or ""
        ).strip().lower()
        if existing_key == entry_key:
            queue[index] = {**existing, **{key: value for key, value in entry.items() if value is not None}}
            entry = queue[index]
            updated = True
            break
    if not updated:
        queue.append(entry)
    state["updated_at"] = utc_now()
    save_state(state, args.state)
    project_state_paths = sync_project_state_files(state)
    entry["project_state_files"] = project_state_paths
    print(json.dumps(entry, ensure_ascii=False, indent=2))


def cmd_manual_pdf_clear(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    if not state:
        raise SystemExit("No workflow state found.")
    cleared_count = len(state.get("manual_pdf_queue", []))
    state["manual_pdf_queue"] = []
    state["updated_at"] = utc_now()
    note = args.note or f"Manual PDF queue cleared ({cleared_count} item(s))."
    state.setdefault("notes", []).append(note)
    save_state(state, args.state)
    project_state_paths = sync_project_state_files(state)
    print(
        json.dumps(
            {
                "cleared": cleared_count,
                "manual_pdf_queue": [],
                "project_state_files": project_state_paths,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_index(args: argparse.Namespace) -> None:
    state = load_state(args.state)
    if not state:
        raise SystemExit("No workflow state found.")
    project_state_paths = sync_project_state_files(state)
    print(json.dumps(project_state_paths, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deep Literature Workflow state helper")
    parser.add_argument("--state", type=Path, default=STATE_PATH, help="Path to workflow state JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Initialize a literature workflow")
    p_init.add_argument("--topic", help="Research topic")
    p_init.add_argument("--slug", help="ASCII slug used for default vault folder")
    p_init.add_argument("--vault", help="Vault root folder")
    p_init.set_defaults(func=cmd_init)

    p_status = sub.add_parser("status", help="Print current workflow state")
    p_status.set_defaults(func=cmd_status)

    p_next = sub.add_parser("next", help="Print next stage guidance")
    p_next.set_defaults(func=cmd_next)

    p_mark = sub.add_parser("mark", help="Mark a stage status")
    p_mark.add_argument("stage", choices=STAGES)
    p_mark.add_argument("status", choices=["pending", "in_progress", "blocked", "done"])
    p_mark.add_argument("--note", help="Append a note to the state")
    p_mark.set_defaults(func=cmd_mark)

    p_manual = sub.add_parser("manual-pdf", help="Add or update a manual PDF queue item")
    p_manual.add_argument("--title", required=True)
    p_manual.add_argument("--doi")
    p_manual.add_argument("--doi-url")
    p_manual.add_argument("--landing-page-url")
    p_manual.add_argument("--oa-url")
    p_manual.add_argument("--expected-filename")
    p_manual.add_argument("--reason")
    p_manual.add_argument("--status", default="needed")
    p_manual.set_defaults(func=cmd_manual_pdf)

    p_manual_clear = sub.add_parser("manual-pdf-clear", help="Clear the manual PDF queue after successful import")
    p_manual_clear.add_argument("--note", help="Append a note explaining why the queue was cleared")
    p_manual_clear.set_defaults(func=cmd_manual_pdf_clear)

    p_index = sub.add_parser("index", help="Refresh workspace index and topic handoff paths")
    p_index.set_defaults(func=cmd_index)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
