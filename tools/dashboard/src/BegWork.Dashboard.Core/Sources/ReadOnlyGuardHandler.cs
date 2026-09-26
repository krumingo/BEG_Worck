namespace BegWork.Dashboard.Core.Sources;

/// <summary>Raised when anything in the dashboard attempts a non-read HTTP call.</summary>
public sealed class ReadOnlyViolationException(HttpMethod method, Uri? uri)
    : InvalidOperationException(
        $"The dashboard is a read-only consumer; refusing {method.Method} {uri?.AbsolutePath ?? "(no uri)"}.")
{
    public HttpMethod Method { get; } = method;

    public Uri? Uri { get; } = uri;
}

/// <summary>
/// Hard guard against the dashboard ever writing to GitHub.
///
/// The requirement is not "we intend not to write" but "it cannot write", so the
/// prohibition lives in the transport rather than in each call site: any future
/// code path that tries a POST/PATCH/PUT/DELETE fails loudly in tests and at
/// runtime instead of quietly mutating coordination state.
/// </summary>
public sealed class ReadOnlyGuardHandler : DelegatingHandler
{
    public ReadOnlyGuardHandler()
    {
    }

    public ReadOnlyGuardHandler(HttpMessageHandler inner)
        : base(inner)
    {
    }

    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(request);

        if (request.Method != HttpMethod.Get && request.Method != HttpMethod.Head)
        {
            throw new ReadOnlyViolationException(request.Method, request.RequestUri);
        }

        if (request.Content is not null)
        {
            throw new ReadOnlyViolationException(request.Method, request.RequestUri);
        }

        return base.SendAsync(request, cancellationToken);
    }
}
