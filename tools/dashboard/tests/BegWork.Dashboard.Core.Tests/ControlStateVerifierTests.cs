using System.Text.Json.Nodes;
using BegWork.Dashboard.Core.Config;
using BegWork.Dashboard.Core.Sources;
using BegWork.Dashboard.Core.Validation;
using Xunit;

namespace BegWork.Dashboard.Core.Tests;

public sealed class ControlStateVerifierTests
{
    private static VerifiedSnapshot Verify(ControlSnapshot snapshot) =>
        ControlStateVerifier.Verify(snapshot, CoordinationFixture.Settings);

    private static bool Has(VerifiedSnapshot verified, string code) =>
        verified.Result.Findings.Any(finding => finding.Code == code);

    [Fact]
    public void PublishedSnapshotWithMatchingSourcesVerifiesAsValid()
    {
        var verified = Verify(CoordinationFixture.Published());

        Assert.Equal(ControlStateStatus.Valid, verified.Status);
        Assert.Empty(verified.Result.Findings);
        Assert.NotNull(verified.State);
        Assert.Equal("W0-03C", verified.State!.TaskId);
        Assert.Equal("BLOCKED", verified.State.State);
    }

    [Fact]
    public void PersistedValidIsNotAcceptedWhenTheCitedActiveBlobNoLongerMatches()
    {
        // The document still says VALID; the bytes on the branch say otherwise.
        var snapshot = CoordinationFixture.Published() with
        {
            ActiveFile = new FetchedFile(
                "coordination/ACTIVE.md",
                "Status: IDLE\n"u8.ToArray(),
                "\"active\""),
        };

        var verified = Verify(snapshot);

        Assert.Equal("VALID", verified.State!.PersistedStatus);
        Assert.Equal(ControlStateStatus.Stale, verified.Status);
        Assert.True(Has(verified, "SOURCE_BLOB_MISMATCH"));
    }

    [Fact]
    public void StalePullRequestHeadDowngradesTheSnapshot()
    {
        var snapshot = CoordinationFixture.Build(
            CoordinationFixture.PublishedStateNode(),
            pullRequest: new PullRequestMetadata(20, CoordinationFixture.EarlierPrHead, Draft: true, "open"));

        var verified = Verify(snapshot);

        Assert.Equal(ControlStateStatus.Stale, verified.Status);
        Assert.True(Has(verified, "PR_HEAD_STALE"));
    }

    [Fact]
    public void UnreadPullRequestMetadataIsReportedAsUnverifiedRatherThanAssumedGood()
    {
        var verified = Verify(CoordinationFixture.Build(
            CoordinationFixture.PublishedStateNode(), includePullRequest: false));

        Assert.Equal(ControlStateStatus.Stale, verified.Status);
        Assert.True(Has(verified, "PR_UNVERIFIED"));
    }

    [Fact]
    public void DraftFlagDisagreementIsAConflict()
    {
        var snapshot = CoordinationFixture.Build(
            CoordinationFixture.PublishedStateNode(),
            pullRequest: new PullRequestMetadata(20, CoordinationFixture.PublishedPrHead, Draft: false, "open"));

        var verified = Verify(snapshot);

        Assert.Equal(ControlStateStatus.Conflict, verified.Status);
        Assert.True(Has(verified, "PR_DRAFT_MISMATCH"));
    }

    [Fact]
    public void MissingRequiredFieldIsInvalidAndBindsNoState()
    {
        var verified = Verify(CoordinationFixture.Mutated(node => node.AsObject().Remove("agent_states")));

        Assert.Equal(ControlStateStatus.Invalid, verified.Status);
        Assert.Null(verified.State);
        Assert.True(Has(verified, "SCHEMA"));
        Assert.Contains("agent_states", verified.Result.Findings[0].Message, StringComparison.Ordinal);
    }

    [Fact]
    public void UnknownFieldIsInvalid()
    {
        var verified = Verify(CoordinationFixture.Mutated(node => node["surprise"] = "value"));

        Assert.Equal(ControlStateStatus.Invalid, verified.Status);
        Assert.Null(verified.State);
    }

    [Fact]
    public void MalformedJsonIsInvalidNotEmpty()
    {
        var snapshot = CoordinationFixture.Published() with
        {
            ControlStateFile = new FetchedFile(
                "coordination/CONTROL_STATE.json", "{ not json"u8.ToArray(), null),
        };

        var verified = Verify(snapshot);

        Assert.Equal(ControlStateStatus.Invalid, verified.Status);
        Assert.True(Has(verified, "CONTROL_STATE_UNPARSED"));
    }

    [Fact]
    public void StateThatContradictsTheIndependentReviewVerdictIsAConflict()
    {
        var verified = Verify(CoordinationFixture.Mutated(node =>
        {
            // Claim PASS while the cited review on the same head says BLOCKED.
            node["state"] = "PASS";
            node["agent_states"]!["CODEX"]!["state"] = "PASS";
        }));

        Assert.Equal(ControlStateStatus.Conflict, verified.Status);
        Assert.True(Has(verified, "REVIEW_VERDICT"));
    }

    [Fact]
    public void ReviewOnAnOlderHeadIsStale()
    {
        var verified = Verify(CoordinationFixture.Mutated(node =>
            node["last_review"]!["reviewed_head_sha"] = CoordinationFixture.EarlierPrHead));

        Assert.Equal(ControlStateStatus.Stale, verified.Status);
        Assert.True(Has(verified, "REVIEW_HEAD"));
    }

    [Fact]
    public void SyntheticSnapshotIsNeverPresentedAsLive()
    {
        var verified = Verify(CoordinationFixture.Mutated(node =>
            node["validation_mode"] = "SYNTHETIC_TEST"));

        Assert.Equal(ControlStateStatus.Conflict, verified.Status);
        Assert.True(Has(verified, "SYNTHETIC_SNAPSHOT"));
    }

    [Theory]
    [InlineData("STALE", ControlStateStatus.Stale)]
    [InlineData("CONFLICT", ControlStateStatus.Conflict)]
    [InlineData("INVALID", ControlStateStatus.Invalid)]
    public void PersistedNonValidStatusIsCarriedThrough(string persisted, ControlStateStatus expected)
    {
        var verified = Verify(CoordinationFixture.Mutated(node =>
            node["control_state_status"] = persisted));

        Assert.Equal(expected, verified.Status);
        Assert.True(Has(verified, "PERSISTED_STATUS"));
    }

    [Fact]
    public void SnapshotForAnotherRepositoryIsAConflict()
    {
        var settings = CoordinationFixture.Settings with { Repository = "krumingo/other" };

        var verified = ControlStateVerifier.Verify(CoordinationFixture.Published(), settings);

        Assert.Equal(ControlStateStatus.Conflict, verified.Status);
        Assert.Contains(verified.Result.Findings, f => f.Code == "REPOSITORY_MISMATCH");
    }

    [Fact]
    public void ProgressThatClaimsNumbersInStageOnlyModeIsInvalid()
    {
        var verified = Verify(CoordinationFixture.Mutated(node =>
        {
            node["progress"]!["completed"] = 4;
            node["progress"]!["total"] = 10;
            node["progress"]!["percent"] = 40;
        }));

        Assert.Equal(ControlStateStatus.Invalid, verified.Status);
        Assert.True(Has(verified, "PROGRESS_STAGE_ONLY"));
    }

    [Fact]
    public void EvidenceCountProgressMustBeArithmeticallyDerivable()
    {
        var verified = Verify(CoordinationFixture.Mutated(node =>
        {
            node["progress"]!["mode"] = "EVIDENCE_COUNT";
            node["progress"]!["completed"] = 3;
            node["progress"]!["total"] = 10;
            node["progress"]!["percent"] = 95;
        }));

        Assert.Equal(ControlStateStatus.Invalid, verified.Status);
        Assert.True(Has(verified, "PROGRESS_NOT_DETERMINISTIC"));
    }

    [Fact]
    public void EvidenceCountProgressIsAcceptedWhenItIsDerivable()
    {
        var verified = Verify(CoordinationFixture.Mutated(node =>
        {
            node["progress"]!["mode"] = "EVIDENCE_COUNT";
            node["progress"]!["completed"] = 3;
            node["progress"]!["total"] = 10;
            node["progress"]!["percent"] = 30;
        }));

        Assert.Equal(ControlStateStatus.Valid, verified.Status);
        Assert.Equal(30, verified.State!.Progress.Percent);
    }

    [Fact]
    public void AgentCardDisagreeingWithTheSnapshotIsAConflict()
    {
        var verified = Verify(CoordinationFixture.Mutated(node =>
            node["agent_states"]!["CODEX"]!["state"] = "WAITING"));

        Assert.Equal(ControlStateStatus.Conflict, verified.Status);
        Assert.True(Has(verified, "AGENT_SNAPSHOT_MISMATCH"));
    }

    [Fact]
    public void WorkingOrReviewMayNotBelongToANonPipelineAgent()
    {
        var verified = Verify(CoordinationFixture.Mutated(node =>
        {
            node["agent_states"]!["CLAUDE"]!["state"] = "WORKING";
            node["agent_states"]!["CLAUDE"]!["work_id"] = "W0-03C/C02/CL";
        }));

        Assert.Equal(ControlStateStatus.Invalid, verified.Status);
        Assert.True(Has(verified, "BUSY_OWNERSHIP"));
    }

    [Fact]
    public void HistoryMayNotInventAFutureCycle()
    {
        var verified = Verify(CoordinationFixture.Mutated(node =>
            node["history"]![0]!["mapped_cycle"] = "C09"));

        Assert.Equal(ControlStateStatus.Invalid, verified.Status);
        Assert.True(Has(verified, "HISTORY_FUTURE_CYCLE"));
    }

    [Fact]
    public void BoardThatDisagreesWithTheStateIsAConflictAndNeverOverridesIt()
    {
        var board = CoordinationFixture.PublishedBoardText()
            .Replace(
                "CURRENT: W0-03C / C02 (migrated) / CODEX / **BLOCKED**",
                "CURRENT: W0-03C / C02 (migrated) / CODEX / **PASS**",
                StringComparison.Ordinal);

        var verified = Verify(CoordinationFixture.Build(
            CoordinationFixture.PublishedStateNode(), boardOverride: board));

        Assert.Equal(ControlStateStatus.Conflict, verified.Status);
        Assert.True(Has(verified, "BOARD_MISMATCH"));
        // The board never promotes a value: the state still reads BLOCKED.
        Assert.Equal("BLOCKED", verified.State!.State);
    }

    [Fact]
    public void UnreadBoardIsStaleNotSilentlyIgnored()
    {
        var verified = Verify(CoordinationFixture.Build(
            CoordinationFixture.PublishedStateNode(), includeBoard: false));

        Assert.Equal(ControlStateStatus.Stale, verified.Status);
        Assert.True(Has(verified, "BOARD_UNREAD"));
    }

    [Fact]
    public void EveryFindingIsCarried_NotJustTheFirst()
    {
        var verified = Verify(CoordinationFixture.Build(
            CoordinationFixture.PublishedStateNode(),
            includeBoard: false,
            includeActive: false,
            includePullRequest: false));

        Assert.Equal(ControlStateStatus.Stale, verified.Status);
        Assert.True(Has(verified, "BOARD_UNREAD"));
        Assert.True(Has(verified, "SOURCE_UNVERIFIED"));
        Assert.True(Has(verified, "PR_UNVERIFIED"));
    }

    [Fact]
    public void WorstFindingWins()
    {
        var result = VerificationResult.From([
            new VerificationFinding(ControlStateStatus.Stale, "A", "a"),
            new VerificationFinding(ControlStateStatus.Conflict, "B", "b"),
            new VerificationFinding(ControlStateStatus.Stale, "C", "c"),
        ]);

        Assert.Equal(ControlStateStatus.Conflict, result.Status);
        Assert.False(result.IsLiveVerified);
    }
}
