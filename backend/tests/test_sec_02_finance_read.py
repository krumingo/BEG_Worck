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
            "alerts": []})
        await op_db.material_entries.insert_one({
            "id": sid(tkey, "me1"), "org_id": org, "project_id": p1, "material_name": "Probe",
            "qty": 5, "unit": "kg", "unit_cost": 7777.0, "total_cost": 7777.0,
            "date": "2026-11-02", "created_at": now})
        await op_db.work_sessions.insert_one({
            "id": sid(tkey, "ws1"), "org_id": org, "worker_id": tech, "site_id": p1,
            "smr_type_id": "Мазилка", "started_at": "2026-11-02T07:00:00",
            "ended_at": "2026-11-02T15:00:00", "duration_hours": 8, "labor_cost": 3200,
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
                    and resp.status_code == 200:
                from app.permissions.finance_read import _is_actual
                row["actual_keys"] = sorted({k for k in body_money_keys(body) if _is_actual(k)})
                row["worker_detail"] = money_keys_in(body, {"workers", "workers_count"})
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
        if r["status"] == 200 and "actual_keys" in r and r["legacy_role"] == "SiteManager" \
                and r["tenant"] in ("A", "B") and r["target"] in ("P1", None):
            # SEC-02-D (audit SEC02C-1; R31): P1 has ONE worker in the seed, so the
            # Technical Manager gets no spent / actual at all, and never worker detail.
            assert r["actual_keys"] == [] and r["worker_detail"] == [], r
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
    assert stripped == {(e.method, e.path) for e in FINANCE_READS if e.rule in (R20_5M, R20_5B)}


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
    assert {a for a in reads | PROJECT_BUDGET_READ_ACTIONS if is_significant_action(a)} == \
        {"finance.company_finance.export", "finance.smr_analysis.export",
         "finance.offer_document.export", "finance.offer_spreadsheet.export"}
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

    async def r31_as_is(_u, _p, body):        # the R31 step is tested on its own below
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
    committed = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))["rows"]
    key = lambda r: (r["mode"], r["tenant"], r["role"], r["probe"], r["target"])
    assert {key(r): (r["status"], r.get("money_keys")) for r in data["rows"]} == \
        {key(r): (r["status"], r.get("money_keys")) for r in committed}


if __name__ == "__main__":
    sys.exit(main())
