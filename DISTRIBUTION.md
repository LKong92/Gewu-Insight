# Distributing Gewu Insight

Gewu Insight 1.0.0 is available as separate macOS and Windows installers.
Both include Python and application dependencies. Source archives and the
legacy folder-based packaging script are development paths, not the current
end-user installers.

The repository and GitHub Releases are public; no repository invitation is
required to download the installers. Contact
[info@gewu-insight.com](mailto:info@gewu-insight.com) for installation help.
Do not change repository visibility as part of a build or update.

## Recipient requirements

| Platform | Requirements | Package and instructions |
| --- | --- | --- |
| macOS | macOS 14 or later; Apple silicon or Intel | [macOS 1.0.0 DMG](https://github.com/LKong92/Gewu-Insight/releases/tag/macos-1.0.0) |
| Windows | Windows 10 version 1607+ or Windows 11; Intel/AMD x64 | [Windows 1.0.0 Setup](https://github.com/LKong92/Gewu-Insight/releases/tag/windows-1.0.0) |

On macOS, open the DMG, drag Gewu Insight.app to Applications, eject the image,
and open the installed App. On Windows, run Setup and choose the program and
Gewu Database folders; Python and .NET are included. Setup reuses Microsoft
WebView2 or installs it from Microsoft when needed, which requires internet.
Online literature services also require network access. Optional LibreOffice
and TeX tools are installed separately.

Use the release's checksum, build information, first-launch notes and bundled
User Guide. The macOS package has an ad-hoc integrity signature and is not
Developer ID signed or notarized. The Windows installer is unsigned. Do not
represent either package as having publisher identity verification it lacks.

## Database, updates and troubleshooting

The installed program and selected Gewu Database are separate. Keep the database
outside the App/program folder. On macOS, choose Create New Database or Open
Existing Database at first launch; Database Location… in the App menu shows the
active folder. On Windows, use Setup's Use existing Gewu Database option to
retain a collection.

Before replacing the program, quit the App and its service, then back up the
complete selected database folder, all additional managed roots and externally
linked originals. Copying the App or source checkout alone is not a research
backup. A migration's SQLite snapshot does not replace a full file backup.
For old source-folder installations, follow the
[migration instructions](docs/SOURCE_DATA_MIGRATION.md).

Installed macOS logs are in `~/Library/Logs/Gewu Insight`. For Windows, follow
the release's bundled User Guide and diagnostics. Do not delete a database to
repair startup. Missing disks, incompatible databases and occupied ports need
to be resolved without silently substituting an empty research collection.

## Research license and commercial rights

Gewu is source-available research software under the custom
[Academic and Non-Commercial Research License](LICENSE). Original and modified
versions, derivative works and patches may be shared free of charge for permitted
research under the same terms, retaining notices and identifying modifications.
Commercial use and redistribution require separate prior written authorization.
See [licensing explained](docs/LICENSING.md) and [contributing](CONTRIBUTING.md).

Keep LICENSE, CONTRIBUTING.md, THIRD_PARTY_NOTICES.md and all applicable component
licenses with distributions. Bundled interpreters, dependencies and platform
runtimes retain their own terms. Review the exact package's versions and notices;
the earlier source-install audit is not a complete audit of a standalone package.
Outstanding artwork/font permissions are recorded in the
[dependency and asset audit](docs/DEPENDENCY_LICENSE_AUDIT.md). The Gewu license
does not supply those permissions.

The [current installer inventory](docs/RELEASE_COMPONENT_AUDIT.md) records the
components and notices actually found in both published packages. Their top-level
third-party notices predate the standalone documentation update; Windows also
lacks CONTRIBUTING.md. Repository edits do not repair those downloaded packages.
The inventory lists the corrections and validation required for a new package;
existing release assets remain unchanged.

## Build paths

- **Standalone macOS DMG:** use `scripts/package_macos_dmg.py` with a selected
  source revision and verified runtime/dependency inputs. See
  [macOS packaging](docs/MACOS_DMG_PREVIEW.md) for commands, input licenses,
  checksums, isolated validation and output boundaries.
- **Windows Setup:** use the existing Windows branch's build instructions and
  the Windows release's build/validation manifests. The macOS builder does not
  produce or validate the Windows installer.
- **Native source development:** `scripts/build_macos_app.sh` builds the native
  shell. Without a root source App it extracts `assets/macos-app-template.zip`
  temporarily and defaults to `dist/Gewu Insight.app`. This is not a standalone
  runtime package or an automatic update of `/Applications/Gewu Insight.app`.
- **Legacy collaborator ZIP:** `scripts/make_release.sh` expects an already
  built, signed `Gewu Insight.app` at the repository root. It copies source and
  supporting files into a folder ZIP and creates empty data/reports directories.
  It does not build either current installer. Do not run it on a clean checkout
  expecting a standalone package or use its empty folders as formal data.

## macOS signing and updates

Local builds explicitly use ad-hoc signing without an Apple certificate,
Team ID or keychain password. Builders stage changes, verify signatures and the
Gewu bundle identifier, and protect against concurrent replacement. Build while
the target App is stopped; retain the same bundle identifier and Browser store
identity across updates. A changed bundle can have a new code hash, so ad-hoc
signing does not guarantee prompt-free first launch or updates.

The Browser and hidden publisher views refuse persistent WebCrypto-key wrapping
and unwrapping. Ordinary cryptography, cookies and website storage remain
available; earlier persisted CryptoKeys cannot be read through these views.
This is separate from Apple Passwords and AutoFill. Do not reset Keychain,
export/delete its key or grant all applications access as an update repair.

For source-linked development, Python-only changes can load after a service
restart. An installed standalone App uses its packaged code; pulling source
and restarting that installed App does not update its runtime. Rebuild and
replace a standalone package through its packaging workflow when required.

## Release checks

Before sharing a new build:

1. Record the source commit, version/build, packaging changes and exact runtime
   inputs. `paper_monitor/__init__.py` supplies the macOS source version/build;
   consult the Windows branch for its packaging revision. Keep Guide labels
   consistent with the build being distributed.
2. Retain third-party notices, source obligations and provenance for the exact
   shipped components, including transitive runtime libraries. Resolve or
   explicitly review outstanding asset permissions for the intended delivery.
3. Verify the actual archive/image checksum, signatures where applicable, and
   installed files. Test first launch, restart and representative workflows with
   isolated data. Record what was exercised and what remains unverified.
4. Exclude real databases, papers, credentials, logs, local development archives
   and benchmark artifacts. Preserve research data during program replacement.
5. Obtain explicit authorization before committing, pushing or publishing.
   Preserve the repository's current visibility and existing Git history.

Retain product source, tests, required build assets and useful documentation in
Git. Store unused design drafts and machine-specific work logs in the ignored
local development archive. A cleanup commit does not erase earlier Git history.
