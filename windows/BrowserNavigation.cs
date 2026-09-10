using System.Text.Json;
using Microsoft.Web.WebView2.Core;

namespace GewuInsight.Windows;

// Home is a local entry. Remote entries refer to Chromium's own history IDs,
// never reconstructed GETs, so POST bodies and native document sessions remain
// owned by the browser. Everything here is discarded with its tab.
internal sealed record BrowserHistoryEntry(int? NativeId, string Url = "", string Title = "Home");

internal sealed partial class WorkspaceWindow
{
    async Task SyncNavigationAsync(BrowserPage page)
    {
        if (page.View?.CoreWebView2 == null || (page.Home && !page.DepartingHome)) return;
        int generation = page.Generation;
        var core = page.View.CoreWebView2;
        using var history = JsonDocument.Parse(await core.CallDevToolsProtocolMethodAsync("Page.getNavigationHistory", "{}"));
        if (!pages.Contains(page) || generation != page.Generation || (page.Home && !page.DepartingHome)) return;
        var items = history.RootElement.GetProperty("entries");
        int current = history.RootElement.GetProperty("currentIndex").GetInt32();
        if (current < 0 || current >= items.GetArrayLength()) return;
        var item = items[current];
        string url = TextValue(item, "url");
        if (!PublicUrl(url)) return;
        int id = item.GetProperty("id").GetInt32();
        var entry = new BrowserHistoryEntry(id, url, core.DocumentTitle);
        int target = page.HistoryTarget ?? -1;
        if (target >= 0 && target < page.History.Count && page.History[target].NativeId == id) {
            page.HistoryIndex = target;
        } else if (page.History[page.HistoryIndex].NativeId != id) {
            int existing = page.History.FindLastIndex(e => e.NativeId == id);
            if (existing >= 0 && !page.DepartingHome) page.HistoryIndex = existing;
            else {
                page.History.RemoveRange(page.HistoryIndex + 1, page.History.Count - page.HistoryIndex - 1);
                page.History.Add(entry); page.HistoryIndex++;
            }
        }
        page.History[page.HistoryIndex] = entry;
        // Discard references Chromium has itself evicted, without replaying URLs.
        var retained = items.EnumerateArray().Select(e => e.GetProperty("id").GetInt32()).ToHashSet();
        for (int i = page.History.Count - 1; i >= 0; i--) {
            if (i == page.HistoryIndex || page.History[i].NativeId is not int native || retained.Contains(native)) continue;
            page.History.RemoveAt(i); if (i < page.HistoryIndex) page.HistoryIndex--;
        }
        if (page.History.Count > 256) {
            int oldest = Math.Min(page.History.Count - 256, page.HistoryIndex);
            page.History.RemoveRange(0, oldest); page.HistoryIndex -= oldest;
            if (page.History.Count > 256) page.History.RemoveRange(256, page.History.Count - 256);
        }
        page.HistoryTarget = null; page.DepartingHome = false; page.Home = false;
        page.Url = url; page.Title = core.DocumentTitle;
        LayoutBrowser(); await SendStateAsync();
    }

    void StopNavigation(BrowserPage page)
    {
        page.Generation++; page.ActiveNavigation = 0; page.DepartingHome = false;
        page.HistoryTarget = null; page.Loading = false;
        page.View?.CoreWebView2?.Stop();
    }

    async Task ShowHomeAsync(BrowserPage page)
    {
        if (!page.Home) await SyncNavigationAsync(page);
        StopNavigation(page);
        if (!page.Home) {
            page.History.RemoveRange(page.HistoryIndex + 1, page.History.Count - page.HistoryIndex - 1);
            page.History.Add(new BrowserHistoryEntry(null)); page.HistoryIndex++;
        }
        page.Home = true; page.Title = "Home"; page.Url = "";
        LayoutBrowser(); await SendStateAsync();
    }

    async Task TraverseHistoryAsync(BrowserPage page, int direction)
    {
        if (!page.Home) await SyncNavigationAsync(page);
        StopNavigation(page);
        int target = page.HistoryIndex + direction;
        if (target < 0 || target >= page.History.Count) { await SendStateAsync(); return; }
        var entry = page.History[target];
        if (entry.NativeId == null) {
            page.HistoryIndex = target; page.Home = true; page.Title = "Home"; page.Url = "";
        } else if (page.View?.CoreWebView2 != null) {
            var core = page.View.CoreWebView2;
            using var history = JsonDocument.Parse(await core.CallDevToolsProtocolMethodAsync("Page.getNavigationHistory", "{}"));
            var items = history.RootElement.GetProperty("entries");
            int current = history.RootElement.GetProperty("currentIndex").GetInt32();
            if (!items.EnumerateArray().Any(e => e.GetProperty("id").GetInt32() == entry.NativeId)) {
                page.History.RemoveAt(target); if (target < page.HistoryIndex) page.HistoryIndex--;
                await SendStateAsync(); return;
            }
            page.HistoryTarget = target; page.DepartingHome = page.Home;
            if (current >= 0 && items[current].GetProperty("id").GetInt32() == entry.NativeId) await SyncNavigationAsync(page);
            else await core.CallDevToolsProtocolMethodAsync("Page.navigateToHistoryEntry", JsonSerializer.Serialize(new { entryId = entry.NativeId }));
        }
        LayoutBrowser(); await SendStateAsync();
    }

    void ConnectNavigation(BrowserPage page)
    {
        var core = page.View!.CoreWebView2;
        core.NavigationStarting += async (_, e) => {
            if (!PublicUrl(e.Uri) || (page.Home && !page.DepartingHome)) { e.Cancel = true; return; }
            page.Generation++; page.ActiveNavigation = e.NavigationId; page.Loading = true;
            await EmitAsync(new { @event = "navigation-start" }); await SendStateAsync();
        };
        core.SourceChanged += async (_, e) => {
            if (e.IsNewDocument) return;
            page.Generation++;
            try { await SyncNavigationAsync(page); }
            catch (Exception error) { if (!stopping && pages.Contains(page)) log?.WriteLine("Browser history: " + error.Message); }
        };
        core.ContentLoading += async (_, e) => {
            if (e.IsErrorPage || e.NavigationId != page.ActiveNavigation) return;
            try { await SyncNavigationAsync(page); }
            catch (Exception error) { if (!stopping && pages.Contains(page)) log?.WriteLine("Browser history: " + error.Message); }
        };
        core.DocumentTitleChanged += async (_, _) => { if (!page.Home) { page.Title = core.DocumentTitle; await SendStateAsync(); } };
        core.NavigationCompleted += async (_, e) => {
            if (!pages.Contains(page) || e.NavigationId != page.ActiveNavigation) return;
            page.Loading = false;
            if (e.IsSuccess) {
                try { await SyncNavigationAsync(page); } catch (Exception error) { log?.WriteLine("Browser history: " + error.Message); }
                if (!page.Home && PublicUrl(page.Url)) await EmitAsync(new { @event = "visit", event_id = Guid.NewGuid().ToString("N"), url = page.Url, title = page.Title });
            } else {
                page.DepartingHome = false; page.HistoryTarget = null;
                if (e.WebErrorStatus != CoreWebView2WebErrorStatus.OperationCanceled && page == selected)
                    await EmitAsync(new { @event = "error", message = "The webpage could not be loaded. Retry the address or return Home." });
            }
            LayoutBrowser(); await SendStateAsync();
        };
    }
}
