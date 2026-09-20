"""W0-10A isolated restore proof — guard tests.

The proof script is exercised against the committed fake docker (tests/fakes/docker), a
sandbox production layout and a fake M.2 sensor tree, so every guard can be driven without
a NAS: the read-only archive mount, the `--internal` network, the temperature gate, and the
fail-closed paths for a bad archive, a failed restore, a count mismatch, an incomplete
cleanup and a production change.

Exit codes under test: 0 PASS · 2 preflight refusal · 3 restore/verification failure ·
4 cleanup failure · 5 production changed.
"""
import gzip
import hashlib
import os
import time
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DR_DIR = os.path.dirname(HERE)
SCRIPT = os.path.join(DR_DIR, "w0_10a_restore_proof.sh")
VERIFY_JS = os.path.join(DR_DIR, "verify_restore.js")
FAKE_DOCKER = os.path.join(HERE, "fakes", "docker")
BASH = shutil.which("bash")

ARCHIVE_NAME = "begwork_atlas_2026-09-20_0310.archive.gz"
RESTORED = 1234

RESTORE_OUT = (
    "2026-09-20T12:00:01.000+0000\tpreparing collections to restore from\n"
    "2026-09-20T12:00:05.000+0000\tfinished restoring begwork_beg.projects (17 documents, 0 failures)\n"
    "2026-09-20T12:00:06.000+0000\t%d document(s) restored successfully. 0 document(s) failed to restore.\n"
    % RESTORED
)


def posix(path):
    return os.path.abspath(path).replace("\\", "/")


def verify_json(documents=RESTORED, ok="true", no_index=0, bad_samples=0, tenant="PASS"):
    return (
        '{\n'
        '  "ok": %s,\n'
        '  "total_databases": 10,\n'
        '  "total_collections": 93,\n'
        '  "total_documents": %d,\n'
        '  "collections_without_id_index": %d,\n'
        '  "sample_reads_failed": %d,\n'
        '  "tenant_check": "%s",\n'
        '  "problems": []\n'
        '}\n' % (ok, documents, no_index, bad_samples, tenant)
    )


@unittest.skipUnless(BASH, "bash is required for the W0-10A proof tests")
class RestoreProofTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="w010a-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.prod = os.path.join(self.tmp, "prod")
        self.backups = os.path.join(self.prod, "backups")
        self.fake = os.path.join(self.tmp, "fake")
        self.out_root = os.path.join(self.tmp, "out")
        self.m2 = os.path.join(self.tmp, "m2")
        for d in (self.backups, os.path.join(self.prod, "repo"), self.fake, self.out_root):
            os.makedirs(d)

        self.write(os.path.join(self.prod, ".env"), "MONGO_URL=mongodb+srv://sentinel\n")
        self.write(os.path.join(self.prod, "DEPLOYED_COMMIT"), "0b53bcd5b977ee27de8d4cee363fed41dd897482\n")
        self.write(os.path.join(self.prod, "repo", "server.py"), "print('prod')\n")
        self.archive = os.path.join(self.backups, ARCHIVE_NAME)
        with gzip.open(self.archive, "wb") as f:
            f.write(b"fake mongodump archive payload")

        self.set_m2(54, 57)
        # fake docker: happy-path defaults
        self.knob("image_ok", "")
        self.knob("image_id", "sha256:1234abcd\n")
        self.knob("mongo_ready", "")
        self.knob("restore_out", RESTORE_OUT)
        self.knob("restore_rc", "0")
        self.knob("verify_json", verify_json())
        self.knob("verify_rc", "0")
        for c in ("begwork-backend", "begwork-frontend", "kpo-photo-cleaner", "beg-raboti"):
            self.knob("prod_" + c, "cid-%s running restarts=7 started=2026-09-16T05:47:27Z\n" % c)

    # ---------------------------------------------------------------- helpers
    def write(self, path, text):
        with open(path, "w", newline="\n") as f:
            f.write(text)

    def knob(self, name, text):
        self.write(os.path.join(self.fake, name), text)

    def set_m2(self, *temps):
        for i, t in enumerate(temps):
            d = os.path.join(self.m2, "nvme%dn1" % i)
            os.makedirs(d, exist_ok=True)
            self.write(os.path.join(d, "temperature"), "%d\n" % t)

    def sha256(self, path):
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def _env(self, **env_extra):
        env = dict(os.environ)
        env.update(
            PROD=posix(self.prod),
            BACKUP_DIR=posix(self.backups),
            OUT_ROOT=posix(self.out_root),
            DOCKER=posix(FAKE_DOCKER),
            FAKE=posix(self.fake),
            M2_GLOB=posix(self.m2) + "/nvme*/temperature",
            VERIFY_JS=posix(VERIFY_JS),
            MONGO_IMAGE="mongo:7",
            TEMP_ABORT="62",
            READY_TIMEOUT="9",
        )
        env.update({k: str(v) for k, v in env_extra.items()})
        if env.pop("_FAKE_CLOCK", None):
            env["PATH"] = posix(os.path.join(HERE, "fakes")) + os.pathsep + env.get("PATH", "")
        return env

    def run_proof(self, *args, **env_extra):
        env = self._env(**env_extra)
        return subprocess.run([BASH, posix(SCRIPT), *args], env=env, capture_output=True, text=True)

    def popen_proof(self, *args, **env_extra):
        env = self._env(**env_extra)
        return subprocess.Popen([BASH, posix(SCRIPT), *args], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def out_dirs(self):
        return sorted(d for d in os.listdir(self.out_root) if d.startswith("out-"))

    def evidence_of(self, out_dir, name):
        path = os.path.join(self.out_root, out_dir, name)
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()

    def run_id_of(self, out_dir):
        for line in self.evidence_of(out_dir, "result.env").splitlines():
            if line.startswith("RUN_ID="):
                return line.split("=", 1)[1]
        return ""

    def calls_of(self, fake_dir):
        path = os.path.join(fake_dir, "calls.log")
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()

    def second_fake(self):
        """An independent fake-docker state, so the two runs' call logs stay separable."""
        d = os.path.join(self.tmp, "fake2")
        os.makedirs(d, exist_ok=True)
        for n in os.listdir(self.fake):
            if n == "calls.log":
                continue
            src, dst = os.path.join(self.fake, n), os.path.join(d, n)
            if os.path.isfile(src):
                shutil.copyfile(src, dst)
        return d

    def foreign_objects(self):
        """A parallel/older run's objects. Cleanup must never touch these."""
        names = ("c_w010a-mongo-OLDRUN", "vol_w010a-vol-OLDRUN", "net_w010a-net-OLDRUN")
        for n in names:
            self.knob(n, "")
        return names

    def lock_dir(self):
        return os.path.join(self.out_root, ".lock")

    def evidence_dir(self):
        dirs = self.out_dirs()          # the lock directory is not evidence
        self.assertTrue(dirs, "no evidence directory was created")
        return os.path.join(self.out_root, dirs[-1])

    def evidence(self, name):
        path = os.path.join(self.evidence_dir(), name)
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()

    def calls(self):
        return self.evidence_calls()

    def evidence_calls(self):
        path = os.path.join(self.fake, "calls.log")
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()

    def assert_no_leftovers(self):
        self.assert_no_leftovers_for_this_run()

    def assert_no_leftovers_for_this_run(self):
        """Objects of THIS run must be gone; foreign w010a-* ones are not our business."""
        left = [n for n in os.listdir(self.fake)
                if n.startswith(("c_w010a", "net_w010a", "vol_w010a")) and "OLDRUN" not in n]
        self.assertEqual([], left, "this run's objects survived cleanup: %s" % left)

    # ---------------------------------------------------------------- happy path
    def test_passes_and_reports_the_assignment_fields(self):
        before = self.sha256(self.archive)
        p = self.run_proof()
        self.assertEqual(0, p.returncode, p.stdout + p.stderr)
        summary = self.evidence("SUMMARY.txt")
        self.assertIn("W0-10A: PASS", summary)
        self.assertIn(ARCHIVE_NAME, summary)
        self.assertIn("RESTORE: PASS", summary)
        self.assertIn("VERIFICATION: PASS", summary)
        self.assertIn("TENANT_CHECK: PASS", summary)
        self.assertIn("CLEANUP: PASS", summary)
        self.assertIn("PRODUCTION_CHANGED: NO", summary)
        self.assertEqual(before, self.sha256(self.archive), "the source archive was modified")
        self.assert_no_leftovers()

    def test_evidence_is_complete(self):
        self.run_proof()
        for name in ("SUMMARY.txt", "result.env", "run.log", "restore.out",
                     "verify.json", "m2-temps.tsv", "prod-before.txt", "prod-after.txt"):
            self.assertTrue(self.evidence(name), "missing evidence file: %s" % name)
        result = self.evidence("result.env")
        self.assertIn("BACKUP_SHA256=" + self.sha256(self.archive), result)
        self.assertIn("MONGO_IMAGE_ID=sha256:1234abcd", result)
        self.assertIn("RESTORED_DOCS=%d" % RESTORED, result)

    # ---------------------------------------------------------------- isolation guarantees
    def test_archive_is_mounted_read_only(self):
        self.run_proof()
        mounts = [l for l in self.calls().splitlines() if "mongorestore" in l]
        self.assertTrue(mounts)
        self.assertIn("/backup:ro", mounts[0])

    def test_network_is_internal_and_mongo_publishes_no_port(self):
        self.run_proof()
        calls = self.calls()
        self.assertIn("network create --internal w010a-net-", calls)
        started = [l for l in calls.splitlines() if " run -d " in l and "w010a-mongo-" in l]
        self.assertTrue(started)
        self.assertNotIn(" -p ", started[0])
        self.assertNotIn("--publish", started[0])
        self.assertNotIn("--network host", started[0])

    def test_no_production_credentials_reach_the_container(self):
        self.run_proof()
        started = [l for l in self.calls().splitlines() if " run -d " in l][0]
        self.assertIn("--env MONGO_URL=", started)
        self.assertNotIn("mongodb+srv", self.calls())
        self.assertNotIn("mongodb+srv", self.evidence("run.log"))

    def test_production_env_is_hashed_never_copied(self):
        self.run_proof()
        snapshot = self.evidence("prod-before.txt")
        self.assertIn("env_sha256 " + self.sha256(os.path.join(self.prod, ".env")), snapshot)
        self.assertNotIn("sentinel", snapshot)

    # ---------------------------------------------------------------- preflight refusals (2)
    def test_refuses_a_corrupt_archive(self):
        with open(self.archive, "wb") as f:
            f.write(b"this is not gzip")
        p = self.run_proof()
        self.assertEqual(2, p.returncode)
        self.assertIn("gzip integrity check failed", self.evidence("run.log"))
        self.assertNotIn("network create", self.calls())

    def test_refuses_when_no_archive_exists(self):
        os.remove(self.archive)
        p = self.run_proof()
        self.assertEqual(2, p.returncode)
        self.assertIn("no backup archive found", self.evidence("run.log"))

    def test_refuses_when_the_image_is_absent(self):
        os.remove(os.path.join(self.fake, "image_ok"))
        p = self.run_proof()
        self.assertEqual(2, p.returncode)
        self.assertIn("is not present locally", self.evidence("run.log"))

    def test_temperature_gate_refuses_a_hot_nas(self):
        self.set_m2(54, 66)
        p = self.run_proof()
        self.assertEqual(2, p.returncode)
        self.assertIn("temperature gate tripped before", self.evidence("run.log"))
        self.assertNotIn("network create", self.calls())

    def test_temperature_gate_allows_a_cool_nas(self):
        self.set_m2(41, 43)
        self.assertEqual(0, self.run_proof().returncode)

    # ---------------------------------------------------------------- restore/verify failures (3)
    def test_failed_restore_is_fail_closed_and_still_cleans_up(self):
        self.knob("restore_rc", "1")
        p = self.run_proof()
        self.assertEqual(3, p.returncode)
        self.assertIn("W0-10A: BLOCKED", self.evidence("SUMMARY.txt"))
        self.assertIn("CLEANUP: PASS", self.evidence("SUMMARY.txt"))
        self.assert_no_leftovers()

    def test_documents_that_failed_to_restore_fail_the_proof(self):
        self.knob("restore_out", RESTORE_OUT.replace("0 document(s) failed", "3 document(s) failed"))
        p = self.run_proof()
        self.assertEqual(3, p.returncode)
        self.assertIn("3 document(s) failed to restore", self.evidence("run.log"))

    def test_unparsable_restore_summary_fails(self):
        self.knob("restore_out", "2026-09-20T12:00:01.000+0000 done, but no summary line\n")
        p = self.run_proof()
        self.assertEqual(3, p.returncode)
        self.assertIn("summary line not found", self.evidence("run.log"))

    def test_count_mismatch_fails(self):
        self.knob("verify_json", verify_json(documents=7))
        p = self.run_proof()
        self.assertEqual(3, p.returncode)
        self.assertIn("document count mismatch", self.evidence("run.log"))
        self.assert_no_leftovers()

    def test_missing_id_index_fails(self):
        self.knob("verify_json", verify_json(no_index=2))
        p = self.run_proof()
        self.assertEqual(3, p.returncode)
        self.assertIn("without an _id index", self.evidence("run.log"))

    def test_unreadable_sample_fails(self):
        self.knob("verify_json", verify_json(bad_samples=1))
        p = self.run_proof()
        self.assertEqual(3, p.returncode)
        self.assertIn("sample read(s) failed", self.evidence("run.log"))

    def test_verifier_saying_not_ok_fails(self):
        self.knob("verify_json", verify_json(ok="false"))
        p = self.run_proof()
        self.assertEqual(3, p.returncode)
        self.assertIn("ok=false", self.evidence("run.log"))

    def test_mongod_that_never_becomes_ready_fails_closed(self):
        os.remove(os.path.join(self.fake, "mongo_ready"))
        p = self.run_proof()
        self.assertEqual(3, p.returncode)
        self.assertIn("did not become ready", self.evidence("run.log"))
        self.assert_no_leftovers()

    # ---------------------------------------------------------------- cleanup (4) and production (5)
    def test_incomplete_cleanup_is_reported(self):
        self.knob("leak_container", "")
        p = self.run_proof()
        self.assertEqual(4, p.returncode)
        self.assertIn("CLEANUP: FAIL", self.evidence("SUMMARY.txt"))

    def test_production_change_is_detected(self):
        self.knob("mutate_prod", "")
        p = self.run_proof()
        self.assertEqual(5, p.returncode)
        self.assertIn("PRODUCTION_CHANGED: YES", self.evidence("SUMMARY.txt"))
        self.assertIn("MUTATED", self.evidence("prod-diff.txt"))

    def test_named_archive_argument_is_honoured(self):
        other = os.path.join(self.backups, "begwork_atlas_2026-09-13_0310.archive.gz")
        with gzip.open(other, "wb") as f:
            f.write(b"older archive")
        p = self.run_proof(os.path.basename(other))
        self.assertEqual(0, p.returncode)
        self.assertIn("BACKUP_FILE=" + os.path.basename(other), self.evidence("result.env"))


    # ------------------------------------------------- BLOCKER 1: cleanup must be run-scoped
    def test_foreign_w010a_objects_are_left_alone(self):
        foreign = self.foreign_objects()
        p = self.run_proof()
        self.assertEqual(0, p.returncode, p.stdout + p.stderr)
        for n in foreign:
            self.assertTrue(os.path.exists(os.path.join(self.fake, n)),
                            "cleanup destroyed another run's object: %s" % n)
        self.assert_no_leftovers_for_this_run()

    def test_cleanup_only_names_its_own_objects(self):
        self.foreign_objects()
        self.run_proof()
        removals = [l for l in self.calls().splitlines()
                    if l.startswith(("docker rm ", "docker volume rm", "docker network rm"))]
        self.assertTrue(removals)
        for line in removals:
            self.assertNotIn("OLDRUN", line, "cleanup addressed a foreign object: %s" % line)

    def test_parallel_run_is_refused_by_the_lock(self):
        os.makedirs(self.lock_dir())
        with open(os.path.join(self.lock_dir(), "owner"), "w") as f:
            f.write("pid=1 stamp=OTHER"+chr(10))
        p = self.run_proof()
        self.assertEqual(2, p.returncode)
        self.assertIn("another restore proof is already running", self.evidence("run.log"))
        self.assertNotIn("network create", self.calls())
        self.assertTrue(os.path.isdir(self.lock_dir()), "the other run's lock was removed")

    def test_lock_is_released_after_a_successful_run(self):
        self.assertEqual(0, self.run_proof().returncode)
        self.assertFalse(os.path.exists(self.lock_dir()), "the lock outlived the run")

    # ------------------------------------------------- BLOCKER 2: sensors are fail-closed
    def test_missing_sensors_refuse_by_default(self):
        empty = os.path.join(self.tmp, "no-sensors")
        os.makedirs(empty)
        p = self.run_proof(M2_GLOB=posix(empty) + "/nvme*/temperature")
        self.assertEqual(2, p.returncode)
        self.assertIn("no sensor found", self.evidence("run.log"))
        self.assertNotIn("network create", self.calls())

    def test_missing_sensors_need_an_explicit_override(self):
        empty = os.path.join(self.tmp, "no-sensors")
        os.makedirs(empty)
        p = self.run_proof(M2_GLOB=posix(empty) + "/nvme*/temperature", M2_SENSORS_REQUIRED="0")
        self.assertEqual(0, p.returncode, p.stdout + p.stderr)
        self.assertIn("M2_SENSORS_REQUIRED=0 was set explicitly", self.evidence("run.log"))

    def test_non_numeric_sensor_refuses(self):
        self.write(os.path.join(self.m2, "nvme1n1", "temperature"), "n/a"+chr(10))
        p = self.run_proof()
        self.assertEqual(2, p.returncode)
        self.assertIn("unreadable or non-numeric", self.evidence("run.log"))

    def test_non_numeric_sensor_refuses_even_with_the_override(self):
        self.write(os.path.join(self.m2, "nvme1n1", "temperature"), "n/a"+chr(10))
        p = self.run_proof(M2_SENSORS_REQUIRED="0")
        self.assertEqual(2, p.returncode)
        self.assertIn("unreadable or non-numeric", self.evidence("run.log"))

    def test_empty_sensor_file_refuses(self):
        self.write(os.path.join(self.m2, "nvme0n1", "temperature"), "")
        p = self.run_proof()
        self.assertEqual(2, p.returncode)
        self.assertIn("unreadable or non-numeric", self.evidence("run.log"))

    # ------------------------------------------------- BLOCKER 3: a trip must block PASS
    def test_hot_sensor_after_verification_blocks_pass(self):
        self.knob("heat_on_verify", "")
        p = self.run_proof()
        self.assertEqual(3, p.returncode)
        self.assertIn("W0-10A: BLOCKED", self.evidence("SUMMARY.txt"))
        self.assertIn("after verification", self.evidence("run.log"))
        self.assert_no_leftovers_for_this_run()

    def test_sampler_trip_during_verification_blocks_pass(self):
        self.knob("heat_on_verify", "")
        self.knob("stall_on_verify", "")
        p = self.run_proof()
        self.assertEqual(3, p.returncode)
        self.assertIn("W0-10A: BLOCKED", self.evidence("SUMMARY.txt"))
        self.assertIn("temperature gate", self.evidence("run.log"))
        self.assert_no_leftovers_for_this_run()

    # ------------------------------------------------- BLOCKER 4: interrupt safety
    def test_interrupted_run_cleans_up_and_releases_the_lock(self):
        foreign = self.foreign_objects()
        self.knob("kill_during_restore", "")
        p = self.run_proof()
        self.assertEqual(6, p.returncode, p.stdout + p.stderr)
        self.assertIn("interrupted by signal", self.evidence("run.log"))
        self.assertIn("INTERRUPTED: yes", self.evidence("SUMMARY.txt"))
        self.assert_no_leftovers_for_this_run()
        self.assertFalse(os.path.exists(self.lock_dir()), "the lock survived an interrupt")
        for n in foreign:
            self.assertTrue(os.path.exists(os.path.join(self.fake, n)),
                            "an interrupt destroyed another run's object: %s" % n)


    # ------------------------------------------------- re-review: same-second concurrency
    def test_two_runs_in_the_same_second_do_not_share_anything(self):
        """The fake clock pins both runs to one instant; uniqueness must come from pid+mktemp."""
        fake2 = self.second_fake()
        self.knob("stall_on_restore", "8")          # run A holds the lock while B tries

        a = self.popen_proof(_FAKE_CLOCK=1)
        try:
            for _ in range(150):                     # wait until A actually owns the lock
                if os.path.isdir(self.lock_dir()):
                    break
                time.sleep(0.1)
            self.assertTrue(os.path.isdir(self.lock_dir()), "run A never took the lock")
            a_dir = self.out_dirs()[0]

            b = self.run_proof(_FAKE_CLOCK=1, FAKE=posix(fake2))
            self.assertEqual(2, b.returncode, b.stdout + b.stderr)

            dirs = self.out_dirs()
            self.assertEqual(2, len(dirs), "the two runs did not get separate evidence directories")
            b_dir = [d for d in dirs if d != a_dir][0]
            self.assertNotEqual(a_dir, b_dir)

            a_id, b_id = self.run_id_of(a_dir), self.run_id_of(b_dir)
            self.assertTrue(a_id and b_id)
            self.assertNotEqual(a_id, b_id, "two runs produced the same RUN_ID")
            self.assertTrue(a_id.startswith("20260920T120000000Z"), a_id)
            self.assertTrue(b_id.startswith("20260920T120000000Z"), b_id)

            self.assertIn("another restore proof is already running", self.evidence_of(b_dir, "run.log"))
            self.assertTrue(os.path.isdir(self.lock_dir()), "the refused run removed the active lock")
            self.assertNotIn(a_id, self.calls_of(fake2), "the refused run addressed the other run's objects")
            self.assertNotIn("network create", self.calls_of(fake2))
            self.assertEqual("", self.evidence_of(b_dir, "restore.out"))

            # nothing of run B leaked into run A's evidence
            for name in ("run.log", "result.env"):
                self.assertNotIn(b_id, self.evidence_of(a_dir, name))
        finally:
            a.communicate(timeout=120)      # also closes the pipes (no ResourceWarning)

        self.assertEqual(0, a.returncode, "run A did not finish cleanly")
        self.assertIn("W0-10A: PASS", self.evidence_of(a_dir, "SUMMARY.txt"))
        self.assertIn("w010a-mongo-" + a_id, self.evidence_of(a_dir, "SUMMARY.txt"))
        self.assertFalse(os.path.exists(self.lock_dir()), "run A did not release the lock")

    def test_run_id_is_unique_across_back_to_back_runs_on_a_frozen_clock(self):
        first = self.run_proof(_FAKE_CLOCK=1)
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        second = self.run_proof(_FAKE_CLOCK=1)
        self.assertEqual(0, second.returncode, second.stdout + second.stderr)
        dirs = self.out_dirs()
        self.assertEqual(2, len(dirs))
        self.assertNotEqual(self.run_id_of(dirs[0]), self.run_id_of(dirs[1]))

    # ------------------------------------------------- re-review: configuration guards
    def test_invalid_sensor_switch_refuses(self):
        for bad in ("yes", "2", "", "1 "):
            p = self.run_proof(M2_SENSORS_REQUIRED=bad)
            self.assertEqual(2, p.returncode, "M2_SENSORS_REQUIRED=%r was accepted" % bad)
            self.assertIn("invalid M2_SENSORS_REQUIRED", self.evidence("run.log"))
            shutil.rmtree(self.out_root); os.makedirs(self.out_root)

    def test_invalid_temp_abort_refuses(self):
        for bad in ("hot", "0", "-5", "62.5", ""):
            p = self.run_proof(TEMP_ABORT=bad)
            self.assertEqual(2, p.returncode, "TEMP_ABORT=%r was accepted" % bad)
            self.assertIn("invalid TEMP_ABORT", self.evidence("run.log"))
            shutil.rmtree(self.out_root); os.makedirs(self.out_root)

    def test_invalid_ready_timeout_refuses(self):
        for bad in ("soon", "0", "-1", ""):
            p = self.run_proof(READY_TIMEOUT=bad)
            self.assertEqual(2, p.returncode, "READY_TIMEOUT=%r was accepted" % bad)
            self.assertIn("invalid READY_TIMEOUT", self.evidence("run.log"))
            shutil.rmtree(self.out_root); os.makedirs(self.out_root)

    def test_config_guards_run_before_any_docker_call(self):
        p = self.run_proof(TEMP_ABORT="hot")
        self.assertEqual(2, p.returncode)
        self.assertNotIn("network create", self.calls())
        self.assertFalse(os.path.exists(self.lock_dir()), "a rejected configuration still took the lock")


if __name__ == "__main__":
    unittest.main()
