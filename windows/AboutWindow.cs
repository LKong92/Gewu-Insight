using System.Diagnostics;
using System.Drawing.Imaging;
using System.Reflection;

namespace GewuInsight.Windows;

internal sealed partial class WorkspaceWindow
{
    AboutWindow? aboutWindow;

    void ShowAboutWindow()
    {
        if (aboutWindow == null || aboutWindow.IsDisposed) aboutWindow = new AboutWindow(root);
        if (!aboutWindow.Visible) aboutWindow.Show(this);
        aboutWindow.Activate();
    }
}

// Keep the shared product content, with native Windows typography and reflow.
internal sealed class AboutWindow : Form
{
    readonly List<Image> images = [];
    readonly List<Font> fonts = [];
    readonly TableLayoutPanel content = new() {
        ColumnCount = 1, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink,
        Dock = DockStyle.Top, Padding = new Padding(28, 24, 28, 24), TabStop = false
    };

    public AboutWindow(string root)
    {
        Text = "About Gewu Insight";
        AutoScaleDimensions = new SizeF(96, 96);
        AutoScaleMode = AutoScaleMode.Dpi;
        ClientSize = new Size(560, 620);
        MinimumSize = new Size(440, 420);
        AutoScroll = true;
        FormBorderStyle = FormBorderStyle.Sizable;
        MaximizeBox = false;
        MinimizeBox = false;
        ShowInTaskbar = false;
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = SystemColors.Control;
        Icon = new Icon(Path.Combine(AppContext.BaseDirectory, "GewuInsight.ico"));
        KeyPreview = true;
        KeyDown += (_, e) => { if (e.KeyCode == Keys.Escape) { e.Handled = true; Close(); } };
        content.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        Controls.Add(content);

        var primary = SystemColors.ControlText;
        var secondary = SystemInformation.HighContrast ? primary : Color.FromArgb(80, 80, 80);
        AddImage("startup-icon.png", new Size(80, 80), "Gewu Insight", 10);
        AddLabel("Gewu Insight", 21, primary, 4, FontStyle.Bold);
        AddImage("about-calligraphy.png", new Size(142, 30), "格物洞见", 12, secondary);

        var metadata = typeof(AboutWindow).Assembly.GetCustomAttributes<AssemblyMetadataAttribute>()
            .ToDictionary(attribute => attribute.Key, attribute => attribute.Value);
        AddLabel($"Version {metadata["GewuProductVersion"]} (Build {metadata["GewuProductBuild"]})",
            11, secondary, 18);
        AddLabel("Your personal research workspace where papers,\nevidence, and files stay connected over time.",
            12, primary, 14);
        var links = new FlowLayoutPanel {
            AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, WrapContents = false,
            Anchor = AnchorStyles.None, Margin = new Padding(0, 0, 0, 22), TabStop = false
        };
        AddLink(links, "User Guide", Path.Combine(root, "Windows_Preview_Guide.html"));
        links.Controls.Add(new Label {
            Text = "·", Font = MakeFont(12), ForeColor = secondary, AutoSize = true,
            Margin = new Padding(12, 0, 12, 0), UseCompatibleTextRendering = false
        });
        AddLink(links, "GitHub", "https://github.com/LKong92/Gewu-Insight");
        AddRow(links);
        AddLabel("Designed and developed by Lingyuan Kong and Zhengran Wu,\nwith coding assistance from OpenAI Codex.",
            11, secondary, 14);
        AddLabel("Copyright © 2026 Lingyuan Kong and Zhengran Wu.\nAll Rights Reserved.",
            11, secondary, 14);
        AddLabel("Source-available research software.\nAcademic/non-commercial research use permitted.\nCommercial use requires written authorization.",
            11, secondary, 0);
    }

    void AddRow(Control control)
    {
        var row = content.RowCount++;
        content.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        content.Controls.Add(control, 0, row);
    }

    Font MakeFont(float size, FontStyle style = FontStyle.Regular)
    {
        var font = new Font("Segoe UI", size, style, GraphicsUnit.Point);
        fonts.Add(font);
        return font;
    }

    void AddLabel(string text, float size, Color color, int spaceAfter, FontStyle style = FontStyle.Regular)
    {
        AddRow(new Label {
            Text = text, AccessibleName = text, Font = MakeFont(size, style),
            ForeColor = color, TextAlign = ContentAlignment.MiddleCenter, AutoSize = true,
            Dock = DockStyle.Fill, Margin = new Padding(0, 0, 0, spaceAfter),
            UseCompatibleTextRendering = false, UseMnemonic = false
        });
    }

    void AddLink(FlowLayoutPanel links, string text, string destination)
    {
        var link = new LinkLabel {
            Text = text, AccessibleName = text, AutoSize = true, Margin = Padding.Empty, Font = MakeFont(12),
            TextAlign = ContentAlignment.MiddleCenter, LinkBehavior = LinkBehavior.HoverUnderline,
            LinkColor = SystemInformation.HighContrast ? SystemColors.HotTrack : Color.FromArgb(0, 102, 204),
            UseCompatibleTextRendering = false, UseMnemonic = false, TabStop = true
        };
        link.LinkClicked += (_, _) => {
            try { Process.Start(new ProcessStartInfo(destination) { UseShellExecute = true }); }
            catch (Exception error) { MessageBox.Show(this, error.Message, "Could not open " + text, MessageBoxButtons.OK, MessageBoxIcon.Error); }
        };
        links.Controls.Add(link);
    }

    void AddImage(string resource, Size size, string description, int spaceAfter, Color? tint = null)
    {
        using var stream = typeof(AboutWindow).Assembly.GetManifestResourceStream("GewuInsight.Windows." + resource)!;
        using var source = Image.FromStream(stream);
        var bitmap = new Bitmap(source.Width, source.Height);
        using (var graphics = Graphics.FromImage(bitmap)) {
            if (tint is Color color) {
                using var attributes = new ImageAttributes();
                attributes.SetColorMatrix(new ColorMatrix(new[] {
                    new float[] { 0, 0, 0, 0, 0 }, new float[] { 0, 0, 0, 0, 0 },
                    new float[] { 0, 0, 0, 0, 0 }, new float[] { 0, 0, 0, 1, 0 },
                    new float[] { color.R / 255f, color.G / 255f, color.B / 255f, 0, 1 }
                }));
                graphics.DrawImage(source, new Rectangle(0, 0, bitmap.Width, bitmap.Height),
                    0, 0, source.Width, source.Height, GraphicsUnit.Pixel, attributes);
            } else graphics.DrawImageUnscaled(source, 0, 0);
        }
        images.Add(bitmap);
        AddRow(new PictureBox {
            Image = bitmap, Size = size, SizeMode = PictureBoxSizeMode.Zoom,
            Anchor = AnchorStyles.None, Margin = new Padding(0, 0, 0, spaceAfter),
            AccessibleName = description, AccessibleRole = AccessibleRole.Graphic, TabStop = false
        });
    }

    protected override void Dispose(bool disposing)
    {
        base.Dispose(disposing);
        if (disposing) {
            foreach (var image in images) image.Dispose();
            foreach (var font in fonts) font.Dispose();
            images.Clear(); fonts.Clear();
        }
    }
}
