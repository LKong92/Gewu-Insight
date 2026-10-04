# Distributing Gewu Insight

The current research and writing baseline is **Gewu Insight 1.0.0, Build 1**.
This project uses macOS folder-based distribution. Keep the App, Python package,
configuration and assets together; the App alone is not a standalone installer.

## Research license and commercial rights

Gewu Insight is source-available research software under the custom
[Academic and Non-Commercial Research License](LICENSE). Academic/non-commercial
research users may download, install, run and modify it. They may share original
and modified versions, derivative works and patches free of charge for those
purposes under the same research-use terms, retaining LICENSE, copyright and
third-party notices and identifying modifications. Public research forks and
pull requests within those terms do not require separate permission.
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

## macOS signing and updates

This local workflow uses explicit ad-hoc signing. Building and packaging do not
require an Apple certificate, developer account, Team ID or keychain password.
Strict signature verification and the fixed Gewu bundle identifier remain
required; removing the certificate dependency does not skip these checks. See
the [development guide](docs/DEVELOPMENT.md#builds-and-verification).

Keep the same bundle identifier and Browser data-store identity across updates.
If a changed native bundle triggers a WebCrypto authorization request, authorize
only the current original Gewu App for the existing
`Gewu Insight WebCrypto Master Key`. Preserve that item and the existing Browser
profile. Never reset the login keychain, delete the master key, export its value,
or allow all applications as an update repair. The build/package scripts do not
automatically change keychain permissions.

A changed ad-hoc bundle can have a new code hash and is bound to a code-hash
partition in securityd. A fixed bundle identifier alone does not override that
protection layer. See Apple's
[securityd partition selection](https://github.com/apple-oss-distributions/Security/blob/main/securityd/src/clientid.cpp)
and [application update authorization](https://support.apple.com/guide/keychain-access/kyca1331/mac).

Build while the installed App is stopped. The builder stages all compilation,
resource updates and signing before replacement, rejects concurrent bundle
changes, and restores the original bundle if installation verification fails.
An identical staged bundle leaves the existing App and signature in place.
Python/backend-only source updates do not require a native rebuild; restart to
load them. Changed native builds can still require user reauthorization; ad-hoc
signing does not guarantee prompt-free updates.
The build and package scripts do not change the database, research files,
Browser profile, saved website sessions or keychain ACLs.

Distribute the verified ZIP from `make_release.sh`. It preserves nested code
signature attributes and verifies the App before copying, after copying and
after extracting the actual ZIP. A failed check does not publish the staged ZIP.
Git does not preserve the signature xattrs of the shell launcher; a Git checkout
is a source update; changed native/bundled files must pass this local build and
verification workflow before being used as an installed App. Do not replace a
running App with a Git-pulled bundle. This local workflow does not claim Apple
notarization or Gatekeeper approval on a recipient's Mac.

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
- `LICENSE`, `CONTRIBUTING.md`, `THIRD_PARTY_NOTICES.md` and `docs/`
  (including licensing and audit notes)
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
`README.md`, `DISTRIBUTION.md`, `LICENSE`, `CONTRIBUTING.md`,
`THIRD_PARTY_NOTICES.md` and `docs/`.
Keep local data out of git using `.gitignore`.

Describe Gewu as **source-available research software**; use **publicly available
source code** only once the repository is public. Do not advertise it as
open-source software or apply a standard-license badge to this custom license.
Repository visibility and the arXiv/public-release timing are separate decisions.
