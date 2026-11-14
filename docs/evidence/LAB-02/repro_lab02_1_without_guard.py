import app.routes.labor_quantities as lq
from tests import test_lab_02_quantity_approval as t

def test_without_the_guard(monkeypatch):
    async def noop(raw_db): return 0
    async def plain(coll, rec): await coll.insert_one(dict(rec))
    monkeypatch.setattr(lq, "ensure_labor_indexes", noop)
    monkeypatch.setattr(lq, "_insert_decision", plain)
    t.test_lab02_1_concurrent_approvals_leave_one_active_record(monkeypatch, "real")
