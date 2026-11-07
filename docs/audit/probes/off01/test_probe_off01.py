"""CLAUDE AUDIT probe — #79 OFF-01 (ea9df81). Copy into backend/tests/; real Mongo RS
(W0_03_REAL_MONGO_URL), off / shadow / enforce. Reuses the PR's own harness.
  O1  D-OFF01-7 restore bypass: a SENT offer (token, total 1200) + an older snapshot
      (total 12) → POST /offers/{id}/versions/1/restore → then the client approves by
      the link → what total is Accepted?  Same on an ACCEPTED and a SUPERSEDED offer.
  O2  the public 409 after a new version names no internal id / org / version id.
  O3  the same token string in tenant A and tenant B → the link is refused (never B's).
  O4  ×10: new-version ∥ internal accept ∥ public approve ∥ cancel on one Sent offer →
      at most ONE of them wins, and the stored state matches the winner.
  O5  public respond: same key, other offer of the same tenant → 409, nothing written;
      same key same body → same answer, one canonical event.
  O6  DELETE: Cancelled / Superseded / v2 draft → 409; never-sent draft → 200.
  O7  accept with an evidence_file_id that does not exist → accepted? (observation)
"""
import asyncio
import pytest

from tests.test_off_01_offer_version_accept import (  # noqa: F401
    ORG_A, ORG_B, PRJ_A, PRJ_B, TOKEN, accept, backend, cancel, code, events, get, hdr,
    mode, new_version, offer_doc, pub, respond, run)

LEAK_MARKERS = ("ORG-OFF01", "o1", "superseded_by", "org_id", "Traceback")


def _with_versions(monkeypatch):
    """The PR's app + the offer_versions router (the restore route)."""
    import tests.test_off_01_offer_version_accept as T
    real_app = T._app

    def app(mp, op, sysdb, mode_):
        a = real_app(mp, op, sysdb, mode_)
        from app.routes import offer_versions as ov
        mp.setattr(ov, "db", op, raising=False)
        a.include_router(ov.router, prefix="/api")
        return a
    monkeypatch.setattr(T, "_app", app)


def _snapshot(oid, total):
    return {"id": "ver-" + oid, "org_id": ORG_A, "project_id": PRJ_A, "offer_id": oid,
            "version_number": 1, "created_at": "2026-11-01T09:00:00+00:00", "created_by": "admin-a",
            "note": "old", "is_auto_backup": False,
            "snapshot_json": {"title": "Баня", "currency": "EUR", "vat_percent": 20, "notes": "",
                              "lines": [{"id": "ln-x", "activity_name": "Плочки", "unit": "m2", "qty": 1,
                                         "material_unit_cost": 5, "labor_unit_cost": 5, "line_total": 10.0}],
                              "subtotal": 10.0, "vat_amount": 2.0, "total": total}}


@pytest.mark.parametrize("start", ["Sent", "Accepted", "Superseded"])
def test_o1_restore_rewrites_a_sent_offer(monkeypatch, backend, mode, start):
    _with_versions(monkeypatch)

    async def scenario(c, op):
        extra = {"superseded_by": "v2-x"} if start == "Superseded" else {}
        await op.offers.insert_one(offer_doc("o1", status=start, token=TOKEN, **extra))
        await op.offer_versions.insert_one(_snapshot("o1", 12.0))
        r = await c.post("/api/offers/o1/versions/1/restore", headers=hdr("admin-a"))
        after = await get(op, "o1")
        ap = await respond(c, TOKEN) if start == "Sent" else None
        final = await get(op, "o1")
        print("O1 %s/%s: restore %s | total %s -> %s | client approve %s | final status %s total %s" % (
            mode, start, r.status_code, 1200.0, after["total"], ap.status_code if ap else "-",
            final["status"], final["total"]))
        assert r.status_code >= 400 and after["total"] == 1200.0, \
            "a %s offer's price was rewritten in place by restore (%s -> %s)" % (start, 1200.0, after["total"])
    run(monkeypatch, backend, mode, scenario)


def test_o2_public_409_leaks_nothing(monkeypatch, backend, mode):
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", token=TOKEN))
        v2 = (await new_version(c, "o1")).json()
        r = await respond(c, TOKEN)
        g = await c.get("/api/offers/review/%s" % TOKEN)
        leaks = [m for m in LEAK_MARKERS + (v2["id"],) if m in r.text]
        print("O2 %s: respond %s %s | leaks %s | GET review %s status %s lines %s" % (
            mode, r.status_code, r.text[:160], leaks or "none", g.status_code,
            g.json().get("status") if g.status_code == 200 else "-",
            len(g.json().get("lines", [])) if g.status_code == 200 else "-"))
        assert r.status_code == 409 and not leaks
    run(monkeypatch, backend, mode, scenario)


def test_o3_same_token_in_two_tenants(monkeypatch, backend, mode):
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("oa", token=TOKEN))
        await op.offers.insert_one(offer_doc("ob", org=ORG_B, project=PRJ_B, token=TOKEN))
        g = await c.get("/api/offers/review/%s" % TOKEN)
        r = await respond(c, TOKEN)
        a, b = await get(op, "oa"), await get(op, "ob")
        print("O3 %s: GET %s | respond %s | A %s | B %s" % (mode, g.status_code, r.status_code,
                                                          a["status"], b["status"]))
        assert r.status_code in (404, 409) and a["status"] == b["status"] == "Sent"
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("rep", range(10))
def test_o4_four_way_race(monkeypatch, backend, mode, rep):
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", token=TOKEN))
        rs = await asyncio.gather(new_version(c, "o1"), accept(c, "o1"), respond(c, TOKEN), cancel(c, "o1"))
        names = ["new_version", "accept", "approve", "cancel"]
        won = [n for n, r in zip(names, rs) if r.status_code in (200, 201)]
        o = await get(op, "o1")
        v2 = await op.offers.count_documents({"parent_offer_id": "o1"})
        evs = await op.audit_events.count_documents({"entity_id": "o1"})
        print("O4 %s/%d: %s | won %s | o1 %s | v2 docs %d | events on o1 %d" % (
            mode, rep, [r.status_code for r in rs], won, o["status"], v2, evs))
        assert len(won) == 1 and not any(r.status_code >= 500 for r in rs)
        want = {"new_version": "Superseded", "accept": "Accepted", "approve": "Accepted",
                "cancel": "Cancelled"}[won[0]]
        assert o["status"] == want and v2 == (1 if won == ["new_version"] else 0) and evs == 1
    run(monkeypatch, backend, mode, scenario)


def test_o5_public_key_reuse(monkeypatch, backend, mode):
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", token=TOKEN))
        await op.offers.insert_one(offer_doc("o2", token="tok" + "b" * 21))
        r1 = await respond(c, TOKEN, key="k-same")
        r2 = await respond(c, TOKEN, key="k-same")
        r3 = await respond(c, "tok" + "b" * 21, key="k-same")
        o2 = await get(op, "o2")
        evs = len(await events(op, "offers.offer.client_approved"))
        print("O5 %s: first %s replay %s same=%s | other offer same key %s %s | o2 %s | events %d" % (
            mode, r1.status_code, r2.status_code, r1.json() == r2.json(), r3.status_code, r3.text[:120],
            o2["status"], evs))
        assert (r1.status_code, r2.status_code) == (200, 200) and r1.json() == r2.json() and evs == 1
        assert r3.status_code == 409 and o2["status"] == "Sent"
    run(monkeypatch, backend, mode, scenario)


def test_o6_delete_matrix(monkeypatch, backend, mode):
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", token=TOKEN))
        v2 = (await new_version(c, "o1")).json()["id"]
        await op.offers.insert_one(offer_doc("oc", status="Sent", token="tok" + "c" * 21))
        await cancel(c, "oc")
        await op.offers.insert_one(offer_doc("od", status="Draft"))
        out = {}
        for oid in ("o1", v2, "oc", "od"):
            r = await c.delete("/api/offers/%s" % oid, headers=hdr("admin-a"))
            out[oid if oid != v2 else "v2"] = (r.status_code, code(r))
        left = await op.offers.count_documents({})
        print("O6 %s: %s | offers left %d" % (mode, out, left))
        assert [out[k][0] for k in ("o1", "v2", "oc", "od")] == [409, 409, 409, 200] and left == 3
    run(monkeypatch, backend, mode, scenario)


def test_o7_accept_evidence_file_unchecked(monkeypatch, backend, mode):
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", token=TOKEN))
        r = await accept(c, "o1", body={"approval_method": "signed_pdf", "evidence_file_id": "file-of-nobody"})
        print("O7 %s: accept with a non-existent evidence_file_id -> %s %s" % (
            mode, r.status_code, (await get(op, "o1")).get("approval", {}).get("evidence_file_id")))
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("rep", range(15))
def test_o8_restore_races_send(monkeypatch, backend, mode, rep):
    """Addendum A (449c1f4): restore is refused unless the offer is an unsent Draft — but the
    check is a read before an unconditional write. restore ∥ send on a Draft: can the offer
    end up Sent with the RESTORED price while the send snapshot (what was sent) says another?"""
    _with_versions(monkeypatch)

    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", status="Draft"))
        await op.offer_versions.insert_one(_snapshot("o1", 12.0))
        rs, rr = await asyncio.gather(
            c.post("/api/offers/o1/send", headers=hdr("admin-a")),
            c.post("/api/offers/o1/versions/1/restore", headers=hdr("admin-a")))
        o = await get(op, "o1")
        sent = await op.offer_versions.find_one({"offer_id": "o1", "note": {"$regex": "изпращане"}}, {"_id": 0})
        sent_total = (sent or {}).get("snapshot_json", {}).get("total")
        print("O8 %s/%d: send %s restore %s | status %s total %s | sent snapshot total %s" % (
            mode, rep, rs.status_code, rr.status_code, o["status"], o["total"], sent_total))
        if o["status"] == "Sent":
            assert o["total"] == sent_total, "Sent offer differs from what was sent: %s vs %s" % (
                o["total"], sent_total)
    run(monkeypatch, backend, mode, scenario)


def test_o9_addendum_a_paths(monkeypatch, backend, mode):
    _with_versions(monkeypatch)

    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("os", status="Sent", token=TOKEN))
        await op.offers.insert_one(offer_doc("oa", status="Accepted", token="tok" + "d" * 21))
        for oid in ("os", "oa"):
            await op.offer_versions.insert_one(dict(_snapshot(oid, 12.0), id="ver-" + oid))
        out = {}
        for oid in ("os", "oa"):
            r1 = await c.post("/api/offers/%s/versions/1/restore" % oid, headers=hdr("admin-a"))
            r2 = await c.delete("/api/offers/%s/versions/1" % oid, headers=hdr("admin-a"))
            out[oid] = (r1.status_code, r2.status_code, (await get(op, oid))["total"],
                        await op.offer_versions.count_documents({"offer_id": oid}))
        nv = await new_version(c, "oa")
        await op.media_files.insert_one({"id": "mf-b", "org_id": ORG_B, "context_type": None})
        await op.media_files.insert_one({"id": "mf-other", "org_id": ORG_A, "context_type": "project",
                                         "context_id": "prj-elsewhere"})
        ev = {}
        for fid in ("mf-b", "mf-other", "file-of-nobody"):
            await op.offers.delete_many({"id": "ox"})
            await op.offers.insert_one(offer_doc("ox", token="tok" + "e" * 21))
            r = await accept(c, "ox", body={"approval_method": "signed_pdf", "evidence_file_id": fid})
            ev[fid] = (r.status_code, code(r), (await get(op, "ox"))["status"])
        print("O9 %s: restore/delete-version %s | new-version of Accepted %s %s | evidence %s" % (
            mode, out, nv.status_code, code(nv), ev))
        assert all(v[:2] == (409, 409) and v[2] == 1200.0 and v[3] == 1 for v in out.values())
        assert nv.status_code == 409 and all(v[0] == 422 and v[2] == "Sent" for v in ev.values())
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("rep", range(15))
def test_o10_vat_put_races_send(monkeypatch, backend, mode, rep):
    """e0dce63 (OFF79-03 CAS): PUT /offers/{id} {"vat_percent": 9} writes twice (the field,
    then the recomputed totals). send ∥ that PUT: a Sent offer must be self-consistent
    (total = subtotal × (1 + vat)) and equal to the send snapshot."""
    _with_versions(monkeypatch)

    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", status="Draft"))
        rp, rs = await asyncio.gather(
            c.put("/api/offers/o1", headers=hdr("admin-a"), json={"vat_percent": 9}),
            c.post("/api/offers/o1/send", headers=hdr("admin-a")))
        o = await get(op, "o1")
        sent = await op.offer_versions.find_one({"offer_id": "o1"}, {"_id": 0})
        snap = (sent or {}).get("snapshot_json", {})
        want_total = round(o["subtotal"] * (1 + (o.get("vat_percent") or 0) / 100), 2)
        print("O10 %s/%d: PUT %s send %s | status %s vat %s total %s (consistent %s) | snapshot vat %s total %s" % (
            mode, rep, rp.status_code, rs.status_code, o["status"], o.get("vat_percent"), o["total"],
            o["total"] == want_total, snap.get("vat_percent"), snap.get("total")))
        if o["status"] == "Sent":
            assert o["total"] == want_total and (snap.get("vat_percent"), snap.get("total")) == (
                o.get("vat_percent"), o["total"])
    run(monkeypatch, backend, mode, scenario)
