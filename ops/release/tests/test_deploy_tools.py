"""W0-09A deploy / rollback / adopt / retention tests (fake docker, compose and curl; real verifier).

Exec bits: on Windows test hosts NTFS cannot store them, so tree verification takes modes
from the release artifact; on Linux the real filesystem modes are verified.
"""
import json
import os
import shutil
import tempfile
import unittest

from harness import (BASH, INITIAL_IMAGES, LIVE_NGINX_BLOB, SECRET_JWT, SECRET_MONGO_PASSWORD, VERIFIER_IMAGE_ID, Layout,
                     build, make_repo, read_json, read_text, tree_matches)
from beg_release import manifest as mf

BUILD_BACKEND = "compose up -d --no-deps --build backend"
EXACT_BACKEND = "compose up -d --no-deps --no-build --force-recreate backend"


@unittest.skipUnless(BASH, "bash is required for the Synology tool tests")
class DeployToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="w009a-")
        cls.repo = os.path.join(cls.tmp, "repo")
        cls.c = make_repo(cls.repo)
        cls.bundles = os.path.join(cls.tmp, "bundles")
        p, cls.b0 = build(cls.repo, cls.c["c0"], cls.bundles, "--no-previous", "--baseline",
                          "--legacy-extra", "nginx.conf=" + LIVE_NGINX_BLOB)
        assert cls.b0, p.stderr + p.stdout
        p, cls.b1 = build(cls.repo, cls.c["c1"], cls.bundles, "--previous-manifest", os.path.join(cls.b0, "manifest.json"))
        assert cls.b1, p.stderr + p.stdout
        p, cls.b2 = build(cls.repo, cls.c["c2"], cls.bundles, "--previous-manifest", os.path.join(cls.b1, "manifest.json"))
        assert cls.b2, p.stderr + p.stdout
        cls.m0 = read_json(os.path.join(cls.b0, "manifest.json"))["release"]
        cls.m1 = read_json(os.path.join(cls.b1, "manifest.json"))["release"]
        cls.m2 = read_json(os.path.join(cls.b2, "manifest.json"))["release"]
        cls.initial_runtime = "backend=%s,frontend=%s" % (INITIAL_IMAGES["backend"], INITIAL_IMAGES["frontend"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="layout-", dir=self.tmp)
        self.lay = Layout(self.root, self.repo, self.c)

    def adopt(self):
        p = self.lay.run(self.b0, "release_adopt.sh")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def assert_live_is_c0(self):
        ok, detail = tree_matches(os.path.join(self.lay.base, "repo"), self.repo, self.c["c0"],
                                  extras={"nginx.conf": LIVE_NGINX_BLOB})
        self.assertTrue(ok, detail)

    def assert_no_secrets(self, *texts):
        blob = "\n".join(texts) + self.lay.all_text()
        self.assertNotIn(SECRET_JWT, blob)
        self.assertNotIn(SECRET_MONGO_PASSWORD, blob)

    # ------------------------------------------------------------------ adopt
    def assert_runtime(self, backend, frontend):
        self.assertEqual(self.lay.container_image("begwork-backend"), backend)
        self.assertEqual(self.lay.container_image("begwork-frontend"), frontend)

    def test_adopt_records_live_release_and_its_runtime_images_without_container_actions(self):
        p = self.adopt()
        cur = self.lay.state("current.env")
        self.assertEqual(cur["RELEASE_ID"], self.m0["release_id"])
        self.assertEqual(cur["TREE_DIR"], "repo")
        self.assertEqual(cur["LEGACY_EXTRAS"], "nginx.conf=" + LIVE_NGINX_BLOB)
        self.assertEqual(cur["RUNTIME_IMAGES"], self.initial_runtime)
        self.assertEqual(cur["RUNTIME_REFS"], "backend=begwork-backend,frontend=begwork-frontend")
        tags = self.lay.tags()
        self.assertEqual(tags["beg-release/backend:" + self.m0["release_id"]], INITIAL_IMAGES["backend"])
        self.assertEqual(tags["beg-release/frontend:" + self.m0["release_id"]], INITIAL_IMAGES["frontend"])
        self.assertEqual(read_text(os.path.join(self.lay.base, "DEPLOYED_COMMIT")).strip(), self.c["c0"])
        self.assertNotIn("compose", self.lay.calls())
        self.assertNotRegex(self.lay.calls(), r"docker (run|rmi|stop|start|restart|rm) ")
        rec = self.lay.records()[-1]
        self.assertEqual(rec["status"], "ADOPTED")
        self.assertEqual(rec["runtime_images"], INITIAL_IMAGES)
        self.assertEqual(mf.validate_record(rec), [])
        self.assert_no_secrets(p.stdout, p.stderr)

    def test_adopt_refuses_when_a_container_is_not_running(self):
        self.lay.set_container("begwork-frontend", "exited", 0, "2026-01-01T00:00:00Z")
        p = self.lay.run(self.b0, "release_adopt.sh")
        self.assertEqual(p.returncode, 2, p.stdout)
        self.assertIn("runtime image cannot be recorded", p.stdout)
        self.assertIsNone(self.lay.state("current.env"))

    def test_adopt_refuses_when_live_tree_differs(self):
        with open(os.path.join(self.lay.base, "repo", "backend", "server.py"), "a") as f:
            f.write("# hotfix on the NAS\n")
        p = self.lay.run(self.b0, "release_adopt.sh")
        self.assertEqual(p.returncode, 2, p.stdout)
        self.assertIsNone(self.lay.state("current.env"))

    # ----------------------------------------------------------------- deploy
    def test_deploy_success_rebuilds_only_changed_service_and_records_everything(self):
        self.adopt()
        self.lay.fake_file("compose_output", "Step 1/7 : FROM python:3.11-slim\nJWT_SECRET=%s\n" % SECRET_JWT)
        p = self.lay.run(self.b1, "release_deploy.sh")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

        ok, detail = tree_matches(os.path.join(self.lay.base, "repo"), self.repo, self.c["c1"])
        self.assertTrue(ok, detail)
        anchor = "repo.rollback-" + self.m0["release_id"]
        ok, detail = tree_matches(os.path.join(self.lay.base, anchor), self.repo, self.c["c0"],
                                  extras={"nginx.conf": LIVE_NGINX_BLOB})
        self.assertTrue(ok, detail)

        cur, prev = self.lay.state("current.env"), self.lay.state("previous.env")
        self.assertEqual(cur["RELEASE_ID"], self.m1["release_id"])
        self.assertEqual(cur["COMMIT"], self.c["c1"])
        self.assertEqual(cur["SERVICES_REBUILT"], "backend")
        self.assertEqual(prev["RELEASE_ID"], self.m0["release_id"])
        self.assertEqual(prev["TREE_DIR"], anchor)
        self.assertEqual(read_text(os.path.join(self.lay.base, "DEPLOYED_COMMIT")).strip(), self.c["c1"])
        self.assertFalse(os.path.exists(os.path.join(self.lay.base, "repo", "DEPLOYED_COMMIT")))

        calls = self.lay.calls()
        self.assertEqual(self.lay.compose_ups(), [BUILD_BACKEND])
        self.assertNotRegex(calls.lower(), r"bootstrap|migrat")
        self.assertFalse([d for d in os.listdir(self.lay.base) if d.startswith("repo.staging-")])

        new_backend = self.lay.builds()[0].split()[-1]
        self.assert_runtime(new_backend, INITIAL_IMAGES["frontend"])
        self.assertEqual(cur["RUNTIME_IMAGES"], "backend=%s,frontend=%s" % (new_backend, INITIAL_IMAGES["frontend"]))
        self.assertEqual(prev["RUNTIME_IMAGES"], self.initial_runtime)
        tags = self.lay.tags()
        self.assertEqual(tags["beg-release/backend:" + self.m0["release_id"]], INITIAL_IMAGES["backend"])
        self.assertEqual(tags["beg-release/backend:" + self.m1["release_id"]], new_backend)
        self.assertEqual(tags["beg-release/frontend:" + self.m1["release_id"]], INITIAL_IMAGES["frontend"])

        rec = self.lay.records()[-1]
        self.assertEqual((rec["status"], rec["smoke"], rec["migrations"]), ("DEPLOYED", "PASS", "NOT_RUN"))
        self.assertEqual((rec["runtime_images"]["backend"], rec["runtime_rollback"]), (new_backend, "NOT_APPLICABLE"))
        self.assertEqual(rec["verifier_image"][:13], "local-python-")
        self.assertEqual(mf.validate_record(rec), [])
        base_images = read_text(os.path.join(rec["evidence_dir"], "base-images.txt"))
        self.assertIn("python:3.11-slim " + VERIFIER_IMAGE_ID, base_images)
        self.assertIn("node:20-alpine absent", base_images)
        self.assertTrue(rec["evidence_dir"].replace("\\", "/").rstrip("/").split("/")[-3:-1] == ["release-state", "history"])
        self.assert_no_secrets(p.stdout, p.stderr)
        compose_log = read_text(os.path.join(rec["evidence_dir"], "compose-deploy.log"))
        self.assertIn("JWT_SECRET=***REDACTED***", compose_log)
        marker = read_text(os.path.join(self.lay.base, "DEPLOYED_VERSION.txt"))
        self.assertIn("deployed=%s\n" % self.c["c1"], marker)
        self.assertIn("release_id=%s\n" % self.m1["release_id"], marker)
        self.assertIn("rollback_dir=%s\n" % anchor, marker)
        self.assertIn("runtime_images=%s\n" % cur["RUNTIME_IMAGES"], marker)

    def test_deploy_without_changed_service_inputs_restarts_nothing(self):
        self._deploy_b1()
        p, b3 = build(self.repo, self.c["c3"], os.path.join(self.tmp, "docs-" + os.path.basename(self.root)),
                      "--previous-manifest", os.path.join(self.b2, "manifest.json"))
        self.assertIsNotNone(b3, p.stderr)
        self.assertEqual(json.loads(p.stdout)["services_to_rebuild"], [])
        self.assertEqual(self.lay.run(self.b2, "release_deploy.sh").returncode, 0)
        calls_before = self.lay.calls()
        p = self.lay.run(b3, "release_deploy.sh")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("no service inputs changed", p.stdout)
        self.assertNotIn("compose", self.lay.calls()[len(calls_before):])
        self.assertEqual(self.lay.state("current.env")["COMMIT"], self.c["c3"])

    def test_docker_verifier_mode_adopt_deploy_rollback(self):
        """Production runs the verifier as `docker run --network none --pull never --read-only` by
        immutable image ID, with bundle, base and hint READ-ONLY and only /evid and /stage writable.
        The fake daemon refuses anything else (including a verifier write outside /evid,/stage)."""
        docker = {"RELEASE_PY_MODE": "docker"}
        p = self.lay.run(self.b0, "release_adopt.sh", **docker)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        p = self.lay.run(self.b1, "release_deploy.sh", **docker)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        ok, detail = tree_matches(os.path.join(self.lay.base, "repo"), self.repo, self.c["c1"])
        self.assertTrue(ok, detail)
        p = self.lay.run(self.b1, "release_rollback.sh", "--yes", **docker)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assert_live_is_c0()
        runs = [l for l in self.lay.calls().splitlines() if l.startswith("docker run")]
        self.assertTrue(runs)
        for line in runs:
            self.assertTrue(line.startswith("docker run --rm --pull never --network none --read-only "
                                            "--security-opt no-new-privileges"), line)
            self.assertIn(":/base:ro ", line)
            self.assertIn(":/bundle:ro ", line)
            self.assertIn(" %s python3 " % VERIFIER_IMAGE_ID, line)
            self.assertNotRegex(line, r":/base (?!:ro)")
        self.assertTrue(any(":/stage " in l for l in runs), "staged extraction must use the narrow /stage mount")
        self.assertTrue(any(":/hint:ro" in l for l in runs), "rollback target tree must be verified with its own artifact")
        records = self.lay.records()
        self.assertEqual([r["status"] for r in records], ["ADOPTED", "DEPLOYED", "ROLLBACK_DONE"])
        self.assertTrue(all(r["verifier_image"] == VERIFIER_IMAGE_ID for r in records))
        self.assert_no_secrets(p.stdout, p.stderr)

    def test_docker_verifier_image_must_exist_and_match_pin(self):
        self.lay.remove_image(VERIFIER_IMAGE_ID)
        p = self.lay.run(self.b0, "release_adopt.sh", RELEASE_PY_MODE="docker")
        self.assertEqual(p.returncode, 3, p.stdout)
        self.assertIn("is not present locally (it is never pulled)", p.stdout)
        self.lay.add_image(VERIFIER_IMAGE_ID)
        p = self.lay.run(self.b0, "release_adopt.sh", RELEASE_PY_MODE="docker", VERIFY_IMAGE_ID="sha256:" + "0" * 64)
        self.assertEqual(p.returncode, 3, p.stdout)
        self.assertIn("pinned VERIFY_IMAGE_ID", p.stdout)
        self.assertIsNone(self.lay.state("current.env"))

    # ----------------------------------------------- precheck: fail closed, no mutation
    def _precheck_must_fail(self, bundle, needle, prepare):
        self.adopt()
        prepare()
        before = self.lay.snapshot()
        calls_before = self.lay.calls()
        p = self.lay.run(bundle, "release_deploy.sh")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("PRECHECK FAILED", p.stdout)
        self.assertIn(needle, p.stdout)
        self.assertIn("NOTHING WAS CHANGED", p.stdout)
        self.assertEqual(self.lay.snapshot(), before, "precheck failure mutated the layout")
        self.assertNotIn("compose", self.lay.calls()[len(calls_before):])
        self.assertEqual(self.lay.state("current.env")["RELEASE_ID"], self.m0["release_id"])
        self.assert_no_secrets(p.stdout, p.stderr)
        return p

    def test_precheck_health_not_200(self):
        self._precheck_must_fail(self.b1, "pre-deploy GET /api/health returned 503",
                                 lambda: self.lay.fake_file("http_codes", "/api/health 503\n"))

    def test_precheck_container_not_running(self):
        self._precheck_must_fail(self.b1, "container begwork-backend is not running",
                                 lambda: self.lay.set_container("begwork-backend", "exited", 0, "2026-01-01T00:00:00Z"))

    def test_precheck_missing_backup(self):
        self._precheck_must_fail(self.b1, "no backup archive",
                                 lambda: shutil.rmtree(os.path.join(self.lay.base, "backups")))

    def test_precheck_layout_file_drift(self):
        def drift():
            with open(os.path.join(self.lay.base, "Dockerfile.backend"), "a", newline="\n") as f:
                f.write("# edited on the NAS\n")
        p = self._precheck_must_fail(self.b1, "bundle/layout verification failed", drift)
        self.assertIn("[FAIL] layout.Dockerfile.backend", p.stdout)

    def test_precheck_required_env_key_missing(self):
        def drop_key():
            path = os.path.join(self.lay.base, ".env")
            lines = [l for l in read_text(path).splitlines() if not l.startswith("JWT_SECRET=")]
            with open(path, "w", newline="\n") as f:
                f.write("\n".join(lines) + "\n")
        p = self._precheck_must_fail(self.b1, "bundle/layout verification failed", drop_key)
        self.assertIn("missing key names: ['JWT_SECRET']", p.stdout)

    def test_precheck_flag_set_to_other_value_in_env(self):
        def enforce():
            with open(os.path.join(self.lay.base, ".env"), "a", newline="\n") as f:
                f.write("PERMISSION_SERVICE_MODE=enforce\n")
        p = self._precheck_must_fail(self.b1, "bundle/layout verification failed", enforce)
        self.assertIn("[FAIL] flag.PERMISSION_SERVICE_MODE", p.stdout)
        self.assertNotIn("enforce", p.stdout)

    def test_precheck_version_mismatch_wrong_previous(self):
        self._precheck_must_fail(self.b2, "version mismatch", lambda: None)

    def test_precheck_tampered_artifact_checksum(self):
        tampered = os.path.join(self.root, "tampered-bundle")
        shutil.copytree(self.b1, tampered)
        with open(os.path.join(tampered, "artifact.tar"), "r+b") as f:
            f.seek(700)
            byte = f.read(1)
            f.seek(700)
            f.write(bytes([byte[0] ^ 0x01]))
        p = self._precheck_must_fail(tampered, "bundle/layout verification failed", lambda: None)
        self.assertIn("[FAIL] sha256sums.match - mismatch: ['artifact.tar']", p.stdout)

    def test_precheck_live_tree_modified_on_nas(self):
        def hotfix():
            with open(os.path.join(self.lay.base, "repo", "backend", "server.py"), "a", newline="\n") as f:
                f.write("# hotfix\n")
        self._precheck_must_fail(self.b1, "does not match recorded tree", hotfix)

    def test_precheck_rollback_anchor_name_taken(self):
        self._precheck_must_fail(self.b1, "rollback anchor name",
                                 lambda: os.makedirs(os.path.join(self.lay.base, "repo.rollback-" + self.m0["release_id"])))

    def test_precheck_runtime_drift_is_refused(self):
        self._precheck_must_fail(self.b1, "runtime drift",
                                 lambda: self.lay.fake_file("cimg_begwork-backend", "sha256:" + "d" * 64))

    def test_precheck_declared_migration_is_refused_and_never_run(self):
        p, bm = build(self.repo, self.c["c1"], os.path.join(self.root, "mig-bundles"),
                      "--previous-manifest", os.path.join(self.b0, "manifest.json"),
                      "--declare-migration", "w0_02_bootstrap_permissions",
                      "--migration-approval", "BEG_Work_AI-1-test")
        self.assertIsNotNone(bm, p.stderr)
        p = self._precheck_must_fail(bm, "bundle/layout verification failed", lambda: None)
        self.assertIn("[FAIL] migrations.not_declared", p.stdout)
        self.assertNotRegex(self.lay.calls().lower(), r"bootstrap|migrat")

    # ------------------------------------------------------- auto-rollback triggers
    def _auto_rollback(self, on_up_1, on_up_2, needle, compose_fail=False):
        self.adopt()
        self.lay.fake_file("on_up_1", on_up_1)
        self.lay.fake_file("on_up_2", on_up_2)
        if compose_fail:
            self.lay.fake_file("compose_fail_1", "")
        p = self.lay.run(self.b1, "release_deploy.sh")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("AUTO-ROLLBACK", p.stdout)
        self.assertIn(needle, p.stdout)
        self.assertIn("ROLLED BACK", p.stdout)
        self.assert_live_is_c0()
        self.assertEqual(self.lay.state("current.env")["RELEASE_ID"], self.m0["release_id"])
        self.assertIsNone(self.lay.state("previous.env"))
        self.assertEqual(read_text(os.path.join(self.lay.base, "DEPLOYED_COMMIT")).strip(), self.c["c0"])
        failed = [d for d in os.listdir(self.lay.base) if d.startswith("repo.failed-" + self.m1["release_id"])]
        self.assertEqual(len(failed), 1, os.listdir(self.lay.base))
        ok, detail = tree_matches(os.path.join(self.lay.base, failed[0]), self.repo, self.c["c1"])
        self.assertTrue(ok, detail)
        self.assertFalse(os.path.exists(os.path.join(self.lay.base, "repo.rollback-" + self.m0["release_id"])))
        # runtime-exact: the recorded image runs again, recreated without a second build
        self.assertEqual(self.lay.compose_ups(), [BUILD_BACKEND, EXACT_BACKEND])
        self.assertLessEqual(len(self.lay.builds()), 1)
        self.assert_runtime(INITIAL_IMAGES["backend"], INITIAL_IMAGES["frontend"])
        self.assertEqual(self.lay.state("current.env")["RUNTIME_IMAGES"], self.initial_runtime)
        self.assertIn("runtime-exact: recorded images restored", p.stdout)
        self.assertNotRegex(self.lay.calls().lower(), r"bootstrap|migrat")
        rec = self.lay.records()[-1]
        self.assertEqual((rec["status"], rec["smoke"], rec["migrations"]), ("ROLLED_BACK", "FAIL", "NOT_RUN"))
        self.assertEqual((rec["runtime_rollback"], rec["runtime_images"]), ("EXACT_IMAGE", INITIAL_IMAGES))
        self.assertEqual(mf.validate_record(rec), [])
        self.assert_no_secrets(p.stdout, p.stderr)
        return p

    def test_auto_rollback_on_compose_startup_failure(self):
        self._auto_rollback("", "", "docker compose up failed", compose_fail=True)

    def test_auto_rollback_on_backend_not_starting(self):
        self._auto_rollback('touch "$FAKE/crash_backend"; echo "/api/health 000" > "$FAKE/http_codes"\n',
                            'rm -f "$FAKE/crash_backend" "$FAKE/http_codes"\n', "did not start")

    def test_auto_rollback_on_health_failure(self):
        self._auto_rollback('echo "/api/health 502" > "$FAKE/http_codes"\n', 'rm -f "$FAKE/http_codes"\n',
                            "health /api/health returned 502")

    def test_auto_rollback_on_restart_loop(self):
        self._auto_rollback('touch "$FAKE/restart_loop_begwork-backend"\n',
                            'rm -f "$FAKE/restart_loop_begwork-backend"\n', "restart loop")

    def test_auto_rollback_on_5xx_endpoint(self):
        self._auto_rollback('echo "/api/roles 500" > "$FAKE/http_codes"\n', 'rm -f "$FAKE/http_codes"\n',
                            "GET /api/roles returned 500")

    def test_auto_rollback_on_startup_config_error_in_log_without_leaking_it(self):
        script = ('printf "Traceback (most recent call last):\\n  bad auth for %s\\n" > "$FAKE/logs_begwork-backend"\n'
                  % SECRET_MONGO_PASSWORD)
        p = self._auto_rollback(script, 'rm -f "$FAKE/logs_begwork-backend"\n', "startup/config errors")
        self.assertIn("content withheld", p.stdout)

    def test_auto_rollback_on_version_mismatch_container_not_recreated(self):
        self._auto_rollback('touch "$FAKE/no_recreate"\n', 'rm -f "$FAKE/no_recreate"\n', "version mismatch")

    def test_auto_rollback_on_flag_mismatch_in_container(self):
        p = self._auto_rollback('printf enforce > "$FAKE/env_begwork-backend_PERMISSION_SERVICE_MODE"\n',
                                'rm -f "$FAKE/env_begwork-backend_PERMISSION_SERVICE_MODE"\n',
                                "flag PERMISSION_SERVICE_MODE")
        self.assertNotIn("enforce", p.stdout)

    def test_auto_rollback_without_the_recorded_image_rebuilds_and_says_it_is_not_runtime_exact(self):
        self.adopt()
        self.lay.fake_file("on_up_1", 'rm -f "$FAKE/images/%s"; echo "/api/health 502" > "$FAKE/http_codes"\n'
                           % INITIAL_IMAGES["backend"].split(":")[1])
        self.lay.fake_file("on_up_2", 'rm -f "$FAKE/http_codes"\n')
        p = self.lay.run(self.b1, "release_deploy.sh")
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("NOT runtime-exact", p.stdout)
        self.assertEqual(self.lay.compose_ups(), [BUILD_BACKEND, BUILD_BACKEND])
        self.assert_live_is_c0()
        rebuilt = self.lay.builds()[-1].split()[-1]
        self.assert_runtime(rebuilt, INITIAL_IMAGES["frontend"])
        self.assertEqual(self.lay.state("current.env")["RUNTIME_IMAGES"],
                         "backend=%s,frontend=%s" % (rebuilt, INITIAL_IMAGES["frontend"]))
        rec = self.lay.records()[-1]
        self.assertEqual((rec["status"], rec["runtime_rollback"]), ("ROLLED_BACK", "SOURCE_REBUILD"))
        self.assertEqual(mf.validate_record(rec), [])

    # ------------------------------------------------------------- standalone rollback
    def _deploy_b1(self):
        self.adopt()
        p = self.lay.run(self.b1, "release_deploy.sh")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_standalone_rollback_uses_recorded_target(self):
        self._deploy_b1()
        before = self.lay.snapshot()
        dry = self.lay.run(self.b1, "release_rollback.sh")
        self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
        self.assertIn("DRY RUN", dry.stdout)
        self.assertEqual(self.lay.snapshot(), before, "dry run must not move anything")

        p = self.lay.run(self.b1, "release_rollback.sh", "--yes")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assert_live_is_c0()
        cur = self.lay.state("current.env")
        self.assertEqual((cur["RELEASE_ID"], cur["COMMIT"], cur["TREE_DIR"]), (self.m0["release_id"], self.c["c0"], "repo"))
        self.assertIsNone(self.lay.state("previous.env"))
        self.assertEqual(read_text(os.path.join(self.lay.base, "DEPLOYED_COMMIT")).strip(), self.c["c0"])
        rolled = [d for d in os.listdir(self.lay.base) if d.startswith("repo.rolledback-" + self.m1["release_id"])]
        self.assertEqual(len(rolled), 1)
        ok, detail = tree_matches(os.path.join(self.lay.base, rolled[0]), self.repo, self.c["c1"])
        self.assertTrue(ok, detail)
        self.assertEqual(self.lay.compose_ups(), [BUILD_BACKEND, EXACT_BACKEND])
        self.assertEqual(len(self.lay.builds()), 1, "rollback must not build")
        self.assert_runtime(INITIAL_IMAGES["backend"], INITIAL_IMAGES["frontend"])
        self.assertEqual(cur["RUNTIME_IMAGES"], self.initial_runtime)
        self.assertIn("runtime plan: exact image restore [backend=%s]" % INITIAL_IMAGES["backend"], dry.stdout)
        self.assertIn("source-exact and runtime-exact", p.stdout)
        rec = self.lay.records()[-1]
        self.assertEqual((rec["action"], rec["status"], rec["release_id"]), ("rollback", "ROLLBACK_DONE", self.m0["release_id"]))
        self.assertEqual((rec["runtime_rollback"], rec["runtime_images"]), ("EXACT_IMAGE", INITIAL_IMAGES))
        self.assertEqual(mf.validate_record(rec), [])
        self.assert_no_secrets(p.stdout, p.stderr, dry.stdout)

    def test_standalone_rollback_without_recorded_image_needs_explicit_source_rebuild(self):
        self._deploy_b1()
        self.lay.remove_image(INITIAL_IMAGES["backend"])
        before = self.lay.snapshot()
        p = self.lay.run(self.b1, "release_rollback.sh", "--yes")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("exact runtime rollback is impossible", p.stdout)
        self.assertEqual(self.lay.snapshot(), before)
        self.assertEqual(self.lay.compose_ups(), [BUILD_BACKEND])

        p = self.lay.run(self.b1, "release_rollback.sh", "--yes", "--allow-source-rebuild")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assert_live_is_c0()
        self.assertEqual(self.lay.compose_ups(), [BUILD_BACKEND, BUILD_BACKEND])
        self.assertIn("NOT runtime-exact", p.stdout)
        rebuilt = self.lay.builds()[-1].split()[-1]
        self.assert_runtime(rebuilt, INITIAL_IMAGES["frontend"])
        rec = self.lay.records()[-1]
        self.assertEqual((rec["status"], rec["runtime_rollback"]), ("ROLLBACK_DONE", "SOURCE_REBUILD"))
        self.assertEqual(mf.validate_record(rec), [])

    def test_standalone_rollback_refuses_runtime_drift(self):
        self._deploy_b1()
        self.lay.fake_file("cimg_begwork-frontend", "sha256:" + "e" * 64)
        before = self.lay.snapshot()
        p = self.lay.run(self.b1, "release_rollback.sh", "--yes")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("runtime drift", p.stdout)
        self.assertEqual(self.lay.snapshot(), before)

    def test_standalone_rollback_refuses_tampered_target(self):
        self._deploy_b1()
        anchor = os.path.join(self.lay.base, "repo.rollback-" + self.m0["release_id"])
        with open(os.path.join(anchor, "backend", "server.py"), "a", newline="\n") as f:
            f.write("# tampered\n")
        before = self.lay.snapshot()
        p = self.lay.run(self.b1, "release_rollback.sh", "--yes")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("missing/tampered", p.stdout)
        self.assertEqual(self.lay.snapshot(), before)

    def test_standalone_rollback_refuses_without_recorded_target(self):
        self.adopt()
        p = self.lay.run(self.b0, "release_rollback.sh", "--yes")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("no rollback target recorded", p.stdout)
        self.assert_live_is_c0()

    def test_second_deploy_retires_older_tree_and_keeps_immediate_target(self):
        self._deploy_b1()
        p = self.lay.run(self.b2, "release_deploy.sh")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        prev = self.lay.state("previous.env")
        self.assertEqual((prev["RELEASE_ID"], prev["TREE_DIR"]), (self.m1["release_id"], "repo.rollback-" + self.m1["release_id"]))
        ok, detail = tree_matches(os.path.join(self.lay.base, prev["TREE_DIR"]), self.repo, self.c["c1"])
        self.assertTrue(ok, detail)
        self.assertFalse(os.path.exists(os.path.join(self.lay.base, "repo.rollback-" + self.m0["release_id"])))
        retired = os.listdir(os.path.join(self.lay.base, "release-state", "retired"))
        self.assertTrue(any(r.startswith("repo.rollback-" + self.m0["release_id"]) for r in retired), retired)
        self.assertEqual(self.lay.compose_ups(), [BUILD_BACKEND, "compose up -d --no-deps --build frontend"])
        backend_1 = self.lay.builds()[0].split()[-1]
        self.assertEqual(prev["RUNTIME_IMAGES"], "backend=%s,frontend=%s" % (backend_1, INITIAL_IMAGES["frontend"]))
        self.assertEqual(self.lay.container_image("begwork-backend"), backend_1, "backend must not be rebuilt")

    # ------------------------------------------------------------------- retention
    def test_retention_never_removes_active_tree_or_rollback_target(self):
        self._deploy_b1()
        base = self.lay.base
        for extra in ("repo.failed-old-1", "repo_before_0123456789abcdef"):
            os.makedirs(os.path.join(base, extra, "x"))
        os.makedirs(os.path.join(base, "release-state", "retired", "repo.rollback-ancient", "x"))
        before = self.lay.snapshot()
        dry = self.lay.run(self.b1, "release_retention.sh", "--keep", "0")
        self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
        self.assertEqual(self.lay.snapshot(), before, "retention dry run removed data")

        p = self.lay.run(self.b1, "release_retention.sh", "--keep", "0", "--apply")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        target = self.lay.state("previous.env")["TREE_DIR"]
        ok, detail = tree_matches(os.path.join(base, "repo"), self.repo, self.c["c1"])
        self.assertTrue(ok, detail)
        ok, detail = tree_matches(os.path.join(base, target), self.repo, self.c["c0"], extras={"nginx.conf": LIVE_NGINX_BLOB})
        self.assertTrue(ok, detail)
        for gone in ("repo.failed-old-1", "repo_before_0123456789abcdef",
                     os.path.join("release-state", "retired", "repo.rollback-ancient")):
            self.assertFalse(os.path.exists(os.path.join(base, gone)), gone)
        self.assertTrue(os.listdir(os.path.join(base, "release-state", "history")))
        self.assertTrue(os.listdir(os.path.join(base, "release-state", "manifests")))
        # the recorded rollback still works after retention
        r = self.lay.run(self.b1, "release_rollback.sh")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_retention_of_release_image_tags_keeps_current_and_previous(self):
        self._deploy_b1()
        self.assertEqual(self.lay.run(self.b2, "release_deploy.sh").returncode, 0)
        ids = {m["release_id"] for m in (self.m0, self.m1, self.m2)}
        self.assertEqual({t.split(":", 1)[1] for t in self.lay.tags() if t.startswith("beg-release/")}, ids)
        tags_before = self.lay.tags()
        default = self.lay.run(self.b2, "release_retention.sh", "--keep", "0", "--apply")
        self.assertEqual(default.returncode, 0, default.stdout)
        self.assertEqual(self.lay.tags(), tags_before, "image tags are only touched with --images")
        dry = self.lay.run(self.b2, "release_retention.sh", "--images")
        self.assertIn("untag  : image tag beg-release/backend:" + self.m0["release_id"], dry.stdout)
        self.assertEqual(self.lay.tags(), tags_before)
        p = self.lay.run(self.b2, "release_retention.sh", "--images", "--apply")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        left = {t.split(":", 1)[1] for t in self.lay.tags() if t.startswith("beg-release/")}
        self.assertEqual(left, {self.m1["release_id"], self.m2["release_id"]})
        self.assertNotRegex(self.lay.calls(), r"docker rmi -|prune")
        r = self.lay.run(self.b2, "release_rollback.sh")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("exact image restore [frontend=", r.stdout)


if __name__ == "__main__":
    unittest.main()
