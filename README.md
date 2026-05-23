# Daiqo

Daiqo is a local macOS research-library and paper-monitoring assistant. It now
opens into a Library-first workspace: you organize papers, preview PDFs, keep
your own publication list, import folders, and use Journal Monitor as one of the
tools attached to the library rather than as the whole app.

All persistent state lives in SQLite. JSON and Markdown are generated artifacts,
not the source of truth.

## What Daiqo Does

- **Library workspace**: Finder-style columns for folders and paper shortcuts,
  with drag/drop, rename, copy/paste, delete/recover, keyboard navigation,
  folder colors, shortcut tabs, and independent green Spaces.
- **PDF reading surface**: Space opens an in-app PDF preview with page
  thumbnails, page syncing, resizable preview window, and macOS Preview opening
  for full editing or annotation.
- **Paper details**: title, journal, DOI, abstract, author list, BibTeX,
  Nature-style citation text, Google Scholar lookup, first-figure previews, and
  download/analysis status.
- **My Publications**: store your own publications, highlight rows, drag rows to
  reorder them, import a Google Scholar profile, and use per-row **Reimport** to
  refresh a Scholar-imported row through DOI/Crossref metadata.
- **Journal Monitor**: monitor journals and arXiv categories, browse papers by
  date, field, journal, search term, and figure visibility, then add papers into
  Library.
- **Folder Loader**: import an existing folder tree into Library with a dry-run
  mode, live log, duplicate detection, missing-file reporting, and no destructive
  changes to the source folder.
- **Codex analysis queue**: queue paper-reading jobs and let Codex write Chinese
  analysis notes from local PDFs.

The current launcher in this repository is:

```text
Daiqo.app
```

## Quick Start

Double-click:

```text
Daiqo.app
```

On first launch the app will:

- create a local `.venv`
- install `requirements.txt`
- create local `data/`, `pdfs/`, and `reports/` folders as needed
- start the local UI server
- open a native macOS window instead of a Safari tab

The first launch can take a minute while dependencies install. If launch fails,
check:

```text
logs/paper_monitor_launcher.log
```

The only external runtime requirement is a working `python3` command on macOS.
For Finder double-click launch, keep the project outside protected macOS folders
when possible; a path such as `~/Applications/Daiqo` or `~/Daiqo` is safer than
Desktop, Documents, or Downloads.

## Manual Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Start the UI manually:

```bash
python3 -m paper_monitor ui --port 8765
```

Then open:

```text
http://127.0.0.1:8765
```

Optional API politeness identifiers:

```bash
export OPENALEX_MAILTO=your.name@example.edu
export CROSSREF_MAILTO=your.name@example.edu
```

## Main Screens

### Library

Library is the default screen. It stores paper shortcuts and folders in SQLite,
while PDFs and reports remain regular files on disk.

Useful interactions:

- click folders to move through Finder-style columns
- use arrow keys to navigate folders and papers
- hold Shift while selecting to range-select entries
- drag folders or paper shortcuts to move or reorder them
- right-click for folder and item actions
- press Space to open or close the in-app PDF preview
- use Details to open PDFs in Preview, copy BibTeX/reference text, download PDFs,
  and inspect metadata
- press Command-F in Library to search without re-rendering on every keystroke

Library search is scoped to the active Library root or Space. Large result sets
show the first visible batch and report the total count in the fixed header.

### My Publications

My Publications is a personal publication table inside Library.

You can:

- add papers by DOI or title through Crossref lookup
- search by saved author name
- import a Google Scholar profile as a simple first pass
- click **Reimport** on an imported row to find its DOI and rewrite that row
  using DOI/Crossref metadata
- drag rows to set a manual display order
- use the star button to highlight important entries

Google Scholar can temporarily block automated profile fetches with a 429 or
verification page. Daiqo reports that clearly and does not keep retrying, because
retries usually extend the block. In that case, wait before trying again or open
the Scholar profile in your browser first.

### Journal Monitor

Journal Monitor is available from the top view switcher. It watches configured
journals and arXiv categories, then stores results in the same SQLite database.

The UI supports:

- calendar day counts
- journal, preprint, and field filters
- title/abstract/DOI search
- optional first-figure display
- background fetch progress while browsing other dates
- adding report items into Library
- queueing downloads and Codex analysis jobs

The monitored list is configured in:

```text
config/journals.json
```

### Folder Loader

Folder Loader imports an existing folder of papers/resources into Library.

Recommended workflow:

1. Choose a source folder.
2. Run **Dry Run**.
3. Inspect created/updated/duplicate/missing counts.
4. Run **Import** only after the dry run looks right.

The source folder is read-only from Daiqo's perspective. Source files are not
moved or deleted.

## CLI Commands

Run the local UI:

```bash
python3 -m paper_monitor ui --port 8765
```

Run Journal Monitor for the default rolling window:

```bash
python3 -m paper_monitor journal
```

Run an explicit journal window:

```bash
python3 -m paper_monitor journal --from-date 2026-05-01 --until-date 2026-05-14
```

Download a paper PDF:

```bash
python3 -m paper_monitor download PAPER_ID
```

Force a PDF re-download:

```bash
python3 -m paper_monitor download PAPER_ID --force
```

Queue a Codex analysis job:

```bash
python3 -m paper_monitor analyze PAPER_ID
```

Inspect queued analysis jobs:

```bash
python3 -m paper_monitor analysis-queue
```

Complete a queued analysis job after Codex writes the note:

```bash
python3 -m paper_monitor complete-analysis-job reports/analysis_jobs/queued/JOB.md
```

Export JSON when needed:

```bash
python3 -m paper_monitor export-json reports/export.json
```

## Data Layout

Important paths:

```text
data/paper_monitor.sqlite      SQLite source of truth
pdfs/                          downloaded and merged PDFs
reports/daily/                 generated Markdown daily reports
reports/analyses/              generated Chinese analysis notes
reports/analysis_jobs/queued/  pending Codex analysis jobs
reports/analysis_jobs/done/    completed Codex analysis jobs
config/journals.json           monitored journal/source configuration
logs/                          launcher and runtime logs
```

Generated analysis content should be Chinese. Original metadata such as title,
journal, DOI, PDF path, and source identifiers remain in their source language.

## Downloads and Analysis

PDF download status is preserved in SQLite so repeated actions are visible:

- `not_attempted`
- `success`
- `partial`
- `failed`
- `skipped`

The downloader looks for a main PDF and PDF supplements, then merges files when
possible. It does not bypass paywalls or institutional login walls.

`analyze` creates a job under `reports/analysis_jobs/queued/`. Codex reads the
job file, PDFs, and bundled skill instructions, writes a Chinese note under
`reports/analyses/`, then runs `complete-analysis-job` to update SQLite and move
the job to `done/`.

Bundled analysis skill:

```text
skills/paper-broad-reading-analysis/SKILL.md
```

## Sharing

To prepare a clean zip for another user:

```bash
scripts/make_release.sh
```

The release zip excludes local databases, PDFs, generated notes, logs, virtual
environments, and other personal artifacts. See `DISTRIBUTION.md` for details.

## Developer Notes

- Keep SQLite as the source of truth.
- Treat JSON as export-only.
- Keep UI labels in English unless intentionally changing the product language.
- Use `paper_monitor/ui_server.py` for most local UI/API behavior.
- Run this compile check after Python changes:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/paper-monitor-pycache \
python3 -m py_compile paper_monitor/*.py paper_monitor/sources/*.py
```
