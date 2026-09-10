using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Net;

namespace GewuInsight.Windows;

// Anonymous, bounded icon requests are separate from both the private UI client
// and website sign-in profiles. No third-party icon service is used.
internal sealed class BrowserFavicons : IDisposable
{
    readonly HttpClient client;
    readonly SemaphoreSlim slots = new(2);
    readonly CancellationTokenSource lifetime = new();
    readonly Dictionary<string, string> cached = new(StringComparer.OrdinalIgnoreCase);
    readonly Dictionary<string, Uri> preferred = new(StringComparer.OrdinalIgnoreCase);
    readonly HashSet<string> pending = new(StringComparer.OrdinalIgnoreCase);
    readonly Func<string, bool> allowed;
    readonly Func<string, string, Task> publish;
    internal bool Active { get; set; }

    internal BrowserFavicons(Func<string, bool> allowed, Func<string, string, Task> publish, HttpMessageHandler? handler = null)
    {
        this.allowed = allowed; this.publish = publish;
        client = new HttpClient(handler ?? new HttpClientHandler { AllowAutoRedirect = false, UseCookies = false, UseDefaultCredentials = false }) { Timeout = TimeSpan.FromSeconds(8) };
        client.DefaultRequestHeaders.Accept.ParseAdd("image/png,image/x-icon,image/*;q=0.8");
    }

    internal async Task RequestAsync(string pageUrl, string iconUrl = "")
    {
        if (!Active || lifetime.IsCancellationRequested || !allowed(pageUrl) || !Uri.TryCreate(pageUrl, UriKind.Absolute, out var page)) return;
        string host = page.IdnHost.ToLowerInvariant();
        if (!page.IsDefaultPort) return;
        if (Uri.TryCreate(iconUrl, UriKind.Absolute, out var hint) && SafeIcon(hint) && hint.IdnHost.Equals(host, StringComparison.OrdinalIgnoreCase)) {
            if (!preferred.TryGetValue(host, out var old) || old != hint) {
                if (preferred.Count >= 256) preferred.Remove(preferred.Keys.First());
                preferred[host] = hint;
                if (cached.GetValueOrDefault(host) == "") cached.Remove(host);
            }
        }
        if (cached.TryGetValue(host, out string? saved)) { await publish(host, saved); return; }
        if (pending.Count >= 64 || !pending.Add(host)) return;
        bool acquired = false;
        try {
            await slots.WaitAsync(lifetime.Token); acquired = true;
            if (!Active || lifetime.IsCancellationRequested) return;
            var url = preferred.GetValueOrDefault(host) ?? new UriBuilder("https", host) { Path = "/favicon.ico" }.Uri;
            string data = "";
            try {
                using var timeout = CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token);
                timeout.CancelAfter(TimeSpan.FromSeconds(8));
                byte[] bytes = await FetchAsync(url, timeout.Token);
                byte[] png = Normalize(bytes);
                if (png.Length > 0) data = "data:image/png;base64," + Convert.ToBase64String(png);
            } catch (Exception error) when (error is HttpRequestException or IOException or OperationCanceledException or ArgumentException or System.Runtime.InteropServices.ExternalException) { }
            if (lifetime.IsCancellationRequested) return;
            if (cached.Count >= 256) cached.Remove(cached.Keys.First());
            cached[host] = data;
            await publish(host, data);
        } catch (OperationCanceledException) { }
        finally { pending.Remove(host); if (acquired) slots.Release(); }
    }

    bool SafeIcon(Uri url) => url.Scheme == "https" && url.IsDefaultPort && allowed(url.AbsoluteUri);

    internal async Task<byte[]> FetchAsync(Uri url, CancellationToken cancellation)
    {
        for (int redirect = 0; redirect <= 3; redirect++) {
            if (!SafeIcon(url)) return [];
            using var response = await client.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, cancellation);
            if (response.StatusCode is HttpStatusCode.MovedPermanently or HttpStatusCode.Redirect or HttpStatusCode.SeeOther or HttpStatusCode.TemporaryRedirect or HttpStatusCode.PermanentRedirect) {
                if (redirect == 3 || response.Headers.Location == null || !Uri.TryCreate(url, response.Headers.Location, out var next)) return [];
                url = next; continue;
            }
            if (response.StatusCode != HttpStatusCode.OK || response.Content.Headers.ContentLength > 512 * 1024) return [];
            await using var stream = await response.Content.ReadAsStreamAsync(cancellation);
            using var buffer = new MemoryStream();
            var block = new byte[8192];
            int count;
            while ((count = await stream.ReadAsync(block, cancellation)) > 0) {
                if (buffer.Length + count > 512 * 1024) return [];
                buffer.Write(block, 0, count);
            }
            return buffer.ToArray();
        }
        return [];
    }

    internal static byte[] Normalize(byte[] bytes)
    {
        if (bytes.Length < 8 || bytes.Length > 512 * 1024) return [];
        using var input = new MemoryStream(bytes);
        using var icon = bytes[0] == 0 && bytes[1] == 0 && bytes[2] == 1 && bytes[3] == 0 ? new Icon(input, 64, 64) : null;
        using var source = icon != null ? icon.ToBitmap() : Image.FromStream(input, false, true);
        if (source.Width > 4096 || source.Height > 4096) return [];
        using var scaled = new Bitmap(64, 64, PixelFormat.Format32bppArgb);
        using (var graphics = Graphics.FromImage(scaled)) {
            graphics.Clear(Color.Transparent); graphics.InterpolationMode = InterpolationMode.HighQualityBicubic;
            double ratio = Math.Min(64.0 / source.Width, 64.0 / source.Height);
            int width = Math.Max(1, (int)(source.Width * ratio)), height = Math.Max(1, (int)(source.Height * ratio));
            graphics.DrawImage(source, new Rectangle((64 - width) / 2, (64 - height) / 2, width, height));
        }
        using var output = new MemoryStream(); scaled.Save(output, ImageFormat.Png);
        return output.Length <= 65536 ? output.ToArray() : [];
    }

    public void Dispose() { Active = false; lifetime.Cancel(); client.Dispose(); }
}
