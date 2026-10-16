using System.Text;
using System.Text.Json.Nodes;
using BegWork.Dashboard.Core.Config;
using BegWork.Dashboard.Core.Projection;
using BegWork.Dashboard.Core.Rendering;
using BegWork.Dashboard.Core.Sources;
using BegWork.Dashboard.Core.Validation;

namespace BegWork.Dashboard.Preview;

/// <summary>
/// Renders the panel's HTML from local coordination files, without Windows and
/// without network access.
///
/// This exists so the layout can be reviewed, diffed and screenshotted on any host.
/// It is explicitly NOT a live dashboard: it reads files from a working tree rather
/// than the coordination branch, and it stubs pull-request metadata. Every page it
/// writes carries that statement in the panel's own status banner, through the same
/// shell-notice channel the Windows shell uses for AppBar fallbacks, so a rendered
/// page can never be mistaken for a live verification.
/// </summary>
internal static class Program
{
    private const string PreviewNotice =
        "OFFLINE LAYOUT PREVIEW rendered from a local working tree with stubbed pull-request "
        + "metadata. This is not a live read of the coordination branch and proves nothing about current state.";

    public static int Main(string[] args)
    {
        var repository = args.Length > 0 ? args[0] : FindRepositoryRoot();
        var output = args.Length > 1 ? args[1] : Path.Combine(repository, "tools", "dashboard", "preview-out");
        Directory.CreateDirectory(output);

        var settings = DashboardSettings.Default;
        var now = DateTimeOffset.UtcNow;

        foreach (var scenario in Scenarios(repository, now))
        {
            var model = DashboardProjection.Project(new ProjectionInput
            {
                Verified = scenario.Snapshot is null
                    ? null
                    : ControlStateVerifier.Verify(scenario.Snapshot, settings),
                Now = now,
                IsOffline = scenario.Offline,
                LastSuccessfulFetchAt = scenario.LastSuccess,
                LastError = scenario.LastError,
                Settings = settings,
                ShellNotices = [PreviewNotice, .. scenario.ExtraNotices],
            });

            var page = DashboardHtmlRenderer.RenderDocument(settings.EffectiveWidth)
                .Replace(
                    "<p class=\"muted\">Waiting for the first verified read…</p>",
                    DashboardHtmlRenderer.RenderFragment(model),
                    StringComparison.Ordinal);

            var path = Path.Combine(output, $"preview-{scenario.Name}.html");
            File.WriteAllText(path, page, Encoding.UTF8);
            Console.WriteLine(
                $"{scenario.Name,-10} status={model.Banner.StatusText,-8} live={model.Banner.IsLiveVerified,-5} -> {path}");
        }

        return 0;
    }

    private sealed record Scenario(
        string Name,
        ControlSnapshot? Snapshot,
        bool Offline = false,
        DateTimeOffset? LastSuccess = null,
        string? LastError = null,
        IReadOnlyList<string>? ExtraNotices = null)
    {
        public IReadOnlyList<string> ExtraNotices { get; init; } = ExtraNotices ?? [];
    }

    private static IEnumerable<Scenario> Scenarios(string repository, DateTimeOffset now)
    {
        yield return new Scenario("verified", Snapshot(repository, now), LastSuccess: now);

        yield return new Scenario(
            "stale-offline",
            Snapshot(repository, now.AddMinutes(-6), withBoard: false, withPullRequest: false),
            Offline: true,
            LastSuccess: now.AddMinutes(-6),
            LastError: "Read of coordination/CONTROL_STATE.json failed with HTTP 503.");

        yield return new Scenario(
            "conflict",
            Snapshot(repository, now, board: Board(repository).Replace(
                "/ **BLOCKED**", "/ **PASS**", StringComparison.Ordinal)),
            LastSuccess: now);

        yield return new Scenario(
            "invalid",
            Snapshot(repository, now, mutate: node => node.AsObject().Remove("progress")),
            LastSuccess: now);

        yield return new Scenario("no-snapshot", null, Offline: true,
            LastError: "No control-state read has succeeded in this session.");
    }

    private static string Board(string repository) =>
        File.ReadAllText(Path.Combine(repository, "coordination", "CONTROL_BOARD.md"));

    private static ControlSnapshot Snapshot(
        string repository,
        DateTimeOffset fetchedAt,
        bool withBoard = true,
        bool withPullRequest = true,
        string? board = null,
        Action<JsonNode>? mutate = null)
    {
        byte[] Read(string relative) =>
            File.ReadAllBytes(Path.Combine(repository, relative.Replace('/', Path.DirectorySeparatorChar)));

        var stateNode = JsonNode.Parse(Read("coordination/CONTROL_STATE.json"))!;
        mutate?.Invoke(stateNode);

        var state = Encoding.UTF8.GetBytes(stateNode.ToJsonString(new System.Text.Json.JsonSerializerOptions
        {
            WriteIndented = true,
        }));

        var head = stateNode["pr_head_sha"]?.GetValue<string>();
        var number = stateNode["pr_number"]?.GetValue<int>();
        var draft = stateNode["pr_draft"]?.GetValue<bool>() ?? true;

        return new ControlSnapshot
        {
            ControlStateFile = new FetchedFile("coordination/CONTROL_STATE.json", state, null),
            SchemaFile = new FetchedFile(
                "coordination/CONTROL_STATE.schema.json", Read("coordination/CONTROL_STATE.schema.json"), null),
            BoardFile = withBoard
                ? new FetchedFile(
                    "coordination/CONTROL_BOARD.md",
                    board is null ? Read("coordination/CONTROL_BOARD.md") : Encoding.UTF8.GetBytes(board),
                    null)
                : null,
            ActiveFile = new FetchedFile("coordination/ACTIVE.md", Read("coordination/ACTIVE.md"), null),
            ReviewFile = new FetchedFile(
                "coordination/REVIEWS/W0-03C.md", Read("coordination/REVIEWS/W0-03C.md"), null),
            // Stubbed from the snapshot's own citation: enough to exercise the layout,
            // never enough to claim the real pull request still has that head.
            PullRequest = withPullRequest && number is { } n && head is { } h
                ? new PullRequestMetadata(n, h, draft, "open")
                : null,
            FetchedAt = fetchedAt,
        };
    }

    private static string FindRepositoryRoot()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            if (File.Exists(Path.Combine(directory.FullName, "coordination", "CONTROL_STATE.schema.json")))
            {
                return directory.FullName;
            }
            directory = directory.Parent;
        }
        throw new InvalidOperationException("repository root not found");
    }
}
