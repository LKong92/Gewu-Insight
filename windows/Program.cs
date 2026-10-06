using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace GewuInsight.Windows;

internal static class Program
{
    [STAThread]
    static void Main(string[] args)
    {
        TaskbarIdentity.Initialize();
        ApplicationConfiguration.Initialize();
        try { Application.Run(new WorkspaceWindow(args)); }
        catch (Exception error) { MessageBox.Show(error.Message, "Gewu Insight could not start", MessageBoxButtons.OK, MessageBoxIcon.Error); }
    }
}

internal sealed class BrowserPage
{
    public string Id { get; } = Guid.NewGuid().ToString("N");
    public WebView2? View;
    public bool Home = true;
    public bool Loading;
    public string Title = "Home";
    public string Url = "";
    public int Generation;
    public string OriginPaperId = "";
    public string OriginLibraryItemId = "";
    public string OriginUrl = "";
    public readonly List<BrowserHistoryEntry> History = [new(null)];
    public int HistoryIndex;
    public int? HistoryTarget;
    public bool DepartingHome;
    public ulong ActiveNavigation;
    public Task? Initializing;
}

internal sealed partial class WorkspaceWindow : Form
{
    readonly WebView2 workspace = new() { Dock = DockStyle.Fill };
    readonly Label startup = new() { Text = "Gewu Insight\nStarting your research workspace…", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter };
    readonly List<BrowserPage> pages = [];
    readonly BrowserFavicons favicons;
    readonly string root;
    readonly string dataRoot;
    readonly string python;
    readonly HttpClient client = new(new HttpClientHandler { UseProxy = false, AllowAutoRedirect = false });
    string workspaceToken = "";
    Process? server;
    CoreWebView2Environment? remoteEnvironment;
    BrowserPage? selected;
    Uri? origin;
    Rectangle browserBounds;
    bool browserVisible;
    bool stopping;
    StreamWriter? log;
    FileStream? workspaceLock;

    public WorkspaceWindow(string[] args)
    {
        string Option(string key, string fallback) { int index = Array.IndexOf(args, key); return index >= 0 && index + 1 < args.Length ? args[index + 1] : fallback; }
        root = Path.GetFullPath(Option("--source", AppContext.BaseDirectory));
        dataRoot = WorkspaceLocation.Resolve(args);
        python = Option("--python", Path.Combine(root, ".venv", "Scripts", "python.exe"));
        Text = "Gewu Insight — Windows Preview";
        Icon = new Icon(Path.Combine(AppContext.BaseDirectory, "GewuInsight.ico"), 256, 256);
        MinimumSize = new Size(900, 640); Size = new Size(1360, 900); StartPosition = FormStartPosition.CenterScreen;
        favicons = new BrowserFavicons(PublicUrl, (host, data) => EmitAsync(new { @event = "favicon", host, data_url = data }));
        Controls.Add(workspace); Controls.Add(startup); Controls.Add(suggestions); startup.BringToFront();
        suggestions.Chosen += async url => await EmitAsync(new { @event = "address-suggestion", url });
        Deactivate += async (_, _) => { suggestions.Hide(); await EmitAsync(new { @event = "suggestions-dismissed" }); };
        ResizeBegin += async (_, _) => { suggestions.Hide(); await EmitAsync(new { @event = "suggestions-dismissed" }); };
        Activated += (_, _) => { if (!startup.Visible) { var view = selected?.View?.Visible == true ? selected.View : workspace; ActiveControl = view; view.Focus(); } };
        Shown += async (_, _) => { try { await StartAsync(); } catch (Exception error) { startup.Text = "Startup failed\n" + error.Message; } };
        FormClosing += (_, _) => { stopping = true; applicationLifetime.Cancel(); browserPageMenu?.Dispose(); favicons.Dispose(); CancelCapture(); StopServer(); };
        FormClosed += (_, _) => { loaderWindow?.Dispose(); foreach (var page in pages) page.View?.Dispose(); client.Dispose(); log?.Dispose(); workspaceLock?.Dispose(); };
        var menu = new MenuStrip();
        var file = new ToolStripMenuItem("File");
        file.DropDownItems.Add("Open Data Folder", null, (_, _) => Process.Start(new ProcessStartInfo(dataRoot) { UseShellExecute = true }));
        file.DropDownItems.Add("Library Loader", null, async (_, _) => await ShowLibraryLoaderAsync());
        file.DropDownItems.Add("Exit", null, (_, _) => Close());
        var edit = new ToolStripMenuItem("Edit");
        foreach (var (label, chord, keys) in new[] { ("Undo", "Ctrl+Z", "^z"), ("Redo", "Ctrl+Y", "^y"), ("Cut", "Ctrl+X", "^x"), ("Copy", "Ctrl+C", "^c"), ("Paste", "Ctrl+V", "^v"), ("Select All", "Ctrl+A", "^a") }) {
            // Let the focused WebView handle normal key shortcuts, including
            // editable text versus Library placement copy/paste.
            var item = new ToolStripMenuItem(label) { ShortcutKeyDisplayString = chord };
            item.Click += (_, _) => {
                var view = selected?.View?.Visible == true ? selected.View : workspace;
                if (view.CoreWebView2 == null) return;
                ActiveControl = view; view.Focus(); SendKeys.Send(keys);
            };
            edit.DropDownItems.Add(item);
        }
        var viewMenu = new ToolStripMenuItem("View");
        viewMenu.DropDownItems.Add("List View", null, async (_, _) => await WorkspaceScriptAsync("window.setLibraryContentView('list')"));
        viewMenu.DropDownItems.Add("Table View", null, async (_, _) => await WorkspaceScriptAsync("window.setLibraryContentView('table')"));
        viewMenu.DropDownItems.Add("Toggle List/Table", null, async (_, _) => await WorkspaceScriptAsync("window.toggleLibraryContentView()"));
        var loader = new ToolStripMenuItem("Loader");
        foreach (var (label, function) in new[] { ("Open Loader", "openLibraryLoader"), ("Refresh All Metadata", "openMetadataRefreshWindow"), ("Find All Missing Identifiers", "openIdentifierRecoveryWindow") })
            loader.DropDownItems.Add(label, null, async (_, _) => await WorkspaceScriptAsync("window." + function + "()"));
        var settings = new ToolStripMenuItem("Settings");
        var naming = new ToolStripMenuItem("Naming Rule");
        foreach (var (label, rule) in new[] { ("Use Title", "title"), ("Use Citation", "citation") }) {
            var item = new ToolStripMenuItem(label) { Tag = rule };
            item.Click += async (_, _) => {
                if (origin == null) return;
                try {
                    using var response = await client.PostAsync(new Uri(origin, "api/settings/library-naming"), new StringContent(JsonSerializer.Serialize(new { rule }), System.Text.Encoding.UTF8, "application/json"));
                    response.EnsureSuccessStatusCode();
                    foreach (ToolStripMenuItem sibling in naming.DropDownItems) sibling.Checked = Equals(sibling.Tag, rule);
                } catch (Exception error) { MessageBox.Show(this, error.Message, "Could not save Naming Rule"); }
            };
            naming.DropDownItems.Add(item);
        }
        naming.DropDownOpening += async (_, _) => {
            if (origin == null) return;
            try {
                using var response = await client.GetAsync(new Uri(origin, "api/settings/library-naming")); response.EnsureSuccessStatusCode();
                using var json = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
                foreach (ToolStripMenuItem item in naming.DropDownItems) item.Checked = Equals(item.Tag, TextValue(json.RootElement, "rule"));
            } catch (Exception error) { log?.WriteLine("Naming Rule menu: " + error.Message); }
        };
        settings.DropDownItems.Add(naming);
        foreach (var (label, function) in new[] { ("Add to Library", "openLibraryDestinationSettings"), ("PDF Rename Settings", "openPdfRenameSettings"), ("Preview Settings", "openQuickLookSettings"), ("Website Links", "openWebsiteLinkSettings"), ("AI Access", "openAIAccessSettings"), ("arXiv Scope Settings", "openArxivSettings"), ("Literature Data Sources", "openCitationSettings"), ("Field Settings", "openFieldSettings"), ("Font Size", "openFontSizeSettings") }) {
            settings.DropDownItems.Add(label, null, async (_, _) => { if (workspace.CoreWebView2 != null) await workspace.CoreWebView2.ExecuteScriptAsync(function + "()"); });
        }
        settings.DropDownItems.Add("Clear Monitor Cache", null, async (_, _) => {
            try {
                await ClearMonitorCacheAsync();
                if (!stopping) MessageBox.Show(this, "Monitor network cache cleared. Saved research results and Browser sign-ins are kept.", "Monitor cache cleared");
            } catch (Exception error) { if (!stopping) MessageBox.Show(this, error.Message, "Could not clear Monitor cache"); }
        });
        var help = new ToolStripMenuItem("Help");
        help.DropDownItems.Add("User Guide", null, (_, _) => Process.Start(new ProcessStartInfo(Path.Combine(root, "Windows_Preview_Guide.html")) { UseShellExecute = true }));
        help.DropDownItems.Add("Contact Us", null, (_, _) => Process.Start(new ProcessStartInfo("mailto:info@gewu-insight.com") { UseShellExecute = true }));
        menu.Items.AddRange([file, edit, viewMenu, loader, settings, help]); MainMenuStrip = menu; Controls.Add(menu);
    }

    Task WorkspaceScriptAsync(string script) => workspace.CoreWebView2 == null ? Task.CompletedTask : workspace.CoreWebView2.ExecuteScriptAsync(script);

    async Task StartAsync()
    {
        Directory.CreateDirectory(Path.Combine(dataRoot, "logs"));
        try { workspaceLock = new FileStream(Path.Combine(dataRoot, ".workspace.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None); }
        catch (IOException) { throw new IOException("This Library is already open in another Gewu Insight window. Close that window first."); }
        log = new StreamWriter(Path.Combine(dataRoot, "logs", "windows-launcher.log"), append: true) { AutoFlush = true };
        log.WriteLine("Workspace: " + dataRoot);
        using (var socket = new TcpListener(IPAddress.Loopback, 0)) { socket.Start(); origin = new Uri($"http://127.0.0.1:{((IPEndPoint)socket.LocalEndpoint).Port}/"); }
        await StartServerAsync();
        RefreshWorkspaceSession();
        // This client only contacts the workspace origin; redirects are disabled.
        // The remote Browser has a separate profile and never receives this token.
        try { CoreWebView2Environment.GetAvailableBrowserVersionString(); }
        catch (WebView2RuntimeNotFoundException) { throw new InvalidOperationException("Microsoft Edge WebView2 Runtime is required. Install the Evergreen Runtime from https://developer.microsoft.com/microsoft-edge/webview2/ and reopen Gewu Insight."); }
        var environment = await CoreWebView2Environment.CreateAsync(null, Path.Combine(dataRoot, "webview", "workspace"));
        remoteEnvironment = await CoreWebView2Environment.CreateAsync(null, Path.Combine(dataRoot, "webview", "browser"));
        await workspace.EnsureCoreWebView2Async(environment);
        ConnectWorkspaceRecovery();
        workspace.GotFocus += (_, _) => DismissMenus();
        workspace.CoreWebView2.Settings.AreHostObjectsAllowed = false;
        workspace.CoreWebView2.NavigationStarting += (_, e) => { if (!Trusted(e.Uri)) e.Cancel = true; };
        workspace.CoreWebView2.NewWindowRequested += (_, e) => { e.Handled = true; if (PublicUrl(e.Uri)) _ = OpenPageAsync(e.Uri, true); };
        workspace.CoreWebView2.PermissionRequested += (_, e) => e.State = CoreWebView2PermissionState.Deny;
        workspace.CoreWebView2.WebMessageReceived += async (_, e) => {
            if (!Trusted(e.Source)) return;
            try {
                using var doc = JsonDocument.Parse(e.WebMessageAsJson);
                string channel = doc.RootElement.GetProperty("channel").GetString() ?? "";
                if (channel == "browser") await BrowserCommandAsync(doc.RootElement.GetProperty("payload"));
                else if (channel == "dismissMenus") DismissMenus();
                else if (channel == "choosePath") await ChoosePathAsync(doc.RootElement.GetProperty("payload"));
                else if (channel == "libraryLoaderWindow" && TextValue(doc.RootElement.GetProperty("payload"), "type") == "open") await ShowLibraryLoaderAsync();
                else if (channel == "nativeFileDrag") StartFileDrag(doc.RootElement.GetProperty("payload"));
                else if (channel == "libraryItemDrag") ArmLibraryItemDrag(doc.RootElement.GetProperty("payload"));
                else if (channel == "publisherPdfDownload") await PublisherPdfDownloadAsync(doc.RootElement.GetProperty("payload").Clone());
                else if (channel == "fileDrop") {
                    if (await HandleLibraryItemFileDropAsync(doc.RootElement.GetProperty("payload"))) return;
                    var paths = e.AdditionalObjects.OfType<CoreWebView2File>().Select(file => file.Path).Where(path => File.Exists(path) || Directory.Exists(path)).Take(256).ToArray();
                    if (paths.Length > 0) await WorkspaceScriptAsync("window.handleNativeFinderDrop(" + JsonSerializer.Serialize(paths) + "," + doc.RootElement.GetProperty("payload").GetRawText() + ")");
                }
                else if (channel == "appReady" && !recoveringService) startup.Visible = false;
                else if (channel == "paperFileChooser") {
                    using var chooser = new OpenFileDialog { Multiselect = true, Title = "Add Paper Files" };
                    var paperId = TextValue(doc.RootElement.GetProperty("payload"), "paper_id");
                    if (chooser.ShowDialog(this) == DialogResult.OK) await workspace.CoreWebView2.ExecuteScriptAsync("window.handleNativePaperFileSelection?.(" + JsonSerializer.Serialize(new { paper_id = paperId, paths = chooser.FileNames }) + ")");
                }
                else if (channel == "authorPhotoChooser") {
                    using var chooser = new OpenFileDialog { Filter = "Images|*.jpg;*.jpeg;*.png;*.webp;*.gif|All Files|*.*", Title = "Choose Author Photo" };
                    var authorId = doc.RootElement.GetProperty("payload").GetProperty("author_id").GetInt32();
                    if (chooser.ShowDialog(this) == DialogResult.OK) await workspace.CoreWebView2.ExecuteScriptAsync("window.handleNativeAuthorPhotoSelection?.(" + JsonSerializer.Serialize(new { author_id = authorId, path = chooser.FileName }) + ")");
                }
            } catch (Exception error) { await EmitAsync(new { @event = "error", message = error.Message }); }
        };
        using (var bridge = new StreamReader(typeof(Program).Assembly.GetManifestResourceStream("GewuInsight.Windows.workspace.js")!))
            await workspace.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(bridge.ReadToEnd().Replace("__WORKSPACE_ORIGIN__", JsonSerializer.Serialize(origin!.GetLeftPart(UriPartial.Authority))));
        using (var preview = new StreamReader(typeof(Program).Assembly.GetManifestResourceStream("GewuInsight.Windows.pdf-preview.js")!))
            await workspace.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync("if(location.origin === " + JsonSerializer.Serialize(origin!.GetLeftPart(UriPartial.Authority)) + ") {" + preview.ReadToEnd() + "}");
        workspace.CoreWebView2.NavigationCompleted += (_, e) => { if (e.IsSuccess && !recoveringService) { startup.Visible = false; ActiveControl = workspace; workspace.Focus(); } };
        var initialRequest = environment.CreateWebResourceRequest(origin!.AbsoluteUri, "GET", null,
            "X-Gewu-Workspace: " + workspaceToken + "\r\n");
        workspace.CoreWebView2.NavigateWithWebResourceRequest(initialRequest);
        workspaceReady = true;
        if (server!.HasExited) await RecoverServiceAsync(server);
    }

    async Task StartServerAsync()
    {
        var bundled = Path.Combine(root, "service", "python.exe");
        var start = new ProcessStartInfo(File.Exists(bundled) ? bundled : python) { WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true, RedirectStandardError = true, RedirectStandardOutput = true };
        start.ArgumentList.Add("-B");
        if (File.Exists(bundled)) start.ArgumentList.Add(Path.Combine(root, "service", "service_entry.py"));
        else { start.ArgumentList.Add("-m"); start.ArgumentList.Add("paper_monitor"); }
        foreach (var argument in new[] { "--db", Path.Combine(dataRoot, "data", "paper_monitor.sqlite"), "ui", "--host", "127.0.0.1", "--port", origin!.Port.ToString() }) start.ArgumentList.Add(argument);
        start.Environment["GEWU_WORKSPACE_ROOT"] = dataRoot;
        start.Environment["GEWU_DATA_ROOT"] = Path.Combine(dataRoot, "data");
        start.Environment["PYTHONUTF8"] = "1";
        start.Environment["PYTHONIOENCODING"] = "utf-8";
        server = Process.Start(start) ?? throw new IOException("Could not start the local service.");
        WatchService(server);
        server.OutputDataReceived += (_, e) => { if (e.Data != null) lock (log!) log.WriteLine(e.Data); };
        server.ErrorDataReceived += (_, e) => { if (e.Data != null) lock (log!) log.WriteLine(e.Data); };
        server.BeginOutputReadLine(); server.BeginErrorReadLine();
        for (int i = 0; i < 600; i++) {
            if (server.HasExited) throw new IOException("The local service stopped. See logs/windows-launcher.log.");
            try { using var response = await client.GetAsync(new Uri(origin, "api/health")); if (response.IsSuccessStatusCode) return; } catch (HttpRequestException) { }
            await Task.Delay(200, applicationLifetime.Token);
        }
        throw new TimeoutException("The local service did not become ready in two minutes.");
    }

    void StopServer() { if (server != null) { try { if (!server.HasExited) { server.Kill(entireProcessTree: true); server.WaitForExit(5000); } } catch (InvalidOperationException) { } server.Dispose(); server = null; } }
    bool Trusted(string url) => Uri.TryCreate(url, UriKind.Absolute, out var uri) && origin != null && uri.Scheme == origin.Scheme && uri.Host == origin.Host && uri.Port == origin.Port;
    static bool PublicUrl(string url)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri) || uri.Scheme is not ("http" or "https") || uri.UserInfo.Length > 0) return false;
        string host = uri.DnsSafeHost.TrimEnd('.').ToLowerInvariant();
        if (!host.Contains('.') && !host.Contains(':')) return false;
        if (host == "localhost" || new[] { ".localhost", ".local", ".internal", ".home", ".lan" }.Any(host.EndsWith)) return false;
        if (!IPAddress.TryParse(host.Trim('[', ']'), out var address)) return true;
        if (address.IsIPv4MappedToIPv6) address = address.MapToIPv4();
        var bytes = address.GetAddressBytes();
        if (address.AddressFamily == AddressFamily.InterNetwork) return bytes[0] is not (0 or 10 or 127) && !(bytes[0] == 169 && bytes[1] == 254) && !(bytes[0] == 172 && bytes[1] >= 16 && bytes[1] <= 31) && !(bytes[0] == 192 && bytes[1] == 168) && bytes[0] < 224;
        return !IPAddress.IsLoopback(address) && !address.IsIPv6LinkLocal && !address.IsIPv6SiteLocal && !address.IsIPv6Multicast && (bytes[0] & 0xfe) != 0xfc && !address.Equals(IPAddress.IPv6Any);
    }
    async Task EmitAsync(object payload)
    {
        if (stopping || workspace.CoreWebView2 == null) return;
        try { await workspace.CoreWebView2.ExecuteScriptAsync("window.gewuBrowserNativeEvent?.(" + JsonSerializer.Serialize(payload) + ");"); }
        catch (Exception error) when (error is InvalidOperationException or System.Runtime.InteropServices.COMException) {
            // Native callbacks can finish while the workspace is being replaced.
            if (!stopping) log?.WriteLine("Workspace event: " + error.Message);
        }
    }
    async Task SendStateAsync()
    {
        await EmitAsync(new { @event = "tabs", tabs = pages.Select(p => new { id = p.Id, title = p.Title, url = p.Url, home = p.Home, loading = p.Loading }).ToArray() });
        await EmitAsync(new { @event = "state", tab_id = selected?.Id, url = selected?.Url ?? "", title = selected?.Title ?? "Home", home = selected?.Home ?? true, loading = selected?.Loading ?? false, progress = 0.5, canBack = selected != null && selected.HistoryIndex > 0, canForward = selected != null && selected.HistoryIndex < selected.History.Count - 1 });
    }

    async Task OpenPageAsync(string url, bool newTab, string originPaperId = "", string originLibraryItemId = "")
    {
        if (url.Length > 0 && !PublicUrl(url)) throw new InvalidOperationException("Only public HTTP(S) websites are allowed.");
        if (newTab || selected == null) { if (pages.Count >= 32) throw new InvalidOperationException("Close a webpage tab before opening another (32 tab limit)."); selected = new BrowserPage(); pages.Add(selected); }
        var page = selected;
        page.OriginPaperId = originPaperId;
        page.OriginLibraryItemId = originLibraryItemId;
        page.OriginUrl = originPaperId.Length > 0 ? url : "";
        if (url.Length == 0) { await ShowHomeAsync(page); return; }
        await EnsureBrowserViewAsync(page);
        if (!pages.Contains(page)) return;
        StopNavigation(page); page.DepartingHome = page.Home;
        page.View!.CoreWebView2.Navigate(url); LayoutBrowser(); await SendStateAsync();
    }

    Task EnsureBrowserViewAsync(BrowserPage page) => page.Initializing ??= CreateBrowserViewAsync(page);

    async Task CreateBrowserViewAsync(BrowserPage page)
    {
        if (page.View == null) {
            page.View = new WebView2 { Visible = false }; Controls.Add(page.View);
            await page.View.EnsureCoreWebView2Async(remoteEnvironment);
            page.View.GotFocus += async (_, _) => { DismissMenus(); suggestions.Hide(); await EmitAsync(new { @event = "suggestions-dismissed" }); };
            var core = page.View.CoreWebView2;
            core.Settings.AreHostObjectsAllowed = false; core.Settings.IsWebMessageEnabled = false;
            core.PermissionRequested += (_, e) => e.State = CoreWebView2PermissionState.Deny;
            ConnectNavigation(page);
            await ConnectLoadedPdfsAsync(page);
            ConnectBrowserKeys(page);
            core.FaviconChanged += async (_, _) => await favicons.RequestAsync(core.Source, core.FaviconUri);
            core.NewWindowRequested += async (_, e) => {
                using var deferral = e.GetDeferral();
                e.Handled = true;
                if (!PublicUrl(e.Uri) || pages.Count >= 32 || stopping) return;
                var popup = new BrowserPage { OriginPaperId = page.OriginPaperId, OriginLibraryItemId = page.OriginLibraryItemId, OriginUrl = page.OriginUrl }; pages.Add(popup);
                try {
                    await EnsureBrowserViewAsync(popup);
                    if (stopping || !pages.Contains(popup)) return;
                    popup.DepartingHome = true; selected = popup;
                    // Hand Chromium the destination view. The original popup
                    // request/body and opener relationship stay browser-owned.
                    e.NewWindow = popup.View!.CoreWebView2;
                    LayoutBrowser(); await SendStateAsync();
                } catch (Exception error) {
                    await ClosePageAsync(popup.Id);
                    await EmitAsync(new { @event = "error", message = error.Message });
                }
            };
            core.WindowCloseRequested += async (_, _) => await ClosePageAsync(page.Id);
            core.DownloadStarting += (_, e) => {
                if (page.Home) { StopNavigation(page); _ = SendStateAsync(); }
                string mime = e.DownloadOperation.MimeType ?? "";
                bool document = mime.Contains("pdf", StringComparison.OrdinalIgnoreCase) || mime.Contains("octet-stream", StringComparison.OrdinalIgnoreCase)
                    || Path.GetExtension(e.ResultFilePath).Equals(".pdf", StringComparison.OrdinalIgnoreCase);
                if (document && !PdfSources.Approved(e.DownloadOperation.Uri)) {
                    e.Cancel = true; e.Handled = true; _ = EmitAsync(new { @event = "error", message = PdfSources.Unverified }); return;
                }
                if (document && BeginPdfPreview(page, e)) return;
                using var save = new SaveFileDialog { FileName = Path.GetFileName(e.ResultFilePath), Title = "Save Download" };
                if (save.ShowDialog(this) == DialogResult.OK) e.ResultFilePath = save.FileName; else e.Cancel = true;
                e.Handled = true;
            };
            core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
            core.WebResourceRequested += (_, e) => { if (!PublicUrl(e.Request.Uri) && !e.Request.Uri.StartsWith("data:") && !e.Request.Uri.StartsWith("blob:")) e.Response = remoteEnvironment!.CreateWebResourceResponse(Stream.Null, 403, "Blocked local resource", ""); };
        }
    }

    void LayoutBrowser() { foreach (var page in pages) if (page.View != null) { page.View.Bounds = browserBounds; page.View.Visible = (browserVisible || (browserActive && capturePreparing)) && page == selected && !page.Home; if (page.View.Visible) page.View.BringToFront(); } if (suggestions.Visible) suggestions.BringToFront(); }
    async Task ClosePageAsync(string id) { var page = pages.FirstOrDefault(p => p.Id == id); if (page == null) return; pages.Remove(page); ForgetLoadedPdfs(page); page.View?.Dispose(); if (selected == page) selected = pages.LastOrDefault(); if (selected == null) await OpenPageAsync("", true); LayoutBrowser(); await SendStateAsync(); }
    static string TextValue(JsonElement e, string key) => e.TryGetProperty(key, out var value) ? value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : value.ValueKind == JsonValueKind.Number ? value.GetRawText() : "" : "";

    async Task BrowserCommandAsync(JsonElement command)
    {
        string action = TextValue(command, "action");
        switch (action) {
            case "layout":
                browserActive = command.TryGetProperty("active", out var active) && active.GetBoolean();
                canReturnToWorkspace = command.TryGetProperty("canReturnToWorkspace", out var canReturn) && canReturn.GetBoolean();
                browserSidebarVisible = command.TryGetProperty("sidebarVisible", out var sidebar) && sidebar.GetBoolean();
                capturePreparing = command.TryGetProperty("capturePreparing", out var preparing) && preparing.GetBoolean();
                favicons.Active = browserActive;
                if (!browserActive) { suggestions.Hide(); CancelCapture(); }
                double scale = workspace.Width / Math.Max(1.0, command.GetProperty("viewportWidth").GetDouble());
                browserBounds = new Rectangle(workspace.Left + (int)(command.GetProperty("x").GetDouble() * scale), workspace.Top + (int)(command.GetProperty("y").GetDouble() * scale), Math.Max(0, (int)(command.GetProperty("width").GetDouble() * scale)), Math.Max(0, (int)(command.GetProperty("height").GetDouble() * scale)));
                browserVisible = command.GetProperty("visible").GetBoolean(); LayoutBrowser(); break;
            case "new-tab": await OpenPageAsync(TextValue(command, "url"), true, TextValue(command, "origin_paper_id"), TextValue(command, "origin_library_item_id")); break;
            case "navigate": await OpenPageAsync(TextValue(command, "url"), false, TextValue(command, "origin_paper_id"), TextValue(command, "origin_library_item_id")); break;
            case "home": await OpenPageAsync("", false); break;
            case "select-tab": selected = pages.FirstOrDefault(p => p.Id == TextValue(command, "tab_id")) ?? selected; LayoutBrowser(); await SendStateAsync(); break;
            case "close-tab": await ClosePageAsync(TextValue(command, "tab_id")); break;
            case "back": if (selected != null) await TraverseHistoryAsync(selected, -1); break;
            case "forward": if (selected != null) await TraverseHistoryAsync(selected, 1); break;
            case "reload": if (selected?.Home != true) selected?.View?.Reload(); else await SendStateAsync(); break;
            case "stop": if (selected != null) StopNavigation(selected); await SendStateAsync(); break;
            case "focus": selected?.View?.Focus(); break;
            case "external": if (selected != null && PublicUrl(selected.Url)) Process.Start(new ProcessStartInfo(selected.Url) { UseShellExecute = true }); break;
            case "share": ShowPageActions(command); break;
            case "download": if (selected != null) await SaveBrowserDownloadAsync(selected); break;
            case "editor": await EditBookmarkAsync(command); break;
            case "confirm": await ConfirmBrowserActionAsync(command); break;
            case "capture": await CaptureArticleAsync(command); break;
            case "capture-download": await CapturePdfAsync(command); break;
            case "capture-cancel": CancelCapture(TextValue(command, "snapshot_id")); break;
            case "read-bookmark-source": await ReadBookmarkSourceAsync(command); break;
            case "choose-bookmark-source-folder": await ChooseBookmarkSourceFolderAsync(command); break;
            case "import-bookmarks":
                using (var open = new OpenFileDialog { Filter = "Bookmark files|*.html;*.htm;*.zip", Title = "Import Bookmarks" }) {
                    if (open.ShowDialog(this) == DialogResult.OK) {
                        if (new FileInfo(open.FileName).Length > 16 * 1024 * 1024) throw new IOException("Bookmark file exceeds 16 MB.");
                        await EmitAsync(new { @event = "bookmark-import", content_base64 = Convert.ToBase64String(await File.ReadAllBytesAsync(open.FileName)) });
                    }
                }
                break;
            case "export-bookmarks":
                using (var save = new SaveFileDialog { Filter = "Bookmark HTML|*.html", FileName = "Gewu Bookmarks.html", Title = "Export Bookmarks" }) {
                    if (save.ShowDialog(this) == DialogResult.OK) await File.WriteAllTextAsync(save.FileName, TextValue(command, "html"));
                }
                break;
            case "find":
                if (selected?.View?.CoreWebView2 != null) {
                    var text = JsonSerializer.Serialize(TextValue(command, "text"));
                    bool backward = command.TryGetProperty("backwards", out var backwards) && backwards.GetBoolean();
                    string found = await selected.View.CoreWebView2.ExecuteScriptAsync($"window.find({text},false,{backward.ToString().ToLowerInvariant()},true)");
                    await EmitAsync(new { @event = "find-result", found = found == "true" });
                }
                break;
            case "favicon": await favicons.RequestAsync(TextValue(command, "url")); break;
            case "suggestions": ShowSuggestions(command); break;
            default: await EmitAsync(new { @event = "error", message = $"Windows development build: {action} is not connected yet." }); break;
        }
    }
}
