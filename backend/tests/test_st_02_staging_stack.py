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


def good_model(project=PROJECT, port=18080, mode="shadow"):
    return {
        "name": project,
        "services": {
            "backend": {"container_name": project + "-backend", "networks": {"st02": None},
                        "environment": {"ENV": "staging", "PERMISSION_SERVICE_MODE": mode,
                                        "MONGO_URL": "mongodb://mongo:27017/?replicaSet=rs0", "DB_NAME": "st02_staging",
                                        "BEG_SYSTEM_DB": "st02_staging_system", "JWT_SECRET": "synthetic",
                                        "PUBLIC_URL": "http://127.0.0.1:%s" % port,
                                        "CORS_ORIGINS": "http://127.0.0.1:%s" % port}},
            "frontend": {"container_name": project + "-frontend", "networks": {"st02": None},
                         "build": {"context": "./repo", "dockerfile": "../Dockerfile.frontend",
                                   "args": {"REACT_APP_BACKEND_URL": "http://127.0.0.1:%s" % port}},
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
    assert iso.check(good_model(), PROJECT, "18080", "shadow") == []


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
    errors = iso.check(m, PROJECT, "18080", "shadow")
    assert errors and any(needle in e for e in errors), errors


def test_isolation_refuses_non_staging_project():
    assert any("not a begwork-staging" in e for e in iso.check(good_model("begwork"), "begwork", "18080", "shadow"))


def test_isolation_main_never_prints_env_values(capsys, monkeypatch):
    m = good_model()
    m["services"]["backend"]["environment"]["JWT_SECRET"] = "SENTINEL-SECRET-VALUE"
    m["services"]["backend"]["environment"]["ENV"] = "SENTINEL-ENV-VALUE"
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps(m)))
    monkeypatch.setenv("ST02_PROJECT", PROJECT); monkeypatch.setenv("ST02_HTTP_PORT", "18080"); monkeypatch.setenv("ST02_MODE", "shadow")
    assert iso.main() == 1
    out = capsys.readouterr().out
    assert "ISOLATION FAIL" in out and "SENTINEL" not in out


# ------------------------------------------------------------ ST-02-C01 (audit ST02-1): production targets refused
STAGING_ROOT = "/srv/st02/begwork-staging"


def _benv(m, **kv):
    m["services"]["backend"]["environment"].update(kv)


def _bvol(m, src, svc="backend", vtype="bind"):
    m["services"][svc].setdefault("volumes", []).append({"type": vtype, "source": src, "target": "/x"})


C01_CASES = [
    # MONGO_URL: external / LAN / srv / localhost / host gateway / other port / other host
    ("srv-cluster", lambda m: _benv(m, MONGO_URL="mongodb+srv://u:p@prod-cluster.abcde.mongodb.net/begwork"), "mongodb+srv"),
    ("srv-no-creds", lambda m: _benv(m, MONGO_URL="mongodb+srv://cluster0.mongodb.net"), "mongodb+srv"),
    ("lan-ip", lambda m: _benv(m, MONGO_URL="mongodb://192.168.1.10:27017"), "LAN address"),
    ("lan-ip-in-replset", lambda m: _benv(m, MONGO_URL="mongodb://mongo:27017,10.0.0.5:27017/?replicaSet=rs0"), "LAN address"),
    ("ipv6", lambda m: _benv(m, MONGO_URL="mongodb://[fd00::5]:27017"), "IP address"),
    ("localhost", lambda m: _benv(m, MONGO_URL="mongodb://localhost:27017"), "LAN address"),
    ("host-gateway", lambda m: _benv(m, MONGO_URL="mongodb://host.docker.internal:27017"), "LAN address"),
    ("prod-container", lambda m: _benv(m, MONGO_URL="mongodb://begwork-mongo:27017"), "host other than"),
    ("nas-hostname", lambda m: _benv(m, MONGO_URL="mongodb://nas.local:27017"), "host other than"),
    ("other-port", lambda m: _benv(m, MONGO_URL="mongodb://mongo:27018"), "port other than"),
    ("creds-to-lan", lambda m: _benv(m, MONGO_URL="mongodb://admin:pw@192.168.1.10/begwork"), "LAN address"),
    ("bad-scheme", lambda m: _benv(m, MONGO_URL="http://mongo:27017"), "scheme"),
    ("missing-url", lambda m: m["services"]["backend"]["environment"].pop("MONGO_URL"), "MONGO_URL is missing"),
    ("second-url-key", lambda m: _benv(m, LEGACY_MONGO_URL="mongodb+srv://prod.mongodb.net"), "LEGACY_MONGO_URL"),
    # DB names
    ("db-begwork", lambda m: _benv(m, DB_NAME="begwork"), "production database name"),
    ("db-begwork-beg", lambda m: _benv(m, DB_NAME="begwork_beg"), "production database name"),
    ("db-begwork-family", lambda m: _benv(m, DB_NAME="begwork_staging_copy"), "production database name"),
    ("db-case", lambda m: _benv(m, DB_NAME="BEGWORK"), "production database name"),
    ("system-db", lambda m: _benv(m, BEG_SYSTEM_DB="begwork_system"), "BEG_SYSTEM_DB is a production"),
    ("missing-db", lambda m: m["services"]["backend"]["environment"].pop("DB_NAME"), "DB_NAME is missing"),
    # mounts
    ("bind-prod-root", lambda m: _bvol(m, "/volume1/docker/begwork"), "production root"),
    ("bind-prod-sub", lambda m: _bvol(m, "/volume1/docker/begwork/uploads"), "production root"),
    ("bind-prod-frontend", lambda m: _bvol(m, "/volume1/docker/begwork/.env", svc="frontend"), "production root"),
    ("bind-outside-root", lambda m: _bvol(m, "/home/user/data"), "outside the staging root"),
    ("bind-escape", lambda m: _bvol(m, STAGING_ROOT + "/../../etc"), "outside the staging root"),
    ("bind-root-itself", lambda m: _bvol(m, STAGING_ROOT), "outside the staging root"),
    ("bind-host-root", lambda m: _bvol(m, "/"), "host root"),
    ("docker-sock", lambda m: _bvol(m, "/var/run/docker.sock"), "Docker socket"),
    ("docker-sock-run", lambda m: _bvol(m, "/run/docker.sock", svc="mongo"), "Docker socket"),
    ("docker-run-dir", lambda m: _bvol(m, "/var/run"), "Docker socket"),
    ("external-volume", lambda m: (_bvol(m, "prod", vtype="volume"),
                                   m["volumes"].update(prod={"name": "begwork_uploads", "external": True})), "not an own"),
    ("anonymous-volume", lambda m: _bvol(m, "", vtype="volume"), "undeclared"),
    # privileges / host namespaces / network
    ("privileged", lambda m: m["services"]["backend"].update(privileged=True), "privileged"),
    ("privileged-mongo", lambda m: m["services"]["mongo"].update(privileged=True), "privileged"),
    ("cap-add", lambda m: m["services"]["backend"].update(cap_add=["SYS_ADMIN"]), "cap_add"),
    ("devices", lambda m: m["services"]["backend"].update(devices=[{"source": "/dev/sda", "target": "/dev/sda"}]), "devices"),
    ("seccomp-unconfined", lambda m: m["services"]["backend"].update(security_opt=["seccomp:unconfined"]), "security_opt"),
    ("pid-host", lambda m: m["services"]["backend"].update(pid="host"), "pid"),
    ("host-network-mode", lambda m: m["services"]["frontend"].update(network_mode="host"), "network_mode"),
    ("host-network-driver", lambda m: m["networks"]["st02"].update(driver="host"), "host driver"),
]


@pytest.mark.parametrize("mutate,needle", [c[1:] for c in C01_CASES], ids=[c[0] for c in C01_CASES])
def test_c01_isolation_refuses_production_targets(mutate, needle):
    m = copy.deepcopy(good_model())
    m["services"]["backend"]["volumes"] = [{"type": "bind", "source": STAGING_ROOT + "/uploads", "target": "/app/backend/uploads"}]
    assert iso.check(m, PROJECT, "18080", "shadow", base=STAGING_ROOT) == []
    mutate(m)
    errors = iso.check(m, PROJECT, "18080", "shadow", base=STAGING_ROOT)
    assert errors and any(needle in e for e in errors), errors


@pytest.mark.parametrize("port", ["80", "443", "8001", "8080", "27017", "1023", "70000", "", "x"])
def test_c01_isolation_refuses_production_ports(port):
    m = good_model(port=port)
    assert any("production/privileged port" in e for e in iso.check(m, PROJECT, port, "shadow"))


def test_c01_bind_mount_needs_known_staging_root():
    m = good_model()
    _bvol(m, STAGING_ROOT + "/uploads")
    assert any("ST02_BASE" in e for e in iso.check(m, PROJECT, "18080", "shadow"))
    assert iso.check(m, PROJECT, "18080", "shadow", base=STAGING_ROOT) == []


@pytest.mark.parametrize("allowed", ["nas-prod.lan", "staging-db.internal", "192.168.1.10", "*.mongodb.net", "mongo"])
def test_c02_fg6_allowed_mongo_hosts_is_refused(allowed):
    """FG-6: the allow-list let any hostname (e.g. nas-prod.lan) through; it is removed — a set value refuses."""
    m = good_model()
    _benv(m, MONGO_URL="mongodb://%s:27017/?replicaSet=rs0" % ("nas-prod.lan" if allowed.startswith(("*", "1")) else allowed))
    errors = iso.check(m, PROJECT, "18080", "shadow", allowed_mongo_hosts=allowed)
    assert any("ST02_ALLOWED_MONGO_HOSTS is not supported" in e for e in errors), errors
    # without the allow-list a foreign host stays refused, the own service passes
    assert any("host other than" in e for e in iso.check(m, PROJECT, "18080", "shadow")) or allowed == "mongo"
    assert iso.check(good_model(), PROJECT, "18080", "shadow", allowed_mongo_hosts="") == []


def test_c01_project_mongo_container_name_and_credentials_pass():
    m = good_model()
    _benv(m, MONGO_URL="mongodb://user:p%40ss@begwork-staging-mongo:27017/st02_staging?replicaSet=rs0")
    assert iso.check(m, PROJECT, "18080", "shadow") == []


def test_c01_main_refuses_with_nonzero_exit_and_never_prints_the_url(capsys, monkeypatch):
    m = good_model()
    _benv(m, MONGO_URL="mongodb+srv://SENTINEL-USER:SENTINEL-PW@prod-cluster.mongodb.net", DB_NAME="begwork")
    _bvol(m, "/volume1/docker/begwork")
    m["services"]["backend"]["privileged"] = True
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps(m)))
    monkeypatch.setenv("ST02_PROJECT", PROJECT); monkeypatch.setenv("ST02_HTTP_PORT", "18080"); monkeypatch.setenv("ST02_MODE", "shadow")
    monkeypatch.setenv("ST02_BASE", STAGING_ROOT)
    assert iso.main() == 1
    out = capsys.readouterr().out
    assert out.strip().endswith("ISOLATION FAIL")
    for needle in ("mongodb+srv", "production database name", "production root", "privileged"):
        assert needle in out, out
    assert "SENTINEL" not in out and "prod-cluster" not in out


def test_c01_audit_probe_model_is_fully_caught():
    """The nine hostile mutations of docs/audit/probes/st02/probe_st02_isolation.py are all refused."""
    base = good_model()
    base["services"]["backend"]["environment"]["DB_NAME"] = "st02_staging"
    probe = [
        lambda m: _benv(m, MONGO_URL="mongodb+srv://u:p@prod-cluster.mongodb.net"),
        lambda m: _benv(m, MONGO_URL="mongodb://192.168.1.10:27017"),
        lambda m: _benv(m, DB_NAME="begwork"),
        lambda m: m["services"]["backend"].update(volumes=[{"type": "bind", "source": "/volume1/docker/begwork", "target": "/data"}]),
        lambda m: m["services"]["backend"].update(volumes=[{"type": "bind", "source": "/var/run/docker.sock", "target": "/var/run/docker.sock"}]),
        lambda m: m["services"]["backend"].update(privileged=True),
        lambda m: m["services"]["mongo"].update(ports=[{"host_ip": "", "published": "27017", "target": 27017}]),
        lambda m: m["volumes"]["st02-mongo-data"].update(external=True, name="begwork_mongo_data"),
        lambda m: m["services"]["backend"].update(network_mode="host"),
    ]
    for i, fn in enumerate(probe):
        m = copy.deepcopy(base); fn(m)
        assert iso.check(m, PROJECT, "18080", "shadow", base=STAGING_ROOT), i


def test_c01_staging_deploy_passes_root_and_allow_list_to_the_check():
    sh = (STAGING / "staging_deploy.sh").read_text()
    assert '-e ST02_BASE="$root"' in sh and "ST02_ALLOWED_MONGO_HOSTS" in sh
    # the check runs before any container action and a refusal exits 3
    i_iso = sh.index('assert_isolated || {'); i_up = sh.index('compose_up "$REBUILD"')
    assert i_iso < i_up and "exit 3; }" in sh[i_iso:i_iso + 120]


_HAS_COMPOSE = shutil.which("docker") is not None and subprocess.run(
    ["docker", "compose", "version"], capture_output=True).returncode == 0


def _real_staging_root(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "check_port", lambda port: None)
    base, _ = up.prepare_base(tmp_path / "st", PROJECT, 18555, "shadow")
    for name in ("docker-compose.yml", "Dockerfile.backend", "Dockerfile.frontend"):
        shutil.copyfile(PROD_LAYOUT / name, base / name)
    return base


@pytest.mark.skipif(not _HAS_COMPOSE, reason="docker compose not installed")
def test_c01_default_staging_up_root_passes(tmp_path, monkeypatch):
    """The layout root exactly as staging_up.py prepares it passes the full check (real compose config)."""
    base = _real_staging_root(tmp_path, monkeypatch)
    up.assert_isolated(base, PROJECT)  # does not raise
    calls = []
    monkeypatch.setattr(up, "compose", lambda *a, **k: calls.append(a) or subprocess.CompletedProcess(a, 0, "", ""))
    monkeypatch.setattr(up, "run", lambda cmd, check=True, **k: subprocess.CompletedProcess(cmd, 0, "1" if "ping" in str(cmd) else "true", ""))
    up.mongo_up(base, PROJECT)  # the gate passes, then mongo would start
    assert calls and calls[0][2:] == ("up", "-d", "--no-deps", "mongo")


@pytest.mark.skipif(not _HAS_COMPOSE, reason="docker compose not installed")
@pytest.mark.parametrize("edit,needle", [
    ("MONGO_URL=mongodb+srv://u:p@prod-cluster.mongodb.net/begwork", "mongodb+srv"),
    ("MONGO_URL=mongodb://192.168.1.10:27017", "LAN address"),
    ("DB_NAME=begwork", "production database name"),
])
def test_c01_hand_edited_env_refused_before_anything_starts(tmp_path, monkeypatch, edit, needle):
    """A copied/hand-edited production .env: up refuses BEFORE the staging MongoDB starts."""
    base = _real_staging_root(tmp_path, monkeypatch)
    key = edit.split("=", 1)[0]
    lines = [l for l in (base / ".env").read_text().splitlines() if not l.startswith(key + "=")]
    (base / ".env").write_text("\n".join(lines + [edit]) + "\n")
    started = []
    monkeypatch.setattr(up, "compose", lambda *a, **k: started.append(a))
    monkeypatch.setattr(up, "run", lambda *a, **k: started.append(a))
    with pytest.raises(up.Refused) as ei:
        up.mongo_up(base, PROJECT)
    msg = str(ei.value)
    assert "ISOLATION FAIL, nothing was started" in msg and needle in msg
    assert "prod-cluster" not in msg and "192.168" not in msg
    assert started == []


@pytest.mark.skipif(not _HAS_COMPOSE, reason="docker compose not installed")
def test_c01_overlay_with_prod_bind_privileged_socket_refused(tmp_path, monkeypatch):
    base = _real_staging_root(tmp_path, monkeypatch)
    text = (base / "docker-compose.staging.yml").read_text().replace(
        "  backend:\n    container_name: ${ST02_PROJECT}-backend\n",
        "  backend:\n    container_name: ${ST02_PROJECT}-backend\n    privileged: true\n    volumes:\n"
        "      - /volume1/docker/begwork:/prod\n      - /var/run/docker.sock:/var/run/docker.sock\n")
    (base / "docker-compose.staging.yml").write_text(text)
    with pytest.raises(up.Refused) as ei:
        up.assert_isolated(base, PROJECT)
    for needle in ("privileged", "production root", "Docker socket"):
        assert needle in str(ei.value), str(ei.value)


# ------------------------------------------------------------ ST-02-C02: R15 shadow default (FG-2)
def _parsed(monkeypatch, argv):
    got = []
    for name in ("cmd_up", "cmd_deploy", "cmd_rehearse"):
        monkeypatch.setattr(up, name, lambda a, _g=got: _g.append(a) or 0)
    assert up.main(argv) == 0
    return got[0]


@pytest.mark.parametrize("argv", [
    ["up", "--base", "/tmp/x"],
    ["deploy", "--base", "/tmp/x", "--commit", "HEAD"],
    ["rehearse", "--base", "/tmp/x", "--from", "A", "--to", "B", "--evidence", "/tmp/e"],
])
def test_c02_default_permission_mode_is_shadow(monkeypatch, argv):
    assert up.DEFAULT_MODE == "shadow"
    assert _parsed(monkeypatch, argv).permission_mode == "shadow"


@pytest.mark.parametrize("mode", ["enforce", "off", "shadow"])
def test_c02_other_modes_only_by_explicit_parameter(monkeypatch, mode):
    assert _parsed(monkeypatch, ["up", "--base", "/tmp/x", "--permission-mode", mode]).permission_mode == mode


def test_c02_prepare_base_default_is_shadow(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "check_port", lambda port: None)
    base, _ = up.prepare_base(tmp_path / "st", PROJECT, 18555)
    assert up.read_kv(base / "staging.env")["ST02_PERMISSION_SERVICE_MODE"] == "shadow"
    assert up.read_kv(base / ".env")["ST02_PERMISSION_SERVICE_MODE"] == "shadow"
    with pytest.raises(up.Refused):
        up.prepare_base(tmp_path / "st2", PROJECT, 18556, "on")


def test_c02_explicit_enforce_is_kept_and_logged(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(up, "check_port", lambda port: None)
    base, _ = up.prepare_base(tmp_path / "st", PROJECT, 18555, up.check_mode("enforce"))
    assert up.read_kv(base / "staging.env")["ST02_PERMISSION_SERVICE_MODE"] == "enforce"
    assert "EXPLICIT --permission-mode" in capsys.readouterr().out
    # a root prepared with enforce is not silently reused as shadow (and vice versa)
    with pytest.raises(up.Refused):
        up.prepare_base(base, PROJECT, 18555)


def test_c02_isolation_default_mode_is_shadow(capsys, monkeypatch):
    assert iso.DEFAULT_MODE == "shadow"
    assert iso.check(good_model(mode="shadow"), PROJECT, "18080") == []
    assert any("PERMISSION_SERVICE_MODE" in e for e in iso.check(good_model(mode="enforce"), PROJECT, "18080"))
    assert any("off/shadow/enforce" in e for e in iso.check(good_model(mode="on"), PROJECT, "18080", "on"))
    monkeypatch.delenv("ST02_MODE", raising=False)
    monkeypatch.setenv("ST02_PROJECT", PROJECT); monkeypatch.setenv("ST02_HTTP_PORT", "18080")
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps(good_model(mode="shadow"))))
    assert iso.main() == 0 and "flag = parameter (shadow)" in capsys.readouterr().out
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps(good_model(mode="enforce"))))
    assert iso.main() == 1


def test_c02_overlay_defaults_to_shadow_text():
    text = (STAGING / "deploy" / "docker-compose.staging.yml").read_text()
    assert "PERMISSION_SERVICE_MODE: ${ST02_PERMISSION_SERVICE_MODE:-shadow}" in text
    readme = (STAGING / "README.md").read_text()
    assert "default `enforce`" not in readme and "default `shadow`" in readme
    src = (STAGING / "staging_up.py").read_text()
    assert 'default="enforce"' not in src


@pytest.mark.skipif(not _HAS_COMPOSE, reason="docker compose not installed")
def test_c02_real_compose_without_mode_runs_shadow(tmp_path):
    for name in ("docker-compose.yml", "Dockerfile.backend", "Dockerfile.frontend"):
        shutil.copyfile(PROD_LAYOUT / name, tmp_path / name)
    shutil.copyfile(STAGING / "deploy" / "docker-compose.staging.yml", tmp_path / "docker-compose.staging.yml")
    (tmp_path / ".env").write_text("PUBLIC_URL=http://127.0.0.1:18555\nCORS_ORIGINS=http://127.0.0.1:18555\n"
                                   "ST02_PROJECT=begwork-staging\nST02_HTTP_PORT=18555\n"
                                   "MONGO_URL=mongodb://mongo:27017/?replicaSet=rs0\nDB_NAME=st02_staging\n")
    r = subprocess.run(["docker", "compose", "-p", PROJECT, "-f", "docker-compose.yml", "-f", "docker-compose.staging.yml",
                        "config", "--format", "json"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    model = json.loads(r.stdout)
    assert model["services"]["backend"]["environment"]["PERMISSION_SERVICE_MODE"] == "shadow"
    assert iso.check(model, PROJECT, "18555", "", base=str(tmp_path)) == []


# ------------------------------------------------------------ ST-02-C02: FG-5 URLs and bootstrap keys
FG5_CASES = [
    ("public-url-prod", lambda m: _benv(m, PUBLIC_URL="https://begwork.example.com"), "backend PUBLIC_URL"),
    ("public-url-other-port", lambda m: _benv(m, PUBLIC_URL="http://127.0.0.1:8080"), "backend PUBLIC_URL"),
    ("public-url-lan", lambda m: _benv(m, PUBLIC_URL="http://192.168.1.10:8080"), "backend PUBLIC_URL"),
    ("public-url-missing", lambda m: m["services"]["backend"]["environment"].pop("PUBLIC_URL"), "PUBLIC_URL is missing"),
    ("cors-prod", lambda m: _benv(m, CORS_ORIGINS="https://begwork.example.com"), "backend CORS_ORIGINS"),
    ("cors-mixed", lambda m: _benv(m, CORS_ORIGINS="http://127.0.0.1:18080,https://begwork.example.com"), "backend CORS_ORIGINS"),
    ("cors-wildcard", lambda m: _benv(m, CORS_ORIGINS="*"), "backend CORS_ORIGINS"),
    ("build-arg-prod", lambda m: m["services"]["frontend"]["build"]["args"].update(
        REACT_APP_BACKEND_URL="https://begwork.example.com"), "REACT_APP_BACKEND_URL"),
    ("build-arg-missing", lambda m: m["services"]["frontend"]["build"]["args"].pop("REACT_APP_BACKEND_URL"),
     "REACT_APP_BACKEND_URL is missing"),
    ("frontend-env-prod", lambda m: m["services"]["frontend"].update(
        environment={"REACT_APP_BACKEND_URL": "https://begwork.example.com"}), "frontend REACT_APP_BACKEND_URL"),
    ("bootstrap-token", lambda m: _benv(m, PLATFORM_BOOTSTRAP_TOKEN="x"), "bootstrap/seed-admin"),
    ("seed-admin-email", lambda m: _benv(m, SEED_ADMIN_EMAIL="a@b.c"), "bootstrap/seed-admin"),
    ("seed-admin-password", lambda m: _benv(m, SEED_ADMIN_PASSWORD="x"), "bootstrap/seed-admin"),
    ("bootstrap-on-mongo", lambda m: m["services"]["mongo"].update(environment={"PLATFORM_BOOTSTRAP_TOKEN": "x"}),
     "service mongo environment has bootstrap"),
]


@pytest.mark.parametrize("mutate,needle", [c[1:] for c in FG5_CASES], ids=[c[0] for c in FG5_CASES])
def test_c02_fg5_urls_and_bootstrap_keys_refused(mutate, needle):
    m = copy.deepcopy(good_model())
    assert iso.check(m, PROJECT, "18080") == []
    mutate(m)
    errors = iso.check(m, PROJECT, "18080")
    assert errors and any(needle in e for e in errors), errors
    assert not any("begwork.example.com" in e or "192.168" in e for e in errors)


def test_c02_fg5_localhost_and_trailing_slash_pass():
    m = good_model()
    _benv(m, PUBLIC_URL="http://localhost:18080/", CORS_ORIGINS="http://127.0.0.1:18080,http://localhost:18080")
    assert iso.check(m, PROJECT, "18080") == []


@pytest.mark.skipif(not _HAS_COMPOSE, reason="docker compose not installed")
@pytest.mark.parametrize("edit,needle", [
    ("PUBLIC_URL=https://begwork.example.com", "REACT_APP_BACKEND_URL"),
    ("CORS_ORIGINS=https://begwork.example.com", "backend CORS_ORIGINS"),
    ("PLATFORM_BOOTSTRAP_TOKEN=synthetic", "bootstrap/seed-admin"),
])
def test_c02_fg5_hand_edited_env_refused_before_anything_starts(tmp_path, monkeypatch, edit, needle):
    base = _real_staging_root(tmp_path, monkeypatch)
    key = edit.split("=", 1)[0]
    lines = [l for l in (base / ".env").read_text().splitlines() if not l.startswith(key + "=")]
    (base / ".env").write_text("\n".join(lines + [edit]) + "\n")
    started = []
    monkeypatch.setattr(up, "compose", lambda *a, **k: started.append(a))
    monkeypatch.setattr(up, "run", lambda *a, **k: started.append(a))
    with pytest.raises(up.Refused) as ei:
        up.mongo_up(base, PROJECT)
    assert needle in str(ei.value) and "begwork.example.com" not in str(ei.value)
    assert started == []


# ------------------------------------------------------------ ST-02-C02: FG-4 deployed_by / approved_by
@pytest.mark.parametrize("argv", [
    ["up", "--base", "/tmp/x"],
    ["up", "--base", "/tmp/x", "--deployed-by", "krum"],
    ["up", "--base", "/tmp/x", "--deployed-by", "unknown", "--approved-by", "krum"],
    ["deploy", "--base", "/tmp/x", "--commit", "HEAD", "--deployed-by", "a b", "--approved-by", "krum"],
    ["rehearse", "--base", "/tmp/x", "--from", "A", "--to", "B", "--evidence", "/tmp/e", "--approved-by", "krum"],
])
def test_c02_fg4_deployer_and_approver_required(argv, capsys):
    assert up.main(argv) == 2
    assert "is required" in capsys.readouterr().err


def test_c02_fg4_build_bundle_names_deployer_and_approver(tmp_path, monkeypatch):
    (tmp_path / "staging.env").write_text("ST02_PERMISSION_SERVICE_MODE=shadow\n")
    seen = []
    monkeypatch.setattr(up, "run", lambda cmd, check=True, **k: seen.append(cmd) or (_ for _ in ()).throw(up.Refused("stop")))
    with pytest.raises(up.Refused):
        up.build_bundle(tmp_path, "HEAD", "origin/main", None, deployed_by="alice", approved_by="krum")
    cmd = seen[0]
    assert cmd[cmd.index("--created-by") + 1] == "alice"
    assert "deploy:approved_by=krum" in cmd
    # R26: the staging mode goes into the Release Manifest's feature_flags snapshot
    assert cmd[cmd.index("--flag-override") + 1] == "PERMISSION_SERVICE_MODE=shadow"
    assert cmd[cmd.index("--flag-override-reason") + 1] == "R15 staging default"
    with pytest.raises(up.Refused, match="--approved-by is required"):
        up.build_bundle(tmp_path, "HEAD", "origin/main", None, deployed_by="alice")
    with pytest.raises(up.Refused, match="--deployed-by is required"):
        up.staging_deploy(tmp_path, tmp_path, "initial", approved_by="krum")


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
    base, created = up.prepare_base(tmp_path / "st", PROJECT, 18555, "shadow")
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
    assert st == {"ST02_PERMISSION_SERVICE_MODE": "shadow", "ST02_HTTP_PORT": "18555", "ST02_PROJECT": PROJECT}
    assert (base / "docker-compose.staging.yml").read_bytes() == (STAGING / "deploy" / "docker-compose.staging.yml").read_bytes()
    # a second prepare with other parameters is refused; with the same ones it is reused
    with pytest.raises(up.Refused):
        up.prepare_base(base, PROJECT, 18556, "shadow")
    with pytest.raises(up.Refused):
        up.prepare_base(base, PROJECT, 18555, "off")
    assert up.prepare_base(base, PROJECT, 18555, "shadow") == (base, False)
    # the JWT secret is not regenerated on reuse
    assert up.read_kv(base / ".env")["JWT_SECRET"] == env["JWT_SECRET"]


def test_prepare_base_refuses_foreign_non_empty_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "check_port", lambda port: None)
    (tmp_path / "x").mkdir(); (tmp_path / "x" / "docker-compose.yml").write_text("services: {}\n")
    with pytest.raises(up.Refused, match="not an ST-02 staging root"):
        up.prepare_base(tmp_path / "x", PROJECT, 18555, "shadow")


def test_secret_scan_finds_leaks(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "check_port", lambda port: None)
    base, _ = up.prepare_base(tmp_path / "st", PROJECT, 18555, "shadow")
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
                                   "ST02_HTTP_PORT=18555\nST02_PERMISSION_SERVICE_MODE=shadow\n")
    base_cmd = ["docker", "compose", "-p", PROJECT, "-f", "docker-compose.yml", "-f", "docker-compose.staging.yml"]
    with (tmp_path / ".env").open("a") as f:
        f.write("MONGO_URL=mongodb://mongo:27017/?replicaSet=rs0\nDB_NAME=st02_staging\n")
    r = subprocess.run(base_cmd + ["config", "--format", "json"], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    model = json.loads(r.stdout)
    assert iso.check(model, PROJECT, "18555", "shadow", base=str(tmp_path)) == []
    assert model["services"]["backend"]["build"]["dockerfile"] == "../Dockerfile.backend"  # same production build
    # without the overlay the model is production-shaped and the check refuses it
    r2 = subprocess.run(["docker", "compose", "-p", PROJECT, "-f", "docker-compose.yml", "config", "--format", "json"],
                        cwd=tmp_path, capture_output=True, text=True)
    assert r2.returncode == 0, r2.stderr
    errs = iso.check(json.loads(r2.stdout), PROJECT, "18555", "shadow", base=str(tmp_path))
    assert any("production container name" in e for e in errs) and any("8080" in e for e in errs)


# ------------------------------------------------------------ staging_deploy.sh refusals (before any docker call)
def _fake_bundle(tmp_path):
    b = tmp_path / "bundle"; (b / "tools" / "synology").mkdir(parents=True)
    shutil.copyfile(REPO / "ops" / "release" / "synology" / "lib.sh", b / "tools" / "synology" / "lib.sh")
    return b


def _deploy(tmp_path, base, *args, **extra_env):
    env = dict(os.environ, BEGWORK_BASE=str(base), DOCKER="/bin/false")
    for k in ("ST02_DEPLOYED_BY", "ST02_APPROVED_BY", "SUDO_USER"):
        env.pop(k, None)
    env.update(extra_env)
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
    ("ST02_PROJECT=begwork\nST02_HTTP_PORT=18080\nST02_PERMISSION_SERVICE_MODE=shadow\n", "begwork-staging"),
    ("ST02_PROJECT=begwork-staging\nST02_HTTP_PORT=8080\nST02_PERMISSION_SERVICE_MODE=shadow\n", "8080"),
    ("ST02_PROJECT=begwork-staging\nST02_HTTP_PORT=18080\nST02_PERMISSION_SERVICE_MODE=on\n", "off, shadow or enforce"),
])
def test_deploy_refuses_bad_staging_parameters(tmp_path, staging_env, needle):
    base = tmp_path / "st"; base.mkdir(); (base / ".st02-staging-root").write_text("x")
    (base / "staging.env").write_text(staging_env)
    r = _deploy(tmp_path, base, "--initial")
    assert r.returncode == 3 and needle in r.stderr, r.stderr


def _st_base(tmp_path, staging_env):
    base = tmp_path / "st"; base.mkdir(); (base / ".st02-staging-root").write_text("x")
    (base / "staging.env").write_text(staging_env)
    (base / "docker-compose.yml").write_text("services: {}\n")
    return base


@pytest.mark.parametrize("who", [{}, {"ST02_DEPLOYED_BY": "alice"}, {"ST02_APPROVED_BY": "krum"},
                                 {"ST02_DEPLOYED_BY": "unknown", "ST02_APPROVED_BY": "krum"},
                                 {"ST02_DEPLOYED_BY": "alice", "ST02_APPROVED_BY": "a;rm"}])
def test_c02_fg4_deploy_refuses_without_named_people(tmp_path, who):
    base = _st_base(tmp_path, "ST02_PROJECT=begwork-staging\nST02_HTTP_PORT=18080\n")
    r = _deploy(tmp_path, base, "--initial", **who)
    assert r.returncode == 3 and "is required" in r.stderr, r.stderr
    assert not (base / "release-state").exists()  # refused before lib.sh created anything


def test_c02_deploy_without_mode_runs_shadow_with_named_actor(tmp_path):
    """staging.env without a mode: staging_deploy.sh takes shadow (R15 default), the actor is the named deployer."""
    base = _st_base(tmp_path, "ST02_PROJECT=begwork-staging\nST02_HTTP_PORT=18080\n")
    r = _deploy(tmp_path, base, "--initial", ST02_DEPLOYED_BY="alice", ST02_APPROVED_BY="krum",
                RELEASE_PY_MODE="local", RELEASE_PYTHON=sys.executable, USER="someone-else", SUDO_USER="root")
    out = r.stdout + r.stderr
    assert "PERMISSION_SERVICE_MODE=shadow (R15 default)" in out, out
    assert "actor=alice" in out and "deployed_by=alice approved_by=krum" in out
    assert r.returncode == 2  # then the (fake) bundle fails verification; nothing changed


def test_c02_deploy_explicit_enforce_is_labelled(tmp_path):
    base = _st_base(tmp_path, "ST02_PROJECT=begwork-staging\nST02_HTTP_PORT=18080\nST02_PERMISSION_SERVICE_MODE=enforce\n")
    r = _deploy(tmp_path, base, "--initial", ST02_DEPLOYED_BY="alice", ST02_APPROVED_BY="krum",
                RELEASE_PY_MODE="local", RELEASE_PYTHON=sys.executable)
    assert "PERMISSION_SERVICE_MODE=enforce (explicit staging parameter)" in r.stdout + r.stderr


def test_c02_fg3_observed_flag_is_checked_and_recorded():
    """FG-3: after the smoke the running flag must equal the staging parameter (unset refused) and the
    manifest expectation, parameter and observed value are written side by side."""
    sh = (STAGING / "staging_deploy.sh").read_text()
    assert 'observe_flag || initial_fail "$FLAG_FAIL"' in sh and 'observe_flag || auto_rollback "$FLAG_FAIL"' in sh
    i_smoke = sh.index('smoke "$DEPLOY_SINCE" "$REBUILD" "$C_RUNTIME_IMAGES" || auto_rollback')
    assert i_smoke < sh.index('observe_flag || auto_rollback') < sh.index("write_record deploy DEPLOYED")
    assert 'OBSERVED_FLAG="UNSET"' in sh
    for key in ('"manifest_expected"', '"staging_parameter"', '"observed_in_backend"', '"deployed_by"', '"approved_by"'):
        assert key in sh
    assert sh.index("write_record deploy DEPLOYED") < sh.index("staging_record DEPLOYED")


def test_forced_failure_only_with_deploy(tmp_path):
    r = _deploy(tmp_path, tmp_path, "--initial", "--force-smoke-fail")
    assert r.returncode == 3


def test_sandbox_base_script_refuses_without_flag(tmp_path):
    r = subprocess.run(["bash", str(STAGING / "sandbox-base" / "prepare_sandbox_base_images.sh"),
                        "--ca", "/dev/null", "--report", str(tmp_path / "r")], capture_output=True, text=True)
    assert r.returncode == 2 and "--sandbox" in r.stderr


# R26 (ST-02-C03): the only ops/release change is the backward-compatible flag override in
# release_build.py + its validator rule, docs and tests; deploy/rollback shell tools and ops/synology
# stay byte-identical to main's.
R26_RELEASE_FILES = {"ops/release/release_build.py", "ops/release/beg_release/manifest.py",
                     "ops/release/release_manifest.schema.json", "ops/release/README.md",
                     "ops/release/tests/test_artifact.py"}


def test_ops_release_tools_are_not_modified_by_st02():
    """ST-02 adapts the logic in ops/staging; only the R26 manifest files of ops/release change."""
    r = subprocess.run(["git", "-C", str(REPO), "diff", "--name-only", "07da9aba0711c0b0784bee8e58c5669ce81a93c1",
                        "--", "ops/release", "ops/synology"], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("base commit not available in this clone")
    changed = set(r.stdout.split())
    assert changed <= R26_RELEASE_FILES, sorted(changed - R26_RELEASE_FILES)
    assert not any(p.startswith(("ops/synology/", "ops/release/synology/")) for p in changed)


def test_c03_r25_no_external_mongo_option_in_the_tools():
    """R25 (Krum, 06.11.2026): staging uses only its own MongoDB. The FG-6 tests above prove a set
    ST02_ALLOWED_MONGO_HOSTS refuses; here: no tool offers the option as a way in."""
    assert "--allowed-mongo-hosts" not in (STAGING / "staging_up.py").read_text()
    assert "ST02_ALLOWED_MONGO_HOSTS" not in (STAGING / "deploy" / "docker-compose.staging.yml").read_text()


# ------------------------------------------------------------ R26: mode in the Release Manifest (real bundles)
@pytest.fixture(scope="module")
def r26_bundles(tmp_path_factory):
    """Real staging bundles of HEAD: one with the staging mode, one whose manifest disagrees."""
    if shutil.which("git") is None:
        pytest.skip("git not available")
    root = tmp_path_factory.mktemp("r26")
    port = 18000 + (os.getpid() % 900)
    base, _ = up.prepare_base(root / "st", PROJECT, port, "shadow")
    who = {"deployed_by": "alice", "approved_by": "krum"}
    good, gs = up.build_bundle(base, "HEAD", "HEAD", None, allow_unmerged=True, **who)
    bad, _ = up.build_bundle(base, "HEAD", "HEAD", None, allow_unmerged=True, manifest_mode="enforce", **who)
    up.install_layout_files(base, good)
    return base, good, bad, gs


def test_c03_r26_manifest_records_the_staging_mode(r26_bundles):
    base, good, bad, gs = r26_bundles
    for bundle, mode in ((good, "shadow"), (bad, "enforce")):
        doc = json.loads((bundle / "manifest.json").read_text())
        spec = doc["release"]["feature_flags"]["PERMISSION_SERVICE_MODE"]
        assert spec["expected"] == mode
        assert spec["source"].startswith("deployment parameter (staging): ") and "layout default off" in spec["source"]
        assert doc["release"]["environment"] == "staging"
    assert gs["feature_flags"]["PERMISSION_SERVICE_MODE"]["expected"] == "shadow"
    assert "R15 staging default" in gs["feature_flags"]["PERMISSION_SERVICE_MODE"]["source"]


def _r26_deploy(base, bundle):
    env = dict(os.environ, BEGWORK_BASE=str(base), DOCKER="/bin/false", RELEASE_PY_MODE="local",
               RELEASE_PYTHON=sys.executable, ST02_DEPLOYED_BY="alice", ST02_APPROVED_BY="krum")
    return subprocess.run(["bash", str(STAGING / "staging_deploy.sh"), "--bundle", str(bundle), "--initial"],
                          env=env, capture_output=True, text=True)


def test_c03_r26_manifest_mode_mismatch_is_refused_before_any_change(r26_bundles):
    base, good, bad, _ = r26_bundles
    r = _r26_deploy(base, bad)
    out = r.stdout + r.stderr
    assert r.returncode == 2, out
    assert "Release Manifest records PERMISSION_SERVICE_MODE=enforce, staging parameter is shadow" in out, out
    assert "NOTHING WAS CHANGED" in out
    assert not (base / "repo").exists() and not (base / "release-state" / "current.env").exists()
    rec = sorted((base / "release-state" / "history").glob("*-deploy-*/record.json"))[-1]
    assert json.loads(rec.read_text())["status"] == "PRECHECK_FAILED"


def test_c03_r26_matching_manifest_passes_the_r26_precheck(r26_bundles):
    base, good, bad, _ = r26_bundles
    r = _r26_deploy(base, good)
    out = r.stdout + r.stderr
    assert "R26: Release Manifest (P) PERMISSION_SERVICE_MODE=shadow = staging parameter (explicit staging parameter)" in out, out
    assert "Release Manifest records" not in out
    assert r.returncode == 3  # next step: the isolation check needs Docker (here /bin/false) -> refused, nothing started
    assert not (base / "repo").exists()


def test_c03_r26_deploy_checks_manifest_backend_and_rollback_target():
    sh = (STAGING / "staging_deploy.sh").read_text()
    assert 'S_FLAG_EXPECT_PERMISSION_SERVICE_MODE="$ST_ST02_PERMISSION_SERVICE_MODE"' not in sh  # no mapping any more
    i_p = sh.index('manifest_flag_matches P || staging_fail')
    assert i_p < sh.index('assert_isolated || { log "REFUSED')
    assert 'manifest_flag_matches C || staging_fail "rollback target: $STAGE_FAIL"' in sh
    assert 'Release Manifest records ${!expect_var:-?}' in sh  # observed != manifest -> FLAG_FAIL -> rollback
    assert 'observe_flag C ||' in sh
    for key in ('"live_release_id"', '"live_release_sha256"', '"live_manifest_feature_flags"',
                '"observed_equals_manifest"', '"manifest_equals_parameter"'):
        assert key in sh

