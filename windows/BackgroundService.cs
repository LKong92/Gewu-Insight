using System.Diagnostics;
using System.Net;
using System.Text.Json;

namespace GewuInsight.Windows;

// A windowless host keeps service output and lifetime independent of the App UI.
internal static class BackgroundService
{
    public static int Run(string[] args)
    {
        string Option(string key, string fallback) { int i = Array.IndexOf(args, key); return i >= 0 && i + 1 < args.Length ? args[i + 1] : fallback; }
        string root = Path.GetFullPath(Option("--source", AppContext.BaseDirectory));
        string workspace = Option("--workspace", "");
        if (!Path.IsPathFullyQualified(workspace)) throw new IOException("Choose an existing Gewu Database.");
        string bundled = Path.Combine(root, "service", "python.exe");
        bool installed = File.Exists(bundled);
        string python = installed ? bundled : Option("--python", Path.Combine(root, ".venv", "Scripts", "python.exe"));
        if (!installed && !args.Contains("--source")) throw new IOException("The installed runtime is missing. Reinstall Gewu Insight.");
        var start = new ProcessStartInfo(python) { WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true };
        start.ArgumentList.Add("-X"); start.ArgumentList.Add("utf8"); start.ArgumentList.Add("-B");
        if (installed) { start.ArgumentList.Add(Path.Combine(root, "service", "service_entry.py")); start.ArgumentList.Add("--background-service"); }
        else { start.ArgumentList.Add("-m"); start.ArgumentList.Add("paper_monitor.windows_background"); }
        foreach (string argument in new[] { "--workspace", workspace, "--app", Environment.ProcessPath!, "--host-pid", Environment.ProcessId.ToString(), "--port", Option("--port", "0") }) start.ArgumentList.Add(argument);
        start.Environment["PYTHONUTF8"] = "1";
        start.Environment["PYTHONIOENCODING"] = "utf-8";
        using var process = Process.Start(start) ?? throw new IOException("Could not start the Gewu background service.");
        process.WaitForExit();
        return process.ExitCode;
    }
}

internal sealed partial class WorkspaceWindow
{
    bool NativeHandoffBusy => publisherDownloading || capturePreparing || captureDownload != null || activePdfReads > 0 || startingPdfPreview.Count > 0;
    bool detachService;
    bool zoteroActive;
    bool presenceBusy;
    string zoteroHandoff = "";
    DateTime handoffDeadline;
    readonly System.Windows.Forms.Timer zoteroTimer = new() { Interval = 1500 };

    async Task<Process?> FindBackgroundServiceAsync()
    {
        try {
            string address = File.ReadAllText(Path.Combine(dataRoot, "data", ".gewu-api-url")).Trim();
            if (!Uri.TryCreate(address, UriKind.Absolute, out var endpoint) || endpoint.Scheme != "http"
                || endpoint.Host != "127.0.0.1" || endpoint.UserInfo.Length > 0 || endpoint.AbsolutePath != "/"
                || endpoint.Query.Length > 0 || endpoint.Fragment.Length > 0) return null;
            RefreshWorkspaceSession();
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(2));
            using var response = await client.GetAsync(new Uri(endpoint, "api/health"), timeout.Token);
            response.EnsureSuccessStatusCode();
            using var json = JsonDocument.Parse(await response.Content.ReadAsStringAsync(timeout.Token));
            var health = json.RootElement;
            if (TextValue(health, "database_uuid") != database.Identity
                || !Path.GetFullPath(TextValue(health, "database_path")).Equals(Path.Combine(dataRoot, "data", "paper_monitor.sqlite"), StringComparison.OrdinalIgnoreCase)
                || !Path.GetFullPath(TextValue(health, "app_path")).Equals(Environment.ProcessPath, StringComparison.OrdinalIgnoreCase)
                || !health.TryGetProperty("host_pid", out var host) || !host.TryGetInt32(out int pid) || pid <= 0) return null;
            var process = Process.GetProcessById(pid);
            if (process.HasExited) { process.Dispose(); return null; }
            origin = endpoint;
            return process;
        } catch (Exception error) when (error is IOException or UnauthorizedAccessException or HttpRequestException or TaskCanceledException or JsonException or ArgumentException or InvalidOperationException) { return null; }
    }

    void StartZoteroPresence()
    {
        zoteroTimer.Tick += async (_, _) => await CheckZoteroPresenceAsync();
        zoteroTimer.Start();
    }

    async Task CheckZoteroPresenceAsync()
    {
        if (presenceBusy || stopping || recoveringService || origin == null) return;
        presenceBusy = true;
        try {
            using var response = await client.GetAsync(new Uri(origin, "api/integrations/zotero/session"), applicationLifetime.Token);
            response.EnsureSuccessStatusCode();
            using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            var status = document.RootElement;
            bool active = status.GetProperty("active").GetBoolean();
            if (!NativeHandoffBusy && zoteroHandoff.Length > 0 && status.GetProperty("handoff_requests").EnumerateArray().Any(v => v.GetString() == zoteroHandoff)) {
                detachService = true; closeApproved = true; Close(); return;
            }
            if (zoteroHandoff.Length > 0 && DateTime.UtcNow > handoffDeadline) {
                zoteroHandoff = "";
                await WorkspaceScriptAsync("window.gewuZoteroHandoffFailed?.()");
            }
            if (active == zoteroActive) return;
            if (active && NativeHandoffBusy) return;
            zoteroActive = active;
            workspace.Enabled = !active;
            if (MainMenuStrip != null) MainMenuStrip.Enabled = !active;
            if (active) {
                CancelCapture(); suggestions.Hide();
                foreach (var page in pages) if (page.View != null) page.View.Visible = false;
                loaderWindow?.Hide();
                startup.SetStatus("Open in Zotero", "Your Gewu workspace is being used in Zotero.\nClose its Gewu Insight tab to continue here.");
                startup.Show(); startup.BringToFront();
            } else {
                // Rebuild only after the other UI releases its session.
                var core = workspace.CoreWebView2;
                core.NavigateWithWebResourceRequest(core.Environment.CreateWebResourceRequest(origin.AbsoluteUri, "GET", null, "X-Gewu-Workspace: " + workspaceToken + "\r\n"));
                startup.Hide(); LayoutBrowser();
            }
        } catch (Exception error) when (error is HttpRequestException or TaskCanceledException or JsonException or InvalidOperationException) {
            log?.WriteLine("Zotero presence check: " + error.Message);
        } finally { presenceBusy = false; }
    }

    Task BeginZoteroHandoffAsync(JsonElement payload)
    {
        string request = TextValue(payload, "request_id");
        if (TextValue(payload, "action") != "handoff" || !System.Text.RegularExpressions.Regex.IsMatch(request, "^[A-Za-z0-9_-]{16,80}$"))
            throw new IOException("Invalid Zotero handoff request.");
        zoteroHandoff = request; handoffDeadline = DateTime.UtcNow.AddSeconds(40);
        return CheckZoteroPresenceAsync();
    }
}
