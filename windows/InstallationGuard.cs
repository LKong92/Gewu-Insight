namespace GewuInsight.Windows;

// These names match the per-user Inno Setup gates. Keep a running marker for
// the entire GUI/helper lifetime; Setup must not replace an active service.
internal static class InstallationGuard
{
    public static string Running => "GewuInsight.Windows.Running." + Environment.UserName;
    static string Installing => "GewuInsight.Windows.Installing." + Environment.UserName;
    static bool InstallerPresent()
    {
        if (!Mutex.TryOpenExisting(Installing, out var marker)) return false;
        marker.Dispose(); return true;
    }
    public static Mutex Enter(bool afterInstall)
    {
        if (afterInstall) {
            var deadline = DateTime.UtcNow.AddMinutes(2);
            while (InstallerPresent() && DateTime.UtcNow < deadline) Thread.Sleep(250);
        }
        if (InstallerPresent()) throw new IOException("Gewu Insight is being installed. Finish or close Windows Setup before opening Gewu or reconnecting Zotero.");
        var running = new Mutex(false, Running);
        // Close the race between checking the installation and opening the App.
        if (InstallerPresent()) { running.Dispose(); throw new IOException("Wait for Windows Setup to finish before opening Gewu Insight."); }
        return running;
    }
}
