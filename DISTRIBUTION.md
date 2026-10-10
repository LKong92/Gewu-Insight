# Distributing Gewu Insight for Windows

The Windows product is **1.0.0, Build 1**, delivered as a self-contained
`Gewu-Insight-Windows-VERSION-x64-Setup.exe`. The source checkout is for
development. Normal use starts the installed **Gewu Insight** from the Start menu.

## Downloads and requirements

- [Windows 1.0.0 Setup](https://github.com/LKong92/Gewu-Insight/releases/tag/windows-1.0.0):
  Windows 10 version 1607 (build 14393)+ or Windows 11, Intel/AMD x64.
  Python, .NET and application dependencies are included. Setup reuses WebView2
  or installs it using Microsoft's Evergreen bootstrapper; that step needs network access.
- [macOS 1.0.0](https://github.com/LKong92/Gewu-Insight/releases/tag/macos-1.0.0):
  a separate DMG maintained on `main`, for macOS 14+ on Apple silicon and Intel.

GitHub access is required while the repository is private. The Windows installer
is intentionally unsigned. It does not change Windows security settings. The
x64 package does not support 32-bit Windows or Windows 10 ARM.

## Program, database and source

Setup selects program and database folders independently. Defaults are
`%LOCALAPPDATA%\Programs\Gewu Insight` and `%USERPROFILE%\Gewu Database`.
Use **Use existing Gewu Database** to keep an existing collection.
`%USERPROFILE%\.gewu-insight\database-location.ini` locates the selected
database; SQLite in that database owns its identity and state.

Browser profiles, logs and cache are under
`%LOCALAPPDATA%\Gewu Insight\Databases\<identity>`. Uninstall retains the
database, locator and browser sign-ins. Never repair startup by deleting data.
Back up the complete stopped database and linked originals before an upgrade;
see [development and backups](docs/DEVELOPMENT.md#safe-updates-and-backups).

## Release source and verification

The October 10 Windows asset and the current `windows-1.0.0` tag both reference
source commit `725ae8f`. A separately authorized release correction aligned the
tag and build metadata; the installer bytes stayed unchanged. Read the release's
build JSON when reproducing a package. The native informational version may
retain its earlier build revision, as that record explains. Exact metadata and
the scope of past package inspection are in [the component audit](docs/RELEASE_COMPONENT_AUDIT.md).

Source changes do not replace installed binaries or published assets.
Build a fresh payload and versioned installer, test with an isolated collection,
then install locally and verify the installed version, startup, database identity
and retained data. See [builds and verification](docs/DEVELOPMENT.md#builds-and-verification).
The Windows 10 minimum is a declared target; the latest recorded native run was
on Windows 11. This repository cleanup does not add Windows 10 acceptance evidence.

## Package contents and notices

`scripts/build_windows.ps1` packages the native shell, CPython service, locked
Python dependencies, .NET runtime, WebView2 SDK notices, assets and the existing
Windows HTML/PDF manual. The service's PDF route and native Help use the same
Windows PDF. Preserve its approved layout and compatibility filenames.

New builds also include LICENSE, CONTRIBUTING.md, THIRD_PARTY_NOTICES.md and
the linked licensing/component audit pages. Nested runtime and wheel licenses
remain required. Historical macOS build templates and generated TeX are excluded
from the Windows service payload. Packaging does not copy local research data,
development archives, credentials or browser profiles.

This source change does not retrofit those documents into an existing installer.
Inspect every notice copy, payload manifest and actual installer before a future
release. Static checks do not replace installed-app acceptance.

## Research license and publication

The [LICENSE](LICENSE) permits academic/non-commercial research use and sharing
of original and modified versions under its conditions. Commercial use requires
separate written authorization. Third-party terms and unresolved provenance
questions remain separate; see [licensing](docs/LICENSING.md) and
[dependency evidence](docs/DEPENDENCY_LICENSE_AUDIT.md).

Keep this repository private. Commit, push, tag or release publication requires
an explicit user request. Publish only verified bytes, disclose source/version
exceptions, and preserve existing history and releases. Windows work remains on
`Windows`; macOS work remains on `main`.
