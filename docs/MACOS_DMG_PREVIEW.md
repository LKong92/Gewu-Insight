# Standalone macOS DMG packaging

This packaging path creates a standalone DMG for distribution and testing.
It leaves the working checkout, installed development App and research data alone.
It does not publish a GitHub Release or use an Apple account, Developer ID, or
notarization. Local ad-hoc code signatures protect bundle integrity only.

## Recipient installation

Requires macOS 14 or later, on Apple Silicon or Intel. Open the DMG, drag
`Gewu Insight.app` to Applications, eject the DMG, then open the copied App.
Python and the required dependencies are included; no Python installation,
Terminal commands, or first-launch dependency download is required.

An unidentified-developer warning is expected on some Macs. After checking the
source, use the system's per-app **Privacy & Security > Open Anyway** option if
available. Do not disable Gatekeeper. A malware or damaged-app warning should be
investigated rather than treated as an ordinary unidentified-developer warning.

On first launch choose **Create New Database** or **Open Existing Database**.
The selected `Gewu Database` directory contains `data/`, `reports/`, `config/`
and `backups/`. Paper Files (including AI analyses) remain managed inside the
existing data layout. The locator at
`~/Library/Application Support/Gewu Insight/database-location.plist` stores the
selected directory and SQLite identity; it contains no paper metadata.

Replacing or moving the App preserves the selected database. A missing disk,
wrong database identity, newer schema, busy database, or occupied service port
stops startup instead of silently opening a different service or creating an
empty replacement. Database upgrades receive an SQLite backup before migration.
The App menu's **Database Location…** shows the active location.

Version 1.1.0 adds **Check for Updates** in that menu. See
[Mac software updates](MACOS_UPDATES.md) for the signed Mac feed, installation
safety and the commit/push/build/publish sequence. Sparkle is fetched from its
pinned official archive during the native build; `config/macos-updates.json`
records its hash and public update key. Signing the release feed requires the
maintainer's dedicated Keychain signing identity; ordinary builds do not.


Logs are in `~/Library/Logs/Gewu Insight`. Rebuildable caches are in
`~/Library/Caches/com.zhengranwu.gewuinsight`; macOS/WebKit continues to manage
browser website storage separately. Bookmarks, history and AI connection grants
remain in the research SQLite database. Optional LibreOffice and TeX tools are
not bundled. Use the installed package's Guide, release notes and DMG Read Me
for its setup instructions; older preview manuals may describe source-folder
installation. Current release links are in [DISTRIBUTION.md](../DISTRIBUTION.md).

Existing database moves must use a verified migration, not a Finder move of
SQLite alone. With all source App/server processes stopped, run
`python -m paper_monitor.database_migration OLD_WORKSPACE NEW_WORKSPACE` from the
source checkout. It copies into a new destination, updates managed pointers and
Finder aliases, verifies file bytes and all table rows, and leaves the source
untouched. The JSON report in the new `backups/` directory is an audit export.
Select the verified destination in the App only after reviewing that report.
External linked originals and preexisting missing targets remain external or
missing; migration does not invent, delete or reclassify research files.

## Build boundaries

`scripts/package_macos_dmg.py` archives an explicit Git commit and applies narrow
packaging adaptations only to that staging copy for isolated Python
child-process/MCP startup. Writable paths use shared source configuration. Runtime
assets and code stay inside the App. Source-folder product behavior is unchanged.

Build with Python 3.12 and the macOS command-line development tools:

```text
python3.12 scripts/package_macos_dmg.py --ref COMMIT \
  --inputs /absolute/path/to/verified-inputs \
  --work /absolute/path/to/new-build-directory \
  --output /absolute/path/to/Gewu-Insight.dmg
```

The input directory contains:

- `python-arm64.tar.gz` and `python-x86_64.tar.gz`: the matching official
  python-build-standalone `install_only_stripped` distributions.
- `runtime-lock.json`: architecture-keyed upstream URLs and verified SHA-256
  digests, including the matching full archives used for licensing metadata.
- `licenses/arm64` and `licenses/x86_64`: matching `PYTHON.json` and component
  license texts extracted from those full archives.
- `deps`: only the required pure-Python packages, installed from PyPI with
  `--only-binary=:all: --platform any --python-version 3.12 --implementation py
  --abi none --no-compile --target ...`, retaining distribution metadata/licenses.

The original preview used GitHub `main` commit `36832f1`, CPython 3.12.15 from Astral's
20261003 release, and the exact dependency versions in the companion build JSON.
The manifest also records packaging-script hashes and adapted source filenames.
Third-party licenses remain separate from Gewu's research-use license; existing
brand/Guide asset licensing limitations in `DEPENDENCY_LICENSE_AUDIT.md` remain.

The builder rejects existing work/output paths and verifies the runtime archive
hashes, nested Mach-O signatures and DMG checksum. It copies only the archived
software and clean runtime inputs, never the developer's local database, paper
files, generated notes, browser profile, virtual environment or tokens. The DMG
has a SHA-256 companion and a build JSON. It needs access to macOS disk services
to create the image; a restricted shell may need explicit tool approval.

Before sharing, mount the actual image read-only, verify its App, copy to a new
location, and exercise first launch, restart, PDF subprocesses and settings/data
persistence with an isolated workspace. Confirm the installed App bytes and
strict signature remain unchanged afterward. A local test is not acceptance on
a friend's clean Mac or a guarantee that Gatekeeper will permit first launch.

For a reviewed local build before committing, add `--working-tree`. Only named
product paths are overlaid, and their SHA-256 values are recorded in the build
manifest. It never copies the working database. Once the old source App has been
archived, `assets/macos-app-template.zip` supplies its signed build seed without
leaving a second launchable App in the repository. Build output belongs in
`dist/` or a temporary directory; install the validated standalone App into
`/Applications/Gewu Insight.app`.
