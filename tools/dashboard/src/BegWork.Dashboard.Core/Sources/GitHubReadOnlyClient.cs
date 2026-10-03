using System.Net;
using System.Net.Http.Headers;
using System.Text.Json;
using BegWork.Dashboard.Core.Config;

namespace BegWork.Dashboard.Core.Sources;

/// <summary>Supplies the GitHub token without ever exposing it on a model or view.</summary>
public interface IGitHubTokenProvider
{
    string? GetToken();
}

public sealed class EnvironmentTokenProvider(params string[] variableNames) : IGitHubTokenProvider
{
    private readonly string[] _variableNames = variableNames.Length > 0
        ? variableNames
        : ["BEGWORK_DASHBOARD_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"];

    public string? GetToken() => _variableNames
        .Select(Environment.GetEnvironmentVariable)
        .FirstOrDefault(value => !string.IsNullOrWhiteSpace(value));
}

/// <summary>Result of one conditional read.</summary>
public sealed record FileFetch(bool NotModified, FetchedFile? File)
{
    public static readonly FileFetch Unchanged = new(true, null);
}

/// <summary>GitHub answered with a rate-limit or secondary-limit response.</summary>
public sealed class GitHubThrottledException(TimeSpan? retryAfter, string message)
    : HttpRequestException(message)
{
    public TimeSpan? RetryAfter { get; } = retryAfter;
}

/// <summary>
/// Minimal read-only GitHub client: conditional GETs for coordination files and
/// pull-request metadata, and nothing else.
///
/// Requests are issued one at a time by the caller (see
/// <see cref="Refresh.CoordinationReader"/>) so a slow round cannot fan out into a
/// burst. Every request carries <c>If-None-Match</c> when an ETag is known, so a
/// quiet repository costs 304s rather than payloads.
/// </summary>
public sealed class GitHubReadOnlyClient : IDisposable
{
    private const string ApiRoot = "https://api.github.com";

    private readonly HttpClient _http;
    private readonly IGitHubTokenProvider _tokens;
    private readonly bool _ownsClient;

    public GitHubReadOnlyClient(
        DashboardSettings settings,
        IGitHubTokenProvider tokens,
        HttpMessageHandler? innerHandler = null)
    {
        ArgumentNullException.ThrowIfNull(settings);
        _tokens = tokens ?? throw new ArgumentNullException(nameof(tokens));
        Settings = settings;

        var guarded = innerHandler is null
            ? new ReadOnlyGuardHandler(new HttpClientHandler())
            : new ReadOnlyGuardHandler(innerHandler);

        _http = new HttpClient(guarded, disposeHandler: true)
        {
            Timeout = TimeSpan.FromSeconds(20),
        };
        _http.DefaultRequestHeaders.UserAgent.Add(
            new ProductInfoHeaderValue("BEG_WORK-Dashboard", "0.1"));
        _http.DefaultRequestHeaders.Add("X-GitHub-Api-Version", "2022-11-28");
        _ownsClient = true;
    }

    public DashboardSettings Settings { get; }

    /// <summary>Conditionally reads one file's raw bytes from a branch or commit.</summary>
    public async Task<FileFetch> GetFileAsync(
        string path, string reference, string? etag, CancellationToken cancellationToken)
    {
        var uri = new Uri(
            $"{ApiRoot}/repos/{Settings.Owner}/{Settings.Name}/contents/{Uri.EscapeDataString(path).Replace("%2F", "/", StringComparison.Ordinal)}?ref={Uri.EscapeDataString(reference)}");

        using var request = Build(uri, etag, "application/vnd.github.raw");
        using var response = await _http.SendAsync(request, cancellationToken).ConfigureAwait(false);

        if (response.StatusCode == HttpStatusCode.NotModified)
        {
            return FileFetch.Unchanged;
        }

        await EnsureReadableAsync(response, path).ConfigureAwait(false);

        var content = await response.Content.ReadAsByteArrayAsync(cancellationToken).ConfigureAwait(false);
        return new FileFetch(false, new FetchedFile(path, content, response.Headers.ETag?.Tag));
    }

    /// <summary>Reads pull-request metadata used only to confirm the cited exact head.</summary>
    public async Task<PullRequestMetadata> GetPullRequestAsync(
        int number, CancellationToken cancellationToken)
    {
        var uri = new Uri($"{ApiRoot}/repos/{Settings.Owner}/{Settings.Name}/pulls/{number}");

        using var request = Build(uri, etag: null, "application/vnd.github+json");
        using var response = await _http.SendAsync(request, cancellationToken).ConfigureAwait(false);
        await EnsureReadableAsync(response, $"pull/{number}").ConfigureAwait(false);

        await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        using var document = await JsonDocument.ParseAsync(stream, default, cancellationToken).ConfigureAwait(false);
        var root = document.RootElement;

        return new PullRequestMetadata(
            root.GetProperty("number").GetInt32(),
            root.GetProperty("head").GetProperty("sha").GetString() ?? string.Empty,
            root.TryGetProperty("draft", out var draft) && draft.GetBoolean(),
            root.GetProperty("state").GetString() ?? string.Empty);
    }

    private HttpRequestMessage Build(Uri uri, string? etag, string accept)
    {
        var request = new HttpRequestMessage(HttpMethod.Get, uri);
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue(accept));

        if (!string.IsNullOrWhiteSpace(etag))
        {
            request.Headers.IfNoneMatch.Add(new EntityTagHeaderValue(etag, isWeak: etag.StartsWith("W/", StringComparison.Ordinal)));
        }

        // The token is attached here, per request, and never stored on a model,
        // written to a log, or handed to the WebView.
        if (_tokens.GetToken() is { Length: > 0 } token)
        {
            request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        }

        return request;
    }

    private static async Task EnsureReadableAsync(HttpResponseMessage response, string what)
    {
        if (response.IsSuccessStatusCode)
        {
            return;
        }

        var remaining = response.Headers.TryGetValues("x-ratelimit-remaining", out var values)
            ? values.FirstOrDefault()
            : null;

        if (response.StatusCode is HttpStatusCode.Forbidden or HttpStatusCode.TooManyRequests)
        {
            throw new GitHubThrottledException(
                RetryAfter(response),
                $"GitHub throttled the read of {what} (HTTP {(int)response.StatusCode}, remaining={remaining ?? "?"}).");
        }

        // The body can echo request details; only the status code is reported.
        await Task.CompletedTask.ConfigureAwait(false);
        throw new HttpRequestException(
            $"Read of {what} failed with HTTP {(int)response.StatusCode}.",
            inner: null,
            statusCode: response.StatusCode);
    }

    private static TimeSpan? RetryAfter(HttpResponseMessage response)
    {
        if (response.Headers.RetryAfter?.Delta is { } delta)
        {
            return delta;
        }

        if (response.Headers.TryGetValues("x-ratelimit-reset", out var reset)
            && long.TryParse(reset.FirstOrDefault(), out var epoch))
        {
            var wait = DateTimeOffset.FromUnixTimeSeconds(epoch) - DateTimeOffset.UtcNow;
            return wait > TimeSpan.Zero ? wait : null;
        }

        return null;
    }

    public void Dispose()
    {
        if (_ownsClient)
        {
            _http.Dispose();
        }
    }
}
