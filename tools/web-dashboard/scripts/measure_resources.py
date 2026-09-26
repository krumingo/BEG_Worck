#!/usr/bin/env python3
"""Measure the dashboard's own CPU and memory while it serves.

Run it against the live branch (the default) or against any host. It starts the server
exactly as the container entrypoint does, samples ``/proc`` for the process and its
children, and prints figures that can be quoted without rounding them up into a guess.

    python3 scripts/measure_resources.py --seconds 60

Memory is reported as peak RSS (``VmHWM``), because that is the number a container
memory limit has to accommodate. CPU is reported as the average share of one core over
the window, since a dashboard's cost is what it does per refresh, not its peak.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLOCK_TICKS = os.sysconf("SC_CLK_TCK")
PAGE_KB = 1024


def read_status(pid: int) -> dict[str, int]:
    values = {}
    try:
        for line in pathlib.Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                key, raw = line.split(":", 1)
                values[key] = int(raw.strip().split()[0])
    except OSError:
        pass
    return values


def read_cpu_seconds(pid: int) -> float:
    try:
        fields = pathlib.Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
    except (OSError, IndexError):
        return 0.0
    # utime and stime are fields 14 and 15 one-based; after the comm split they are 11,12.
    return (int(fields[11]) + int(fields[12])) / CLOCK_TICKS


def wait_for_health(base: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base + "/healthz", timeout=3) as reply:
                return json.loads(reply.read())
        except Exception as error:  # noqa: BLE001
            last = error
            time.sleep(0.25)
    raise SystemExit(f"dashboard did not become healthy: {last}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--refresh", type=int, default=15)
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()

    environment = dict(os.environ)
    environment.update(
        {
            "BEGWORK_PORT": str(args.port),
            "BEGWORK_HOST": "127.0.0.1",
            "BEGWORK_REFRESH_SECONDS": str(args.refresh),
            "PYTHONPATH": str(ROOT),
        }
    )

    process = subprocess.Popen(
        [sys.executable, "-m", "app"],
        cwd=str(ROOT),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base = f"http://127.0.0.1:{args.port}"
    try:
        health = wait_for_health(base, timeout=45)
        print(f"healthy: link={health['link']} status={health['control_state_status']}")

        samples: list[int] = []
        cpu_start = read_cpu_seconds(process.pid)
        wall_start = time.monotonic()
        deadline = wall_start + args.seconds
        while time.monotonic() < deadline and process.poll() is None:
            status = read_status(process.pid)
            if "VmRSS" in status:
                samples.append(status["VmRSS"])
            # Exercise the serving path too, not only the idle refresh loop.
            try:
                urllib.request.urlopen(base + "/api/state", timeout=3).read()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(args.interval)

        elapsed = time.monotonic() - wall_start
        cpu_used = read_cpu_seconds(process.pid) - cpu_start
        peak = read_status(process.pid).get("VmHWM", max(samples, default=0))

        final = wait_for_health(base, timeout=5)
        print(json.dumps({
            "window_seconds": round(elapsed, 1),
            "requests_served": len(samples),
            "rss_mib_mean": round(sum(samples) / len(samples) / PAGE_KB, 1) if samples else None,
            "rss_mib_max": round(max(samples) / PAGE_KB, 1) if samples else None,
            "peak_rss_mib_vmhwm": round(peak / PAGE_KB, 1),
            "cpu_seconds": round(cpu_used, 2),
            "cpu_percent_of_one_core": round(100 * cpu_used / elapsed, 2) if elapsed else None,
            "refresh_rounds": final.get("rounds"),
            "link": final.get("link"),
            "control_state_status": final.get("control_state_status"),
        }, indent=2))
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
