#!/usr/bin/env python3
"""Acceptance evidence for the BEG_WORK dashboard.

One script, runnable in two places:

* **On this host**, to produce the evidence a development container can honestly
  produce — live refresh rounds, an application-level write audit, token containment.
* **On the Synology test container**, to produce the rest — the same checks plus an
  OS-level write-denial probe that only means something inside the read-only container.

It never prints the token. It reads ``BEGWORK_GITHUB_TOKEN`` to *search for* the value
in responses, and reports only whether it was found. Nothing it writes to stdout can
disclose a credential.

Exit codes
----------
``0`` everything asked for was proven. ``1`` something failed. ``2`` a check could not
be proven on this host or from this surface (a development host cannot demonstrate
container write denial; a probe cannot establish a token's scope) -- reported as
unproven rather than quietly passing.

Usage
-----
    # Live rounds against the configured branch, in-process:
    python3 scripts/acceptance_probe.py rounds --count 5

    # Everything, against an already-running instance (this is the NAS case):
    python3 scripts/acceptance_probe.py all --base-url http://nas.local:8787

    # Application write audit and OS write-denial probe:
    python3 scripts/acceptance_probe.py writes
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import pathlib
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.github import GitHubReadOnlyClient, TransportError  # noqa: E402
from app.refresh import Refresher  # noqa: E402
from app.settings import Settings  # noqa: E402

#: Paths a correctly behaving deployment may write to. Everything else is a finding.
ALLOWED_WRITE_PREFIXES = ("/tmp", "/var/tmp", tempfile.gettempdir())


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _token() -> str:
    return (os.environ.get("BEGWORK_GITHUB_TOKEN") or "").strip()


# --------------------------------------------------------------- live rounds


def live_rounds(count: int, settings: Settings) -> int:
    """Perform ``count`` consecutive refresh rounds and report each one."""
    client = GitHubReadOnlyClient(
        repository=settings.repository,
        token=settings.token,
        api_base=settings.api_base,
        timeout=settings.request_timeout_seconds,
    )
    refresher = Refresher(client, settings)

    print(f"LIVE REFRESH ROUNDS — target {settings.repository} @ {settings.branch}")
    print(f"authenticated: {'yes' if settings.has_token else 'no (anonymous)'}")
    print("")
    header = f"{'#':>2}  {'timestamp':20}  {'status':9}  {'link':8}  {'reqs':>4}  {'304s':>4}  findings"
    print(header)
    print("-" * len(header))

    successes = 0
    for index in range(1, count + 1):
        started = time.monotonic()
        state = refresher.tick()
        elapsed = time.monotonic() - started
        verified = state.verified
        status = verified.status.label if verified else "—"
        findings = [f.code for f in verified.verdict.worst_first()] if verified else []
        requests = verified.snapshot.request_count if verified else 0
        hits = verified.snapshot.conditional_hits if verified else 0
        ok = state.link.value == "ONLINE" and state.last_error is None
        successes += 1 if ok else 0
        print(
            f"{index:>2}  {now():20}  {status:9}  {state.link.value:8}  {requests:>4}  {hits:>4}  "
            f"{','.join(findings) or 'none'}   ({elapsed:.2f}s)"
        )
        if not ok:
            print(f"    failure: {state.last_error}")
        if index < count:
            time.sleep(2)

    print("")
    print(f"consecutive successful rounds: {successes}/{count}")
    print(f"total rounds recorded by the refresher: {refresher.current().rounds}")
    return 0 if successes == count else 1


# ------------------------------------------------------------- write audit


def write_audit(seconds: float, settings: Settings) -> int:
    """Record every filesystem write the application attempts, via an audit hook.

    This is application-level evidence and is valid on any host: it shows what the
    process *tries* to do. Whether the filesystem would refuse is a separate, container
    property — see ``write_denial_probe``.
    """
    attempts: list[tuple[str, str]] = []

    def hook(event: str, args):
        if event == "open":
            path, _, flags = (list(args) + [None, None, None])[:3]
            # Mode is an int flags bitmask for os.open, or a string for builtins.open.
            writing = False
            if isinstance(flags, int):
                writing = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND))
            elif isinstance(flags, str):
                writing = any(ch in flags for ch in "wax+")
            if writing and path:
                attempts.append((event, str(path)))
        elif event in {"os.remove", "os.rename", "os.mkdir", "os.rmdir", "shutil.copyfile"}:
            attempts.append((event, str(args[0]) if args else "?"))

    sys.addaudithook(hook)

    client = GitHubReadOnlyClient(
        repository=settings.repository, token=settings.token,
        api_base=settings.api_base, timeout=settings.request_timeout_seconds,
    )
    refresher = Refresher(client, settings)
    deadline = time.monotonic() + seconds
    rounds = 0
    while time.monotonic() < deadline:
        refresher.tick()
        rounds += 1
        time.sleep(1)

    outside = [
        (event, path) for event, path in attempts
        if not any(str(path).startswith(prefix) for prefix in ALLOWED_WRITE_PREFIXES)
    ]

    print("APPLICATION WRITE AUDIT")
    print(f"rounds executed         : {rounds}")
    print(f"write attempts observed : {len(attempts)}")
    print(f"allowed prefixes        : {', '.join(sorted(set(ALLOWED_WRITE_PREFIXES)))}")
    print(f"writes outside allowed  : {len(outside)}")
    for event, path in outside[:20]:
        print(f"  ! {event} {path}")
    print("RESULT:", "PASS — the application wrote nothing outside the allowed paths"
          if not outside else "FAIL — see the list above")
    return 0 if not outside else 1


def write_denial_probe() -> int:
    """Try to write where a hardened container must refuse, and report what happened.

    Only meaningful inside the deployed container (``read_only: true``). On an ordinary
    development host the writes will succeed, and this says so rather than pretending
    the protection was verified.
    """
    targets = [
        pathlib.Path("/app/acceptance-write-probe.tmp"),
        pathlib.Path.cwd() / "acceptance-write-probe.tmp",
        pathlib.Path("/etc/acceptance-write-probe.tmp"),
    ]
    allowed = pathlib.Path(tempfile.gettempdir()) / "acceptance-write-probe.tmp"

    print("RUNTIME WRITE-DENIAL PROBE")
    denied = 0
    for target in targets:
        try:
            target.write_text("probe\n", encoding="utf-8")
            print(f"  WRITABLE  {target}  <-- not denied on this host")
            try:
                target.unlink()
            except OSError:
                pass
        except OSError as error:
            denied += 1
            print(f"  DENIED    {target}  ({error.__class__.__name__}: {error.strerror or error})")

    try:
        allowed.write_text("probe\n", encoding="utf-8")
        allowed.unlink()
        print(f"  WRITABLE  {allowed}  <-- expected: the allowed tmp path")
        tmp_ok = True
    except OSError as error:
        print(f"  DENIED    {allowed}  <-- unexpected: the app needs a writable tmp ({error})")
        tmp_ok = False

    print(f"denied {denied}/{len(targets)} out-of-scope paths; tmp writable: {tmp_ok}")
    if denied == len(targets) and tmp_ok:
        print("RESULT: PASS — writes outside the allowed tmp path are refused by the runtime")
        return 0
    print(
        "RESULT: NOT PROVEN ON THIS HOST — this probe only demonstrates protection inside "
        "the hardened container (read_only: true). Re-run it in the deployed container."
    )
    return 2


# -------------------------------------------------------- token containment


def token_containment(base_url: str) -> int:
    """Confirm the configured token appears in nothing the dashboard serves."""
    token = _token()
    paths = ["/", "/api/state", "/healthz", "/app.js", "/app.css", "/manifest.webmanifest", "/sw.js"]

    print("TOKEN CONTAINMENT")
    if not token:
        print("  BEGWORK_GITHUB_TOKEN is not set in this environment.")
        print("  RESULT: NOT APPLICABLE — configure a read-only token and re-run to prove containment.")
        return 2

    print(f"  token configured: yes (length {len(token)}; value never printed)")
    leaked = []
    for path in paths:
        try:
            request = urllib.request.Request(base_url.rstrip("/") + path)
            with urllib.request.urlopen(request, timeout=10) as reply:
                body = reply.read().decode("utf-8", "replace")
                headers = "\n".join(f"{k}: {v}" for k, v in reply.headers.items())
        except urllib.error.HTTPError as error:
            body, headers = error.read().decode("utf-8", "replace"), ""
        except OSError as error:
            print(f"  {path:24} UNREACHABLE ({error})")
            continue
        found = token in body or token in headers
        leaked.append(path) if found else None
        print(f"  {path:24} {'LEAK' if found else 'clean'}  ({len(body)} bytes)")

    print("RESULT:", "PASS — the token appears in no served response" if not leaked
          else f"FAIL — token present in {leaked}")
    return 0 if not leaked else 1


# ------------------------------------------------------------- remote checks


@dataclasses.dataclass(frozen=True, slots=True)
class TargetProfile:
    """What could be established about the target before observing it."""

    reachable: bool
    token_configured: bool | None
    refresh_seconds: int | None
    repository: str | None
    branch: str | None
    acceptance_mode: bool | None
    detail: str = ""


def profile_target(base_url: str) -> TargetProfile:
    """Read the target's own description of itself from ``/api/state``.

    Used to answer one question before any refresh claim is made: is this target even
    configured to authenticate? ``config.token_configured`` is a boolean the dashboard
    publishes; the token itself is never exposed, by design.
    """
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/api/state", timeout=10) as reply:
            payload = json.loads(reply.read())
    except (OSError, ValueError) as error:
        return TargetProfile(False, None, None, None, None, None, f"{error.__class__.__name__}: {error}")

    config = payload.get("config") or {}
    return TargetProfile(
        reachable=True,
        token_configured=config.get("token_configured"),
        refresh_seconds=payload.get("refresh_seconds"),
        repository=config.get("repository"),
        branch=config.get("branch"),
        acceptance_mode=config.get("acceptance_mode"),
    )


@dataclasses.dataclass(frozen=True, slots=True)
class ObservationResult:
    counted: int
    required: int
    samples: int
    failure: str | None

    @property
    def ok(self) -> bool:
        return self.failure is None and self.counted >= self.required


def observe_rounds(
    base_url: str,
    count: int,
    poll_interval: float,
    max_wait: float,
    printer=print,
    sleep=time.sleep,
    monotonic=time.monotonic,
) -> ObservationResult:
    """Count refresh cycles, requiring ``/healthz.rounds`` to advance for each one.

    A *cycle* is one completed refresh by the target. Polling ``/healthz`` five times
    does not make five cycles: without checking that the counter moved, five samples of
    a single round -- or of a target whose refresh loop has stopped entirely -- read as
    five successes. That was the defect this function is a correction for.

    So each counted cycle requires ``rounds`` to be **strictly greater** than the value
    at the previously counted cycle, and each cycle has a bounded wait: if no new round
    arrives within ``max_wait`` seconds the observation fails rather than reporting what
    it merely kept sampling. A round that advances but is unhealthy fails immediately --
    the claim being tested is *consecutive successful* cycles.
    """
    header = f"{'sample':>6}  {'timestamp':20}  {'link':8}  {'status':9}  {'rounds':>6}  {'fails':>5}  {'age':>7}  note"
    printer(header)
    printer("-" * len(header))

    baseline: int | None = None
    last_counted: int | None = None
    counted = 0
    samples = 0
    cycle_deadline = monotonic() + max_wait

    while counted < count:
        if monotonic() > cycle_deadline:
            waited = max_wait
            failure = (
                f"no new refresh round within the bounded {waited:.0f}s window after "
                f"{counted} counted cycle(s); the target's refresh loop is not advancing"
            )
            printer(f"{'--':>6}  {now():20}  TIMEOUT   {failure}")
            return ObservationResult(counted, count, samples, failure)

        samples += 1
        try:
            with urllib.request.urlopen(base_url.rstrip("/") + "/healthz", timeout=10) as reply:
                health = json.loads(reply.read())
        except (OSError, ValueError) as error:
            failure = f"target unreachable at sample {samples}: {error}"
            printer(f"{samples:>6}  {now():20}  UNREACHABLE  {error}")
            return ObservationResult(counted, count, samples, failure)

        rounds = health.get("rounds")
        link = health.get("link")
        failures = health.get("consecutive_failures") or 0
        age = health.get("age_seconds")
        healthy = link == "ONLINE" and not failures

        if not isinstance(rounds, int):
            failure = f"/healthz did not report an integer round counter (got {rounds!r})"
            printer(f"{samples:>6}  {now():20}  {str(link):8}  {'':9}  {'?':>6}  {failures:>5}  {'':>7}  {failure}")
            return ObservationResult(counted, count, samples, failure)

        if baseline is None:
            baseline = rounds
            last_counted = rounds
            note = f"baseline (rounds={rounds}); waiting for it to advance"
            advanced = False
        else:
            advanced = rounds > last_counted
            note = "" if advanced else "no new round yet — not counted"

        printer(
            f"{samples:>6}  {now():20}  {str(link):8}  {str(health.get('control_state_status')):9}  "
            f"{rounds:>6}  {failures:>5}  "
            f"{('—' if age is None else format(age, '.1f') + 's'):>7}  {note}"
        )

        if advanced:
            if not healthy:
                failure = (
                    f"round {rounds} completed but the target is not healthy "
                    f"(link={link}, consecutive_failures={failures}); "
                    "the run was not five consecutive *successful* cycles"
                )
                printer(f"{'--':>6}  {now():20}  FAILED    {failure}")
                return ObservationResult(counted, count, samples, failure)
            counted += 1
            last_counted = rounds
            cycle_deadline = monotonic() + max_wait
            printer(f"{'--':>6}  {now():20}  COUNTED   cycle {counted}/{count} at rounds={rounds}")

        if counted < count:
            sleep(poll_interval)

    return ObservationResult(counted, count, samples, None)


def remote_rounds(
    base_url: str,
    count: int,
    interval: float,
    max_wait: float | None = None,
    require_auth: bool = False,
    auth_evidence: str = "",
    printer=print,
    sleep=time.sleep,
    monotonic=time.monotonic,
) -> int:
    """Observe a running instance completing consecutive successful refresh cycles.

    This is the NAS case. Two claims are kept apart on purpose:

    * **Did it refresh?** Proven here, by requiring the round counter to advance.
    * **Was it authenticated, with read-only scope?** Only partly provable from
      outside. That the target has a token configured is published at ``/api/state``.
      That the token's *scope* is read-only cannot be established from the dashboard's
      surface at all -- it never exposes the token, deliberately -- so it is reported as
      operator-attested or as unproven, never as something this probe verified.
    """
    printer(f"REMOTE REFRESH OBSERVATION — {base_url}")
    printer("")

    profile = profile_target(base_url)
    printer("TARGET")
    if not profile.reachable:
        printer(f"  /api/state unreachable: {profile.detail}")
    else:
        printer(f"  repository        : {profile.repository}")
        printer(f"  branch            : {profile.branch}")
        printer(f"  refresh cadence   : {profile.refresh_seconds}s")
        printer(f"  token configured  : {profile.token_configured}")
        printer(f"  acceptance mode   : {profile.acceptance_mode}")
    printer("")

    if max_wait is None:
        # Three cadences plus slack: long enough to survive one missed round and a
        # backoff step, short enough that a stopped loop is reported rather than waited
        # out. Bounded in both directions.
        cadence = profile.refresh_seconds if isinstance(profile.refresh_seconds, int) else 30
        max_wait = min(600.0, max(90.0, cadence * 3.0))
    printer(f"OBSERVATION — {count} cycles, polling every {interval:.0f}s, "
            f"max {max_wait:.0f}s per cycle for the round counter to advance")

    result = observe_rounds(
        base_url, count, interval, max_wait, printer=printer, sleep=sleep, monotonic=monotonic
    )

    printer("")
    printer(f"cycles counted (strictly increasing rounds): {result.counted}/{result.required} "
            f"from {result.samples} sample(s)")
    if result.failure:
        printer(f"REFRESH RESULT: FAIL — {result.failure}")
        return 1
    printer("REFRESH RESULT: PASS — each counted cycle had a strictly higher round counter")

    # --- the authentication claim, kept separate from the refresh claim ---------------
    printer("")
    printer("AUTHENTICATION")
    if profile.token_configured is not True:
        printer("  token configured on target : NO (or not reported)")
        printer("  read-only scope            : NOT APPLICABLE")
        printer("  AUTHENTICATED REFRESH PASS : NOT CLAIMED — the target is reading anonymously.")
        if require_auth:
            printer("  --require-auth was set, so this is a failure.")
            return 1
        printer("  The refresh cycles above are ANONYMOUS. Configure a read-only token and re-run")
        printer("  with --require-auth to produce authenticated evidence.")
        return 2

    printer("  token configured on target : YES (value never exposed by the dashboard)")
    if not auth_evidence.strip():
        printer("  read-only scope            : UNPROVEN")
        printer("  AUTHENTICATED REFRESH PASS : NOT CLAIMED.")
        printer("  A configured token proves authentication, not that its scope is read-only, and")
        printer("  the dashboard never exposes the token, so this probe cannot establish scope.")
        printer("  Confirm in GitHub token settings that it is repository-scoped to this repo with")
        printer("  Contents: Read-only and Pull requests: Read-only, then re-run with")
        printer("  --auth-evidence '<how and when scope was confirmed>'.")
        return 2

    printer(f"  read-only scope            : OPERATOR-ATTESTED — {auth_evidence.strip()}")
    printer("  AUTHENTICATED REFRESH PASS : YES, with scope attested by the operator above")
    printer("  (attestation, not probe-verified: the token is never exposed to this probe).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["rounds", "remote", "writes", "token", "all"])
    parser.add_argument("--count", type=int, default=5, help="number of rounds (default 5)")
    parser.add_argument("--interval", type=float, default=20.0, help="seconds between remote polls")
    parser.add_argument("--seconds", type=float, default=8.0, help="write-audit duration")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080", help="a running instance")
    parser.add_argument("--max-wait", type=float, default=None,
                        help="bounded seconds to wait for each new round (default: 3x the target cadence, min 90)")
    parser.add_argument("--require-auth", action="store_true",
                        help="fail unless the target is configured with a token")
    parser.add_argument("--auth-evidence", default="",
                        help="operator attestation of how read-only token scope was confirmed")
    args = parser.parse_args()

    settings = Settings.from_environment()
    codes = []

    if args.mode in {"rounds", "all"}:
        codes.append(live_rounds(args.count, settings))
        print("")
    if args.mode in {"remote"}:
        codes.append(remote_rounds(args.base_url, args.count, args.interval,
                                   max_wait=args.max_wait,
                                   require_auth=args.require_auth,
                                   auth_evidence=args.auth_evidence))
        print("")
    if args.mode in {"writes", "all"}:
        codes.append(write_audit(args.seconds, settings))
        print("")
        codes.append(write_denial_probe())
        print("")
    if args.mode in {"token", "all"}:
        codes.append(token_containment(args.base_url))
        print("")

    # 1 is a failure. 2 is "not proven from here", which must stay distinguishable from
    # success: an acceptance gate checking `rc == 0` should not read an unproven claim
    # as a passed one.
    if any(code == 1 for code in codes):
        return 1
    return 2 if any(code == 2 for code in codes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
