"""CLAUDE AUDIT probe — #75 LAB-02-D (388b81c, Codex F-75-01). Copy into backend/tests/; real
Mongo RS (W0_03_REAL_MONGO_URL), off / shadow / enforce. Reuses the PR's harness.
  L1  10 concurrent PUT /labor-terms, different keys, ×10 per mode: versions gap-free 1..k,
      one history row + one AuditEvent per version, each before = previous after, package = last.
  L2  one Idempotency-Key, 6 concurrent PUTs -> exactly ONE version / history row / AuditEvent.
  L3  a package already at version 3 -> 6 concurrent changes -> 4..3+k, no gap, no duplicate.
  L4  rate change ∥ quantity approval -> the approval's (piece_rate, labor_terms_version) pair is
      a real committed pair (equals the history row of that version), never torn.
"""
import asyncio
import uuid
import pytest

from tests.test_lab_02_quantity_approval import H, ORG, run  # noqa: F401

MODES = ["off", "shadow", "enforce"]


def _real():
    from tests.test_lab_02_quantity_approval import _real_refusal
    r = _real_refusal()
    if r:
        pytest.skip(r)
    return "real"


async def _check_chain(op, base, k):
    hist = await op.labor_terms_history.find({"package_id": "pkg-sh"}, {"_id": 0}).sort("version", 1).to_list(100)
    vers = [h["version"] for h in hist]
    ev = sorted([int(e["entity_version"]) async for e in op.audit_events.find(
        {"action": "labor_terms.set", "entity_id": "pkg-sh"})])
    pkg = await op.execution_packages.find_one({"id": "pkg-sh"})
    chain = all(c["before"] == p["after"] for p, c in zip(hist, hist[1:]))
    ok = (vers == list(range(base + 1, base + k + 1)) and ev == vers and chain
          and pkg.get("labor_terms_version") == base + k
          and (k == 0 or pkg.get("labor_piece_rate") == hist[-1]["after"]["labor_piece_rate"]))
    return ok, vers, ev, pkg.get("labor_terms_version")


@pytest.mark.parametrize("rep", range(10))
@pytest.mark.parametrize("mode", MODES)
def test_l1_ten_concurrent_changes(monkeypatch, mode, rep):
    backend = _real()

    async def scenario(c, op):
        whos = ("acct", "admin", "owner")
        rs = await asyncio.gather(*[c.put("/api/labor-terms/pkg-sh", json={
            "labor_pay_type": "Akord", "labor_piece_rate": r, "reason": "x"}, headers=H(whos[r % 3]))
            for r in range(1, 11)])
        codes = [r.status_code for r in rs]
        k = codes.count(200)
        ok, vers, ev, pv = await _check_chain(op, 0, k)
        if rep == 0 or not ok or not set(codes) <= {200, 409}:
            print("L1 %s/%d: codes %s | versions %s events %s pkg v%s ok %s" % (mode, rep, sorted(codes), vers, ev, pv, ok))
        assert ok and set(codes) <= {200, 409} and k >= 1
    run(monkeypatch, scenario, backend, mode)


@pytest.mark.parametrize("mode", MODES)
def test_l2_same_key_six_times(monkeypatch, mode):
    backend = _real()

    async def scenario(c, op):
        h = H("acct")
        rs = await asyncio.gather(*[c.put("/api/labor-terms/pkg-sh", json={
            "labor_pay_type": "Akord", "labor_piece_rate": 7, "reason": "x"}, headers=dict(h)) for _ in range(6)])
        ok, vers, ev, pv = await _check_chain(op, 0, 1)
        print("L2 %s: codes %s | versions %s events %s pkg v%s" % (mode, sorted(r.status_code for r in rs), vers, ev, pv))
        assert ok and max(r.status_code for r in rs) < 500
    run(monkeypatch, scenario, backend, mode)


@pytest.mark.parametrize("mode", MODES)
def test_l3_from_version_three(monkeypatch, mode):
    backend = _real()

    async def scenario(c, op):
        for r in (2, 3, 4):
            assert (await c.put("/api/labor-terms/pkg-sh", json={"labor_pay_type": "Akord", "labor_piece_rate": r,
                                                                "reason": "x"}, headers=H("acct"))).status_code == 200
        rs = await asyncio.gather(*[c.put("/api/labor-terms/pkg-sh", json={
            "labor_pay_type": "Akord", "labor_piece_rate": 10 + r, "reason": "x"}, headers=H("owner")) for r in range(6)])
        k = [r.status_code for r in rs].count(200)
        ok, vers, ev, pv = await _check_chain(op, 0, 3 + k)
        print("L3 %s: codes %s | versions %s pkg v%s ok %s" % (mode, sorted(r.status_code for r in rs), vers, pv, ok))
        assert ok
    run(monkeypatch, scenario, backend, mode)


@pytest.mark.parametrize("rep", range(5))
@pytest.mark.parametrize("mode", MODES)
def test_l4_rate_change_races_approval(monkeypatch, mode, rep):
    backend = _real()

    async def scenario(c, op):
        assert (await c.put("/api/labor-terms/pkg-sh", json={"labor_pay_type": "Akord", "labor_piece_rate": 5,
                                                            "reason": "x"}, headers=H("acct"))).status_code == 200
        r = await c.put("/api/labor-quantities/entry", json={"report_id": "R-AK", "quantity": 120}, headers=H("w-ak", False))
        assert r.status_code == 200, r.text
        await op.employee_daily_reports.update_one({"id": "R-AK"}, {"$set": {"status": "APPROVED"}})
        ver = (await op.employee_daily_reports.find_one({"id": "R-AK"}))["report_version"]
        ra, rc = await asyncio.gather(
            c.post("/api/labor-quantities/approve", json={"report_id": "R-AK", "report_version": ver,
                                                          "approved_quantity": 120, "execution_package_id": "pkg-sh",
                                                          "note": "x"}, headers=H("sm")),
            c.put("/api/labor-terms/pkg-sh", json={"labor_pay_type": "Akord", "labor_piece_rate": 9, "reason": "y"},
                  headers=H("owner")))
        appr = await op.labor_quantity_approvals.find_one({"report_id": "R-AK", "status": "approved"}, {"_id": 0})
        hist = {h["version"]: h["after"] async for h in op.labor_terms_history.find({"package_id": "pkg-sh"})}
        pair = (appr or {}).get("piece_rate"), (appr or {}).get("labor_terms_version")
        real = pair[1] in hist and hist[pair[1]]["labor_piece_rate"] == pair[0]
        if rep == 0 or not real:
            print("L4 %s/%d: approve %s change %s | approval (rate, v) %s | history %s | consistent %s" % (
                mode, rep, ra.status_code, rc.status_code, pair, {v: a["labor_piece_rate"] for v, a in hist.items()}, real))
        assert ra.status_code == 200 and rc.status_code == 200 and real
    run(monkeypatch, scenario, backend, mode)
