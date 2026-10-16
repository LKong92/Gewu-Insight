# AGENTS.md

## Context Loading

- Before broad repo exploration, read `PROJECT_STATE.md` first.
- Use `PROJECT_STATE.md` as the current handoff summary.
- Do not scan the whole repo unless the task requires it.

## Project Rules

- This repo is a local paper-monitoring and research reading assistant. Use paths relative to the repo root unless the user gives an absolute path.
- SQLite is the source of truth; JSON is export-only.
- Obtain real paper files through the configured Gewu MCP. `get_paper_file` delivers an authorized read-only client copy that may be read/rendered/OCR-processed locally; this does not authorize direct Library/SQLite access. Write derived outputs separately. `save_analysis` only appends classified Markdown notes; no MCP operation may edit, overwrite or delete existing Paper Files, including earlier AI analyses.
- User-authorized development exception (2026-09-10): developing, optimizing and debugging Gewu may directly read local files, SQLite, logs and internal interfaces as needed, without a separate MCP-bypass approval. Ordinary literature queries, citations and analyses still require MCP. Data changes remain scoped to the authorized development task.
- Keep Markdown reports and analysis notes useful as user-facing reading artifacts.
- Prefer scoped edits that reuse existing `paper_monitor` modules.
- Avoid filtering by user research keywords unless explicitly requested.
- UI labels should stay in English unless the user asks otherwise.
- Generated analysis content should be Chinese, except original metadata such as title, journal, DOI, PDF path, and source identifiers.
- PDF opening from the UI should use macOS Preview.
- `Note` should open on demand as a right-side drawer that compresses the report area and scrolls independently.
- Keep the left calendar/filter column independent from report scrolling.
- Calendar day counts show numbers only. Subject Monitor must not display an incomplete-discovery asterisk or its explanatory legend; keep internal fetch status tracking.
- Preserve download and analysis status so repeated actions are visible and avoidable.
- Subject Monitor must reject Zenodo records during candidate ingestion and cached-result display; do not expose a Zenodo show/hide control.
- Keep `main` product-only. Benchmark instrumentation, source overrides, tests, data, and artifacts must stay in a separate local benchmark worktree and must not change product runtime behavior.
- Develop and commit product changes directly on `main`. Do not create extra product branches or PRs unless the user explicitly requests them; GitHub should retain only `main` and the existing Windows branch. Preserve existing isolated local benchmark worktrees without publishing them.
- Never push benchmark branches, benchmark-only commits, benchmark artifacts, or benchmark data to GitHub.
- The product and evaluation repositories are public by explicit user authorization. Preserve their current visibility; documentation, cleanup and release work do not authorize changing visibility.
- Keep unused design drafts and machine-specific historical logs in ignored `local-development-archive/`; retain a concise current handoff in Git.

## Commit Messages

- Every future commit must include a specific English subject, a blank line, and a readable English body describing purpose, concrete changes, relevant behavior/data boundaries, and actual validation. Never claim unrun tests passed.
- Follow `docs/COMMIT_GUIDELINES.md` and inspect every outgoing commit message before pushing. Leave existing history and hashes unchanged; do not rewrite or force-push history to add descriptions.
- Commit or push only when explicitly requested. Stage related files by name, never with `git add -A`, and preserve existing user changes.

## Commands

- Daily App: `/Applications/Gewu Insight.app`. Formal data belongs in the user's selected `Gewu Database`; discover the local location instead of copying another machine's path. Never implicitly recreate project-local user data.
- Development CLI commands require `GEWU_WORKSPACE_ROOT` pointing to an isolated workspace. Initialize once with `python3 -m paper_monitor.workspace create "$PWD/tmp/development-database"`, then export that path for the commands below.
- The old project App is a non-launchable build seed in `assets/macos-app-template.zip`. Native builds extract it temporarily; standalone builds stage their own App. Existing bundle-reading tests need a temporary extracted template, removed after testing.

- Setup: `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`
- Run UI: `python3 -m paper_monitor ui --port 8765`
- Run journal monitor: `python3 -m paper_monitor journal`
- Run explicit journal window: `python3 -m paper_monitor journal --from-date YYYY-MM-DD --until-date YYYY-MM-DD`
- Download paper: `python3 -m paper_monitor download PAPER_ID`
- Compile check: `python3 -m py_compile paper_monitor/*.py paper_monitor/sources/*.py`

## Key Paths

- `paper_monitor/`: main Python package.
- `paper_monitor/ui_server.py`: local web UI and UI API.
- `config/journals.json`: monitored journals and section policies.
- Selected workspace `data/paper_monitor.sqlite`: SQLite database; never use the source checkout for formal data.
- Selected workspace `reports/daily/`: generated Markdown reports.
- Paper Files AI analyses live in selected workspace `data/Associated Files/`; legacy reports remain under its `reports/`.
- `README.md`: user-facing usage documentation.

## Done Criteria

- Follow `docs/USER_GUIDE_SCREENSHOTS.md`: real original App only, no overlays or hidden navigation; retain all six tabs. Show Add Monitored Author empty without cooldown text, Hong Ding for Author Monitor, Nature with figures for Journal Monitor, and classified multiple Paper Files for Library.
- In the PDF, Product Identity chapters 4-1 through 4-4 flow continuously; do not force each onto a new page. Preserve numbering/links and encode this rule in the builder, not only generated TeX.
- Relevant CLI or UI workflow still works for the changed area.
- Run `py_compile` for Python code changes when practical.
- Keep `AGENTS.md` concise and `PROJECT_STATE.md` under 100 lines when updating project context.
