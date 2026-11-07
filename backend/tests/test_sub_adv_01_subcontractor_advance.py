"""
SUB-ADV-01 — advance to a subcontractor, deducted explicitly on acts (R39, R40).

Package: ``docs/architecture/tasks/SUB-ADV-01_SUBCONTRACTOR_ADVANCE.md`` (branch
``claude/happy-meitner-bmcnel``). Canon: FLOW-021 (advance given / deducted / remaining; no
"аванс без прихващане/остатък", no payment above the measured without Approval), FLOW-006
(one Payment ledger), CLAUDE §2.5, §7 (no automatic netting), §14. Code:
``app/routes/subcontractors.py`` (SUB-ADV-01 section), ``app/permissions/catalog.py``.

Rules under test, in off, shadow and enforce, on a real MongoDB replica set (ST-01 tenant A):
  roles      POST /subcontractor-packages/{id}/advances: Owner, Accountant -> 201; Admin,
             SiteManager, Technician, Viewer, Driver -> 403 and NOTHING written (R39).
  main       advance 1000 -> act 3000 paid with ``amount`` 2000 + ``advance_deducted`` 1000
             -> paid 2000, advance remaining 0, committed 3000, payable 0, cash out 3000,
             the act shows ``advance_deducted`` 1000; the ledger got 1000 + 2000.
  cap (R40)  per package: ordinary payments + deducted <= certified; an ordinary payment
             above it -> 409 PAYMENT_EXCEEDS_CERTIFIED (unchanged); a deduction above the
             remaining advance -> 409 ADVANCE_DEDUCTION_EXCEEDS_OUTSTANDING; above the act
             -> 409 ADVANCE_DEDUCTION_EXCEEDS_ACT; nothing written.
  key        6 concurrent advance requests with ONE key -> 1 advance row, 1 ledger row,
             advance_total = the amount once; no key -> 428, nothing written.
  reversal   DELETE /finance/payments/{advance ledger row} -> 409
             SOURCE_MODULE_REVERSAL_REQUIRED, nothing written (FG-45, until PAY-01 Part 2).

    PYTHONPATH=. pytest tests/test_sub_adv_01_subcontractor_advance.py -v --noconftest -p no:cacheprovider
    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \\
        PYTHONPATH=. pytest tests/test_sub_adv_01_subcontractor_advance.py -v --noconftest -p no:cacheprovider
    # regenerate the evidence:
    PYTHONPATH=. python tests/test_sub_adv_01_subcontractor_advance.py --harness \\
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
EVIDENCE = REPO / "docs" / "evidence" / "SUB-ADV-01"
RESULTS_JSON = EVIDENCE / "results.json"

MODES = ("off", "shadow", "enforce")
DB_PREFIX_OP, DB_PREFIX_SYS = "subadv_op_", "subadv_sys_"
SYNTH_PASSWORD = "SubAdv-Synthetic-Pass-2026!"   # synthetic users of a scratch database
AUDIT = {"audit_events", "audit_logs", "audit_chain_heads", "audit_chain", "audit_idempotency"}
ROLES = ("owner", "accountant", "admin", "requester", "technician", "viewer", "driver")
ADVANCE_HOLDERS = {"owner", "accountant"}                    # R39


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parent / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _pm01():
    return _load("subadv_pm01_helpers", "test_pm_01_permission_matrix.py")


def _c02():
    return _load("subadv_c02_helpers", "test_sec_01_c02_flow_guard_money_writes.py")


def rid(name: str) -> str:
    return "subadv-A-%s" % name


async def seed_advance_records(op_db, fx: Dict[str, Any]) -> None:
    """Tenant A: a confirmed package certified 3200 with two CONFIRMED acts (3000, 200)."""
    now = "2026-11-07T08:00:00+00:00"
    t = fx["A"]
    org, p1 = t["tenant_id"], t["project_id"]
    await op_db.subcontractor_packages.insert_one({
        "id": rid("pkg"), "org_id": org, "project_id": p1,
        "subcontractor_id": "pm01probe-A-c02-sub", "subcontractor_name": "Probe Sub",
        "package_no": "SP-ADV1", "title": "Advance package", "currency": "EUR",
        "status": "partially_certified", "contract_total": 5000, "certified_total": 3200,
        "paid_total": 0, "created_at": now})
    # addendum A (FG-115): a second package, contract 1000, one confirmed act of 400.
    await op_db.subcontractor_packages.insert_one({
        "id": rid("pkg2"), "org_id": org, "project_id": p1,
        "subcontractor_id": "pm01probe-A-c02-sub", "subcontractor_name": "Probe Sub",
        "package_no": "SP-ADV2", "title": "Advance package 2", "currency": "EUR",
        "status": "partially_certified", "contract_total": 1000, "certified_total": 400,
        "paid_total": 0, "created_at": now})
    for name, total, pkg in (("act1", 3000, "pkg"), ("act2", 200, "pkg"), ("act3", 400, "pkg2")):
        await op_db.subcontractor_acts.insert_one({
            "id": rid(name), "org_id": org, "project_id": p1, "package_id": rid(pkg),
            "act_no": "SA-%s" % name, "status": "confirmed", "certified_total": total,
            "lines": [], "created_at": now})
    if "subcontractor_acts" not in await op_db.list_collection_names():
        await op_db.create_collection("subcontractor_acts")


# ═══════════════════════════════════════════════════════════════════════ the harness
def run_harness(mongo_url: str, out_json: Path) -> Dict[str, Any]:
    op_name, sys_name = os.environ["DB_NAME"], os.environ["BEG_SYSTEM_DB"]
    assert op_name.startswith(DB_PREFIX_OP) and sys_name.startswith(DB_PREFIX_SYS)
    pm, c02 = _pm01(), _c02()
    import server
    import httpx
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
        tc.portal.call(lambda: seed_advance_records(op_db, fx))
        for name in ("audit_idempotency", "audit_logs"):
            if name not in tc.portal.call(lambda: op_db.list_collection_names()):
                tc.portal.call(lambda: op_db.create_collection(name))
        # The W0-04 unique indexes of the key registry, as in a bootstrapped tenant.
        tc.portal.call(lambda: op_db.audit_idempotency.create_index([("id", 1)], unique=True))
        tc.portal.call(lambda: op_db.audit_idempotency.create_index(
            [("tenant_id", 1), ("action", 1), ("key", 1)], unique=True))
        tokens: Dict[str, str] = {}
        for key in ROLES:
            r = tc.post("/api/auth/login", json={
                "email": fx["A"]["users"][key]["email"], "password": SYNTH_PASSWORD})
            assert r.status_code == 200, (key, r.status_code, r.text[:200])
            tokens[key] = r.json()["token"]
        snap = tc.portal.call(lambda: pm._snapshot(client, dbs))

        def call(method, role, url, body=None, idem: Optional[str] = "auto"):
            headers = {"Authorization": "Bearer " + tokens[role]}
            if idem == "auto":
                idem = uuid.uuid4().hex
            if idem is not None:
                headers["Idempotency-Key"] = idem
            before = tc.portal.call(lambda: pm._last_ts(oplog))
            resp = tc.request(method, url, json=body, headers=headers)
            written = tc.portal.call(lambda: pm.writes_with_org(client, oplog, before, dbs, snap))
            try:
                payload = resp.json()
            except Exception:                                     # noqa: BLE001
                payload = resp.text[:300]
            detail = payload.get("detail") if isinstance(payload, dict) else None
            return {"status": resp.status_code,
                    "error_code": detail.get("error_code") if isinstance(detail, dict) else None,
                    "business_written": sorted({short(n) for n, _ in written
                                                if n.split(".", 1)[1] not in AUDIT}),
                    "body": payload}

        def slim(res):
            return {k: res[k] for k in ("status", "error_code", "business_written")}

        def restore_all():
            tc.portal.call(lambda: pm._restore(client, snap, sorted(snap)))

        def pkg_state(pkg_id=rid("pkg")):
            p = tc.portal.call(lambda: op_db.subcontractor_packages.find_one({"id": pkg_id},
                                                                             {"_id": 0}))
            return {k: p.get(k) for k in ("certified_total", "paid_total", "advance_total",
                                          "advance_deducted_total", "advance_outstanding",
                                          "committed_paid_total", "payable_total",
                                          "cash_out_total")}

        def ledger_amounts() -> List[float]:
            rows = tc.portal.call(lambda: op_db.finance_payments.find(
                {"org_id": fx["A"]["tenant_id"]}, {"_id": 0, "amount": 1}).sort("_id", 1)
                .to_list(1000))
            return sorted(float(r["amount"]) for r in rows)

        adv_url = "/api/subcontractor-packages/%s/advances" % rid("pkg")
        pay_url = "/api/subcontractor-payments"
        adv = {"amount": 1000, "reason": "Аванс по договор", "advance_date": "2026-11-07"}

        roles_rows, flows, races, refusals, reversal = [], [], [], [], []
        cap_races, fg115, crashes, visibility = [], [], [], []
        headroom, audit_once = [], []

        from app.permissions import workflow
        original_mark = workflow.mark_idempotent_step

        def crash_at(step_name):
            state = {"armed": True}

            async def failing(db_, *, step, **kw):
                if step == step_name and state["armed"]:
                    state["armed"] = False      # the write is done; its step is not recorded
                    raise RuntimeError("injected crash after step %s" % step_name)
                return await original_mark(db_, step=step, **kw)
            return failing

        def post_crashing(step_name, role, url, body, idem):
            workflow.mark_idempotent_step = crash_at(step_name)
            try:
                return slim(call("POST", role, url, body, idem))
            finally:
                workflow.mark_idempotent_step = original_mark

        def adv_state():
            p = pkg_state()
            a1 = tc.portal.call(lambda: op_db.subcontractor_acts.find_one({"id": rid("act2")},
                                                                         {"_id": 0}))
            full = tc.portal.call(lambda: op_db.subcontractor_packages.find_one(
                {"id": rid("pkg")}, {"_id": 0}))
            return {"advance_total": p["advance_total"] or 0,
                    "advance_pending": full.get("advance_pending_total") or 0,
                    "deducted": p["advance_deducted_total"] or 0,
                    "deduction_pending": full.get("advance_deduction_pending_total") or 0,
                    "advance_rows": tc.portal.call(lambda: op_db.subcontractor_payments
                                                   .count_documents({"package_id": rid("pkg"),
                                                                     "kind": "advance"})),
                    "advance_ledger_rows": tc.portal.call(lambda: op_db.finance_payments
                                                          .count_documents(
                                                              {"subcontractor_advance": True})),
                    "act2_deducted": (a1 or {}).get("advance_deducted") or 0,
                    "act2_entries": len((a1 or {}).get("advance_deductions") or [])}

        def crash_probe(mode):
            out: Dict[str, Any] = {"mode": mode}
            ded_url = "/api/subcontractor-acts/%s/advance-deduction" % rid("act2")
            # A) advance: crash right after the cap reservation
            key = uuid.uuid4().hex
            out["advance_crash_after_reserve"] = post_crashing("advance_reserve", "accountant",
                                                                adv_url, adv, key)
            out["after_advance_crash"] = adv_state()
            # a deduction can never use the advance that does not exist
            out["deduct_phantom"] = slim(call("POST", "accountant", ded_url, {"amount": 100}))
            out["pay_deducting_phantom"] = slim(call("POST", "accountant", pay_url, {
                "package_id": rid("pkg"), "act_id": rid("act1"), "amount": 2000,
                "advance_deducted": 1000}))
            out["advance_retry"] = slim(call("POST", "accountant", adv_url, adv, key))
            out["advance_retry_again"] = slim(call("POST", "accountant", adv_url, adv, key))
            out["after_advance_retry"] = adv_state()
            # B) advance: crash after the rows and the AuditEvent, before the confirmation
            key = uuid.uuid4().hex
            out["advance_crash_after_audit"] = post_crashing("audit", "accountant", adv_url,
                                                             {**adv, "amount": 500}, key)
            out["after_audit_crash"] = adv_state()
            out["advance_b_retry"] = slim(call("POST", "accountant", adv_url,
                                               {**adv, "amount": 500}, key))
            out["after_advance_b_retry"] = adv_state()
            # C) deduction: crash right after its reservation
            key = uuid.uuid4().hex
            out["deduct_crash_after_reserve"] = post_crashing("reserve", "accountant", ded_url,
                                                              {"amount": 200}, key)
            out["after_deduct_crash"] = adv_state()
            out["deduct_retry"] = slim(call("POST", "accountant", ded_url, {"amount": 200}, key))
            out["after_deduct_retry"] = adv_state()
            restore_all()
            # D) deduction: crash after the act update, before its step is recorded
            call("POST", "accountant", adv_url, adv)
            key = uuid.uuid4().hex
            out["deduct_crash_after_act"] = post_crashing("act_deduction", "accountant", ded_url,
                                                          {"amount": 150}, key)
            out["after_act_crash"] = adv_state()
            out["deduct_d_retry"] = slim(call("POST", "accountant", ded_url, {"amount": 150}, key))
            out["after_deduct_d_retry"] = adv_state()
            restore_all()
            return out

        def taken_vs_contract():
            p = tc.portal.call(lambda: op_db.subcontractor_packages.find_one(
                {"id": rid("pkg")}, {"_id": 0}))
            g = lambda k: float(p.get(k) or 0)                       # noqa: E731
            return {"taken": round(g("advance_total") + g("advance_pending_total")
                                   - g("advance_deducted_total")
                                   - g("advance_deduction_pending_total")
                                   + g("committed_paid_total"), 2),
                    "contract": g("contract_total")}

        def headroom_probe(mode):
            """F-76-01: outstanding advance + committed <= contract, whatever the order."""
            out: Dict[str, Any] = {"mode": mode}
            pay = lambda amount, **x: slim(call("POST", "accountant", pay_url, {   # noqa: E731
                "package_id": rid("pkg"), "act_id": rid("act1"), "amount": amount, **x}))
            # order 1: advance, then an ordinary payment
            out["o1_advance_5000"] = slim(call("POST", "accountant", adv_url,
                                               {**adv, "amount": 5000}))
            out["o1_pay_100"] = pay(100)
            # cash 100 + deduction 100 is still 100 of new money on a full contract -> refused;
            # a deduction without cash only moves the advance into committed -> fits
            out["o1_pay_100_deducting_100"] = pay(100, advance_deducted=100)
            out["o1_deduct_100_no_cash"] = slim(call(
                "POST", "accountant", "/api/subcontractor-acts/%s/advance-deduction" % rid("act1"),
                {"amount": 100}))
            out["o1_end"] = taken_vs_contract()
            restore_all()
            # order 2: an ordinary payment, then the advance
            out["o2_pay_3000"] = pay(3000)
            out["o2_advance_2000_01"] = slim(call("POST", "accountant", adv_url,
                                                  {**adv, "amount": 2000.01}))
            out["o2_advance_2000"] = slim(call("POST", "accountant", adv_url,
                                               {**adv, "amount": 2000}))
            out["o2_pay_0_01"] = slim(call("POST", "accountant", pay_url, {
                "package_id": rid("pkg"), "act_id": rid("act2"), "amount": 0.01}))
            out["o2_end"] = taken_vs_contract()
            restore_all()
            # race: advance 1000 || ordinary payment 1000 at taken 4000 (only one fits)
            hdr = {"Authorization": "Bearer " + tokens["accountant"]}
            rounds = []
            for _ in range(3):
                call("POST", "accountant", adv_url, {**adv, "amount": 4000})

                async def pair():
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                                 base_url="http://testserver") as ac:
                        return await asyncio.gather(
                            ac.post(adv_url, json=adv,
                                    headers={**hdr, "Idempotency-Key": uuid.uuid4().hex}),
                            ac.post(pay_url, json={"package_id": rid("pkg"),
                                                   "act_id": rid("act1"), "amount": 1000},
                                    headers={**hdr, "Idempotency-Key": uuid.uuid4().hex}))
                a, b = tc.portal.call(pair)
                rounds.append({"statuses": sorted([a.status_code, b.status_code]),
                               "codes_409": sorted((r.json().get("detail") or {}).get("error_code")
                                                   for r in (a, b) if r.status_code == 409),
                               **taken_vs_contract()})
                restore_all()
            out["race"] = rounds
            return out

        def audit_crash_probe(mode):
            """F-76-02: crash right after the audit insert, then two same-key retries."""
            def audits(action):
                return tc.portal.call(lambda: op_db.audit_logs.count_documents(
                    {"action": action, "org_id": fx["A"]["tenant_id"]}))
            out: Dict[str, Any] = {"mode": mode}
            a0 = audits("subcontractor_advance_created")
            key = uuid.uuid4().hex
            first = post_crashing("audit", "accountant", adv_url, adv, key)
            r1 = slim(call("POST", "accountant", adv_url, adv, key))
            r2 = slim(call("POST", "accountant", adv_url, adv, key))
            out["advance"] = {"statuses": [first["status"], r1["status"], r2["status"]],
                              "audit_rows": audits("subcontractor_advance_created") - a0,
                              "advance_rows": tc.portal.call(
                                  lambda: op_db.subcontractor_payments.count_documents(
                                      {"package_id": rid("pkg"), "kind": "advance"})),
                              "advance_total": pkg_state()["advance_total"]}
            d0 = audits("subcontractor_advance_deducted")
            key = uuid.uuid4().hex
            ded_url = "/api/subcontractor-acts/%s/advance-deduction" % rid("act2")
            first = post_crashing("audit_deduction", "accountant", ded_url, {"amount": 100}, key)
            r1 = slim(call("POST", "accountant", ded_url, {"amount": 100}, key))
            r2 = slim(call("POST", "accountant", ded_url, {"amount": 100}, key))
            act2 = tc.portal.call(lambda: op_db.subcontractor_acts.find_one({"id": rid("act2")},
                                                                           {"_id": 0}))
            out["deduction"] = {"statuses": [first["status"], r1["status"], r2["status"]],
                                "audit_rows": audits("subcontractor_advance_deducted") - d0,
                                "act_entries": len(act2.get("advance_deductions") or []),
                                "deducted": pkg_state()["advance_deducted_total"]}
            restore_all()
            return out

        def visibility_probe(mode):
            call("POST", "accountant", adv_url, adv)
            call("POST", "accountant", "/api/subcontractor-acts/%s/advance-deduction"
                 % rid("act2"), {"amount": 100})
            pid = fx["A"]["project_id"]
            adv_keys = {"advance", "advance_total", "advance_deducted_total",
                        "advance_outstanding", "cash_out_total", "advance_deducted_by_act"}
            out: Dict[str, Any] = {"mode": mode}
            for role in ("accountant", "owner", "admin", "requester", "technician"):
                pkgs = call("GET", role, "/api/subcontractor-packages?project_id=%s" % pid,
                            None, None)
                one = call("GET", role, "/api/subcontractor-packages/%s" % rid("pkg"), None, None)
                acts = call("GET", role, "/api/subcontractor-acts?package_id=%s" % rid("pkg"),
                            None, None)
                pays = call("GET", role, "/api/subcontractor-payments?package_id=%s"
                            % rid("pkg"), None, None)
                prof = call("GET", role, "/api/project-profit/%s" % pid, None, None)
                row = next((p for p in (pkgs["body"] if isinstance(pkgs["body"], list) else [])
                            if p.get("id") == rid("pkg")), {})
                act2 = next((a for a in (acts["body"] if isinstance(acts["body"], list) else [])
                             if a.get("id") == rid("act2")), {})
                out[role] = {
                    "statuses": [pkgs["status"], one["status"], acts["status"], pays["status"],
                                 prof["status"]],
                    "list_keys": sorted(adv_keys & set(row)),
                    "one_advance": (one["body"] or {}).get("advance")
                    if one["status"] == 200 else None,
                    "one_keys": sorted(adv_keys & set(one["body"] or {}))
                    if one["status"] == 200 else [],
                    "act_keys": sorted({"advance_deducted", "advance_deductions"} & set(act2)),
                    "advance_rows": sum(1 for r in (pays["body"] if isinstance(pays["body"], list)
                                                    else []) if r.get("kind") == "advance"),
                    "profit_advances": (prof["body"] or {}).get("subcontract_advances")
                    if prof["status"] == 200 else "n/a",
                    "profit_expenses_keys": sorted(((prof["body"] or {}).get("expenses") or {})
                                                   .keys()) if prof["status"] == 200 else []}
            restore_all()
            return out
        for mode in MODES:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            # ── roles × mode (R39)
            for role in ROLES:
                res = call("POST", role, adv_url, adv)
                roles_rows.append({"mode": mode, "role": role, **slim(res)})
                if res["business_written"]:
                    restore_all()
            # ── main flow: advance 1000 -> act 3000 paid 2000 + deducted 1000
            led0 = ledger_amounts()
            f: Dict[str, Any] = {"mode": mode}
            f["advance"] = slim(call("POST", "accountant", adv_url, adv))
            f["after_advance"] = pkg_state()
            # FG-114: 1 000 000 on a contract of 5 000 -> refused, nothing written
            f["advance_1m"] = slim(call("POST", "accountant", adv_url, {**adv, "amount": 1000000}))
            f["pay_with_deduction"] = slim(call("POST", "accountant", pay_url, {
                "package_id": rid("pkg"), "act_id": rid("act1"), "amount": 2000,
                "advance_deducted": 1000}))
            f["after_payment"] = pkg_state()
            act1 = tc.portal.call(lambda: op_db.subcontractor_acts.find_one(
                {"id": rid("act1")}, {"_id": 0}))
            f["act1_advance_deducted"] = act1.get("advance_deducted")
            f["act1_deduction_entries"] = len(act1.get("advance_deductions") or [])
            from collections import Counter
            added = Counter(ledger_amounts()) - Counter(led0)
            f["ledger_added"] = sorted(added.elements())
            f["ledger_rows_added"] = sum(added.values())
            # R40 cap: 200 certified left (act2); an ordinary 200.01 is refused (unchanged)
            f["ordinary_over_cap"] = slim(call("POST", "accountant", pay_url, {
                "package_id": rid("pkg"), "amount": 200.01}))
            f["deduct_over_outstanding"] = slim(call(
                "POST", "accountant", "/api/subcontractor-acts/%s/advance-deduction" % rid("act2"),
                {"amount": 1}))
            # a second advance, then the deduction without cash on act2 (200 certified)
            f["advance_2"] = slim(call("POST", "owner", adv_url, {**adv, "amount": 500}))
            f["deduct_over_act"] = slim(call(
                "POST", "accountant", "/api/subcontractor-acts/%s/advance-deduction" % rid("act2"),
                {"amount": 250}))
            f["deduct_requester"] = slim(call(
                "POST", "requester", "/api/subcontractor-acts/%s/advance-deduction" % rid("act2"),
                {"amount": 200}))
            f["deduct_act2"] = slim(call(
                "POST", "admin", "/api/subcontractor-acts/%s/advance-deduction" % rid("act2"),
                {"amount": 200, "reason": "Акт покрит от аванса"}))
            f["after_act2"] = pkg_state()
            # FG-114: taken = outstanding 300 + committed 3200 = 3500 of the contract 5000
            f["advance_over_value"] = slim(call("POST", "owner", adv_url, {**adv, "amount": 1500.01}))
            f["advance_to_value"] = slim(call("POST", "owner", adv_url, {**adv, "amount": 1500}))
            f["ordinary_0_01_at_cap"] = slim(call("POST", "accountant", pay_url, {
                "package_id": rid("pkg"), "amount": 0.01}))
            # FG-90 on the C02 package (certified 100): unchanged
            f["c02_pay_101"] = slim(call("POST", "accountant", pay_url, {
                "package_id": c02.rid("A", "pkg"), "amount": 101}))
            # the advance's ledger row cannot be hard-deleted (FG-45)
            adv_row = tc.portal.call(lambda: op_db.finance_payments.find_one(
                {"subcontractor_advance": True}, {"_id": 0, "id": 1}))
            reversal.append({"mode": mode, **slim(call(
                "DELETE", "accountant", "/api/finance/payments/%s" % adv_row["id"],
                {"reason": "Опит за сторно на аванс от финанси"}))})   # PAY-01 (#70): reason required
            flows.append(f)
            restore_all()
            # ── refusals: nothing written
            for name, method, url, body, idem in (
                    ("no_key", "POST", adv_url, adv, None),
                    ("no_reason", "POST", adv_url, {"amount": 10}, "auto"),
                    ("nan", "POST", adv_url, {**adv, "amount": "nan"}, "auto"),
                    ("deduction_without_act", "POST", pay_url,
                     {"package_id": rid("pkg"), "amount": 10, "advance_deducted": 5}, "auto"),
                    ("payment_type_advance", "POST", pay_url,
                     {"package_id": rid("pkg"), "amount": 10, "payment_type": "advance"}, "auto"),
                    ("no_contract_value", "POST", "/api/subcontractor-packages/%s/advances"
                     % c02.rid("A", "pkg"), adv, "auto"),
                    ("unknown_package", "POST", "/api/subcontractor-packages/%s/advances"
                     % "pm01probe-A-c02-pkg-none", adv, "auto")):
                res = call(method, "accountant", url, body, idem)
                refusals.append({"mode": mode, "probe": name, **slim(res)})
                if res["business_written"]:
                    restore_all()
            # ── six concurrent advance requests with ONE key
            hdr = {"Authorization": "Bearer " + tokens["accountant"]}
            key = "subadv-race-%s-%s" % (mode, uuid.uuid4().hex[:8])

            async def six():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                             base_url="http://testserver") as ac:
                    return await asyncio.gather(*[ac.post(adv_url, json=adv, headers={
                        **hdr, "Idempotency-Key": key}) for _ in range(6)])
            led0 = len(ledger_amounts())
            resps = tc.portal.call(six)
            advs = tc.portal.call(lambda: op_db.subcontractor_payments.find(
                {"package_id": rid("pkg"), "kind": "advance"}, {"_id": 0, "id": 1}).to_list(100))
            races.append({"mode": mode, "statuses": sorted(r.status_code for r in resps),
                          "ids_201": sorted({r.json().get("id") for r in resps
                                             if r.status_code == 201}),
                          "advance_rows": len(advs),
                          "ledger_rows_added": len(ledger_amounts()) - led0,
                          "advance_total": pkg_state()["advance_total"]})
            restore_all()
            # ── FG-114: six concurrent advances of 1000, DIFFERENT keys, contract 5000

            async def six_keys():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                             base_url="http://testserver") as ac:
                    return await asyncio.gather(*[ac.post(adv_url, json=adv, headers={
                        **hdr, "Idempotency-Key": uuid.uuid4().hex}) for _ in range(6)])
            led0 = len(ledger_amounts())
            resps = tc.portal.call(six_keys)
            advs = tc.portal.call(lambda: op_db.subcontractor_payments.count_documents(
                {"package_id": rid("pkg"), "kind": "advance"}))
            cap_races.append({
                "mode": mode, "statuses": sorted(r.status_code for r in resps),
                "codes_409": sorted({(r.json().get("detail") or {}).get("error_code")
                                     for r in resps if r.status_code == 409}),
                "advance_rows": advs, "ledger_rows_added": len(ledger_amounts()) - led0,
                "advance_total": pkg_state()["advance_total"]})
            restore_all()
            # ── FG-115: an advance is cash, not cost; the cost comes with the deduction
            pid = fx["A"]["project_id"]

            def money_views():
                pnl = call("GET", "owner", "/api/projects/%s/pnl" % pid, None, None)["body"]
                fr = call("GET", "owner", "/api/projects/%s/financial-results" % pid,
                          None, None)["body"]
                return {"pnl_subcontractor_cost": pnl["expense"]["subcontractor_cost"],
                        "cash_paid_subcontractors":
                            fr["cash"]["breakdown"]["paid_subcontractors"],
                        "operating_subcontractor_direct":
                            fr["operating"]["subcontractor_direct"]}
            v0 = money_views()
            r_adv = slim(call("POST", "accountant",
                              "/api/subcontractor-packages/%s/advances" % rid("pkg2"), adv))
            v1 = money_views()
            r_ded = slim(call("POST", "accountant",
                              "/api/subcontractor-acts/%s/advance-deduction" % rid("act3"),
                              {"amount": 400}))
            v2 = money_views()
            r_more = slim(call("POST", "owner",
                               "/api/subcontractor-packages/%s/advances" % rid("pkg2"),
                               {**adv, "amount": 0.01}))
            delta = lambda a, b: {k: round(b[k] - a[k], 2) for k in a}   # noqa: E731
            fg115.append({"mode": mode, "advance": r_adv, "deduct_400": r_ded,
                          "after_advance": delta(v0, v1), "after_deduction": delta(v0, v2),
                          "advance_0_01_over_contract": r_more})
            restore_all()
            # ── FG-103: crash right after a write, before its step is recorded
            crashes.append(crash_probe(mode))
            # ── FG-128: the advance is shown to the finance roles only
            visibility.append(visibility_probe(mode))
            # ── Codex F-76-01 / F-76-02
            headroom.append(headroom_probe(mode))
            audit_once.append(audit_crash_probe(mode))
        os.environ["PERMISSION_SERVICE_MODE"] = "off"

    result = {
        "schema": "beg.sub-adv-01-subcontractor-advance/v1",
        "fixture": "ST-01 synthetic tenant A + PM-01/C02 records + package certified 3200 "
                   "(contract 5000, acts 3000 and 200) + package 2 (contract 1000, act 400)",
        "modes": list(MODES), "mongo": "local replica set (oplog)",
        "seconds": round(time.time() - started, 1),
        "roles": roles_rows, "flows": flows, "refusals": refusals,
        "same_key_race": races, "reversal": reversal,
        "fg114_different_keys_race": cap_races, "fg115_cash_vs_cost": fg115,
        "fg103_crash": crashes, "fg128_visibility": visibility,
        "f76_01_headroom": headroom, "f76_02_audit_once": audit_once,
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
    env["JWT_SECRET"] = "subadv-local-" + uuid.uuid4().hex
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
    parser = argparse.ArgumentParser(description="SUB-ADV-01 subcontractor advance evidence")
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
def _nothing(code: str, status: int = 409) -> Dict[str, Any]:
    return {"status": status, "error_code": code, "business_written": []}


def check_result(result: Dict[str, Any]) -> None:
    roles = result["roles"]
    assert {(r["mode"], r["role"]) for r in roles} == {(m, k) for m in MODES for k in ROLES}
    for r in roles:
        if r["role"] in ADVANCE_HOLDERS:
            assert r["status"] == 201, r
            assert r["business_written"] == ["op.finance_payments", "op.subcontractor_packages",
                                             "op.subcontractor_payments"], r
        else:
            assert r["status"] == 403 and r["business_written"] == [], r

    flows = result["flows"]
    assert [f["mode"] for f in flows] == list(MODES)
    for f in flows:
        assert f["advance"]["status"] == 201, f
        a = f["after_advance"]
        assert (a["advance_total"], a["advance_outstanding"], a["paid_total"]) == (1000, 1000, 0), f
        assert a["committed_paid_total"] in (None, 0), f       # the advance reserves nothing
        assert f["advance_1m"] == _nothing("ADVANCE_EXCEEDS_PACKAGE_VALUE"), f
        assert f["pay_with_deduction"]["status"] == 201, f
        p = f["after_payment"]
        assert p == {"certified_total": 3200, "paid_total": 2000, "advance_total": 1000,
                     "advance_deducted_total": 1000, "advance_outstanding": 0,
                     "committed_paid_total": 3000, "payable_total": 200,
                     "cash_out_total": 3000}, f
        assert f["act1_advance_deducted"] == 1000 and f["act1_deduction_entries"] == 1, f
        assert f["ledger_rows_added"] == 2 and f["ledger_added"] == [1000.0, 2000.0], f
        assert f["ordinary_over_cap"] == _nothing("PAYMENT_EXCEEDS_CERTIFIED"), f
        assert f["deduct_over_outstanding"] == _nothing("ADVANCE_DEDUCTION_EXCEEDS_OUTSTANDING"), f
        assert f["advance_2"]["status"] == 201, f
        assert f["deduct_over_act"] == _nothing("ADVANCE_DEDUCTION_EXCEEDS_ACT"), f
        assert f["deduct_requester"]["status"] == 403, f
        assert f["deduct_requester"]["business_written"] == [], f
        assert f["deduct_requester"]["error_code"] in (None, "PERMISSION_DENIED"), f
        assert f["deduct_act2"]["status"] == 201, f
        assert f["deduct_act2"]["business_written"] == ["op.subcontractor_acts",
                                                        "op.subcontractor_packages"], f
        assert f["after_act2"] == {"certified_total": 3200, "paid_total": 2000,
                                   "advance_total": 1500, "advance_deducted_total": 1200,
                                   "advance_outstanding": 300, "committed_paid_total": 3200,
                                   "payable_total": 0, "cash_out_total": 3500}, f
        assert f["ordinary_0_01_at_cap"] == _nothing("PAYMENT_EXCEEDS_CERTIFIED"), f
        assert f["advance_over_value"] == _nothing("ADVANCE_EXCEEDS_PACKAGE_VALUE"), f
        assert f["advance_to_value"]["status"] == 201, f
        assert f["c02_pay_101"] == _nothing("PAYMENT_EXCEEDS_CERTIFIED"), f

    expected = {"no_key": _nothing("IDEMPOTENCY_KEY_REQUIRED", 428),
                "no_reason": _nothing("REASON_INVALID", 422),
                "nan": {"status": 422, "business_written": []},
                "deduction_without_act": _nothing("ADVANCE_DEDUCTION_NEEDS_ACT", 422),
                "payment_type_advance": _nothing("ADVANCE_NOT_A_PAYMENT", 422),
                "no_contract_value": _nothing("ADVANCE_PACKAGE_VALUE_REQUIRED", 422),
                "unknown_package": {"status": 404, "business_written": []}}
    refusals = result["refusals"]
    assert {(r["mode"], r["probe"]) for r in refusals} == {(m, k) for m in MODES for k in expected}
    for r in refusals:
        want = expected[r["probe"]]
        assert {k: r[k] for k in want} == want, r

    races = result["same_key_race"]
    assert [r["mode"] for r in races] == list(MODES)
    for r in races:
        assert set(r["statuses"]) <= {201, 409} and 201 in r["statuses"], r
        assert len(r["ids_201"]) == 1, r                       # every 201 = the same advance
        assert r["advance_rows"] == 1 and r["ledger_rows_added"] == 1, r
        assert r["advance_total"] == 1000, r

    cap = result["fg114_different_keys_race"]
    assert [r["mode"] for r in cap] == list(MODES)
    for r in cap:                       # contract 5000: five of six 1000s, never more
        assert r["statuses"] == [201] * 5 + [409], r
        assert r["codes_409"] == ["ADVANCE_EXCEEDS_PACKAGE_VALUE"], r
        assert r["advance_rows"] == 5 and r["ledger_rows_added"] == 5, r
        assert r["advance_total"] == 5000, r

    fg115 = result["fg115_cash_vs_cost"]
    assert [r["mode"] for r in fg115] == list(MODES)
    for r in fg115:
        assert r["advance"]["status"] == 201 and r["deduct_400"]["status"] == 201, r
        assert r["after_advance"] == {"pnl_subcontractor_cost": 0,
                                      "cash_paid_subcontractors": 1000,
                                      "operating_subcontractor_direct": 0}, r
        assert r["after_deduction"] == {"pnl_subcontractor_cost": 400,
                                        "cash_paid_subcontractors": 1000,
                                        "operating_subcontractor_direct": 400}, r
        assert r["advance_0_01_over_contract"] == _nothing("ADVANCE_EXCEEDS_PACKAGE_VALUE"), r

    zero_adv = {"advance_total": 0, "advance_pending": 0, "deducted": 0, "deduction_pending": 0,
                "advance_rows": 0, "advance_ledger_rows": 0, "act2_deducted": 0, "act2_entries": 0}
    crashes = result["fg103_crash"]
    assert [r["mode"] for r in crashes] == list(MODES)
    for r in crashes:
        # A) the reservation is pending only: not deductible, no rows, no cash
        assert r["advance_crash_after_reserve"]["status"] == 500, r
        assert r["after_advance_crash"] == {**zero_adv, "advance_pending": 1000}, r
        assert r["deduct_phantom"] == _nothing("ADVANCE_DEDUCTION_EXCEEDS_OUTSTANDING"), r
        assert r["pay_deducting_phantom"] == _nothing("ADVANCE_DEDUCTION_EXCEEDS_OUTSTANDING"), r
        assert r["advance_retry"]["status"] == 201, r              # the same key finishes it
        assert r["advance_retry_again"] == {"status": 201, "error_code": None,
                                            "business_written": []}, r      # replay
        assert r["after_advance_retry"] == {**zero_adv, "advance_total": 1000,
                                            "advance_rows": 1, "advance_ledger_rows": 1}, r
        # B) rows written, not yet confirmed: still not deductible; the retry confirms once
        assert r["advance_crash_after_audit"]["status"] == 500, r
        assert r["after_audit_crash"] == {**zero_adv, "advance_total": 1000,
                                          "advance_pending": 500, "advance_rows": 2,
                                          "advance_ledger_rows": 2}, r
        assert r["advance_b_retry"]["status"] == 201, r
        assert r["after_advance_b_retry"] == {**zero_adv, "advance_total": 1500,
                                              "advance_rows": 2, "advance_ledger_rows": 2}, r
        # C) deduction reserved, not on the act: pending only (no cost); the retry finishes once
        assert r["deduct_crash_after_reserve"]["status"] == 500, r
        assert r["after_deduct_crash"] == {**zero_adv, "advance_total": 1500,
                                           "advance_rows": 2, "advance_ledger_rows": 2,
                                           "deduction_pending": 200}, r
        assert r["deduct_retry"]["status"] == 201, r
        assert r["after_deduct_retry"] == {**zero_adv, "advance_total": 1500,
                                           "advance_rows": 2, "advance_ledger_rows": 2,
                                           "deducted": 200, "act2_deducted": 200,
                                           "act2_entries": 1}, r
        # D) crash after the act update: the retry never adds the deduction twice
        assert r["deduct_crash_after_act"]["status"] == 500, r
        assert r["after_act_crash"]["act2_entries"] == 1 and \
            r["after_act_crash"]["deducted"] == 0 and \
            r["after_act_crash"]["deduction_pending"] == 150, r
        assert r["deduct_d_retry"]["status"] == 201, r
        assert r["after_deduct_d_retry"] == {**zero_adv, "advance_total": 1000,
                                             "advance_rows": 1, "advance_ledger_rows": 1,
                                             "deducted": 150, "act2_deducted": 150,
                                             "act2_entries": 1}, r

    vis = result["fg128_visibility"]
    assert [r["mode"] for r in vis] == list(MODES)
    for r in vis:
        for role in ("accountant", "owner", "admin"):
            v = r[role]
            assert v["statuses"] == [200] * 5, (role, r)
            assert {"advance", "advance_total", "advance_deducted_total",
                    "advance_outstanding"} <= set(v["list_keys"]), (role, r)
            assert v["one_advance"] == {"given": 1000, "deducted": 100, "outstanding": 900,
                                        "pending": 0}, (role, r)
            assert v["act_keys"] == ["advance_deducted", "advance_deductions"], (role, r)
            assert v["advance_rows"] == 1, (role, r)
            assert v["profit_advances"] == {"given": 1000, "deducted": 100,
                                            "outstanding": 900, "pending": 0}, (role, r)
            assert not any("advance" in k for k in v["profit_expenses_keys"]), (role, r)
        for role in ("requester", "technician"):
            v = r[role]
            assert v["list_keys"] == [] and v["one_keys"] == [], (role, r)
            assert v["one_advance"] is None and v["act_keys"] == [], (role, r)
            assert v["advance_rows"] == 0, (role, r)
            assert v["profit_advances"] in (None, "n/a"), (role, r)

    head = result["f76_01_headroom"]
    assert [r["mode"] for r in head] == list(MODES)
    for r in head:
        assert r["o1_advance_5000"]["status"] == 201, r
        assert r["o1_pay_100"] == _nothing("PAYMENT_EXCEEDS_PACKAGE_VALUE"), r
        assert r["o1_pay_100_deducting_100"] == _nothing("PAYMENT_EXCEEDS_PACKAGE_VALUE"), r
        assert r["o1_deduct_100_no_cash"]["status"] == 201, r      # explicit deduction: fits
        assert r["o1_end"] == {"taken": 5000, "contract": 5000}, r
        assert r["o2_pay_3000"]["status"] == 201, r
        assert r["o2_advance_2000_01"] == _nothing("ADVANCE_EXCEEDS_PACKAGE_VALUE"), r
        assert r["o2_advance_2000"]["status"] == 201, r
        assert r["o2_pay_0_01"] == _nothing("PAYMENT_EXCEEDS_PACKAGE_VALUE"), r
        assert r["o2_end"] == {"taken": 5000, "contract": 5000}, r
        assert len(r["race"]) == 3, r
        for rnd in r["race"]:
            assert rnd["statuses"] == [201, 409], r
            assert rnd["codes_409"][0] in ("ADVANCE_EXCEEDS_PACKAGE_VALUE",
                                           "PAYMENT_EXCEEDS_PACKAGE_VALUE"), r
            assert rnd["taken"] == 5000 and rnd["contract"] == 5000, r

    aud = result["f76_02_audit_once"]
    assert [r["mode"] for r in aud] == list(MODES)
    for r in aud:
        assert r["advance"] == {"statuses": [500, 201, 201], "audit_rows": 1,
                                "advance_rows": 1, "advance_total": 1000}, r
        assert r["deduction"] == {"statuses": [500, 201, 201], "audit_rows": 1,
                                  "act_entries": 1, "deducted": 100}, r

    rev = result["reversal"]
    assert [r["mode"] for r in rev] == list(MODES)
    for r in rev:
        assert {k: r[k] for k in ("status", "error_code", "business_written")} == \
            _nothing("SOURCE_MODULE_REVERSAL_REQUIRED"), r


# ═════════════════════════════════════════════════════════════════════ DB-free tests
def _route(path: str, method: str = "POST"):
    import server
    for route in server.app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", ()):
            return route
    raise AssertionError(path)


def test_the_catalog_gives_the_advance_to_owner_and_accountant_only():
    from app.permissions.catalog import (
        ACTIONS, PERMISSION_MATRIX, SUBCONTRACTOR_ADVANCE_ACTIONS,
        SUBCONTRACTOR_ADVANCE_DEDUCTION_ACTIONS, MONEY_WRITE_ACTIONS, is_significant_action)
    assert SUBCONTRACTOR_ADVANCE_ACTIONS == {"finance.subcontractor_advance.create"}
    assert SUBCONTRACTOR_ADVANCE_DEDUCTION_ACTIONS == {"subcontract.advance_deduction.execute"}
    both = SUBCONTRACTOR_ADVANCE_ACTIONS | SUBCONTRACTOR_ADVANCE_DEDUCTION_ACTIONS
    assert both <= ACTIONS and not (both & MONEY_WRITE_ACTIONS)
    assert all(is_significant_action(a) for a in both)            # denials are audited
    holders = {r for r, acts in PERMISSION_MATRIX.items() if acts & SUBCONTRACTOR_ADVANCE_ACTIONS}
    assert holders == {"owner", "accountant"}                     # R39: not Admin
    holders = {r for r, acts in PERMISSION_MATRIX.items()
               if acts & SUBCONTRACTOR_ADVANCE_DEDUCTION_ACTIONS}
    assert holders == {"owner", "admin", "accountant"}            # as the payment (R14)
    # Admin keeps every other action of its full set
    assert PERMISSION_MATRIX["admin"] == frozenset(ACTIONS - SUBCONTRACTOR_ADVANCE_ACTIONS)


def test_the_routes_check_the_role_before_any_read_and_take_the_key():
    from app.routes import subcontractors as s
    for path, action, roles in (
            ("/api/subcontractor-packages/{pkg_id}/advances",
             "finance.subcontractor_advance.create", ("Owner", "Accountant")),
            ("/api/subcontractor-acts/{act_id}/advance-deduction",
             "subcontract.advance_deduction.execute", None)):
        route = _route(path)
        first = route.dependant.dependencies[0].call
        assert getattr(first, "sec01_action", None) == action, path
        assert "idempotency_key" in inspect.signature(route.endpoint).parameters, path
    assert s.ADVANCE_ROLES == ("Owner", "Accountant")
    src = inspect.getsource(s.create_subcontractor_advance)
    # validation before the first read; the ledger row before the package's advance total
    assert src.index("money_value(") < src.index("find_one(")
    # FG-114: the contract-value reservation is the FIRST write, before the ledger row
    assert src.index("_reserve_advance(") < src.index("finance_payments.insert_one")
    assert "ADVANCE_PACKAGE_VALUE_REQUIRED" in src
    assert "delete_one" not in inspect.getsource(s.deduct_advance_on_act)


def test_the_advance_ledger_row_is_not_hard_deleted():
    """After the merge of #70 (PAY-01): a payment is reversed, never deleted, and a row owned
    by another module is refused (FG-45). The advance's ledger row carries
    ``subcontractor_payment_id`` -> classified as the subcontractor module's row."""
    from app.services.payment_state import source_module
    from app.routes import finance
    assert source_module({"subcontractor_payment_id": "adv-1",
                          "subcontractor_advance": True}) == "subcontractor"
    assert finance._source_module_refusal({"subcontractor_payment_id": "adv-1"}) is not None
    assert "finance_payments.delete_one" not in inspect.getsource(finance)


def test_reason_rule():
    from fastapi import HTTPException
    from app.routes.subcontractors import _reason
    assert _reason("  Аванс по договор ") == "Аванс по договор"
    assert _reason(None, required=False) == ""
    for bad in (None, "", "   ", 5, "a" * 501, "x\x00y", "x\x1by", "x‮y", "x​y"):
        with pytest.raises(HTTPException) as exc:
            _reason(bad)
        assert exc.value.status_code == 422


def test_payable_counts_the_deducted_advance():
    from app.routes.subcontractors import _payable
    assert _payable(3000, {"paid_total": 2000, "advance_deducted_total": 1000}) == 0
    assert _payable(3200, {"paid_total": 2000, "advance_deducted_total": 1000}) == 200
    assert _payable(100, {"paid_total": 150}) == 0
    assert _payable(100, None) == 100


def test_the_package_screen_shows_the_advance_in_bulgarian():
    src = (REPO / "frontend" / "src" / "pages" / "ProjectOperationsPage.js").read_text("utf-8")
    for label in ("Аванси", "Приспаднато", "Остатък аванс", "Приспаднат аванс"):
        assert label in src, label
    assert "/advances" in src and "advance_deducted" in src


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
        return "SUB-ADV-01 needs a replica set (the oplog measures writes): --replSet rs0"
    return ""


@pytest.mark.skipif(bool(_real_refusal()), reason=_real_refusal() or "ok")
def test_a_fresh_real_mongo_run_follows_the_rules_in_every_mode(tmp_path):
    out = tmp_path / "results.json"
    run_in_child(os.environ["W0_03_REAL_MONGO_URL"], out)
    check_result(json.loads(out.read_text(encoding="utf-8")))


if __name__ == "__main__":
    sys.exit(main())
