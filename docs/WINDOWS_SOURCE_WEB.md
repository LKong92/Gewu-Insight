# Windows Source Web

This is the optional external-browser mode. The default launcher now opens
[Desktop from Source](WINDOWS_SOURCE_DESKTOP.md), using the 0.1.20 native shell.

Earlier local delivery on 2026-09-29: the real CMD launcher started the existing Library
in Chrome; service/authenticated API, database integrity, protected-row digests
and research-file hashes passed. Computer Use could identify the Chrome window
but stopped before visual inspection because it could not reliably determine its
URL. Full interactive feature acceptance is not claimed.

Source Web runs the Python service directly from this checkout and opens the
authenticated local interface in your default browser. It needs no Gewu installer
or publisher certificate. It does require a working Python environment and its
dependencies; it does not guarantee that every Windows policy allows every
dependency or a downloaded launcher. It never changes Windows security settings.

## Start and stop

At the repository root, run `& '.\Start Gewu Insight.cmd' --web` in PowerShell.
Keep its console open while using Gewu. Press **Ctrl+C** to stop the service;
closing only the browser tab does not stop it. Reopen the launcher to start again.

The launcher uses the existing Preview Library selection in
`%USERPROFILE%\.gewu-insight\preview-workspace.txt`. If no selection exists, it
uses an existing `%USERPROFILE%\Gewu Insight Preview` Library, otherwise creates
`%USERPROFILE%\Gewu Insight Source`. An invalid saved selection stops startup
instead of creating an empty replacement. The data remains outside the checkout.
The desktop App and Source Web cannot open the same workspace concurrently.

First-time setup, in a terminal at the repository root:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Use a supported Python 3 version with Windows wheels for the pinned dependencies.
The local acceptance run used the existing Python 3.13 environment; it did not
test a fresh dependency installation on another machine.

To choose another existing Library or create a separate one:

```powershell
.venv\Scripts\python.exe scripts/windows_source.py --web --workspace "C:\Research\Gewu"
.venv\Scripts\python.exe scripts/windows_source.py --web --workspace "C:\Research\New Gewu" --new-workspace
```

The server binds only to `127.0.0.1`, selects an available port, and uses the
existing one-time browser launch ticket and workspace session. No token needs
to be copied into a shortcut, terminal, or document.

## Update from source

1. Stop Source Web with Ctrl+C and back up the complete workspace, including the
   SQLite database and managed files. Check for local source changes.
2. Update this checkout from the intended Windows branch or reviewed release.
   Do not overwrite local edits, switch to macOS `main`, or replace data folders.
3. Run the dependency-install command again only when requirements change.
4. Run the same launcher with `--web`. Python and web-interface changes now load
   from the updated source. Check the Library after any data migration.

GitHub commits and source ZIP downloads do not update a running process or the
separately installed Preview App. This launcher does not fetch updates itself.

## Functional boundaries

Library, notes, monitoring and other Python/web features use the existing shared
product code. Source Web is not the full Windows desktop application: the native
embedded Browser, its institution-authenticated publisher download bridge,
native shell drag/drop integration and native PDF preview are not supplied by
the external browser. Web-supported alternatives remain subject to their normal
limitations. Updating C# files does not update a desktop shell or give Source Web
those features. In particular, the 0.1.20 native Nature download change is not
delivered in `--web` mode. The default desktop-source mode includes that fix.

The installed Preview 0.1.19 remains separate. To return to it, stop Source Web
and open the original App; do not use an older App if a future source update has
made an incompatible schema migration. No installation or uninstallation is
needed to switch between compatible versions.

## Future GitHub distribution

For source users, distribute this launcher with versioned source and setup
instructions. A ZIP portable desktop build is also possible, but it still
contains native EXE/DLL files and does not fix Smart App Control rejection.
EXE/MSI installers simplify desktop installation; MSIX with App Installer can
provide automatic updates, but direct MSIX distribution introduces signing
requirements. These are separate distribution options, not implemented updaters.

References: [Windows packaging](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/packaging/),
[App Installer updates](https://learn.microsoft.com/en-us/windows/msix/app-installer/auto-update-and-repair--overview),
[Smart App Control FAQ](https://support.microsoft.com/en-us/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions),
[GitHub releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).
