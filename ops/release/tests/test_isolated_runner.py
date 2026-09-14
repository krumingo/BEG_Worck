"""Self-test of the isolated Synology validation runner (tests/synology/run_isolated.sh).

Builds the package from the working tree and runs the runner in `sim` mode: same scenarios as
on the NAS, but `docker run` executes the verifier with the local Python and phase 2 (real Docker
+ compose) is reported NOT RUN. On the NAS the same runner uses the real python:3.11-slim image.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from harness import BASH, PYTHON, RELEASE_DIR, read_text

MAKE_PACKAGE = os.path.join(RELEASE_DIR, "tests", "synology", "make_package.py")


@unittest.skipUnless(BASH, "bash is required for the isolated runner")
class IsolatedRunnerSelfTest(unittest.TestCase):
    def test_runner_passes_every_phase_1_scenario_in_sim_mode(self):
        out = tempfile.mkdtemp(prefix="w9")  # short: Windows MAX_PATH
        try:
            p = subprocess.run([sys.executable, MAKE_PACKAGE, "--out", out, "--allow-dirty"], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            pkg = [os.path.join(out, d) for d in os.listdir(out) if d.startswith("w009a-isolated-")][0]
            env = dict(os.environ, ISOLATED_MODE="sim", RELEASE_PYTHON=PYTHON)
            r = subprocess.run([BASH, os.path.join(pkg, "runner", "run_isolated.sh").replace("\\", "/")],
                               capture_output=True, text=True, env=env, timeout=1800)
            runs = os.path.join(pkg, "runs")
            run = os.path.join(runs, sorted(os.listdir(runs))[-1])
            results = read_text(os.path.join(run, "results.tsv"))
            failures = [line for line in results.splitlines() if line.startswith("FAIL")]
            self.assertEqual(failures, [], r.stdout[-4000:])
            self.assertEqual(r.returncode, 0, r.stdout[-4000:])
            self.assertEqual(read_text(os.path.join(run, "final.exit")).strip(), "0")
            scenarios = {line.split("\t")[1] for line in results.splitlines()}
            for required in ("adopt", "deploy", "precheck-tampered", "precheck-runtime-drift", "precheck-migration",
                             "auto-compose-failure", "auto-backend-not-starting", "auto-health", "auto-restart-loop",
                             "auto-5xx", "auto-startup-log", "auto-not-recreated", "auto-flag-mismatch",
                             "auto-image-missing", "rollback", "rollback-tampered", "rollback-image-missing",
                             "retention", "secrets", "env"):
                self.assertIn(required, scenarios)
            self.assertGreaterEqual(len(results.splitlines()), 120)
            self.assertIn("phase 2 NOT RUN in sim mode", results)
        finally:
            shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
