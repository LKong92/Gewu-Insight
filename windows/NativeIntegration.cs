using System.Text.Json;

namespace GewuInsight.Windows;

internal sealed partial class WorkspaceWindow
{
    bool fileDragging;

    void StartFileDrag(JsonElement payload)
    {
        string path = TextValue(payload, "path");
        // OLE starts a nested message loop. Leave WebMessageReceived before
        // entering it: WebView2 event callbacks do not support reentrancy.
        BeginInvoke(new Action(async () => {
            try { DragFile(path); }
            catch (Exception error) { await EmitAsync(new { @event = "error", message = error.Message }); }
        }));
    }

    void DragFile(string path)
    {
        if (fileDragging || stopping || (Control.MouseButtons & MouseButtons.Left) == 0) return;
        if (!Path.IsPathFullyQualified(path) || !File.Exists(path)) return;
        path = Path.GetFullPath(path);
        var file = new FileInfo(path);
        if (file.LinkTarget != null) path = file.ResolveLinkTarget(true)?.FullName ?? path;
        if (Path.GetExtension(path).Equals(".lnk", StringComparison.OrdinalIgnoreCase)) return;
        // OLE CF_HDROP supports Explorer and applications. Copy is the only
        // offered effect, so a destination cannot move/delete the owned file.
        var data = new DataObject();
        data.SetFileDropList(new System.Collections.Specialized.StringCollection { path });
        fileDragging = true;
        try { workspace.DoDragDrop(data, DragDropEffects.Copy); }
        finally { fileDragging = false; _ = WorkspaceScriptAsync("window.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));"); }
    }

    void DismissMenus()
    {
        if (MainMenuStrip == null) return;
        foreach (ToolStripMenuItem item in MainMenuStrip.Items)
            if (item.DropDown.Visible) item.HideDropDown();
    }

    async Task ChoosePathAsync(JsonElement payload)
    {
        string requestId = TextValue(payload, "request_id");
        string kind = TextValue(payload, "kind");
        string path = "";
        DismissMenus();
        if (kind == "folder") {
            using var dialog = new FolderBrowserDialog { Description = "Choose a folder to import", UseDescriptionForTitle = true, ShowNewFolderButton = false };
            if (dialog.ShowDialog(this) == DialogResult.OK) path = dialog.SelectedPath;
        } else if (kind == "loader-report") {
            using var dialog = new OpenFileDialog { Title = "Choose a Loader report", Filter = "Loader reports|*.json", InitialDirectory = Path.Combine(dataRoot, "reports", "imports") };
            if (dialog.ShowDialog(this) == DialogResult.OK) path = dialog.FileName;
        } else {
            await WorkspaceScriptAsync("window.gewuPathChosen(" + JsonSerializer.Serialize(new { request_id = requestId, error = "Unsupported file dialog" }) + ")");
            return;
        }
        await WorkspaceScriptAsync("window.gewuPathChosen(" + JsonSerializer.Serialize(new { request_id = requestId, path, cancelled = path.Length == 0 }) + ")");
    }
}
