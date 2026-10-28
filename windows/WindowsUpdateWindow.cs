using System.Diagnostics;
using System.Reflection;
using System.Text;
using System.Text.Json;

namespace GewuInsight.Windows;

internal sealed partial class WorkspaceWindow
{
    WindowsUpdateWindow? updateWindow;
    async Task CheckUpdatesAutomaticallyAsync()
    {
        if (!WindowsUpdatePreferences.Due || !File.Exists(Path.Combine(root,"service","service_entry.py"))) return;
        WindowsUpdatePreferences.MarkChecked();
        try {
            using var publicClient = WindowsUpdateRelease.CreateClient();
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(applicationLifetime.Token);
            timeout.CancelAfter(TimeSpan.FromSeconds(30));
            var available = await WindowsUpdateRelease.CheckAsync(publicClient,WindowsUpdateWindow.Current,timeout.Token);
            if (available != null && !IsDisposed && !stopping && !zoteroActive) {
                if (updateWindow == null || updateWindow.IsDisposed) updateWindow = new WindowsUpdateWindow(InstallUpdateAsync,available);
                updateWindow.Show(this);
            }
        } catch (Exception error) when (error is HttpRequestException or IOException or OperationCanceledException) {
            // A startup check never interrupts work or claims a failed check succeeded.
        }
    }

    void ShowUpdates()
    {
        if (updateWindow == null || updateWindow.IsDisposed) updateWindow = new WindowsUpdateWindow(InstallUpdateAsync);
        updateWindow.Show(this); updateWindow.Activate();
    }

    async Task InstallUpdateAsync(WindowsUpdateRelease release, string path)
    {
        if (!File.Exists(Path.Combine(root, "service", "service_entry.py")) || !Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar).Equals(AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase))
            throw new IOException("Install updates from the installed Gewu Insight App, not a development window.");
        if (stopping || recoveringService || NativeHandoffBusy || origin == null || server == null)
            throw new IOException("Wait for current work to finish before installing.");
        await release.VerifyAsync(path, applicationLifetime.Token);
        string token = ""; bool stopRequested = false;
        stopping = true;
        workspace.Enabled = false;
        if (MainMenuStrip != null) MainMenuStrip.Enabled = false;
        zoteroTimer.Stop();
        try {
            using (var response = await client.PostAsync(new Uri(origin,"api/windows-update"), new StringContent("{\"action\":\"prepare\"}", Encoding.UTF8,"application/json"))) {
                using var json = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
                if (!response.IsSuccessStatusCode) throw new IOException(TextValue(json.RootElement,"error"));
                token = TextValue(json.RootElement,"token");
                if (token.Length < 20) throw new IOException("The service did not confirm a safe update.");
            }
            using (var response = await client.PostAsync(new Uri(origin,"api/windows-update"), new StringContent(JsonSerializer.Serialize(new { action="stop", token }),Encoding.UTF8,"application/json"))) {
                response.EnsureSuccessStatusCode(); stopRequested = true;
            }
            await server.WaitForExitAsync().WaitAsync(TimeSpan.FromSeconds(45));
            await release.VerifyAsync(path, applicationLifetime.Token);
            // Use the normal installer, retaining its confirmation and error UI.
            // It never force-closes database users; other open instances block it.
            var start = new ProcessStartInfo(path) { UseShellExecute = true };
            foreach (string arg in new[] { "/NORESTART", "/NOCLOSEAPPLICATIONS", "/NOFORCECLOSEAPPLICATIONS", "/DIR=" + root, "/DATABASEMODE=existing", "/DATABASEDIR=" + dataRoot }) start.ArgumentList.Add(arg);
            using var installer = Process.Start(start) ?? throw new IOException("Windows could not open the installer.");
            detachService = false; closeApproved = true;
            Close();
        } catch {
            if (token.Length > 0 && !stopRequested) {
                try { using var cancelled = await client.PostAsync(new Uri(origin,"api/windows-update"), new StringContent(JsonSerializer.Serialize(new {action="cancel",token}),Encoding.UTF8,"application/json")); }
                catch (HttpRequestException) { }
            }
            stopping = false;
            if (!IsDisposed) {
                workspace.Enabled = !zoteroActive;
                if (MainMenuStrip != null) MainMenuStrip.Enabled = !zoteroActive;
                zoteroTimer.Start();
                if (stopRequested && server.HasExited) await RecoverServiceAsync(server);
            }
            throw;
        }
    }
}

internal sealed class WindowsUpdateWindow : Form
{
    readonly Func<WindowsUpdateRelease,string,Task> install;
    readonly CancellationTokenSource lifetime = new();
    readonly HttpClient client = WindowsUpdateRelease.CreateClient();
    readonly Label title = new() { AutoSize=true, Dock=DockStyle.Fill, Margin=new Padding(0,0,0,12) };
    readonly Label message = new() { AutoSize=true, Dock=DockStyle.Fill, MaximumSize=new Size(500,0), Margin=new Padding(0,0,0,16), UseMnemonic=false };
    readonly ProgressBar progress = new() { Dock=DockStyle.Fill, Height=12, Visible=false, Margin=new Padding(0,0,0,16) };
    readonly Button action = new() { AutoSize=true, MinimumSize=new Size(150,36), Text="Check for Updates" };
    readonly Button close = new() { AutoSize=true, MinimumSize=new Size(100,36), Text="Close" };
    readonly LinkLabel notes = new() { Text="Release Notes", AutoSize=true, Visible=false, Margin=new Padding(0,0,0,16) };
    WindowsUpdateRelease? release;
    string downloaded = "";
    bool working;
    bool installing;
    internal static Version Current => Version.Parse(typeof(WindowsUpdateWindow).Assembly.GetCustomAttributes<AssemblyMetadataAttribute>().First(a=>a.Key=="GewuProductVersion").Value!);

    public WindowsUpdateWindow(Func<WindowsUpdateRelease,string,Task> install, WindowsUpdateRelease? available = null)
    {
        this.install = install;
        release = available;
        Text="Software Update"; StartPosition=FormStartPosition.CenterParent;
        AutoScaleMode=AutoScaleMode.Dpi; AutoScaleDimensions=new SizeF(96,96);
        Font=new Font("Segoe UI",11); FormBorderStyle=FormBorderStyle.FixedDialog;
        ShowInTaskbar=false; MaximizeBox=false; MinimizeBox=false;
        AutoSize=true; AutoSizeMode=AutoSizeMode.GrowAndShrink; MinimumSize=new Size(560,0);
        Icon=new Icon(Path.Combine(AppContext.BaseDirectory,"GewuInsight.ico"));
        var body=new TableLayoutPanel { ColumnCount=1, AutoSize=true, AutoSizeMode=AutoSizeMode.GrowAndShrink, Dock=DockStyle.Fill, Padding=new Padding(28), Width=560 };
        body.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100));
        title.Font=new Font("Segoe UI",16,FontStyle.Bold);
        title.Text="Gewu Insight for Windows";
        message.Text=$"Current version: {Current}\nCheck GitHub for the latest Windows release.";
        var buttons=new FlowLayoutPanel { AutoSize=true, Dock=DockStyle.Fill, FlowDirection=FlowDirection.RightToLeft, WrapContents=false, Margin=Padding.Empty };
        buttons.Controls.Add(action); buttons.Controls.Add(close);
        var automatic = new CheckBox { Text="Check automatically once a day", Checked=WindowsUpdatePreferences.Automatic, AutoSize=true, Margin=new Padding(0,0,0,16) };
        automatic.CheckedChanged+=(_,_)=>WindowsUpdatePreferences.SetAutomatic(automatic.Checked);
        foreach (Control control in new Control[]{title,message,notes,automatic,progress,buttons}) { body.RowStyles.Add(new RowStyle(SizeType.AutoSize)); body.Controls.Add(control,0,body.RowCount++); }
        Controls.Add(body); AcceptButton=action; CancelButton=close;
        close.Click+=(_,_)=>Close();
        notes.LinkClicked+=(_,_)=> { if(release!=null) Process.Start(new ProcessStartInfo(release.Page.AbsoluteUri){UseShellExecute=true}); };
        action.Click+=async(_,_)=>await ActAsync();
        Shown+=async(_,_)=> {
            if(release==null) await ActAsync();
            else { ShowAvailability(); action.Text="Download Update"; }
        };
        FormClosing+=(_,e)=> { if(installing && e.CloseReason==CloseReason.UserClosing) { e.Cancel=true; return; } lifetime.Cancel(); };
        FormClosed+=(_,_)=> { client.Dispose(); lifetime.Dispose(); title.Font.Dispose(); Font.Dispose(); };
    }

    void ShowAvailability()
    {
        message.Text=release==null ? $"You're up to date.\nGewu Insight {Current} is the latest Windows version." : $"Gewu Insight {release.Version} is available. You have {Current}.\nDownload size: {release.Bytes/1048576.0:F1} MB. Your Library and settings stay in their current database.";
        notes.Visible=release!=null;
    }

    async Task ActAsync()
    {
        if(working) return;
        working=true; action.Enabled=false;
        try {
            if(release==null) {
                message.Text="Checking GitHub for Windows updates…";
                using var timeout=CancellationTokenSource.CreateLinkedTokenSource(lifetime.Token);
                timeout.CancelAfter(TimeSpan.FromSeconds(45));
                WindowsUpdatePreferences.MarkChecked();
                release=await WindowsUpdateRelease.CheckAsync(client,Current,timeout.Token);
                if(IsDisposed) return;
                ShowAvailability();
            } else if(downloaded.Length==0) {
                progress.Visible=true; progress.Value=0;
                message.Text=$"Downloading Gewu Insight {release.Version}…";
                string directory=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Gewu Insight","Updates",release.Version.ToString());
                downloaded=await release.DownloadAsync(client,directory,new Progress<int>(value=> { if(!IsDisposed) progress.Value=value; }),lifetime.Token);
                if(IsDisposed) return;
                message.Text="Download verified. Installing closes Gewu after current work has finished. Follow Windows Setup, then leave Open Gewu Insight selected on its final page.\nClose Gewu tabs in Zotero before installing.";
            } else {
                installing=true; close.Enabled=false;
                await install(release,downloaded);
            }
        } catch(OperationCanceledException) {
            if(!IsDisposed) message.Text="Update check or download cancelled. You can try again.";
        } catch(Exception error) {
            if(!IsDisposed) message.Text="The update could not continue.\n"+error.Message;
        } finally {
            working=false; installing=false;
            if(!IsDisposed) { progress.Visible=false; action.Enabled=true; close.Enabled=true; action.Text=release==null?"Check for Updates":downloaded.Length==0?"Download Update":"Install Update"; }
        }
    }
}
