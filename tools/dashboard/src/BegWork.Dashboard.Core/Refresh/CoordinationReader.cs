using BegWork.Dashboard.Core.Config;
using BegWork.Dashboard.Core.Model;
using BegWork.Dashboard.Core.Sources;
using System.Text.Json;

namespace BegWork.Dashboard.Core.Refresh;

/// <summary>One polling round: read every source the verifier needs.</summary>
public interface ICoordinationSource
{
    Task<ControlSnapshot> ReadAsync(CancellationToken cancellationToken);
}

/// <summary>
/// Reads the coordination read-model from GitHub, one request at a time.
///
/// Serial rather than parallel: the sources are cross-checked against each other,
/// so a round that interleaves with a producer commit would compare a new state
/// against an old board. Requests are conditional, and unchanged files are served
/// from the previous round's bytes, so a quiet branch costs six 304s.
/// </summary>
public sealed class CoordinationReader(
    GitHubReadOnlyClient client,
    DashboardSettings settings,
    IClock clock) : ICoordinationSource
{
    private const string SchemaPath = "coordination/CONTROL_STATE.schema.json";
    private const string StatePath = "coordination/CONTROL_STATE.json";
    private const string BoardPath = "coordination/CONTROL_BOARD.md";

    private readonly Dictionary<string, (string? ETag, FetchedFile File)> _cache = new(StringComparer.Ordinal);

    public async Task<ControlSnapshot> ReadAsync(CancellationToken cancellationToken)
    {
        var state = await ReadFileAsync(StatePath, cancellationToken).ConfigureAwait(false);
        var schema = await ReadFileAsync(SchemaPath, cancellationToken).ConfigureAwait(false);
        var board = await TryReadFileAsync(BoardPath, cancellationToken).ConfigureAwait(false);

        // The cited source paths come from the state document itself, so they are
        // read only after the state has been parsed far enough to name them.
        var citedActive = "coordination/ACTIVE.md";
        string? citedReview = null;
        int? prNumber = null;

        try
        {
            using var document = JsonDocument.Parse(state.Content);
            var root = document.RootElement;
            if (root.TryGetProperty("source_refs", out var refs))
            {
                citedActive = Text(refs, "active_path") ?? citedActive;
                citedReview = Text(refs, "review_path");
            }

            if (root.TryGetProperty("pr_number", out var number) && number.ValueKind == JsonValueKind.Number)
            {
                prNumber = number.GetInt32();
            }
        }
        catch (JsonException)
        {
            // Leave the optional sources unread; the verifier reports the parse failure.
        }

        var active = await TryReadFileAsync(citedActive, cancellationToken).ConfigureAwait(false);
        var review = citedReview is null
            ? null
            : await TryReadFileAsync(citedReview, cancellationToken).ConfigureAwait(false);

        PullRequestMetadata? pullRequest = null;
        if (prNumber is { } number2)
        {
            try
            {
                pullRequest = await client.GetPullRequestAsync(number2, cancellationToken).ConfigureAwait(false);
            }
            catch (HttpRequestException)
            {
                // Unverified PR head degrades the status; it does not fail the round.
            }
        }

        return new ControlSnapshot
        {
            ControlStateFile = state,
            SchemaFile = schema,
            BoardFile = board,
            ActiveFile = active,
            ReviewFile = review,
            PullRequest = pullRequest,
            FetchedAt = clock.UtcNow,
        };
    }

    private static string? Text(JsonElement parent, string name) =>
        parent.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.String
            ? value.GetString()
            : null;

    private async Task<FetchedFile> ReadFileAsync(string path, CancellationToken cancellationToken)
    {
        _cache.TryGetValue(path, out var previous);
        var fetch = await client
            .GetFileAsync(path, settings.Branch, previous.ETag, cancellationToken)
            .ConfigureAwait(false);

        if (fetch.NotModified && previous.File is { } cached)
        {
            return cached;
        }

        if (fetch.File is not { } file)
        {
            throw new InvalidOperationException($"GitHub reported {path} unchanged but nothing was cached.");
        }

        _cache[path] = (file.ETag, file);
        return file;
    }

    private async Task<FetchedFile?> TryReadFileAsync(string path, CancellationToken cancellationToken)
    {
        try
        {
            return await ReadFileAsync(path, cancellationToken).ConfigureAwait(false);
        }
        catch (HttpRequestException)
        {
            return null;
        }
        catch (InvalidOperationException)
        {
            return null;
        }
    }
}
