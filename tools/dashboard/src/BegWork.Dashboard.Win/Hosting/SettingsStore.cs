using System.IO;
using System.Text.Json;
using BegWork.Dashboard.Core.Config;
using BegWork.Dashboard.Core.Logging;

namespace BegWork.Dashboard.Win.Hosting;

/// <summary>
/// Per-user settings in <c>%APPDATA%\BEG_Work\dashboard\settings.json</c>.
///
/// A missing, unreadable or malformed file yields the defaults rather than an
/// error dialog: the dashboard's job is to be on screen, and its defaults are safe
/// (autostart off, 460 px, 8 s cadence).
/// </summary>
internal static class SettingsStore
{
    private static readonly JsonSerializerOptions Options = new() { WriteIndented = true };

    public static string Directory => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
        "BEG_Work",
        "dashboard");

    public static string FilePath => System.IO.Path.Combine(Directory, "settings.json");

    public static DashboardSettings Load(IRedactingLog log)
    {
        try
        {
            if (!File.Exists(FilePath))
            {
                return DashboardSettings.Default;
            }

            return JsonSerializer.Deserialize<DashboardSettings>(File.ReadAllText(FilePath))
                   ?? DashboardSettings.Default;
        }
        catch (Exception exception) when (exception is IOException or JsonException or UnauthorizedAccessException)
        {
            log.Warning($"settings could not be read ({exception.GetType().Name}); using defaults.");
            return DashboardSettings.Default;
        }
    }

    public static void Save(DashboardSettings settings, IRedactingLog log)
    {
        try
        {
            System.IO.Directory.CreateDirectory(Directory);
            File.WriteAllText(FilePath, JsonSerializer.Serialize(settings, Options));
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            log.Warning($"settings could not be written ({exception.GetType().Name}).");
        }
    }
}
