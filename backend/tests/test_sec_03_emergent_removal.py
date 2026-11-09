"""
SEC-03 — Emergent removal and SEC-SCAN hardening (Р75, Р76).

Backend items of docs/architecture/tasks/SEC-03_EMERGENT_REMOVAL_AND_HARDENING.md:

* M-1  JWT_SECRET fails closed: no known fallback, < 32 bytes refused outside an
       explicit test run, the application refuses to start (import fails).
* M-3  POST /api/internal/run-reminder-jobs: internal job key (constant-time) or
       Platform Admin; explicit tenant scope; one AuditEvent per tenant run.
* M-2  No emergentintegrations / EMERGENT_* anywhere in the app; one adapter
       (app/services/ai_provider.py) over the pinned official ``anthropic`` SDK;
       key and model only from env; without them, or with the tenant flag
       ``ai_enabled`` off (default), "AI не е настроен" — never a 500 — and the
       manual / rule-based paths keep working. ЕГН / IBAN never reach the model.

Every case has its positive and its forbidden side. DB-free (mongomock) except
for the subprocess start-up checks, which need no database at all.

    PYTHONPATH=. pytest --noconftest -q -p no:cacheprovider tests/test_sec_03_emergent_removal.py
"""
import asyncio
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from jose import jwt
from mongomock_motor import AsyncMongoMockClient

BACKEND = pathlib.Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
ORG_A, ORG_B = "org-sec03-a", "org-sec03-b"


def run(coro):
    return asyncio.run(coro)


def fresh_db():
    return AsyncMongoMockClient()["sec03_%s" % os.urandom(4).hex()]


# ════════════════════════════════════════════════════════════ M-1 JWT_SECRET
def _start(env_overrides, code="import app.deps.auth as a; print('STARTED', len(a.JWT_SECRET))"):
    env = {k: v for k, v in os.environ.items()
           if k not in ("JWT_SECRET", "PYTEST_VERSION", "ENV", "ENVIRONMENT", "PYTEST_CURRENT_TEST")}
    env.update(env_overrides)
    env["PYTHONPATH"] = str(BACKEND)
    return subprocess.run([sys.executable, "-c", code], cwd=str(BACKEND), env=env,
                          capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("label,overrides", [
    ("missing", {}),
    ("empty", {"JWT_SECRET": ""}),
    ("short-31", {"JWT_SECRET": "x" * 31}),
    ("old-default", {"JWT_SECRET": "dev-secret-key"}),
    ("missing-in-production", {"ENV": "production"}),
    ("short-in-production", {"ENV": "production", "JWT_SECRET": "short"}),
    ("missing-unknown-env", {"ENV": "qa-box"}),
])
def test_forbidden_the_server_refuses_to_start_without_a_strong_jwt_secret(label, overrides):
    r = _start(overrides)
    assert r.returncode != 0, (label, r.stdout, r.stderr)
    assert "JwtSecretMissing" in r.stderr and "STARTED" not in r.stdout, (label, r.stderr[-800:])


def test_forbidden_the_whole_application_refuses_to_start_without_jwt_secret():
    r = _start({"MONGO_URL": "mongodb://127.0.0.1:1"}, code="import server; print('STARTED')")
    assert r.returncode != 0 and "STARTED" not in r.stdout
    assert "JwtSecretMissing" in r.stderr


def test_positive_a_32_byte_secret_starts_and_is_the_key():
    secret = "s" * 32
    r = _start({"JWT_SECRET": secret}, code=(
        "import app.deps.auth as a; import app.utils.crypto as c; "
        "t = a.create_token({'user_id': 'u'}); "
        "print('STARTED', a.JWT_SECRET == %r, c.decode_token(t)['user_id'])" % secret))
    assert r.returncode == 0, r.stderr[-800:]
    assert "STARTED True u" in r.stdout


def test_positive_explicit_test_mode_starts_with_a_random_never_known_key():
    outs = []
    for _ in range(2):
        r = _start({"ENV": "test"}, code="import app.deps.auth as a; print('KEY', a.JWT_SECRET)")
        assert r.returncode == 0, r.stderr[-800:]
        outs.append(r.stdout.split("KEY ", 1)[1].strip())
    assert outs[0] != outs[1], "test-mode key must be per process, not a constant"
    for key in outs:
        assert len(key) >= 32 and key not in ("dev-secret-key", "dev-secret-key-NOT-FOR-PRODUCTION")


def test_no_known_fallback_secret_is_left_in_the_code():
    for rel in ("app/deps/auth.py", "app/utils/crypto.py"):
        src = (BACKEND / rel).read_text(encoding="utf-8")
        assert "dev-secret-key" not in src, rel


def test_forbidden_a_token_signed_with_the_old_default_is_refused(monkeypatch):
    from fastapi import HTTPException
    from app.deps import auth
    monkeypatch.setattr(auth, "JWT_SECRET", "k" * 48)
    forged = jwt.encode({"user_id": "u1", "org_id": ORG_A}, "dev-secret-key", algorithm="HS256")
    with pytest.raises(HTTPException) as exc:
        run(auth.get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=forged)))
    assert exc.value.status_code == 401


# ════════════════════════════════════════════════════════════ M-3 reminder trigger
KEY = "internal-job-key-" + "z" * 32
PLATFORM = {"id": "pa-1", "org_id": ORG_A, "role": "Admin", "email": "pa@x", "is_platform_admin": True}
TENANT_ADMIN = {"id": "ad-1", "org_id": ORG_A, "role": "Admin", "email": "ad@x"}
TOKENS = {"platform": PLATFORM, "admin": TENANT_ADMIN}


@pytest.fixture
def reminder(monkeypatch):
    from fastapi import HTTPException
    from app.routes import attendance
    db = fresh_db()
    run(db["organizations"].insert_many([{"id": ORG_A, "name": "A"}, {"id": ORG_B, "name": "B"}]))
    monkeypatch.setattr(attendance, "db", db)
    ran = []

    async def _for_org(org_id):
        ran.append(org_id)
    monkeypatch.setattr(attendance, "run_reminder_jobs_for_org", _for_org)

    async def _user(credentials):
        if credentials.credentials not in TOKENS:
            raise HTTPException(status_code=401, detail="Invalid token")
        return dict(TOKENS[credentials.credentials])
    monkeypatch.setattr(attendance, "get_current_user", _user)
    monkeypatch.delenv("INTERNAL_JOB_KEY", raising=False)
    app = FastAPI()
    app.include_router(attendance.router, prefix="/api")
    return TestClient(app, raise_server_exceptions=False), db, ran


def _events(db):
    from app.audit.store import AUDIT_COLLECTION
    return run(db[AUDIT_COLLECTION].find({"action": "reminder_jobs.triggered"}, {"_id": 0}).to_list(None))


URL = "/api/internal/run-reminder-jobs"


def test_forbidden_reminder_trigger_without_any_credential_is_401(reminder):
    client, db, ran = reminder
    for q in ("", "?all_tenants=true", "?tenant_id=" + ORG_A):
        r = client.post(URL + q)
        assert r.status_code == 401, (q, r.text)
    assert ran == [] and _events(db) == []


def test_forbidden_a_tenant_admin_is_not_a_platform_admin(reminder):
    client, db, ran = reminder
    r = client.post(URL + "?tenant_id=" + ORG_A, headers={"Authorization": "Bearer admin"})
    assert r.status_code == 403, r.text
    assert ran == [] and _events(db) == []


@pytest.mark.parametrize("configured,sent", [
    (None, KEY),                    # no key configured → the key path is closed
    ("", KEY),
    ("short-key", "short-key"),     # a configured key shorter than 32 bytes never works
    (KEY, KEY + "x"),
    (KEY, KEY[:-1]),
    (KEY, ""),
])
def test_forbidden_a_wrong_or_unconfigured_job_key_is_401(reminder, monkeypatch, configured, sent):
    client, db, ran = reminder
    if configured is not None:
        monkeypatch.setenv("INTERNAL_JOB_KEY", configured)
    r = client.post(URL + "?tenant_id=" + ORG_A, headers={"X-Internal-Job-Key": sent})
    assert r.status_code == 401, r.text
    assert ran == [] and _events(db) == []


def test_forbidden_no_implicit_all_tenant_run(reminder, monkeypatch):
    client, db, ran = reminder
    monkeypatch.setenv("INTERNAL_JOB_KEY", KEY)
    r = client.post(URL, headers={"X-Internal-Job-Key": KEY})
    assert r.status_code == 400, r.text
    r = client.post(URL + "?tenant_id=%s&all_tenants=true" % ORG_A, headers={"X-Internal-Job-Key": KEY})
    assert r.status_code == 400, r.text
    r = client.post(URL + "?tenant_id=org-nope", headers={"X-Internal-Job-Key": KEY})
    assert r.status_code == 404, r.text
    assert ran == [] and _events(db) == []


def test_positive_the_job_key_runs_exactly_one_tenant_with_an_audit_event(reminder, monkeypatch):
    client, db, ran = reminder
    monkeypatch.setenv("INTERNAL_JOB_KEY", KEY)
    r = client.post(URL + "?tenant_id=" + ORG_B, headers={"X-Internal-Job-Key": KEY})
    assert r.status_code == 200, r.text
    assert r.json()["tenants"] == 1 and ran == [ORG_B]
    [ev] = _events(db)
    assert ev["tenant_id"] == ORG_B and ev["actor_type"] == "system"
    assert ev["source_flow"] == "FLOW-013" and ev["structured_diff"] == {"scope": "tenant"}
    assert KEY not in json.dumps(ev, default=str)


def test_positive_a_platform_admin_runs_all_tenants_only_when_asked(reminder):
    client, db, ran = reminder
    r = client.post(URL + "?all_tenants=true", headers={"Authorization": "Bearer platform"})
    assert r.status_code == 200, r.text
    assert sorted(ran) == sorted([ORG_A, ORG_B])
    evs = _events(db)
    assert sorted(e["tenant_id"] for e in evs) == sorted([ORG_A, ORG_B])
    assert {(e["actor_type"], e["actor_id"]) for e in evs} == {("human", "pa-1")}


def test_the_comparison_is_constant_time():
    src = (BACKEND / "app/routes/attendance.py").read_text(encoding="utf-8")
    block = src[src.index("async def _internal_job_caller"):src.index("async def _reminder_trigger_event")]
    assert "hmac.compare_digest" in block and "== expected" not in block


# ════════════════════════════════════════════════════════════ M-2 AI provider
APP_FILES = sorted(p for p in (BACKEND / "app").rglob("*.py")) + [BACKEND / "server.py"]


def test_no_emergent_integration_is_left_in_the_application():
    hits = [str(p.relative_to(BACKEND)) for p in APP_FILES
            if re.search(r"emergentintegrations|EMERGENT_LLM_KEY|EMERGENT_API_KEY", p.read_text(encoding="utf-8"))]
    assert hits == []


MODEL_ID = re.compile(r"""["'](?:gpt-\d[\w.-]*|o\d-[\w-]+|claude-[a-z0-9.-]*\d[\w.-]*)["']""", re.I)
KEY_LIKE = re.compile(r"sk-ant-[\w-]{8,}|sk-emergent-[\w-]{8,}|sk-[A-Za-z0-9]{20,}")


def test_no_model_id_or_api_key_is_hard_coded_in_the_application():
    models = [(str(p.relative_to(BACKEND)), m.group(0)) for p in APP_FILES
              for m in MODEL_ID.finditer(p.read_text(encoding="utf-8"))]
    keys = [str(p.relative_to(BACKEND)) for p in APP_FILES if KEY_LIKE.search(p.read_text(encoding="utf-8"))]
    assert models == [] and keys == []


def test_the_official_sdk_is_pinned_to_an_exact_version():
    pins = [l.strip() for l in (BACKEND / "requirements.txt").read_text().splitlines()
            if l.strip().lower().startswith("anthropic")]
    assert len(pins) == 1 and re.fullmatch(r"anthropic==\d+\.\d+\.\d+", pins[0]), pins
    assert not any("emergentintegrations" in l for l in (BACKEND / "requirements.txt").read_text().splitlines())


class FakeMessages:
    def __init__(self, answer, fail=None):
        self.answer, self.fail, self.calls = answer, fail, []

    async def create(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise self.fail

        class Block:
            type, text = "text", self.answer

        class Resp:
            content = [Block()]
        return Resp()


class FakeClient:
    def __init__(self, answer="{}", fail=None):
        self.messages = FakeMessages(answer, fail)
        self.keys = []

    def __call__(self, api_key):
        self.keys.append(api_key)
        return self


@pytest.fixture
def ai(monkeypatch):
    """A tenant db, nothing configured, the SDK replaced by a fake (it must never be needed)."""
    from app.services import ai_provider
    db = fresh_db()
    monkeypatch.setattr(ai_provider, "db", db)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    fake = FakeClient()
    monkeypatch.setattr(ai_provider, "client_factory", fake)
    return ai_provider, db, fake


def configure(monkeypatch, db, *, key=True, model=True, enabled=True, org=ORG_A):
    if key:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-key-sec03")
    if model:
        monkeypatch.setenv("ANTHROPIC_MODEL", "configured-model-sec03")
    if enabled is not None:
        run(db["feature_flags"].insert_one({"org_id": org, "module_code": "ai_enabled", "enabled": enabled}))


@pytest.mark.parametrize("key,model,enabled,reason", [
    (False, False, None, "no_api_key"),
    (False, True, True, "no_api_key"),
    (True, False, True, "no_model"),
    (True, True, None, "disabled_for_tenant"),     # default: no flag row = off
    (True, True, False, "disabled_for_tenant"),
])
def test_forbidden_ai_is_not_configured_without_key_model_or_tenant_flag(ai, monkeypatch, key, model, enabled, reason):
    ai_provider, db, fake = ai
    configure(monkeypatch, db, key=key, model=model, enabled=enabled)
    with pytest.raises(ai_provider.AINotConfigured) as exc:
        run(ai_provider.complete(ORG_A, system="s", text="t"))
    assert exc.value.reason == reason and str(exc.value) == "AI не е настроен"
    assert fake.keys == [] and fake.messages.calls == []        # nothing left the server


def test_forbidden_another_tenants_flag_does_not_enable_ai(ai, monkeypatch):
    ai_provider, db, fake = ai
    configure(monkeypatch, db, org=ORG_B)
    with pytest.raises(ai_provider.AINotConfigured):
        run(ai_provider.complete(ORG_A, system="s", text="t"))
    assert fake.messages.calls == []


def test_positive_configured_and_enabled_calls_the_configured_model_with_minimised_text(ai, monkeypatch, caplog):
    ai_provider, db, fake = ai
    configure(monkeypatch, db)
    fake.messages.answer = '{"ok": 1}'
    text = "Иван, ЕГН 8001010000, IBAN BG80BNBG96611020345678, мазилка 12 м2"
    out = run(ai_provider.complete(ORG_A, system="sys", text=text, images=["/9j/4AAQSkZJRg" + "A" * 200]))
    assert out == '{"ok": 1}'
    assert fake.keys == ["test-only-key-sec03"]
    [call] = fake.messages.calls
    assert call["model"] == "configured-model-sec03" and call["system"] == "sys"
    blocks = call["messages"][0]["content"]
    assert blocks[0]["type"] == "image" and blocks[0]["source"]["media_type"] == "image/jpeg"
    sent = blocks[-1]["text"]
    assert "8001010000" not in sent and "BG80BNBG96611020345678" not in sent
    assert "мазилка 12 м2" in sent and sent.count("[скрито]") == 2
    assert "test-only-key-sec03" not in caplog.text
    assert ai_provider.model_and_version() == "anthropic/configured-model-sec03"


def test_forbidden_a_provider_failure_never_leaks_content_or_key(ai, monkeypatch, caplog):
    ai_provider, db, fake = ai
    configure(monkeypatch, db)
    fake.messages.fail = RuntimeError("upstream said: secret prompt ЕГН 8001010000 test-only-key-sec03")
    with pytest.raises(ai_provider.AIProviderError) as exc:
        run(ai_provider.complete(ORG_A, system="s", text="t"))
    assert "8001010000" not in str(exc.value) and "test-only-key-sec03" not in str(exc.value)
    assert "8001010000" not in caplog.text and "test-only-key-sec03" not in caplog.text


# ── the AI endpoints ──
ADMIN = {"id": "admin-1", "org_id": ORG_A, "role": "Admin", "email": "a@x", "first_name": "A", "last_name": "B"}
TECH = {"id": "tech-1", "org_id": ORG_A, "role": "Technician", "email": "t@x"}
IMG = "/9j/4AAQSkZJRg" + "A" * 300


def _client(monkeypatch, module, db, user):
    from app.deps.auth import get_current_user
    from app.deps.modules import require_m2
    monkeypatch.setattr(module, "db", db, raising=False)
    app = FastAPI()
    app.include_router(module.router, prefix="/api")

    async def _user():
        return dict(user)
    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[require_m2] = _user
    return TestClient(app, raise_server_exceptions=False)


def _observed(monkeypatch, module_name="app.master_data.intake_hooks"):
    from app.master_data import intake_hooks
    seen = []

    async def _observe(user, suggestion, source_ref=None, model_and_version=None):
        seen.append(model_and_version)
    monkeypatch.setattr(intake_hooks, "observe_ai_asset", _observe)
    return seen


def test_positive_and_not_configured_single_photo_intake(ai, monkeypatch):
    from app.routes import assets_ai_intake
    ai_provider, db, fake = ai
    seen = _observed(monkeypatch)
    client = _client(monkeypatch, assets_ai_intake, db, ADMIN)
    r = client.post("/api/assets/ai-intake", json={"image_base64": IMG})
    assert r.status_code == 503 and r.json()["detail"] == "AI не е настроен", r.text
    assert fake.messages.calls == [] and seen == []
    configure(monkeypatch, db)
    fake.messages.answer = json.dumps({"name": "Ъглошлайф", "type": "tool", "confidence": 80})
    r = client.post("/api/assets/ai-intake", json={"image_base64": IMG, "plate_image_base64": IMG})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Ъглошлайф" and r.json()["confidence"] == 80
    assert len(fake.messages.calls[0]["messages"][0]["content"]) == 3          # 2 photos + text
    assert seen == ["anthropic/configured-model-sec03"]


def test_forbidden_single_photo_intake_role_is_checked_before_any_ai_call(ai, monkeypatch):
    from app.routes import assets_ai_intake
    ai_provider, db, fake = ai
    configure(monkeypatch, db)
    r = _client(monkeypatch, assets_ai_intake, db, TECH).post("/api/assets/ai-intake", json={"image_base64": IMG})
    assert r.status_code == 403 and fake.messages.calls == []


def test_forbidden_a_provider_failure_is_502_not_500(ai, monkeypatch):
    from app.routes import assets_ai_intake
    ai_provider, db, fake = ai
    configure(monkeypatch, db)
    fake.messages.fail = RuntimeError("boom 8001010000")
    r = _client(monkeypatch, assets_ai_intake, db, ADMIN).post("/api/assets/ai-intake", json={"image_base64": IMG})
    assert r.status_code == 502 and "8001010000" not in r.text
    fake.messages.fail, fake.messages.answer = None, "not json"
    r = _client(monkeypatch, assets_ai_intake, db, ADMIN).post("/api/assets/ai-intake", json={"image_base64": IMG})
    assert r.status_code == 502


def test_positive_and_not_configured_batch_recognition(ai, monkeypatch):
    from app.routes import assets_batch_intake, assets_intake_pending, asset_item_types
    ai_provider, db, fake = ai
    seen = _observed(monkeypatch)

    async def can_submit(user):
        return True
    monkeypatch.setattr(assets_intake_pending, "_can_submit", can_submit)
    monkeypatch.setattr(asset_item_types, "db", db)
    client = _client(monkeypatch, assets_batch_intake, db, ADMIN)
    r = client.post("/api/assets/batch-intake/recognize", json={"images_base64": [IMG]})
    assert r.status_code == 503 and r.json()["detail"] == "AI не е настроен", r.text
    assert fake.messages.calls == []
    configure(monkeypatch, db)
    fake.messages.answer = json.dumps({"name": "Перфоратор", "type_label": "Бормашини", "confidence": 70})
    r = client.post("/api/assets/batch-intake/recognize", json={"images_base64": [IMG, IMG]})
    assert r.status_code == 200, r.text
    assert r.json()["suggestion"]["name"] == "Перфоратор"
    assert seen == ["anthropic/configured-model-sec03"]


def test_forbidden_batch_recognition_needs_the_intake_right_before_any_ai_call(ai, monkeypatch):
    from app.routes import assets_batch_intake, assets_intake_pending
    ai_provider, db, fake = ai
    configure(monkeypatch, db)

    async def cannot(user):
        return False
    monkeypatch.setattr(assets_intake_pending, "_can_submit", cannot)
    r = _client(monkeypatch, assets_batch_intake, db, TECH).post(
        "/api/assets/batch-intake/recognize", json={"images_base64": [IMG]})
    assert r.status_code == 403 and fake.messages.calls == []


def test_the_smr_proposal_falls_back_to_rules_when_ai_is_not_configured(ai, monkeypatch):
    from app.services import ai_proposal
    ai_provider, db, fake = ai
    monkeypatch.setattr("app.routes.ai_calibration.db", db, raising=False)
    res = run(ai_proposal.get_ai_proposal("Мазилка вътрешна", "м2", 20, None, ORG_A))
    assert res["provider"] != "llm" and "AI не е настроен" in res["fallback_reason"]
    assert fake.messages.calls == []
    configure(monkeypatch, db)
    fake.messages.answer = json.dumps({"activity_type": "Мокри процеси", "activity_subtype": "Мазилка",
                                       "material_price_per_unit": 8, "labor_price_per_unit": 12,
                                       "materials": []})
    res = run(ai_proposal.get_ai_proposal("Мазилка вътрешна", "м2", 20, None, ORG_A))
    assert res["provider"] == "llm" and res["pricing"]["total_price_per_unit"] == 20
    assert fake.messages.calls[0]["model"] == "configured-model-sec03"


def test_the_smr_breakdown_uses_the_manual_split_when_ai_is_not_configured(ai, monkeypatch):
    from app.routes import smr_analysis
    ai_provider, db, fake = ai
    run(db["smr_analyses"].insert_one({"id": "an-1", "org_id": ORG_A, "lines": [
        {"line_id": "l1", "smr_type": "Мазилка", "unit": "м2", "unit_price": 10}]}))
    client = _client(monkeypatch, smr_analysis, db, ADMIN)
    r = client.post("/api/smr-analyses/an-1/ai-breakdown")
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "fallback" and r.json()["error"] == "AI не е настроен"
    line = run(db["smr_analyses"].find_one({"id": "an-1"}))["lines"][0]
    assert (line["material_cena_per_unit"], line["trud_cena_per_unit"]) == (6.0, 4.0)
    assert fake.messages.calls == []


# ── the per-tenant flag ──
def _flags_client(monkeypatch, db, user):
    from app.routes import auth as auth_routes
    from app.deps.auth import get_current_user, require_platform_admin
    from fastapi import HTTPException
    monkeypatch.setattr(auth_routes, "db", db)

    async def _noop(*a, **kw):
        return None
    monkeypatch.setattr(auth_routes, "log_audit", _noop)
    app = FastAPI()
    app.include_router(auth_routes.router, prefix="/api")

    async def _user():
        return dict(user)

    async def _platform():
        if not user.get("is_platform_admin"):
            raise HTTPException(status_code=403, detail="Platform administrator access required")
        return dict(user)
    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[require_platform_admin] = _platform
    return TestClient(app, raise_server_exceptions=False)


def test_the_ai_flag_is_off_by_default_and_only_a_platform_admin_turns_it_on(ai, monkeypatch):
    ai_provider, db, fake = ai
    assert run(ai_provider.ai_enabled_for_tenant(ORG_A)) is False
    r = _flags_client(monkeypatch, db, TENANT_ADMIN).put(
        "/api/feature-flags", json={"module_code": "ai_enabled", "enabled": True})
    assert r.status_code == 403
    assert run(ai_provider.ai_enabled_for_tenant(ORG_A)) is False
    client = _flags_client(monkeypatch, db, PLATFORM)
    r = client.put("/api/feature-flags", json={"module_code": "ai_enabled", "enabled": True})
    assert r.status_code == 200, r.text
    assert run(ai_provider.ai_enabled_for_tenant(ORG_A)) is True
    assert run(ai_provider.ai_enabled_for_tenant(ORG_B)) is False
    r = client.put("/api/feature-flags", json={"module_code": "ai_enabled", "enabled": False})
    assert r.status_code == 200 and run(ai_provider.ai_enabled_for_tenant(ORG_A)) is False
    # a module code that does not exist is still refused (no upsert for modules)
    r = client.put("/api/feature-flags", json={"module_code": "M99", "enabled": True})
    assert r.status_code == 404


# ════════════════════════════════════════════════════════════ frontend template (H-1, M-4, L-6)
INDEX = REPO / "frontend" / "public" / "index.html"
NGINX = REPO / "nginx.conf"


def test_index_html_loads_no_third_party_script_and_no_emergent_trace():
    html = INDEX.read_text(encoding="utf-8")
    assert re.findall(r"<script[^>]*\bsrc=", html, re.I) == []
    assert "emergent" not in html.lower() and "debug-monitor" not in html and "cdn.tailwindcss.com" not in html
    assert "<title>BEG_Work</title>" in html


def test_csp_and_anti_framing_headers_are_set_for_production():
    conf = NGINX.read_text(encoding="utf-8")
    csp = re.search(r'add_header Content-Security-Policy "([^"]+)" always;', conf).group(1)
    assert "script-src 'self';" in csp and "frame-ancestors 'none'" in csp and "default-src 'self'" in csp
    assert "unsafe-eval" not in csp and "script-src 'self' 'unsafe-inline'" not in csp
    for header in ('X-Frame-Options "DENY" always', 'X-Content-Type-Options "nosniff" always',
                   'Referrer-Policy "strict-origin-when-cross-origin" always'):
        assert "add_header " + header in conf
    meta = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', INDEX.read_text(encoding="utf-8"))
    assert meta and "script-src 'self';" in meta.group(1)
