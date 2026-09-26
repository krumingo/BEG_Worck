using System.Diagnostics;
using System.IO;
using BegWork.Dashboard.Core.Config;
using BegWork.Dashboard.Core.Logging;

namespace BegWork.Dashboard.Win.Hosting;

/// <summary>
/// Per-user autostart via a shortcut in the Startup folder.
///
/// Deliberately the Startup folder and not a Run registry key or a service: it
/// needs no elevation, it is visible to the user in a place they already know, and
/// they can delete it without the dashboard's cooperation.
///
/// Nothing here runs unless <see cref="DashboardSettings.Autostart"/> is true, and
/// that setting ships false. Installing autostart is a separate, explicit decision.
/// </summary>
internal sealed class StartupFolderAutostartInstaller(IRedactingLog log) : IAutostartInstaller
{
    private const string ShortcutName = "BEG_WORK Dashboard.lnk";

    private static string ShortcutPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.Startup), ShortcutName);

    public bool IsInstalled() => File.Exists(ShortcutPath);

    public void Install()
    {
        var target = Environment.ProcessPath;
        if (string.IsNullOrEmpty(target))
        {
            log.Warning("autostart not installed: the executable path is unknown.");
            return;
        }

        try
        {
            // WScript.Shell through COM is the dependency-free way to write a .lnk;
            // it is resolved late so the type is not needed unless autostart is on.
            var shellType = Type.GetTypeFromProgID("WScript.Shell")
                            ?? throw new InvalidOperationException("WScript.Shell is unavailable.");
            dynamic shell = Activator.CreateInstance(shellType)!;
            dynamic shortcut = shell.CreateShortcut(ShortcutPath);
            shortcut.TargetPath = target;
            shortcut.WorkingDirectory = Path.GetDirectoryName(target);
            shortcut.Description = "BEG_WORK control panel (read-only)";
            shortcut.Save();
            log.Information("autostart shortcut installed.");
        }
        catch (Exception exception)
        {
            log.Warning($"autostart shortcut could not be created ({exception.GetType().Name}).");
        }
    }

    public void Remove()
    {
        try
        {
            if (File.Exists(ShortcutPath))
            {
                File.Delete(ShortcutPath);
                log.Information("autostart shortcut removed.");
            }
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            log.Warning($"autostart shortcut could not be removed ({exception.GetType().Name}).");
        }
    }

    /// <summary>Opens the Startup folder so the user can see exactly what is installed.</summary>
    public static void RevealStartupFolder() => Process.Start(new ProcessStartInfo
    {
        FileName = Environment.GetFolderPath(Environment.SpecialFolder.Startup),
        UseShellExecute = true,
    });
}
