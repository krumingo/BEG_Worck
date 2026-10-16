using System.Globalization;
using System.Net;
using System.Text;
using BegWork.Dashboard.Core.Projection;
using BegWork.Dashboard.Core.Validation;

namespace BegWork.Dashboard.Core.Rendering;

/// <summary>
/// Renders the view model to HTML for the WebView2 surface.
///
/// The document shell is loaded once and the body is replaced from a pushed
/// fragment, so a refresh does not renavigate — renavigating every few seconds
/// would reset scroll position and can pull focus, which this panel must never do.
///
/// Every value is HTML-escaped here, in one place. The fragment therefore contains
/// only markup this renderer produced plus escaped read-model text, and the page
/// carries no credentials: the view model has no token field and the client attaches
/// the token per request, outside the WebView entirely.
/// </summary>
public static class DashboardHtmlRenderer
{
    public const string FragmentElementId = "beg-root";

    /// <summary>The static shell: styles, the mount point and the message pump.</summary>
    public static string RenderDocument(int width)
    {
        var builder = new StringBuilder();
        builder.Append("<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">");
        builder.Append("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">");
        // No network origins at all: the panel is entirely self-contained.
        builder.Append("<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';\">");
        builder.Append("<title>BEG_WORK control panel</title>");
        builder.Append("<style>").Append(Css(width)).Append("</style></head>");
        builder.Append("<body><main id=\"").Append(FragmentElementId)
               .Append("\" aria-label=\"BEG_WORK control panel\"><p class=\"muted\">Waiting for the first verified read…</p></main>");
        builder.Append("<script>").Append(Script()).Append("</script>");
        builder.Append("</body></html>");
        return builder.ToString();
    }

    private static string Script() =>
        """
        (function () {
          var root = document.getElementById('beg-root');
          if (!window.chrome || !window.chrome.webview) { return; }
          window.chrome.webview.addEventListener('message', function (event) {
            var payload = event.data;
            if (!payload || typeof payload.html !== 'string') { return; }
            var top = window.scrollY;
            root.innerHTML = payload.html;
            window.scrollTo(0, top);
          });
        })();
        """;

    public static string RenderFragment(DashboardViewModel model)
    {
        ArgumentNullException.ThrowIfNull(model);

        var html = new StringBuilder();
        AppendBanner(html, model.Banner);

        if (!model.HasContent)
        {
            html.Append("<section class=\"card empty\"><h2>No verified control state</h2><p>")
                .Append(Escape(model.EmptyStateMessage ?? "Nothing to show."))
                .Append("</p></section>");
            return html.ToString();
        }

        AppendHeader(html, model);
        AppendProgress(html, model.Progress);
        AppendPipeline(html, model.Pipeline);
        AppendAgents(html, model.AgentCards);
        AppendTasks(html, model);
        AppendActivity(html, model.RecentActivity);
        AppendEvidence(html, model.Evidence);
        return html.ToString();
    }

    private static void AppendBanner(StringBuilder html, StatusBannerView banner)
    {
        // role=status + aria-live so a screen reader announces a status change; the
        // status word is always spelled out, never signalled by colour alone.
        html.Append("<section class=\"banner ").Append(StatusClass(banner.Status))
            .Append("\" role=\"status\" aria-live=\"polite\">");
        html.Append("<p class=\"banner-head\"><span class=\"tag\">")
            .Append(Escape(banner.StatusText)).Append("</span> ")
            .Append(Escape(banner.Headline)).Append("</p>");

        html.Append("<p class=\"muted\">Last verified read: ")
            .Append(Escape(banner.LastVerifiedAtText ?? "never"));
        if (banner.Age is { } age)
        {
            html.Append(" · age ").Append(Escape(FormatAge(age)));
        }
        html.Append(banner.IsOffline ? " · <strong>OFFLINE</strong>" : string.Empty).Append("</p>");

        if (!banner.IsLiveVerified)
        {
            html.Append("<p class=\"warn-line\">Not live-verified. Values below are a snapshot, not confirmed current truth.</p>");
        }

        if (banner.LastError is { Length: > 0 } error)
        {
            html.Append("<p class=\"warn-line\">Last read error: ").Append(Escape(error)).Append("</p>");
        }

        foreach (var notice in banner.ShellNotices)
        {
            html.Append("<p class=\"warn-line\">Shell: ").Append(Escape(notice)).Append("</p>");
        }

        if (banner.Findings.Count > 0)
        {
            html.Append("<ul class=\"findings\">");
            foreach (var finding in banner.Findings)
            {
                html.Append("<li><span class=\"tag small ").Append(StatusClass(finding.Status)).Append("\">")
                    .Append(Escape(finding.Status.ToProtocolName())).Append("</span> <code>")
                    .Append(Escape(finding.Code)).Append("</code> ")
                    .Append(Escape(finding.Message)).Append("</li>");
            }
            html.Append("</ul>");
        }

        html.Append("</section>");
    }

    private static void AppendHeader(StringBuilder html, DashboardViewModel model)
    {
        var header = model.Header!;
        html.Append("<section class=\"card\">");
        html.Append("<h1>BEG_WORK</h1>");
        html.Append("<dl class=\"grid\">");
        Definition(html, "Wave", header.Wave);
        Definition(html, "Flow", header.Flow);
        Definition(html, "Task-ID", header.TaskId);
        Definition(html, "Cycle-ID", $"{header.CycleId} ({header.CycleOrigin.ToLowerInvariant()})");
        Definition(html, "Work-ID", header.WorkId);
        Definition(html, "State", header.StateDisplay);
        Definition(html, "Current", $"{header.CurrentAgent} · {header.CurrentRole}");
        Definition(html, "Next", header.NextAgent);
        Definition(html, "Dispatch", header.DispatchState);
        Definition(html, "Source", $"{header.Repository} @ {header.Branch}");
        html.Append("</dl>");

        html.Append("<p class=\"row\"><span class=\"label\">Waiting for</span> <span>")
            .Append(Escape(header.WaitingFor ?? "—")).Append("</span></p>");

        html.Append("<p class=\"krum ").Append(header.KrumActionRequired ? "required" : "none")
            .Append("\"><span class=\"label\">KRUM ACTION</span> <strong>")
            .Append(Escape(header.KrumActionText)).Append("</strong></p>");

        html.Append("<p class=\"muted\">Snapshot validated ").Append(Escape(header.SnapshotValidatedAt))
            .Append(" · source updated ").Append(Escape(header.SourceUpdatedAt))
            .Append(" · producer ").Append(Escape(header.Producer)).Append("</p>");
        html.Append("</section>");
    }

    private static void AppendProgress(StringBuilder html, ProgressView progress)
    {
        html.Append("<section class=\"card\"><h2>Progress</h2>");
        html.Append("<p class=\"row\"><span class=\"label\">Stage</span> <span>")
            .Append(Escape(progress.Stage ?? "UNKNOWN")).Append("</span></p>");
        html.Append("<p class=\"row\"><span class=\"label\">Mode</span> <span>")
            .Append(Escape(progress.Mode ?? "UNKNOWN")).Append("</span></p>");

        if (progress.CountsText is { } counts)
        {
            html.Append("<p class=\"row\"><span class=\"label\">Verified</span> <span>")
                .Append(Escape(counts)).Append("</span></p>");
        }

        if (progress.HasProvenPercentage)
        {
            var percent = progress.Percent!.Value;
            html.Append("<div class=\"meter\" role=\"img\" aria-label=\"Progress ")
                .Append(percent.ToString(CultureInfo.InvariantCulture))
                .Append(" percent\"><span style=\"width:").Append(percent.ToString(CultureInfo.InvariantCulture))
                .Append("%\"></span></div>");
            html.Append("<p class=\"row\"><span class=\"label\">Percent</span> <span>")
                .Append(Escape(progress.PercentText)).Append("</span></p>");
        }
        else
        {
            // No bar, no number: the read-model proved none, so none is shown.
            html.Append("<p class=\"muted\">No proven percentage. Stage and verified counts only.</p>");
        }

        html.Append("</section>");
    }

    private static void AppendPipeline(StringBuilder html, IReadOnlyList<PipelineStepView> pipeline)
    {
        html.Append("<section class=\"card\"><h2>Pipeline</h2><ol class=\"pipeline\">");
        foreach (var step in pipeline)
        {
            html.Append("<li class=\"").Append(step.IsActive ? "active" : "idle").Append('"');
            if (step.IsActive)
            {
                html.Append(" aria-current=\"step\"");
            }
            html.Append("><span class=\"ord\">").Append(step.Ordinal.ToString(CultureInfo.InvariantCulture))
                .Append("</span> <span>").Append(Escape(step.Label)).Append("</span>");
            if (step.IsActive)
            {
                html.Append(" <span class=\"tag small\">")
                    .Append(step.IsActiveVerified ? "ACTIVE" : "ACTIVE (UNVERIFIED)").Append("</span>");
            }
            html.Append("</li>");
        }
        html.Append("</ol></section>");
    }

    private static void AppendAgents(StringBuilder html, IReadOnlyList<AgentCardView> agents)
    {
        html.Append("<section class=\"card\"><h2>Agents</h2>");
        html.Append("<p class=\"muted\">From published <code>agent_states</code> only; history is evidence, not status.</p>");
        foreach (var agent in agents)
        {
            html.Append("<article class=\"agent ").Append(agent.IsCurrent ? "current" : "other").Append("\">");
            html.Append("<p class=\"agent-head\"><strong>").Append(Escape(agent.DisplayName))
                .Append("</strong> <span class=\"muted\">").Append(Escape(agent.Role)).Append("</span>");
            if (agent.IsCurrent)
            {
                html.Append(" <span class=\"tag small\">CURRENT</span>");
            }
            html.Append("</p>");
            html.Append("<p class=\"row\"><span class=\"label\">State</span> <span class=\"state-")
                .Append(StateClass(agent.State)).Append("\">").Append(Escape(agent.State)).Append("</span></p>");
            html.Append("<p class=\"row\"><span class=\"label\">Work-ID</span> <span>")
                .Append(Escape(agent.WorkId ?? "—")).Append("</span></p>");
            html.Append("<p class=\"row\"><span class=\"label\">Waiting for</span> <span>")
                .Append(Escape(agent.WaitingFor ?? "—")).Append("</span></p>");
            html.Append("<p class=\"muted\">Updated ").Append(Escape(agent.UpdatedAt)).Append("</p>");
            html.Append("</article>");
        }
        html.Append("</section>");
    }

    private static void AppendTasks(StringBuilder html, DashboardViewModel model)
    {
        html.Append("<section class=\"card\"><h2>Tasks</h2>");
        html.Append("<p class=\"muted\">").Append(Escape(model.TaskListNote)).Append("</p>");

        if (model.Tasks.Count == 0)
        {
            html.Append("<p class=\"muted\">—</p></section>");
            return;
        }

        html.Append("<table><thead><tr><th scope=\"col\">Task</th><th scope=\"col\">Cycle</th>")
            .Append("<th scope=\"col\">State</th><th scope=\"col\">Agent</th><th scope=\"col\">Stage</th></tr></thead><tbody>");
        foreach (var task in model.Tasks)
        {
            html.Append("<tr><th scope=\"row\">").Append(Escape(task.TaskId)).Append("<br><span class=\"muted\">")
                .Append(Escape($"{task.Wave} · {task.Flow}")).Append("</span></th><td>")
                .Append(Escape(task.CycleId)).Append("</td><td>").Append(Escape(task.State)).Append("</td><td>")
                .Append(Escape(task.CurrentAgent)).Append("</td><td>").Append(Escape(task.StageText))
                .Append(task.PercentText is { } percent ? Escape($" · {percent}") : string.Empty)
                .Append("</td></tr>");
        }
        html.Append("</tbody></table></section>");
    }

    private static void AppendActivity(StringBuilder html, IReadOnlyList<ActivityEntryView> activity)
    {
        html.Append("<section class=\"card\"><h2>Recent evidence</h2>");
        if (activity.Count == 0)
        {
            html.Append("<p class=\"muted\">No recorded events.</p></section>");
            return;
        }

        html.Append("<ul class=\"activity\">");
        foreach (var entry in activity)
        {
            html.Append("<li><p class=\"row\"><span class=\"tag small\">").Append(Escape(entry.Kind))
                .Append("</span> <span class=\"muted\">").Append(Escape(entry.OccurredAt)).Append("</span></p>");
            html.Append("<p>").Append(Escape(entry.Summary)).Append("</p>");
            html.Append("<p class=\"muted\">").Append(Escape(entry.Actor)).Append(" · ")
                .Append(Escape(entry.CycleLabel))
                .Append(entry.StateAfter is { } after ? Escape($" · → {after}") : string.Empty)
                .Append(entry.HeadShaShort is { } head ? Escape($" · {head}") : string.Empty)
                .Append(" · ").Append(Link(entry.SourceUrl, "evidence")).Append("</p></li>");
        }
        html.Append("</ul></section>");
    }

    private static void AppendEvidence(StringBuilder html, IReadOnlyList<EvidenceLinkView> evidence)
    {
        html.Append("<section class=\"card\"><h2>Sources</h2><dl class=\"grid\">");
        foreach (var item in evidence)
        {
            html.Append("<dt>").Append(Escape(item.Label)).Append("</dt><dd>");
            html.Append(item.Url is { Length: > 0 } url
                ? Link(url, item.Detail)
                : Escape(item.Detail));
            html.Append("</dd>");
        }
        html.Append("</dl></section>");
    }

    private static void Definition(StringBuilder html, string term, string value) =>
        html.Append("<dt>").Append(Escape(term)).Append("</dt><dd>").Append(Escape(value)).Append("</dd>");

    /// <summary>
    /// Renders a link only for http(s) URLs. Anything else is printed as text, so a
    /// malformed or hostile value in the read-model cannot become a javascript: link.
    /// </summary>
    private static string Link(string url, string text)
    {
        var safe = Uri.TryCreate(url, UriKind.Absolute, out var parsed)
                   && (parsed.Scheme == Uri.UriSchemeHttps || parsed.Scheme == Uri.UriSchemeHttp);
        return safe
            ? $"<a href=\"{Escape(url)}\" rel=\"noreferrer noopener\">{Escape(text)}</a>"
            : Escape(text);
    }

    private static string StatusClass(ControlStateStatus status) => status switch
    {
        ControlStateStatus.Valid => "ok",
        ControlStateStatus.Stale => "stale",
        ControlStateStatus.Conflict => "conflict",
        _ => "invalid",
    };

    private static string StateClass(string state) => state switch
    {
        "WORKING" => "working",
        "REVIEW" => "review",
        "BLOCKED" => "blocked",
        "PASS" => "pass",
        "CHANGES_REQUESTED" => "changes",
        "WAITING" or "HANDOFF" => "waiting",
        _ => "unknown",
    };

    private static string FormatAge(TimeSpan age) => age.TotalSeconds < 90
        ? $"{(int)age.TotalSeconds}s"
        : age.TotalMinutes < 90
            ? $"{(int)age.TotalMinutes}m"
            : $"{(int)age.TotalHours}h";

    public static string Escape(string? value) => WebUtility.HtmlEncode(value ?? string.Empty);

    private static string Css(int width) =>
        $$"""
        :root {
          --bg: #10131a; --panel: #171b24; --line: #262c39; --ink: #e6e9ef; --muted: #98a2b3;
          --ok: #2e9e6b; --stale: #c98a20; --conflict: #c2643a; --invalid: #c5433f; --accent: #4b83d6;
        }
        @media (prefers-color-scheme: light) {
          :root { --bg: #f4f6fa; --panel: #ffffff; --line: #d9dee8; --ink: #14181f; --muted: #5a6577; }
        }
        * { box-sizing: border-box; }
        html, body { margin: 0; padding: 0; background: var(--bg); color: var(--ink); }
        body {
          font: 12.5px/1.45 "Segoe UI", system-ui, sans-serif;
          max-width: {{width}}px; padding: 8px 10px 20px; overflow-x: hidden;
        }
        h1 { font-size: 15px; letter-spacing: .14em; margin: 0 0 8px; }
        h2 { font-size: 11px; letter-spacing: .1em; text-transform: uppercase; color: var(--muted); margin: 0 0 6px; }
        p { margin: 0 0 4px; }
        code { font-family: Consolas, ui-monospace, monospace; font-size: 11px; }
        a { color: var(--accent); }
        .muted { color: var(--muted); font-size: 11px; }
        .card, .banner {
          background: var(--panel); border: 1px solid var(--line); border-left-width: 3px;
          border-radius: 6px; padding: 8px 10px; margin-bottom: 8px;
        }
        .banner.ok { border-left-color: var(--ok); }
        .banner.stale { border-left-color: var(--stale); }
        .banner.conflict { border-left-color: var(--conflict); }
        .banner.invalid { border-left-color: var(--invalid); }
        .banner-head { font-weight: 600; }
        .tag {
          display: inline-block; padding: 1px 6px; border: 1px solid currentColor;
          border-radius: 3px; font-size: 10px; letter-spacing: .08em; font-weight: 700;
        }
        .tag.small { font-size: 9px; }
        .tag.ok { color: var(--ok); } .tag.stale { color: var(--stale); }
        .tag.conflict { color: var(--conflict); } .tag.invalid { color: var(--invalid); }
        .warn-line { color: var(--stale); font-size: 11px; }
        .findings { margin: 6px 0 0; padding-left: 16px; font-size: 11px; }
        .findings li { margin-bottom: 3px; }
        .grid { display: grid; grid-template-columns: 88px 1fr; gap: 2px 8px; margin: 0; font-size: 11.5px; }
        .grid dt { color: var(--muted); }
        .grid dd { margin: 0; overflow-wrap: anywhere; }
        .row { display: flex; gap: 8px; align-items: baseline; }
        .row .label { color: var(--muted); min-width: 78px; flex: none; font-size: 11px; }
        .krum { margin-top: 6px; padding: 5px 7px; border-radius: 4px; border: 1px solid var(--line); }
        .krum.required { border-color: var(--conflict); color: var(--conflict); }
        .meter { height: 6px; background: var(--line); border-radius: 3px; overflow: hidden; margin: 5px 0; }
        .meter span { display: block; height: 100%; background: var(--ok); }
        .pipeline { list-style: none; margin: 0; padding: 0; }
        .pipeline li {
          display: flex; gap: 7px; align-items: center; padding: 3px 6px;
          border-left: 2px solid var(--line); font-size: 11.5px;
        }
        .pipeline li.active { border-left-color: var(--accent); font-weight: 600; }
        .pipeline .ord { color: var(--muted); font-size: 10px; }
        .agent { border-top: 1px solid var(--line); padding-top: 6px; margin-top: 6px; }
        .agent.current { border-left: 2px solid var(--accent); padding-left: 6px; }
        .agent-head { display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; }
        .state-working, .state-pass { color: var(--ok); }
        .state-review, .state-waiting { color: var(--stale); }
        .state-blocked, .state-changes { color: var(--invalid); }
        .state-unknown { color: var(--muted); }
        table { width: 100%; border-collapse: collapse; font-size: 11px; }
        th, td { text-align: left; padding: 3px 4px; border-bottom: 1px solid var(--line); vertical-align: top; }
        thead th { color: var(--muted); font-weight: 500; }
        .activity { list-style: none; margin: 0; padding: 0; }
        .activity li { border-top: 1px solid var(--line); padding: 5px 0; }
        .empty { border-left-color: var(--muted); }
        """;
}
