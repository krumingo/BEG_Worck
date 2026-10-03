using BegWork.Dashboard.Core.Config;
using BegWork.Dashboard.Core.Logging;
using BegWork.Dashboard.Core.Sources;
using BegWork.Dashboard.Core.Validation;

namespace BegWork.Dashboard.Core.Refresh;

/// <summary>Observable state of the refresh loop, and the cache behind it.</summary>
public sealed record RefreshState
{
    /// <summary>Most recent snapshot that produced a bound state; survives failures.</summary>
    public VerifiedSnapshot? Latest { get; init; }

    public bool IsOffline { get; init; }

    public DateTimeOffset? LastSuccessAt { get; init; }

    public string? LastError { get; init; }

    public int ConsecutiveFailures { get; init; }

    public int Rounds { get; init; }

    public static readonly RefreshState Initial = new();
}

/// <summary>
/// Serial polling loop at the configured 5-10s cadence, with bounded backoff on
/// failure.
///
/// The loop never issues a write and never calls a model: it reads, verifies and
/// hands the result to the UI. On failure it keeps the last bound snapshot so the
/// panel can carry on showing it, explicitly marked offline and stale rather than
/// blanked, because "what was true 40 seconds ago, and it is 40 seconds old" is
/// more useful to an operator than an empty panel.
/// </summary>
public sealed class RefreshScheduler(
    ICoordinationSource source,
    DashboardSettings settings,
    BackoffPolicy backoff,
    IDelayProvider delays,
    IRedactingLog log)
{
    private RefreshState _state = RefreshState.Initial;

    public RefreshState State => _state;

    /// <summary>Raised after every round, successful or not.</summary>
    public event Action<RefreshState>? Updated;

    public async Task RunAsync(CancellationToken cancellationToken)
    {
        while (!cancellationToken.IsCancellationRequested)
        {
            var delay = await RunOnceAsync(cancellationToken).ConfigureAwait(false);

            try
            {
                await delays.DelayAsync(delay, cancellationToken).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return;
            }
        }
    }

    /// <summary>Runs one round and returns how long to wait before the next one.</summary>
    public async Task<TimeSpan> RunOnceAsync(CancellationToken cancellationToken)
    {
        try
        {
            var snapshot = await source.ReadAsync(cancellationToken).ConfigureAwait(false);
            var verified = ControlStateVerifier.Verify(snapshot, settings);

            _state = _state with
            {
                // A round that cannot bind a state keeps the previous one visible;
                // the banner reports the failure rather than the panel going blank.
                Latest = verified.State is null ? _state.Latest ?? verified : verified,
                IsOffline = false,
                LastSuccessAt = snapshot.FetchedAt,
                LastError = null,
                ConsecutiveFailures = 0,
                Rounds = _state.Rounds + 1,
            };

            log.Information(
                $"refresh round {_state.Rounds}: status {verified.Status.ToProtocolName()}");
            Updated?.Invoke(_state);
            return TimeSpan.FromSeconds(settings.EffectiveRefreshSeconds);
        }
        catch (OperationCanceledException)
        {
            throw;
        }
        catch (Exception exception)
        {
            var failures = _state.ConsecutiveFailures + 1;
            var retryAfter = (exception as GitHubThrottledException)?.RetryAfter;

            _state = _state with
            {
                IsOffline = true,
                LastError = exception.Message,
                ConsecutiveFailures = failures,
                Rounds = _state.Rounds + 1,
            };

            log.Warning($"refresh round {_state.Rounds} failed ({failures} in a row): {exception.Message}");
            Updated?.Invoke(_state);
            return backoff.Next(failures, retryAfter);
        }
    }
}
