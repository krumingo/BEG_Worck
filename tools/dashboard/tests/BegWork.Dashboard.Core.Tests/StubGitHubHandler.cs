using System.Net;
using System.Text;

namespace BegWork.Dashboard.Core.Tests;

/// <summary>
/// In-process stand-in for api.github.com.
///
/// It records every request so a test can assert what the dashboard actually sent —
/// the method, and that no body ever accompanied it — and it implements
/// <c>If-None-Match</c> so the conditional-read path is exercised for real rather
/// than mocked away.
/// </summary>
internal sealed class StubGitHubHandler : HttpMessageHandler
{
    private readonly Dictionary<string, (byte[] Body, string ETag)> _files = new(StringComparer.Ordinal);

    public List<HttpRequestMessage> Requests { get; } = [];

    public string? PullRequestJson { get; set; }

    public Func<HttpRequestMessage, HttpResponseMessage?>? Interceptor { get; set; }

    public void AddFile(string path, byte[] body, string etag) => _files[path] = (body, etag);

    public void AddFile(string path, string body, string etag) =>
        AddFile(path, Encoding.UTF8.GetBytes(body), etag);

    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        Requests.Add(request);

        if (Interceptor?.Invoke(request) is { } intercepted)
        {
            return Task.FromResult(intercepted);
        }

        var uri = request.RequestUri!;

        if (uri.AbsolutePath.Contains("/pulls/", StringComparison.Ordinal))
        {
            return Task.FromResult(PullRequestJson is null
                ? new HttpResponseMessage(HttpStatusCode.NotFound)
                : Json(PullRequestJson));
        }

        const string marker = "/contents/";
        var index = uri.AbsolutePath.IndexOf(marker, StringComparison.Ordinal);
        if (index < 0)
        {
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound));
        }

        var path = uri.AbsolutePath[(index + marker.Length)..];
        if (!_files.TryGetValue(path, out var file))
        {
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotFound));
        }

        if (request.Headers.IfNoneMatch.Any(tag => tag.Tag == file.ETag))
        {
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.NotModified));
        }

        var response = new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new ByteArrayContent(file.Body),
        };
        response.Headers.ETag = new System.Net.Http.Headers.EntityTagHeaderValue(file.ETag);
        return Task.FromResult(response);
    }

    private static HttpResponseMessage Json(string body)
    {
        var response = new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(body, Encoding.UTF8, "application/json"),
        };
        return response;
    }
}
