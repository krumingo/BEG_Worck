#!/usr/bin/env python3
"""Build the W0-09A isolated Synology validation package for one committed version.

    python ops/release/tests/synology/make_package.py --out <dir> [--commit HEAD] [--allow-dirty]

The package holds everything run_isolated.sh needs on the NAS (no git, no network):
  COMMIT, expected.env, SHA256SUMS
  bundles/{b0,b1,b2,bmig}      synthetic repo on the REAL layout files, tools = blobs of COMMIT
  bundles/{rt0,rt1,rtcrash}    tiny runtime layout (own container names) for the real-Docker proof
  layout/, rt-layout/          layout root files for the temporary BEGWORK_BASE directories
  runner/                      run_isolated.sh + fakes (docker, docker-compose, curl), from COMMIT
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import harness  # noqa: E402
from harness import LIVE_NGINX_BLOB, REPO_ROOT, SECRET_JWT, SECRET_MONGO_PASSWORD, build, make_repo, run_git  # noqa: E402

RT_LAYOUT = {
    "layout": "synology-compose-repo-copy-v1",
    "deployment_id": "w009a-rt",
    "description": "W0-09A isolated runtime-rollback proof: same compose shape as production, own container names.",
    "versioned_layout_dir": "ops/synology/deploy",
    "layout_files": ["docker-compose.yml", "Dockerfile.backend", "Dockerfile.frontend"],
    "source_dir": "repo",
    "services": {
        "backend": {"container": "w009a-rt-backend", "context": "./repo", "dockerfile": "../Dockerfile.backend",
                    "build_args": {}},
        "frontend": {"container": "w009a-rt-frontend", "context": "./repo", "dockerfile": "../Dockerfile.frontend",
                     "build_args": {"REACT_APP_BACKEND_URL": "${PUBLIC_URL}"}},
    },
    "required_env_keys": ["PUBLIC_URL", "JWT_SECRET"],
    "feature_flags": {"PERMISSION_SERVICE_MODE": "off"},
    "smoke": {"base_url": "http://127.0.0.1:18080", "health_path": "/api/health", "http_paths": ["/api/health", "/"],
              "health_timeout_sec": 30, "restart_sample_sec": 15, "log_service": "backend"},
}

RT_COMPOSE = """services:
  backend:
    build:
      context: ./repo
      dockerfile: ../Dockerfile.backend
    container_name: w009a-rt-backend
    restart: unless-stopped
    env_file:
      - ./.env
    labels:
      - begwork.w009a.isolated=1

  frontend:
    build:
      context: ./repo
      dockerfile: ../Dockerfile.frontend
      args:
        REACT_APP_BACKEND_URL: ${PUBLIC_URL}
    container_name: w009a-rt-frontend
    restart: unless-stopped
    labels:
      - begwork.w009a.isolated=1
"""

RT_DOCKERFILE_BACKEND = """FROM python:3.11-slim
COPY backend/ /app/
CMD ["python3", "-u", "/app/server.py"]
"""

RT_DOCKERFILE_FRONTEND = """FROM python:3.11-slim
ARG REACT_APP_BACKEND_URL
COPY frontend/ /app/
COPY nginx.conf /app/nginx.conf
CMD ["python3", "-u", "/app/app.py"]
"""

SLEEPER = "import time\nprint('w009a rt %s', flush=True)\nwhile True:\n    time.sleep(3600)\n"
CRASHER = "import sys\nprint('w009a rt crash on purpose', flush=True)\nsys.exit(3)\n"


def git(repo, *args):
    return run_git(repo, *args)


def commit_all(repo, message):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def write(root, rel, data):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))


def make_rt_repo(root, tools):
    os.makedirs(root)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "tester")
    git(root, "config", "user.email", "tester@example.invalid")
    git(root, "config", "core.autocrlf", "false")
    files = dict(tools)
    files["ops/release/synology/layout.json"] = (json.dumps(RT_LAYOUT, indent=2) + "\n").encode()
    files.update({
        "ops/synology/deploy/docker-compose.yml": RT_COMPOSE,
        "ops/synology/deploy/Dockerfile.backend": RT_DOCKERFILE_BACKEND,
        "ops/synology/deploy/Dockerfile.frontend": RT_DOCKERFILE_FRONTEND,
        "backend/server.py": SLEEPER % "backend v1",
        "frontend/app.py": SLEEPER % "frontend v1",
        "nginx.conf": "# w009a rt placeholder\n",
    })
    for rel, data in files.items():
        write(root, rel, data)
    c = {"rt0": commit_all(root, "rt0")}
    write(root, "backend/server.py", SLEEPER % "backend v2")
    c["rt1"] = commit_all(root, "rt1 backend change")
    git(root, "checkout", "-q", "-b", "crash", c["rt0"])
    write(root, "backend/server.py", CRASHER)
    c["rtcrash"] = commit_all(root, "rtcrash backend exits")
    git(root, "checkout", "-q", "main")
    return c


def ok(result):
    p, bundle = result
    if not bundle:
        raise SystemExit("bundle build failed:\n%s\n%s" % (p.stdout, p.stderr))
    return bundle


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--commit", default="HEAD")
    ap.add_argument("--allow-dirty", action="store_true", help="local runner tests only")
    a = ap.parse_args()

    commit = git(REPO_ROOT, "rev-parse", "--verify", a.commit + "^{commit}")
    dirty = subprocess.run(["git", "-C", REPO_ROOT, "status", "--porcelain", "--", "ops/release", "ops/synology/deploy",
                            "nginx.conf"], capture_output=True, text=True).stdout.strip()
    if (dirty or commit != git(REPO_ROOT, "rev-parse", "HEAD")) and not a.allow_dirty:
        raise SystemExit("refusing: working tree differs from %s under ops/release (commit first)" % commit)

    pkg = os.path.join(os.path.abspath(a.out), "w009a-isolated-%s" % commit[:12])
    if os.path.exists(pkg):
        raise SystemExit("package exists: %s" % pkg)
    tmp = tempfile.mkdtemp(prefix="w009a-pkg-")
    try:
        tools = harness.tool_files() if a.allow_dirty else harness.tool_files(commit)
        repo = os.path.join(tmp, "repo")
        c = make_repo(repo, tools=tools)
        out = os.path.join(tmp, "bundles")
        b = {}
        b["b0"] = ok(build(repo, c["c0"], os.path.join(out, "b0"), "--no-previous", "--baseline",
                           "--legacy-extra", "nginx.conf=" + LIVE_NGINX_BLOB))
        b["b1"] = ok(build(repo, c["c1"], os.path.join(out, "b1"), "--previous-manifest", os.path.join(b["b0"], "manifest.json")))
        b["b2"] = ok(build(repo, c["c2"], os.path.join(out, "b2"), "--previous-manifest", os.path.join(b["b1"], "manifest.json")))
        b["bmig"] = ok(build(repo, c["c1"], os.path.join(out, "bmig"), "--previous-manifest",
                             os.path.join(b["b0"], "manifest.json"), "--declare-migration", "w009a_isolated_probe",
                             "--migration-approval", "W0-09A-isolated-validation"))
        rt = os.path.join(tmp, "rt")
        rc = make_rt_repo(rt, tools)

        def rt_build(name, commit_sha, *extra):
            p, bundle = build(rt, commit_sha, os.path.join(out, name), "--deployment-id", "w009a-rt",
                              "--reachable-from", name == "rtcrash" and "crash" or "main",
                              "--approval", "validation:W0-09A-isolated", *extra, environment="staging")
            return ok((p, bundle))
        b["rt0"] = rt_build("rt0", rc["rt0"], "--no-previous")
        b["rt1"] = rt_build("rt1", rc["rt1"], "--previous-manifest", os.path.join(b["rt0"], "manifest.json"))
        b["rtcrash"] = rt_build("rtcrash", rc["rtcrash"], "--previous-manifest", os.path.join(b["rt0"], "manifest.json"))

        os.makedirs(pkg)
        expected = {"COMMIT": commit, "SECRET_JWT": SECRET_JWT, "SECRET_MONGO": SECRET_MONGO_PASSWORD,
                    "NGINX_BLOB": LIVE_NGINX_BLOB}
        for name, bundle in b.items():
            shutil.copytree(bundle, os.path.join(pkg, "bundles", name))
            doc = json.load(open(os.path.join(bundle, "manifest.json"), encoding="utf-8"))
            key = name.upper()
            expected[key + "_RELEASE"] = doc["release"]["release_id"]
            expected[key + "_TREE"] = doc["release"]["app"]["tree"]
            expected[key + "_REBUILD"] = ",".join(doc["release"]["services_to_rebuild"])
        for rel in ("docker-compose.yml", "Dockerfile.backend", "Dockerfile.frontend"):
            write(pkg, "layout/" + rel, harness.real_blob("ops/synology/deploy/" + rel))
        write(pkg, "layout/nginx.conf", harness.real_blob("nginx.conf"))
        write(pkg, "rt-layout/docker-compose.yml", RT_COMPOSE)
        write(pkg, "rt-layout/Dockerfile.backend", RT_DOCKERFILE_BACKEND)
        write(pkg, "rt-layout/Dockerfile.frontend", RT_DOCKERFILE_FRONTEND)
        entries = harness.gitobj.ls_tree(REPO_ROOT, commit)
        runner = {"ops/release/tests/synology/run_isolated.sh": "runner/run_isolated.sh",
                  "ops/release/tests/fakes/docker": "runner/fakes/docker",
                  "ops/release/tests/fakes/docker-compose": "runner/fakes/docker-compose",
                  "ops/release/tests/fakes/curl": "runner/fakes/curl"}
        for src, dst in runner.items():
            if a.allow_dirty:
                data = harness.read_bytes(os.path.join(REPO_ROOT, *src.split("/"))).replace(b"\r\n", b"\n")
            else:
                data = harness.gitobj.read_blobs(REPO_ROOT, [entries[src][1]])[entries[src][1]]
            write(pkg, dst, data)
        write(pkg, "COMMIT", commit + "\n")
        write(pkg, "expected.env", "".join("%s=%s\n" % (k, expected[k]) for k in sorted(expected)))
        sums = []
        for dirpath, _dirs, names in os.walk(pkg):
            for n in names:
                full = os.path.join(dirpath, n)
                rel = os.path.relpath(full, pkg).replace(os.sep, "/")
                sums.append("%s  %s\n" % (hashlib.sha256(harness.read_bytes(full)).hexdigest(), rel))
        write(pkg, "SHA256SUMS", "".join(sorted(sums, key=lambda s: s[66:])))
        print(json.dumps({"package": pkg, "commit": commit, "bundles": {k: expected[k.upper() + "_RELEASE"] for k in b}},
                         indent=2))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
