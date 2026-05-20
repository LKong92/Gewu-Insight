# Paper Monitor

Paper Monitor is a local macOS paper-monitoring and reading assistant. It
fetches recent journal papers, stores state in SQLite, downloads PDFs when
possible, queues Codex reading-analysis jobs, and serves a browser UI.

## Quick Start on macOS

Double-click:

```text
Daico.app
```

On first launch the app will:

- create a local `.venv`
- install `requirements.txt`
- create local `data/` and `reports/` folders if needed
- start the UI server
- open the interface in its own native macOS window instead of a Safari tab

The first launch may take a minute while Python dependencies install. If it
fails, check:

```text
logs/paper_monitor_launcher.log
```

If double-clicking the app only flashes and no page opens, ask the user to run:

```bash
scripts/diagnose_macos.sh
```

The most common causes are missing `python3`, no network access during the first
dependency install, or macOS quarantine/permission changes after sharing the zip.
For Finder double-click launch, keep the whole project folder outside protected
macOS folders such as `Desktop`, `Documents`, and `Downloads`; a location such
as `~/Applications/PaperMonitor` or `~/PaperMonitor` is safer.

The only external requirement is a working `python3` command on macOS.

## Current Scope

Journal monitor:

- Nature
- Science
- Nature Materials
- Nature Physics
- Nature Photonics
- Physical Review Letters

The monitor fetches a rolling date window, stores papers in SQLite, and writes a
Markdown report. Empty fetches are recorded as fetch-run status only; they do not
close or permanently skip a date. Re-running the monitor over the same rolling
window will backfill delayed metadata.

## Manual Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Optional API politeness identifiers:

```bash
export OPENALEX_MAILTO=your.name@example.edu
export CROSSREF_MAILTO=your.name@example.edu
```

## Run Journal Monitor

Default behavior:

- fetches the most recent 14 days
- reports the most recent 14 days
- enriches metadata from paper landing pages when possible

```bash
python -m paper_monitor journal
```

Explicit window:

```bash
python -m paper_monitor journal --from-date 2026-05-01 --until-date 2026-05-14
```

When an explicit `--from-date` is provided, the Markdown report uses the same
window unless you also provide `--report-days`.

Skip landing-page enrichment for a faster metadata-only run:

```bash
python -m paper_monitor journal --no-enrich
```

Reports are written to:

```text
reports/daily/
```

The database is:

```text
data/paper_monitor.sqlite
```

## Download PDFs

Each paper in the Markdown report includes a command:

```bash
python -m paper_monitor download PAPER_ID
```

Download status is stored in SQLite and appears in future Markdown reports:

- `not_attempted`
- `success`
- `partial`
- `failed`
- `skipped`

If a paper was already downloaded successfully or partially, the command skips
it unless you pass `--force`.

```bash
python -m paper_monitor download PAPER_ID --force
```

The downloader tries to find a main PDF and PDF supplementary files, then merges
them when possible. After a successful merge, intermediate PDFs are deleted and
only the merged PDF is kept. It does not bypass paywalls or institutional login
walls.

## Analysis Notes

Queue a Codex analysis job:

```bash
python -m paper_monitor analyze PAPER_ID
```

`analyze` now queues a Codex analysis job instead of generating a note inside
the local UI process. The job records metadata, local PDF/supplement paths, the
current `paper-broad-reading-analysis` skill path, and the target note path.

```bash
python -m paper_monitor analysis-queue
```

Then ask Codex to process queued analysis jobs. Codex reads the queued job files,
the listed PDFs, and the current skill, writes the Chinese broad-reading note,
and moves completed jobs to `reports/analysis_jobs/done/`.

Distributed copies include bundled skill instructions at:

```text
skills/paper-broad-reading-analysis/SKILL.md
```

So a recipient who has Codex does not need to install the skill globally. They
can open this project in Codex and say:

```text
处理分析队列
```

Codex should read `AGENTS.md`, follow the queued job files, write notes to
`reports/analyses/`, and run `python -m paper_monitor complete-analysis-job ...`
after each note is written.

## Local UI

Start the local interface manually in a browser if needed:

```bash
python -m paper_monitor ui
```

Then open:

```text
http://127.0.0.1:8765
```

The UI reads the same SQLite database as the CLI. It provides:

- a calendar for selecting a report date
- journal filters and title/abstract/DOI search
- per-paper download and Queue Codex Analysis buttons
- a physical-science filter for physics/materials/chemistry-related papers
- a section filter for article/review/perspective-style sections
- configurable journal monitoring from the UI
- automatic one-day fetch when an unfetched calendar date is opened
- an on-demand analysis drawer for reading generated notes without leaving the page
- Preview-based PDF opening on macOS for downloaded merged PDFs
- per-paper deletion for local PDFs and generated analysis notes
- a Library view listing downloaded or queued/analyzed papers with date and journal filters
- visible download/analysis status so failed or completed actions are not lost

The Queue Codex Analysis button creates a job file under
`reports/analysis_jobs/queued/`. Codex can then process queued jobs and write
Chinese broad-reading notes under `reports/analyses/`.

A clickable macOS app is available in the project folder and is the recommended
way for non-developer users to start the app. It opens a native app window and keeps
the Paper Monitor icon in the Dock while the app is running:

```text
Daico.app
```

## Sharing This Project

To prepare a clean zip for another user:

```bash
scripts/make_release.sh
```

The release zip excludes local databases, PDFs, generated notes, logs, virtual
environments, and other personal artifacts. See `DISTRIBUTION.md` for details.

## Optional JSON Export

JSON is not used as the main state store. SQLite is the source of truth. You can
export JSON when needed:

```bash
python -m paper_monitor export-json reports/export.json
```
