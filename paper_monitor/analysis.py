from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import DEFAULT_ANALYSIS_DIR, DEFAULT_PDF_DIR, ROOT
from .reporting import analysis_filename
from .storage import Storage
from .text import safe_slug
from .time_utils import now_iso


DEFAULT_ANALYSIS_JOB_DIR = ROOT / "reports" / "analysis_jobs"
BUNDLED_SKILL_PATH = ROOT / "skills" / "paper-broad-reading-analysis" / "SKILL.md"
USER_SKILL_PATH = Path.home() / ".codex" / "skills" / "paper-broad-reading-analysis" / "SKILL.md"
DEFAULT_SKILL_PATH = Path(os.getenv("PAPER_MONITOR_SKILL_PATH") or (BUNDLED_SKILL_PATH if BUNDLED_SKILL_PATH.exists() else USER_SKILL_PATH))


def queue_codex_analysis(
    *,
    storage: Storage,
    paper_id: str,
    job_dir: Path = DEFAULT_ANALYSIS_JOB_DIR,
    output_dir: Path = DEFAULT_ANALYSIS_DIR,
    skill_path: Path = DEFAULT_SKILL_PATH,
) -> Path:
    paper = storage.get_paper(paper_id)
    if not paper:
        raise ValueError(f"Unknown paper id: {paper_id}")

    queued_dir = job_dir / "queued"
    queued_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    analysis_path = output_dir / analysis_filename(paper)
    pdf_paths = collect_pdf_paths(paper)
    job_path = queued_dir / job_filename(paper)
    job = {
        "status": "queued",
        "created_at": now_iso(),
        "skill_path": str(skill_path),
        "paper": {
            "paper_id": paper.get("paper_id") or "",
            "title": paper.get("title") or "",
            "journal": paper.get("journal") or "",
            "publication_date": paper.get("publication_date") or "",
            "doi": paper.get("doi") or "",
            "url": paper.get("url") or paper.get("landing_url") or "",
            "abstract": paper.get("abstract") or "",
        },
        "pdf_paths": [str(path) for path in pdf_paths],
        "analysis_path": str(analysis_path),
        "instructions": [
            "Use the paper-broad-reading-analysis skill instructions.",
            "If the skill is not installed in Codex, read the bundled skill file at skill_path and follow it directly.",
            "Read only the listed PDFs, the skill file, and necessary metadata.",
            "Write the final Chinese broad-reading note to analysis_path.",
            "After writing the note, run: python -m paper_monitor complete-analysis-job JOB_PATH",
        ],
    }
    job_path.write_text(render_job_markdown(job), encoding="utf-8")
    storage.queue_analysis(paper_id, analysis_path=str(analysis_path), message=f"job: {job_path}")
    return job_path


def collect_pdf_paths(paper: dict[str, Any]) -> list[Path]:
    raw_paths: list[str] = []
    for key in ("merged_pdf_path", "main_pdf_path"):
        value = paper.get(key)
        if value:
            raw_paths.append(str(value))

    supplements = paper.get("supplement_pdf_paths")
    if supplements:
        try:
            raw_paths.extend(str(value) for value in json.loads(supplements) if value)
        except (TypeError, json.JSONDecodeError):
            pass

    paths: list[Path] = []
    for raw_path in raw_paths:
        path = Path(raw_path).expanduser()
        if path.exists() and path.suffix.lower() == ".pdf":
            paths.append(path)

    search_dirs: list[Path] = []
    for path in paths:
        if path.parent not in search_dirs:
            search_dirs.append(path.parent)
    paper_dir = DEFAULT_PDF_DIR / str(paper.get("paper_id") or "")
    if paper_dir.exists() and paper_dir not in search_dirs:
        search_dirs.append(paper_dir)

    for directory in search_dirs:
        for path in sorted(directory.glob("*.pdf")):
            if path not in paths:
                paths.append(path)

    seen: set[Path] = set()
    output: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            output.append(path)
    return output


def pending_analysis_jobs(job_dir: Path = DEFAULT_ANALYSIS_JOB_DIR) -> list[Path]:
    queued_dir = job_dir / "queued"
    if not queued_dir.exists():
        return []
    jobs: list[Path] = []
    for path in sorted(queued_dir.glob("*.md")):
        job = read_job(path)
        analysis_path = Path(str(job.get("analysis_path") or ""))
        if not analysis_path.exists():
            jobs.append(path)
    return jobs


def mark_job_done(job_path: Path, *, note_path: Path | None = None, job_dir: Path = DEFAULT_ANALYSIS_JOB_DIR) -> Path:
    job = read_job(job_path)
    job["status"] = "done"
    job["completed_at"] = now_iso()
    if note_path:
        job["analysis_path"] = str(note_path)
    done_dir = job_dir / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    done_path = done_dir / job_path.name
    done_path.write_text(render_job_markdown(job), encoding="utf-8")
    job_path.unlink(missing_ok=True)
    return done_path


def read_job(job_path: Path) -> dict[str, Any]:
    text = job_path.read_text(encoding="utf-8")
    marker = "```json"
    start = text.find(marker)
    if start < 0:
        return {}
    start = text.find("\n", start)
    end = text.find("```", start + 1)
    if start < 0 or end < 0:
        return {}
    return json.loads(text[start:end].strip())


def render_job_markdown(job: dict[str, Any]) -> str:
    paper = job["paper"]
    pdf_lines = "\n".join(f"- `{path}`" for path in job.get("pdf_paths") or []) or "- 未找到本地 PDF"
    return f"""# Codex Analysis Job

- Status: `{job["status"]}`
- Created: `{job.get("created_at") or ""}`
- Paper ID: `{paper.get("paper_id") or ""}`
- Title: {paper.get("title") or ""}
- Journal: {paper.get("journal") or ""}
- Date: {paper.get("publication_date") or ""}
- DOI: {paper.get("doi") or ""}
- Skill: `{job.get("skill_path") or ""}`
- Output: `{job.get("analysis_path") or ""}`

## PDFs

{pdf_lines}

## Machine Data

```json
{json.dumps(job, ensure_ascii=False, indent=2)}
```
"""


def job_filename(paper: dict[str, Any]) -> str:
    date = paper.get("publication_date") or "unknown-date"
    paper_id = paper.get("paper_id") or safe_slug(paper.get("title") or "paper", 80)
    return f"{date}_{safe_slug(str(paper_id), 80)}.md"
