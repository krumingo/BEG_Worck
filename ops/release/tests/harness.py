"""Shared fixtures for the W0-09A release tests.

* a synthetic Git repository whose tree carries the REAL production layout files
  (ops/synology/deploy/*), the REAL root nginx.conf and the REAL release tools from this
  checkout, so the code under test is exactly what a bundle ships;
* a fake Synology layout root (compose, Dockerfiles, .env with sentinel secrets, repo/,
  backups/) and fake docker / docker-compose / curl written in bash (no CRLF artefacts).
"""
import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile

RELEASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(os.path.dirname(RELEASE_DIR))
sys.path.insert(0, RELEASE_DIR)

from beg_release import gitobj  # noqa: E402

SECRET_JWT = "SENTINEL-JWT-7f3a9c2e41b84d6f"
SECRET_MONGO_PASSWORD = "SENTINEL-MONGO-PW-5b1d8e"
PYTHON = sys.executable.replace("\\", "/")
BASH = shutil.which("bash")
LIVE_NGINX_BLOB = "b87dfcda80a6fbcfd0fa18bd36a220b77a425607"


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def read_text(path):
    return read_bytes(path).decode("utf-8", "replace")


def read_json(path):
    return json.loads(read_text(path))


def posix(path):
    return os.path.abspath(path).replace("\\", "/")


def run_git(repo, *args, input_bytes=None, check=True):
    p = subprocess.run(["git", "-C", repo, *args], input=input_bytes, capture_output=True)
    if check and p.returncode != 0:
        raise RuntimeError("git %s: %s" % (args, p.stderr.decode()))
    return p.stdout.decode("utf-8", "replace").strip()


def real_blob(path):
    """Bytes of a file from the real repository HEAD (not the working tree)."""
    return subprocess.run(["git", "-C", REPO_ROOT, "cat-file", "blob", "HEAD:" + path],
                          capture_output=True, check=True).stdout


def _write(root, rel, data, mode=None):
    full = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode("utf-8"))


def tool_files():
    """Working-tree release tools (the code under test), LF-normalised like the Git blobs."""
    files = {}
    for dirpath, _dirs, names in os.walk(RELEASE_DIR):
        if "__pycache__" in dirpath or os.sep + "tests" in dirpath[len(RELEASE_DIR):]:
            continue
        for n in names:
            full = os.path.join(dirpath, n)
            rel = os.path.relpath(full, REPO_ROOT).replace(os.sep, "/")
            data = read_bytes(full)
            if n.endswith((".py", ".sh", ".json", ".md")):
                data = data.replace(b"\r\n", b"\n")
            files[rel] = data
    return files


def make_repo(root):
    """Synthetic repo with commits:
       c0 legacy baseline (no tracked nginx.conf), c1 tracks nginx.conf + backend change,
       c2 frontend change, c3 docs-only change."""
    os.makedirs(root)
    run_git(root, "init", "-q", "-b", "main")
    run_git(root, "config", "user.name", "tester")
    run_git(root, "config", "user.email", "tester@example.invalid")
    run_git(root, "config", "core.autocrlf", "false")
    base_files = {
        "backend/server.py": "print('release one')\n",
        "backend/requirements.txt": "fastapi==0.110.1\n",
        "backend/app/__init__.py": "",
        "frontend/package.json": '{"name": "frontend"}\n',
        "frontend/yarn.lock": "# yarn lockfile v1\n",
        "frontend/src/index.js": "console.log('one');\n",
        "tools/run.sh": "#!/usr/bin/env bash\necho run\n",
        "docs/readme.md": "docs v1\n",
        "ops/synology/deploy/docker-compose.yml": real_blob("ops/synology/deploy/docker-compose.yml"),
        "ops/synology/deploy/Dockerfile.backend": real_blob("ops/synology/deploy/Dockerfile.backend"),
        "ops/synology/deploy/Dockerfile.frontend": real_blob("ops/synology/deploy/Dockerfile.frontend"),
    }
    base_files.update(tool_files())
    for rel, data in base_files.items():
        _write(root, rel, data)
    run_git(root, "add", "-A")
    run_git(root, "update-index", "--chmod=+x", "tools/run.sh")
    run_git(root, "commit", "-q", "-m", "c0 legacy baseline")
    c0 = run_git(root, "rev-parse", "HEAD")

    _write(root, "nginx.conf", real_blob("nginx.conf"))
    _write(root, "backend/server.py", "print('release two')\n")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-q", "-m", "c1 track nginx.conf, backend change")
    c1 = run_git(root, "rev-parse", "HEAD")

    _write(root, "frontend/src/index.js", "console.log('two');\n")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-q", "-m", "c2 frontend change")
    c2 = run_git(root, "rev-parse", "HEAD")

    _write(root, "docs/readme.md", "docs v2\n")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-q", "-m", "c3 docs only")
    c3 = run_git(root, "rev-parse", "HEAD")
    return {"c0": c0, "c1": c1, "c2": c2, "c3": c3}


def build(repo, commit, out, *extra, environment="production"):
    cmd = [sys.executable, os.path.join(RELEASE_DIR, "release_build.py"), "--repo", repo, "--commit", commit,
           "--environment", environment, "--deployment-id", "synology-begwork", "--out", out,
           "--reachable-from", "main", "--created-by", "tester", *extra]
    if environment == "production" and "--approval" not in extra:
        cmd += ["--approval", "deploy:test-approval"]
    p = subprocess.run(cmd, capture_output=True, text=True)
    bundle = None
    if p.returncode == 0:
        bundle = json.loads(p.stdout)["bundle"]
    return p, bundle


def verify(*args):
    return subprocess.run([sys.executable, os.path.join(RELEASE_DIR, "release_verify.py"), *args],
                          capture_output=True, text=True)


FAKE_DOCKER = r'''#!/usr/bin/env bash
echo "docker $*" >> "$FAKE/calls.log"
cmd="$1"; shift
case "$cmd" in
  inspect)
    shift 2 2>/dev/null   # -f FORMAT
    name="$1"; f="$FAKE/c_$name"
    [ -f "$f" ] || exit 1
    if [ -f "$FAKE/restart_loop_$name" ]; then
      IFS='|' read -r st rc cr < "$f"; rc=$((rc + 1)); printf '%s|%s|%s\n' "$st" "$rc" "$cr" > "$f"
    fi
    cat "$f" ;;
  logs)
    name="${@: -1}"; [ -f "$FAKE/logs_$name" ] && cat "$FAKE/logs_$name"; exit 0 ;;
  exec)
    name="$1"; key="$3"; f="$FAKE/env_${name}_${key}"
    [ -f "$f" ] && { cat "$f"; exit 0; }; exit 1 ;;
  run)
    # Simulates the production verifier container: enforces the isolation flags and read-only
    # bundle mounts, maps container paths back to host paths and runs the local Python.
    [ "${RELEASE_PY_MODE:-}" = docker ] || { echo "unexpected docker run in local verifier mode" >&2; exit 99; }
    net=""; pull=""; maps=()
    while [ $# -gt 0 ]; do
      case "$1" in
        --rm) shift ;;
        --pull) pull="$2"; shift 2 ;;
        --network) net="$2"; shift 2 ;;
        -v) maps+=("$2"); shift 2 ;;
        -*) echo "fake docker: unexpected run option $1" >&2; exit 97 ;;
        *) break ;;
      esac
    done
    if [ "$net" != none ] || [ "$pull" != never ]; then echo "fake docker: verifier needs --network none --pull never" >&2; exit 98; fi
    [ "$1" = python:3.11-slim ] && [ "$2" = python3 ] || { echo "fake docker: unexpected image/command $1 $2" >&2; exit 97; }
    shift 2
    for m in "${maps[@]}"; do
      case "$m" in *:/bundle|*:/hint) echo "fake docker: $m must be mounted read-only" >&2; exit 97 ;; esac
    done
    args=()
    for a in "$@"; do
      for m in "${maps[@]}"; do
        spec="${m%:ro}"; dst="${spec##*:}"; src="${spec%:*}"
        case "$a" in "$dst"|"$dst"/*) a="$(cygpath -m "$src" 2>/dev/null || printf '%s' "$src")${a#"$dst"}"; break ;; esac
      done
      args+=("$a")
    done
    exec "$RELEASE_PYTHON" "${args[@]}" ;;
  *) exit 0 ;;
esac
'''

FAKE_COMPOSE = r'''#!/usr/bin/env bash
echo "compose $*" >> "$FAKE/calls.log"
if [ "$1" = up ]; then
  n=$(( $(cat "$FAKE/up_count" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$FAKE/up_count"
  [ -f "$FAKE/compose_output" ] && cat "$FAKE/compose_output"
  [ -f "$FAKE/on_up_$n" ] && bash "$FAKE/on_up_$n"
  if [ -f "$FAKE/compose_fail_$n" ]; then echo "ERROR: build failed"; exit 1; fi
  shift; shift; shift   # up -d --build
  for svc in "$@"; do
    c="$(cat "$FAKE/svc_$svc")"
    [ -f "$FAKE/no_recreate" ] && continue
    status=running; [ -f "$FAKE/crash_$svc" ] && status=exited
    printf '%s|0|%s\n' "$status" "$(date -u +%Y-%m-%dT%H:%M:%S.000000000Z)" > "$FAKE/c_$c"
  done
fi
exit 0
'''

FAKE_CURL = r'''#!/usr/bin/env bash
url="${@: -1}"; path="/${url#*://*/}"; [ "$url" = "${url#*://*/}" ] && path="/"
echo "curl $path" >> "$FAKE/calls.log"
code=200
if [ -f "$FAKE/http_codes" ]; then
  while read -r p c; do [ "$p" = "$path" ] && code="$c"; done < "$FAKE/http_codes"
fi
printf '%s' "$code"
'''


class Layout:
    """A fake /volume1/docker/begwork with fakes, adopted from a baseline bundle."""

    def __init__(self, root, repo, commits):
        self.root = root
        self.base = os.path.join(root, "base")
        self.fake = os.path.join(root, "fake")
        self.bin = os.path.join(root, "bin")
        for d in (self.base, self.fake, self.bin):
            os.makedirs(d)
        for name, data in (("docker", FAKE_DOCKER), ("docker-compose", FAKE_COMPOSE), ("curl", FAKE_CURL)):
            with open(os.path.join(self.bin, name), "w", newline="\n") as f:
                f.write(data)
            os.chmod(os.path.join(self.bin, name), 0o755)
        for name in ("docker-compose.yml", "Dockerfile.backend", "Dockerfile.frontend"):
            with open(os.path.join(self.base, name), "wb") as f:
                f.write(real_blob("ops/synology/deploy/" + name))
        with open(os.path.join(self.base, ".env"), "w", newline="\n") as f:
            f.write("MONGO_URL=mongodb+srv://beg:%s@cluster.example.invalid/db\n" % SECRET_MONGO_PASSWORD)
            f.write("DB_NAME=begwork\nBEG_SYSTEM_DB=begwork_system\nPUBLIC_URL=http://192.0.2.10:8080\n")
            f.write("CORS_ORIGINS=*\nJWT_SECRET=%s\n" % SECRET_JWT)
        os.makedirs(os.path.join(self.base, "backups"))
        with gzip.open(os.path.join(self.base, "backups", "begwork_atlas_2026-09-13_0310.archive.gz"), "wb") as g:
            g.write(b"fake archive")
        # live repo = exact c0 tree + the hand-copied nginx.conf (pre-W0-09A reality)
        self.extract_commit(repo, commits["c0"], os.path.join(self.base, "repo"))
        with open(os.path.join(self.base, "repo", "nginx.conf"), "wb") as f:
            f.write(real_blob("nginx.conf"))
        for svc, c in (("backend", "begwork-backend"), ("frontend", "begwork-frontend")):
            with open(os.path.join(self.fake, "svc_" + svc), "w", newline="\n") as f:
                f.write(c)
            self.set_container(c, "running", 0, "2026-01-01T00:00:00.000000000Z")

    @staticmethod
    def extract_commit(repo, commit, dest):
        entries = gitobj.ls_tree(repo, commit)
        blobs = gitobj.read_blobs(repo, [s for _, s in entries.values()])
        data = gitobj.build_tar(entries, blobs, 1)
        tmp = dest + ".tar"
        with open(tmp, "wb") as f:
            f.write(data)
        gitobj.safe_extract(tmp, dest)
        os.remove(tmp)

    def set_container(self, name, status, restarts, created):
        with open(os.path.join(self.fake, "c_" + name), "w", newline="\n") as f:
            f.write("%s|%d|%s\n" % (status, restarts, created))

    def fake_file(self, name, content):
        with open(os.path.join(self.fake, name), "w", newline="\n") as f:
            f.write(content)

    def env(self, **extra):
        e = dict(os.environ)
        e.update({
            "PATH": posix(self.bin) + os.pathsep + os.environ.get("PATH", ""),
            "BEGWORK_BASE": posix(self.base), "RELEASE_PY_MODE": "local", "RELEASE_PYTHON": PYTHON,
            "DOCKER": "docker", "CURL": "curl", "COMPOSE_BIN": "docker-compose", "SLEEP": "true",
            "FAKE": posix(self.fake), "REQUIRE_BACKUP": "1", "USER": "tester", "SUDO_USER": "tester",
        })
        e.update(extra)
        return e

    def run(self, bundle, script, *args, **env_extra):
        path = posix(os.path.join(bundle, "tools", "synology", script))
        return subprocess.run([BASH, path, *args], env=self.env(**env_extra),
                              capture_output=True, text=True, timeout=300)

    def calls(self):
        p = os.path.join(self.fake, "calls.log")
        return read_text(p) if os.path.exists(p) else ""

    def state(self, name):
        p = os.path.join(self.base, "release-state", name)
        if not os.path.exists(p):
            return None
        return dict(line.split("=", 1) for line in read_text(p).splitlines() if "=" in line)

    def records(self):
        hist = os.path.join(self.base, "release-state", "history")
        out = []
        for d in sorted(os.listdir(hist)) if os.path.isdir(hist) else []:
            p = os.path.join(hist, d, "record.json")
            if os.path.exists(p):
                out.append(read_json(p))
        return out

    def snapshot(self):
        """Content snapshot of the layout, ignoring evidence/lock (which a failed precheck may write)."""
        snap = {}
        for dirpath, dirs, files in os.walk(self.base):
            rel_dir = os.path.relpath(dirpath, self.base).replace(os.sep, "/")
            if rel_dir.startswith("release-state/history") or rel_dir.startswith("release-state/lock"):
                continue
            for d in dirs:
                snap["D:" + (rel_dir + "/" + d).lstrip("./")] = ""
            for n in files:
                full = os.path.join(dirpath, n)
                snap[(rel_dir + "/" + n).lstrip("./")] = hashlib.sha256(read_bytes(full)).hexdigest()
        return snap

    def all_text(self):
        """Everything the tools wrote (state + evidence) for secret scanning."""
        chunks = []
        for dirpath, _dirs, files in os.walk(os.path.join(self.base, "release-state")):
            for n in files:
                chunks.append(read_text(os.path.join(dirpath, n)))
        for n in ("DEPLOYED_COMMIT", "DEPLOYED_VERSION.txt"):
            p = os.path.join(self.base, n)
            if os.path.exists(p):
                chunks.append(read_text(p))
        return "\n".join(chunks)


def tree_matches(dir_path, repo, commit, extras=None):
    tree = run_git(repo, "rev-parse", commit + "^{tree}")
    entries = gitobj.ls_tree(repo, commit)
    ok, detail = gitobj.verify_dir_tree(dir_path, tree, allow_extra=extras,
                                        mode_hint={p: m for p, (m, _) in entries.items()})
    return ok, detail
