"""
LAB-AKORD-01 — the WRITE side of the akord quantity on the single labor line (FLOW-028, Р100).

FLOW-028: "заработка = одобрено измерено количество × договорена единична цена труд"; "Без
одобрено количество или цена не възниква окончателно задължение и не може да има плащане";
"двустепенно одобрение". Р100: from #73/#75 — not paid twice, four-eyes, P&L = pay run.

Scenario: akord worker W3, a flat approved labor line on P, the SMR package "pkg-ak" (m2) whose
agreed unit labor price 12 €/m2 the Accountant sets through ``PUT /labor-terms``. The
Technician (member of P) enters 20 m2 → pending, the pay run shows the line blocked; the
SiteManager of P approves → pay run 20 × 12 = 240 = reader = P&L. Four-eyes, reject,
correction with history, payment lock, tenant isolation, forbidden roles, Idempotency-Key.

Same harness as ``test_fix_pay_03_payrun_flow028.py`` (mongomock and, with
``W0_03_REAL_MONGO_URL``, a real disposable MongoDB).

    PYTHONPATH=. pytest tests/test_lab_akord_01_quantity_approval.py -v --noconftest -p no:cacheprovider
"""
import importlib
import uuid

import pytest

import tests.test_lab_r96_rules as rules
from tests.test_fix_pay_03_payrun_flow028 import W3, akord_worker, create_run, flat_line, reader
from tests.test_lab_r96_money_rules import generate, pay, pnl, row_of
from tests.test_lab_r96_rules import ORG, P, P2, TODAY, backend, headers

__all__ = ["backend"]

OTHER = "ORG-AKORD-OTHER"
PKG = "pkg-ak"
LINE = "ln-ak"
NO_QTY = "Акорд: няма одобрено количество"


def tok(uid, role, org=ORG):
    from app.deps.auth import create_token
    return {"Authorization": "Bearer " + create_token({"user_id": uid, "org_id": org, "role": role})}


ACC = tok("acc", "Accountant")
SM = headers("sm")
TECH = headers("tech")
ADMIN = headers("admin")


def key():
    return {"Idempotency-Key": "k-" + uuid.uuid4().hex}


def run(monkeypatch, backend, scenario):
    importlib.import_module("app.services.labor_quantity_service")
    monkeypatch.setattr(rules, "ROUTERS", rules.ROUTERS + ("labor_quantities",))

    async def wrapped(c, op):
        from app.services.offline_sync import UNIQUE_INDEXES        # the startup indexes of this task
        for coll, keys, name, field in UNIQUE_INDEXES:
            if coll == "labor_quantity_approvals":
                await op[coll].create_index(keys, unique=True, name=name,
                                            partialFilterExpression={field: {"$type": "string"}})
        for uid, role in (("acc", "Accountant"), ("sm2", "SiteManager"), ("tech2", "Technician")):
            await op.users.insert_one({"id": uid, "org_id": ORG, "role": role, "is_active": True,
                                       "email": uid + "@akord.example", "first_name": uid, "last_name": "S"})
        await op.users.insert_one({"id": "admin-o", "org_id": OTHER, "role": "Admin", "is_active": True,
                                   "email": "admin-o@akord.example", "first_name": "A", "last_name": "O"})
        await op.execution_packages.insert_one({"id": PKG, "org_id": ORG, "project_id": P,
                                                "activity_name": rules.A, "unit": "m2"})
        await op.execution_packages.insert_one({"id": "pkg-p2", "org_id": ORG, "project_id": P2,
                                                "activity_name": rules.A, "unit": "m2"})
        await akord_worker(op)
        await flat_line(op, LINE, W3, P, 8)
        return await scenario(c, op)
    return rules.run(monkeypatch, backend, wrapped)


async def set_price(c, rate=12, who=ACC, k=None):
    return await c.put("/api/labor-terms/" + PKG, headers={**who, **(k or key())},
                       json={"labor_piece_rate": rate, "reason": "Договор за акорд"})


async def enter(c, qty=20, who=TECH, line=LINE, k=None, pkg=PKG):
    return await c.post("/api/labor-quantities", headers={**who, **(k or key())},
                        json={"line_id": line, "quantity": qty, "execution_package_id": pkg})


async def approve(c, rid, who=SM, k=None):
    return await c.post("/api/labor-quantities/%s/approve" % rid, headers={**who, **(k or key())}, json={})


async def reject(c, rid, reason="Не е измерено", who=SM, k=None):
    return await c.post("/api/labor-quantities/%s/reject" % rid, headers={**who, **(k or key())},
                        json={"reason": reason})


async def earned(c):
    return row_of(await generate(c), W3)


async def blocked_reason(c):
    w = await earned(c)
    assert (w["earned_amount"], w["day_cells"]) == (0, []), w
    return [(b["report_id"], b["reason"]) for b in w["blocked_lines"]]


async def reader_cost():
    return [(ln["line_id"], ln["cost"]) for ln in await reader().labor_lines(ORG, project_id=P)]


async def entered_and_approved(c, qty=20):
    assert (await set_price(c)).status_code == 200
    r = await enter(c, qty)
    assert r.status_code == 200, r.text
    a = await approve(c, r.json()["id"])
    assert a.status_code == 200, a.text
    return a.json()


async def audit_actions(op):
    rows = await op.audit_events.find({"tenant_id": ORG}, {"_id": 0, "action": 1}).to_list(500)
    return [r["action"] for r in rows if r["action"].startswith(("labor_quantity.", "labor_terms."))]


# ═══════════════════════════════════════════════════════════════════ the main path
def test_enter_pending_blocked_then_approved_pays_240(monkeypatch, backend):
    async def scenario(c, op):
        p = await set_price(c)
        assert p.status_code == 200, p.text
        assert (p.json()["labor_piece_rate"], p.json()["labor_terms_version"]) == (12, 1)
        r = await enter(c, 20)
        assert r.status_code == 200, r.text
        rec = r.json()
        assert (rec["status"], rec["entered_quantity"], rec["unit"], rec["entered_by"],
                rec["quantity_version"]) == ("pending", 20, "m2", "tech", 1)
        # pending → blocked, with the reason, 0 everywhere
        assert await blocked_reason(c) == [(LINE, NO_QTY + " — количеството чака одобрение")]
        assert await reader_cost() == [(LINE, 0)]
        assert (await pnl(c))["labor_cost"] == 0
        a = await approve(c, rec["id"])
        assert a.status_code == 200, a.text
        out = a.json()
        assert (out["status"], out["approved_quantity"], out["approved_by"]) == ("approved", 20, "sm")
        assert "piece_rate" not in out                                  # R31: no price for the SiteManager
        stored = await op.labor_quantity_approvals.find_one({"id": rec["id"]}, {"_id": 0})
        assert (stored["piece_rate"], stored["labor_terms_version"], stored["report_id"],
                stored["entry_id"], stored["report_version"]) == (12, 1, LINE, None, 0)
        w = await earned(c)
        assert (w["earned_amount"], w["blocked_lines"]) == (240, [])
        assert await reader_cost() == [(LINE, 240)]
        assert (await pnl(c))["labor_cost"] == 240
        # a later price change does not touch the approved quantity (snapshot)
        assert (await set_price(c, 15)).status_code == 200
        assert (await earned(c))["earned_amount"] == 240
        await pay(c, W3, 240)
        assert await reader_cost() == [(LINE, 240)]
        assert (await pnl(c))["labor_cost"] == 240
        assert await audit_actions(op) == ["labor_terms.set", "labor_quantity.entered",
                                           "labor_quantity.approved", "labor_terms.set"]
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ four-eyes
@pytest.mark.parametrize("case", ["approver_is_enterer", "approver_is_worker"])
def test_four_eyes(monkeypatch, backend, case):
    async def scenario(c, op):
        assert (await set_price(c)).status_code == 200
        line = LINE
        if case == "approver_is_worker":                 # the SiteManager is himself on akord
            await op.employee_profiles.insert_one({"org_id": ORG, "user_id": "sm", "pay_type": "Akord"})
            line = await flat_line(op, "ln-sm", "sm", P, 8)
            r = await enter(c, 20, who=TECH, line=line)
        else:
            r = await enter(c, 20, who=SM)
        assert r.status_code == 200, r.text
        a = await approve(c, r.json()["id"], who=SM)
        assert a.status_code == 403 and a.json()["detail"]["error_code"] == "FOUR_EYES", a.text
        rec = await op.labor_quantity_approvals.find_one({"id": r.json()["id"]}, {"_id": 0})
        assert rec["status"] == "pending" and "approved_by" not in rec
        a = await approve(c, r.json()["id"], who=ADMIN)   # another person
        assert a.status_code == 200, a.text
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ reject
def test_reject_blocks_again_with_reason(monkeypatch, backend):
    async def scenario(c, op):
        assert (await set_price(c)).status_code == 200
        r = await enter(c, 20)
        rid = r.json()["id"]
        bad = await reject(c, rid, reason="  ")
        assert bad.status_code == 422, bad.text
        x = await reject(c, rid, "Не е измерено на място")
        assert x.status_code == 200 and x.json()["status"] == "rejected", x.text
        assert await blocked_reason(c) == [(LINE, NO_QTY + " — количеството е отказано: Не е измерено на място")]
        assert (await approve(c, rid)).status_code == 409             # a rejected record stays rejected
        # a new entry after the rejection, approved, then revoked (reject of an approved one)
        r2 = await enter(c, 18)
        assert (r2.status_code, r2.json()["quantity_version"]) == (200, 2), r2.text
        assert (await approve(c, r2.json()["id"])).status_code == 200
        assert (await earned(c))["earned_amount"] == 216
        x = await reject(c, r2.json()["id"], "Грешно измерване")
        assert x.status_code == 200, x.text
        assert await blocked_reason(c) == [(LINE, NO_QTY + " — количеството е отказано: Грешно измерване")]
        assert await reader_cost() == [(LINE, 0)]
        assert (await pnl(c))["labor_cost"] == 0
        assert (await create_run(c, W3, 216)).status_code == 400       # nothing payable
        hist = await op.labor_quantity_approvals.find({"report_id": LINE}, {"_id": 0}).to_list(10)
        assert sorted((h["quantity_version"], h["status"]) for h in hist) == [(1, "rejected"), (2, "rejected")]
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ correction
def test_correction_after_approval_is_a_new_version_with_history(monkeypatch, backend):
    async def scenario(c, op):
        v1 = await entered_and_approved(c, 20)
        r = await enter(c, 25)                                           # correction
        assert r.status_code == 200, r.text
        v2 = r.json()
        assert (v2["quantity_version"], v2["replaces"], v2["status"]) == (2, v1["id"], "pending")
        again = await enter(c, 26)
        assert again.status_code == 409 and again.json()["detail"]["error_code"] == "QUANTITY_PENDING"
        # until the correction is approved the pay run uses the valid (approved) one
        assert (await earned(c))["earned_amount"] == 240
        assert (await approve(c, v2["id"])).status_code == 200
        w = await earned(c)
        assert (w["earned_amount"], w["blocked_lines"]) == (300, [])
        assert await reader_cost() == [(LINE, 300)]
        assert (await pnl(c))["labor_cost"] == 300
        old = await op.labor_quantity_approvals.find_one({"id": v1["id"]}, {"_id": 0})
        assert (old["status"], old["approved_quantity"], old["superseded_by"]) == ("superseded", 20, v2["id"])
        lst = await c.get("/api/labor-quantities", headers=SM, params={"project_id": P})
        assert lst.status_code == 200, lst.text
        item = lst.json()["items"][0]
        assert (item["state"], item["approved"]["approved_quantity"]) == ("approved", 25)
        assert [(h["quantity_version"], h["status"]) for h in item["history"]] == [(2, "approved"), (1, "superseded")]
        assert all("piece_rate" not in h for h in item["history"])       # R31
        acc = (await c.get("/api/labor-quantities", headers=ACC, params={"project_id": P})).json()
        assert acc["items"][0]["approved"]["piece_rate"] == 12
        assert "labor_quantity.corrected" in await audit_actions(op)
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ payment lock
@pytest.mark.parametrize("state", ["batched", "paid"])
def test_batched_or_paid_line_is_locked(monkeypatch, backend, state):
    async def scenario(c, op):
        v1 = await entered_and_approved(c, 20)
        if state == "paid":
            await pay(c, W3, 240)
        else:
            assert (await create_run(c, W3, 240)).status_code == 200    # confirmed, not paid
        doc = await op.employee_daily_reports.find_one({"id": LINE}, {"_id": 0})
        assert doc["payroll_status"] == state
        r = await enter(c, 25)
        assert r.status_code == 409 and r.json()["detail"]["error_code"] == "LABOR_LINE_PAID", r.text
        x = await reject(c, v1["id"], "късно")
        assert x.status_code == 409 and x.json()["detail"]["error_code"] == "LABOR_LINE_PAID", x.text
        rec = await op.labor_quantity_approvals.find_one({"id": v1["id"]}, {"_id": 0})
        assert rec["status"] == "approved"
        assert await reader_cost() == [(LINE, 240)]
    run(monkeypatch, backend, scenario)


def test_pending_record_cannot_be_approved_once_the_line_is_batched(monkeypatch, backend):
    async def scenario(c, op):
        await entered_and_approved(c, 20)
        r = await enter(c, 25)
        await create_run(c, W3, 240)
        a = await approve(c, r.json()["id"], who=ADMIN)
        assert a.status_code == 409 and a.json()["detail"]["error_code"] == "LABOR_LINE_PAID", a.text
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ tenant isolation
def test_tenant_isolation(monkeypatch, backend):
    async def scenario(c, op):
        assert (await set_price(c)).status_code == 200
        r = await enter(c, 20)
        rid = r.json()["id"]
        other = tok("admin-o", "Admin", org=OTHER)
        assert (await approve(c, rid, who=other)).status_code == 404
        assert (await reject(c, rid, who=other)).status_code == 404
        assert (await enter(c, 5, who=other)).status_code == 404       # ORG's line is not theirs
        assert (await c.put("/api/labor-terms/" + PKG, headers={**other, **key()},
                            json={"labor_piece_rate": 99, "reason": "x"})).status_code == 404
        lst = await c.get("/api/labor-quantities", headers=other, params={"project_id": P})
        assert lst.status_code == 200 and lst.json()["items"] == []
        rec = await op.labor_quantity_approvals.find_one({"id": rid}, {"_id": 0})
        assert (rec["org_id"], rec["status"]) == (ORG, "pending")
        pkg = await op.execution_packages.find_one({"id": PKG}, {"_id": 0})
        assert pkg["labor_piece_rate"] == 12
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ forbidden roles
def test_forbidden_roles(monkeypatch, backend):
    async def scenario(c, op):
        w0 = headers(rules.W0)                                           # a worker, not W3
        for who in (SM, TECH, w0):                                       # price: finance roles only
            assert (await set_price(c, who=who)).status_code == 403
            assert (await c.get("/api/labor-terms", headers=who, params={"project_id": P})).status_code == 403
        assert (await set_price(c)).status_code == 200
        assert (await enter(c, 20, who=w0)).status_code == 403          # another worker's line
        assert (await enter(c, 20, who=tok("tech2", "Technician"))).status_code == 403   # not on P
        r = await enter(c, 20)
        rid = r.json()["id"]
        for who in (ACC, TECH, w0, headers(W3), tok("sm2", "SiteManager")):   # sm2 is not on P
            a = await approve(c, rid, who=who)
            assert a.status_code == 403, (who, a.text)
            assert (await reject(c, rid, who=who)).status_code == 403
        rec = await op.labor_quantity_approvals.find_one({"id": rid}, {"_id": 0})
        assert rec["status"] == "pending"
        # a line of a worker who is not on akord / a package of another project
        assert (await enter(c, 20, line=await flat_line(op, "ln-h", rules.W0, P, 8))).status_code == 422
        assert (await enter(c, 20, pkg="pkg-p2")).status_code == 422          # package of P2
        # the worker himself may enter his own quantity (Р96), never approve it
        assert (await reject(c, rid)).status_code == 200
        assert (await enter(c, 21, who=headers(W3))).status_code == 200
    run(monkeypatch, backend, scenario)


# ═══════════════════════════════════════════════════════════════════ Idempotency-Key
def test_idempotency_key(monkeypatch, backend):
    async def scenario(c, op):
        assert (await c.put("/api/labor-terms/" + PKG, headers=ACC,
                            json={"labor_piece_rate": 12, "reason": "x"})).status_code == 428
        nk = await c.post("/api/labor-quantities", headers=TECH, json={"line_id": LINE, "quantity": 20})
        assert nk.status_code == 428, nk.text
        assert await op.labor_quantity_approvals.count_documents({}) == 0
        assert (await set_price(c)).status_code == 200
        k = key()
        r1, r2 = await enter(c, 20, k=k), await enter(c, 20, k=k)
        assert (r1.status_code, r2.status_code) == (200, 200), r2.text
        assert r2.json()["id"] == r1.json()["id"] and r2.json()["idempotent_replay"] is True
        assert (await enter(c, 21, k=k)).status_code == 409             # same key, another body
        ka = key()
        a1, a2 = await approve(c, r1.json()["id"], k=ka), await approve(c, r1.json()["id"], k=ka)
        assert (a1.status_code, a2.status_code) == (200, 200)
        assert await op.labor_quantity_approvals.count_documents({}) == 1
        assert (await earned(c))["earned_amount"] == 240
        assert (await audit_actions(op)).count("labor_quantity.approved") == 1
    run(monkeypatch, backend, scenario)
