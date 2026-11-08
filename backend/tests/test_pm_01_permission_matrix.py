"""
PM-01 — every role × every public endpoint × PERMISSION_SERVICE_MODE off / shadow / enforce.

Package: docs/architecture/tasks/PM-01_PERMISSION_MODE_ROLE_MATRIX.md (approved by Krum,
06.11.2026, R9). Source: PR #64 ``02-release-gates.md`` step 5 — "Existing layout expects
PERMISSION_SERVICE_MODE=off; LIVE-OPS writes require enforce. Resolve this explicitly with
tested roles before building." FLOW-002 (users/roles), FLOW-043 (W0-02 Permission Service).

Tests and evidence only. Nothing here changes a role, a permission, a flag or business code.

What the generated run does (``python tests/test_pm_01_permission_matrix.py --harness``):

* a fresh pair of scratch databases ``pm01_op_<hex>`` / ``pm01_sys_<hex>`` on a disposable,
  LOCAL replica-set MongoDB (the oplog is how "was anything written" is measured);
* the ST-01 fixtures (``ops/staging/seed_synthetic.py``, tenants A and B) — real users,
  TenantMemberships and FLOW-002 RoleAssignments, real JWT from ``/api/auth/login``;
* the WHOLE application (``server.app``, startup hooks not run — no demo seed), every
  APIRoute it serves, called once per role of tenant A and per mode, with a body/query
  generated from the route's own OpenAPI schema (required fields only, synthetic values);
* per call: HTTP status and every namespace of the two scratch databases that the oplog
  shows written (insert/update/delete/command, transactions unpacked); after a call that
  wrote, exactly those collections are put back to the seeded baseline, so each cell
  starts from the same data;
* outbound HTTP goes to a closed local port (no email, billing or AI provider is reached).

The result is ``docs/evidence/PM-01/matrix.csv`` (one row per endpoint × role × mode) and
``docs/evidence/PM-01/run_meta.json``. The tests below keep it as a regression:

* DB-free: the committed matrix covers exactly the routes the application serves today,
  every role and every mode (a new or removed endpoint makes this fail until the run is
  repeated and the report updated);
* real Mongo (``W0_03_REAL_MONGO_URL``, local only): a fresh run gives the same status and
  the same "wrote / did not write" for every cell as the committed matrix.

    PYTHONPATH=. pytest tests/test_pm_01_permission_matrix.py -v --noconftest
    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \\
        PYTHONPATH=. pytest tests/test_pm_01_permission_matrix.py -v --noconftest
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
STAGING = REPO / "ops" / "staging"
EVIDENCE = REPO / "docs" / "evidence" / "PM-01"
MATRIX_CSV = EVIDENCE / "matrix.csv"
META_JSON = EVIDENCE / "run_meta.json"

MODES = ("off", "shadow", "enforce")
# The eight distinct roles of the package (Owner, Admin, SiteManager, Technician,
# Accountant, Warehousekeeper, Driver, Viewer) as ST-01 fixture keys. ``approver`` and
# ``denied`` are the same legacy roles as ``admin`` / ``viewer`` and are not repeated.
ROLE_KEYS = ("owner", "admin", "requester", "technician", "accountant",
             "warehousekeeper", "driver", "viewer")
CSV_FIELDS = ("module", "method", "path", "role", "legacy_role", "mode", "status",
              "wrote", "written")
DB_PREFIX_OP, DB_PREFIX_SYS = "pm01_op_", "pm01_sys_"
SYNTH_PASSWORD = "PM01-Synthetic-Pass-2026!"     # synthetic users of a scratch database
MISSING_ID = "pm01-missing-id"
DEAD_PROXY = "http://127.0.0.1:9"                  # closed port: no outbound HTTP succeeds

# Collections whose only purpose is the audit trail. A call that wrote ONLY these did
# not change business data (e.g. the enforce-mode "permission denied" AuditEvent).
AUDIT_COLLECTIONS = ("audit_events", "audit_logs", "audit_chain_heads", "audit_chain")


def route_key(method: str, path: str) -> str:
    return "%s %s" % (method, path)


def is_audit_only(written: List[str]) -> bool:
    return bool(written) and all(ns.split(".", 1)[1] in AUDIT_COLLECTIONS for ns in written)


# ═════════════════════════════════════════════════════════════════════ route inventory
def app_routes(app) -> List[Tuple[str, str, str, Any]]:
    """(module, method, path, route) for every APIRoute the application serves."""
    from fastapi.routing import APIRoute
    out = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        module = route.endpoint.__module__.rsplit(".", 1)[-1]
        for method in sorted(route.methods):
            out.append((module, method, route.path, route))
    out.sort(key=lambda r: (r[0], r[2], r[1]))
    return out


# ═══════════════════════════════════════════════════════ request synthesis from OpenAPI
def _resolve(schema: Dict[str, Any], spec: Dict[str, Any]) -> Dict[str, Any]:
    seen = 0
    while isinstance(schema, dict) and "$ref" in schema and seen < 20:
        ref = schema["$ref"].split("/")[-1]
        schema = spec.get("components", {}).get("schemas", {}).get(ref, {})
        seen += 1
    return schema or {}


def sample(schema: Dict[str, Any], spec: Dict[str, Any], depth: int = 0, name: str = "") -> Any:
    """A deterministic synthetic value for ``schema`` (required fields only). A plain
    string field whose name says it holds a date gets an ISO date."""
    schema = _resolve(schema, spec)
    if depth > 6:
        return None
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = [s for s in schema[key] if _resolve(s, spec).get("type") != "null"]
            return sample(options[0], spec, depth + 1) if options else None
    if "allOf" in schema:
        merged: Dict[str, Any] = {}
        for part in schema["allOf"]:
            value = sample(part, spec, depth + 1)
            if isinstance(value, dict):
                merged.update(value)
        return merged
    kind = schema.get("type")
    fmt = schema.get("format", "")
    if kind == "object" or "properties" in schema:
        props = schema.get("properties", {})
        return {key: sample(props.get(key, {}), spec, depth + 1, key)
                for key in schema.get("required", [])}
    if kind == "array":
        n = int(schema.get("minItems") or 0)
        return [sample(schema.get("items", {}), spec, depth + 1) for _ in range(n)]
    if kind == "integer":
        return max(1, int(schema.get("minimum", 1) or 1))
    if kind == "number":
        return max(1.0, float(schema.get("minimum", 1) or 1))
    if kind == "boolean":
        return False
    if kind == "string" or not kind:
        if fmt == "date" or re.search(r"(^|_)(date|from|to|start|end)(_|$)", name):
            return "2026-11-02"
        if fmt == "date-time":
            return "2026-11-02T08:00:00+00:00"
        if fmt == "email":
            return "pm01.sample@pm01.test"
        n = int(schema.get("minLength") or 0)
        return "PM01" + "x" * max(0, n - 4)
    return None


def path_values(fx: Dict[str, Any]) -> Dict[str, str]:
    """Path parameters that name a real ST-01 record of tenant A; all others get a
    synthetic id that exists nowhere."""
    a = fx["A"]
    return {"project_id": a["project_id"], "warehouse_id": a["warehouse_id"],
            "user_id": a["users"]["denied"]["id"], "org_id": a["tenant_id"]}


def build_request(method: str, path: str, spec: Dict[str, Any], values: Dict[str, str]):
    op = spec.get("paths", {}).get(path, {}).get(method.lower(), {})
    url = re.sub(r"\{([^}:]+)(:[^}]*)?\}",
                 lambda m: values.get(m.group(1), MISSING_ID), path)
    query: Dict[str, Any] = {}
    for p in op.get("parameters", []):
        if p.get("in") == "query" and p.get("required"):
            query[p["name"]] = sample(p.get("schema", {}), spec, 0, p["name"])
    body = None
    content = op.get("requestBody", {}).get("content", {})
    if "application/json" in content:
        body = sample(content["application/json"].get("schema", {}), spec)
    # multipart/form-data: no body is generated (no file is uploaded anywhere); the
    # route answers 422 unless its authorization refuses first.
    return url, query, body


# ═══════════════════════════════════════════════════════════════════════════ harness
def _load_seed():
    spec = importlib.util.spec_from_file_location("pm01_st01_seed", STAGING / "seed_synthetic.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def _last_ts(oplog):
    rows = await oplog.find({}, {"ts": 1}).sort("$natural", -1).limit(1).to_list(1)
    return rows[0]["ts"] if rows else None


def _namespaces(entry: Dict[str, Any], dbs: Tuple[str, str]) -> List[str]:
    out = []
    o = entry.get("o") or {}
    if entry.get("op") == "c" and isinstance(o, dict) and "applyOps" in o:
        for inner in o["applyOps"]:
            out.extend(_namespaces(inner, dbs))
        return out
    ns = entry.get("ns", "")
    dbname = ns.split(".", 1)[0]
    if dbname not in dbs:
        return out
    if entry.get("op") == "c":
        coll = next((o[k] for k in ("create", "drop", "createIndexes", "dropIndexes",
                                    "renameCollection", "collMod") if k in o), "$cmd")
        if isinstance(coll, str) and "." in coll:
            coll = coll.split(".", 1)[1]
        out.append("%s.%s" % (dbname, coll))
    elif entry.get("op") in ("i", "u", "d"):
        out.append(ns)
    return out


async def _writes_since(oplog, ts, dbs):
    query = {"ts": {"$gt": ts}, "op": {"$in": ["i", "u", "d", "c"]}}
    found = set()
    async for entry in oplog.find(query):
        found.update(_namespaces(entry, dbs))
    return sorted(found)


async def _snapshot(client, dbs):
    snap = {}
    for name in dbs:
        for coll in await client[name].list_collection_names():
            snap["%s.%s" % (name, coll)] = await client[name][coll].find({}).to_list(None)
    return snap


async def _restore(client, snap, namespaces):
    for ns in namespaces:
        dbname, coll = ns.split(".", 1)
        if coll == "$cmd":
            continue
        handle = client[dbname][coll]
        await handle.delete_many({})
        rows = snap.get(ns) or []
        if rows:
            await handle.insert_many([dict(r) for r in rows])


def run_harness(mongo_url: str, out_csv: Path, out_meta: Path,
                roles: Tuple[str, ...] = ROLE_KEYS, modes: Tuple[str, ...] = MODES,
                path_filter: Optional[str] = None) -> Dict[str, Any]:
    """Run the full matrix in THIS process. The caller sets MONGO_URL / DB_NAME /
    BEG_SYSTEM_DB before ``server`` is imported (see :func:`main`)."""
    op_name, sys_name = os.environ["DB_NAME"], os.environ["BEG_SYSTEM_DB"]
    assert op_name.startswith(DB_PREFIX_OP) and sys_name.startswith(DB_PREFIX_SYS)
    import server
    from fastapi.testclient import TestClient
    from motor.motor_asyncio import AsyncIOMotorClient

    app = server.app
    app.router.on_startup.clear()       # no demo seed, no reminder loop
    app.router.on_shutdown.clear()
    spec = app.openapi()
    routes = app_routes(app)
    if path_filter:
        routes = [r for r in routes if re.search(path_filter, r[2])]
    seed_mod = _load_seed()
    dbs = (op_name, sys_name)
    started = time.time()

    with TestClient(app, raise_server_exceptions=False) as tc:
        client = tc.portal.call(lambda: _make_client(mongo_url))
        oplog = client.local["oplog.rs"]

        async def _seed():
            return await seed_mod.seed(client[op_name], client[sys_name], SYNTH_PASSWORD)
        report = tc.portal.call(_seed)

        fx: Dict[str, Any] = {}
        for t in report["tenants"]:
            fx[t["key"]] = {"tenant_id": t["tenant_id"], "project_id": t["project_id"],
                            "warehouse_id": t["warehouse_id"],
                            "users": {u["key"]: u for u in t["users"]}}
        tokens: Dict[str, str] = {}
        for key in roles:
            r = tc.post("/api/auth/login", json={"email": fx["A"]["users"][key]["email"],
                                                 "password": SYNTH_PASSWORD})
            assert r.status_code == 200, (key, r.status_code, r.text[:200])
            tokens[key] = r.json()["token"]
        snap = tc.portal.call(lambda: _snapshot(client, dbs))
        values = path_values(fx)
        legacy = {key: fx["A"]["users"][key]["role"] for key in roles}

        rows: List[Dict[str, Any]] = []
        slow: List[Dict[str, Any]] = []
        for mode in modes:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            for module, method, path, _route in routes:
                url, query, body = build_request(method, path, spec, values)
                for key in roles:
                    before = tc.portal.call(lambda: _last_ts(oplog))
                    t0 = time.time()
                    kwargs: Dict[str, Any] = {"params": query,
                                              "headers": {"Authorization": "Bearer " + tokens[key]}}
                    if body is not None:
                        kwargs["json"] = body
                    try:
                        resp = tc.request(method, url, **kwargs)
                        status = resp.status_code
                    except Exception as exc:            # noqa: BLE001 — recorded, not hidden
                        status = "EXC:%s" % type(exc).__name__
                    elapsed = time.time() - t0
                    written = tc.portal.call(lambda: _writes_since(oplog, before, dbs))
                    if written:
                        tc.portal.call(lambda: _restore(client, snap, written))
                    if elapsed > 2:
                        slow.append({"route": route_key(method, path), "role": key,
                                     "mode": mode, "seconds": round(elapsed, 2)})
                    rows.append({
                        "module": module, "method": method, "path": path, "role": key,
                        "legacy_role": legacy[key], "mode": mode, "status": status,
                        "wrote": ("audit_only" if is_audit_only(written)
                                  else ("yes" if written else "no")),
                        "written": ";".join(n.split(".", 1)[0].replace(op_name, "op")
                                            .replace(sys_name, "sys") + "." + n.split(".", 1)[1]
                                            for n in written)})
        os.environ["PERMISSION_SERVICE_MODE"] = "off"

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    meta = {
        "schema": "beg.pm-01-permission-matrix/v1",
        "roles": {k: legacy[k] for k in roles},
        "role_ids": {k: fx["A"]["users"][k]["role_id"] for k in roles},
        "modes": list(modes), "routes": len(routes), "cells": len(rows),
        "caller_tenant": "A (ST-01 synthetic)",
        "path_values": {k: ("<tenant A %s>" % k) for k in values},
        "seconds": round(time.time() - started, 1), "slow_calls": slow,
        "mongo": "local replica set (oplog)", "outbound_http": "closed local port",
    }
    out_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return meta


async def _make_client(url):
    from motor.motor_asyncio import AsyncIOMotorClient
    return AsyncIOMotorClient(url, tz_aware=False)


def child_env(mongo_url: str, op_name: str, sys_name: str) -> Dict[str, str]:
    """A minimal environment: no production URL, no provider key, outbound HTTP dead."""
    env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")
           if k in os.environ}
    env.update({
        "PYTHONPATH": str(BACKEND), "MONGO_URL": mongo_url, "DB_NAME": op_name,
        "BEG_SYSTEM_DB": sys_name, "JWT_SECRET": "pm01-local-" + uuid.uuid4().hex,
        "PERMISSION_SERVICE_MODE": "off", "STRIPE_MOCK_MODE": "true",
        "HTTP_PROXY": DEAD_PROXY, "HTTPS_PROXY": DEAD_PROXY, "ALL_PROXY": DEAD_PROXY,
        "http_proxy": DEAD_PROXY, "https_proxy": DEAD_PROXY, "all_proxy": DEAD_PROXY,
        "NO_PROXY": "", "no_proxy": "", "PYTHONDONTWRITEBYTECODE": "1",
    })
    return env


def run_in_child(mongo_url: str, out_csv: Path, out_meta: Path, timeout: int = 7200,
                 extra: Optional[List[str]] = None) -> None:
    """Run the harness in a fresh interpreter on two fresh scratch databases and drop
    exactly those two databases afterwards."""
    suffix = uuid.uuid4().hex[:12]
    op_name, sys_name = DB_PREFIX_OP + suffix, DB_PREFIX_SYS + suffix
    cmd = [sys.executable, str(Path(__file__).resolve()), "--child",
           "--mongo-url", mongo_url, "--out-csv", str(out_csv), "--out-meta", str(out_meta)]
    try:
        subprocess.run(cmd + (extra or []), cwd=str(BACKEND), timeout=timeout, check=True,
                       env=child_env(mongo_url, op_name, sys_name))
    finally:
        import pymongo
        c = pymongo.MongoClient(mongo_url, serverSelectionTimeoutMS=5000)
        for name in (op_name, sys_name):
            assert name.startswith(("pm01_op_", "pm01_sys_"))
            c.drop_database(name)
        c.close()


def _check_local(url: str) -> None:
    from app.master_data import index_bootstrap as ib
    from scripts.w0_03c_master_data_uniqueness import parse_mongo_url
    scheme, hosts = parse_mongo_url(url)
    ib.check_local(hosts=hosts, scheme=scheme)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="PM-01 permission-mode matrix")
    parser.add_argument("--harness", action="store_true",
                        help="regenerate docs/evidence/PM-01 against a local MongoDB")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--mongo-url", default=os.environ.get("W0_03_REAL_MONGO_URL", ""))
    parser.add_argument("--out-csv", default=str(MATRIX_CSV))
    parser.add_argument("--out-meta", default=str(META_JSON))
    parser.add_argument("--paths", default=None, help="regex: only matching paths (debug)")
    args = parser.parse_args(argv)
    if not args.mongo_url:
        print("no --mongo-url and no W0_03_REAL_MONGO_URL", file=sys.stderr)
        return 2
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    _check_local(args.mongo_url)
    if args.child:
        run_harness(args.mongo_url, Path(args.out_csv), Path(args.out_meta),
                    path_filter=args.paths)
        return 0
    if args.harness:
        run_in_child(args.mongo_url, Path(args.out_csv), Path(args.out_meta),
                     extra=(["--paths", args.paths] if args.paths else None))
        return 0
    parser.print_help()
    return 2


# ═══════════════════════════════════════════ existing-record probes (SEC-01-C01)
# The matrix above calls every route with nonexistent ids and empty bodies, so a
# DELETE-by-id or a "sync from existing data" route answers 404/400 and never shows a
# write (audit #69, SEC-S1/S2). These helpers create REAL records first (as the seed /
# an Admin would) so a probe acts on data that exists. Used by
# tests/test_sec_01_c01_all_money_writes.py; they do not change the matrix above.
PROBE_PROJECT2 = "P2"          # a second project per tenant where nobody is a member


def probe_id(tkey: str, *parts: str) -> str:
    return "pm01probe-%s-%s" % (tkey, "-".join(parts))


async def seed_existing_records(op_db, fx: Dict[str, Any]) -> None:
    """Per tenant: a second project (P2, nobody a member), two client companies (P1 and
    P2 are linked to the first), project + company price modifiers, an Approved work
    report and an execution package on P1, an hourly rate, and one existing record in
    every SEC-01 money collection. Every row carries the tenant's own org_id."""
    now = "2026-11-06T08:00:00+00:00"
    for tkey, t in fx.items():
        org, p1 = t["tenant_id"], t["project_id"]
        p2 = probe_id(tkey, "project2")
        c1, c2 = probe_id(tkey, "company1"), probe_id(tkey, "company2")
        tech = t["users"]["technician"]["id"]
        t.update({"project2_id": p2, "company1_id": c1, "company2_id": c2})
        await op_db.projects.update_one({"id": p1, "org_id": org}, {"$set": {
            "owner_type": "company", "owner_id": c1}})
        await op_db.projects.insert_one({
            "id": p2, "org_id": org, "code": "PRB-%s-2" % tkey, "name": "Probe P2 " + tkey,
            "status": "Active", "type": "Billable", "owner_type": "company", "owner_id": c1,
            "created_at": now, "updated_at": now})
        for cid, name in ((c1, "Probe Client 1"), (c2, "Probe Client 2")):
            await op_db.companies.insert_one({"id": cid, "org_id": org, "name": name,
                                              "created_at": now})
        await op_db.price_modifiers_config.insert_many([
            {"id": probe_id(tkey, "pm-org"), "org_id": org, "scope": "org_default",
             "project_id": None, "line_id": None, "modifiers": {}, "auto_rules": {},
             "created_at": now, "updated_at": now},
            {"id": probe_id(tkey, "pm-p1"), "org_id": org, "scope": "project",
             "project_id": p1, "line_id": None, "modifiers": {"risk_percent": 5},
             "auto_rules": {}, "created_at": now, "updated_at": now}])
        await op_db.work_reports.insert_one({
            "id": probe_id(tkey, "wr1"), "org_id": org, "project_id": p1, "user_id": tech,
            "date": "2026-11-02", "status": "Approved", "total_hours": 2,
            "lines": [{"activity_name": "Probe activity", "hours": 2}], "created_at": now})
        await op_db.execution_packages.insert_one({
            "id": probe_id(tkey, "ep1"), "org_id": org, "project_id": p1,
            "activity_name": "Probe activity", "qty": 1, "labor_budget_total": 100,
            "created_at": now})
        await op_db.employee_profiles.insert_one({"org_id": org, "user_id": tech,
                                                  "hourly_rate": 20})
        await op_db.labor_entries.insert_one({
            "id": probe_id(tkey, "le1"), "org_id": org, "project_id": p1,
            "employee_id": tech, "execution_package_id": probe_id(tkey, "ep1"),
            "work_report_id": probe_id(tkey, "wr1"), "date": "2026-11-02", "hours": 2,
            "activity_name": "Probe activity", "hourly_rate": 20, "labor_cost": 40,
            "source": "work_report_sync", "created_at": now})
        await op_db.material_waste_entries.insert_one({
            "id": probe_id(tkey, "mw1"), "org_id": org, "project_id": p1,
            "material_name": "Probe", "qty": 1, "unit": "бр", "waste_type": "damaged",
            "date": "2026-11-02", "created_at": now, "updated_at": now})
        for coll in ("cash_transactions", "overhead_transactions", "bonus_payments",
                     "overhead_snapshots"):
            await op_db[coll].insert_one({"id": probe_id(tkey, coll), "org_id": org,
                                          "amount": 1, "date": "2026-11-02",
                                          "created_at": now})


async def writes_with_org(client, oplog, ts, dbs, snap) -> List[Tuple[str, Optional[str]]]:
    """(namespace, org_id of the written row) for every write since ``ts``. The org of
    an updated/deleted row is read from the row now, or from the snapshot."""
    query = {"ts": {"$gt": ts}, "op": {"$in": ["i", "u", "d", "c"]}}
    entries: List[Dict[str, Any]] = []
    async for entry in oplog.find(query):
        o = entry.get("o") or {}
        inner = o.get("applyOps") if entry.get("op") == "c" and isinstance(o, dict) else None
        entries.extend(inner if inner else [entry])
    out = set()
    for e in entries:
        ns = e.get("ns", "")
        dbname, _, coll = ns.partition(".")
        if dbname not in dbs or e.get("op") not in ("i", "u", "d"):
            for n in _namespaces(e, dbs):
                out.add((n, None))
            continue
        o = e.get("o") or {}
        _id = (e.get("o2") or {}).get("_id") if e.get("op") == "u" else o.get("_id")
        org = o.get("org_id") if e.get("op") == "i" else None
        if org is None and _id is not None:
            row = await client[dbname][coll].find_one({"_id": _id}, {"org_id": 1})
            if row is None:
                row = next((r for r in snap.get(ns, []) if r.get("_id") == _id), None)
            org = (row or {}).get("org_id")
        out.add((ns, org))
    return sorted(out, key=lambda x: (x[0], str(x[1])))


# ═════════════════════════════════════════════════════════════════════════════ tests
def load_matrix(path: Path = MATRIX_CSV) -> List[Dict[str, str]]:
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _cells(rows):
    return {(r["method"], r["path"], r["role"], r["mode"]): (r["status"], r["wrote"], r["written"])
            for r in rows}


def test_the_committed_matrix_covers_every_route_role_and_mode_served_today():
    """A new or removed endpoint fails here until the matrix and the report are redone."""
    import server
    served = {(m, p) for _mod, m, p, _r in app_routes(server.app)}
    rows = load_matrix()
    covered = {(r["method"], r["path"]) for r in rows}
    assert served == covered, {"not in matrix": sorted(served - covered)[:20],
                               "no longer served": sorted(covered - served)[:20]}
    cells = _cells(rows)
    assert len(cells) == len(rows) == len(served) * len(ROLE_KEYS) * len(MODES)
    for m, p in served:
        for role in ROLE_KEYS:
            for mode in MODES:
                assert (m, p, role, mode) in cells


def test_every_cell_has_a_status_and_a_write_verdict():
    for r in load_matrix():
        assert r["status"].isdigit() and 100 <= int(r["status"]) <= 599, r
        assert r["wrote"] in ("no", "yes", "audit_only"), r
        assert (r["wrote"] == "no") == (r["written"] == ""), r


def test_the_roles_are_the_eight_release_roles_of_the_st01_fixture():
    fixture = json.loads((STAGING / "st01_fixture.json").read_text(encoding="utf-8"))
    legacy = {r["key"]: r["legacy_role"] for r in fixture["roles"]}
    meta = json.loads(META_JSON.read_text(encoding="utf-8"))
    assert meta["roles"] == {k: legacy[k] for k in ROLE_KEYS}
    assert sorted(set(meta["roles"].values())) == sorted(
        ["Owner", "Admin", "SiteManager", "Technician", "Accountant", "Warehousekeeper",
         "Driver", "Viewer"])


def _by_mode(rows):
    out: Dict[Tuple[str, str, str], Dict[str, Dict[str, str]]] = {}
    for r in rows:
        out.setdefault((r["method"], r["path"], r["role"]), {})[r["mode"]] = r
    return out


def test_shadow_answers_like_off_and_writes_like_off_except_the_role_sync():
    """W0-02: shadow never changes a response. Its only extra write (app/permissions/sync.py,
    runs when the mode is not off) is the FLOW-002 RoleAssignment + canonical AuditEvent
    when Owner/Admin create a user."""
    status_diff, write_diff = [], {}
    for k, v in _by_mode(load_matrix()).items():
        off, sh = v["off"], v["shadow"]
        if off["status"] != sh["status"]:
            status_diff.append((k, off["status"], sh["status"]))
        if off["written"] != sh["written"]:
            write_diff[k] = set(sh["written"].split(";")) - set(off["written"].split(";"))
    assert not status_diff, status_diff[:15]
    assert set(write_diff) == {("POST", "/api/users", "owner"), ("POST", "/api/users", "admin")}
    assert all(extra == {"op.audit_events", "sys.tenant_role_assignments"}
               for extra in write_diff.values()), write_diff


# The only cells where enforce does something off does not (main @ 07da9ab + SEC-01): the
# Permission Service refuses exactly as the legacy check did and writes a denial
# AuditEvent, or (Owner/Admin creating a user) the FLOW-002 RoleAssignment and the
# canonical AuditEvent are written next to the legacy user row.
ENFORCE_EXTRA_WRITES = {
    ("POST", "/api/assets/intake/{intake_id}/approve"): "denial",
    ("POST", "/api/users"): "denial+create",
    ("PUT", "/api/users/{user_id}"): "denial",
    # SEC-01 (R14): the eight money writes refuse every non-finance role in all three
    # modes; in enforce the refusal is audited (app/permissions/money_write.py).
    ("POST", "/api/finance/cash-transactions"): "denial",
    ("POST", "/api/finance/bonus-payments"): "denial",
    ("POST", "/api/finance/overhead-transactions"): "denial",
    ("POST", "/api/overhead-snapshots"): "denial",
    ("PUT", "/api/price-modifiers/project/{project_id}"): "denial",
    ("POST", "/api/labor-entries"): "denial",
    ("POST", "/api/projects/{project_id}/material-waste"): "denial",
    ("PATCH", "/api/projects/{project_id}/client-link"): "denial",
    # SEC-01-C01 (R14/R16): the other write routes on the same resources.
    ("POST", "/api/overhead/snapshots/compute"): "denial",
    ("PUT", "/api/price-modifiers/org"): "denial",
    ("DELETE", "/api/price-modifiers/project/{project_id}"): "denial",
    ("POST", "/api/labor-entries/sync-from-work-reports"): "denial",
    ("POST", "/api/execution-packages/recompute-labor/{project_id}"): "denial",
    # SEC-01-C02 (R14; FLOW Guard FG-27, FG-30): the remaining money writes.
    ("POST", "/api/subcontractor-payments"): "denial",
    ("POST", "/api/client-acts/{act_id}/confirm"): "denial",
    ("POST", "/api/subcontractor-acts/{act_id}/confirm"): "denial",
    ("PUT", "/api/supplier-invoices/{inv_id}"): "denial",
    ("POST", "/api/worker-calendar"): "denial",
    ("PUT", "/api/worker-calendar/{entry_id}"): "denial",
    ("POST", "/api/worker-calendar/bulk"): "denial",
    ("POST", "/api/worker-calendar/sync-from-sessions"): "denial",
    ("POST", "/api/overhead-allocation/compute/{project_id}"): "denial",
    ("PUT", "/api/ocr-invoice/{intake_id}/approve"): "denial",
    ("POST", "/api/sales/commit"): "denial",
    ("POST", "/api/pricing/refresh"): "denial",
    # LIVE-OPS-01 / TASK 5C (#55, Р28): the refused migration execute writes the
    # enforce "access denied" AuditEvent — 403 in every mode, nothing else written.
    ("POST", "/api/warehouse/migration-readiness/execute"): "denial",
}


def test_enforce_answers_like_off_and_differs_only_by_audit_and_role_sync_writes():
    """Fact for Krum's decision: on main no role gains or loses a status in enforce."""
    status_diff, write_diff = [], set()
    for (m, p, role), v in _by_mode(load_matrix()).items():
        off, enf = v["off"], v["enforce"]
        if off["status"] != enf["status"]:
            status_diff.append((m, p, role, off["status"], enf["status"]))
        if off["written"] != enf["written"]:
            write_diff.add((m, p))
            if enf["status"] == "403":
                assert off["wrote"] == "no" and enf["written"] == "op.audit_events", (m, p, role)
            else:
                extra = set(enf["written"].split(";")) - set(off["written"].split(";"))
                assert extra <= {"op.audit_events", "op.audit_idempotency",
                                 "sys.tenant_role_assignments"}, (m, p, role, extra)
    assert not status_diff, status_diff[:15]
    assert write_diff == set(ENFORCE_EXTRA_WRITES), sorted(write_diff)


def _real_refusal() -> str:
    url = os.environ.get("W0_03_REAL_MONGO_URL", "")
    if not url:
        return "W0_03_REAL_MONGO_URL is not set — no disposable local MongoDB given"
    try:
        _check_local(url)
    except Exception as exc:                                  # noqa: BLE001
        return "W0_03_REAL_MONGO_URL refused: %s" % exc
    try:
        import pymongo
        c = pymongo.MongoClient(url, serverSelectionTimeoutMS=3000)
        hello = c.admin.command("hello")
        c.close()
    except Exception as exc:                                  # noqa: BLE001
        return "MongoDB not reachable: %s" % exc
    if not hello.get("setName"):
        return "PM-01 needs a replica set (the oplog measures writes): --replSet rs0"
    return ""


@pytest.mark.skipif(bool(_real_refusal()), reason=_real_refusal() or "ok")
def test_a_fresh_real_mongo_run_reproduces_the_committed_matrix(tmp_path):
    """Regression: every cell — status and wrote/not-wrote — as committed."""
    url = os.environ["W0_03_REAL_MONGO_URL"]
    out_csv, out_meta = tmp_path / "matrix.csv", tmp_path / "meta.json"
    run_in_child(url, out_csv, out_meta)
    fresh, committed = _cells(load_matrix(out_csv)), _cells(load_matrix())
    assert fresh.keys() == committed.keys()
    diff = [(k, committed[k], fresh[k]) for k in committed if committed[k] != fresh[k]]
    assert not diff, "%d cells differ, first: %s" % (len(diff), diff[:15])


if __name__ == "__main__":
    sys.exit(main())
