"""CLAUDE AUDIT probe — #89 OFF-02 (1b13d11). Copy into backend/tests/; real Mongo
(W0_03_REAL_MONGO_URL), off / shadow / enforce. Reuses the PR's own OFF-01/OFF-02 harness.
  P1  A SiteManager reads his draft offer (money stripped, like FG-350 intends), changes only a
      quantity in the editor and saves the lines he was given (PUT /offers/{id}/lines).
      Are the stored client prices kept, or silently replaced by the model defaults (0)?
"""
import pytest

import tests.test_off_02_offer_money_strip as O
from tests.test_off_02_offer_money_strip import _with_extra_works, LINE  # noqa: F401
from tests.test_off_01_offer_version_accept import (  # noqa: F401
    PRJ_A, backend, get, mode, run)
import tests.test_off_01_offer_version_accept as T


def test_p1_site_manager_round_trip_keeps_prices(monkeypatch, backend, mode):
    async def scenario(c, op):
        r = await c.post("/api/offers", headers=T.hdr("site-a"), json={
            "project_id": PRJ_A, "title": "Кухня", "vat_percent": 20, "lines": [LINE]})
        assert r.status_code == 201, r.text[:300]
        oid = r.json()["id"]
        before = await get(op, oid)
        seen = await c.get("/api/offers/%s" % oid, headers=T.hdr("site-a"))
        assert seen.status_code == 200, seen.text[:300]
        lines = seen.json()["lines"]
        sent = [{k: v for k, v in dict(l, qty=12).items()
                 if k in ("activity_code", "activity_name", "unit", "qty", "material_unit_cost",
                          "labor_unit_cost", "labor_hours_per_unit", "note", "sort_order",
                          "activity_type", "activity_subtype")} for l in lines]
        put = await c.put("/api/offers/%s/lines" % oid, headers=T.hdr("site-a"), json={"lines": sent})
        after = await get(op, oid)
        print("P1 %s/%s: GET keys %s | PUT %s | before mat=%s lab=%s total=%s | after mat=%s lab=%s total=%s" % (
            backend, mode, sorted(lines[0]), put.status_code,
            before["lines"][0]["material_unit_cost"], before["lines"][0]["labor_unit_cost"], before["total"],
            after["lines"][0]["material_unit_cost"], after["lines"][0]["labor_unit_cost"], after["total"]))
        if put.status_code == 200:
            assert after["lines"][0]["material_unit_cost"] == 8 and \
                after["lines"][0]["labor_unit_cost"] == 12, \
                "a SiteManager save of the stripped lines zeroed the client prices"
    run(monkeypatch, backend, mode, scenario)
