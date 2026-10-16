namespace BegWork.Dashboard.Core.Config;

public enum AutostartAction
{
    /// <summary>Leave the user's machine alone.</summary>
    NoAction = 0,
    Install = 1,
    Remove = 2,
}

/// <summary>Platform hook for the per-user Startup-folder shortcut.</summary>
public interface IAutostartInstaller
{
    bool IsInstalled();

    void Install();

    void Remove();
}

/// <summary>
/// Decides, and only then applies, autostart changes.
///
/// The rule is deliberately narrow: the dashboard touches the Startup folder only
/// when the persisted setting and the observed installation disagree. With the
/// shipped defaults (<see cref="DashboardSettings.Autostart"/> false, nothing
/// installed) the decision is <see cref="AutostartAction.NoAction"/>, so simply
/// running the dashboard can never enable autostart.
/// </summary>
public static class AutostartCoordinator
{
    public static AutostartAction Decide(bool wanted, bool installed) => (wanted, installed) switch
    {
        (true, false) => AutostartAction.Install,
        (false, true) => AutostartAction.Remove,
        _ => AutostartAction.NoAction,
    };

    public static AutostartAction Apply(DashboardSettings settings, IAutostartInstaller installer)
    {
        ArgumentNullException.ThrowIfNull(settings);
        ArgumentNullException.ThrowIfNull(installer);

        var action = Decide(settings.Autostart, installer.IsInstalled());
        switch (action)
        {
            case AutostartAction.Install:
                installer.Install();
                break;
            case AutostartAction.Remove:
                installer.Remove();
                break;
        }
        return action;
    }
}
