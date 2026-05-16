# Distributing Paper Monitor

This project is prepared for macOS folder-based distribution.

## What to Share

Use the release script:

```bash
scripts/make_release.sh
```

It creates a zip under `dist/` containing:

- `Paper Monitor.app`
- source code under `paper_monitor/`
- `config/`
- `requirements.txt`
- `README.md`
- helper scripts
- empty `data/` and `reports/` directories

It does not include local SQLite databases, downloaded PDFs, generated notes,
analysis jobs, logs, virtual environments, or presentation/output artifacts.

## Recipient Requirements

The recipient needs macOS and a working `python3` command. On first launch,
`Paper Monitor.app` creates `.venv`, installs `requirements.txt`, starts the
local UI, and opens `http://127.0.0.1:8765`.

If the first launch fails, check:

```text
logs/paper_monitor_launcher.log
```

If the app only flashes and no page opens, run:

```bash
scripts/diagnose_macos.sh
```

The launcher now includes the last few log lines in its failure dialog. Common
causes are missing `python3`, blocked network access during dependency install,
quarantine/permission changes introduced by file sharing, or keeping the folder
inside protected macOS locations such as `Desktop`, `Documents`, or `Downloads`.
For Finder launch, tell recipients to move the whole folder to a regular location
such as `~/Applications/PaperMonitor` or `~/PaperMonitor`.

## Codex Analysis

The UI can queue Codex analysis jobs, but it does not bundle Codex itself. It
does bundle the paper-reading skill instructions at:

```text
skills/paper-broad-reading-analysis/SKILL.md
```

A recipient who has Codex can open the project folder in Codex and say:

```text
处理分析队列
```

Codex should read `AGENTS.md`, inspect `reports/analysis_jobs/queued/*.md`, read
the listed PDFs, write notes to `reports/analyses/`, and run
`python -m paper_monitor complete-analysis-job JOB_PATH` for each completed job.

If the user has installed a customized global skill, queued jobs may also point
to:

```text
~/.codex/skills/paper-broad-reading-analysis/SKILL.md
```

Users can override this with:

```bash
export PAPER_MONITOR_SKILL_PATH=/path/to/SKILL.md
```

## GitHub

For GitHub, commit source files, `Paper Monitor.app`, `config/`, scripts,
`README.md`, and `DISTRIBUTION.md`. Keep local data out of git using
`.gitignore`.
