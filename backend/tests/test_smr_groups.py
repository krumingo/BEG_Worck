"""
Tests for SMR Groups (triple hierarchy) module.
Run: pytest backend/tests/test_smr_groups.py -v
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


@pytest.fixture(scope="module")
def location_id(auth_headers, project_id):
    r = httpx.post(f"{API}/projects/{project_id}/locations", json={
        "type": "room", "name": "Баня ет.2 (GRP test)",
    }, headers=auth_headers)
    return r.json()["id"]


# ── Test 1: Create group ──────────────────────────────────────────

def test_create_group(auth_headers, project_id):
    r = httpx.post(f"{API}/projects/{project_id}/smr-groups", json={
        "name": "Довършителни",
    }, headers=auth_headers)
    assert r.status_code == 201
    d = r.json()
    assert d["name"] == "Довършителни"
    assert d["report_mode"] == "per_line"


# ── Test 2: Create group with location_id ──────────────────────────

def test_create_group_with_location(auth_headers, project_id, location_id):
    r = httpx.post(f"{API}/projects/{project_id}/smr-groups", json={
        "location_id": location_id,
        "name": "Плочки",
        "color": "#3b82f6",
    }, headers=auth_headers)
    assert r.status_code == 201
    assert r.json()["location_id"] == location_id
    assert r.json()["color"] == "#3b82f6"


# ── Test 3: Assign line to group ──────────────────────────────────

def test_assign_line(auth_headers, project_id):
    # Create a missing_smr record
    ms = httpx.post(f"{API}/missing-smr", json={
        "project_id": project_id,
        "smr_type": "Монтаж плочки",
        "qty": 12,
        "unit": "m2",
        "source": "web",
    }, headers=auth_headers).json()

    # Get a group
    groups = httpx.get(f"{API}/projects/{project_id}/smr-groups", headers=auth_headers).json()["items"]
    grp = groups[-1]  # last created (Плочки)

    r = httpx.post(f"{API}/smr-groups/{grp['id']}/assign-line", json={
        "line_id": ms["id"],
        "source": "missing_smr",
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ── Test 4: Unassign line from group ──────────────────────────────

def test_unassign_line(auth_headers, project_id):
    # Create another record
    ms = httpx.post(f"{API}/missing-smr", json={
        "project_id": project_id,
        "smr_type": "Фугиране",
        "qty": 12,
        "unit": "m2",
        "source": "web",
    }, headers=auth_headers).json()

    groups = httpx.get(f"{API}/projects/{project_id}/smr-groups", headers=auth_headers).json()["items"]
    grp = groups[-1]

    # Assign
    httpx.post(f"{API}/smr-groups/{grp['id']}/assign-line", json={
        "line_id": ms["id"], "source": "missing_smr",
    }, headers=auth_headers)

    # Unassign
    r = httpx.post(f"{API}/smr-groups/{grp['id']}/unassign-line", json={
        "line_id": ms["id"], "source": "missing_smr",
    }, headers=auth_headers)
    assert r.status_code == 200


# ── Test 5: Get tree (location → group → lines) ───────────────────

def test_get_tree(auth_headers, project_id):
    r = httpx.get(f"{API}/projects/{project_id}/smr-groups/tree", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "tree" in d
    assert "grand_total" in d
    assert len(d["tree"]) >= 1  # at least one location node


# ── Test 6: Summary aggregation (mixed units) ─────────────────────

def test_summary(auth_headers, project_id):
    groups = httpx.get(f"{API}/projects/{project_id}/smr-groups", headers=auth_headers).json()["items"]
    grp = next((g for g in groups if g["name"] == "Плочки"), groups[-1])

    r = httpx.get(f"{API}/smr-groups/{grp['id']}/summary", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "total_cost" in d
    assert "lines_count" in d
    assert "by_unit" in d


# ── Test 7: Delete group (lines keep existing) ────────────────────

def test_delete_group(auth_headers, project_id):
    # Create temp group
    g = httpx.post(f"{API}/projects/{project_id}/smr-groups", json={
        "name": "Temp Delete Test",
    }, headers=auth_headers).json()

    # Create and assign a line
    ms = httpx.post(f"{API}/missing-smr", json={
        "project_id": project_id,
        "smr_type": "Delete Test Line",
        "qty": 5,
        "unit": "m2",
        "source": "web",
    }, headers=auth_headers).json()
    httpx.post(f"{API}/smr-groups/{g['id']}/assign-line", json={
        "line_id": ms["id"], "source": "missing_smr",
    }, headers=auth_headers)

    # Delete group
    r = httpx.delete(f"{API}/smr-groups/{g['id']}", headers=auth_headers)
    assert r.status_code == 200

    # Line should still exist
    line = httpx.get(f"{API}/missing-smr/{ms['id']}", headers=auth_headers)
    assert line.status_code == 200


# ── Test 8: Reverse lookup by smr_type ─────────────────────────────

def test_reverse_by_type(auth_headers, project_id):
    r = httpx.get(f"{API}/projects/{project_id}/smr-by-type?smr_type=Монтаж", headers=auth_headers)
    assert r.status_code == 200
    assert "results" in r.json()
    assert r.json()["total"] >= 0


# ── Test 9: Report per_line mode ───────────────────────────────────

def test_report_per_line(auth_headers, project_id):
    groups = httpx.get(f"{API}/projects/{project_id}/smr-groups", headers=auth_headers).json()["items"]
    if not groups:
        pytest.skip("No groups")
    grp = groups[0]

    r = httpx.post(f"{API}/smr-groups/{grp['id']}/report", json={
        "mode": "per_line",
        "line_reports": [
            {"line_id": "test-line-1", "hours": 2, "cost": 50, "notes": "OK"},
        ],
        "notes": "Test report",
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["mode"] == "per_line"
    assert r.json()["total_hours"] == 2


# ── Test 10: Report group_total mode ───────────────────────────────

def test_report_group_total(auth_headers, project_id):
    groups = httpx.get(f"{API}/projects/{project_id}/smr-groups", headers=auth_headers).json()["items"]
    if not groups:
        pytest.skip("No groups")
    grp = groups[0]

    r = httpx.post(f"{API}/smr-groups/{grp['id']}/report", json={
        "mode": "group_total",
        "total_hours": 8,
        "total_cost": 200,
        "notes": "Group report",
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["mode"] == "group_total"
    assert r.json()["total_hours"] == 8
    assert r.json()["total_cost"] == 200


# ── Test 11: Get group lines ──────────────────────────────────────

def test_get_group_lines(auth_headers, project_id):
    groups = httpx.get(f"{API}/projects/{project_id}/smr-groups", headers=auth_headers).json()["items"]
    grp = next((g for g in groups if g["name"] == "Плочки"), groups[-1])

    r = httpx.get(f"{API}/smr-groups/{grp['id']}/lines", headers=auth_headers)
    assert r.status_code == 200
    assert "lines" in r.json()
    assert "group" in r.json()
