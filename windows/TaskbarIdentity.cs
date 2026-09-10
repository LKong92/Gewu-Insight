using System.Runtime.InteropServices;

namespace GewuInsight.Windows;

internal static class TaskbarIdentity
{
    // Keep this stable across releases and match the installer shortcut. Without
    // it, Explorer infers the group from the executable and can retain the old
    // padded macOS artwork after an in-place upgrade.
    internal const string AppId = "GewuInsight.Windows.Preview";

    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
    static extern int SetCurrentProcessExplicitAppUserModelID(string appId);

    internal static void Initialize() =>
        Marshal.ThrowExceptionForHR(SetCurrentProcessExplicitAppUserModelID(AppId));
}
