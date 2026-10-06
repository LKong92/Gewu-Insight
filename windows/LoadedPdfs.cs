using System.Net.Http;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;

namespace GewuInsight.Windows;

internal sealed partial class WorkspaceWindow
{
    sealed record LoadedPdf(BrowserPage Page, int Epoch, string Url, string Name, byte[] Bytes);
    readonly List<LoadedPdf> loadedPdfs = [];
    readonly Dictionary<BrowserPage, int> pdfEpochs = [];
    readonly Dictionary<BrowserPage, LoadedPdf> pdfPreviews = [];
    readonly HashSet<BrowserPage> startingPdfPreview = [];
    readonly List<Task> readingPdfs = [];
    int activePdfReads;
    const long PdfLimit = 128L * 1024 * 1024;
    static string PdfUrl(string value) => Uri.TryCreate(value, UriKind.Absolute, out var uri) ? new UriBuilder(uri) { Fragment = "" }.Uri.AbsoluteUri : value;
    int PdfEpoch(BrowserPage page) => pdfEpochs.GetValueOrDefault(page);
    LoadedPdf? LoadedPdfFor(BrowserPage page, string url) => loadedPdfs.LastOrDefault(p => p.Page == page && p.Epoch == PdfEpoch(page) && PdfUrl(p.Url) == PdfUrl(url));
    void ForgetLoadedPdfs(BrowserPage page)
    {
        loadedPdfs.RemoveAll(p => p.Page == page); pdfPreviews.Remove(page);
        startingPdfPreview.Remove(page); pdfEpochs.Remove(page);
    }
    void RememberPdf(LoadedPdf pdf)
    {
        if (stopping || !pages.Contains(pdf.Page) || pdf.Epoch != PdfEpoch(pdf.Page) || !PdfSources.Approved(pdf.Url) || pdf.Bytes.LongLength > PdfLimit || pdf.Bytes.Length < 5 || !pdf.Bytes.AsSpan(0, 5).SequenceEqual("%PDF-"u8)) return;
        loadedPdfs.RemoveAll(p => !pages.Contains(p.Page) || (p.Page == pdf.Page && PdfUrl(p.Url) == PdfUrl(pdf.Url)));
        loadedPdfs.Add(pdf);
        while (loadedPdfs.Count > 8 || loadedPdfs.Sum(p => p.Bytes.LongLength) > 256L * 1024 * 1024) {
            var removed = loadedPdfs[0]; loadedPdfs.RemoveAt(0);
            if (pdfPreviews.GetValueOrDefault(removed.Page) == removed) pdfPreviews.Remove(removed.Page);
        }
    }
    async Task ConnectLoadedPdfsAsync(BrowserPage page)
    {
        var core = page.View!.CoreWebView2;
        core.NavigationStarting += (_, e) => {
            if (startingPdfPreview.Remove(page) && pdfPreviews.TryGetValue(page, out var preview) && PdfUrl(e.Uri) == PdfUrl(preview.Url)) return;
            pdfEpochs[page] = PdfEpoch(page) + 1;
            pdfPreviews.Remove(page); loadedPdfs.RemoveAll(p => p.Page == page);
        };
        core.WebResourceRequested += (_, e) => {
            if (pdfPreviews.TryGetValue(page, out var preview) && preview.Epoch == PdfEpoch(page) && e.Request.Method == "GET" && PdfUrl(e.Request.Uri) == PdfUrl(preview.Url))
                e.Response = remoteEnvironment!.CreateWebResourceResponse(new MemoryStream(preview.Bytes, false), 200, "OK", "Content-Type: application/pdf\r\nContent-Disposition: inline\r\nCache-Control: no-store\r\n");
        };
        core.GetDevToolsProtocolEventReceiver("Fetch.requestPaused").DevToolsProtocolEventReceived += (_, e) => {
            readingPdfs.RemoveAll(t => t.IsCompleted);
            readingPdfs.Add(PreservePdfResponseAsync(page, e.ParameterObjectAsJson));
        };
        await core.CallDevToolsProtocolMethodAsync("Fetch.enable", JsonSerializer.Serialize(new { patterns = new[] { new { urlPattern = "*", requestStage = "Response" } } }));
    }

    async Task PreservePdfResponseAsync(BrowserPage page, string json)
    {
        var core = page.View!.CoreWebView2;
        string requestId = "", stream = ""; bool consumed = false, reading = false;
        try {
            using var document = JsonDocument.Parse(json);
            var response = document.RootElement;
            requestId = TextValue(response, "requestId");
            string url = TextValue(response.GetProperty("request"), "url");
            int status = response.TryGetProperty("responseStatusCode", out var code) ? code.GetInt32() : 0;
            var headers = response.TryGetProperty("responseHeaders", out var values) ? values.EnumerateArray().ToArray() : [];
            string Header(string name) => headers.FirstOrDefault(h => TextValue(h,"name").Equals(name, StringComparison.OrdinalIgnoreCase)) is var h && h.ValueKind == JsonValueKind.Object ? TextValue(h,"value") : "";
            if (status != 200 || !Header("content-type").Contains("application/pdf", StringComparison.OrdinalIgnoreCase) || !PdfSources.Approved(url) || activePdfReads >= 2) {
                await core.CallDevToolsProtocolMethodAsync("Fetch.continueRequest", JsonSerializer.Serialize(new { requestId })); requestId = ""; return;
            }
            if (long.TryParse(Header("content-length"), out var length) && length > PdfLimit) {
                await core.CallDevToolsProtocolMethodAsync("Fetch.continueRequest", JsonSerializer.Serialize(new { requestId })); requestId = ""; return;
            }
            int epoch = PdfEpoch(page);
            activePdfReads++; reading = true;
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(applicationLifetime.Token);
            timeout.CancelAfter(TimeSpan.FromMinutes(15));
            using var opened = JsonDocument.Parse(await core.CallDevToolsProtocolMethodAsync("Fetch.takeResponseBodyAsStream", JsonSerializer.Serialize(new { requestId })).WaitAsync(TimeSpan.FromSeconds(90), timeout.Token));
            stream = TextValue(opened.RootElement,"stream"); consumed = true;
            using var output = new MemoryStream();
            while (true) {
                if (epoch != PdfEpoch(page) || !pages.Contains(page)) throw new OperationCanceledException();
                using var part = JsonDocument.Parse(await core.CallDevToolsProtocolMethodAsync("IO.read", JsonSerializer.Serialize(new { handle = stream, size = 65536 })).WaitAsync(TimeSpan.FromSeconds(90), timeout.Token));
                var value = part.RootElement;
                byte[] bytes = value.TryGetProperty("base64Encoded", out var encoded) && encoded.GetBoolean() ? Convert.FromBase64String(TextValue(value,"data")) : System.Text.Encoding.UTF8.GetBytes(TextValue(value,"data"));
                if (output.Length + bytes.Length > PdfLimit) throw new IOException("Choose a PDF up to 128 MB.");
                output.Write(bytes);
                if (value.TryGetProperty("eof", out var eof) && eof.GetBoolean()) break;
            }
            var body = output.ToArray();
            if (body.Length < 5 || !body.AsSpan(0,5).SequenceEqual("%PDF-"u8)) throw new IOException("The website did not return a PDF.");
            string name = Path.GetFileName(Uri.UnescapeDataString(new Uri(url).AbsolutePath));
            if (System.Net.Http.Headers.ContentDispositionHeaderValue.TryParse(Header("content-disposition"), out var disposition)) name = disposition.FileNameStar ?? disposition.FileName?.Trim('"') ?? name;
            if (!name.EndsWith(".pdf", StringComparison.OrdinalIgnoreCase)) name = "Article.pdf";
            RememberPdf(new LoadedPdf(page, epoch, url, Path.GetFileName(name), body));
            // Return the exact intercepted bytes to Chromium. Only presentation
            // headers change, so attachments open in the tab without another GET.
            var returned = headers.Where(h => !new[] {"content-encoding", "content-length", "content-disposition", "transfer-encoding"}.Contains(TextValue(h,"name").ToLowerInvariant()))
                .Select(h => new { name = TextValue(h,"name"), value = TextValue(h,"value") }).ToList();
            returned.Add(new { name = "Content-Length", value = body.Length.ToString() });
            returned.Add(new { name = "Content-Disposition", value = "inline" });
            await core.CallDevToolsProtocolMethodAsync("Fetch.fulfillRequest", JsonSerializer.Serialize(new { requestId, responseCode = status, responseHeaders = returned, body = Convert.ToBase64String(body) })).WaitAsync(TimeSpan.FromSeconds(30), timeout.Token);
            requestId = "";
        } catch (Exception error) { if (!stopping) log?.WriteLine("Original PDF response: " + error.Message); }
        finally {
            if (reading) activePdfReads--;
            if (stream.Length > 0) try { await core.CallDevToolsProtocolMethodAsync("IO.close", JsonSerializer.Serialize(new { handle = stream })); } catch { }
            if (requestId.Length > 0) try {
                await core.CallDevToolsProtocolMethodAsync(consumed ? "Fetch.failRequest" : "Fetch.continueRequest", JsonSerializer.Serialize(new { requestId, errorReason = "Aborted" }));
            } catch { }
        }
    }
    bool BeginPdfPreview(BrowserPage page, CoreWebView2DownloadStartingEventArgs e)
    {
        var operation = e.DownloadOperation;
        if (!operation.MimeType.Contains("pdf", StringComparison.OrdinalIgnoreCase) && !e.ResultFilePath.EndsWith(".pdf", StringComparison.OrdinalIgnoreCase)) return false;
        e.Handled = true;
        if (operation.TotalBytesToReceive > PdfLimit) { e.Cancel = true; _ = EmitAsync(new { @event = "error", message = "Choose a PDF up to 128 MB." }); return true; }
        string directory = Path.Combine(Path.GetTempPath(), "gewu-pdf-preview-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        var security = new System.Security.AccessControl.DirectorySecurity();
        security.SetAccessRuleProtection(true, false);
        security.AddAccessRule(new System.Security.AccessControl.FileSystemAccessRule(
            System.Security.Principal.WindowsIdentity.GetCurrent().User!,
            System.Security.AccessControl.FileSystemRights.FullControl,
            System.Security.AccessControl.InheritanceFlags.ContainerInherit | System.Security.AccessControl.InheritanceFlags.ObjectInherit,
            System.Security.AccessControl.PropagationFlags.None, System.Security.AccessControl.AccessControlType.Allow));
        System.IO.FileSystemAclExtensions.SetAccessControl(new DirectoryInfo(directory), security);
        string path = Path.Combine(directory, "response.pdf"), name = Path.GetFileName(e.ResultFilePath), url = operation.Uri;
        int epoch = PdfEpoch(page);
        e.ResultFilePath = path;
        operation.BytesReceivedChanged += (_, _) => { if (operation.BytesReceived > PdfLimit || stopping || !pages.Contains(page) || epoch != PdfEpoch(page)) operation.Cancel(); };
        operation.StateChanged += async (_, _) => {
            if (operation.State == CoreWebView2DownloadState.InProgress) return;
            try {
                if (operation.State != CoreWebView2DownloadState.Completed || stopping || !pages.Contains(page) || epoch != PdfEpoch(page)) return;
                if (new FileInfo(path).Length > PdfLimit) throw new IOException("Choose a PDF up to 128 MB.");
                var bytes = await File.ReadAllBytesAsync(path, applicationLifetime.Token);
                if (bytes.Length < 5 || !bytes.AsSpan(0, 5).SequenceEqual("%PDF-"u8)) throw new IOException("The website did not return a PDF.");
                var pdf = new LoadedPdf(page, epoch, url, name, bytes);
                RememberPdf(pdf);
                if (LoadedPdfFor(page, url) != pdf) throw new IOException("This PDF source is not approved for saving.");
                pdfPreviews[page] = pdf; startingPdfPreview.Add(page);
                page.DepartingHome = page.Home;
                page.View!.CoreWebView2.Navigate(url);
            } catch (Exception error) { if (!stopping) await EmitAsync(new { @event = "error", message = error.Message }); }
            finally { try { File.Delete(path); Directory.Delete(directory); } catch (IOException) { } catch (UnauthorizedAccessException) { } }
        };
        return true;
    }
    async Task UploadLoadedPdfAsync(LoadedPdf pdf, string uploadToken, CancellationToken cancellation)
    {
        using var uploader = new HttpClient(new HttpClientHandler { UseProxy = false, AllowAutoRedirect = false }) { Timeout = TimeSpan.FromMinutes(5) };
        using var content = new ByteArrayContent(pdf.Bytes); content.Headers.ContentType = new("application/pdf");
        using var upload = new HttpRequestMessage(HttpMethod.Post, new Uri(origin!, "api/browser-capture-file")) { Content = content };
        upload.Headers.Add("X-Gewu-Capture-Token", uploadToken);
        upload.Headers.Add("X-Gewu-Filename", Uri.EscapeDataString(pdf.Name));
        upload.Headers.Add("X-Gewu-PDF-Source", Uri.EscapeDataString(pdf.Url));
        using var response = await uploader.SendAsync(upload, cancellation);
        if (!response.IsSuccessStatusCode) {
            using var result = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellation));
            throw new IOException(TextValue(result.RootElement, "error"));
        }
    }
}
