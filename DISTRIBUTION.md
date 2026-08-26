# Distributing Gewu Insight

This project is prepared for macOS folder-based distribution.

## What to Share

Use the release script:

```bash
scripts/make_release.sh
```

It creates a zip under `dist/` containing:

- `Gewu Insight.app`
- source code under `paper_monitor/`
- `config/`
- `requirements.txt`
- `README.md`
- helper scripts
- empty `data/` and `reports/` directories

It does not include local SQLite databases, downloaded PDFs, generated notes,
logs, virtual environments, or presentation/output artifacts.

## Recipient Requirements

The recipient needs macOS and a working `python3` command. On first launch,
`Gewu Insight.app` creates `.venv`, installs `requirements.txt`, starts the
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

## GitHub

For GitHub, commit source files, `Gewu Insight.app`, `config/`, scripts,
`README.md`, and `DISTRIBUTION.md`. Keep local data out of git using
`.gitignore`.
