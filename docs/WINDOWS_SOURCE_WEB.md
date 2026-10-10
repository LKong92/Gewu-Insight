# Windows Source Web diagnostics

Source Web starts the checkout's Python service in an external browser for
isolated development. Daily use and final acceptance use the installed desktop
App. The root CMD launches that installed App; do not pass `--web` to the CMD.

After [development setup](DEVELOPMENT.md#manual-setup), run in PowerShell:

```powershell
.venv\Scripts\python.exe scripts/windows_source.py --web --workspace $env:GEWU_WORKSPACE_ROOT
```

Keep the terminal open; Ctrl+C stops the service. Closing the browser tab alone
does not stop it. The service binds to loopback and uses a one-time launch ticket;
do not paste authentication tokens into documentation or shortcuts.

For a different fresh synthetic workspace, supply a new empty absolute directory
and `--new-workspace`. Always give an explicit development path. The current
launcher does not consult the installed App's database locator or old
`preview-workspace.txt`; its implicit fallback is a per-checkout development
folder. An existing explicit workspace must contain the expected database.

Source Web does not provide the native WebView2 Browser, its authenticated
publisher capture bridge, Windows drag/drop or native PDF integration. Source
updates require service restart; C# changes require a rebuilt shell and installer.
Do not use a real research collection as test data or run two processes against
the same collection.
