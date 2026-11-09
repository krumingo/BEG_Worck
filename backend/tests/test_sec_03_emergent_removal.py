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
    # FG-516: no deployment label is a test mode — only the pytest runner is.
    ("missing-ENV-test", {"ENV": "test"}),
    ("missing-ENV-development", {"ENV": "development"}),
    ("missing-ENV-local", {"ENV": "local"}),
    ("missing-ENVIRONMENT-staging", {"ENVIRONMENT": "staging"}),
    ("short-ENV-dev", {"ENV": "dev", "JWT_SECRET": "short"}),
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
    """Only the pytest runner (PYTEST_VERSION) is test mode (FG-516)."""
    outs = []
    for _ in range(2):
        r = _start({"PYTEST_VERSION": "9"}, code="import app.deps.auth as a; print('KEY', a.JWT_SECRET)")
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
    return run(db[AUDIT_COLLECTION].find({"action": {"$regex": "^reminder_jobs\\."}}, {"_id": 0})
               .sort("recorded_at", 1).to_list(None))


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


def test_positive_the_job_key_runs_exactly_one_tenant_with_started_and_completed_events(reminder, monkeypatch):
    client, db, ran = reminder
    monkeypatch.setenv("INTERNAL_JOB_KEY", KEY)
    r = client.post(URL + "?tenant_id=" + ORG_B, headers={"X-Internal-Job-Key": KEY})
    assert r.status_code == 200, r.text
    assert r.json()["tenants"] == 1 and ran == [ORG_B]
    evs = _events(db)
    assert [e["action"] for e in evs] == ["reminder_jobs.started", "reminder_jobs.completed"]
    assert {e["tenant_id"] for e in evs} == {ORG_B} and {e["actor_type"] for e in evs} == {"system"}
    assert len({e["correlation_id"] for e in evs}) == 1 and evs[0]["correlation_id"]
    assert evs[0]["source_flow"] == "FLOW-013" and evs[0]["structured_diff"] == {"scope": "tenant", "phase": "started"}
    assert KEY not in json.dumps(evs, default=str)


def test_positive_only_the_job_key_runs_all_tenants(reminder, monkeypatch):
    client, db, ran = reminder
    monkeypatch.setenv("INTERNAL_JOB_KEY", KEY)
    r = client.post(URL + "?all_tenants=true", headers={"X-Internal-Job-Key": KEY})
    assert r.status_code == 200, r.text
    assert sorted(ran) == sorted([ORG_A, ORG_B])
    evs = _events(db)
    assert sorted((e["tenant_id"], e["action"]) for e in evs) == sorted(
        (t, "reminder_jobs." + ph) for t in (ORG_A, ORG_B) for ph in ("started", "completed"))


@pytest.mark.parametrize("query", ["?all_tenants=true", "?tenant_id=" + ORG_B])
def test_forbidden_a_platform_admin_cannot_run_another_tenant_without_a_support_grant(reminder, query):
    client, db, ran = reminder
    r = client.post(URL + query, headers={"Authorization": "Bearer platform"})
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["error_code"] == "SUPPORT_ACCESS_GRANT_REQUIRED"
    assert ran == [] and _events(db) == []


def test_positive_a_platform_admin_runs_the_tenant_of_their_own_session(reminder):
    client, db, ran = reminder
    r = client.post(URL + "?tenant_id=" + ORG_A, headers={"Authorization": "Bearer platform"})
    assert r.status_code == 200, r.text
    assert ran == [ORG_A]
    assert [(e["actor_type"], e["actor_id"], e["action"]) for e in _events(db)] == [
        ("human", "pa-1", "reminder_jobs.started"), ("human", "pa-1", "reminder_jobs.completed")]


def test_a_failing_run_is_recorded_as_failed_after_its_started_event(reminder, monkeypatch):
    from app.routes import attendance
    client, db, ran = reminder
    monkeypatch.setenv("INTERNAL_JOB_KEY", KEY)

    async def _boom(org_id):
        raise RuntimeError("db down 8001010008")
    monkeypatch.setattr(attendance, "run_reminder_jobs_for_org", _boom)
    r = client.post(URL + "?tenant_id=" + ORG_A, headers={"X-Internal-Job-Key": KEY})
    assert r.status_code == 500
    evs = _events(db)
    assert [(e["action"], e["result"]) for e in evs] == [
        ("reminder_jobs.started", "success"), ("reminder_jobs.failed", "failure")]
    assert evs[1]["error_code"] == "RuntimeError" and "8001010008" not in json.dumps(evs, default=str)


def test_the_comparison_is_constant_time():
    src = (BACKEND / "app/routes/attendance.py").read_text(encoding="utf-8")
    block = src[src.index("async def _internal_job_caller"):src.index("async def _reminder_event")]
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


def test_unused_llm_vendor_sdks_are_not_pinned():
    """FG-520: nothing imports them; the pinned anthropic SDK is the only AI client."""
    names = {re.sub(r"[-_.]+", "-", l.split("==")[0]).lower()
             for l in (BACKEND / "requirements.txt").read_text().splitlines() if "==" in l}
    for gone in ("litellm", "openai", "google-genai", "google-generativeai", "google-ai-generativelanguage",
                 "tiktoken", "tokenizers", "huggingface-hub", "google-api-python-client"):
        assert gone not in names, gone


class FakeMessages:
    def __init__(self, answer, fail=None):
        self.answer, self.fail, self.calls = answer, fail, []

    async def create(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise self.fail

        class Block:
            type, text = "text", self.answer

        class Usage:
            input_tokens, output_tokens = 120, 45

        class Resp:
            content = [Block()]
            usage = Usage()
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
    monkeypatch.setattr(ai_provider, "run_in_transaction", snapshot_transaction)
    return ai_provider, db, fake


TX_COLLECTIONS = ("ai_usage_ledger", "audit_events", "feature_flags")


async def snapshot_transaction(db, body):
    """mongomock has no sessions: emulate commit-or-nothing (the contract of
    auth_tx.run_in_transaction) by restoring the touched collections when ``body``
    raises. Atomicity on a real replica set: test_real_mongo_* below."""
    snap = {n: await db[n].find({}).to_list(None) for n in TX_COLLECTIONS}
    try:
        return await body(None)
    except BaseException:
        for n, docs in snap.items():
            await db[n].delete_many({})
            if docs:
                await db[n].insert_many(docs)
        raise


def configure(monkeypatch, db, *, key=True, model=True, enabled=True, org=ORG_A):
    if key:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-key-sec03")
    if model:
        monkeypatch.setenv("ANTHROPIC_MODEL", "configured-model-sec03")
    if enabled is not None:
        run(db["feature_flags"].insert_one({"org_id": org, "module_code": "ai_enabled", "enabled": enabled}))


def ai_events(db):
    from app.audit.store import AUDIT_COLLECTION
    return run(db[AUDIT_COLLECTION].find({"action": {"$regex": "^ai\\.call\\."}}, {"_id": 0}).to_list(None))


def ledger(db):
    return run(db["ai_usage_ledger"].find({}, {"_id": 0}).to_list(None))


def call(ai_provider, text="t", images=None, user="u-1", feature="test_feature"):
    return run(ai_provider.complete(ORG_A, user_id=user, feature=feature, system="s", text=text, images=images))


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
        call(ai_provider)
    assert exc.value.reason == reason and str(exc.value) == "AI не е настроен"
    assert fake.keys == [] and fake.messages.calls == []        # nothing left the server
    assert ai_events(db) == [] and ledger(db) == []              # no AI call happened


def test_forbidden_another_tenants_flag_does_not_enable_ai(ai, monkeypatch):
    ai_provider, db, fake = ai
    configure(monkeypatch, db, org=ORG_B)
    with pytest.raises(ai_provider.AINotConfigured):
        call(ai_provider)
    assert fake.messages.calls == []


def test_positive_a_completed_call_uses_the_configured_model_and_writes_audit_and_ledger(ai, monkeypatch, caplog):
    ai_provider, db, fake = ai
    configure(monkeypatch, db)
    fake.messages.answer = '{"ok": 1}'
    text = "Иван, ЕГН 8001010008, IBAN BG80BNBG96611020345678, мазилка 12 м2"
    out = call(ai_provider, text=text, user="u-7", feature="smr_ai_proposal")
    assert out == '{"ok": 1}'
    assert fake.keys == ["test-only-key-sec03"]
    [sent] = fake.messages.calls
    assert sent["model"] == "configured-model-sec03" and sent["system"] == "s"
    body = sent["messages"][0]["content"][-1]["text"]
    assert "8001010008" not in body and "BG80BNBG96611020345678" not in body
    assert "мазилка 12 м2" in body and body.count("[скрито]") == 2
    assert "test-only-key-sec03" not in caplog.text
    # FG-519: one AuditEvent (metadata only) + one ledger row
    [ev] = ai_events(db)
    assert ev["action"] == "ai.call.completed" and ev["tenant_id"] == ORG_A and ev["actor_id"] == "u-7"
    assert ev["model_and_version"] == "anthropic/configured-model-sec03" and ev["source_flow"] == "FLOW-050"
    assert ev["structured_diff"] == {"feature": "smr_ai_proposal", "outcome": "completed",
                                     "usage_in": 120, "usage_out": 45}
    dumped = json.dumps(ev, default=str, ensure_ascii=False)
    for secret in ("мазилка", "Иван", "скрито", '{\\"ok\\"', "test-only-key-sec03", "8001010008"):
        assert secret not in dumped, secret                      # no prompt, response, personal data, key
    [row] = ledger(db)
    assert (row["org_id"], row["user_id"], row["feature"], row["actions"]) == (ORG_A, "u-7", "smr_ai_proposal", 1)
    assert (row["input_tokens"], row["output_tokens"]) == (120, 45) and len(row["period"]) == 7


def test_forbidden_a_provider_failure_is_audited_not_counted_and_never_leaks(ai, monkeypatch, caplog):
    ai_provider, db, fake = ai
    configure(monkeypatch, db)
    fake.messages.fail = RuntimeError("upstream said: secret prompt ЕГН 8001010008 test-only-key-sec03")
    with pytest.raises(ai_provider.AIProviderError) as exc:
        call(ai_provider)
    assert "8001010008" not in str(exc.value) and "test-only-key-sec03" not in str(exc.value)
    assert "8001010008" not in caplog.text and "test-only-key-sec03" not in caplog.text
    [ev] = ai_events(db)
    assert ev["action"] == "ai.call.failed" and ev["result"] == "failure" and ev["error_code"] == "RuntimeError"
    assert "8001010008" not in json.dumps(ev, default=str)
    assert ledger(db) == []                                      # only completed actions count


# ── FG-517 / FG-535 redaction: anything that looks like one is hidden ──
@pytest.mark.parametrize("text", [
    "IBAN BG80BNBG96611020345678", "iban bg80bnbg96611020345678", "bg80 bnbg 9661 1020 3456 78 мазилка",
    "BG80-BNBG-9661-1020-3456-78", "GB82 WEST 1234 5698 7654 32", "IBAN BG80BNBG96611020345678 and more",
    "BG80\u00a0BNBG\u00a09661\u00a01020\u00a03456\u00a078", "BG80  BNBG  9661  1020  3456  78",
    "BG80BNBG96611020345679",                       # bad IBAN checksum — still hidden
    "ЕГН 8001010008", "800101 0008", "80-01-01-0008", "800 101 0008", "egn:8001010008,",
    "ЕГН 8001010008, тел.", "ЕГН:8001010008.", "ЕГН8001010008 и 5 бр", "800101\u00a00008",
    "ID 8001010000",                                # bad ЕГН checksum — still hidden
    "ЛНЧ 1001234567", "ЛНЧ: 10 0123 4567",
])
def test_personal_ids_are_redacted_in_any_case_spacing_and_checksum(text):
    from app.services.ai_provider import redact_personal
    out = redact_personal(text)
    assert "[скрито]" in out, out
    digits = re.sub(r"\D", "", out)
    for leaked in ("8001010008", "8001010000", "96611020345678", "96611020345679", "12345698765432", "1001234567"):
        assert leaked not in digits, (text, out)
    if "and more" in text:
        assert out.endswith(" and more")
    if "мазилка" in text:
        assert out.endswith(" мазилка")
    if " и 5 бр" in text:
        assert out.endswith(" и 5 бр")


@pytest.mark.parametrize("text", [
    "1 234 567,89", "QR-000012", "12 345,00 лв", "мазилка 12 м2 по 18,50 лв", "Обект №17, етаж 3, 120 м2",
])
def test_ordinary_amounts_and_short_ids_stay_readable(text):
    """Over-redaction is accepted (FG-535) — but ordinary quantities and short ids pass."""
    from app.services.ai_provider import redact_personal
    assert redact_personal(text) == text


# ── FG-536: audit + ledger in one transaction ──
def test_forbidden_if_the_audit_fails_no_counted_action_remains(ai, monkeypatch):
    from app.audit import store
    ai_provider, db, fake = ai
    configure(monkeypatch, db)

    async def broken(*a, **kw):
        raise RuntimeError("audit store down")
    monkeypatch.setattr(store, "record_event", broken)
    with pytest.raises(ai_provider.AIAuditFailed):
        call(ai_provider)
    assert fake.messages.calls != []          # the model answered…
    assert ledger(db) == []                   # …but nothing is counted, and the answer is not returned


def _real_mongo_db():
    url = os.environ.get("W0_03_REAL_MONGO_URL")
    if not url:
        pytest.skip("W0_03_REAL_MONGO_URL not set (the gates run on real Mongo)")
    from motor.motor_asyncio import AsyncIOMotorClient
    return AsyncIOMotorClient(url)["sec03_tx_%s" % os.urandom(4).hex()]


def test_real_mongo_ai_call_audit_and_ledger_commit_together_or_not_at_all(monkeypatch):
    """FG-536 on a real replica set (no emulation): a failing audit write rolls the
    ledger row back; a good call commits both."""
    from app.audit import store
    from app.services import ai_provider

    async def scenario():
        db = _real_mongo_db()
        try:
            monkeypatch.setattr(ai_provider, "db", db)
            monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-key-sec03")
            monkeypatch.setenv("ANTHROPIC_MODEL", "configured-model-sec03")
            await db["feature_flags"].insert_one({"org_id": ORG_A, "module_code": "ai_enabled", "enabled": True})
            fake = FakeClient('{"ok": 1}')
            monkeypatch.setattr(ai_provider, "client_factory", fake)
            real_record = store.record_event

            async def broken(database, event, session=None):
                await real_record(database, event, session=session)   # written inside the txn…
                raise RuntimeError("fail after the audit write")       # …then the txn aborts
            monkeypatch.setattr(store, "record_event", broken)
            with pytest.raises(ai_provider.AIAuditFailed):
                await ai_provider.complete(ORG_A, user_id="u-1", feature="f", system="s", text="t")
            assert await db["ai_usage_ledger"].count_documents({}) == 0
            assert await db["audit_events"].count_documents({"action": "ai.call.completed"}) == 0
            monkeypatch.setattr(store, "record_event", real_record)
            assert await ai_provider.complete(ORG_A, user_id="u-1", feature="f", system="s", text="t") == '{"ok": 1}'
            assert await db["ai_usage_ledger"].count_documents({}) == 1
            assert await db["audit_events"].count_documents({"action": "ai.call.completed"}) == 1
        finally:
            await db.client.drop_database(db.name)
    run(scenario())


# ── the AI endpoints ──
ADMIN = {"id": "admin-1", "org_id": ORG_A, "role": "Admin", "email": "a@x", "first_name": "A", "last_name": "B"}
OWNER = {"id": "owner-1", "org_id": ORG_A, "role": "Owner", "email": "o@x"}
TECH = {"id": "tech-1", "org_id": ORG_A, "role": "Technician", "email": "t@x"}
IMG = "/9j/4AAQSkZJRg" + "A" * 300
NEEDS_REGISTRY = "изисква файлов регистър"


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


def _observed(monkeypatch):
    from app.master_data import intake_hooks
    seen = []

    async def _observe(user, suggestion, source_ref=None, model_and_version=None):
        seen.append(model_and_version)
    monkeypatch.setattr(intake_hooks, "observe_ai_asset", _observe)
    return seen


def _batch_rights(monkeypatch, db, allowed=True):
    from app.routes import assets_intake_pending, asset_item_types

    async def can_submit(user):
        return allowed
    monkeypatch.setattr(assets_intake_pending, "_can_submit", can_submit)
    monkeypatch.setattr(asset_item_types, "db", db)


@pytest.mark.parametrize("enabled", [False, True])
def test_forbidden_photo_ai_is_hard_disabled_until_the_file_registry_exists(ai, monkeypatch, enabled):
    """FG-522 (§4): even with key, model and ai_enabled on, no photo reaches AI."""
    from app.routes import assets_ai_intake, assets_batch_intake
    ai_provider, db, fake = ai
    seen = _observed(monkeypatch)
    _batch_rights(monkeypatch, db)
    configure(monkeypatch, db, enabled=enabled)
    r1 = _client(monkeypatch, assets_ai_intake, db, ADMIN).post("/api/assets/ai-intake", json={"image_base64": IMG})
    r2 = _client(monkeypatch, assets_batch_intake, db, ADMIN).post(
        "/api/assets/batch-intake/recognize", json={"images_base64": [IMG]})
    for r in (r1, r2):
        assert r.status_code == 503 and NEEDS_REGISTRY in r.json()["detail"], r.text
    assert fake.messages.calls == [] and seen == [] and ai_events(db) == [] and ledger(db) == []
    with pytest.raises(ai_provider.AIPhotoNeedsFileRegistry):     # the adapter refuses too
        call(ai_provider, images=[IMG])
    assert fake.messages.calls == []


def test_photo_paths_once_the_registry_exists_answer_ai_not_configured_or_a_suggestion(ai, monkeypatch):
    """The downstream path stays tested for when W0-06 flips the switch."""
    from app.routes import assets_ai_intake, assets_batch_intake
    ai_provider, db, fake = ai
    monkeypatch.setattr(ai_provider, "PHOTO_AI_FILE_REGISTRY_READY", True)
    seen = _observed(monkeypatch)
    _batch_rights(monkeypatch, db)
    single = _client(monkeypatch, assets_ai_intake, db, ADMIN)
    batch = _client(monkeypatch, assets_batch_intake, db, ADMIN)
    r = single.post("/api/assets/ai-intake", json={"image_base64": IMG})
    assert r.status_code == 503 and r.json()["detail"] == "AI не е настроен", r.text
    configure(monkeypatch, db)
    fake.messages.answer = json.dumps({"name": "Ъглошлайф", "type": "tool", "confidence": 80})
    r = single.post("/api/assets/ai-intake", json={"image_base64": IMG, "plate_image_base64": IMG})
    assert r.status_code == 200 and r.json()["name"] == "Ъглошлайф", r.text
    assert len(fake.messages.calls[0]["messages"][0]["content"]) == 3          # 2 photos + text
    fake.messages.answer = json.dumps({"name": "Перфоратор", "type_label": "Бормашини", "confidence": 70})
    r = batch.post("/api/assets/batch-intake/recognize", json={"images_base64": [IMG, IMG]})
    assert r.status_code == 200 and r.json()["suggestion"]["name"] == "Перфоратор", r.text
    assert seen == ["anthropic/configured-model-sec03"] * 2
    assert [e["structured_diff"]["feature"] for e in ai_events(db)] == ["assets_ai_intake", "assets_batch_intake"]
    fake.messages.fail = RuntimeError("boom 8001010008")
    r = single.post("/api/assets/ai-intake", json={"image_base64": IMG})
    assert r.status_code == 502 and "8001010008" not in r.text


def test_forbidden_photo_endpoints_check_rights_before_anything_else(ai, monkeypatch):
    from app.routes import assets_ai_intake, assets_batch_intake
    ai_provider, db, fake = ai
    monkeypatch.setattr(ai_provider, "PHOTO_AI_FILE_REGISTRY_READY", True)
    configure(monkeypatch, db)
    _batch_rights(monkeypatch, db, allowed=False)
    r = _client(monkeypatch, assets_ai_intake, db, TECH).post("/api/assets/ai-intake", json={"image_base64": IMG})
    assert r.status_code == 403
    r = _client(monkeypatch, assets_batch_intake, db, TECH).post(
        "/api/assets/batch-intake/recognize", json={"images_base64": [IMG]})
    assert r.status_code == 403 and fake.messages.calls == []


def test_text_ai_runs_when_enabled_and_falls_back_to_rules_when_not(ai, monkeypatch):
    from app.services import ai_proposal
    ai_provider, db, fake = ai
    monkeypatch.setattr("app.routes.ai_calibration.db", db, raising=False)
    res = run(ai_proposal.get_ai_proposal("Мазилка вътрешна", "м2", 20, None, ORG_A, "u-1"))
    assert res["provider"] != "llm" and "AI не е настроен" in res["fallback_reason"]
    assert fake.messages.calls == [] and ledger(db) == []
    configure(monkeypatch, db)
    fake.messages.answer = json.dumps({"activity_type": "Мокри процеси", "activity_subtype": "Мазилка",
                                       "material_price_per_unit": 8, "labor_price_per_unit": 12,
                                       "materials": []})
    res = run(ai_proposal.get_ai_proposal("Мазилка вътрешна", "м2", 20, None, ORG_A, "u-1"))
    assert res["provider"] == "llm" and res["pricing"]["total_price_per_unit"] == 20
    assert fake.messages.calls[0]["model"] == "configured-model-sec03"
    assert [(r["user_id"], r["feature"]) for r in ledger(db)] == [("u-1", "smr_ai_proposal")]


def _analysis(db):
    run(db["smr_analyses"].insert_one({"id": "an-1", "org_id": ORG_A, "lines": [
        {"line_id": "l1", "smr_type": "Мазилка", "unit": "м2", "unit_price": 10}]}))
    run(db["ai_cache"].insert_one({"key": "ai_breakdown_an-1", "org_id": ORG_A, "created_at": "2026-01-01",
                                   "results": [{"line_id": "l1", "material_cena": 9, "trud_cena": 1,
                                                "uverenost": 99, "beleshka": "стар AI резултат"}]}))


def _line(db):
    return run(db["smr_analyses"].find_one({"id": "an-1"}))["lines"][0]


@pytest.mark.parametrize("key,enabled", [(False, True), (True, False), (True, None)])
def test_forbidden_the_breakdown_cache_is_not_applied_when_ai_is_off(ai, monkeypatch, key, enabled):
    """FG-518: earlier AI results are not applied without AI; the manual split is."""
    from app.routes import smr_analysis
    ai_provider, db, fake = ai
    _analysis(db)
    configure(monkeypatch, db, key=key, enabled=enabled)
    r = _client(monkeypatch, smr_analysis, db, ADMIN).post("/api/smr-analyses/an-1/ai-breakdown")
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "fallback" and r.json()["error"] == "AI не е настроен"
    line = _line(db)
    assert (line["material_cena_per_unit"], line["trud_cena_per_unit"]) == (6.0, 4.0)
    assert line["ai_beleshka"] != "стар AI резултат" and fake.messages.calls == []


def test_positive_the_breakdown_cache_is_applied_only_when_ai_is_on(ai, monkeypatch):
    from app.routes import smr_analysis
    ai_provider, db, fake = ai
    _analysis(db)
    configure(monkeypatch, db)
    r = _client(monkeypatch, smr_analysis, db, ADMIN).post("/api/smr-analyses/an-1/ai-breakdown")
    assert r.status_code == 200 and r.json()["source"] == "cache", r.text
    assert (_line(db)["material_cena_per_unit"], _line(db)["trud_cena_per_unit"]) == (9, 1)


# ── the per-tenant switch (FG-519: Owner only, canonical AuditEvent) ──
def _auth_client(monkeypatch, db, user):
    from app.routes import auth as auth_routes
    from app.deps.auth import get_current_user, require_platform_admin
    from fastapi import HTTPException
    monkeypatch.setattr(auth_routes, "db", db)
    monkeypatch.setattr(auth_routes, "run_ai_settings_transaction", snapshot_transaction)
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")

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


def _switch_events(db):
    from app.audit.store import AUDIT_COLLECTION
    return run(db[AUDIT_COLLECTION].find({"action": "ai.settings.changed"}, {"_id": 0}).to_list(None))


def _put(client, enabled, key="k-1", reason="тест на живо от Крум"):
    headers = {"Idempotency-Key": key} if key else {}
    body = {"enabled": enabled} if reason is None else {"enabled": enabled, "reason": reason}
    return client.put("/api/ai/settings", json=body, headers=headers)


@pytest.mark.parametrize("user", [TENANT_ADMIN, PLATFORM, TECH], ids=["admin", "platform-admin", "technician"])
def test_forbidden_only_the_owner_switches_ai(ai, monkeypatch, user):
    ai_provider, db, fake = ai
    client = _auth_client(monkeypatch, db, user)
    r = _put(client, True)
    assert r.status_code == 403, r.text
    # the generic module switch refuses the AI flag for everyone, platform admin included
    r = client.put("/api/feature-flags", json={"module_code": "ai_enabled", "enabled": True})
    assert r.status_code in (400, 403), r.text
    assert run(ai_provider.ai_enabled_for_tenant(ORG_A)) is False and _switch_events(db) == []


@pytest.mark.parametrize("key,reason,status", [(None, "причина", 428), ("k", None, 422), ("k", "  ", 422),
                                               ("k", "x", 422)])
def test_forbidden_the_switch_needs_an_idempotency_key_and_a_reason(ai, monkeypatch, key, reason, status):
    ai_provider, db, fake = ai
    r = _put(_auth_client(monkeypatch, db, OWNER), True, key=key, reason=reason)
    assert r.status_code == status, r.text
    assert run(ai_provider.ai_enabled_for_tenant(ORG_A)) is False and _switch_events(db) == []


def test_positive_the_owner_switches_ai_with_an_audit_event_and_it_is_off_by_default(ai, monkeypatch):
    ai_provider, db, fake = ai
    client = _auth_client(monkeypatch, db, OWNER)
    assert client.get("/api/ai/settings").json() == {"enabled": False, "configured": False}
    r = _put(client, True, key="k-on")
    assert r.status_code == 200, r.text
    assert run(ai_provider.ai_enabled_for_tenant(ORG_A)) is True
    assert run(ai_provider.ai_enabled_for_tenant(ORG_B)) is False
    r = _put(client, False, key="k-off", reason="край на теста")
    assert r.status_code == 200 and run(ai_provider.ai_enabled_for_tenant(ORG_A)) is False
    evs = _switch_events(db)
    assert [(e["actor_id"], e["structured_diff"]["before"]["enabled"], e["structured_diff"]["after"]["enabled"],
             e["reason"], e["idempotency_key"]) for e in evs] == [
        ("owner-1", False, True, "тест на живо от Крум", "k-on"), ("owner-1", True, False, "край на теста", "k-off")]
    assert {e["tenant_id"] for e in evs} == {ORG_A}


def test_the_switch_is_idempotent_per_key(ai, monkeypatch):
    ai_provider, db, fake = ai
    client = _auth_client(monkeypatch, db, OWNER)
    first = _put(client, True, key="same")
    again = _put(client, True, key="same")
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    assert len(_switch_events(db)) == 1                                   # replay: nothing written twice
    other = _put(client, False, key="same")                               # same key, different request
    assert other.status_code == 409 and other.json()["detail"]["error_code"] == "IDEMPOTENCY_KEY_REUSED"
    assert run(ai_provider.ai_enabled_for_tenant(ORG_A)) is True and len(_switch_events(db)) == 1


def test_forbidden_if_the_switch_event_fails_the_flag_does_not_change(ai, monkeypatch):
    from app.audit import store
    ai_provider, db, fake = ai
    client = _auth_client(monkeypatch, db, OWNER)

    async def broken(*a, **kw):
        raise RuntimeError("audit store down")
    monkeypatch.setattr(store, "record_event", broken)
    r = _put(client, True, key="k-broken")
    assert r.status_code == 500
    assert run(ai_provider.ai_enabled_for_tenant(ORG_A)) is False and _switch_events(db) == []


def test_real_mongo_the_switch_and_its_event_commit_together(monkeypatch):
    """FG-538 on a real replica set: the flag write is rolled back when the event fails.
    The route function is driven directly in ONE event loop (a Motor client cannot
    cross TestClient's loop)."""
    from fastapi import HTTPException
    from app.audit import store
    from app.routes import auth as auth_routes
    from app.services import ai_provider
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")

    async def scenario():
        real_db = _real_mongo_db()
        try:
            monkeypatch.setattr(ai_provider, "db", real_db)
            monkeypatch.setattr(auth_routes, "db", real_db)
            real_record = store.record_event

            async def broken(database, event, session=None):
                await real_record(database, event, session=session)
                raise RuntimeError("fail after the event write")
            monkeypatch.setattr(store, "record_event", broken)
            body = auth_routes.AISettingsUpdate(enabled=True, reason="тест на живо")
            with pytest.raises(RuntimeError):
                await auth_routes.put_ai_settings(body, None, dict(OWNER), idempotency_key="rk-1")
            assert await real_db["feature_flags"].count_documents({"module_code": "ai_enabled"}) == 0
            assert await real_db["audit_events"].count_documents({"action": "ai.settings.changed"}) == 0
            monkeypatch.setattr(store, "record_event", real_record)
            out = await auth_routes.put_ai_settings(body, None, dict(OWNER), idempotency_key="rk-2")
            assert out["enabled"] is True
            assert await real_db["feature_flags"].count_documents({"module_code": "ai_enabled", "enabled": True}) == 1
            assert await real_db["audit_events"].count_documents({"action": "ai.settings.changed"}) == 1
            with pytest.raises(HTTPException):          # a tenant Admin never reaches the transaction
                await auth_routes.put_ai_settings(body, None, dict(TENANT_ADMIN), idempotency_key="rk-3")
        finally:
            await real_db.client.drop_database(real_db.name)
    run(scenario())


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
    assert "script-src 'self';" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    # FG-515: the header fixes nothing that depends on configuration — connect-src
    # (and the default-src it would fall back to) is the build-templated meta's job,
    # so an analytics host configured at build time is never blocked by nginx.
    assert "connect-src" not in csp and "default-src" not in csp
    for header in ('X-Frame-Options "DENY" always', 'X-Content-Type-Options "nosniff" always',
                   'Referrer-Policy "strict-origin-when-cross-origin" always'):
        assert "add_header " + header in conf
    meta = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', INDEX.read_text(encoding="utf-8"))
    assert meta and "script-src 'self';" in meta.group(1) and "default-src 'self'" in meta.group(1)
    assert "connect-src 'self' %REACT_APP_BACKEND_URL% %REACT_APP_POSTHOG_HOST%;" in meta.group(1)
