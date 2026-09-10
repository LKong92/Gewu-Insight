namespace GewuInsight.Windows;

internal static class PdfSources
{
    public const string Unverified = "PDF source is not verified as a publisher or authorized repository. Download stopped.";
    static readonly string[] Hosts = ReadHosts();
    static string[] ReadHosts() {
        using var reader = new StreamReader(typeof(PdfSources).Assembly.GetManifestResourceStream("GewuInsight.Windows.pdf_source_hosts.txt")!);
        return reader.ReadToEnd().Split('\n').Select(line => line.Trim()).Where(line => line.Length > 0 && !line.StartsWith('#')).ToArray();
    }
    public static bool Approved(string url) {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri) || uri.Scheme is not ("http" or "https") || uri.UserInfo.Length > 0 || uri.Port is not (80 or 443)) return false;
        string host = uri.IdnHost.TrimEnd('.').ToLowerInvariant();
        return Hosts.Any(domain => host == domain || host.EndsWith("." + domain, StringComparison.Ordinal));
    }
}
