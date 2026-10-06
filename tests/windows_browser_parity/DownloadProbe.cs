using System.Text;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace GewuInsight.Windows;

internal sealed partial class WorkspaceWindow
{
    async Task CheckPageActionsAsync(BrowserPage page)
    {
        using (var command = Command(new { x = 500, y = 100, viewportWidth = workspace.Width })) ShowPageActions(command.RootElement);
        await Until(() => browserPageMenu?.Visible == true);
        Check(browserPageMenu!.Items.Cast<ToolStripItem>().Select(i => i.Text).SequenceEqual(new[] { "Add Bookmark", "Copy Link", "Save Download", "Open in Default Browser" }), "native Share menu exposes the four Mac page actions with Windows browser routing");
        browserPageMenu.Close();
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(40));
        foreach (string scenario in new[] { "html", "pdf", "redirect", "unverified", "redirect-unverified", "private", "oversized", "spoof-pdf" }) {
            using var view = new WebView2 { Visible = false }; Controls.Add(view);
            await view.EnsureCoreWebView2Async(remoteEnvironment);
            var core = view.CoreWebView2;
            var requests = new List<string>();
            bool workspaceHeader = false;
            byte[] expected = Encoding.UTF8.GetBytes(scenario == "html" ? "<!doctype html><title>Saved original</title><p>下载测试</p>" : "%PDF-1.7\nSynthetic authorized response\n%%EOF");
            core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
            core.WebResourceRequested += (_, e) => {
                requests.Add(e.Request.Uri);
                workspaceHeader |= e.Request.Headers.Contains("X-Gewu-Workspace");
                int code = 200;
                string headers = "Content-Type: " + (scenario is "html" or "spoof-pdf" ? "text/html" : "application/pdf") + "\r\nContent-Disposition: attachment; filename=download.bin\r\n";
                if (e.Request.Uri.EndsWith("/start") && scenario is "redirect" or "redirect-unverified" or "private") {
                    code = 302;
                    string target = scenario == "redirect" ? "https://www.w3.org/__gewu_fixture/final" : scenario == "private" ? "http://127.0.0.1/private" : "https://unverified.example/file.pdf";
                    headers = "Location: " + target + "\r\n";
                }
                headers += "Content-Length: " + (scenario == "oversized" ? (129L * 1024 * 1024).ToString() : expected.Length.ToString()) + "\r\n";
                e.Response = remoteEnvironment!.CreateWebResourceResponse(new MemoryStream(expected), code, code == 200 ? "OK" : "Found", headers);
            };
            string url = scenario is "unverified" or "spoof-pdf" ? "https://unverified.example/start" : "https://www.w3.org/__gewu_fixture/start";
            string destination = Path.Combine(dataRoot, "fixture-download-" + scenario);
            Exception? failure = null;
            try { await ReadBrowserDownloadAsync(core, url, destination, timeout.Token); }
            catch (Exception error) { failure = error; }
            bool expectedFailure = scenario is not ("html" or "pdf" or "redirect");
            Check(expectedFailure ? failure is IOException : failure == null, "session Save Download outcome: " + scenario + (failure == null ? "" : " (" + failure.Message + ")"));
            if (!expectedFailure) Check(File.ReadAllBytes(destination).SequenceEqual(expected), "saved response bytes match the original: " + scenario);
            if (scenario is "redirect-unverified" or "private") Check(requests.Count == 1, "unsupported redirect stops before the target request: " + scenario);
            Check(!workspaceHeader, "workspace authentication stays out of download requests: " + scenario);
            Controls.Remove(view);
        }
        Check(selected == page && !page.Home, "standalone downloads retain the original webpage tab");
    }
}
