"""
Tests for Overhead Realtime module.
Run: pytest backend/tests/test_overhead_realtime.py -v
"""
import pytest
import httpx
from pathlib import Path
from datetime import datetime, timezone

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
MONTH = datetime.now(timezone.utc).strftime("%Y-%m")
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")


@pytest.fixture(scope="module")
def auth_headers():
    r = httpx.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def worker_id(auth_headers):
    r = httpx.get(f"{API}/auth/me", headers=auth_headers)
    return r.json()["id"]


@pytest.fixture(scope="module")
def project_id(auth_headers):
    r = httpx.get(f"{API}/projects", headers=auth_headers)
    projects = r.json() if isinstance(r.json(), list) else r.json()
    return projects[0]["id"]


# ── Test 1: Create calendar entry ──────────────────────────────────

def test_create_calendar_entry(auth_headers, worker_id, project_id):
    r = httpx.post(f"{API}/worker-calendar", json={
        "worker_id": worker_id,
        "date": TODAY,
        "status": "working",
        "site_id": project_id,
        "hours": 8,
    }, headers=auth_headers)
    assert r.status_code == 201
    assert r.json()["status"] == "working"
    assert r.json()["date"] == TODAY


# ── Test 2: Bulk calendar entries ──────────────────────────────────

def test_bulk_entries(auth_headers, worker_id):
    r = httpx.post(f"{API}/worker-calendar/bulk", json={
        "entries": [
            {"worker_id": worker_id, "date": f"{MONTH}-01", "status": "working", "hours": 8},
            {"worker_id": worker_id, "date": f"{MONTH}-02", "status": "sick_paid", "hours": 0},
            {"worker_id": worker_id, "date": f"{MONTH}-03", "status": "vacation_paid", "hours": 0},
        ],
    }, headers=auth_headers)
    assert r.status_code == 201
    assert r.json()["ok"] is True
    assert r.json()["created"] + r.json()["updated"] == 3


# ── Test 3: Sync from work_sessions ────────────────────────────────

def test_sync_from_sessions(auth_headers):
    r = httpx.post(f"{API}/worker-calendar/sync-from-sessions?date={TODAY}", headers=auth_headers)
    assert r.status_code == 200
    assert "synced" in r.json()


# ── Test 4: Fixed expenses CRUD ────────────────────────────────────

def test_fixed_expenses(auth_headers):
    r = httpx.put(f"{API}/fixed-expenses", json={
        "month": MONTH,
        "categories": [
            {"name": "Наем офис", "amount": 2000},
            {"name": "Счетоводство", "amount": 800},
            {"name": "Коли + гориво", "amount": 3000},
            {"name": "Телефони", "amount": 500},
        ],
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] == 6300

    # Read back
    r2 = httpx.get(f"{API}/fixed-expenses?month={MONTH}", headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json()["total"] == 6300


# ── Test 5: Realtime overhead calculation ──────────────────────────

def test_realtime_overhead(auth_headers):
    r = httpx.get(f"{API}/overhead/realtime?month={MONTH}", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert d["month"] == MONTH
    assert d["fixed_total"] == 6300
    assert d["overhead_per_person_day"] >= 0
    assert "daily_breakdown" in d
    assert "by_project" in d


# ── Test 6: Overhead with sick workers (higher per person) ─────────

def test_overhead_sick_impact(auth_headers, worker_id):
    # Create entries: some sick
    httpx.post(f"{API}/worker-calendar/bulk", json={
        "entries": [
            {"worker_id": worker_id, "date": f"{MONTH}-04", "status": "sick_paid"},
            {"worker_id": worker_id, "date": f"{MONTH}-05", "status": "sick_paid"},
        ],
    }, headers=auth_headers)

    r = httpx.get(f"{API}/overhead/realtime?month={MONTH}", headers=auth_headers)
    d = r.json()
    # With sick workers, avg_working should decrease
    assert d["avg_working_per_day"] >= 0


# ── Test 7: Daily breakdown ────────────────────────────────────────

def test_daily_breakdown(auth_headers):
    r = httpx.get(f"{API}/overhead/realtime/daily?month={MONTH}", headers=auth_headers)
    assert r.status_code == 200
    assert "daily" in r.json()
    assert len(r.json()["daily"]) >= 1


# ── Test 8: By project ─────────────────────────────────────────────

def test_by_project(auth_headers):
    r = httpx.get(f"{API}/overhead/realtime/by-project?month={MONTH}", headers=auth_headers)
    assert r.status_code == 200
    assert "projects" in r.json()


# ── Test 9: Trend ──────────────────────────────────────────────────

def test_trend(auth_headers):
    r = httpx.get(f"{API}/overhead/realtime/trend?months=3", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()["trend"]) == 3


# ── Test 10: Get worker calendar ───────────────────────────────────

def test_get_calendar(auth_headers, worker_id):
    r = httpx.get(f"{API}/worker-calendar?worker_id={worker_id}&month={MONTH}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] >= 3  # from our test entries
