"""
SEC-01-C02 — the remaining money writes outside the rules (FLOW Guard FG-24, FG-26,
FG-27, FG-30, FG-31; decisions R9, R14 and R16, Krum 06.11.2026).

Package: ``docs/architecture/tasks/SEC-01-C02_FLOW_GUARD_MONEY_WRITES.md`` (branch
``claude/happy-meitner-bmcnel``). Findings: ``docs/flow-guard/DIVERGENCES.md`` (branch
``claude/flow-guard``).

Rules under test:
  finance  R14: Owner/Admin/Accountant; every other role 403, nothing written.
           FG-27 ``POST /subcontractor-payments`` and every FG-30 endpoint.
  ledger   FG-27: a subcontractor payment is accepted only WITH its row in the one
           payment ledger (``finance_payments``, the W0-05/FLOW-006 ledger). Tenant A has
           a Cash account -> 201, both rows written and linked. Tenant B has none -> 409
           PAYMENT_LEDGER_ACCOUNT_REQUIRED, nothing written (no payment outside the ledger).
  r16      FG-24: labor and waste — Owner/Admin/Accountant everywhere; SiteManager and
           Technician on a project they are MEMBERS of (P1); not on P2; Viewer/Driver
           403 even as members.
  no delete  FG-26: ``sync-from-work-reports`` never deletes a labor row. A changed
           work-report line gives a REVERSAL row + the new row; the original stays; a
           second sync writes nothing. Every call of the matrix is checked for
           delete operations in the oplog: there are none.

Every probe acts on EXISTING records: the PM-01 ``seed_existing_records`` plus the C02
records below (a subcontractor package and draft act, a draft client act, a supplier
invoice, a worker-calendar day and a finished work session, a reviewed OCR intake, a
warehouse batch, and a work report whose line differs from its synced labor row).

    PYTHONPATH=. pytest tests/test_sec_01_c02_flow_guard_money_writes.py -v --noconftest
    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \\
        PYTHONPATH=. pytest tests/test_sec_01_c02_flow_guard_money_writes.py -v --noconftest
    # regenerate the evidence:
    PYTHONPATH=. python tests/test_sec_01_c02_flow_guard_money_writes.py --harness \\
        --mongo-url 'mongodb://127.0.0.1:27019/?directConnection=true'
"""
from __future__ import annotations

import argparse
import hashlib
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
EVIDENCE = REPO / "docs" / "evidence" / "SEC-01-C02"
RESULTS_JSON = EVIDENCE / "results.json"

MODES = ("off", "shadow", "enforce")
ROLE_KEYS = ("owner", "admin", "requester", "technician", "accountant",
             "warehousekeeper", "driver", "viewer")
FINANCE = {"Owner", "Admin", "Accountant"}
FIELD_MEMBER = {"SiteManager", "Technician"}
DB_PREFIX_OP, DB_PREFIX_SYS = "c02_op_", "c02_sys_"
SYNTH_PASSWORD = "C02-Synthetic-Pass-2026!"     # synthetic users of a scratch database
AUDIT = {"audit_events", "audit_logs", "audit_chain_heads", "audit_chain", "audit_idempotency"}
TEAM = (("requester", "SiteManager"), ("technician", "Technician"),
        ("viewer", "Viewer"), ("driver", "Viewer"))
CROSS_ROLES = ("admin", "accountant", "requester", "technician", "viewer")
SALE_BATCH_QTY = 10.0
WORK_DATE = "2026-11-03"


# ═══════════════════════════════════════════════════════════════════════ the probes
# (key, method, path, action, rule, collection written on success, success status, kind)
# kind: "project" -> called on P1 and P2; "record" -> also called by tenant B on A's id.
PROBES = (
    ("subpay", "POST", "/api/subcontractor-payments", "finance.subcontractor_payment.create",
     "ledger", "finance_payments", 201, "record"),
    ("subpay_unknown_account", "POST", "/api/subcontractor-payments",
     "finance.subcontractor_payment.create", "finance_404", None, 404, None),
    ("client_act_confirm", "POST", "/api/client-acts/{client_act}/confirm",
     "revenue.client_act_confirm.execute", "finance", "client_acts", 200, "record"),
    ("sub_act_confirm", "POST", "/api/subcontractor-acts/{sub_act}/confirm",
     "subcontract.act_confirm.execute", "finance", "subcontractor_acts", 200, "record"),
    ("supinv_put", "PUT", "/api/supplier-invoices/{sup_inv}",
     "procurement.supplier_invoice.update", "finance", "supplier_invoices", 200, "record"),
    ("wcal_create", "POST", "/api/worker-calendar", "overhead.worker_calendar.create",
     "finance", "worker_calendar", 201, None),
    ("wcal_put", "PUT", "/api/worker-calendar/{wcal}", "overhead.worker_calendar.update",
     "finance", "worker_calendar", 200, "record"),
    ("wcal_bulk", "POST", "/api/worker-calendar/bulk", "overhead.worker_calendar_bulk.execute",
     "finance", "worker_calendar", 201, None),
    ("wcal_sync", "POST", "/api/worker-calendar/sync-from-sessions?date=" + WORK_DATE,
     "overhead.worker_calendar_sync.execute", "finance", "worker_calendar", 200, None),
    ("oh_alloc", "POST", "/api/overhead-allocation/compute/{project_id}",
     "finance.overhead_allocation.execute", "finance", "project_overhead_alloc", 200, None),
    ("ocr_approve", "PUT", "/api/ocr-invoice/{ocr}/approve", "ocr_invoice.intake.approve",
     "finance", "pending_expenses", 200, "record"),
    ("sales_commit", "POST", "/api/sales/commit", "sales.sale_commit.execute",
     "finance", "sales", 201, None),
    ("pricing_refresh", "POST", "/api/pricing/refresh?name=C02%20probe",
     "pricing.material_price_refresh.execute", "finance_reached", None, None, None),
    ("labor_sync", "POST", "/api/labor-entries/sync-from-work-reports",
     "labor.work_report_sync.execute", "r16", "labor_entries", 200, "project"),
    ("labor_create", "POST", "/api/labor-entries", "labor.entry.create",
     "r16", "labor_entries", 201, "project"),
    ("waste_create", "POST", "/api/projects/{project_id}/material-waste",
     "material_waste.entry.create", "r16", "material_waste_entries", 201, "project"),
)
PROBE = {p[0]: p for p in PROBES}
PROJECT_PROBES = {p[0] for p in PROBES if p[7] == "project"}
RECORD_PROBES = {p[0] for p in PROBES if p[7] == "record"}
# labor_sync on P2, or B on A's project (no work report in the caller's tenant):
# allowed, nothing to sync.
WRITES_ONLY_WITH_SOURCE_DATA = {"labor_sync"}


def rid(tkey: str, name: str) -> str:
    return "pm01probe-%s-c02-%s" % (tkey, name)


def sale_token(tkey: str) -> str:
    return hashlib.md5(("%s:%s" % (rid(tkey, "batch1"), SALE_BATCH_QTY)).encode()).hexdigest()


async def seed_c02_records(op_db, fx: Dict[str, Any]) -> None:
    """The C02 existing records, per tenant, each with the tenant's own org_id. Tenant B
    gets NO financial account (FG-27: its payment must be refused, not written)."""
    now = "2026-11-06T08:00:00+00:00"
    # Collections first written by a probe are created here, so a probe's first call
    # does not show the (org-less) collection-create entry of the oplog.
    existing = set(await op_db.list_collection_names())
    for name in ("finance_payments", "subcontractor_payments", "audit_logs",
                 "project_overhead_alloc", "pending_expenses", "sales", "material_prices"):
        if name not in existing:
            await op_db.create_collection(name)
    for tkey, t in fx.items():
        org, p1 = t["tenant_id"], t["project_id"]
        tech = t["users"]["technician"]["id"]
        if tkey == "A":
            await op_db.financial_accounts.insert_one({
                "id": rid(tkey, "cash"), "org_id": org, "name": "Каса", "account_type": "Cash",
                "currency": "EUR", "created_at": now})
        await op_db.subcontractors.insert_one({"id": rid(tkey, "sub"), "org_id": org,
                                               "name": "Probe Sub", "created_at": now})
        await op_db.subcontractor_packages.insert_one({
            "id": rid(tkey, "pkg"), "org_id": org, "project_id": p1,
            "subcontractor_id": rid(tkey, "sub"), "subcontractor_name": "Probe Sub",
            "title": "Probe package", "currency": "EUR", "status": "confirmed",
            "certified_total": 100, "paid_total": 0, "created_at": now})
        await op_db.subcontractor_acts.insert_one({
            "id": rid(tkey, "sact"), "org_id": org, "project_id": p1,
            "package_id": rid(tkey, "pkg"), "status": "draft", "lines": [],
            "created_at": now})
        await op_db.client_acts.insert_one({
            "id": rid(tkey, "cact"), "org_id": org, "project_id": p1, "act_number": "PRB-1",
            "status": "Draft", "lines": [{"activity_name": "Probe", "qty": 1,
                                          "unit_price": 10, "line_total": 10}],
            "subtotal": 10, "total": 10, "created_at": now})
        await op_db.supplier_invoices.insert_one({
            "id": rid(tkey, "sinv"), "org_id": org, "project_id": p1, "status": "uploaded",
            "invoice_number": "PRB-INV", "lines": [], "subtotal": 0, "total": 0,
            "created_at": now})
        await op_db.worker_calendar.insert_one({
            "id": rid(tkey, "wcal"), "org_id": org, "worker_id": tech, "date": "2026-11-02",
            "status": "working", "hours": 8, "source": "manual", "created_at": now})
        await op_db.work_sessions.insert_one({
            "id": rid(tkey, "ws"), "org_id": org, "worker_id": tech, "site_id": p1,
            "started_at": WORK_DATE + "T07:00:00", "ended_at": WORK_DATE + "T15:00:00",
            "duration_hours": 8, "created_at": now})
        await op_db.ocr_invoice_intake.insert_one({
            "id": rid(tkey, "ocr"), "org_id": org, "project_id": p1, "status": "reviewed",
            "reviewed_data": {"supplier_name": "Probe", "invoice_number": "1",
                              "total_amount": 5, "currency": "EUR"},
            "created_by": tech, "created_at": now})
        await op_db.warehouse_batches.insert_one({
            "id": rid(tkey, "batch1"), "org_id": org, "item_id": rid(tkey, "item"),
            "warehouse_id": rid(tkey, "wh"), "batch_number": "B1", "status": "active",
            "remaining_qty": SALE_BATCH_QTY, "unit_cost": 1.0,
            "received_at": "2026-11-01T08:00:00", "created_at": now})
        # FG-26: a work report whose line (1 h) differs from the row synced earlier (3 h).
        await op_db.work_reports.insert_one({
            "id": rid(tkey, "wr2"), "org_id": org, "project_id": p1, "user_id": tech,
            "date": WORK_DATE, "status": "Approved", "total_hours": 1,
            "lines": [{"activity_name": "Probe activity", "hours": 1}], "created_at": now})
        await op_db.labor_entries.insert_one({
            "id": rid(tkey, "le2"), "org_id": org, "project_id": p1, "employee_id": tech,
            "execution_package_id": "pm01probe-%s-ep1" % tkey,
            "work_report_id": rid(tkey, "wr2"), "date": WORK_DATE, "hours": 3,
            "activity_name": "Probe activity", "hourly_rate": 20, "labor_cost": 60,
            "source": "work_report_sync", "created_at": now})


def ids_of(tkey: str) -> Dict[str, str]:
    return {"client_act": rid(tkey, "cact"), "sub_act": rid(tkey, "sact"),
            "sup_inv": rid(tkey, "sinv"), "wcal": rid(tkey, "wcal"), "ocr": rid(tkey, "ocr")}


def body_for(key: str, t: Dict[str, Any], rec_tkey: str, project_id: Optional[str]):
    tech = t["users"]["technician"]["id"]
    if key == "subpay":
        return {"package_id": rid(rec_tkey, "pkg"), "amount": 10}
    if key == "subpay_unknown_account":
        return {"package_id": rid(rec_tkey, "pkg"), "amount": 10,
                "account_id": rid(rec_tkey, "no-such-account")}
    if key in ("client_act_confirm", "sub_act_confirm", "ocr_approve", "wcal_sync",
               "oh_alloc", "pricing_refresh"):
        return {"period_key": "2026-11"} if key == "oh_alloc" else None
    if key == "supinv_put":
        return {"notes": "C02"}
    if key in ("wcal_create", "wcal_put"):
        return {"worker_id": tech, "date": "2026-11-04", "status": "working", "hours": 8}
    if key == "wcal_bulk":
        return {"entries": [{"worker_id": tech, "date": "2026-11-05", "status": "working"}]}
    if key == "sales_commit":
        return {"item_id": rid(rec_tkey, "item"), "warehouse_id": rid(rec_tkey, "wh"),
                "quantity": 1, "unit_sale_price": 2.0, "currency": "EUR",
                "snapshot_token": sale_token(rec_tkey)}
    if key in ("labor_sync", "labor_create"):
        return {"project_id": project_id, "hours": 1, "activity_name": "C02"}
    if key == "waste_create":
        return {"material_name": "C02", "qty": 1}
    raise AssertionError(key)


# ═════════════════════════════════════════════════════════════════ expected outcome
def expected(key: str, legacy_role: str, tenant: str, target: Optional[str]) -> Dict[str, Any]:
    """{"status": int|None, "writes": bool|None}. None = any non-403 status / either.

    ``target``: None, "P1" (members: SiteManager, Technician, Viewer, Driver), "P2"
    (no members), "XA" (tenant B's caller on tenant A's record or project).
    """
    _k, _m, _p, _a, rule, coll, ok, _kind = PROBE[key]
    deny = {"status": 403, "writes": False}
    if rule == "r16":
        allowed = legacy_role in FINANCE or (legacy_role in FIELD_MEMBER and target == "P1")
        if not allowed:
            return deny
        writes = not (key in WRITES_ONLY_WITH_SOURCE_DATA and target in ("P2", "XA"))
        return {"status": ok, "writes": writes}
    if legacy_role not in FINANCE:
        return deny
    if target == "XA":
        return {"status": 404, "writes": False}          # looked up in the caller's tenant
    if rule == "ledger":
        if tenant == "B":                                 # B has no account: no ledger row
            return {"status": 409, "writes": False}
        return {"status": ok, "writes": True}
    if rule == "finance_404":
        return {"status": 404, "writes": False}
    if rule == "finance_reached":
        return {"status": None, "writes": None}
    return {"status": ok, "writes": True}


def _pm01():
    spec = importlib.util.spec_from_file_location(
        "c02_pm01_helpers", Path(__file__).resolve().parent / "test_pm_01_permission_matrix.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def deletes_since(oplog, ts, op_name: str) -> List[str]:
    """Namespaces of the operational database with a DELETE since ``ts``."""
    out = set()
    async for entry in oplog.find({"ts": {"$gt": ts}, "op": {"$in": ["d", "c"]}}):
        o = entry.get("o") or {}
        inner = o.get("applyOps") if entry.get("op") == "c" and isinstance(o, dict) else None
        for e in (inner or [entry]):
            if e.get("op") == "d" and e.get("ns", "").startswith(op_name + "."):
                out.add("op." + e["ns"].split(".", 1)[1])
    return sorted(out)


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
        op_db = client[op_name]
        report = tc.portal.call(lambda: seed_mod.seed(client[op_name], client[sys_name],
                                                      SYNTH_PASSWORD))
        fx: Dict[str, Any] = {}
        for t in report["tenants"]:
            fx[t["key"]] = {"tenant_id": t["tenant_id"], "project_id": t["project_id"],
                            "users": {u["key"]: u for u in t["users"]}}
        tc.portal.call(lambda: pm.seed_existing_records(op_db, fx))
        tc.portal.call(lambda: seed_c02_records(op_db, fx))
        tokens: Dict[tuple, str] = {}
        for tkey in ("A", "B"):
            for key in ROLE_KEYS:
                r = tc.post("/api/auth/login", json={
                    "email": fx[tkey]["users"][key]["email"], "password": SYNTH_PASSWORD})
                assert r.status_code == 200, (tkey, key, r.status_code, r.text[:200])
                tokens[(tkey, key)] = r.json()["token"]
        # P1's team through the real API in ENFORCE: project_team + mirrored assignments.
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
            if target == "XA":
                return fx["A"]["project_id"]
            if target == "P2":
                return fx[tkey]["project2_id"]
            return fx[tkey]["project_id"]

        def call(mode, tkey, role, key, target):
            _k, method, path, *_rest = PROBE[key]
            rec_tkey = "A" if target == "XA" else tkey
            pid = project_of(tkey, target)
            url = path.replace("{project_id}", pid)
            for name, value in ids_of(rec_tkey).items():
                url = url.replace("{%s}" % name, value)
            body = body_for(key, fx[tkey], rec_tkey, pid)
            before = tc.portal.call(lambda: pm._last_ts(oplog))
            kwargs: Dict[str, Any] = {
                "headers": {"Authorization": "Bearer " + tokens[(tkey, role)]}}
            if body is not None:
                kwargs["json"] = body
            resp = tc.request(method, url, **kwargs)
            written = tc.portal.call(lambda: pm.writes_with_org(client, oplog, before, dbs,
                                                                 snap))
            deleted = tc.portal.call(lambda: deletes_since(oplog, before, op_name))
            if written:
                tc.portal.call(lambda: pm._restore(client, snap, sorted({n for n, _ in written})))
            orgs = {"A" if o == fx["A"]["tenant_id"] else "B" if o == fx["B"]["tenant_id"]
                    else (None if o is None else "other") for n, o in written
                    if n.split(".", 1)[1] not in AUDIT}
            return {"mode": mode, "tenant": tkey, "role": role,
                    "legacy_role": fx[tkey]["users"][role]["role"], "probe": key,
                    "method": method, "path": path, "target": target,
                    "status": resp.status_code,
                    "error_code": ((resp.json() or {}).get("detail") or {}).get("error_code")
                    if resp.headers.get("content-type", "").startswith("application/json")
                    and isinstance((resp.json() or {}).get("detail"), dict) else None,
                    "written": sorted({short(n) for n, _o in written}),
                    "written_orgs": sorted(str(o) for o in orgs),
                    "deleted": deleted}

        rows: List[Dict[str, Any]] = []
        for mode in MODES:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            for tkey in ("A", "B"):
                for key, *_ in PROBES:
                    targets = ("P1", "P2") if key in PROJECT_PROBES else (None,)
                    for target in targets:
                        for role in ROLE_KEYS:
                            rows.append(call(mode, tkey, role, key, target))
            for key in sorted(RECORD_PROBES | PROJECT_PROBES):
                for role in CROSS_ROLES:
                    rows.append(call(mode, "B", role, key, "XA"))

        # ── FG-26 sequence (off): two syncs by A's SiteManager member on P1; FG-27 links.
        os.environ["PERMISSION_SERVICE_MODE"] = "off"
        seq: Dict[str, Any] = {}
        hdr = {"Authorization": "Bearer " + tokens[("A", "requester")]}
        before = tc.portal.call(lambda: pm._last_ts(oplog))
        r1 = tc.post("/api/labor-entries/sync-from-work-reports",
                     json={"project_id": fx["A"]["project_id"]}, headers=hdr)
        mid = tc.portal.call(lambda: pm._last_ts(oplog))
        r2 = tc.post("/api/labor-entries/sync-from-work-reports",
                     json={"project_id": fx["A"]["project_id"]}, headers=hdr)
        after_writes = tc.portal.call(lambda: pm.writes_with_org(client, oplog, mid, dbs, snap))
        rows_now = tc.portal.call(lambda: op_db.labor_entries.find(
            {"org_id": fx["A"]["tenant_id"], "project_id": fx["A"]["project_id"]},
            {"_id": 0}).to_list(100))
        seq["labor_sync"] = {
            "first": {"status": r1.status_code, "body": r1.json()},
            "second": {"status": r2.status_code, "body": r2.json(),
                       "written": sorted({short(n) for n, _ in after_writes})},
            "deleted": tc.portal.call(lambda: deletes_since(oplog, before, op_name)),
            "rows": sorted(({"id": x["id"] if x["id"].startswith("pm01probe") else "new",
                             "hours": x["hours"], "labor_cost": x.get("labor_cost"),
                             "entry_kind": x.get("entry_kind"),
                             "reverses_seed": (x.get("reverses_entry_id") or "")
                             .startswith("pm01probe"),
                             "reversed": bool(x.get("reversed_by_entry_id"))}
                            for x in rows_now), key=lambda d: (d["id"], d["hours"])),
            "sum_hours": round(sum(float(x["hours"]) for x in rows_now), 4),
            "sum_cost": round(sum(float(x["labor_cost"]) for x in rows_now
                                  if x.get("labor_cost") is not None), 2),
        }
        tc.portal.call(lambda: pm._restore(client, snap, [op_name + ".labor_entries"]))
        before = tc.portal.call(lambda: pm._last_ts(oplog))
        rp = tc.post("/api/subcontractor-payments", json=body_for("subpay", fx["A"], "A", None),
                     headers={"Authorization": "Bearer " + tokens[("A", "accountant")]})
        pay = tc.portal.call(lambda: op_db.subcontractor_payments.find_one(
            {"id": rp.json().get("id")}, {"_id": 0}))
        led = tc.portal.call(lambda: op_db.finance_payments.find_one(
            {"id": (pay or {}).get("finance_payment_id")}, {"_id": 0}))
        seq["subpay_link"] = {
            "status": rp.status_code,
            "ledger_row": bool(led), "ledger_direction": (led or {}).get("direction"),
            "ledger_amount": (led or {}).get("amount"),
            "ledger_points_back": (led or {}).get("subcontractor_payment_id") == (pay or {}).get("id"),
            "audit_logs": tc.portal.call(lambda: op_db.audit_logs.count_documents(
                {"entity_id": (led or {}).get("id")})),
        }
        written = tc.portal.call(lambda: pm.writes_with_org(client, oplog, before, dbs, snap))
        tc.portal.call(lambda: pm._restore(client, snap, sorted({n for n, _ in written})))

    result = {
        "schema": "beg.sec-01-c02-flow-guard-money-writes/v1",
        "fixture": "ST-01 synthetic tenants A and B + PM-01 and C02 existing-record probes",
        "roles": {k: fx["A"]["users"][k]["role"] for k in ROLE_KEYS},
        "team_of_P1": [list(t) for t in TEAM],
        "modes": list(MODES), "probes": [list(p[:5]) for p in PROBES],
        "mongo": "local replica set (oplog)", "outbound_http": "closed local port",
        "seconds": round(time.time() - started, 1), "rows": rows, "sequences": seq,
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
    env["JWT_SECRET"] = "c02-local-" + uuid.uuid4().hex
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
    parser = argparse.ArgumentParser(description="SEC-01-C02 money-write evidence")
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
        exp = expected(r["probe"], r["legacy_role"], r["tenant"], r["target"])
        business = [ns for ns in r["written"] if ns.split(".", 1)[1] not in AUDIT]
        assert r["deleted"] == [], r                       # FG-26: no delete, ever
        if exp["status"] is None:
            assert r["status"] != 403, r                   # reached the handler
        else:
            assert r["status"] == exp["status"], (exp, r)
        if r["status"] == 403:
            assert business == [], r
            if r["mode"] == "enforce":
                assert set(r["written"]) <= {"op.audit_events"}, r
            else:
                assert r["written"] == [], r
        elif exp["writes"]:
            coll = "op." + PROBE[r["probe"]][5]
            assert coll in r["written"], r
            assert all(ns.startswith("op.") for ns in r["written"]), r
            assert r["written_orgs"] == [r["tenant"]], r
            if r["probe"] == "subpay":                     # FG-27: both rows, never one
                assert {"op.finance_payments", "op.subcontractor_payments"} <= set(business), r
        elif exp["writes"] is False:
            assert business == [], r
            if r["probe"] == "subpay" and r["status"] == 409:
                assert r["error_code"] == "PAYMENT_LEDGER_ACCOUNT_REQUIRED", r
        else:
            assert r["written_orgs"] in ([], [r["tenant"]]), r
        by_cell.setdefault((r["tenant"], r["role"], r["probe"], r["target"]), {})[r["mode"]] = r
    for cell, modes in by_cell.items():                   # same answer in every mode
        assert set(modes) == set(MODES), cell
        assert len({m["status"] for m in modes.values()}) == 1, (cell, modes)
        assert len({tuple(m["written"]) for m in modes.values()
                    if m["mode"] != "enforce"}) == 1, (cell, modes)
    assert {c[2] for c in by_cell} == set(PROBE)
    own = [c for c in by_cell if c[3] != "XA"]
    assert len(own) == 2 * len(ROLE_KEYS) * sum(
        2 if k in PROJECT_PROBES else 1 for k in PROBE)
    assert len([c for c in by_cell if c[3] == "XA"]) == \
        len(RECORD_PROBES | PROJECT_PROBES) * len(CROSS_ROLES)


def check_sequences(seq: Dict[str, Any]) -> None:
    ls = seq["labor_sync"]
    assert ls["first"]["status"] == 200 and ls["second"]["status"] == 200
    # wr1 (unchanged, 2 h) kept; wr2 changed (3 h synced -> 1 h now): reversal + new row.
    assert ls["first"]["body"]["synced"] == 1 and ls["first"]["body"]["reversed"] == 1
    assert ls["first"]["body"]["unchanged"] == 1
    assert ls["second"]["body"] == {**ls["second"]["body"], "synced": 0, "reversed": 0,
                                    "unchanged": 2}
    assert ls["second"]["written"] == []                  # idempotent by content
    assert ls["deleted"] == []
    seed_rows = {r["id"]: r for r in ls["rows"] if r["id"] != "new"}
    assert set(seed_rows) == {"pm01probe-A-le1", "pm01probe-A-c02-le2"}   # both still there
    assert seed_rows["pm01probe-A-c02-le2"]["reversed"] is True
    assert seed_rows["pm01probe-A-le1"]["reversed"] is False
    new = [r for r in ls["rows"] if r["id"] == "new"]
    assert sorted((r["entry_kind"] or "", r["hours"]) for r in new) == \
        [("", 1.0), ("reversal", -3.0)]
    assert [r["reverses_seed"] for r in new if r["entry_kind"] == "reversal"] == [True]
    assert ls["sum_hours"] == 3.0 and ls["sum_cost"] == 60.0   # 2 h + 1 h at 20 EUR/h
    sp = seq["subpay_link"]
    assert sp == {"status": 201, "ledger_row": True, "ledger_direction": "Outflow",
                  "ledger_amount": 10.0, "ledger_points_back": True, "audit_logs": 1}


# ═════════════════════════════════════════════════════════════════════ DB-free tests
def _routes():
    os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:1")
    os.environ.setdefault("DB_NAME", "c02_dbfree")
    os.environ.setdefault("JWT_SECRET", "c02-dbfree")
    import server
    from fastapi.routing import APIRoute
    return [r for r in server.app.routes if isinstance(r, APIRoute)]


# The routes C02 guards (R14), each with the guard as its FIRST dependency.
C02_GUARDED_ROUTES = {
    ("POST", "/api/subcontractor-payments"): "finance.subcontractor_payment.create",
    ("POST", "/api/client-acts/{act_id}/confirm"): "revenue.client_act_confirm.execute",
    ("POST", "/api/subcontractor-acts/{act_id}/confirm"): "subcontract.act_confirm.execute",
    ("PUT", "/api/supplier-invoices/{inv_id}"): "procurement.supplier_invoice.update",
    ("POST", "/api/worker-calendar"): "overhead.worker_calendar.create",
    ("PUT", "/api/worker-calendar/{entry_id}"): "overhead.worker_calendar.update",
    ("POST", "/api/worker-calendar/bulk"): "overhead.worker_calendar_bulk.execute",
    ("POST", "/api/worker-calendar/sync-from-sessions"): "overhead.worker_calendar_sync.execute",
    ("POST", "/api/overhead-allocation/compute/{project_id}"):
        "finance.overhead_allocation.execute",
    ("PUT", "/api/ocr-invoice/{intake_id}/approve"): "ocr_invoice.intake.approve",
    ("POST", "/api/sales/commit"): "sales.sale_commit.execute",
    ("POST", "/api/pricing/refresh"): "pricing.material_price_refresh.execute",
}


def test_every_c02_route_carries_its_finance_action_first():
    seen = set()
    for route in _routes():
        for method in route.methods:
            key = (method, route.path)
            if key in C02_GUARDED_ROUTES:
                first = route.dependant.dependencies[0].call
                assert getattr(first, "sec01_action", None) == C02_GUARDED_ROUTES[key], key
                assert getattr(first, "sec01_rule", None) is None, key     # R14, not R16
                seen.add(key)
    assert seen == set(C02_GUARDED_ROUTES)


def test_the_catalog_gives_the_c02_actions_to_the_finance_roles_only():
    from app.permissions.catalog import (ACTIONS, PERMISSION_MATRIX, MONEY_WRITE_ACTIONS,
                                         MONEY_WRITE_ACTIONS_C02, is_significant_action)
    actions = set(C02_GUARDED_ROUTES.values())
    assert actions == MONEY_WRITE_ACTIONS_C02
    assert actions <= MONEY_WRITE_ACTIONS and actions <= ACTIONS
    assert all(is_significant_action(a) for a in actions)       # denials are audited
    holders = {rid_ for rid_, acts in PERMISSION_MATRIX.items() if acts & actions}
    assert holders == {"owner", "admin", "accountant"}


def test_no_hard_delete_left_in_the_labor_sync():
    """FG-26: the sync handler holds no delete call; the rows are reversed instead."""
    import ast
    import inspect
    from app.routes import labor_smr
    src = inspect.getsource(labor_smr.sync_labor_entries_from_work_reports)
    calls = {n.func.attr for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not calls & {"delete_one", "delete_many", "find_one_and_delete", "drop", "remove"}
    assert "insert_one" in calls


def test_the_subcontractor_payment_writes_the_ledger_or_nothing():
    """FG-27: the only write paths of the handler are the ledger row + its allocation
    record; no branch writes subcontractor_payments without finance_payments."""
    import inspect
    from app.routes import subcontractors
    src = inspect.getsource(subcontractors.create_subcontractor_payment)
    assert src.index("PAYMENT_LEDGER_ACCOUNT_REQUIRED") < src.index(".insert_one(")
    assert src.index("finance_payments.insert_one") < src.index("subcontractor_payments.insert_one")
    assert "if account_id:" not in src


def test_the_rule_table_itself():
    assert expected("labor_sync", "SiteManager", "A", "P1") == {"status": 200, "writes": True}
    assert expected("labor_sync", "Technician", "A", "P2")["status"] == 403
    assert expected("labor_sync", "Viewer", "A", "P1")["status"] == 403
    assert expected("labor_sync", "Accountant", "A", "P2") == {"status": 200, "writes": False}
    assert expected("labor_create", "Technician", "A", "P1")["status"] == 201   # FG-24
    assert expected("waste_create", "SiteManager", "A", "P1")["status"] == 201  # FG-24
    assert expected("subpay", "Viewer", "A", None)["status"] == 403            # FG-27
    assert expected("subpay", "Accountant", "A", None) == {"status": 201, "writes": True}
    assert expected("subpay", "Accountant", "B", None) == {"status": 409, "writes": False}
    assert expected("subpay", "Admin", "B", "XA")["status"] == 404
    assert expected("wcal_bulk", "SiteManager", "A", None)["status"] == 403


def test_the_committed_evidence_satisfies_the_package():
    data = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    assert data["modes"] == list(MODES)
    assert sorted(set(data["roles"].values())) == sorted(
        ["Owner", "Admin", "SiteManager", "Technician", "Accountant", "Warehousekeeper",
         "Driver", "Viewer"])
    check_rows(data["rows"])
    check_sequences(data["sequences"])


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
    data = json.loads(out.read_text(encoding="utf-8"))
    check_rows(data["rows"])
    check_sequences(data["sequences"])
    committed = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))["rows"]
    key = lambda r: (r["mode"], r["tenant"], r["role"], r["probe"], r["target"])
    assert {key(r): (r["status"], r["written"]) for r in data["rows"]} == \
        {key(r): (r["status"], r["written"]) for r in committed}


if __name__ == "__main__":
    sys.exit(main())
