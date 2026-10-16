using System.Text.RegularExpressions;

namespace BegWork.Dashboard.Core.Logging;

public interface IRedactingLog
{
    void Information(string message);

    void Warning(string message);

    void Error(string message);
}

/// <summary>
/// Log sink that scrubs credentials before anything is written.
///
/// Redaction happens at the sink rather than at call sites: exception messages and
/// URLs are the usual way a token escapes into a log file, and those strings are
/// assembled by code the dashboard does not own. Everything written passes through
/// here, so the token cannot reach disk even from a message nobody reviewed.
/// </summary>
public sealed class RedactingLog(Action<string> sink, IGitHubTokenSecret? secret = null) : IRedactingLog
{
    private const string Mask = "***REDACTED***";

    private static readonly Regex[] Patterns =
    [
        // GitHub token families, personal/installation/OAuth/refresh/server-to-server.
        new(@"\b(gh[pousr]|github_pat)_[A-Za-z0-9_]{16,}\b", RegexOptions.Compiled, TimeSpan.FromSeconds(1)),
        // Authorization headers however they were formatted.
        new(@"(?i)\b(authorization|bearer|token)\b\s*[:=]?\s*[A-Za-z0-9._\-]{12,}", RegexOptions.Compiled, TimeSpan.FromSeconds(1)),
        // Credentials embedded in a URL.
        new(@"://[^/\s:@]+:[^/\s@]+@", RegexOptions.Compiled, TimeSpan.FromSeconds(1)),
    ];

    public void Information(string message) => Write("INFO", message);

    public void Warning(string message) => Write("WARN", message);

    public void Error(string message) => Write("ERROR", message);

    private void Write(string level, string message) =>
        sink($"{DateTimeOffset.UtcNow:yyyy-MM-dd HH:mm:ss'Z'} {level} {Redact(message, secret)}");

    public static string Redact(string message, IGitHubTokenSecret? secret = null)
    {
        if (string.IsNullOrEmpty(message))
        {
            return message;
        }

        var scrubbed = message;

        // The exact configured token first: it may not match any known shape.
        if (secret?.GetToken() is { Length: >= 8 } token)
        {
            scrubbed = scrubbed.Replace(token, Mask, StringComparison.Ordinal);
        }

        foreach (var pattern in Patterns)
        {
            scrubbed = pattern.Replace(scrubbed, Mask);
        }

        return scrubbed;
    }
}

/// <summary>Read side of the token, used only so the sink can redact its exact value.</summary>
public interface IGitHubTokenSecret
{
    string? GetToken();
}

public sealed class NullLog : IRedactingLog
{
    public void Information(string message)
    {
    }

    public void Warning(string message)
    {
    }

    public void Error(string message)
    {
    }

    public static readonly NullLog Instance = new();
}
