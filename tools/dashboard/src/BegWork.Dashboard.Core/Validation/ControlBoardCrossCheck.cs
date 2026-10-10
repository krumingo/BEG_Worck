using System.Text.RegularExpressions;
using BegWork.Dashboard.Core.Model;

namespace BegWork.Dashboard.Core.Validation;

/// <summary>
/// Cross-checks <c>coordination/CONTROL_BOARD.md</c> against the control state.
///
/// The board is a rendered view of the same snapshot, never a second source of
/// truth: nothing here can promote a field, only disagree with one. A disagreement
/// means the published pair is internally inconsistent, which the dashboard reports
/// as CONFLICT and refuses to present as live.
/// </summary>
public static class ControlBoardCrossCheck
{
    private static readonly Regex CurrentLine = new(
        @"^CURRENT:\s*(?<task>\S+)\s*/\s*(?<cycle>C\d+)[^/]*/\s*(?<agent>\S+)\s*/\s*\*\*(?<state>[A-Z_]+)\*\*\s*$",
        RegexOptions.Multiline | RegexOptions.ExplicitCapture, TimeSpan.FromSeconds(1));

    private static readonly Regex BannerField = new(
        @"^(?<key>TASK|CYCLE|STATE|NEXT|WAITING_FOR):\s*(?<value>.*)$",
        RegexOptions.Multiline | RegexOptions.ExplicitCapture, TimeSpan.FromSeconds(1));

    public static VerificationResult Verify(ControlState state, string? board)
    {
        if (board is null)
        {
            return VerificationResult.From([
                new VerificationFinding(
                    ControlStateStatus.Stale, "BOARD_UNREAD",
                    "CONTROL_BOARD.md could not be read, so the rendered view is unverified.")
            ]);
        }

        var findings = new List<VerificationFinding>();

        var current = CurrentLine.Match(board);
        if (!current.Success)
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Conflict, "BOARD_UNPARSED",
                "CONTROL_BOARD.md has no recognisable CURRENT banner."));
        }
        else
        {
            Compare(findings, "CURRENT task", current.Groups["task"].Value, state.TaskId);
            Compare(findings, "CURRENT cycle", current.Groups["cycle"].Value, state.CycleId);
            Compare(findings, "CURRENT agent", current.Groups["agent"].Value, state.CurrentAgent);
            Compare(findings, "CURRENT state", current.Groups["state"].Value, state.State);
        }

        var banner = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (Match match in BannerField.Matches(board))
        {
            // The agent banner is the authoritative copy inside the board; later
            // duplicates of the same key would be a rendering bug, so keep the first.
            banner.TryAdd(match.Groups["key"].Value, match.Groups["value"].Value.Trim());
        }

        CompareBanner(findings, banner, "TASK", state.TaskId);
        CompareBanner(findings, banner, "CYCLE", state.CycleId);
        CompareBanner(findings, banner, "STATE", state.State);
        CompareBanner(findings, banner, "NEXT", state.NextAgent);
        CompareBanner(findings, banner, "WAITING_FOR", state.WaitingFor ?? "NONE");

        return VerificationResult.From(findings);
    }

    private static void CompareBanner(
        List<VerificationFinding> findings,
        IReadOnlyDictionary<string, string> banner,
        string key,
        string expected)
    {
        if (!banner.TryGetValue(key, out var actual))
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Conflict, "BOARD_FIELD_MISSING",
                $"CONTROL_BOARD.md banner has no {key} field."));
            return;
        }

        Compare(findings, $"banner {key}", actual, expected);
    }

    private static void Compare(
        List<VerificationFinding> findings, string label, string actual, string expected)
    {
        if (!string.Equals(actual, expected, StringComparison.Ordinal))
        {
            findings.Add(new VerificationFinding(
                ControlStateStatus.Conflict, "BOARD_MISMATCH",
                $"CONTROL_BOARD.md {label} is '{actual}' but CONTROL_STATE.json says '{expected}'."));
        }
    }
}
