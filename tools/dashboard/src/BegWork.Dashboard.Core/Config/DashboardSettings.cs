using System.Text.Json.Serialization;

namespace BegWork.Dashboard.Core.Config;

/// <summary>
/// Per-user dashboard configuration. Every field has a safe default so a missing
/// or partial settings file still yields a usable, non-privileged panel.
/// </summary>
public sealed record DashboardSettings
{
    public const int MinimumWidth = 420;
    public const int MaximumWidth = 500;
    public const int DefaultWidth = 460;

    public const int MinimumRefreshSeconds = 5;
    public const int MaximumRefreshSeconds = 10;
    public const int DefaultRefreshSeconds = 8;

    [JsonPropertyName("repository")] public string Repository { get; init; } = "krumingo/BEG_Worck";

    /// <summary>The coordination branch the read-model is published on.</summary>
    [JsonPropertyName("branch")] public string Branch { get; init; } = "codex/claude-queue";

    /// <summary>Panel width in logical pixels; always clamped to 420-500.</summary>
    [JsonPropertyName("width")] public int Width { get; init; } = DefaultWidth;

    /// <summary>Normal poll cadence in seconds; always clamped to 5-10.</summary>
    [JsonPropertyName("refresh_seconds")] public int RefreshSeconds { get; init; } = DefaultRefreshSeconds;

    /// <summary>
    /// Per-user autostart. OFF by default and never turned on implicitly: enabling
    /// it installs a Startup-folder shortcut, which is a user decision, not a
    /// side effect of running the dashboard once.
    /// </summary>
    [JsonPropertyName("autostart")] public bool Autostart { get; init; }

    /// <summary>
    /// Zero-based index of the monitor to dock against; out-of-range falls back to
    /// the primary monitor at runtime.
    /// </summary>
    [JsonPropertyName("monitor_index")] public int MonitorIndex { get; init; }

    /// <summary>
    /// Register a right-edge Windows AppBar that reserves desktop space. When
    /// registration fails the shell falls back to a topmost overlay instead.
    /// </summary>
    [JsonPropertyName("reserve_desktop_space")] public bool ReserveDesktopSpace { get; init; } = true;

    /// <summary>How many recent history events the activity list shows.</summary>
    [JsonPropertyName("recent_activity_count")] public int RecentActivityCount { get; init; } = 6;

    /// <summary>
    /// After this many seconds without a successful read the cached snapshot is
    /// shown as STALE. Defaults to four normal cadences plus a grace period.
    /// </summary>
    [JsonPropertyName("stale_after_seconds")] public int StaleAfterSeconds { get; init; } = 45;

    public int EffectiveWidth => Math.Clamp(Width, MinimumWidth, MaximumWidth);

    public int EffectiveRefreshSeconds =>
        Math.Clamp(RefreshSeconds, MinimumRefreshSeconds, MaximumRefreshSeconds);

    public int EffectiveStaleAfterSeconds =>
        Math.Max(StaleAfterSeconds, EffectiveRefreshSeconds * 2);

    public int EffectiveRecentActivityCount => Math.Clamp(RecentActivityCount, 1, 25);

    public string Owner => Repository.Split('/', 2)[0];

    public string Name => Repository.Contains('/') ? Repository.Split('/', 2)[1] : Repository;

    public static DashboardSettings Default => new();
}
