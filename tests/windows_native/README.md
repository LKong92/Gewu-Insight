# Windows native acceptance

This is a product integration check, not a benchmark. It compiles the actual
Windows shell sources and exercises WebView2 plus an isolated Python service.
It refuses to run outside a repository `tmp` workspace. It never uses the
installed Library or browser profile. Its only Internet request is a public
W3C sample PDF; it stages and cancels that capture without saving a paper.

1. Generate a fresh workspace with the project's development Python:
   `python tests/windows_native/seed_workspace.py tmp/native-check`
2. Build `tests/windows_native/NativeAcceptance.csproj` using .NET 10 and the
   pinned WebView2 SDK. Put its output in `tmp/native-check-bin`.
3. Run `NativeAcceptance.exe REPOSITORY_ABSOLUTE_PATH WORKSPACE_ABSOLUTE_PATH [PYTHON_EXE]`.
   The optional runtime path supports validation with the packaged Python; without
   it, the probe uses the development virtual environment.
   `native-results.json` in that workspace contains the results. The native
   app is transparent, has no taskbar entry, and closes after completion;
   nonzero exit or `ok:false` means failure. Do not add visible test panels.

Checks cover first-page rendering, page 240, continuous wheel scroll, Ctrl-wheel
pinch events, horizontal pan, absence of the extra toolbar, canceled/stale
PDF requests versus Markdown, images without MIME hints, closing preview,
source-page metadata, browser-session PDF transfer and backend PDF validation.
Observed timings describe the generated fixtures only, not publisher papers.

For actual drag/drop, open the finished package with `--workspace` pointing to
the disposable fixture Library, then copy a file icon/name to an empty Explorer
test folder. Verify the destination hash matches and the owned source remains.
Real Shell deletion/recovery checks are in `tests/test_windows_recycle.py`.
