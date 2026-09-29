# Windows Desktop from Source

Double-click **Start Gewu Insight.cmd** at the repository root. It opens an
independent Gewu desktop window with the native menus, embedded Browser and PDF
integration. The desktop shell starts the Python service from this checkout.
Close the Gewu window to stop both the shell and its service; the launch console
does not need to stay open. Close another Gewu instance or Source Web first.

## Current local delivery

On 2026-09-29, the launcher was verified with the complete existing build at
`dist/windows-preview-0.1.20/Gewu Insight.exe` and the local `.venv` interpreter.
About displays **Windows Preview 0.1.20**. Both the Python and native Nature
download fixes from 0.1.20 are present; updating Python alone with the old
0.1.19 shell would omit the native fix, so the launcher rejects older shells.

The original Library remains at `%USERPROFILE%\Gewu Insight Preview`, outside
the checkout. Its protected database tables and 19 research files were verified
unchanged, with SQLite integrity OK and no foreign-key errors. Library and the
embedded Browser/history render in the actual desktop window. Normal close,
service exit, lock release and reopening through the CMD entry were checked.
This run did not repeat a real institution-authenticated publisher download.

The installed Preview remains 0.1.19. Its old shortcuts still start that version;
use **Start Gewu Insight.cmd** for the source desktop. A verified recovery backup
is retained. No installer, certificate enrollment or Windows security change was
used. The same 0.1.20 DLL that was previously blocked now starts locally; the
reason for the changed Windows decision is unknown. This does not establish
signed-release acceptance or guarantee execution on another computer.

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
changes or replace this shell. Do not delete `dist/windows-preview-0.1.20` while
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

The launcher prefers the local 0.1.20 build, then the installed Preview, and
checks for version 0.1.20 or later. In PowerShell, use the quoted filename with
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
