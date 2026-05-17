# PROJECT_STATE.md

## Current handoff

- Repo: `/Users/lingyuan/PaperMonitor-20260516`
- App launcher: `Paper Monitor.app`
- Main UI/API file: `paper_monitor/ui_server.py`
- SQLite is the source of truth: `data/paper_monitor.sqlite`
- Current Git HEAD before Library external page open fix: `89b192f Follow library preview on selection`

## Completed work

1. Analysis queue
   - Processed the queued Codex analysis job for the Nature Physics paper.
   - Wrote Chinese analysis note under `reports/analyses/`.
   - Completed the queue job and updated SQLite.

2. Nature-family PDF download reliability
   - Fixed false PDF detection where Springer/Nature “Peer Review File” could be treated as the main article PDF.
   - Added PDF magic-header validation and clearer partial-download messages.
   - Corrected the affected SQLite download status for a previously false-positive Nature paper.

3. Native macOS app behavior
   - Replaced Safari-tab launch behavior with a native macOS wrapper.
   - `.app` now opens a real app window and keeps its Dock icon.
   - Backup zip before this work: `backups/PaperMonitor-20260516-backup-before-native-window-20260516-183542.zip`

4. Calendar/report loading correctness
   - Fixed stale async report responses overwriting the currently selected date.
   - Local report loading is now decoupled from background fetching.
   - Users can browse already-loaded dates while another date is fetching.
   - Calendar updates after background fetch completion.

5. Fetch progress UI
   - Calendar cells now show only a green pulsing dot while fetching, not the word “Fetching”.
   - Right-side report pane shows live fetch progress:
     “Fetching papers for this date in the background. You can keep browsing other dates.”
   - Progress is percentage by completed journals, e.g. `1 / 4 journals completed`.

6. Report UI improvements
   - Journal Settings add/remove now refreshes UI state immediately.
   - Journal Settings only removes a journal from the explicit `Remove` button.
   - Journal add supports OpenAlex lookup for missing ISSN and remembers validated journals in history.
   - Field Filter is multi-select across `Physics`, `Materials`, `Chemistry`, `All Fields`, and `Other Fields`.
   - Each report/library item shows first three and last three authors when metadata has authors.
   - Journal names in paper meta rows are bold.
   - Report view now uses horizontal journal tabs with journal logos where available.
   - Report items can show first figures; the toolbar toggle shows/hides figures and the item layout adapts.
   - No-match dates get a red diagonal mark on the calendar cell.
   - Report item `Open` now opens inside the app via a local proxied internal page with a `Back` button, instead of launching Safari.
   - Date switching is kept responsive by limiting background journal fetches to one date at a time.
   - Report figure hydration is queued with low concurrency so publisher image lookups do not flood the local UI server.
   - The internal publisher page has an `External Browser` button that opens the current article URL with the system default browser.

7. PDF download fixes
   - Nature/Springer supplementary detection includes Peer Review File and Reporting Summary as supplements, while keeping them out of main-PDF candidates.
   - Science PDF candidates are augmented from Crossref `link` metadata and Science PDF/EPDF variants.
   - Physical Review candidates include direct APS `journals.aps.org/{journal}/pdf/{doi}` and `link.aps.org/pdf/{doi}` URLs.
   - Publisher Cloudflare/anti-bot 403 failures are reported clearly and no longer waste retry time.

8. Library rewrite
   - Library is now a filesystem-style workspace backed by SQLite folders and shortcut rows.
   - Existing downloaded/analyzed papers are seeded into the Library root on first migration.
   - Report items can be added to Library as shortcuts.
   - Library uses Finder-style left-to-right columns, supports six-plus-level folders, drag/drop moving, folder rename, Finder-like keyboard navigation, adjustable Space-to-in-app PDF preview, PDF download from details, and a Zotero-like detail panel with BibTeX.

## Useful commits

- `ab9566a` Initial local snapshot before native app window work
- `dbf5916` Open Paper Monitor in a native macOS window
- `1181036` Keep calendar navigation responsive during background fetches
- `8e6e7a7` Show calendar progress while a date is fetching
- `5d77520` Show live fetch progress in report view
- `eaf2cc7` Improve report grouping and field filters
- `31803ce` Improve report media and internal article viewing
- `df30f7a` Rewrite library as folder workspace
- `c4809f2` Open library PDFs in Preview
- `89b192f` Follow library preview on selection

## Verification already done

- Ran Python compile check:
  `PYTHONPYCACHEPREFIX=/private/tmp/paper-monitor-pycache .venv/bin/python -m py_compile paper_monitor/*.py paper_monitor/sources/*.py`
- Ran frontend JavaScript syntax check by extracting the embedded script and using `new Function(...)`.
- Smoke-tested `http://127.0.0.1:8766/`, `/api/report?date=2026-05-15`, and `/api/page-proxy?url=https%3A%2F%2Fwww.nature.com%2Fnphys%2F`.
- Smoke-tested `http://127.0.0.1:8767/`; `/api/report?date=2026-05-15&auto_fetch=0` returned in about 0.013s.
- Verified `/api/open-url` rejects invalid URLs without launching a browser.
- Verified in the native `.app`:
  - live fetch progress appears and updates,
  - fetching calendar cell uses a dot only,
  - switching dates during fetch still works,
  - report grouping and author display are visible.

## Current caveats

- Field classification is keyword/journal-hint based, not a learned classifier. Some interdisciplinary papers may appear in multiple fields or the closest heuristic field.
- Fetch progress percentage is by journal completion, not elapsed time or individual paper count.
- New-journal auto-detection depends on network access to OpenAlex; if unavailable, users must provide ISSNs manually.
- Article figure, journal logo enrichment, and publisher PDF downloads depend on publisher page/network availability; Science.org and APS may still require browser/manual PDF attachment.
