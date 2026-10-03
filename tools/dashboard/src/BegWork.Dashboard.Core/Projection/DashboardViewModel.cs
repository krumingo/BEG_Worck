using BegWork.Dashboard.Core.Validation;

namespace BegWork.Dashboard.Core.Projection;

/// <summary>
/// Everything the panel is allowed to show, and nothing else.
///
/// The view model is produced only from a verified snapshot. Fields the read-model
/// cannot prove are null, and the renderer prints an explicit placeholder rather
/// than a plausible-looking value.
/// </summary>
public sealed record DashboardViewModel
{
    public string Product => "BEG_WORK";

    public required StatusBannerView Banner { get; init; }

    /// <summary>Null when no usable state could be verified; the panel then shows the empty state.</summary>
    public HeaderView? Header { get; init; }

    public IReadOnlyList<PipelineStepView> Pipeline { get; init; } = [];

    /// <summary>Exactly the three protocol agents, or empty when nothing is verified.</summary>
    public IReadOnlyList<AgentCardView> AgentCards { get; init; } = [];

    public ProgressView Progress { get; init; } = ProgressView.Unknown;

    public IReadOnlyList<ActivityEntryView> RecentActivity { get; init; } = [];

    public IReadOnlyList<TaskRowView> Tasks { get; init; } = [];

    /// <summary>Why the task list has the length it has; the read-model's own scope, stated.</summary>
    public string TaskListNote { get; init; } = "";

    public IReadOnlyList<EvidenceLinkView> Evidence { get; init; } = [];

    public string? EmptyStateMessage { get; init; }

    public bool HasContent => Header is not null;
}

/// <summary>The always-visible trust banner.</summary>
public sealed record StatusBannerView
{
    public required ControlStateStatus Status { get; init; }

    public string StatusText => Status.ToProtocolName();

    /// <summary>True only when this round verified everything; drives the "live" wording.</summary>
    public required bool IsLiveVerified { get; init; }

    public required bool IsOffline { get; init; }

    public DateTimeOffset? LastVerifiedAt { get; init; }

    public string? LastVerifiedAtText => LastVerifiedAt?.ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss'Z'");

    /// <summary>Age of the newest successful read, so an operator can judge staleness directly.</summary>
    public TimeSpan? Age { get; init; }

    public string? LastError { get; init; }

    public IReadOnlyList<VerificationFinding> Findings { get; init; } = [];

    /// <summary>Shell-level notices, e.g. AppBar registration fell back to overlay mode.</summary>
    public IReadOnlyList<string> ShellNotices { get; init; } = [];

    public string Headline => Status switch
    {
        ControlStateStatus.Valid when IsOffline => "VERIFIED SNAPSHOT — OFFLINE",
        ControlStateStatus.Valid => "LIVE VERIFIED",
        ControlStateStatus.Stale => "STALE — not live truth",
        ControlStateStatus.Conflict => "CONFLICT — sources disagree",
        _ => "INVALID — read-model unusable",
    };
}

public sealed record HeaderView
{
    public required string Wave { get; init; }
    public required string Flow { get; init; }
    public required string TaskId { get; init; }
    public required string CycleId { get; init; }
    public required string CycleOrigin { get; init; }
    public required string WorkId { get; init; }

    /// <summary>Raw protocol state, e.g. BLOCKED.</summary>
    public required string State { get; init; }

    /// <summary>
    /// State as it may be shown. An unverified snapshot never presents a bare PASS;
    /// it is suffixed so no reader can mistake it for a live verdict.
    /// </summary>
    public required string StateDisplay { get; init; }

    public required string CurrentAgent { get; init; }
    public required string CurrentRole { get; init; }
    public required string NextAgent { get; init; }
    public string? WaitingFor { get; init; }
    public required bool KrumActionRequired { get; init; }
    public string? KrumActionReason { get; init; }
    public required string DispatchState { get; init; }
    public required string Producer { get; init; }
    public required string Repository { get; init; }
    public required string Branch { get; init; }
    public required string SnapshotValidatedAt { get; init; }
    public required string SourceUpdatedAt { get; init; }

    public string KrumActionText => KrumActionRequired
        ? $"REQUIRED — {KrumActionReason}"
        : "NONE";
}

public sealed record PipelineStepView(
    int Ordinal,
    string Step,
    string Agent,
    string Label,
    bool IsActive,
    /// <summary>An active step on an unverified snapshot is drawn as unconfirmed.</summary>
    bool IsActiveVerified);

/// <summary>
/// One agent card. Built only from <c>agent_states</c>; history never contributes,
/// because the last event an agent produced is not the state it is in now.
/// </summary>
public sealed record AgentCardView(
    string Agent,
    string DisplayName,
    string Role,
    string State,
    string? WorkId,
    string? WaitingFor,
    string UpdatedAt,
    bool IsCurrent);

public sealed record ProgressView
{
    public string? Mode { get; init; }
    public string? Stage { get; init; }
    public int? Completed { get; init; }
    public int? Total { get; init; }
    public int? Percent { get; init; }

    /// <summary>True when the read-model proves no percentage; the UI must show none.</summary>
    public bool HasProvenPercentage => Percent is not null;

    public string? CountsText => Completed is { } completed && Total is { } total
        ? $"{completed} / {total}"
        : null;

    public string PercentText => Percent is { } percent ? $"{percent}%" : "no proven percentage";

    public static readonly ProgressView Unknown = new();
}

public sealed record ActivityEntryView(
    string OccurredAt,
    string Kind,
    string Actor,
    string? StateAfter,
    string CycleLabel,
    string? HeadShaShort,
    string SourceUrl,
    string Summary);

public sealed record TaskRowView(
    string TaskId,
    string Wave,
    string Flow,
    string CycleId,
    string State,
    string CurrentAgent,
    string StageText,
    string? PercentText,
    string UpdatedAt);

public sealed record EvidenceLinkView(string Label, string Detail, string? Url);
