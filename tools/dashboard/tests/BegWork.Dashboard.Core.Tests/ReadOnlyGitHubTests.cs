using System.Net;
using System.Text;
using BegWork.Dashboard.Core.Config;
using BegWork.Dashboard.Core.Refresh;
using BegWork.Dashboard.Core.Sources;
using BegWork.Dashboard.Core.Validation;
using Xunit;

namespace BegWork.Dashboard.Core.Tests;

public sealed class ReadOnlyGitHubTests
{
    private sealed class FixedToken(string? token) : IGitHubTokenProvider
    {
        public string? GetToken() => token;
    }

    private sealed class FixedClock(DateTimeOffset now) : IClock
    {
        public DateTimeOffset UtcNow => now;
    }

    private static StubGitHubHandler Handler()
    {
        var handler = new StubGitHubHandler();
        handler.AddFile(
            "coordination/CONTROL_STATE.json",
            CoordinationFixture.ReadRepositoryFile("coordination/CONTROL_STATE.json"),
            "\"state-1\"");
        handler.AddFile(
            "coordination/CONTROL_STATE.schema.json",
            CoordinationFixture.ReadRepositoryFile("coordination/CONTROL_STATE.schema.json"),
            "\"schema-1\"");
        handler.AddFile(
            "coordination/CONTROL_BOARD.md",
            CoordinationFixture.ReadRepositoryFile("coordination/CONTROL_BOARD.md"),
            "\"board-1\"");
        handler.AddFile(
            "coordination/ACTIVE.md",
            CoordinationFixture.ReadRepositoryFile("coordination/ACTIVE.md"),
            "\"active-1\"");
        handler.AddFile(
            "coordination/REVIEWS/W0-03C.md",
            CoordinationFixture.ReadRepositoryFile("coordination/REVIEWS/W0-03C.md"),
            "\"review-1\"");
        handler.PullRequestJson =
            "{\"number\":20,\"draft\":true,\"state\":\"open\",\"head\":{\"sha\":\""
            + CoordinationFixture.PublishedPrHead + "\"}}";
        return handler;
    }

    private static (CoordinationReader Reader, GitHubReadOnlyClient Client) Reader(
        StubGitHubHandler handler, string? token = null)
    {
        var settings = CoordinationFixture.Settings;
        var client = new GitHubReadOnlyClient(settings, new FixedToken(token), handler);
        return (new CoordinationReader(client, settings, new FixedClock(CoordinationFixture.Now)), client);
    }

    [Fact]
    public async Task AFullRefreshRoundIssuesOnlyReadRequests()
    {
        var handler = Handler();
        var (reader, client) = Reader(handler);
        using (client)
        {
            await reader.ReadAsync(CancellationToken.None);
            await reader.ReadAsync(CancellationToken.None);
        }

        Assert.NotEmpty(handler.Requests);
        Assert.All(handler.Requests, request =>
        {
            Assert.Equal(HttpMethod.Get, request.Method);
            Assert.Null(request.Content);
        });
    }

    [Theory]
    [InlineData("POST")]
    [InlineData("PUT")]
    [InlineData("PATCH")]
    [InlineData("DELETE")]
    public async Task AnyWriteMethodIsRefusedByTheTransport(string method)
    {
        var handler = Handler();
        using var guard = new ReadOnlyGuardHandler(handler);
        using var http = new HttpClient(guard);
        using var request = new HttpRequestMessage(
            new HttpMethod(method), "https://api.github.com/repos/krumingo/BEG_Worck/issues/26/comments");

        var violation = await Assert.ThrowsAsync<ReadOnlyViolationException>(
            () => http.SendAsync(request));

        Assert.Equal(method, violation.Method.Method);
        Assert.Empty(handler.Requests);
    }

    [Fact]
    public async Task AGetCarryingABodyIsAlsoRefused()
    {
        var handler = Handler();
        using var guard = new ReadOnlyGuardHandler(handler);
        using var http = new HttpClient(guard);
        using var request = new HttpRequestMessage(HttpMethod.Get, "https://api.github.com/graphql")
        {
            Content = new StringContent("{\"query\":\"mutation{}\"}", Encoding.UTF8, "application/json"),
        };

        await Assert.ThrowsAsync<ReadOnlyViolationException>(() => http.SendAsync(request));
        Assert.Empty(handler.Requests);
    }

    [Fact]
    public async Task TheSecondRoundSendsConditionalReadsAndReusesUnchangedBytes()
    {
        var handler = Handler();
        var (reader, client) = Reader(handler);
        ControlSnapshot second;
        using (client)
        {
            var first = await reader.ReadAsync(CancellationToken.None);
            second = await reader.ReadAsync(CancellationToken.None);
            Assert.Equal(first.ControlStateFile.BlobSha, second.ControlStateFile.BlobSha);
        }

        var fileRequests = handler.Requests
            .Where(request => request.RequestUri!.AbsolutePath.Contains("/contents/", StringComparison.Ordinal))
            .ToList();

        // Round one has no ETag to send; round two conditions every file read.
        Assert.Equal(10, fileRequests.Count);
        Assert.All(fileRequests.Take(5), request => Assert.Empty(request.Headers.IfNoneMatch));
        Assert.All(fileRequests.Skip(5), request => Assert.NotEmpty(request.Headers.IfNoneMatch));
        Assert.Equal("4bd7800657b9c7d60eab5b5b7560ecbfe46540da", second.ActiveFile!.BlobSha);
    }

    [Fact]
    public async Task ReadRequestsAreSerialisedOneAtATime()
    {
        var handler = Handler();
        var inFlight = 0;
        var peak = 0;
        handler.Interceptor = _ =>
        {
            var current = Interlocked.Increment(ref inFlight);
            peak = Math.Max(peak, current);
            Interlocked.Decrement(ref inFlight);
            return null;
        };

        var (reader, client) = Reader(handler);
        using (client)
        {
            await reader.ReadAsync(CancellationToken.None);
        }

        Assert.Equal(1, peak);
    }

    [Fact]
    public async Task ARoundReadFromTheStubVerifiesAsValidEndToEnd()
    {
        var handler = Handler();
        var (reader, client) = Reader(handler);
        ControlSnapshot snapshot;
        using (client)
        {
            snapshot = await reader.ReadAsync(CancellationToken.None);
        }

        var verified = ControlStateVerifier.Verify(snapshot, CoordinationFixture.Settings);

        Assert.Equal(ControlStateStatus.Valid, verified.Status);
        Assert.Equal("W0-03C", verified.State!.TaskId);
    }

    [Fact]
    public async Task TheTokenTravelsOnlyInTheRequestHeaderAndNeverIntoTheSnapshot()
    {
        const string token = "ghp_EXAMPLEnotarealtoken00001";
        var handler = Handler();
        var (reader, client) = Reader(handler, token);
        ControlSnapshot snapshot;
        using (client)
        {
            snapshot = await reader.ReadAsync(CancellationToken.None);
        }

        Assert.All(handler.Requests, request =>
            Assert.Equal(token, request.Headers.Authorization!.Parameter));

        var model = Projection.DashboardProjection.Project(new Projection.ProjectionInput
        {
            Verified = ControlStateVerifier.Verify(snapshot, CoordinationFixture.Settings),
            Now = CoordinationFixture.Now,
            Settings = CoordinationFixture.Settings,
            LastSuccessfulFetchAt = snapshot.FetchedAt,
        });
        var html = Rendering.DashboardHtmlRenderer.RenderFragment(model)
                   + Rendering.DashboardHtmlRenderer.RenderDocument(460);

        Assert.DoesNotContain(token, html, StringComparison.Ordinal);
        Assert.DoesNotContain("Authorization", html, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task ThrottledResponsesSurfaceAsThrottlingWithARetryHint()
    {
        var handler = Handler();
        handler.Interceptor = _ =>
        {
            var response = new HttpResponseMessage(HttpStatusCode.Forbidden);
            response.Headers.Add("x-ratelimit-remaining", "0");
            response.Headers.Add("retry-after", "42");
            return response;
        };

        using var client = new GitHubReadOnlyClient(
            CoordinationFixture.Settings, new FixedToken(null), handler);

        var thrown = await Assert.ThrowsAsync<GitHubThrottledException>(
            () => client.GetFileAsync("coordination/CONTROL_STATE.json", "codex/claude-queue", null, CancellationToken.None));

        Assert.Equal(TimeSpan.FromSeconds(42), thrown.RetryAfter);
    }

    [Fact]
    public async Task AnUnreadableOptionalSourceDegradesTheRoundInsteadOfFailingIt()
    {
        var handler = Handler();
        handler.Interceptor = request =>
            request.RequestUri!.AbsolutePath.Contains("ACTIVE.md", StringComparison.Ordinal)
                ? new HttpResponseMessage(HttpStatusCode.NotFound)
                : null;

        var (reader, client) = Reader(handler);
        ControlSnapshot snapshot;
        using (client)
        {
            snapshot = await reader.ReadAsync(CancellationToken.None);
        }

        Assert.Null(snapshot.ActiveFile);

        var verified = ControlStateVerifier.Verify(snapshot, CoordinationFixture.Settings);
        Assert.Equal(ControlStateStatus.Stale, verified.Status);
        Assert.Contains(verified.Result.Findings, finding => finding.Code == "SOURCE_UNVERIFIED");
    }
}
