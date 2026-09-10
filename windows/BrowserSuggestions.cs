using System.Text.Json;

namespace GewuInsight.Windows;

// A sibling of both WebViews: HTML cannot paint above a native webpage view.
// Mouse selection leaves the address field focused until navigation is chosen.
internal sealed class BrowserSuggestions : Control
{
    internal sealed record Entry(string Title, string Url);
    internal Entry[] Entries { get; private set; } = [];
    internal int Selected { get; private set; } = -1;
    internal int RowHeight => Math.Max(44, (int)(48 * DeviceDpi / 96.0));
    internal event Action<string>? Chosen;

    internal BrowserSuggestions()
    {
        SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);
        SetStyle(ControlStyles.Selectable, false);
        TabStop = false; Visible = false; BackColor = Color.White;
        AccessibleName = "Address history suggestions";
        AccessibleRole = AccessibleRole.List;
    }

    internal void UpdateItems(JsonElement command, Func<string, bool> allowed)
    {
        Entries = command.GetProperty("items").EnumerateArray().Take(8)
            .Select(item => new Entry(item.TryGetProperty("title", out var title) ? title.GetString() ?? "" : "", item.GetProperty("url").GetString() ?? ""))
            .Where(item => allowed(item.Url)).ToArray();
        Selected = command.TryGetProperty("selected", out var value) ? value.GetInt32() : -1;
        if (Selected < -1 || Selected >= Entries.Length) Selected = -1;
        Invalidate();
    }

    protected override void WndProc(ref Message message)
    {
        if (message.Msg == 0x21) { message.Result = (IntPtr)3; return; } // WM_MOUSEACTIVATE: MA_NOACTIVATE
        base.WndProc(ref message);
    }

    protected override void OnMouseDown(MouseEventArgs e)
    {
        base.OnMouseDown(e);
        int index = e.Y / RowHeight;
        if (e.Button == MouseButtons.Left && index >= 0 && index < Entries.Length) {
            string url = Entries[index].Url; Hide(); Chosen?.Invoke(url);
        }
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        for (int i = 0; i < Entries.Length; i++) {
            var row = new Rectangle(1, i * RowHeight + 1, Width - 2, RowHeight);
            if (i == Selected) { using var brush = new SolidBrush(Color.FromArgb(231, 239, 251)); e.Graphics.FillRectangle(brush, row); }
            var flags = TextFormatFlags.EndEllipsis | TextFormatFlags.NoPrefix | TextFormatFlags.SingleLine;
            int half = RowHeight / 2;
            TextRenderer.DrawText(e.Graphics, Entries[i].Title.Length > 0 ? Entries[i].Title : Entries[i].Url, Font,
                new Rectangle(10, row.Y + 3, Width - 20, half), ForeColor, flags);
            TextRenderer.DrawText(e.Graphics, Entries[i].Url, Font,
                new Rectangle(10, row.Y + half, Width - 20, half), Color.DimGray, flags);
        }
        e.Graphics.DrawRectangle(SystemPens.ControlDark, 0, 0, Math.Max(0, Width - 1), Math.Max(0, Height - 1));
    }
}

internal sealed partial class WorkspaceWindow
{
    readonly BrowserSuggestions suggestions = new();
    bool browserActive;

    void ShowSuggestions(JsonElement command)
    {
        suggestions.UpdateItems(command, PublicUrl);
        if (!browserActive || suggestions.Entries.Length == 0) { suggestions.Hide(); return; }
        double scale = workspace.Width / Math.Max(1, command.GetProperty("viewportWidth").GetDouble());
        int width = Math.Clamp((int)(command.GetProperty("width").GetDouble() * scale), 1, ClientSize.Width);
        int x = Math.Clamp(workspace.Left + (int)(command.GetProperty("x").GetDouble() * scale), 0, ClientSize.Width - width);
        int y = Math.Clamp(workspace.Top + (int)(command.GetProperty("y").GetDouble() * scale), 0, ClientSize.Height);
        suggestions.Bounds = new Rectangle(x, y, width, Math.Min(ClientSize.Height - y, suggestions.Entries.Length * suggestions.RowHeight + 2));
        suggestions.Show(); suggestions.BringToFront();
    }
}
