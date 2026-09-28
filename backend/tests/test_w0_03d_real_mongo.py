"""
W0-03D against a REAL, disposable, local MongoDB.

Skipped unless ``W0_03_REAL_MONGO_URL`` names a plain local server — the same
local-only guard as test_w0_03c_real_mongo.py (no Atlas, no NAS, no
``mongodb+srv``); each test works in its own ``w003c_realmongo_<random>``
database and drops exactly that database afterwards::

    W0_03_REAL_MONGO_URL=mongodb://localhost:27017 pytest tests/test_w0_03d_real_mongo.py -v --noconftest

What the in-memory double can only model is checked against the server:
``{"merged_into": None}`` compare-and-set semantics, the lock's upsert racing
on the built-in unique ``_id``, duplicate-key handling of the history insert,
and the audit hash chain across merge, interruption, retry and unmerge.
Approval comes from the test-only verifier; the build has none that approves.
"""
import asyncio

import pytest

from app.audit.store import AUDIT_COLLECTION, verify_chain
from app.master_data import merge as mm
from app.master_data import models
from app.master_data.deps import MODE_ENFORCE
from app.master_data.merge import HISTORY_COLLECTION, LOCK_COLLECTION, MasterDataApprovalRequired
from app.master_data.models import build_entity
from app.master_data.repository import MasterDataRepository
from app.master_data.service import MasterDataRefused

from tests.test_w0_03c_real_mongo import Ctx, _refusal, scratch
from tests.test_w0_03d_merge_redirect import TrustedTestVerifier

pytestmark = pytest.mark.skipif(bool(_refusal()), reason=_refusal() or "ok")

ORG = models.ENTITY_ORGANIZATION
T = "tenant-real"
NOW = "2026-09-27T09:00:00+00:00"


async def _seed(db, *ids):
    for eid in ids:
        await db["md_organization"].insert_one(
            build_entity(tenant_id=T, entity_type=ORG, display_name="Фирма " + eid,
                         entity_id=eid, now=NOW))


async def _preview(db, src, tgt):
    return await mm.preview_merge(Ctx(T, db), entity_type=ORG, source_id=src, target_id=tgt,
                                  mode=MODE_ENFORCE, repository=MasterDataRepository(T, db=db))


async def _merge(db, src, tgt, token, key, verifier="trusted", **kw):
    return await mm.merge(Ctx(T, db), entity_type=ORG, source_id=src, target_id=tgt,
                          preview_token=token, idempotency_key=key, confirmation=True,
                          approval_id="APR-" + key, mode=MODE_ENFORCE,
                          repository=MasterDataRepository(T, db=db),
                          approval_verifier=TrustedTestVerifier() if verifier == "trusted"
                          else verifier, **kw)


async def _events(db):
    return await db[AUDIT_COLLECTION].find({"tenant_id": T}, {"_id": 0}).sort(
        "sequence", 1).to_list(None)


def test_merge_resolve_unmerge_on_a_real_server():
    async def body(db, _name):
        await _seed(db, "a", "b")
        p = await _preview(db, "a", "b")
        with pytest.raises(MasterDataApprovalRequired):
            await _merge(db, "a", "b", p["preview_token"], "k0", verifier=None)
        assert (await db["md_organization"].find_one({"id": "a"}))["status"] == "active"

        out = await _merge(db, "a", "b", p["preview_token"], "k1")
        assert out.performed
        r = await mm.resolve(Ctx(T, db), entity_type=ORG, entity_id="a", mode=MODE_ENFORCE,
                             repository=MasterDataRepository(T, db=db))
        assert r["canonical_id"] == "b" and r["chain"] == ["a", "b"]
        assert (await _merge(db, "a", "b", p["preview_token"], "k1")).replayed

        up = await mm.preview_unmerge(Ctx(T, db), entity_type=ORG, source_id="a",
                                      mode=MODE_ENFORCE, repository=MasterDataRepository(T, db=db))
        done = await mm.unmerge(Ctx(T, db), entity_type=ORG, source_id="a",
                                merge_event_id=out.event_id, preview_token=up["preview_token"],
                                idempotency_key="u1", reason="real-mongo check", confirmation=True,
                                approval_id="APR-u1", mode=MODE_ENFORCE,
                                repository=MasterDataRepository(T, db=db),
                                approval_verifier=TrustedTestVerifier())
        assert done.performed and done.target_id == "b"
        kinds = [e["kind"] for e in await db[HISTORY_COLLECTION].find({}).sort(
            "sequence", 1).to_list(None)]
        assert kinds == ["merge", "unmerge"]
        # C02: the server sorts by sequence before the limit — a causal prefix
        for limit, expected in ((1, ["merge"]), (2, ["merge", "unmerge"]), (1000, ["merge", "unmerge"])):
            got = await mm.history(Ctx(T, db), entity_type=ORG, entity_id="a", mode=MODE_ENFORCE,
                                   repository=MasterDataRepository(T, db=db), limit=limit)
            assert [e["kind"] for e in got] == expected, limit
        assert await db["md_organization"].count_documents({}) == 2, "nothing deleted"
        assert verify_chain(await _events(db)) == (True, None)
    scratch(body)


def test_c02_history_limit_and_cap_follow_server_causal_sort_not_natural_order():
    """A real cursor must sort before limit even when insertion order is reversed."""
    async def body(db, _name):
        await _seed(db, "a", "b")
        first_preview = await _preview(db, "a", "b")
        first = await _merge(db, "a", "b", first_preview["preview_token"], "c02-first")
        undo_preview = await mm.preview_unmerge(
            Ctx(T, db), entity_type=ORG, source_id="a", mode=MODE_ENFORCE,
            repository=MasterDataRepository(T, db=db))
        undo = await mm.unmerge(
            Ctx(T, db), entity_type=ORG, source_id="a",
            merge_event_id=first.event_id, preview_token=undo_preview["preview_token"],
            idempotency_key="c02-undo", reason="real-Mongo causal history", confirmation=True,
            approval_id="APR-c02-undo", mode=MODE_ENFORCE,
            repository=MasterDataRepository(T, db=db),
            approval_verifier=TrustedTestVerifier())
        second_preview = await _preview(db, "a", "b")
        second = await _merge(db, "a", "b", second_preview["preview_token"], "c02-second")

        events = await db[HISTORY_COLLECTION].find(
            {"tenant_id": T, "source_id": "a", "target_id": "b"}, {"_id": 0}
        ).sort("sequence", 1).to_list(None)
        assert [(e["kind"], e["sequence"]) for e in events] == [
            ("merge", 1), ("unmerge", 2), ("merge", 3)]
        assert [e["id"] for e in events] == [first.event_id, undo.event_id, second.event_id]
        for entity in ("a", "b"):
            for limit, expected in ((2, [1, 2]), (3, [1, 2, 3])):
                got = await mm.history(
                    Ctx(T, db), entity_type=ORG, entity_id=entity,
                    mode=MODE_ENFORCE, repository=MasterDataRepository(T, db=db), limit=limit)
                assert [e["sequence"] for e in got] == expected
                assert all(e["kind"] != "unmerge" or
                           e["reverses_event_id"] in {m["id"] for m in got if m["kind"] == "merge"}
                           for e in got)

        # Test-only mirror events make the natural server order intentionally 3,2,1.
        # The application API must still return 1,2 for a bounded answer.
        mirror = []
        for event in events:
            copy = dict(event)
            copy.update(id="c02-reverse-%d" % event["sequence"],
                        source_id="reverse-src", target_id="reverse-tgt")
            if copy["kind"] == "unmerge":
                copy["reverses_event_id"] = "c02-reverse-1"
            mirror.append(copy)
        await db[HISTORY_COLLECTION].insert_many(list(reversed(mirror)))
        natural = await db[HISTORY_COLLECTION].find(
            {"source_id": "reverse-src"}, {"_id": 0}).sort("$natural", 1).to_list(None)
        assert [e["sequence"] for e in natural] == [3, 2, 1]
        reversed_prefix = await mm.history(
            Ctx(T, db), entity_type=ORG, entity_id="reverse-src", mode=MODE_ENFORCE,
            repository=MasterDataRepository(T, db=db), limit=2)
        assert [(e["kind"], e["sequence"]) for e in reversed_prefix] == [
            ("merge", 1), ("unmerge", 2)]

        # More than 500 events in reverse insertion order expose pre-sort truncation.
        capped = []
        for seq in range(1, 602):
            event = {"id": "c02-cap-%04d" % seq, "tenant_id": T, "entity_type": ORG,
                     "source_id": "cap-src", "target_id": "cap-tgt", "sequence": seq,
                     "kind": "merge" if seq % 2 else "unmerge"}
            if seq % 2 == 0:
                event["reverses_event_id"] = "c02-cap-%04d" % (seq - 1)
            capped.append(event)
        await db[HISTORY_COLLECTION].insert_many(list(reversed(capped)))
        await db[HISTORY_COLLECTION].insert_many([
            {"id": "c02-other-tenant", "tenant_id": "other-tenant", "entity_type": ORG,
             "source_id": "cap-src", "target_id": "cap-tgt", "sequence": 0,
             "kind": "merge"},
            {"id": "c02-other-type", "tenant_id": T, "entity_type": models.ENTITY_ITEM,
             "source_id": "cap-src", "target_id": "cap-tgt", "sequence": 0,
             "kind": "merge"},
        ])
        got = await mm.history(
            Ctx(T, db), entity_type=ORG, entity_id="cap-src", mode=MODE_ENFORCE,
            repository=MasterDataRepository(T, db=db), limit=1000)
        assert len(got) == 500
        assert [e["sequence"] for e in got] == list(range(1, 501))
        assert {(e["tenant_id"], e["entity_type"]) for e in got} == {(T, ORG)}
        assert (await db["md_organization"].count_documents({})) == 2, "no hard delete"
        assert verify_chain(await _events(db)) == (True, None)
    scratch(body)


def test_an_interrupted_merge_is_finished_by_its_retry_on_a_real_server():
    async def body(db, _name):
        await _seed(db, "a", "b", "c")
        p = await _preview(db, "a", "b")
        with pytest.raises(mm._Interrupted):
            await _merge(db, "a", "b", p["preview_token"], "k1", _fail_after="source_written")
        pc = await _preview(db, "c", "b")
        with pytest.raises(MasterDataRefused):              # the lock is still held
            await _merge(db, "c", "b", pc["preview_token"], "k2")
        out = await _merge(db, "a", "b", p["preview_token"], "k1")
        assert out.performed and out.resumed
        assert await db[HISTORY_COLLECTION].count_documents({}) == 1
        assert (await db[LOCK_COLLECTION].find_one({}))["holder"] is None
        success = [e for e in await _events(db) if e["result"] == "success"]
        assert [e["action"] for e in success] == ["master_data.organization.merged"]
        assert verify_chain(await _events(db)) == (True, None)
    scratch(body)


def test_crossing_merges_on_a_real_server_cannot_form_a_cycle():
    async def body(db, _name):
        await _seed(db, "a", "b")
        t_ab = (await _preview(db, "a", "b"))["preview_token"]
        t_ba = (await _preview(db, "b", "a"))["preview_token"]

        async def one(src, tgt, token, key):
            try:
                return await _merge(db, src, tgt, token, key)
            except MasterDataRefused as exc:
                return exc
        results = await asyncio.gather(one("a", "b", t_ab, "k-ab"), one("b", "a", t_ba, "k-ba"))
        assert sum(1 for r in results if not isinstance(r, Exception)) == 1
        statuses = sorted([d["status"] async for d in db["md_organization"].find({})])
        assert statuses == ["active", "merged"]
    scratch(body)
