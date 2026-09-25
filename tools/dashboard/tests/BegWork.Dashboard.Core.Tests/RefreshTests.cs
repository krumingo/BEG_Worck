using System.Net;
using BegWork.Dashboard.Core.Config;
using BegWork.Dashboard.Core.Logging;
using BegWork.Dashboard.Core.Refresh;
using BegWork.Dashboard.Core.Sources;
using BegWork.Dashboard.Core.Validation;
using Xunit;

namespace BegWork.Dashboard.Core.Tests;

public sealed class RefreshTests
{
    private sealed class RecordingDelays : IDelayProvider
    {
        public List<TimeSpan> Delays { get; } = [];

        public Task DelayAsync(TimeSpan duration, CancellationToken cancellationToken)
        {
            Delays.Add(duration);
            return Task.CompletedTask;
        }
    }

    private sealed class ScriptedSource(params Func<ControlSnapshot>[] rounds) : ICoordinationSource
    {
        private int _index;

        public int Calls { get; private set; }

        public Task<ControlSnapshot> ReadAsync(CancellationToken cancellationToken)
        {
            Calls++;
            var round = rounds[Math.Min(_index++, rounds.Length - 1)];
            return Task.FromResult(round());
        }
    }

    private static RefreshScheduler Scheduler(
        ICoordinationSource source,
        IDelayProvider delays,
        DashboardSettings? settings = null,
        BackoffPolicy? backoff = null) =>
        new(source,
            settings ?? CoordinationFixture.Settings,
            backoff ?? new BackoffPolicy(TimeSpan.FromSeconds(10), TimeSpan.FromSeconds(120)),
            delays,
            NullLog.Instance);

    [Fact]
    public async Task SuccessfulRoundSchedulesTheNormalCadence()
    {
        var delays = new RecordingDelays();
        var scheduler = Scheduler(
            new ScriptedSource(CoordinationFixture.Published), delays);

        var wait = await scheduler.RunOnceAsync(CancellationToken.None);

        Assert.Equal(TimeSpan.FromSeconds(DashboardSettings.DefaultRefreshSeconds), wait);
        Assert.InRange(
            wait.TotalSeconds,
            DashboardSettings.MinimumRefreshSeconds,
            DashboardSettings.MaximumRefreshSeconds);
        Assert.False(scheduler.State.IsOffline);
        Assert.Equal(ControlStateStatus.Valid, scheduler.State.Latest!.Status);
    }

    [Fact]
    public async Task ConsecutiveFailuresBackOffAndStayBounded()
    {
        var delays = new RecordingDelays();
        var scheduler = Scheduler(
            new ScriptedSource(() => throw new HttpRequestException("network down")),
            delays,
            backoff: new BackoffPolicy(TimeSpan.FromSeconds(10), TimeSpan.FromSeconds(120)));

        var observed = new List<double>();
        for (var round = 0; round < 8; round++)
        {
            observed.Add((await scheduler.RunOnceAsync(CancellationToken.None)).TotalSeconds);
        }

        Assert.Equal([10, 20, 40, 80, 120, 120, 120, 120], observed);
        Assert.True(scheduler.State.IsOffline);
        Assert.Equal(8, scheduler.State.ConsecutiveFailures);
        Assert.Equal("network down", scheduler.State.LastError);
    }

    [Fact]
    public async Task ThrottlingHintIsHonouredButStillCapped()
    {
        var scheduler = Scheduler(
            new ScriptedSource(() => throw new GitHubThrottledException(
                TimeSpan.FromHours(1), "secondary rate limit")),
            new RecordingDelays(),
            backoff: new BackoffPolicy(TimeSpan.FromSeconds(10), TimeSpan.FromSeconds(120)));

        var wait = await scheduler.RunOnceAsync(CancellationToken.None);

        Assert.Equal(TimeSpan.FromSeconds(120), wait);
    }

    [Fact]
    public async Task AFailedRoundKeepsTheLastBoundSnapshotAndMarksItOffline()
    {
        var scheduler = Scheduler(
            new ScriptedSource(
                CoordinationFixture.Published,
                () => throw new HttpRequestException("offline")),
            new RecordingDelays());

        await scheduler.RunOnceAsync(CancellationToken.None);
        var good = scheduler.State.Latest;
        await scheduler.RunOnceAsync(CancellationToken.None);

        Assert.Same(good, scheduler.State.Latest);
        Assert.True(scheduler.State.IsOffline);
        Assert.Equal(CoordinationFixture.Now, scheduler.State.LastSuccessAt);

        var model = Projection.DashboardProjection.Project(new Projection.ProjectionInput
        {
            Verified = scheduler.State.Latest,
            Now = CoordinationFixture.Now.AddMinutes(5),
            IsOffline = scheduler.State.IsOffline,
            LastSuccessfulFetchAt = scheduler.State.LastSuccessAt,
            LastError = scheduler.State.LastError,
            Settings = CoordinationFixture.Settings,
        });

        Assert.Equal(ControlStateStatus.Stale, model.Banner.Status);
        Assert.True(model.Banner.IsOffline);
        Assert.True(model.HasContent);
    }

    [Fact]
    public async Task RecoveryAfterFailuresReturnsToTheNormalCadence()
    {
        var failFirst = true;
        var scheduler = Scheduler(
            new ScriptedSource(() =>
            {
                if (failFirst)
                {
                    failFirst = false;
                    throw new HttpRequestException("blip");
                }
                return CoordinationFixture.Published();
            }),
            new RecordingDelays());

        var backedOff = await scheduler.RunOnceAsync(CancellationToken.None);
        var recovered = await scheduler.RunOnceAsync(CancellationToken.None);

        Assert.Equal(TimeSpan.FromSeconds(10), backedOff);
        Assert.Equal(TimeSpan.FromSeconds(DashboardSettings.DefaultRefreshSeconds), recovered);
        Assert.Equal(0, scheduler.State.ConsecutiveFailures);
        Assert.False(scheduler.State.IsOffline);
    }

    [Fact]
    public async Task RunLoopStopsOnCancellation()
    {
        using var cancellation = new CancellationTokenSource();
        var source = new ScriptedSource(CoordinationFixture.Published);
        var scheduler = Scheduler(source, new StoppingDelays(cancellation, stopAfter: 3));

        await scheduler.RunAsync(cancellation.Token);

        Assert.Equal(3, source.Calls);
    }

    private sealed class StoppingDelays(CancellationTokenSource cancellation, int stopAfter) : IDelayProvider
    {
        private int _count;

        public Task DelayAsync(TimeSpan duration, CancellationToken cancellationToken)
        {
            if (++_count >= stopAfter)
            {
                cancellation.Cancel();
            }
            return Task.CompletedTask;
        }
    }

    [Fact]
    public void BackoffRejectsAMaximumBelowItsInitialDelay()
    {
        Assert.Throws<ArgumentOutOfRangeException>(
            () => new BackoffPolicy(TimeSpan.FromSeconds(30), TimeSpan.FromSeconds(10)));
    }

    [Fact]
    public void NoFailuresMeansNoBackoff()
    {
        Assert.Equal(TimeSpan.Zero, BackoffPolicy.Default.Next(0));
    }
}
