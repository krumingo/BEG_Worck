"""
SEC-02 — reading money per the canon (FLOW-002, FLOW-010; decision R20, Krum 06.11.2026;
FLOW Guard FG-1 GET, FG-12, FG-14, FG-15).

Package: ``docs/architecture/tasks/SEC-02_FINANCE_READ_PER_CANON.md`` (branch
``claude/happy-meitner-bmcnel``) with its R20 addendum. Registry of every guarded read
(endpoint -> action -> rule -> canon): ``app/permissions/finance_read.py``.

Rules under test (``finance_read.RULE_TEXT``):
  R20-1   company finance: Owner/Admin/Accountant; everyone else 403, nothing written.
  R20-2   project money: Owner/Admin/Accountant on every project; everyone else 403 —
          SiteManager, Technician, Viewer and Driver even as MEMBERS of the project.
  R20-2B  project budget view: finance roles everywhere; SiteManager only on a project he
          is a CURRENT member of (P1); on P2 his membership starts tomorrow -> 403;
          Technician/Viewer/Driver 403 even as members. For SiteManager the SMR-group and
          location amounts (client prices) are absent from expected-actual.
  R20-5   shared screens (all-reports, weekly matrix, GET/POST /labor-entries): reached
          as before, but no money key (rate, cost, value, pay) in the response of a
          non-finance caller. GET /labor-entries for a non-finance caller: only rows of
          CURRENT member projects; a project filter on a non-member project -> 403.

Every probe runs on EXISTING records (PM-01 ``seed_existing_records`` + SEC-01-C02
``seed_c02_records`` + the SEC-02 records below), with the SEC-01-C02 team on P1
(SiteManager, Technician, Viewer, Driver) and the dated SEC-R1 memberships on P2, for
tenants A and B, the eight ST-01 roles and the three PERMISSION_SERVICE_MODEs, plus
tenant B's callers on tenant A's project.

    PYTHONPATH=. pytest tests/test_sec_02_finance_read.py -v --noconftest
    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \\
        PYTHONPATH=. pytest tests/test_sec_02_finance_read.py -v --noconftest
    # regenerate the evidence:
    PYTHONPATH=. python tests/test_sec_02_finance_read.py --harness \\
        --mongo-url 'mongodb://127.0.0.1:27019/?directConnection=true'
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.permissions.finance_read import (  # noqa: E402
    FINANCE_READS, NOT_MONEY, R20_1, R20_2, R20_2B, R20_5, R20_5M, R20_5B, MONEY_VALUES_READ,
    BUDGET_VIEW_HIDDEN_FIELDS, SUBSCRIPTION_PRICE_FIELDS,
    EMPLOYEE_FILE_ACTION, is_money_key, strip_money,
    FINANCE_READ_ACTIONS, PROJECT_BUDGET_READ_ACTIONS, LABOR_MONEY_FIELDS,
    REPORT_LINE_MONEY_FIELDS, WEEKLY_MATRIX_MONEY_FIELDS, EXPECTED_ACTUAL_CLIENT_PRICE_FIELDS,
)

EVIDENCE = REPO / "docs" / "evidence" / "SEC-02"
RESULTS_JSON = EVIDENCE / "results.json"
PM01_REPORT = REPO / "docs" / "architecture" / "PM-01_PERMISSION_MODE_REPORT.md"
FRONTEND_ACCESS = REPO / "frontend" / "src" / "lib" / "financeAccess.js"

MODES = ("off", "shadow", "enforce")
ROLE_KEYS = ("owner", "admin", "requester", "technician", "accountant",
             "warehousekeeper", "driver", "viewer")
FINANCE = {"Owner", "Admin", "Accountant"}
DB_PREFIX_OP, DB_PREFIX_SYS = "sec02_op_", "sec02_sys_"
SYNTH_PASSWORD = "SEC02-Synthetic-Pass-2026!"    # synthetic users of a scratch database
AUDIT = {"audit_events", "audit_logs", "audit_chain_heads", "audit_chain", "audit_idempotency"}
CROSS_ROLES = ("admin", "accountant", "requester", "technician", "viewer")
# P1's team (SEC-01-C02): SiteManager, Technician, Viewer, Driver members. P2: the
# Technician's membership ended yesterday, the SiteManager's starts tomorrow.
P1_MEMBERS = {"SiteManager", "Technician", "Viewer", "Driver"}

ALL_MONEY_KEYS = (set(LABOR_MONEY_FIELDS) | set(REPORT_LINE_MONEY_FIELDS)
                  | set(WEEKLY_MATRIX_MONEY_FIELDS))

# R20-5 probes: (key, method, path, query, body-kind). Targets for labor GET: None, P1, P2.
SHARED_PROBES = (
    ("all_reports", "GET", "/api/all-reports", {"date_from": "2026-10-01",
                                                "date_to": "2026-11-30"}),
    ("weekly_matrix", "GET", "/api/weekly-matrix", {"week_of": "2026-11-02"}),
    ("labor_list", "GET", "/api/labor-entries", {}),
    ("labor_create", "POST", "/api/labor-entries", {}),
    ("subscription", "GET", "/api/subscription", {}),          # SEC-02-B: plan price
)
SHARED = {p[0]: p for p in SHARED_PROBES}


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parent / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _pm01():
    return _load("sec02_pm01_helpers", "test_pm_01_permission_matrix.py")


def _c02():
    return _load("sec02_c02_helpers", "test_sec_01_c02_flow_guard_money_writes.py")


def sid(tkey: str, name: str) -> str:
    return "pm01probe-%s-sec02-%s" % (tkey, name)


def is_project(path: str) -> bool:
    return "{project_id}" in path or "{site_id}" in path        # a site IS a project


def probes() -> List[Dict[str, Any]]:
    out = []
    for e in FINANCE_READS:
        if e.rule == R20_5:
            continue
        out.append({"key": e.method + " " + e.path, "method": e.method, "path": e.path,
                    "rule": e.rule, "action": e.action})
    # SEC-02-A: the R20-5M probes are already above (rule R20-5M); the employee file
    # (D9) is the R20-2B row with EMPLOYEE_FILE_ACTION.
    for key, method, path, _q in SHARED_PROBES:
        out.append({"key": key, "method": method, "path": path, "rule": R20_5,
                    "action": MONEY_VALUES_READ})
    return out


def targets_for(p: Dict[str, Any]):
    if is_project(p["path"]) or p["key"] in ("labor_list", "labor_create"):
        return ("P1", "P2") + ((None,) if p["key"] == "labor_list" else ())
    return (None,)


async def seed_sec02_records(op_db, fx: Dict[str, Any]) -> None:
    """Money on P1 so that a leak would show: an SMR budget and an SMR group whose
    analysis line carries a client price, a finished work session with a labor cost."""
    now = "2026-11-06T08:00:00+00:00"
    for tkey, t in fx.items():
        org, p1 = t["tenant_id"], t["project_id"]
        tech = t["users"]["technician"]["id"]
        await op_db.activity_budgets.insert_one({
            "id": sid(tkey, "ab1"), "org_id": org, "project_id": p1, "type": "Мазилка",
            "labor_budget": 5000, "material_budget": 0, "coefficient": 1,
            "planned_man_hours": 100, "created_at": now})
        await op_db.smr_groups.insert_one({"id": sid(tkey, "grp1"), "org_id": org,
                                           "project_id": p1, "name": "Probe group",
                                           "created_at": now})
        await op_db.smr_analyses.insert_one({
            "id": sid(tkey, "an1"), "org_id": org, "project_id": p1, "created_at": now,
            "lines": [{"line_id": "l1", "group_id": sid(tkey, "grp1"), "is_active": True,
                       "smr_type": "Мазилка", "qty": 10, "final_total": 7777.0,
                       "labor_price_per_unit": 10}]})
        await op_db.offers.insert_one({
            "id": sid(tkey, "off1"), "org_id": org, "project_id": p1, "offer_no": "SEC02-1",
            "status": "Draft", "currency": "EUR", "created_at": now, "updated_at": now,
            "lines": [{"id": "ol1", "activity_name": "Мазилка", "unit": "m2", "qty": 10,
                       "material_unit_cost": 3, "labor_unit_cost": 4, "unit_price": 777.7,
                       "line_total": 7777.0}],
            "subtotal": 7777.0, "vat_amount": 0, "total": 7777.0})
        # SEC-02-C (R31): a stored site pulse of P1 with a per-worker labor cost of 7777 —
        # the Technical Manager may see the site budget, never the 7777.
        await op_db.site_pulses.insert_one({
            "id": sid(tkey, "pulse1"), "org_id": org, "site_id": p1, "date": "2026-11-02",
            "site_name": "P1", "generated_at": now, "total_workers": 1, "total_hours": 8,
            "workers": [{"worker_id": tech, "worker_name": "T", "hours": 8, "labor_cost": 7777.0}],
            "smr_summary": [{"smr_type": "Мазилка", "total_hours": 8, "total_cost": 3200.0,
                             "workers_count": 1}],
            "total_labor_cost": 3200.0, "materials_used": [], "total_material_cost": 0,
            "budget_snapshot": {"total_budget": 5000.0, "total_spent": 3200.0,
                                "remaining": 1800.0, "burn_pct": 64.0, "status": "ok"},
            # SEC-02-G (SEC71-03): a stored alert with the >80 % text
            "alerts": [{"type": "budget_warning", "message": "Бюджетът е 85.0% изхарчен",
                        "severity": "warning"}]})
        await op_db.material_entries.insert_one({
            "id": sid(tkey, "me1"), "org_id": org, "project_id": p1, "material_name": "Probe",
            "qty": 5, "unit": "kg", "unit_cost": 7777.0, "total_cost": 7777.0,
            "date": "2026-11-02", "created_at": now})
        await op_db.work_sessions.insert_one({
            "id": sid(tkey, "ws1"), "org_id": org, "worker_id": tech, "site_id": p1,
            "smr_type_id": "Мазилка", "started_at": "2026-11-02T07:00:00",
            "ended_at": "2026-11-02T15:00:00", "duration_hours": 8, "labor_cost": 3200,
            "created_at": now})
        # SEC-02-E (FG-63): activity-budget-summary sums daily work log hours, so P1 gets
        # ONE worker there too — the screen must hide his "spent" as well.
        await op_db.work_types.insert_one({
            "id": sid(tkey, "wt1"), "org_id": org, "name": "Мазилка",
            "activity_type": "Мазилка", "default_hourly_rate": 400.0})
        await op_db.daily_work_logs.insert_one({
            "id": sid(tkey, "dwl1"), "org_id": org, "site_id": p1, "date": "2026-11-02",
            "work_type_id": sid(tkey, "wt1"),
            "entries": [{"user_id": tech, "hours": 8}], "created_at": now})
        # SEC-02-G (Codex SEC71-01): an execution package with a client price and a margin,
        # so the budget freeze answer would show them if the budget view kept them.
        await op_db.execution_packages.insert_one({
            "id": sid(tkey, "ep2"), "org_id": org, "project_id": p1,
            "activity_name": "Мазилка", "unit": "m2", "qty": 10, "sale_total": 12345.0,
            "labor_budget_total": 500.0, "material_budget_total": 100.0,
            "budget_total": 600.0, "planned_margin": 77.0, "created_at": now})
        # SEC-02-G (Codex SEC71-02, FG-74): ONE paid worker (160) and one with no pay on the
        # same day and SMR — a stored pulse of P1 and the work sessions behind it.
        driver = t["users"]["driver"]["id"]
        await op_db.site_pulses.insert_one({
            "id": sid(tkey, "pulse2"), "org_id": org, "site_id": p1, "date": "2026-11-03",
            "site_name": "P1", "generated_at": now, "total_workers": 2, "total_hours": 16,
            "workers": [{"worker_id": tech, "worker_name": "T", "hours": 8,
                         "smr_types": ["Мазилка"], "labor_cost": 160.0},
                        {"worker_id": driver, "worker_name": "D", "hours": 8,
                         "smr_types": ["Мазилка"], "labor_cost": 0}],
            "smr_summary": [{"smr_type": "Мазилка", "total_hours": 16, "total_cost": 160.0,
                             "workers_count": 2}],
            "total_labor_cost": 160.0, "materials_used": [], "total_material_cost": 0,
            "budget_snapshot": {"total_budget": 5000.0, "total_spent": 3360.0,
                                "remaining": 1640.0, "burn_pct": 67.2, "status": "ok"},
            # SEC-02-G (Codex SEC71-03): a stored alert with the >100 % text
            "alerts": [{"type": "budget_warning", "message": "Надхвърлен бюджет! (900.0%)",
                        "severity": "critical"}]})
        await op_db.work_sessions.insert_one({
            "id": sid(tkey, "ws2"), "org_id": org, "worker_id": driver, "site_id": p1,
            "smr_type_id": "Мазилка", "started_at": "2026-11-02T07:00:00",
            "ended_at": "2026-11-02T15:00:00", "duration_hours": 8, "labor_cost": 0,
            "created_at": now})
        # SEC-02-G (FLOW Guard FG-111): a stored budget alarm of P1 ("900.0%" + metric_value)
        # and an active budget rule (> 80 %) — POST /alarms/evaluate raises a new one (124 %).
        await op_db.alarm_rules.insert_one({
            "id": sid(tkey, "rule1"), "org_id": org, "name": "Бюджет над 80%",
            "type": "budget", "severity": "critical", "is_active": True,
            "condition": {"metric": "burn_pct", "operator": ">", "threshold": 80},
            "notify_roles": [], "cooldown_hours": 24, "auto_resolve": False,
            "created_at": now, "updated_at": now})
        await op_db.alarm_events.insert_one({
            "id": sid(tkey, "alarm1"), "org_id": org, "rule_id": sid(tkey, "rule1"),
            "rule_name": "Бюджет над 80%", "severity": "critical", "type": "budget",
            "site_id": p1, "site_name": "P1", "triggered_at": "2026-11-03T08:00:00+00:00",
            "message": "P1: бюджет 900.0% изхарчен",
            "context": {"metric_value": 900.0, "threshold": 80, "entity_id": p1,
                        "entity_type": "project", "details": {}},
            "status": "active", "acknowledged_by": None, "acknowledged_at": None,
            "resolved_by": None, "resolved_at": None, "resolve_notes": None})
        # SEC-02-G (SEC71-03): the SAME paid technician on 2026-11-04 — P1 stays a one-paid-
        # worker site, and its cumulative burn is 6200 / 5000 = 124 % -> a generated pulse
        # carries the ">100 %" budget alert.
        await op_db.work_sessions.insert_one({
            "id": sid(tkey, "ws3"), "org_id": org, "worker_id": tech, "site_id": p1,
            "smr_type_id": "Мазилка", "started_at": "2026-11-04T07:00:00",
            "ended_at": "2026-11-04T15:00:00", "duration_hours": 8, "labor_cost": 3000,
            "created_at": now})


def url_values(fx: Dict[str, Any], tkey: str) -> Dict[str, str]:
    t = fx[tkey]
    c02 = _c02()
    return {"worker_id": t["users"]["technician"]["id"],
            "user_id": t["users"]["technician"]["id"],
            "line_id": sid(tkey, "none"), "warehouse_id": t.get("warehouse_id") or sid(tkey, "wh"),
            "client_id": t.get("company1_id", sid(tkey, "none")),
            "run_id": sid(tkey, "none"), "snapshot_id": sid(tkey, "none"),
            "act_id": c02.rid(tkey, "cact"), "pkg_id": "pm01probe-%s-ep1" % tkey,
            "counterparty_id": sid(tkey, "none"),
            "analysis_id": sid(tkey, "an1"), "version": "1", "offer_id": sid(tkey, "off1"),
            "version_number": "1", "draft_id": sid(tkey, "none"), "module_code": "M2"}


def body_money_keys(value: Any, keep=()) -> List[str]:
    """Every money key (finance_read.is_money_key) anywhere in a JSON body."""
    found = set()

    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                if isinstance(k, str) and is_money_key(k, list(v), keep):
                    found.add(k)
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(value)
    return sorted(found)


def forbidden_budget_view_keys(value: Any) -> List[str]:
    """SEC-02-G: every key with a non-zero number that the budget view must never carry
    (``finance_read.budget_view_forbidden``: client price, sale, margin, profit, ...)."""
    from app.permissions.finance_read import budget_view_forbidden
    found = set()

    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                if budget_view_forbidden(k) and isinstance(x, (int, float)) \
                        and not isinstance(x, bool) and x != 0:
                    found.add(k)
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(value)
    return sorted(found)


def money_keys_in(value: Any, keys) -> List[str]:
    found = set()

    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                if k in keys:
                    found.add(k)
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(value)
    return sorted(found)


def money_fields_of(key: str):
    return {"all_reports": REPORT_LINE_MONEY_FIELDS, "weekly_matrix": WEEKLY_MATRIX_MONEY_FIELDS,
            "labor_list": LABOR_MONEY_FIELDS, "labor_create": LABOR_MONEY_FIELDS,
            "subscription": SUBSCRIPTION_PRICE_FIELDS}[key]


# ═════════════════════════════════════════════════════════════════ expected outcome
def expected(p: Dict[str, Any], legacy_role: str, target: Optional[str]) -> Dict[str, Any]:
    """{"reached": bool, "money": bool|None}. ``target``: None, "P1", "P2", "XA"."""
    fin = legacy_role in FINANCE
    rule, key = p["rule"], p["key"]
    if rule in (R20_1, R20_2):
        return {"reached": fin, "money": None}
    if p["action"] == EMPLOYEE_FILE_ACTION:                     # SEC-02-A, D9
        ok = fin or legacy_role == "SiteManager"
        return {"reached": ok, "money": fin if ok else None}
    if rule == R20_5M:                                         # the route keeps its own
        return {"reached": None, "money": fin}                 # access rule; money = fin
    if rule == R20_5B:                                         # SEC-02-B, FG-43
        sm = legacy_role == "SiteManager" and (target == "P1" or p["path"] == "/api/pulse/today")
        # FG-43 + SEC-02-C (B-D1): Accountant reads the four project budget screens on
        # every project; the pulse keeps its own (open) access rule.
        fg43 = p["path"].endswith(("/activities-overview", "/activity-budget-summary",
                                   "/activity-budgets", "/budget-health"))
        return {"reached": True if (fin and fg43) else None, "money": fin,
                "budget_view": sm}
    if key == "subscription":
        return {"reached": True, "money": legacy_role in ("Owner", "Admin")}
    if rule == R20_2B:
        return {"reached": fin or (legacy_role == "SiteManager" and target == "P1"),
                "money": fin}
    # R20-5
    if key == "labor_create":                                  # R16 + FG-15
        ok = fin or (legacy_role in ("SiteManager", "Technician") and target == "P1")
        return {"reached": ok, "money": fin if ok else None}
    if key == "labor_list":
        if fin:
            return {"reached": True, "money": True}
        if target is None:
            return {"reached": True, "money": False}
        return {"reached": target == "P1" and legacy_role in P1_MEMBERS, "money": False}
    return {"reached": True, "money": fin}                     # all-reports, weekly matrix


# ═══════════════════════════════════════════════════════════════════════════ harness
def run_harness(mongo_url: str, out_json: Path) -> Dict[str, Any]:
    op_name, sys_name = os.environ["DB_NAME"], os.environ["BEG_SYSTEM_DB"]
    assert op_name.startswith(DB_PREFIX_OP) and sys_name.startswith(DB_PREFIX_SYS)
    pm, c02 = _pm01(), _c02()
    import server
    from fastapi.testclient import TestClient

    app = server.app
    app.router.on_startup.clear()
    app.router.on_shutdown.clear()
    seed_mod = pm._load_seed()
    dbs = (op_name, sys_name)
    started = time.time()
    plist = probes()
    keep_of = {r.path: getattr(r.endpoint, "sec02_keep", ()) for r in app.routes
               if hasattr(r, "endpoint")}

    def short(ns: str) -> str:
        d, c = ns.split(".", 1)
        return ("op" if d == op_name else "sys") + "." + c

    with TestClient(app, raise_server_exceptions=False) as tc:
        client = tc.portal.call(lambda: pm._make_client(mongo_url))
        oplog = client.local["oplog.rs"]
        op_db = client[op_name]
        report = tc.portal.call(lambda: seed_mod.seed(client[op_name], client[sys_name],
                                                      SYNTH_PASSWORD))
        fx: Dict[str, Any] = {}
        for t in report["tenants"]:
            fx[t["key"]] = {"tenant_id": t["tenant_id"], "project_id": t["project_id"],
                            "warehouse_id": t.get("warehouse_id"),
                            "users": {u["key"]: u for u in t["users"]}}
        tc.portal.call(lambda: pm.seed_existing_records(op_db, fx))
        tc.portal.call(lambda: c02.seed_c02_records(op_db, fx))
        tc.portal.call(lambda: seed_sec02_records(op_db, fx))
        tokens: Dict[tuple, str] = {}
        for tkey in ("A", "B"):
            for key in ROLE_KEYS:
                r = tc.post("/api/auth/login", json={
                    "email": fx[tkey]["users"][key]["email"], "password": SYNTH_PASSWORD})
                assert r.status_code == 200, (tkey, key, r.status_code, r.text[:200])
                tokens[(tkey, key)] = r.json()["token"]
        # The SEC-01-C02 team, through the real API in ENFORCE (project_team + mirrors).
        os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
        for tkey in ("A", "B"):
            for ukey, role_in_project in c02.TEAM:
                r = tc.post("/api/projects/%s/team" % fx[tkey]["project_id"],
                            json={"user_id": fx[tkey]["users"][ukey]["id"],
                                  "role_in_project": role_in_project},
                            headers={"Authorization": "Bearer " + tokens[(tkey, "admin")]})
                assert r.status_code == 201, (tkey, ukey, r.status_code, r.text[:300])
            for ukey, role_in_project, kind in c02.P2_DATED:
                r = tc.post("/api/projects/%s/team" % fx[tkey]["project2_id"],
                            json={"user_id": fx[tkey]["users"][ukey]["id"],
                                  "role_in_project": role_in_project,
                                  **c02.dated_window(kind)},
                            headers={"Authorization": "Bearer " + tokens[(tkey, "admin")]})
                assert r.status_code == 201, (tkey, ukey, kind, r.status_code, r.text[:300])
        os.environ["PERMISSION_SERVICE_MODE"] = "off"
        from app.permissions.sync import project_assignment_id
        from app.tenancy import registry
        mirrors = []
        for tkey in ("A", "B"):
            uid = fx[tkey]["users"]["requester"]["id"]
            for pkey in ("project_id", "project2_id"):
                m = tc.portal.call(lambda: registry.get_role_assignment(
                    project_assignment_id(uid, fx[tkey]["tenant_id"], fx[tkey][pkey])))
                mirrors.append({"tenant": tkey, "project": "P1" if pkey == "project_id" else "P2",
                                "budget_actions": sorted(
                                    set((m or {}).get("permissions") or [])
                                    & PROJECT_BUDGET_READ_ACTIONS),
                                "finance_actions": sorted(
                                    set((m or {}).get("permissions") or [])
                                    & (FINANCE_READ_ACTIONS | {MONEY_VALUES_READ}))})
        snap = tc.portal.call(lambda: pm._snapshot(client, dbs))

        def call(mode, tkey, role, p, target):
            data_tkey = "A" if target == "XA" else tkey
            pid = {"P1": fx[data_tkey]["project_id"], "XA": fx["A"]["project_id"],
                   "P2": fx[tkey]["project2_id"], None: None}[target]
            url = p["path"]
            if pid:
                url = url.replace("{project_id}", pid).replace("{site_id}", pid)
            for name, value in url_values(fx, tkey).items():
                url = url.replace("{%s}" % name, value)
            kwargs: Dict[str, Any] = {
                "headers": {"Authorization": "Bearer " + tokens[(tkey, role)]}}
            params = dict(SHARED[p["key"]][3]) if p["key"] in SHARED else {}
            if p["key"] == "labor_list" and pid:
                params["project_id"] = pid
            if p["key"] == "labor_create":
                kwargs["json"] = {"project_id": pid, "hours": 1, "activity_name": "SEC02",
                                  "employee_id": fx[tkey]["users"]["technician"]["id"]}
                # R29 (#69): a money POST needs an Idempotency-Key — a fresh one per call
                kwargs["headers"]["Idempotency-Key"] = "sec02-%s" % uuid.uuid4().hex
            if params:
                kwargs["params"] = params
            before = tc.portal.call(lambda: pm._last_ts(oplog))
            resp = tc.request(p["method"], url, **kwargs)
            written = tc.portal.call(lambda: pm.writes_with_org(client, oplog, before, dbs,
                                                                 snap))
            if written:
                tc.portal.call(lambda: pm._restore(client, snap, sorted({n for n, _ in written})))
            try:
                body = resp.json()
            except Exception:                                  # noqa: BLE001
                body = None
            row = {"mode": mode, "tenant": tkey, "role": role,
                   "legacy_role": fx[tkey]["users"][role]["role"], "probe": p["key"],
                   "rule": p["rule"], "target": target, "status": resp.status_code,
                   "written": sorted({short(n) for n, _o in written}),
                   "foreign_ids": ("pm01probe-A-" in resp.text) if tkey == "B" else False}
            if p["key"] in SHARED:
                row["money_keys"] = money_keys_in(body, money_fields_of(p["key"]))
                if p["key"] == "labor_list" and isinstance(body, list):
                    pids = {fx[data_tkey]["project_id"]: "P1", fx[tkey]["project2_id"]: "P2"}
                    row["row_projects"] = sorted({pids.get(x.get("project_id"), "other")
                                                  for x in body})
            if (p["rule"] in (R20_5M, R20_5B) or p["action"] == EMPLOYEE_FILE_ACTION) \
                    and resp.status_code == 200:
                row["money_keys"] = body_money_keys(body, keep_of.get(p["path"], ()))
                if p["rule"] == R20_5B:
                    row["hidden_budget_keys"] = money_keys_in(body, BUDGET_VIEW_HIDDEN_FIELDS)
                if p["path"] == "/api/pulse/today" and isinstance(body, dict):
                    sites = {fx[tkey]["project_id"]: "P1", fx[tkey]["project2_id"]: "P2"}
                    row["sites_with_money"] = sorted({
                        sites.get(it.get("site_id"), "other") for it in body.get("items", [])
                        if body_money_keys(it)})
                row["leaks_7777"] = "7777" in resp.text
                if p["action"] == EMPLOYEE_FILE_ACTION and isinstance(body, dict):
                    row["has_payroll"] = "payroll" in body or "advances" in body
            if p["rule"] in (R20_2B, R20_5B) and p["action"] != EMPLOYEE_FILE_ACTION \
                    and resp.status_code in (200, 201):
                from app.permissions.finance_read import _is_actual
                row["actual_keys"] = sorted({k for k in body_money_keys(body) if _is_actual(k)})
                row["worker_detail"] = money_keys_in(body, {"workers", "workers_count"})
                # SEC-02-G (Codex SEC71-01): client prices / sale / margin / profit
                row["forbidden_keys"] = forbidden_budget_view_keys(body)
            if p["rule"] == R20_2B and resp.status_code == 200 and "expected-actual" in p["path"]:
                groups = (body.get("groups") if "groups" in body
                          else body.get("top_overruns", {}).get("groups")) or []
                row["groups"] = len(groups)
                row["group_price_keys"] = money_keys_in(groups, EXPECTED_ACTUAL_CLIENT_PRICE_FIELDS)
                row["leaks_7777"] = "7777" in resp.text
            return row

        rows: List[Dict[str, Any]] = []
        for mode in MODES:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            for tkey in ("A", "B"):
                for p in plist:
                    for target in targets_for(p):
                        for role in ROLE_KEYS:
                            rows.append(call(mode, tkey, role, p, target))
            for p in plist:
                if is_project(p["path"]):
                    for role in CROSS_ROLES:
                        rows.append(call(mode, "B", role, p, "XA"))
        # SEC-02-B (FG-15): POST /labor-entries twice with the SAME Idempotency-Key — the
        # replay (#69 SEC-01-C03) must not show the rate / cost either.
        replay = []
        for mode in MODES:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            for role in ("technician", "requester", "accountant"):
                key = "sec02b-%s-%s" % (mode, role)
                body = {"project_id": fx["A"]["project_id"], "hours": 1, "activity_name": "SEC02B",
                        "employee_id": fx["A"]["users"]["technician"]["id"]}
                hdr = {"Authorization": "Bearer " + tokens[("A", role)], "Idempotency-Key": key}
                r1 = tc.post("/api/labor-entries", json=body, headers=hdr)
                r2 = tc.post("/api/labor-entries", json=body, headers=hdr)
                replay.append({"mode": mode, "role": role,
                               "legacy_role": fx["A"]["users"][role]["role"],
                               "first": r1.status_code, "replay": r2.status_code,
                               "same_id": (r1.json() or {}).get("id") == (r2.json() or {}).get("id"),
                               "first_money": money_keys_in(r1.json(), LABOR_MONEY_FIELDS),
                               "replay_money": money_keys_in(r2.json(), LABOR_MONEY_FIELDS)})
        # SEC-02-F (FG-75): every PUT /price-modifiers writes ONE canonical AuditEvent
        # (FLOW-040 envelope, R1, before/after) in the database of the write; a refused
        # PUT writes none (only the enforce "permission denied" event).
        pm_audit = []
        n = 0
        for mode in MODES:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            for role in ("admin", "accountant", "viewer"):
                for scope, url in (("org", "/api/price-modifiers/org"),
                                   ("project", "/api/price-modifiers/project/%s"
                                    % fx["A"]["project_id"])):
                    n += 1
                    key = "sec02f-%s-%s-%s" % (mode, role, scope)
                    r = tc.put(url, json={"modifiers": {"risk_pct": 5 + n}},
                               headers={"Authorization": "Bearer " + tokens[("A", role)],
                                        "Idempotency-Key": key})
                    events = tc.portal.call(lambda: op_db.audit_events.find(
                        {"idempotency_key": key}, {"_id": 0}).to_list(10))
                    pm_audit.append({
                        "mode": mode, "role": role, "scope": scope, "status": r.status_code,
                        "legacy_role": fx["A"]["users"][role]["role"],
                        "user_id": fx["A"]["users"][role]["id"],
                        # ST-01: the legacy org of tenant A IS its tenant id
                        "expected_tenant": fx["A"]["tenant_id"],
                        "project_id": fx["A"]["project_id"], "risk_pct": 5 + n,
                        "events": [{k: e.get(k) for k in (
                            "action", "result", "retention_class", "source_flow", "tenant_id",
                            "actor_id", "actor_type", "entity_type", "entity_id",
                            "scope_type", "scope_id", "structured_diff", "tool_or_endpoint",
                            "idempotency_key", "sequence", "integrity_hash")}
                            for e in events]})
        # SEC-02-G (Codex SEC71-02): the stored P1 pulse of 2026-11-03 — one worker paid
        # 160, one with no pay. The Technical Manager gets no day / SMR total; finance does.
        pulse_paid = []
        for mode in MODES:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            for role in ("requester", "accountant", "owner"):
                r = tc.get("/api/sites/%s/pulse" % fx["A"]["project_id"],
                           params={"date": "2026-11-03"},
                           headers={"Authorization": "Bearer " + tokens[("A", role)]})
                body = r.json() if r.status_code == 200 else {}
                pulse_paid.append({
                    "mode": mode, "role": role, "legacy_role": fx["A"]["users"][role]["role"],
                    "status": r.status_code, "date": body.get("date"),
                    "total_labor_cost": body.get("total_labor_cost"),
                    "smr_total_cost": [x.get("total_cost") for x in body.get("smr_summary") or []],
                    "has_workers": "workers" in body,
                    "budget_snapshot": body.get("budget_snapshot")})
        # SEC-02-G (Codex SEC71-03): the budget alert text — stored (>80 %, >100 %),
        # generated (>100 %) and generated on demand (>100 %) — one paid worker on P1.
        alert_rows = []
        p1 = fx["A"]["project_id"]
        for mode in MODES:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            for role in ("requester", "accountant"):
                hdr = {"Authorization": "Bearer " + tokens[("A", role)]}
                for case, method, path, date in (
                        ("stored_over_80", "GET", "/api/sites/%s/pulse", "2026-11-02"),
                        ("stored_over_100", "GET", "/api/sites/%s/pulse", "2026-11-03"),
                        ("generated_over_100", "POST", "/api/sites/%s/pulse/generate",
                         "2026-11-04"),
                        ("on_demand_over_100", "GET", "/api/sites/%s/pulse", "2026-11-05")):
                    r = tc.request(method, path % p1, params={"date": date}, headers=hdr)
                    body = r.json() if r.status_code == 200 else {}
                    alert_rows.append({
                        "mode": mode, "role": role, "case": case, "status": r.status_code,
                        "legacy_role": fx["A"]["users"][role]["role"],
                        "alerts": body.get("alerts"),
                        "budget_snapshot": body.get("budget_snapshot")})
        # SEC-02-G (FLOW Guard FG-111): /alarms readers — the stored "900.0%" alarm and a
        # freshly evaluated one (124 %), one paid worker on P1, visible budget.
        from app.permissions.finance_read import MONEY_TEXT, _TEXT_KEYS

        def alarm_events_in(v, out):
            if isinstance(v, dict):
                if "rule_id" in v and "triggered_at" in v:
                    out.append(v)
                for x in v.values():
                    alarm_events_in(x, out)
            elif isinstance(v, list):
                for x in v:
                    alarm_events_in(x, out)
            return out
        alarm_rows = []
        stored = sid("A", "alarm1")
        for mode in MODES:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            for role in ("requester", "technician", "viewer", "accountant"):
                hdr = {"Authorization": "Bearer " + tokens[("A", role)]}
                for case, method, path in (("list", "GET", "/api/alarms"),
                                           ("one", "GET", "/api/alarms/" + stored),
                                           ("dashboard", "GET", "/api/alarms/dashboard"),
                                           ("evaluate", "POST", "/api/alarms/evaluate")):
                    r = tc.request(method, path, headers=hdr)
                    if case == "evaluate":               # next caller evaluates afresh
                        tc.portal.call(lambda: op_db.alarm_events.delete_many(
                            {"org_id": fx["A"]["tenant_id"], "id": {"$ne": stored}}))
                    body = r.json() if r.status_code == 200 else None
                    evs = alarm_events_in(body, [])
                    alarm_rows.append({
                        "mode": mode, "role": role, "case": case, "status": r.status_code,
                        "legacy_role": fx["A"]["users"][role]["role"],
                        "events": [{"type": e.get("type"), "message": e.get("message"),
                                    "rule_name": e.get("rule_name"),
                                    "severity": e.get("severity"),
                                    "context_keys": sorted((e.get("context") or {}).keys())}
                                   for e in evs],
                        "money_text": sorted({x for e in evs for k in _TEXT_KEYS + ("rule_name",)
                                              for x in [e.get(k)] if isinstance(x, str)
                                              and MONEY_TEXT.search(x)}),
                        "leaks_900": "900" in r.text, "leaks_124": "124.0" in r.text})
        # SEC-02-G (audit SEC71-04; R31): the band — snapshot status, alarm severity, the
        # ?severity= filter, /alarms/count — with ONE paid worker on P1 and with TWO (a
        # second paid session added for the call and removed after).
        band_rows = []
        second = {"id": sid("A", "ws_band"), "org_id": fx["A"]["tenant_id"],
                  "worker_id": fx["A"]["users"]["driver"]["id"], "site_id": p1,
                  "smr_type_id": "Мазилка", "started_at": "2026-11-05T07:00:00",
                  "ended_at": "2026-11-05T15:00:00", "duration_hours": 8, "labor_cost": 500}
        for mode in MODES:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            for paid in (1, 2):
                if paid == 2:
                    tc.portal.call(lambda: op_db.work_sessions.insert_one(dict(second)))
                for role in ("requester", "technician", "viewer", "accountant"):
                    hdr = {"Authorization": "Bearer " + tokens[("A", role)]}
                    cnt = tc.get("/api/alarms/count", headers=hdr)
                    crit = tc.get("/api/alarms", params={"severity": "critical"}, headers=hdr)
                    dash = tc.get("/api/alarms/dashboard", headers=hdr)
                    gen = tc.post("/api/sites/%s/pulse/generate" % p1,
                                  params={"date": "2026-11-06"}, headers=hdr)
                    one = tc.get("/api/alarms/" + stored, headers=hdr)
                    mb = tc.get("/api/morning-briefing", headers=hdr)
                    mbc = tc.get("/api/morning-briefing/compact", headers=hdr)
                    items = (crit.json() or {}).get("items", []) if crit.status_code == 200 else []
                    band_rows.append({
                        "mode": mode, "paid_workers": paid, "role": role,
                        "legacy_role": fx["A"]["users"][role]["role"],
                        "count_status": cnt.status_code,
                        "count": cnt.json() if cnt.status_code == 200 else None,
                        "critical_list": [(i.get("type"), i.get("severity"), i.get("message"))
                                          for i in items],
                        "dashboard_by_severity": (dash.json() or {}).get("by_severity")
                        if dash.status_code == 200 else None,
                        "one_status": one.status_code,
                        # SEC-02-G (SEC71-05): the morning briefing burns the same band
                        "briefing_status": (mb.status_code, mbc.status_code),
                        "briefing_p1_reasons": [x for t in ((mb.json() or {}).get("top_risks")
                                                            or []) if t.get("project_id") == p1
                                                for x in t.get("reasons") or []]
                        if mb.status_code == 200 else None,
                        "briefing_critical": (((mb.json() or {}).get("summary") or {})
                                              .get("critical_alarms"),
                                              (mbc.json() or {}).get("critical_count"))
                        if mb.status_code == 200 and mbc.status_code == 200 else None,
                        "briefing_top_alarms": len((mb.json() or {}).get("top_alarms") or [])
                        if mb.status_code == 200 else None,
                        "generate_status": gen.status_code,
                        "snapshot": (gen.json() or {}).get("budget_snapshot")
                        if gen.status_code == 200 else None,
                        "generate_budget_alerts": [a.get("type") for a in
                                                   ((gen.json() or {}).get("alerts") or [])
                                                   if gen.status_code == 200 and "budget"
                                                   in str(a.get("type"))]})
                if paid == 2:
                    tc.portal.call(lambda: op_db.work_sessions.delete_one({"id": second["id"]}))
        os.environ["PERMISSION_SERVICE_MODE"] = "off"

    result = {
        "schema": "beg.sec-02-finance-read/v1",
        "fixture": "ST-01 synthetic tenants A and B + PM-01, C02 and SEC-02 existing records",
        "roles": {k: fx["A"]["users"][k]["role"] for k in ROLE_KEYS},
        "modes": list(MODES), "probes": [[p["key"], p["rule"], p["action"]] for p in plist],
        "mongo": "local replica set (oplog)", "outbound_http": "closed local port",
        "seconds": round(time.time() - started, 1), "rows": rows,
        "site_manager_mirrors": mirrors,
        "labor_replay": replay,
        "price_modifier_audit": pm_audit,
        "pulse_one_paid_worker": pulse_paid,
        "pulse_budget_alerts": alert_rows,
        "alarms": alarm_rows,
        "band_paid_workers": band_rows,
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    return result


def run_in_child(mongo_url: str, out_json: Path, timeout: int = 3600) -> None:
    pm = _pm01()
    suffix = uuid.uuid4().hex[:12]
    op_name, sys_name = DB_PREFIX_OP + suffix, DB_PREFIX_SYS + suffix
    env = pm.child_env(mongo_url, op_name, sys_name)
    env["JWT_SECRET"] = "sec02-local-" + uuid.uuid4().hex
    cmd = [sys.executable, str(Path(__file__).resolve()), "--child",
           "--mongo-url", mongo_url, "--out-json", str(out_json)]
    try:
        subprocess.run(cmd, cwd=str(BACKEND), timeout=timeout, check=True, env=env)
    finally:
        import pymongo
        c = pymongo.MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
        for name in (op_name, sys_name):
            assert name.startswith((DB_PREFIX_OP, DB_PREFIX_SYS))
            c.drop_database(name)
        c.close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="SEC-02 finance-read evidence")
    parser.add_argument("--harness", action="store_true")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--mongo-url", default=os.environ.get("W0_03_REAL_MONGO_URL", ""))
    parser.add_argument("--out-json", default=str(RESULTS_JSON))
    args = parser.parse_args(argv)
    if not args.mongo_url:
        print("no --mongo-url and no W0_03_REAL_MONGO_URL", file=sys.stderr)
        return 2
    _pm01()._check_local(args.mongo_url)
    if args.child:
        run_harness(args.mongo_url, Path(args.out_json))
        return 0
    if args.harness:
        run_in_child(args.mongo_url, Path(args.out_json))
        return 0
    parser.print_help()
    return 2


# ═══════════════════════════════════════════════════════════════════ rule assertions
def check_rows(rows: List[Dict[str, Any]]) -> None:
    assert rows
    plist = {p["key"]: p for p in probes()}
    by_cell: Dict[tuple, Dict[str, Dict[str, Any]]] = {}
    for r in rows:
        p = plist[r["probe"]]
        exp = expected(p, r["legacy_role"], r["target"])
        business = [ns for ns in r["written"] if ns.split(".", 1)[1] not in AUDIT]
        assert r["foreign_ids"] is False, r                       # never A's record to B
        if exp["reached"] is None:
            pass                                                  # the route's own rule
        elif exp["reached"]:
            assert r["status"] != 403, (exp, r)
        else:
            assert r["status"] == 403, (exp, r)
            assert business == [], r
            if r["mode"] == "enforce":
                assert set(r["written"]) <= {"op.audit_events"}, r
            else:
                assert r["written"] == [], r
        if r["status"] in (200, 201) and "actual_keys" in r \
                and r["legacy_role"] == "SiteManager" \
                and r["tenant"] in ("A", "B") and r["target"] in ("P1", None):
            # SEC-02-D (audit SEC02C-1; R31): P1 has ONE PAID worker in the seed (SEC-02-G:
            # plus one with no pay, in the sessions and in a stored pulse), so the
            # Technical Manager gets no spent / actual at all, and never worker detail.
            assert r["actual_keys"] == [] and r["worker_detail"] == [], r
        if r["status"] in (200, 201) and "forbidden_keys" in r \
                and r["legacy_role"] not in FINANCE:
            # SEC-02-G (Codex SEC71-01): no allowed budget view carries a client price,
            # sale, margin or profit — in every mode, for every R20-2B / R20-5B route
            assert r["forbidden_keys"] == [], r
        if r["probe"] == "POST /api/budget-freezes/{project_id}" and r["status"] == 201 \
                and r["legacy_role"] in FINANCE and r["target"] in ("P1", None):
            # finance roles keep the full view (the seed's package has sale 12345, margin 77)
            assert {"sale_total", "planned_margin", "total_sale"} <= set(r["forbidden_keys"]), r
        if r["status"] == 200 or r["status"] == 201:
            if r["rule"] == R20_5B and "money_keys" in r and not exp["money"]:
                assert r["hidden_budget_keys"] == [] and not r["leaks_7777"], r
                if "sites_with_money" in r:                       # SEC-02-C: own site only
                    assert set(r["sites_with_money"]) <= ({"P1"} if exp["budget_view"]
                                                           else set()), r
                # R31 (FLOW-037 §3.4): never a per-person rate or labor cost
                assert not {"hourly_rate", "labor_cost", "rate", "daily_rate"} & \
                    set(r["money_keys"]), r
                if not exp["budget_view"]:
                    assert r["money_keys"] == [], r              # FG-43: other members
            elif "money_keys" in r and (r["rule"] == R20_5M or "has_payroll" in r):
                if exp["money"] is False:                          # SEC-02-A: nothing leaks
                    assert r["money_keys"] == [] and not r["leaks_7777"], r
                    assert not r.get("has_payroll"), r
            elif "money_keys" in r:
                if exp["money"] is False:
                    assert r["money_keys"] == [], r               # R20-5: nothing leaks
                elif exp["money"] and r["probe"] in ("labor_list", "labor_create") \
                        and r["target"] != "P2":
                    assert "hourly_rate" in r["money_keys"], r    # finance still sees it
            if "group_price_keys" in r:
                assert (r["groups"] >= 1) == (r["target"] == "P1"), r   # seeded on P1 only
                if exp["money"] and r["target"] == "P1":
                    assert r["group_price_keys"], r
                else:
                    assert r["group_price_keys"] == [] and not r["leaks_7777"], r
            if r["probe"] == "labor_list" and not exp["money"]:
                allowed = {"P1"} if r["legacy_role"] in P1_MEMBERS else set()
                assert set(r.get("row_projects", [])) <= allowed, r
        by_cell.setdefault((r["tenant"], r["role"], r["probe"], r["target"]), {})[r["mode"]] = r
    for cell, modes in by_cell.items():                           # same answer in every mode
        assert set(modes) == set(MODES), cell
        assert len({m["status"] for m in modes.values()}) == 1, (cell, modes)
        assert len({tuple(m.get("money_keys", [])) for m in modes.values()}) == 1, (cell, modes)
    assert {c[2] for c in by_cell} == set(plist)


def check_replay(replay: List[Dict[str, Any]]) -> None:
    """SEC-02-B (FG-15): neither the first answer nor the Idempotency-Key replay gives a
    non-finance writer the rate or the cost; the finance role sees them in both."""
    assert len(replay) == 3 * len(MODES)
    for r in replay:
        assert r["first"] == 201 and r["replay"] in (200, 201) and r["same_id"], r
        if r["legacy_role"] in FINANCE:
            assert r["first_money"] == r["replay_money"] == ["hourly_rate", "labor_cost"], r
        else:
            assert r["first_money"] == r["replay_money"] == [], r


def check_price_modifier_audit(rows: List[Dict[str, Any]]) -> None:
    """SEC-02-F (FG-75; CLAUDE.md §14, FLOW-040): each successful PUT /price-modifiers
    writes exactly ONE canonical AuditEvent — R1, success, FLOW-023, the tenant of the
    write, the actor, the scope, before/after of the changed field, the endpoint and the
    request's Idempotency-Key, chained (sequence + integrity hash). A refused PUT writes
    no pricing event in any mode."""
    assert len(rows) == len(MODES) * 3 * 2
    for r in rows:
        allowed = (r["legacy_role"] in ("Owner", "Admin") if r["scope"] == "org"
                   else r["legacy_role"] in FINANCE)
        if not allowed:
            assert r["status"] == 403 and r["events"] == [], r
            continue
        assert r["status"] == 200 and len(r["events"]) == 1, r
        e = r["events"][0]
        org = r["scope"] == "org"
        assert e["action"] == ("pricing.org_modifier.updated" if org
                               else "pricing.project_modifier.updated"), e
        assert (e["result"], e["retention_class"], e["source_flow"], e["actor_type"]) == \
            ("success", "R1", "FLOW-023", "human"), e
        assert e["tenant_id"] == r["expected_tenant"] and e["actor_id"] == r["user_id"], e
        assert e["entity_type"] == "price_modifiers_config" and e["entity_id"], e
        assert e["scope_type"] == ("company" if org else "project"), e
        assert e["scope_id"] == (r["expected_tenant"] if org else r["project_id"]), e
        assert e["structured_diff"]["after"]["modifiers"]["risk_pct"] == r["risk_pct"], e
        before = e["structured_diff"]["before"]
        assert before is None or before["modifiers"].get("risk_pct") != r["risk_pct"], e
        assert e["tool_or_endpoint"].startswith("PUT /api/price-modifiers/"), e
        assert e["idempotency_key"] and isinstance(e["sequence"], int) and e["integrity_hash"], e


def check_pulse_one_paid_worker(rows: List[Dict[str, Any]]) -> None:
    """SEC-02-G (Codex SEC71-02): the stored pulse with ONE paid worker (160) and one with
    no pay — the Technical Manager (member of P1) gets the pulse without the day total,
    the SMR total, the worker list or the cumulative spent; finance roles get 160."""
    assert len(rows) == len(MODES) * 3
    for r in rows:
        assert r["status"] == 200 and r["date"] == "2026-11-03", r
        if r["legacy_role"] in FINANCE:
            assert r["total_labor_cost"] == 160.0 and r["smr_total_cost"] == [160.0], r
            assert r["has_workers"], r
        else:
            assert r["total_labor_cost"] is None and r["smr_total_cost"] == [None], r
            assert not r["has_workers"], r
            assert r["budget_snapshot"] == {"total_budget": 5000.0}, r   # SEC71-04: no status


def check_pulse_budget_alerts(rows: List[Dict[str, Any]]) -> None:
    """SEC-02-G (Codex SEC71-03; R31): with ONE paid worker and a visible budget, the
    budget alert text would give his pay ("900.0%" x budget). The Technical Manager gets
    one generic budget alert — no amount, no percent, the SAME for >80 % and >100 %, for a
    stored, a generated and an on-demand pulse; no text of any alert holds a number with
    a % or a currency. Finance roles keep the full text."""
    from app.permissions.finance_read import MONEY_TEXT, GENERIC_BUDGET_ALERT, _TEXT_KEYS
    assert len(rows) == len(MODES) * 2 * 4
    expect = {"stored_over_80": "85.0%", "stored_over_100": "900.0%",
              "generated_over_100": "124.0%", "on_demand_over_100": "124.0%"}
    seen = {}
    for r in rows:
        assert r["status"] == 200 and isinstance(r["alerts"], list), r
        budget = [a for a in r["alerts"] if a.get("type") in ("budget_warning",
                                                              "budget_attention")]
        if r["legacy_role"] in FINANCE:
            assert len(budget) == 1, r
            assert budget[0]["type"] == "budget_warning", r
            assert expect[r["case"]] in budget[0]["message"], r
            continue
        # SEC-02-G (SEC71-04): P1 has ONE paid worker — not even the generic alert or the
        # snapshot status (no band to bisect on); with 2+ paid see check_band_two_paid
        assert budget == [], r
        for a in r["alerts"]:
            for k in _TEXT_KEYS:
                assert not (isinstance(a.get(k), str) and MONEY_TEXT.search(a[k])), (r, a)
        assert r["budget_snapshot"] == {"total_budget": 5000.0}, r
        snap = {k: float(v) if isinstance(v, (int, float)) else v
                for k, v in (r["budget_snapshot"] or {}).items()}   # 5000 (generated) == 5000.0
        seen.setdefault(r["mode"], []).append(json.dumps([budget, snap], sort_keys=True))
    for mode, texts in seen.items():
        assert len(set(texts)) == 1 and len(texts) == 4, (mode, texts)   # no threshold told


def check_alarms(rows: List[Dict[str, Any]]) -> None:
    """SEC-02-G (FLOW Guard FG-111): /alarms, /alarms/{id}, /alarms/dashboard and
    POST /alarms/evaluate — a budget alarm with "бюджет 900.0% изхарчен" + metric_value
    (and a fresh 124 % one) on a one-paid-worker site. Technician, Viewer and SiteManager
    get the generic alarm: no amount / percent in any text or rule name, no metric_value /
    threshold / details, severity warning; finance roles get the full alarm."""
    from app.permissions.finance_read import GENERIC_BUDGET_ALERT, GENERIC_ALARM_RULE_NAME
    assert len(rows) == len(MODES) * 4 * 4
    for r in rows:
        # SEC-02-G (SEC71-04): a non-finance read of P1's money alarm by id is a 404
        fin = r["legacy_role"] in FINANCE
        expect = 200
        if not fin and r["case"] == "one":
            expect = 404              # SEC71-04: the hidden alarm does not exist for him
        if not fin and r["case"] == "evaluate":
            expect = 403              # SEC71-05: evaluating every rule is finance only
        assert r["status"] == expect, r
        budget = [e for e in r["events"] if e["type"] == "budget"]
        if r["legacy_role"] not in FINANCE:
            # SEC-02-G (SEC71-04): P1 has ONE paid worker — its money alarm is not shown
            # to a non-finance role at all (no band); see check_band_two_paid for 2+
            assert budget == [] and r["money_text"] == [], r
            assert not r["leaks_900"] and not r["leaks_124"], r
            continue
        assert budget, r
        if r["legacy_role"] in FINANCE:
            assert any(MONEY_TEXT_OK in e["message"] for e in budget
                       for MONEY_TEXT_OK in ("900.0%", "124.0%")), r
            assert all("metric_value" in e["context_keys"] for e in budget), r
            continue
        assert r["money_text"] == [] and not r["leaks_900"] and not r["leaks_124"], r
        for e in budget:
            assert e["message"] == GENERIC_BUDGET_ALERT["message"], r
            assert e["rule_name"] == GENERIC_ALARM_RULE_NAME and e["severity"] == "warning", r
            assert not {"metric_value", "threshold", "details"} & set(e["context_keys"]), r


def check_band_two_paid(rows: List[Dict[str, Any]]) -> None:
    """SEC-02-G (audit SEC71-04, addendum F; R31): with ONE paid worker on P1 a role
    without the finance right gets no band of P1's labor cost at all — no snapshot status,
    no budget alert, its money alarm is not in the list, the ?severity= filter, the counts,
    the dashboard, nor readable by id (404). With TWO paid workers the band is allowed:
    status, severity and counts are there (still without amount / percent / metric).
    Finance roles always get everything."""
    from app.permissions.finance_read import GENERIC_BUDGET_ALERT
    assert len(rows) == len(MODES) * 2 * 4
    for r in rows:
        assert r["count_status"] == 200, r
        # pulse/generate is R20-2B: finance roles and the Technical Manager (member) only
        tm_or_fin = r["legacy_role"] in FINANCE or r["legacy_role"] == "SiteManager"
        assert r["generate_status"] == (200 if tm_or_fin else 403), r
        if not tm_or_fin:
            r = {**r, "snapshot": None, "generate_budget_alerts": None}
        assert tuple(r["briefing_status"]) == (200, 200), r
        budget_reason = [x for x in r["briefing_p1_reasons"] if "Бюджет" in x or "аларм" in x]
        if r["legacy_role"] in FINANCE:
            assert r["count"]["critical"] >= 1 and r["critical_list"], r
            assert r["one_status"] == 200 and "status" in r["snapshot"], r
            assert r["generate_budget_alerts"], r
            assert "Бюджетът е надхвърлен" in r["briefing_p1_reasons"], r
            assert r["briefing_critical"][0] >= 1 and r["briefing_critical"][1] >= 1, r
            continue
        if r["paid_workers"] == 1:
            # SEC71-05: no budget burn reason, no alarm counts / top alarms for P1
            assert budget_reason == [] and tuple(r["briefing_critical"]) == (0, 0), r
            assert r["briefing_top_alarms"] == 0, r
        else:
            assert "Бюджетът е надхвърлен" in r["briefing_p1_reasons"], r
            assert r["briefing_critical"][0] >= 1, r
        if r["paid_workers"] == 1:
            assert r["count"]["critical"] == 0 and r["count"]["total"] == 0, r
            assert r["critical_list"] == [] and r["one_status"] == 404, r
            assert r["dashboard_by_severity"] == {"critical": 0, "warning": 0, "info": 0}, r
            if tm_or_fin:
                assert r["snapshot"] == {"total_budget": 5000}, r
                assert r["generate_budget_alerts"] == [], r
        else:
            assert r["count"]["critical"] >= 1 and r["one_status"] == 200, r
            assert r["critical_list"] and all(
                t == "budget" and sev == "critical" and m == GENERIC_BUDGET_ALERT["message"]
                for t, sev, m in r["critical_list"]), r
            assert r["dashboard_by_severity"]["critical"] >= 1, r
            if tm_or_fin:
                assert set(r["snapshot"]) == {"total_budget", "status"}, r
                assert r["generate_budget_alerts"] == ["budget_attention"], r


def check_mirrors(mirrors: List[Dict[str, Any]]) -> None:
    """FG-14 / FG-12 in enforce: the SiteManager's project mirrors carry the budget view
    and never a finance read."""
    assert len(mirrors) == 4
    for m in mirrors:
        assert m["budget_actions"] == sorted(PROJECT_BUDGET_READ_ACTIONS), m
        assert m["finance_actions"] == [], m


# ═════════════════════════════════════════════════════════════════════ DB-free tests
def _app():
    os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:1")
    os.environ.setdefault("DB_NAME", "sec02_static")
    import server
    return server.app


def _routes():
    from fastapi.routing import APIRoute
    out = {}
    for r in _app().routes:
        if isinstance(r, APIRoute):
            for m in r.methods:
                out[(m, r.path)] = r
    return out


def test_every_guarded_read_carries_its_action_first():
    routes = _routes()
    for e in FINANCE_READS:
        route = routes[(e.method, e.path)]                    # served today
        if e.rule in (R20_5M, R20_5B):
            assert getattr(route.endpoint, "sec02_strips_money", False), e
            assert getattr(route.endpoint, "sec02_budget_view", False) == (e.rule == R20_5B), e
            continue
        if e.rule == R20_5:
            src = Path(route.endpoint.__code__.co_filename).read_text(encoding="utf-8")
            assert "money_values_visible" in src, e
            continue
        first = route.dependant.dependencies[0].call
        assert getattr(first, "sec02_action", None) == e.action, e
        assert (getattr(first, "sec01_rule", None) == "R20-2B") == (
            e.rule == R20_2B and e.action != EMPLOYEE_FILE_ACTION), e


def test_no_other_route_carries_a_sec02_action():
    marked = {k for k, r in _routes().items()
              if any(hasattr(d.call, "sec02_action") for d in r.dependant.dependencies)}
    assert marked == {(e.method, e.path) for e in FINANCE_READS
                      if e.rule not in (R20_5, R20_5M, R20_5B)}
    stripped = {k for k, r in _routes().items() if getattr(r.endpoint, "sec02_strips_money", False)}
    # SEC-02-E: the pulse generator is guarded (R20-2B) AND answers with the pulse view;
    # SEC-02-G (SEC71-01): so does the budget freeze, with the R20 budget view.
    assert stripped == {(e.method, e.path) for e in FINANCE_READS if e.rule in (R20_5M, R20_5B)} \
        | {("POST", "/api/sites/{site_id}/pulse/generate"),
           ("POST", "/api/budget-freezes/{project_id}")}


def test_the_registry_has_one_action_per_endpoint_and_known_rules():
    keys = [(e.method, e.path) for e in FINANCE_READS]
    assert len(keys) == len(set(keys))
    acts = [e.action for e in FINANCE_READS if e.rule not in (R20_5, R20_5M, R20_5B)]
    assert len(acts) == len(set(acts))
    assert all(e.rule in (R20_1, R20_2, R20_2B, R20_5, R20_5M, R20_5B) and e.canon
               for e in FINANCE_READS)
    assert not set(NOT_MONEY) & set(keys)


def test_every_pm01_5_2_endpoint_is_ruled():
    """PM-01 §5.2 (Viewer reads finance): each listed GET is in the registry or recorded as
    carrying no money, with the reason."""
    text = PM01_REPORT.read_text(encoding="utf-8")
    section = text.split("### 5.2.", 1)[1].split("### 5.3.", 1)[0]
    listed = set()
    for line in section.splitlines():
        if line.startswith("| `") and "`/api/" in line:
            listed |= {("GET", p) for p in re.findall(r"`(/api/[^`]+)`", line)}
    assert len(listed) == 58, len(listed)
    ruled = {(e.method, e.path) for e in FINANCE_READS} | set(NOT_MONEY)
    assert listed <= ruled, sorted(listed - ruled)


def test_the_catalog_grants():
    from app.permissions.catalog import (
        ACTIONS, PERMISSION_MATRIX, project_membership_actions, CANONICAL_ROLES,
        LEGACY_ROLES, is_significant_action)
    reads = FINANCE_READ_ACTIONS | {MONEY_VALUES_READ}
    assert reads | PROJECT_BUDGET_READ_ACTIONS <= ACTIONS
    holders = {rid for rid, acts in PERMISSION_MATRIX.items() if acts & reads}
    assert holders == {"owner", "admin", "accountant"}
    budget = {rid for rid, acts in PERMISSION_MATRIX.items() if acts & PROJECT_BUDGET_READ_ACTIONS}
    assert budget == {"owner", "admin", "accountant"}         # company scope
    # FG-12/FG-14: a project mirror never carries a finance read; the budget view only
    # when the COMPANY role is site_manager — whatever the role in the project.
    for rid in list(CANONICAL_ROLES) + list(LEGACY_ROLES):
        for rip in ("SiteManager", "Technician", "Viewer", ""):
            acts = set(project_membership_actions(rid, rip))
            assert not acts & reads, (rid, rip)
            assert bool(acts & PROJECT_BUDGET_READ_ACTIONS) == (rid == "site_manager"), (rid, rip)
    # Only the export is audited on denial (a significant verb); plain reads are not.
    # A plain read is not audited on denial; an export / execute / update (SEC-02-A/E) is.
    for a in reads | PROJECT_BUDGET_READ_ACTIONS:
        assert is_significant_action(a) == (not a.endswith(".read")), a
    # SEC-02-A (D9): the employee file — finance roles and the Technical Manager only.
    assert {rid for rid, acts in PERMISSION_MATRIX.items() if EMPLOYEE_FILE_ACTION in acts} == \
        {"owner", "admin", "accountant", "site_manager"}


def _decide(assignments, action, scope_type, scope_id):
    import asyncio
    from app.permissions import service

    class Ctx:
        user_id, tenant_id = "u", "T"

    async def load(_u, _t):
        return assignments
    orig = service._load_assignments
    service._load_assignments = load
    try:
        return asyncio.run(service.evaluate_permission(
            Ctx(), action, module=None, scope_type=scope_type, scope_id=scope_id)).allowed
    finally:
        service._load_assignments = orig


def test_the_enforce_decisions_and_fg12_combinations():
    from app.permissions.catalog import project_membership_actions

    def company(rid):
        return {"id": "c-" + rid, "status": "active", "role_id": rid, "scope_type": "company",
                "scope_id": None, "permissions": []}

    def mirror(rid, pid, rip):
        return {"id": "p-%s-%s" % (rid, pid), "status": "active", "role_id": rid,
                "scope_type": "project", "scope_id": pid,
                "permissions": project_membership_actions(rid, rip)}

    budget = sorted(PROJECT_BUDGET_READ_ACTIONS)[0]
    profit = "finance.project_profit.read"
    sm = [company("site_manager"), mirror("site_manager", "P1", "SiteManager")]
    assert _decide(sm, budget, "project", "P1")
    assert not _decide(sm, budget, "project", "P2")
    assert not _decide(sm, profit, "company", None)
    assert not _decide(sm, MONEY_VALUES_READ, "company", None)
    viewer = [company("LEGACY_VIEWER"), mirror("LEGACY_VIEWER", "P1", "SiteManager")]
    assert not _decide(viewer, budget, "project", "P1")       # role in project is not enough
    tech = [company("LEGACY_TECHNICIAN"), mirror("LEGACY_TECHNICIAN", "P1", "Technician")]
    assert not _decide(tech, budget, "project", "P1")
    assert not _decide(tech, MONEY_VALUES_READ, "company", None)
    acc = [company("accountant")]
    assert _decide(acc, profit, "company", None) and _decide(acc, budget, "project", "P9")
    assert _decide(acc, MONEY_VALUES_READ, "company", None)
    # FG-12, documented limit: a narrower project assignment does not take money away
    # from a company Accountant (no deny-overrides in the service).
    assert _decide(acc + [mirror("LEGACY_VIEWER", "P1", "Viewer")], profit, "company", None)


def test_without_keys_and_the_budget_view(monkeypatch):
    import asyncio
    from app.permissions import money_write
    from app.routes import expected_actual
    assert money_write.without_keys({"a": 1, "hourly_rate": 2, "x": [{"labor_cost": 3, "h": 4}]},
                                    LABOR_MONEY_FIELDS) == {"a": 1, "x": [{"h": 4}]}
    full = {"summary": {"total_planned_cost": 5000, "biggest_overrun_group": "G"},
            "activities": [{"name": "Мазилка", "planned_cost": 5000, "actual_cost": 3200,
                            "variance_cost": -1800}],
            "groups": [{"name": "G", "planned_hours": 1, "planned_cost": 7777,
                        "actual_cost": 1, "variance_cost": 1, "status": "over"}],
            "locations": [{"name": "L", "planned_cost": 7777, "missing_smr_count": 0}]}

    async def no(_r, _u):
        return False

    async def yes(_r, _u):
        return True
    monkeypatch.setattr(expected_actual, "money_values_visible", no)

    async def r31_as_is(_u, _p, body, **_k):  # the R31 step is tested on its own below
        return body
    monkeypatch.setattr(money_write, "r31_budget_view", r31_as_is)
    v = asyncio.run(expected_actual._budget_view(None, {}, full, "P1"))
    assert v["activities"] == full["activities"]               # budget, spent, remainder
    assert v["groups"] == [{"name": "G", "planned_hours": 1}]
    assert v["locations"] == [{"name": "L", "missing_smr_count": 0}]
    assert v["summary"]["biggest_overrun_group"] is None and "7777" not in json.dumps(v)
    monkeypatch.setattr(expected_actual, "money_values_visible", yes)
    assert asyncio.run(expected_actual._budget_view(None, {}, full, "P1")) is full


def test_r31_no_per_worker_pay_by_derivation():
    """SEC-02-D (audit SEC02C-1; R31, FLOW-037 §3.4)."""
    from app.permissions.finance_read import r31_view
    body = {"summary": {"total_planned_cost": 5000, "total_actual_cost": 410},
            "activities": [{"name": "Мазилка", "planned_cost": 300, "actual_cost": 200,
                            "actual_hours": 8, "variance_cost": -100},
                           {"name": "Шпакловка", "planned_cost": 300, "actual_cost": 210,
                            "actual_hours": 6}],
            "workers": [{"worker_id": "w1", "hours": 8, "smr_types": ["Мазилка"]}],
            "smr_summary": [{"smr_type": "Мазилка", "total_cost": 200, "workers_count": 1}]}
    # one SMR with ONE worker -> no row keeps its spent; worker detail always goes
    v = r31_view(body, {"мазилка": {"w1"}, "шпакловка": {"w2", "w3"}}, 3)
    assert "workers" not in v and "workers_count" not in v["smr_summary"][0]
    assert all("actual_cost" not in a and "variance_cost" not in a for a in v["activities"])
    assert "total_cost" not in v["smr_summary"][0]
    assert v["activities"][0]["planned_cost"] == 300           # the budget stays
    assert v["summary"]["total_actual_cost"] == 410            # project total, 3 workers
    # every SMR with 2+ workers -> the per-SMR spent stays
    v2 = r31_view(body, {"мазилка": {"w1", "w4"}, "шпакловка": {"w2", "w3"}}, 4)
    assert [a["actual_cost"] for a in v2["activities"]] == [200, 210]
    # no worker map, but the row itself says one worker -> hidden as well
    v4 = r31_view(body, {}, 3)
    assert "total_cost" not in v4["smr_summary"][0]
    # the whole project has ONE worker -> no project-level spent either
    v3 = r31_view(body, {"мазилка": {"w1"}}, 1)
    assert "total_actual_cost" not in v3["summary"] and v3["summary"]["total_planned_cost"] == 5000


def test_the_money_key_rule():
    """SEC-02-A (R20-5M): what a mixed response keeps and loses for a non-finance caller."""
    money = ["unit_price", "line_total", "subtotal", "vat_amount", "total_cost", "labor_cost",
             "hourly_rate", "rates", "markup_pct", "risk_pct", "margin_percent", "net_pay",
             "payments", "advances", "material_budget", "labor_variance_value", "final_total",
             "paid_amount", "unpaid", "overhead", "balance", "income", "certified_total",
             "pay_type", "earned_amount", "monthly_salary", "price", "amount", "value"]
    keep = ["qty", "unit", "name", "status", "date", "project_id", "total_hours", "total_qty",
            "certified_qty", "progress_percent", "hours", "normal", "overtime", "currency",
            "migrated_from", "generated_at", "payroll_status", "attendance_rate", "waste_pct",
            "count", "days_total", "vat_number", "display_name", "activity_name"]
    assert [k for k in money if not is_money_key(k)] == []
    assert [k for k in keep if is_money_key(k)] == []
    assert is_money_key("total") and not is_money_key("total", ["items", "total", "page"])
    body = {"items": [{"name": "A", "qty": 2, "unit_price": 3, "lines": [{"line_total": 6,
            "unit": "m2"}]}], "total": 1, "page": 1}
    assert strip_money(body) == {"items": [{"name": "A", "qty": 2, "lines": [{"unit": "m2"}]}],
                                 "total": 1, "page": 1}


def _fake_tenant(collections):
    """A minimal async TenantData stand-in: find(query) with equality, $ne, $in, $gte, $lte."""
    def match(doc, q):
        for k, cond in q.items():
            v = doc.get(k)
            if isinstance(cond, dict):
                if "$ne" in cond and v == cond["$ne"]:
                    return False
                if "$in" in cond and v not in cond["$in"]:
                    return False
                if "$gte" in cond and (v is None or v < cond["$gte"]):
                    return False
                if "$lte" in cond and (v is None or v > cond["$lte"]):
                    return False
            elif v != cond:
                return False
        return True

    class Coll:
        def __init__(self, docs):
            self.docs = docs

        def find(self, q, _p=None):
            docs = [d for d in self.docs if match(d, q)]

            async def gen():
                for d in docs:
                    yield d
            return gen()

    class T:
        pass
    t = T()
    for name in ("work_sessions", "employee_daily_reports", "daily_work_logs", "work_types"):
        setattr(t, name, Coll(collections.get(name, [])))
    return t


def test_fg63_workers_are_counted_from_the_money_source_and_window(monkeypatch):
    """SEC-02-E (FLOW Guard FG-63; R31): the 2+ rule uses the workers of the SAME source,
    filter and window as the "spent" figure."""
    import asyncio
    from app.permissions import money_write
    from app.tenancy import data_access
    org, p = "T", "P1"
    sess = lambda w, day, smr="Мазилка", ended=True, cost=800: {
        "org_id": org, "site_id": p, "worker_id": w, "smr_type_id": smr, "labor_cost": cost,
        "started_at": day + "T07:00:00", "ended_at": day + "T15:00:00" if ended else None}
    data = {"work_sessions": [sess("w1", "2026-11-02"), sess("w2", "2026-11-03"),
                              sess("w3", "2026-11-02", ended=False)]}
    monkeypatch.setattr(data_access.TenantData, "for_user",
                        staticmethod(lambda _db, _u: _fake_tenant(data)))
    user = {"org_id": org, "id": "sm"}
    run = lambda *a, **k: asyncio.run(money_write.project_labor_workers(user, p, *a, **k))
    # whole history, ended sessions only: w1 + w2 (w3 not ended, w4 is a draft report)
    assert run("sessions") == ({"мазилка": {"w1", "w2"}}, 2)
    # a one-day window: ONE worker -> the 2+ rule must hide that day's spent
    assert run("sessions", "2026-11-03", "2026-11-03") == ({"мазилка": {"w2"}}, 1)
    # the centralized screen also sums draft reports -> w4 counts there, and only there
    # (SEC-02-F: from the handler's own entries, the same pay as its "spent")
    ent = lambda w, pay: {"worker_id": w, "smr_type": "Мазилка", "amount_clean_labor": pay}
    assert run("centralized", entries=[ent("w1", 800), ent("w2", 800), ent("w4", 400)])[1] == 3
    body = {"activities": [{"name": "Мазилка", "planned_cost": 100, "actual_cost": 60}],
            "summary": {"total_actual_cost": 60}}
    v = asyncio.run(money_write.r31_budget_view(user, p, body, source="sessions",
                                                date_from="2026-11-03", date_to="2026-11-03"))
    assert "actual_cost" not in v["activities"][0] and "total_actual_cost" not in v["summary"]


def test_fg74_only_workers_with_pay_in_the_window_count(monkeypatch):
    """SEC-02-F (FLOW Guard FG-74; R31): a worker with zero cost adds nothing to "spent",
    so he must not lift one paid worker over the 2+ rule — in every source."""
    import asyncio
    from app.permissions import money_write
    from app.tenancy import data_access
    org, p = "T", "P1"
    sess = lambda w, cost, smr="Мазилка": {
        "org_id": org, "site_id": p, "worker_id": w, "smr_type_id": smr, "labor_cost": cost,
        "started_at": "2026-11-02T07:00:00", "ended_at": "2026-11-02T15:00:00"}
    data = {
        # w1 is paid, w2 has no rate (labor_cost 0), w3 nets out to 0 (+100 / -100)
        "work_sessions": [sess("w1", 800), sess("w2", 0), sess("w3", 100), sess("w3", -100),
                          sess("w5", 300, smr="Шпакловка"), sess("w6", 0, smr="Шпакловка")],
        "work_types": [{"id": "wt-paid", "org_id": org, "activity_type": "Мазилка",
                        "default_hourly_rate": 50},
                       {"id": "wt-free", "org_id": org, "activity_type": "Мазилка",
                        "default_hourly_rate": 0}],
        "daily_work_logs": [
            {"org_id": org, "site_id": p, "work_type_id": "wt-paid",
             "entries": [{"user_id": "u1", "hours": 8}, {"user_id": "u2", "hours": 0}]},
            {"org_id": org, "site_id": p, "work_type_id": "wt-free",
             "entries": [{"user_id": "u3", "hours": 8}]}]}
    monkeypatch.setattr(data_access.TenantData, "for_user",
                        staticmethod(lambda _db, _u: _fake_tenant(data)))
    user = {"org_id": org, "id": "sm"}
    run = lambda *a, **k: asyncio.run(money_write.project_labor_workers(user, p, *a, **k))
    # sessions: only w1 (Мазилка) and w5 (Шпакловка) are paid
    assert run("sessions") == ({"мазилка": {"w1"}, "шпакловка": {"w5"}}, 2)
    # daily logs: u2 has 0 hours, u3 a zero rate -> only u1
    assert run("daily_logs") == ({"мазилка": {"u1"}}, 1)
    # centralized: the handler's entries; a zero-pay entry does not count
    ent = lambda w, pay: {"worker_id": w, "smr_type": "Мазилка", "amount_clean_labor": pay}
    assert run("centralized", entries=[ent("w1", 800), ent("w2", 0)]) == ({"мазилка": {"w1"}}, 1)
    # the view: Мазилка has ONE paid worker -> no row keeps "spent"; the two paid workers
    # of the project keep the project total
    body = {"activities": [{"name": "Мазилка", "planned_cost": 900, "actual_cost": 800},
                           {"name": "Шпакловка", "planned_cost": 400, "actual_cost": 300}],
            "summary": {"total_actual_cost": 1100}}
    v = asyncio.run(money_write.r31_budget_view(user, p, body, source="sessions"))
    assert all("actual_cost" not in a for a in v["activities"]), v
    assert v["summary"]["total_actual_cost"] == 1100
    # before FG-74 u2 (0 hours) and u3 (rate 0) made Мазилка a "3 workers" row, 800 visible
    v = asyncio.run(money_write.r31_budget_view(
        user, p, {"activities": [{"name": "Мазилка", "actual_cost": 800}]},
        source="daily_logs"))
    assert "actual_cost" not in v["activities"][0], v


def test_sec71_01_the_budget_freeze_answer_is_the_budget_view(monkeypatch):
    """SEC-02-G (Codex SEC71-01; R20-5B): POST /budget-freezes answers a Technical Manager
    with budgets only — no client price (sale), margin, profit — while finance roles keep
    the full answer. The projection is a key pattern, not only a list of names."""
    import asyncio
    from app.permissions import money_write
    from app.routes import budget_progress
    endpoint = budget_progress.create_budget_freeze
    assert getattr(endpoint, "sec02_budget_view", False), "not decorated"
    freeze = {"packages": [{"activity_name": "Мазилка", "sale_total": 12345.0,
                            "labor_budget_total": 500.0, "budget_total": 600.0,
                            "planned_margin": 77.0, "client_unit_price": 9.0}],
              "totals": {"labor_budget": 500.0, "total_budget": 600.0, "total_sale": 12345.0,
                         "expected_profit": 5.0, "markup_pct": 3.0}}

    @money_write.strip_for_budget_view
    async def handler(project_id: str, user: dict = None):
        return freeze

    async def r31_as_is(_u, _p, body, **_k):
        return body
    monkeypatch.setattr(money_write, "r31_budget_view", r31_as_is)

    def visible(fin, tm):
        async def mv(*_a, **_k):
            return fin

        async def bv(*_a, **_k):
            return tm
        monkeypatch.setattr(money_write, "money_values_visible", mv)
        monkeypatch.setattr(money_write, "budget_view_visible", bv)
    visible(False, True)
    v = asyncio.run(handler(project_id="P1", user={"id": "sm"}, _sec02_request=None))
    assert forbidden_budget_view_keys(v) == [] and "12345" not in json.dumps(v), v
    assert v["packages"][0]["labor_budget_total"] == 500.0 and v["totals"]["total_budget"] == 600.0
    visible(True, True)
    assert asyncio.run(handler(project_id="P1", user={"id": "acc"}, _sec02_request=None)) is freeze


def test_sec71_02_pulse_counts_only_paid_workers(monkeypatch):
    """SEC-02-G (Codex SEC71-02; FG-74 on the pulse path): one paid worker (160) and one
    with no pay — the Technical Manager gets neither the day total nor the SMR total. A
    worker with several SMRs that day cannot be attributed and counts for none of them."""
    import asyncio
    from app.permissions import money_write

    def pulse(workers, smr):
        return {"site_id": "P1", "workers": workers,
                "smr_summary": [{"smr_type": k, "total_hours": 8, "total_cost": c,
                                 "workers_count": n} for k, c, n in smr],
                "total_labor_cost": sum(w["labor_cost"] for w in workers),
                "budget_snapshot": {"total_budget": 5000.0, "total_spent": 160.0,
                                    "status": "ok"}}
    w = lambda i, cost, *smr: {"worker_id": i, "labor_cost": cost, "smr_types": list(smr)}

    @money_write.strip_pulse_for_non_finance
    async def handler(site_id: str, user: dict = None):
        return current

    async def no(*_a, **_k):
        return False

    async def yes(*_a, **_k):
        return True
    async def two_paid(_u, _sites):           # SEC71-04 is tested on its own below
        return set()
    monkeypatch.setattr(money_write, "single_paid_sites", two_paid)
    monkeypatch.setattr(money_write, "money_values_visible", no)
    monkeypatch.setattr(money_write, "budget_view_visible", yes)
    run = lambda: asyncio.run(handler(site_id="P1", user={"id": "sm"}, _sec02_request=None))

    # Codex: 160 + 0 -> one paid worker -> no day total, no SMR total
    current = pulse([w("t", 160.0, "Мазилка"), w("d", 0, "Мазилка")], [("Мазилка", 160.0, 2)])
    assert money_write.pulse_paid_workers(current) == ({"мазилка": {"t"}}, 1)
    v = run()
    assert "total_labor_cost" not in v and "total_cost" not in v["smr_summary"][0], v
    assert "workers" not in v and "workers_count" not in v["smr_summary"][0], v
    assert v["budget_snapshot"] == {"total_budget": 5000.0, "status": "ok"}
    # two paid workers on one SMR -> both totals stay
    current = pulse([w("t", 160.0, "Мазилка"), w("d", 200.0, "Мазилка")],
                    [("Мазилка", 360.0, 2)])
    v = run()
    assert v["total_labor_cost"] == 360.0 and v["smr_summary"][0]["total_cost"] == 360.0
    # y is paid but on two SMRs: Шпакловка has x only -> no SMR keeps its total; the day
    # has 2 paid workers -> the day total stays
    current = pulse([w("x", 100.0, "Шпакловка"), w("y", 300.0, "Мазилка", "Шпакловка")],
                    [("Мазилка", 250.0, 1), ("Шпакловка", 150.0, 2)])
    assert money_write.pulse_paid_workers(current) == (
        {"мазилка": set(), "шпакловка": {"x"}}, 2)
    v = run()
    assert all("total_cost" not in r for r in v["smr_summary"]) and v["total_labor_cost"] == 400.0


def test_sec71_03_budget_alert_text_gives_no_amount(monkeypatch):
    """SEC-02-G (Codex SEC71-03 [P1]; R31): "Надхвърлен бюджет! (900.0%)" next to a visible
    budget of 10 gives 90 = one worker's pay. Without the finance right every money
    alert becomes ONE generic budget alert (same for >80 % and >100 %), and any other
    text with an amount / percent is replaced — in the pulse view (Technical Manager and
    other roles), in strip_money (labor / material / progress warnings, pulse summary)
    and in the budget view. Finance roles keep the full text."""
    import asyncio
    from app.permissions import money_write
    from app.permissions.finance_read import (strip_money, without_budget_view_forbidden,
                                              MONEY_TEXT, GENERIC_BUDGET_ALERT, _TEXT_KEYS)

    def texts(v):
        out = []
        if isinstance(v, dict):
            out += [x for k, x in v.items() if k in _TEXT_KEYS and isinstance(x, str)]
            for x in v.values():
                out += texts(x)
        elif isinstance(v, list):
            for x in v:
                out += texts(x)
        return out
    over_100 = {"type": "budget_warning", "message": "Надхвърлен бюджет! (900.0%)",
                "severity": "critical"}
    over_80 = {"type": "budget_warning", "message": "Бюджетът е 85.0% изхарчен",
               "severity": "warning"}
    keep = [{"type": "overtime", "message": "Извънреден труд: 2ч", "severity": "info"},
            {"type": "no_report", "message": "Липсва дневен отчет", "severity": "info"}]

    def pulse(alert):
        return {"site_id": "P1", "date": "2026-11-03", "alerts": [alert] + keep,
                "workers": [{"worker_id": "t", "labor_cost": 90.0, "smr_types": ["Мазилка"]}],
                "smr_summary": [{"smr_type": "Мазилка", "total_hours": 8, "total_cost": 90.0,
                                 "workers_count": 1}],
                "total_labor_cost": 90.0,
                "budget_snapshot": {"total_budget": 10.0, "total_spent": 90.0,
                                    "remaining": -80.0, "burn_pct": 900.0,
                                    "status": "over_budget"}}

    @money_write.strip_pulse_for_non_finance
    async def handler(site_id: str, user: dict = None):
        return current

    def visible(fin, tm):
        async def mv(*_a, **_k):
            return fin

        async def bv(*_a, **_k):
            return tm
        monkeypatch.setattr(money_write, "money_values_visible", mv)
        monkeypatch.setattr(money_write, "budget_view_visible", bv)
    async def two_paid(_u, _sites):           # SEC71-04 is tested on its own below
        return set()
    monkeypatch.setattr(money_write, "single_paid_sites", two_paid)
    run = lambda: asyncio.run(handler(site_id="P1", user={"id": "u"}, _sec02_request=None))
    for tm in (True, False):                       # Technical Manager / any other role
        visible(False, tm)
        answers = []
        for alert in (over_80, over_100):
            current = pulse(alert)
            v = run()
            assert v["alerts"] == [GENERIC_BUDGET_ALERT] + keep, v
            assert not any(MONEY_TEXT.search(x) for x in texts(v)), v
            assert "900" not in json.dumps(v, ensure_ascii=False) and \
                "90.0" not in json.dumps(v, ensure_ascii=False), v
            answers.append(v["alerts"])
        assert answers[0] == answers[1]            # the threshold is not told either
    visible(True, False)
    current = pulse(over_100)
    assert run() is current                        # finance: the full text
    # the other money texts, through strip_money / the budget view
    warnings = {"warnings": [
        {"type": "over_labor_budget", "package_id": "p", "activity": "Мазилка",
         "message": "Мазилка: 90 EUR / 10 EUR budget (80 EUR over)"},
        {"type": "over_material_budget", "message": "Мазилка: 12 EUR / 10 EUR бюджет (+2 EUR)"},
        {"type": "missing_material_budget", "message": "Мазилка: разход 12 EUR без бюджет"},
        {"type": "labor_ahead_of_progress", "message": "Мазилка: труд 90.0% vs прогрес 10%"},
        {"type": "progress_lag", "message": "Мазилка: прогрес 10% но разход 90.0% от бюджет"},
        {"type": "budget_overrun", "message": "Бюджетът за труд е надхвърлен: 900.0%"},
        {"type": "client_receivable", "amount": 5.0, "message": "Вземания: 5.0 EUR"},
        {"type": "unknown_new_alert", "message": "нещо 90 лв"},
        {"type": "unmapped_time_entries", "message": "3 от 10 записа за труд нямат връзка"}]}
    for f in (strip_money, without_budget_view_forbidden):
        v = f(warnings)
        assert not any(MONEY_TEXT.search(x) for x in texts(v)), (f, v)
        assert [a["type"] for a in v["warnings"]][:7] == ["budget_attention"] * 7, v
        assert v["warnings"][8]["message"] == "3 от 10 записа за труд нямат връзка"
        assert "amount" not in v["warnings"][6]


def test_fg111_alarms_give_no_amount_metric_or_threshold():
    """SEC-02-G (FLOW Guard FG-111): every /alarms reader strips money for a caller
    without the finance right (R20-5M, registered); an alarm event loses metric_value /
    threshold / details, and a money alarm gets the generic text and rule name — the same
    for an 80 % and a 100 % rule, stored or just evaluated."""
    from app.routes import alarms
    from app.permissions.finance_read import (strip_money, by_route, R20_5M, MONEY_TEXT,
                                              GENERIC_BUDGET_ALERT, GENERIC_ALARM_RULE_NAME)
    readers = {("GET", "/api/alarms"): alarms.list_alarms,
               ("GET", "/api/alarms/dashboard"): alarms.alarm_dashboard,
               ("GET", "/api/alarms/{event_id}"): alarms.get_alarm,
               ("PUT", "/api/alarms/{event_id}/acknowledge"): alarms.acknowledge_alarm,
               ("PUT", "/api/alarms/{event_id}/resolve"): alarms.resolve_alarm}
    reg = by_route()
    for key, fn in readers.items():
        assert reg[key].rule == R20_5M and getattr(fn, "sec02_strips_money", False), key
    # SEC-02-G (SEC71-05): evaluate is finance only (R20-1, a guarded execute action)
    from app.permissions.finance_read import R20_1
    assert reg[("POST", "/api/alarms/evaluate")].rule == R20_1
    assert reg[("POST", "/api/alarms/evaluate")].action == "finance.alarm_evaluation.execute"

    def ev(name, sev, pct, threshold):
        return {"id": "e", "rule_id": "r", "rule_name": name, "severity": sev,
                "type": "budget", "site_id": "P1", "site_name": "P1",
                "triggered_at": "2026-11-03T08:00:00", "status": "active",
                "message": "P1: бюджет %s%% изхарчен" % pct,
                "context": {"metric_value": pct, "threshold": threshold, "entity_id": "P1",
                            "entity_type": "project", "details": {"spent": 90}}}
    a = strip_money({"items": [ev("Бюджет над 80%", "warning", 85.0, 80)], "total": 1,
                     "page": 1, "page_size": 50})
    b = strip_money({"items": [ev("Бюджет над 100%", "critical", 900.0, 100)], "total": 1,
                     "page": 1, "page_size": 50})
    # no amount; the band (severity) is the rule's — shown only with 2+ paid workers on
    # the site, else the alarm is left out (SEC71-04, test_sec71_04_* below)
    sev = lambda x: {**x, "items": [{k: v for k, v in i.items() if k != "severity"}
                                    for i in x["items"]]}
    assert sev(a) == sev(b), (a, b)
    assert (a["items"][0]["severity"], b["items"][0]["severity"]) == ("warning", "critical")
    e = a["items"][0]
    assert e["message"] == GENERIC_BUDGET_ALERT["message"]
    assert e["rule_name"] == GENERIC_ALARM_RULE_NAME
    assert e["context"] == {"entity_id": "P1", "entity_type": "project"}
    assert a["total"] == 1 and e["id"] == "e" and e["status"] == "active"
    # a non-money alarm keeps its text (hours), not its metric / threshold
    ot = strip_money({"rule_id": "r2", "triggered_at": "t", "type": "overtime",
                      "message": "Иван: 12.5ч извънреден труд/седмица", "severity": "info",
                      "context": {"metric_value": 12.5, "threshold": 10, "entity_id": "w"}})
    assert ot["message"].startswith("Иван: 12.5ч") and ot["context"] == {"entity_id": "w"}
    # evaluate answer and dashboard: the events inside are projected too
    evald = strip_money({"new_events": 1, "resolved_events": 0,
                         "events": [ev("x", "critical", 124.0, 80)]})
    assert not MONEY_TEXT.search(evald["events"][0]["message"]) and \
        "124" not in json.dumps(evald, ensure_ascii=False)


def test_sec71_04_no_band_with_fewer_than_two_paid_workers(monkeypatch):
    """SEC-02-G (audit SEC71-04 BLOCKING, addendum F; R31): the band of a hidden "spent"
    (status on_track / warning / over_budget, green / yellow / red, the over / warning
    counts, the biggest overrun) is bisectable by moving the budget, so it goes with the
    spent. On the pulse: a site whose cumulative labor cost has fewer than 2 paid workers
    gives a non-finance role no snapshot status and no budget alert — the same answer on
    track and over budget; with 2+ paid workers the band stays."""
    import asyncio
    from app.permissions import money_write
    from app.permissions.finance_read import r31_view

    def pulse(status, alert_type):
        return {"site_id": "P1", "date": "2026-11-06",
                "alerts": [{"type": alert_type, "message": "Бюджетът е 85.0% изхарчен",
                            "severity": "warning"},
                           {"type": "no_report", "message": "Липсва дневен отчет",
                            "severity": "info"}] if alert_type else
                          [{"type": "no_report", "message": "Липсва дневен отчет",
                            "severity": "info"}],
                "workers": [{"worker_id": "t", "labor_cost": 90.0, "smr_types": ["Мазилка"]}],
                "total_labor_cost": 90.0,
                "budget_snapshot": {"total_budget": 10.0, "total_spent": 6200.0,
                                    "burn_pct": 62000.0, "status": status}}

    @money_write.strip_pulse_for_non_finance
    async def handler(site_id: str, user: dict = None):
        return current

    def setup(fin, tm, single):
        async def mv(*_a, **_k):
            return fin

        async def bv(*_a, **_k):
            return tm

        async def sp(_u, sites):
            return {x for x in sites if x in single}
        monkeypatch.setattr(money_write, "money_values_visible", mv)
        monkeypatch.setattr(money_write, "budget_view_visible", bv)
        monkeypatch.setattr(money_write, "single_paid_sites", sp)
    run = lambda: asyncio.run(handler(site_id="P1", user={"id": "u"}, _sec02_request=None))
    for tm in (True, False):
        setup(False, tm, {"P1"})
        answers = []
        for status, alert in (("on_track", None), ("warning", "budget_warning"),
                              ("over_budget", "budget_warning")):
            current = pulse(status, alert)
            v = run()
            assert "status" not in (v.get("budget_snapshot") or {}), v
            assert [a["type"] for a in v["alerts"]] == ["no_report"], v
            answers.append(json.dumps(v, sort_keys=True, ensure_ascii=False))
        assert len(set(answers)) == 1                     # nothing to bisect on
    setup(False, True, set())                             # 2+ paid workers: band allowed
    current = pulse("over_budget", "budget_warning")
    v = run()
    assert v["budget_snapshot"] == {"total_budget": 10.0, "status": "over_budget"}
    assert [a["type"] for a in v["alerts"]] == ["budget_attention", "no_report"]
    setup(True, False, {"P1"})
    assert run() is current                               # finance: everything
    # the budget screens: the band of a hidden spent goes with it (R31 rows / summary)
    body = {"summary": {"total_planned_cost": 100, "total_actual_cost": 90,
                        "overall_status": "over", "warning_count": 0, "over_count": 1,
                        "biggest_overrun_activity": "Мазилка", "total_planned_hours": 8},
            "activities": [{"name": "Мазилка", "planned_cost": 100, "actual_cost": 90,
                            "status": "over", "planned_hours": 8}]}
    one = r31_view(body, {"мазилка": {"t"}}, 1)
    assert one["summary"] == {"total_planned_cost": 100, "total_planned_hours": 8}, one
    assert one["activities"] == [{"name": "Мазилка", "planned_cost": 100, "planned_hours": 8}]
    two = r31_view(body, {"мазилка": {"t", "u"}}, 2)
    assert two["summary"]["overall_status"] == "over" and two["activities"][0]["status"] == "over"


def test_fg133_alarm_rules_give_only_known_condition_keys(monkeypatch):
    """SEC-02-G (FLOW Guard FG-133, addendum G): GET /alarm-rules — the only rule route
    open to every role — gives a caller without the finance right only metric / operator /
    threshold (%, hours, days) / secondary_* of a rule's free-form condition; any other key
    (e.g. a future EUR amount) is dropped. Finance roles get the stored condition."""
    import asyncio
    from app.routes import alarms
    rule = {"id": "r", "org_id": "T", "name": "Бюджет над 80%", "type": "budget",
            "severity": "critical", "is_active": True,
            "condition": {"metric": "burn_pct", "operator": ">", "threshold": 80,
                          "secondary_metric": "progress_pct", "secondary_operator": "<",
                          "secondary_threshold": 50, "threshold_eur": 6200.0,
                          "spent_at_creation": 6200.0}}

    class Coll:
        def find(self, *_a, **_k):
            class C:
                async def to_list(self, _n):
                    return [dict(rule, condition=dict(rule["condition"]))]
            return C()

    class Tenant:
        alarm_rules = Coll()
    monkeypatch.setattr(alarms, "_tenant", lambda _u: Tenant())
    for fin in (False, True):
        async def mv(*_a, _fin=fin, **_k):
            return _fin
        monkeypatch.setattr(alarms, "money_values_visible", mv)
        out = asyncio.run(alarms.list_rules(None, {"org_id": "T", "id": "u"}))
        cond = out["items"][0]["condition"]
        if fin:
            assert cond == rule["condition"]
        else:
            assert cond == {"metric": "burn_pct", "operator": ">", "threshold": 80,
                            "secondary_metric": "progress_pct", "secondary_operator": "<",
                            "secondary_threshold": 50}, cond
            assert "6200" not in json.dumps(out), out


def test_money_values_visible_off_and_shadow_follow_the_legacy_role(monkeypatch):
    import asyncio
    from app.permissions.money_write import money_values_visible
    for mode in ("off", "shadow"):
        monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
        for role in ("Owner", "Admin", "Accountant"):
            assert asyncio.run(money_values_visible(None, {"role": role}))
        for role in ("SiteManager", "Technician", "Viewer", "Driver", "Warehousekeeper"):
            assert not asyncio.run(money_values_visible(None, {"role": role}))


def test_overhead_reads_are_finance_only():
    from app.routes.overhead import check_overhead_access
    for role in ("Owner", "Admin", "Accountant"):
        assert check_overhead_access({"role": role})
    for role in ("SiteManager", "Technician", "Viewer", "Driver", "Warehousekeeper"):
        assert not check_overhead_access({"role": role})


def test_the_frontend_mirror_matches_the_catalog():
    from app.permissions.catalog import PERMISSION_MATRIX, LEGACY_ROLE_MAP
    src = FRONTEND_ACCESS.read_text(encoding="utf-8")

    def js_list(name):
        m = re.search(r"export const %s = \[([^\]]*)\]" % name, src)
        return sorted(re.findall(r'"([^"]+)"', m.group(1)))
    fin = sorted(legacy for legacy, rid in LEGACY_ROLE_MAP.items()
                 if MONEY_VALUES_READ in PERMISSION_MATRIX.get(rid, ()))
    assert js_list("FINANCE_ROLES") == fin
    assert js_list("BUDGET_VIEW_ROLES") == sorted(fin + ["SiteManager"])


def test_the_rule_table_itself():
    pr = {p["key"]: p for p in probes()}
    profit = pr["GET /api/project-profit/{project_id}"]
    ea = pr["GET /api/projects/{project_id}/expected-actual"]
    assert expected(profit, "Accountant", "P2")["reached"]
    assert not expected(profit, "SiteManager", "P1")["reached"]       # R20: no profit
    assert expected(ea, "SiteManager", "P1") == {"reached": True, "money": False}
    assert not expected(ea, "SiteManager", "P2")["reached"]           # not (yet) a member
    assert not expected(ea, "Technician", "P1")["reached"]
    assert expected(pr["labor_create"], "Technician", "P1") == {"reached": True, "money": False}
    assert not expected(pr["labor_list"], "Warehousekeeper", "P1")["reached"]
    assert expected(pr["labor_list"], "Viewer", None) == {"reached": True, "money": False}


def test_the_committed_evidence_satisfies_the_package():
    data = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    assert data["modes"] == list(MODES)
    assert sorted(set(data["roles"].values())) == sorted(
        ["Owner", "Admin", "SiteManager", "Technician", "Accountant", "Warehousekeeper",
         "Driver", "Viewer"])
    assert [p[0] for p in data["probes"]] == [p["key"] for p in probes()]
    check_rows(data["rows"])
    check_mirrors(data["site_manager_mirrors"])
    check_replay(data["labor_replay"])
    check_price_modifier_audit(data["price_modifier_audit"])
    check_pulse_one_paid_worker(data["pulse_one_paid_worker"])
    check_pulse_budget_alerts(data["pulse_budget_alerts"])
    check_alarms(data["alarms"])
    check_band_two_paid(data["band_paid_workers"])


def test_the_audit_scan_finds_no_money_for_non_finance_roles():
    """SEC-02-B: the audit scanner (tools/sec02_money_scan.py) over EVERY GET x SiteManager,
    Technician, Warehousekeeper, Driver, Viewer x off/shadow/enforce found no money,
    except the R20 budget view of the Technical Manager on his own project, the three
    judged non-money rates/price lists, and a technician's OWN profile."""
    from app.permissions.finance_read import (by_route, SCAN_JUDGED_NOT_MONEY,
                                              SCAN_OWN_RECORD_PATHS)
    scan = json.loads((EVIDENCE / "scan_sec02b.json").read_text(encoding="utf-8"))
    assert scan["calls"] > 5000 and scan["modes"] == ["off", "shadow", "enforce"]
    assert scan["hits"] == {}
    reg = by_route()
    for path, cells in scan["allowed_budget_view"].items():
        e = reg[("GET", path)]
        assert e.rule in (R20_2B, R20_5B) and e.action != EMPLOYEE_FILE_ACTION, path
        assert {c.split("/")[1] for c in cells} == {"requester"}, (path, cells)
    # R31 (FLOW-037 §3.4): what the Technical Manager keeps is per SMR / project only —
    # no per-worker list, rate or piece-rate price in any allowed path.
    for path, cells in scan["allowed_budget_view"].items():
        for keys in cells.values():
            for k in keys:
                assert not re.search(r"worker|hourly_rate|\.rate$|daily_rate|akord|"
                                     r"personnel", k), (path, k)
    assert set(scan["judged_not_money"]) <= set(SCAN_JUDGED_NOT_MONEY)
    assert set(scan["own_record"]) <= SCAN_OWN_RECORD_PATHS
    for cells in scan["own_record"].values():
        assert {c.split("/")[1] for c in cells} == {"technician"}


def test_sec71_01_no_allowed_budget_view_route_carries_a_forbidden_field():
    """SEC-02-G (Codex SEC71-01): EVERY route the scanners accept as the Technical
    Manager's budget view (``allowed_budget_view``, GET and POST/PUT scans, all modes)
    answered with no non-zero client price, sale, margin, profit, markup or commission —
    the scanners now file such a key as a hit (``budget_view_forbidden``), and the full
    key list of every allowed answer is kept. Also: each allowed route keeps budget keys
    only, and the budget freeze POST is among them."""
    from app.permissions.finance_read import budget_view_forbidden
    leaf = lambda k: re.split(r"[.\[\]]+", k.strip(".[]"))[-1]
    seen = set()
    for name in ("scan_sec02b.json", "scan_sec02e_post.json"):
        scan = json.loads((EVIDENCE / name).read_text(encoding="utf-8"))
        assert scan["hits"] == {}, name
        for path, cells in scan["allowed_budget_view"].items():
            seen.add(path)
            for keys in cells.values():
                assert keys, (name, path)
                bad = [k for k in keys if k.endswith("=text") or budget_view_forbidden(leaf(k))]
                assert bad == [], (name, path, bad)
    assert "POST /api/budget-freezes/{project_id}" in seen


# ═══════════════════════════════════════════════════════════════════ real-Mongo test
def _real_refusal() -> str:
    url = os.environ.get("W0_03_REAL_MONGO_URL", "")
    if not url:
        return "W0_03_REAL_MONGO_URL is not set — no disposable local MongoDB given"
    try:
        return _pm01()._real_refusal()
    except Exception as exc:                                   # noqa: BLE001
        return "refused: %s" % exc


@pytest.mark.skipif(bool(_real_refusal()), reason=_real_refusal() or "ok")
def test_the_audit_pulse_generate_probe_finds_nothing():
    """SEC-02-E: the audit's probe docs/audit/probes/sec02/probe_sec02_d_pulse_generate.py
    (claude/audit-log; vendored unchanged as tools/audit_probe_sec02_d_pulse_generate.py),
    off and enforce: (a) a non-member Warehousekeeper / a Viewer get no per-worker labor
    cost from POST /sites/{id}/pulse/generate; (b) the member SiteManager cannot derive a
    single-worker day's pay from two stored daily pulses."""
    probe = BACKEND / "tools" / "audit_probe_sec02_d_pulse_generate.py"
    for mode in ("off", "enforce"):
        env = dict(os.environ, MONGO_URL=os.environ["W0_03_REAL_MONGO_URL"], PROBE_MODE=mode,
                   PYTHONPATH=str(BACKEND))
        out = subprocess.run([sys.executable, str(probe)], cwd=str(BACKEND), env=env,
                             capture_output=True, text=True, timeout=600)
        assert out.returncode == 0, out.stderr[-2000:]
        assert "FAILS: none" in out.stdout, out.stdout[-2000:]
        assert "pulse/generate → 403" in out.stdout, out.stdout[-2000:]


@pytest.mark.skipif(bool(_real_refusal()), reason=_real_refusal() or "ok")
def test_the_audit_band_bisection_probe_finds_nothing():
    """SEC-02-G (audit SEC71-04 + SEC71-05, addenda F + H): the audit's probe
    docs/audit/probes/sec02/probe_sec71_d1_band_bisect.py (claude/audit-log; vendored
    unchanged as tools/audit_probe_sec71_d1_band_bisect.py) moves P1's budget as the
    Technical Manager and reads the generated pulse's status, in off/shadow/enforce. With
    one paid worker on P1 there is no status to bisect on: FAILS none."""
    probe = BACKEND / "tools" / "audit_probe_sec71_d1_band_bisect.py"
    # the in-process tests above leave MONGO_URL on a closed port; the probe needs the real one
    env = dict(os.environ, MONGO_URL=os.environ["W0_03_REAL_MONGO_URL"],
               PYTHONPATH=str(BACKEND))
    out = subprocess.run([sys.executable, str(probe)], cwd=str(BACKEND), env=env,
                         capture_output=True, text=True, timeout=900)
    assert out.returncode == 0, out.stderr[-2000:]
    # SEC-02-G (SEC71-05, addendum H): the probe also bisects through /alarms + resolve and
    # through evaluate.resolved_events with an auto_resolve rule. Its "known-pay variant"
    # (2 paid workers, one of them the TM himself) is a canon question put to Krum and is
    # left as it is — every OTHER finding must be gone.
    fails = out.stdout.rsplit("FAILS:", 1)[1].strip()
    if fails != "none":
        import ast
        left = [f for f in ast.literal_eval(fails) if not f.startswith("known-pay variant")]
        assert left == [], left
    for mode in MODES:
        assert "%s: first answer" % mode in out.stdout, out.stdout[-2000:]
        assert "%s /alarms: first" % mode in out.stdout, out.stdout[-2000:]
    assert "e90 auto_resolve oracle" in out.stdout and "404-oracle" in out.stdout, \
        out.stdout[-2000:]


def test_the_post_scan_finds_no_money_for_non_finance_roles():
    """SEC-02-E: tools/sec02_money_scan_post.py — every POST/PUT x 5 non-finance roles x
    3 modes, database restored after each call: no answer with money, except the Technical
    Manager's budget view on his own project and judged non-money rates."""
    from app.permissions.finance_read import by_route, SCAN_JUDGED_NOT_MONEY
    scan = json.loads((EVIDENCE / "scan_sec02e_post.json").read_text(encoding="utf-8"))
    assert scan["calls"] > 4000 and scan["modes"] == ["off", "shadow", "enforce"]
    assert scan["hits"] == {}
    reg = by_route()
    for path, cells in scan["allowed_budget_view"].items():
        method, p = path.split(" ", 1)
        assert reg[(method, p)].rule in (R20_2B, R20_5B), path
        assert {c.split("/")[1] for c in cells} == {"requester"}, (path, cells)
        for keys in cells.values():
            assert not any(re.search(r"worker|hourly_rate|daily_rate|spent|actual", k)
                           for k in keys), (path, keys)
    assert set(scan["judged_not_money"]) <= set(SCAN_JUDGED_NOT_MONEY)


@pytest.mark.skipif(bool(_real_refusal()), reason=_real_refusal() or "ok")
def test_the_audit_pulse_derive_probe_finds_nothing():
    """SEC-02-D: the audit's own probe (claude/audit-log
    docs/audit/probes/sec02/probe_sec02_c_pulse_derive.py, vendored unchanged as
    tools/audit_probe_sec02_c_pulse_derive.py) in off and enforce: no per-worker pay is
    derivable from the Technical Manager's pulse."""
    probe = BACKEND / "tools" / "audit_probe_sec02_c_pulse_derive.py"
    for mode in ("off", "enforce"):
        env = dict(os.environ, MONGO_URL=os.environ["W0_03_REAL_MONGO_URL"], PROBE_MODE=mode,
                   PYTHONPATH=str(BACKEND))
        out = subprocess.run([sys.executable, str(probe)], cwd=str(BACKEND), env=env,
                             capture_output=True, text=True, timeout=600)
        assert out.returncode == 0, out.stderr[-2000:]
        assert "FAILS: none" in out.stdout, out.stdout[-2000:]
        assert "DERIVED per-worker (pay, rate/h): {}" in out.stdout, out.stdout[-2000:]


@pytest.mark.skipif(bool(_real_refusal()), reason=_real_refusal() or "ok")
def test_a_fresh_real_mongo_run_on_two_tenants_follows_the_rules_in_every_mode(tmp_path):
    out = tmp_path / "results.json"
    run_in_child(os.environ["W0_03_REAL_MONGO_URL"], out)
    data = json.loads(out.read_text(encoding="utf-8"))
    check_rows(data["rows"])
    check_mirrors(data["site_manager_mirrors"])
    check_replay(data["labor_replay"])
    check_price_modifier_audit(data["price_modifier_audit"])
    check_pulse_one_paid_worker(data["pulse_one_paid_worker"])
    check_pulse_budget_alerts(data["pulse_budget_alerts"])
    check_alarms(data["alarms"])
    check_band_two_paid(data["band_paid_workers"])
    committed = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))["rows"]
    key = lambda r: (r["mode"], r["tenant"], r["role"], r["probe"], r["target"])
    assert {key(r): (r["status"], r.get("money_keys")) for r in data["rows"]} == \
        {key(r): (r["status"], r.get("money_keys")) for r in committed}


if __name__ == "__main__":
    sys.exit(main())
