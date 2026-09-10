namespace GewuInsight.Windows;

internal static class WorkspaceLocation
{
    // Store the selected root outside AppData: packaged launchers can redirect
    // AppData while Explorer launches see a different directory at the same name.
    public static string Resolve(string[] args)
    {
        int index = Array.IndexOf(args, "--workspace");
        if (index >= 0) {
            if (index + 1 >= args.Length) throw new ArgumentException("--workspace requires a directory.");
            return Path.GetFullPath(args[index + 1]);
        }
        string profile = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        string selection = Path.Combine(profile, ".gewu-insight", "preview-workspace.txt");
        if (File.Exists(selection)) {
            string chosen = File.ReadAllText(selection).Trim();
            if (!Path.IsPathFullyQualified(chosen) || !File.Exists(Path.Combine(chosen, "data", "paper_monitor.sqlite")))
                throw new IOException("The selected Library could not be found. No new Library was created. Check " + selection);
            return Path.GetFullPath(chosen);
        }
        string legacy = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Gewu Insight Preview");
        if (File.Exists(Path.Combine(legacy, "data", "paper_monitor.sqlite")))
            throw new IOException("An existing Preview Library needs its physical data folder selected before opening. No files were changed. Use --workspace with its verified location.");
        return Path.Combine(profile, "Gewu Insight Preview");
    }
}
