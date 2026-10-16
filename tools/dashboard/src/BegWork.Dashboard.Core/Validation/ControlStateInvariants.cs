using BegWork.Dashboard.Core.Model;

namespace BegWork.Dashboard.Core.Validation;

/// <summary>
/// Semantic invariants of protocol v1, ported from
/// <c>tools/control_engine.py:validate_state</c>.
///
/// The producer's validator throws on the first violation; the dashboard instead
/// collects every finding, because an operator staring at a panel needs to see all
/// the reasons a snapshot is untrustworthy, not just the first one. The verdicts
/// (INVALID / CONFLICT / STALE) are kept identical to the producer's so the two
/// implementations cannot disagree about severity.
/// </summary>
public static class ControlStateInvariants
{
    private static readonly IReadOnlyDictionary<string, string> WorkIdSuffix =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["GPT"] = "GPT",
            ["CODEX"] = "CX",
            ["CLAUDE"] = "CL",
        };

    private static readonly IReadOnlyDictionary<string, string> AgentRole =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["GPT"] = "ARCHITECT",
            ["CODEX"] = "TECH_LEAD_QA",
            ["CLAUDE"] = "IMPLEMENTER",
        };

    private static readonly IReadOnlyDictionary<string, string> StepAgent =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["ARCHITECT"] = "GPT",
            ["ASSIGNMENT"] = "CODEX",
            ["IMPLEMENTATION"] = "CLAUDE",
            ["REVIEW"] = "CODEX",
            ["ARCHITECT_FEEDBACK"] = "GPT",
        };

    public static VerificationResult Validate(ControlState state)
    {
        var findings = new List<VerificationFinding>();

        CheckPersistedStatus(state, findings);
        CheckTimestamps(state, findings);
        CheckIdentity(state, findings);
        CheckAgentStates(state, findings);
        CheckWaitingAndKrum(state, findings);
        CheckEvidence(state, findings);
        CheckHistory(state, findings);
        CheckProgress(state, findings);

        return VerificationResult.From(findings);
    }

    private static void CheckPersistedStatus(ControlState state, List<VerificationFinding> findings)
    {
        var persisted = ControlStateStatusText.Parse(state.PersistedStatus);
        if (persisted != ControlStateStatus.Valid)
        {
            findings.Add(new VerificationFinding(
                persisted,
                "PERSISTED_STATUS",
                $"Producer published control_state_status = {state.PersistedStatus}."));
        }

        // A snapshot validated against fixtures is never evidence about the live repo.
        if (state.ValidationMode == "SYNTHETIC_TEST")
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Conflict,
                "SYNTHETIC_SNAPSHOT",
                "Snapshot was produced in SYNTHETIC_TEST mode and is not live evidence."));
        }
    }

    private static void CheckTimestamps(ControlState state, List<VerificationFinding> findings)
    {
        if (!ControlStateSchemaValidator.TryParseOffset(state.ValidatedAt, out var validated)
            || !ControlStateSchemaValidator.TryParseOffset(state.UpdatedAt, out var updated))
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Invalid, "TIMESTAMP", "validated_at or updated_at is not parseable."));
            return;
        }

        if (validated < updated)
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Invalid, "VALIDATION_PREDATES_SOURCE",
                "Validation predates the source update it claims to cover."));
        }
    }

    private static void CheckIdentity(ControlState state, List<VerificationFinding> findings)
    {
        if (!WorkIdSuffix.TryGetValue(state.CurrentAgent, out var suffix))
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Invalid, "CURRENT_AGENT", $"Unknown current_agent {state.CurrentAgent}."));
            return;
        }

        var expectedWorkId = $"{state.TaskId}/{state.CycleId}/{suffix}";
        if (!string.Equals(state.CurrentWorkId, expectedWorkId, StringComparison.Ordinal))
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Invalid, "WORK_ID",
                $"current_work_id {state.CurrentWorkId} does not match {expectedWorkId}."));
        }

        if (!string.Equals(state.CurrentRole, AgentRole[state.CurrentAgent], StringComparison.Ordinal))
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Invalid, "ROLE", "current_role does not match current_agent."));
        }

        if (!StepAgent.TryGetValue(state.PipelineStep, out var stepAgent))
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Invalid, "PIPELINE_STEP", $"Unknown pipeline_step {state.PipelineStep}."));
        }
        else if (!string.Equals(state.CurrentAgent, stepAgent, StringComparison.Ordinal))
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Invalid, "PIPELINE_AGENT",
                $"pipeline_step {state.PipelineStep} belongs to {stepAgent}, not {state.CurrentAgent}."));
        }
    }

    private static void CheckAgentStates(ControlState state, List<VerificationFinding> findings)
    {
        var agents = state.AgentStates;
        foreach (var name in WorkIdSuffix.Keys)
        {
            if (!agents.ContainsKey(name))
            {
                findings.Add(new VerificationFinding(
                    ControlStateStatus.Invalid, "AGENT_MISSING", $"agent_states is missing {name}."));
            }
        }

        if (agents.TryGetValue(state.CurrentAgent, out var current))
        {
            if (!string.Equals(current.State, state.State, StringComparison.Ordinal)
                || !string.Equals(current.WorkId, state.CurrentWorkId, StringComparison.Ordinal)
                || !string.Equals(current.WaitingFor, state.WaitingFor, StringComparison.Ordinal))
            {
                findings.Add(new VerificationFinding(
                    ControlStateStatus.Conflict, "AGENT_SNAPSHOT_MISMATCH",
                    "Current agent card disagrees with the top-level snapshot."));
            }
        }

        var busy = agents
            .Where(pair => pair.Value.State is "WORKING" or "REVIEW")
            .Select(pair => pair.Key)
            .OrderBy(name => name, StringComparer.Ordinal)
            .ToList();
        var expectedBusy = state.State is "WORKING" or "REVIEW"
            ? new List<string> { state.CurrentAgent }
            : [];
        if (!busy.SequenceEqual(expectedBusy, StringComparer.Ordinal))
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Invalid, "BUSY_OWNERSHIP",
                "WORKING/REVIEW must belong only to the current pipeline agent."));
        }

        ControlStateSchemaValidator.TryParseOffset(state.ValidatedAt, out var validated);
        foreach (var (name, agent) in agents)
        {
            if (ControlStateSchemaValidator.TryParseOffset(agent.UpdatedAt, out var observed)
                && observed > validated)
            {
                findings.Add(new VerificationFinding(
                    ControlStateStatus.Invalid, "AGENT_AFTER_VALIDATION",
                    $"{name} agent state was updated after validation."));
            }

            if (agent.State == "NOT_ACTIVE" && (agent.WorkId is not null || agent.WaitingFor is not null))
            {
                findings.Add(new VerificationFinding(
                    ControlStateStatus.Invalid, "NOT_ACTIVE_PAYLOAD",
                    $"{name} is NOT_ACTIVE but still carries work or waiting_for."));
            }

            if (agent.State == "WAITING" && string.IsNullOrWhiteSpace(agent.WaitingFor))
            {
                findings.Add(new VerificationFinding(
                    ControlStateStatus.Invalid, "WAITING_WITHOUT_REASON",
                    $"{name} is WAITING without an explicit waiting_for."));
            }

            if (agent.WorkId is null || !WorkIdSuffix.TryGetValue(name, out var suffix))
            {
                continue;
            }

            var expected = $"{state.TaskId}/{state.CycleId}/{suffix}";
            if (!string.Equals(agent.WorkId, expected, StringComparison.Ordinal))
            {
                findings.Add(new VerificationFinding(
                    ControlStateStatus.Invalid, "AGENT_WORK_ID",
                    $"{name} work_id {agent.WorkId} does not match {expected}."));
            }
        }
    }

    private static void CheckWaitingAndKrum(ControlState state, List<VerificationFinding> findings)
    {
        if (state.RequiresKrum && string.IsNullOrWhiteSpace(state.RequiresKrumReason))
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Invalid, "KRUM_REASON", "requires_krum is set with no reason."));
        }

        if (state.State is "WAITING" or "BLOCKED" && string.IsNullOrWhiteSpace(state.WaitingFor))
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Invalid, "BLOCKED_WITHOUT_REASON",
                $"{state.State} state has no waiting_for."));
        }

        if (state.NextAgent == "KRUM" && !state.RequiresKrum)
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Invalid, "KRUM_NEXT",
                "next_agent is KRUM without requires_krum."));
        }
    }

    private static void CheckEvidence(ControlState state, List<VerificationFinding> findings)
    {
        if (state.PrNumber is null)
        {
            if (state.PrHeadSha is not null || state.PrDraft is not null
                || state.LastHandoff is not null || state.LastReview is not null)
            {
                findings.Add(new VerificationFinding(
                    ControlStateStatus.Invalid, "PR_EVIDENCE", "PR evidence is incomplete."));
            }
        }
        else if (state.PrHeadSha is null || state.PrDraft is null)
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Invalid, "PR_EVIDENCE", "PR number needs head and draft status."));
        }

        var review = state.LastReview;
        if (review is not null)
        {
            if (!string.Equals(state.PrHeadSha, review.ReviewedHeadSha, StringComparison.Ordinal))
            {
                findings.Add(new VerificationFinding(
                    ControlStateStatus.Stale, "REVIEW_HEAD",
                    "Review was not performed on the current PR head."));
            }

            if (!string.Equals(review.BlobSha, state.SourceRefs.ReviewBlobSha, StringComparison.Ordinal))
            {
                findings.Add(new VerificationFinding(
                    ControlStateStatus.Stale, "REVIEW_BLOB", "Review blob reference mismatch."));
            }

            if (state.State is "PASS" or "CHANGES_REQUESTED" or "BLOCKED"
                && !string.Equals(review.Verdict, state.State, StringComparison.Ordinal))
            {
                findings.Add(new VerificationFinding(
                    ControlStateStatus.Conflict, "REVIEW_VERDICT",
                    $"State {state.State} conflicts with independent review verdict {review.Verdict}."));
            }
        }
        else if (state.State is "PASS" or "CHANGES_REQUESTED")
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Invalid, "REVIEW_MISSING",
                $"State {state.State} requires exact review evidence."));
        }

        if (state.LastHandoff is not null
            && !string.Equals(state.LastHandoff.HeadSha, state.PrHeadSha, StringComparison.Ordinal))
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Stale, "HANDOFF_HEAD", "HANDOFF is not on the current PR head."));
        }
    }

    private static void CheckHistory(ControlState state, List<VerificationFinding> findings)
    {
        var ids = state.History.Select(item => item.EventId).ToList();
        if (ids.Distinct(StringComparer.Ordinal).Count() != ids.Count)
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Invalid, "HISTORY_DUPLICATE", "Duplicate history event_id."));
        }

        var currentCycle = ParseCycle(state.CycleId);
        foreach (var item in state.History)
        {
            if (!string.Equals(item.TaskId, state.TaskId, StringComparison.Ordinal))
            {
                findings.Add(new VerificationFinding(
                    ControlStateStatus.Invalid, "HISTORY_TASK", "History Task-ID mismatch."));
            }

            if ((item.CycleId is null) == (item.MappedCycle is null))
            {
                findings.Add(new VerificationFinding(
                    ControlStateStatus.Invalid, "HISTORY_CYCLE",
                    "History needs exactly one native or mapped cycle."));
                continue;
            }

            var cycle = ParseCycle(item.CycleId ?? item.MappedCycle!);
            if (currentCycle is not null && cycle is not null && cycle > currentCycle)
            {
                findings.Add(new VerificationFinding(
                    ControlStateStatus.Invalid, "HISTORY_FUTURE_CYCLE",
                    "History invents a future cycle."));
            }
        }
    }

    private static void CheckProgress(ControlState state, List<VerificationFinding> findings)
    {
        var progress = state.Progress;
        if (progress.Mode == "STAGE_ONLY")
        {
            if (progress.Completed is not null || progress.Total is not null || progress.Percent is not null)
            {
                findings.Add(new VerificationFinding(
                    ControlStateStatus.Invalid, "PROGRESS_STAGE_ONLY",
                    "Stage-only progress cannot claim numbers."));
            }
            return;
        }

        if (progress.Completed is null || progress.Total is null || progress.Percent is null)
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Invalid, "PROGRESS_INCOMPLETE",
                "Evidence-count progress needs numerator, denominator and percent."));
            return;
        }

        if (progress.Completed > progress.Total
            || progress.Percent != 100 * progress.Completed / progress.Total)
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Invalid, "PROGRESS_NOT_DETERMINISTIC",
                "Progress percentage is not deterministic from completed/total."));
        }
    }

    private static int? ParseCycle(string cycle) =>
        cycle.Length > 1 && int.TryParse(cycle[1..], out var value) ? value : null;
}
