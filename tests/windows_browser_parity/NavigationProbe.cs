using System.Text.Json;
using Microsoft.Web.WebView2.Core;

namespace GewuInsight.Windows;

internal sealed partial class WorkspaceWindow
{
    async Task CheckNavigationAsync(BrowserPage page, string fixtures)
    {
        var core = page.View!.CoreWebView2;
        await Until(() => !page.Home && !page.Loading && page.History.Count >= 2);
        Check(page.History[0].NativeId == null, "first webpage has a local Home back entry");
        await core.ExecuteScriptAsync("document.getElementById('draft').value='retained at Home'");
        int count = page.History.Count;
        await TraverseHistoryAsync(page, -1);
        Check(page.Home && !page.View.Visible && page.HistoryIndex == 0, "Back from first document shows local Home");
        await TraverseHistoryAsync(page, 1);
        await Until(() => !page.Home);
        Check(await core.ExecuteScriptAsync("document.getElementById('draft').value") == "\"retained at Home\"", "Forward from Home reuses the retained native document and draft");
        Check(page.History.Count == count, "Home traversal does not add duplicate history");
        await OpenPageAsync("", false);
        Check(page.Home && page.HistoryIndex == page.History.Count - 1, "Home button records a local forward entry");
        await TraverseHistoryAsync(page, -1);
        await Until(() => !page.Home);
        Check(await core.ExecuteScriptAsync("document.getElementById('draft').value") == "\"retained at Home\"", "Back from explicit Home also preserves the unsent draft");
        await core.ExecuteScriptAsync("history.pushState({},'', '#chapter')");
        await Until(() => page.Url.EndsWith("#chapter"));
        Check(page.HistoryIndex == page.History.Count - 1, "new same-document navigation prunes the abandoned Home forward branch");
        await TraverseHistoryAsync(page, -1);
        await Until(() => !page.Url.Contains('#'));
        Check(await core.ExecuteScriptAsync("document.getElementById('draft').value") == "\"retained at Home\"", "same-document Back uses browser-owned history");
        await OpenPageAsync("", false);
        var delay = new TaskCompletionSource<bool>();
        async void Delayed(object? sender, CoreWebView2WebResourceRequestedEventArgs args) {
            if (!args.Request.Uri.EndsWith("/delayed.html")) return;
            using var deferral = args.GetDeferral();
            await delay.Task;
            args.Response = remoteEnvironment!.CreateWebResourceResponse(new MemoryStream(System.Text.Encoding.UTF8.GetBytes("<title>Late response</title>late")), 200, "OK", "Content-Type: text/html");
        }
        core.WebResourceRequested += Delayed;
        await OpenPageAsync("https://parity.example/delayed.html", false);
        await Until(() => page.Loading);
        Check(page.Home && !page.View.Visible, "pending Home departure keeps Favorites and hides the retained old document");
        StopNavigation(page); delay.SetResult(true);
        await Task.Delay(250);
        Check(page.Home && !page.Loading && !page.View.Visible, "Stop and a late response cannot reveal a cancelled Home departure");
        core.WebResourceRequested -= Delayed;
        await TraverseHistoryAsync(page, -1);
        await Until(() => !page.Home);
        Check(await core.ExecuteScriptAsync("document.getElementById('draft').value") == "\"retained at Home\"", "cancelled Home departure preserves the preceding real document");
        await core.ExecuteScriptAsync("document.getElementById('draft').focus()");
        Check(!await BrowserAtEdgeAsync(page, "up"), "isolated edge probe leaves editable fields in the webpage");
        await core.ExecuteScriptAsync("document.getElementById('draft').blur(); window.scrollTo(0,0)");
        Check(await BrowserAtEdgeAsync(page, "up"), "isolated probe recognizes the document top boundary");
        Check(BrowserKeyAction(Keys.Control | Keys.Shift | Keys.L) == "" && BrowserKeyAction(Keys.Alt | Keys.Left) == "", "unrelated modifiers and native page navigation shortcuts remain unclaimed");
        await Until(() => browserVisible && page.View.Visible);
        SetActiveWindow(Handle); SendMessage(Handle, 0x6, (IntPtr)1, IntPtr.Zero);
        ActiveControl = page.View; SetFocus(page.View.Handle); page.View.Focus(); await Task.Delay(100);
        Check(BrowserKeyContext(page), "native key routing only activates for the visible focused Browser page: " + JsonSerializer.Serialize(new { active = Form.ActiveForm == this, Enabled, browserActive, browserVisible, focused = page.View.ContainsFocus, visible = page.View.Visible }));
        // Win32 key messages to the real WinForms control on its own desktop,
        // with no document key listener or input sent to the user's desktop.
        DispatchBrowserKey(page, Keys.L);
        await UntilJS("document.activeElement.id==='browserAddress'");
        Check(true, "native Ctrl+L reaches the trusted address field from a remote webpage");
        ActiveControl = page.View; SetFocus(page.View.Handle); page.View.Focus(); await Task.Delay(100);
        Check(BrowserKeyContext(page), "refocusing the native webpage restores keyboard routing");
        DispatchBrowserKey(page, Keys.F);
        await UntilJS("document.activeElement.id==='browserFindInput'");
        Check(true, "native Ctrl+F opens the shared Find bar from the webpage");
        await workspace.CoreWebView2.ExecuteScriptAsync("document.getElementById('browserFindClose').click()");
        await OpenPageAsync("https://parity.example/article.html", false);
        await Until(() => !page.Loading && page.Title == "Parity article");
        await CheckPopupAndReturnAsync(page, fixtures);
    }

    async Task CheckPopupAndReturnAsync(BrowserPage original, string fixtures)
    {
        string posted = "";
        void Added(object? sender, ControlEventArgs args) {
            if (args.Control is not Microsoft.Web.WebView2.WinForms.WebView2 view) return;
            view.CoreWebView2InitializationCompleted += (_, e) => {
                if (!e.IsSuccess) return;
                view.CoreWebView2.SetVirtualHostNameToFolderMapping("parity.example", fixtures, CoreWebView2HostResourceAccessKind.DenyCors);
                view.CoreWebView2.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
                view.CoreWebView2.WebResourceRequested += (_, request) => {
                    if (!request.Request.Uri.EndsWith("/post-result")) return;
                    using var reader = new StreamReader(request.Request.Content);
                    posted = request.Request.Method + ":" + reader.ReadToEnd();
                    request.Response = remoteEnvironment!.CreateWebResourceResponse(new MemoryStream(System.Text.Encoding.UTF8.GetBytes("<title>Posted popup</title>POST retained")), 200, "OK", "Content-Type: text/html");
                };
            };
        }
        ControlAdded += Added;
        try {
            var core = original.View!.CoreWebView2;
            await core.ExecuteScriptAsync("window.open('https://parity.example/second.html','_blank','opener')");
            await Until(() => selected != original && selected?.Title == "Second article" && selected?.Loading == false);
            var popup = selected!;
            Check(await popup.View!.CoreWebView2.ExecuteScriptAsync("window.opener!==null") == "true", "native popup preserves the browser-owned opener relationship");
            await ClosePageAsync(popup.Id);
            // Virtual-folder mapping is GET-only; generate this POST response
            // through the test view's request handler on a separate hostname.
            await core.ExecuteScriptAsync("const f=document.createElement('form'); f.method='POST'; f.target='_blank'; f.action='https://post.parity.example/post-result'; const i=document.createElement('input'); i.name='draft'; i.value='body retained'; f.append(i); document.body.append(f); f.submit()");
            await Until(() => selected != original && selected?.Title == "Posted popup" && selected?.Loading == false);
            Check(posted == "POST:draft=body+retained", "popup form keeps its original POST body instead of becoming a GET");
            await ClosePageAsync(selected!.Id);
            await workspace.CoreWebView2.ExecuteScriptAsync("document.getElementById('libraryMode').click()");
            await UntilJS("state.mode==='library'");
            await workspace.CoreWebView2.ExecuteScriptAsync("window.gewuBrowser.openURL('https://parity.example/second.html')");
            await Until(() => selected != original && selected?.Title == "Second article" && selected?.Loading == false && canReturnToWorkspace && browserVisible);
            var detour = selected!;
            SetActiveWindow(Handle); ActiveControl = detour.View; SetFocus(detour.View!.Handle); detour.View.Focus();
            DispatchBrowserKey(detour, Keys.OemOpenBrackets);
            await UntilJS("state.mode==='library'");
            Check(!canReturnToWorkspace && pages.Contains(detour), "native Ctrl+[ returns to the source Library while preserving the webpage tab");
            await workspace.CoreWebView2.ExecuteScriptAsync("document.getElementById('browserMode').click()");
            await Until(() => browserActive);
            await ClosePageAsync(detour.Id);
            Check(selected == original, "closing popup and research-detour tabs returns to the retained original tab");
        } finally { ControlAdded -= Added; }
    }

    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern bool GetKeyboardState(byte[] state);
    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern IntPtr SetActiveWindow(IntPtr handle);
    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern IntPtr SetFocus(IntPtr handle);
    [System.Runtime.InteropServices.DllImport("user32.dll")] static extern bool SetKeyboardState(byte[] state);
    static void DispatchBrowserKey(BrowserPage page, Keys key)
    {
        byte[] before = new byte[256]; GetKeyboardState(before);
        byte[] held = (byte[])before.Clone(); held[(int)Keys.ControlKey] = 0x80;
        try { SetKeyboardState(held); SendMessage(page.View!.Handle, 0x100, (IntPtr)(int)key, (IntPtr)1); }
        finally { SetKeyboardState(before); }
    }
}
