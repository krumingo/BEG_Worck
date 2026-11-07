"""LAB-02 probe (copy to <wt75>/backend/tests/, harness = test_lab_02_quantity_approval).

Q1 4 concurrent approvals of the same line, DIFFERENT keys, different quantities -> how many
   'approved' records; earned = one of them (never the sum)?
Q2 rate 5 -> approve 120 -> finance changes rate to 9 -> earned still 600 (snapshot)?
Q3 roles: tech / acct / sm-other / worker approve -> 403; acct GET labor-terms 200, sm 403.
Q4 cross-tenant: a tenant-B admin approves tenant-A report id -> 404.
Q5 classify DOWNTIME by sm on w-ak's approved akord line -> earned from DOWNTIME at hourly 15?
"""
import asyncio
import uuid
from tests.test_lab_02_quantity_approval import (ORG, DAY, H, _token, _set_rate, _approve_flow, _preview, run)  # noqa


async def _ready(c, op, qty=120):
    assert (await _set_rate(c)).status_code == 200
    r = await c.put("/api/labor-quantities/entry", json={"report_id": "R-AK", "quantity": qty}, headers=H("w-ak", False))
    assert r.status_code == 200, r.text
    await op.employee_daily_reports.update_one({"id": "R-AK"}, {"$set": {"status": "APPROVED"}})
    return (await op.employee_daily_reports.find_one({"id": "R-AK"}))["report_version"]


def test_q1_concurrent_approvals(monkeypatch):
    async def scenario(c, op):
        ver = await _ready(c, op)
        rs = await asyncio.gather(*[c.post("/api/labor-quantities/approve", json={
            "report_id": "R-AK", "report_version": ver, "approved_quantity": 100 + 10 * i,
            "execution_package_id": "pkg-sh"}, headers=H(who)) for i, who in enumerate(["sm", "admin", "owner", "sm"])])
        n = await op.labor_quantity_approvals.count_documents({"status": "approved"})
        earned = (await _preview(c))["w-ak"]["earned_amount"]
        print("Q1 codes", [r.status_code for r in rs], "approved records", n, "earned", earned)
        assert earned in (500.0, 550.0, 600.0, 650.0)
    run(monkeypatch, scenario, "real")


def test_q2_rate_change_after_approval(monkeypatch):
    async def scenario(c, op):
        await _approve_flow(c, op)
        e1 = (await _preview(c))["w-ak"]["earned_amount"]
        r = await _set_rate(c, rate=9)
        e2 = (await _preview(c))["w-ak"]["earned_amount"]
        hist = await op.labor_terms_history.count_documents({})
        print("Q2 earned before", e1, "| rate->9", r.status_code, "| earned after", e2, "| history rows", hist)
        assert e1 == e2 == 600.0
    run(monkeypatch, scenario, "real")


def test_q3_roles(monkeypatch):
    async def scenario(c, op):
        ver = await _ready(c, op)
        out = {}
        for who in ("tech", "acct", "sm-other", "w-ak", "w-month"):
            r = await c.post("/api/labor-quantities/approve", json={
                "report_id": "R-AK", "report_version": ver, "approved_quantity": 999,
                "execution_package_id": "pkg-sh"}, headers=H(who))
            out[who] = r.status_code
        terms = {who: (await c.get("/api/labor-terms", params={"project_id": "P"}, headers=_token(who))).status_code
                 for who in ("acct", "sm", "tech")}
        setr = {who: (await _set_rate(c, rate=7, who=who)).status_code for who in ("sm", "admin")}
        n = await op.labor_quantity_approvals.count_documents({})
        print("Q3 approve", out, "| GET terms", terms, "| PUT terms", setr, "| records", n)
        assert all(v == 403 for v in out.values()) and n == 0 and terms["sm"] == 403 and setr["sm"] == 403
    run(monkeypatch, scenario, "real")


def test_q4_cross_tenant(monkeypatch):
    async def scenario(c, op):
        ver = await _ready(c, op)
        await op.users.insert_one({"id": "b-admin", "org_id": "ORG-B", "role": "Admin", "is_active": True,
                                   "email": "b@x.example", "first_name": "b", "last_name": "B"})
        from app.deps.auth import create_token
        hb = {"Authorization": "Bearer " + create_token({"user_id": "b-admin", "org_id": "ORG-B", "role": "Admin"}),
              "Idempotency-Key": "k-" + uuid.uuid4().hex}
        r = await c.post("/api/labor-quantities/approve", json={
            "report_id": "R-AK", "report_version": ver, "approved_quantity": 999, "execution_package_id": "pkg-sh"}, headers=hb)
        r2 = await c.put("/api/labor-terms/pkg-sh", json={"labor_pay_type": "Akord", "labor_piece_rate": 99}, headers=hb)
        r3 = await c.put("/api/labor-quantities/entry", json={"report_id": "R-AK", "quantity": 999},
                         headers={"Authorization": hb["Authorization"]})
        pkg = await op.execution_packages.find_one({"id": "pkg-sh"})
        print("Q4 tenant-B approve", r.status_code, "| set terms", r2.status_code, "| entry", r3.status_code,
              "| A rate", pkg.get("labor_piece_rate"), "| A records", await op.labor_quantity_approvals.count_documents({}))
        assert r.status_code == 404 and r2.status_code == 404 and r3.status_code == 404 and pkg.get("labor_piece_rate") == 5
    run(monkeypatch, scenario, "real")
