using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace GewuInsight.Windows;

internal sealed partial class WorkspaceWindow
{
    sealed record ArticleSnapshot(string Id, BrowserPage Page, int Generation, string Url, string[] Candidates);
    ArticleSnapshot? articleSnapshot;
    CancellationTokenSource? captureDownload;
    long captureGeneration;
    bool capturePreparing;

    void CancelCapture(string snapshotId = "")
    {
        if (snapshotId.Length > 0 && articleSnapshot?.Id != snapshotId) return;
        captureGeneration++;
        captureDownload?.Cancel();
        articleSnapshot = null;
    }

    bool CurrentSnapshot(ArticleSnapshot snapshot) => !stopping && articleSnapshot == snapshot &&
        selected == snapshot.Page && pages.Contains(snapshot.Page) && !snapshot.Page.Home &&
        !snapshot.Page.Loading && snapshot.Page.Generation == snapshot.Generation && snapshot.Page.Url == snapshot.Url;

    async Task CaptureArticleAsync(JsonElement command)
    {
        CancelCapture();
        string requestId = TextValue(command, "request_id");
        var page = selected;
        int generation = page?.Generation ?? 0;
        string url = page?.Url ?? "";
        long requestGeneration = captureGeneration;
        try {
            if (page?.View?.CoreWebView2 == null || page.Home || page.Loading || !PublicUrl(url))
                throw new InvalidOperationException("Wait for a public article page to finish loading.");
            var core = page.View.CoreWebView2;
            _ = CaptureBackdropAsync(page, requestId, requestGeneration);
            using var tree = JsonDocument.Parse(await core.CallDevToolsProtocolMethodAsync("Page.getFrameTree", "{}"));
            string frameId = tree.RootElement.GetProperty("frameTree").GetProperty("frame").GetProperty("id").GetString()!;
            using var world = JsonDocument.Parse(await core.CallDevToolsProtocolMethodAsync("Page.createIsolatedWorld", JsonSerializer.Serialize(new { frameId, worldName = "GewuArticleCapture" })));
            int contextId = world.RootElement.GetProperty("executionContextId").GetInt32();
            using var script = new StreamReader(typeof(Program).Assembly.GetManifestResourceStream("GewuInsight.Windows.capture.js")!);
            string result = await core.CallDevToolsProtocolMethodAsync("Runtime.evaluate", JsonSerializer.Serialize(new { expression = script.ReadToEnd(), contextId, returnByValue = true }));
            if (result.Length > 262144) throw new InvalidOperationException("Article metadata exceeded the capture limit.");
            using var evaluated = JsonDocument.Parse(result);
            if (evaluated.RootElement.TryGetProperty("exceptionDetails", out _)) throw new InvalidOperationException("The article metadata could not be read.");
            if (stopping || captureGeneration != requestGeneration || selected != page || page.Generation != generation || page.Url != url || page.Home)
                throw new InvalidOperationException("The page changed. Close Save to Gewu and try again.");
            var value = evaluated.RootElement.GetProperty("result").GetProperty("value");
            bool isPdf = value.TryGetProperty("is_pdf", out var pdf) && pdf.GetBoolean();
            var candidates = value.GetProperty("pdf_urls").EnumerateArray().Select(item => item.GetString() ?? "").Where(candidate => PublicUrl(candidate) && PdfSources.Approved(candidate)).Take(8).ToList();
            if (isPdf && PdfSources.Approved(url) && !candidates.Contains(url)) candidates.Insert(0, url);
            articleSnapshot = new ArticleSnapshot(Guid.NewGuid().ToString("N"), page, generation, url, candidates.Take(8).ToArray());
            await EmitAsync(new { @event = "capture-metadata", request_id = requestId, snapshot = new {
                snapshot_id = articleSnapshot.Id, tab_id = page.Id, url,
                metadata = value.GetProperty("metadata").Clone(), pdf_urls = candidates.Take(8).ToArray(), is_pdf = isPdf,
                origin_paper_id = page.OriginPaperId, origin_url = page.OriginUrl
            }});
        } catch (Exception error) {
            if (!stopping && captureGeneration == requestGeneration) await EmitAsync(new { @event = "capture-metadata", request_id = requestId, error = error.Message });
        }
    }

    async Task CaptureBackdropAsync(BrowserPage page, string requestId, long requestGeneration)
    {
        int generation = page.Generation;
        string url = page.Url;
        bool Current() => !stopping && browserActive && captureGeneration == requestGeneration &&
            selected == page && pages.Contains(page) && !page.Home && !page.Loading && page.Generation == generation && page.Url == url;
        if (!Current() || page.View?.CoreWebView2 == null) return;
        try {
            // Screenshot bytes stay in memory; the backend receives metadata only.
            // Keep the existing surface visible only while the dialog prepares
            // its snapshot. The UI releases it after 1.5 seconds even on failure.
            var core = page.View.CoreWebView2;
            using var metrics = JsonDocument.Parse(await core.CallDevToolsProtocolMethodAsync("Page.getLayoutMetrics", "{}").WaitAsync(TimeSpan.FromSeconds(5)));
            var viewport = metrics.RootElement.GetProperty("cssVisualViewport");
            double width = viewport.GetProperty("clientWidth").GetDouble(), height = viewport.GetProperty("clientHeight").GetDouble();
            if (!Current() || width < 1 || height < 1 || width * height > 32_000_000) return;
            double pixelsPerCssPixel = Math.Max(1, page.View.DeviceDpi / 96.0 * page.View.ZoomFactor);
            var clip = new { x = viewport.GetProperty("pageX").GetDouble(), y = viewport.GetProperty("pageY").GetDouble(), width, height, scale = Math.Min(1, 1600 / (width * pixelsPerCssPixel)) };
            string result = await core.CallDevToolsProtocolMethodAsync("Page.captureScreenshot", JsonSerializer.Serialize(new { format = "jpeg", quality = 55, clip, fromSurface = true, captureBeyondViewport = false })).WaitAsync(TimeSpan.FromSeconds(5));
            if (!Current() || result.Length > 6 * 1024 * 1024) return;
            using var image = JsonDocument.Parse(result);
            string data = TextValue(image.RootElement, "data");
            if (data.Length == 0 || data.Length > 4 * 1024 * 1024) return;
            await EmitAsync(new { @event = "capture-backdrop", request_id = requestId, image = "data:image/jpeg;base64," + data });
        } catch (Exception error) when (error is InvalidOperationException or ArgumentException or TimeoutException or JsonException or System.Runtime.InteropServices.ExternalException) {
            // A missing decorative image must not block article capture.
            if (!stopping) log?.WriteLine("Capture background: " + error.Message);
        } finally {
            if (Current()) await EmitAsync(new { @event = "capture-backdrop", request_id = requestId, image = "" });
        }
    }

    async Task CapturePdfAsync(JsonElement command)
    {
        string token = TextValue(command, "token"), uploadToken = TextValue(command, "upload_token");
        string url = TextValue(command, "url"), snapshotId = TextValue(command, "snapshot_id");
        var snapshot = articleSnapshot;
        if (!PdfSources.Approved(url)) {
            await EmitAsync(new { @event = "capture-pdf", token, error = PdfSources.Unverified }); return;
        }
        if (snapshot == null || snapshot.Id != snapshotId || !CurrentSnapshot(snapshot) ||
            !snapshot.Candidates.Contains(url) || !PublicUrl(url) || token.Length is < 16 or > 128 || uploadToken.Length is < 16 or > 128) {
            await EmitAsync(new { @event = "capture-pdf", token, error = "The article changed. Close Save to Gewu and try again." });
            return;
        }
        captureDownload?.Cancel();
        using var cancellation = new CancellationTokenSource(TimeSpan.FromSeconds(90));
        captureDownload = cancellation;
        // A hidden browser surface shares the existing Browser environment and
        // cookie policy. No cookie export or credential forwarding is needed.
        using var downloadView = new WebView2 { Visible = false };
        Controls.Add(downloadView);
        string directory = Path.Combine(Path.GetTempPath(), "gewu-browser-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        string destination = Path.Combine(directory, "Article.pdf");
        CoreWebView2DownloadOperation? operation = null;
        const long limit = 64L * 1024 * 1024;
        var completion = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        var navigations = new HashSet<string>(StringComparer.Ordinal) { url };
        bool copying = false;
        var responseTasks = new List<Task>();
        void CheckCurrent() {
            cancellation.Token.ThrowIfCancellationRequested();
            if (!CurrentSnapshot(snapshot)) throw new OperationCanceledException("The article changed.");
        }
        try {
            await downloadView.EnsureCoreWebView2Async(remoteEnvironment);
            CheckCurrent();
            var core = downloadView.CoreWebView2;
            core.Settings.AreHostObjectsAllowed = false; core.Settings.IsWebMessageEnabled = false;
            core.PermissionRequested += (_, e) => e.State = CoreWebView2PermissionState.Deny;
            core.NewWindowRequested += (_, e) => e.Handled = true;
            core.NavigationStarting += (_, e) => {
                if (!CurrentSnapshot(snapshot) || !PublicUrl(e.Uri) || !PdfSources.Approved(e.Uri) || navigations.Count >= 12) {
                    e.Cancel = true; completion.TrySetException(new IOException("The PDF redirected to an unsupported destination."));
                } else navigations.Add(e.Uri);
            };
            core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
            core.WebResourceRequested += (_, e) => {
                if (!CurrentSnapshot(snapshot) || !PublicUrl(e.Request.Uri) ||
                    (e.ResourceContext == CoreWebView2WebResourceContext.Document && !PdfSources.Approved(e.Request.Uri)))
                    e.Response = remoteEnvironment!.CreateWebResourceResponse(Stream.Null, 403, "Blocked local resource", "");
            };
            core.DownloadStarting += (_, e) => {
                e.Handled = true;
                if (!CurrentSnapshot(snapshot) || operation != null || copying || !PublicUrl(e.DownloadOperation.Uri) || !PdfSources.Approved(e.DownloadOperation.Uri) ||
                    e.DownloadOperation.TotalBytesToReceive > limit) {
                    e.Cancel = true; completion.TrySetException(new IOException("Choose one readable PDF up to 64 MB.")); return;
                }
                e.ResultFilePath = destination; operation = e.DownloadOperation;
                operation.BytesReceivedChanged += (_, _) => {
                    if (operation.BytesReceived > limit || cancellation.IsCancellationRequested || !CurrentSnapshot(snapshot)) {
                        operation.Cancel(); completion.TrySetException(new IOException("PDF retrieval was cancelled or exceeded 64 MB."));
                    }
                };
                operation.StateChanged += (_, _) => {
                    if (operation.State == CoreWebView2DownloadState.Completed) completion.TrySetResult(destination);
                    else if (operation.State == CoreWebView2DownloadState.Interrupted)
                        completion.TrySetException(new IOException("PDF download was interrupted. Retry Get PDF."));
                };
            };
            async Task ReadResponse(string json) {
                string requestId = "", stream = "";
                try {
                    using var message = JsonDocument.Parse(json);
                    var paused = message.RootElement;
                    requestId = TextValue(paused, "requestId");
                    string responseUrl = TextValue(paused.GetProperty("request"), "url");
                    CheckCurrent();
                    if (!PublicUrl(responseUrl) || !PdfSources.Approved(responseUrl)) throw new IOException(PdfSources.Unverified);
                    int status = paused.TryGetProperty("responseStatusCode", out var code) ? code.GetInt32() : 0;
                    var headers = paused.TryGetProperty("responseHeaders", out var allHeaders) ? allHeaders.EnumerateArray().ToArray() : [];
                    string Header(string name) => headers.Where(h => TextValue(h,"name").Equals(name, StringComparison.OrdinalIgnoreCase)).Select(h => TextValue(h,"value")).FirstOrDefault() ?? "";
                    if (status is 301 or 302 or 303 or 307 or 308) {
                        if (!Uri.TryCreate(new Uri(responseUrl), Header("location"), out var redirect) || !PublicUrl(redirect.AbsoluteUri) || !PdfSources.Approved(redirect.AbsoluteUri))
                            throw new IOException(PdfSources.Unverified);
                        await core.CallDevToolsProtocolMethodAsync("Fetch.continueRequest", JsonSerializer.Serialize(new {requestId}));
                        requestId = ""; return;
                    }
                    if (status != 200) throw new IOException("The website did not return a complete PDF. Finish signing in on the website, then retry.");
                    string type = Header("content-type");
                    if (!type.Contains("application/pdf", StringComparison.OrdinalIgnoreCase) && !type.Contains("application/octet-stream", StringComparison.OrdinalIgnoreCase))
                        throw new IOException("The website returned a webpage instead of a PDF. Open its PDF link or finish signing in, then retry.");
                    if (long.TryParse(Header("content-length"), out long length) && length > limit) throw new IOException("Choose a PDF up to 64 MB.");
                    if (copying || operation != null || completion.Task.IsCompleted) throw new IOException("A PDF transfer is already in progress.");
                    copying = true;
                    // Read the network body before Chromium replaces an inline
                    // PDF response with its internal HTML viewer document.
                    using var body = JsonDocument.Parse(await core.CallDevToolsProtocolMethodAsync("Fetch.takeResponseBodyAsStream", JsonSerializer.Serialize(new {requestId})));
                    stream = TextValue(body.RootElement, "stream");
                    await using (var file = new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.None, 65536, true)) {
                        long total = 0;
                        while (true) {
                            CheckCurrent();
                            using var chunk = JsonDocument.Parse(await core.CallDevToolsProtocolMethodAsync("IO.read", JsonSerializer.Serialize(new {handle = stream, size = 65536})));
                            var value = chunk.RootElement;
                            byte[] bytes = value.TryGetProperty("base64Encoded", out var encoded) && encoded.GetBoolean()
                                ? Convert.FromBase64String(TextValue(value,"data")) : System.Text.Encoding.UTF8.GetBytes(TextValue(value,"data"));
                            total += bytes.Length; if (total > limit) throw new IOException("Choose a PDF up to 64 MB.");
                            await file.WriteAsync(bytes, cancellation.Token);
                            if (value.TryGetProperty("eof", out var eof) && eof.GetBoolean()) break;
                        }
                    }
                    completion.TrySetResult(destination);
                } catch (Exception error) { completion.TrySetException(error); }
                finally {
                    if (stream.Length > 0) try { await core.CallDevToolsProtocolMethodAsync("IO.close", JsonSerializer.Serialize(new {handle = stream})); } catch (Exception) { }
                    if (requestId.Length > 0) try { await core.CallDevToolsProtocolMethodAsync("Fetch.failRequest", JsonSerializer.Serialize(new {requestId, errorReason = "Aborted"})); } catch (Exception) { }
                }
            }
            core.GetDevToolsProtocolEventReceiver("Fetch.requestPaused").DevToolsProtocolEventReceived += (_, e) => responseTasks.Add(ReadResponse(e.ParameterObjectAsJson));
            await core.CallDevToolsProtocolMethodAsync("Fetch.enable", JsonSerializer.Serialize(new {patterns = new[] {new {urlPattern = "*", resourceType = "Document", requestStage = "Response"}}}));
            core.NavigationCompleted += (_, e) => {
                if (!e.IsSuccess && e.WebErrorStatus != CoreWebView2WebErrorStatus.OperationCanceled && operation == null && !copying)
                    completion.TrySetException(new IOException("The PDF could not be loaded. Retry Get PDF after the website finishes signing in."));
            };
            using var registration = cancellation.Token.Register(() => completion.TrySetCanceled(cancellation.Token));
            var sourceUri = new Uri(snapshot.Url); var targetUri = new Uri(url);
            string referer = sourceUri.GetLeftPart(UriPartial.Authority) == targetUri.GetLeftPart(UriPartial.Authority)
                ? new UriBuilder(sourceUri) { Fragment = "" }.Uri.AbsoluteUri : sourceUri.GetLeftPart(UriPartial.Authority) + "/";
            if (sourceUri.Scheme == "https" && targetUri.Scheme != "https") referer = "";
            var request = remoteEnvironment!.CreateWebResourceRequest(url, "GET", null, referer.Length > 0 ? "Referer: " + referer + "\r\n" : "");
            core.NavigateWithWebResourceRequest(request);
            string file = await completion.Task;
            CheckCurrent();
            var info = new FileInfo(file);
            if (info.Length is <= 0 or > limit) throw new IOException("Choose a PDF up to 64 MB.");
            // Upload capabilities are loopback-only, never sent through the
            // browser or through a redirect. Backend performs structural and
            // identity validation before the review can become PDF-ready.
            using var uploader = new HttpClient(new HttpClientHandler { UseProxy = false, AllowAutoRedirect = false });
            await using var input = File.OpenRead(file);
            using var content = new StreamContent(input);
            content.Headers.ContentType = new("application/pdf");
            using var upload = new HttpRequestMessage(HttpMethod.Post, new Uri(origin!, "api/browser-capture-file")) { Content = content };
            upload.Headers.Add("X-Gewu-Capture-Token", uploadToken);
            upload.Headers.Add("X-Gewu-Filename", "Article.pdf");
            upload.Headers.Add("X-Gewu-PDF-Source", Uri.EscapeDataString(url));
            using var response = await uploader.SendAsync(upload, cancellation.Token);
            if (!response.IsSuccessStatusCode) {
                using var result = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellation.Token));
                throw new IOException(TextValue(result.RootElement, "error"));
            }
            CheckCurrent();
            await EmitAsync(new { @event = "capture-pdf", token });
        } catch (Exception error) {
            if (!stopping && articleSnapshot == snapshot)
                await EmitAsync(new { @event = "capture-pdf", token, error = error is OperationCanceledException ? "PDF retrieval was cancelled or timed out. Retry Get PDF." : error.Message });
        } finally {
            cancellation.Cancel();
            if (operation?.State == CoreWebView2DownloadState.InProgress) operation.Cancel();
            downloadView.Dispose(); Controls.Remove(downloadView);
            try { await Task.WhenAll(responseTasks).WaitAsync(TimeSpan.FromSeconds(5)); } catch (Exception) { }
            if (captureDownload == cancellation) captureDownload = null;
            try { Directory.Delete(directory, true); } catch (IOException) { } catch (UnauthorizedAccessException) { }
        }
    }
}
