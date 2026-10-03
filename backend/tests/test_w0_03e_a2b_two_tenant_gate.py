"""
W0-03E-A2B / C01 — the gate: BEG backfill, then a second tenant, end to end.

One scenario, Issue #38 Phases 1–9 in order, in ONE disposable environment:

 1. the current single-tenant BEG legacy dataset (ownerless rows in every
    org-keyed collection, registry from the W0-01 shape) — precondition proven
    from registry/organization state only;
 2. dry run: full inventory, every Issue #38 family, plan token;
 3. execute with an approval bound to that plan token, then zero-ownerless
    reconciliation and an independent ownership verification;
 4. (real MongoDB only) the server-side ownership invariant is installed and
    the SERVER refuses an ownerless insert and the removal of an owner;
 5. the W0-02 permission bootstrap derives BEG's project permissions from the
    now tenant-bound memberships;
 6. TEST COMPANY B is onboarded through the canonical path, over HTTP
    (``POST /api/billing/signup``); its owner and BEG's users log in over HTTP
    (``POST /api/auth/login``) and every later request carries a real JWT;
 7. both tenants create records over HTTP — a forged body ``org_id`` /
    ``tenant_id`` naming the other tenant is sent every time — and each stored
    row carries ITS creator's server-derived tenant;
 8. colliding ids: B receives records with BEG's legacy ids (project, user,
    person, company, client, counterparty, subcontractor, team tuple, invoice,
    payment, allocation, warehouse, location, item, offer), stamped by the
    tenant layer from B's registry-resolved TenantContext; and a second id set
    is created by B FIRST and by BEG afterwards, so a tenant-blind lookup finds
    the other tenant's copy in BOTH directions;
 9. the HTTP matrix as BEG SiteManager, BEG Admin, B SiteManager (same user
    id as BEG's) and B Owner: project/team authorization, finance invoice
    list/detail/PDF, payments/allocations, offers list/detail/XLSX/PDF,
    reports/drilldowns/exports, and protected legacy/Master reads. No response
    of one tenant contains the other's names, codes, values or amounts, and B's
    membership never authorizes BEG (nor the reverse). Cross-tenant writes by
    colliding id are refused/404 and the other tenant's rows are unchanged.
10. teardown: the disposable databases are dropped and proven gone.

The same scenario runs on an in-process database (always) and on a REAL
MongoDB (``W0_03_REAL_MONGO_URL``, loopback only, fresh random database
names under the CLI's disposable prefix), where steps 2–4 go through the
operator CLI ``scripts/w0_03e_a2b_beg_backfill.py`` as a subprocess.

Run:  W0_03_REAL_MONGO_URL=mongodb://127.0.0.1:<port> \\
      pytest tests/test_w0_03e_a2b_two_tenant_gate.py -v --noconftest -rs
"""
import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from app.tenancy import legacy_backfill as lb
from app.tenancy import ownership as own
from tests.test_w0_03c_real_mongo import REAL_URL, _refusal
from tests.test_w0_03e_a2b_backfill import BEG_ORG, TrustedApproval, seed_legacy
from tests.test_w0_03e_r1_exports import pdf_text, xlsx_text

BACKEND = Path(__file__).resolve().parent.parent
CLI = BACKEND / "scripts" / "w0_03e_a2b_beg_backfill.py"
PASSWORD = "Gate-Pass-2026!"
BEG_AMOUNT, B_AMOUNT = 1111.11, 7777.77
#: Ids BEG has from its legacy data; B receives the same ids AFTER BEG.
LEGACY_IDS = {"projects": "P-L", "users": "U-L", "persons": "PE-L", "companies": "CO-L",
              "clients": "C-L", "counterparties": "CP-L", "subcontractors": "S-L",
              "invoices": "I-L", "finance_payments": "PAY-L", "payment_allocations": "AL-L",
              "warehouses": "W-L", "location_nodes": "LOC-L", "items": "IT-L", "offers": "O-L"}
#: Ids B creates FIRST and BEG creates afterwards.
NEW_IDS = {k: v[:-1] + "N" for k, v in LEGACY_IDS.items() if k != "users"}
PERIOD = "date_from=2026-01-01&date_to=2026-12-31"


def _mark(tenant):
    return "BEG-" if tenant == "beg" else "TCB-"


# ======================================================================= records
def _records(prefix, ids, amount):
    """One record per colliding family, carrying ``prefix`` markers. No org_id:
    the tenant layer stamps it."""
    p, i = prefix, ids
    return {
        "projects": {"id": i["projects"], "code": p + "CODE-" + i["projects"],
                     "name": p + "PROJECT-" + i["projects"], "status": "Active"},
        "persons": {"id": i["persons"], "first_name": p + "PERSON", "last_name": "X"},
        "companies": {"id": i["companies"], "name": p + "COMPANY", "eik": "999"},
        "clients": {"id": i["clients"], "companyName": p + "CLIENT", "type": "company",
                    "is_active": True},
        "counterparties": {"id": i["counterparties"], "name": p + "CP", "type": "company",
                           "active": True},
        "subcontractors": {"id": i["subcontractors"], "name": p + "SUB"},
        "invoices": {"id": i["invoices"], "project_id": i["projects"], "direction": "Issued",
                     "invoice_no": p + "INV", "status": "Sent", "total": amount,
                     "subtotal": amount, "vat_amount": 0, "counterparty_name": p + "CP",
                     "counterparty_id": i["counterparties"], "issue_date": "2026-03-01",
                     "invoice_date": "2026-03-01", "date": "2026-03-01", "currency": "BGN",
                     "paid_amount": amount, "remaining_amount": 0,
                     "allocations": [{"type": "project", "ref_id": i["projects"]}],
                     "lines": [{"description": p + "LINE", "qty": 1, "unit_price": amount,
                                "line_total": amount}]},
        "finance_payments": {"id": i["finance_payments"], "direction": "Inflow",
                             "amount": amount, "currency": "BGN", "date": "2026-03-02",
                             "reference": p + "PAY", "counterparty_name": p + "CP",
                             "method": "Bank"},
        "payment_allocations": {"id": i["payment_allocations"],
                                "payment_id": i["finance_payments"],
                                "invoice_id": i["invoices"], "amount_allocated": amount},
        "warehouses": {"id": i["warehouses"], "code": p + "W", "name": p + "WAREHOUSE",
                       "type": "project", "project_id": i["projects"],
                       "person_id": i["persons"], "active": True},
        "location_nodes": {"id": i["location_nodes"], "project_id": i["projects"],
                           "name": p + "LOC", "type": "floor"},
        "items": {"id": i["items"], "name": p + "ITEM", "sku": p + "SKU", "unit": "pcs"},
        "offers": {"id": i["offers"], "project_id": i["projects"], "offer_no": p + "OFF",
                   "title": p + "OFFER", "status": "Sent", "version": 1, "currency": "BGN",
                   "created_at": "2026-03-01T00:00:00", "subtotal": amount, "vat_percent": 0,
                   "vat_amount": 0, "total": amount,
                   "lines": [{"id": "l1", "activity_name": p + "OFFER-LINE", "unit": "m2",
                              "qty": 1.0, "material_unit_cost": amount, "labor_unit_cost": 0,
                              "note": ""}]},
    }


# ======================================================================= the app
def _app(monkeypatch, op, sysdb):
    """The real routers, every module handle pointed at the disposable databases.

    Authentication is REAL (JWT -> get_current_user). Only the subscription
    module gates (require_m2/m4/m5) are reduced to "authenticated", because
    the gate is about tenancy, not feature plans.
    """
    from fastapi import Depends, FastAPI

    import app.db as appdb
    from app.deps import auth as deps_auth
    from app.deps import modules as deps_modules
    from app.deps.auth import get_current_user
    from app.deps.modules import require_m2, require_m4, require_m5
    from app.master_data.deps import ENV_MODE
    from app.tenancy import registry
    import server  # noqa: F401 — billing imports server constants; load it first
    from app.routes import (auth, billing, clients, counterparties, dashboard, finance, hr,
                            items, locations, offers, projects, reports, subcontractors,
                            warehouses)
    from app.services import audit as services_audit, paid_labor
    from app.utils import audit as utils_audit

    monkeypatch.setenv(ENV_MODE, "off")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    for module in (appdb, deps_auth, deps_modules, paid_labor, utils_audit, services_audit):
        monkeypatch.setattr(module, "db", op)
    monkeypatch.setattr(registry, "system_db", sysdb)
    for name in ("tenant_registry", "tenant_memberships", "tenant_role_assignments"):
        monkeypatch.setattr(registry, name, sysdb[name])
    app = FastAPI()
    for module in (auth, billing, clients, counterparties, dashboard, finance, hr, items,
                   locations, offers, projects, reports, subcontractors, warehouses):
        monkeypatch.setattr(module, "db", op)
        app.include_router(module.router, prefix="/api")

    async def _authenticated(user: dict = Depends(get_current_user)):
        return user
    for dep in (require_m2, require_m4, require_m5):
        app.dependency_overrides[dep] = _authenticated
    return app


class Caller:
    def __init__(self, client, token, user, tenant):
        self.c, self.token, self.user, self.tenant = client, token, user, tenant
        self.h = {"Authorization": "Bearer " + token}

    async def get(self, path, ok=(200,)):
        r = await self.c.get(path, headers=self.h)
        assert r.status_code in ok, (self.tenant, path, r.status_code, r.text[:400])
        return r

    async def post(self, path, body):
        return await self.c.post(path, json=body, headers=self.h)

    async def delete(self, path):
        return await self.c.delete(path, headers=self.h)


async def _login(c, email, tenant):
    r = await c.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, (email, r.status_code, r.text[:300])
    body = r.json()
    return Caller(c, body["token"], body["user"], tenant)


def _foreign(tenant):
    """What must never appear in a response to ``tenant``."""
    if tenant == "beg":
        return ("TCB-", str(B_AMOUNT), "7777.8", "7 777")
    return ("BEG-", str(BEG_AMOUNT), "1111.1", "1 111")


def _assert_clean(tenant, where, text, b_tenant_id=None):
    for marker in _foreign(tenant):
        assert marker not in text, "%s response %s leaked %r: %s" % (
            tenant, where, marker, text[:600])
    if tenant == "beg" and b_tenant_id:
        assert b_tenant_id not in text, "%s leaked B's tenant id" % where
    if tenant == "b":
        assert BEG_ORG not in text, "%s leaked BEG's tenant id" % where


# ======================================================================= the scenario
async def _backfill_in_process(op, sysdb, ev):
    report = await lb.dry_run(op, sysdb)
    assert report["executable"], report["blockers"]
    ev["dry_run"] = {"totals": report["totals"], "plan_token": report["plan_token"]}
    result = await lb.execute(op, sysdb, plan_token=report["plan_token"],
                              idempotency_key="gate-1", actor_id="krum",
                              approval_id="APR-GATE", approval_verifier=TrustedApproval())
    ev["execute"] = {"status": result["status"],
                     "planned": result["reconciliation"]["planned"],
                     "journaled": result["reconciliation"]["journaled"]}
    ev["verify"] = {k: v for k, v in (await lb.verify_ownership(op, sysdb)).items()
                    if k != "rows"}
    return report


def _cli(*args, expect=0):
    r = subprocess.run([sys.executable, str(CLI), "--mongo-url", REAL_URL, *args],
                       cwd=BACKEND, capture_output=True, text=True, timeout=300)
    assert r.returncode == expect, (args, r.returncode, r.stdout[-1500:], r.stderr[-1500:])
    return json.loads(r.stdout) if r.stdout.strip().startswith("{") else r.stdout


async def _backfill_cli(op, sysdb, ev):
    names = ["--db", op.name, "--system-db", sysdb.name]
    report = _cli(*names)
    assert report["executable"] and report["precondition"]["proven"], report["blockers"]
    ev["dry_run"] = {"totals": report["totals"], "plan_token": report["plan_token"],
                     "via": "CLI", "rows": [{k: r[k] for k in (
                         "collection", "class", "family", "total", "bound", "ownerless",
                         "conflicting", "platform", "action")} for r in report["rows"]]}
    # a wrong plan token is refused (exit 1), nothing written
    stale = _cli(*names, "--execute", "--plan-token", "0" * 64, "--idempotency-key", "g",
                 "--actor", "krum", "--approval-id", "APR", expect=1)
    assert stale["code"] == "STALE_PLAN"
    result = _cli(*names, "--execute", "--plan-token", report["plan_token"],
                  "--idempotency-key", "gate-1", "--actor", "krum",
                  "--approval-id", "APR-GATE", "--batch-size", "7")
    rec = result["reconciliation"]
    ev["execute"] = {"status": result["status"], "planned": rec["planned"],
                     "journaled": rec["journaled"], "via": "CLI"}
    replay = _cli(*names, "--execute", "--plan-token", report["plan_token"],
                  "--idempotency-key", "gate-1", "--actor", "krum", "--approval-id", "APR-GATE")
    assert replay["replayed"] is True
    verified = _cli(*names, "--verify")
    ev["verify"] = {k: v for k, v in verified.items() if k != "rows"}
    enforced = _cli(*names, "--enforce", "--actor", "krum")
    ev["invariant_collections"] = len(enforced["installed"])
    return report


async def _server_refuses_ownerless(op, ev):
    """Real MongoDB: the database itself now rejects an ownerless row."""
    from pymongo.errors import WriteError
    refused = 0
    for coll in ("projects", "project_team", "invoices", "finance_payments", "users"):
        for doc in ({"id": "x-" + coll}, {"id": "x-" + coll, "org_id": None},
                    {"id": "x-" + coll, "org_id": ""}):
            with pytest.raises(WriteError) as exc:
                await op[coll].insert_one(doc)
            assert exc.value.code == 121          # DocumentValidationFailure
            refused += 1
        with pytest.raises(WriteError):
            await op[coll].update_one({"org_id": BEG_ORG}, {"$unset": {"org_id": ""}})
        refused += 1
    ev["server_refused_ownerless_writes"] = refused


async def scenario(op, sysdb, monkeypatch, real):
    import httpx
    ev = {"real_mongo": real, "databases": [op.name, sysdb.name]}
    # ---- 1. legacy BEG dataset + its two log-in users
    await seed_legacy(op, sysdb)
    from app.deps.auth import hash_password
    pw = hash_password(PASSWORD)
    await op.users.update_many({"id": {"$in": ["U-L", "A-L"]}}, {"$set": {"password_hash": pw}})
    tenant = await lb.prove_precondition(op, sysdb)
    assert tenant.tenant_id == BEG_ORG
    ev["precondition"] = tenant.as_dict()

    # ---- 2-4. dry run, approved execute, reconciliation (+ invariant on real Mongo)
    if real:
        report = await _backfill_cli(op, sysdb, ev)
        await _server_refuses_ownerless(op, ev)
    else:
        report = await _backfill_in_process(op, sysdb, ev)
    rows = {r["collection"]: r for r in report["rows"]}
    assert set(own.FAMILIES) <= {r["family"] for r in report["rows"]}
    assert all(rows[c]["action"] == lb.ACTION_BACKFILL for c in own.ORG_KEYED)
    assert ev["execute"]["status"] == lb.STATUS_COMPLETED
    assert ev["execute"]["journaled"] == ev["execute"]["planned"] == report["totals"]["ownerless"]
    assert ev["verify"]["ok"] and ev["verify"]["ownerless"] == 0
    assert ev["verify"]["authorization_ownerless"] == 0 and ev["verify"]["unknown_owner"] == 0

    # ---- 5. W0-02 bootstrap on the backfilled memberships
    from tests.test_w0_03e_a2b_onboarding_bootstrap import _boot
    boot = _boot(op, sysdb)
    assert await boot.run(apply=True, verify_only=False, revert=False) == boot.EXIT_OK
    proj = await sysdb.tenant_role_assignments.find({"scope_type": "project"}).to_list(None)
    assert {(r["tenant_id"], r["user_id"], r["scope_id"]) for r in proj} == {
        (BEG_ORG, "U-L", "P-L")}
    # The synthetic per-collection filler rows proved the backfill above; they
    # have no business shape, so they leave the disposable database before the
    # HTTP phase. BEG's legacy colliding records get their full realistic shape
    # (same id, same backfilled owner).
    removed = 0
    for coll in own.ORG_KEYED:
        res = await op[coll].delete_many({"id": {"$regex": "-(bound|missing|null|empty)$"}})
        removed += res.deleted_count
    ev["synthetic_filler_rows_removed_after_proof"] = removed
    for coll, doc in _records("BEG-", LEGACY_IDS, BEG_AMOUNT).items():
        res = await op[coll].update_one({"id": doc["id"], "org_id": BEG_ORG}, {"$set": doc})
        assert res.matched_count == 1, coll
    beg_before = {c: await op[c].find({"org_id": BEG_ORG}, {"_id": 0}).to_list(None)
                  for c in sorted(own.ORG_KEYED)}

    app = _app(monkeypatch, op, sysdb)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://gate") as c:
        # ---- 6. onboard TEST COMPANY B over HTTP (canonical path)
        r = await c.post("/api/billing/signup", json={
            "org_name": "TEST COMPANY B", "owner_name": "Owner TCB",
            "owner_email": "owner@tcb.test", "password": PASSWORD,
            "org_id": BEG_ORG, "tenant_id": BEG_ORG})
        assert r.status_code == 200, r.text[:400]
        b_id = r.json()["organization"]["id"]
        assert b_id != BEG_ORG
        b_reg = await sysdb.tenant_registry.find_one({"id": b_id})
        assert b_reg["is_primary_installation"] is False and b_reg["database_name"] == op.name
        with pytest.raises(lb.PreconditionFailed):
            await lb.prove_precondition(op, sysdb)      # the one-time rule is closed now
        ev["tenant_b"] = {"id": b_id, "registry_status": b_reg["status"]}

        # the gate is about tenancy, not plan limits: B's synthetic trial is upgraded
        await op.subscriptions.update_many({"org_id": b_id},
                                           {"$set": {"plan_id": "enterprise", "status": "active"}})
        await op.subscriptions.insert_one({"id": "sub-beg", "org_id": BEG_ORG,
                                           "plan_id": "enterprise", "status": "active"})
        b_owner = await _login(c, "owner@tcb.test", "b")
        beg_admin = await _login(c, "admin@beg.test", "beg")
        assert b_owner.user["org_id"] == b_id and beg_admin.user["org_id"] == BEG_ORG

        # ---- 8a. B gets BEG's legacy ids, stamped from B's registry-resolved context
        from app.tenancy.data_access import TenantData
        from app.tenancy.guard import get_tenant_context
        from starlette.requests import Request

        async def tenant_view(user):
            req = Request({"type": "http", "query_string": b"", "headers": []})
            ctx = await get_tenant_context(req, user)
            assert ctx.tenant_id == user["org_id"]
            return TenantData.for_context(op, ctx)
        b_view = await tenant_view(b_owner.user)
        beg_view = await tenant_view(beg_admin.user)
        for coll, doc in _records("TCB-", LEGACY_IDS, B_AMOUNT).items():
            await b_view.collection(coll).insert_one(dict(doc))
        await b_view.users.insert_one({"id": "U-L", "email": "sm@tcb.test",
                                       "password_hash": pw, "first_name": "TCB-SM",
                                       "last_name": "B", "role": "SiteManager",
                                       "is_active": True})
        # ---- 8b. a second id set, created by B FIRST and by BEG afterwards
        for view, prefix, amount in ((b_view, "TCB-", B_AMOUNT), (beg_view, "BEG-", BEG_AMOUNT)):
            for coll, doc in _records(prefix, NEW_IDS, amount).items():
                await view.collection(coll).insert_one(dict(doc))
        # B's SiteManager is on BOTH B projects; BEG's only on its legacy P-L
        r = await b_owner.post("/api/projects/P-L/team", {
            "user_id": "U-L", "role_in_project": "SiteManager",
            "org_id": BEG_ORG, "tenant_id": BEG_ORG})
        assert r.status_code == 201, r.text[:300]
        r = await b_owner.post("/api/projects/P-N/team", {"user_id": "U-L",
                                                          "role_in_project": "SiteManager"})
        assert r.status_code == 201, r.text[:300]
        b_sm = await _login(c, "sm@tcb.test", "b")
        beg_sm = await _login(c, "sm@beg.test", "beg")
        assert b_sm.user["id"] == beg_sm.user["id"] == "U-L"
        assert (b_sm.user["org_id"], beg_sm.user["org_id"]) == (b_id, BEG_ORG)
        assert "TCB-" in b_sm.user["first_name"] and "BEG-" in beg_sm.user["first_name"]

        # precondition of a REAL collision: a tenant-blind lookup finds the
        # other tenant's copy, in both directions
        for coll, rid, first in (("projects", "P-L", BEG_ORG), ("projects", "P-N", b_id),
                                 ("invoices", "I-L", BEG_ORG), ("invoices", "I-N", b_id),
                                 ("users", "U-L", BEG_ORG)):
            assert (await op[coll].find_one({"id": rid}))["org_id"] == first, (coll, rid)

        # ---- 7. new records over HTTP: each carries its creator's tenant
        created = {}
        forged = {"org_id": BEG_ORG, "tenant_id": BEG_ORG}
        for who, caller, mark in (("b", b_owner, "TCB-"), ("beg", beg_admin, "BEG-")):
            tid = b_id if who == "b" else BEG_ORG
            wanted = {
                ("projects", "/api/projects"): {"code": mark + "HTTP", "name": mark + "HTTP-PRJ"},
                ("clients", "/api/clients"): {"first_name": mark + "HTTP", "last_name": "C",
                                              "phone": "+3591" + ("1" if who == "b" else "2")},
                ("counterparties", "/api/counterparties"): {"name": mark + "HTTP-CP"},
                ("warehouses", "/api/warehouses"): {"code": mark + "HW", "name": mark + "HW"},
                ("offers", "/api/offers"): {"project_id": "P-L", "title": mark + "HTTP-OFF"},
                ("invoices", "/api/finance/invoices"): {
                    "direction": "Issued", "project_id": "P-L", "issue_date": "2026-03-05",
                    "due_date": "2026-04-05", "counterparty_name": mark + "HTTP-CP",
                    "lines": [{"description": mark + "L", "qty": 1, "unit_price": 1}]},
            }
            for (coll, path), body in wanted.items():
                if who == "b":
                    body = {**body, **forged}
                else:
                    body = {**body, "org_id": b_id, "tenant_id": b_id}
                r = await caller.post(path, body)
                assert r.status_code in (200, 201), (who, path, r.status_code, r.text[:400])
                rid = r.json()["id"]
                stored = await op[coll].find_one({"id": rid}, {"_id": 0})
                assert stored["org_id"] == tid, (who, coll, stored.get("org_id"))
                assert "tenant_id" not in stored or stored["tenant_id"] == tid
                created.setdefault(who, {})[coll] = rid
        ev["http_created"] = {k: sorted(v) for k, v in created.items()}

        # ---- 9. the HTTP matrix
        seen = {"beg": 0, "b": 0}

        async def probe(caller, path, ok=(200,)):
            r = await caller.get(path, ok)
            ctype = r.headers.get("content-type", "")
            if "spreadsheet" in ctype or path.endswith("xlsx") or "format=xlsx" in path:
                text = repr(xlsx_text(r.content))
            elif "pdf" in ctype:
                text = pdf_text(r.content)
            else:
                text = r.text
            _assert_clean(caller.tenant, path, text, b_id)
            seen[caller.tenant] += 1
            return r

        def ids(r):
            body = r.json()
            items = body.get("items", body) if isinstance(body, dict) else body
            return {x.get("id") for x in items if isinstance(x, dict)}

        for sm, own_t in ((beg_sm, "beg"), (b_sm, "b")):
            # project/team authorization: P-L for both; P-N only for B
            lst = await probe(sm, "/api/projects")
            expect = {"P-L"} if own_t == "beg" else {"P-L", "P-N"}
            assert ids(lst) == expect, (own_t, ids(lst))
            assert "BEG-" in lst.text if own_t == "beg" else "TCB-" in lst.text
            await probe(sm, "/api/projects/P-L")
            team = await probe(sm, "/api/projects/P-L/team")
            assert len(team.json()) == 1
            pn = await probe(sm, "/api/projects/P-N", ok=(200, 403, 404))
            assert (pn.status_code == 200) is (own_t == "b"), (own_t, pn.status_code)
            pnt = await probe(sm, "/api/projects/P-N/team", ok=(200, 403, 404))
            assert (pnt.status_code == 200) is (own_t == "b")
            # membership-scoped finance + offers
            inv = await probe(sm, "/api/finance/invoices")
            assert "I-L" in ids(inv) and ("I-N" in ids(inv)) is (own_t == "b")
            await probe(sm, "/api/finance/invoices/I-L")
            await probe(sm, "/api/finance/invoices/I-N", ok=(200, 403, 404))
            off = await probe(sm, "/api/offers")
            assert "O-L" in ids(off) and ("O-N" in ids(off)) is (own_t == "b")
            await probe(sm, "/api/offers/O-L")

        for adm in (beg_admin, b_owner):
            # identity-bearing detail reads by colliding id
            for path in ("/api/projects/P-L", "/api/projects/P-N", "/api/finance/invoices/I-L",
                         "/api/finance/invoices/I-N", "/api/finance/payments/PAY-L",
                         "/api/finance/payments/PAY-N", "/api/finance/invoices/I-L/payments",
                         "/api/offers/O-L", "/api/offers/O-N", "/api/clients/C-L",
                         "/api/clients/C-N", "/api/counterparties/CP-L",
                         "/api/counterparties/CP-N", "/api/companies/CO-L",
                         "/api/companies/CO-N", "/api/persons/PE-L", "/api/persons/PE-N",
                         "/api/warehouses/W-L", "/api/warehouses/W-N", "/api/locations/LOC-L",
                         "/api/locations/LOC-N", "/api/items/IT-L", "/api/items/IT-N",
                         "/api/subcontractors/S-L", "/api/subcontractors/S-N"):
                r = await probe(adm, path)
                assert _mark(adm.tenant) in r.text, (adm.tenant, path, r.text[:300])
            # lists, projections, reports, drilldowns
            for path in ("/api/projects", "/api/finance/invoices", "/api/finance/payments",
                         "/api/offers", "/api/clients", "/api/counterparties",
                         "/api/warehouses", "/api/users", "/api/persons", "/api/companies",
                         "/api/items", "/api/subcontractors", "/api/finance/stats",
                         "/api/reports/turnover-by-counterparty",
                         "/api/reports/turnover-by-counterparty/CP-L/invoices?type=all",
                         "/api/reports/turnover-by-client",
                         "/api/reports/finance-details/by-project?" + PERIOD,
                         "/api/reports/finance-details/by-counterparty?" + PERIOD,
                         "/api/reports/finance-details/transactions?transaction_type=invoice&"
                         + PERIOD, "/api/prices", "/api/advances"):
                await probe(adm, path)
            # exports: offer XLSX/PDF, invoice PDF, company finance XLSX
            for path in ("/api/offers/O-L/xlsx", "/api/offers/O-N/xlsx", "/api/offers/O-L/pdf",
                         "/api/finance/invoices/I-L/pdf",
                         "/api/reports/company-finance-export?year=2026&month=3&format=xlsx"):
                r = await probe(adm, path)
                if "offers" in path and "xlsx" in path:
                    assert _mark(adm.tenant) in repr(xlsx_text(r.content))
            # the payment/allocation projection of the colliding invoice
            pays = (await probe(adm, "/api/finance/invoices/I-L/payments")).json()
            amounts = {round(float(p.get("amount_allocated", p.get("amount", 0))), 2)
                       for p in (pays if isinstance(pays, list) else pays.get("items", []))}
            assert amounts <= {BEG_AMOUNT if adm.tenant == "beg" else B_AMOUNT}, amounts

        # ---- cross-tenant writes by colliding id: refused, other tenant unchanged
        beg_team = await op.project_team.find_one({"id": "T-L"}, {"_id": 0})
        assert beg_team["org_id"] == BEG_ORG
        r = await b_owner.delete("/api/projects/P-L/team/T-L")
        assert r.status_code == 404, r.status_code
        assert await op.project_team.find_one({"id": "T-L"}, {"_id": 0}) == beg_team
        r = await beg_sm.post("/api/projects/P-N/team", {"user_id": "U-L",
                                                         "role_in_project": "SiteManager"})
        assert r.status_code in (403, 404), r.status_code
        b_client = await op.clients.find_one({"id": "C-L", "org_id": b_id}, {"_id": 0})
        r = await beg_admin.delete("/api/clients/C-L")
        assert r.status_code in (200, 204, 409), r.status_code
        assert await op.clients.find_one({"id": "C-L", "org_id": b_id}, {"_id": 0}) == b_client
        ev["http_requests_checked"] = seen

    # ---- final ownership proof with two tenants
    final = await lb.verify_ownership(op, sysdb)
    assert final["ok"], {k: v for k, v in final.items() if k != "rows"}
    assert sorted(final["registry_tenants"]) == sorted([BEG_ORG, b_id])
    assert final["rows_per_tenant"][b_id] > 0
    ev["final_verify"] = {k: v for k, v in final.items() if k != "rows"}
    # B's activity never changed a BEG row that existed before B was onboarded
    for coll, docs in beg_before.items():
        now = {d["id"]: d for d in await op[coll].find({"org_id": BEG_ORG}, {"_id": 0}).to_list(None)
               if "id" in d}
        for d in docs:
            if "id" not in d or coll in ("audit_logs", "clients"):
                continue
            assert now.get(d["id"]) == d, (coll, d["id"])
    # every B row in the database carries B, every BEG row BEG — nothing else
    owners = set()
    for coll in own.ORG_KEYED:
        owners |= set(await op[coll].distinct("org_id"))
    assert owners <= {BEG_ORG, b_id, own.PLATFORM_SYSTEM_OWNER,
                      "9f0d2a77-1111-4c1b-8e2e-platform0001"}, owners
    return ev


# ======================================================================= the tests
def test_the_gate_in_process(monkeypatch):
    from mongomock_motor import AsyncMongoMockClient

    async def body():
        client = AsyncMongoMockClient()
        return await scenario(client["w003e_a2b_disposable_op"],
                              client["w003e_a2b_disposable_sys"], monkeypatch, real=False)
    ev = asyncio.run(body())
    assert ev["http_requests_checked"]["beg"] > 40 and ev["http_requests_checked"]["b"] > 40


@pytest.mark.skipif(bool(_refusal()), reason=_refusal() or "ok")
def test_the_gate_on_a_real_disposable_mongodb(monkeypatch, plain_pdf_fonts_real):
    from motor.motor_asyncio import AsyncIOMotorClient
    tag = uuid.uuid4().hex[:10]
    op_name = "w003e_a2b_disposable_%s_op" % tag
    sys_name = "w003e_a2b_disposable_%s_sys" % tag

    async def body():
        client = AsyncIOMotorClient(REAL_URL, serverSelectionTimeoutMS=5000)
        try:
            assert op_name not in await client.list_database_names()
            return await scenario(client[op_name], client[sys_name], monkeypatch, real=True)
        finally:
            await client.drop_database(op_name)
            await client.drop_database(sys_name)
            left = [n for n in await client.list_database_names() if tag in n]
            client.close()
            assert left == [], "disposable databases were not dropped: %s" % left
    ev = asyncio.run(body())
    assert ev["server_refused_ownerless_writes"] == 20
    assert ev["invariant_collections"] == len(own.ORG_KEYED)
    out = os.environ.get("W0_03E_A2B_EVIDENCE")
    if out:
        Path(out).write_text(json.dumps(ev, indent=2, sort_keys=True, default=str),
                             encoding="utf-8")


@pytest.fixture
def plain_pdf_fonts_real(monkeypatch):
    import reportlab.pdfbase.ttfonts as ttfonts

    def unavailable(*a, **kw):
        raise OSError("font unavailable in this test")
    monkeypatch.setattr(ttfonts, "TTFont", unavailable)


@pytest.fixture(autouse=True)
def _plain_fonts_everywhere(monkeypatch):
    """Searchable PDF text in both gates (the exporter's Helvetica fallback)."""
    import reportlab.pdfbase.ttfonts as ttfonts

    def unavailable(*a, **kw):
        raise OSError("font unavailable in this test")
    monkeypatch.setattr(ttfonts, "TTFont", unavailable)
