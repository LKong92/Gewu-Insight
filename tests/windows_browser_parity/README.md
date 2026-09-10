# Windows browser parity regression

This product integration probe compiles the actual Windows shell sources and
runs them with a disposable SQLite Library, a separate WebView2 profile, and
generated webpages. It contains no product runtime switches or benchmark hooks.

Build `ParityProbe.csproj` with .NET 10 and the pinned WebView2 SDK, then run:

```powershell
python tests/run_windows_browser_parity.py --app tmp/windows-parity-0.1.12/probe/ParityProbe.exe --dotnet tmp/windows-toolchain/dotnet --python .venv/Scripts/python.exe --output tmp/windows-parity-0.1.12
```

The runner creates a separate hidden desktop and a job that owns only the probe
and its child processes. It refuses output outside repository `tmp`, disables
automatic monitoring, and closes the entire test process tree. WebView2 may need
normal desktop permissions outside a restricted execution sandbox.

Checks also cover local Home/native-history traversal, retained forms, cancelled
Home departures, same-document branches, original popup POST bodies/opener,
Win32 key-message routing for Ctrl+L/Ctrl+F/Ctrl+[, source-workspace return, a
native page-actions menu and response-byte downloads with blocked-source,
redirect, disguised-PDF and size-limit cases. Generated download responses are
provided only by the test views; these checks do not contact real publishers.
Keyboard messages target this test's own controls; physical keyboard/IME input
and the native Save dialog's final file selection remain separate acceptance.

Earlier checks cover native history suggestions and mouse/keyboard handling, bounded
anonymous favicon requests using a fake HTTP transport, a real webpage JPEG and
blurred capture backdrop, cancellation and missing-image fallback, selected
Chrome bookmark-folder sync and repeat reuse, and three service crash/restart
cycles that retain webpage drafts and SQLite bookmarks. A fourth rapid crash
must stop automatic retries. The generated hostname is mapped only inside the
test WebView; this does not change the product's URL policy or the hosts file.

`latest-native-result.json` points to the unique run directory and its evidence.
A successful probe is not acceptance of a newly installed signed release, an
actual personal Chrome profile, every publisher, physical IME input, or all DPI
and accessibility configurations. Do not use the real Library as test data.
