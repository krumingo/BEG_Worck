"""
W0-03C review fix (PR #19): who may use the office screen, a pending row that
stays single under concurrency, and sources that are not lost when repeats merge.

1. **Access.** The screen follows the canonical catalog, not AdminRoute. The
   frontend keeps a copy of exactly the rights it needs
   (``frontend/src/lib/masterDataAccess.json``); the first test fails when that
   copy and ``app/permissions/catalog.py`` drift apart. The HTTP matrix below
   pins what each role really gets from the six endpoints.

2. **Concurrency.** A MongoDB upsert whose filter is not covered by a unique
   index is not atomic: two writers can both find nothing and both insert.
   ``RacyCollection`` reproduces exactly that — it decides "no match", yields to
   the event loop, and only then inserts — while ``_id`` stays unique, as in
   every MongoDB collection. Two ``propose`` calls run truly concurrently
   through ``asyncio.gather`` and interleave at that point.
   ``test_the_double_reproduces_the_race_a_plain_upsert_loses`` proves the
   double would catch the old implementation; the same file was also run
   against the old head, where the concurrency tests fail (see the HANDOFF).

3. **Sources.** A repeat is counted on the open row. The first sighting stays in
   ``source_channel`` / ``source_ref``; every channel that saw the text is kept
   in ``source_channels`` and the latest one in ``last_source_*``, and the
   source filter finds the row under each of its channels.

Run:  pytest tests/test_w0_03c_access_concurrency_sources.py -v --noconftest
"""
import asyncio
import json
import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps.auth import get_current_user
from app.master_data import models, pending as pending_mod, review
from app.master_data.pending import (
    PENDING_COLLECTION,
    PENDING_SLOT_COLLECTION,
    SOURCE_EXCEL,
    SOURCE_OCR,
    STATUS_PENDING,
    STATUS_REJECTED,
)
from app.master_data.repository import MasterDataRepository
from app.permissions import catalog
from app.routes import master_data as routes

from tests.test_w0_03b3_review_and_matching import Ctx, Result, SpyCollection, SpyDb, run
from tests.test_w0_03c_intake_and_office_api import (  # noqa: F401 — fixture
    AI_ASSET,
    ASSET_TYPE,
    ENV_MODE,
    ENV_PERMISSION_MODE,
    OFFICE,
    wired,
)
from app.master_data import intake_hooks

ORG = models.ENTITY_ORGANIZATION
ACTIVITY = models.ENTITY_ACTIVITY
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND_ACCESS = REPO_ROOT / "frontend" / "src" / "lib" / "masterDataAccess.json"
SCREEN_ACTIONS = {routes.ACTION_PENDING_READ, routes.ACTION_APPROVE, routes.ACTION_REJECT}


# ===========================================================================
# 1. access — the screen follows the canonical catalog
# ===========================================================================

def test_the_frontend_copy_of_the_rights_is_the_catalog():
    mirror = json.loads(FRONTEND_ACCESS.read_text(encoding="utf-8"))

    assert mirror["legacy_role_map"] == catalog.LEGACY_ROLE_MAP

    expected = {}
    for role_id in list(catalog.CANONICAL_ROLES) + list(catalog.LEGACY_ROLES):
        granted = catalog.role_actions(role_id) & SCREEN_ACTIONS
        if granted:
            expected[role_id] = sorted(granted)
    assert {r: sorted(a) for r, a in mirror["role_actions"].items()} == expected


def test_the_office_holds_the_rights_that_admin_route_denied_it():
    office = catalog.role_actions("office")
    assert SCREEN_ACTIONS <= office
    for legacy in ("SiteManager", "Accountant"):
        rights = catalog.role_actions(catalog.LEGACY_ROLE_MAP[legacy])
        assert routes.ACTION_PENDING_READ in rights
        assert not ({routes.ACTION_APPROVE, routes.ACTION_REJECT} & rights)


def _client_as(role, monkeypatch, ctx):
    monkeypatch.setenv(ENV_MODE, "enforce")
    monkeypatch.setenv(ENV_PERMISSION_MODE, "off")      # the canonical catalog decides

    async def resolved(request, user):
        return ctx

    monkeypatch.setattr(routes, "get_tenant_context", resolved)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    async def session_user():
        return {"id": "u-" + str(role), "role": role}

    app.dependency_overrides[get_current_user] = session_user
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("role, may_read, may_decide", [
    ("office", True, True),
    ("Admin", True, True),
    ("Owner", True, True),
    ("SiteManager", True, False),
    ("Accountant", True, False),
    ("Technician", False, False),
    ("Viewer", False, False),
    ("Driver", False, False),
    ("Warehousekeeper", False, False),
])
def test_what_each_role_gets_from_the_screens_endpoints(role, may_read, may_decide,
                                                         wired, monkeypatch):
    db, ctx = wired
    monkeypatch.setenv(ENV_MODE, "enforce")
    run(intake_hooks.observe_ai_asset(OFFICE, AI_ASSET, source_ref="recognition-1"))
    row_id = db[PENDING_COLLECTION].docs[0]["id"]
    client = _client_as(role, monkeypatch, ctx)

    queue = client.get("/api/master-data/pending")
    matches = client.get("/api/master-data/pending/%s/matches" % row_id)
    assert queue.status_code == (200 if may_read else 403)
    assert matches.status_code == (200 if may_read else 403)

    rejected = client.post("/api/master-data/pending/%s/reject" % row_id,
                           json={"reason": "not an identity"})
    if may_decide:
        assert rejected.status_code == 200 and rejected.json()["performed"] is True
        assert db[PENDING_COLLECTION].docs[0]["status"] == STATUS_REJECTED
    else:
        assert rejected.status_code == 403
        assert db[PENDING_COLLECTION].docs[0]["status"] == STATUS_PENDING
        approved = client.post("/api/master-data/pending/%s/approve" % row_id,
                               json={"confirmation": True, "create_new": True,
                                     "display_name": "Ъглошлайф"})
        assert approved.status_code == 403
        assert not (db.master(ASSET_TYPE) and db.master(ASSET_TYPE).docs)


# ===========================================================================
# 2. concurrency — one open row, whatever the interleaving
# ===========================================================================

class RacyCollection(SpyCollection):
    """MongoDB under concurrency, as far as ``create_pending`` can observe it.

    An upsert that finds no match yields to the event loop **before** it
    inserts: that is the window MongoDB leaves open when no unique index covers
    the filter, and it is where a second writer slips in. ``_id`` is unique, as
    in every MongoDB collection, so a second insert of the same ``_id`` fails
    with ``DuplicateKeyError`` — and nothing else is unique.
    """

    async def update_one(self, query, update, upsert=False):
        if not upsert or self._match(query):
            return await super().update_one(query, update, upsert=upsert)
        await asyncio.sleep(0)          # decided "no match"; the other writer runs now
        await asyncio.sleep(0)
        doc = {k: v for k, v in (query or {}).items()
               if not k.startswith("$") and not (isinstance(v, dict) and any(
                   str(op).startswith("$") for op in v))}
        doc.update(update.get("$setOnInsert", {}))
        self._check_unique_id(doc)      # the only uniqueness MongoDB gives for free
        self.docs.append(doc)
        for k, v in update.get("$set", {}).items():
            doc[k] = v
        for k, v in update.get("$addToSet", {}).items():
            items = doc.setdefault(k, [])
            if v not in items:
                items.append(v)
        for k, v in update.get("$inc", {}).items():
            doc[k] = doc.get(k, 0) + v
        return Result(0, upserted_id=doc.get("id", doc.get("_id", True)), matched=0)


class RacyDb(SpyDb):
    RACY = {PENDING_COLLECTION, PENDING_SLOT_COLLECTION}

    def __getitem__(self, name):
        if name not in self.collections:
            self.collections[name] = RacyCollection() if name in self.RACY else SpyCollection()
        return self.collections[name]


def racy_world(tenant="tenant-a", db=None):
    db = db if db is not None else RacyDb()
    ctx = Ctx(tenant, user_id="importer-1", db=db)
    return db, ctx, MasterDataRepository(tenant, db=db)


def propose(ctx, repo, raw, channel=SOURCE_EXCEL, ref=None, entity_type=ORG):
    return pending_mod.propose(ctx, entity_type=entity_type, raw_value=raw, source_channel=channel,
                               source_ref=ref, mode="enforce", repository=repo)


def concurrently(*coros):
    async def together():
        return await asyncio.gather(*coros)
    return run(together())


def pending_rows(db, tenant=None, status=STATUS_PENDING):
    coll = db.collections.get(PENDING_COLLECTION)
    return [r for r in (coll.docs if coll else [])
            if (status is None or r["status"] == status)
            and (tenant is None or r["tenant_id"] == tenant)]


def proposed_events(db, tenant=None):
    audit = db.audit()
    return [e for e in (audit.docs if audit else [])
            if e["action"] == "master_data.pending.proposed"
            and (tenant is None or e["tenant_id"] == tenant)]


def test_two_concurrent_imports_of_one_text_leave_one_row_two_sightings_one_event():
    db, ctx, repo = racy_world()

    outcomes = concurrently(propose(ctx, repo, "Баумит ЕООД", ref="import-1:row-4"),
                            propose(ctx, repo, "Баумит ЕООД", ref="import-2:row-9"))

    rows = pending_rows(db)
    assert len(rows) == 1, "two concurrent imports opened %d rows" % len(rows)
    assert rows[0]["occurrences"] == 2
    assert len(proposed_events(db)) == 1
    assert sorted(o.deduplicated for o in outcomes) == [False, True]
    assert all(o.performed for o in outcomes)
    assert {o.pending["id"] for o in outcomes} == {rows[0]["id"]}


def test_many_concurrent_sightings_are_all_counted_on_one_row():
    db, ctx, repo = racy_world()

    concurrently(*[propose(ctx, repo, "Баумит ЕООД", ref="import-%d" % i) for i in range(12)])

    rows = pending_rows(db)
    assert len(rows) == 1
    assert rows[0]["occurrences"] == 12
    assert len(proposed_events(db)) == 1


def test_spellings_that_normalize_alike_share_the_row_under_concurrency():
    db, ctx, repo = racy_world()

    concurrently(propose(ctx, repo, "Баумит ЕООД"), propose(ctx, repo, "  БАУМИТ   ЕООД "),
                 propose(ctx, repo, "баумит еоод"))

    rows = pending_rows(db)
    assert len(rows) == 1 and rows[0]["occurrences"] == 3
    assert len(proposed_events(db)) == 1


def test_tenants_and_types_never_share_a_row_even_when_they_race():
    db, ctx_a, repo_a = racy_world("tenant-a")
    _, ctx_b, repo_b = racy_world("tenant-b", db=db)

    concurrently(propose(ctx_a, repo_a, "Баумит ЕООД"), propose(ctx_b, repo_b, "Баумит ЕООД"),
                 propose(ctx_a, repo_a, "Баумит ЕООД", entity_type=ACTIVITY))

    assert len(pending_rows(db, "tenant-a")) == 2        # organization and activity
    assert len(pending_rows(db, "tenant-b")) == 1
    assert all(r["occurrences"] == 1 for r in pending_rows(db))
    assert len(proposed_events(db, "tenant-a")) == 2 and len(proposed_events(db, "tenant-b")) == 1


def test_a_text_seen_again_after_a_decision_opens_exactly_one_new_proposal():
    db, ctx, repo = racy_world()
    first = run(propose(ctx, repo, "Баумит ЕООД")).pending
    assert run(repo.reject_pending(first["id"], reason="not a supplier", actor_id="office-1",
                                   now="2026-09-21T10:00:00+00:00"))

    concurrently(propose(ctx, repo, "Баумит ЕООД", ref="later-1"),
                 propose(ctx, repo, "Баумит ЕООД", ref="later-2"))

    open_rows = pending_rows(db)
    assert len(open_rows) == 1 and open_rows[0]["id"] != first["id"]
    assert open_rows[0]["occurrences"] == 2
    assert [r["status"] for r in pending_rows(db, status=None) if r["id"] == first["id"]] == [STATUS_REJECTED]
    assert len(proposed_events(db)) == 2                  # the first proposal and the new one


def test_the_double_reproduces_the_race_a_plain_upsert_loses():
    """Control: the previous implementation — one upsert conditioned on
    (tenant, type, normalized value, status) with no unique index — opens two
    rows under this double. So the tests above passing means something."""
    db = RacyDb()

    async def plain_upsert(ref):
        doc = pending_mod.build_pending(tenant_id="tenant-a", entity_type=ORG, raw_value="Баумит ЕООД",
                                        source_channel=SOURCE_EXCEL, created_by="importer-1",
                                        source_ref=ref)
        for f in ("occurrences", "last_seen_at", "updated_at"):
            doc.pop(f)
        await db[PENDING_COLLECTION].update_one(
            {"entity_type": ORG, "normalized_value": doc["normalized_value"],
             "status": STATUS_PENDING, "tenant_id": "tenant-a"},
            {"$setOnInsert": doc, "$inc": {"occurrences": 1}, "$set": {"last_seen_at": "t"}},
            upsert=True)

    concurrently(plain_upsert("a"), plain_upsert("b"))
    assert len(pending_rows(db)) == 2


# ===========================================================================
# 3. sources — a merged repeat keeps what it knew
# ===========================================================================

def test_a_row_seen_by_ocr_then_excel_keeps_both_channels_and_both_references():
    db, ctx, repo = racy_world()
    run(propose(ctx, repo, "Баумит ЕООД", channel=SOURCE_OCR, ref="ocr-intake:inv-1"))
    run(propose(ctx, repo, "Баумит ЕООД", channel=SOURCE_EXCEL, ref="kss-import:f-1:r-3"))

    [row] = pending_rows(db)
    assert row["source_channel"] == SOURCE_OCR and row["source_ref"] == "ocr-intake:inv-1"
    assert row["source_channels"] == [SOURCE_OCR, SOURCE_EXCEL]
    assert row["last_source_channel"] == SOURCE_EXCEL
    assert row["last_source_ref"] == "kss-import:f-1:r-3"
    assert row["occurrences"] == 2
    assert len(proposed_events(db)) == 1


def test_a_repeat_from_the_same_channel_does_not_list_it_twice():
    db, ctx, repo = racy_world()
    run(propose(ctx, repo, "Баумит ЕООД", ref="import-1"))
    run(propose(ctx, repo, "Баумит ЕООД", ref="import-2"))

    [row] = pending_rows(db)
    assert row["source_channels"] == [SOURCE_EXCEL]
    assert row["source_ref"] == "import-1" and row["last_source_ref"] == "import-2"


def test_concurrent_sightings_from_different_channels_keep_every_channel():
    db, ctx, repo = racy_world()
    concurrently(propose(ctx, repo, "Баумит ЕООД", channel=SOURCE_OCR, ref="ocr-1"),
                 propose(ctx, repo, "Баумит ЕООД", channel=SOURCE_EXCEL, ref="excel-1"))

    [row] = pending_rows(db)
    assert sorted(row["source_channels"]) == [SOURCE_EXCEL, SOURCE_OCR]
    assert row["occurrences"] == 2


def test_the_source_filter_finds_a_row_under_every_channel_that_proposed_it():
    db, ctx, repo = racy_world()
    run(propose(ctx, repo, "Баумит ЕООД", channel=SOURCE_OCR, ref="ocr-intake:inv-1"))
    run(propose(ctx, repo, "Баумит ЕООД", channel=SOURCE_EXCEL, ref="kss-import:f-1:r-3"))
    run(propose(ctx, repo, "Шпакловка стени", channel=SOURCE_EXCEL, entity_type=ACTIVITY))

    def listed(channel):
        return sorted(r["raw_value"] for r in run(review.list_pending(
            ctx, source_channel=channel, mode="enforce", repository=repo)))

    assert listed(SOURCE_EXCEL) == ["Баумит ЕООД", "Шпакловка стени"]
    assert listed(SOURCE_OCR) == ["Баумит ЕООД"]
    assert listed("ai") == []


def test_the_screen_sees_every_channel_of_a_merged_row_over_http(wired, monkeypatch):
    db, ctx = wired
    monkeypatch.setenv(ENV_MODE, "enforce")
    repo = MasterDataRepository(ctx.tenant_id, db=db)
    run(propose(ctx, repo, "Баумит ЕООД", channel=SOURCE_OCR, ref="ocr-intake:inv-1"))
    run(propose(ctx, repo, "Баумит ЕООД", channel=SOURCE_EXCEL, ref="kss-import:f-1:r-3"))
    client = _client_as("office", monkeypatch, ctx)

    by_excel = client.get("/api/master-data/pending?source_channel=excel").json()
    by_ocr = client.get("/api/master-data/pending?source_channel=ocr").json()

    assert by_excel["count"] == 1 and by_ocr["count"] == 1
    item = by_excel["items"][0]
    assert item["source_channels"] == ["ocr", "excel"]
    assert item["source_ref"] == "ocr-intake:inv-1"
    assert item["last_source_ref"] == "kss-import:f-1:r-3"
    assert "_id" not in item
