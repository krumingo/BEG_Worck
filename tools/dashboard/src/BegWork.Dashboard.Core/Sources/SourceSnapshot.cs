namespace BegWork.Dashboard.Core.Sources;

/// <summary>One file as fetched from the coordination branch, with its bytes kept
/// so the consumer can recompute the blob id instead of trusting the response.</summary>
public sealed record FetchedFile(string Path, byte[] Content, string? ETag)
{
    public string BlobSha => GitObjectId.BlobSha1(Content);

    public string Text => System.Text.Encoding.UTF8.GetString(Content);
}

/// <summary>Read-only pull-request metadata used only to verify the cited exact head.</summary>
public sealed record PullRequestMetadata(int Number, string HeadSha, bool Draft, string State);

/// <summary>
/// Everything one polling round managed to read. Any member may be null when that
/// source could not be read; the verifier degrades the status rather than guessing.
/// </summary>
public sealed record ControlSnapshot
{
    public required FetchedFile ControlStateFile { get; init; }
    public required FetchedFile SchemaFile { get; init; }
    public FetchedFile? BoardFile { get; init; }
    public FetchedFile? ActiveFile { get; init; }
    public FetchedFile? ReviewFile { get; init; }
    public PullRequestMetadata? PullRequest { get; init; }

    /// <summary>Head commit of the coordination branch at fetch time, when known.</summary>
    public string? BranchHeadSha { get; init; }

    public required DateTimeOffset FetchedAt { get; init; }
}
