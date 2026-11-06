#!/usr/bin/env python3
"""ST-02 — isolated staging stack from an exact release bundle + deploy/rollback rehearsal.

Package: docs/architecture/tasks/ST-02_ISOLATED_STAGING_STACK.md (approved by Krum, R9,
06.11.2026). Source: PR #64 02-release-gates.md steps 5-6 and "Exercise W0-09A deploy ->
smoke -> exact-image rollback in isolated staging".

    python3 ops/staging/staging_up.py up       --base <dir> [--commit origin/main] [options]
    python3 ops/staging/staging_up.py deploy   --base <dir> --commit <ref> [--force-smoke-fail]
    python3 ops/staging/staging_up.py rehearse --base <dir> --from <X> --to <X+1> --evidence <dir>
    python3 ops/staging/staging_up.py down     --base <dir> [--volumes]

``up``       builds a bundle from the exact commit with ops/release/release_build.py
             (environment=staging), verifies it with release_verify.py, prepares an own layout
             root, starts an own MongoDB replica set, deploys with staging_deploy.sh (the
             release's lib.sh: verifier, smoke, runtime images), checks /api/version and the UI
             bundle against the bundle commit, seeds the ST-01 tenants A/B and runs the ST-01
             API scenarios.
``deploy``   next release on a running stack (previous = recorded current manifest).
``rehearse`` up(X) -> seed + scenarios -> deploy(X+1) with a CONTROLLED smoke failure ->
             automatic rollback to the exact image IDs of X with the synthetic data kept ->
             deploy(X+1) without the failure -> scenarios again. Writes summary.json with every
             assertion and copies the evidence (manifests, SHA256SUMS, records, logs).
``down``     stops the staging project only (``--volumes`` also drops its MongoDB volume).

Safety: refuses /volume1/docker/begwork (production) and any non-``begwork-staging`` project;
refuses busy ports; writes only synthetic values (random JWT secret and seed password stay in
the layout root, mode 600, never in evidence or Git); no SMTP/Stripe/LLM keys; never touches
production containers, images, layout.json or flags. Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
RELEASE_BUILD = REPO / "ops" / "release" / "release_build.py"
RELEASE_VERIFY = REPO / "ops" / "release" / "release_verify.py"
OVERLAY = HERE / "deploy" / "docker-compose.staging.yml"
DEPLOY_SH = HERE / "staging_deploy.sh"
PRODUCTION_BASE = "/volume1/docker/begwork"
LAYOUT_DIR = "ops/synology/deploy"
LAYOUT_FILES = ("docker-compose.yml", "Dockerfile.backend", "Dockerfile.frontend")
DB_NAME = "st02_staging"
SYSTEM_DB = "st02_staging_system"
DEPLOYMENT_ID = "staging-begwork"
MODES = ("off", "shadow", "enforce")
APPROVAL = "validation:ST-02-R9-2026-11-06"
FORCED_PATH = "/api/st02-forced-smoke-failure"
MARKER = ".st02-staging-root"


class Refused(Exception):
    pass


def log(msg):
    print("[%s] %s" % (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), msg), flush=True)


def utc_stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------- guards
def check_base(base: Path):
    b = os.path.abspath(str(base)).rstrip("/")
    if b == PRODUCTION_BASE or b.startswith(PRODUCTION_BASE + "/"):
        raise Refused("the staging layout root may never be %s (production)" % PRODUCTION_BASE)
    if b in ("", "/") or b == os.path.abspath(str(REPO)) or b.startswith(os.path.abspath(str(REPO)) + "/"):
        raise Refused("the staging layout root must be outside the Git work tree and not /")
    return Path(b)


def check_project(project):
    if not re.match(r"^begwork-staging[a-z0-9-]*$", project):
        raise Refused("--project must start with begwork-staging (got %r)" % project)
    return project


def port_free(port, host="127.0.0.1"):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def check_port(port):
    if port == 8080:
        raise Refused("port 8080 is the production port; choose another --port")
    if not 1024 <= port <= 65535:
        raise Refused("--port must be 1024..65535")
    if not port_free(port):
        raise Refused("port %d on 127.0.0.1 is in use; choose another --port" % port)
    published = run(["docker", "ps", "--format", "{{.Ports}}"], check=False).stdout
    if re.search(r":%d->" % port, published):
        raise Refused("port %d is published by another container" % port)


def run(cmd, check=True, env=None, cwd=None, capture=True, input_bytes=None):
    r = subprocess.run(cmd, cwd=cwd, env=env, input=input_bytes,
                       stdout=subprocess.PIPE if capture else None, stderr=subprocess.STDOUT if capture else None)
    out = r.stdout.decode("utf-8", "replace") if capture and r.stdout is not None else ""
    res = subprocess.CompletedProcess(cmd, r.returncode, out, "")
    if check and r.returncode != 0:
        raise Refused("command failed (%d): %s\n%s" % (r.returncode, " ".join(map(str, cmd[:6])), out[-3000:]))
    return res


# ---------------------------------------------------------------- layout root
def read_kv(path: Path):
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            k, _, v = line.partition("=")
            out[k] = v
    return out


def write_private(path: Path, text):
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.chmod(str(path), 0o600)


def prepare_base(base: Path, project, port, mode, restart_sample=None):
    """Create (or re-check) the staging layout root. Synthetic values only."""
    base = check_base(base)
    if (base / MARKER).exists():
        st = read_kv(base / "staging.env")
        if st.get("ST02_PROJECT") != project or st.get("ST02_HTTP_PORT") != str(port) \
                or st.get("ST02_PERMISSION_SERVICE_MODE") != mode:
            raise Refused("%s already holds staging stack %s on port %s mode %s; use the same parameters or a new --base"
                          % (base, st.get("ST02_PROJECT"), st.get("ST02_HTTP_PORT"), st.get("ST02_PERMISSION_SERVICE_MODE")))
        return base, False
    if base.exists() and any(base.iterdir()):
        raise Refused("%s exists and is not an ST-02 staging root" % base)
    check_port(port)
    base.mkdir(parents=True, exist_ok=True)
    for d in ("releases", "backups", "uploads", "evidence"):
        (base / d).mkdir(exist_ok=True)
    url = "http://127.0.0.1:%d" % port
    st = {"ST02_PROJECT": project, "ST02_HTTP_PORT": str(port), "ST02_PERMISSION_SERVICE_MODE": mode}
    if restart_sample is not None:
        st["ST02_RESTART_SAMPLE_SEC"] = str(int(restart_sample))
    (base / "staging.env").write_text("".join("%s=%s\n" % kv for kv in sorted(st.items())), encoding="utf-8")
    env = {
        "MONGO_URL": "mongodb://mongo:27017/?replicaSet=rs0",
        "DB_NAME": DB_NAME,
        "BEG_SYSTEM_DB": SYSTEM_DB,
        "PUBLIC_URL": url,
        "CORS_ORIGINS": url,
        "JWT_SECRET": secrets.token_urlsafe(48),
    }
    env.update(st)
    write_private(base / ".env", "# ST-02 synthetic staging values (never production; no SMTP/Stripe/LLM keys)\n"
                  + "".join("%s=%s\n" % kv for kv in env.items()))
    write_private(base / ".st02-seed.env", "ST01_SEED_PASSWORD=%s\n" % secrets.token_urlsafe(18))
    shutil.copyfile(str(OVERLAY), str(base / "docker-compose.staging.yml"))
    (base / MARKER).write_text("ST-02 isolated staging layout root; project %s\ncreated %s\n" % (project, utc_stamp()),
                               encoding="utf-8")
    log("staging layout root %s prepared (project %s, port %d, PERMISSION_SERVICE_MODE=%s)" % (base, project, port, mode))
    return base, True


def install_layout_files(base: Path, bundle: Path):
    """Byte-identical production layout files of this release (from its artifact)."""
    with tarfile.open(str(bundle / "artifact.tar")) as tar:
        for name in LAYOUT_FILES:
            data = tar.extractfile(LAYOUT_DIR + "/" + name).read()
            target = base / name
            if not target.exists() or target.read_bytes() != data:
                target.write_bytes(data)
    man = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    for name, digest in man["release"]["configuration"]["layout_files"].items():
        if hashlib.sha256((base / name).read_bytes()).hexdigest() != digest:
            raise Refused("layout file %s differs from the manifest" % name)


def compose(base: Path, project, *args, check=True):
    return run(["docker", "compose", "-p", project, "-f", "docker-compose.yml", "-f", "docker-compose.staging.yml",
                *args], cwd=str(base), check=check)


def _isolation_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("st02_isolation_check_gate", str(HERE / "isolation_check.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def assert_isolated(base: Path, project):
    """ST-02-C01: the merged compose model passes isolation_check BEFORE any container starts.

    Raises Refused (nothing started) with the check's reasons; never prints an env value."""
    st = read_kv(base / "staging.env")
    r = subprocess.run(["docker", "compose", "-p", project, "-f", "docker-compose.yml", "-f", "docker-compose.staging.yml",
                        "config", "--format", "json"], cwd=str(base), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                       universal_newlines=True)  # stderr dropped: it may echo .env lines
    if r.returncode != 0:
        raise Refused("docker compose config failed for %s; nothing was started" % base)
    try:
        model = json.loads(r.stdout)
    except ValueError:
        raise Refused("docker compose config output is not JSON; nothing was started")
    errors = _isolation_module().check(model, project, st.get("ST02_HTTP_PORT", ""), st.get("ST02_PERMISSION_SERVICE_MODE", ""),
                                       base=str(base), allowed_mongo_hosts=st.get("ST02_ALLOWED_MONGO_HOSTS", ""))
    if errors:
        raise Refused("ISOLATION FAIL, nothing was started:\n  " + "\n  ".join(errors))
    log("isolation of the merged compose model: ISOLATION PASS (before any container starts)")


def mongo_up(base: Path, project):
    assert_isolated(base, project)
    compose(base, project, "up", "-d", "--no-deps", "mongo")
    c = project + "-mongo"
    for _ in range(60):
        if run(["docker", "exec", c, "mongosh", "--quiet", "--eval", "db.adminCommand({ping:1}).ok"], check=False).stdout.strip() == "1":
            break
        time.sleep(2)
    else:
        raise Refused("staging MongoDB did not answer")
    st = run(["docker", "exec", c, "mongosh", "--quiet", "--eval",
              "try { rs.status().ok } catch (e) { 'NOINIT' }"], check=False).stdout.strip()
    if st != "1":
        run(["docker", "exec", c, "mongosh", "--quiet", "--eval",
             'rs.initiate({_id:"rs0",members:[{_id:0,host:"mongo:27017"}]}).ok'])
    for _ in range(60):
        if run(["docker", "exec", c, "mongosh", "--quiet", "--eval", "db.hello().isWritablePrimary"], check=False).stdout.strip() == "true":
            log("staging MongoDB replica set rs0 primary is %s (volume %s_mongo_data, not published)" % (c, project))
            return
        time.sleep(2)
    raise Refused("staging MongoDB replica set has no primary")


# ---------------------------------------------------------------- release bundle
def build_bundle(base: Path, commit, reachable_from, previous: Path | None, allow_unmerged=False):
    cmd = [sys.executable, str(RELEASE_BUILD), "--repo", str(REPO), "--commit", commit, "--environment", "staging",
           "--deployment-id", DEPLOYMENT_ID, "--out", str(base / "releases"), "--approval", APPROVAL,
           "--reachable-from", reachable_from]
    if allow_unmerged:
        cmd.append("--allow-unmerged")
    cmd += ["--previous-manifest", str(previous)] if previous else ["--no-previous"]
    out = run(cmd).stdout
    summary = json.loads(out[out.index("{"):])
    bundle = Path(summary["bundle"])
    ver = run([sys.executable, str(RELEASE_VERIFY), "bundle", "--bundle", str(bundle)], check=False)
    if ver.returncode != 0 or "RESULT PASS" not in ver.stdout:
        raise Refused("release_verify.py bundle failed for %s:\n%s" % (bundle, ver.stdout[-2000:]))
    log("bundle %s commit %s tree %s verified (release_sha256 %s)" % (
        summary["release_id"], summary["commit"], summary["tree"], summary["release_sha256"]))
    summary["verify_stdout"] = ver.stdout
    return bundle, summary


def staging_deploy(base: Path, bundle: Path, mode, force_fail=False, verify_image=None):
    env = dict(os.environ, BEGWORK_BASE=str(base), REQUIRE_BACKUP="1")
    if verify_image:
        env["VERIFY_IMAGE"] = verify_image
    cmd = ["bash", str(DEPLOY_SH), "--bundle", str(bundle), "--" + mode] + (["--force-smoke-fail"] if force_fail else [])
    log("staging_deploy.sh --%s%s %s" % (mode, " --force-smoke-fail" if force_fail else "", bundle.name))
    r = subprocess.run(cmd, env=env)
    hist = sorted((base / "release-state" / "history").glob("*-deploy-*"), key=lambda p: p.stat().st_mtime)
    return r.returncode, hist[-1] if hist else None


def state(base: Path, name="current.env"):
    p = base / "release-state" / name
    return read_kv(p) if p.exists() else {}


def http_json(url, timeout=10):
    with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def http_text(url, timeout=10):
    with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", "replace")


def identity(port, commit):
    """/api/version must be the bundle commit; the served UI bundle must embed the same SHA."""
    base = "http://127.0.0.1:%d" % port
    status, ver = http_json(base + "/api/version")
    _, html = http_text(base + "/")
    scripts = re.findall(r'src="(/static/js/[^"]+\.js)"', html)
    ui_has_sha = False
    for s in scripts:
        _, js = http_text(base + s, timeout=30)
        if commit in js:
            ui_has_sha = True
            break
    return {"api_status": status, "api_version": ver, "api_build_sha_equals_bundle": ver.get("build_sha") == commit,
            "environment_label_is_staging": ver.get("environment_label") == "staging",
            "ui_scripts": scripts, "ui_bundle_embeds_bundle_sha": ui_has_sha, "bundle_commit": commit}


def data_snapshot(project):
    """Per-collection document counts of the staging databases (synthetic data only)."""
    js = ("const out={};for (const d of ['%s','%s']) {const x=db.getSiblingDB(d);out[d]={};"
          "for (const c of x.getCollectionNames().sort()) {out[d][c]=x.getCollection(c).countDocuments({});}}"
          "print(JSON.stringify(out));" % (DB_NAME, SYSTEM_DB))
    out = run(["docker", "exec", project + "-mongo", "mongosh", "--quiet", "--eval", js]).stdout.strip().splitlines()[-1]
    return json.loads(out)


def tool_container(base: Path, project, image_id, script_args, evid: Path):
    """Run an ST-01 script inside the deployed backend image on the staging network."""
    cmd = ["docker", "run", "--rm", "--pull", "never", "--network", project + "_net",
           "--env-file", str(base / ".st02-seed.env"), "-e", "PYTHONPATH=/app", "-e", "PYTHONDONTWRITEBYTECODE=1",
           "-v", "%s:/st:ro" % HERE, "-v", "%s:/evid" % evid, "-w", "/app", image_id, "python"] + script_args
    return subprocess.run(cmd).returncode


def backend_image(base: Path):
    imgs = dict(item.split("=", 1) for item in state(base)["RUNTIME_IMAGES"].split(","))
    return imgs["backend"]


def seed(base: Path, project, evid: Path):
    rc = tool_container(base, project, backend_image(base), [
        "/st/seed_synthetic.py", "--mongo-url", "mongodb://mongo:27017/?replicaSet=rs0", "--allow-remote",
        "--db", DB_NAME, "--system-db", SYSTEM_DB, "--confirm-db", DB_NAME, "--out", "/evid/seed_report.json"], evid)
    log("seed_synthetic.py exit %d" % rc)
    return rc


def scenarios(base: Path, project, evid: Path, name):
    rc = tool_container(base, project, backend_image(base), [
        "/st/run_scenarios.py", "--base-url", "http://frontend", "--allow-remote", "--out", "/evid/%s" % name], evid)
    log("run_scenarios.py exit %d -> %s" % (rc, name))
    return rc


def scenario_counts(path: Path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    steps = {"pass": 0, "fail": 0, "blocked": 0}
    sc = {"pass": 0, "fail": 0, "blocked": 0}
    for s in doc.get("scenarios", []):
        sc[s.get("status", "blocked")] = sc.get(s.get("status", "blocked"), 0) + 1
        for st in s.get("steps", []):
            steps[st.get("status", "blocked")] = steps.get(st.get("status", "blocked"), 0) + 1
    return {"scenarios": sc, "steps": steps, "outcome": doc.get("outcome")}


# ---------------------------------------------------------------- evidence
def copy_bundle_evidence(bundle: Path, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("manifest.json", "SHA256SUMS", "build_info.json"):
        shutil.copyfile(str(bundle / name), str(dest / name))


def copy_history(hist: Path, dest: Path):
    if hist and hist.exists():
        shutil.copytree(str(hist), str(dest / hist.name), dirs_exist_ok=True)


def secret_scan(base: Path, evid: Path):
    secrets_ = [v for k, v in read_kv(base / ".env").items() if k == "JWT_SECRET"]
    secrets_ += list(read_kv(base / ".st02-seed.env").values())
    hits = []
    for p in evid.rglob("*"):
        if p.is_file():
            data = p.read_bytes()
            for s in secrets_:
                if s and s.encode() in data:
                    hits.append(str(p.relative_to(evid)))
    return {"scanned_files": sum(1 for p in evid.rglob("*") if p.is_file()), "secret_values_checked": len(secrets_),
            "hits": sorted(set(hits))}


def record_of(hist: Path):
    p = hist / "record.json" if hist else None
    return json.loads(p.read_text(encoding="utf-8")) if p and p.exists() else None


def validate_record(path: Path):
    r = run([sys.executable, str(RELEASE_VERIFY), "record", "--record", str(path)], check=False)
    return r.returncode == 0 and "record VALID" in r.stdout


# ---------------------------------------------------------------- commands
def cmd_up(a):
    base, _ = prepare_base(Path(a.base), check_project(a.project), a.port, a.permission_mode, a.restart_sample)
    evid = Path(a.evidence or (base / "evidence" / ("up-" + utc_stamp())))
    evid.mkdir(parents=True, exist_ok=True)
    if state(base):
        raise Refused("a release is already deployed on %s; use `deploy`" % base)
    bundle, summary = build_bundle(base, a.commit, a.reachable_from, None, a.allow_unmerged)
    install_layout_files(base, bundle)
    mongo_up(base, a.project)
    rc, hist = staging_deploy(base, bundle, "initial", verify_image=a.verify_image)
    copy_bundle_evidence(bundle, evid / ("bundle-" + summary["release_id"]))
    copy_history(hist, evid / "history")
    if rc != 0:
        raise Refused("initial staging deploy failed (exit %d); see %s" % (rc, hist))
    ident = identity(a.port, summary["commit"])
    (evid / "identity.json").write_text(json.dumps(ident, indent=2) + "\n", encoding="utf-8")
    log("/api/version build_sha=%s (bundle %s) env=%s" % (ident["api_version"].get("build_sha"), summary["commit"],
                                                          ident["api_version"].get("environment_label")))
    seed_rc = seed(base, a.project, evid)
    sc_rc = scenarios(base, a.project, evid, "scenarios.json") if seed_rc == 0 else None
    ok = ident["api_build_sha_equals_bundle"] and ident["environment_label_is_staging"] and seed_rc == 0
    log("staging up %s: %s on http://127.0.0.1:%d" % ("OK" if ok else "INCOMPLETE", summary["release_id"], a.port))
    return 0 if ok and sc_rc in (0, 1) else 1


def cmd_deploy(a):
    base, _ = prepare_base(Path(a.base), check_project(a.project), a.port, a.permission_mode, a.restart_sample)
    if not state(base):
        raise Refused("no release deployed on %s; use `up`" % base)
    bundle, _ = build_bundle(base, a.commit, a.reachable_from, base / "release-state" / "current.json", a.allow_unmerged)
    install_layout_files(base, bundle)
    assert_isolated(base, a.project)
    rc, hist = staging_deploy(base, bundle, "deploy", force_fail=a.force_smoke_fail, verify_image=a.verify_image)
    log("staging deploy exit %d (record %s)" % (rc, hist / "record.json" if hist else None))
    return rc


def cmd_down(a):
    base = check_base(Path(a.base))
    if not (base / MARKER).exists():
        raise Refused("%s is not an ST-02 staging root" % base)
    project = check_project(read_kv(base / "staging.env")["ST02_PROJECT"])
    compose(base, project, "down", *(["--volumes"] if a.volumes else []))
    log("staging project %s stopped%s" % (project, " and its MongoDB volume dropped" if a.volumes else ""))
    return 0


def cmd_rehearse(a):
    project = check_project(a.project)
    base, _ = prepare_base(Path(a.base), project, a.port, a.permission_mode, a.restart_sample)
    if state(base):
        raise Refused("rehearse needs a fresh --base (a release is already deployed there)")
    evid = Path(a.evidence).resolve()
    evid.mkdir(parents=True, exist_ok=True)
    if a.sandbox_base_report:
        shutil.copyfile(a.sandbox_base_report, str(evid / "sandbox-base-images.txt"))
    checks = []
    runtime = {}

    def check(name, ok, detail=""):
        checks.append({"check": name, "result": "PASS" if ok else "FAIL", "detail": detail})
        log("%s %s %s" % ("PASS" if ok else "FAIL", name, detail))
        return ok

    commit_x = run(["git", "-C", str(REPO), "rev-parse", "--verify", a.from_ref + "^{commit}"]).stdout.strip()
    commit_y = run(["git", "-C", str(REPO), "rev-parse", "--verify", a.to_ref + "^{commit}"]).stdout.strip()
    check("X+1 is a descendant of X", run(["git", "-C", str(REPO), "merge-base", "--is-ancestor", commit_x, commit_y],
                                         check=False).returncode == 0, "%s -> %s" % (commit_x, commit_y))

    # --- 1. X: build, verify, initial deploy, identity, seed, scenarios
    bx, sx = build_bundle(base, commit_x, a.reachable_from, None, a.allow_unmerged)
    install_layout_files(base, bx)
    mongo_up(base, project)
    rc, hist = staging_deploy(base, bx, "initial", verify_image=a.verify_image)
    copy_bundle_evidence(bx, evid / "1-X" / "bundle")
    (evid / "1-X" / "bundle" / "release_verify.txt").write_text(sx["verify_stdout"], encoding="utf-8")
    copy_history(hist, evid / "1-X")
    if not check("X initial deploy exit 0 (DEPLOYED)", rc == 0 and (record_of(hist) or {}).get("status") == "DEPLOYED",
                 "exit %d" % rc):
        return finish(evid, base, checks, {"X": sx}, runtime=runtime)
    images_x = state(base)["RUNTIME_IMAGES"]
    runtime["X"] = images_x
    check("X record is a valid beg.deployment-record/v1", validate_record(hist / "record.json"))
    ident_x = identity(a.port, commit_x)
    (evid / "1-X" / "identity.json").write_text(json.dumps(ident_x, indent=2) + "\n", encoding="utf-8")
    check("X /api/version build_sha == bundle commit", ident_x["api_build_sha_equals_bundle"], ident_x["api_version"].get("build_sha", ""))
    check("X environment_label == staging", ident_x["environment_label_is_staging"])
    check("X UI bundle embeds the bundle SHA", ident_x["ui_bundle_embeds_bundle_sha"])
    check("ST-01 seed of tenants A/B exit 0", seed(base, project, evid / "1-X") == 0)
    sc1 = scenarios(base, project, evid / "1-X", "scenarios.json")
    check("ST-01 scenarios ran with evidence (exit 0 or 1, not 2/3)", sc1 in (0, 1), "exit %s" % sc1)
    snap_x = data_snapshot(project)
    (evid / "1-X" / "data_snapshot.json").write_text(json.dumps(snap_x, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    mongo_id = run(["docker", "inspect", "-f", "{{.Id}}", project + "-mongo"]).stdout.strip()

    # --- 2. X+1 with a controlled smoke failure -> automatic exact-image rollback
    by, sy = build_bundle(base, commit_y, a.reachable_from, base / "release-state" / "current.json", a.allow_unmerged)
    install_layout_files(base, by)
    copy_bundle_evidence(by, evid / "2-X+1-forced-failure" / "bundle")
    (evid / "2-X+1-forced-failure" / "bundle" / "release_verify.txt").write_text(sy["verify_stdout"], encoding="utf-8")
    rc, hist = staging_deploy(base, by, "deploy", force_fail=True, verify_image=a.verify_image)
    copy_history(hist, evid / "2-X+1-forced-failure")
    rec = record_of(hist) or {}
    check("X+1 forced-failure deploy exit 1 (auto rollback)", rc == 1, "exit %d" % rc)
    check("record ROLLED_BACK with runtime_rollback EXACT_IMAGE",
          rec.get("status") == "ROLLED_BACK" and rec.get("runtime_rollback") == "EXACT_IMAGE",
          "%s / %s" % (rec.get("status"), rec.get("runtime_rollback")))
    check("rollback record is a valid beg.deployment-record/v1", validate_record(hist / "record.json"))
    check("rollback reason is the controlled smoke failure", FORCED_PATH in rec.get("failure", ""), rec.get("failure", ""))
    log_text = (hist / "deploy.log").read_text(encoding="utf-8", errors="replace")
    built = re.findall(r"compose up -d --no-deps --build ([a-z, ]+) -> exit 0", log_text)
    check("X+1 images were really built and started before the failure", bool(built), "; ".join(built))
    frt = hist / "failed-release-runtime.txt"
    failed = read_kv(frt) if frt.exists() else {}
    check("the failed attempt really served X+1 (/api/version during the failed smoke)",
          failed.get("served_build_sha") == commit_y, failed.get("served_build_sha", "unreadable"))
    check("the failed attempt ran image IDs different from X", bool(failed.get("runtime_images"))
          and failed.get("runtime_images") != images_x, failed.get("runtime_images", ""))
    runtime["X+1 failed attempt (rolled back)"] = failed.get("runtime_images")
    cur = state(base)
    check("current release is still X", cur.get("COMMIT") == commit_x, cur.get("RELEASE_ID", ""))
    running = ",".join("%s=%s" % (svc, run(["docker", "inspect", "-f", "{{.Image}}", "%s-%s" % (project, svc)]).stdout.strip())
                       for svc in ("backend", "frontend"))
    runtime["after rollback"] = running
    check("running image IDs == recorded image IDs of X", running == images_x, running)
    ident_rb = identity(a.port, commit_x)
    (evid / "2-X+1-forced-failure" / "identity_after_rollback.json").write_text(json.dumps(ident_rb, indent=2) + "\n", encoding="utf-8")
    check("after rollback /api/version == X", ident_rb["api_build_sha_equals_bundle"], ident_rb["api_version"].get("build_sha", ""))
    snap_rb = data_snapshot(project)
    (evid / "2-X+1-forced-failure" / "data_snapshot_after_rollback.json").write_text(
        json.dumps(snap_rb, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    check("synthetic data kept (per-collection counts equal)", snap_rb == snap_x)
    check("MongoDB container not recreated", run(["docker", "inspect", "-f", "{{.Id}}", project + "-mongo"]).stdout.strip() == mongo_id)

    # --- 3. X+1 without the failure
    rc, hist = staging_deploy(base, by, "deploy", verify_image=a.verify_image)
    copy_history(hist, evid / "3-X+1-deploy")
    rec = record_of(hist) or {}
    check("X+1 deploy exit 0 (DEPLOYED)", rc == 0 and rec.get("status") == "DEPLOYED", "exit %d" % rc)
    if rc == 0:
        check("X+1 record is a valid beg.deployment-record/v1", validate_record(hist / "record.json"))
        images_y = state(base)["RUNTIME_IMAGES"]
        runtime["X+1"] = images_y
        check("X+1 runtime image IDs differ from X", images_y != images_x, images_y)
        prev = state(base, "previous.env")
        check("rollback target recorded = X with its image IDs", prev.get("COMMIT") == commit_x and prev.get("RUNTIME_IMAGES") == images_x)
        ident_y = identity(a.port, commit_y)
        (evid / "3-X+1-deploy" / "identity.json").write_text(json.dumps(ident_y, indent=2) + "\n", encoding="utf-8")
        check("X+1 /api/version build_sha == bundle commit", ident_y["api_build_sha_equals_bundle"], ident_y["api_version"].get("build_sha", ""))
        check("X+1 UI bundle embeds the bundle SHA", ident_y["ui_bundle_embeds_bundle_sha"])
        snap_y = data_snapshot(project)
        check("synthetic data kept across X -> X+1", snap_y == snap_x)
        sc2 = scenarios(base, project, evid / "3-X+1-deploy", "scenarios.json")
        check("ST-01 scenarios on X+1 ran with evidence (exit 0 or 1)", sc2 in (0, 1), "exit %s" % sc2)
    return finish(evid, base, checks, {"X": sx, "X+1": sy}, project=project, port=a.port, runtime=runtime)


def finish(evid: Path, base: Path, checks, bundles, project=None, port=None, runtime=None):
    scan = secret_scan(base, evid)
    checks.append({"check": "no secret value (JWT secret, seed password) in evidence",
                   "result": "PASS" if not scan["hits"] else "FAIL", "detail": scan})
    sc = {}
    for p in sorted(evid.rglob("scenarios.json")):
        sc[str(p.relative_to(evid))] = scenario_counts(p)
    summary = {
        "schema": "beg.st02-rehearsal/v1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project": project, "url": "http://127.0.0.1:%s" % port if port else None,
        "staging_root": str(base),
        "staging_parameters": read_kv(base / "staging.env"),
        "bundles": {k: {kk: v[kk] for kk in ("release_id", "release_sha256", "commit", "tree", "artifact_sha256",
                                              "files", "services_to_rebuild", "previous")} for k, v in bundles.items()},
        "scenario_results": sc,
        "runtime_images": runtime or {},
        "checks": checks,
        "result": "PASS" if all(c["result"] == "PASS" for c in checks) else "FAIL",
    }
    (evid / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log("rehearsal %s: %d/%d checks passed -> %s" % (summary["result"], sum(c["result"] == "PASS" for c in checks),
                                                     len(checks), evid / "summary.json"))
    return 0 if summary["result"] == "PASS" else 1


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--base", required=True, help="own staging layout root (never %s)" % PRODUCTION_BASE)
        sp.add_argument("--project", default="begwork-staging")
        sp.add_argument("--port", type=int, default=18080, help="127.0.0.1 port of the staging frontend (checked free)")
        sp.add_argument("--permission-mode", choices=MODES, default="enforce",
                        help="PERMISSION_SERVICE_MODE of the staging backend (default enforce; production is not touched)")
        sp.add_argument("--reachable-from", default="origin/main")
        sp.add_argument("--allow-unmerged", action="store_true", help="staging only: commit need not be on --reachable-from")
        sp.add_argument("--verify-image", default=None, help="verifier image (default: lib.sh VERIFY_IMAGE)")
        sp.add_argument("--restart-sample", type=int, default=None, help="smoke restart-loop sample seconds (default: manifest)")

    up = sub.add_parser("up"); common(up)
    up.add_argument("--commit", default="origin/main"); up.add_argument("--evidence")
    dp = sub.add_parser("deploy"); common(dp)
    dp.add_argument("--commit", required=True); dp.add_argument("--force-smoke-fail", action="store_true")
    rh = sub.add_parser("rehearse"); common(rh)
    rh.add_argument("--from", dest="from_ref", required=True); rh.add_argument("--to", dest="to_ref", required=True)
    rh.add_argument("--evidence", required=True)
    rh.add_argument("--sandbox-base-report", help="report of sandbox-base/prepare_sandbox_base_images.sh (cloud container only)")
    dn = sub.add_parser("down"); dn.add_argument("--base", required=True); dn.add_argument("--volumes", action="store_true")
    a = p.parse_args(argv)
    try:
        return {"up": cmd_up, "deploy": cmd_deploy, "rehearse": cmd_rehearse, "down": cmd_down}[a.cmd](a)
    except Refused as exc:
        print("ST-02 REFUSED: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
