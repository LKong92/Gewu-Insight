using System.Diagnostics;
using System.Text.Json;

namespace GewuInsight.Windows;

internal sealed record DatabaseLocation(string Workspace, string Identity, string Runtime);

internal static class WorkspaceLocation
{
    static JsonElement Invoke(string root, string python, params string[] arguments)
    {
        string bundled = Path.Combine(root, "service", "python.exe");
        bool installed = File.Exists(bundled);
        if (!installed && Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar).Equals(
            Path.GetFullPath(AppContext.BaseDirectory).TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase))
            throw new IOException("The installed runtime is missing. Reinstall Gewu Insight.");
        var start = new ProcessStartInfo(installed ? bundled : python) {
            WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardError = true, RedirectStandardOutput = true,
            StandardOutputEncoding = System.Text.Encoding.UTF8, StandardErrorEncoding = System.Text.Encoding.UTF8
        };
        start.ArgumentList.Add("-X"); start.ArgumentList.Add("utf8");
        start.ArgumentList.Add("-B");
        if (installed) { start.ArgumentList.Add(Path.Combine(root, "service", "service_entry.py")); start.ArgumentList.Add("--database-control"); }
        else { start.ArgumentList.Add("-m"); start.ArgumentList.Add("paper_monitor.windows_database"); }
        foreach (string argument in arguments) start.ArgumentList.Add(argument);
        start.Environment["PYTHONUTF8"] = "1";
        start.Environment["PYTHONIOENCODING"] = "utf-8";
        using var process = Process.Start(start) ?? throw new IOException("Database checks could not start.");
        var output = process.StandardOutput.ReadToEndAsync();
        var errors = process.StandardError.ReadToEndAsync();
        process.WaitForExit();
        if (process.ExitCode != 0) throw new IOException(errors.GetAwaiter().GetResult().Trim());
        using var result = JsonDocument.Parse(output.GetAwaiter().GetResult());
        return result.RootElement.Clone();
    }

    public static DatabaseLocation Prepare(string root, string python, string workspace, bool create, bool select, string identity = "")
    {
        if (!Path.IsPathFullyQualified(workspace)) throw new IOException("Choose an absolute Gewu Database path.");
        workspace = Path.GetFullPath(workspace);
        string install = Path.GetFullPath(AppContext.BaseDirectory).TrimEnd(Path.DirectorySeparatorChar);
        if (workspace.Equals(install, StringComparison.OrdinalIgnoreCase) || workspace.StartsWith(install + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
            || install.StartsWith(workspace.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new IOException("The software installation and Gewu Database must use separate directories.");
        var arguments = new List<string> { "prepare", "--workspace", workspace };
        if (create) arguments.Add("--create");
        if (select) arguments.Add("--select");
        if (identity.Length > 0) { arguments.Add("--identity"); arguments.Add(identity); }
        var result = Invoke(root, python, arguments.ToArray());
        return new(result.GetProperty("workspace").GetString()!, result.GetProperty("identity").GetString()!, result.GetProperty("runtime").GetString()!);
    }

    public static DatabaseLocation Resolve(string[] args, string root, string python)
    {
        int index = Array.IndexOf(args, "--workspace");
        if (index >= 0) {
            if (index + 1 >= args.Length) throw new ArgumentException("--workspace requires a directory.");
            return Prepare(root, python, args[index + 1], args.Contains("--new-workspace"), false);
        }
        if (args.Contains("--source")) throw new IOException("Development requires an explicit isolated --workspace.");
        if (!args.Contains("--choose-database")) {
            try {
                var saved = Invoke(root, python, "locate");
                if (saved.ValueKind != JsonValueKind.Null)
                    return Prepare(root, python, saved.GetProperty("workspace").GetString()!, false, false, saved.GetProperty("identity").GetString()!);
                string legacy = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".gewu-insight", "preview-workspace.txt");
                if (File.Exists(legacy)) return Prepare(root, python, File.ReadAllText(legacy).Trim(), false, true);
            } catch (Exception error) {
                if (MessageBox.Show(error.Message + "\n\nLocate an existing Gewu Database?", "Gewu Database unavailable", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes)
                    throw new OperationCanceledException();
                return Choose(root, python, existingOnly: true);
            }
        }
        return Choose(root, python);
    }

    static DatabaseLocation Choose(string root, string python, bool existingOnly = false)
    {
        using var dialog = new Form { Text = "Choose Gewu Database", Width = 640, Height = 250, StartPosition = FormStartPosition.CenterScreen, FormBorderStyle = FormBorderStyle.FixedDialog, MaximizeBox = false, MinimizeBox = false };
        var description = new Label { Text = "Research data is kept separately from Gewu Insight. Uninstalling the App keeps your database.", Left = 20, Top = 16, Width = 580, Height = 40 };
        var create = new RadioButton { Text = "Create new Gewu Database", Left = 20, Top = 62, Width = 270, Checked = !existingOnly, Enabled = !existingOnly };
        var existing = new RadioButton { Text = "Use existing Gewu Database", Left = 305, Top = 62, Width = 280, Checked = existingOnly };
        var path = new TextBox { Left = 20, Top = 100, Width = 490, Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Gewu Database") };
        var browse = new Button { Text = "Browse…", Left = 520, Top = 98, Width = 85 };
        browse.Click += (_, _) => { using var picker = new FolderBrowserDialog { Description = "Choose the root folder containing data, reports, config and backups", UseDescriptionForTitle = true, SelectedPath = path.Text }; if (picker.ShowDialog(dialog) == DialogResult.OK) path.Text = picker.SelectedPath; };
        var open = new Button { Text = "Continue", Left = 420, Top = 155, Width = 90 };
        var cancel = new Button { Text = "Cancel", Left = 520, Top = 155, Width = 85, DialogResult = DialogResult.Cancel };
        DatabaseLocation? location = null;
        open.Click += (_, _) => {
            try { location = Prepare(root, python, path.Text, create.Checked, true); dialog.DialogResult = DialogResult.OK; }
            catch (Exception error) { MessageBox.Show(dialog, error.Message, "Cannot use Gewu Database", MessageBoxButtons.OK, MessageBoxIcon.Error); }
        };
        dialog.Controls.AddRange([description, create, existing, path, browse, open, cancel]);
        dialog.AcceptButton = open; dialog.CancelButton = cancel;
        if (dialog.ShowDialog() != DialogResult.OK || location == null) throw new OperationCanceledException();
        return location;
    }
}
