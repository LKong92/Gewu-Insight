using System.Net;
using System.Security.Cryptography;
using System.Text.Json;
using GewuInsight.Windows;

int checks = 0;
void Expect(bool condition, string description) { if (!condition) throw new Exception(description); checks++; }
async Task Fails(Func<Task> task, string description) { try { await task(); } catch (IOException) { checks++; return; } throw new Exception(description); }
var bytes = System.Text.Encoding.UTF8.GetBytes("A disposable installer fixture; never executable.");
string digest = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
object Release(string tag, string version, string platform = "windows", string channel = "stable", string? checksum = null, string? url = null) => new {
    schema = 1, channel, platform, architecture = "x64", version, tag,
    asset = new { name = $"Gewu-Insight-Windows-{version}-x64-Setup.exe", size = bytes.Length,
        sha256 = checksum ?? digest,
        url = url ?? $"{WindowsUpdateRelease.Repository}/releases/download/{tag}/Gewu-Insight-Windows-{version}-x64-Setup.exe" }
};
WindowsUpdateRelease? Select(object value) { using var json = JsonDocument.Parse(JsonSerializer.Serialize(value)); return WindowsUpdateRelease.Select(json.RootElement, new Version(1, 0, 0)); }
Expect(Select(Release("windows-1.2.0", "1.2.0"))?.Version == new Version(1,2,0), "Select the published Windows channel");
Expect(Select(Release("windows-1.0.0", "1.0.0")) == null && Select(Release("windows-0.9.0", "0.9.0")) == null, "Never downgrade or reinstall current version");
Expect(Select(Release("v1.1.0", "1.1.0")) != null, "Mixed-platform version tags may contain the exact Windows asset");
await Fails(() => { Select(Release("macos-1.1.0", "1.1.0", platform:"macos")); return Task.CompletedTask; }, "Mac feed cannot update Windows");
await Fails(() => { Select(Release("windows-1.1.0", "1.1.0", channel:"beta")); return Task.CompletedTask; }, "Stable feed rejects prereleases");
await Fails(() => { Select(Release("windows-2.0.0", "1.1.0")); return Task.CompletedTask; }, "Tag and version must agree");
await Fails(() => { Select(Release("windows-1.1.0", "1.1.0", checksum:"")); return Task.CompletedTask; }, "Missing verification must fail closed");
await Fails(() => { Select(Release("windows-1.1.0", "1.1.0", url:"https://example.com/setup.exe")); return Task.CompletedTask; }, "Foreign installer address");
foreach (var url in new[] { "http://github.com/LKong92/Gewu-Insight/releases/download/a/b", "https://user@github.com/LKong92/Gewu-Insight/releases/download/a/b", "https://github.com/other/repo/releases/download/a/b", "https://github.com.evil.example/a", "https://127.0.0.1/setup.exe", "https://github.com:444/LKong92/Gewu-Insight/releases/download/a/b" })
    Expect(!WindowsUpdateRelease.AllowedDownload(new Uri(url)), "Reject unsafe redirect " + url);
var release = Select(Release("windows-1.1.0", "1.1.0"))!;
string temp = Path.Combine(Path.GetTempPath(), "gewu-update-tests-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(temp);
try {
    using var good = new HttpClient(new FakeHandler(request => {
        Expect(request.Headers.Authorization == null && !request.Headers.Contains("X-Gewu-Workspace"), "No workspace credential leaves the machine");
        if (request.RequestUri!.Host == "github.com") return new HttpResponseMessage(HttpStatusCode.Found) { Headers = { Location = new Uri("https://release-assets.githubusercontent.com/fixture") } };
        return new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(bytes) };
    }));
    var path = await release.DownloadAsync(good, temp, new Progress<int>(), CancellationToken.None);
    Expect(File.ReadAllBytes(path).SequenceEqual(bytes), "Verified bytes preserved");
    await release.VerifyAsync(path, CancellationToken.None);
    File.WriteAllText(path, "tampered");
    await Fails(() => release.VerifyAsync(path, CancellationToken.None), "Recheck before execution");
    using var corrupt = new HttpClient(new FakeHandler(_ => new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(new byte[bytes.Length]) }));
    await Fails(() => release.DownloadAsync(corrupt, temp, new Progress<int>(), CancellationToken.None), "Corrupted installer never accepted");
    Expect(!Directory.EnumerateFiles(temp, "*.partial").Any(), "Failed partial download cleaned");
    using var foreign = new HttpClient(new FakeHandler(_ => new HttpResponseMessage(HttpStatusCode.Found) { Headers = { Location = new Uri("https://example.com/setup.exe") } }));
    await Fails(() => release.DownloadAsync(foreign, temp, new Progress<int>(), CancellationToken.None), "Download cannot leave release hosts");
    using var limited = new HttpClient(new FakeHandler(_ => new HttpResponseMessage(HttpStatusCode.Forbidden)));
    await Fails(() => WindowsUpdateRelease.CheckAsync(limited, new Version(1,0,0), CancellationToken.None), "Rate limited is not up to date");
    using var channel = new HttpClient(new FakeHandler(request => {
        Expect(request.RequestUri!.AbsoluteUri == WindowsUpdateRelease.Feed && request.Headers.Authorization == null, "Check only the public Windows feed without credentials");
        return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(JsonSerializer.Serialize(Release("windows-1.1.0", "1.1.0"))) };
    }));
    Expect((await WindowsUpdateRelease.CheckAsync(channel,new Version(1,0,0),CancellationToken.None))?.Version == new Version(1,1,0), "Read Windows release independently of GitHub API pagination");
    using var malformed = new HttpClient(new FakeHandler(_ => new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent("{}") }));
    await Fails(() => WindowsUpdateRelease.CheckAsync(malformed,new Version(1,0,0),CancellationToken.None), "Incomplete feed is not up to date");
} finally { Directory.Delete(temp, true); }
Console.WriteLine($"{checks} Windows update checks passed.");

sealed class FakeHandler(Func<HttpRequestMessage,HttpResponseMessage> respond) : HttpMessageHandler
{
    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancel) { cancel.ThrowIfCancellationRequested(); return Task.FromResult(respond(request)); }
}
