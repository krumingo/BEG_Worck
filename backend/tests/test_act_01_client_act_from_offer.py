"""
ACT-01 — a client act takes price and quantity from the offer, keeps the remainder, and the
same quantity is never acted twice (FLOW-004, FG-106).

Package: ``docs/architecture/tasks/ACT-01_CLIENT_ACT_FROM_OFFER.md`` (branch
``claude/happy-meitner-bmcnel`` @ 7f27c11). Canon: FLOW-004 (BUSINESS LOCK) "Какво НЕ трябва
да позволява": an act above the contracted scope at fixed price, a different unit price
without an annex, additional work without a contractual basis, the same quantity acted
twice; FLOW-006; CLAUDE.md §7, §8, §14, §15; R14/R20 (money writes and client prices — the
finance roles only); R29 (a money write without ``Idempotency-Key`` -> 428).

What the harness does (``python tests/test_act_01_client_act_from_offer.py --harness``):

* two fresh scratch databases on a disposable LOCAL MongoDB replica set (the oplog says
  what a call wrote; transactions are real);
* the ST-01 fixtures (tenants A and B, real users, TenantMemberships and FLOW-002
  RoleAssignments, real JWT from ``/api/auth/login``) plus ACT-01 offers:
    O1  accepted, project P (tenant A):  L1 10 m2 @ 3+7 = 10.00;  L2 5 m3 @ 12+8 = 20.00
    O2  draft,    project P:             L3
    OX  accepted extra offer (offer_type "extra"), project P: LX 4 pcs @ 25.00
    OP2 accepted, project P2 (tenant A): LP2
    OB  accepted, project of tenant B:   LB
  and a pre-ACT-01 ("legacy") act on L2 with 4 of 5 m3 and number ACT-0007;
* the WHOLE application (``server.app``, startup hooks not run), every scenario below in
  PERMISSION_SERVICE_MODE off, shadow and enforce, each from the same seeded baseline;
* outbound HTTP goes to a closed local port.

The result is ``docs/evidence/ACT-01/results.json``; the tests below assert it (a fresh run
on real Mongo when ``W0_03_REAL_MONGO_URL`` is set, else the committed file).

    PYTHONPATH=. pytest tests/test_act_01_client_act_from_offer.py -v --noconftest -rs
    W0_03_REAL_MONGO_URL='mongodb://127.0.0.1:27019/?directConnection=true' \\
        PYTHONPATH=. pytest tests/test_act_01_client_act_from_offer.py -v --noconftest -rs
"""
from __future__ import annotations

import argparse
import asyncio
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
EVIDENCE = REPO / "docs" / "evidence" / "ACT-01"
RESULTS_JSON = EVIDENCE / "results.json"

MODES = ("off", "shadow", "enforce")
DB_PREFIX_OP, DB_PREFIX_SYS = "act01_op_", "act01_sys_"
SYNTH_PASSWORD = "ACT01-Synthetic-Pass-2026!"    # synthetic users of a scratch database
# Bookkeeping collections: a refused call may write these (denial AuditEvent in enforce,
# the FAILED state of an idempotency key) — never business data.
AUDIT = {"audit_events", "audit_logs", "audit_chain_heads", "audit_chain", "audit_idempotency"}
# The business collections an ACT-01 write may touch.
ACT_COLLECTIONS = ("client_acts", "client_act_line_totals", "org_counters")
FINANCE = ("owner", "admin", "accountant")
NON_FINANCE = ("requester", "technician", "viewer", "driver", "warehousekeeper")

# Offer lines: id -> (offer key, qty, material_unit_cost, labor_unit_cost)
LINES = {
    "L1": ("O1", 10.0, 3.0, 7.0),
    "L2": ("O1", 5.0, 12.0, 8.0),
    "L3": ("O2", 6.0, 1.0, 1.0),
    "LX": ("OX", 4.0, 20.0, 5.0),
    "LP2": ("OP2", 9.0, 2.0, 2.0),
    "LB": ("OB", 9.0, 2.0, 2.0),
    # Addendum A: two versions of one offer (OFF-0005); v2 clones v1 with new line ids, 10 -> 12
    "LV1": ("OV1", 10.0, 4.0, 6.0),
    "LV2": ("OV2", 12.0, 4.0, 6.0),
    # FG-121: an exact unit price with three decimals (5.000 + 7.345 = 12.345)
    "LD": ("OD", 100.0, 5.0, 7.345),
}
PRICE = {k: round(v[2] + v[3], 2) for k, v in LINES.items()}
CONCURRENT = 6


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parent / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _pm01():
    return _load("act01_pm01_helpers", "test_pm_01_permission_matrix.py")


def ids(fx_a: Dict[str, Any]) -> Dict[str, str]:
    """Stable ids of the ACT-01 records (per scratch database)."""
    return {k: "act01-%s" % k.lower() for k in
            ("O1", "O2", "OX", "OP2", "OB", "OV1", "OV2", "P2", "L1", "L2", "L3", "LX", "LP2",
             "LB", "LV1", "LV2", "LEGACY", "OD", "LD", "LEGACY2")}


async def seed_act01(op_db, fx: Dict[str, Any]) -> Dict[str, str]:
    """The offers, a second project of A and the legacy act (synthetic, marked st-01)."""
    i = ids(fx["A"])
    a, b = fx["A"], fx["B"]
    now = "2026-11-07T08:00:00+00:00"
    await op_db.projects.insert_one({"id": i["P2"], "org_id": a["tenant_id"], "code": "ACT01-P2",
                                     "name": "ACT-01 P2", "status": "Active",
                                     "created_at": now, "updated_at": now, "_st01_marker": "st-01"})
    offers = {
        "O1": (a["tenant_id"], a["project_id"], "Accepted", "main", "OFF-0001"),
        "O2": (a["tenant_id"], a["project_id"], "Draft", "main", "OFF-0002"),
        "OX": (a["tenant_id"], a["project_id"], "Accepted", "extra", "OFF-0003"),
        "OP2": (a["tenant_id"], i["P2"], "Accepted", "main", "OFF-0004"),
        "OB": (b["tenant_id"], b["project_id"], "Accepted", "main", "OFF-0001"),
        "OV1": (a["tenant_id"], a["project_id"], "Accepted", "main", "OFF-0005"),
        "OV2": (a["tenant_id"], a["project_id"], "Sent", "main", "OFF-0005"),   # accepted later
        "OD": (a["tenant_id"], a["project_id"], "Accepted", "main", "OFF-0006"),
    }
    versions = {"OV2": (2, "OV1")}
    vat = {"OX": 9}                          # FLOW-003: the act takes the offer's VAT
    for okey, (org, project, status, otype, number) in offers.items():
        lines = []
        for n, (lkey, (lo, qty, mat, lab)) in enumerate(sorted(LINES.items())):
            if lo != okey:
                continue
            lines.append({"id": i[lkey], "activity_code": lkey, "activity_name": "ACT-01 " + lkey,
                          "unit": "m2", "qty": qty, "material_unit_cost": mat,
                          "labor_unit_cost": lab, "line_material_cost": round(qty * mat, 2),
                          "line_labor_cost": round(qty * lab, 2),
                          "line_total": round(qty * (mat + lab), 2), "sort_order": n})
        subtotal = round(sum(x["line_total"] for x in lines), 2)
        await op_db.offers.insert_one({
            "id": i[okey], "org_id": org, "project_id": project, "offer_no": number,
            "title": "ACT-01 " + okey, "status": status, "offer_type": otype,
            "version": versions.get(okey, (1, None))[0],
            "parent_offer_id": i[versions[okey][1]] if okey in versions else None,
            "currency": "EUR", "vat_percent": vat.get(okey, 20), "lines": lines,
            "subtotal": subtotal, "vat_amount": round(subtotal * vat.get(okey, 20) / 100, 2),
            "total": round(subtotal * (100 + vat.get(okey, 20)) / 100, 2),
            "created_at": now, "updated_at": now, "_st01_marker": "st-01"})
    # A pre-ACT-01 act: 4 of the 5 m3 of L2 are already acted (Draft), number ACT-0007.
    await op_db.client_acts.insert_one({
        "id": i["LEGACY"], "org_id": a["tenant_id"], "project_id": a["project_id"],
        "source_offer_id": i["O1"], "act_number": "ACT-0007", "act_date": "2026-10-01",
        "lines": [{"id": "act01-legacy-line", "offer_line_id": i["L2"], "activity_name": "L2",
                   "unit": "m3", "contracted_qty": 5.0, "executed_qty": 4.0,
                   "executed_percent": 80.0, "unit_price": 20.0, "line_total": 80.0,
                   "sort_order": 0}],
        "subtotal": 80.0, "vat_percent": 20, "vat_amount": 16.0, "total": 96.0,
        "currency": "EUR", "status": "Draft", "created_at": "2026-10-01T08:00:00+00:00",
        "updated_at": "2026-10-01T08:00:00+00:00", "created_by": a["users"]["admin"]["id"],
        "_st01_marker": "st-01"})
    # A pre-ACT-01 draft with a free-text line (no offer line), number ACT-0006.
    await op_db.client_acts.insert_one({
        "id": i["LEGACY2"], "org_id": a["tenant_id"], "project_id": a["project_id"],
        "source_offer_id": None, "act_number": "ACT-0006", "act_date": "2026-10-02",
        "lines": [{"id": "act01-legacy2-line", "offer_line_id": None, "activity_name": "free",
                   "unit": "m2", "contracted_qty": 0, "executed_qty": 3.0, "unit_price": 50.0,
                   "line_total": 150.0, "sort_order": 0}],
        "subtotal": 150.0, "vat_percent": 20, "vat_amount": 30.0, "total": 180.0,
        "currency": "EUR", "status": "Draft", "created_at": "2026-10-02T08:00:00+00:00",
        "updated_at": "2026-10-02T08:00:00+00:00", "created_by": a["users"]["admin"]["id"],
        "_st01_marker": "st-01"})
    return i


# ═══════════════════════════════════════════════════════════════════════ the harness
def run_harness(mongo_url: str, out_json: Path, modes=MODES) -> Dict[str, Any]:
    op_name, sys_name = os.environ["DB_NAME"], os.environ["BEG_SYSTEM_DB"]
    assert op_name.startswith(DB_PREFIX_OP) and sys_name.startswith(DB_PREFIX_SYS)
    pm = _pm01()
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
        i = tc.portal.call(lambda: seed_act01(op_db, fx))
        # ACT77-01: the ACT-01 collections are NOT pre-created — a fresh tenant has none.
        for name in ("audit_idempotency", "audit_events"):
            if name not in tc.portal.call(lambda: op_db.list_collection_names()):
                tc.portal.call(lambda: op_db.create_collection(name))
        def reindex():
            tc.portal.call(lambda: op_db.audit_events.create_index(
                [("tenant_id", 1), ("sequence", 1)], unique=True))
            tc.portal.call(lambda: op_db.audit_events.create_index([("event_id", 1)], unique=True))
            try:
                from app.services import client_acts as svc
                tc.portal.call(lambda: svc.ensure_indexes(op_db))
            except ImportError:
                pass
        # The W0-04 unique indexes of the key registry, as in a bootstrapped tenant.
        tc.portal.call(lambda: op_db.audit_idempotency.create_index([("id", 1)], unique=True))
        tc.portal.call(lambda: op_db.audit_idempotency.create_index(
            [("tenant_id", 1), ("action", 1), ("key", 1)], unique=True))
        # ... and of the audit chain: concurrent acts append concurrently.
        tc.portal.call(lambda: op_db.audit_events.create_index(
            [("tenant_id", 1), ("sequence", 1)], unique=True))
        tc.portal.call(lambda: op_db.audit_events.create_index([("event_id", 1)], unique=True))
        # ACT-01 indexes (server startup creates them; startup hooks are not run here).
        try:
            from app.services import client_acts as ca_service
            tc.portal.call(lambda: ca_service.ensure_indexes(op_db))
            have_service = True
        except ImportError:                       # main: no ACT-01 service
            have_service = False
        tokens: Dict[str, str] = {}
        for key in FINANCE + NON_FINANCE:
            r = tc.post("/api/auth/login", json={
                "email": fx["A"]["users"][key]["email"], "password": SYNTH_PASSWORD})
            assert r.status_code == 200, (key, r.status_code, r.text[:200])
            tokens[key] = r.json()["token"]
        r = tc.post("/api/auth/login", json={"email": fx["B"]["users"]["admin"]["email"],
                                             "password": SYNTH_PASSWORD})
        tokens["admin_b"] = r.json()["token"]
        snap = tc.portal.call(lambda: pm._snapshot(client, dbs))
        project = fx["A"]["project_id"]

        def hdr(role, key: Optional[str] = "auto"):
            h = {"Authorization": "Bearer " + tokens[role]}
            if key == "auto":
                key = uuid.uuid4().hex
            if key is not None:
                h["Idempotency-Key"] = key
            return h

        def call(method, url, role="admin", body=None, key: Optional[str] = "auto"):
            before = tc.portal.call(lambda: pm._last_ts(oplog))
            resp = tc.request(method, url, json=body, headers=hdr(role, key))
            written = tc.portal.call(lambda: pm._writes_since(oplog, before, dbs))
            try:
                payload = resp.json()
            except Exception:                                     # noqa: BLE001
                payload = resp.text[:300]
            detail = payload.get("detail") if isinstance(payload, dict) else None
            return {"status": resp.status_code,
                    "business_written": sorted({short(n) for n in written
                                                if n.split(".", 1)[1] not in AUDIT}),
                    "written": sorted({short(n) for n in written}),
                    "error_code": detail.get("error_code") if isinstance(detail, dict) else None,
                    "message": (detail.get("message") if isinstance(detail, dict) else detail),
                    "body": payload}

        def line(lkey, qty, **extra):
            return {"offer_line_id": i[lkey], "activity_name": "ACT-01 " + lkey, "unit": "m2",
                    "executed_qty": qty, **extra}

        def act_body(*lines, **extra):
            return {"project_id": project, "lines": list(lines), **extra}

        def post_act(body, role="admin", key: Optional[str] = "auto"):
            return call("POST", "/api/client-acts", role, body, key)

        def acts_on(lkey) -> float:
            async def q():
                total = 0.0
                async for a in op_db.client_acts.find({"org_id": fx["A"]["tenant_id"]}):
                    for ln in a.get("lines") or []:
                        if ln.get("offer_line_id") == i[lkey]:
                            total += float(ln.get("executed_qty") or 0)
                return round(total, 4)
            return tc.portal.call(q)

        def value_on(lkey) -> float:
            """Σ line_total of every act on one offer line (Decimal, to the cent)."""
            from decimal import Decimal
            async def q():
                total = Decimal(0)
                async for a in op_db.client_acts.find({"org_id": fx["A"]["tenant_id"]}):
                    for ln in a.get("lines") or []:
                        if ln.get("offer_line_id") == i[lkey]:
                            total += Decimal(str(ln.get("line_total") or 0))
                return float(total)
            return tc.portal.call(q)

        def count(coll, flt=None) -> int:
            return tc.portal.call(lambda: op_db[coll].count_documents(flt or {}))

        def audit_actions(entity_id) -> List[str]:
            async def q():
                rows = await op_db.audit_events.find(
                    {"entity_id": entity_id}, {"_id": 0, "action": 1}).to_list(None)
                return [r["action"] for r in rows]
            return tc.portal.call(q)

        def restore():
            tc.portal.call(lambda: pm._restore(client, snap, sorted(set(snap) | {
                "%s.%s" % (op_name, c) for c in ACT_COLLECTIONS + ("audit_events",
                                                                    "audit_idempotency")})))

        def concurrent(bodies, role="admin"):
            async def go():
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(transport=transport, base_url="http://act01") as c:
                    return await asyncio.gather(*[
                        c.post("/api/client-acts", json=b, headers=hdr(role)) for b in bodies])
            responses = tc.portal.call(go)
            out = []
            for r in responses:
                try:
                    payload = r.json()
                except Exception:                                 # noqa: BLE001
                    payload = r.text[:200]
                out.append({"status": r.status_code,
                            "act_number": payload.get("act_number") if isinstance(payload, dict) else None})
            return out

        results: Dict[str, Any] = {"modes": {}}
        for mode in modes:
            os.environ["PERMISSION_SERVICE_MODE"] = mode
            res: Dict[str, Any] = {}

            def scenario(name, fn):
                restore()
                try:
                    res[name] = fn()
                except Exception as exc:                          # noqa: BLE001 — recorded
                    res[name] = {"exception": "%s: %s" % (type(exc).__name__, exc)}

            # 1. free price
            scenario("free_price", lambda: post_act(act_body(line("L1", 1, unit_price=999))))
            # 2/3. the offer's price, given or omitted
            scenario("price_given_equal", lambda: post_act(act_body(line("L1", 2, unit_price=10))))
            scenario("price_omitted", lambda: post_act(act_body(line("L1", 2))))
            # 4. no offer line
            scenario("no_offer_line", lambda: post_act(act_body(
                {"activity_name": "free text", "unit": "m2", "executed_qty": 1, "unit_price": 10})))
            # 5. above the remainder
            scenario("over_remaining", lambda: post_act(act_body(line("L1", 11))))
            # 6. partial acting up to the exact remainder, then nothing more
            def partial():
                steps = [post_act(act_body(line("L1", q))) for q in (3, 3, 4)]
                steps.append(post_act(act_body(line("L1", 0.5))))
                return {"steps": steps, "acted": acts_on("L1"),
                        "remaining": call("GET", "/api/client-acts/remaining/%s" % project,
                                          key=None)}
            scenario("partial", partial)
            # 7. the UI flow (from-offer 100 %) twice
            def double_from_offer():
                # OX (one line, LX 4 pcs): O1 cannot take 100 % — the legacy act holds L2.
                first = call("POST", "/api/client-acts/from-offer/%s" % i["OX"],
                             body={"percent": 100})
                second = call("POST", "/api/client-acts/from-offer/%s" % i["OX"],
                              body={"percent": 100})
                o1_full = call("POST", "/api/client-acts/from-offer/%s" % i["O1"],
                               body={"percent": 100})
                return {"first": first, "second": second, "acted_LX": acts_on("LX"),
                        "o1_full": o1_full, "acted_L1": acts_on("L1")}
            scenario("double_from_offer", double_from_offer)
            # 8. from-offer of a draft offer; a line of a draft offer
            scenario("from_draft_offer", lambda: call(
                "POST", "/api/client-acts/from-offer/%s" % i["O2"], body={"percent": 50}))
            scenario("draft_offer_line", lambda: post_act(act_body(line("L3", 1))))
            # 9. a line of another project of the same tenant
            scenario("other_project_line", lambda: post_act(act_body(line("LP2", 1))))
            # 10. tenant B's offer line / offer
            scenario("foreign_tenant_line", lambda: post_act(act_body(line("LB", 1))))
            scenario("foreign_tenant_offer", lambda: call(
                "POST", "/api/client-acts/from-offer/%s" % i["OB"], body={"percent": 10}))
            # 11. contracted quantity from the body
            scenario("contracted_qty_mismatch", lambda: post_act(act_body(
                line("L1", 1, contracted_qty=1000))))
            # 12. additional work with a contractual basis (accepted extra offer)
            scenario("extra_offer_line", lambda: post_act(act_body(line("LX", 4))))
            # 13. legacy act already holds 4 of 5 m3 of L2
            def legacy():
                over = post_act(act_body(line("L2", 2)))
                ok = post_act(act_body(line("L2", 1)))
                return {"over": over, "ok": ok, "acted_L2": acts_on("L2")}
            scenario("legacy_remaining", legacy)
            # 14. numbering: sequential acts after the legacy ACT-0007
            def numbering():
                a1 = post_act(act_body(line("L1", 1)))
                a2 = post_act(act_body(line("L1", 1)))
                return {"numbers": [a1["body"].get("act_number") if isinstance(a1["body"], dict) else None,
                                    a2["body"].get("act_number") if isinstance(a2["body"], dict) else None]}
            scenario("numbering", numbering)
            scenario("act_number_from_body", lambda: post_act(act_body(
                line("L1", 1), act_number="ACT-9999")))
            # 15. R29
            scenario("no_key", lambda: post_act(act_body(line("L1", 1)), key=None))
            def replay():
                k = uuid.uuid4().hex
                first = post_act(act_body(line("L1", 2)), key=k)
                again = post_act(act_body(line("L1", 2)), key=k)
                other = post_act(act_body(line("L1", 3)), key=k)
                return {"first": first, "again": again, "other": other,
                        "acts": count("client_acts", {"project_id": project}),
                        "acted_L1": acts_on("L1")}
            scenario("replay", replay)
            scenario("from_offer_no_key", lambda: call(
                "POST", "/api/client-acts/from-offer/%s" % i["O1"], body={"percent": 10},
                key=None))
            # 16. who may write
            def roles():
                out = {}
                for role in FINANCE + NON_FINANCE:
                    restore()
                    out[role] = {
                        "post": post_act(act_body(line("L1", 1)), role=role),
                        "from_offer": call("POST", "/api/client-acts/from-offer/%s" % i["O1"],
                                           role=role, body={"percent": 10}),
                        "put": call("PUT", "/api/client-acts/%s" % i["LEGACY"], role=role,
                                    body={"lines": [line("L2", 1)]}),
                        "remaining": call("GET", "/api/client-acts/remaining/%s" % project,
                                          role=role, key=None),
                    }
                return out
            scenario("roles", roles)
            # 17. concurrency: 6 acts x 10 on a 10 m2 line; 6 acts x 2 on the same line
            def race():
                big = concurrent([act_body(line("L1", 10)) for _ in range(CONCURRENT)])
                big_acted = acts_on("L1")
                restore()
                small = concurrent([act_body(line("L1", 2)) for _ in range(CONCURRENT)])
                return {"big": big, "big_acted": big_acted, "small": small,
                        "small_acted": acts_on("L1")}
            scenario("race", race)
            def race_numbers():
                bodies = [act_body(line("L1", 0.5)) for _ in range(CONCURRENT)]
                return {"responses": concurrent(bodies)}
            scenario("race_numbers", race_numbers)
            # 18. Draft edit moves the reservation by the difference, both ways
            def edit():
                created = post_act(act_body(line("L1", 4)))
                act_id = created["body"].get("id") if isinstance(created["body"], dict) else None
                up = call("PUT", "/api/client-acts/%s" % act_id, body={"lines": [line("L1", 6)]})
                after_up = acts_on("L1")
                down = call("PUT", "/api/client-acts/%s" % act_id, body={"lines": [line("L1", 2)]})
                after_down = acts_on("L1")
                other = post_act(act_body(line("L1", 8)))
                too_much = call("PUT", "/api/client-acts/%s" % act_id,
                                body={"lines": [line("L1", 3)]})
                price = call("PUT", "/api/client-acts/%s" % act_id,
                             body={"lines": [line("L1", 1, unit_price=999)]})
                no_key = call("PUT", "/api/client-acts/%s" % act_id,
                              body={"lines": [line("L1", 1)]}, key=None)
                return {"created": created, "up": up, "after_up": after_up, "down": down,
                        "after_down": after_down, "other": other, "too_much": too_much,
                        "price": price, "no_key": no_key, "final_acted": acts_on("L1"),
                        "audit": audit_actions(act_id)}
            scenario("edit", edit)
            # 19. an accepted act is not edited
            def accepted():
                created = post_act(act_body(line("L1", 1)))
                act_id = created["body"].get("id") if isinstance(created["body"], dict) else None
                conf = call("POST", "/api/client-acts/%s/confirm" % act_id)
                put = call("PUT", "/api/client-acts/%s" % act_id, body={"lines": [line("L1", 2)]})
                return {"confirm": conf, "put": put}
            scenario("accepted_not_edited", accepted)
            # 20. foreign tenant cannot edit / read A's act
            def foreign_edit():
                return {"put": call("PUT", "/api/client-acts/%s" % i["LEGACY"], role="admin_b",
                                    body={"lines": [line("LB", 1)]}),
                        "remaining": call("GET", "/api/client-acts/remaining/%s" % project,
                                          role="admin_b", key=None)}
            scenario("foreign_tenant_edit", foreign_edit)
            # 21. one canonical AuditEvent per create
            def audit():
                created = post_act(act_body(line("L1", 1)))
                act_id = created["body"].get("id") if isinstance(created["body"], dict) else None
                return {"created": created, "audit": audit_actions(act_id)}
            scenario("audit_create", audit)
            # 22. the act committed but marking the key COMPLETED failed: the retry of the
            #     same request finds that act (key-derived id) and writes nothing new
            def resume():
                from app.permissions import workflow
                original = workflow.RecoverableWrite.complete
                state = {"armed": True}

                async def failing(self, ref):
                    if state["armed"]:
                        state["armed"] = False
                        raise RuntimeError("injected: complete() lost after the commit")
                    return await original(self, ref)
                workflow.RecoverableWrite.complete = failing
                try:
                    k = uuid.uuid4().hex
                    first = post_act(act_body(line("L1", 3)), key=k)
                    acted_after_first = acts_on("L1")
                    retry = post_act(act_body(line("L1", 3)), key=k)
                finally:
                    workflow.RecoverableWrite.complete = original
                return {"first": first, "acted_after_first": acted_after_first, "retry": retry,
                        "acted": acts_on("L1"),
                        "acts": count("client_acts", {"project_id": project})}
            scenario("resume_after_commit", resume)
            # 23. addendum A: versions of one offer are one scope
            def versions():
                v1_first = post_act(act_body(line("LV1", 6)))            # v1 the only accepted
                v2_not_accepted = post_act(act_body(line("LV2", 1)))     # v2 still Sent
                tc.portal.call(lambda: op_db.offers.update_one(
                    {"id": i["OV2"]}, {"$set": {"status": "Accepted",
                                                "accepted_at": "2026-11-07T09:00:00+00:00"}}))
                v1_after = post_act(act_body(line("LV1", 1)))            # superseded
                v2_after = post_act(act_body(line("LV2", 1)))            # no line lineage
                v1_id = v1_first["body"].get("id") if isinstance(v1_first["body"], dict) else None
                release = call("PUT", "/api/client-acts/%s" % v1_id,
                               body={"lines": [line("LV1", 4)]})          # releasing is allowed
                grow = call("PUT", "/api/client-acts/%s" % v1_id, body={"lines": [line("LV1", 5)]})
                from_v1 = call("POST", "/api/client-acts/from-offer/%s" % i["OV1"],
                               body={"percent": 10})
                extra = post_act(act_body(line("LX", 1)))                # own cap
                return {"v1_first": v1_first, "v2_not_accepted": v2_not_accepted,
                        "v1_after": v1_after, "v2_after": v2_after, "release": release,
                        "grow": grow, "from_v1": from_v1, "extra": extra,
                        "acted_LV1": acts_on("LV1"), "acted_LV2": acts_on("LV2")}
            scenario("offer_versions", versions)
            # 25. FG-119: confirm is a finance-only, keyed, transactional, audited transition
            def confirm():
                out = {}
                created_ = post_act(act_body(line("L1", 2)))
                act_id = created_["body"].get("id") if isinstance(created_["body"], dict) else None
                for role in NON_FINANCE:
                    out["role_" + role] = call("POST", "/api/client-acts/%s/confirm" % act_id,
                                               role=role)
                out["no_key"] = call("POST", "/api/client-acts/%s/confirm" % act_id, key=None)
                k = uuid.uuid4().hex
                out["ok"] = call("POST", "/api/client-acts/%s/confirm" % act_id, role="accountant",
                                 key=k)
                out["replay"] = call("POST", "/api/client-acts/%s/confirm" % act_id,
                                     role="accountant", key=k)
                out["again"] = call("POST", "/api/client-acts/%s/confirm" % act_id)
                out["audit"] = audit_actions(act_id)
                out["legacy_free_line"] = call("POST", "/api/client-acts/%s/confirm" % i["LEGACY2"])
                out["legacy_linked"] = call("POST", "/api/client-acts/%s/confirm" % i["LEGACY"])
                out["foreign"] = call("POST", "/api/client-acts/%s/confirm" % act_id, role="admin_b")
                return out
            scenario("confirm", confirm)
            # 26. FG-119 + addendum A: a draft on v1 is not confirmed after v2 is accepted
            def confirm_superseded():
                draft = post_act(act_body(line("LV1", 2)))
                act_id = draft["body"].get("id") if isinstance(draft["body"], dict) else None
                tc.portal.call(lambda: op_db.offers.update_one(
                    {"id": i["OV2"]}, {"$set": {"status": "Accepted"}}))
                return {"draft": draft,
                        "confirm": call("POST", "/api/client-acts/%s/confirm" % act_id),
                        "remaining": call("GET", "/api/client-acts/remaining/%s" % project, key=None)}
            scenario("confirm_superseded", confirm_superseded)
            # 27. FG-121: the exact offer price 12.345 x 100
            scenario("exact_price", lambda: post_act(act_body(line("LD", 100))))
            scenario("rounded_price", lambda: post_act(act_body(line("LD", 1, unit_price=12.35))))
            # 28. FG-122: readers without the money right see quantities only
            def readers():
                created_ = post_act(act_body(line("L1", 2)))
                act_id = created_["body"].get("id") if isinstance(created_["body"], dict) else None
                out = {}
                for role in FINANCE + NON_FINANCE:
                    out[role] = {"list": call("GET", "/api/client-acts?project_id=%s" % project,
                                              role=role, key=None),
                                 "detail": call("GET", "/api/client-acts/%s" % act_id, role=role,
                                                key=None)}
                return out
            scenario("readers", readers)
            # 29. FG-123: v2 is accepted AFTER the act's transaction took its snapshot (it still
            #     sees v2 "Sent") and BEFORE it commits -> the act on v1 must not commit
            def version_race():
                from app.services import client_acts as svc
                original = svc.guard_offer_family
                state = {"armed": True}

                async def accept_meanwhile(tenant, offer, session):
                    if state["armed"]:
                        state["armed"] = False
                        await op_db.offers.update_one({"id": i["OV2"]},
                                                      {"$set": {"status": "Accepted"}})
                    return await original(tenant, offer, session)
                svc.guard_offer_family = accept_meanwhile
                try:
                    res = post_act(act_body(line("LV1", 1)))
                finally:
                    svc.guard_offer_family = original
                return {"act": res, "fired": not state["armed"], "acted_LV1": acts_on("LV1")}
            scenario("version_race", version_race)
            # 30. ACT77-01: a FRESH tenant (no client_act_line_totals, no org_counters yet):
            #     10 concurrent first acts — no 500 from the implicit collection creation
            def fresh_tenant():
                def drop():
                    # every collection the act transaction writes; none exists in a new tenant
                    for name in ("client_act_line_totals", "org_counters", "client_acts",
                                 "audit_events"):
                        tc.portal.call(lambda: op_db.drop_collection(name))
                drop()
                # lines of three different offers: the offer-family guard (FG-123) does not
                # serialise them, so they meet at the implicit collection creation
                mix = [("L1", 1), ("LX", 1), ("LD", 1)]
                small = concurrent([act_body(line(*mix[n % 3])) for n in range(10)])
                small_acted = acts_on("L1") + acts_on("LX") + acts_on("LD")
                restore()
                drop()
                big = concurrent([act_body(line("L1", 10)) for _ in range(10)])
                out = {"small": small, "small_acted": small_acted, "big": big,
                       "big_acted": acts_on("L1")}
                restore()
                reindex()               # the dropped collections lost their indexes
                return out
            scenario("fresh_tenant", fresh_tenant)
            # 31. FG-131 (addendum C): cumulative rounding — acts on a line add up to exactly
            #     round(quantity x 12.345); never 1234.51 for 1234.50
            def cumulative():
                parts = [post_act(act_body(line("LD", n))) for n in (33, 33, 34)]
                three = {"statuses": [p_["status"] for p_ in parts],
                         "values": [p_["body"]["lines"][0]["line_total"]
                                    if isinstance(p_["body"], dict) and p_["body"].get("lines")
                                    else None for p_ in parts],
                         "sum": value_on("LD"), "acted": acts_on("LD")}
                restore()
                ones = [post_act(act_body(line("LD", 1)))["status"] for _ in range(100)]
                hundred = {"statuses": sorted(set(ones)), "sum": value_on("LD"),
                           "acted": acts_on("LD")}
                restore()
                conc = concurrent([act_body(line("LD", 10)) for _ in range(10)])
                concurrent_ = {"statuses": sorted(x["status"] for x in conc),
                               "sum": value_on("LD"), "acted": acts_on("LD")}
                restore()
                a1 = post_act(act_body(line("LD", 33)))
                a2 = post_act(act_body(line("LD", 33)))
                a1_id = a1["body"].get("id") if isinstance(a1["body"], dict) else None
                down = call("PUT", "/api/client-acts/%s" % a1_id, body={"lines": [line("LD", 30)]})
                after_down = {"sum": value_on("LD"), "acted": acts_on("LD")}
                up = call("PUT", "/api/client-acts/%s" % a1_id, body={"lines": [line("LD", 41)]})
                last = post_act(act_body(line("LD", 26)))               # 41 + 33 + 26 = 100
                edits = {"statuses": [a1["status"], a2["status"], down["status"], up["status"],
                                      last["status"]],
                         "after_down": after_down, "sum": value_on("LD"), "acted": acts_on("LD")}
                return {"three": three, "hundred": hundred, "concurrent": concurrent_,
                        "edits": edits}
            scenario("cumulative_rounding", cumulative)
            # 24. the answer shows contracted / acted / remaining per line
            scenario("line_view", lambda: post_act(act_body(line("L1", 3))))
            results["modes"][mode] = res
        os.environ["PERMISSION_SERVICE_MODE"] = "off"

    results["meta"] = {"schema": "beg.act-01-results/v1", "modes": list(modes),
                       "seconds": round(time.time() - started, 1),
                       "service_present": have_service,
                       "mongo": "local replica set (oplog, transactions)",
                       "caller_tenant": "A (ST-01 synthetic)", "outbound_http": "closed local port"}
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(results, indent=1, ensure_ascii=False, sort_keys=True,
                                   default=str) + "\n", encoding="utf-8")
    return results


def run_in_child(mongo_url: str, out_json: Path, timeout: int = 3600) -> None:
    pm = _pm01()
    suffix = uuid.uuid4().hex[:12]
    op_name, sys_name = DB_PREFIX_OP + suffix, DB_PREFIX_SYS + suffix
    cmd = [sys.executable, str(Path(__file__).resolve()), "--child", "--mongo-url", mongo_url,
           "--out-json", str(out_json)]
    env = pm.child_env(mongo_url, op_name, sys_name)
    env["JWT_SECRET"] = "act01-local-" + uuid.uuid4().hex
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
    parser = argparse.ArgumentParser(description="ACT-01 client act harness")
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


# ═════════════════════════════════════════════════════════════════════════════ tests
def _real_refusal() -> str:
    return _pm01()._real_refusal()


_CACHE: Dict[str, Any] = {}


def results() -> Dict[str, Any]:
    """A fresh run on the real replica set when one is given, else the committed file."""
    if "r" not in _CACHE:
        given = os.environ.get("ACT01_RESULTS_FILE")   # evaluate a recorded run (red proof)
        if given:
            _CACHE["r"] = json.loads(Path(given).read_text(encoding="utf-8"))
        elif not _real_refusal():
            out = Path(os.environ.get("TMPDIR", "/tmp")) / ("act01-%s.json" % uuid.uuid4().hex)
            run_in_child(os.environ["W0_03_REAL_MONGO_URL"], out)
            _CACHE["r"] = json.loads(out.read_text(encoding="utf-8"))
            out.unlink()
        else:
            if not RESULTS_JSON.exists():
                pytest.skip("no committed ACT-01 results and no W0_03_REAL_MONGO_URL")
            _CACHE["r"] = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    return _CACHE["r"]


@pytest.fixture(params=MODES)
def r(request):
    return results()["modes"][request.param]


def nothing(cell) -> None:
    assert not cell.get("business_written"), cell


def created(cell) -> Dict[str, Any]:
    assert cell["status"] == 201, cell
    return cell["body"]


# ── red on main ────────────────────────────────────────────────────────────────────
def test_a_free_unit_price_is_refused(r):
    cell = r["free_price"]
    assert cell["status"] == 422 and cell["error_code"] == "UNIT_PRICE_MISMATCH", cell
    nothing(cell)


def test_the_unit_price_comes_from_the_offer(r):
    for name in ("price_given_equal", "price_omitted"):
        body = created(r[name])
        ln = body["lines"][0]
        assert ln["unit_price"] == 10.0 and ln["contracted_qty"] == 10.0, ln
        assert ln["line_total"] == round(ln["executed_qty"] * 10.0, 2), ln


def test_a_line_without_an_offer_line_is_refused(r):
    cell = r["no_offer_line"]
    assert cell["status"] == 422 and cell["error_code"] == "OFFER_LINE_REQUIRED", cell
    nothing(cell)


def test_an_act_above_the_remainder_is_refused(r):
    cell = r["over_remaining"]
    assert cell["status"] == 409 and cell["error_code"] == "ACT_EXCEEDS_REMAINING", cell
    nothing(cell)


def test_the_same_quantity_is_not_acted_twice_through_the_ui_flow(r):
    cell = r["double_from_offer"]
    created(cell["first"])
    assert cell["second"]["status"] == 409, cell["second"]
    assert cell["second"]["error_code"] == "ACT_EXCEEDS_REMAINING"
    nothing(cell["second"])
    assert cell["acted_LX"] == 4.0
    # 100 % of O1 would act L2 twice (the legacy act holds 4 of 5): the whole act is refused.
    assert cell["o1_full"]["status"] == 409, cell["o1_full"]
    nothing(cell["o1_full"])
    assert cell["acted_L1"] == 0.0


def test_concurrent_acts_never_exceed_the_offer_quantity(r):
    race = r["race"]
    assert [x["status"] for x in race["big"]].count(201) == 1, race["big"]
    assert all(x["status"] in (201, 409) for x in race["big"]), race["big"]
    assert race["big_acted"] == 10.0
    assert [x["status"] for x in race["small"]].count(201) == 5, race["small"]
    assert race["small_acted"] == 10.0


def test_concurrent_acts_get_unique_numbers(r):
    resp = r["race_numbers"]["responses"]
    assert all(x["status"] == 201 for x in resp), resp
    numbers = [x["act_number"] for x in resp]
    assert len(set(numbers)) == CONCURRENT, numbers


def test_a_money_write_without_idempotency_key_is_refused(r):
    for name in ("no_key", "from_offer_no_key"):
        cell = r[name]
        assert cell["status"] == 428 and cell["error_code"] == "IDEMPOTENCY_KEY_REQUIRED", cell
        assert not cell["written"], cell
    assert r["edit"]["no_key"]["status"] == 428, r["edit"]["no_key"]


def test_roles_without_the_right_write_nothing(r):
    for role in NON_FINANCE:
        for op in ("post", "from_offer", "put"):
            cell = r["roles"][role][op]
            assert cell["status"] == 403, (role, op, cell)
            nothing(cell)


def test_offer_lines_of_a_draft_offer_another_project_or_tenant_are_refused(r):
    for name in ("draft_offer_line", "other_project_line", "foreign_tenant_line"):
        cell = r[name]
        assert cell["status"] == 422 and cell["error_code"] == "OFFER_LINE_NOT_FOUND", (name, cell)
        nothing(cell)
    cell = r["from_draft_offer"]
    assert cell["status"] == 422 and cell["error_code"] == "OFFER_NOT_ACCEPTED", cell
    nothing(cell)
    cell = r["foreign_tenant_offer"]
    assert cell["status"] == 404, cell
    nothing(cell)


def test_contracted_quantity_comes_from_the_offer(r):
    cell = r["contracted_qty_mismatch"]
    assert cell["status"] == 422 and cell["error_code"] == "CONTRACTED_QTY_MISMATCH", cell
    nothing(cell)


def test_the_act_number_is_assigned_by_the_server(r):
    cell = r["act_number_from_body"]
    assert cell["status"] == 422 and cell["error_code"] == "ACT_NUMBER_SERVER_ASSIGNED", cell
    nothing(cell)
    assert r["numbering"]["numbers"] == ["ACT-0008", "ACT-0009"], r["numbering"]


# ── positive ───────────────────────────────────────────────────────────────────────
def test_partial_acting_in_three_acts_reaches_the_exact_remainder(r):
    steps = r["partial"]["steps"]
    for cell in steps[:3]:
        created(cell)
    assert steps[3]["status"] == 409 and steps[3]["error_code"] == "ACT_EXCEEDS_REMAINING"
    nothing(steps[3])
    assert r["partial"]["acted"] == 10.0
    rem = r["partial"]["remaining"]
    assert rem["status"] == 200, rem
    by_line = {x["offer_line_id"]: x for x in rem["body"]["lines"]}
    l1 = by_line["act01-l1"]
    assert (l1["contracted_qty"], l1["acted_qty"], l1["remaining_qty"]) == (10.0, 10.0, 0.0), l1
    assert (l1["contracted_value"], l1["acted_value"], l1["remaining_value"]) == (100.0, 100.0, 0.0)
    l2 = by_line["act01-l2"]       # the legacy act counts
    assert (l2["acted_qty"], l2["remaining_qty"]) == (4.0, 1.0), l2


def test_additional_work_with_an_accepted_extra_offer_is_acted(r):
    body = created(r["extra_offer_line"])
    assert body["lines"][0]["unit_price"] == 25.0


def test_an_act_made_before_act_01_counts_against_the_remainder(r):
    cell = r["legacy_remaining"]
    assert cell["over"]["status"] == 409, cell["over"]
    nothing(cell["over"])
    created(cell["ok"])
    assert cell["acted_L2"] == 5.0


def test_a_replay_returns_the_same_answer_and_writes_nothing(r):
    cell = r["replay"]
    first = created(cell["first"])
    assert cell["again"]["status"] == 201 and cell["again"]["body"] == first, cell["again"]
    nothing(cell["again"])
    assert cell["other"]["status"] == 409, cell["other"]
    assert cell["other"]["error_code"] == "IDEMPOTENCY_CONFLICT"
    nothing(cell["other"])
    assert cell["acts"] == 3 and cell["acted_L1"] == 2.0     # the two legacy acts + one


def test_the_finance_roles_may_write(r):
    for role in FINANCE:
        for op in ("post", "from_offer", "put"):
            cell = r["roles"][role][op]
            assert cell["status"] in (200, 201), (role, op, cell)
        assert r["roles"][role]["remaining"]["status"] == 200


def test_the_remainder_view_is_finance_only(r):
    for role in NON_FINANCE:
        cell = r["roles"][role]["remaining"]
        assert cell["status"] == 403, (role, cell)


def test_the_answer_shows_contracted_acted_and_remaining_per_line(r):
    ln = created(r["line_view"])["lines"][0]
    assert (ln["contracted_qty"], ln["acted_qty_total"], ln["remaining_qty"]) == (10.0, 3.0, 7.0), ln
    assert (ln["contracted_value"], ln["acted_value_total"], ln["remaining_value"]) == (100.0, 30.0, 70.0)


def test_a_retry_after_a_committed_but_unacknowledged_act_writes_no_second_act(r):
    cell = r["resume_after_commit"]
    assert cell["first"]["status"] == 500, cell["first"]           # the injected failure
    assert cell["acted_after_first"] == 3.0                         # the act did commit
    body = created(cell["retry"])
    assert body["lines"][0]["executed_qty"] == 3.0
    assert not [n for n in cell["retry"]["business_written"] if n != "op.audit_events"], cell
    assert cell["acted"] == 3.0 and cell["acts"] == 3, cell         # 2 legacy acts + one


def test_only_the_latest_accepted_version_of_an_offer_is_acted(r):
    """ACT-01 addendum A (FLOW-003 "Версии", FLOW-005)."""
    v = r["offer_versions"]
    created(v["v1_first"])
    # v2 not accepted yet: its lines are no basis at all
    assert v["v2_not_accepted"]["status"] == 422, v["v2_not_accepted"]
    assert v["v2_not_accepted"]["error_code"] == "OFFER_LINE_NOT_FOUND"
    for name, code in (("v1_after", "OFFER_VERSION_SUPERSEDED"), ("grow", "OFFER_VERSION_SUPERSEDED"),
                       ("from_v1", "OFFER_VERSION_SUPERSEDED"),
                       ("v2_after", "OFFER_VERSION_LINEAGE_UNKNOWN")):
        assert v[name]["status"] == 409 and v[name]["error_code"] == code, (name, v[name])
        nothing(v[name])
    assert v["release"]["status"] == 200, v["release"]
    assert v["acted_LV1"] == 4.0 and v["acted_LV2"] == 0.0, v
    created(v["extra"])                                      # an additional offer: own cap


def test_vat_and_currency_come_from_the_accepted_offer(r):
    body = created(r["extra_offer_line"])                    # OX: 4 x 25.00, VAT 9 %
    assert (body["subtotal"], body["vat_percent"], body["vat_amount"], body["total"]) == \
        (100.0, 9.0, 9.0, 109.0), body
    assert body["currency"] == "EUR" and body["lines"][0]["vat_percent"] == 9.0
    other = created(r["line_view"])                          # O1: 20 %
    assert (other["vat_percent"], other["vat_amount"]) == (20.0, 6.0), other


def test_confirm_is_a_finance_keyed_transactional_audited_transition(r):
    """FG-119 (addendum B)."""
    c = r["confirm"]
    for role in NON_FINANCE:
        assert c["role_" + role]["status"] == 403, (role, c["role_" + role])
        nothing(c["role_" + role])
    assert c["no_key"]["status"] == 428 and not c["no_key"]["written"], c["no_key"]
    assert c["ok"]["status"] == 200 and c["ok"]["body"]["status"] == "Accepted", c["ok"]
    assert c["replay"]["status"] == 200 and c["replay"]["body"] == c["ok"]["body"]
    nothing(c["replay"])
    assert c["again"]["status"] == 400 and c["again"]["error_code"] == "ACT_NOT_DRAFT"
    nothing(c["again"])
    assert c["audit"] == ["client_act.created", "client_act.confirmed"], c["audit"]
    assert c["legacy_free_line"]["status"] == 422, c["legacy_free_line"]
    assert c["legacy_free_line"]["error_code"] == "OFFER_LINE_REQUIRED"
    nothing(c["legacy_free_line"])
    assert c["legacy_linked"]["status"] == 200, c["legacy_linked"]   # 4 of 5 m3, price 20.00
    assert c["foreign"]["status"] == 404 and not c["foreign"]["business_written"]


def test_a_draft_on_a_superseded_version_is_not_confirmed(r):
    cs = r["confirm_superseded"]
    created(cs["draft"])
    assert cs["confirm"]["status"] == 409, cs["confirm"]
    assert cs["confirm"]["error_code"] == "OFFER_VERSION_SUPERSEDED"
    nothing(cs["confirm"])


def test_the_remainder_view_shows_the_active_version_only(r):
    """FG-120: never v1 + v2 caps added; with no line lineage, no remainder is invented."""
    rem = r["confirm_superseded"]["remaining"]
    assert rem["status"] == 200, rem
    by_line = {x["offer_line_id"]: x for x in rem["body"]["lines"]}
    assert "act01-lv1" not in by_line                       # the superseded version
    lv2 = by_line["act01-lv2"]
    assert lv2["contracted_qty"] == 12.0 and lv2["remaining_qty"] is None, lv2
    assert lv2["acting_blocked"] == "OFFER_VERSION_LINEAGE_UNKNOWN"
    old = {x["offer_line_id"]: x for x in rem["body"]["acted_on_superseded_versions"]}
    assert old["act01-lv1"]["acted_qty"] == 2.0, old
    assert by_line["act01-l1"]["acting_blocked"] is None    # other offers unaffected


def test_the_exact_offer_unit_price_is_used(r):
    """FG-121: 12.345 x 100 = 1234.50 (not 12.35 x 100 = 1235.00)."""
    ln = created(r["exact_price"])["lines"][0]
    assert ln["unit_price"] == 12.345 and ln["line_total"] == 1234.5, ln
    cell = r["rounded_price"]
    assert cell["status"] == 422 and cell["error_code"] == "UNIT_PRICE_MISMATCH", cell
    nothing(cell)


def test_readers_without_the_money_right_see_quantities_only(r):
    """FG-122 (R20)."""
    for role in FINANCE + NON_FINANCE:
        for op in ("list", "detail"):
            cell = r["readers"][role][op]
            assert cell["status"] == 200, (role, op, cell)
            acts = cell["body"] if op == "list" else [cell["body"]]
            assert acts, (role, op)
            for act in acts:
                money_keys = {"subtotal", "vat_amount", "total"} & set(act)
                line_money = {k for ln in act["lines"] for k in ln
                              if k in ("unit_price", "line_total", "contracted_value",
                                       "acted_value_total", "remaining_value")}
                if role in FINANCE:
                    assert money_keys == {"subtotal", "vat_amount", "total"}, (role, act)
                else:
                    assert not money_keys and not line_money, (role, op, money_keys, line_money)
                    assert all("executed_qty" in ln for ln in act["lines"]), act


def test_a_version_accepted_during_the_act_transaction_blocks_the_act(r):
    """FG-123: the version check and the act commit as one (the family is written in the
    transaction, so a concurrent accept forces a retry that sees it)."""
    vr = r["version_race"]
    assert vr["fired"], vr
    assert vr["act"]["status"] == 409, vr["act"]
    assert vr["act"]["error_code"] == "OFFER_VERSION_SUPERSEDED"
    assert vr["acted_LV1"] == 0.0


def test_a_fresh_tenant_takes_concurrent_first_acts_without_errors(r):
    """ACT77-01: the collections are created outside the act transaction."""
    f = r["fresh_tenant"]
    assert [x["status"] for x in f["small"]] == [201] * 10, f["small"]
    assert len({x["act_number"] for x in f["small"]}) == 10, f["small"]
    assert f["small_acted"] == 10.0
    statuses = sorted(x["status"] for x in f["big"])
    assert statuses == [201] + [409] * 9, f["big"]
    assert f["big_acted"] == 10.0


def test_acts_on_a_line_add_up_to_exactly_the_offer_line_value(r):
    """FG-131 (addendum C): value = round(cum after x p) - round(cum before x p)."""
    c = r["cumulative_rounding"]
    t = c["three"]
    assert t["statuses"] == [201, 201, 201], t
    assert t["values"] == [407.39, 407.38, 419.73], t            # not 407.39 + 407.39 + 419.73
    assert t["sum"] == 1234.5 and t["acted"] == 100.0, t
    h = c["hundred"]
    assert h["statuses"] == [201] and h["sum"] == 1234.5 and h["acted"] == 100.0, h
    k = c["concurrent"]
    assert k["statuses"] == [201] * 10 and k["sum"] == 1234.5 and k["acted"] == 100.0, k
    e = c["edits"]
    assert e["statuses"] == [201, 201, 200, 200, 201], e
    assert e["after_down"]["acted"] == 63.0 and e["after_down"]["sum"] == 777.74, e  # round(63 x p)
    assert e["sum"] == 1234.5 and e["acted"] == 100.0, e


# ── correction ─────────────────────────────────────────────────────────────────────
def test_a_draft_edit_moves_the_reservation_by_the_difference(r):
    e = r["edit"]
    created(e["created"])
    assert e["up"]["status"] == 200 and e["after_up"] == 6.0, e["up"]
    assert e["down"]["status"] == 200 and e["after_down"] == 2.0, e["down"]
    created(e["other"])                                     # 2 + 8 = 10
    assert e["too_much"]["status"] == 409, e["too_much"]
    assert e["too_much"]["error_code"] == "ACT_EXCEEDS_REMAINING"
    nothing(e["too_much"])
    assert e["price"]["status"] == 422 and e["price"]["error_code"] == "UNIT_PRICE_MISMATCH"
    nothing(e["price"])
    assert e["final_acted"] == 10.0
    assert e["audit"] == ["client_act.created", "client_act.updated", "client_act.updated"], e


def test_an_accepted_act_is_not_edited(r):
    a = r["accepted_not_edited"]
    assert a["confirm"]["status"] == 200, a["confirm"]
    assert a["put"]["status"] == 400 and a["put"]["error_code"] == "ACT_NOT_DRAFT", a["put"]
    nothing(a["put"])


def test_another_tenant_cannot_edit_or_read_the_act(r):
    cell = r["foreign_tenant_edit"]
    assert cell["put"]["status"] == 404, cell["put"]
    nothing(cell["put"])
    rem = cell["remaining"]
    assert rem["status"] == 404, rem


def test_one_canonical_audit_event_per_create(r):
    a = r["audit_create"]
    created(a["created"])
    assert a["audit"] == ["client_act.created"], a


def test_the_three_modes_give_the_same_answers():
    res = results()["modes"]

    def statuses(m):
        out = {}
        for name, cell in res[m].items():
            out[name] = json.dumps(_statuses(cell), sort_keys=True)
        return out
    assert statuses("off") == statuses("shadow") == statuses("enforce")


def _statuses(cell):
    if isinstance(cell, dict):
        if "status" in cell:
            return cell["status"]
        return {k: _statuses(v) for k, v in cell.items()}
    if isinstance(cell, list):            # concurrent answers: order is not meaningful
        out = [_statuses(x) for x in cell]
        return sorted(out) if all(isinstance(x, int) for x in out) else out
    return None


# ── static (DB-free) ───────────────────────────────────────────────────────────────
def test_the_client_act_writes_declare_their_catalog_actions():
    from app.permissions import catalog
    for action in ("revenue.client_act.create", "finance.client_act.update",
                   "finance.client_act_from_offer.execute", "finance.client_act_remaining.read"):
        assert action in catalog.ACTIONS
        assert action in catalog.role_actions("owner")
        assert action in catalog.role_actions("admin")
        assert action in catalog.role_actions("accountant")
        for role_id in ("site_manager", "project_manager", "warehouse", "procurement",
                        "office", "worker", "driver", "LEGACY_TECHNICIAN", "LEGACY_VIEWER"):
            assert action not in catalog.role_actions(role_id), (action, role_id)


if __name__ == "__main__":
    sys.exit(main())
