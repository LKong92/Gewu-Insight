using System.Diagnostics;
using Microsoft.Web.WebView2.Core;

namespace GewuInsight.Windows;

internal sealed partial class WorkspaceWindow
{
    readonly CancellationTokenSource applicationLifetime = new();
    readonly Queue<DateTime> serviceRestarts = new();
    bool workspaceReady;
    bool recoveringService;

    void RefreshWorkspaceSession()
    {
        workspaceToken = File.ReadAllText(Path.Combine(dataRoot, "data", ".gewu-workspace-token")).Trim();
        if (workspaceToken.Length != 64 || workspaceToken.Any(c => !"0123456789abcdef".Contains(c)))
            throw new IOException("The private workspace session is invalid. Restore its backup before reopening.");
        client.DefaultRequestHeaders.Remove("X-Gewu-Workspace");
        client.DefaultRequestHeaders.Add("X-Gewu-Workspace", workspaceToken);
    }

    void WatchService(Process process)
    {
        process.Exited += (_, _) => {
            if (stopping || !IsHandleCreated) return;
            try { BeginInvoke(new Action(async () => await RecoverServiceAsync(process))); }
            catch (InvalidOperationException) { }
        };
        process.EnableRaisingEvents = true;
    }

    async Task RecoverServiceAsync(Process exited)
    {
        if (stopping || !workspaceReady || recoveringService || server != exited) return;
        recoveringService = true;
        CancelCapture(); suggestions.Hide(); browserVisible = false; browserActive = false; favicons.Active = false;
        LayoutBrowser(); startup.Text = "Reconnecting to your research workspace…"; startup.Show(); startup.BringToFront();
        try {
            for (int attempt = 0; attempt < 3 && !stopping; attempt++) {
                while (serviceRestarts.Count > 0 && DateTime.UtcNow - serviceRestarts.Peek() > TimeSpan.FromMinutes(1)) serviceRestarts.Dequeue();
                if (serviceRestarts.Count >= 3) break;
                serviceRestarts.Enqueue(DateTime.UtcNow);
                StopServer();
                try {
                    await Task.Delay(300 * (attempt + 1), applicationLifetime.Token);
                    await StartServerAsync();
                    RefreshWorkspaceSession();
                    var loaded = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
                    void Completed(object? sender, CoreWebView2NavigationCompletedEventArgs args) => loaded.TrySetResult(args.IsSuccess);
                    workspace.CoreWebView2.NavigationCompleted += Completed;
                    try {
                        var request = workspace.CoreWebView2.Environment.CreateWebResourceRequest(origin!.AbsoluteUri, "GET", null, "X-Gewu-Workspace: " + workspaceToken + "\r\n");
                        workspace.CoreWebView2.NavigateWithWebResourceRequest(request);
                        if (!await loaded.Task.WaitAsync(TimeSpan.FromSeconds(20), applicationLifetime.Token) || server!.HasExited)
                            throw new IOException("The workspace did not reconnect.");
                    } finally { workspace.CoreWebView2.NavigationCompleted -= Completed; }
                    // Retain the separate webpage views and their native sessions,
                    // including unsent forms. Only the trusted workspace reloads.
                    await SendStateAsync();
                    startup.Hide(); ActiveControl = workspace; workspace.Focus();
                    log?.WriteLine("Local service recovered; existing Browser tabs retained.");
                    return;
                } catch (OperationCanceledException) when (stopping) { return; }
                catch (Exception error) { log?.WriteLine("Service recovery: " + error.Message); }
            }
            if (!stopping) { StopServer(); startup.Text = "The local service could not recover.\nClose and reopen Gewu Insight. See logs/windows-launcher.log."; }
        } finally { recoveringService = false; }
    }
}
