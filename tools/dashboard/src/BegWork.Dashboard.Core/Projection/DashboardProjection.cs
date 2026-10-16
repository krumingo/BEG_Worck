using BegWork.Dashboard.Core.Config;
using BegWork.Dashboard.Core.Model;
using BegWork.Dashboard.Core.Validation;

namespace BegWork.Dashboard.Core.Projection;

/// <summary>Inputs the projection needs beyond the snapshot itself.</summary>
public sealed record ProjectionInput
{
    /// <summary>Newest snapshot that produced a bound state; may be a cached one.</summary>
    public VerifiedSnapshot? Verified { get; init; }

    public required DateTimeOffset Now { get; init; }

    /// <summary>The most recent poll attempt failed, so the panel is showing cache.</summary>
    public bool IsOffline { get; init; }

    public DateTimeOffset? LastSuccessfulFetchAt { get; init; }

    public string? LastError { get; init; }

    public required DashboardSettings Settings { get; init; }

    public IReadOnlyList<string> ShellNotices { get; init; } = [];
}

/// <summary>
/// Turns a verified snapshot into the panel's view model.
///
/// Two rules shape everything here. Agent cards come from <c>agent_states</c> only,
/// never from <c>history</c>. Progress comes from the validated <c>progress</c>
/// object only, so a snapshot that proves no percentage produces no percentage.
/// </summary>
public static class DashboardProjection
{
    private static readonly (string Agent, string Display, string Role)[] Agents =
    [
        ("GPT", "ChatGPT", "Architect"),
        ("CODEX", "Codex", "Tech Lead · QA"),
        ("CLAUDE", "Claude", "Implementer"),
    ];

    private static readonly (string Step, string Agent, string Label)[] PipelineRoute =
    [
        ("ARCHITECT", "GPT", "ChatGPT · Architect"),
        ("ASSIGNMENT", "CODEX", "Codex · Assignment"),
        ("IMPLEMENTATION", "CLAUDE", "Claude · Implementation"),
        ("REVIEW", "CODEX", "Codex · Review"),
        ("ARCHITECT_FEEDBACK", "GPT", "ChatGPT · Feedback"),
    ];

    public static DashboardViewModel Project(ProjectionInput input)
    {
        ArgumentNullException.ThrowIfNull(input);

        var staleness = Staleness(input);
        var verified = input.Verified;

        if (verified?.State is not { } state)
        {
            return new DashboardViewModel
            {
                Banner = Banner(input, staleness, verified?.Result, isLive: false),
                EmptyStateMessage = verified is null
                    ? "No control-state snapshot has been verified yet. The panel shows nothing until one is."
                    : "The published control state could not be verified. Showing no projected state is the correct result.",
                TaskListNote = "No task list: the read-model proved no task.",
            };
        }

        var status = Worse(verified.Result.Status, staleness);
        var isLive = status == ControlStateStatus.Valid && !input.IsOffline;

        return new DashboardViewModel
        {
            Banner = Banner(input, staleness, verified.Result, isLive),
            Header = BuildHeader(state, isLive),
            Pipeline = BuildPipeline(state, isLive),
            AgentCards = BuildAgentCards(state),
            Progress = BuildProgress(state),
            RecentActivity = BuildActivity(state, input.Settings.EffectiveRecentActivityCount),
            Tasks = BuildTasks(state),
            TaskListNote =
                "Protocol v1 publishes the active task only, so this read-model proves exactly one task row.",
            Evidence = BuildEvidence(state),
        };
    }

    /// <summary>
    /// Staleness derived from wall-clock age of the last successful read, not from
    /// the snapshot's own <c>validated_at</c>: a genuinely blocked task can sit
    /// untouched for days without the panel being out of date about it.
    /// </summary>
    private static ControlStateStatus Staleness(ProjectionInput input)
    {
        if (input.LastSuccessfulFetchAt is not { } fetched)
        {
            return input.Verified is null ? ControlStateStatus.Valid : ControlStateStatus.Stale;
        }

        var age = input.Now - fetched;
        return age > TimeSpan.FromSeconds(input.Settings.EffectiveStaleAfterSeconds)
            ? ControlStateStatus.Stale
            : ControlStateStatus.Valid;
    }

    private static StatusBannerView Banner(
        ProjectionInput input,
        ControlStateStatus staleness,
        VerificationResult? result,
        bool isLive)
    {
        var findings = new List<VerificationFinding>(result?.Findings ?? []);
        var age = input.LastSuccessfulFetchAt is { } fetched ? input.Now - fetched : (TimeSpan?)null;

        if (staleness == ControlStateStatus.Stale)
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Stale,
                "SNAPSHOT_AGE",
                age is { } observed
                    ? $"Last successful read was {(int)observed.TotalSeconds}s ago, beyond the {input.Settings.EffectiveStaleAfterSeconds}s stale threshold."
                    : "No successful read yet in this session."));
        }

        var status = Worse(result?.Status ?? ControlStateStatus.Invalid, staleness);

        return new StatusBannerView
        {
            Status = status,
            IsLiveVerified = isLive,
            IsOffline = input.IsOffline,
            LastVerifiedAt = input.LastSuccessfulFetchAt,
            Age = age,
            LastError = input.LastError,
            Findings = findings,
            ShellNotices = input.ShellNotices,
        };
    }

    private static HeaderView BuildHeader(ControlState state, bool isLive) => new()
    {
        Wave = state.Wave,
        Flow = state.Flow,
        TaskId = state.TaskId,
        CycleId = state.CycleId,
        CycleOrigin = state.CycleOrigin,
        WorkId = state.CurrentWorkId,
        State = state.State,
        // An unverified snapshot must never present PASS (or any verdict) as live.
        StateDisplay = isLive ? state.State : $"{state.State} (UNVERIFIED)",
        CurrentAgent = state.CurrentAgent,
        CurrentRole = state.CurrentRole,
        NextAgent = state.NextAgent,
        WaitingFor = state.WaitingFor,
        KrumActionRequired = state.RequiresKrum,
        KrumActionReason = state.RequiresKrumReason,
        DispatchState = state.DispatchState,
        Producer = state.Producer,
        Repository = state.Repository,
        Branch = state.Branch,
        SnapshotValidatedAt = state.ValidatedAt,
        SourceUpdatedAt = state.UpdatedAt,
    };

    private static IReadOnlyList<PipelineStepView> BuildPipeline(ControlState state, bool isLive) =>
        PipelineRoute
            .Select((step, index) =>
            {
                var active = string.Equals(step.Step, state.PipelineStep, StringComparison.Ordinal);
                return new PipelineStepView(
                    index + 1, step.Step, step.Agent, step.Label, active, active && isLive);
            })
            .ToList();

    private static IReadOnlyList<AgentCardView> BuildAgentCards(ControlState state) =>
        Agents
            .Select(agent =>
            {
                // Explicit agent_states only. If the producer did not publish a card
                // for an agent, the panel says UNKNOWN rather than reading history.
                var published = state.AgentStates.TryGetValue(agent.Agent, out var value) ? value : null;
                return new AgentCardView(
                    agent.Agent,
                    agent.Display,
                    agent.Role,
                    published?.State ?? "UNKNOWN",
                    published?.WorkId,
                    published?.WaitingFor,
                    published?.UpdatedAt ?? "—",
                    string.Equals(agent.Agent, state.CurrentAgent, StringComparison.Ordinal));
            })
            .ToList();

    private static ProgressView BuildProgress(ControlState state) => new()
    {
        Mode = state.Progress.Mode,
        Stage = state.Progress.Stage,
        Completed = state.Progress.Completed,
        Total = state.Progress.Total,
        Percent = state.Progress.Percent,
    };

    private static IReadOnlyList<ActivityEntryView> BuildActivity(ControlState state, int take) =>
        state.History
            .OrderByDescending(item =>
                ControlStateSchemaValidator.TryParseOffset(item.OccurredAt, out var at)
                    ? at
                    : DateTimeOffset.MinValue)
            .ThenByDescending(item => item.EventId, StringComparer.Ordinal)
            .Take(take)
            .Select(item => new ActivityEntryView(
                item.OccurredAt,
                item.Kind,
                item.Actor,
                item.StateAfter,
                item.CycleId ?? (item.MappedCycle is { } mapped ? $"{mapped} (mapped)" : "—"),
                item.HeadSha is { Length: >= 8 } head ? head[..8] : item.HeadSha,
                item.SourceUrl,
                item.Summary))
            .ToList();

    private static IReadOnlyList<TaskRowView> BuildTasks(ControlState state) =>
    [
        new TaskRowView(
            state.TaskId,
            state.Wave,
            state.Flow,
            state.CycleId,
            state.State,
            state.CurrentAgent,
            state.Progress.Stage,
            state.Progress.Percent is { } percent ? $"{percent}%" : null,
            state.UpdatedAt),
    ];

    private static IReadOnlyList<EvidenceLinkView> BuildEvidence(ControlState state)
    {
        var repositoryUrl = $"https://github.com/{state.Repository}";
        var evidence = new List<EvidenceLinkView>
        {
            new("ACTIVE",
                $"{state.SourceRefs.ActivePath} · blob {Short(state.SourceRefs.ActiveBlobSha)} · commit {Short(state.ActiveSourceCommitSha)}",
                $"{repositoryUrl}/blob/{state.ActiveSourceCommitSha}/{state.SourceRefs.ActivePath}"),
        };

        if (state.LastReview is { } review)
        {
            evidence.Add(new EvidenceLinkView(
                "Review",
                $"{review.Path} · blob {Short(review.BlobSha)} · verdict {review.Verdict} on {Short(review.ReviewedHeadSha)}",
                $"{repositoryUrl}/blob/{review.ReviewedHeadSha}/{review.Path}"));
        }

        if (state.PrNumber is { } prNumber)
        {
            evidence.Add(new EvidenceLinkView(
                state.PrDraft == true ? "Draft PR" : "PR",
                $"#{prNumber} · exact head {Short(state.PrHeadSha)}",
                $"{repositoryUrl}/pull/{prNumber}"));
        }

        if (state.LastHandoff is { } handoff)
        {
            evidence.Add(new EvidenceLinkView(
                "HANDOFF", $"head {Short(handoff.HeadSha)} · {handoff.At}", handoff.Url));
        }

        evidence.Add(new EvidenceLinkView(
            "Dispatch", state.DispatchState, state.DispatchRunUrl));

        foreach (var document in state.SourceRefs.CanonicalDocs)
        {
            evidence.Add(new EvidenceLinkView(
                "Canonical", $"{document.Path} @ {Short(document.BlobSha)}", null));
        }

        return evidence;
    }

    private static string Short(string? sha) =>
        string.IsNullOrEmpty(sha) ? "—" : sha.Length <= 8 ? sha : sha[..8];

    private static ControlStateStatus Worse(ControlStateStatus left, ControlStateStatus right) =>
        (ControlStateStatus)Math.Max((int)left, (int)right);
}
