using System.Text.Json;

namespace GewuInsight.Windows;

internal sealed partial class WorkspaceWindow
{
    sealed record FolderChoice(long Id, string Title) { public override string ToString() => Title; }
    sealed record SourceFolderChoice(string Id, string Title) { public override string ToString() => Title; }
    string bookmarkSourceDirectory = "";

    internal static async Task<object> ReadChromeBookmarkFileAsync(string path)
    {
        var file = new FileInfo(Path.GetFullPath(path));
        const int limit = 10 * 1024 * 1024;
        if (!file.Name.Equals("Bookmarks", StringComparison.OrdinalIgnoreCase) || !file.Exists || file.Length is <= 0 or > limit)
            throw new IOException("Choose Chrome's Bookmarks file, no larger than 10 MB. No other profile files are read.");
        // Read only the explicitly selected file. Never enumerate a profile or
        // open cookies, passwords, history, or another file beside Bookmarks.
        await using var input = new FileStream(file.FullName, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        using var buffer = new MemoryStream();
        var block = new byte[8192]; int count;
        while ((count = await input.ReadAsync(block)) > 0) {
            if (buffer.Length + count > limit) throw new IOException("The selected Bookmarks file exceeds 10 MB.");
            buffer.Write(block, 0, count);
        }
        using var json = JsonDocument.Parse(buffer.ToArray());
        if (!json.RootElement.TryGetProperty("roots", out var roots) || roots.ValueKind != JsonValueKind.Object)
            throw new IOException("Choose a valid Chrome Bookmarks file. HTML exports use Import instead.");
        string identity = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(file.FullName.ToUpperInvariant()))).ToLowerInvariant();
        return new { @event = "bookmark-source", source = "chrome", source_id = identity, content_base64 = Convert.ToBase64String(buffer.ToArray()) };
    }

    async Task ReadBookmarkSourceAsync(JsonElement command)
    {
        if (TextValue(command, "source") != "chrome") {
            await EmitAsync(new { @event = "bookmark-source-cancel", message = "Use an HTML export to import Safari bookmarks on Windows." }); return;
        }
        using var open = new OpenFileDialog { Title = "Choose Chrome Bookmarks — then choose a folder to sync", FileName = "Bookmarks",
            Filter = "Chrome Bookmarks|Bookmarks|All Files|*.*", InitialDirectory = bookmarkSourceDirectory, CheckFileExists = true };
        if (open.ShowDialog(this) != DialogResult.OK) { await EmitAsync(new { @event = "bookmark-source-cancel" }); return; }
        try {
            var result = await ReadChromeBookmarkFileAsync(open.FileName);
            bookmarkSourceDirectory = Path.GetDirectoryName(open.FileName) ?? "";
            await EmitAsync(result);
        } catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException) {
            await EmitAsync(new { @event = "bookmark-source-cancel", message = error.Message });
        }
    }

    async Task ChooseBookmarkSourceFolderAsync(JsonElement command)
    {
        var entries = command.GetProperty("folders");
        if (entries.GetArrayLength() is < 1 or > 2000) {
            await EmitAsync(new { @event = "bookmark-source-cancel", message = "No selectable source folder was found." }); return;
        }
        using var dialog = new Form { Text = "Choose a folder to sync into Gewu", StartPosition = FormStartPosition.CenterParent,
            AutoScaleDimensions = new SizeF(96, 96), AutoScaleMode = AutoScaleMode.Dpi,
            ClientSize = new Size(620, 235), FormBorderStyle = FormBorderStyle.FixedDialog, MaximizeBox = false, MinimizeBox = false };
        var panel = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, Padding = new Padding(18) };
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        panel.Controls.Add(new Label { AutoSize = true, MaximumSize = new Size(580, 0), Text = "Only this folder and its subfolders are included. Repeat Sync from Chrome to refresh. Local edits and source deletions are kept; Chrome is never modified." });
        var choice = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Top, DropDownWidth = 820, AccessibleName = "Source bookmark folder" };
        foreach (var entry in entries.EnumerateArray()) choice.Items.Add(new SourceFolderChoice(TextValue(entry, "id"), TextValue(entry, "title") + " (" + entry.GetProperty("count").GetInt32() + " bookmarks)"));
        choice.SelectedIndex = 0; panel.Controls.Add(choice);
        var buttons = new FlowLayoutPanel { FlowDirection = FlowDirection.RightToLeft, Dock = DockStyle.Fill, AutoSize = true };
        var sync = new Button { Text = "Sync Folder", DialogResult = DialogResult.OK, AutoSize = true, MinimumSize = new Size(105, 32) };
        var cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, AutoSize = true, MinimumSize = new Size(90, 32) };
        buttons.Controls.Add(sync); buttons.Controls.Add(cancel); panel.Controls.Add(buttons);
        dialog.Controls.Add(panel); dialog.AcceptButton = sync; dialog.CancelButton = cancel;
        if (dialog.ShowDialog(this) == DialogResult.OK)
            await EmitAsync(new { @event = "bookmark-source-folder", folder_id = ((SourceFolderChoice)choice.SelectedItem!).Id });
        else await EmitAsync(new { @event = "bookmark-source-cancel" });
    }

    async Task EditBookmarkAsync(JsonElement command)
    {
        bool folder = TextValue(command, "kind") == "folder";
        using var dialog = new Form { Text = folder ? "Folder" : "Bookmark", StartPosition = FormStartPosition.CenterParent,
            AutoScaleDimensions = new SizeF(96, 96), AutoScaleMode = AutoScaleMode.Dpi,
            ClientSize = new Size(520, folder ? 230 : 290), FormBorderStyle = FormBorderStyle.FixedDialog, MaximizeBox = false, MinimizeBox = false };
        var panel = new TableLayoutPanel { Dock = DockStyle.Top, ColumnCount = 2, AutoSize = true, Padding = new Padding(16) };
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize)); panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        var title = new TextBox { Text = TextValue(command, "title"), Dock = DockStyle.Fill };
        var url = new TextBox { Text = TextValue(command, "url"), Dock = DockStyle.Fill };
        var folders = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Fill };
        folders.Items.Add(new FolderChoice(0, "Bookmarks"));
        foreach (var entry in command.GetProperty("folders").EnumerateArray()) folders.Items.Add(new FolderChoice(entry.GetProperty("id").GetInt64(), TextValue(entry, "title")));
        var parentId = command.GetProperty("parent_id").GetInt64();
        folders.SelectedIndex = 0;
        for (int i = 0; i < folders.Items.Count; i++) if (((FolderChoice)folders.Items[i]!).Id == parentId) folders.SelectedIndex = i;
        panel.Controls.Add(new Label { Text = "Title", AutoSize = true }); panel.Controls.Add(title);
        if (!folder) { panel.Controls.Add(new Label { Text = "URL", AutoSize = true }); panel.Controls.Add(url); }
        panel.Controls.Add(new Label { Text = "Folder", AutoSize = true }); panel.Controls.Add(folders);
        var buttons = new FlowLayoutPanel { FlowDirection = FlowDirection.RightToLeft, Dock = DockStyle.Fill, AutoSize = true, Margin = new Padding(0, 14, 0, 0) };
        var save = new Button { Text = "Save", DialogResult = DialogResult.OK, AutoSize = true, MinimumSize = new Size(90, 32) };
        var cancel = new Button { Text = "Cancel", DialogResult = DialogResult.Cancel, AutoSize = true, MinimumSize = new Size(90, 32) };
        buttons.Controls.Add(save); buttons.Controls.Add(cancel); panel.Controls.Add(buttons); panel.SetColumnSpan(buttons, 2);
        dialog.Controls.Add(panel); dialog.AcceptButton = save; dialog.CancelButton = cancel;
        bool accepted = dialog.ShowDialog(this) == DialogResult.OK;
        await EmitAsync(new { @event = "editor-result", cancelled = !accepted, title = title.Text, url = folder ? "" : url.Text,
            parent_id = ((FolderChoice)folders.SelectedItem!).Id });
    }

    async Task ConfirmBrowserActionAsync(JsonElement command)
    {
        if (command.TryGetProperty("history", out var history) && history.GetBoolean()) {
            using var dialog = new Form { Text = "Clear History", StartPosition = FormStartPosition.CenterParent,
                AutoScaleDimensions = new SizeF(96, 96), AutoScaleMode = AutoScaleMode.Dpi,
                ClientSize = new Size(490, 220), FormBorderStyle = FormBorderStyle.FixedDialog, MaximizeBox = false, MinimizeBox = false };
            var panel = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, Padding = new Padding(18), WrapContents = false };
            panel.Controls.Add(new Label { Text = "Choose the browsing history to remove.\nBookmarks, files and website sign-ins will be kept.", AutoSize = true, Margin = new Padding(0, 0, 0, 14) });
            var range = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 280 };
            range.Items.AddRange(["Last hour", "Last 24 hours", "Last 7 days", "All history"]); range.SelectedIndex = 0;
            panel.Controls.Add(range);
            var buttons = new FlowLayoutPanel { AutoSize = true, Margin = new Padding(0, 18, 0, 0) };
            var clear = new Button { Text = "Clear History", AutoSize = true, DialogResult = DialogResult.OK };
            var cancel = new Button { Text = "Cancel", AutoSize = true, DialogResult = DialogResult.Cancel };
            buttons.Controls.Add(clear); buttons.Controls.Add(cancel); panel.Controls.Add(buttons);
            dialog.Controls.Add(panel); dialog.CancelButton = cancel;
            bool confirmed = dialog.ShowDialog(this) == DialogResult.OK;
            await EmitAsync(new { @event = "confirm-result", confirmed, range = new[] { "hour", "day", "week", "all" }[range.SelectedIndex] });
            return;
        }
        bool accepted = MessageBox.Show(this, TextValue(command, "message"), TextValue(command, "title"), MessageBoxButtons.OKCancel, MessageBoxIcon.Question) == DialogResult.OK;
        await EmitAsync(new { @event = "confirm-result", confirmed = accepted });
    }
}
