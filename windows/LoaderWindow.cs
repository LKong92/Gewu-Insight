using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace GewuInsight.Windows;

internal sealed partial class WorkspaceWindow
{
    Form? loaderWindow;
    WebView2? loaderView;
    Task? openingLoader;

    async Task ShowLibraryLoaderAsync()
    {
        if (!workspaceReady || stopping || recoveringService) return;
        try {
            if (loaderView == null) {
                openingLoader ??= CreateLibraryLoaderAsync();
                try { await openingLoader; } finally { openingLoader = null; }
            } else if (openingLoader != null) await openingLoader;
            if (stopping || loaderWindow == null || loaderView?.CoreWebView2 == null) return;
            // Keep the existing document and job when simply reopening. A draft
            // handed over by the main window is consumed by the shared UI.
            await loaderView.CoreWebView2.ExecuteScriptAsync("window.openLibraryLoader?.()");
            if (loaderWindow.WindowState == FormWindowState.Minimized) loaderWindow.WindowState = FormWindowState.Normal;
            if (!loaderWindow.Visible) loaderWindow.Show(this);
            loaderWindow.Activate(); loaderView.Focus();
        } catch (Exception error) {
            log?.WriteLine("Folder Loader: " + error.Message);
            if (!stopping) MessageBox.Show(this, error.Message, "Could not open Folder Loader");
        }
    }

    async Task CreateLibraryLoaderAsync()
    {
        var window = new Form { Text = "Folder Loader", Size = new Size(1220, 780), MinimumSize = new Size(940, 620),
            StartPosition = FormStartPosition.CenterParent, Icon = Icon, ShowInTaskbar = true };
        var view = new WebView2 { Dock = DockStyle.Fill };
        window.Controls.Add(view);
        loaderWindow = window; loaderView = view;
        window.FormClosing += (_, e) => { if (!stopping) { e.Cancel = true; window.Hide(); } };
        try {
            await view.EnsureCoreWebView2Async(workspace.CoreWebView2.Environment);
            var core = view.CoreWebView2;
            core.Settings.AreHostObjectsAllowed = false;
            core.PermissionRequested += (_, e) => e.State = CoreWebView2PermissionState.Deny;
            core.NavigationStarting += (_, e) => {
                e.Cancel = !Trusted(e.Uri) || !Uri.TryCreate(e.Uri, UriKind.Absolute, out var uri) || uri.AbsolutePath != "/" || uri.Query != "?standalone=loader";
            };
            core.NewWindowRequested += (_, e) => { e.Handled = true; if (PublicUrl(e.Uri)) _ = OpenPageAsync(e.Uri, true); };
            core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
            core.WebResourceRequested += (_, e) => {
                if (!Trusted(e.Request.Uri)) e.Response = core.Environment.CreateWebResourceResponse(Stream.Null, 403, "Local Loader only", "");
            };
            core.WebMessageReceived += (_, e) => {
                if (!Trusted(e.Source)) return;
                // Leave the WebView callback before showing a native dialog.
                string json = e.WebMessageAsJson;
                string[] paths = [];
                try {
                    using var message = JsonDocument.Parse(json);
                    if (TextValue(message.RootElement, "channel") == "fileDrop")
                        paths = e.AdditionalObjects.OfType<CoreWebView2File>().Select(file => file.Path).Where(path => File.Exists(path) || Directory.Exists(path)).Take(256).ToArray();
                } catch (Exception error) { log?.WriteLine("Folder Loader message: " + error.Message); return; }
                window.BeginInvoke(new Action(async () => {
                    try {
                        if (stopping || view.IsDisposed) return;
                        using var doc = JsonDocument.Parse(json);
                        string channel = TextValue(doc.RootElement, "channel");
                        var payload = doc.RootElement.GetProperty("payload");
                        if (channel == "libraryLoaderWindow" && TextValue(payload, "type") == "close") window.Hide();
                        else if (channel == "choosePath") await ChoosePathAsync(payload, view, window);
                        else if (channel == "fileDrop" && paths.Length > 0)
                            await core.ExecuteScriptAsync("window.handleNativeFinderDrop?.(" + JsonSerializer.Serialize(paths) + "," + payload.GetRawText() + ")");
                    } catch (Exception error) { log?.WriteLine("Folder Loader operation: " + error.Message); }
                }));
            };
            using var bridge = new StreamReader(typeof(Program).Assembly.GetManifestResourceStream("GewuInsight.Windows.workspace.js")!);
            await core.AddScriptToExecuteOnDocumentCreatedAsync(bridge.ReadToEnd().Replace("__WORKSPACE_ORIGIN__", JsonSerializer.Serialize(origin!.GetLeftPart(UriPartial.Authority))));
            var loaded = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
            void Completed(object? sender, CoreWebView2NavigationCompletedEventArgs e) => loaded.TrySetResult(e.IsSuccess);
            core.NavigationCompleted += Completed;
            try {
                core.NavigateWithWebResourceRequest(core.Environment.CreateWebResourceRequest(new Uri(origin!, "?standalone=loader").AbsoluteUri,
                    "GET", null, "X-Gewu-Workspace: " + workspaceToken + "\r\n"));
                if (!await loaded.Task.WaitAsync(TimeSpan.FromSeconds(30), applicationLifetime.Token)) throw new IOException("Folder Loader did not finish loading.");
            } finally { core.NavigationCompleted -= Completed; }
        } catch {
            loaderView = null; loaderWindow = null; window.Dispose(); throw;
        }
    }

    async Task ResumeLoaderAfterServiceRecoveryAsync()
    {
        if (loaderView?.CoreWebView2 == null || loaderView.IsDisposed) return;
        // Both local views share the refreshed workspace cookie. Preserve all
        // unsaved controls and let the shared progress reader report job state.
        try { await loaderView.CoreWebView2.ExecuteScriptAsync("if(state.libraryImportJobId){refreshLibraryImportJob().then(resumeLibraryImportPollingIfNeeded)}"); }
        catch (Exception error) { log?.WriteLine("Folder Loader reconnect: " + error.Message); }
    }

    bool clearingMonitorCache;
    async Task ClearMonitorCacheAsync()
    {
        if (workspace.CoreWebView2 == null || recoveringService || stopping) throw new IOException("Wait for the research workspace to be ready.");
        if (clearingMonitorCache) throw new IOException("Monitor cache cleanup is already running.");
        clearingMonitorCache = true;
        try {
            // This is the local Monitor/Library profile, never remoteEnvironment.
            // Explicit DiskCache excludes cookies, history, storage and passwords.
            await workspace.CoreWebView2.Profile.ClearBrowsingDataAsync(CoreWebView2BrowsingDataKinds.DiskCache);
        } finally { clearingMonitorCache = false; }
    }
}
