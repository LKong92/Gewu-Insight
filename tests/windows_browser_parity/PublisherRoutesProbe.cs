using System.Text;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace GewuInsight.Windows;

internal sealed partial class WorkspaceWindow
{
    async Task CheckPublisherRoutesAsync()
    {
        byte[] expected = await File.ReadAllBytesAsync(Path.Combine(dataRoot, "publisher.pdf"));
        foreach (var (scenario, publisher, host, target) in new[] {
            ("acs-cdn", "acs", "pubs.acs.org", "acs.figshare.com"),
            ("oup-cdn", "oup", "academic.oup.com", "oup.silverchair-cdn.com"),
            ("oup-watermark", "oup", "academic.oup.com", "watermark.silverchair.com"),
            ("elsevier-cdn", "elsevier", "www.sciencedirect.com", "pdf.sciencedirectassets.com"),
            ("wrong-tenant", "oup", "academic.oup.com", "other.silverchair-cdn.com"),
            ("acs-cloud", "acs", "pubs.acs.org", "ndownloader.figshare.com"),
            ("button", "aps", "journals.aps.org", ""),
            ("fetch", "aps", "journals.aps.org", ""),
            ("xhr", "aps", "journals.aps.org", ""),
            ("ambiguous", "aps", "journals.aps.org", ""),
            ("form", "aps", "journals.aps.org", ""),
            ("once", "aps", "journals.aps.org", ""),
            ("popup", "aps", "journals.aps.org", ""),
            ("popup-post", "aps", "journals.aps.org", ""),
            ("popup-blank", "aps", "journals.aps.org", ""),
            ("popup-opener", "aps", "journals.aps.org", ""),
            ("popup-unverified", "aps", "journals.aps.org", ""),
            ("popup-local", "aps", "journals.aps.org", ""),
            ("popup-redirect", "aps", "journals.aps.org", ""),
            ("popup-nested", "aps", "journals.aps.org", ""),
            ("popup-unexpected", "aps", "journals.aps.org", ""),
            ("popup-cancel", "aps", "journals.aps.org", ""),
            ("popup-close", "aps", "journals.aps.org", "") }) {
            using var view = new WebView2 { Visible = false, Size = new Size(900, 700) }; Controls.Add(view);
            await view.EnsureCoreWebView2Async(remoteEnvironment);
            var core = view.CoreWebView2;
            var requests = new List<string>(); bool leaked = false, originalPost = false;
            var children = new List<WebView2>();
            void Fixture(CoreWebView2 fixture) {
              fixture.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
              fixture.WebResourceRequested += (_, e) => {
                requests.Add(e.Request.Uri); leaked |= e.Request.Headers.Contains("X-Gewu-Workspace");
                int status = 200; string mime = "application/pdf", headers = ""; byte[] bytes = expected;
                string path = new Uri(e.Request.Uri).AbsolutePath;
                if (path == "/main.pdf" && e.Request.Method == "POST") {
                    using var reader = new StreamReader(e.Request.Content, leaveOpen: true);
                    originalPost = reader.ReadToEnd() == "article=popup-body";
                }
                if (target.Length > 0 && path == "/start") { status = 302; headers = "Location: https://" + target + "/main.pdf\r\n"; }
                else if (path == "/redirect") { status = 302; headers = "Location: https://unverified.example/main.pdf\r\n"; }
                else if (path == "/state.json") { mime = "application/json"; bytes = Encoding.UTF8.GetBytes("{\"ready\":true}"); }
                else if (path == "/child") {
                    mime = "text/html";
                    string body = scenario switch {
                        "popup-opener" => "<script>if(window.opener && window.opener.__stamp==='original' && document.cookie.includes('popupFixture=yes')) location.href='/main.pdf';</script>",
                        "popup-nested" => "<button type='button' onclick=\"window.open('/main.pdf','_blank')\">Download PDF</button>",
                        "popup-close" => "<script>window.close()</script>", _ => "<p>Preparing document</p>" };
                    bytes = Encoding.UTF8.GetBytes("<!doctype html><title>Publisher child</title>"+body);
                }
                else if (path == "/start") {
                    mime = "text/html";
                    string action = scenario switch {
                        "fetch" => "fetch('/main.pdf')", "xhr" => "const r=new XMLHttpRequest();r.open('GET','/main.pdf');r.send()",
                        "once" => "window.__clicks=(window.__clicks||0)+1", "popup" => "window.open('/main.pdf','_blank')",
                        "popup-post" => "const f=document.createElement('form');f.method='POST';f.target='_blank';f.action='/main.pdf';const i=document.createElement('input');i.name='article';i.value='popup-body';f.append(i);document.body.append(f);f.submit()",
                        "popup-blank" => "const w=window.open('about:blank','pdf');w.location.href='/main.pdf'",
                        "popup-unverified" => "window.open('https://unverified.example/main.pdf','_blank')",
                        "popup-local" => "window.open('http://127.0.0.1/private.pdf','_blank')",
                        "popup-redirect" => "window.open('/redirect','_blank')",
                        "popup-opener" or "popup-nested" or "popup-cancel" or "popup-close" => "window.open('/child','_blank')",
                        _ => "location.href='/main.pdf'" };
                    string button = "<button type='button' onclick=\"" + action + "\">Download PDF</button>";
                    string body = scenario == "form" ? "<form>"+button+"</form>" : scenario == "ambiguous" ? button+button : button;
                    string initial = scenario == "popup-unexpected" ? "window.open('/main.pdf','_blank');" : "";
                    bytes = Encoding.UTF8.GetBytes("<!doctype html><title>PDF control fixture</title><script>window.__stamp='original';document.cookie='popupFixture=yes;Secure;SameSite=Lax';fetch('/state.json');"+initial+"</script>"+body);
                }
                headers += "Content-Type: " + mime + "\r\nContent-Length: " + bytes.Length + "\r\n";
                e.Response = remoteEnvironment!.CreateWebResourceResponse(new MemoryStream(bytes), status, status==200?"OK":"Found", headers);
              };
            }
            Fixture(core);
            void ChildAdded(object? sender, ControlEventArgs e) {
                if (e.Control is WebView2 child && child != view) {
                    children.Add(child);
                    child.CoreWebView2InitializationCompleted += (_, done) => { if (done.IsSuccess) Fixture(child.CoreWebView2); };
                }
            }
            ControlAdded += ChildAdded;
            using var context = Command(new { publisher_download_kind = "publisher-main-pdf", publisher_download_name = publisher });
            var request = new PublisherRequest(context.RootElement);
            bool denied = scenario is "wrong-tenant" or "acs-cloud" or "ambiguous" or "form" or "once" or
                "popup-unverified" or "popup-local" or "popup-redirect" or "popup-nested" or "popup-unexpected" or "popup-cancel" or "popup-close";
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(denied ? 4 : 12));
            string pathOut = Path.Combine(dataRoot, "route-" + scenario + ".pdf");
            Exception? error = null;
            try { await ReadBrowserDownloadAsync(core, "https://" + host + "/start", pathOut, timeout.Token, request); }
            catch (Exception exception) { error = exception; }
            finally { ControlAdded -= ChildAdded; }
            Check(denied ? error != null : error == null && File.ReadAllBytes(pathOut).SequenceEqual(expected), "publisher route original bytes and result: " + scenario + " " + error?.Message + (error != null && !denied ? " requests="+string.Join(",",requests)+" children="+children.Count : ""));
            Check(!leaked, "publisher route excludes workspace authentication: " + scenario);
            if (scenario is "wrong-tenant" or "acs-cloud") Check(requests.Count == 1, "unreviewed tenant/cloud redirect stops before request: " + scenario);
            if (scenario is "ambiguous" or "form") Check(requests.All(u => !u.EndsWith("/main.pdf")), "uncertain/form PDF control is never activated: " + scenario);
            if (scenario == "once") Check(await core.ExecuteScriptAsync("window.__clicks") == "1", "a PDF control is activated at most once per page");
            if (scenario.StartsWith("popup")) {
                Check(children.All(c => c.IsDisposed && !Controls.Contains(c)), "publisher popup is disposed on completion/failure/cancel: " + scenario);
                Check(children.Count <= 1 && requests.All(u => !u.Contains("unverified.example") && !u.Contains("127.0.0.1")), "publisher popup bounds and request policy: " + scenario);
            }
            if (scenario is "popup-unverified" or "popup-local" or "popup-unexpected") Check(children.Count == 0, "unsupported popup rejected before child creation: " + scenario);
            if (scenario == "popup-post") Check(originalPost, "publisher popup preserves original POST body");
            if (scenario == "popup-cancel") Check(error is OperationCanceledException && !File.Exists(pathOut), "cancelled publisher popup produces no output");
            Controls.Remove(view);
        }
    }
}
