# Distributing Gewu Insight

The current research and writing baseline is **Gewu Insight 1.0.0, Build 1**.
This project uses macOS folder-based distribution. Keep the App, Python package,
configuration and assets together; the App alone is not a standalone installer.

## Research license and commercial rights

Gewu Insight is source-available research software under the custom
[Academic and Non-Commercial Research License](LICENSE). Academic/non-commercial
research users may download, install, run and privately modify it. They may share
only unmodified official versions free of charge for those purposes under the
same terms, retaining LICENSE, copyright and third-party notices. Public sharing
of modified versions or patches requires separate prior written authorization.
Commercial use, commercial redistribution, sublicensing and incorporation into
commercial products or services require separate prior written authorization
from the copyright holders. See [licensing explained](docs/LICENSING.md).

Third-party rights are separate. Before public or commercial distribution,
review [the dependency and asset audit](docs/DEPENDENCY_LICENSE_AUDIT.md), especially
the outstanding artwork/font permissions. The Gewu license does not clear those
rights. Do not add a virtual environment, third-party binaries or fonts to a
release without auditing that exact distribution and retaining required notices.

## Version and build

`paper_monitor/__init__.py` owns `__version__` and `__build__`. The App builder
reads them for About and the bundle; the PDF builder reads the same source.
The icon checksum only selects a cache-safe icon filename. It is not the build
number. For a future patch, update the version and reset Build to 1; increase
Build when packaging a revised build of that same version.

Regenerate the manual before packaging:

```bash
.venv/bin/python scripts/build_user_guide_pdf.py
scripts/build_macos_app.sh
```

The HTML edition label and About screenshot must also match the intended
release. Verify the generated PDF and App signature before sharing.

## What to Share

Use the release script:

```bash
scripts/make_release.sh 1.0.0
```

It creates a zip under `dist/` containing:

- `Gewu Insight.app`
- source code under `paper_monitor/`
- `config/`
- `requirements.txt`
- `README.md`
- `LICENSE`, `THIRD_PARTY_NOTICES.md` and `docs/` (including licensing and audit notes)
- helper scripts
- empty `data/` and `reports/` directories

It does not include local SQLite databases, downloaded PDFs, generated notes,
logs, virtual environments, or presentation/output artifacts.

## Recipient Requirements

The supplied universal launcher requires macOS 14 or later and a working
`python3` command. The minimum version matches the binary deployment target. On first launch,
`Gewu Insight.app` creates `.venv`, installs `requirements.txt`, starts the
local UI, and opens `http://127.0.0.1:8765`.

If the first launch fails, check:

```text
logs/paper_monitor_launcher.log
```

If the app only flashes and no page opens, run:

```bash
scripts/diagnose_macos.sh
```

The launcher now includes the last few log lines in its failure dialog. Common
causes are missing `python3`, blocked network access during dependency install,
quarantine/permission changes introduced by file sharing, or keeping the folder
inside protected macOS locations such as `Desktop`, `Documents`, or `Downloads`.
For Finder launch, tell recipients to move the whole folder to a regular location
such as `~/Applications/PaperMonitor` or `~/PaperMonitor`.

## GitHub

For GitHub, commit source files, `Gewu Insight.app`, `config/`, scripts,
`README.md`, `DISTRIBUTION.md`, `LICENSE`, `THIRD_PARTY_NOTICES.md` and `docs/`.
Keep local data out of git using `.gitignore`.

Describe Gewu as **source-available research software**; use **publicly available
source code** only once the repository is public. Do not advertise it as
open-source software or apply a standard-license badge to this custom license.
Repository visibility and the arXiv/public-release timing are separate decisions.
