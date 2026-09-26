using System.IO;
using System.Windows;
using BegWork.Dashboard.Core.Config;
using BegWork.Dashboard.Core.Logging;
using BegWork.Dashboard.Core.Sources;
using BegWork.Dashboard.Win.Hosting;

namespace BegWork.Dashboard.Win.Shell;

/// <summary>
/// Entry point. Constructed in code rather than from App.xaml so the whole startup
/// order — single instance, settings, logging, autostart decision, window — is
/// visible in one place.
/// </summary>
internal static class Program
{
    [STAThread]
    public static int Main()
    {
        using var instance = SingleInstance.Acquire();
        if (!instance.IsFirstInstance)
        {
            // A second launch is a request to see the panel, not to run another one.
            instance.SignalExistingInstance();
            return 0;
        }

        var log = CreateLog();
        var settings = SettingsStore.Load(log);

        // Autostart is applied from the persisted setting only. With the shipped
        // defaults this is a no-op: starting the dashboard never installs itself.
        var action = AutostartCoordinator.Apply(settings, new StartupFolderAutostartInstaller(log));
        log.Information($"autostart setting={settings.Autostart}, action={action}");

        using var host = new DashboardHost(settings, log);
        // Explicit shutdown: Escape hides the panel, it does not end the session.
        var application = new Application { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        var window = new DashboardWindow(settings, host, log);

        instance.OnShowRequested(window.RevealWithoutStealingFocus);

        application.MainWindow = window;
        // Show() on a window with ShowActivated=false does not take focus.
        window.Show();
        host.Start();

        window.Closed += (_, _) => application.Shutdown();

        return application.Run();
    }

    private static IRedactingLog CreateLog()
    {
        var directory = Path.Combine(SettingsStore.Directory, "logs");
        try
        {
            Directory.CreateDirectory(directory);
            var path = Path.Combine(directory, $"dashboard-{DateTime.UtcNow:yyyyMMdd}.log");
            return new RedactingLog(
                line =>
                {
                    try
                    {
                        File.AppendAllText(path, line + Environment.NewLine);
                    }
                    catch (IOException)
                    {
                        // A log that cannot be written must not take the panel down.
                    }
                },
                new EnvironmentTokenSecret());
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException)
        {
            return NullLog.Instance;
        }
    }

    /// <summary>Lets the log sink recognise and mask the exact configured token.</summary>
    private sealed class EnvironmentTokenSecret : IGitHubTokenSecret
    {
        private readonly EnvironmentTokenProvider _provider = new();

        public string? GetToken() => _provider.GetToken();
    }
}
