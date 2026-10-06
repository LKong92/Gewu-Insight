using System.Text.Json;
using Microsoft.Web.WebView2.Core;

namespace GewuInsight.Windows;
internal sealed partial class WorkspaceWindow
{
    async Task CheckLoadedPdfsAsync()
    {
        await FixturePython("""
            import sys
            from pathlib import Path
            from pypdf import PdfWriter
            writer=PdfWriter();writer.add_blank_page(width=400,height=600)
            writer.add_metadata({'/Title':'Original loaded fixture'})
            writer.write(Path(sys.argv[1])/'loaded-original.pdf')
            """);
        var bytes = await File.ReadAllBytesAsync(Path.Combine(dataRoot, "loaded-original.pdf"));
        using var server = new System.Net.Sockets.TcpListener(System.Net.IPAddress.Loopback, 0);
        server.Start(); int port = ((System.Net.IPEndPoint)server.LocalEndpoint).Port;
        string baseUrl = "http://www.w3.org/parity-loaded";
        using var cancel = new CancellationTokenSource(); int network = 0;
        async Task Serve() {
            while (!cancel.IsCancellationRequested) {
                using var socket = await server.AcceptTcpClientAsync(cancel.Token);
                using var stream = socket.GetStream(); using var reader = new StreamReader(stream, leaveOpen: true);
                string request = await reader.ReadLineAsync(cancel.Token) ?? "";
                while ((await reader.ReadLineAsync(cancel.Token)) is { Length: > 0 }) { }
                string path = request.Split(' ').ElementAtOrDefault(1) ?? "";
                bool pdf = path.StartsWith("/parity-loaded") && !path.EndsWith("/article");
                if (pdf) network++;
                byte[] body = pdf ? bytes : System.Text.Encoding.UTF8.GetBytes("<!doctype html><title>Loaded fixture</title><link rel='icon' href='data:,'><meta name='citation_pdf_url' content='" + baseUrl + "/document'><iframe src='" + baseUrl + "/document'></iframe>");
                string headers = "HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: " + body.Length + "\r\nContent-Type: " + (pdf ? "application/pdf" : "text/html") + "\r\n" + (path.EndsWith("attachment") ? "Content-Disposition: attachment; filename=Original.pdf\r\n" : "") + "\r\n";
                await stream.WriteAsync(System.Text.Encoding.ASCII.GetBytes(headers),cancel.Token); await stream.WriteAsync(body,cancel.Token);
            }
        }
        var serving = Serve();
        var originalEnvironment = remoteEnvironment;
        remoteEnvironment = await CoreWebView2Environment.CreateAsync(null, Path.Combine(dataRoot,"pdf-profile"), new CoreWebView2EnvironmentOptions("--host-resolver-rules=\"MAP www.w3.org 127.0.0.1:" + port + "\" --no-proxy-server"));
        await OpenPageAsync("", true);
        var page = selected!; await EnsureBrowserViewAsync(page);
        var core = page.View!.CoreWebView2;
        var events = new List<string>();
        core.NavigationStarting += (_, e) => events.Add("nav " + e.NavigationId + " " + e.Uri + " epoch " + PdfEpoch(page));
        core.GetDevToolsProtocolEventReceiver("Fetch.requestPaused").DevToolsProtocolEventReceived += (_, e) => events.Add("fetch " + e.ParameterObjectAsJson);
        core.WebResourceResponseReceived += (_, e) => events.Add("response " + (e.Request.Uri.StartsWith("data:") ? "data" : e.Request.Uri));
        core.NavigationCompleted += (_, e) => events.Add("done " + e.NavigationId + " epoch " + PdfEpoch(page) + " pdfs " + JsonSerializer.Serialize(loadedPdfs.Select(p=>new {p.Url,p.Epoch,length=p.Bytes.Length})));

        await OpenPageAsync(baseUrl + "/document", false, "source-paper", "7");
        try { await Until(() => LoadedPdfFor(page, page.Url) != null && !page.Loading); }
        finally { await File.WriteAllLinesAsync(Path.Combine(dataRoot,"pdf-events.txt"),events); }
        var loaded = LoadedPdfFor(page, page.Url)!;
        Check(loaded.Bytes.SequenceEqual(bytes), "loaded extensionless PDF retains exact original response bytes");
        int requests = network;
        await WorkspaceScriptAsync("window.__pdfPreviousEvent=window.gewuBrowserNativeEvent;window.__pdfEvents=[];window.gewuBrowserNativeEvent=e=>window.__pdfEvents.push(e)");
        using (var capture = Command(new { request_id = "loaded-fixture" })) await CaptureArticleAsync(capture.RootElement);
        Check(articleSnapshot?.Candidates.Contains(page.Url) == true, "loaded PDF becomes an explicit Save to Gewu candidate");
        Check(network == requests && page.OriginLibraryItemId == "7", "loaded capture retains source membership and makes no second network request");
        // Expire the response and require no-download: the UI must receive an error,
        // never a hidden GET or a re-rendered/printed PDF.
        loadedPdfs.RemoveAll(p => p.Page == page);
        using (var command = Command(new { token = new string('a',32), upload_token = new string('b',32), url = page.Url, snapshot_id = articleSnapshot!.Id, allow_download = false })) await CapturePdfAsync(command.RootElement);
        Check(network == requests, "Use Loaded PDF missing bytes never falls back to network retrieval");
        await WorkspaceScriptAsync("window.gewuBrowserNativeEvent=window.__pdfPreviousEvent");
        await OpenPageAsync(baseUrl + "/article", false);
        await Until(() => !page.Loading && LoadedPdfFor(page, baseUrl + "/document") != null);
        Check(LoadedPdfFor(page, baseUrl + "/document")!.Bytes.SequenceEqual(bytes), "iframe PDF original response is available in its owning document");
        await OpenPageAsync(baseUrl + "/attachment", false);
        await Until(() => !page.Loading && PdfUrl(page.Url).EndsWith("/attachment") && LoadedPdfFor(page, page.Url) != null);
        Check(LoadedPdfFor(page, page.Url)!.Bytes.SequenceEqual(bytes), "attachment PDF previews original browser download bytes in the tab");
        Check(LoadedPdfFor(page, baseUrl + "/document") == null, "document navigation expires earlier iframe PDF bytes");
        await ClosePageAsync(page.Id);
        cancel.Cancel(); server.Stop();
        try { await serving; } catch (OperationCanceledException) { }
        remoteEnvironment = originalEnvironment;
    }
}
