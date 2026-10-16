using BegWork.Dashboard.Core.Config;
using BegWork.Dashboard.Core.Logging;
using BegWork.Dashboard.Core.Projection;
using BegWork.Dashboard.Core.Refresh;
using BegWork.Dashboard.Core.Rendering;
using BegWork.Dashboard.Core.Sources;

namespace BegWork.Dashboard.Win.Hosting;

/// <summary>
/// Wires the read-only pipeline: poll, verify, project, render.
///
/// The host owns no UI. It hands a finished HTML fragment to whatever callback the
/// window supplies, which keeps every decision about what may be shown inside the
/// tested core and leaves the shell responsible only for placement and focus.
/// </summary>
internal sealed class DashboardHost : IDisposable
{
    private readonly GitHubReadOnlyClient _client;
    private readonly RefreshScheduler _scheduler;
    private readonly IRedactingLog _log;
    private readonly CancellationTokenSource _cancellation = new();
    private readonly List<string> _shellNotices = [];

    private Task? _loop;

    public DashboardHost(DashboardSettings settings, IRedactingLog log)
    {
        Settings = settings;
        _log = log;

        var tokens = new EnvironmentTokenProvider();
        _client = new GitHubReadOnlyClient(settings, tokens);
        var reader = new CoordinationReader(_client, settings, SystemClock.Instance);

        _scheduler = new RefreshScheduler(
            reader,
            settings,
            new BackoffPolicy(
                TimeSpan.FromSeconds(settings.EffectiveRefreshSeconds + 2),
                TimeSpan.FromSeconds(120)),
            TaskDelayProvider.Instance,
            log);

        _scheduler.Updated += _ => Publish();
    }

    public DashboardSettings Settings { get; }

    /// <summary>Called with a rendered HTML fragment whenever there is something new to show.</summary>
    public event Action<string>? FragmentReady;

    /// <summary>Records a shell-level condition (e.g. AppBar fallback) for the status banner.</summary>
    public void AddShellNotice(string notice)
    {
        if (!_shellNotices.Contains(notice, StringComparer.Ordinal))
        {
            _shellNotices.Add(notice);
            Publish();
        }
    }

    public void Start()
    {
        _loop ??= Task.Run(() => _scheduler.RunAsync(_cancellation.Token), _cancellation.Token);
        Publish();
    }

    /// <summary>Re-renders from the current refresh state without issuing a request.</summary>
    public void Publish()
    {
        var state = _scheduler.State;
        var model = DashboardProjection.Project(new ProjectionInput
        {
            Verified = state.Latest,
            Now = DateTimeOffset.UtcNow,
            IsOffline = state.IsOffline,
            LastSuccessfulFetchAt = state.LastSuccessAt,
            LastError = state.LastError,
            Settings = Settings,
            ShellNotices = _shellNotices,
        });

        try
        {
            FragmentReady?.Invoke(DashboardHtmlRenderer.RenderFragment(model));
        }
        catch (Exception exception)
        {
            _log.Error($"rendering failed: {exception.Message}");
        }
    }

    public void Dispose()
    {
        _cancellation.Cancel();
        try
        {
            _loop?.Wait(TimeSpan.FromSeconds(2));
        }
        catch (AggregateException)
        {
            // Cancellation during shutdown; nothing to report.
        }
        _cancellation.Dispose();
        _client.Dispose();
    }
}
