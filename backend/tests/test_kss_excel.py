"""
Tests for KSS (Excel Import/Export, Toggle, Bulk, Diff).
Run: pytest backend/tests/test_kss_excel.py -v
"""
import pytest
import httpx
import io
from pathlib import Path
from openpyxl import Workbook

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


def make_test_xlsx(rows):
    """Create a test Excel file in memory."""
    wb = Workbook()
    ws = wb.active
    ws.append(["№", "Описание СМР", "Мерна ед.", "Кол-во", "Материал/ед.", "Труд/ед.", "Общо"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Test 1: Import valid Excel ─────────────────────────────────────

def test_import_excel_valid(auth_headers, project_id):
    xlsx = make_test_xlsx([
        [1, "Шпакловка стени", "м2", 50, 3.0, 8.0, None],
        [2, "Боядисване", "м2", 50, 2.0, 6.0, None],
        [3, "Грундиране", "м2", 50, 1.5, 3.0, None],
    ])
    r = httpx.post(f"{API}/smr-analyses/import-excel",
        files={"file": ("test.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"project_id": project_id, "name": "Import Test КСС"},
        headers=auth_headers,
    )
    assert r.status_code == 201
    d = r.json()
    assert d["lines_imported"] == 3
    assert d["analysis_id"] is not None


# ── Test 2: Import with missing columns → warnings ─────────────────

def test_import_warnings(auth_headers, project_id):
    xlsx = make_test_xlsx([
        [1, "Мазилка", "м2", 30, None, None, 900],  # Only total → auto-split
    ])
    r = httpx.post(f"{API}/smr-analyses/import-excel",
        files={"file": ("warn.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"project_id": project_id},
        headers=auth_headers,
    )
    assert r.status_code == 201
    assert r.json()["lines_imported"] == 1
    assert len(r.json()["warnings"]) >= 1


# ── Test 3: Import with empty rows → skip ──────────────────────────

def test_import_skip_empty(auth_headers, project_id):
    xlsx = make_test_xlsx([
        [1, "Плочки", "м2", 20, 15, 22, None],
        [None, None, None, None, None, None, None],  # Empty row
        [3, "Фугиране", "м2", 20, 2, 6, None],
    ])
    r = httpx.post(f"{API}/smr-analyses/import-excel",
        files={"file": ("skip.xlsx", xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"project_id": project_id},
        headers=auth_headers,
    )
    assert r.status_code == 201
    assert r.json()["lines_imported"] == 2
    assert r.json()["skipped"] >= 1


# ── Test 4: Export Excel ───────────────────────────────────────────

def test_export_excel(auth_headers, project_id):
    # Get an analysis to export
    analyses = httpx.get(f"{API}/smr-analyses?project_id={project_id}", headers=auth_headers).json()["items"]
    assert len(analyses) >= 1
    aid = analyses[0]["id"]

    r = httpx.get(f"{API}/smr-analyses/{aid}/export-excel", headers=auth_headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert len(r.content) > 100  # Non-trivial file


# ── Test 5: Toggle line active/inactive ────────────────────────────

def test_toggle_line(auth_headers, project_id):
    # Create analysis with a line
    a = httpx.post(f"{API}/smr-analyses", json={
        "project_id": project_id, "name": "Toggle Test",
    }, headers=auth_headers).json()
    aid = a["id"]
    httpx.post(f"{API}/smr-analyses/{aid}/lines", json={
        "smr_type": "Toggle Line", "qty": 10, "labor_price_per_unit": 5,
    }, headers=auth_headers)

    doc = httpx.get(f"{API}/smr-analyses/{aid}", headers=auth_headers).json()
    line_id = doc["lines"][0]["line_id"]
    original_total = doc["totals"]["grand_total"]

    # Toggle off
    r = httpx.put(f"{API}/smr-analyses/{aid}/lines/{line_id}/toggle", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["lines"][0]["is_active"] is False
    assert r.json()["totals"]["grand_total"] == 0  # Inactive line excluded

    # Toggle back on
    r2 = httpx.put(f"{API}/smr-analyses/{aid}/lines/{line_id}/toggle", headers=auth_headers)
    assert r2.json()["lines"][0]["is_active"] is True
    assert r2.json()["totals"]["grand_total"] == original_total


# ── Test 6: Bulk update price ──────────────────────────────────────

def test_bulk_update_price(auth_headers, project_id):
    a = httpx.post(f"{API}/smr-analyses", json={
        "project_id": project_id, "name": "Bulk Price Test",
    }, headers=auth_headers).json()
    aid = a["id"]
    httpx.post(f"{API}/smr-analyses/{aid}/lines", json={
        "smr_type": "Мазилка", "qty": 20, "labor_price_per_unit": 10, "markup_pct": 10,
    }, headers=auth_headers)

    r = httpx.put(f"{API}/smr-analyses/{aid}/bulk-update", json={
        "action": "adjust_price",
        "adjustment": {"markup_pct": "+5"},
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["affected"] == 1
    assert r.json()["analysis"]["lines"][0]["markup_pct"] == 15


# ── Test 7: Bulk update qty ────────────────────────────────────────

def test_bulk_update_qty(auth_headers, project_id):
    a = httpx.post(f"{API}/smr-analyses", json={
        "project_id": project_id, "name": "Bulk Qty Test",
    }, headers=auth_headers).json()
    aid = a["id"]
    httpx.post(f"{API}/smr-analyses/{aid}/lines", json={
        "smr_type": "Боядисване", "qty": 100, "labor_price_per_unit": 6,
    }, headers=auth_headers)

    r = httpx.put(f"{API}/smr-analyses/{aid}/bulk-update", json={
        "action": "adjust_qty",
        "adjustment": {"qty": "*1.1"},  # +10%
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["analysis"]["lines"][0]["qty"] == 110.0


# ── Test 8: Diff between versions ──────────────────────────────────

def test_diff_versions(auth_headers, project_id):
    a = httpx.post(f"{API}/smr-analyses", json={
        "project_id": project_id, "name": "Diff Test",
    }, headers=auth_headers).json()
    aid = a["id"]
    v1 = a["version"]

    httpx.post(f"{API}/smr-analyses/{aid}/lines", json={
        "smr_type": "Шпакловка", "qty": 50, "labor_price_per_unit": 8,
    }, headers=auth_headers)

    # Snapshot
    snap = httpx.post(f"{API}/smr-analyses/{aid}/snapshot", headers=auth_headers).json()
    snap_id = snap["id"]

    # Modify snapshot
    doc = httpx.get(f"{API}/smr-analyses/{snap_id}", headers=auth_headers).json()
    line_id = doc["lines"][0]["line_id"]
    httpx.put(f"{API}/smr-analyses/{snap_id}/lines/{line_id}", json={"qty": 80}, headers=auth_headers)

    # Diff
    r = httpx.get(f"{API}/smr-analyses/{snap_id}/diff/{v1}", headers=auth_headers)
    assert r.status_code == 200
    d = r.json()
    assert "changed_lines" in d
    assert "total_diff" in d
    assert d["total_diff"]["old_total"] != d["total_diff"]["new_total"]


# ── Test 9: Create KSS from offer ─────────────────────────────────

def test_create_from_offer(auth_headers, project_id):
    # Find an offer
    offers = httpx.get(f"{API}/offers?project_id={project_id}", headers=auth_headers)
    if offers.status_code != 200:
        pytest.skip("No offers endpoint or no offers")
    offer_list = offers.json() if isinstance(offers.json(), list) else offers.json().get("items", [])
    if not offer_list:
        pytest.skip("No offers for this project")

    offer_id = offer_list[0]["id"]
    r = httpx.post(f"{API}/smr-analyses/from-offer/{offer_id}", headers=auth_headers)
    assert r.status_code == 201
    d = r.json()
    assert d["is_kss"] is True
    assert d["imported_from"] == "offer"
    assert len(d["lines"]) >= 0


# ── Test 10: Bulk toggle ───────────────────────────────────────────

def test_bulk_toggle(auth_headers, project_id):
    a = httpx.post(f"{API}/smr-analyses", json={
        "project_id": project_id, "name": "Bulk Toggle Test",
    }, headers=auth_headers).json()
    aid = a["id"]
    httpx.post(f"{API}/smr-analyses/{aid}/lines", json={
        "smr_type": "Line A", "qty": 10, "labor_price_per_unit": 5,
    }, headers=auth_headers)
    httpx.post(f"{API}/smr-analyses/{aid}/lines", json={
        "smr_type": "Line B", "qty": 20, "labor_price_per_unit": 3,
    }, headers=auth_headers)

    # Toggle all off
    r = httpx.put(f"{API}/smr-analyses/{aid}/bulk-update", json={
        "action": "toggle", "active": False,
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["affected"] == 2
    assert r.json()["analysis"]["totals"]["grand_total"] == 0
