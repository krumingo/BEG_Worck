"""
FIX-PERM-01 (Р98, Krum 16.11.2026) — the Technical Manager sees people without money.

Р98 (``docs/ops/DECISIONS.md`` on ``claude/happy-meitner-bmcnel``): on "Служители",
"Служител" and "Календар на работниците" SiteManager sees the people, positions and the
calendar (where, leave, sick) but not rates, salaries and advances; the server returns him
only those fields; the screen and the server use one rule.

Defect on de720f94 (role-bot run, ~1 200 x 403): the frontend opened the three screens for
SiteManager, the backend refused ``GET /employees``, ``/employees/{id}/dashboard`` and
``/employees/{id}/calendar`` (``hr.payroll_permission`` = Owner/Admin/Accountant).

The rule lives in ``app/permissions/people_read.py`` (backend) and
``frontend/src/lib/financeAccess.js`` ``PEOPLE_VIEW_ROLES`` (frontend mirror).

Real Mongo (a disposable LOCAL replica set; the ST-01 synthetic tenants A and B; real JWT
from ``/api/auth/login``; the whole ``server.app``; off / shadow / enforce):

    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27081/?replicaSet=rs0&directConnection=true' \\
        PYTHONPATH=. pytest tests/test_fix_perm_01_people_read.py -v --noconftest

Without ``W0_03_REAL_MONGO_URL`` only the DB-free tests run.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
FRONTEND_ACCESS = REPO / "frontend" / "src" / "lib" / "financeAccess.js"

MODES = ("off", "shadow", "enforce")
FINANCE_KEYS = ("owner", "admin", "accountant")
REFUSED_KEYS = ("technician", "driver", "viewer", "warehousekeeper")
DB_PREFIX_OP, DB_PREFIX_SYS = "fp01_op_", "fp01_sys_"

# Every key that carries pay / money in these three responses (checked recursively, at any
# depth) — plus the generic SEC-02 money-key rule ``finance_read.is_money_key``.
MONEY_KEYS = frozenset({
    "pay_type", "hourly_rate", "daily_rate", "monthly_salary", "akord_note",
    "insurance_pct", "insurance_amount", "pay_schedule", "salary", "rate",
    "advances", "advance", "loans", "loan", "balance", "remaining", "amount",
    "earned", "earned_amount", "gross_pay", "net_pay", "base_amount", "payslips",
    "pay_runs", "payroll", "payroll_status", "overhead", "overhead_cost", "labor_value",
    "labor_cost", "value", "total_value", "bonuses", "deductions",
    "standard_hours_per_day", "working_days_per_month",
})
SEEDED_MONEY = ("2222.22", "111.11", "13.13", "7777")   # values that must never leak
# Counts the generic rule would call money because of the word "total" (declared here, as
# SEC-02 declares ``keep`` next to a route): number of present days / of projects.
COUNT_KEYS = ("total_present", "total_projects")


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _pm01():
    return _load("fp01_pm01_helpers", "test_pm_01_permission_matrix.py")


def money_keys_anywhere(value: Any, path: str = "") -> List[str]:
    from app.permissions.finance_read import is_money_key
    found: List[str] = []
    if isinstance(value, dict):
        keys = list(value)
        for k, v in value.items():
            p = "%s.%s" % (path, k) if path else str(k)
            if k in MONEY_KEYS or (isinstance(k, str) and is_money_key(k, keys, COUNT_KEYS)):
                found.append(p)
            found.extend(money_keys_anywhere(v, p))
    elif isinstance(value, list):
        for v in value:
            found.extend(money_keys_anywhere(v, path + "[]"))
    return found


# ═════════════════════════════════════════════════════════════════ DB-free tests
def test_the_rule_is_finance_plus_site_manager_and_money_is_finance_only():
    from app.permissions.people_read import PEOPLE_READ_ROLES, PEOPLE_MONEY_ROLES
    from app.permissions.money_write import FINANCE_WRITE_ROLES
    assert sorted(PEOPLE_MONEY_ROLES) == sorted(FINANCE_WRITE_ROLES) == \
        ["Accountant", "Admin", "Owner"]
    assert sorted(PEOPLE_READ_ROLES) == ["Accountant", "Admin", "Owner", "SiteManager"]


def test_the_frontend_mirror_matches_the_backend_rule():
    from app.permissions.people_read import PEOPLE_READ_ROLES
    src = FRONTEND_ACCESS.read_text(encoding="utf-8")
    m = re.search(r"export const PEOPLE_VIEW_ROLES = \[([^\]]*)\];", src)
    assert m, "PEOPLE_VIEW_ROLES missing in financeAccess.js"
    assert sorted(re.findall(r'"([^"]+)"', m.group(1))) == sorted(PEOPLE_READ_ROLES)
    assert "export function canReadPeople(role)" in src
    app_js = (REPO / "frontend" / "src" / "App.js").read_text(encoding="utf-8")
    for route, page in (("/employees", "EmployeesPage"), ("/employees/:userId", "EmployeeDetailPage"),
                        ("/worker-calendar", "WorkerCalendarPage")):
        assert ('<Route path="%s" element={<PeopleRoute><%s /></PeopleRoute>} />'
                % (route, page)) in app_js, route
    cal = (REPO / "frontend" / "src" / "pages" / "WorkerCalendarPage.js").read_text(encoding="utf-8")
    assert "seesMoney ? API.get(`/overhead/realtime" in cal       # no 403 call for SiteManager


def test_the_no_money_views_are_allow_lists():
    from app.permissions import people_read as pr
    prof = {"id": "p", "user_id": "u", "position": "Зидар", "active": True,
            "pay_type": "Monthly", "hourly_rate": 13.13, "monthly_salary": 2222.22,
            "some_future_field": 1}
    row = pr.employee_row_no_money({"id": "u", "first_name": "A", "role": "Technician",
                                    "secret": "x", "profile": prof, "has_profile": True})
    assert row == {"id": "u", "first_name": "A", "role": "Technician", "has_profile": True,
                   "money_hidden": True,
                   "profile": {"id": "p", "user_id": "u", "position": "Зидар", "active": True}}
    dash = pr.dashboard_no_money({"employee": {"id": "u"}, "profile": prof,
                                  "attendance": [{"date": "d", "status": "Present", "cost": 1}],
                                  "project_history": [], "hours_summary": {},
                                  "payslips": [{"gross_pay": 1}]})
    assert "payslips" not in dash and money_keys_anywhere(dash) == []
    cal = pr.calendar_no_money({"month": "2026-11", "total_hours": 8, "total_present": 1, "days": [
        {"date": "2026-11-02", "total_hours": 8, "attendance": {"status": "Sick", "x": 1},
         "reports": [{"report_id": "r", "hours": 8, "payroll_status": "paid", "value": 7777}],
         "work_reports": [{"project_code": "P", "hours": 8, "value": 1}]}]})
    assert money_keys_anywhere(cal) == []
    assert cal["days"][0]["attendance"] == {"status": "Sick"}
    assert cal["days"][0]["reports"] == [{"report_id": "r", "hours": 8}]


def test_the_write_routes_keep_the_payroll_rule():
    """Р98 opens READS only: every employee / advance write still calls payroll_permission."""
    src = (BACKEND / "app" / "routes" / "hr.py").read_text(encoding="utf-8")
    for decorator, fn in (('@router.post("/employees"', "upsert_employee_profile"),
                          ('@router.put("/employees/{user_id}")', "update_employee_profile"),
                          ('@router.put("/employees/{user_id}/basic")', None),
                          ('@router.post("/advances"', "create_advance")):
        start = src.index(decorator)
        body = src[start:src.index("@router.", start + 10)]
        assert "if not payroll_permission(user):" in body, decorator
        assert "people_view" not in body, decorator


# ═════════════════════════════════════════════════════════════════ real Mongo harness
def _today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


async def seed_people(op_db, fx: Dict[str, Any]) -> None:
    """Per tenant: the 'denied' user (the subject) gets a profile full of money, an
    attendance day, an approved + paid daily report, a sick day, an advance."""
    today = _today()
    month = today[:7]
    other = month + ("-14" if today[-2:] == "15" else "-15")
    now = datetime.now(timezone.utc).isoformat()
    for tkey, t in fx.items():
        org, p1, subj = t["tenant_id"], t["project_id"], t["users"]["denied"]["id"]
        await op_db.employee_profiles.insert_one({
            "id": "fp01-%s-prof" % tkey, "org_id": org, "user_id": subj, "pay_type": "Monthly",
            "position": "Зидар %s" % tkey, "hourly_rate": 13.13, "daily_rate": 111.11,
            "monthly_salary": 2222.22, "akord_note": "7777 на задача", "insurance_pct": 0.3,
            "insurance_amount": 77.77, "standard_hours_per_day": 8,
            "working_days_per_month": 22, "pay_schedule": "Monthly", "active": True,
            "start_date": "2026-01-05", "created_at": now, "updated_at": now})
        await op_db.attendance_entries.insert_one({
            "id": "fp01-%s-att" % tkey, "org_id": org, "date": today, "project_id": p1,
            "user_id": subj, "status": "Present", "note": "", "marked_at": now,
            "marked_by_user_id": subj, "source": "fp01"})
        await op_db.employee_daily_reports.insert_one({
            "id": "fp01-%s-dr" % tkey, "org_id": org, "worker_id": subj, "date": today,
            "project_id": p1, "smr_type": "Мазилка", "hours": 8, "status": "APPROVED",
            "payroll_status": "paid", "hourly_rate": 13.13, "labor_value": 105.04,
            "created_at": now})
        await op_db.employee_daily_reports.insert_one({
            "id": "fp01-%s-sick" % tkey, "org_id": org, "employee_id": subj,
            "report_date": other, "day_status": "SICK", "approval_status": "APPROVED",
            "total_hours": 0, "day_entries": []})
        await op_db.advances.insert_one({
            "id": "fp01-%s-adv" % tkey, "org_id": org, "user_id": subj, "type": "Advance",
            "amount": 7777.0, "remaining_amount": 7777.0, "currency": "EUR",
            "status": "active", "issued_date": today, "created_at": now})


def run_harness(mongo_url: str, out_json: Path) -> Dict[str, Any]:
    pm = _pm01()
    op_name, sys_name = os.environ["DB_NAME"], os.environ["BEG_SYSTEM_DB"]
    assert op_name.startswith(DB_PREFIX_OP) and sys_name.startswith(DB_PREFIX_SYS)
    import server
    from fastapi.testclient import TestClient

    app = server.app
    app.router.on_startup.clear()
    app.router.on_shutdown.clear()
    seed_mod = pm._load_seed()
    dbs = (op_name, sys_name)
    rows: List[Dict[str, Any]] = []
    with TestClient(app, raise_server_exceptions=False) as tc:
        client = tc.portal.call(lambda: pm._make_client(mongo_url))
        oplog = client.local["oplog.rs"]
        report = tc.portal.call(lambda: seed_mod.seed(client[op_name], client[sys_name],
                                                      pm.SYNTH_PASSWORD))
        fx = {t["key"]: {"tenant_id": t["tenant_id"], "project_id": t["project_id"],
                         "users": {u["key"]: u for u in t["users"]}} for t in report["tenants"]}
        tc.portal.call(lambda: seed_people(client[op_name], fx))
        a, b = fx["A"], fx["B"]
        subj, foreign = a["users"]["denied"]["id"], b["users"]["denied"]["id"]
        keys = ("requester",) + FINANCE_KEYS + REFUSED_KEYS
        tokens = {}
        for key in keys:
            r = tc.post("/api/auth/login", json={"email": a["users"][key]["email"],
                                                 "password": pm.SYNTH_PASSWORD})
            assert r.status_code == 200, (key, r.text[:200])
            tokens[key] = r.json()["token"]
        snap = tc.portal.call(lambda: pm._snapshot(client, dbs))
        reads = [("list", "GET", "/api/employees", None),
                 ("dashboard", "GET", "/api/employees/%s/dashboard" % subj, None),
                 ("calendar", "GET", "/api/employees/%s/calendar" % subj, None),
                 ("foreign_dashboard", "GET", "/api/employees/%s/dashboard" % foreign, None),
                 ("foreign_calendar", "GET", "/api/employees/%s/calendar" % foreign, None)]
        writes = [("w_create", "POST", "/api/employees",
                   {"user_id": subj, "pay_type": "Monthly", "monthly_salary": 9999}),
                  ("w_update", "PUT", "/api/employees/%s" % subj, {"monthly_salary": 9999}),
                  ("w_basic", "PUT", "/api/employees/%s/basic" % subj, {"first_name": "X"}),
                  ("w_advance", "POST", "/api/advances",
                   {"user_id": subj, "type": "Advance", "amount": 100}),
                  ("w_calendar", "POST", "/api/worker-calendar",
                   {"worker_id": subj, "date": _today(), "status": "sick_paid"})]
        own = ("own_dashboard", "GET",
               "/api/employees/%s/dashboard" % a["users"]["technician"]["id"], None)
        for mode in MODES:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            calls = [(k, c) for k in keys for c in reads]
            calls += [("requester", c) for c in writes] + [("technician", own)]
            for key, (name, method, url, body) in calls:
                before = tc.portal.call(lambda: pm._last_ts(oplog))
                kw: Dict[str, Any] = {"headers": {"Authorization": "Bearer " + tokens[key],
                                                  "Idempotency-Key": "fp01-%s" % uuid.uuid4().hex}}
                if body is not None:
                    kw["json"] = body
                resp = tc.request(method, url, **kw)
                written = tc.portal.call(lambda: pm._writes_since(oplog, before, dbs))
                if written:
                    tc.portal.call(lambda: pm._restore(client, snap, written))
                try:
                    payload = resp.json()
                except Exception:                           # noqa: BLE001
                    payload = None
                rows.append({"mode": mode, "role": key, "call": name, "status": resp.status_code,
                             "body": payload, "text": resp.text,
                             "business_writes": [n for n in written
                                                 if n.split(".", 1)[1] not in pm.AUDIT_COLLECTIONS]})
        os.environ["PERMISSION_SERVICE_MODE"] = "off"
    data = {"tenant_a_users": [u["id"] for u in a["users"].values()],
            "tenant_b_users": [u["id"] for u in b["users"].values()],
            "subject": subj, "rows": rows}
    out_json.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    return data


def run_in_child(mongo_url: str, out_json: Path, timeout: int = 1800) -> Dict[str, Any]:
    pm = _pm01()
    suffix = uuid.uuid4().hex[:12]
    op_name, sys_name = DB_PREFIX_OP + suffix, DB_PREFIX_SYS + suffix
    cmd = [sys.executable, str(Path(__file__).resolve()), "--child", "--mongo-url", mongo_url,
           "--out-json", str(out_json)]
    try:
        subprocess.run(cmd, cwd=str(BACKEND), timeout=timeout, check=True,
                       env=pm.child_env(mongo_url, op_name, sys_name))
    finally:
        import pymongo
        c = pymongo.MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
        for name in (op_name, sys_name):
            assert name.startswith((DB_PREFIX_OP, DB_PREFIX_SYS))
            c.drop_database(name)
        c.close()
    return json.loads(out_json.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    url = os.environ.get("W0_03_REAL_MONGO_URL")
    if not url:
        pytest.skip("W0_03_REAL_MONGO_URL not set (a disposable local replica set)")
    return run_in_child(url, tmp_path_factory.mktemp("fp01") / "result.json")


def _rows(run, **flt):
    out = [r for r in run["rows"] if all(r[k] == v for k, v in flt.items())]
    assert out, flt
    return out


@pytest.mark.parametrize("mode", MODES)
def test_site_manager_reads_the_three_screens_without_money(run, mode):
    for call in ("list", "dashboard", "calendar"):
        r = _rows(run, mode=mode, role="requester", call=call)[0]
        assert r["status"] == 200, (mode, call, r["text"][:300])
        assert money_keys_anywhere(r["body"]) == [], (mode, call, money_keys_anywhere(r["body"]))
        for v in SEEDED_MONEY:
            assert v not in r["text"], (mode, call, v)
        assert r["business_writes"] == []
    lst = _rows(run, mode=mode, role="requester", call="list")[0]["body"]
    me = next(e for e in lst if e["id"] == run["subject"])
    assert me["profile"]["position"] == "Зидар A" and me["role"] == "Viewer"
    assert {e["id"] for e in lst} <= set(run["tenant_a_users"])          # tenant A only
    dash = _rows(run, mode=mode, role="requester", call="dashboard")[0]["body"]
    assert dash["profile"]["position"] == "Зидар A" and "payslips" not in dash
    assert dash["attendance"] and dash["attendance"][0]["status"] == "Present"
    cal = _rows(run, mode=mode, role="requester", call="calendar")[0]["body"]
    statuses = {(d.get("attendance") or {}).get("status") for d in cal["days"]}
    assert {"Present", "Sick"} <= statuses
    assert cal["total_hours"] == 8


@pytest.mark.parametrize("mode", MODES)
def test_finance_roles_keep_the_money(run, mode):
    for key in FINANCE_KEYS:
        lst = _rows(run, mode=mode, role=key, call="list")[0]
        assert lst["status"] == 200
        me = next(e for e in lst["body"] if e["id"] == run["subject"])
        assert me["profile"]["monthly_salary"] == 2222.22 and me["profile"]["hourly_rate"] == 13.13
        assert "money_hidden" not in me
        dash = _rows(run, mode=mode, role=key, call="dashboard")[0]
        assert dash["status"] == 200 and "payslips" in dash["body"]
        assert dash["body"]["profile"]["daily_rate"] == 111.11
        cal = _rows(run, mode=mode, role=key, call="calendar")[0]
        assert cal["status"] == 200 and "money_hidden" not in cal["body"]
        assert any(rep.get("payroll_status") == "paid"
                   for d in cal["body"]["days"] for rep in d.get("reports", []))


@pytest.mark.parametrize("mode", MODES)
def test_other_roles_are_still_refused(run, mode):
    for key in REFUSED_KEYS:
        for call in ("list", "dashboard", "calendar"):
            r = _rows(run, mode=mode, role=key, call=call)[0]
            assert r["status"] == 403, (mode, key, call, r["status"])
            assert r["business_writes"] == []


@pytest.mark.parametrize("mode", MODES)
def test_own_record_is_unchanged(run, mode):
    r = _rows(run, mode=mode, role="technician", call="own_dashboard")[0]
    assert r["status"] == 200 and "payslips" in r["body"]


@pytest.mark.parametrize("mode", MODES)
def test_site_manager_writes_are_still_refused_and_write_nothing(run, mode):
    for call in ("w_create", "w_update", "w_basic", "w_advance", "w_calendar"):
        r = _rows(run, mode=mode, role="requester", call=call)[0]
        assert r["status"] == 403, (mode, call, r["status"], r["text"][:200])
        assert r["business_writes"] == [], (mode, call, r["business_writes"])


@pytest.mark.parametrize("mode", MODES)
def test_tenant_isolation(run, mode):
    """An employee of tenant B is 'not found' for every caller of tenant A."""
    for key in ("requester",) + FINANCE_KEYS:
        for call in ("foreign_dashboard",):
            r = _rows(run, mode=mode, role=key, call=call)[0]
            assert r["status"] == 404, (mode, key, call, r["status"])
            assert "Зидар B" not in r["text"]
        cal = _rows(run, mode=mode, role=key, call="foreign_calendar")[0]
        # the calendar has no existence check: it must come back EMPTY, never B's days
        assert cal["status"] == 200 and cal["body"]["days"] == [], (mode, key, cal["text"][:200])
        lst = _rows(run, mode=mode, role=key, call="list")[0]["body"]
        assert not ({e["id"] for e in lst} & set(run["tenant_b_users"]))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="FIX-PERM-01 people read harness")
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--mongo-url", default=os.environ.get("W0_03_REAL_MONGO_URL", ""))
    parser.add_argument("--out-json", required=True)
    args = parser.parse_args(argv)
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    _pm01()._check_local(args.mongo_url)
    run_harness(args.mongo_url, Path(args.out_json))
    return 0


if __name__ == "__main__":
    sys.exit(main())
