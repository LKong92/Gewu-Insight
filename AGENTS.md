# AGENTS.md

## Context Loading

- Before broad repo exploration, read `PROJECT_STATE.md` first.
- Use `PROJECT_STATE.md` as the current handoff summary.
- Do not scan the whole repo unless the task requires it.

## Project Rules

- This repo is a local paper-monitoring and research reading assistant. Use paths relative to the repo root unless the user gives an absolute path.
- SQLite is the source of truth; JSON is export-only.
- Keep Markdown reports and analysis notes useful as user-facing reading artifacts.
- Prefer scoped edits that reuse existing `paper_monitor` modules.
- Avoid filtering by user research keywords unless explicitly requested.
- UI labels should stay in English unless the user asks otherwise.
- Generated analysis content should be Chinese, except original metadata such as title, journal, DOI, PDF path, and source identifiers.
- PDF opening from the UI should use macOS Preview.
- `Note` should open on demand as a right-side drawer that compresses the report area and scrolls independently.
- Keep the left calendar/filter column independent from report scrolling.
- Calendar day counts should show numbers only, with a superscript asterisk for incomplete Subject Monitor discovery.
- Preserve download and analysis status so repeated actions are visible and avoidable.
- Subject Monitor must reject Zenodo records during candidate ingestion and cached-result display; do not expose a Zenodo show/hide control.
- Keep `main` product-only. Benchmark instrumentation, source overrides, tests, data, and artifacts must stay in a separate local benchmark worktree and must not change product runtime behavior.
- Never push benchmark branches, benchmark-only commits, benchmark artifacts, or benchmark data to GitHub.

## Commands

- Setup: `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`
- Run UI: `python3 -m paper_monitor ui --port 8765`
- Run journal monitor: `python3 -m paper_monitor journal`
- Run explicit journal window: `python3 -m paper_monitor journal --from-date YYYY-MM-DD --until-date YYYY-MM-DD`
- Download paper: `python3 -m paper_monitor download PAPER_ID`
- Compile check: `python3 -m py_compile paper_monitor/*.py paper_monitor/sources/*.py`
- Clickable launcher: `Gewu Insight.app`

## Key Paths

- `paper_monitor/`: main Python package.
- `paper_monitor/ui_server.py`: local web UI and UI API.
- `config/journals.json`: monitored journals and section policies.
- `data/paper_monitor.sqlite`: SQLite database.
- `reports/daily/`: generated Markdown reports.
- `reports/analyses/`: generated analysis notes.
- `README.md`: user-facing usage documentation.

## Done Criteria

- Relevant CLI or UI workflow still works for the changed area.
- Run `py_compile` for Python code changes when practical.
- Keep `AGENTS.md` concise and `PROJECT_STATE.md` under 100 lines when updating project context.
