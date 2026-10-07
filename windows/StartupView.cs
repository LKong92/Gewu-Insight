using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Drawing.Text;

namespace GewuInsight.Windows;

// Paint the first frame natively: neither the service nor WebView2 is ready yet.
internal sealed class StartupView : Control
{
    readonly Image icon = LoadImage("startup-icon.png");
    readonly Image brandArt = LoadImage("startup-seal.png");
    string title = "Starting Gewu Insight";
    string message = "Preparing the local reading workspace.";

    public StartupView()
    {
        Dock = DockStyle.Fill;
        BackColor = Color.FromArgb(244, 242, 237);
        SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
            ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw | ControlStyles.Opaque, true);
        TabStop = false;
        AccessibleRole = AccessibleRole.StaticText;
        UpdateAccessibleText();
    }

    static Image LoadImage(string name)
    {
        using var stream = typeof(StartupView).Assembly.GetManifestResourceStream("GewuInsight.Windows." + name)!;
        using var source = Image.FromStream(stream);
        return new Bitmap(source);
    }

    public void SetStatus(string heading, string detail)
    {
        title = heading;
        message = detail;
        UpdateAccessibleText();
        Invalidate();
    }

    void UpdateAccessibleText()
    {
        AccessibleName = title;
        AccessibleDescription = message;
        Text = title + ". " + message;
    }

    static GraphicsPath RoundedRectangle(RectangleF bounds, float radius)
    {
        var path = new GraphicsPath();
        float diameter = radius * 2;
        path.AddArc(bounds.Left, bounds.Top, diameter, diameter, 180, 90);
        path.AddArc(bounds.Right - diameter, bounds.Top, diameter, diameter, 270, 90);
        path.AddArc(bounds.Right - diameter, bounds.Bottom - diameter, diameter, diameter, 0, 90);
        path.AddArc(bounds.Left, bounds.Bottom - diameter, diameter, diameter, 90, 90);
        path.CloseFigure();
        return path;
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        var graphics = e.Graphics;
        graphics.Clear(BackColor);
        graphics.SmoothingMode = SmoothingMode.AntiAlias;
        graphics.InterpolationMode = InterpolationMode.HighQualityBicubic;
        graphics.TextRenderingHint = TextRenderingHint.AntiAliasGridFit;
        var state = graphics.Save();
        float scale = DeviceDpi / 96f;
        graphics.ScaleTransform(scale, scale);
        float width = ClientSize.Width / scale, height = ClientSize.Height / scale;
        float cardWidth = Math.Min(460, Math.Max(280, width - 40));
        float textWidth = cardWidth - 135;
        using var headingFont = new Font("Segoe UI", 19, FontStyle.Bold, GraphicsUnit.Pixel);
        using var detailFont = new Font("Segoe UI", 13, FontStyle.Regular, GraphicsUnit.Pixel);
        using var format = new StringFormat(StringFormat.GenericTypographic) { Trimming = StringTrimming.EllipsisCharacter };
        float headingHeight = graphics.MeasureString(title, headingFont, (int)textWidth, format).Height;
        float detailHeight = graphics.MeasureString(message, detailFont, (int)textWidth, format).Height;
        float cardHeight = Math.Max(116, Math.Min(height - 40, headingHeight + detailHeight + 66));
        var card = new RectangleF((width - cardWidth) / 2, (height - cardHeight) / 2, cardWidth, cardHeight);

        // Soft, inexpensive shadow; all artwork is clipped to the rounded card.
        for (int spread = 24; spread >= 1; spread--)
        {
            var shadowBounds = card;
            shadowBounds.Inflate(spread, spread);
            shadowBounds.Offset(0, 10);
            using var shadowPath = RoundedRectangle(shadowBounds, 18 + spread);
            using var shadowBrush = new SolidBrush(Color.FromArgb(1, 35, 31, 26));
            graphics.FillPath(shadowBrush, shadowPath);
        }
        using var outline = RoundedRectangle(card, 18);
        using var fill = new SolidBrush(Color.FromArgb(253, 252, 251));
        graphics.FillPath(fill, outline);
        var clip = graphics.Save();
        graphics.SetClip(outline, CombineMode.Intersect);
        using (var attributes = new ImageAttributes())
        {
            // Retain the original seal's alpha while tinting its light glyphs black.
            attributes.SetColorMatrix(new ColorMatrix(new[] {
                new float[] { 0, 0, 0, 0, 0 }, new float[] { 0, 0, 0, 0, 0 },
                new float[] { 0, 0, 0, 0, 0 }, new float[] { 0, 0, 0, .075f, 0 },
                new float[] { 0, 0, 0, 0, 1 }
            }));
            graphics.DrawImage(brandArt, Rectangle.Round(new RectangleF(card.Right - 208, card.Top - 66, 236, 236)),
                0, 0, brandArt.Width, brandArt.Height, GraphicsUnit.Pixel, attributes);
        }
        graphics.Restore(clip);
        using var border = new Pen(Color.FromArgb(31, 35, 31, 26), 1);
        graphics.DrawPath(border, outline);
        graphics.DrawImage(icon, new RectangleF(card.Left + 33, card.Top + (card.Height - 58) / 2, 58, 58));
        float textTop = card.Top + (card.Height - headingHeight - detailHeight - 7) / 2;
        using var headingBrush = new SolidBrush(Color.FromArgb(33, 33, 33));
        using var detailBrush = new SolidBrush(Color.FromArgb(94, 90, 84));
        graphics.DrawString(title, headingFont, headingBrush,
            new RectangleF(card.Left + 111, textTop, textWidth, headingHeight + 2), format);
        graphics.DrawString(message, detailFont, detailBrush,
            new RectangleF(card.Left + 111, textTop + headingHeight + 7, textWidth, card.Bottom - textTop - headingHeight - 25), format);
        graphics.Restore(state);
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing) { icon.Dispose(); brandArt.Dispose(); }
        base.Dispose(disposing);
    }
}
