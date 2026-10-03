using BegWork.Dashboard.Core.Config;
using BegWork.Dashboard.Core.Projection;
using BegWork.Dashboard.Core.Rendering;
using BegWork.Dashboard.Core.Sources;
using BegWork.Dashboard.Core.Validation;
using Xunit;

namespace BegWork.Dashboard.Core.Tests;

public sealed class RenderingTests
{
    private static DashboardViewModel Model(
        ControlSnapshot? snapshot = null, bool offline = false, DateTimeOffset? now = null)
    {
        snapshot ??= CoordinationFixture.Published();
        return DashboardProjection.Project(new ProjectionInput
        {
            Verified = ControlStateVerifier.Verify(snapshot, CoordinationFixture.Settings),
            Now = now ?? CoordinationFixture.Now,
            IsOffline = offline,
            LastSuccessfulFetchAt = snapshot.FetchedAt,
            Settings = CoordinationFixture.Settings,
        });
    }

    [Fact]
    public void FragmentShowsTheProtocolFactsAsText()
    {
        var html = DashboardHtmlRenderer.RenderFragment(Model());

        Assert.Contains("BEG_WORK", html, StringComparison.Ordinal);
        Assert.Contains("W0-03C", html, StringComparison.Ordinal);
        Assert.Contains("C02", html, StringComparison.Ordinal);
        Assert.Contains("W0-03C/C02/CX", html, StringComparison.Ordinal);
        Assert.Contains("KRUM ACTION", html, StringComparison.Ordinal);
        Assert.Contains("REQUIRED", html, StringComparison.Ordinal);
        Assert.Contains("ChatGPT", html, StringComparison.Ordinal);
        Assert.Contains("Codex", html, StringComparison.Ordinal);
        Assert.Contains("Claude", html, StringComparison.Ordinal);
    }

    [Fact]
    public void StatusIsAlwaysSpelledOutAndNotSignalledByColourAlone()
    {
        var stale = DashboardHtmlRenderer.RenderFragment(
            Model(offline: true, now: CoordinationFixture.Now.AddMinutes(10)));

        Assert.Contains(">STALE<", stale, StringComparison.Ordinal);
        Assert.Contains("OFFLINE", stale, StringComparison.Ordinal);
        Assert.Contains("Not live-verified", stale, StringComparison.Ordinal);
        Assert.Contains("role=\"status\"", stale, StringComparison.Ordinal);
        Assert.Contains("aria-live=\"polite\"", stale, StringComparison.Ordinal);
    }

    [Fact]
    public void NoProgressBarIsDrawnWhenNoPercentageIsProven()
    {
        var html = DashboardHtmlRenderer.RenderFragment(Model());

        Assert.DoesNotContain("class=\"meter\"", html, StringComparison.Ordinal);
        Assert.Contains("No proven percentage", html, StringComparison.Ordinal);
    }

    [Fact]
    public void AProvenPercentageIsDrawnWithAnAccessibleLabel()
    {
        var snapshot = CoordinationFixture.Mutated(node =>
        {
            node["progress"]!["mode"] = "EVIDENCE_COUNT";
            node["progress"]!["completed"] = 1;
            node["progress"]!["total"] = 4;
            node["progress"]!["percent"] = 25;
        });

        var html = DashboardHtmlRenderer.RenderFragment(Model(snapshot));

        Assert.Contains("aria-label=\"Progress 25 percent\"", html, StringComparison.Ordinal);
        Assert.Contains("width:25%", html, StringComparison.Ordinal);
    }

    [Fact]
    public void HostileTextInTheReadModelIsEscaped()
    {
        var snapshot = CoordinationFixture.Mutated(node =>
        {
            var injected = "<img src=x onerror=alert(1)>\"'";
            node["waiting_for"] = injected;
            node["agent_states"]!["CODEX"]!["waiting_for"] = injected;
            node["requires_krum_reason"] = injected;
        });

        var html = DashboardHtmlRenderer.RenderFragment(Model(snapshot));

        Assert.DoesNotContain("<img src=x", html, StringComparison.Ordinal);
        Assert.Contains("&lt;img src=x onerror=alert(1)&gt;", html, StringComparison.Ordinal);
    }

    [Fact]
    public void ANonHttpEvidenceUrlIsPrintedAsTextRatherThanLinked()
    {
        var snapshot = CoordinationFixture.Mutated(node =>
            node["dispatch_run_url"] = "javascript:alert(1)");

        var html = DashboardHtmlRenderer.RenderFragment(Model(snapshot));

        Assert.DoesNotContain("href=\"javascript:", html, StringComparison.Ordinal);
    }

    [Fact]
    public void TheEmptyStateExplainsItselfInsteadOfShowingBlankFields()
    {
        var html = DashboardHtmlRenderer.RenderFragment(DashboardProjection.Project(new ProjectionInput
        {
            Verified = null,
            Now = CoordinationFixture.Now,
            IsOffline = true,
            Settings = CoordinationFixture.Settings,
        }));

        Assert.Contains("No verified control state", html, StringComparison.Ordinal);
        Assert.DoesNotContain("KRUM ACTION", html, StringComparison.Ordinal);
    }

    [Fact]
    public void FindingsAreListedSoTheOperatorSeesEveryReason()
    {
        var html = DashboardHtmlRenderer.RenderFragment(Model(CoordinationFixture.Build(
            CoordinationFixture.PublishedStateNode(), includeBoard: false, includePullRequest: false)));

        Assert.Contains("BOARD_UNREAD", html, StringComparison.Ordinal);
        Assert.Contains("PR_UNVERIFIED", html, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(420)]
    [InlineData(460)]
    [InlineData(500)]
    public void TheDocumentShellConstrainsItselfToThePanelWidth(int width)
    {
        var document = DashboardHtmlRenderer.RenderDocument(width);

        Assert.Contains($"max-width: {width}px", document, StringComparison.Ordinal);
        Assert.Contains("overflow-x: hidden", document, StringComparison.Ordinal);
        Assert.Contains("id=\"beg-root\"", document, StringComparison.Ordinal);
    }

    [Fact]
    public void TheDocumentShellAllowsNoNetworkOrigins()
    {
        var document = DashboardHtmlRenderer.RenderDocument(DashboardSettings.DefaultWidth);

        Assert.Contains("default-src 'none'", document, StringComparison.Ordinal);
        Assert.DoesNotContain("http://", document, StringComparison.Ordinal);
        Assert.DoesNotContain("https://", document, StringComparison.Ordinal);
    }

    [Fact]
    public void PipelineMarksExactlyOneActiveStepWithAriaCurrent()
    {
        var html = DashboardHtmlRenderer.RenderFragment(Model());

        Assert.Equal(1, CountOf(html, "aria-current=\"step\""));
    }

    private static int CountOf(string haystack, string needle)
    {
        var count = 0;
        var index = 0;
        while ((index = haystack.IndexOf(needle, index, StringComparison.Ordinal)) >= 0)
        {
            count++;
            index += needle.Length;
        }
        return count;
    }
}
