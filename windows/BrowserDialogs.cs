using System.Text.Json;

namespace GewuInsight.Windows;

internal sealed partial class WorkspaceWindow
{
    sealed record FolderChoice(long Id, string Title) { public override string ToString() => Title; }

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
