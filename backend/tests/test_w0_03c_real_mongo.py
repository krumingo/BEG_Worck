"""
W0-03C against a REAL, disposable, local MongoDB.

Skipped unless ``W0_03_REAL_MONGO_URL`` names a plain local server, for example::

    W0_03_REAL_MONGO_URL=mongodb://localhost:27017 pytest tests/test_w0_03c_real_mongo.py -v --noconftest

Everything the doubles in the other W0-03C tests only model is checked here against the
server itself:

  * the open-slot mechanism of PR #19 under truly concurrent imports: one pending row,
    every sighting counted, one ``master_data.pending.proposed`` AuditEvent;
  * a text seen again after a proposal was rejected or resolved opens exactly one new
    proposal, and the audit chain of the tenant stays valid;
  * the duplicate report agrees with the server: for every tricky fixture the report
    says "blocked" exactly when the server refuses to build the unique index;
  * the bootstrap: apply, re-run (the definitions the server hands back must compare
    equal), enforcement of each key, conflict, and a rollback driven by the run ledger
    (an edited plan is refused; an index rebuilt by a later run survives the earlier undo).

Safety: the URL must pass the same local-only guard as the bootstrap (no Atlas, no NAS,
no ``mongodb+srv``). Each test works in its own database ``w003c_realmongo_<random>``
and drops exactly that database afterwards — never anything else. Nothing here reads
``.env`` or ``MONGO_URL``.
"""
import asyncio
import os
import uuid

import pytest

from app.master_data import index_bootstrap as ib
from app.master_data import models, pending as pending_mod, uniqueness as uq
from app.master_data.models import build_entity, new_alias, new_identifier
from app.master_data.pending import PENDING_COLLECTION, SOURCE_EXCEL, STATUS_PENDING, STATUS_REJECTED
from app.master_data.repository import MasterDataRepository
from app.master_data.review import approve, reject

REAL_URL = os.environ.get("W0_03_REAL_MONGO_URL", "")
DB_PREFIX = "w003c_realmongo_"
NOW = "2026-09-21T10:00:00+00:00"
ORG = models.ENTITY_ORGANIZATION


def _refusal():
    if not REAL_URL:
        return "W0_03_REAL_MONGO_URL is not set — no disposable local MongoDB given"
    try:
        from scripts.w0_03c_master_data_uniqueness import parse_mongo_url
        scheme, hosts = parse_mongo_url(REAL_URL)
        ib.check_local(hosts=hosts, scheme=scheme)
    except Exception as exc:                                  # noqa: BLE001
        return "W0_03_REAL_MONGO_URL refused: %s" % exc
    try:
        import motor.motor_asyncio  # noqa: F401
    except ImportError:
        return "motor is not installed"
    return ""


pytestmark = pytest.mark.skipif(bool(_refusal()), reason=_refusal() or "ok")


class Ctx:
    """The resolver-backed context the service layer expects (see test_w0_03b3)."""
    enforced = True

    def __init__(self, tenant_id, db, user_id="office-1"):
        self.tenant_id, self.user_id, self._db = tenant_id, user_id, db

    async def db(self, require_operational: bool = False):
        return self._db


def scratch(test):
    """Run ``test(db, name)`` in a fresh database on the real server; drop it afterwards."""
    async def body():
        from motor.motor_asyncio import AsyncIOMotorClient
        name = DB_PREFIX + uuid.uuid4().hex[:12]
        assert name.startswith(DB_PREFIX)
        client = AsyncIOMotorClient(REAL_URL, serverSelectionTimeoutMS=5000)
        try:
            return await test(client[name], name)
        finally:
            await client.drop_database(name)
            client.close()
    return asyncio.run(body())


def target(name):
    from scripts.w0_03c_master_data_uniqueness import parse_mongo_url
    scheme, hosts = parse_mongo_url(REAL_URL)
    return {"scheme": scheme, "hosts": hosts, "confirm_database": name}


def propose(ctx, repo, raw, ref=None, entity_type=ORG):
    return pending_mod.propose(ctx, entity_type=entity_type, raw_value=raw, source_channel=SOURCE_EXCEL,
                               source_ref=ref, mode="enforce", repository=repo)


async def open_rows(db, tenant):
    return await db[PENDING_COLLECTION].find({"tenant_id": tenant, "status": STATUS_PENDING},
                                             {"_id": 0}).to_list(None)


async def proposed_events(db, tenant):
    return await db["audit_events"].find({"tenant_id": tenant, "action": "master_data.pending.proposed"},
                                         {"_id": 0}).to_list(None)


# ================================================================ PR #19: the open slot on a real server

@pytest.mark.parametrize("writers", [2, 12])
def test_concurrent_imports_open_one_row_count_every_sighting_and_audit_once(writers):
    async def t(db, name):
        ctx, repo = Ctx("tenant-a", db), MasterDataRepository("tenant-a", db=db)
        outcomes = await asyncio.gather(*[propose(ctx, repo, "Баумит ЕООД", ref="import-%d" % i)
                                          for i in range(writers)])
        rows = await open_rows(db, "tenant-a")
        assert len(rows) == 1, "%d concurrent imports opened %d rows" % (writers, len(rows))
        assert rows[0]["occurrences"] == writers
        assert len(await proposed_events(db, "tenant-a")) == 1
        assert sum(1 for o in outcomes if not o.deduplicated) == 1
        assert all(o.performed for o in outcomes)
    scratch(t)


def test_a_text_seen_again_after_reject_or_resolve_opens_exactly_one_new_proposal():
    async def t(db, name):
        from app.audit.store import verify_tenant_chain
        ctx, repo = Ctx("tenant-a", db), MasterDataRepository("tenant-a", db=db)

        first = (await propose(ctx, repo, "Баумит ЕООД")).pending
        assert (await reject(ctx, pending_id=first["id"], reason="не е доставчик",
                             mode="enforce", repository=repo)).performed
        await asyncio.gather(*[propose(ctx, repo, "Баумит ЕООД", ref="later-%d" % i) for i in range(5)])
        [second] = await open_rows(db, "tenant-a")
        assert second["id"] != first["id"] and second["occurrences"] == 5

        assert (await approve(ctx, pending_id=second["id"], confirmation=True, create_new=True,
                              display_name="Баумит ЕООД", mode="enforce", repository=repo)).performed
        await asyncio.gather(*[propose(ctx, repo, "Баумит ЕООД", ref="again-%d" % i) for i in range(5)])
        [third] = await open_rows(db, "tenant-a")
        assert third["id"] not in (first["id"], second["id"]) and third["occurrences"] == 5

        statuses = {r["id"]: r["status"] for r in await db[PENDING_COLLECTION].find({}, {"_id": 0}).to_list(None)}
        assert statuses[first["id"]] == STATUS_REJECTED
        assert statuses[second["id"]] == "resolved"
        assert len(await proposed_events(db, "tenant-a")) == 3
        ok, why = await verify_tenant_chain(db, "tenant-a")
        assert ok, why
    scratch(t)


def test_two_tenants_racing_on_one_text_never_share_a_row():
    async def t(db, name):
        a = (Ctx("tenant-a", db), MasterDataRepository("tenant-a", db=db))
        b = (Ctx("tenant-b", db), MasterDataRepository("tenant-b", db=db))
        await asyncio.gather(*[propose(*(a if i % 2 else b), "Баумит ЕООД") for i in range(10)])
        assert [r["occurrences"] for r in await open_rows(db, "tenant-a")] == [5]
        assert [r["occurrences"] for r in await open_rows(db, "tenant-b")] == [5]
    scratch(t)


def test_the_slot_and_the_open_pending_index_work_together():
    async def t(db, name):
        applied = await ib.bootstrap(db, database=name, apply=True, target=target(name), env={})
        assert applied["status"] == ib.STATUS_APPLIED, applied.get("reason")
        ctx, repo = Ctx("tenant-a", db), MasterDataRepository("tenant-a", db=db)
        await asyncio.gather(*[propose(ctx, repo, "Кнауф АД", ref="r-%d" % i) for i in range(8)])
        [row] = await open_rows(db, "tenant-a")
        assert row["occurrences"] == 8
        assert len(await proposed_events(db, "tenant-a")) == 1
    scratch(t)


# ================================================================ the report agrees with the server

def _org(tenant, name, *, eik=None, aliases=(), status="active", entity_id=None):
    doc = build_entity(tenant_id=tenant, entity_type=ORG, display_name=name, entity_id=entity_id, now=NOW)
    doc["aliases"] = [new_alias(a, "office-1", now=NOW) for a in aliases]
    if eik:
        doc["identifiers"] = [new_identifier(ORG, "eik", eik)]
    doc["status"] = status
    if status == "merged":
        doc["merged_into"] = "x"
    return doc


def _alias_without_normalized(doc):
    doc["aliases"].append({"value": "стар запис", "added_by": "legacy"})
    return doc


FIXTURES = {
    "same eik, one tenant": [_org("t", "А", eik="123"), _org("t", "Б", eik="1-2-3")],
    "same eik, two tenants": [_org("t1", "А", eik="123"), _org("t2", "А", eik="123")],
    "same eik, one merged": [_org("t", "А", eik="123"), _org("t", "Б", eik="123", status="merged")],
    "empty alias lists": [_org("t", "А"), _org("t", "Б"), _org("t", "В")],
    "alias repeated in one record": [_org("t", "А", aliases=["Строй", "строй"])],
    "alias on two active records": [_org("t", "А", aliases=["Строй"]), _org("t", "Б", aliases=["СТРОЙ"])],
    "alias elements without normalized": [_alias_without_normalized(_org("t", "А", aliases=["x"])),
                                          _alias_without_normalized(_org("t", "Б", aliases=["y"]))],
    "reused id across statuses": [_org("t", "А", entity_id="same"),
                                  _org("t", "Б", entity_id="same", status="archived")],
}


@pytest.mark.parametrize("fixture", sorted(FIXTURES))
def test_the_report_predicts_exactly_what_the_server_refuses_to_build(fixture):
    async def t(db, name):
        await db["md_organization"].insert_many([dict(d) for d in FIXTURES[fixture]])
        report = await uq.duplicate_report(db, database=name)
        predicted = {i["name"] for i in report["canonical"]["indexes"]
                     if i["collection"] == "md_organization" and not i["clean"]}
        refused = set()
        for key in (k for k in uq.CANONICAL_KEYS if k.collection == "md_organization"):
            spec = key.index_spec()
            opts = {"name": key.name, "unique": True}
            if "partialFilterExpression" in spec:
                opts["partialFilterExpression"] = spec["partialFilterExpression"]
            try:
                await db["md_organization"].create_index(spec["keys"], **opts)
                await db["md_organization"].drop_index(key.name)
            except Exception:                              # noqa: BLE001 — the server said no
                refused.add(key.name)
        assert predicted == refused, "report %s vs server %s" % (sorted(predicted), sorted(refused))
    scratch(t)


# ================================================================ the bootstrap on a real server

def test_apply_rerun_enforce_and_roll_back_on_a_real_server():
    async def t(db, name):
        from pymongo.errors import DuplicateKeyError
        await db["md_organization"].insert_one(_org("t", "Строй ЕООД", eik="123456789", aliases=["Строй"]))

        planned = await ib.bootstrap(db, database=name, env={})
        assert planned["status"] == ib.STATUS_PLANNED and len(planned["to_create"]) == 25

        applied = await ib.bootstrap(db, database=name, apply=True, target=target(name), env={})
        assert applied["status"] == ib.STATUS_APPLIED, applied.get("reason")
        assert len(applied["created"]) == 25

        again = await ib.bootstrap(db, database=name, apply=True, target=target(name), env={})
        assert again["status"] == ib.STATUS_ALREADY_APPLIED, again.get("reason")

        for dup in (_org("t", "Друга", eik="123-456-789"), _org("t", "Трета", aliases=["строй"])):
            with pytest.raises(DuplicateKeyError):
                await db["md_organization"].insert_one(dup)
        await db["md_organization"].insert_one(_org("t2", "Строй ЕООД", eik="123456789", aliases=["Строй"]))
        await db["md_organization"].insert_one(_org("t", "Стара", eik="123456789", status="archived"))

        entry = await db[ib.LEDGER_COLLECTION].find_one({"_id": applied["run_id"]})
        assert entry["status"] == ib.RUN_APPLIED and len(entry["created"]) == 25

        forged = applied["rollback_plan"] + [{"collection": "md_tag", "index": "md_uq_x"}]
        refused = await ib.rollback(db, applied["run_id"], database=name, plan=forged,
                                    target=target(name), env={})
        assert refused["status"] == ib.STATUS_REFUSED_TARGET
        assert "md_uq_id" in await db["md_organization"].index_information()

        rb = await ib.rollback(db, applied["run_id"], database=name, plan=applied["rollback_plan"],
                               target=target(name), env={})
        assert rb["status"] == ib.STATUS_ROLLED_BACK, rb
        left = set(await db["md_organization"].index_information())
        assert left == {"_id_"}
        rb2 = await ib.rollback(db, applied["run_id"], database=name, plan=applied["rollback_plan"],
                                target=target(name), env={})
        assert rb2["status"] == ib.STATUS_ROLLED_BACK and rb2["results"] == []
    scratch(t)


def test_an_index_rebuilt_by_a_later_run_survives_the_earlier_rollback_on_a_real_server():
    async def t(db, name):
        a = await ib.bootstrap(db, database=name, apply=True, target=target(name), env={})
        await db["md_tag"].drop_index("md_uq_name")
        b = await ib.bootstrap(db, database=name, apply=True, target=target(name), env={})
        assert b["created"] == ["md_tag.md_uq_name"]
        await ib.rollback(db, a["run_id"], database=name, target=target(name), env={})
        assert "md_uq_name" in await db["md_tag"].index_information()
        await ib.rollback(db, b["run_id"], database=name, target=target(name), env={})
        assert "md_uq_name" not in await db["md_tag"].index_information()
    scratch(t)


def test_duplicates_refuse_the_whole_run_on_a_real_server():
    async def t(db, name):
        await db["md_tag"].insert_many([
            build_entity(tenant_id="t", entity_type="tag", display_name="спешно", now=NOW),
            build_entity(tenant_id="t", entity_type="tag", display_name="СПЕШНО", now=NOW)])
        r = await ib.bootstrap(db, database=name, apply=True, target=target(name), env={})
        assert r["status"] == ib.STATUS_REFUSED_DUPLICATES
        for coll in await db.list_collection_names():
            assert set(await db[coll].index_information()) == {"_id_"}
    scratch(t)


def test_a_conflicting_definition_is_refused_on_a_real_server():
    async def t(db, name):
        await db["md_unit"].create_index([("tenant_id", 1), ("normalized_name", 1)], name="md_uq_name",
                                         unique=True)
        r = await ib.bootstrap(db, database=name, apply=True, target=target(name), env={})
        assert r["status"] == ib.STATUS_REFUSED_CONFLICT
    scratch(t)


# ================================================================ a failed build, reconciled against
# the real server (W0-03C review C02 of PR #20)
#
# ``create_index`` can raise AFTER the server has built the index — a reset reply, a
# timeout. The doubles model that; here the index really is on a real server, and the
# read-back really goes through ``listIndexes`` and pymongo's own ``index_information()``.

class _RaiseAfterBuild:
    """A real database handle whose ``create_index`` for ONE index builds on the server
    and only then raises, the way a lost reply looks to the caller."""

    def __init__(self, db, collection, index):
        self._db, self._collection, self._index = db, collection, index

    def __getattr__(self, item):
        return getattr(self._db, item)

    def __getitem__(self, item):
        coll = self._db[item]
        return _RaiseAfterBuildCollection(coll, self._index) if item == self._collection else coll


class _RaiseAfterBuildCollection:
    def __init__(self, coll, index):
        self._coll, self._index = coll, index

    def __getattr__(self, item):
        return getattr(self._coll, item)

    async def create_index(self, keys, **kw):
        out = await self._coll.create_index(keys, **kw)
        if kw.get("name") == self._index:
            from pymongo.errors import OperationFailure
            raise OperationFailure("connection reset while reading the reply for %s" % self._index)
        return out


def test_a_build_that_raises_after_a_real_server_built_it_is_not_rolled_back():
    """The C02 finding on a real server: the index is genuinely there afterwards, so
    ``FAILED_ROLLED_BACK`` would be a lie and nothing may be dropped."""
    async def t(db, name):
        handle = _RaiseAfterBuild(db, PENDING_COLLECTION, "md_uq_open_pending")
        r = await ib.bootstrap(handle, database=name, apply=True, target=target(name), env={})

        assert r["status"] == ib.STATUS_FAILED_INDEX_PRESENT, r.get("reason")
        assert r["reconciliation"]["state"] == "present"
        assert r["undone"] == []
        assert "md_uq_open_pending" in await db[PENDING_COLLECTION].index_information()
        assert "md_uq_id" in await db["md_organization"].index_information()

        entry = await db[ib.LEDGER_COLLECTION].find_one({"_id": r["run_id"]})
        assert entry["status"] == ib.RUN_INDEX_PRESENT_UNCONFIRMED and len(entry["created"]) == 25

        rb = await ib.rollback(db, r["run_id"], database=name, plan=r["rollback_plan"],
                               target=target(name), env={})
        assert rb["status"] == ib.STATUS_ROLLED_BACK, rb
        for coll in await db.list_collection_names():
            if coll != ib.LEDGER_COLLECTION:
                assert set(await db[coll].index_information()) == {"_id_"}
    scratch(t)


def test_reconciliation_reads_every_planned_index_back_from_a_real_server():
    """What only a real server can show: its own ``index_information()`` output compares
    equal to the planned definition, field by field, for all 25 keys."""
    async def t(db, name):
        applied = await ib.bootstrap(db, database=name, apply=True, target=target(name), env={})
        assert applied["status"] == ib.STATUS_APPLIED, applied.get("reason")
        for key in uq.CANONICAL_KEYS:
            assert await ib._reconcile(db, key) == ("present", ib._wanted_spec(key)), key.name
        await db["md_tag"].drop_index("md_uq_name")
        assert await ib._reconcile(db, [k for k in uq.CANONICAL_KEYS
                                        if k.collection == "md_tag"
                                        and k.name == "md_uq_name"][0]) == ("absent", None)
    scratch(t)


def test_a_real_index_of_another_definition_is_a_conflict_and_is_never_dropped():
    """The claimed name is taken by something else on the server: reconciliation says
    conflict, and the rollback refuses to delete it."""
    async def t(db, name):
        applied = await ib.bootstrap(db, database=name, apply=True, target=target(name), env={})
        key = [k for k in uq.CANONICAL_KEYS if k.collection == "md_unit" and k.name == "md_uq_name"][0]
        await db["md_unit"].drop_index("md_uq_name")
        await db["md_unit"].create_index([("tenant_id", 1), ("normalized_name", 1)],
                                         name="md_uq_name", unique=True,
                                         collation={"locale": "bg"})          # foreign definition
        state, found = await ib._reconcile(db, key)
        assert state == "conflict" and found != ib._wanted_spec(key)

        rb = await ib.rollback(db, applied["run_id"], database=name, plan=applied["rollback_plan"],
                               target=target(name), env={})
        assert rb["status"] == ib.STATUS_ROLLBACK_FAILED
        refused = [x for x in rb["results"] if x["index"] == "md_unit.md_uq_name"][0]
        assert refused["result"].startswith("refused")
        assert "md_uq_name" in await db["md_unit"].index_information()        # still there
    scratch(t)
