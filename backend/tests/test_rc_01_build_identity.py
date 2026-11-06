"""
RC-01 — build identity: the same full SHA in the release manifest, the API and the UI.

Cases of docs/architecture/tasks/RC-01_BUILD_IDENTITY.md:

1. ``/api/version`` with BUILD_INFO.json → the file's SHA, no authentication needed;
2. env only (``BUILD_SHA``) → the env SHA, ``source=env``;
3. neither → ``build_sha="unknown"``;
4. env that contradicts the file → the file wins and the disagreement is logged;
5. the response has exactly the allowlisted keys and no secret, path or host name;
6. ``environment_label`` follows R0-07: exact raw ``ENV`` only, everything else ``unknown``;
7. ``/api/health`` is unchanged;
8. one release build: manifest commit == bundle build_info.json == ``/api/version`` ==
   the frontend build constant (``frontend/build-info.js``, the file craco bakes in).

    PYTHONPATH=. pytest tests/test_rc_01_build_identity.py -v --noconftest
"""
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.core import build_info as bi
from app.routes.health import router as health_router

REPO = Path(__file__).resolve().parents[2]
RELEASE_DIR = REPO / "ops" / "release"
SHA_FILE = "c0e34e1f3037010311d352683d519c3c9d7dcbfa"
SHA_ENV = "0b53bcd5b977ee27de8d4cee363fed41dd897482"
SECRETS = {"JWT_SECRET": "SENTINEL-JWT-rc01-9d2f", "MONGO_URL": "mongodb://u:SENTINEL-PW-rc01@db-host-rc01:27017",
           "STRIPE_SECRET_KEY": "sk_test_SENTINEL_rc01"}


def _client():
    app = FastAPI()
    api = APIRouter(prefix="/api")
    api.include_router(health_router)
    app.include_router(api)
    return TestClient(app)


def _write_info(path, sha, t="2026-10-20T16:32:08Z"):
    path.write_text(json.dumps({"schema": "beg.build-info/v1", "build_sha": sha, "build_time": t,
                                "source": "git-objects"}), encoding="utf-8")


@pytest.fixture
def env(monkeypatch, tmp_path):
    for k in ("BUILD_SHA", "BUILD_TIME", "ENV"):
        monkeypatch.delenv(k, raising=False)
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    info = tmp_path / "BUILD_INFO.json"
    monkeypatch.setattr(bi, "BUILD_INFO_FILE", info)
    return info


def test_file_is_served_without_auth(env, monkeypatch):
    _write_info(env, SHA_FILE)
    monkeypatch.setenv("ENV", "staging")
    r = _client().get("/api/version")
    assert r.status_code == 200
    assert r.json() == {"build_sha": SHA_FILE, "build_time": "2026-10-20T16:32:08Z",
                        "environment_label": "staging", "source": "build-info-file"}


def test_env_only(env, monkeypatch):
    monkeypatch.setenv("BUILD_SHA", SHA_ENV)
    monkeypatch.setenv("BUILD_TIME", "2026-11-01T10:00:00Z")
    body = _client().get("/api/version").json()
    assert (body["build_sha"], body["build_time"], body["source"]) == (SHA_ENV, "2026-11-01T10:00:00Z", "env")


def test_nothing_is_unknown(env):
    body = _client().get("/api/version").json()
    assert body == {"build_sha": "unknown", "build_time": None, "environment_label": "unknown", "source": "none"}


@pytest.mark.parametrize("bad", ["C0E34E1F3037010311D352683D519C3C9D7DCBFA", "c0e34e1f", "", " " + SHA_ENV])
def test_malformed_env_is_ignored(env, monkeypatch, bad):
    monkeypatch.setenv("BUILD_SHA", bad)
    assert _client().get("/api/version").json()["build_sha"] == "unknown"


@pytest.mark.parametrize("content", ["{not json", json.dumps({"build_sha": SHA_FILE}),
                                     json.dumps({"schema": "beg.build-info/v1", "build_sha": "HEAD"}), "[]"])
def test_invalid_file_is_ignored(env, monkeypatch, content):
    env.write_text(content, encoding="utf-8")
    assert _client().get("/api/version").json()["build_sha"] == "unknown"
    monkeypatch.setenv("BUILD_SHA", SHA_ENV)
    assert _client().get("/api/version").json()["source"] == "env"


def test_file_wins_over_contradicting_env_and_logs(env, monkeypatch, caplog):
    _write_info(env, SHA_FILE)
    monkeypatch.setenv("BUILD_SHA", SHA_ENV)
    with caplog.at_level(logging.WARNING, logger=bi.__name__):
        body = _client().get("/api/version").json()
    assert body["build_sha"] == SHA_FILE and body["source"] == "build-info-file"
    assert any("disagrees" in r.getMessage() and SHA_ENV[:12] in r.getMessage() for r in caplog.records)
    for r in caplog.records:  # the log carries no secret
        assert not any(v in r.getMessage() for v in SECRETS.values())


def test_no_mismatch_log_when_equal(env, monkeypatch, caplog):
    _write_info(env, SHA_FILE)
    monkeypatch.setenv("BUILD_SHA", SHA_FILE)
    with caplog.at_level(logging.WARNING, logger=bi.__name__):
        _client().get("/api/version")
    assert not caplog.records


@pytest.mark.parametrize("setup", ["file", "env", "none"])
def test_allowlisted_keys_only_and_no_secrets(env, monkeypatch, setup):
    if setup == "file":
        _write_info(env, SHA_FILE)
    elif setup == "env":
        monkeypatch.setenv("BUILD_SHA", SHA_ENV)
    monkeypatch.setenv("ENV", "production")
    r = _client().get("/api/version")
    assert tuple(sorted(r.json())) == tuple(sorted(bi.RESPONSE_KEYS))
    text = r.text
    for v in SECRETS.values():
        assert v not in text
    for leak in (str(env), str(REPO), "db-host-rc01", os.uname().nodename):
        assert leak not in text


@pytest.mark.parametrize("raw,label", [
    ("production", "production"), ("staging", "staging"), ("development", "development"), ("test", "test"),
    (None, "unknown"), ("", "unknown"), ("prod", "unknown"), ("PRODUCTION", "unknown"), (" test", "unknown"),
    ("test\n", "unknown"), ("dev", "unknown")])
def test_environment_label_is_r0_07_fail_closed(env, monkeypatch, raw, label):
    if raw is not None:
        monkeypatch.setenv("ENV", raw)
    monkeypatch.setenv("ENVIRONMENT", "production")  # the old variable is not read
    assert _client().get("/api/version").json()["environment_label"] == label


def test_health_unchanged(env):
    r = _client().get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_real_app_serves_version_without_auth(env, monkeypatch):
    _write_info(env, SHA_FILE)
    import server
    r = TestClient(server.app).get("/api/version")
    assert r.status_code == 200 and r.json()["build_sha"] == SHA_FILE


# ── 8. manifest == API == frontend for one build ───────────────────────────────────────

def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.mark.skipif(shutil.which("node") is None or shutil.which("git") is None, reason="needs git and node")
def test_manifest_equals_api_equals_frontend(env, monkeypatch, tmp_path):
    sys.path.insert(0, str(RELEASE_DIR / "tests"))
    sys.path.insert(0, str(RELEASE_DIR))
    try:
        import harness
    finally:
        sys.path.remove(str(RELEASE_DIR / "tests"))
        sys.path.remove(str(RELEASE_DIR))
    repo = tmp_path / "repo"
    commits = harness.make_repo(str(repo))
    target = commits["c2"]
    p, bundle = harness.build(str(repo), target, str(tmp_path / "out"), "--no-previous", environment="test")
    assert bundle, p.stderr

    manifest = json.loads((Path(bundle) / "manifest.json").read_text(encoding="utf-8"))
    bundle_info = json.loads((Path(bundle) / "build_info.json").read_text(encoding="utf-8"))
    sums = (Path(bundle) / "SHA256SUMS").read_text(encoding="ascii")
    assert "  build_info.json\n" in sums
    v = subprocess.run([sys.executable, str(RELEASE_DIR / "release_verify.py"), "bundle", "--bundle", bundle],
                       capture_output=True, text=True)
    assert v.returncode == 0, v.stdout + v.stderr

    # stamp an extracted build context from the verified bundle, as a deploy would
    ctx = tmp_path / "ctx"
    (ctx / "backend").mkdir(parents=True)
    (ctx / "frontend").mkdir()
    w = subprocess.run([sys.executable, str(RELEASE_DIR / "write_build_info.py"), "--from-bundle", bundle,
                        "--target", str(ctx)], capture_output=True, text=True)
    assert w.returncode == 0, w.stderr

    monkeypatch.setattr(bi, "BUILD_INFO_FILE", ctx / "backend" / "BUILD_INFO.json")
    monkeypatch.setenv("BUILD_SHA", SHA_ENV)  # an editable runtime value cannot override the build
    api = _client().get("/api/version").json()

    fe = subprocess.run(["node", str(REPO / "frontend" / "build-info.js"), str(ctx / "frontend")],
                        capture_output=True, text=True, env={"PATH": os.environ["PATH"], "REACT_APP_BUILD_SHA": SHA_ENV})
    assert fe.returncode == 0, fe.stderr
    frontend = json.loads(fe.stdout)

    commit = manifest["release"]["app"]["commit"]
    assert commit == target == _git(repo, "rev-parse", target)
    assert len(commit) == 40
    assert bundle_info["build_sha"] == api["build_sha"] == frontend["build_sha"] == commit
    assert bundle_info["build_time"] == api["build_time"] == frontend["build_time"]
    assert api["source"] == frontend["source"] == "build-info-file"
    assert api["environment_label"] == "unknown"  # ENV unset in this test


def test_write_build_info_refuses_bundle_with_tampered_identity(tmp_path):
    bundle = tmp_path / "b"
    bundle.mkdir()
    (bundle / "manifest.json").write_text(json.dumps({"release": {"app": {"commit": SHA_FILE}}}), encoding="utf-8")
    _write_info(bundle / "build_info.json", SHA_ENV)
    (tmp_path / "ctx" / "backend").mkdir(parents=True)
    (tmp_path / "ctx" / "frontend").mkdir()
    w = subprocess.run([sys.executable, str(RELEASE_DIR / "write_build_info.py"), "--from-bundle", str(bundle),
                        "--target", str(tmp_path / "ctx")], capture_output=True, text=True)
    assert w.returncode == 2 and "!= manifest commit" in w.stderr
    assert not (tmp_path / "ctx" / "backend" / "BUILD_INFO.json").exists()
