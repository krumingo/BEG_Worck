"""ST-02 — isolated staging stack: guards, isolation proof and refusals.

DB-free; run with ``--noconftest``. The compose-model test uses the real ``docker compose``
(no daemon needed for ``config``) and is skipped when Docker Compose is not installed.

    cd backend && PYTHONPATH=. pytest tests/test_st_02_staging_stack.py -v --noconftest
"""
import copy
import importlib.util
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
STAGING = REPO / "ops" / "staging"
PROD_LAYOUT = REPO / "ops" / "synology" / "deploy"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


up = _load("st02_staging_up", STAGING / "staging_up.py")
iso = _load("st02_isolation_check", STAGING / "isolation_check.py")

PROJECT = "begwork-staging"


def good_model(project=PROJECT, port=18080, mode="enforce"):
    return {
        "name": project,
        "services": {
            "backend": {"container_name": project + "-backend", "networks": {"st02": None},
                        "environment": {"ENV": "staging", "PERMISSION_SERVICE_MODE": mode, "MONGO_URL": "x",
                                        "JWT_SECRET": "synthetic"}},
            "frontend": {"container_name": project + "-frontend", "networks": {"st02": None},
                         "ports": [{"host_ip": "127.0.0.1", "published": str(port), "target": 80, "protocol": "tcp"}]},
            "mongo": {"container_name": project + "-mongo", "networks": {"st02": None},
                      "command": ["--replSet", "rs0", "--bind_ip_all"],
                      "volumes": [{"type": "volume", "source": "st02-mongo-data", "target": "/data/db"}]},
        },
        "networks": {"st02": {"name": project + "_net", "driver": "bridge"}},
        "volumes": {"st02-mongo-data": {"name": project + "_mongo_data"}},
    }


# ------------------------------------------------------------ isolation_check
def test_isolation_good_model_passes():
    assert iso.check(good_model(), PROJECT, "18080", "enforce") == []


@pytest.mark.parametrize("mutate,needle", [
    (lambda m: m["services"]["backend"].update(container_name="begwork-backend"), "production container name"),
    (lambda m: m["services"]["frontend"].update(container_name="begwork-frontend"), "production container name"),
    (lambda m: m["services"]["frontend"]["ports"].append(
        {"host_ip": "", "published": "8080", "target": 80}), "8080"),
    (lambda m: m["services"]["frontend"]["ports"][0].update(host_ip="0.0.0.0"), "published ports"),
    (lambda m: m["services"]["mongo"].update(ports=[{"host_ip": "127.0.0.1", "published": "27017", "target": 27017}]),
     "published ports"),
    (lambda m: m["networks"]["st02"].update(external=True), "external"),
    (lambda m: m["services"]["backend"].update(networks={"st02": None, "prod": None}), "networks"),
    (lambda m: m["services"]["backend"].update(network_mode="host"), "network_mode"),
    (lambda m: m["services"].update(extra={"container_name": PROJECT + "-extra", "networks": {"st02": None}}), "services are"),
    (lambda m: m["services"]["mongo"].update(command=["--bind_ip_all"]), "replica set"),
    (lambda m: m["volumes"]["st02-mongo-data"].update(name="begwork_mongo"), "named volume"),
    (lambda m: m["services"]["backend"]["environment"].update(ENV="production"), "ENV is not staging"),
    (lambda m: m["services"]["backend"]["environment"].update(PERMISSION_SERVICE_MODE="off"), "PERMISSION_SERVICE_MODE"),
    (lambda m: m["services"]["backend"]["environment"].update(STRIPE_API_KEY="sk_test"), "real-provider"),
    (lambda m: m["services"]["backend"]["environment"].update(SMTP_HOST="mail"), "real-provider"),
    (lambda m: m["services"]["backend"]["environment"].update(EMERGENT_LLM_KEY="k"), "real-provider"),
    (lambda m: m["services"]["backend"]["environment"].update(BILLING_PROVIDER="stripe"), "real-provider"),
    (lambda m: m.update(name="begwork"), "project name"),
])
def test_isolation_violations_fail(mutate, needle):
    m = copy.deepcopy(good_model())
    mutate(m)
    errors = iso.check(m, PROJECT, "18080", "enforce")
    assert errors and any(needle in e for e in errors), errors


def test_isolation_refuses_non_staging_project():
    assert any("not a begwork-staging" in e for e in iso.check(good_model("begwork"), "begwork", "18080", "enforce"))


def test_isolation_main_never_prints_env_values(capsys, monkeypatch):
    m = good_model()
    m["services"]["backend"]["environment"]["JWT_SECRET"] = "SENTINEL-SECRET-VALUE"
    m["services"]["backend"]["environment"]["ENV"] = "SENTINEL-ENV-VALUE"
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps(m)))
    monkeypatch.setenv("ST02_PROJECT", PROJECT); monkeypatch.setenv("ST02_HTTP_PORT", "18080"); monkeypatch.setenv("ST02_MODE", "enforce")
    assert iso.main() == 1
    out = capsys.readouterr().out
    assert "ISOLATION FAIL" in out and "SENTINEL" not in out


# ------------------------------------------------------------ staging_up guards
@pytest.mark.parametrize("bad", ["/volume1/docker/begwork", "/volume1/docker/begwork/", "/volume1/docker/begwork/sub", "/"])
def test_base_refuses_production_and_root(bad):
    with pytest.raises(up.Refused):
        up.check_base(Path(bad))


def test_base_refuses_inside_git_work_tree():
    with pytest.raises(up.Refused):
        up.check_base(REPO / "tmp-staging")


def test_base_allows_separate_staging_dir(tmp_path):
    assert up.check_base(tmp_path / "begwork-staging") == tmp_path / "begwork-staging"
    # a sibling with the same prefix is not production
    assert str(up.check_base(Path("/volume1/docker/begwork-staging"))) == "/volume1/docker/begwork-staging"


@pytest.mark.parametrize("bad", ["begwork", "staging", "begwork_staging", "BEGWORK-STAGING", "begwork-prod"])
def test_project_must_be_staging(bad):
    with pytest.raises(up.Refused):
        up.check_project(bad)


def test_port_8080_is_refused():
    with pytest.raises(up.Refused, match="production port"):
        up.check_port(8080)


def test_busy_port_is_refused():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(1)
    try:
        assert not up.port_free(s.getsockname()[1])
        with pytest.raises(up.Refused, match="in use"):
            up.check_port(s.getsockname()[1])
    finally:
        s.close()


def _free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close()
    return p


def test_prepare_base_synthetic_private_values(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "check_port", lambda port: None)
    base, created = up.prepare_base(tmp_path / "st", PROJECT, 18555, "enforce")
    assert created and (base / up.MARKER).exists()
    env = up.read_kv(base / ".env")
    assert set(env) == {"MONGO_URL", "DB_NAME", "BEG_SYSTEM_DB", "PUBLIC_URL", "CORS_ORIGINS", "JWT_SECRET",
                        "ST02_PROJECT", "ST02_HTTP_PORT", "ST02_PERMISSION_SERVICE_MODE"}
    assert not any(k.startswith(("STRIPE", "SMTP", "EMERGENT", "BILLING")) for k in env)
    assert env["DB_NAME"] == "st02_staging" and not env["DB_NAME"].startswith("begwork")
    assert env["MONGO_URL"] == "mongodb://mongo:27017/?replicaSet=rs0"
    assert len(env["JWT_SECRET"]) >= 48 and "PERMISSION_SERVICE_MODE" not in env  # flag only via the overlay
    for f in (".env", ".st02-seed.env"):
        assert stat.S_IMODE(os.stat(base / f).st_mode) == 0o600
    st = up.read_kv(base / "staging.env")
    assert st == {"ST02_PERMISSION_SERVICE_MODE": "enforce", "ST02_HTTP_PORT": "18555", "ST02_PROJECT": PROJECT}
    assert (base / "docker-compose.staging.yml").read_bytes() == (STAGING / "deploy" / "docker-compose.staging.yml").read_bytes()
    # a second prepare with other parameters is refused; with the same ones it is reused
    with pytest.raises(up.Refused):
        up.prepare_base(base, PROJECT, 18556, "enforce")
    with pytest.raises(up.Refused):
        up.prepare_base(base, PROJECT, 18555, "off")
    assert up.prepare_base(base, PROJECT, 18555, "enforce") == (base, False)
    # the JWT secret is not regenerated on reuse
    assert up.read_kv(base / ".env")["JWT_SECRET"] == env["JWT_SECRET"]


def test_prepare_base_refuses_foreign_non_empty_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "check_port", lambda port: None)
    (tmp_path / "x").mkdir(); (tmp_path / "x" / "docker-compose.yml").write_text("services: {}\n")
    with pytest.raises(up.Refused, match="not an ST-02 staging root"):
        up.prepare_base(tmp_path / "x", PROJECT, 18555, "enforce")


def test_secret_scan_finds_leaks(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "check_port", lambda port: None)
    base, _ = up.prepare_base(tmp_path / "st", PROJECT, 18555, "enforce")
    evid = tmp_path / "evid"; evid.mkdir()
    (evid / "clean.log").write_text("nothing here\n")
    assert up.secret_scan(base, evid)["hits"] == []
    (evid / "leak.log").write_text("jwt=%s\n" % up.read_kv(base / ".env")["JWT_SECRET"])
    (evid / "leak2.log").write_text("pw=%s\n" % up.read_kv(base / ".st02-seed.env")["ST01_SEED_PASSWORD"])
    assert up.secret_scan(base, evid)["hits"] == ["leak.log", "leak2.log"]


# ------------------------------------------------------------ overlay + production layout unchanged
def test_overlay_replaces_port_and_renames_everything():
    text = (STAGING / "deploy" / "docker-compose.staging.yml").read_text()
    assert "ports: !override" in text
    code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    assert "8080" not in code
    for svc in ("backend", "frontend", "mongo"):
        assert "container_name: ${ST02_PROJECT}-%s" % svc in text
    assert "--replSet" in code and "external" not in code


def test_production_layout_and_flags_untouched():
    layout = json.loads((REPO / "ops" / "release" / "synology" / "layout.json").read_text())
    assert layout["feature_flags"] == {"PERMISSION_SERVICE_MODE": "off"}
    assert layout["services"]["backend"]["container"] == "begwork-backend"
    assert layout["smoke"]["base_url"] == "http://127.0.0.1:8080"
    compose = (PROD_LAYOUT / "docker-compose.yml").read_text()
    assert "container_name: begwork-backend" in compose and '"8080:80"' in compose


@pytest.mark.skipif(shutil.which("docker") is None or subprocess.run(
    ["docker", "compose", "version"], capture_output=True).returncode != 0, reason="docker compose not installed")
def test_real_compose_model_of_overlay_is_isolated(tmp_path):
    """The production compose file + overlay, merged by the real docker compose, passes the check."""
    for name in ("docker-compose.yml", "Dockerfile.backend", "Dockerfile.frontend"):
        shutil.copyfile(PROD_LAYOUT / name, tmp_path / name)
    shutil.copyfile(STAGING / "deploy" / "docker-compose.staging.yml", tmp_path / "docker-compose.staging.yml")
    (tmp_path / ".env").write_text("PUBLIC_URL=http://127.0.0.1:18555\nST02_PROJECT=begwork-staging\n"
                                   "ST02_HTTP_PORT=18555\nST02_PERMISSION_SERVICE_MODE=enforce\n")
    base_cmd = ["docker", "compose", "-p", PROJECT, "-f", "docker-compose.yml", "-f", "docker-compose.staging.yml"]
    r = subprocess.run(base_cmd + ["config", "--format", "json"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    model = json.loads(r.stdout)
    assert iso.check(model, PROJECT, "18555", "enforce") == []
    assert model["services"]["backend"]["build"]["dockerfile"] == "../Dockerfile.backend"  # same production build
    # without the overlay the model is production-shaped and the check refuses it
    r2 = subprocess.run(["docker", "compose", "-p", PROJECT, "-f", "docker-compose.yml", "config", "--format", "json"],
                        cwd=tmp_path, capture_output=True, text=True)
    assert r2.returncode == 0, r2.stderr
    errs = iso.check(json.loads(r2.stdout), PROJECT, "18555", "enforce")
    assert any("production container name" in e for e in errs) and any("8080" in e for e in errs)


# ------------------------------------------------------------ staging_deploy.sh refusals (before any docker call)
def _fake_bundle(tmp_path):
    b = tmp_path / "bundle"; (b / "tools" / "synology").mkdir(parents=True)
    shutil.copyfile(REPO / "ops" / "release" / "synology" / "lib.sh", b / "tools" / "synology" / "lib.sh")
    return b


def _deploy(tmp_path, base, *args):
    env = dict(os.environ, BEGWORK_BASE=str(base), DOCKER="/bin/false")
    return subprocess.run(["bash", str(STAGING / "staging_deploy.sh"), "--bundle", str(_fake_bundle(tmp_path)), *args],
                          env=env, capture_output=True, text=True)


@pytest.mark.parametrize("base", ["/volume1/docker/begwork", "/volume1/docker/begwork/x", ""])
def test_deploy_refuses_production_base(tmp_path, base):
    r = _deploy(tmp_path, base, "--initial")
    assert r.returncode == 3 and "refused" in r.stderr


def test_deploy_refuses_base_without_marker(tmp_path):
    (tmp_path / "st").mkdir()
    r = _deploy(tmp_path, tmp_path / "st", "--initial")
    assert r.returncode == 3 and ".st02-staging-root" in r.stderr


@pytest.mark.parametrize("staging_env,needle", [
    ("ST02_PROJECT=begwork\nST02_HTTP_PORT=18080\nST02_PERMISSION_SERVICE_MODE=enforce\n", "begwork-staging"),
    ("ST02_PROJECT=begwork-staging\nST02_HTTP_PORT=8080\nST02_PERMISSION_SERVICE_MODE=enforce\n", "8080"),
    ("ST02_PROJECT=begwork-staging\nST02_HTTP_PORT=18080\nST02_PERMISSION_SERVICE_MODE=on\n", "off, shadow or enforce"),
])
def test_deploy_refuses_bad_staging_parameters(tmp_path, staging_env, needle):
    base = tmp_path / "st"; base.mkdir(); (base / ".st02-staging-root").write_text("x")
    (base / "staging.env").write_text(staging_env)
    r = _deploy(tmp_path, base, "--initial")
    assert r.returncode == 3 and needle in r.stderr, r.stderr


def test_forced_failure_only_with_deploy(tmp_path):
    r = _deploy(tmp_path, tmp_path, "--initial", "--force-smoke-fail")
    assert r.returncode == 3


def test_sandbox_base_script_refuses_without_flag(tmp_path):
    r = subprocess.run(["bash", str(STAGING / "sandbox-base" / "prepare_sandbox_base_images.sh"),
                        "--ca", "/dev/null", "--report", str(tmp_path / "r")], capture_output=True, text=True)
    assert r.returncode == 2 and "--sandbox" in r.stderr


def test_ops_release_tools_are_not_modified_by_st02():
    """ST-02 adapts the logic in ops/staging; the production release tools stay byte-identical to main's."""
    r = subprocess.run(["git", "-C", str(REPO), "diff", "--name-only", "07da9aba0711c0b0784bee8e58c5669ce81a93c1",
                        "--", "ops/release", "ops/synology"], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("base commit not available in this clone")
    assert r.stdout.strip() == ""
