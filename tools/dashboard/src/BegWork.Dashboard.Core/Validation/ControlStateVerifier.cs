using System.Text.Json;
using BegWork.Dashboard.Core.Config;
using BegWork.Dashboard.Core.Model;
using BegWork.Dashboard.Core.Sources;

namespace BegWork.Dashboard.Core.Validation;

/// <summary>Outcome of verifying one fetched snapshot.</summary>
/// <param name="State">Bound state, or null when the document was not even structurally usable.</param>
/// <param name="Result">Worst-of verdict plus every finding.</param>
/// <param name="Snapshot">The bundle that was verified.</param>
public sealed record VerifiedSnapshot(
    ControlState? State,
    VerificationResult Result,
    ControlSnapshot Snapshot)
{
    public ControlStateStatus Status => Result.Status;

    public DateTimeOffset VerifiedAt => Snapshot.FetchedAt;
}

/// <summary>
/// The dashboard's own verification pass over a fetched snapshot.
///
/// Persisted <c>control_state_status: VALID</c> is treated as a claim, not as
/// truth: it is folded in as one more finding and the effective status is the worst
/// of everything observed. A snapshot only reaches VALID here when the schema, the
/// protocol invariants, the cited blob SHAs, the exact PR head and the rendered
/// board all agree with the bytes fetched in this round.
/// </summary>
public static class ControlStateVerifier
{
    public static VerifiedSnapshot Verify(ControlSnapshot snapshot, DashboardSettings settings)
    {
        ArgumentNullException.ThrowIfNull(snapshot);
        ArgumentNullException.ThrowIfNull(settings);

        JsonDocument stateDocument;
        JsonDocument schemaDocument;
        try
        {
            stateDocument = JsonDocument.Parse(snapshot.ControlStateFile.Content);
        }
        catch (JsonException exception)
        {
            return Unusable(snapshot, "CONTROL_STATE_UNPARSED",
                $"CONTROL_STATE.json is not valid JSON: {exception.Message}");
        }

        using (stateDocument)
        {
            try
            {
                schemaDocument = JsonDocument.Parse(snapshot.SchemaFile.Content);
            }
            catch (JsonException exception)
            {
                return Unusable(snapshot, "SCHEMA_UNPARSED",
                    $"CONTROL_STATE.schema.json is not valid JSON: {exception.Message}");
            }

            using (schemaDocument)
            {
                var schema = ControlStateSchemaValidator.Validate(
                    stateDocument.RootElement, schemaDocument.RootElement);
                if (schema.Status == ControlStateStatus.Invalid)
                {
                    // Binding an object that failed its own schema would invent
                    // defaults for missing fields, which is exactly the guessing the
                    // protocol forbids.
                    return new VerifiedSnapshot(null, schema, snapshot);
                }

                ControlState state;
                try
                {
                    state = ControlState.Bind(stateDocument.RootElement);
                }
                catch (JsonException exception)
                {
                    return Unusable(snapshot, "CONTROL_STATE_UNBINDABLE",
                        $"CONTROL_STATE.json could not be bound: {exception.Message}");
                }

                var result = schema
                    .Merge(ControlStateInvariants.Validate(state))
                    .Merge(VerifyConfiguredTarget(state, settings))
                    .Merge(VerifyCitedBlobs(state, snapshot))
                    .Merge(VerifyPullRequest(state, snapshot))
                    .Merge(ControlBoardCrossCheck.Verify(state, snapshot.BoardFile?.Text));

                return new VerifiedSnapshot(state, result, snapshot);
            }
        }
    }

    private static VerifiedSnapshot Unusable(ControlSnapshot snapshot, string code, string message) =>
        new(null,
            VerificationResult.From([
                new VerificationFinding(ControlStateStatus.Invalid, code, message)
            ]),
            snapshot);

    private static VerificationResult VerifyConfiguredTarget(ControlState state, DashboardSettings settings)
    {
        var findings = new List<VerificationFinding>();

        if (!string.Equals(state.Repository, settings.Repository, StringComparison.Ordinal))
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Conflict, "REPOSITORY_MISMATCH",
                $"Snapshot names repository '{state.Repository}', dashboard is configured for '{settings.Repository}'."));
        }

        if (!string.Equals(state.Branch, settings.Branch, StringComparison.Ordinal))
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Conflict, "BRANCH_MISMATCH",
                $"Snapshot names branch '{state.Branch}', dashboard is configured for '{settings.Branch}'."));
        }

        return VerificationResult.From(findings);
    }

    private static VerificationResult VerifyCitedBlobs(ControlState state, ControlSnapshot snapshot)
    {
        var findings = new List<VerificationFinding>();

        VerifyBlob(
            findings,
            snapshot.ActiveFile,
            state.SourceRefs.ActivePath,
            state.SourceRefs.ActiveBlobSha,
            "ACTIVE");

        if (!string.IsNullOrEmpty(state.SourceRefs.ReviewBlobSha))
        {
            VerifyBlob(
                findings,
                snapshot.ReviewFile,
                state.SourceRefs.ReviewPath ?? "coordination/REVIEWS/",
                state.SourceRefs.ReviewBlobSha,
                "REVIEW");
        }

        return VerificationResult.From(findings);
    }

    private static void VerifyBlob(
        List<VerificationFinding> findings,
        FetchedFile? file,
        string citedPath,
        string citedBlobSha,
        string label)
    {
        if (file is null)
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Stale, "SOURCE_UNVERIFIED",
                $"{label} source '{citedPath}' was not read this round, so its cited blob is unverified."));
            return;
        }

        if (!string.Equals(file.Path, citedPath, StringComparison.Ordinal))
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Conflict, "SOURCE_PATH_MISMATCH",
                $"{label} was read from '{file.Path}' but the snapshot cites '{citedPath}'."));
            return;
        }

        var observed = file.BlobSha;
        if (!string.Equals(observed, citedBlobSha, StringComparison.OrdinalIgnoreCase))
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Stale, "SOURCE_BLOB_MISMATCH",
                $"{label} '{citedPath}' is blob {observed[..8]} on the branch but the snapshot cites {Shorten(citedBlobSha)}."));
        }
    }

    private static VerificationResult VerifyPullRequest(ControlState state, ControlSnapshot snapshot)
    {
        if (state.PrNumber is null)
        {
            return VerificationResult.Clean;
        }

        var pr = snapshot.PullRequest;
        if (pr is null)
        {
            return VerificationResult.From([
                new VerificationFinding(
                    ControlStateStatus.Stale, "PR_UNVERIFIED",
                    $"PR #{state.PrNumber} metadata was not read this round, so the cited exact head is unverified.")
            ]);
        }

        var findings = new List<VerificationFinding>();

        if (pr.Number != state.PrNumber)
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Conflict, "PR_NUMBER_MISMATCH",
                $"Read PR #{pr.Number} but the snapshot cites #{state.PrNumber}."));
            return VerificationResult.From(findings);
        }

        if (!string.Equals(pr.HeadSha, state.PrHeadSha, StringComparison.OrdinalIgnoreCase))
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Stale, "PR_HEAD_STALE",
                $"PR #{pr.Number} head is {Shorten(pr.HeadSha)} but the snapshot was validated against {Shorten(state.PrHeadSha)}."));
        }

        if (state.PrDraft is { } draft && draft != pr.Draft)
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Conflict, "PR_DRAFT_MISMATCH",
                $"PR #{pr.Number} draft flag is {pr.Draft} but the snapshot records {draft}."));
        }

        return VerificationResult.From(findings);
    }

    private static string Shorten(string? sha) =>
        string.IsNullOrEmpty(sha) ? "—" : sha.Length <= 8 ? sha : sha[..8];
}
