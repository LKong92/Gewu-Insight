using System.Text.Json;
using Microsoft.Web.WebView2.Core;

namespace GewuInsight.Windows;

internal sealed partial class WorkspaceWindow
{
    async Task UntilLoaderJS(string expression)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(35));
        while (loaderView?.CoreWebView2 == null || await loaderView.CoreWebView2.ExecuteScriptAsync("Boolean(" + expression + ")") != "true")
            await Task.Delay(50, timeout.Token);
    }

    async Task CheckLoaderAsync()
    {
        await WorkspaceScriptAsync("window.openLibraryLoader()");
        await Until(() => loaderWindow?.Visible == true && openingLoader == null);
        await UntilLoaderJS("document.body.classList.contains('loader-window-body') && state.libraryLoaderOpen");
        var view = loaderView!; var window = loaderWindow!;
        Check(view.CoreWebView2.Profile.ProfilePath == workspace.CoreWebView2.Profile.ProfilePath, "Loader shares only the trusted workspace profile and authentication");
        Check(await workspace.CoreWebView2.ExecuteScriptAsync("!state.libraryLoaderOpen") == "true", "native Loader leaves the main report surface unchanged");
        await view.CoreWebView2.ExecuteScriptAsync("state.libraryImportPath='unsaved-loader-draft'; renderLibraryLoader()");
        window.Close();
        Check(!window.Visible && !window.IsDisposed, "closing Folder Loader hides its live document");
        await ShowLibraryLoaderAsync();
        Check(loaderView == view && await view.CoreWebView2.ExecuteScriptAsync("state.libraryImportPath") == "\"unsaved-loader-draft\"", "reopening Loader retains the unsaved source field");
        await WorkspaceScriptAsync("window.openMetadataRefreshWindow()");
        await UntilLoaderJS("state.libraryTaskMode==='metadata-refresh'");
        Check(true, "main metadata action hands its draft to the independent Loader");
        await WorkspaceScriptAsync("window.openIdentifierRecoveryWindow()");
        await UntilLoaderJS("state.libraryTaskMode==='identifier-recovery'");
        Check(true, "identifier recovery menu shares the native Loader");
        using (var invalid = Command(new { request_id = "loader-only", kind = "unsupported" })) {
            await WorkspaceScriptAsync("window.__mainPathReply=false;window.__mainPathChosen=window.gewuPathChosen;window.gewuPathChosen=()=>window.__mainPathReply=true");
            await view.CoreWebView2.ExecuteScriptAsync("window.__loaderPathReply=null;window.gewuPathChosen=x=>window.__loaderPathReply=x");
            await ChoosePathAsync(invalid.RootElement, view, window);
            Check(await view.CoreWebView2.ExecuteScriptAsync("window.__loaderPathReply.request_id") == "\"loader-only\"" &&
                await workspace.CoreWebView2.ExecuteScriptAsync("window.__mainPathReply") == "false", "native path replies target the requesting Loader only");
            await WorkspaceScriptAsync("window.gewuPathChosen=window.__mainPathChosen");
        }
        string folder = Path.Combine(dataRoot, "loader-input"); Directory.CreateDirectory(folder);
        await File.WriteAllTextAsync(Path.Combine(folder, "Loader fixture.md"), "# 原生 Loader 测试\nOnly a generated reading note.");
        await view.CoreWebView2.ExecuteScriptAsync("applyLibraryImportDraft({source_root:" + JsonSerializer.Serialize(folder) + ",metadata_mode:'skip',target_folder_id:1}); renderLibraryLoader(); runLibraryFolderImport()");
        await UntilLoaderJS("state.libraryImportJob?.status==='completed'");
        Check(true, "independent Loader imports a generated folder with metadata lookup skipped");
        await UntilJS("state.libraryItems.some(x=>x.display_name?.includes('Loader fixture') || x.paper?.title?.includes('Loader fixture'))");
        Check(true, "Loader completion refreshes the main Library through the shared storage signal");
        string messageReceived = "none";
        view.CoreWebView2.WebMessageReceived += (_, e) => messageReceived = e.WebMessageAsJson;
        string closeResult = await view.CoreWebView2.ExecuteScriptAsync("(()=>{try{closeLibraryLoader();return 'sent:'+IS_STANDALONE_LOADER_WINDOW+':'+Boolean(window.webkit?.messageHandlers?.libraryLoaderWindow)}catch(e){return e.message}})()");
        Check(closeResult == "\"sent:true:true\"", "Loader close action dispatches native bridge: " + closeResult);
        await Task.Delay(200);
        Check(messageReceived.Contains("close"), "Loader receives close message: " + messageReceived + "; enabled=" + view.CoreWebView2.Settings.IsWebMessageEnabled);
        await Until(() => !window.Visible);
        Check(!window.IsDisposed, "Loader close bridge keeps the document available");
        await ShowLibraryLoaderAsync();
        string before = view.CoreWebView2.Source;
        view.CoreWebView2.Navigate("https://unverified.example/loader");
        await Task.Delay(200);
        Check(view.CoreWebView2.Source == before, "Loader refuses remote top-level navigation");
        Check(await view.CoreWebView2.ExecuteScriptAsync("typeof closeLibraryLoader") == "\"function\"", "refused navigation retains the local Loader document");
        window.Close();
    }

    async Task CheckMonitorCacheAsync(BrowserPage page)
    {
        string url = new Uri(origin!, "api/file-icon?ext=pdf&cache_probe=" + Guid.NewGuid().ToString("N")).AbsoluteUri;
        async Task<long> ReadIcon() {
            await WorkspaceScriptAsync("window.__cacheRead=false;fetch(" + JsonSerializer.Serialize(url) + ").then(r=>{if(!r.ok)throw Error(r.status);return r.text()}).then(t=>window.__cacheRead=t.includes('<svg'))");
            await UntilJS("window.__cacheRead");
            return long.Parse(await workspace.CoreWebView2.ExecuteScriptAsync("Math.round(performance.getEntriesByName(" + JsonSerializer.Serialize(url) + ").at(-1).transferSize)"));
        }
        long first = await ReadIcon(), cached = await ReadIcon();
        Check(first > 0 && cached == 0, "actual loopback icon response is served from Monitor network cache on repeat");
        await WorkspaceScriptAsync("localStorage.setItem('__cache_fixture','keep'); document.cookie='cache_fixture=keep; path=/'");
        await page.View!.CoreWebView2.ExecuteScriptAsync("localStorage.setItem('__remote_cache_fixture','keep'); document.cookie='remote_fixture=keep; path=/'");
        await ClearMonitorCacheAsync();
        Check(await ReadIcon() > 0, "Clear Monitor Cache forces a fresh request for the previously cached response");
        Check(await workspace.CoreWebView2.ExecuteScriptAsync("localStorage.getItem('__cache_fixture')==='keep' && document.cookie.includes('cache_fixture=keep')") == "true", "Monitor cleanup preserves local storage and workspace cookies");
        Check(page.View.CoreWebView2.Profile.ProfilePath != workspace.CoreWebView2.Profile.ProfilePath &&
            await page.View.CoreWebView2.ExecuteScriptAsync("localStorage.getItem('__remote_cache_fixture')==='keep' && document.cookie.includes('remote_fixture=keep')") == "true", "remote Browser profile and session cookies survive Monitor cleanup");
        using var health = await client.GetAsync(new Uri(origin!, "api/library/bootstrap"));
        Check(health.IsSuccessStatusCode, "Monitor cleanup preserves authenticated SQLite workspace access");
    }
}
