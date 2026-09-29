using System.Net;
using System.Runtime.InteropServices;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;

namespace GewuInsight.Windows;

internal static class ParityProbeMain
{
    [STAThread]
    static void Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        var window = new WorkspaceWindow(args);
        window.Shown += async (_, _) => await window.RunParityProbeAsync(args.Contains("--publisher-only"));
        Application.Run(window);
    }
}

internal sealed partial class WorkspaceWindow
{
    readonly List<string> probeChecks = [];
    void Check(bool condition, string name) { if (!condition) throw new Exception(name); probeChecks.Add(name); }
    static async Task Until(Func<bool> condition, int seconds = 30)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(seconds));
        while (!condition()) await Task.Delay(50, timeout.Token);
    }
    async Task UntilJS(string expression, int seconds = 20)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(seconds));
        while (await workspace.CoreWebView2.ExecuteScriptAsync("Boolean(" + expression + ")") != "true") await Task.Delay(50, timeout.Token);
    }
    static JsonDocument Command(object value) => JsonDocument.Parse(JsonSerializer.Serialize(value));
    [DllImport("user32.dll")] static extern IntPtr SendMessage(IntPtr handle, uint message, IntPtr wParam, IntPtr lParam);

    internal async Task RunParityProbeAsync(bool publisherOnly = false)
    {
        string output = Path.Combine(dataRoot, "native-results.json");
        string stage = "startup";
        using var progress = new System.Windows.Forms.Timer { Interval = 500 };
        progress.Tick += (_, _) => File.WriteAllText(Path.Combine(dataRoot, "stage.txt"), stage + " | " + startup.Text + " | " + startup.Visible);
        progress.Start();
        try {
            await Until(() => workspaceReady && !startup.Visible, 60);
            await UntilJS("window.gewuBrowserNativeEvent && document.getElementById('browserMode')");
            await UntilJS("state.libraryLoaded && state.mode==='library'");
            Check(!server!.HasExited, "original source shell and authenticated workspace start");
            if (publisherOnly) {
                await WorkspaceScriptAsync("document.getElementById('browserMode').click()");
                await Until(() => browserActive && selected != null);
                await EnsureBrowserViewAsync(selected!);
                stage = "publisher downloads and native Library drag"; await CheckPublisherAndDragAsync();
                stage = "publisher CDN and PDF controls"; await CheckPublisherRoutesAsync();
                await File.WriteAllTextAsync(output, JsonSerializer.Serialize(new { success = true, scope = "publisher", checks = probeChecks }, new JsonSerializerOptions { WriteIndented = true }));
                return;
            }
            stage = "independent Folder Loader"; await CheckLoaderAsync();
            stage = "favicons"; await CheckFaviconsAsync();
            stage = "browser";
            await workspace.CoreWebView2.ExecuteScriptAsync("document.getElementById('browserMode').click()");
            await Until(() => browserActive && selected != null);
            string fixtures = Path.Combine(dataRoot, "fixtures"); Directory.CreateDirectory(fixtures);
            string html = "<!doctype html><meta charset=utf-8><title>Parity article</title><meta name='citation_title' content='Synthetic parity paper'><meta name='citation_doi' content='10.1234/parity'><body style='margin:0;background:#b9daf0'><h1 style='padding:80px'>Synthetic article</h1><input id='draft' value='unsent draft'><p>Only disposable test data.</p>";
            await File.WriteAllTextAsync(Path.Combine(fixtures, "article.html"), html);
            await File.WriteAllTextAsync(Path.Combine(fixtures, "second.html"), html.Replace("Parity article", "Second article"));
            var page = selected!;
            await EnsureBrowserViewAsync(page);
            var core = page.View!.CoreWebView2;
            core.SetVirtualHostNameToFolderMapping("parity.example", fixtures, CoreWebView2HostResourceAccessKind.DenyCors);
            await OpenPageAsync("https://parity.example/article.html", false);
            await Until(() => !page.Loading && page.Title == "Parity article");
            stage = "Monitor cache"; await CheckMonitorCacheAsync(page);
            stage = "Home history and keyboard"; await CheckNavigationAsync(page, fixtures);
            stage = "page actions and downloads"; await CheckPageActionsAsync(page);
            stage = "publisher downloads and native Library drag"; await CheckPublisherAndDragAsync();
            stage = "publisher CDN and PDF controls"; await CheckPublisherRoutesAsync();
            await workspace.CoreWebView2.ExecuteScriptAsync("window.__parityEvents=[]; const original=window.gewuBrowserNativeEvent; window.gewuBrowserNativeEvent=e=>{window.__parityEvents.push(e); original(e)}");
            stage = "suggestions";
            await workspace.CoreWebView2.ExecuteScriptAsync("document.getElementById('browserAddress').focus()");
            using (var command = Command(new { items = new[] { new { title = "Second article", url = "https://parity.example/second.html" }, new { title = "Unsafe", url = "file:///private" } }, selected = 0, x = 200, y = 150, width = 620, viewportWidth = workspace.Width })) ShowSuggestions(command.RootElement);
            Check(suggestions.Visible && suggestions.Entries.Length == 1 && suggestions.Selected == 0, "native history candidates reject unsupported URLs and retain selection");
            Check(Controls.GetChildIndex(suggestions) < Controls.GetChildIndex(page.View), "suggestions draw above the native webpage");
            Check(await workspace.CoreWebView2.ExecuteScriptAsync("document.activeElement.id") == "\"browserAddress\"", "showing suggestions retains address focus");
            using (var screenshot = new Bitmap(Width, Height)) { suggestions.DrawToBitmap(screenshot, new Rectangle(0, 0, suggestions.Width, suggestions.Height)); screenshot.Save(Path.Combine(dataRoot, "suggestions.png")); }
            SendMessage(suggestions.Handle, 0x201, (IntPtr)1, (IntPtr)(10 | (10 << 16)));
            await Until(() => page.Url.EndsWith("/second.html") && !page.Loading && page.Title == "Second article");
            Check(!suggestions.Visible, "native mouse selection navigates to the chosen candidate and dismisses it");
            using (var command = Command(new { items = Array.Empty<object>() })) ShowSuggestions(command.RootElement);
            Check(!suggestions.Visible, "empty suggestions dismiss without geometry fields");
            await workspace.CoreWebView2.ExecuteScriptAsync("const field=document.getElementById('browserAddress'); field.focus(); field.value='parity'; field.dispatchEvent(new InputEvent('input',{inputType:'insertText',bubbles:true}))");
            await Until(() => suggestions.Visible && suggestions.Entries.Length > 0);
            int nextSuggestion = suggestions.Selected < 0 ? 0 : (suggestions.Selected + 1) % suggestions.Entries.Length;
            await workspace.CoreWebView2.ExecuteScriptAsync("document.getElementById('browserAddress').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}))");
            await Until(() => suggestions.Selected == nextSuggestion);
            Check(await workspace.CoreWebView2.ExecuteScriptAsync("document.getElementById('browserAddress').value.startsWith('https://parity.example/')") == "true", "address typing queries actual history and ArrowDown selects a candidate");
            await workspace.CoreWebView2.ExecuteScriptAsync("document.getElementById('browserAddress').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})); document.getElementById('browserAddress').blur()");
            await Until(() => !suggestions.Visible);
            Check(true, "Escape dismisses the native history list through the shared keyboard handler");
            stage = "capture";
            await UntilJS("!document.getElementById('browserSaveGewu').disabled");
            await workspace.CoreWebView2.ExecuteScriptAsync("document.getElementById('browserSaveGewu').click()");
            await UntilJS("window.__parityEvents.some(e=>e.event==='capture-backdrop' && e.image)");
            await UntilJS("window.__parityEvents.some(e=>e.event==='capture-metadata' && e.snapshot)");
            string backdrop = JsonSerializer.Deserialize<string>(await workspace.CoreWebView2.ExecuteScriptAsync("window.__parityEvents.find(e=>e.event==='capture-backdrop' && e.image).image"))!;
            byte[] jpeg = Convert.FromBase64String(backdrop.Split(',')[1]);
            using (var input = new MemoryStream(jpeg)) using (var image = Image.FromStream(input)) {
                Check(image.Width <= 1600 && image.Height > 0 && jpeg.Length <= 4 * 1024 * 1024, "real WebView snapshot is a bounded JPEG");
                image.Save(Path.Combine(dataRoot, "backdrop.png"));
            }
            await UntilJS("document.querySelector('.capture-page-backdrop')?.hidden===false");
            Check(await workspace.CoreWebView2.ExecuteScriptAsync("getComputedStyle(document.querySelector('.capture-page-backdrop')).filter.includes('blur')") == "true", "snapshot renders with the existing dialog blur");
            await workspace.CoreWebView2.ExecuteScriptAsync("document.querySelector('[data-capture=cancel]').click()");
            await Until(() => articleSnapshot == null);
            await workspace.CoreWebView2.ExecuteScriptAsync("window.__parityEvents=[]");
            using (var command = Command(new { request_id = "cancelled-probe" })) {
                Task task = CaptureArticleAsync(command.RootElement); CancelCapture(); await task;
            }
            await Task.Delay(300);
            Check(await workspace.CoreWebView2.ExecuteScriptAsync("window.__parityEvents.filter(e=>e.request_id==='cancelled-probe').length") == "0", "cancelled capture emits neither late metadata nor background image");
            await workspace.CoreWebView2.ExecuteScriptAsync("window.__originalBrowserSend=window.webkit.messageHandlers.browser.postMessage; window.webkit.messageHandlers.browser.postMessage=p=>{if(p.action!=='capture')window.__originalBrowserSend(p)}; document.getElementById('browserSaveGewu').click()");
            await UntilJS("!!document.querySelector('.browser-capture-overlay')");
            await Until(() => !page.View.Visible, 4);
            Check(await workspace.CoreWebView2.ExecuteScriptAsync("!document.querySelector('[data-capture=cancel]').disabled") == "true", "a missing snapshot releases the webpage overlay and leaves Cancel usable");
            await workspace.CoreWebView2.ExecuteScriptAsync("window.webkit.messageHandlers.browser.postMessage=window.__originalBrowserSend; document.querySelector('[data-capture=cancel]').click()");
            stage = "bookmark sync";
            string bookmarks = Path.Combine(fixtures, "Bookmarks");
            var tree = new { version = 1, roots = new { bookmark_bar = new { type = "folder", guid = "bar", name = "Bar", children = new[] {
                new { type = "folder", guid = "research", name = "Research", children = new[] { new { type = "url", guid = "paper", name = "Chosen paper", url = "https://parity.example/article.html" } } },
                new { type = "folder", guid = "other", name = "Unselected", children = new[] { new { type = "url", guid = "private", name = "Keep outside", url = "https://parity.example/second.html" } } }
            } } } };
            await File.WriteAllTextAsync(bookmarks, JsonSerializer.Serialize(tree));
            byte[] before = await File.ReadAllBytesAsync(bookmarks);
            using (var payload = Command(await ReadChromeBookmarkFileAsync(bookmarks))) {
                Check(payload.RootElement.GetProperty("source_id").GetString()!.Length == 64, "Chrome source uses a stable path digest");
            }
            bool rejected = false;
            try { await ReadChromeBookmarkFileAsync(Path.Combine(fixtures, "article.html")); } catch (IOException) { rejected = true; }
            Check(rejected, "source reader refuses non-Bookmarks files");
            for (int pass = 0; pass < 2; pass++) {
                using var timer = new System.Windows.Forms.Timer { Interval = 100 };
                timer.Tick += (_, _) => {
                    var dialog = Application.OpenForms.Cast<Form>().FirstOrDefault(form => form.Text == "Choose a folder to sync into Gewu");
                    if (dialog == null) return;
                    var choice = Descendants(dialog).OfType<ComboBox>().Single();
                    choice.SelectedIndex = Enumerable.Range(0, choice.Items.Count).First(i => choice.Items[i]!.ToString()!.Contains("Research"));
                    Descendants(dialog).OfType<Button>().Single(button => button.Text == "Sync Folder").PerformClick(); timer.Stop();
                };
                await workspace.CoreWebView2.ExecuteScriptAsync("document.getElementById('browserMessageText').textContent=''");
                timer.Start(); await EmitAsync(await ReadChromeBookmarkFileAsync(bookmarks));
                await UntilJS("document.getElementById('browserMessageText').textContent.includes('Synced ')");
                if (pass == 1) Check(await workspace.CoreWebView2.ExecuteScriptAsync("document.getElementById('browserMessageText').textContent.startsWith('Synced 0 new bookmarks')") == "true", "repeat native folder sync reuses existing bookmarks");
            }
            byte[] after = await File.ReadAllBytesAsync(bookmarks);
            Check(before.SequenceEqual(after), "native source sync never writes the selected Chrome file");
            await UntilJS("[...document.querySelectorAll('.browser-entry-title')].some(e=>e.textContent==='Chosen paper')");
            Check(await workspace.CoreWebView2.ExecuteScriptAsync("[...document.querySelectorAll('.browser-entry-title')].every(e=>e.textContent!=='Keep outside')") == "true", "only the chosen source subtree reaches the real Library database");
            stage = "service recovery";
            await core.ExecuteScriptAsync("document.getElementById('draft').value='draft retained through crash'");
            for (int crash = 0; crash < 3; crash++) {
                int previousPid = server!.Id;
                server.Kill();
                await Until(() => server != null && server.Id != previousPid && !recoveringService && !startup.Visible, 45);
                Check(selected == page && page.View.CoreWebView2 == core, $"service restart {crash + 1} retains the webpage view");
                Check(loaderView?.CoreWebView2 != null && await loaderView.CoreWebView2.ExecuteScriptAsync("state.libraryImportJob?.status==='completed'") == "true", $"service restart {crash + 1} preserves the Loader document and completed result");
                Check(await core.ExecuteScriptAsync("document.getElementById('draft').value") == "\"draft retained through crash\"", $"service restart {crash + 1} preserves the unsent form");
                using var health = await client.GetAsync(new Uri(origin!, "api/library/bootstrap"));
                Check(health.IsSuccessStatusCode, $"service restart {crash + 1} restores authenticated Library access");
            }
            await workspace.CoreWebView2.ExecuteScriptAsync("document.getElementById('browserMode').click()");
            await Until(() => browserActive && page.View.Visible);
            Check(!page.Home && page.Url.EndsWith("/second.html"), "reopening Browser after recovery keeps the existing page instead of resetting Home");
            await UntilJS("[...document.querySelectorAll('.browser-entry-title')].some(e=>e.textContent==='Chosen paper')");
            Check(true, "synced bookmarks persist through repeated service crashes");
            server!.Kill();
            await Until(() => !recoveringService && startup.Text.Contains("could not recover"));
            Check(server == null, "repeated crashes stop at the bounded recovery limit");
            await File.WriteAllTextAsync(output, JsonSerializer.Serialize(new { success = true, checks = probeChecks }, new JsonSerializerOptions { WriteIndented = true }));
        } catch (Exception error) {
            string diagnostics = workspace.CoreWebView2 == null ? "" : await workspace.CoreWebView2.ExecuteScriptAsync("JSON.stringify({events:window.__parityEvents?.map(e=>({event:e.event,error:e.error})),capture:!!document.querySelector('.browser-capture-overlay'),status:document.querySelector('.capture-status')?.textContent,disabled:document.getElementById('browserSaveGewu')?.disabled})");
            diagnostics += JsonSerializer.Serialize(new { selected?.Home, selected?.DepartingHome, selected?.Title, selected?.Url, selected?.Loading, selected?.HistoryIndex, selected?.HistoryTarget, nativeUrl = selected?.View?.CoreWebView2?.Source });
            await File.WriteAllTextAsync(output, JsonSerializer.Serialize(new { success = false, stage, checks = probeChecks, error = error.ToString(), startup = startup.Text, diagnostics, browserActive, captureGeneration }, new JsonSerializerOptions { WriteIndented = true }));
        } finally { Close(); }
    }

    static IEnumerable<Control> Descendants(Control root)
    {
        foreach (Control child in root.Controls) { yield return child; foreach (var descendant in Descendants(child)) yield return descendant; }
    }

    sealed class IconHandler : HttpMessageHandler
    {
        internal readonly List<Uri> Requests = [];
        internal byte[] Bytes = [];
        internal string Redirect = "";
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken token)
        {
            Requests.Add(request.RequestUri!); await Task.Delay(10, token);
            if (request.Headers.Contains("X-Gewu-Workspace") || request.Headers.Contains("Cookie") || request.Headers.Authorization != null) throw new Exception("Icon request leaked authentication");
            if (Redirect.Length > 0) { var response = new HttpResponseMessage(HttpStatusCode.Redirect); response.Headers.Location = new Uri(Redirect); return response; }
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(Bytes) };
        }
    }
    async Task CheckFaviconsAsync()
    {
        using var bitmap = new Bitmap(96, 48);
        using (var graphics = Graphics.FromImage(bitmap)) graphics.Clear(Color.ForestGreen);
        using var raw = new MemoryStream(); bitmap.Save(raw, System.Drawing.Imaging.ImageFormat.Png);
        var handler = new IconHandler { Bytes = raw.ToArray() };
        var results = new List<string>();
        using (var icons = new BrowserFavicons(PublicUrl, (_, value) => { results.Add(value); return Task.CompletedTask; }, handler)) {
            await icons.RequestAsync("https://example.org/paper"); Check(handler.Requests.Count == 0, "inactive Browser makes no favicon requests");
            icons.Active = true;
            await Task.WhenAll(icons.RequestAsync("https://example.org/paper"), icons.RequestAsync("https://example.org/other"));
            await icons.RequestAsync("https://example.org/again");
            Check(handler.Requests.Count == 1 && results.Count == 2, "favicon requests deduplicate in flight and reuse the cache");
            Check(results.All(value => value.StartsWith("data:image/png;base64,") && value.Length < 90000), "favicon bytes normalize to the existing UI PNG contract");
            using var png = new MemoryStream(Convert.FromBase64String(results[0].Split(',')[1])); using var image = Image.FromStream(png);
            Check(image.Size == new Size(64, 64), "favicon preserves aspect ratio inside a 64 pixel image");
        }
        var redirect = new IconHandler { Redirect = "http://127.0.0.1/private" };
        using (var icons = new BrowserFavicons(PublicUrl, (_, _) => Task.CompletedTask, redirect) { Active = true }) {
            await icons.RequestAsync("https://example.org/"); Check(redirect.Requests.Count == 1, "favicon refuses private or insecure redirects before requesting them");
        }
        var oversized = new IconHandler { Bytes = new byte[512 * 1024 + 1] };
        using (var icons = new BrowserFavicons(PublicUrl, (_, data) => { Check(data == "", "oversized favicon returns only a placeholder"); return Task.CompletedTask; }, oversized) { Active = true }) await icons.RequestAsync("https://example.org/");
    }
}
