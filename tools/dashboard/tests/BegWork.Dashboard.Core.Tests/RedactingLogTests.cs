using BegWork.Dashboard.Core.Logging;
using Xunit;

namespace BegWork.Dashboard.Core.Tests;

public sealed class RedactingLogTests
{
    private sealed class Secret(string? token) : IGitHubTokenSecret
    {
        public string? GetToken() => token;
    }

    [Fact]
    public void TheConfiguredTokenNeverReachesTheSink()
    {
        const string token = "ghp_EXAMPLEnotarealtoken00001";
        var written = new List<string>();
        var log = new RedactingLog(written.Add, new Secret(token));

        log.Error($"read failed for Authorization: Bearer {token}");

        var line = Assert.Single(written);
        Assert.DoesNotContain(token, line, StringComparison.Ordinal);
        Assert.Contains("REDACTED", line, StringComparison.Ordinal);
    }

    // Deliberately not real-length tokens: these exercise the redaction pattern
    // without planting a string that looks like a live credential in the history.
    [Theory]
    [InlineData("ghp_EXAMPLEnotarealtoken00000")]
    [InlineData("gho_EXAMPLEnotarealtoken00000")]
    [InlineData("github_pat_EXAMPLEnotareal0000")]
    public void KnownTokenShapesAreScrubbedEvenWithoutAConfiguredSecret(string token)
    {
        Assert.DoesNotContain(token, RedactingLog.Redact($"boom: {token}"), StringComparison.Ordinal);
    }

    [Fact]
    public void CredentialsEmbeddedInAUrlAreScrubbed()
    {
        var scrubbed = RedactingLog.Redact("clone https://user:s3cr3tvalue@github.com/krumingo/BEG_Worck");

        Assert.DoesNotContain("s3cr3tvalue", scrubbed, StringComparison.Ordinal);
    }

    [Fact]
    public void OrdinaryMessagesSurviveIntactWithALevelAndTimestamp()
    {
        var written = new List<string>();
        var log = new RedactingLog(written.Add, new Secret(null));

        log.Information("refresh round 3: status VALID");

        Assert.Contains("INFO refresh round 3: status VALID", Assert.Single(written), StringComparison.Ordinal);
    }
}
