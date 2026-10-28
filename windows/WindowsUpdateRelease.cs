using System.Net;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace GewuInsight.Windows;

internal sealed record WindowsUpdateRelease(Version Version, Uri Download, Uri Page, long Bytes, string Sha256)
{
    public const string Repository = "https://github.com/LKong92/Gewu-Insight";
    public const string Feed = "https://raw.githubusercontent.com/LKong92/Gewu-Insight/Windows/updates/windows/stable.json";
    public string FileName => $"Gewu-Insight-Windows-{Version}-x64-Setup.exe";
    public const long MaximumBytes = 2L * 1024 * 1024 * 1024;

    // The Windows channel is promoted only after its public installer is verified.
    // It is independent of mixed-platform release order and GitHub API quotas.
    public static WindowsUpdateRelease? Select(JsonElement feed, Version current)
    {
        if (feed.GetProperty("schema").GetInt32() != 1 || feed.GetProperty("channel").GetString() != "stable"
            || feed.GetProperty("platform").GetString() != "windows" || feed.GetProperty("architecture").GetString() != "x64")
            throw new IOException("The update feed does not describe stable Windows x64 updates.");
        string text = feed.GetProperty("version").GetString() ?? "";
        if (!Regex.IsMatch(text, @"^[0-9]+\.[0-9]+\.[0-9]+$") || (!Version.TryParse(text, out var version) || version.ToString() != text))
            throw new IOException("The Windows update version is invalid.");
        string tag = feed.GetProperty("tag").GetString() ?? "";
        if (tag != "windows-" + text && tag != "v" + text && tag != text)
            throw new IOException("The release tag does not match the Windows version.");
        var asset = feed.GetProperty("asset");
        string file = $"Gewu-Insight-Windows-{text}-x64-Setup.exe";
        string expected = $"{Repository}/releases/download/{tag}/{file}";
        long size = asset.GetProperty("size").GetInt64();
        string digest = asset.GetProperty("sha256").GetString() ?? "";
        if (size <= 0 || size > MaximumBytes || !Regex.IsMatch(digest, "^[0-9a-fA-F]{64}$"))
            throw new IOException("The Windows release has no valid download verification data. Please try again later.");
        if (asset.GetProperty("name").GetString() != file || asset.GetProperty("url").GetString() != expected)
            throw new IOException("The Windows installer is not at the expected project release address.");
        return version > current ? new WindowsUpdateRelease(version, new Uri(expected), new Uri($"{Repository}/releases/tag/{tag}"), size, digest.ToLowerInvariant()) : null;
    }

    internal static bool AllowedDownload(Uri uri) => uri.Scheme == "https" && uri.IsDefaultPort
        && uri.UserInfo.Length == 0 && uri.Fragment.Length == 0
        && (uri.Host == "github.com" && uri.AbsolutePath.StartsWith("/LKong92/Gewu-Insight/releases/download/", StringComparison.Ordinal)
            || uri.Host == "release-assets.githubusercontent.com" || uri.Host == "objects.githubusercontent.com");

    public static HttpClient CreateClient()
    {
        // Workspace credentials are never placed on this public release client.
        var client = new HttpClient(new HttpClientHandler { AllowAutoRedirect = false }) { Timeout = TimeSpan.FromMinutes(20) };
        client.DefaultRequestHeaders.UserAgent.ParseAdd("Gewu-Insight-Windows-Updater/1.1");
        return client;
    }

    public static async Task<WindowsUpdateRelease?> CheckAsync(HttpClient client, Version current, CancellationToken cancel)
    {
        using var request = new HttpRequestMessage(HttpMethod.Get, Feed);
        request.Headers.Accept.ParseAdd("application/json");
        using var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancel);
        if (response.StatusCode is HttpStatusCode.Forbidden or HttpStatusCode.TooManyRequests)
            throw new IOException("The update server is temporarily unavailable. Please try again later.");
        response.EnsureSuccessStatusCode();
        await response.Content.LoadIntoBufferAsync(64 * 1024, cancel);
        try {
            using var json = JsonDocument.Parse(await response.Content.ReadAsByteArrayAsync(cancel));
            return Select(json.RootElement, current);
        } catch (Exception error) when (error is JsonException or KeyNotFoundException or InvalidOperationException or FormatException or OverflowException) {
            throw new IOException("The Windows update feed could not be read. Please try again later.", error);
        }
    }

    public async Task<string> DownloadAsync(HttpClient client, string directory, IProgress<int> progress, CancellationToken cancel)
    {
        Directory.CreateDirectory(directory);
        string path = Path.Combine(directory, FileName);
        // Each attempt has a private fresh name; cancelled downloads never look installed.
        string partial = Path.Combine(directory, Guid.NewGuid().ToString("N") + ".partial");
        try {
            Uri url = Download;
            for (int redirects = 0; redirects <= 5; redirects++) {
                if (!AllowedDownload(url)) throw new IOException("The installer download redirected outside GitHub's release storage.");
                using var response = await client.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, cancel);
                if ((int)response.StatusCode is 301 or 302 or 303 or 307 or 308) {
                    url = new Uri(url, response.Headers.Location ?? throw new IOException("Missing download location."));
                    continue;
                }
                response.EnsureSuccessStatusCode();
                if (response.Content.Headers.ContentLength is long length && length != Bytes) throw new IOException("The installer size does not match the release.");
                await using (var input = await response.Content.ReadAsStreamAsync(cancel))
                await using (var output = new FileStream(partial, FileMode.CreateNew, FileAccess.Write, FileShare.None, 65536, true)) {
                    using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
                    byte[] buffer = new byte[65536]; long total = 0;
                    for (int count; (count = await input.ReadAsync(buffer, cancel)) != 0;) {
                        total += count;
                        if (total > Bytes) throw new IOException("The installer is larger than the verified release.");
                        hash.AppendData(buffer, 0, count);
                        await output.WriteAsync(buffer.AsMemory(0, count), cancel);
                        progress.Report((int)(total * 100 / Bytes));
                    }
                    if (total != Bytes || !Convert.ToHexString(hash.GetHashAndReset()).Equals(Sha256, StringComparison.OrdinalIgnoreCase))
                        throw new IOException("Installer verification failed. Nothing was installed; download it again.");
                }
                File.Move(partial, path, true);
                return path;
            }
            throw new IOException("Too many installer download redirects.");
        } finally { if (File.Exists(partial)) File.Delete(partial); }
    }

    public async Task VerifyAsync(string path, CancellationToken cancel)
    {
        await using var input = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, 65536, true);
        if (input.Length != Bytes || !Convert.ToHexString(await SHA256.HashDataAsync(input, cancel)).Equals(Sha256, StringComparison.OrdinalIgnoreCase))
            throw new IOException("The downloaded installer changed. Download it again before installing.");
    }
}
