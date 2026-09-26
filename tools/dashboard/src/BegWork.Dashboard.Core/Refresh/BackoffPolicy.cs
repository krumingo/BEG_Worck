namespace BegWork.Dashboard.Core.Refresh;

/// <summary>
/// Bounded exponential backoff for failed reads.
///
/// Bounded in both directions on purpose: it must back off far enough that a
/// rate-limited or offline dashboard stops hammering the API, and cap low enough
/// that the panel recovers on its own within a couple of minutes once the network
/// returns, without anyone restarting it.
/// </summary>
public sealed class BackoffPolicy(TimeSpan initial, TimeSpan maximum, int maximumDoublings = 6)
{
    public TimeSpan Initial { get; } = initial > TimeSpan.Zero
        ? initial
        : throw new ArgumentOutOfRangeException(nameof(initial));

    public TimeSpan Maximum { get; } = maximum >= initial
        ? maximum
        : throw new ArgumentOutOfRangeException(nameof(maximum));

    public int MaximumDoublings { get; } = Math.Clamp(maximumDoublings, 1, 16);

    public static BackoffPolicy Default => new(TimeSpan.FromSeconds(10), TimeSpan.FromSeconds(120));

    /// <param name="consecutiveFailures">1 for the first failure.</param>
    /// <param name="retryAfter">Server-supplied hint; honoured but still capped.</param>
    public TimeSpan Next(int consecutiveFailures, TimeSpan? retryAfter = null)
    {
        if (consecutiveFailures <= 0)
        {
            return TimeSpan.Zero;
        }

        var doublings = Math.Min(consecutiveFailures - 1, MaximumDoublings);
        var scaled = TimeSpan.FromTicks(Initial.Ticks * (1L << doublings));
        var delay = scaled > Maximum ? Maximum : scaled;

        if (retryAfter is { } hint && hint > delay)
        {
            delay = hint > Maximum ? Maximum : hint;
        }

        return delay;
    }
}
