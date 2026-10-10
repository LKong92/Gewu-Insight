# PROJECT_STATE.md — Windows current handoff

Updated: October 10, 2026. Keep this file under 100 lines and focused on current state.

## Branch and delivery

- Develop Windows on `Windows`; macOS stays on `main`. Commit/push only when explicitly requested. Keep the GitHub repository private and never publish benchmark work.
- Current private Windows release: `windows-1.0.0`, version 1.0.0 / Build 1. Current installer source and the remotely aligned release tag both point to `725ae8f`. The source/build metadata agree after the separately authorized tag correction recorded by upstream `dc2f84f`; this cleanup does not alter tags.
- Current installer SHA-256: `b9056eab0ec6a0af40ae7608a24437d82cfd3508ecb300c8d43047286cf3445e`, 86,255,214 bytes. See `docs/RELEASE_COMPONENT_AUDIT.md` for current metadata and separately scoped historical package evidence.
- Preserve the approved 94-page Windows PDF, SHA-256 `458cd0560a03dcd41ba5e4144f94c79090c1a9840db98b34d7a6389fa7a1eb18`. The prior Windows run records 872 destinations/358 annotations and only section 4.3.2 on page 84 changed. Do not invoke legacy ReportLab reflow; requested HTML adaptation uses `--html-only`.
- Shared seal artwork/provenance matches macOS `eb8714d`; Windows keeps its 4% native watermark opacity. This cleanup changes neither artwork nor runtime UI.
- Prior Windows-host handoff records installed payload/startup/data checks on Windows 11. Windows 10 was not retested. Those results are historical evidence, not fresh validation from this macOS cleanup.

## Source and data separation

- Daily use starts the installed Gewu Insight from the Start menu. The root CMD opens that installed shortcut. Source changes reach the App only after rebuild/install; source diagnostics use isolated data.
- Program default: `%LOCALAPPDATA%\Programs\Gewu Insight`. New database default: `%USERPROFILE%\Gewu Database`, selected independently. Discover the actual selection instead of copying a personal path from history.
- `%USERPROFILE%\.gewu-insight\database-location.ini` locates the database and expected identity; SQLite is authoritative. Profiles/logs/cache are under `%LOCALAPPDATA%\Gewu Insight\Databases\<identity>`.
- Before upgrades or migration, stop the App/service and back up the entire database, additional managed roots and externally linked originals. Preserve recovery material; do not use real research data for development tests.
- Development setup uses `paper_monitor.windows_database prepare` with an explicit isolated workspace, without `--select`; see `docs/DEVELOPMENT.md`. The relocation CLI changes the current locator only after verified copying when explicitly given `--select`; use it only for a planned migration.

## Product and validation contracts

- Preserve paper/resource identities, versions, classifications, manual Default choices, placements and provenance. Coordinate file/SQL changes with rollback or recovery.
- MCP paper access uses authorized client copies; saved analyses append Markdown and never replace existing files. Keep grants scoped and existing permissions unchanged.
- Windows PDFs open in the registered application; native integration uses WebView2 and Windows shortcuts. Apple Passwords/AutoFill, Safari sync and macOS system Quick Look remain excluded.
- Preserve bounded source access, verified publisher/repository downloads, cooldowns and stored status. Subject Monitor rejects Zenodo; calendar counts contain numbers only.
- Runtime fixes follow isolated validation → fresh Setup → local install/update → installed startup/version/data verification. Documentation-only changes do not replace a running App. Publication needs its own explicit user request.

## Repository cleanup

- Cleanup began at `9d61270` and incorporates upstream `dc2f84f` (release tag alignment). Prior handoff, machine-specific logs, generated TeX and old root Mac App were hash-verified into ignored `local-development-archive/repository-cleanup-20261010/`; the manifest records exact paths/hashes. The eight unused logo drafts were deleted as requested, without creating another archive copy; Git history retains the originals.
- Current README, distribution/development, source-diagnostic and database-location instructions replace old 0.1.21 daily-use claims. Historical signing/parity/migration journals are archived; current Windows signing guidance stays concise.
- LICENSE 1.1 is unchanged. CONTRIBUTING and licensing checklist follow the shared policy with Windows-specific development links. Font/About-calligraphy reuse evidence and the external contributor agreement/signature process remain unresolved; AI provenance is not legal clearance.
- Future Windows builds copy CONTRIBUTING and licensing/audit pages with the existing notices. No installer was rebuilt, installed or published for this cleanup; current installer notice contents have not been re-extracted.
- `assets/macos-app-template.zip` retains the old Mac bundle as a build fixture. It and generated TeX are excluded from Windows service packages. Bundle-reading tests temporarily extract the fixture and remove it afterward. Current macOS development belongs on `main`.
- The shared PDF builder regenerates ignored `paper_monitor/user_guide.tex`; tests inspect PDF structure and builder rules instead of requiring tracked TeX. Windows HTML/PDF compatibility filenames and the six-tab guide remain intact.
- Cleanup validation: 40 guide/structure/notice/bundle checks passed; actual service/notice staging passed with synthetic runtime/dependencies; Windows guide edition check, Python compilation and shell syntax passed. Both branches' 353 relative link paths exist. All 41 archive hashes and 28 template entries match; LICENSE, manuals, artwork and runtime source are unchanged. The historical Mac bundle/manual identity check was excluded; Windows native build/install and PowerShell preflight were not run on this macOS host.
- The user authorized committing and pushing this cleanup to GitHub `Windows`, with only release-document corrections on `main`; no installer or Release asset change is part of this request.
