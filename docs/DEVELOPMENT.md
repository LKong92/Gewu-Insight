# Developing and maintaining Gewu Insight

This guide collects the setup, architecture, maintenance, and command-line
material linked from the [README](../README.md). For normal App use, start with
the [User Guide](../paper_monitor/Gewu_Insight_User_Guide.pdf).

These instructions do not expand the custom [research license](../LICENSE).
Before contributing code, read [CONTRIBUTING.md](../CONTRIBUTING.md); research
sharing permission and acceptance into a release with commercial licensing
rights are separate questions.

## Manual setup

Run these commands from the complete repository folder:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python3 -m paper_monitor ui --port 8765
```

This starts the browser-hosted UI. Open `http://127.0.0.1:8765`; the service
health endpoint is `http://127.0.0.1:8765/api/health`. The native macOS App adds
platform integration beyond the browser-hosted interface. Avoid starting a
second service while the App's service is already running on the same port.

For the supplied native launcher, macOS 14 or later and a working `python3`
command are required. Keep the App and project files together in a regular
local folder; the App is not a standalone installer. Initial setup needs network
access to install dependencies. See [distribution and startup troubleshooting](../DISTRIBUTION.md).

## Architecture and state

```text
External research sources
  journals · arXiv · metadata services · scholarly profiles
                         │
                         ▼
              Local application service
        identity resolution · scheduling · validation
                    │                 │
                    ▼                 ▼
            SQLite state core   Visible research files
        identity · relations     PDFs · versions · notes
        resources · provenance   supplements · data · code
                    │                 │
                    └────────┬────────┘
                             ▼
                  Research workspace
      Library & Spaces · My Publications · Monitors · Browser
                             │
                             ▼
                  Optional authorized API/MCP
```

SQLite is authoritative for identities, identifiers, relationships, folder
placements, resource roles, provenance, preferences, and operational state.
JSON, Markdown, HTML, Word, LaTeX, and PDF reports are exports or reading
artifacts, not a second database. Browser bookmarks and history use SQLite;
cookies and cache use the native Browser's separate persistent WebKit profile.

One paper identity can have multiple placements and multiple files. File roles,
manual Default selection, and source evidence must survive refreshes and moves.
Exact SHA-256 detects byte-identical resources; content fingerprints can relate
clean and annotated copies without discarding their differences. PDF validation
rejects HTML responses, empty files, and truncated pseudo-PDFs. Coordinated
filesystem/database changes use rollback or recovery paths.

Reuse existing modules and contracts when working on these areas:

- [Managed file layout](MANAGED_FILE_LAYOUT.md): canonical files, Associated
  Files, Finder aliases, operation journals, and recovery.
- [AI Access](AI_ACCESS.md): shared API/MCP authorization, metadata-first imports,
  append-only analyses, and explicit organization permissions.
- [Browser capture](BROWSER_CAPTURE.md): reviewable identity, file classification,
  and import boundaries.
- [Website link routing](WORKSPACE_BROWSER_LINKS.md): native Browser and
  browser-hosted UI behavior.

## Data layout

The default project layout is:

```text
data/paper_monitor.sqlite       authoritative SQLite database
data/Library/                   visible main Library and current files
data/Spaces/                    independent Space roots
data/My Publications/           managed files for personal publications
data/Associated Files/          versions, supplements, and attachments
data/cache/journal_logos/       rebuildable local logo cache
reports/                        generated notes and reports
logs/                           launcher and runtime diagnostics
config/journals.json            initial/default journal source definitions
```

Configured data roots can differ. Journal subscriptions are personal database
state: `config/journals.json` supplies initial/default definitions, so replacing
source code does not reset active subscriptions or re-enable disabled journals.
Move and classify managed files through the App; manual filesystem changes can
leave saved paths inconsistent with physical locations.

## Safe updates and backups

Before a major update or migration:

1. Quit Gewu Insight and make sure its local service has stopped.
2. Inspect `git status --short`; preserve uncommitted product changes.
3. Back up the complete project, plus any configured managed roots outside it.
   Include SQLite and all managed files, not just `data/Library`.
4. Pull or install the new version and rebuild the native App as needed.
5. Start the App once so required additive database migrations can run.
6. Verify a current PDF, an older version, an attachment, a Space,
   My Publications, and a monitor before discarding the backup.

Copying only SQLite or only visible files is not a complete workspace migration.
Do not delete the database as a startup repair. Start with
`logs/paper_monitor_launcher.log` and the diagnostic instructions in
[DISTRIBUTION.md](../DISTRIBUTION.md#recipient-requirements).

## CLI commands

Use the project environment and run from the repository root:

```bash
. .venv/bin/activate

# Journal Monitor default publication window
python3 -m paper_monitor journal

# An explicit publication window; replace the date placeholders
python3 -m paper_monitor journal --from-date YYYY-MM-DD --until-date YYYY-MM-DD

# Download one existing paper; replace PAPER_ID with its internal record ID
python3 -m paper_monitor download PAPER_ID

# Export diagnostic JSON without replacing SQLite
python3 -m paper_monitor export-json reports/export.json
```

These commands operate on the configured workspace; they are not test fixtures.

## Network services and credentials

Source availability depends on network access, provider limits, and access
policies. Keep pacing and cooldowns intact. Never put real keys in source code,
tests, commits, screenshots, logs, or issue reports.

OpenAlex, Semantic Scholar, and NASA ADS keys can be configured in
**Setting → Literature Data Source**. arXiv discovery coverage is configured separately in
**Setting → arXiv Scope Settings**.

Optional polite API identity values can be supplied through the environment:

```bash
export OPENALEX_MAILTO=your.name@example.edu
export CROSSREF_MAILTO=your.name@example.edu
```

## Builds and verification

Read [AGENTS.md](../AGENTS.md) before making product changes. Keep benchmark-only
instrumentation, data, and artifacts in a separate local benchmark worktree;
never push them to this repository.

Rebuild the native App after changing its native UI, bundled resources, or
identity:

```bash
./scripts/build_macos_app.sh
```

Local builds explicitly use ad-hoc signing (`codesign --sign -`) without an
Apple certificate, Team ID, signing configuration or keychain password.
Quit the installed App before rebuilding it. The builder stages compilation,
resource updates and signing, verifies the signatures and Gewu bundle identifier,
then installs with rollback if final verification fails. A concurrent bundle
change or a newly running App cancels installation. If the complete staged App
is identical to the installed App, the builder retains the existing bundle and
signature. No database, research file, WebKit profile or existing keychain item
is changed by the builder.

Python/backend-only changes do not require rebuilding the native bundle; restart
the App to load that source update. A changed native bundle can have a new
`cdhash`; ad-hoc signing alone does not eliminate macOS authorization prompts.
Current Browser and hidden publisher views separately refuse persistent
WebCrypto-key operations before Keychain access. Ordinary cryptography and site
storage remain enabled; old persisted CryptoKeys are unreadable through these
views. Keep this compatibility boundary distinct from saved passwords, signing
and the trusted workspace. See
[macOS signing and updates](../DISTRIBUTION.md#macos-signing-and-updates).

For an isolated native QA build:

```bash
./scripts/build_macos_app.sh --output /private/tmp/Gewu-QA.app
```

Choose a fresh output path. The legacy `--development-adhoc` option remains
supported and additionally rejects replacing the installed App. Do not launch
a QA copy against real accounts or authorize it to the production WebCrypto key.

When the HTML User Guide changes, regenerate the PDF before building the App:

```bash
.venv/bin/python scripts/build_user_guide_pdf.py
./scripts/build_macos_app.sh
```

Inspect the affected PDF pages and verify the resulting App signature. Screenshot
rules and source provenance are recorded in
[USER_GUIDE_SCREENSHOTS.md](USER_GUIDE_SCREENSHOTS.md).

Choose verification appropriate to the change. Typical checks from the project
root are:

```bash
.venv/bin/python -X pycache_prefix=/private/tmp/gewu-pycache \
  -m py_compile paper_monitor/*.py paper_monitor/sources/*.py

.venv/bin/python -X pycache_prefix=/private/tmp/gewu-pycache \
  -m unittest discover -s tests -v

git diff --check
```

Use temporary, isolated databases and files for tests. Do not modify or rebuild
a user's production database for verification. Native UI, AppKit, and local
server checks may require the corresponding macOS session and permissions.
Record what was actually exercised; a source-level assertion does not establish
that a real mouse gesture or publisher sign-in works.

## Packaging and contributions

Create a clean folder-based collaborator package with:

```bash
scripts/make_release.sh
```

The release workflow excludes local databases, managed research files, generated
notes, credentials, logs, and virtual environments. Follow
[DISTRIBUTION.md](../DISTRIBUTION.md) for versioning and packaging requirements,
and retain the license and third-party notices. Review the
[dependency and asset audit](DEPENDENCY_LICENSE_AUDIT.md) before distribution.

For external contributions, follow [CONTRIBUTING.md](../CONTRIBUTING.md).
For commits, follow [COMMIT_GUIDELINES.md](COMMIT_GUIDELINES.md); do not claim
unrun tests or rewrite existing history to change commit descriptions.
