using System.Text.Json;
using System.Text.Json.Serialization;

namespace BegWork.Dashboard.Core.Model;

/// <summary>
/// Typed view over <c>coordination/CONTROL_STATE.json</c> (protocol v1).
///
/// The dashboard is a read-only consumer. Nothing in this namespace may mutate a
/// remote record; the type exists purely so the projection can be written against
/// named fields instead of ad-hoc JSON lookups. Binding happens only after the raw
/// document has passed <see cref="Validation.ControlStateSchemaValidator"/>, so the
/// required fields are known to exist by the time these properties are read.
/// </summary>
public sealed record ControlState
{
    [JsonPropertyName("protocol_version")] public int ProtocolVersion { get; init; }

    /// <summary>
    /// The status the producer persisted. This is an as-of-<see cref="ValidatedAt"/>
    /// claim, never live truth: the dashboard recomputes its own status and only ever
    /// takes the worse of the two. See <see cref="Validation.ControlStateVerifier"/>.
    /// </summary>
    [JsonPropertyName("control_state_status")] public string PersistedStatus { get; init; } = "";

    [JsonPropertyName("validated_at")] public string ValidatedAt { get; init; } = "";
    [JsonPropertyName("validation_mode")] public string ValidationMode { get; init; } = "";
    [JsonPropertyName("repository")] public string Repository { get; init; } = "";
    [JsonPropertyName("branch")] public string Branch { get; init; } = "";
    [JsonPropertyName("producer")] public string Producer { get; init; } = "";
    [JsonPropertyName("active_source_commit_sha")] public string ActiveSourceCommitSha { get; init; } = "";
    [JsonPropertyName("control_state_commit_sha")] public string? ControlStateCommitSha { get; init; }
    [JsonPropertyName("generated_from")] public IReadOnlyList<string> GeneratedFrom { get; init; } = [];
    [JsonPropertyName("task_id")] public string TaskId { get; init; } = "";
    [JsonPropertyName("cycle_id")] public string CycleId { get; init; } = "";
    [JsonPropertyName("cycle_origin")] public string CycleOrigin { get; init; } = "";
    [JsonPropertyName("current_agent")] public string CurrentAgent { get; init; } = "";
    [JsonPropertyName("current_role")] public string CurrentRole { get; init; } = "";

    /// <summary>
    /// The only authority for the three agent cards. Agent state is never inferred
    /// from <see cref="History"/>; history is evidence, not status.
    /// </summary>
    [JsonPropertyName("agent_states")] public IReadOnlyDictionary<string, AgentState> AgentStates { get; init; }
        = new Dictionary<string, AgentState>();

    [JsonPropertyName("current_work_id")] public string CurrentWorkId { get; init; } = "";
    [JsonPropertyName("state")] public string State { get; init; } = "";
    [JsonPropertyName("pipeline_step")] public string PipelineStep { get; init; } = "";
    [JsonPropertyName("next_agent")] public string NextAgent { get; init; } = "";
    [JsonPropertyName("waiting_for")] public string? WaitingFor { get; init; }
    [JsonPropertyName("wave")] public string Wave { get; init; } = "";
    [JsonPropertyName("flow")] public string Flow { get; init; } = "";
    [JsonPropertyName("pr_number")] public int? PrNumber { get; init; }
    [JsonPropertyName("pr_head_sha")] public string? PrHeadSha { get; init; }
    [JsonPropertyName("pr_draft")] public bool? PrDraft { get; init; }
    [JsonPropertyName("dispatch_state")] public string DispatchState { get; init; } = "";
    [JsonPropertyName("dispatch_run_url")] public string? DispatchRunUrl { get; init; }
    [JsonPropertyName("last_handoff")] public HandoffRef? LastHandoff { get; init; }
    [JsonPropertyName("last_review")] public ReviewRef? LastReview { get; init; }
    [JsonPropertyName("requires_krum")] public bool RequiresKrum { get; init; }
    [JsonPropertyName("requires_krum_reason")] public string? RequiresKrumReason { get; init; }
    [JsonPropertyName("progress")] public ProgressRef Progress { get; init; } = new();
    [JsonPropertyName("source_refs")] public SourceRefs SourceRefs { get; init; } = new();
    [JsonPropertyName("updated_at")] public string UpdatedAt { get; init; } = "";
    [JsonPropertyName("history")] public IReadOnlyList<HistoryEvent> History { get; init; } = [];

    public static readonly JsonSerializerOptions SerializerOptions = new()
    {
        PropertyNameCaseInsensitive = false,
        ReadCommentHandling = JsonCommentHandling.Disallow,
    };

    public static ControlState Bind(JsonElement root) =>
        root.Deserialize<ControlState>(SerializerOptions)
        ?? throw new InvalidOperationException("control state bound to null");
}

public sealed record AgentState
{
    [JsonPropertyName("state")] public string State { get; init; } = "";
    [JsonPropertyName("work_id")] public string? WorkId { get; init; }
    [JsonPropertyName("waiting_for")] public string? WaitingFor { get; init; }
    [JsonPropertyName("updated_at")] public string UpdatedAt { get; init; } = "";
}

public sealed record HandoffRef
{
    [JsonPropertyName("url")] public string Url { get; init; } = "";
    [JsonPropertyName("head_sha")] public string HeadSha { get; init; } = "";
    [JsonPropertyName("at")] public string At { get; init; } = "";
}

public sealed record ReviewRef
{
    [JsonPropertyName("path")] public string Path { get; init; } = "";
    [JsonPropertyName("blob_sha")] public string BlobSha { get; init; } = "";
    [JsonPropertyName("reviewed_head_sha")] public string ReviewedHeadSha { get; init; } = "";
    [JsonPropertyName("verdict")] public string Verdict { get; init; } = "";
}

public sealed record ProgressRef
{
    [JsonPropertyName("mode")] public string Mode { get; init; } = "";
    [JsonPropertyName("stage")] public string Stage { get; init; } = "";
    [JsonPropertyName("completed")] public int? Completed { get; init; }
    [JsonPropertyName("total")] public int? Total { get; init; }
    [JsonPropertyName("percent")] public int? Percent { get; init; }
}

public sealed record SourceRefs
{
    [JsonPropertyName("active_path")] public string ActivePath { get; init; } = "";
    [JsonPropertyName("active_blob_sha")] public string ActiveBlobSha { get; init; } = "";
    [JsonPropertyName("review_path")] public string? ReviewPath { get; init; }
    [JsonPropertyName("review_blob_sha")] public string? ReviewBlobSha { get; init; }
    [JsonPropertyName("handoff_comment_sha256")] public string? HandoffCommentSha256 { get; init; }
    [JsonPropertyName("canonical_docs")] public IReadOnlyList<CanonicalDoc> CanonicalDocs { get; init; } = [];
}

public sealed record CanonicalDoc
{
    [JsonPropertyName("path")] public string Path { get; init; } = "";
    [JsonPropertyName("blob_sha")] public string BlobSha { get; init; } = "";
}

public sealed record HistoryEvent
{
    [JsonPropertyName("event_id")] public string EventId { get; init; } = "";
    [JsonPropertyName("occurred_at")] public string OccurredAt { get; init; } = "";
    [JsonPropertyName("task_id")] public string TaskId { get; init; } = "";
    [JsonPropertyName("cycle_id")] public string? CycleId { get; init; }
    [JsonPropertyName("mapped_cycle")] public string? MappedCycle { get; init; }
    [JsonPropertyName("actor")] public string Actor { get; init; } = "";
    [JsonPropertyName("kind")] public string Kind { get; init; } = "";
    [JsonPropertyName("state_after")] public string? StateAfter { get; init; }
    [JsonPropertyName("head_sha")] public string? HeadSha { get; init; }
    [JsonPropertyName("source_url")] public string SourceUrl { get; init; } = "";
    [JsonPropertyName("source_commit_sha")] public string? SourceCommitSha { get; init; }
    [JsonPropertyName("summary")] public string Summary { get; init; } = "";
}
