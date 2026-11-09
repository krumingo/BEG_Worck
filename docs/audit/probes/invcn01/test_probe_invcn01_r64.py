"""CLAUDE AUDIT probe — #84 INV-CN-01 R64 / FG-415 (8d2a48e). Copy into backend/tests/; real Mongo
or mongomock as the PR's own harness, off / shadow / enforce.
  R64a  An accepted difference on a supplier line, reversed by the Owner; its project is then
        Archived; the Accountant re-books it "back to the line's own allocation" (target project,
        no project_id). R64 says: a proposal for the Owner, never booked at once. Three shapes of
        the SAME line allocation to the archived project:
          new     allocations[] = [{type: project, ref_id: prj-1}]      (the PR's own test)
          legacy  allocation_type / allocation_ref_id (no allocations[]) — the deprecated single
                  allocation that canonical_material_cost.effective_allocations still reads
          camel   allocations[] = [{type: project, refId: prj-1}]       — also read by
                  effective_allocations
"""
import pytest

from tests.test_inv_cn_01_credit_notes import (  # noqa: F401
    ORG_A, hdr, mode, note, run, sent)

SHAPES = {
    "new": {"allocations": [{"type": "project", "ref_id": "prj-1", "qty": 10}]},
    "legacy": {"allocation_type": "project", "allocation_ref_id": "prj-1"},
    "camel": {"allocations": [{"type": "project", "refId": "prj-1", "qty": 10}]},
}


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_r64a_back_to_own_allocation_on_an_archived_project(monkeypatch, mode, shape):
    async def scenario(c, op):
        bill = await sent(c, direction="Received", project="prj-1")
        row = {"id": "il-p", "org_id": ORG_A, "invoice_id": bill["id"], "description": "il-p",
               "qty": 10, "unit_price": 10, "line_total_ex_vat": 100.0, "vat_amount": 20.0,
               "created_at": "2026-10-02T08:00:00+00:00", **SHAPES[shape]}
        await op.invoice_lines.insert_one(row)
        await op.expected_credit_notes.insert_one({
            "id": "ecn_p", "org_id": ORG_A, "invoice_id": bill["id"], "amount": 36.0, "status": "open",
            "created_at": "2026-10-05T08:00:00+00:00", "dq_task": {"status": "open"}})
        n = (await note(c, bill, number="CN-P", expected_credit_note_ids=["ecn_p"],
                        lines=[{"original_line_id": "il-p", "amount": 25.0}])).json()
        base = "/api/finance/credit-notes/%s" % n["id"]
        acc = await c.post(base + "/accept-difference", headers=hdr("owner-a"), json={"reason": "не коригира"})
        assert acc.status_code == 200, acc.text
        lines = acc.json()["difference_accepted"].get("lines") or []
        rev = await c.post(base + "/reverse-difference", headers=hdr("owner-a"), json={"reason": "грешно"})
        assert rev.status_code == 200, rev.text
        await op.projects.update_one({"id": "prj-1"}, {"$set": {"status": "Archived"}})
        before = (await op.credit_debit_notes.find_one({"id": n["id"]}))["difference_accepted"]["postings"]
        r = await c.post(base + "/difference-lines/il-p/resolve", headers=hdr("acct-a"),
                         json={"target": "project", "reason": "обратно на обекта"})
        after_doc = (await op.credit_debit_notes.find_one({"id": n["id"]}))["difference_accepted"]
        props = after_doc.get("proposals") or []
        booked = len(after_doc["postings"]) - len(before)
        print("R64a %s/%s: accepted lines %s | resolve %s | proposals %s | booked at once %s" % (
            mode, shape, [(l.get("original_line_id"), l.get("target"), l.get("basis")) for l in lines],
            r.status_code, [(p.get("why_approval"), p.get("project_statuses")) for p in props], booked))
        assert r.status_code in (200, 409, 422), r.text
        assert booked == 0, "re-booked onto an Archived project at once, without the Owner (R64)"
    run(monkeypatch, mode, scenario)
