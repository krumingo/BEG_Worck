"""
Tests for Alarms module.
Run: pytest backend/tests/test_alarms.py -v
"""
import pytest
import httpx
from pathlib import Path

BASE_URL = ""
fe_env = Path(__file__).parent.parent.parent / "frontend" / ".env"
if fe_env.exists():
    for line in fe_env.read_text().splitlines():
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
            break

API = f"{BASE_URL}/api"
EMAIL = "admin@begwork.com"
PASSWORD = "AdminTest123!Secure"


@pytest.fixture(scope="module")
def auth_headers():
    r = httpx.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def project_id(auth_headers):
    r = httpx.get(f"{API}/projects", headers=auth_headers)
    projects = r.json() if isinstance(r.json(), list) else r.json()
    return projects[0]["id"]


# ── Test 1: Create alarm rule ──────────────────────────────────────

def test_create_rule(auth_headers):
    r = httpx.post(f"{API}/alarm-rules", json={
        "name": "Бюджет > 80%",
        "type": "budget",
        "condition": {"metric": "burn_pct", "operator": ">", "threshold": 80},
        "severity": "warning",
        "cooldown_hours": 1,
        "auto_resolve": True,
    }, headers=auth_headers)
    assert r.status_code == 201
    d = r.json()
    assert d["name"] == "Бюджет > 80%"
    assert d["type"] == "budget"
    assert d["is_active"] is True


def test_create_critical_rule(auth_headers):
    r = httpx.post(f"{API}/alarm-rules", json={
        "name": "Бюджет > 100%",
        "type": "budget",
        "condition": {"metric": "burn_pct", "operator": ">", "threshold": 100},
        "severity": "critical",
        "cooldown_hours": 1,
    }, headers=auth_headers)
    assert r.status_code == 201


def test_create_overtime_rule(auth_headers):
    r = httpx.post(f"{API}/alarm-rules", json={
        "name": "OT > 20ч/седмица",
        "type": "overtime",
        "condition": {"metric": "weekly_overtime_hours", "operator": ">", "threshold": 20},
        "severity": "warning",
        "cooldown_hours": 1,
    }, headers=auth_headers)
    assert r.status_code == 201


# ── Test 2: Evaluate rules (triggers events) ──────────────────────

def test_evaluate(auth_headers):
    r = httpx.post(f"{API}/alarms/evaluate", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "new_events" in d
    assert "resolved_events" in d
    assert isinstance(d["events"], list)


# ── Test 3: List alarms ───────────────────────────────────────────

def test_list_alarms(auth_headers):
    r = httpx.get(f"{API}/alarms?status=active", headers=auth_headers)
    assert r.status_code == 200
    assert "items" in r.json()


# ── Test 4: Alarm count ────────────────────────────────────────────

def test_alarm_count(auth_headers):
    r = httpx.get(f"{API}/alarms/count", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "critical" in d
    assert "warning" in d
    assert "info" in d
    assert "total" in d
    assert d["total"] == d["critical"] + d["warning"] + d["info"]


# ── Test 5: Acknowledge event ──────────────────────────────────────

def test_acknowledge(auth_headers):
    # Get an active alarm
    alarms = httpx.get(f"{API}/alarms?status=active", headers=auth_headers).json()["items"]
    if not alarms:
        # Create one by evaluating
        httpx.post(f"{API}/alarms/evaluate", headers=auth_headers)
        alarms = httpx.get(f"{API}/alarms?status=active", headers=auth_headers).json()["items"]
    if not alarms:
        pytest.skip("No active alarms to acknowledge")

    eid = alarms[0]["id"]
    r = httpx.put(f"{API}/alarms/{eid}/acknowledge", json={"notes": "Видяно"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "acknowledged"


# ── Test 6: Resolve event ──────────────────────────────────────────

def test_resolve(auth_headers):
    alarms = httpx.get(f"{API}/alarms?status=acknowledged", headers=auth_headers).json()["items"]
    if not alarms:
        alarms = httpx.get(f"{API}/alarms?status=active", headers=auth_headers).json()["items"]
    if not alarms:
        pytest.skip("No alarms to resolve")

    eid = alarms[0]["id"]
    r = httpx.put(f"{API}/alarms/{eid}/resolve", json={"notes": "Решено"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "resolved"


# ── Test 7: Dashboard ──────────────────────────────────────────────

def test_dashboard(auth_headers):
    r = httpx.get(f"{API}/alarms/dashboard", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "by_severity" in d
    assert "by_type" in d
    assert "recent" in d
    assert "trend" in d


# ── Test 8: List rules ─────────────────────────────────────────────

def test_list_rules(auth_headers):
    r = httpx.get(f"{API}/alarm-rules", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] >= 3


# ── Test 9: Toggle rule ────────────────────────────────────────────

def test_toggle_rule(auth_headers):
    rules = httpx.get(f"{API}/alarm-rules", headers=auth_headers).json()["items"]
    rid = rules[0]["id"]
    was_active = rules[0]["is_active"]

    r = httpx.put(f"{API}/alarm-rules/{rid}/toggle", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["is_active"] == (not was_active)

    # Toggle back
    httpx.put(f"{API}/alarm-rules/{rid}/toggle", headers=auth_headers)


# ── Test 10: Delete rule ───────────────────────────────────────────

def test_delete_rule(auth_headers):
    r = httpx.post(f"{API}/alarm-rules", json={
        "name": "Delete Test Rule",
        "type": "custom",
        "condition": {"metric": "test", "operator": ">", "threshold": 999},
        "severity": "info",
    }, headers=auth_headers)
    rid = r.json()["id"]

    d = httpx.delete(f"{API}/alarm-rules/{rid}", headers=auth_headers)
    assert d.status_code == 200
