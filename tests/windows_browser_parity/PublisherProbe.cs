using System.Diagnostics;
using System.Text;
using System.Text.Json;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace GewuInsight.Windows;

internal sealed partial class WorkspaceWindow
{
    async Task FixturePython(string code)
    {
        var info = new ProcessStartInfo(python) { WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true, RedirectStandardError = true, RedirectStandardOutput = true };
        info.ArgumentList.Add("-c"); info.ArgumentList.Add(code); info.ArgumentList.Add(dataRoot);
        using var process = Process.Start(info)!;
        string error = await process.StandardError.ReadToEndAsync();
        await process.WaitForExitAsync();
        if (process.ExitCode != 0) throw new Exception(error);
    }

    async Task CheckPublisherAndDragAsync()
    {
        await FixturePython("""
            import sys
            from pathlib import Path
            from pypdf import PdfWriter
            from paper_monitor.storage import Storage
            root=Path(sys.argv[1]); writer=PdfWriter(); writer.add_blank_page(width=400,height=600)
            writer.add_metadata({'/Subject':'Synthetic publisher parity'}); writer.write(root/'publisher.pdf')
            db=Storage(root/'data/paper_monitor.sqlite')
            db.upsert_paper({'paper_id':'publisher-fixture','title':'Synthetic publisher parity','journal':'Fixture Journal','source':'fixture','raw':{}})
            db.close()
            """);
        byte[] pdf = await File.ReadAllBytesAsync(Path.Combine(dataRoot, "publisher.pdf"));
        await WorkspaceScriptAsync("window.__publisherReplies=[];const oldPublisher=window.handleNativePublisherDownloadResult;window.handleNativePublisherDownloadResult=p=>{window.__publisherReplies.push(p);oldPublisher(p)}");
        string scenario = "direct";
        var requests = new List<string>(); bool leakedToken = false;
        ControlEventHandler hook = (_, args) => {
            if (args.Control is not WebView2 view) return;
            view.CoreWebView2InitializationCompleted += (_, e) => {
                if (!e.IsSuccess) return;
                var core = view.CoreWebView2;
                core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
                core.WebResourceRequested += (_, resource) => {
                    requests.Add(resource.Request.Uri); leakedToken |= resource.Request.Headers.Contains("X-Gewu-Workspace");
                    int status = 200; string mime = "application/pdf", headers = ""; byte[] bytes = pdf;
                    string path = new Uri(resource.Request.Uri).AbsolutePath;
                    if (path.EndsWith("/landing")) {
                        mime = "text/html";
                        string body = scenario == "discovery" ? "<a href='/supplement.pdf'>Supporting Information PDF</a><a href='https://unverified.example/supplement.pdf'>Supplement PDF</a>" : "<meta name='citation_pdf_url' content='/main.pdf'>";
                        bytes = Encoding.UTF8.GetBytes("<!doctype html><title>Fixture</title>" + body);
                    }
                    if (scenario == "blocked") { status = 302; headers = "Location: https://unverified.example/paper.pdf\r\n"; }
                    if (scenario == "invalid") bytes = Encoding.UTF8.GetBytes("not a readable PDF");
                    headers += "Content-Type: " + mime + "\r\nContent-Length: " + (scenario == "oversized" ? 129L*1024*1024 : bytes.Length) + "\r\n";
                    resource.Response = remoteEnvironment!.CreateWebResourceResponse(new MemoryStream(bytes), status, status == 200 ? "OK" : "Found", headers);
                };
            };
        };
        ControlAdded += hook;
        try {
            int count = 0;
            foreach (string value in new[] { "direct", "landing", "discovery", "supplement", "blocked", "invalid", "oversized" }) {
                scenario = value; requests.Clear(); leakedToken = false;
                string kind = scenario == "discovery" ? "publisher-supplement-discovery" : scenario == "supplement" ? "publisher-supplement-file" : "publisher-main-pdf";
                string url = "https://journals.aps.org/" + (scenario is "landing" or "discovery" ? "landing" : "main.pdf");
                using var command = Command(new { token = Guid.NewGuid().ToString("N"), url, context = new { paper_id = "publisher-fixture", publisher_download_kind = kind, publisher_download_name = "aps", publisher_download_referer = "https://journals.aps.org/article" } });
                await WorkspaceScriptAsync("window.webkit.messageHandlers.publisherPdfDownload.postMessage(" + command.RootElement.GetRawText() + ")");
                await UntilJS("window.__publisherReplies.length===" + (++count), 35);
                await Until(() => !publisherDownloading);
                using var result = JsonDocument.Parse(await workspace.CoreWebView2.ExecuteScriptAsync("window.__publisherReplies.at(-1)"));
                bool success = result.RootElement.GetProperty("success").GetBoolean();
                Check(success == (scenario is "direct" or "landing" or "discovery" or "supplement"), "publisher bridge and backend outcome: " + scenario + " " + TextValue(result.RootElement, "error"));
                Check(!leakedToken, "publisher Browser requests exclude workspace authentication: " + scenario);
                if (scenario == "landing") Check(requests.Any(u => u.EndsWith("/main.pdf")), "rendered publisher metadata reaches the original PDF response");
                if (scenario == "landing") await FixturePython("""
                    import sys
                    from pathlib import Path
                    from paper_monitor.storage import Storage
                    root=Path(sys.argv[1]); db=Storage(root/'data/paper_monitor.sqlite'); rows=db.list_paper_resources('publisher-fixture')
                    assert len(rows)==1 and Path(db.resource_local_path(rows[0])).read_bytes()==(root/'publisher.pdf').read_bytes()
                    assert rows[0]['file_type']=='published_version'; db.close()
                    """);
                if (scenario == "discovery") Check(result.RootElement.GetProperty("data").GetProperty("supplement_urls").GetArrayLength() == 1, "supplement discovery filters unverified links");
                if (scenario == "blocked") Check(requests.Count == 1, "unverified publisher redirect is rejected before contacting target");
                Check(!Directory.EnumerateDirectories(Path.GetTempPath(), "gewu-publisher-*").Any(), "publisher temporary response is removed: " + scenario);
            }
        } finally { ControlAdded -= hook; }
        await FixturePython("""
            import sys
            from pathlib import Path
            from paper_monitor.storage import Storage
            from pypdf import PdfReader
            root=Path(sys.argv[1]); db=Storage(root/'data/paper_monitor.sqlite')
            rows=db.list_paper_resources('publisher-fixture')
            assert len(rows)==1, len(rows)
            pages=PdfReader(db.resource_local_path(rows[0])).pages
            assert len(pages)==2 and all(tuple(p.mediabox)==(0,0,400,600) for p in pages)
            assert db.conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert not db.conn.execute('PRAGMA foreign_key_check').fetchall()
            db.close()
            """);
        Check(true, "main download deduplicates; existing supplementary merge yields two intact pages and rejected responses preserve SQLite integrity");

        string folder = Path.Combine(Path.GetTempPath(), "daiqo-folder-drag-" + Guid.NewGuid().ToString("N"));
        string exported = Path.Combine(folder, "Research"); Directory.CreateDirectory(exported);
        await File.WriteAllTextAsync(Path.Combine(exported, "note.md"), "# Synthetic copy");
        Check(FileDragData(exported)!.GetFileDropList()![0] == exported, "OLE CF_HDROP contains a real folder export");
        Check(FileDragData(Path.Combine(exported, "note.md"))!.GetFileDropList()!.Count == 1, "single-file CF_HDROP remains supported");
        Check(FileDragData("relative.pdf") == null && FileDragData(Path.Combine(exported, "missing.pdf")) == null, "native drag rejects relative and missing paths");
        Check(SafeFolderDragCleanup(exported, folder) && !SafeFolderDragCleanup(dataRoot, dataRoot) && !SafeFolderDragCleanup(exported, Path.GetTempPath()), "cleanup accepts only the exact temporary folder export");
        await WorkspaceScriptAsync("window.__itemDrops=[];window.__oldItemDrop=window.handleNativeLibraryItemDrop;window.handleNativeLibraryItemDrop=(id,p)=>window.__itemDrops.push({id,p})");
        activeDragId = "fixture-drag"; activeDragItem = 42; activeItemHandled = false;
        using (var point = Command(new { drag_id = activeDragId, x = 300, y = 200 })) {
            Check(await HandleLibraryItemFileDropAsync(point.RootElement), "native self-drop uses Library item relay");
            Check(await HandleLibraryItemFileDropAsync(point.RootElement), "duplicate native self-drop is consumed without external import");
        }
        Check(await workspace.CoreWebView2.ExecuteScriptAsync("window.__itemDrops.length===1 && window.__itemDrops[0].id===42 && window.__itemDrops[0].p.x===300") == "true", "one native item drop reaches shared Paper Files handler with CSS coordinates");
        using (var point = Command(new { x = 1, y = 1 })) Check(!await HandleLibraryItemFileDropAsync(point.RootElement), "external files retain the standard import path");
        await WorkspaceScriptAsync("window.handleNativeLibraryItemDrop=window.__oldItemDrop");
        activeDragId = ""; activeDragItem = 0;
        if (SafeFolderDragCleanup(exported, folder)) Directory.Delete(folder, true);
    }
}
