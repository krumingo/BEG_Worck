using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using BegWork.Dashboard.Core.Config;
using BegWork.Dashboard.Core.Sources;

namespace BegWork.Dashboard.Core.Tests;

/// <summary>
/// Builds snapshots from the repository's own published coordination artifacts.
///
/// The baseline is the real <c>coordination/</c> tree rather than a hand-written
/// fixture, so a test that says "the published snapshot verifies" is evidence about
/// the actual read-model and not about a copy that drifted. Negative cases mutate a
/// clone of that baseline, one field at a time.
/// </summary>
internal static class CoordinationFixture
{
    /// <summary>Exact PR head cited by the published W0-03C snapshot.</summary>
    public const string PublishedPrHead = "ed588e9420e241f58c14146de6f0c890b38b3743";

    public const string EarlierPrHead = "be8cd207c94388e81b24173af6d690d69abcea00";

    public static readonly DateTimeOffset Now = DateTimeOffset.Parse("2026-09-25T18:00:00Z");

    private static readonly Lazy<DirectoryInfo> Root = new(FindRepositoryRoot);

    public static DashboardSettings Settings => DashboardSettings.Default;

    public static byte[] ReadRepositoryFile(string relativePath) =>
        File.ReadAllBytes(Path.Combine(Root.Value.FullName, relativePath));

    public static JsonNode PublishedStateNode() =>
        JsonNode.Parse(ReadRepositoryFile("coordination/CONTROL_STATE.json"))
        ?? throw new InvalidOperationException("published control state did not parse");

    /// <summary>The published snapshot, with PR metadata matching its cited exact head.</summary>
    public static ControlSnapshot Published() => Build(PublishedStateNode());

    /// <summary>The published snapshot with one mutation applied to the state document.</summary>
    public static ControlSnapshot Mutated(Action<JsonNode> mutate)
    {
        var node = PublishedStateNode();
        mutate(node);
        return Build(node);
    }

    public static ControlSnapshot Build(
        JsonNode state,
        string? boardOverride = null,
        bool includeBoard = true,
        bool includeActive = true,
        bool includeReview = true,
        PullRequestMetadata? pullRequest = null,
        bool includePullRequest = true,
        DateTimeOffset? fetchedAt = null)
    {
        var stateBytes = Encoding.UTF8.GetBytes(state.ToJsonString(new JsonSerializerOptions
        {
            WriteIndented = true,
        }));

        return new ControlSnapshot
        {
            ControlStateFile = new FetchedFile("coordination/CONTROL_STATE.json", stateBytes, "\"state\""),
            SchemaFile = new FetchedFile(
                "coordination/CONTROL_STATE.schema.json",
                ReadRepositoryFile("coordination/CONTROL_STATE.schema.json"),
                "\"schema\""),
            BoardFile = !includeBoard
                ? null
                : new FetchedFile(
                    "coordination/CONTROL_BOARD.md",
                    boardOverride is null
                        ? ReadRepositoryFile("coordination/CONTROL_BOARD.md")
                        : Encoding.UTF8.GetBytes(boardOverride),
                    "\"board\""),
            ActiveFile = includeActive
                ? new FetchedFile("coordination/ACTIVE.md", ReadRepositoryFile("coordination/ACTIVE.md"), "\"active\"")
                : null,
            ReviewFile = includeReview
                ? new FetchedFile(
                    "coordination/REVIEWS/W0-03C.md",
                    ReadRepositoryFile("coordination/REVIEWS/W0-03C.md"),
                    "\"review\"")
                : null,
            PullRequest = includePullRequest
                ? pullRequest ?? new PullRequestMetadata(20, PublishedPrHead, Draft: true, "open")
                : null,
            FetchedAt = fetchedAt ?? Now,
        };
    }

    public static string PublishedBoardText() =>
        Encoding.UTF8.GetString(ReadRepositoryFile("coordination/CONTROL_BOARD.md"));

    /// <summary>
    /// The published board rewritten to agree with a different protocol state, so a
    /// test can exercise that state without tripping the board cross-check, which is
    /// a separate concern with its own tests.
    /// </summary>
    public static string BoardWithState(string state) => PublishedBoardText()
        .Replace("/ **BLOCKED**", $"/ **{state}**", StringComparison.Ordinal)
        .Replace("STATE: BLOCKED", $"STATE: {state}", StringComparison.Ordinal);

    private static DirectoryInfo FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "coordination", "CONTROL_STATE.schema.json")))
            {
                return directory;
            }
            directory = directory.Parent;
        }

        throw new InvalidOperationException(
            "Could not locate the repository root from " + AppContext.BaseDirectory);
    }
}
