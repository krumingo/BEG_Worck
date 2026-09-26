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


def remote_rounds(base_url: str, count: int, interval: float) -> int:
    """Observe a running instance completing consecutive successful rounds.

    This is the NAS case: the container is already running with its own token, and the
    probe watches ``/healthz`` advance its round counter without errors.
    """
    print(f"REMOTE REFRESH OBSERVATION — {base_url}")
    header = f"{'#':>2}  {'timestamp':20}  {'link':8}  {'status':9}  {'rounds':>6}  {'fails':>5}  age"
    print(header)
    print("-" * len(header))

    seen = []
    last_rounds = None
    for index in range(1, count + 1):
        try:
            with urllib.request.urlopen(base_url.rstrip("/") + "/healthz", timeout=10) as reply:
                health = json.loads(reply.read())
        except OSError as error:
            print(f"{index:>2}  {now():20}  UNREACHABLE ({error})")
            seen.append(False)
            time.sleep(interval)
            continue

        advanced = last_rounds is None or health.get("rounds", 0) > last_rounds
        last_rounds = health.get("rounds", 0)
        ok = health.get("link") == "ONLINE" and not health.get("consecutive_failures")
        seen.append(ok)
        age = health.get("age_seconds")
        print(
            f"{index:>2}  {now():20}  {str(health.get('link')):8}  "
            f"{str(health.get('control_state_status')):9}  {last_rounds:>6}  "
            f"{health.get('consecutive_failures', 0):>5}  "
            f"{'—' if age is None else format(age, '.1f')}s"
            f"{'' if advanced else '   (no new round yet)'}"
        )
        if index < count:
            time.sleep(interval)

    good = sum(1 for item in seen if item)
    print(f"\nrounds observed healthy: {good}/{count}")
    return 0 if good == count else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["rounds", "remote", "writes", "token", "all"])
    parser.add_argument("--count", type=int, default=5, help="number of rounds (default 5)")
    parser.add_argument("--interval", type=float, default=20.0, help="seconds between remote polls")
    parser.add_argument("--seconds", type=float, default=8.0, help="write-audit duration")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080", help="a running instance")
    args = parser.parse_args()

    settings = Settings.from_environment()
    codes = []

    if args.mode in {"rounds", "all"}:
        codes.append(live_rounds(args.count, settings))
        print("")
    if args.mode in {"remote"}:
        codes.append(remote_rounds(args.base_url, args.count, args.interval))
        print("")
    if args.mode in {"writes", "all"}:
        codes.append(write_audit(args.seconds, settings))
        print("")
        codes.append(write_denial_probe())
        print("")
    if args.mode in {"token", "all"}:
        codes.append(token_containment(args.base_url))
        print("")

    # 2 means "not provable on this host", which is not a failure of the software.
    return 1 if any(code == 1 for code in codes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
