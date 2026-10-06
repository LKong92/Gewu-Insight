using System.Text.Json;

namespace GewuInsight.Windows;

internal sealed partial class WorkspaceWindow
{
    bool fileDragging;
    long pendingLibraryItem;
    string activeDragId = "";
    long activeDragItem;
    bool activeItemHandled;
    JsonElement? activeDragPayload;
    int dragArmGeneration;

    void ArmLibraryItemDrag(JsonElement payload)
    {
        pendingLibraryItem = payload.TryGetProperty("item_id", out var item) && item.TryGetInt64(out long id) && id > 0 ? id : 0;
    }

    void StartFileDrag(JsonElement payload)
    {
        string path = TextValue(payload, "path");
        string cleanup = TextValue(payload, "cleanup_path");
        JsonElement? managed = payload.TryGetProperty("library_payload", out var libraryPayload) && libraryPayload.ValueKind == JsonValueKind.Object ? libraryPayload.Clone() : null;
        long item = pendingLibraryItem; pendingLibraryItem = 0;
        int generation = ++dragArmGeneration;
        Point start = Cursor.Position;
        // OLE starts a nested message loop. Leave WebMessageReceived before
        // entering it: WebView2 event callbacks do not support reentrancy.
        BeginInvoke(new Action(async () => {
            try {
                // Folder handles intentionally have no HTML dragstart. Arm on
                // mousedown, then start OLE only after the Windows threshold.
                while (!stopping && generation == dragArmGeneration && (Control.MouseButtons & MouseButtons.Left) != 0) {
                    var point = Cursor.Position;
                    if (Math.Abs(point.X - start.X) >= SystemInformation.DragSize.Width / 2 || Math.Abs(point.Y - start.Y) >= SystemInformation.DragSize.Height / 2) {
                        await DragFileAsync(path, item, managed); break;
                    }
                    await Task.Delay(20);
                }
            }
            catch (Exception error) { await EmitAsync(new { @event = "error", message = error.Message }); }
            finally { if (cleanup.Length > 0) _ = CleanupFolderDragAsync(path, cleanup); }
        }));
    }

    static DataObject? FileDragData(string path)
    {
        if (!Path.IsPathFullyQualified(path) || (!File.Exists(path) && !Directory.Exists(path))) return null;
        path = Path.GetFullPath(path);
        FileSystemInfo file = Directory.Exists(path) ? new DirectoryInfo(path) : new FileInfo(path);
        if (file.LinkTarget != null) path = file.ResolveLinkTarget(true)?.FullName ?? path;
        if (Path.GetExtension(path).Equals(".lnk", StringComparison.OrdinalIgnoreCase)) return null;
        // OLE CF_HDROP supports Explorer and applications. Copy is the only
        // offered effect, so a destination cannot move/delete the owned file.
        var data = new DataObject();
        data.SetFileDropList(new System.Collections.Specialized.StringCollection { path });
        return data;
    }

    async Task DragFileAsync(string path, long item, JsonElement? managed = null)
    {
        if (fileDragging || stopping || (Control.MouseButtons & MouseButtons.Left) == 0) return;
        var data = FileDragData(path);
        if (data == null) return;
        activeDragId = Guid.NewGuid().ToString("N"); activeDragItem = item; activeItemHandled = false; activeDragPayload = managed;
        await WorkspaceScriptAsync("window.gewuNativeDragId=" + JsonSerializer.Serialize(activeDragId));
        if (stopping || (Control.MouseButtons & MouseButtons.Left) == 0) return;
        fileDragging = true;
        try { workspace.DoDragDrop(data, DragDropEffects.Copy); }
        finally {
            fileDragging = false;
            // Keep the completed ID until the next drag so queued WebView drop
            // messages cannot fall through to a second external-file import.
            await WorkspaceScriptAsync("window.gewuNativeDragId='';window.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}));");
        }
    }

    async Task<bool> HandleLibraryItemFileDropAsync(JsonElement payload)
    {
        string id = TextValue(payload, "drag_id");
        if (id.Length == 0 || id != activeDragId || (activeDragItem <= 0 && activeDragPayload == null)) return false;
        if (activeItemHandled) return true;
        activeItemHandled = true;
        double x = payload.GetProperty("x").GetDouble(), y = payload.GetProperty("y").GetDouble();
        if (!double.IsFinite(x) || !double.IsFinite(y)) return true;
        if (activeDragPayload is JsonElement resource) {
            await WorkspaceScriptAsync("window.handleNativeLibraryManagedDrop?.(" + resource.GetRawText() + "," + JsonSerializer.Serialize(new { x, y }) + ")"); return true;
        }
        await WorkspaceScriptAsync("window.handleNativeLibraryItemDrop?.(" + activeDragItem + "," + JsonSerializer.Serialize(new { x, y }) + ")");
        return true;
    }

    static bool SafeFolderDragCleanup(string path, string cleanup)
    {
        if (!Path.IsPathFullyQualified(path) || !Path.IsPathFullyQualified(cleanup)) return false;
        string root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(cleanup));
        string temp = Path.TrimEndingDirectorySeparator(Path.GetFullPath(Path.GetTempPath()));
        if (!string.Equals(Path.GetDirectoryName(root), temp, StringComparison.OrdinalIgnoreCase) ||
            !Path.GetFileName(root).StartsWith("daiqo-folder-drag-", StringComparison.Ordinal) ||
            !string.Equals(Path.GetDirectoryName(Path.GetFullPath(path)), root, StringComparison.OrdinalIgnoreCase) || !Directory.Exists(root)) return false;
        // Never recursively follow a replaced export folder/junction.
        var pending = new Stack<DirectoryInfo>(); pending.Push(new DirectoryInfo(root));
        while (pending.Count > 0) {
            var directory = pending.Pop();
            if ((directory.Attributes & FileAttributes.ReparsePoint) != 0) return false;
            foreach (var child in directory.EnumerateFileSystemInfos()) {
                if ((child.Attributes & FileAttributes.ReparsePoint) != 0) return false;
                if (child is DirectoryInfo subdirectory) pending.Push(subdirectory);
            }
        }
        return true;
    }

    static async Task CleanupFolderDragAsync(string path, string cleanup)
    {
        // Allow Shell receivers to finish reading their copy. The only deletion
        // target is the backend's temporary export, never a Library directory.
        await Task.Delay(TimeSpan.FromSeconds(60));
        try { if (SafeFolderDragCleanup(path, cleanup)) Directory.Delete(Path.GetFullPath(cleanup), true); }
        catch (IOException) { } catch (UnauthorizedAccessException) { }
    }

    void DismissMenus()
    {
        if (MainMenuStrip == null) return;
        foreach (ToolStripMenuItem item in MainMenuStrip.Items)
            if (item.DropDown.Visible) item.HideDropDown();
    }

    async Task ChoosePathAsync(JsonElement payload, Microsoft.Web.WebView2.WinForms.WebView2? sourceView = null, Form? owner = null)
    {
        var view = sourceView ?? workspace;
        var parent = owner ?? this;
        string session = workspaceToken;
        async Task Reply(object result) {
            if (session == workspaceToken && !view.IsDisposed && view.CoreWebView2 != null && Trusted(view.CoreWebView2.Source))
                await view.CoreWebView2.ExecuteScriptAsync("window.gewuPathChosen(" + JsonSerializer.Serialize(result) + ")");
        }
        string requestId = TextValue(payload, "request_id");
        string kind = TextValue(payload, "kind");
        string path = "";
        DismissMenus();
        if (kind == "folder") {
            using var dialog = new FolderBrowserDialog { Description = "Choose a folder to import", UseDescriptionForTitle = true, ShowNewFolderButton = false };
            if (dialog.ShowDialog(parent) == DialogResult.OK) path = dialog.SelectedPath;
        } else if (kind == "loader-report") {
            using var dialog = new OpenFileDialog { Title = "Choose a Loader report", Filter = "Loader reports|*.json", InitialDirectory = Path.Combine(dataRoot, "reports", "imports") };
            if (dialog.ShowDialog(parent) == DialogResult.OK) path = dialog.FileName;
        } else {
            await Reply(new { request_id = requestId, error = "Unsupported file dialog" });
            return;
        }
        await Reply(new { request_id = requestId, path, cancelled = path.Length == 0 });
    }
}
