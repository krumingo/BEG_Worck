"""
SEC-01-C03 — the amount and the repeated request of a money write (audit of PR #69).

Package: ``docs/architecture/tasks/SEC-01-C03_PAYMENT_AMOUNT_IDEMPOTENCY.md`` (branch
``claude/happy-meitner-bmcnel``): CLAUDE.md §14 (validation/DQ + idempotency key on every
consequential write), FLOW-006, R14, R16. Code: ``app/permissions/money_input.py``.

Rules under test, for the seven money POSTs of PR #69 (cash, bonus, overhead
transactions, overhead snapshots, subcontractor payments, labor entries, material waste):
  amount     "nan", "inf", "-inf", "1e309", "", "abc", -1, 0 or a missing field -> 422 and
             NOTHING written (oplog); a valid amount -> 201.
  key        the same ``Idempotency-Key`` + the same body -> 201 with the ORIGINAL body,
             no new business row; the same key + a different body -> 409, nothing
             written; NO key -> 428 IDEMPOTENCY_KEY_REQUIRED, nothing written
             (R29, Krum 06.11.2026 — addendum A).
  SEC-R1     confirmed on this head: an expired (P2, Technician) or future (P2,
             SiteManager) membership writes no labor/waste (403, nothing written); an
             active membership with no dates (P1) -> 201.
All in off, shadow and enforce, on a real MongoDB replica set (ST-01 tenant A).

    PYTHONPATH=. pytest tests/test_sec_01_c03_payment_amount_idempotency.py -v --noconftest
    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \\
        PYTHONPATH=. pytest tests/test_sec_01_c03_payment_amount_idempotency.py -v --noconftest
    # regenerate the evidence:
    PYTHONPATH=. python tests/test_sec_01_c03_payment_amount_idempotency.py --harness \\
        --mongo-url 'mongodb://127.0.0.1:27019/?directConnection=true'
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import inspect
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
EVIDENCE = REPO / "docs" / "evidence" / "SEC-01-C03"
RESULTS_JSON = EVIDENCE / "results.json"

MODES = ("off", "shadow", "enforce")
DB_PREFIX_OP, DB_PREFIX_SYS = "c03_op_", "c03_sys_"
SYNTH_PASSWORD = "C03-Synthetic-Pass-2026!"     # synthetic users of a scratch database
AUDIT = {"audit_events", "audit_logs", "audit_chain_heads", "audit_chain", "audit_idempotency"}
# SEC-01-C03-B (FG-47): a numeric STRING and a boolean are refused too (the rule of #70).
INVALID = ("nan", "inf", "-inf", "1e309", "", "abc", "10", True, [10], -1, 0, "<missing>")

# (key, path, amount field, business collections the valid call writes, handler)
ENDPOINTS = (
    ("cash", "/api/finance/cash-transactions", "amount", ("cash_transactions",),
     ("reports", "create_cash_transaction")),
    ("bonus", "/api/finance/bonus-payments", "amount", ("bonus_payments",),
     ("reports", "create_bonus_payment")),
    ("ohtx", "/api/finance/overhead-transactions", "amount", ("overhead_transactions",),
     ("reports", "create_overhead_transaction")),
    ("ohsnap", "/api/overhead-snapshots", "amount", ("overhead_snapshots",),
     ("full_cost", "create_overhead_snapshot")),
    ("subpay", "/api/subcontractor-payments", "amount",
     ("finance_payments", "subcontractor_payments", "subcontractor_packages"),
     ("subcontractors", "create_subcontractor_payment")),
    ("subpay_vat", "/api/subcontractor-payments", "vat_amount",
     ("finance_payments", "subcontractor_payments", "subcontractor_packages"),
     ("subcontractors", "create_subcontractor_payment")),
    ("labor", "/api/labor-entries", "hours", ("labor_entries",),
     ("labor_smr", "create_labor_entry")),
    ("waste", "/api/projects/{project_id}/material-waste", "qty", ("material_waste_entries",),
     ("material_waste", "create_waste_entry")),
)
EP = {e[0]: e for e in ENDPOINTS}


def COMPUTED_ROUTES(fx_a: Dict[str, Any]):
    """F-69-02: the money POSTs that compute rather than create (R29 applies to them too)."""
    return (
        ("labor_sync", "/api/labor-entries/sync-from-work-reports",
         {"project_id": fx_a["project_id"]}),
        ("recompute_labor", "/api/execution-packages/recompute-labor/%s" % fx_a["project_id"],
         None),
        ("overhead_compute", "/api/overhead/snapshots/compute",
         {"period_start": "2026-11-01", "period_end": "2026-11-07", "method": "Hours"}),
    )


def OTHER_BODY(key: str, body: Optional[Dict[str, Any]]):
    """The same route with different business inputs (same key -> 409)."""
    if key == "labor_sync":
        return {"project_id": body["project_id"] + "-other"}
    if key == "overhead_compute":
        return {**body, "method": "PersonDays"}
    return None


def body_for(key: str, fx_a: Dict[str, Any], c02) -> Dict[str, Any]:
    if key == "cash":
        return {"type": "expense", "amount": 10, "category": "c03", "description": "C03"}
    if key == "bonus":
        return {"amount": 10, "user_id": fx_a["users"]["viewer"]["id"], "description": "C03"}
    if key == "ohtx":
        return {"amount": 10, "category": "c03", "description": "C03"}
    if key == "ohsnap":
        return {"category_code": "general", "amount": 10, "period_key": "2026-11"}
    if key == "subpay":
        return c02.body_for("subpay", fx_a, "A", None)
    if key == "subpay_vat":
        return {**c02.body_for("subpay", fx_a, "A", None), "vat_amount": 2}
    if key == "labor":
        return {"project_id": fx_a["project_id"], "hours": 1, "activity_name": "C03"}
    if key == "waste":
        return {"material_name": "C03", "qty": 1}
    raise AssertionError(key)


def with_value(body: Dict[str, Any], field: str, value: Any) -> Dict[str, Any]:
    out = dict(body)
    if value == "<missing>":
        out.pop(field, None)
    else:
        out[field] = value
    return out


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parent / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _pm01():
    return _load("c03_pm01_helpers", "test_pm_01_permission_matrix.py")


def _c02():
    return _load("c03_c02_helpers", "test_sec_01_c02_flow_guard_money_writes.py")


# ═══════════════════════════════════════════════════════════════════════ the harness
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
        tc.portal.call(lambda: c02.seed_c02_records(op_db, fx))
        for name in ("cash_transactions", "bonus_payments", "overhead_transactions",
                     "overhead_snapshots", "material_waste_entries", "labor_entries",
                     "audit_idempotency"):
            if name not in tc.portal.call(lambda: op_db.list_collection_names()):
                tc.portal.call(lambda: op_db.create_collection(name))
        tokens: Dict[str, str] = {}
        for key in ("admin", "accountant", "technician", "requester"):
            r = tc.post("/api/auth/login", json={
                "email": fx["A"]["users"][key]["email"], "password": SYNTH_PASSWORD})
            assert r.status_code == 200, (key, r.status_code, r.text[:200])
            tokens[key] = r.json()["token"]
        # SEC-R1 fixture, exactly as C02: P1 team without dates, P2 expired/future,
        # all through the real API in ENFORCE (project_team + the mirrored assignments).
        os.environ["PERMISSION_SERVICE_MODE"] = "enforce"
        admin = {"Authorization": "Bearer " + tokens["admin"]}
        for ukey, role_in_project in (("technician", "Technician"), ("requester", "SiteManager")):
            r = tc.post("/api/projects/%s/team" % fx["A"]["project_id"], headers=admin,
                        json={"user_id": fx["A"]["users"][ukey]["id"],
                              "role_in_project": role_in_project})
            assert r.status_code == 201, (ukey, r.status_code, r.text[:300])
        for ukey, role_in_project, kind in c02.P2_DATED:
            r = tc.post("/api/projects/%s/team" % fx["A"]["project2_id"], headers=admin,
                        json={"user_id": fx["A"]["users"][ukey]["id"],
                              "role_in_project": role_in_project, **c02.dated_window(kind)})
            assert r.status_code == 201, (ukey, kind, r.status_code, r.text[:300])
        os.environ["PERMISSION_SERVICE_MODE"] = "off"
        # The W0-04 unique indexes of the key registry (scripts/w0_04_bootstrap_audit_indexes
        # .py, PLANNED_INDEXES), as in a bootstrapped tenant and in the Codex review of #69.
        tc.portal.call(lambda: op_db.audit_idempotency.create_index([("id", 1)], unique=True))
        tc.portal.call(lambda: op_db.audit_idempotency.create_index(
            [("tenant_id", 1), ("action", 1), ("key", 1)], unique=True))
        snap = tc.portal.call(lambda: pm._snapshot(client, dbs))

        def post(role, key, body, idem=None, project_id=None):
            url = EP[key][1].replace("{project_id}", project_id or fx["A"]["project_id"])
            headers = {"Authorization": "Bearer " + tokens[role]}
            if idem is not None:
                headers["Idempotency-Key"] = idem
            before = tc.portal.call(lambda: pm._last_ts(oplog))
            resp = tc.post(url, json=body, headers=headers)
            written = tc.portal.call(lambda: pm.writes_with_org(client, oplog, before, dbs, snap))
            business = sorted({short(n) for n, _o in written if n.split(".", 1)[1] not in AUDIT})
            try:
                payload = resp.json()
            except Exception:                                     # noqa: BLE001
                payload = resp.text[:300]
            detail = payload.get("detail") if isinstance(payload, dict) else None
            return {"status": resp.status_code, "business_written": business,
                    "written": sorted({short(n) for n, _o in written}),
                    "error_code": detail.get("error_code") if isinstance(detail, dict) else None,
                    "body": payload}

        def restore_all():
            tc.portal.call(lambda: pm._restore(client, snap, sorted(snap)))

        def count(coll: str) -> int:
            return tc.portal.call(lambda: op_db[coll].count_documents({}))

        rows: List[Dict[str, Any]] = []
        sequences: List[Dict[str, Any]] = []
        r1: List[Dict[str, Any]] = []
        fg29: List[Dict[str, Any]] = []
        fg15: List[Dict[str, Any]] = []
        computed: List[Dict[str, Any]] = []
        race: List[Dict[str, Any]] = []
        fg90: List[Dict[str, Any]] = []
        fg105: List[Dict[str, Any]] = []

        def many_payments_probe(mode: str) -> Dict[str, Any]:
            base = body_for("subpay", fx["A"], c02)
            pkg_id = base["package_id"]
            org = fx["A"]["tenant_id"]
            tc.portal.call(lambda: op_db.subcontractor_packages.update_one(
                {"id": pkg_id}, {"$set": {"certified_total": 1000, "paid_total": 250,
                                          "committed_paid_total": 250}}))
            tc.portal.call(lambda: op_db.subcontractor_payments.insert_many([
                {"id": "c03-fg105-%d" % i, "org_id": org, "package_id": pkg_id,
                 "amount": 1.0, "status": "completed", "created_at": "2026-11-01T00:00:00"}
                for i in range(250)]))
            resp = tc.post("/api/subcontractor-payments", json={**base, "amount": 1},
                           headers={"Authorization": "Bearer " + tokens["accountant"],
                                    "Idempotency-Key": uuid.uuid4().hex})
            pkg = tc.portal.call(lambda: op_db.subcontractor_packages.find_one(
                {"id": pkg_id}, {"_id": 0}))
            restore_all()
            return {"mode": mode, "earlier_payments": 250, "status": resp.status_code,
                    "paid_total": pkg.get("paid_total"),
                    "payable_total": pkg.get("payable_total")}

        def certified_cap_probe(mode: str) -> Dict[str, Any]:
            import httpx
            hdr = {"Authorization": "Bearer " + tokens["accountant"]}
            base = body_for("subpay", fx["A"], c02)
            pkg_id = base["package_id"]

            def pay(amount, **extra):
                before = tc.portal.call(lambda: pm._last_ts(oplog))
                resp = tc.post("/api/subcontractor-payments", json={**base, "amount": amount, **extra},
                               headers={**hdr, "Idempotency-Key": uuid.uuid4().hex})
                written = tc.portal.call(lambda: pm.writes_with_org(client, oplog, before, dbs, snap))
                detail = resp.json().get("detail") if resp.status_code >= 400 else None
                return {"status": resp.status_code,
                        "error_code": detail.get("error_code") if isinstance(detail, dict) else None,
                        "business_written": sorted({short(n) for n, _ in written
                                                    if n.split(".", 1)[1] not in AUDIT})}
            pkg0 = tc.portal.call(lambda: op_db.subcontractor_packages.find_one({"id": pkg_id}, {"_id": 0}))
            out: Dict[str, Any] = {"mode": mode, "certified_total": pkg0.get("certified_total"),
                                   "paid_before": pkg0.get("paid_total")}
            out["over_101"] = pay(101)
            out["pay_60"] = pay(60)
            out["then_50"] = pay(50)
            out["then_40_to_the_cap"] = pay(40)
            out["then_0_01"] = pay(0.01)
            out["unknown_act"] = pay(1, act_id="c03-no-such-act")
            out["draft_act"] = pay(1, act_id=c02.rid("A", "sact"))
            pkg1 = tc.portal.call(lambda: op_db.subcontractor_packages.find_one({"id": pkg_id}, {"_id": 0}))
            out["paid_total_after"] = pkg1.get("paid_total")
            out["committed_after"] = pkg1.get("committed_paid_total")
            restore_all()

            async def two_at_once():          # 60 + 60 > 100, two different keys, concurrent
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                             base_url="http://testserver") as ac:
                    return await asyncio.gather(*[ac.post(
                        "/api/subcontractor-payments", json={**base, "amount": 60},
                        headers={**hdr, "Idempotency-Key": uuid.uuid4().hex}) for _ in range(2)])
            pair = tc.portal.call(two_at_once)
            allocs = tc.portal.call(lambda: op_db.subcontractor_payments.find(
                {"package_id": pkg_id}, {"_id": 0, "amount": 1}).to_list(100))
            out["concurrent_60_60"] = {
                "statuses": sorted(r.status_code for r in pair),
                "allocations_sum": round(sum(float(a["amount"]) for a in allocs), 2)}
            restore_all()
            return out

        def interrupted_payment_race(mode: str) -> Dict[str, Any]:
            from app.tenancy import data_access
            hdr = {"Authorization": "Bearer " + tokens["accountant"]}
            body = body_for("subpay", fx["A"], c02)
            pkg_id = body["package_id"]
            led0 = tc.portal.call(lambda: op_db.finance_payments.count_documents({}))
            alloc0 = tc.portal.call(lambda: op_db.subcontractor_payments.count_documents(
                {"package_id": pkg_id}))
            original = data_access.TenantCollection.insert_one
            state = {"armed": True}

            async def failing_insert(self, doc):
                if self.name == "subcontractor_payments" and state["armed"]:
                    state["armed"] = False          # once: after the ledger row is written
                    raise RuntimeError("injected failure between ledger and allocation")
                return await original(self, doc)
            idem = uuid.uuid4().hex
            data_access.TenantCollection.insert_one = failing_insert
            try:
                first = tc.post("/api/subcontractor-payments", json=body,
                                headers={**hdr, "Idempotency-Key": idem})
            finally:
                data_access.TenantCollection.insert_one = original
            after_fail = {
                "ledger": tc.portal.call(lambda: op_db.finance_payments.count_documents({})) - led0,
                "allocations": tc.portal.call(lambda: op_db.subcontractor_payments
                                              .count_documents({"package_id": pkg_id})) - alloc0}
            # Six retries truly concurrent in the app's own event loop (one ASGI transport,
            # asyncio.gather): each interleaves at every await, so all of them can read the
            # FAILED key before any of them writes — the interleaving of Codex F-69-01.
            import httpx

            async def six_retries():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                             base_url="http://testserver") as ac:
                    return await asyncio.gather(*[ac.post(
                        "/api/subcontractor-payments", json=body,
                        headers={**hdr, "Idempotency-Key": idem}) for _ in range(6)])
            resps = tc.portal.call(six_retries)
            allocs = tc.portal.call(lambda: op_db.subcontractor_payments.find(
                {"package_id": pkg_id}, {"_id": 0}).to_list(100))
            pkg = tc.portal.call(lambda: op_db.subcontractor_packages.find_one(
                {"id": pkg_id}, {"_id": 0}))
            out = {
                "mode": mode, "first_status": first.status_code, "after_failure": after_fail,
                "retry_statuses": sorted(r.status_code for r in resps),
                "retry_payment_ids": sorted({(r.json() or {}).get("id") for r in resps
                                             if r.status_code == 201}),
                "ledger_rows_added": tc.portal.call(
                    lambda: op_db.finance_payments.count_documents({})) - led0,
                "allocations_added": len(allocs) - alloc0,
                "package_paid_total": (pkg or {}).get("paid_total"),
                "allocations_sum": round(sum(float(a["amount"]) for a in allocs), 2),
                "amount": body["amount"]}
            restore_all()
            return out
        for mode in MODES:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            for key, _path, field, colls, _h in ENDPOINTS:
                base = body_for(key, fx["A"], c02)
                for value in INVALID:
                    if key == "subpay_vat" and (value == "<missing>" or
                                                (type(value) is int and value == 0)):
                        continue                  # a zero/absent VAT is a valid payment
                    res = post("accountant", key, with_value(base, field, value),
                               uuid.uuid4().hex)
                    res.pop("body")
                    rows.append({"mode": mode, "probe": key, "field": field,
                                 "value": value, **res})
                    if res["written"]:
                        restore_all()
                # valid, no key: refused (R29), nothing written
                n0 = count(colls[0])
                nokey = post("accountant", key, base)
                n_nokey = count(colls[0]) - n0
                if nokey["written"]:
                    restore_all()
                # the same key twice, then the same key with a different body
                idem = "c03-%s-%s-%s" % (mode, key, uuid.uuid4().hex[:8])
                n0 = count(colls[0])
                k1 = post("accountant", key, base, idem)
                k2 = post("accountant", key, base, idem)
                k3 = post("accountant", key, with_value(base, field, 11), idem)
                n_key = count(colls[0]) - n0
                ledger = count("finance_payments")
                restore_all()
                sequences.append({
                    "mode": mode, "probe": key,
                    "valid_no_key": {k: nokey[k] for k in
                                     ("status", "error_code", "business_written")},
                    "rows_added_no_key": n_nokey,
                    "same_key_first": {k: k1[k] for k in ("status", "business_written")},
                    "same_key_replay": {k: k2[k] for k in ("status", "business_written")},
                    "replay_body_equals_first": k1["body"] == k2["body"],
                    "same_key_other_body": {k: k3[k] for k in
                                            ("status", "error_code", "business_written")},
                    "rows_added_with_key": n_key,
                    "ledger_rows_after_keyed_sequence": ledger,
                })
            # SEC-R1 on this head (471eaaa + C03): membership window, three modes.
            for ukey, target in (("technician", "P1"), ("technician", "P2"),
                                 ("requester", "P1"), ("requester", "P2")):
                pid = fx["A"]["project_id"] if target == "P1" else fx["A"]["project2_id"]
                for key in ("labor", "waste"):
                    body = body_for(key, fx["A"], c02)
                    if key == "labor":
                        body["project_id"] = pid
                    res = post(ukey, key, body, uuid.uuid4().hex, project_id=pid)
                    res.pop("body")
                    r1.append({"mode": mode, "user": ukey, "project": target, "probe": key, **res})
                    if res["written"]:
                        restore_all()
            # FG-29: the project must exist in THIS tenant (Accountant of A, finance role).
            foreign, unknown = fx["B"]["project_id"], "c03-no-such-project"
            cases = [("labor", foreign, "B's project"), ("labor", unknown, "unknown"),
                     ("labor", None, "missing"), ("waste", foreign, "B's project"),
                     ("waste", unknown, "unknown"), ("pm_put", foreign, "B's project"),
                     ("pm_put", unknown, "unknown")]
            for key, pid, what in cases:
                if key == "pm_put":
                    before = tc.portal.call(lambda: pm._last_ts(oplog))
                    resp = tc.put("/api/price-modifiers/project/%s" % pid, json={"modifiers": {}},
                                  headers={"Authorization": "Bearer " + tokens["accountant"]})
                    written = tc.portal.call(lambda: pm.writes_with_org(client, oplog, before,
                                                                        dbs, snap))
                    res = {"status": resp.status_code, "written": sorted({short(n) for n, _ in written}),
                           "business_written": sorted({short(n) for n, _ in written
                                                       if n.split(".", 1)[1] not in AUDIT})}
                else:
                    body = body_for(key, fx["A"], c02)
                    if key == "labor":
                        body["project_id"] = pid
                        if pid is None:
                            body.pop("project_id")
                    res = post("accountant", key, body, uuid.uuid4().hex, project_id=pid)
                    res.pop("body")
                fg29.append({"mode": mode, "probe": key, "project": what, **res})
                if res["written"]:
                    restore_all()
            # FG-15: an R16 member (Technician on P1) writes labor but never sees the rate or
            # cost — neither in the response nor in a replay; the Accountant sees them.
            for ukey in ("technician", "accountant"):
                body = body_for("labor", fx["A"], c02)
                idem = uuid.uuid4().hex
                first = post(ukey, "labor", body, idem)
                again = post(ukey, "labor", body, idem)
                stored = tc.portal.call(lambda: op_db.labor_entries.find_one(
                    {"id": (first["body"] or {}).get("id")}, {"_id": 0}))
                fg15.append({"mode": mode, "user": ukey,
                             "status": [first["status"], again["status"]],
                             "response_money_keys": sorted(
                                 k for k in ("hourly_rate", "labor_cost") if k in first["body"]),
                             "replay_money_keys": sorted(
                                 k for k in ("hourly_rate", "labor_cost") if k in again["body"]),
                             "stored_money_keys": sorted(
                                 k for k in ("hourly_rate", "labor_cost") if k in (stored or {}))})
                restore_all()
            # F-69-02 (R29): sync / recompute / compute need a key; a repeat replays.
            for key3, url, body3 in COMPUTED_ROUTES(fx["A"]):
                hdr = {"Authorization": "Bearer " + tokens["admin"]}

                def call3(extra=None, body=body3):
                    before = tc.portal.call(lambda: pm._last_ts(oplog))
                    resp = tc.post(url, json=body, headers={**hdr, **(extra or {})})
                    written = tc.portal.call(lambda: pm.writes_with_org(client, oplog, before,
                                                                        dbs, snap))
                    return resp, sorted({short(n) for n, _ in written
                                         if n.split(".", 1)[1] not in AUDIT})
                nokey, w_nokey = call3()
                idem = uuid.uuid4().hex
                k1, w1 = call3({"Idempotency-Key": idem})
                k2, w2 = call3({"Idempotency-Key": idem})
                k3, w3 = call3({"Idempotency-Key": idem}, body=OTHER_BODY(key3, body3))
                snaps = tc.portal.call(lambda: op_db.overhead_snapshots.count_documents(
                    {"computed_by_user_id": fx["A"]["users"]["admin"]["id"]}))
                computed.append({
                    "mode": mode, "route": key3,
                    "no_key": {"status": nokey.status_code, "business_written": w_nokey,
                               "error_code": (nokey.json().get("detail") or {}).get("error_code")},
                    "first": {"status": k1.status_code, "business_written": w1},
                    "replay": {"status": k2.status_code, "business_written": w2},
                    "replay_body_equals_first": k1.json() == k2.json(),
                    "other_body": {"status": k3.status_code, "business_written": w3},
                    "admin_snapshots_after": snaps})
                restore_all()
            # F-69-01: a payment interrupted after the ledger row, then 6 CONCURRENT retries.
            race.append(interrupted_payment_race(mode))
            # FG-90 (FLOW-021): no payment above the certified total of the package (100).
            fg90.append(certified_cap_probe(mode))
            # FG-105: paid_total counts more than 200 earlier payments.
            fg105.append(many_payments_probe(mode))
        os.environ["PERMISSION_SERVICE_MODE"] = "off"

    result = {
        "schema": "beg.sec-01-c03-payment-amount-idempotency/v1",
        "fixture": "ST-01 synthetic tenant A + PM-01 and C02 existing records; actor Accountant",
        "modes": list(MODES), "endpoints": [list(e[:4]) for e in ENDPOINTS],
        "invalid_values": list(INVALID),
        "mongo": "local replica set (oplog)", "outbound_http": "closed local port",
        "seconds": round(time.time() - started, 1),
        "amount_rows": rows, "idempotency_sequences": sequences, "sec_r1": r1,
        "fg29_project_in_tenant": fg29, "fg15_labor_money": fg15,
        "f69_02_computed_routes": computed, "f69_01_interrupted_payment_race": race,
        "fg90_certified_cap": fg90, "fg105_many_payments": fg105,
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str) + "\n",
                        encoding="utf-8")
    return result


def run_in_child(mongo_url: str, out_json: Path, timeout: int = 3600) -> None:
    pm = _pm01()
    suffix = uuid.uuid4().hex[:12]
    op_name, sys_name = DB_PREFIX_OP + suffix, DB_PREFIX_SYS + suffix
    env = pm.child_env(mongo_url, op_name, sys_name)
    env["JWT_SECRET"] = "c03-local-" + uuid.uuid4().hex
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
    parser = argparse.ArgumentParser(description="SEC-01-C03 amount + idempotency evidence")
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
def check_result(result: Dict[str, Any]) -> None:
    rows = result["amount_rows"]
    assert rows
    for row in rows:
        assert row["status"] == 422, row
        assert row["business_written"] == [], row
    seen = {(r["mode"], r["probe"]) for r in rows}
    assert seen == {(m, e[0]) for m in MODES for e in ENDPOINTS}

    seqs = result["idempotency_sequences"]
    assert {(s["mode"], s["probe"]) for s in seqs} == seen
    for s in seqs:
        assert s["valid_no_key"] == {"status": 428, "error_code": "IDEMPOTENCY_KEY_REQUIRED",
                                     "business_written": []}, s
        assert s["rows_added_no_key"] == 0, s               # R29: no key, no row
        assert s["same_key_first"]["status"] == 201, s
        assert s["same_key_first"]["business_written"], s
        assert s["same_key_replay"] == {"status": 201, "business_written": []}, s
        assert s["replay_body_equals_first"] is True, s
        assert s["same_key_other_body"] == {"status": 409, "error_code": "IDEMPOTENCY_CONFLICT",
                                            "business_written": []}, s
        assert s["rows_added_with_key"] == 1, s              # one row for the key
    for s in seqs:
        if s["probe"].startswith("subpay"):
            # the ONE payment ledger got exactly one Outflow for the keyed sequence
            base = [x for x in seqs if x["mode"] == s["mode"] and x["probe"] == "cash"][0]
            assert s["ledger_rows_after_keyed_sequence"] == \
                base["ledger_rows_after_keyed_sequence"] + 1, s

    r1 = result["sec_r1"]
    assert {(r["mode"], r["user"], r["project"], r["probe"]) for r in r1} == {
        (m, u, p, k) for m in MODES for u in ("technician", "requester")
        for p in ("P1", "P2") for k in ("labor", "waste")}
    for r in r1:
        if r["project"] == "P1":
            assert r["status"] == 201 and r["business_written"], r
        else:
            assert r["status"] == 403 and r["business_written"] == [], r

    fg29 = result["fg29_project_in_tenant"]
    assert len(fg29) == 7 * len(MODES)
    for r in fg29:
        expected = 422 if r["project"] == "missing" else 404
        assert r["status"] == expected and r["business_written"] == [], r

    fg15 = result["fg15_labor_money"]
    assert {(r["mode"], r["user"]) for r in fg15} == {
        (m, u) for m in MODES for u in ("technician", "accountant")}
    for r in fg15:
        assert r["status"] == [201, 201], r
        assert r["stored_money_keys"] == ["hourly_rate", "labor_cost"], r
        visible = [] if r["user"] == "technician" else ["hourly_rate", "labor_cost"]
        assert r["response_money_keys"] == visible and r["replay_money_keys"] == visible, r

    check_computed_and_race(result)
    check_certified_cap(result)
    rows = result["fg105_many_payments"]
    assert [r["mode"] for r in rows] == list(MODES)
    for r in rows:   # 250 earlier payments of 1 + this one: all counted (before: only 200)
        assert r == {"mode": r["mode"], "earlier_payments": 250, "status": 201,
                     "paid_total": 251.0, "payable_total": 749.0}, r


def check_computed_and_race(result: Dict[str, Any]) -> None:
    computed = result["f69_02_computed_routes"]
    assert {(r["mode"], r["route"]) for r in computed} == {
        (m, k) for m in MODES for k in ("labor_sync", "recompute_labor", "overhead_compute")}
    for r in computed:
        assert r["no_key"] == {"status": 428, "business_written": [],
                               "error_code": "IDEMPOTENCY_KEY_REQUIRED"}, r
        assert r["first"]["status"] == 200, r
        assert r["replay"] == {"status": 200, "business_written": []}, r
        assert r["replay_body_equals_first"] is True, r
        if r["route"] == "recompute_labor":
            # the route's key fingerprint is its path only: the same path is the same request
            continue
        assert r["other_body"] == {"status": 409, "business_written": []}, r
        if r["route"] == "overhead_compute":
            assert r["first"]["business_written"] == ["op.overhead_snapshots"], r
            assert r["admin_snapshots_after"] == 1, r          # same key twice: 1 snapshot
    race = result["f69_01_interrupted_payment_race"]
    assert [r["mode"] for r in race] == list(MODES)
    for r in race:
        assert r["first_status"] == 500, r
        assert r["after_failure"] == {"ledger": 1, "allocations": 0}, r
        assert set(r["retry_statuses"]) <= {201, 409} and 201 in r["retry_statuses"], r
        assert len(r["retry_payment_ids"]) == 1, r            # every 201 = the same payment
        assert r["ledger_rows_added"] == 1 and r["allocations_added"] == 1, r
        assert r["package_paid_total"] == r["allocations_sum"], r


def check_certified_cap(result: Dict[str, Any]) -> None:
    rows = result["fg90_certified_cap"]
    assert [r["mode"] for r in rows] == list(MODES)
    nothing = {"status": 409, "error_code": "PAYMENT_EXCEEDS_CERTIFIED", "business_written": []}
    for r in rows:
        assert r["certified_total"] == 100 and r["paid_before"] == 0, r
        assert r["over_101"] == nothing, r
        assert r["pay_60"]["status"] == 201, r
        assert r["then_50"] == nothing, r                  # 60 + 50 > 100
        assert r["then_40_to_the_cap"]["status"] == 201, r  # exactly the cap
        assert r["then_0_01"] == nothing, r
        assert r["unknown_act"]["status"] == 404 and r["unknown_act"]["business_written"] == [], r
        assert r["draft_act"] == {"status": 409, "error_code": "PAYMENT_ACT_NOT_CONFIRMED",
                                  "business_written": []}, r
        assert r["paid_total_after"] == 100 and r["committed_after"] == 100, r
        assert r["concurrent_60_60"] == {"statuses": [201, 409], "allocations_sum": 60.0}, r


# ═════════════════════════════════════════════════════════════════════ DB-free tests
def test_money_value_accepts_only_finite_positive_numbers():
    from fastapi import HTTPException
    from app.permissions.money_input import money_value
    assert money_value(10) == 10.0
    assert money_value(12.5) == 12.5
    assert money_value(1e300) == 1e300                       # no upper limit in the canon
    assert money_value(0, allow_zero=True) == 0.0
    # FG-47: only a JSON number (the rule of #70) — numeric text and booleans are refused
    for bad in ("12.5", " 3 ", "10", "nan", "NaN", "inf", "-inf", "Infinity", "1e309", "",
                "  ", "abc", "1,5", -1, -0.01, 0, "0", None, True, False, [], [10], {},
                float("nan"), float("inf"), 10 ** 400):
        with pytest.raises(HTTPException) as exc:
            money_value(bad)
        assert exc.value.status_code == 422
    for bad in (-1, "nan", "inf", "0", False):
        with pytest.raises(HTTPException):
            money_value(bad, allow_zero=True)


def _handler(module: str, name: str):
    mod = importlib.import_module("app.routes." + module)
    return getattr(mod, name)


def test_every_money_post_validates_before_its_first_write_and_takes_the_key():
    for key, _p, field, _c, (module, name) in ENDPOINTS:
        fn = _handler(module, name)
        src = inspect.getsource(fn)
        if module == "subcontractors":
            src += inspect.getsource(_handler(module, "_write_subcontractor_payment"))
        sig = inspect.signature(fn)
        hdr = sig.parameters.get("idempotency_key")
        assert hdr is not None, key
        assert getattr(hdr.default, "alias", None) == "Idempotency-Key", key
        check = src.index("money_value(")
        begin = src.index("MoneyWrite.begin(")
        assert check < begin, key
        for write in (".insert_one(", ".update_one("):
            if write in src:
                assert check < src.index(write), (key, write)
        after = src.split("MoneyWrite.begin(", 1)[1]
        # F-69-01: every insert after the reservation is atomic once-per-key: inside
        # ``mw.insert_once()`` with ``_id`` = the key-derived id (no separate read).
        assert after.count(".insert_one(") == after.count(".insert_one(mw.unique(") >= 1, key
        assert after.count(".insert_one(") == after.count("mw.insert_once()"), key
        assert "needs_insert" not in src, key


def test_the_forms_send_an_idempotency_key():
    fe = REPO / "frontend" / "src"
    ops = (fe / "pages" / "ProjectOperationsPage.js").read_text(encoding="utf-8")
    waste = (fe / "components" / "MaterialWastePanel.js").read_text(encoding="utf-8")
    helper = (fe / "lib" / "idempotency.js").read_text(encoding="utf-8")
    assert "Idempotency-Key" in helper
    assert "idempotencyHeaders" in ops and "idempotencyHeaders" in waste


class _Coll:
    """A tiny async collection for the registry (DB-free)."""

    def __init__(self):
        self.rows: List[Dict[str, Any]] = []

    async def find_one(self, flt, proj=None):
        for r in self.rows:
            if all(r.get(k) == v for k, v in flt.items() if not isinstance(v, dict)):
                return dict(r)
        return None

    async def insert_one(self, doc):
        if any(r.get("id") == doc.get("id") for r in self.rows):
            raise RuntimeError("E11000 duplicate key")
        self.rows.append(dict(doc))

    async def update_one(self, flt, update):
        for r in self.rows:
            if all(r.get(k) == v for k, v in flt.items()):
                for k, v in (update.get("$set") or {}).items():
                    r[k] = v
                for k, v in (update.get("$addToSet") or {}).items():
                    r.setdefault(k, [])
                    if v not in r[k]:
                        r[k].append(v)
                return


class _BusinessColl(_Coll):
    """A business collection: ``_id`` is unique, a duplicate raises DuplicateKeyError."""

    async def insert_one(self, doc):
        from pymongo.errors import DuplicateKeyError
        if any(r.get("_id") == doc.get("_id") for r in self.rows):
            raise DuplicateKeyError("E11000 duplicate key", 11000,
                                    {"keyPattern": {"_id": 1}, "keyValue": {"_id": doc["_id"]}})
        self.rows.append(dict(doc))


class _DB(dict):
    def __getitem__(self, name):
        if name not in self:
            self[name] = _Coll()
        return dict.__getitem__(self, name)


def test_money_write_replays_conflicts_refuses_in_progress_and_resumes(monkeypatch):
    from fastapi import HTTPException
    from app.permissions import money_input as mi
    fake = _DB()
    monkeypatch.setattr(mi, "db", fake)
    user = {"id": "u1", "org_id": "t1"}
    other = {"id": "u2", "org_id": "t1"}
    business = _BusinessColl()

    async def scenario():
        # no key (absent or blank): 428, before the registry (R29)
        for missing in (None, "", "   "):
            with pytest.raises(HTTPException) as exc:
                await mi.MoneyWrite.begin(user, "a", missing, {"amount": 1})
            assert exc.value.status_code == 428
            assert exc.value.detail["error_code"] == "IDEMPOTENCY_KEY_REQUIRED"
        assert fake.get("audit_idempotency") is None
        # first keyed attempt fails after its insert -> FAILED, then the same request
        # finishes it without a second row
        mw = await mi.MoneyWrite.begin(user, "a", "k1", {"amount": 1})
        rid = mw.new_id("row")
        with pytest.raises(RuntimeError):
            async with mw:
                async with mw.insert_once():
                    await business.insert_one(mw.unique({"id": rid}))
                raise RuntimeError("crash after the insert")
        mw = await mi.MoneyWrite.begin(user, "a", "k1", {"amount": 1})
        assert mw.replay_id is None and mw.new_id("row") == rid
        async with mw:
            async with mw.insert_once():                          # already there: no 2nd row
                await business.insert_one(mw.unique({"id": rid}))
            mw.result_id = rid
        assert len(business.rows) == 1
        # completed: the same key + body replays; a different body is a conflict
        mw = await mi.MoneyWrite.begin(user, "a", "k1", {"amount": 1})
        assert mw.replay_id == rid
        with pytest.raises(HTTPException) as exc:
            await mi.MoneyWrite.begin(user, "a", "k1", {"amount": 2})
        assert exc.value.status_code == 409
        assert exc.value.detail["error_code"] == "IDEMPOTENCY_CONFLICT"
        # another user's same key is a different operation, never a replay
        mw = await mi.MoneyWrite.begin(other, "a", "k1", {"amount": 1})
        assert mw.replay_id is None and mw.new_id("row") != rid
        # a second request while the first still runs -> 409 in progress
        await mi.MoneyWrite.begin(user, "a", "k2", {"amount": 1})
        with pytest.raises(HTTPException) as exc:
            await mi.MoneyWrite.begin(user, "a", "k2", {"amount": 1})
        assert exc.value.status_code == 409
        assert exc.value.detail["error_code"] == "IDEMPOTENCY_IN_PROGRESS"
        # an over-long key is refused before the registry
        with pytest.raises(HTTPException) as exc:
            await mi.MoneyWrite.begin(user, "a", "x" * 201, {"amount": 1})
        assert exc.value.status_code == 422

    asyncio.run(scenario())


def test_the_committed_evidence_satisfies_the_package():
    if not RESULTS_JSON.exists():
        pytest.skip("no committed evidence yet")
    check_result(json.loads(RESULTS_JSON.read_text(encoding="utf-8")))


# ═══════════════════════════════════════════════════════════════════ real MongoDB run
def _real_refusal() -> str:
    url = os.environ.get("W0_03_REAL_MONGO_URL", "")
    if not url:
        return "W0_03_REAL_MONGO_URL not set"
    try:
        import pymongo
        c = pymongo.MongoClient(url, serverSelectionTimeoutMS=3000)
        hello = c.admin.command("hello")
        c.close()
    except Exception as exc:                                  # noqa: BLE001
        return "MongoDB not reachable: %s" % exc
    if not hello.get("setName"):
        return "C03 needs a replica set (the oplog measures writes): --replSet rs0"
    return ""


@pytest.mark.skipif(bool(_real_refusal()), reason=_real_refusal() or "ok")
def test_a_fresh_real_mongo_run_follows_the_rules_in_every_mode(tmp_path):
    out = tmp_path / "results.json"
    run_in_child(os.environ["W0_03_REAL_MONGO_URL"], out)
    check_result(json.loads(out.read_text(encoding="utf-8")))


if __name__ == "__main__":
    sys.exit(main())
