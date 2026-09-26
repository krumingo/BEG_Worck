"""W0-03C — the duplicate report hook for the W0-10A restore proof.

Three layers, none of which needs a NAS:

  * the hook alone (``w0_03c_duplicate_report_hook.sh``) against the committed fake docker:
    the export runs on the isolated network, the report runs with no network and a
    read-only root filesystem, the raw export is deleted, ЕГН never reaches the evidence,
    and every way of not producing a trustworthy report fails the hook;
  * the runner with a hook (``w0_10a_restore_proof.sh`` + ``POST_VERIFY_HOOK``): the hook
    runs after verification and before cleanup; a failing, hanging or overheating hook
    blocks PASS and cleanup still happens; without a hook nothing changes;
  * the export script (``w0_03c_export.js``): its plan is exactly the one the report
    reads, and — under node, with a stand-in ``db`` — it reads only planned collections
    and fields and skips the system databases.

The report itself runs for real (the local python stands in for ``python:3.11-slim``),
so the end-to-end tests exercise the same code that will run on the NAS.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DR_DIR = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(DR_DIR))
BACKEND = os.path.join(REPO, "backend")
HOOK = os.path.join(DR_DIR, "w0_03c_duplicate_report_hook.sh")
RUNNER = os.path.join(DR_DIR, "w0_10a_restore_proof.sh")
EXPORT_JS = os.path.join(DR_DIR, "w0_03c_export.js")
VERIFY_JS = os.path.join(DR_DIR, "verify_restore.js")
FAKE_DOCKER = os.path.join(HERE, "fakes", "docker")
BASH = shutil.which("bash")
NODE = shutil.which("node")

NET = "w010a-net-20260921T100000000Z-p1-abc"
HOST = "w010a-mongo-20260921T100000000Z-p1-abc"
EGN = "8001011234"


def posix(path):
    return os.path.abspath(path).replace("\\", "/")


def bash_path(path):
    """An absolute path as bash sees it: ``C:/x`` on Windows is ``/c/x`` (the NAS is Linux,
    where the two are the same)."""
    p = posix(path)
    return "/" + p[0].lower() + p[2:] if re.match(r"^[A-Za-z]:/", p) else p


def tag(tenant, name, tid, status="active"):
    return {"id": tid, "tenant_id": tenant, "entity_type": "tag", "display_name": name,
            "normalized_name": name.strip().lower(), "status": status, "aliases": []}


#: What begwork_beg held in the restored copy of 20.09.2026 (W0-10A verify.json) — the
#: hook's default expectations. A fixture that stands for a real restore carries them.
EXPECTED = ("companies", "clients", "counterparties", "persons", "items", "asset_units")


def export(databases, scanned=None):
    return json.dumps({"schema": "beg.master-data-uniqueness-export/v1",
                       "exported_at": "2026-09-21T10:00:00.000Z",
                       "scanned_databases": sorted(scanned if scanned is not None else
                                                   list(databases) + ["begwork_system"]),
                       "databases": databases},
                      ensure_ascii=False)


def begwork_beg(**collections):
    """begwork_beg as restored: every expected collection present (empty unless given)."""
    colls = {c: [] for c in EXPECTED}
    colls.update(collections)
    return {"collections": colls}


CLEAN_EXPORT = export({"begwork_beg": begwork_beg(
    md_tag=[tag("t1", "спешно", "g1")],
    companies=[{"id": "c1", "org_id": "o1", "name": "Строй ЕООД", "eik": "123456789"},
               {"id": "c2", "org_id": "o1", "name": "Строй", "eik": "123 456 789"}],
    persons=[{"id": "p1", "org_id": "o1", "first_name": "Иван", "egn": EGN},
             {"id": "p2", "org_id": "o1", "first_name": "Иван", "egn": EGN}],
)})

BLOCKED_EXPORT = export({"begwork_beg": begwork_beg(
    md_tag=[tag("t1", "спешно", "g1"), tag("t1", "Спешно", "g2")],
)})

#: Exports that prove nothing. EMPTY_EXPORT is literally the case of the review of
#: 25394418; the others are what w0_03c_export.js writes for a restore that lacks data.
EMPTY_EXPORT = json.dumps({"databases": {}})
NOTHING_SCANNED_EXPORT = export({}, scanned=[])
NO_PLANNED_COLLECTION_EXPORT = export({}, scanned=["begwork_beg", "begwork_system"])   # scanned, nothing planned
NOT_RESTORED_EXPORT = export({"tenant_two": {"collections": {"md_tag": []}}},
                             scanned=["begwork_system", "tenant_two"])
MISSING_COLLECTION_EXPORT = export({"begwork_beg": {"collections": {
    c: [] for c in EXPECTED if c != "companies"}}})


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="w003c-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.fake = os.path.join(self.tmp, "fake")
        self.out = os.path.join(self.tmp, "hook")
        os.makedirs(self.fake)
        self.knob("image_ok", "")
        self.knob("image_id", "sha256:1234abcd\n")
        self.knob("export_json", CLEAN_EXPORT)
        self.knob("report_python", posix(sys.executable))

    def write(self, path, text):
        with open(path, "w", newline="\n", encoding="utf-8") as f:
            f.write(text)

    def read(self, path):
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()

    def knob(self, name, text):
        self.write(os.path.join(self.fake, name), text)

    def calls(self):
        return self.read(os.path.join(self.fake, "calls.log"))


@unittest.skipUnless(BASH, "bash is required for the W0-03C hook tests")
class HookTests(_Base):
    def run_hook(self, **extra):
        env = dict(os.environ)
        env.update(W010A_NET=NET, W010A_MONGO_HOST=HOST, W010A_MONGO_IMAGE="mongo:7",
                   W010A_HOOK_OUT=posix(self.out), DOCKER=posix(FAKE_DOCKER), FAKE=posix(self.fake))
        env.update({k: str(v) for k, v in extra.items()})
        return subprocess.run([BASH, posix(HOOK)], env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    def result(self):
        return self.read(os.path.join(self.out, "result.env"))

    def report(self):
        return json.loads(self.read(os.path.join(self.out, "report.json")))

    def assert_export_gone(self):
        self.assertFalse(os.path.exists(os.path.join(self.out, "export.sensitive.json")),
                         "the raw export outlived the hook")

    # ---------------------------------------------------------------- results
    def test_clean_copy_gives_a_clean_report_and_the_export_is_deleted(self):
        p = self.run_hook()
        self.assertEqual(0, p.returncode, p.stdout + p.stderr)
        result = self.result()
        self.assertIn("W003C_REPORT=CLEAN", result)
        self.assertIn("W003C_EXPORT_DELETED=yes", result)
        self.assertIn("W003C_RESULT=PASS", result)
        self.assertRegex(result, r"W003C_EXPORT_SHA256=[0-9a-f]{64}")
        self.assertRegex(result, r"W003C_REPORT_SHA256=[0-9a-f]{64}")
        self.assert_export_gone()
        rep = self.report()
        self.assertEqual("beg.master-data-duplicate-report-set/v1", rep["schema"])
        self.assertTrue(rep["clean"])
        legacy = {x["key"]: x for x in rep["summary"][0]["legacy"]}
        self.assertEqual(1, legacy["organization.eik"]["groups"])        # informational
        self.assertEqual(1, legacy["person.egn"]["within_collection_groups"])

    def test_duplicates_are_a_result_not_a_hook_failure(self):
        self.knob("export_json", BLOCKED_EXPORT)
        p = self.run_hook()
        self.assertEqual(0, p.returncode, p.stdout + p.stderr)
        self.assertIn("W003C_REPORT=BLOCKED", self.result())
        rep = self.report()
        self.assertFalse(rep["clean"])
        self.assertEqual(["md_tag.md_uq_name"], rep["summary"][0]["blocked_indexes"])
        groups = [g for i in rep["databases"][0]["canonical"]["indexes"] for g in i["blocking_groups"]]
        self.assertEqual({"g1", "g2"}, {r["id"] for g in groups for r in g["records"]})
        self.assert_export_gone()

    # ---------------------------------------------------------------- an export that proves nothing
    def assert_incomplete(self, p, why):
        self.assertEqual(1, p.returncode, p.stdout + p.stderr)
        result = self.result()
        self.assertIn("W003C_REPORT=INCOMPLETE", result)
        self.assertIn("W003C_RESULT=FAIL", result)
        self.assertIn("W003C_REPORT_EXIT=5", result)
        self.assertNotIn("W003C_RESULT=PASS", result)
        self.assertNotIn("W003C_REPORT=BLOCKED", result)
        self.assertNotIn("W003C_REPORT=CLEAN", result)
        self.assertIn(why, result)
        self.assert_export_gone()
        rep = self.report()                      # kept, so the reason can be read
        self.assertEqual("INCOMPLETE", rep["verdict"])
        self.assertFalse(rep["evidence"]["complete"])

    def test_an_empty_export_fails_it_is_not_duplicates(self):
        self.knob("export_json", EMPTY_EXPORT)
        self.assert_incomplete(self.run_hook(), "no database with a planned collection")

    def test_an_export_that_scanned_nothing_fails(self):
        self.knob("export_json", NOTHING_SCANNED_EXPORT)
        self.assert_incomplete(self.run_hook(), "names no scanned database")

    def test_a_restored_database_without_any_planned_collection_fails(self):
        self.knob("export_json", NO_PLANNED_COLLECTION_EXPORT)
        self.assert_incomplete(self.run_hook(), "expected database begwork_beg holds none of the planned collections")

    def test_a_copy_without_the_tenant_database_fails(self):
        self.knob("export_json", NOT_RESTORED_EXPORT)
        self.assert_incomplete(self.run_hook(), "expected database begwork_beg was not found in the restored copy")

    def test_a_missing_expected_collection_fails(self):
        self.knob("export_json", MISSING_COLLECTION_EXPORT)
        self.assert_incomplete(self.run_hook(), "expected collection begwork_beg.companies is missing")

    def test_expectations_are_recorded_and_can_be_narrowed_explicitly(self):
        self.knob("export_json", MISSING_COLLECTION_EXPORT)
        p = self.run_hook(W003C_EXPECT_COLLECTIONS="begwork_beg.clients")
        self.assertEqual(0, p.returncode, p.stdout + p.stderr)
        self.assertIn("W003C_EXPECT_COLLECTIONS=begwork_beg.clients", self.result())
        self.assertIn("W003C_REPORT=CLEAN", self.result())

    def test_an_empty_database_expectation_is_refused(self):
        p = self.run_hook(W003C_EXPECT_DBS="")
        self.assertEqual(1, p.returncode)
        self.assertIn("W003C_EXPECT_DBS is empty", p.stdout)
        self.assertNotIn(" run ", self.calls())

    def test_an_unsafe_expectation_is_refused_before_any_container(self):
        for extra in ({"W003C_EXPECT_DBS": "begwork_beg;rm"},
                      {"W003C_EXPECT_COLLECTIONS": "begwork_beg.companies$(id)"},
                      {"W003C_EXPECT_COLLECTIONS": "companies"},
                      {"W003C_EXPECT_COLLECTIONS": "begwork_beg..companies"}):
            p = self.run_hook(**extra)
            self.assertEqual(1, p.returncode, extra)
            self.assertIn("invalid W003C_EXPECT", p.stdout)
        self.assertNotIn(" run ", self.calls())

    # ---------------------------------------------------------------- the exit code alone is not trusted
    def canned(self, rc, report):
        os.remove(os.path.join(self.fake, "report_python"))
        self.knob("report_rc", str(rc))
        self.knob("report_json", json.dumps(report, indent=2))

    def test_exit_1_without_a_blocked_verdict_fails(self):
        self.canned(1, {"verdict": "INCOMPLETE", "clean": False})
        p = self.run_hook()
        self.assertEqual(1, p.returncode)
        self.assertIn("they must agree", p.stdout)
        self.assertNotIn("W003C_REPORT=BLOCKED", self.result())
        self.assert_export_gone()

    def test_exit_0_with_a_report_that_is_not_clean_fails(self):
        self.canned(0, {"verdict": "INCOMPLETE", "clean": False})
        p = self.run_hook()
        self.assertEqual(1, p.returncode)
        self.assertIn("they must agree", p.stdout)
        self.assertNotIn("W003C_RESULT=PASS", self.result())

    def test_egn_never_reaches_the_evidence(self):
        p = self.run_hook()
        self.assertEqual(0, p.returncode, p.stdout + p.stderr)
        for name in os.listdir(self.out):
            self.assertNotIn(EGN, self.read(os.path.join(self.out, name)), name)
        self.assertNotIn(EGN, p.stdout + p.stderr)
        self.assertIn("egn:80****34", json.dumps(self.report(), ensure_ascii=False))

    # ---------------------------------------------------------------- isolation of the two containers
    def test_export_runs_on_the_isolated_network_with_the_script_read_only(self):
        self.run_hook()
        export_calls = [l for l in self.calls().splitlines() if "/w003c_export.js" in l and " run " in l]
        self.assertEqual(1, len(export_calls))
        line = export_calls[0]
        self.assertIn("--network %s" % NET, line)
        self.assertIn("--host %s" % HOST, line)
        self.assertIn("/w003c_export.js:ro", line)
        self.assertNotIn(" -p ", line)
        self.assertNotIn("mongodb+srv", self.calls())

    def test_report_runs_without_network_on_a_read_only_filesystem(self):
        self.run_hook()
        report_calls = [l for l in self.calls().splitlines() if "/w003c/scripts/" in l and " run " in l]
        self.assertEqual(1, len(report_calls))
        line = report_calls[0]
        self.assertIn("--network none", line)
        self.assertIn("--read-only", line)
        self.assertIn(":/w003c/app/master_data:ro", line)
        self.assertIn(":/w003c/scripts/w0_03c_master_data_uniqueness.py:ro", line)
        self.assertIn("python:3.11-slim python -I -B", line)

    # ---------------------------------------------------------------- refusals
    def test_refuses_to_run_outside_the_runner(self):
        for missing in ("W010A_NET", "W010A_MONGO_HOST", "W010A_MONGO_IMAGE"):
            p = self.run_hook(**{missing: ""})
            self.assertNotEqual(0, p.returncode, missing)
            self.assertNotIn(" run ", self.calls(), missing)

    def test_refuses_a_network_or_host_that_is_not_w010a(self):
        for extra in ({"W010A_NET": "bridge"}, {"W010A_NET": "host"},
                      {"W010A_MONGO_HOST": "begwork-backend"},
                      {"W010A_MONGO_HOST": "cluster0.abcde.mongodb.net"}):
            p = self.run_hook(**extra)
            self.assertNotEqual(0, p.returncode, extra)
            self.assertIn("refusing", p.stdout + p.stderr)
        self.assertNotIn(" run ", self.calls())

    def test_refuses_when_the_python_image_is_absent(self):
        self.knob("absent_python_3.11-slim", "")
        p = self.run_hook()
        self.assertEqual(1, p.returncode)
        self.assertIn("is not present locally", p.stdout)
        self.assertNotIn(" run ", self.calls())

    def test_a_failed_export_fails_and_leaves_no_export(self):
        self.knob("export_rc", "1")
        p = self.run_hook()
        self.assertEqual(1, p.returncode)
        self.assertIn("W003C_RESULT=FAIL", self.result())
        self.assert_export_gone()
        self.assertNotIn("/w003c/scripts/", self.calls())

    def test_an_export_that_reports_a_fatal_error_fails(self):
        self.knob("export_json", '{"ok":false,"fatal":"MongoServerError: not primary"}\n')
        p = self.run_hook()
        self.assertEqual(1, p.returncode)
        self.assertIn("not primary", self.read(os.path.join(self.out, "export.err")))
        self.assert_export_gone()

    def test_an_empty_export_fails(self):
        self.knob("export_json", "")
        p = self.run_hook()
        self.assertEqual(1, p.returncode)
        self.assertIn("export is empty", p.stdout)

    def test_an_unreadable_export_fails_the_report_and_the_export_still_goes(self):
        self.knob("export_json", "{not json")
        p = self.run_hook()
        self.assertEqual(1, p.returncode)
        self.assertIn("report exited 2", p.stdout)
        self.assert_export_gone()
        self.assertFalse(os.path.exists(os.path.join(self.out, "report.json")))

    def test_an_export_of_another_schema_is_refused(self):
        self.knob("export_json", json.dumps({"schema": "something/else", "databases": {}}))
        p = self.run_hook()
        self.assertEqual(1, p.returncode)
        self.assert_export_gone()

    def test_a_report_container_that_writes_nothing_fails(self):
        os.remove(os.path.join(self.fake, "report_python"))
        self.knob("report_rc", "0")                  # claims success, writes no report.json
        p = self.run_hook()
        self.assertEqual(1, p.returncode)
        self.assertIn("wrote no report.json", p.stdout)
        self.assert_export_gone()


@unittest.skipUnless(BASH, "bash is required for the W0-10A runner tests")
class RunnerWithHookTests(_Base):
    """The runner side of POST_VERIFY_HOOK (W0-10A behaviour without a hook is covered,
    unchanged, by test_w0_10a_restore_proof.py)."""

    ARCHIVE = "begwork_atlas_2026-09-21_0310.archive.gz"

    def setUp(self):
        super().setUp()
        import gzip
        self.prod = os.path.join(self.tmp, "prod")
        self.backups = os.path.join(self.prod, "backups")
        self.out_root = os.path.join(self.tmp, "out")
        self.m2 = os.path.join(self.tmp, "m2")
        for d in (self.backups, os.path.join(self.prod, "repo"), self.out_root):
            os.makedirs(d)
        self.write(os.path.join(self.prod, ".env"), "MONGO_URL=mongodb+srv://sentinel\n")
        with gzip.open(os.path.join(self.backups, self.ARCHIVE), "wb") as f:
            f.write(b"fake archive")
        self.set_m2(54, 57)
        self.knob("mongo_ready", "")
        self.knob("restore_out", "x\t1234 document(s) restored successfully. 0 document(s) failed to restore.\n")
        self.knob("verify_json", '{"ok": true, "total_databases": 2, "total_collections": 93, '
                                 '"total_documents": 1234, "collections_without_id_index": 0, '
                                 '"sample_reads_failed": 0, "tenant_check": "PASS", "problems": []}\n')
        for c in ("begwork-backend", "begwork-frontend", "kpo-photo-cleaner", "beg-raboti"):
            self.knob("prod_" + c, "cid-%s running restarts=7\n" % c)

    def set_m2(self, *temps):
        for i, t in enumerate(temps):
            d = os.path.join(self.m2, "nvme%dn1" % i)
            os.makedirs(d, exist_ok=True)
            self.write(os.path.join(d, "temperature"), "%d\n" % t)

    def hook_script(self, body):
        path = os.path.join(self.tmp, "hook.sh")
        self.write(path, "#!/usr/bin/env bash\n" + body)
        return bash_path(path)

    def run_proof(self, **extra):
        env = dict(os.environ)
        env.update(PROD=posix(self.prod), BACKUP_DIR=posix(self.backups), OUT_ROOT=posix(self.out_root),
                   DOCKER=posix(FAKE_DOCKER), FAKE=posix(self.fake),
                   M2_GLOB=posix(self.m2) + "/nvme*/temperature", VERIFY_JS=posix(VERIFY_JS),
                   MONGO_IMAGE="mongo:7", TEMP_ABORT="62", READY_TIMEOUT="9")
        env.update({k: str(v) for k, v in extra.items()})
        return subprocess.run([BASH, posix(RUNNER)], env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    def evidence_dir(self):
        dirs = sorted(d for d in os.listdir(self.out_root) if d.startswith("out-"))
        self.assertTrue(dirs)
        return os.path.join(self.out_root, dirs[-1])

    def evidence(self, name):
        return self.read(os.path.join(self.evidence_dir(), name))

    def assert_no_leftovers(self):
        left = [n for n in os.listdir(self.fake) if n.startswith(("c_w010a", "net_w010a", "vol_w010a"))]
        self.assertEqual([], left)

    # ---------------------------------------------------------------- happy path
    def test_hook_runs_against_the_live_copy_before_cleanup(self):
        marker = posix(os.path.join(self.tmp, "marker"))
        hook = self.hook_script(
            'echo "net=$W010A_NET host=$W010A_MONGO_HOST image=$W010A_MONGO_IMAGE out=$W010A_HOOK_OUT" > %s\n'
            '[ -f "$FAKE/c_$W010A_MONGO_HOST" ] && echo container-alive >> %s\n'
            '[ -f "$FAKE/net_$W010A_NET" ] && echo network-alive >> %s\n'
            'exit 0\n' % (marker, marker, marker))
        p = self.run_proof(POST_VERIFY_HOOK=hook)
        self.assertEqual(0, p.returncode, p.stdout + p.stderr)
        seen = self.read(marker)
        self.assertRegex(seen, r"net=w010a-net-\S+ host=w010a-mongo-\S+ image=mongo:7 out=\S+/hook")
        self.assertIn("container-alive", seen)
        self.assertIn("network-alive", seen)
        summary = self.evidence("SUMMARY.txt")
        self.assertIn("W0-10A: PASS", summary)
        self.assertIn("POST_VERIFY_HOOK: PASS", summary)
        self.assertIn("CLEANUP: PASS", summary)
        self.assertRegex(self.evidence("result.env"), r"POST_VERIFY_HOOK_SHA256=[0-9a-f]{64}")
        self.assert_no_leftovers()

    def test_without_a_hook_nothing_changes(self):
        p = self.run_proof()
        self.assertEqual(0, p.returncode, p.stdout + p.stderr)
        self.assertNotIn("POST_VERIFY_HOOK", self.evidence("SUMMARY.txt"))
        self.assertNotIn("POST_VERIFY_HOOK", self.evidence("result.env"))
        self.assertFalse(os.path.exists(os.path.join(self.evidence_dir(), "hook")))
        self.assertNotIn("post-verify hook", self.evidence("run.log"))

    # ---------------------------------------------------------------- the hook cannot make a run pass
    def test_a_failing_hook_blocks_pass_and_cleanup_still_runs(self):
        p = self.run_proof(POST_VERIFY_HOOK=self.hook_script("exit 7\n"))
        self.assertEqual(3, p.returncode, p.stdout + p.stderr)
        summary = self.evidence("SUMMARY.txt")
        self.assertIn("W0-10A: BLOCKED", summary)
        self.assertIn("POST_VERIFY_HOOK: FAIL", summary)
        self.assertIn("CLEANUP: PASS", summary)
        self.assertIn("post-verify hook exited 7", self.evidence("run.log"))
        self.assert_no_leftovers()

    def test_a_hanging_hook_is_stopped_and_blocks_pass(self):
        p = self.run_proof(POST_VERIFY_HOOK=self.hook_script("sleep 30\n"), HOOK_TIMEOUT="2")
        self.assertEqual(3, p.returncode, p.stdout + p.stderr)
        self.assertIn("POST_VERIFY_HOOK_RESULT=TIMEOUT", self.evidence("result.env"))
        self.assertIn("did not finish in 2s", self.evidence("run.log"))
        self.assert_no_leftovers()

    def test_heat_during_the_hook_blocks_pass(self):
        hook = self.hook_script('for s in $(ls %s/nvme*/temperature); do echo 70 > "$s"; done\nexit 0\n'
                                % posix(self.m2))
        p = self.run_proof(POST_VERIFY_HOOK=hook)
        self.assertEqual(3, p.returncode, p.stdout + p.stderr)
        self.assertIn("after the post-verify hook", self.evidence("run.log"))
        self.assertIn("W0-10A: BLOCKED", self.evidence("SUMMARY.txt"))
        self.assert_no_leftovers()

    def test_sensitive_output_a_hook_leaves_behind_is_removed_by_cleanup(self):
        hook = self.hook_script('echo raw > "$W010A_HOOK_OUT/export.sensitive.json"\nexit 1\n')
        p = self.run_proof(POST_VERIFY_HOOK=hook)
        self.assertEqual(3, p.returncode, p.stdout + p.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.evidence_dir(), "hook", "export.sensitive.json")))
        self.assertIn("CLEANUP: PASS", self.evidence("SUMMARY.txt"))

    # ---------------------------------------------------------------- configuration guards
    def test_a_relative_or_missing_hook_is_refused_before_any_docker_call(self):
        for bad in ("hook.sh", "C:/does-not-exist.sh", bash_path(os.path.join(self.tmp, "does-not-exist.sh"))):
            p = self.run_proof(POST_VERIFY_HOOK=bad)
            self.assertEqual(2, p.returncode, bad)
            self.assertNotIn("network create", self.calls())
            shutil.rmtree(self.out_root); os.makedirs(self.out_root)

    def test_an_invalid_hook_timeout_is_refused(self):
        hook = self.hook_script("exit 0\n")
        for bad in ("soon", "0", "-1", ""):
            p = self.run_proof(POST_VERIFY_HOOK=hook, HOOK_TIMEOUT=bad)
            self.assertEqual(2, p.returncode, "HOOK_TIMEOUT=%r was accepted" % bad)
            self.assertIn("invalid HOOK_TIMEOUT", self.evidence("run.log"))
            shutil.rmtree(self.out_root); os.makedirs(self.out_root)

    # ---------------------------------------------------------------- end to end with the real hook
    def assert_proof_blocked_by_an_incomplete_export(self, why):
        p = self.run_proof(POST_VERIFY_HOOK=bash_path(HOOK))
        self.assertEqual(3, p.returncode, p.stdout + p.stderr)
        summary = self.evidence("SUMMARY.txt")
        self.assertIn("W0-10A: BLOCKED", summary)
        self.assertIn("POST_VERIFY_HOOK: FAIL", summary)
        self.assertIn("CLEANUP: PASS", summary)
        self.assertIn("PRODUCTION_CHANGED: NO", summary)
        self.assertIn("post-verify hook exited 1", self.evidence("run.log"))
        hook_dir = os.path.join(self.evidence_dir(), "hook")
        hook_result = self.read(os.path.join(hook_dir, "result.env"))
        self.assertIn("W003C_REPORT=INCOMPLETE", hook_result)
        self.assertIn("W003C_RESULT=FAIL", hook_result)
        self.assertIn(why, hook_result)
        self.assertEqual("INCOMPLETE", json.loads(self.read(os.path.join(hook_dir, "report.json")))["verdict"])
        self.assertFalse([n for n in os.listdir(hook_dir) if ".sensitive" in n])
        self.assert_no_leftovers()

    def test_restore_proof_is_blocked_by_an_empty_export(self):
        self.knob("export_json", EMPTY_EXPORT)
        self.assert_proof_blocked_by_an_incomplete_export("no database with a planned collection")

    def test_restore_proof_is_blocked_by_a_database_without_planned_collections(self):
        self.knob("export_json", NO_PLANNED_COLLECTION_EXPORT)
        self.assert_proof_blocked_by_an_incomplete_export(
            "expected database begwork_beg holds none of the planned collections")

    def test_restore_proof_is_blocked_by_a_missing_expected_collection(self):
        self.knob("export_json", MISSING_COLLECTION_EXPORT)
        self.assert_proof_blocked_by_an_incomplete_export("expected collection begwork_beg.companies is missing")

    def test_restore_proof_with_a_clean_complete_copy_passes(self):
        self.knob("export_json", CLEAN_EXPORT)
        p = self.run_proof(POST_VERIFY_HOOK=bash_path(HOOK))
        self.assertEqual(0, p.returncode, p.stdout + p.stderr)
        self.assertIn("W0-10A: PASS", self.evidence("SUMMARY.txt"))
        hook_dir = os.path.join(self.evidence_dir(), "hook")
        self.assertIn("W003C_REPORT=CLEAN", self.read(os.path.join(hook_dir, "result.env")))

    def test_restore_proof_with_the_real_duplicate_report_hook(self):
        self.knob("export_json", BLOCKED_EXPORT)
        p = self.run_proof(POST_VERIFY_HOOK=bash_path(HOOK))
        self.assertEqual(0, p.returncode, p.stdout + p.stderr)
        self.assertIn("POST_VERIFY_HOOK: PASS", self.evidence("SUMMARY.txt"))
        hook_dir = os.path.join(self.evidence_dir(), "hook")
        self.assertIn("W003C_REPORT=BLOCKED", self.read(os.path.join(hook_dir, "result.env")))
        rep = json.loads(self.read(os.path.join(hook_dir, "report.json")))
        self.assertEqual(["md_tag.md_uq_name"], rep["summary"][0]["blocked_indexes"])
        self.assertFalse(os.path.exists(os.path.join(hook_dir, "export.sensitive.json")))
        self.assert_no_leftovers()


@unittest.skipUnless(BASH and shutil.which("git"), "bash and git are required for the bundle test")
class BundleTests(unittest.TestCase):
    """The NAS gets the files of ONE commit, byte-identical, LF only, with a manifest."""

    def test_bundle_of_head_is_complete_lf_only_and_checksummed(self):
        head = subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"], capture_output=True, text=True)
        if head.returncode != 0:
            self.skipTest("not a git checkout")
        sha = head.stdout.strip()
        present = subprocess.run(["git", "-C", REPO, "cat-file", "-e",
                                  "%s:ops/dr/w0_03c_duplicate_report_hook.sh" % sha], capture_output=True)
        if present.returncode != 0:
            self.skipTest("HEAD does not contain the W0-03C hook yet (uncommitted work)")
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "bundle")
            p = subprocess.run([BASH, posix(os.path.join(DR_DIR, "w0_03c_make_bundle.sh")), sha, posix(out)],
                               cwd=REPO, capture_output=True, text=True)
            self.assertEqual(0, p.returncode, p.stdout + p.stderr)
            name = "w0_03c_bundle_%s.tar.gz" % sha[:12]
            archive = os.path.join(out, name)
            self.assertTrue(os.path.exists(archive))
            import hashlib
            import tarfile
            with open(archive, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
            with open(archive + ".sha256", encoding="utf-8") as f:
                self.assertEqual(digest, f.read().split()[0])
            with tarfile.open(archive) as tar:
                members = {m.name: m for m in tar.getmembers() if m.isfile()}
                root = sha[:12] + "/"
                for needed in ("ops/dr/w0_10a_restore_proof.sh", "ops/dr/verify_restore.js",
                               "ops/dr/w0_03c_duplicate_report_hook.sh", "ops/dr/w0_03c_export.js",
                               "backend/app/master_data/uniqueness.py",
                               "backend/scripts/w0_03c_master_data_uniqueness.py", "BUNDLE_MANIFEST.txt"):
                    self.assertIn(root + needed, members)
                self.assertFalse([n for n in members if not n.startswith(root)])
                self.assertFalse([n for n in members if "/backend/" in n and
                                  not n.startswith((root + "backend/app/master_data/",
                                                    root + "backend/scripts/w0_03c_"))])
                for n in members:
                    self.assertNotIn(b"\r", tar.extractfile(members[n]).read(), n)
                manifest = tar.extractfile(members[root + "BUNDLE_MANIFEST.txt"]).read().decode()
                self.assertIn("commit " + sha, manifest)
                self.assertIn("./ops/dr/w0_03c_duplicate_report_hook.sh", manifest)


class ExportScriptTests(unittest.TestCase):
    PLAN_RE = re.compile(r"// BEGIN EXPORT PLAN\nconst PLAN = (\{.*?\});\n// END EXPORT PLAN", re.S)

    def js(self):
        with open(EXPORT_JS, encoding="utf-8") as f:
            return f.read()

    def test_the_export_plan_is_the_one_the_report_reads(self):
        sys.path.insert(0, BACKEND)
        try:
            from app.master_data.uniqueness import export_plan
        finally:
            sys.path.remove(BACKEND)
        m = self.PLAN_RE.search(self.js())
        self.assertIsNotNone(m, "the PLAN block is missing from w0_03c_export.js")
        self.assertEqual(export_plan(), json.loads(m.group(1)),
                         "w0_03c_export.js drifted from uniqueness.export_plan() — regenerate it")

    def test_the_export_only_reads(self):
        code = re.sub(r"//.*", "", self.js())
        for write in ("insert", "update", "delete", "remove", "drop", "createIndex", "aggregate",
                      "bulkWrite", "replaceOne", "findOneAnd", "renameCollection", "$out", "$merge"):
            self.assertNotIn(write, code)

    HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const reads = [];
const data = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
function project(doc, proj) {
  const out = {};
  for (const k of Object.keys(proj)) {
    if (k === '_id' || !proj[k]) continue;
    const [head, rest] = k.split('.', 2);
    if (!(head in doc)) continue;
    out[head] = rest ? doc[head].map((e) => ({[rest]: e[rest]})) : doc[head];
  }
  return out;
}
const db = {
  adminCommand: () => ({databases: Object.keys(data).map((name) => ({name}))}),
  getSiblingDB: (name) => ({
    getCollectionNames: () => Object.keys(data[name]),
    getCollection: (coll) => ({
      find: (q, proj) => { reads.push({db: name, coll, q, proj}); return {toArray: () => data[name][coll].map((d) => project(d, proj))}; },
    }),
  }),
};
let printed = null;
const ctx = {db, print: (s) => { printed = s; }, quit: (c) => { throw new Error('quit ' + c); },
             EJSON: {stringify: (v) => JSON.stringify(v)}, Object, JSON, Date};
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
process.stdout.write(JSON.stringify({printed: JSON.parse(printed), reads}));
"""

    def run_export(self, data):
        """Execute w0_03c_export.js under node against a stand-in server holding ``data``."""
        with tempfile.TemporaryDirectory() as tmp:
            path, src = os.path.join(tmp, "harness.js"), os.path.join(tmp, "data.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.HARNESS)
            with open(src, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            p = subprocess.run([NODE, path, EXPORT_JS, src], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(0, p.returncode, p.stderr)
        result = json.loads(p.stdout)
        return result["printed"], result["reads"]

    def report_of(self, exported, **expect):
        sys.path.insert(0, BACKEND)
        try:
            from app.master_data.uniqueness import report_set_from_export
        finally:
            sys.path.remove(BACKEND)
        return report_set_from_export(exported, **expect)

    @unittest.skipUnless(NODE, "node is required to execute the export script")
    def test_the_export_reads_only_planned_collections_and_fields(self):
        out, reads = self.run_export({
            "begwork_beg": {
                "companies": [{"id": "c1", "org_id": "o", "name": "А", "eik": "1", "iban": "BG00SECRET", "_id": "x"}],
                "md_tag": [{"id": "t1", "tenant_id": "t", "status": "active", "normalized_name": "a",
                            "notes": "secret"}],
                "payments": [{"id": "pay1", "amount": 5}],
            },
            "begwork_system": {"tenant_registry": [{"id": "t"}]},
            "admin": {"companies": [{"id": "should-not-be-read"}]},
        })
        self.assertEqual(["begwork_beg", "begwork_system"], out["scanned_databases"])
        self.assertEqual(["begwork_beg"], list(out["databases"]))
        self.assertEqual({"companies", "md_tag"}, set(out["databases"]["begwork_beg"]["collections"]))
        self.assertEqual({("begwork_beg", "companies"), ("begwork_beg", "md_tag")},
                         {(r["db"], r["coll"]) for r in reads})
        for r in reads:
            self.assertEqual({}, r["q"])
            self.assertEqual(0, r["proj"]["_id"])
        text = json.dumps(out)
        self.assertNotIn("BG00SECRET", text)
        self.assertNotIn("secret", text)
        self.assertNotIn("pay1", text)

    @unittest.skipUnless(NODE, "node is required to execute the export script")
    def test_what_the_export_writes_for_a_restore_without_planned_collections_is_incomplete(self):
        """The real export script, then the real report: a restored begwork_beg that holds
        none of the planned collections (or no restored tenant database at all) comes out
        INCOMPLETE — never CLEAN, never BLOCKED."""
        for data in ({"begwork_beg": {"payments": [{"id": 1}]}, "begwork_system": {"tenant_registry": []}},
                     {"begwork_system": {"tenant_registry": []}},
                     {}):
            out, _ = self.run_export(data)
            rs = self.report_of(out, expected_databases=["begwork_beg"])
            self.assertEqual("INCOMPLETE", rs["verdict"], data)

    @unittest.skipUnless(NODE, "node is required to execute the export script")
    def test_what_the_export_writes_for_a_complete_restore_is_evidence(self):
        out, _ = self.run_export({
            "begwork_beg": {c: [] for c in EXPECTED},
            "begwork_system": {"tenant_registry": []},
        })
        rs = self.report_of(out, expected_databases=["begwork_beg"],
                            expected_collections=["begwork_beg." + c for c in EXPECTED])
        self.assertEqual("CLEAN", rs["verdict"])
        self.assertEqual([], rs["evidence"]["problems"])


if __name__ == "__main__":
    unittest.main()
