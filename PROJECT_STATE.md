# PROJECT_STATE.md — Windows current handoff

Updated: October 28, 2026. Keep this file under 100 lines and focused on current state.

## Branch and delivery

- Develop Windows on `Windows`; macOS stays on `main`. Commit/push only when explicitly requested. The repository is public by explicit user authorization; preserve that visibility and never publish benchmark work.
- Current public Windows release: `windows-1.1.0`, version 1.1.0 / Build 11001, matching the Mac version as explicitly required by the user. Tag and installer source are `190a9689b92e4594ede10042bedc1c45b9324a52` on `Windows`; native version is `1.1.0+190a9689b92e4594ede10042bedc1c45b9324a52`. macOS `main` is unchanged.
- Installer: 93,365,506 bytes, SHA-256 `3d8a271de45e1d8d872313d270653e4cbac8666185895722c8d8cad19167fdae`. Five public attachments (Setup, checksum, build/validation JSON, PDF) were independently downloaded and exactly matched. Previous `windows-1.0.0` remains available.
- Windows guide: 113 pages, SHA-256 `83bc75fa686c8aa38115693b43f64ce078ba2b7b48150e7886aec46871b4e31d`, 411 resolving internal links. Actual Windows update, connected-import and empty-preview screenshots are in `assets/user-guide/windows/`. Shared Mac captures are never represented as Windows screenshots. HTML/PDF edition and changed-page visual checks passed.

## Current delivery and remaining cleanup

- The user authorized Mac-to-Windows feature migration, VM operation, guide updates, commit/push and release. Feature commit `190a968` is pushed. This post-publication change promotes only Windows release metadata/docs and does not change the verified binaries. Check the public raw Windows feed after pushing it.
- Features: Zotero companion 0.4.2; one authenticated background service; confirmed Open in Zotero handoff; copied-library import preserving hierarchy/empty directories; scoped manual DOI conflict review; Paper Files/website and folder-rename fixes; verified Windows-only updater. Windows Zotero `-url`, UTF-8 packaging and file receipt/handle fixes are included. Mac remains at its separately published 1.1.0 with its own plugin version.
- Host and guest regression suites passed for the affected shared workflows. Win11 native preview passed 18 cases, browser capture 3, import 35 and Windows copy-safety 5. Installed update/public-download exercise passed 24 checks including prepare/cancel/write barrier/authentication/clean stop and unchanged original data. Final installed package verified 2,198 files, normal Setup, automatic `--after-install` startup, source revision and test Paper Files/locator preservation.
- User-driven Zotero handoff/menu/PDF preview and connected/empty import preview passed with Zotero 10.0.6 in Parallels Win11 ARM/x64 emulation. The real Zotero library is empty; that UI check is not a populated-library import test. Windows 10 and physical hardware were not freshly tested. Update lookup/download/service stop and normal Setup/restart were validated separately, not as a full GUI upgrade through a later public version.
- Installed App: `%LOCALAPPDATA%/Programs/Gewu Insight`. Parallels Standard has no guest-exec; CUA can observe but guest clicks still fail with noWindowsAvailable. Shared host folder `~/Downloads/Gewu-Windows-Test` is guest `Z:/Downloads/Gewu-Windows-Test`; no sharing/security settings were changed. User launches the prepared scripts in PowerShell.
- Original selected Windows database: `C:/Users/lingyuan/Downloads/dd`, identity `6a0975aa-d92c-4f22-b594-bc48f21ba7b0`, 235 papers/0 resources/4 folders/0 placements. Original 15 files and recovery backup were unchanged through final installation. Recovery is under `%LOCALAPPDATA%/GewuBuild/Parity110/recovery`; retain it.
- Pending user action: run `restore-original-1.1.0.cmd` after closing the Zotero Gewu tab and standalone App. It restores the original locator, starts the installed Start-menu App, verifies the original identity/records, then observes the user's Plugin > Zotero Integration > Open in Zotero so both interfaces return to the original workspace. Do not leave the user unknowingly on the test Library.
- Until that script succeeds, selected test database remains `%LOCALAPPDATA%/GewuBuild/Parity110/source-candidate-a/tmp/installed-acceptance-a`, identity `974160ef-2989-4bf0-9e5b-f5b9e16caf9d`. No test data is deleted. Read `restore-original-1.1.0-result.json` from the shared folder for completion.
- Exact committed source/build scripts and private acceptance evidence live in main-checkout ignored `tmp/windows-parity/final-1.1.0/`. Published artifacts have sanitized provenance/validation JSON, never credentials, real database records or machine logs. Full earlier handoff is retained there, not expanded in this file.
- The Mac main checkout's user-owned `metadata/` directory is unrelated and excluded. The Mac Ed25519 signing key remains only in its Keychain and was not exported/shared; Windows packaging is intentionally unsigned.

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
