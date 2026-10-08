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

// Match showAboutWindow in the macOS shell. Coordinates below use its 336 x 380
// point content area, converted from AppKit's bottom-left origin to top-left.
internal sealed class AboutWindow : Form
{
    readonly List<Image> images = [];
    readonly List<Font> fonts = [];

    public AboutWindow(string root)
    {
        Text = "About Gewu Insight";
        AutoScaleDimensions = new SizeF(96, 96);
        AutoScaleMode = AutoScaleMode.Dpi;
        ClientSize = new Size(336, 380);
        FormBorderStyle = FormBorderStyle.FixedSingle;
        MaximizeBox = false;
        MinimizeBox = false;
        ShowInTaskbar = false;
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = SystemColors.Control;
        Icon = new Icon(Path.Combine(AppContext.BaseDirectory, "GewuInsight.ico"));
        KeyPreview = true;
        KeyDown += (_, e) => { if (e.KeyCode == Keys.Escape) { e.Handled = true; Close(); } };

        var primary = SystemColors.ControlText;
        var secondary = SystemInformation.HighContrast ? primary : Color.FromArgb(100, 100, 100);
        var tertiary = SystemInformation.HighContrast ? primary : Color.FromArgb(130, 130, 130);
        AddImage("startup-icon.png", new Rectangle(132, 20, 72, 72), "Gewu Insight");
        AddLabel("Gewu Insight", 23.5f, new Rectangle(20, 99, 296, 30), primary, FontStyle.Bold);
        AddImage("about-calligraphy.png", new Rectangle(116, 136, 104, 22), "格物洞见", secondary);

        var metadata = typeof(AboutWindow).Assembly.GetCustomAttributes<AssemblyMetadataAttribute>()
            .ToDictionary(attribute => attribute.Key, attribute => attribute.Value);
        AddLabel($"Version {metadata["GewuProductVersion"]} (Build {metadata["GewuProductBuild"]})",
            11.5f, new Rectangle(20, 164, 296, 16), tertiary);
        AddLabel("Your personal research workspace where papers,\nevidence, and files stay connected over time.",
            12, new Rectangle(16, 192, 304, 36), primary);
        AddLink("User Guide", new Rectangle(83, 234, 82, 22), Path.Combine(root, "Windows_Preview_Guide.html"));
        AddLabel("·", 12, new Rectangle(162, 235, 12, 20), tertiary);
        AddLink("GitHub", new Rectangle(171, 234, 82, 22), "https://github.com/LKong92/Gewu-Insight");
        AddLabel("Designed and developed by Lingyuan Kong and Zhengran Wu,\nwith coding assistance from OpenAI Codex.",
            9.5f, new Rectangle(18, 267, 300, 25), secondary);
        AddLabel("Copyright © 2026 Lingyuan Kong and Zhengran Wu.\nAll Rights Reserved.",
            9, new Rectangle(14, 303, 308, 25), tertiary);
        AddLabel("Source-available research software.\nAcademic/non-commercial research use permitted.\nCommercial use requires written authorization.",
            9, new Rectangle(14, 336, 308, 35), secondary);
    }

    Font MakeFont(float size, FontStyle style = FontStyle.Regular)
    {
        var font = new Font("Segoe UI", size, style, GraphicsUnit.Pixel);
        fonts.Add(font);
        return font;
    }

    void AddLabel(string text, float size, Rectangle bounds, Color color, FontStyle style = FontStyle.Regular)
    {
        Controls.Add(new Label {
            Text = text, AccessibleName = text, Bounds = bounds, Font = MakeFont(size, style),
            ForeColor = color, TextAlign = ContentAlignment.MiddleCenter, AutoSize = false,
            UseCompatibleTextRendering = true, UseMnemonic = false
        });
    }

    void AddLink(string text, Rectangle bounds, string destination)
    {
        var link = new LinkLabel {
            Text = text, AccessibleName = text, Bounds = bounds, Font = MakeFont(12.5f),
            TextAlign = ContentAlignment.MiddleCenter, LinkBehavior = LinkBehavior.HoverUnderline,
            LinkColor = SystemInformation.HighContrast ? SystemColors.HotTrack : Color.FromArgb(0, 102, 204),
            UseCompatibleTextRendering = true, TabStop = true
        };
        link.LinkClicked += (_, _) => {
            try { Process.Start(new ProcessStartInfo(destination) { UseShellExecute = true }); }
            catch (Exception error) { MessageBox.Show(this, error.Message, "Could not open " + text, MessageBoxButtons.OK, MessageBoxIcon.Error); }
        };
        Controls.Add(link);
    }

    void AddImage(string resource, Rectangle bounds, string description, Color? tint = null)
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
        Controls.Add(new PictureBox {
            Image = bitmap, Bounds = bounds, SizeMode = PictureBoxSizeMode.Zoom,
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
