namespace BegWork.Dashboard.Core.Validation;

/// <summary>
/// The four statuses the control protocol defines. Ordered by severity so the
/// dashboard can always fall back to the worst observation it has.
/// </summary>
public enum ControlStateStatus
{
    Valid = 0,
    Stale = 1,
    Conflict = 2,
    Invalid = 3,
}

/// <summary>One reason the dashboard cannot present the snapshot as live truth.</summary>
/// <param name="Status">Severity contributed by this finding.</param>
/// <param name="Code">Stable machine code, safe to assert on in tests.</param>
/// <param name="Message">Operator-readable explanation shown in the UI.</param>
public sealed record VerificationFinding(ControlStateStatus Status, string Code, string Message);

/// <summary>
/// Aggregate verdict. <see cref="Status"/> is the worst of every contributing
/// finding, so a single STALE observation can never be rounded up to VALID.
/// </summary>
public sealed record VerificationResult(ControlStateStatus Status, IReadOnlyList<VerificationFinding> Findings)
{
    public bool IsLiveVerified => Status == ControlStateStatus.Valid;

    public static VerificationResult From(IEnumerable<VerificationFinding> findings)
    {
        var list = findings.ToList();
        var status = list.Count == 0
            ? ControlStateStatus.Valid
            : list.Max(f => f.Status);
        return new VerificationResult(status, list);
    }

    public VerificationResult Merge(VerificationResult other) =>
        From(Findings.Concat(other.Findings));

    public static readonly VerificationResult Clean = new(ControlStateStatus.Valid, []);
}

public static class ControlStateStatusText
{
    public static string ToProtocolName(this ControlStateStatus status) => status switch
    {
        ControlStateStatus.Valid => "VALID",
        ControlStateStatus.Stale => "STALE",
        ControlStateStatus.Conflict => "CONFLICT",
        ControlStateStatus.Invalid => "INVALID",
        _ => "INVALID",
    };

    /// <summary>
    /// Parses a persisted <c>control_state_status</c>. Anything unrecognised is
    /// treated as INVALID rather than optimistically ignored.
    /// </summary>
    public static ControlStateStatus Parse(string? value) => value switch
    {
        "VALID" => ControlStateStatus.Valid,
        "STALE" => ControlStateStatus.Stale,
        "CONFLICT" => ControlStateStatus.Conflict,
        _ => ControlStateStatus.Invalid,
    };
}
