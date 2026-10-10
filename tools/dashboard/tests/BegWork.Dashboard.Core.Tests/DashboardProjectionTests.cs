using System.Text.Json.Nodes;
using BegWork.Dashboard.Core.Config;
using BegWork.Dashboard.Core.Projection;
using BegWork.Dashboard.Core.Sources;
using BegWork.Dashboard.Core.Validation;
using Xunit;

namespace BegWork.Dashboard.Core.Tests;

public sealed class DashboardProjectionTests
{
    private static ProjectionInput Input(
        ControlSnapshot? snapshot = null,
        DateTimeOffset? now = null,
        bool offline = false,
        DateTimeOffset? lastSuccess = null,
        string? lastError = null,
        DashboardSettings? settings = null,
        IReadOnlyList<string>? shellNotices = null)
    {
        var effective = settings ?? CoordinationFixture.Settings;
        var verified = snapshot is null
            ? null
            : ControlStateVerifier.Verify(snapshot, effective);

        return new ProjectionInput
        {
            Verified = verified,
            Now = now ?? CoordinationFixture.Now,
            IsOffline = offline,
            LastSuccessfulFetchAt = lastSuccess ?? (snapshot is null ? null : snapshot.FetchedAt),
            LastError = lastError,
            Settings = effective,
            ShellNotices = shellNotices ?? [],
        };
    }

    [Fact]
    public void PublishedBlockedSnapshotProjectsTheBlockedHeaderAndKrumAction()
    {
        var model = DashboardProjection.Project(Input(CoordinationFixture.Published()));

        Assert.True(model.HasContent);
        Assert.Equal(ControlStateStatus.Valid, model.Banner.Status);
        Assert.True(model.Banner.IsLiveVerified);

        var header = Assert.IsType<HeaderView>(model.Header);
        Assert.Equal("W0", header.Wave);
        Assert.Equal("FLOW-032", header.Flow);
        Assert.Equal("W0-03C", header.TaskId);
        Assert.Equal("C02", header.CycleId);
        Assert.Equal("W0-03C/C02/CX", header.WorkId);
        Assert.Equal("BLOCKED", header.State);
        Assert.Equal("BLOCKED", header.StateDisplay);
        Assert.Equal("CODEX", header.CurrentAgent);
        Assert.Equal("KRUM", header.NextAgent);
        Assert.True(header.KrumActionRequired);
        Assert.StartsWith("REQUIRED —", header.KrumActionText, StringComparison.Ordinal);
        Assert.Equal(
            "Explicit technical correction cycle or design decision from Krum",
            header.WaitingFor);
    }

    [Fact]
    public void AgentCardsComeFromAgentStatesAndNeverFromHistory()
    {
        // History's newest events are authored by CODEX and CLAUDE, and the newest
        // CLAUDE event is a HANDOFF. agent_states says CLAUDE is NOT_ACTIVE, and
        // that is what the card must show.
        var model = DashboardProjection.Project(Input(CoordinationFixture.Published()));

        Assert.Equal(3, model.AgentCards.Count);
        Assert.Equal(["GPT", "CODEX", "CLAUDE"], model.AgentCards.Select(card => card.Agent));

        var claude = model.AgentCards.Single(card => card.Agent == "CLAUDE");
        Assert.Equal("NOT_ACTIVE", claude.State);
        Assert.Null(claude.WorkId);
        Assert.Null(claude.WaitingFor);
        Assert.False(claude.IsCurrent);

        var latestClaudeEvent = model.RecentActivity
            .First(entry => entry.Actor == "CLAUDE");
        Assert.Equal("HANDOFF", latestClaudeEvent.StateAfter);
        Assert.NotEqual(latestClaudeEvent.StateAfter, claude.State);

        var codex = model.AgentCards.Single(card => card.Agent == "CODEX");
        Assert.Equal("BLOCKED", codex.State);
        Assert.Equal("W0-03C/C02/CX", codex.WorkId);
        Assert.True(codex.IsCurrent);

        var gpt = model.AgentCards.Single(card => card.Agent == "GPT");
        Assert.Equal("NOT_ACTIVE", gpt.State);
    }

    [Fact]
    public void AnAgentWithNoPublishedCardIsUnknownRatherThanInferred()
    {
        // Removing a card makes the document schema-invalid, so no state binds at
        // all: the panel shows the empty state instead of two-thirds of a picture.
        var snapshot = CoordinationFixture.Mutated(node =>
            node["agent_states"]!.AsObject().Remove("GPT"));

        var model = DashboardProjection.Project(Input(snapshot));

        Assert.False(model.HasContent);
        Assert.Empty(model.AgentCards);
        Assert.Equal(ControlStateStatus.Invalid, model.Banner.Status);
    }

    [Fact]
    public void ReviewStateMarksTheReviewPipelineStepAndTheReviewingAgent()
    {
        var node = CoordinationFixture.PublishedStateNode();
        node["state"] = "REVIEW";
        node["agent_states"]!["CODEX"]!["state"] = "REVIEW";
        var snapshot = CoordinationFixture.Build(
            node, boardOverride: CoordinationFixture.BoardWithState("REVIEW"));

        var model = DashboardProjection.Project(Input(snapshot));

        Assert.Equal(ControlStateStatus.Valid, model.Banner.Status);
        Assert.Equal("REVIEW", model.Header!.State);

        var active = Assert.Single(model.Pipeline, step => step.IsActive);
        Assert.Equal("REVIEW", active.Step);
        Assert.Equal(4, active.Ordinal);
        Assert.Equal("CODEX", active.Agent);
        Assert.True(active.IsActiveVerified);

        Assert.Equal("REVIEW", model.AgentCards.Single(card => card.Agent == "CODEX").State);
    }

    [Fact]
    public void PipelineAlwaysHasTheFiveProtocolStepsInOrder()
    {
        var model = DashboardProjection.Project(Input(CoordinationFixture.Published()));

        Assert.Equal(
            ["ARCHITECT", "ASSIGNMENT", "IMPLEMENTATION", "REVIEW", "ARCHITECT_FEEDBACK"],
            model.Pipeline.Select(step => step.Step));
        Assert.Equal(["GPT", "CODEX", "CLAUDE", "CODEX", "GPT"], model.Pipeline.Select(step => step.Agent));
    }

    [Fact]
    public void StageOnlyProgressProducesNoPercentage()
    {
        var model = DashboardProjection.Project(Input(CoordinationFixture.Published()));

        Assert.Equal("STAGE_ONLY", model.Progress.Mode);
        Assert.Equal("REVIEW", model.Progress.Stage);
        Assert.Null(model.Progress.Percent);
        Assert.Null(model.Progress.Completed);
        Assert.Null(model.Progress.Total);
        Assert.Null(model.Progress.CountsText);
        Assert.False(model.Progress.HasProvenPercentage);
        Assert.Equal("no proven percentage", model.Progress.PercentText);
        Assert.Null(Assert.Single(model.Tasks).PercentText);
    }

    [Fact]
    public void EvidenceCountProgressSurfacesExactlyThePublishedNumbers()
    {
        var snapshot = CoordinationFixture.Mutated(node =>
        {
            node["progress"]!["mode"] = "EVIDENCE_COUNT";
            node["progress"]!["completed"] = 3;
            node["progress"]!["total"] = 8;
            node["progress"]!["percent"] = 37;
        });

        var model = DashboardProjection.Project(Input(snapshot));

        Assert.True(model.Progress.HasProvenPercentage);
        Assert.Equal(37, model.Progress.Percent);
        Assert.Equal("3 / 8", model.Progress.CountsText);
        Assert.Equal("37%", model.Progress.PercentText);
    }

    [Fact]
    public void AnUnverifiedPassIsNeverPresentedAsALiveVerdict()
    {
        var snapshot = CoordinationFixture.Mutated(node =>
        {
            node["state"] = "PASS";
            node["agent_states"]!["CODEX"]!["state"] = "PASS";
            node["last_review"]!["verdict"] = "PASS";
        });

        var model = DashboardProjection.Project(Input(snapshot, offline: true));

        Assert.Equal("PASS", model.Header!.State);
        Assert.Equal("PASS (UNVERIFIED)", model.Header.StateDisplay);
        Assert.False(model.Banner.IsLiveVerified);
        Assert.True(model.Banner.IsOffline);
        Assert.False(model.Pipeline.Single(step => step.IsActive).IsActiveVerified);
    }

    [Fact]
    public void AnAgedSnapshotIsMarkedStaleEvenWhenTheDocumentItselfVerified()
    {
        var snapshot = CoordinationFixture.Published();
        var settings = CoordinationFixture.Settings with { StaleAfterSeconds = 45 };

        var model = DashboardProjection.Project(Input(
            snapshot,
            now: snapshot.FetchedAt.AddSeconds(120),
            lastSuccess: snapshot.FetchedAt,
            settings: settings));

        Assert.Equal(ControlStateStatus.Stale, model.Banner.Status);
        Assert.False(model.Banner.IsLiveVerified);
        Assert.Contains(model.Banner.Findings, finding => finding.Code == "SNAPSHOT_AGE");
        Assert.Equal(TimeSpan.FromSeconds(120), model.Banner.Age);
        // The cached content is still shown, explicitly labelled rather than blanked.
        Assert.True(model.HasContent);
        Assert.Equal("BLOCKED (UNVERIFIED)", model.Header!.StateDisplay);
    }

    [Fact]
    public void AFreshSnapshotWithinTheThresholdStaysValid()
    {
        var snapshot = CoordinationFixture.Published();

        var model = DashboardProjection.Project(Input(
            snapshot, now: snapshot.FetchedAt.AddSeconds(20), lastSuccess: snapshot.FetchedAt));

        Assert.Equal(ControlStateStatus.Valid, model.Banner.Status);
        Assert.True(model.Banner.IsLiveVerified);
    }

    [Fact]
    public void OfflineWithNoSnapshotYetShowsAnExplicitEmptyState()
    {
        var model = DashboardProjection.Project(Input(
            snapshot: null, offline: true, lastError: "Read of coordination/CONTROL_STATE.json failed with HTTP 503."));

        Assert.False(model.HasContent);
        Assert.Null(model.Header);
        Assert.Empty(model.AgentCards);
        Assert.Empty(model.Tasks);
        Assert.NotNull(model.EmptyStateMessage);
        Assert.Equal("Read of coordination/CONTROL_STATE.json failed with HTTP 503.", model.Banner.LastError);
    }

    [Fact]
    public void InvalidSnapshotProjectsNoHeaderAndSaysWhy()
    {
        var model = DashboardProjection.Project(Input(
            CoordinationFixture.Mutated(node => node.AsObject().Remove("progress"))));

        Assert.False(model.HasContent);
        Assert.Equal(ControlStateStatus.Invalid, model.Banner.Status);
        Assert.Contains("could not be verified", model.EmptyStateMessage, StringComparison.Ordinal);
        Assert.Contains(model.Banner.Findings, finding => finding.Code == "SCHEMA");
    }

    [Fact]
    public void TaskListOnlyClaimsWhatTheReadModelProves()
    {
        var model = DashboardProjection.Project(Input(CoordinationFixture.Published()));

        var task = Assert.Single(model.Tasks);
        Assert.Equal("W0-03C", task.TaskId);
        Assert.Equal("C02", task.CycleId);
        Assert.Equal("BLOCKED", task.State);
        Assert.Equal("REVIEW", task.StageText);
        Assert.Contains("active task only", model.TaskListNote, StringComparison.Ordinal);
    }

    [Fact]
    public void RecentActivityIsNewestFirstAndBounded()
    {
        var settings = CoordinationFixture.Settings with { RecentActivityCount = 3 };

        var model = DashboardProjection.Project(Input(CoordinationFixture.Published(), settings: settings));

        Assert.Equal(3, model.RecentActivity.Count);
        Assert.Equal("2026-09-22T06:17:02Z", model.RecentActivity[0].OccurredAt);
        Assert.Equal("CONTROL_UPDATE", model.RecentActivity[0].Kind);
        Assert.Equal("C02 (mapped)", model.RecentActivity[0].CycleLabel);
        Assert.Equal("ed588e94", model.RecentActivity[0].HeadShaShort);
    }

    [Fact]
    public void EvidenceListsTheExactCitedSources()
    {
        var model = DashboardProjection.Project(Input(CoordinationFixture.Published()));

        Assert.Contains(model.Evidence, item =>
            item.Label == "Draft PR" && item.Detail.Contains("ed588e94", StringComparison.Ordinal));
        Assert.Contains(model.Evidence, item =>
            item.Label == "Review" && item.Detail.Contains("verdict BLOCKED", StringComparison.Ordinal));
        Assert.Contains(model.Evidence, item => item.Label == "HANDOFF");
        Assert.Contains(model.Evidence, item => item.Label == "ACTIVE");
    }

    [Fact]
    public void ShellNoticesReachTheBanner()
    {
        var model = DashboardProjection.Project(Input(
            CoordinationFixture.Published(),
            shellNotices: ["AppBar registration failed; running as a topmost overlay."]));

        Assert.Contains(
            "AppBar registration failed; running as a topmost overlay.",
            model.Banner.ShellNotices);
    }
}
