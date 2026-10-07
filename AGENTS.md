# AGENTS.md

## Context Loading

- Before broad repo exploration, read `PROJECT_STATE.md` first.
- Use `PROJECT_STATE.md` as the current handoff summary.
- Do not scan the whole repo unless the task requires it.

## Project Rules

- This repo is a local paper-monitoring and research reading assistant. Use paths relative to the repo root unless the user gives an absolute path.
- SQLite is the source of truth; JSON is export-only.
- Obtain paper files through configured Gewu MCP: `get_paper_file` provides an authorized read-only client copy for local reading/rendering/OCR, not direct Library/SQLite access. Write derived files separately; `save_analysis` only appends classified Markdown notes and never edits existing Paper Files or earlier analyses.
- Keep Markdown reports and analysis notes useful as user-facing reading artifacts.
- Do not create or update help documents, user guides, or their PDFs unless the user explicitly requests them; prioritize software changes and necessary validation.
- Prefer scoped edits that reuse existing `paper_monitor` modules.
- Avoid filtering by user research keywords unless explicitly requested.
- UI labels should stay in English unless the user asks otherwise.
- Generated analysis content should be Chinese, except original metadata such as title, journal, DOI, PDF path, and source identifiers.
- PDF opening uses macOS Preview on macOS and the registered Windows PDF application on Windows.
- `Note` should open on demand as a right-side drawer that compresses the report area and scrolls independently.
- Keep the left calendar/filter column independent from report scrolling.
- Calendar day counts show numbers only. Subject Monitor must not display an incomplete-discovery asterisk or its explanatory legend; keep internal fetch status tracking.
- Preserve download and analysis status so repeated actions are visible and avoidable.
- Download PDFs only from verified publishers or authorized repositories. Stop on unverified sources/redirects; never use piracy services or bypass subscription/access controls.
- Subject Monitor must reject Zenodo records during candidate ingestion and cached-result display; do not expose a Zenodo show/hide control.
- Keep `main` product-only. Benchmark instrumentation, source overrides, tests, data, and artifacts must stay in a separate local benchmark worktree and must not change product runtime behavior.
- Never push benchmark branches, benchmark-only commits, benchmark artifacts, or benchmark data to GitHub.
- Windows development and releases stay on a separate Windows branch (`codex/windows-preview-0.1.10-20260910` or an explicitly chosen successor). Never merge or push Windows changes into remote `main` or any macOS branch without a new explicit user request.
- Windows startup is installed-App-only. Source is for development, isolated tests and building installers. `Start Gewu Insight.cmd` opens the installed Start-menu shortcut; never launch the historical source shell for daily use or acceptance. Other computers/VMs have independent installation status.
- Windows parity excludes Apple Passwords/AutoFill, Safari source sync, and macOS system Quick Look; the user does not need those Apple-specific capabilities.
- User-approved Windows development workflow (2026-10-06): **edit source → build a versioned Setup.exe → install/update locally → test the installed App → report results and deliver the local installer**. The workflow ends locally; passing validation never triggers publication. Keep this source checkout for development; source edits reach the installed App only after rebuilding and installing. For daily use/final acceptance, launch Gewu Insight from the Start menu; the source launcher remains a development tool. This supersedes the earlier source-only/package-only workflow.
- Windows fix requests include backup, package installation/update and installed-version/data verification; do not ask separately for routine local installation unless the current request explicitly excludes it or installation is blocked. First validate on an isolated test Library/copy; preserve and verify the original Library before switching daily use. Development and installed processes must not concurrently use the same Library. A rules-only request does not trigger installation. Commit/push still require an explicit user request.
- Keep local upgrades efficient: reuse existing installation/backup scripts and validated artifacts when unchanged. Keep a verified recovery backup and check the installed version, startup and data integrity; repeat or broaden checks only for changed behavior, failures or unresolved concerns. Batch independent checks instead of adding many separate tool rounds.
- Windows packaging is intentionally unsigned. Release filenames use `Gewu-Insight-Windows-VERSION-x64-Setup.exe`; installer titles, program directory, shortcuts and notice use Gewu Insight without Trial/Unsigned branding. Do not reintroduce publisher-signing requirements or change Windows security settings. Reuse installed WebView2, otherwise install online with the verified official Evergreen Bootstrapper. Keep manifest/version/dependency checks and isolated startup validation.
- **Release gate: create/edit a GitHub Release (including drafts), upload/replace release assets or publish a release only when the user explicitly requests that release action.** Fix/build/test/install requests and successful validation do not authorize release operations; prior publication requests are not standing authorization for future versions. When explicitly requested, publish the exact verified bytes, increment the version and preserve previous releases. Include source, requested guide changes and packaging scripts in the tagged commit after authorized commit/push; disclose exceptions. For requested guide alignment, reuse the shared manual with Windows adapters and verify bundled HTML/PDF against installed-app behavior.
- Keep program, source and **Gewu Database** separate. Fresh program default `%LOCALAPPDATA%\Programs\Gewu Insight`; database default `%USERPROFILE%\Gewu Database`, chosen independently. Current real database is `C:\Users\Zhengran\Desktop\Gewu Database`; SQLite owns identity/state, `%USERPROFILE%\.gewu-insight\database-location.ini` only locates it. Browser profiles/logs/cache live under `%LOCALAPPDATA%\Gewu Insight\Databases\<identity>`. Uninstall retains data, locator and browser sign-ins. Do not migrate real data for cosmetic changes.
- Notify the user promptly once installation and essential verification succeed, before lengthy documentation cleanup. Keep the handoff concise; when explaining elapsed time, distinguish actual installer time from preparation, backup, verification and documentation time.

## Commit Messages

- Every future commit must include a specific English subject, a blank line, and a readable English body describing purpose, concrete changes, relevant behavior/data boundaries, and actual validation. Never claim unrun tests passed.
- Follow `docs/COMMIT_GUIDELINES.md` and inspect every outgoing commit message before pushing. Leave existing history and hashes unchanged; do not rewrite or force-push history to add descriptions.
- Commit or push only when explicitly requested. Stage related files by name, never with `git add -A`, and preserve existing user changes.

## Commands

- Setup: `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt`
- Run UI: `python3 -m paper_monitor ui --port 8765`
- Run journal monitor: `python3 -m paper_monitor journal`
- Run explicit journal window: `python3 -m paper_monitor journal --from-date YYYY-MM-DD --until-date YYYY-MM-DD`
- Download paper: `python3 -m paper_monitor download PAPER_ID`
- Compile check: `python3 -m py_compile paper_monitor/*.py paper_monitor/sources/*.py`
- Windows launcher: installed **Gewu Insight** from the Start menu; `Start Gewu Insight.cmd` opens that installed shortcut. Source-only diagnostics must use isolated data.
- macOS clickable launcher: `Gewu Insight.app`.

## Key Paths

- `paper_monitor/`: main Python package.
- `paper_monitor/ui_server.py`: local web UI and UI API.
- `config/journals.json`: monitored journals and section policies.
- `data/paper_monitor.sqlite`: SQLite database.
- `reports/daily/`: generated Markdown reports.
- `reports/analyses/`: generated analysis notes.
- `README.md`: user-facing usage documentation.

## Done Criteria

- User Guide screenshots must come from the real original App, without Codex/Computer Use overlays. Use Hong Ding for Author Monitor, Nature with visible figures for Journal Monitor, and already-classified multiple Paper Files for Library.
- In the PDF, Product Identity chapters 4-1 through 4-4 flow continuously; do not force each onto a new page. Preserve numbering/links and encode this rule in the builder, not only generated TeX.
- Relevant CLI or UI workflow still works for the changed area.
- Run `py_compile` for Python code changes when practical.
- Keep `AGENTS.md` concise and `PROJECT_STATE.md` under 100 lines when updating project context.
