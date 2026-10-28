using System.Text.Json;

namespace GewuInsight.Windows;

// Per-computer updater preferences stay outside the research database.
internal static class WindowsUpdatePreferences
{
    sealed record State(bool Automatic = true, DateTime LastCheckUtc = default);
    static readonly string PathName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Gewu Insight","Updates","preferences.json");
    static State Read()
    {
        try { return JsonSerializer.Deserialize<State>(File.ReadAllText(PathName)) ?? new(); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException) { return new(); }
    }
    static void Save(State state)
    {
        try {
            Directory.CreateDirectory(Path.GetDirectoryName(PathName)!);
            string temporary = PathName + "." + Guid.NewGuid().ToString("N");
            try { File.WriteAllText(temporary,JsonSerializer.Serialize(state)); File.Move(temporary,PathName,true); }
            finally { if(File.Exists(temporary)) File.Delete(temporary); }
        } catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
    }
    public static bool Automatic => Read().Automatic;
    public static bool Due { get { var state=Read(); return state.Automatic && (DateTime.UtcNow-state.LastCheckUtc).TotalHours>=24; } }
    public static void SetAutomatic(bool value) => Save(Read() with { Automatic=value });
    public static void MarkChecked() => Save(Read() with { LastCheckUtc=DateTime.UtcNow });
}
