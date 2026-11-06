"""
SEC-01 — money writes only for the finance roles (decision R14, Krum 06.11.2026).

Package: ``docs/architecture/tasks/SEC-01_MONEY_WRITE_PERMISSIONS.md``. Evidence of the hole:
``docs/architecture/PM-01_PERMISSION_MODE_REPORT.md`` §5.1. FLOW-002 (roles/permissions),
FLOW-006 (one Payment ledger — not touched here), W0-02 Permission Service.

The eight endpoints are refused for every role except Owner/Admin/Accountant, BEFORE any
read or write, identically in PERMISSION_SERVICE_MODE off / shadow / enforce
(``app/permissions/money_write.py``; catalog actions in ``app/permissions/catalog.py``).

DB-free tests (always):
  * the catalog grants the eight actions to owner/admin/accountant and to nobody else;
  * each of the eight routes carries the SEC-01 dependency, declared before the module
    (subscription) dependency, and no other route does;
  * the committed real-Mongo evidence (``docs/evidence/SEC-01/results.json``) says what
    the package requires.

Real Mongo (``W0_03_REAL_MONGO_URL``, a LOCAL replica set — the oplog measures writes):
  a fresh run on the ST-01 fixtures (tenants A and B) for every role × endpoint × mode,
  checked against the rules directly, not only against the committed file.

    PYTHONPATH=. pytest tests/test_sec_01_money_write_permissions.py -v --noconftest
    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \\
        PYTHONPATH=. pytest tests/test_sec_01_money_write_permissions.py -v --noconftest
    # regenerate the evidence:
    PYTHONPATH=. python tests/test_sec_01_money_write_permissions.py --harness \\
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
from typing import Any, Dict, List, Optional

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
EVIDENCE = REPO / "docs" / "evidence" / "SEC-01"
RESULTS_JSON = EVIDENCE / "results.json"

MODES = ("off", "shadow", "enforce")
ROLE_KEYS = ("owner", "admin", "requester", "technician", "accountant",
             "warehousekeeper", "driver", "viewer")
ALLOWED_LEGACY = {"Owner", "Admin", "Accountant"}
# FG-24 (SEC-01-C02): this harness runs on the bare ST-01 fixture, which has NO project
# membership (test_the_fixture_has_no_project_membership below). So a SiteManager or
# Technician refused here on labor/waste is a NON-member — exactly R16. A MEMBER
# SiteManager/Technician writes labor and waste: tests/test_sec_01_c01_*.py and
# tests/test_sec_01_c02_*.py. This file does not assert "SiteManager never writes labor".
R16_PATHS = {"/api/labor-entries", "/api/projects/{project_id}/material-waste"}
DB_PREFIX_OP, DB_PREFIX_SYS = "sec01_op_", "sec01_sys_"
SYNTH_PASSWORD = "SEC01-Synthetic-Pass-2026!"   # synthetic users of a scratch database

# (method, path, action, business collection written on success, status on success)
ENDPOINTS = (
    ("POST", "/api/finance/cash-transactions", "finance.cash_transaction.create",
     "cash_transactions", 201),
    ("POST", "/api/finance/bonus-payments", "finance.bonus_payment.create",
     "bonus_payments", 201),
    ("POST", "/api/finance/overhead-transactions", "finance.overhead_transaction.create",
     "overhead_transactions", 201),
    ("POST", "/api/overhead-snapshots", "finance.overhead_snapshot.create",
     "overhead_snapshots", 201),
    ("PUT", "/api/price-modifiers/project/{project_id}", "pricing.project_modifier.update",
     "price_modifiers_config", 200),
    ("POST", "/api/labor-entries", "labor.entry.create", "labor_entries", 201),
    ("POST", "/api/projects/{project_id}/material-waste", "material_waste.entry.create",
     "material_waste_entries", 201),
    ("PATCH", "/api/projects/{project_id}/client-link", "project.client_link.update",
     "projects", 200),
)
MONEY_ACTIONS = {e[2] for e in ENDPOINTS}


def _body(path: str, fx_t: Dict[str, Any]) -> Dict[str, Any]:
    if path.endswith("cash-transactions"):
        return {"type": "expense", "amount": 10, "category": "sec01", "description": "SEC-01"}
    if path.endswith("bonus-payments"):
        return {"amount": 10, "user_id": fx_t["users"]["viewer"]["id"], "description": "SEC-01"}
    if path.endswith("overhead-transactions"):
        return {"amount": 10, "category": "sec01", "description": "SEC-01"}
    if path.endswith("overhead-snapshots"):
        return {"category_code": "general", "amount": 10, "period_key": "2026-11"}
    if "price-modifiers" in path:
        return {"modifiers": {}}
    if path.endswith("labor-entries"):
        return {"project_id": fx_t["project_id"], "hours": 1, "activity_name": "SEC-01"}
    if path.endswith("material-waste"):
        return {"material_name": "SEC-01", "qty": 1}
    if path.endswith("client-link"):
        return {"client_id": None}
    raise AssertionError(path)


def _pm01():
    """The PM-01 harness helpers (oplog write detection, snapshot/restore, child env)."""
    spec = importlib.util.spec_from_file_location(
        "sec01_pm01_helpers", Path(__file__).resolve().parent / "test_pm_01_permission_matrix.py")
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
        tokens: Dict[tuple, str] = {}
        for tkey in ("A", "B"):
            for key in ROLE_KEYS:
                r = tc.post("/api/auth/login", json={
                    "email": fx[tkey]["users"][key]["email"], "password": SYNTH_PASSWORD})
                assert r.status_code == 200, (tkey, key, r.status_code, r.text[:200])
                tokens[(tkey, key)] = r.json()["token"]
        snap = tc.portal.call(lambda: pm._snapshot(client, dbs))

        def call(mode, tkey, role, method, path, project_of):
            url = path.replace("{project_id}", fx[project_of]["project_id"])
            before = tc.portal.call(lambda: pm._last_ts(oplog))
            resp = tc.request(method, url, json=_body(path, fx[tkey]),
                              headers={"Authorization": "Bearer " + tokens[(tkey, role)]})
            written = tc.portal.call(lambda: pm._writes_since(oplog, before, dbs))
            org = None
            if resp.status_code < 300:
                payload = resp.json()
                org = payload.get("org_id") if isinstance(payload, dict) else None
                if path.endswith("client-link"):
                    proj = tc.portal.call(lambda: client[op_name]["projects"].find_one(
                        {"id": fx[project_of]["project_id"]}, {"_id": 0, "org_id": 1}))
                    org = proj["org_id"]
            if written:
                tc.portal.call(lambda: pm._restore(client, snap, written))
            return {"mode": mode, "tenant": tkey, "role": role,
                    "legacy_role": fx[tkey]["users"][role]["role"],
                    "method": method, "path": path, "target_project_tenant": project_of,
                    "status": resp.status_code,
                    "written": sorted(short(n) for n in written),
                    "record_org_is_caller_tenant": (None if org is None
                                                    else org == fx[tkey]["tenant_id"])}

        rows: List[Dict[str, Any]] = []
        for mode in MODES:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            for tkey in ("A", "B"):
                for method, path, _a, _c, _s in ENDPOINTS:
                    for role in ROLE_KEYS:
                        rows.append(call(mode, tkey, role, method, path, tkey))
            # cross-tenant: B's roles against A's project (project-scoped endpoints)
            for method, path, _a, _c, _s in ENDPOINTS:
                if "{project_id}" not in path:
                    continue
                for role in ("accountant", "viewer"):
                    rows.append(call(mode, "B", role, method, path, "A"))
        os.environ["PERMISSION_SERVICE_MODE"] = "off"

    result = {
        "schema": "beg.sec-01-money-write/v1",
        "fixture": "ST-01 synthetic tenants A and B",
        "roles": {k: fx["A"]["users"][k]["role"] for k in ROLE_KEYS},
        "modes": list(MODES), "endpoints": [list(e[:3]) for e in ENDPOINTS],
        "mongo": "local replica set (oplog)", "outbound_http": "closed local port",
        "seconds": round(time.time() - started, 1), "rows": rows,
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    return result


def run_in_child(mongo_url: str, out_json: Path, timeout: int = 1800) -> None:
    pm = _pm01()
    suffix = uuid.uuid4().hex[:12]
    op_name, sys_name = DB_PREFIX_OP + suffix, DB_PREFIX_SYS + suffix
    env = pm.child_env(mongo_url, op_name, sys_name)
    env["JWT_SECRET"] = "sec01-local-" + uuid.uuid4().hex
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
    parser = argparse.ArgumentParser(description="SEC-01 money-write permission evidence")
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
BUSINESS = {e[1]: "op." + e[3] for e in ENDPOINTS}
SUCCESS = {e[1]: e[4] for e in ENDPOINTS}
# Debt SEC-01-D1 (not fixed here — CLAUDE.md §18: technical anomalies are recorded, Krum
# decides): these handlers write without checking that {project_id} is a project of the
# caller's tenant. The write still goes to the caller's own tenant (org_id).
CROSS_TENANT_UNCHECKED_PROJECT = {
    "/api/price-modifiers/project/{project_id}",
    "/api/projects/{project_id}/material-waste",
}


def check_rows(rows: List[Dict[str, Any]]) -> None:
    """The package's rules, cell by cell."""
    assert rows
    by_cell: Dict[tuple, Dict[str, Dict[str, Any]]] = {}
    for r in rows:
        allowed = r["legacy_role"] in ALLOWED_LEGACY
        cross = r["target_project_tenant"] != r["tenant"]
        if not allowed:
            # Denied: 403, and NOTHING of business is written. In enforce the only write is
            # the W0-02 "permission denied" AuditEvent (by design, app/permissions/deps.py).
            assert r["status"] == 403, r
            expected = ["op.audit_events"] if r["mode"] == "enforce" else []
            assert r["written"] == expected, r
        elif cross:
            # A finance role of tenant B never touches tenant A's data. client-link looks
            # the project up in the caller's tenant -> 404, nothing written. price-modifiers
            # and material-waste do NOT check that the project exists (pre-existing, outside
            # SEC-01, recorded as debt SEC-01-D1): their row lands in tenant B with B's
            # org_id — tenant A is not written.
            if r["path"] in CROSS_TENANT_UNCHECKED_PROJECT:
                assert r["status"] == SUCCESS[r["path"]], r
                assert r["written"] == [BUSINESS[r["path"]]], r
                assert r["record_org_is_caller_tenant"] is True, r
            else:
                assert r["status"] == 404, r
                assert r["written"] == [], r
        else:
            assert r["status"] == SUCCESS[r["path"]], r
            assert BUSINESS[r["path"]] in r["written"], r
            assert all(ns.startswith("op.") for ns in r["written"]), r
            assert r["record_org_is_caller_tenant"] is True, r
        by_cell.setdefault((r["tenant"], r["role"], r["method"], r["path"],
                            r["target_project_tenant"]), {})[r["mode"]] = r
    # off / shadow / enforce give the same status for every cell
    for cell, modes in by_cell.items():
        assert set(modes) == set(MODES), cell
        assert len({m["status"] for m in modes.values()}) == 1, (cell, modes)
    # coverage: 8 endpoints × 8 roles × 2 tenants × 3 modes, + the cross-tenant cells
    own = [c for c in by_cell if c[0] == c[4]]
    assert len(own) == len(ENDPOINTS) * len(ROLE_KEYS) * 2
    assert {c[1] for c in own} == set(ROLE_KEYS)


# ═════════════════════════════════════════════════════════════════════ DB-free tests
def test_the_catalog_grants_the_money_writes_to_owner_admin_accountant_only():
    from app.permissions.catalog import ACTIONS, PERMISSION_MATRIX, MONEY_WRITE_ACTIONS
    # SEC-01-C01 adds the other write routes on the same resources (superset).
    assert MONEY_ACTIONS <= MONEY_WRITE_ACTIONS
    assert MONEY_ACTIONS <= ACTIONS
    holders = {rid for rid, acts in PERMISSION_MATRIX.items() if acts & MONEY_ACTIONS}
    assert holders == {"owner", "admin", "accountant"}
    for rid in holders:
        assert MONEY_ACTIONS <= PERMISSION_MATRIX[rid], rid


def test_every_money_write_denial_is_audited_in_enforce():
    from app.permissions.catalog import is_significant_action
    assert all(is_significant_action(a) for a in MONEY_ACTIONS)


def _routes():
    os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:1")
    os.environ.setdefault("DB_NAME", "sec01_dbfree")
    os.environ.setdefault("JWT_SECRET", "sec01-dbfree")
    import server
    from fastapi.routing import APIRoute
    return [r for r in server.app.routes if isinstance(r, APIRoute)]


def _dep_calls(route):
    return [d.call for d in route.dependant.dependencies]


def test_the_eight_routes_carry_the_sec01_dependency_before_any_other():
    """SEC-01-C01 guards more routes; the complete list is asserted in
    tests/test_sec_01_c01_all_money_writes.py."""
    found = {}
    for route in _routes():
        calls = _dep_calls(route)
        marked = [c for c in calls if hasattr(c, "sec01_action")]
        for method in route.methods:
            if marked:
                found[(method, route.path)] = route
    assert {(e[0], e[1]) for e in ENDPOINTS} <= set(found), sorted(found)
    for key, route in found.items():
        calls = _dep_calls(route)
        first = calls[0]
        assert hasattr(first, "sec01_action"), (key, calls)
        assert len([c for c in calls if hasattr(c, "sec01_action")]) == 1, key


def test_the_routes_ask_for_the_action_of_their_endpoint():
    expected = {(e[0], e[1]): e[2] for e in ENDPOINTS}
    seen = set()
    for route in _routes():
        for method in route.methods:
            if (method, route.path) in expected:
                first = route.dependant.dependencies[0].call
                assert getattr(first, "sec01_action", None) == expected[(method, route.path)]
                seen.add((method, route.path))
    assert seen == set(expected)


def test_the_committed_evidence_satisfies_the_package():
    data = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    assert data["modes"] == list(MODES)
    assert sorted(set(data["roles"].values())) == sorted(
        ["Owner", "Admin", "SiteManager", "Technician", "Accountant", "Warehousekeeper",
         "Driver", "Viewer"])
    check_rows(data["rows"])


def test_the_fixture_has_no_project_membership():
    """FG-24: the R16 denials of this file are non-member denials (see R16_PATHS)."""
    src = (REPO / "ops" / "staging" / "seed_synthetic.py").read_text(encoding="utf-8")
    assert "project_team" not in src and "/team" not in src


def test_the_pm01_matrix_shows_the_money_write_cells_closed():
    """PM-01 §5.1 re-run: for the eight endpoints, every non-finance role gets 403 and
    nothing of business is written, in every mode; the finance roles still write."""
    import csv
    path = REPO / "docs" / "evidence" / "PM-01" / "matrix.csv"
    with open(path, encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh)
                if (r["method"], r["path"]) in {(e[0], e[1]) for e in ENDPOINTS}]
    assert len(rows) == len(ENDPOINTS) * len(ROLE_KEYS) * len(MODES)
    for r in rows:
        if r["legacy_role"] in ALLOWED_LEGACY:
            assert r["status"] == str(SUCCESS[r["path"]]) and r["wrote"] == "yes", r
            assert BUSINESS[r["path"]] in r["written"].split(";"), r
        else:
            assert r["status"] == "403", r
            assert r["wrote"] == ("audit_only" if r["mode"] == "enforce" else "no"), r


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
def test_a_fresh_real_mongo_run_on_two_tenants_follows_the_rule_in_every_mode(tmp_path):
    out = tmp_path / "results.json"
    run_in_child(os.environ["W0_03_REAL_MONGO_URL"], out)
    fresh = json.loads(out.read_text(encoding="utf-8"))["rows"]
    check_rows(fresh)
    committed = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))["rows"]
    key = lambda r: (r["mode"], r["tenant"], r["role"], r["method"], r["path"],
                     r["target_project_tenant"])
    assert {key(r): (r["status"], r["written"]) for r in fresh} == \
        {key(r): (r["status"], r["written"]) for r in committed}


if __name__ == "__main__":
    sys.exit(main())
