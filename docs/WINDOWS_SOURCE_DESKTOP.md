# Windows Desktop from Source

Double-click **Start Gewu Insight.cmd** at the repository root. It opens an
independent Gewu desktop window with the native menus, embedded Browser and PDF
integration. The desktop shell starts the Python service from this checkout.
Close the Gewu window to stop both the shell and its service; the launch console
does not need to stay open. Close another Gewu instance or Source Web first.

## Current local delivery

On 2026-09-29, Windows Preview **0.1.21** was built and deployed at
`dist/windows-preview-0.1.21/Gewu Insight.exe`. It loads this checkout with the
existing `.venv`; the launcher requires a matching 0.1.21 or newer shell.
The shared product includes macOS changes through `8a27895` with Windows
file, browser, PDF, drag/drop and recovery adapters.

The original Library remains at `%USERPROFILE%\Gewu Insight Preview`. Its
schema is now 22. After normal close/reopen, all protected original rows and
19 research-file hashes remained unchanged, with integrity OK and no foreign-key
errors. A verified database/file/source backup is in
`tmp/windows-parity-0.1.21/delivery-backup/`. Do not open the upgraded Library
with older source. See [scope and validation](WINDOWS_MAC_PARITY_0.1.21.md).

Installed Preview 0.1.19 remains uninstalled. Its archive and the old 0.1.20
payload are recovery material, not active apps. This delivery creates no
installer and changes no Windows trust settings. The current shell's 279
files were hash-verified and its actual delivery path passed isolated startup.
Real institution-authenticated downloads and every third-party drop target
were not comprehensively tested.

## Source updates

1. Close Gewu and back up the complete Library, including SQLite and managed
   files. Check for uncommitted source changes before updating.
2. Update the intended Windows source branch or reviewed source release.
   Preserve local edits and the complete desktop build directory.
3. Reinstall dependencies only if `requirements.txt` changes.
4. Double-click the same CMD entry and check the Library after any migration.

Python, HTML and JavaScript changes load from source after restart. C# shell
changes require a matching new desktop build; editing `.cs` files alone cannot
update the running native code. GitHub source updates do not automatically fetch
changes or replace this shell. Do not delete `dist/windows-preview-0.1.21` while
using this configuration.

## Setup and another Library

The current machine already has the required environment. First-time setup on
another machine requires Python, dependencies, a compatible complete desktop
build and its runtime prerequisites; a source ZIP alone is insufficient.

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The existing Python 3.13 environment was used for local verification; a clean
dependency installation on another machine was not part of this task.

The launcher prefers the local 0.1.21 build, then the installed Preview, and
checks for version 0.1.21 or later. In PowerShell, use the quoted filename with
the call operator to choose another build or Library:

```powershell
& '.\Start Gewu Insight.cmd' --desktop-exe 'C:\Apps\Gewu\Gewu Insight.exe'
& '.\Start Gewu Insight.cmd' --workspace 'C:\Research\Gewu'
& '.\Start Gewu Insight.cmd' --workspace 'C:\Research\New Gewu' --new-workspace
```

Without `--workspace`, the launcher follows the existing Preview selection in
`%USERPROFILE%\.gewu-insight\preview-workspace.txt`. An unavailable saved
selection stops startup instead of creating an empty replacement. Without a
selection, it uses an existing Preview Library or a separate Gewu Insight Source
folder. The native workspace lock prevents concurrent access by either mode.

The optional [Source Web](WINDOWS_SOURCE_WEB.md) mode is available with `--web`.
It uses an external browser and has fewer native integrations.
