using System.Text;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace GewuInsight.Windows;

internal sealed partial class WorkspaceWindow
{
    bool publisherDownloading;

    sealed class PublisherRequest(JsonElement context)
    {
        public string Kind = TextValue(context, "publisher_download_kind");
        public string Publisher = TextValue(context, "publisher_download_name");
        public string Referer = TextValue(context, "publisher_download_referer");
        public string Target = TextValue(context, "publisher_download_target_url");
        public string FileUrl = "";
        public string FileMime = "";
        public string[] SupplementUrls = [];
        public readonly HashSet<string> Visited = new(StringComparer.Ordinal);
        public readonly HashSet<string> ButtonAttemptedPages = new(StringComparer.Ordinal);
        public bool Inspecting;
        public bool InspectAgain;
        public CoreWebView2? ActiveView;
        public string PdfActionPage = "";
        public bool Discovery => Kind is "aaas-supplement-discovery" or "publisher-supplement-discovery";
        public bool Supplement => Discovery || Kind is "aaas-supplement-pdf" or "publisher-supplement-file";
        public bool ValidKind => Supplement || Kind is "aaas-published-pdf" or "publisher-main-pdf";
        public bool Allowed(string url)
        {
            if (!PublicUrl(url) || !PdfSources.Approved(url) || !Uri.TryCreate(url, UriKind.Absolute, out var uri) || uri.Scheme != "https") return false;
            string host = uri.IdnHost.TrimEnd('.').ToLowerInvariant();
            bool Domain(string value) => host == value || host.EndsWith("." + value, StringComparison.Ordinal);
            string publisher = Publisher.Length > 0 ? Publisher.ToLowerInvariant() : Kind.StartsWith("aaas-") ? "aaas" : "";
            // Intersect the existing reviewed source policy with the requested
            // publisher. Unknown CDN hosts stop instead of broadening access.
            return publisher switch {
                "nature" => Domain("nature.com") || host == "media.springernature.com",
                "aaas" => Domain("science.org") || Domain("sciencemag.org"),
                "acs" => host is "pubs.acs.org" or "acs.figshare.com",
                "aps" => Domain("aps.org"),
                "wiley" => Domain("onlinelibrary.wiley.com"),
                "cpl" => host is "cpl.iphy.ac.cn" or "iopscience.iop.org",
                "cpb" => host is "cpb.iphy.ac.cn" or "iopscience.iop.org",
                "elsevier" => host is "www.sciencedirect.com" or "sciencedirect.com" or "linkinghub.elsevier.com" or "reader.elsevier.com" or "ars.els-cdn.com" || Domain("sciencedirectassets.com"),
                "oup" => host is "academic.oup.com" or "preview.academic.oup.com" or "watermark.silverchair.com" or "oup.silverchair-cdn.com",
                _ => false
            };
        }
    }

    void NavigatePublisher(CoreWebView2 core, PublisherRequest request, string url, string referer)
    {
        if (!request.Allowed(url)) throw new IOException(PdfSources.Unverified);
        request.Visited.Add(url);
        string headers = "Accept: application/pdf,application/octet-stream;q=0.9,text/html;q=0.8,*/*;q=0.5\r\n";
        if (request.Allowed(referer)) {
            var source = new Uri(referer); var target = new Uri(url);
            string value = source.Authority == target.Authority ? new UriBuilder(source) { Fragment = "" }.Uri.AbsoluteUri : source.GetLeftPart(UriPartial.Authority) + "/";
            headers += "Referer: " + value + "\r\n";
        }
        core.NavigateWithWebResourceRequest(remoteEnvironment!.CreateWebResourceRequest(url, "GET", null, headers));
    }

    async Task InspectPublisherPageAsync(CoreWebView2 core, PublisherRequest request, TaskCompletionSource<string> finished, CancellationToken cancellation)
    {
        if (request.Inspecting) { request.InspectAgain = true; return; }
        request.Inspecting = true;
        string pageUrl = core.Source;
        try {
            if (!request.Allowed(pageUrl)) throw new IOException(PdfSources.Unverified);
            for (int attempt = 0; attempt < (request.Discovery ? 6 : 20); attempt++) {
                cancellation.ThrowIfCancellationRequested();
                if (finished.Task.IsCompleted || core.Source != pageUrl || request.ActiveView != core) return;
                using var tree = JsonDocument.Parse(await core.CallDevToolsProtocolMethodAsync("Page.getFrameTree", "{}"));
                string frameId = tree.RootElement.GetProperty("frameTree").GetProperty("frame").GetProperty("id").GetString()!;
                using var world = JsonDocument.Parse(await core.CallDevToolsProtocolMethodAsync("Page.createIsolatedWorld", JsonSerializer.Serialize(new { frameId, worldName = "GewuPublisherLinks" })));
                int contextId = world.RootElement.GetProperty("executionContextId").GetInt32();
                // Bounded, read-only discovery in an isolated world. No login,
                // verification, payment, consent or credential control is used.
                string expression = "(" + """
                    supplement => {
                      const files=[], landings=[];
                      for(const el of Array.from(document.querySelectorAll('meta[name="citation_pdf_url"],meta[property="citation_pdf_url"],a[href],iframe[src],embed[src]')).slice(0,3000)) {
                        let u; try {u=new URL(el.getAttribute('content')||el.getAttribute('href')||el.getAttribute('src')||'',location.href)} catch {continue}
                        const path=u.pathname.toLowerCase(), label=`${(el.textContent||'').slice(0,500)} ${el.getAttribute('title')||''} ${el.getAttribute('aria-label')||''}`.toLowerCase();
                        const sup=/supplement|supporting information|suppl_file|supinfo|suppinfo|suppdata|additional file|appendix|attachment|mmc\d|figshare/.test(`${path} ${u.search} ${label}`);
                        const pdf=/\.pdf$/i.test(path)||/\/doi\/(pdf|epdf)\/|article-pdf|pdfft|downloadarticlefile.do/.test(path)||/\bpdf\b/.test(label)||el.tagName==='META';
                        const word=/\.docx?$/i.test(path)||/\b(word|docx?)\b/.test(label);
                        if(supplement ? sup&&(pdf||word) : !sup&&pdf) files.push(u.href);
                        else if(supplement&&sup) landings.push(u.href);
                        if(files.length>=32||landings.length>=32) break;
                      }
                      return {files:[...new Set(files)],landings:[...new Set(landings)]};
                    }
                    """ + ")(" + (request.Supplement ? "true" : "false") + ")";
                using var result = JsonDocument.Parse(await core.CallDevToolsProtocolMethodAsync("Runtime.evaluate", JsonSerializer.Serialize(new { expression, contextId, returnByValue = true })));
                var links = result.RootElement.GetProperty("result").GetProperty("value");
                string[] Read(string key) => links.GetProperty(key).EnumerateArray().Select(e => e.GetString() ?? "").Where(request.Allowed).Distinct().Take(32).ToArray();
                string[] files = Read("files");
                if (request.Discovery && files.Length > 0) { request.SupplementUrls = files; finished.TrySetResult(""); return; }
                string next = !request.Supplement && request.Allowed(request.Target) && !request.Visited.Contains(request.Target) ? request.Target :
                    (request.Discovery ? Read("landings") : files).FirstOrDefault(u => !request.Visited.Contains(u)) ?? "";
                if (next.Length > 0 && request.Visited.Count < 6) { NavigatePublisher(core, request, next, pageUrl); return; }
                if (!request.Supplement && !request.ButtonAttemptedPages.Contains(pageUrl)) {
                    // A single unambiguous PDF action on an approved article
                    // page. Never use login, consent, verification or pay controls.
                    const string clickPdf = """
                        (() => {
                          const candidates=[];
                          for(const el of Array.from(document.querySelectorAll('button,[role="button"],a')).slice(0,1000)) {
                            if(el.closest('form,[role="dialog"],dialog')||el.disabled||el.getAttribute('aria-disabled')==='true') continue;
                            const label=(el.getAttribute('aria-label')||el.textContent||el.getAttribute('title')||'').trim().replace(/\s+/g,' ');
                            if(!/^(?:(?:download|view|open)\s+)?(?:full[ -]?text\s+)?pdf(?:\s*\(\s*[\d.]+\s*(?:kb|mb)\s*\))?$/i.test(label)) continue;
                            const style=getComputedStyle(el);
                            if(style.visibility==='hidden'||style.display==='none'||!el.getClientRects().length) continue;
                            if(el.tagName==='A') {
                              const raw=el.getAttribute('href')||'';
                              if(raw&&!raw.startsWith('#')&&!/^javascript:\s*void\(0\);?$/.test(raw)) continue;
                            }
                            candidates.push(el);
                          }
                          if(candidates.length!==1) return false;
                          HTMLElement.prototype.click.call(candidates[0]); return true;
                        })()
                        """;
                    request.PdfActionPage = pageUrl;
                    using var click = JsonDocument.Parse(await core.CallDevToolsProtocolMethodAsync("Runtime.evaluate", JsonSerializer.Serialize(new { expression = clickPdf, contextId, returnByValue = true })));
                    if (click.RootElement.GetProperty("result").TryGetProperty("value", out var clicked) && clicked.ValueKind == JsonValueKind.True)
                        request.ButtonAttemptedPages.Add(pageUrl);
                    else request.PdfActionPage = "";
                }
                if (attempt < (request.Discovery ? 5 : 19)) await Task.Delay(1000, cancellation);
            }
            if (request.ActiveView != core) return;
            if (request.Discovery) finished.TrySetResult("");
            else throw new IOException("The publisher did not expose a supported file. Open its page in Browser, finish any required sign-in, then retry Download.");
        } catch (Exception error) { if (request.ActiveView == core) finished.TrySetException(error); }
        finally {
            request.Inspecting = false;
            if (request.InspectAgain && request.ActiveView is { } active && !finished.Task.IsCompleted && !cancellation.IsCancellationRequested) {
                request.InspectAgain = false;
                await InspectPublisherPageAsync(active, request, finished, cancellation);
            }
        }
    }

    async Task<JsonElement> AttachPublisherFileAsync(PublisherRequest request, JsonElement context, string path, CancellationToken cancellation)
    {
        var payload = JsonSerializer.Deserialize<Dictionary<string, object>>(context.GetRawText())!;
        payload["source_path"] = path;
        payload["preserve_filename"] = false;
        payload["publisher_download_target_url"] = request.FileUrl;
        if (request.Discovery) payload["publisher_download_kind"] = request.Kind.StartsWith("aaas-") ? "aaas-supplement-pdf" : "publisher-supplement-file";
        using var response = await client.PostAsync(new Uri(origin!, "api/manual-pdf-path"), new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json"), cancellation);
        using var result = JsonDocument.Parse(await response.Content.ReadAsStringAsync(cancellation));
        if (!response.IsSuccessStatusCode) throw new IOException(TextValue(result.RootElement, "error"));
        return result.RootElement.Clone();
    }

    async Task PublisherPdfDownloadAsync(JsonElement payload)
    {
        string token = TextValue(payload, "token");
        async Task Reply(bool success, object? data, string error = "") => await WorkspaceScriptAsync("window.handleNativePublisherDownloadResult?.(" + JsonSerializer.Serialize(new { token, success, data, error }) + ")");
        if (publisherDownloading) { await Reply(false, null, "Another publisher download is already in progress."); return; }
        string directory = "";
        publisherDownloading = true;
        try {
            var context = payload.GetProperty("context");
            var request = new PublisherRequest(context);
            string url = TextValue(payload, "url"), session = workspaceToken;
            if (token.Length is < 16 or > 128 || TextValue(context, "paper_id").Length == 0 || !request.ValidKind || !request.Allowed(url)) throw new IOException(PdfSources.Unverified);
            using var cancellation = CancellationTokenSource.CreateLinkedTokenSource(applicationLifetime.Token);
            cancellation.CancelAfter(TimeSpan.FromSeconds(80));
            directory = Path.Combine(Path.GetTempPath(), "gewu-publisher-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(directory);
            string path = Path.Combine(directory, "response");
            using var view = new WebView2 { Visible = false }; Controls.Add(view);
            try {
                await view.EnsureCoreWebView2Async(remoteEnvironment).WaitAsync(cancellation.Token);
                string name = await ReadBrowserDownloadAsync(view.CoreWebView2, url, path, cancellation.Token, request);
                if (session != workspaceToken || stopping) throw new IOException("The workspace restarted. Retry the publisher download.");
                if (name.Length == 0) { await Reply(true, new { supplement_urls = request.SupplementUrls }); return; }
                string suffix = Path.GetExtension(name).ToLowerInvariant();
                if (suffix is not (".pdf" or ".doc" or ".docx")) {
                    suffix = request.Supplement && request.FileMime.Contains("wordprocessingml", StringComparison.OrdinalIgnoreCase) ? ".docx" :
                        request.Supplement && request.FileMime.Contains("msword", StringComparison.OrdinalIgnoreCase) ? ".doc" : ".pdf";
                }
                string file = Path.Combine(directory, "Publisher" + suffix); File.Move(path, file);
                var result = await AttachPublisherFileAsync(request, context, file, cancellation.Token);
                if (request.Discovery) {
                    var data = JsonSerializer.Deserialize<Dictionary<string, object>>(result.GetRawText())!;
                    data["supplement_attached"] = true; await Reply(true, data);
                } else await Reply(true, result);
            } finally { Controls.Remove(view); }
        } catch (Exception error) {
            if (!stopping) await Reply(false, null, error is OperationCanceledException ? "The publisher download timed out. Finish signing in in Browser, then retry." : error.Message);
        } finally {
            publisherDownloading = false;
            if (directory.Length > 0) try { Directory.Delete(directory, true); } catch (IOException) { } catch (UnauthorizedAccessException) { }
        }
    }
}
