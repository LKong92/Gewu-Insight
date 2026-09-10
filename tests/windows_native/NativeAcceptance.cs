using System.Diagnostics;
using System.Reflection;
using System.Text.Json;
using Microsoft.Web.WebView2.WinForms;

namespace GewuInsight.Windows;

internal static class NativeAcceptance
{
    static readonly BindingFlags Private = BindingFlags.Instance | BindingFlags.NonPublic;
    static WorkspaceWindow form = null!;
    static WebView2 workspace = null!;
    static readonly List<object> results = [];
    static string output = "";

    [STAThread]
    static void Main(string[] args)
    {
        string root = Path.GetFullPath(args[0]), scratch = Path.GetFullPath(args[1]);
        if (!scratch.StartsWith(Path.Combine(root, "tmp") + Path.DirectorySeparatorChar)) throw new Exception("A disposable repo tmp workspace is required.");
        output = Path.Combine(scratch, "native-results.json");
        Environment.SetEnvironmentVariable("GEWU_DOCUMENTATION_MODE", "1");
        ApplicationConfiguration.Initialize();
        form = new WorkspaceWindow(["--source", root, "--workspace", scratch, "--python", Path.Combine(root, ".venv/Scripts/python.exe")]);
        form.Opacity = 0; form.ShowInTaskbar = false;
        workspace = (WebView2)typeof(WorkspaceWindow).GetField("workspace", Private)!.GetValue(form)!;
        form.Shown += async (_, _) => {
            try {
                await Until(async () => workspace.CoreWebView2 != null && await Js("typeof state !== 'undefined' && typeof quickLookLibraryPdf === 'function'") == "true", 60);
                await TestPreview();
                await TestCapture();
                File.WriteAllText(output, JsonSerializer.Serialize(new { ok = true, results }, new JsonSerializerOptions { WriteIndented = true }));
            } catch (Exception error) {
                if (workspace.CoreWebView2 != null) File.WriteAllText(Path.ChangeExtension(output, ".state.txt"), await Js("document.body.innerText.slice(-5000)"));
                File.WriteAllText(output, JsonSerializer.Serialize(new { ok = false, error = error.ToString(), results }, new JsonSerializerOptions { WriteIndented = true }));
                Environment.ExitCode = 1;
            } finally { form.Close(); }
        };
        Application.Run(form);
    }

    static Task<string> Js(string script) => workspace.CoreWebView2.ExecuteScriptAsync(script);

    static Task Call(string name, params object[] args) => (Task)typeof(WorkspaceWindow).GetMethod(name, Private)!.Invoke(form, args)!;
    static async Task Until(Func<Task<bool>> test, int seconds = 20) {
        var watch = Stopwatch.StartNew();
        while (watch.Elapsed.TotalSeconds < seconds) { if (await test()) return; await Task.Delay(50); }
        throw new TimeoutException("Native acceptance condition timed out.");
    }
    static async Task AssertJs(string expression, string label) {
        if (await Js(expression) != "true") throw new Exception(label + ": " + await Js(expression));
        results.Add(new { check = label, passed = true });
    }

    static async Task TestPreview()
    {
        await Until(async () => await Js("!!document.querySelector('[data-library-type=\"item\"]')") == "true");
        await Js("window.__files = []; document.querySelector('[data-library-type=\"item\"]').click()");
        await Until(async () => await Js("document.querySelectorAll('.library-resource-card').length >= 5") == "true");
        await Js("window.__files = Array.from(document.querySelectorAll('.library-resource-card')).map(e=>({id:Number(e.dataset.libraryResourceId),path:e.querySelector('[data-native-drag-path]').dataset.nativeDragPath}));");
        for (int i = 0; i < 2; i++) {
            var watch = Stopwatch.StartNew();
            await Js($"quickLookLibraryPdf({{merged_pdf_path:__files[{i}].path}})");
            await Until(async () => await Js("!!document.querySelector('.windows-pdf-body img')") == "true");
            results.Add(new { check = "native PDF first page", file = i, elapsed_ms = watch.ElapsedMilliseconds });
        }
        await AssertJs("!document.querySelector('.windows-pdf-toolbar') && !document.querySelector('[data-pdf=text]')", "no added preview toolbar");
        await AssertJs("document.querySelector('.windows-pdf-body').clientHeight <= document.querySelector('#libraryQuickLookPages').clientHeight && document.querySelector('.windows-pdf-body').scrollHeight > document.querySelector('.windows-pdf-body').clientHeight * 20", "bounded viewport with continuous document layout");
        using var rect = JsonDocument.Parse(await Js("(()=>{const r=document.querySelector('.windows-pdf-body').getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()"));
        double x = rect.RootElement.GetProperty("x").GetDouble(), y = rect.RootElement.GetProperty("y").GetDouble();
        await workspace.CoreWebView2.CallDevToolsProtocolMethodAsync("Input.dispatchMouseEvent", JsonSerializer.Serialize(new { type="mouseWheel", x, y, deltaX=0, deltaY=1100 }));
        await Until(async () => await Js("state.libraryQuickLookPage >= 2 && document.querySelector('.windows-pdf-body').scrollTop > 500") == "true");
        await AssertJs("state.libraryQuickLookPage >= 2", "wheel continuously scrolls into next page");
        await Js("window.__pdfWidth=document.querySelector('.windows-pdf-sheet').getBoundingClientRect().width; window.__workspaceWidth=document.documentElement.clientWidth");
        await workspace.CoreWebView2.CallDevToolsProtocolMethodAsync("Input.dispatchMouseEvent", JsonSerializer.Serialize(new { type="mouseWheel", x, y, deltaX=0, deltaY=-45, modifiers=2 }));
        await Until(async () => await Js("document.querySelector('.windows-pdf-sheet').getBoundingClientRect().width > __pdfWidth * 1.3") == "true");
        await AssertJs("document.documentElement.clientWidth === __workspaceWidth", "Ctrl-wheel pinch zoom changes PDF only");
        await Js("window.__horizontal=document.querySelector('.windows-pdf-body').scrollLeft");
        await workspace.CoreWebView2.CallDevToolsProtocolMethodAsync("Input.dispatchMouseEvent", JsonSerializer.Serialize(new { type="mouseWheel", x, y, deltaX=120, deltaY=0 }));
        await Until(async () => await Js("document.querySelector('.windows-pdf-body').scrollLeft > __horizontal") == "true");
        await AssertJs("document.querySelector('.windows-pdf-body').scrollLeft > __horizontal", "horizontal wheel pans enlarged PDF");
        // Page 240 verifies that continuous layout retains all document pages.
        await Js("gewuWindowsPdf.page(240)");
        await Until(async () => await Js("!!document.querySelector('.windows-pdf-sheet[data-page=\"240\"] img')") == "true");
        await AssertJs("state.libraryQuickLookPageCount === 240", "240-page document navigation");
        await AssertJs("document.querySelectorAll('.windows-pdf-body img').length < 12", "offscreen page pixels released");
        await Js("for(let n=0;n<20;n++) quickLookLibraryPdf({merged_pdf_path:__files[n%2].path}); quickLookLibraryFile({native_file_path:__files[2].path})");
        await Until(async () => await Js("!!document.querySelector('.library-file-preview.markdown strong')") == "true");
        await AssertJs("!document.querySelector('.windows-pdf-reader') && state.libraryQuickLookPath === __files[2].path", "stale PDF requests cannot replace Markdown");
        await Js("quickLookLibraryFile({native_file_path:__files[4].path})");
        await Until(async () => await Js("document.querySelector('.library-file-preview.image img')?.naturalWidth === 640") == "true");
        await AssertJs("state.libraryQuickLookPath === __files[4].path", "image attachment renders without supplied MIME metadata");
        await Js("closeLibraryQuickLook({restoreFocus:true})");
        await AssertJs("!state.libraryQuickLookOpen", "preview close");
    }

    static async Task TestCapture()
    {
        await Js("window.__captureEvents=[]; window.__originalBrowserEvent=window.gewuBrowserNativeEvent; window.gewuBrowserNativeEvent=e=>{if(e.event.startsWith('capture-')) __captureEvents.push(e); else __originalBrowserEvent(e)}");
        await Call("OpenPageAsync", "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf", true, "");
        await Until(async () => {
            var page = (BrowserPage?)typeof(WorkspaceWindow).GetField("selected", Private)!.GetValue(form);
            return page is { Loading:false, Home:false } && page.Url.Contains("dummy.pdf");
        }, 60);
        using var capture = JsonDocument.Parse("{\"request_id\":\"native-acceptance\"}");
        await Call("CaptureArticleAsync", capture.RootElement);
        await AssertJs("!!__captureEvents.find(e=>e.event==='capture-metadata')?.snapshot", "native PDF metadata snapshot");
        await Js("window.__review=null; fetch('/api/browser',{method:'POST',headers:{'Content-Type':'application/json','X-Gewu-Browser':'1'},body:JSON.stringify({action:'capture_begin',snapshot:__captureEvents.find(e=>e.snapshot).snapshot})}).then(r=>r.json()).then(r=>window.__review=r)");
        await Until(async () => await Js("!!__review") == "true");
        string data = await Js("JSON.stringify(__review)");
        using var review = JsonDocument.Parse(JsonSerializer.Deserialize<string>(data)!);
        var r = review.RootElement;
        if (!r.TryGetProperty("token", out var token)) throw new Exception("Capture review response: " + r.GetRawText());
        string snapshotId = r.GetProperty("snapshot").GetProperty("snapshot_id").GetString()!;
        using var download = JsonDocument.Parse(JsonSerializer.Serialize(new { token = token.GetString(), upload_token = r.GetProperty("upload_token").GetString(), snapshot_id = snapshotId, url = r.GetProperty("snapshot").GetProperty("pdf_urls")[0].GetString() }));
        await Call("CapturePdfAsync", download.RootElement);
        await AssertJs("__captureEvents.some(e=>e.event==='capture-pdf' && !e.error)", "native session PDF retrieval and loopback upload");
        await Js("window.__ready=null; fetch('/api/browser',{method:'POST',headers:{'Content-Type':'application/json','X-Gewu-Browser':'1'},body:JSON.stringify({action:'capture_review',token:__review.token})}).then(r=>r.json()).then(r=>window.__ready=r)");
        await Until(async () => await Js("!!__ready") == "true");
        await AssertJs("__ready.pdf_ready === true", "backend confirms readable PDF staged");
        await Js("fetch('/api/browser',{method:'POST',headers:{'Content-Type':'application/json','X-Gewu-Browser':'1'},body:JSON.stringify({action:'capture_cancel',token:__review.token})})");
    }
}
