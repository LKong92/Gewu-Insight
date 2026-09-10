using System.Text.Json;

namespace GewuInsight.Windows;

internal sealed partial class WorkspaceWindow
{
    bool canReturnToWorkspace;
    bool browserSidebarVisible;
    int browserInputGeneration;
    bool arrowProbePending;

    void ConnectBrowserKeys(BrowserPage page)
    {
        page.View!.KeyDown += (_, e) => {
            int input = ++browserInputGeneration;
            if (!BrowserKeyContext(page)) return;
            string action = BrowserKeyAction(e.KeyData);
            if (action.Length > 0) {
                e.Handled = true; e.SuppressKeyPress = true;
                // WebView2 accelerator delivery can be synchronous. Defer all
                // focus/COM operations until after this callback returns.
                BeginInvoke(new Action(async () => {
                    try { if (BrowserKeyContext(page)) await RunBrowserKeyAsync(page, action); }
                    catch (Exception error) { await EmitAsync(new { @event = "error", message = error.Message }); }
                }));
            } else if (e.Modifiers == Keys.None && (e.KeyCode == Keys.Up || (e.KeyCode == Keys.Left && browserSidebarVisible))) {
                // Dispatch the original arrow unchanged. Only transfer focus
                // when a one-shot isolated geometry check says it hit an edge.
                _ = ConsiderBrowserArrowAsync(page, e.KeyCode == Keys.Up ? "up" : "left", input);
            }
        };
        page.View.MouseDown += (_, _) => browserInputGeneration++;
        page.View.LostFocus += (_, _) => browserInputGeneration++;
    }

    [System.Runtime.InteropServices.DllImport("user32.dll", EntryPoint = "GetActiveWindow")]
    static extern IntPtr BrowserActiveWindow();

    // Use the UI thread's native active window. Form.ActiveForm consults the
    // foreground process and can be null while WebView2 owns native focus.
    bool BrowserKeyContext(BrowserPage page) => !stopping && Enabled && BrowserActiveWindow() == Handle &&
        browserActive && browserVisible && page == selected && !page.Home && page.View?.ContainsFocus == true &&
        !Application.OpenForms.Cast<Form>().Any(form => form != this && form.Modal) &&
        !(MainMenuStrip?.Items.OfType<ToolStripMenuItem>().Any(item => item.DropDown.Visible) ?? false);

    string BrowserKeyAction(Keys keys) => keys switch {
        Keys.Control | Keys.OemOpenBrackets when canReturnToWorkspace => "return-workspace",
        Keys.Control | Keys.L => "focus-address",
        Keys.Control | Keys.D => "bookmark",
        Keys.Control | Keys.F => "find",
        Keys.Control | Keys.T => "new-tab",
        Keys.Control | Keys.W => "close-tab",
        Keys.Control | Keys.R => "reload",
        _ => ""
    };

    async Task RunBrowserKeyAsync(BrowserPage page, string action)
    {
        switch (action) {
            case "new-tab": await OpenPageAsync("", true); workspace.Focus(); return;
            case "close-tab": await ClosePageAsync(page.Id); if (selected?.Home != false) workspace.Focus(); return;
            case "reload": page.View!.Reload(); return;
            case "return-workspace": if (!canReturnToWorkspace) return; canReturnToWorkspace = false; break;
        }
        ActiveControl = workspace; workspace.Focus();
        await EmitAsync(new { @event = action });
    }

    async Task<bool> BrowserAtEdgeAsync(BrowserPage page, string direction)
    {
        var core = page.View!.CoreWebView2;
        using var tree = JsonDocument.Parse(await core.CallDevToolsProtocolMethodAsync("Page.getFrameTree", "{}"));
        string frameId = TextValue(tree.RootElement.GetProperty("frameTree").GetProperty("frame"), "id");
        using var world = JsonDocument.Parse(await core.CallDevToolsProtocolMethodAsync("Page.createIsolatedWorld", JsonSerializer.Serialize(new { frameId, worldName = "GewuBrowserNavigation" })));
        using var script = new StreamReader(typeof(Program).Assembly.GetManifestResourceStream("GewuInsight.Windows.navigation.js")!);
        using var result = JsonDocument.Parse(await core.CallDevToolsProtocolMethodAsync("Runtime.evaluate", JsonSerializer.Serialize(new {
            expression = "(" + script.ReadToEnd() + ")(" + JsonSerializer.Serialize(direction) + ")",
            contextId = world.RootElement.GetProperty("executionContextId").GetInt32(), returnByValue = true
        })));
        return result.RootElement.TryGetProperty("result", out var value) && value.TryGetProperty("value", out var boundary) && boundary.ValueKind == JsonValueKind.True;
    }

    async Task ConsiderBrowserArrowAsync(BrowserPage page, string direction, int input)
    {
        if (arrowProbePending) return;
        arrowProbePending = true;
        int generation = page.Generation;
        long started = Environment.TickCount64;
        try {
            await Task.Delay(25);
            if (!BrowserKeyContext(page) || input != browserInputGeneration) return;
            // Keep a single outstanding probe even if the renderer hangs. A
            // late result cannot transfer focus, and no polling queue grows.
            bool boundary = await BrowserAtEdgeAsync(page, direction);
            if (!boundary || Environment.TickCount64 - started > 1000 || !BrowserKeyContext(page) || page.Generation != generation || input != browserInputGeneration) return;
            ActiveControl = workspace; workspace.Focus();
            await EmitAsync(new { @event = "focus-chrome", destination = direction == "left" ? "sidebar" : "tabs" });
        } catch (Exception) { /* Uncertain/slow pages retain keyboard ownership. */ }
        finally { arrowProbePending = false; }
    }
}
