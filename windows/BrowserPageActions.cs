using System.Diagnostics;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace GewuInsight.Windows;

internal sealed partial class WorkspaceWindow
{
    bool savingBrowserDownload;
    ContextMenuStrip? browserPageMenu;

    void ShowPageActions(JsonElement command)
    {
        if (selected is not { Home: false } page || !PublicUrl(page.Url)) return;
        browserPageMenu?.Dispose();
        var menu = browserPageMenu = new ContextMenuStrip();
        bool Current() => selected == page && pages.Contains(page) && !page.Home && browserActive;
        menu.Items.Add("Add Bookmark", null, async (_, _) => { if (Current()) { workspace.Focus(); await EmitAsync(new { @event = "bookmark" }); } });
        menu.Items.Add("Copy Link", null, (_, _) => { if (Current()) Clipboard.SetText(page.Url); });
        menu.Items.Add("Save Download", null, async (_, _) => { if (Current()) await SaveBrowserDownloadAsync(page); });
        menu.Items.Add("Open in Default Browser", null, (_, _) => { if (Current() && PublicUrl(page.Url)) Process.Start(new ProcessStartInfo(page.Url) { UseShellExecute = true }); });
        double scale = workspace.Width / Math.Max(1.0, command.GetProperty("viewportWidth").GetDouble());
        var point = new Point((int)(command.GetProperty("x").GetDouble() * scale), (int)(command.GetProperty("y").GetDouble() * scale));
        BeginInvoke(new Action(() => { if (Current()) menu.Show(workspace, point); }));
    }

    async Task SaveBrowserDownloadAsync(BrowserPage page)
    {
        if (savingBrowserDownload || page.Home || !PublicUrl(page.Url)) return;
        savingBrowserDownload = true;
        string url = page.Url;
        string directory = Path.Combine(Path.GetTempPath(), "gewu-browser-save-" + Guid.NewGuid().ToString("N"));
        string destination = Path.Combine(directory, "response");
        Directory.CreateDirectory(directory);
        using var view = new WebView2 { Visible = false };
        Controls.Add(view);
        using var cancel = CancellationTokenSource.CreateLinkedTokenSource(applicationLifetime.Token);
        cancel.CancelAfter(TimeSpan.FromMinutes(2));
        try {
            await EmitAsync(new { @event = "download", message = "Preparing Save Download with this website session…" });
            await view.EnsureCoreWebView2Async(remoteEnvironment);
            string name = await ReadBrowserDownloadAsync(view.CoreWebView2, url, destination, cancel.Token);
            if (stopping) return;
            using var save = new SaveFileDialog { Title = "Save Download", FileName = name, Filter = "All files|*.*" };
            if (save.ShowDialog(this) != DialogResult.OK) { await EmitAsync(new { @event = "download", message = "Save Download cancelled." }); return; }
            // Finish writing beside the chosen target before replacing it, so
            // a full disk/failed copy cannot truncate an existing destination.
            string staged = Path.Combine(Path.GetDirectoryName(save.FileName)!, ".gewu-save-" + Guid.NewGuid().ToString("N"));
            try { File.Copy(destination, staged); File.Move(staged, save.FileName, overwrite: true); }
            catch (IOException) { throw new IOException("Could not save the download. Retry Save Download and choose another location."); }
            finally { try { File.Delete(staged); } catch (IOException) { } catch (UnauthorizedAccessException) { } }
            await EmitAsync(new { @event = "download", message = "Saved " + Path.GetFileName(save.FileName) });
        } catch (Exception error) {
            if (!stopping) await EmitAsync(new { @event = "error", message = error is OperationCanceledException ? "Save Download timed out. Retry after the website finishes loading." : error.Message });
        } finally {
            view.Dispose(); Controls.Remove(view); savingBrowserDownload = false;
            try { Directory.Delete(directory, true); } catch (IOException) { } catch (UnauthorizedAccessException) { }
        }
    }

    async Task<string> ReadBrowserDownloadAsync(CoreWebView2 core, string url, string destination, CancellationToken cancellation)
    {
        if (!PublicUrl(url)) throw new IOException("Use a public HTTP(S) download address.");
        const long limit = 64L * 1024 * 1024;
        bool approvedChain = PdfSources.Approved(url), takingBody = false;
        int redirects = 0;
        var finished = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        var responses = new List<Task>();
        core.Settings.AreHostObjectsAllowed = false; core.Settings.IsWebMessageEnabled = false;
        core.PermissionRequested += (_, e) => e.State = CoreWebView2PermissionState.Deny;
        core.NewWindowRequested += (_, e) => e.Handled = true;
        core.DownloadStarting += (_, e) => { e.Cancel = true; e.Handled = true; if (!takingBody) finished.TrySetException(new IOException("The response could not be captured. Download it from the website.")); };
        core.NavigationStarting += (_, e) => { if (!PublicUrl(e.Uri)) { e.Cancel = true; finished.TrySetException(new IOException("The download redirected to an unsupported address.")); } };
        core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
        core.WebResourceRequested += (_, e) => {
            if (e.ResourceContext != CoreWebView2WebResourceContext.Document || !PublicUrl(e.Request.Uri))
                e.Response = remoteEnvironment!.CreateWebResourceResponse(Stream.Null, 403, "Unsupported download resource", "");
        };
        async Task ResponseAsync(string json)
        {
            string requestId = "", stream = "";
            try {
                cancellation.ThrowIfCancellationRequested();
                using var document = JsonDocument.Parse(json);
                var value = document.RootElement; requestId = TextValue(value, "requestId");
                string responseUrl = TextValue(value.GetProperty("request"), "url");
                if (!PublicUrl(responseUrl)) throw new IOException("The download redirected to an unsupported address.");
                approvedChain &= PdfSources.Approved(responseUrl);
                int status = value.TryGetProperty("responseStatusCode", out var code) ? code.GetInt32() : 0;
                var headers = value.TryGetProperty("responseHeaders", out var all) ? all.EnumerateArray().ToArray() : [];
                string Header(string name) => headers.Where(h => TextValue(h, "name").Equals(name, StringComparison.OrdinalIgnoreCase)).Select(h => TextValue(h, "value")).FirstOrDefault() ?? "";
                if (status is 301 or 302 or 303 or 307 or 308) {
                    if (++redirects > 10 || !Uri.TryCreate(new Uri(responseUrl), Header("location"), out var next) || !PublicUrl(next.AbsoluteUri) ||
                        (approvedChain && !PdfSources.Approved(next.AbsoluteUri))) throw new IOException(PdfSources.Unverified);
                    approvedChain &= PdfSources.Approved(next.AbsoluteUri);
                    await core.CallDevToolsProtocolMethodAsync("Fetch.continueRequest", JsonSerializer.Serialize(new { requestId }));
                    requestId = ""; return;
                }
                if (status != 200) throw new IOException("The website did not return a complete download. Finish signing in on the website, then retry.");
                string mime = Header("content-type");
                string name = Uri.UnescapeDataString(Path.GetFileName(new Uri(responseUrl).AbsolutePath));
                if (ContentDispositionHeaderValue.TryParse(Header("content-disposition"), out var disposition)) name = disposition.FileNameStar ?? disposition.FileName?.Trim('"') ?? name;
                name = Path.GetFileName(name.Replace('\\', '/'));
                name = string.Concat(name.Select(c => Path.GetInvalidFileNameChars().Contains(c) ? '_' : c)).Trim().TrimEnd('.');
                if (name.Length > 160) name = name[..160];
                if (name.Length == 0) name = mime.Contains("pdf", StringComparison.OrdinalIgnoreCase) ? "Download.pdf" : "Download.html";
                bool documentFile = mime.Contains("pdf", StringComparison.OrdinalIgnoreCase) || mime.Contains("octet-stream", StringComparison.OrdinalIgnoreCase) || name.EndsWith(".pdf", StringComparison.OrdinalIgnoreCase);
                if (documentFile && !approvedChain) throw new IOException(PdfSources.Unverified);
                if (long.TryParse(Header("content-length"), out long length) && length > limit) throw new IOException("Save Download supports files up to 64 MB.");
                if (takingBody) throw new IOException("A download is already being read.");
                takingBody = true;
                using var body = JsonDocument.Parse(await core.CallDevToolsProtocolMethodAsync("Fetch.takeResponseBodyAsStream", JsonSerializer.Serialize(new { requestId })));
                stream = TextValue(body.RootElement, "stream");
                await using (var file = new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.None, 65536, true)) {
                    long total = 0;
                    using var prefix = new MemoryStream();
                    while (true) {
                        cancellation.ThrowIfCancellationRequested();
                        using var chunk = JsonDocument.Parse(await core.CallDevToolsProtocolMethodAsync("IO.read", JsonSerializer.Serialize(new { handle = stream, size = 65536 })));
                        var part = chunk.RootElement;
                        byte[] bytes = part.TryGetProperty("base64Encoded", out var encoded) && encoded.GetBoolean() ? Convert.FromBase64String(TextValue(part, "data")) : Encoding.UTF8.GetBytes(TextValue(part, "data"));
                        if (!approvedChain && prefix.Length < 1024) {
                            prefix.Write(bytes, 0, Math.Min(bytes.Length, 1024 - (int)prefix.Length));
                            if (Encoding.ASCII.GetString(prefix.ToArray()).Contains("%PDF-")) throw new IOException(PdfSources.Unverified);
                        }
                        total += bytes.Length; if (total > limit) throw new IOException("Save Download supports files up to 64 MB.");
                        await file.WriteAsync(bytes, cancellation);
                        if (part.TryGetProperty("eof", out var eof) && eof.GetBoolean()) break;
                    }
                    if (total == 0) throw new IOException("The website returned an empty download.");
                }
                finished.TrySetResult(name);
            } catch (Exception error) { finished.TrySetException(error); }
            finally {
                if (stream.Length > 0) try { await core.CallDevToolsProtocolMethodAsync("IO.close", JsonSerializer.Serialize(new { handle = stream })); } catch (Exception) { }
                if (requestId.Length > 0) try { await core.CallDevToolsProtocolMethodAsync("Fetch.failRequest", JsonSerializer.Serialize(new { requestId, errorReason = "Aborted" })); } catch (Exception) { }
            }
        }
        var receiver = core.GetDevToolsProtocolEventReceiver("Fetch.requestPaused");
        void Response(object? sender, CoreWebView2DevToolsProtocolEventReceivedEventArgs args) => responses.Add(ResponseAsync(args.ParameterObjectAsJson));
        receiver.DevToolsProtocolEventReceived += Response;
        try {
            await core.CallDevToolsProtocolMethodAsync("Fetch.enable", JsonSerializer.Serialize(new { patterns = new[] { new { urlPattern = "*", resourceType = "Document", requestStage = "Response" } } }));
            core.Navigate(url);
            return await finished.Task.WaitAsync(cancellation);
        } finally {
            receiver.DevToolsProtocolEventReceived -= Response;
            try { await Task.WhenAll(responses).WaitAsync(TimeSpan.FromSeconds(3)); } catch (Exception) { }
            // The caller owns and disposes this dedicated view. No workspace
            // token, upload capability, or local file is sent to a website.
        }
    }
}
