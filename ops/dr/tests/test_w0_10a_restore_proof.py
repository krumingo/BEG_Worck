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

    def run_proof(self, *args):
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
        proc = subprocess.run([BASH, posix(SCRIPT), *args], env=env, capture_output=True, text=True)
        return proc

    def evidence_dir(self):
        dirs = sorted(os.listdir(self.out_root))
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
        left = [n for n in os.listdir(self.fake)
                if n.startswith(("c_w010a", "net_w010a", "vol_w010a"))]
        self.assertEqual([], left, "isolated objects survived cleanup: %s" % left)

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


if __name__ == "__main__":
    unittest.main()
