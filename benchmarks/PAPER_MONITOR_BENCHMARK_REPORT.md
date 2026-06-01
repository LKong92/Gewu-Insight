# Paper Monitor Local Benchmark Report

## Environment

- Benchmark time: 2026-06-01T22:44:58
- Project path: `/Users/lingyuan/PaperMonitor-20260516`
- Local service URL: `http://127.0.0.1:8765`
- Python: 3.9.13
- macOS: 15.1.1
- Machine: Apple M1 Max
- Git commit: `235c332`

## Local-Only Safety

- The benchmark used only local SQLite reads and HTTP requests to `http://127.0.0.1:8765`.
- No code, database, PDFs, logs, screenshots, traces, or benchmark artifacts were uploaded.
- No destructive import, download, delete, analysis, or metadata-refresh action was executed.
- No browser automation dependency was installed; UI flow coverage below is based on local HTML/API readiness and PDF preview endpoints.

## Service Health

- Root HTML shell: 20/20 OK, mean 2.991 ms, p95 4.631 ms.
- Library bootstrap API: 20/20 OK, mean 11.278 ms, p95 13.299 ms.
- Health route note: `/api/health` is not registered; service health was confirmed via `/` and `/api/library/bootstrap`.

## API Route Discovery

- Routes discovered in `paper_monitor/ui_server.py`: 101
- `/api/...` routes discovered: 98
- Sample API routes: `/api/analysis, /api/analyze, /api/arxiv-daily-refresh, /api/cache/clear-web, /api/deep-survey/status, /api/delete-analysis, /api/delete-pdf, /api/download, /api/fetch-progress, /api/file-icon, /api/google-scholar-profiles, /api/journal-logo, /api/journals, /api/journals/add, /api/journals/remove, /api/library, /api/library/bootstrap, /api/library/delete, /api/library/delete-batch, /api/library/delete-file`

## Dataset

- Papers: 11402
- Papers with PDFs: 5952
- Library items: 8469
- Library folders: 1303
- Resources: 8441
- My Publications: 40
- SQLite DB size: 246.9 MB
- Library file tree size: 26.6 GB
- Spaces file tree size: 89.8 MB
- Busiest sampled folder items: 462
- Latest sampled report date: `2026-06-01`
- Sample PDF size: 55.5 MB

## Results

| Scenario | Kind | OK/Requested | Mean ms | Median ms | P95 ms | P99 ms | Errors | Mean bytes read |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| UI HTML shell | http | 20/20 | 2.991 | 2.419 | 4.631 | 5.754 | 0 | 669471.0 |
| Library bootstrap | http | 20/20 | 11.278 | 9.885 | 13.299 | 31.441 | 0 | 378474.0 |
| Full library snapshot | http | 20/20 | 361.748 | 361.684 | 371.191 | 371.262 | 0 | 8630265.0 |
| Library root folder | http | 20/20 | 3.307 | 2.695 | 4.673 | 10.722 | 0 | 7080.0 |
| Library busiest folder | http | 20/20 | 13.926 | 13.009 | 17.853 | 18.878 | 0 | 421394.0 |
| Latest report no-fetch | http | 20/20 | 6.030 | 5.107 | 8.526 | 11.365 | 0 | 2091.0 |
| PDF info | http | 20/20 | 50.195 | 48.292 | 56.394 | 82.725 | 0 | 101.0 |
| PDF thumbnail p1 | http | 20/20 | 143.759 | 138.508 | 176.124 | 192.379 | 0 | 11469.0 |
| PDF file first 64KB | http | 20/20 | 11.175 | 11.018 | 13.444 | 14.132 | 0 | 65536.0 |
| SQLite count papers | sqlite | 20/20 | 0.008 | 0.008 | 0.008 | 0.009 | 0 | 0.0 |
| SQLite count library items | sqlite | 20/20 | 0.006 | 0.006 | 0.006 | 0.009 | 0 | 0.0 |
| SQLite folder children | sqlite | 20/20 | 0.044 | 0.044 | 0.047 | 0.048 | 0 | 0.0 |
| SQLite title search quantum | sqlite | 20/20 | 15.149 | 15.012 | 15.847 | 15.967 | 0 | 0.0 |

## Local Score

Overall local score: **91 / 100**

| Area | Score | Why |
|---|---:|---|
| Service health and app shell | 100 | Root shell p95 4.631 ms; Library bootstrap p95 13.299 ms. |
| Library scale handling | 83 | Full snapshot p95 371.191 ms with about 8.2 MB payload; busiest folder p95 17.853 ms. |
| PDF preview pipeline | 94 | PDF info p95 56.394 ms; page thumbnail p95 176.124 ms; first 64KB p95 13.444 ms. |
| SQLite/query layer | 100 | Title search p95 15.847 ms on the local database. |
| UI workflow evidence | 70 | Covered by local API/HTML/PDF endpoint proxies; no browser automation trace was installed or run. |
| Local-only reproducibility | 100 | Single standard-library script, local SQLite reads, loopback HTTP only, JSON plus Markdown output. |

Interpretation:

- `90-100`: excellent local desktop responsiveness for this dataset.
- `75-89`: good, with one or two clear bottlenecks.
- `60-74`: usable but likely noticeable waits in common workflows.
- `<60`: needs focused performance work before broad daily use.

## Slowest P95

- Full library snapshot: p95 371.191 ms, mean 361.748 ms
- PDF thumbnail p1: p95 176.124 ms, mean 143.759 ms
- PDF info: p95 56.394 ms, mean 50.195 ms
- Library busiest folder: p95 17.853 ms, mean 13.926 ms
- SQLite title search quantum: p95 15.847 ms, mean 15.149 ms

## UI Flow Coverage

This first pass avoids installing Playwright/k6/autocannon/hyperfine and avoids screenshots/traces.
The measured local-only proxy for the core UI flow is:

- Open app shell: `UI HTML shell`
- Open Library: `Library bootstrap`, `Library root folder`, `Library busiest folder`
- Search-like workload: `SQLite title search quantum`
- Click/select paper detail data source: `Full library snapshot` and folder endpoints
- PDF preview path: `PDF info`, `PDF thumbnail p1`, `PDF file first 64KB`

## Positioning Versus Commercial Reference Managers

This is a product-positioning comparison, not a same-machine benchmark of the other apps.
No commercial software was installed or tested by this script.

| Product | Public positioning | Where Daiqo is stronger | Where Daiqo is weaker / unproven |
|---|---|---|---|
| Zotero | Open-source reference manager with browser capture, citation plugins, sync, groups, notes, and PDF annotation. See https://www.zotero.org/ | Daiqo is more local-workflow-first for monitored papers, filesystem-like Spaces, loader/import workflows, and Chinese analysis artifacts. | Zotero is much more mature for citation workflows, cross-device sync, group libraries, connectors, and broad community ecosystem. |
| EndNote | Commercial reference manager centered on library/reference editing, PDF attachment/viewing/annotation, full-text discovery, and Word workflows. See https://docs.endnote.com/ | Daiqo feels more specialized for a personal research-reading pipeline, local journal monitoring, and direct Library filesystem organization. | EndNote is stronger for institutional citation management, manuscript workflows, and established support/documentation. |
| Mendeley Reference Manager | Reference manager with PDF reader, annotations, Notebook, and Word citation workflow. See https://www.mendeley.com/reference-management/reference-manager | Daiqo keeps the tested workload local and is built around local paper monitoring plus project-specific Library/Spaces behavior. | Mendeley is stronger for standard citation/reference workflows and account-based sync; Daiqo has not been benchmarked for collaboration/sync. |
| ReadCube Papers | Literature manager with SmartLists, annotations, subscription integration, group management, and AI-oriented library features. See https://www.readcube.com/ | Daiqo is more transparent/local for the user's own database and file tree, and can be tailored tightly to the user's reading workflow. | ReadCube Papers is stronger as a polished commercial cross-device product; Daiqo's UI polish and PDF preview smoothness still need iteration. |

Bottom line: Daiqo currently scores as a good local specialized research cockpit, not as a drop-in replacement for mature citation-suite software. Its biggest measured bottleneck is the full Library snapshot payload; its biggest product differentiator is local monitored-reading workflow plus filesystem-like Library/Spaces.

## Reproduction

```bash
python3 scripts/bench_local.py --base-url http://127.0.0.1:8765 --runs 20 --warmup 2
```

JSON result:

```text
benchmarks/results/local_benchmark_20260601-224458.json
```
