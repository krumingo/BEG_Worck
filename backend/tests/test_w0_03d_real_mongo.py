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
            "recorded_at", 1).to_list(None)]
        assert kinds == ["merge", "unmerge"]
        assert await db["md_organization"].count_documents({}) == 2, "nothing deleted"
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
