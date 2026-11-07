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


@pytest.mark.parametrize("rep", range(10))
def test_o11_lines_put_races_new_version_of_a_draft(monkeypatch, backend, mode, rep):
    """ed68cb9: new-version (Draft allowed since Addendum A) CAS carries updated_at. A lines PUT
    ∥ new-version on a Draft: the new version must copy the lines the old one ends with,
    and a superseded draft must not take the edit."""
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", status="Draft"))
        body = {"lines": [{"activity_name": "Боя", "unit": "m2", "qty": 2, "material_unit_cost": 1,
                           "labor_unit_cost": 1}]}
        rp, rn = await asyncio.gather(c.put("/api/offers/o1/lines", headers=hdr("admin-a"), json=body),
                                      new_version(c, "o1"))
        o = await get(op, "o1")
        v2 = await op.offers.find_one({"parent_offer_id": "o1"}, {"_id": 0})
        print("O11 %s/%d: PUT %s new-version %s | v1 %s total %s | v2 total %s" % (
            mode, rep, rp.status_code, rn.status_code, o["status"], o["total"], (v2 or {}).get("total")))
        if v2:
            assert o["status"] == "Superseded" and v2["total"] == o["total"]
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("rep", range(10))
def test_o12_reject_races_new_version(monkeypatch, backend, mode, rep):
    """/reject (not changed by OFF-01) writes {"id"} only. reject ∥ new-version on a Sent
    offer: does a superseded offer end with status Rejected (observation)?"""
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", token=TOKEN))
        rr, rn = await asyncio.gather(
            c.post("/api/offers/o1/reject", headers=hdr("admin-a"), json={"reason": "x"}), new_version(c, "o1"))
        o = await get(op, "o1")
        print("O12 %s/%d: reject %s new-version %s | status %s superseded_by %s" % (
            mode, rep, rr.status_code, rn.status_code, o["status"], bool(o.get("superseded_by"))))
    run(monkeypatch, backend, mode, scenario)


def test_o13_legacy_pair_parent_is_replaced(monkeypatch, backend, mode):
    """b03b806 FG-135: v1 Sent (token T1, 1200) + v2 Sent child (1500), v1 never marked superseded."""
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("v1", token=TOKEN))
        await op.offers.insert_one(offer_doc("v2", version=2, parent="v1", token="tok" + "f" * 21, total=1500.0))
        g = await c.get("/api/offers/review/%s" % TOKEN)
        r = await respond(c, TOKEN)
        rj = await respond(c, TOKEN, action="reject")
        a = await accept(c, "v1")
        nv = await new_version(c, "v1")
        o = await get(op, "v1")
        leak = [m for m in ("1200", "Плочки", "v1", "ORG-OFF01") if m in g.text]
        print("O13 %s: GET %s leak %s | approve %s reject %s | accept %s | new-version %s | v1 %s" % (
            mode, g.status_code, leak or "none", r.status_code, rj.status_code, a.status_code, nv.status_code, o["status"]))
        assert g.status_code == 410 and not leak and (r.status_code, rj.status_code, a.status_code, nv.status_code) == (409,) * 4
        assert o["status"] == "Sent"
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("rep", range(10))
def test_o14_delete_races_send(monkeypatch, backend, mode, rep):
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", status="Draft"))
        rd, rs = await asyncio.gather(c.delete("/api/offers/o1", headers=hdr("admin-a")),
                                      c.post("/api/offers/o1/send", headers=hdr("admin-a")))
        o = await get(op, "o1")
        print("O14 %s/%d: delete %s send %s | offer %s" % (mode, rep, rd.status_code, rs.status_code,
                                                         (o or {}).get("status", "GONE")))
        assert rd.status_code < 500 and rs.status_code < 500
        assert not (rs.status_code == 200 and o is None), "a sent offer was deleted"
        assert not (rd.status_code == 200 and rs.status_code == 200)
    run(monkeypatch, backend, mode, scenario)


def test_o15_carriers_and_closed_links(monkeypatch, backend, mode):
    async def scenario(c, op):
        out = {}
        for m in ("signed_pdf", "verified_email"):
            await op.offers.delete_many({"id": "oc"})
            await op.offers.insert_one(offer_doc("oc", token=TOKEN))
            r = await accept(c, "oc", body={"approval_method": m})
            out[m] = (r.status_code, code(r), (await get(op, "oc"))["status"])
        await op.offers.insert_one(offer_doc("ok", token="tok" + "g" * 21))
        await cancel(c, "ok")
        g = await c.get("/api/offers/review/%s" % ("tok" + "g" * 21))
        leak = [m for m in ("1200", "Плочки", "lines", "total") if m in g.text]
        print("O15 %s: %s | GET cancelled link %s leak %s" % (mode, out, g.status_code, leak or "none"))
        assert all(v[0] == 422 and v[2] == "Sent" for v in out.values()) and g.status_code == 410 and not leak
    run(monkeypatch, backend, mode, scenario)


def test_o16_r43_client_sees_only_the_combined_price(monkeypatch, backend, mode):
    """5d17063 R43: no client-facing answer (review GET, respond, PDF) carries the
    material / labour split or anything to derive it (line_material_cost, line_labor_cost,
    labor_hours_per_unit, the split figures 40 / 60 / 400 / 600)."""
    async def scenario(c, op):
        doc = offer_doc("o1", token=TOKEN)
        doc["lines"][0].update({"material_unit_cost": 40.0, "labor_unit_cost": 60.0, "line_material_cost": 400.0,
                                "line_labor_cost": 600.0, "labor_hours_per_unit": 1.5})
        await op.offers.insert_one(doc)
        g = await c.get("/api/offers/review/%s" % TOKEN)
        lines = g.json().get("lines", []) if g.status_code == 200 else []
        keys = sorted({k for ln in lines for k in ln})
        bad_keys = [k for k in keys if k in ("material_unit_cost", "labor_unit_cost", "line_material_cost",
                                             "line_labor_cost", "labor_hours_per_unit")]
        nums = [n for n in ('"40.0"', ": 40.0", ": 60.0", ": 400.0", ": 600.0", ": 1.5", "40.00", "60.00") if n in g.text]
        p = await c.get("/api/offers/o1/pdf", headers=hdr("admin-a"))
        txt = ""
        try:
            import io
            from pypdf import PdfReader
            txt = " ".join(pg.extract_text() or "" for pg in PdfReader(io.BytesIO(p.content)).pages)
        except Exception as exc:  # noqa: BLE001
            txt = "<no text: %s>" % type(exc).__name__
        pdf_bad = [w for w in ("Мат", "Труд", "40.00", "60.00", "400.00", "600.00") if w in txt]
        r = await respond(c, TOKEN)
        print("O16 %s: GET %s keys %s bad %s nums %s | PDF %s %d bytes split-terms %s (unit 100.00 present %s) | respond %s %s" % (
            mode, g.status_code, keys, bad_keys or "none", nums or "none", p.status_code, len(p.content),
            pdf_bad or "none", "100.00" in txt, r.status_code, r.text[:60]))
        assert g.status_code == 200 and not bad_keys and not nums and not pdf_bad
        assert lines and lines[0]["unit_price"] == 100.0
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("rep", range(100))
def test_o17_client_approve_races_internal_reject(monkeypatch, backend, mode, rep):
    """acc472f FG-144: public approve ∥ internal reject → exactly one winner; never Rejected with
    accepted_at, never Accepted with rejected_at; exactly one canonical decision event."""
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", token=TOKEN))
        ra, rr = await asyncio.gather(respond(c, TOKEN),
                                      c.post("/api/offers/o1/reject", headers=hdr("admin-a"), json={"reason": "x"}))
        o = await get(op, "o1")
        evs = await op.audit_events.count_documents({"entity_id": "o1", "action": {"$in": [
            "offers.offer.client_approved", "offers.offer.rejected"]}})
        won = [n for n, r in (("approve", ra), ("reject", rr)) if r.status_code == 200]
        if rep < 3 or len(won) != 1:
            print("O17 %s/%d: approve %s reject %s | %s accepted_at %s rejected_at %s | events %d" % (
                mode, rep, ra.status_code, rr.status_code, o["status"], bool(o.get("accepted_at")),
                bool(o.get("rejected_at")), evs))
        assert len(won) == 1 and evs == 1 and max(ra.status_code, rr.status_code) < 500
        assert (o["status"], bool(o.get("accepted_at")), bool(o.get("rejected_at"))) == (
            ("Accepted", True, False) if won == ["approve"] else ("Rejected", False, True))
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("rep", range(20))
def test_o18_double_send(monkeypatch, backend, mode, rep):
    """D-OFF01-18 (send has no key): send ∥ send on one Draft → one 200, one 409; one sent event,
    one snapshot, one offer_events 'sent'."""
    _with_versions(monkeypatch)

    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", status="Draft"))
        r1, r2 = await asyncio.gather(c.post("/api/offers/o1/send", headers=hdr("admin-a")),
                                      c.post("/api/offers/o1/send", headers=hdr("admin-a")))
        ev = await op.audit_events.count_documents({"entity_id": "o1", "action": "offers.offer.sent"})
        snaps = await op.offer_versions.count_documents({"offer_id": "o1"})
        legacy = await op.offer_events.count_documents({"offer_id": "o1", "event_type": "sent"})
        nk = await c.post("/api/offers/o1/reject", headers=hdr("admin-a", key=False), json={"reason": "x"})
        if rep < 2:
            print("O18 %s/%d: send %s %s | sent events %d snapshots %d offer_events %d | reject without key %s" % (
                mode, rep, r1.status_code, r2.status_code, ev, snaps, legacy, nk.status_code))
        assert sorted([r1.status_code, r2.status_code]) == [200, 409] and (ev, snaps, legacy) == (1, 1, 1)
        assert nk.status_code == 428
    run(monkeypatch, backend, mode, scenario)


@pytest.mark.parametrize("rep", range(20))
def test_o19_client_view_races_new_version(monkeypatch, backend, mode, rep):
    """653a1a5 FG-149: a client opening the link (GET review) ∥ new-version on the same Sent
    offer → new-version always 200 (the view no longer bumps updated_at)."""
    async def scenario(c, op):
        await op.offers.insert_one(offer_doc("o1", token=TOKEN))
        g, nv = await asyncio.gather(c.get("/api/offers/review/%s" % TOKEN), new_version(c, "o1"))
        o = await get(op, "o1")
        leak = [k for k in ("view_count", "last_viewed_at", "updated_at") if k in g.text]
        if rep < 2 or nv.status_code != 200:
            print("O19 %s/%d: view %s new-version %s | o1 %s view_count %s | leak %s" % (
                mode, rep, g.status_code, nv.status_code, o["status"], o.get("view_count"), leak or "none"))
        assert nv.status_code == 200 and o["status"] == "Superseded" and not leak
        assert g.status_code in (200, 410)
    run(monkeypatch, backend, mode, scenario)
