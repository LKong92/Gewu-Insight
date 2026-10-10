# Developing Gewu Insight for Windows

Work on `Windows`; macOS implementation and packaging are maintained on `main`.
Read [AGENTS.md](../AGENTS.md), [CONTRIBUTING.md](../CONTRIBUTING.md) and the
[commit guidelines](COMMIT_GUIDELINES.md). Commit and push only when requested.

Daily use starts the installed App from the Start menu. Source edits reach it
only after building and installing a new package. The repository CMD opens the
installed shortcut; it is not a development launcher.

## Manual setup

Use a Windows development host with Python 3.13, .NET 10 SDK and, for Setup,
Inno Setup. Build dependencies are recorded in `windows/requirements.lock` and
`windows/GewuInsight.Windows.csproj`. From the repository root in PowerShell:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r windows/requirements.lock
$env:GEWU_WORKSPACE_ROOT = Join-Path $PWD 'tmp\development-database'
$env:GEWU_DATA_ROOT = Join-Path $env:GEWU_WORKSPACE_ROOT 'data'
.venv\Scripts\python.exe -m paper_monitor.windows_database prepare --workspace $env:GEWU_WORKSPACE_ROOT --create
```

Initialize a fresh isolated database once. On later sessions, set the same two
environment variables and omit `--create`. Do not add `--select`: development
must not change the installed App's database locator. Use synthetic files.
`paper_monitor.workspace create` belongs to the macOS branch, not this branch.

For optional browser-hosted diagnostics, see [Source Web](WINDOWS_SOURCE_WEB.md).
Native acceptance requires the installed Windows App. Never run development and
installed processes against the same research collection.

## Architecture and state

The Python service manages discovery, metadata, paper identities, files and
SQLite. The Windows Forms shell adds WebView2, native menus, file operations,
browser capture and PDF integration. C# changes require a rebuilt shell.

SQLite is authoritative; JSON and reports are exports. The database folder
contains `data/paper_monitor.sqlite`, Library, Spaces, My Publications,
Associated Files, configuration and reports. AI analyses saved as Paper Files
belong in Associated Files; legacy analysis reports may remain under `reports/`.
Additional managed roots and externally linked originals can live elsewhere.

The locator is `%USERPROFILE%\.gewu-insight\database-location.ini`.
Runtime profiles/logs/cache are separate under
`%LOCALAPPDATA%\Gewu Insight\Databases\<identity>`. Discover the user's
selection; never copy a machine-specific path from an old handoff.

Preserve paper/resource IDs, classifications, manual Default choices and
provenance. File/database operations need rollback or recovery. MCP access uses
explicit grants; analyses append and never overwrite existing Paper Files.
See [file layout](MANAGED_FILE_LAYOUT.md), [AI Access](AI_ACCESS.md) and
[Browser capture](BROWSER_CAPTURE.md) for the shared contracts.

## Safe updates and backups

1. Stop the App, its service and development processes using the database.
2. Preserve source changes separately. Back up the entire selected Gewu Database,
   all additional managed roots and externally linked originals. The source
   checkout is not the research backup.
3. For same-machine recovery of browser sessions, preserve the matching runtime
   profile and locator separately while stopped; do not publish them in source.
4. Validate the new package with an isolated database/copy before local upgrade.
5. Install/update the program using the existing database selection. Verify
   version, startup, database identity, representative files and integrity.
6. Keep recovery material until those checks pass. Do not reopen an older build
   against a newer schema or overwrite later research with an older backup.

Moving a database can require path-aware migration. Follow
[database location guidance](WINDOWS_WORKSPACE_RELOCATION.md). The relocation
CLI updates the current locator only when explicitly run with `--select` after
its copy and verification; routine development setup must omit that option.

## CLI commands

After setting the isolated environment from Manual setup:

```powershell
.venv\Scripts\python.exe -m paper_monitor journal
.venv\Scripts\python.exe -m paper_monitor journal --from-date YYYY-MM-DD --until-date YYYY-MM-DD
.venv\Scripts\python.exe -m paper_monitor download PAPER_ID
```

These commands operate on the selected development database and may contact
online sources. Keep credentials out of source, logs submitted for review and
test fixtures. Provider limits and institutional access still apply.

## Builds and verification

Use the shared version/build from `paper_monitor/__init__.py`. Supply a verified
official x64 CPython embedded runtime and Microsoft's WebView2 bootstrapper.
For example, after replacing the example input paths:

```powershell
& .\scripts\build_windows.ps1 -Version 1.0.0 `
  -PythonRuntime 'C:\BuildInputs\python-embedded' `
  -WebView2Bootstrapper 'C:\BuildInputs\MicrosoftEdgeWebview2Setup.exe' `
  -InnoCompiler 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' `
  -PayloadDirectory (Join-Path $PWD 'dist\review-1.0.0') `
  -InstallerDirectory (Join-Path $PWD 'dist\installers\review-1.0.0')
```

Use fresh output directories; the builder refuses to replace an existing payload
or installer. It retains original dependency notices and verifies manifests.
It builds locally and does not install or publish automatically.

Run existing checks relevant to the changes, including Python compilation,
`tests/test_windows_database.py`, `tests/test_windows_source.py`, notice packaging
tests and `tests/test_windows_release.ps1` when packaging changes. The
[native acceptance probe](../tests/windows_native/README.md) and
[browser parity probe](../tests/windows_browser_parity/README.md) use isolated
fixtures. Windows-only checks require a Windows host; report platform skips.

For runtime fixes, finish with local Setup installation/update, Start-menu
startup and installed-version/data verification. Repository-only documentation
cleanup does not itself rebuild the installer or replace a running App.

## Manual and historical macOS fixtures

`windows/Windows_Preview_Guide.html` and `.pdf` are current compatibility
filenames used by Help and packaging. Preserve the approved 94-page PDF.
`scripts/build_windows_preview_guide.py --version 1.0.0 --check` validates the
edition. `--html-only` is reserved for requested HTML adaptations; the legacy
ReportLab PDF reflow is blocked. Do not rebuild the manual for repository cleanup.

Shared `paper_monitor/user_guide.html` remains an input to the Windows adapter.
The separate shared PDF builder regenerates `paper_monitor/user_guide.tex`;
that TeX is an ignored intermediate. Existing PDF/structure tests inspect the
shipped PDF and builder rules rather than requiring a checked-in TeX file.

`assets/macos-app-template.zip` preserves the historical macOS fixture formerly
stored as a launchable root App. It is not a current macOS distribution and is
excluded from the Windows payload. Legacy macOS build scripts extract it only
when needed. Bundle-reading tests may temporarily extract it at the root and
must remove that extracted copy afterward. Use `main` for current macOS work.

Superseded machine-specific logs and design drafts are archived under ignored
`local-development-archive/`, with hash manifests; tracked originals remain
recoverable from the pre-cleanup Windows revision recorded in PROJECT_STATE.md.
