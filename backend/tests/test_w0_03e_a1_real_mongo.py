"""
W0-03E-A1 / C01 — the A/B collision matrix on a disposable REAL MongoDB.

Same coroutine as ``tests/test_w0_03e_a1_collision_matrix.py`` (actual HTTP
routes over the ASGI transport, on the motor client's event loop), against a
fresh scratch database on a local server that ``W0_03_REAL_MONGO_URL`` names.
The URL is refused unless it is loopback (W0-03C ``check_local``); every
database is created with a random ``w003c_realmongo_`` name and dropped after
the test. Never Atlas, NAS, production or a real BEG database.

Run:  W0_03_REAL_MONGO_URL=mongodb://127.0.0.1:<port> \
      pytest tests/test_w0_03e_a1_real_mongo.py -v --noconftest
"""
import pytest

from tests.test_w0_03c_real_mongo import _refusal, scratch
from tests.test_w0_03e_a1_collision_matrix import (
    EXPECTED_PATHS, SHARED_IDS, _a1_world, _matrix,
)
from tests.test_w0_03e_c03_isolation import MODES
from tests.test_w0_03e_legacy_migration import ORG_A, ORG_B

pytestmark = pytest.mark.skipif(bool(_refusal()), reason=_refusal() or "ok")


@pytest.fixture
def plain_pdf_fonts(monkeypatch):
    import reportlab.pdfbase.ttfonts as ttfonts

    def unavailable(*a, **kw):
        raise OSError("font unavailable in this test")
    monkeypatch.setattr(ttfonts, "TTFont", unavailable)


@pytest.mark.parametrize("mode", MODES)
def test_a1_collision_matrix_on_a_real_server(monkeypatch, plain_pdf_fonts, mode):
    async def body(db, _name):
        await _a1_world(db)
        # on the server too, a global id lookup would return B's copy first
        for entity, (coll, rid) in SHARED_IDS.items():
            assert (await db[coll].find_one({"id": rid}))["org_id"] == ORG_B, entity
        return await _matrix(monkeypatch, db, mode)
    assert set(scratch(body)) == EXPECTED_PATHS


def test_the_scoped_join_and_refusals_on_a_real_server():
    from app.tenancy.data_access import TenantData, TenantScopeViolation

    async def body(db, _name):
        for org, no in ((ORG_B, "B-SECRET-INVOICE"), (ORG_A, "A-INV")):
            await db.invoices.insert_one({"id": "i1", "org_id": org, "invoice_no": no})
            await db.invoice_lines.insert_one({"id": "l1", "org_id": org, "invoice_id": "i1"})
        await db.invoice_lines.insert_one({"id": "l2", "org_id": ORG_A, "invoice_id": "i-only-b"})
        await db.invoices.insert_one({"id": "i-only-b", "org_id": ORG_B, "invoice_no": "B-SECRET-INVOICE"})
        tenant = TenantData.for_user(db, {"id": "u", "org_id": ORG_A})
        rows = await tenant.invoice_lines.aggregate(
            tenant.lookup("invoices", "invoice_id", "inv") + [{"$sort": {"id": 1}}]).to_list(None)
        assert [[i["invoice_no"] for i in r["inv"]] for r in rows] == [["A-INV"], []]
        with pytest.raises(TenantScopeViolation):
            tenant.invoice_lines.aggregate([{"$lookup": {
                "from": "invoices", "localField": "invoice_id", "foreignField": "id", "as": "inv"}}])
        with pytest.raises(TenantScopeViolation):
            await tenant.invoices.find_one({"org_id": ORG_B})
        assert (await tenant.invoices.get("i-only-b")) is None
    scratch(body)
