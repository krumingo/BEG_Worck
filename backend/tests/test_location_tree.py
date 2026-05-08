"""
Tests for Location Tree module.
Run: pytest backend/tests/test_location_tree.py -v
"""
import pytest
import httpx
import os
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
    assert r.status_code == 200, f"Login failed: {r.text}"
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def project_id(auth_headers):
    r = httpx.get(f"{API}/projects", headers=auth_headers)
    assert r.status_code == 200
    projects = r.json().get("items", r.json()) if isinstance(r.json(), dict) else r.json()
    assert len(projects) > 0
    return projects[0]["id"]


# ── Test 1: Create root location (building) ──────────────────────

def test_create_building(auth_headers, project_id):
    r = httpx.post(f"{API}/projects/{project_id}/locations", json={
        "type": "building",
        "name": "Сграда А",
        "code": "A",
    }, headers=auth_headers)
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Сграда А"
    assert data["type"] == "building"
    assert data["parent_id"] is None
    assert data["project_id"] == project_id


# ── Test 2: Create child nodes (floor, room, zone) ───────────────

def test_create_nested_hierarchy(auth_headers, project_id):
    # Create building
    b = httpx.post(f"{API}/projects/{project_id}/locations", json={
        "type": "building", "name": "Сграда Б",
    }, headers=auth_headers).json()
    assert b["type"] == "building"

    # Create floor under building
    f = httpx.post(f"{API}/projects/{project_id}/locations", json={
        "type": "floor", "name": "Етаж 1", "parent_id": b["id"],
    }, headers=auth_headers).json()
    assert f["parent_id"] == b["id"]
    assert f["type"] == "floor"

    # Create room under floor
    rm = httpx.post(f"{API}/projects/{project_id}/locations", json={
        "type": "room", "name": "Хол", "parent_id": f["id"], "area_m2": 25.5,
    }, headers=auth_headers).json()
    assert rm["parent_id"] == f["id"]
    assert rm["type"] == "room"

    # Create zone under room
    z = httpx.post(f"{API}/projects/{project_id}/locations", json={
        "type": "zone", "name": "Стена Юг", "parent_id": rm["id"],
    }, headers=auth_headers).json()
    assert z["parent_id"] == rm["id"]


# ── Test 3: Get full tree (nested JSON) ──────────────────────────

def test_get_tree(auth_headers, project_id):
    r = httpx.get(f"{API}/projects/{project_id}/locations", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert "tree" in data
    assert data["total"] >= 4  # building + floor + room + zone
    # Check nesting
    buildings = [n for n in data["tree"] if n["type"] == "building"]
    assert len(buildings) >= 1


# ── Test 4: Update a node ────────────────────────────────────────

def test_update_location(auth_headers, project_id):
    # Create a temp node
    n = httpx.post(f"{API}/projects/{project_id}/locations", json={
        "type": "room", "name": "Temp Room",
    }, headers=auth_headers).json()
    
    r = httpx.put(f"{API}/locations/{n['id']}", json={
        "name": "Спалня", "area_m2": 18.0,
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["name"] == "Спалня"
    assert r.json()["metadata"]["area_m2"] == 18.0

    # Cleanup
    httpx.delete(f"{API}/locations/{n['id']}", headers=auth_headers)


# ── Test 5: Delete blocked if has children ────────────────────────

def test_delete_blocked_with_children(auth_headers, project_id):
    parent = httpx.post(f"{API}/projects/{project_id}/locations", json={
        "type": "building", "name": "DeleteTest Parent",
    }, headers=auth_headers).json()

    child = httpx.post(f"{API}/projects/{project_id}/locations", json={
        "type": "floor", "name": "DeleteTest Child", "parent_id": parent["id"],
    }, headers=auth_headers).json()

    # Try deleting parent — should fail
    r = httpx.delete(f"{API}/locations/{parent['id']}", headers=auth_headers)
    assert r.status_code == 400
    assert "child" in r.json()["detail"].lower()

    # Delete child first, then parent
    httpx.delete(f"{API}/locations/{child['id']}", headers=auth_headers)
    r2 = httpx.delete(f"{API}/locations/{parent['id']}", headers=auth_headers)
    assert r2.status_code == 200


# ── Test 6: Get children of a node ───────────────────────────────

def test_get_children(auth_headers, project_id):
    parent = httpx.post(f"{API}/projects/{project_id}/locations", json={
        "type": "building", "name": "ChildrenTest",
    }, headers=auth_headers).json()

    c1 = httpx.post(f"{API}/projects/{project_id}/locations", json={
        "type": "floor", "name": "Child1", "parent_id": parent["id"], "sort_order": 1,
    }, headers=auth_headers).json()
    c2 = httpx.post(f"{API}/projects/{project_id}/locations", json={
        "type": "floor", "name": "Child2", "parent_id": parent["id"], "sort_order": 2,
    }, headers=auth_headers).json()

    r = httpx.get(f"{API}/locations/{parent['id']}/children", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] == 2
    names = [c["name"] for c in r.json()["children"]]
    assert "Child1" in names
    assert "Child2" in names

    # Cleanup
    httpx.delete(f"{API}/locations/{c1['id']}", headers=auth_headers)
    httpx.delete(f"{API}/locations/{c2['id']}", headers=auth_headers)
    httpx.delete(f"{API}/locations/{parent['id']}", headers=auth_headers)


# ── Test 7: SMR linkage at location ──────────────────────────────

def test_smr_at_location(auth_headers, project_id):
    # Create a location
    loc = httpx.post(f"{API}/projects/{project_id}/locations", json={
        "type": "room", "name": "SMRTestRoom",
    }, headers=auth_headers).json()

    # Get SMR at this location (should be empty initially)
    r = httpx.get(f"{API}/locations/{loc['id']}/smr", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] == 0

    # Cleanup
    httpx.delete(f"{API}/locations/{loc['id']}", headers=auth_headers)


# ── Test 8: Reverse lookup ────────────────────────────────────────

def test_reverse_lookup(auth_headers, project_id):
    r = httpx.get(
        f"{API}/projects/{project_id}/smr-reverse-lookup?smr_type=Шпакловка",
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert "results" in r.json()
    assert "total" in r.json()


# ── Test 9: Invalid type rejected ─────────────────────────────────

def test_invalid_type(auth_headers, project_id):
    r = httpx.post(f"{API}/projects/{project_id}/locations", json={
        "type": "invalid_type", "name": "Test",
    }, headers=auth_headers)
    assert r.status_code == 400


# ── Test 10: 404 for non-existent location ────────────────────────

def test_not_found(auth_headers):
    r = httpx.get(f"{API}/locations/nonexistent-id-xyz", headers=auth_headers)
    assert r.status_code == 404
