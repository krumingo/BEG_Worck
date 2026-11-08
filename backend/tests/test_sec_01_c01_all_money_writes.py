"""
SEC-01-C01 — every write route on the SEC-01 money resources, plus R16
(decisions R14 and R16, Krum 06.11.2026).

Package: ``docs/architecture/tasks/SEC-01-C01_ALL_WRITES_ON_MONEY_RESOURCES.md``
(branch ``claude/happy-meitner-bmcnel``). Audit: ``docs/audit/AUDIT_LOG.md`` #69
(SEC-S1 Viewer hard-deletes project price modifiers, SEC-S2 Viewer creates labor rows
through sync-from-work-reports).

Rules under test (``app/permissions/money_write.py``):
  finance      Owner/Admin/Accountant, everybody else 403 (R14);
  owner_admin  Owner/Admin only — the existing rule of PUT /price-modifiers/org;
  r16          labor entries and material waste: Owner/Admin/Accountant everywhere;
               SiteManager/Technician ONLY on a project they are a member of;
               Viewer/Driver/others 403 — member or not;
  delete       DELETE /price-modifiers/project: no hard delete of a financial record
               (CLAUDE.md §2.9) and no archive model -> finance roles 409, others 403,
               nothing written;
  project owner  PUT/POST /projects that SET or CHANGE owner_type/owner_id = the
               client-link rule; unchanged values and projects without an owner keep
               their existing rule.

Every probe acts on EXISTING records (``tests/test_pm_01_permission_matrix.py``
``seed_existing_records``): a second project nobody is a member of, client companies,
price modifiers, a work report and an execution package, an existing row in every
money collection. Writes are measured from the oplog, with the org_id of each row.

    PYTHONPATH=. pytest tests/test_sec_01_c01_all_money_writes.py -v --noconftest
    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \\
        PYTHONPATH=. pytest tests/test_sec_01_c01_all_money_writes.py -v --noconftest
    # regenerate the evidence:
    PYTHONPATH=. python tests/test_sec_01_c01_all_money_writes.py --harness \\
        --mongo-url 'mongodb://127.0.0.1:27019/?directConnection=true'
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
EVIDENCE = REPO / "docs" / "evidence" / "SEC-01-C01"
RESULTS_JSON = EVIDENCE / "results.json"

MODES = ("off", "shadow", "enforce")
ROLE_KEYS = ("owner", "admin", "requester", "technician", "accountant",
             "warehousekeeper", "driver", "viewer")
FINANCE = {"Owner", "Admin", "Accountant"}
OWNER_ADMIN = {"Owner", "Admin"}
FIELD_MEMBER = {"SiteManager", "Technician"}
DB_PREFIX_OP, DB_PREFIX_SYS = "c01_op_", "c01_sys_"
SYNTH_PASSWORD = "C01-Synthetic-Pass-2026!"     # synthetic users of a scratch database
AUDIT = {"audit_events", "audit_logs", "audit_chain_heads", "audit_chain", "audit_idempotency"}

# Team of P1 in each tenant (P2 has no members). Viewer and Driver ARE members of P1:
# R16 still refuses them.
TEAM = (("requester", "SiteManager"), ("technician", "Technician"),
        ("viewer", "Viewer"), ("driver", "Viewer"))

# Cross-tenant callers: tenant B's roles against tenant A's P1.
CROSS_ROLES = ("admin", "accountant", "requester", "technician", "viewer")


# ═══════════════════════════════════════════════════════════════════════ the probes
# (key, method, path, action, rule, collection written on success, success status)
PROBES = (
    ("cash", "POST", "/api/finance/cash-transactions", "finance.cash_transaction.create",
     "finance", "cash_transactions", 201),
    ("bonus", "POST", "/api/finance/bonus-payments", "finance.bonus_payment.create",
     "finance", "bonus_payments", 201),
    ("ohtx", "POST", "/api/finance/overhead-transactions",
     "finance.overhead_transaction.create", "finance", "overhead_transactions", 201),
    ("ohsnap", "POST", "/api/overhead-snapshots", "finance.overhead_snapshot.create",
     "finance", "overhead_snapshots", 201),
    ("ohcompute", "POST", "/api/overhead/snapshots/compute",
     "finance.overhead_snapshot_compute.execute", "finance", "overhead_snapshots", 200),
    ("pm_org", "PUT", "/api/price-modifiers/org", "pricing.org_modifier.update",
     "owner_admin", "price_modifiers_config", 200),
    ("pm_put", "PUT", "/api/price-modifiers/project/{project_id}",
     "pricing.project_modifier.update", "finance", "price_modifiers_config", 200),
    ("pm_delete", "DELETE", "/api/price-modifiers/project/{project_id}",
     "pricing.project_modifier.delete", "delete", None, 409),
    ("client_link", "PATCH", "/api/projects/{project_id}/client-link",
     "project.client_link.update", "finance", "projects", 200),
    ("project_put_owner", "PUT", "/api/projects/{project_id}",
     "project.client_link.update", "project_put_owner", "projects", 200),
    ("project_put_same_owner", "PUT", "/api/projects/{project_id}",
     None, "project_put_same", "projects", 200),
    ("project_create_owner", "POST", "/api/projects",
     "project.client_link.update", "owner_admin", "projects", 201),
    ("project_create_plain", "POST", "/api/projects",
     None, "project_create_plain", "projects", 201),
    ("labor_create", "POST", "/api/labor-entries", "labor.entry.create",
     "r16", "labor_entries", 201),
    ("labor_sync", "POST", "/api/labor-entries/sync-from-work-reports",
     "labor.work_report_sync.execute", "r16", "labor_entries", 200),
    ("labor_recompute", "POST", "/api/execution-packages/recompute-labor/{project_id}",
     "labor.package_recompute.execute", "r16", "execution_packages", 200),
    ("waste_create", "POST", "/api/projects/{project_id}/material-waste",
     "material_waste.entry.create", "r16", "material_waste_entries", 201),
)
PROBE = {p[0]: p for p in PROBES}
PROJECT_PROBES = {p[0] for p in PROBES if "{project_id}" in p[2]} | {"labor_create",
                                                                      "labor_sync"}
# Probes whose success writes nothing when the target project has no source data
# (no work report / no execution package): P2, and A's project seen from tenant B.
WRITES_ONLY_WITH_SOURCE_DATA = {"labor_sync", "labor_recompute"}
# SEC-01-C02 (FG-26): the sync no longer deletes and recreates its rows. P1's synced row
# equals its work report, so a re-sync writes nothing at all; the changed-line case
# (reversal + new row, no delete) is proven in tests/test_sec_01_c02_*.py.
UNCHANGED_RESYNC = {"labor_sync"}
# Debt SEC-01-D1 (recorded by SEC-01, not fixed): these handlers do not check that the
# project id is one of the caller's tenant; a finance role of B writes a row in B.
# SEC-01-C03-B (FG-29) closed debt SEC-01-D1: these routes now check that the project
# exists in the caller's tenant (B -> A's project: 404, nothing written).
UNCHECKED_PROJECT: set = set()
PROJECT_CHECKED_R16 = {"labor_create", "waste_create"}


def body_for(key: str, t: Dict[str, Any], project_id: Optional[str]) -> Optional[dict]:
    if key == "cash":
        return {"type": "expense", "amount": 10, "category": "c01", "description": "C01"}
    if key == "bonus":
        return {"amount": 10, "user_id": t["users"]["viewer"]["id"], "description": "C01"}
    if key == "ohtx":
        return {"amount": 10, "category": "c01", "description": "C01"}
    if key == "ohsnap":
        return {"category_code": "general", "amount": 10, "period_key": "2026-11"}
    if key == "ohcompute":
        return {"period_start": "2026-11-01", "period_end": "2026-11-30",
                "method": "PersonDays"}
    if key in ("pm_org", "pm_put"):
        return {"modifiers": {"risk_percent": 7}}
    if key == "pm_delete":
        return None
    if key == "client_link":
        return {"client_id": t["company2_id"], "client_type": "company"}
    if key == "project_put_owner":
        return {"owner_type": "company", "owner_id": t["company2_id"]}
    if key == "project_put_same_owner":
        return {"owner_type": "company", "owner_id": t["company1_id"], "notes": "C01"}
    if key == "project_create_owner":
        return {"code": "C01-" + uuid.uuid4().hex[:8], "name": "C01", "status": "Active",
                "owner_type": "company", "owner_id": t["company1_id"]}
    if key == "project_create_plain":
        return {"code": "C01-" + uuid.uuid4().hex[:8], "name": "C01", "status": "Active"}
    if key in ("labor_create", "labor_sync"):
        return {"project_id": project_id, "hours": 1, "activity_name": "C01"}
    if key == "labor_recompute":
        return None
    if key == "waste_create":
        return {"material_name": "C01", "qty": 1}
    raise AssertionError(key)


# ═════════════════════════════════════════════════════════════════ expected outcome
def expected(key: str, legacy_role: str, target: Optional[str]) -> Dict[str, Any]:
    """The package's rule for one cell: {"status": int, "writes": bool}.

    ``target``: None (no project), "P1" (own project; SiteManager/Technician/Viewer/
    Driver are members), "P2" (own project, no members), "XA" (B's caller -> A's P1).
    """
    _k, _m, _p, _a, rule, coll, ok = PROBE[key]
    deny = {"status": 403, "writes": False}
    success = {"status": ok, "writes": True}
    if key in WRITES_ONLY_WITH_SOURCE_DATA and target in ("P2", "XA"):
        success = {"status": ok, "writes": False}
    if key in UNCHANGED_RESYNC:
        success = {"status": ok, "writes": False}
    if key == "waste_create":
        # WH-FIX-01 FG-159 (package WH-FIX-01, FLOW-009 single writer, merged after #69): POST material-waste is the CANONICAL write-off — it needs a Master item, stock on the project and evidence; this harness body has no item_id → 422 MASTER_IDENTITY_MISSING, nothing written. Its rights (R16 + Р27) stay checked here; the canonical write, its idempotency and replay are proven in tests/test_wh_fix_01_post_55.py::test_fg159_*.
        success = {"status": 422, "writes": False}
    if rule == "finance":
        if legacy_role not in FINANCE:
            return deny
        if target == "XA" and key not in UNCHECKED_PROJECT:
            return {"status": 404, "writes": False}         # looked up in the caller's tenant
        return success
    if rule == "owner_admin":
        return success if legacy_role in OWNER_ADMIN else deny
    if rule == "delete":
        return {"status": 409, "writes": False} if legacy_role in FINANCE else deny
    if rule == "r16":
        member = legacy_role in FIELD_MEMBER and target == "P1"
        if not (legacy_role in FINANCE or member):
            return deny
        if target == "XA" and key in PROJECT_CHECKED_R16:
            return {"status": 404, "writes": False}         # FG-29: not the caller's project
        return success
    if rule in ("project_put_owner", "project_put_same"):
        if target == "XA":
            return {"status": 404, "writes": False}         # the project is not B's
        if legacy_role in OWNER_ADMIN:
            return success
        manages = legacy_role == "SiteManager" and target == "P1"   # can_manage_project
        if rule == "project_put_same" and manages:
            return success                                  # unchanged owner: old rule
        return deny
    if rule == "project_create_plain":
        return success if legacy_role in OWNER_ADMIN | {"SiteManager"} else deny
    raise AssertionError(rule)


def _pm01():
    spec = importlib.util.spec_from_file_location(
        "c01_pm01_helpers", Path(__file__).resolve().parent / "test_pm_01_permission_matrix.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ═══════════════════════════════════════════════════════════════════════════ harness
def run_harness(mongo_url: str, out_json: Path) -> Dict[str, Any]:
    op_name, sys_name = os.environ["DB_NAME"], os.environ["BEG_SYSTEM_DB"]
    assert op_name.startswith(DB_PREFIX_OP) and sys_name.startswith(DB_PREFIX_SYS)
    pm = _pm01()
    import server
    from fastapi.testclient import TestClient

    app = server.app
    app.router.on_startup.clear()
    app.router.on_shutdown.clear()
    seed_mod = pm._load_seed()
    dbs = (op_name, sys_name)
    started = time.time()

    def short(ns: str) -> str:
        d, c = ns.split(".", 1)
        return ("op" if d == op_name else "sys") + "." + c

    with TestClient(app, raise_server_exceptions=False) as tc:
        client = tc.portal.call(lambda: pm._make_client(mongo_url))
        oplog = client.local["oplog.rs"]
        report = tc.portal.call(lambda: seed_mod.seed(client[op_name], client[sys_name],
                                                      SYNTH_PASSWORD))
        fx: Dict[str, Any] = {}
        for t in report["tenants"]:
            fx[t["key"]] = {"tenant_id": t["tenant_id"], "project_id": t["project_id"],
                            "users": {u["key"]: u for u in t["users"]}}
        tc.portal.call(lambda: pm.seed_existing_records(client[op_name], fx))
        tokens: Dict[tuple, str] = {}
        for tkey in ("A", "B"):
            for key in ROLE_KEYS:
                r = tc.post("/api/auth/login", json={
                    "email": fx[tkey]["users"][key]["email"], "password": SYNTH_PASSWORD})
                assert r.status_code == 200, (tkey, key, r.status_code, r.text[:200])
                tokens[(tkey, key)] = r.json()["token"]
        # The team of P1, added through the real API by the tenant's Admin in ENFORCE, so
        # project_team AND the mirrored project-scope RoleAssignment exist (W0-02 sync).
        os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
        for tkey in ("A", "B"):
            for ukey, role_in_project in TEAM:
                r = tc.post("/api/projects/%s/team" % fx[tkey]["project_id"],
                            json={"user_id": fx[tkey]["users"][ukey]["id"],
                                  "role_in_project": role_in_project},
                            headers={"Authorization": "Bearer " + tokens[(tkey, "admin")]})
                assert r.status_code == 201, (tkey, ukey, r.status_code, r.text[:300])
        os.environ["PERMISSION_SERVICE_MODE"] = "off"
        snap = tc.portal.call(lambda: pm._snapshot(client, dbs))

        def project_of(tkey: str, target: Optional[str]) -> Optional[str]:
            if target is None:
                return None
            if target == "XA":
                return fx["A"]["project_id"]
            return fx[tkey]["project_id"] if target == "P1" else fx[tkey]["project2_id"]

        def call(mode, tkey, role, key, target):
            _k, method, path, _a, _r, _c, _s = PROBE[key]
            pid = project_of(tkey, target)
            url = path.replace("{project_id}", pid or "")
            body = body_for(key, fx[tkey], pid)
            before = tc.portal.call(lambda: pm._last_ts(oplog))
            kwargs: Dict[str, Any] = {
                "headers": {"Authorization": "Bearer " + tokens[(tkey, role)],
                            # R29 / SEC-01-C03-A: every money POST carries a key
                            "Idempotency-Key": uuid.uuid4().hex}}
            if body is not None:
                kwargs["json"] = body
            resp = tc.request(method, url, **kwargs)
            written = tc.portal.call(lambda: pm.writes_with_org(client, oplog, before, dbs,
                                                                 snap))
            if written:
                tc.portal.call(lambda: pm._restore(client, snap, sorted({n for n, _ in written})))
            orgs = {"A" if o == fx["A"]["tenant_id"] else "B" if o == fx["B"]["tenant_id"]
                    else (None if o is None else "other") for n, o in written
                    if n.split(".", 1)[1] not in AUDIT}         # rows of business only
            return {"mode": mode, "tenant": tkey, "role": role,
                    "legacy_role": fx[tkey]["users"][role]["role"], "probe": key,
                    "method": method, "path": path, "target": target,
                    "status": resp.status_code,
                    "written": sorted({short(n) for n, _o in written
                                       if not n.endswith(".audit_idempotency")}),  # SEC-01-C03: the key registry is bookkeeping
                    "written_orgs": sorted(str(o) for o in orgs)}

        rows: List[Dict[str, Any]] = []
        for mode in MODES:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            for tkey in ("A", "B"):
                for key, *_ in PROBES:
                    targets = ("P1", "P2") if key in PROJECT_PROBES else (None,)
                    for target in targets:
                        for role in ROLE_KEYS:
                            rows.append(call(mode, tkey, role, key, target))
            for key in sorted(PROJECT_PROBES):
                for role in CROSS_ROLES:
                    rows.append(call(mode, "B", role, key, "XA"))
        os.environ["PERMISSION_SERVICE_MODE"] = "off"

    result = {
        "schema": "beg.sec-01-c01-money-writes/v1",
        "fixture": "ST-01 synthetic tenants A and B + PM-01 existing-record probes",
        "roles": {k: fx["A"]["users"][k]["role"] for k in ROLE_KEYS},
        "team_of_P1": [list(t) for t in TEAM],
        "modes": list(MODES), "probes": [list(p[:5]) for p in PROBES],
        "mongo": "local replica set (oplog)", "outbound_http": "closed local port",
        "seconds": round(time.time() - started, 1), "rows": rows,
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
    env["JWT_SECRET"] = "c01-local-" + uuid.uuid4().hex
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
    parser = argparse.ArgumentParser(description="SEC-01-C01 money-write evidence")
    parser.add_argument("--harness", action="store_true")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--mongo-url", default=os.environ.get("W0_03_REAL_MONGO_URL", ""))
    parser.add_argument("--out-json", default=str(RESULTS_JSON))
    args = parser.parse_args(argv)
    if not args.mongo_url:
        print("no --mongo-url and no W0_03_REAL_MONGO_URL", file=sys.stderr)
        return 2
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
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
    by_cell: Dict[tuple, Dict[str, Dict[str, Any]]] = {}
    for r in rows:
        exp = expected(r["probe"], r["legacy_role"], r["target"])
        assert r["status"] == exp["status"], (exp, r)
        business = [ns for ns in r["written"] if ns.split(".", 1)[1] not in AUDIT]
        if r["status"] == 403:
            # Nothing of business. off/shadow: nothing at all. enforce: at most the W0-02
            # "permission denied" AuditEvent (app/permissions/deps.py).
            assert business == [], r
            if r["mode"] == "enforce":
                assert set(r["written"]) <= {"op.audit_events"}, r
            else:
                assert r["written"] == [], r
        elif exp["writes"]:
            coll = "op." + PROBE[r["probe"]][5]
            assert coll in r["written"], r
            assert all(ns.startswith("op.") for ns in r["written"]), r
            # every written row is the CALLER's tenant; the other tenant is never written
            assert r["written_orgs"] == [r["tenant"]], r
        else:
            assert business == [], r                      # 404 / 409 / nothing to sync
        by_cell.setdefault((r["tenant"], r["role"], r["probe"], r["target"]), {})[r["mode"]] = r
    for cell, modes in by_cell.items():                   # same answer in every mode
        assert set(modes) == set(MODES), cell
        assert len({m["status"] for m in modes.values()}) == 1, (cell, modes)
        assert len({tuple(m["written"]) for m in modes.values()
                    if m["mode"] != "enforce"}) == 1, (cell, modes)
    probes = {c[2] for c in by_cell}
    assert probes == set(PROBE), probes
    own = [c for c in by_cell if c[3] != "XA"]
    assert len(own) == 2 * len(ROLE_KEYS) * sum(
        2 if k in PROJECT_PROBES else 1 for k in PROBE)
    assert len([c for c in by_cell if c[3] == "XA"]) == len(PROJECT_PROBES) * len(CROSS_ROLES)


# ═════════════════════════════════════════════════════════════════════ DB-free tests
def _routes():
    os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:1")
    os.environ.setdefault("DB_NAME", "c01_dbfree")
    os.environ.setdefault("JWT_SECRET", "c01-dbfree")
    import server
    from fastapi.routing import APIRoute
    return [r for r in server.app.routes if isinstance(r, APIRoute)]


# Every write route on the SEC-01 resources that carries the guard as a DEPENDENCY,
# declared first (before the module/subscription dependency and any read).
GUARDED_ROUTES = {
    ("POST", "/api/finance/cash-transactions"): "finance.cash_transaction.create",
    ("POST", "/api/finance/bonus-payments"): "finance.bonus_payment.create",
    ("POST", "/api/finance/overhead-transactions"): "finance.overhead_transaction.create",
    ("POST", "/api/overhead-snapshots"): "finance.overhead_snapshot.create",
    ("POST", "/api/overhead/snapshots/compute"): "finance.overhead_snapshot_compute.execute",
    ("PUT", "/api/price-modifiers/org"): "pricing.org_modifier.update",
    ("PUT", "/api/price-modifiers/project/{project_id}"): "pricing.project_modifier.update",
    ("DELETE", "/api/price-modifiers/project/{project_id}"): "pricing.project_modifier.delete",
    ("PATCH", "/api/projects/{project_id}/client-link"): "project.client_link.update",
    ("POST", "/api/labor-entries"): "labor.entry.create",
    ("POST", "/api/labor-entries/sync-from-work-reports"): "labor.work_report_sync.execute",
    ("POST", "/api/execution-packages/recompute-labor/{project_id}"):
        "labor.package_recompute.execute",
    ("POST", "/api/projects/{project_id}/material-waste"): "material_waste.entry.create",
}
R16_ROUTES = {k for k, a in GUARDED_ROUTES.items() if a.startswith(("labor.", "material_waste."))}


def _c02_routes():
    spec = importlib.util.spec_from_file_location(
        "c01_c02_routes",
        Path(__file__).resolve().parent / "test_sec_01_c02_flow_guard_money_writes.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.C02_GUARDED_ROUTES


def test_every_guarded_route_carries_its_action_first_and_no_other_route_does():
    """C01's routes; the only other marked routes are SEC-01-C02's (R14, FG-27/FG-30)."""
    c02 = _c02_routes()
    found = {}
    for route in _routes():
        calls = [d.call for d in route.dependant.dependencies]
        marked = [c for c in calls if hasattr(c, "sec01_action")]
        for method in route.methods:
            if marked and (method, route.path) not in c02:
                found[(method, route.path)] = (calls, marked)
    assert set(found) == set(GUARDED_ROUTES), sorted(set(found) ^ set(GUARDED_ROUTES))
    for key, (calls, marked) in found.items():
        assert len(marked) == 1 and calls[0] is marked[0], key
        assert marked[0].sec01_action == GUARDED_ROUTES[key], key
        assert (getattr(marked[0], "sec01_rule", None) == "R16") == (key in R16_ROUTES), key


def test_the_two_recompute_routes_of_pr55_are_not_touched():
    for route in _routes():
        if route.path in ("/api/execution-packages/recompute-material/{project_id}",
                          "/api/material-entries/sync/{project_id}"):
            assert not any(hasattr(d.call, "sec01_action")
                           for d in route.dependant.dependencies), route.path


def test_the_catalog_r16_and_money_grants():
    from app.permissions.catalog import (
        ACTIONS, PERMISSION_MATRIX, MONEY_WRITE_ACTIONS, FIELD_COST_WRITE_ACTIONS,
        ORG_PRICING_ACTIONS, project_membership_actions, is_significant_action,
        PROJECT_MEMBER_ACTIONS, PROJECT_MANAGER_ACTIONS, MONEY_WRITE_ACTIONS_C02)
    actions = set(GUARDED_ROUTES.values())
    assert actions <= ACTIONS
    assert all(is_significant_action(a) for a in actions)       # denials are audited
    company_money = actions - ORG_PRICING_ACTIONS
    assert company_money == MONEY_WRITE_ACTIONS - MONEY_WRITE_ACTIONS_C02   # + SEC-01-C02
    holders = {rid for rid, acts in PERMISSION_MATRIX.items() if acts & actions}
    assert holders == {"owner", "admin", "accountant"}           # company scope only
    assert not (PERMISSION_MATRIX["accountant"] & ORG_PRICING_ACTIONS)
    assert FIELD_COST_WRITE_ACTIONS == {a for k, a in GUARDED_ROUTES.items() if k in R16_ROUTES}
    # project-scope mirror of a membership: R16 only for SiteManager/Technician
    field = sorted(FIELD_COST_WRITE_ACTIONS)
    assert project_membership_actions("site_manager", "SiteManager") == \
        PROJECT_MANAGER_ACTIONS + field
    assert project_membership_actions("LEGACY_TECHNICIAN", "Technician") == \
        PROJECT_MEMBER_ACTIONS + field
    for rid in ("LEGACY_VIEWER", "driver", "warehouse", "accountant", "office", "worker"):
        for rip in ("SiteManager", "Technician", "Viewer"):
            assert not set(project_membership_actions(rid, rip)) & FIELD_COST_WRITE_ACTIONS


def test_the_enforce_scope_rule_for_r16():
    """The Permission Service decision on the assignments R16 creates (no database)."""
    import asyncio
    from app.permissions import service
    from app.permissions.catalog import project_membership_actions

    def company(rid):
        return {"id": "c-" + rid, "status": "active", "role_id": rid, "scope_type": "company",
                "scope_id": None, "permissions": []}

    def mirror(rid, pid, rip):
        return {"id": "p-%s-%s" % (rid, pid), "status": "active", "role_id": rid,
                "scope_type": "project", "scope_id": pid,
                "permissions": project_membership_actions(rid, rip)}

    class Ctx:
        user_id, tenant_id = "u", "T"

    def allowed(assignments, pid):
        async def load(_u, _t):
            return assignments
        orig = service._load_assignments
        service._load_assignments = load
        try:
            return asyncio.run(service.evaluate_permission(
                Ctx(), "labor.entry.create", module="M2", scope_type="project",
                scope_id=pid)).allowed
        finally:
            service._load_assignments = orig

    assert allowed([company("accountant")], "P1") and allowed([company("accountant")], "P2")
    assert allowed([company("site_manager"), mirror("site_manager", "P1", "SiteManager")], "P1")
    assert not allowed([company("site_manager"), mirror("site_manager", "P1", "SiteManager")], "P2")
    assert allowed([mirror("LEGACY_TECHNICIAN", "P1", "Technician")], "P1")
    assert not allowed([company("LEGACY_VIEWER"), mirror("LEGACY_VIEWER", "P1", "Viewer")], "P1")
    assert not allowed([company("driver"), mirror("driver", "P1", "Viewer")], "P1")
    assert not allowed([company("site_manager")], None)       # no project -> no grant


def test_the_rule_table_itself():
    assert expected("labor_create", "Technician", "P1")["status"] == 201
    assert expected("labor_create", "Technician", "P2")["status"] == 403
    assert expected("labor_create", "Viewer", "P1")["status"] == 403
    assert expected("labor_create", "Driver", "P1")["status"] == 403
    assert expected("labor_create", "SiteManager", "XA")["status"] == 403
    assert expected("pm_delete", "Accountant", "P1") == {"status": 409, "writes": False}
    assert expected("pm_delete", "Viewer", "P1")["status"] == 403
    assert expected("pm_org", "Accountant", None)["status"] == 403
    assert expected("project_put_owner", "SiteManager", "P1")["status"] == 403
    assert expected("project_put_same_owner", "SiteManager", "P1")["status"] == 200
    assert expected("project_create_owner", "SiteManager", None)["status"] == 403
    assert expected("project_create_plain", "SiteManager", None)["status"] == 201


def test_the_committed_evidence_satisfies_the_package():
    data = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    assert data["modes"] == list(MODES)
    assert sorted(set(data["roles"].values())) == sorted(
        ["Owner", "Admin", "SiteManager", "Technician", "Accountant", "Warehousekeeper",
         "Driver", "Viewer"])
    check_rows(data["rows"])


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
def test_a_fresh_real_mongo_run_on_two_tenants_follows_the_rules_in_every_mode(tmp_path):
    out = tmp_path / "results.json"
    run_in_child(os.environ["W0_03_REAL_MONGO_URL"], out)
    fresh = json.loads(out.read_text(encoding="utf-8"))["rows"]
    check_rows(fresh)
    committed = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))["rows"]
    key = lambda r: (r["mode"], r["tenant"], r["role"], r["probe"], r["target"])
    assert {key(r): (r["status"], r["written"]) for r in fresh} == \
        {key(r): (r["status"], r["written"]) for r in committed}


if __name__ == "__main__":
    sys.exit(main())
