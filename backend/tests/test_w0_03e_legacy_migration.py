"""
W0-03E — legacy migration foundation: inventory, deterministic plan, dry run,
execute/resume/verify, reconciliation, rollback, human mapping, old-id
resolution, tenant isolation.

The promises under test (contract §6 W0-03E, FLOW-032, §4.5, CLAUDE.md §8):

  * the dry run writes NOTHING and is deterministic (same data, any storage
    order -> same plan and token);
  * every inventoried source collection has a decision per legacy document;
    an equal name without an authoritative identifier is a candidate, never a
    link — not even an exact one; conflicting or duplicate identifiers, a
    person-shaped client, a project-scoped СМР group stay pending;
  * one canonical organization across client/supplier/subcontractor roles;
  * execute fails closed without trusted Approval (W0-07 absent) and audits
    the refusal; with the test-only verifier it writes, verifies, reconciles
    with zero lost references, and never touches a legacy collection;
  * an interrupted run is resumed by the SAME request after its checkpoint,
    with one AuditEvent per batch and one completion event; no silent
    partial success;
  * every old id resolves through its tenant-bound reverse reference and any
    merge redirect; a foreign org_id, an injected legacy_ref, another tenant's
    identical legacy id are refused or isolated — never guessed;
  * rollback archives and detaches, never deletes; refused when something was
    built on the run;
  * off is inert, shadow reads and writes nothing.

In-process MongoDB double: mongomock-motor. The same flows against a real
disposable server are in test_w0_03e_real_mongo.py. Approval for the happy
paths comes from the test-only verifier of the W0-03D tests; no production code
path can supply one.

Run:  pytest tests/test_w0_03e_legacy_migration.py -v --noconftest
"""
import asyncio
import copy
import uuid

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.audit.store import AUDIT_COLLECTION, verify_chain
from app.master_data import legacy_adapter as la
from app.master_data import legacy_migration as lm
from app.master_data import legacy_plan as lp
from app.master_data import legacy_sources as ls
from app.master_data import merge as mm
from app.master_data import models
from app.master_data.deps import MODE_ENFORCE, MODE_OFF, MODE_SHADOW, MasterDataTenantContextMissing
from app.master_data.merge import MasterDataApprovalRequired
from app.master_data.models import MasterDataInvalid, build_entity, new_identifier
from app.master_data.repository import MasterDataRepository
from app.master_data.service import MasterDataAuditFailed, MasterDataRefused

from tests.test_w0_03d_merge_redirect import TrustedTestVerifier

T_A, ORG_A = "tenant-a", "org-a"
T_B, ORG_B = "tenant-b", "org-b"
NOW = "2026-09-28T09:00:00+00:00"
LEGACY = [s.collection for s in ls.SOURCES]


def run(coro):
    return asyncio.run(coro)


# ================================================================ doubles
WRITE_METHODS = ("insert_one", "insert_many", "update_one", "update_many", "replace_one",
                 "delete_one", "delete_many", "find_one_and_update", "find_one_and_delete",
                 "find_one_and_replace", "bulk_write", "create_index", "drop")


class Spy:
    """A database proxy that records every write and can refuse or fail them."""

    def __init__(self, db, refuse_writes=False, refuse_reads=False):
        self._db, self.writes, self.reads = db, [], []
        self.refuse_writes, self.refuse_reads = refuse_writes, refuse_reads
        self.fail_on = {}          # (collection, method) -> remaining failures

    def __getitem__(self, name):
        return _SpyColl(self, self._db[name], name)

    @property
    def name(self):
        return self._db.name


class _SpyColl:
    def __init__(self, spy, coll, name):
        self._spy, self._coll, self._name = spy, coll, name

    def __getattr__(self, attr):
        target = getattr(self._coll, attr)
        if attr in WRITE_METHODS:
            def write(*a, **kw):
                self._spy.writes.append((self._name, attr))
                if self._spy.refuse_writes:
                    raise AssertionError("write attempted: %s.%s" % (self._name, attr))
                left = self._spy.fail_on.get((self._name, attr))
                if left:
                    self._spy.fail_on[(self._name, attr)] = left - 1
                    raise RuntimeError("simulated storage failure on %s.%s" % (self._name, attr))
                return target(*a, **kw)
            return write
        if attr in ("find", "find_one", "count_documents", "aggregate"):
            def read(*a, **kw):
                self._spy.reads.append(self._name)
                if self._spy.refuse_reads:
                    raise AssertionError("read attempted: %s" % self._name)
                return target(*a, **kw)
            return read
        return target


class Ctx:
    enforced = True

    def __init__(self, db, tenant_id=T_A, org_id=ORG_A, user_id="owner-1"):
        self.tenant_id, self.org_id, self.user_id, self._db = tenant_id, org_id, user_id, db

    async def db(self, require_operational=False):
        return self._db


def new_db():
    return AsyncMongoMockClient()["w003e_" + uuid.uuid4().hex[:8]]


def repo(db, tenant=T_A):
    return MasterDataRepository(tenant, db=db)


# ================================================================ fixture data
def legacy_docs(org, suffix=""):
    """Every inventoried source, with the cases the plan must tell apart."""
    s = suffix

    def d(i, **kw):
        return dict(id=i + s, org_id=org, created_at=NOW, **kw)
    return {
        "users": [d("u1", first_name="Иван", last_name="Петров", email="ivan@x"),
                  d("u2", first_name="Мария", last_name="Георгиева"),
                  d("u3", first_name="Георги", last_name="Иванов"),
                  {"org_id": org, "first_name": "Без", "last_name": "Идентификатор"}],
        "persons": [d("p1", first_name="Мария", last_name="Георгиева"),
                    d("p2", first_name="Стоян", last_name="Колев", egn="8001011234"),
                    d("p3", first_name="С.", last_name="Колев", egn="8001011234"),
                    d("p4", first_name="Нина", last_name="Попова", egn="9002021234")],
        "employee_profiles": [d("ep1", user_id="u1" + s), d("ep2", user_id="u-missing"),
                              d("ep3", user_id="u2" + s)],
        "companies": [d("c1", name="Баумит ЕООД", eik="123456789")],
        "clients": [d("cl1", companyName="Баумит", eik="123 456 789"),
                    d("cl2", first_name="Петър", last_name="Петров", phone="0888")],
        "counterparties": [d("cp1", name="Baumit Bulgaria", eik="123456789", vat_number="BG123456789",
                             type="supplier"),
                           d("cp2", name="Петров", type="person"),
                           d("cp3", name="Техно ЕООД", type="both"),
                           d("cp4", name="Конфликт ООД", eik="111111111", vat_number="BG222222222",
                             type="supplier")],
        "subcontractors": [d("s1", name="Техно ЕООД"), d("s2", name="Монтаж АД", eik="987654321"),
                           d("s3", name="Конфликт", eik="111111111", vat_number="BG333333333")],
        "work_types": [d("w1", name="Боядисване"), d("w2", name="Шпакловка")],
        "smr_groups": [d("g1", name="Боядисване", project_id="pr1", location_id="ln2" + s)],
        "items": [d("i1", name="Цимент", sku="ABC-1", unit="торба"),
                  d("i2", name="Цимент", sku="XYZ-9", unit="торба")],
        "asset_item_types": [d("at1", key="drill", label_bg="Бормашини")],
        "asset_items": [d("ai1", name="Bosch GBH", type="drill", brand="Bosch", model="GBH")],
        "asset_units": [d("au1", item_id="ai1" + s, serial_no="SN-1", qr_id="Q1"),
                        d("au2", item_id="ai-missing", serial_no="SN-2")],
        "warehouses": [d("wh1", name="Централен склад", code="C1")],
        "location_nodes": [d("ln2", project_id="pr1", parent_id="ln1" + s, name="Етаж 1"),
                           d("ln1", project_id="pr1", parent_id=None, name="Сграда А"),
                           d("ln3", project_id="pr1", parent_id="ln-gone", name="Сграда Б"),
                           d("ln4", project_id="pr1", parent_id="ln3" + s, name="Етаж 1")],
    }


def reference_docs(org, suffix=""):
    s = suffix

    def d(i, **kw):
        return dict(id=i + s, org_id=org, **kw)
    return {
        "advances": [d("adv1", user_id="u1" + s, amount=100),
                     d("adv2", user_id=None, guest_name="Мария Георгиева", type="Loan", amount=50)],
        "project_team": [d("pt1", user_id="u1" + s, project_id="pr1")],
        "invoices": [d("inv1", supplier_counterparty_id="cp1" + s),
                     d("inv2", supplier_counterparty_id="cp-gone")],
        "projects": [d("pr1", owner_type="company", owner_id="c1" + s),
                     d("pr2", owner_type="person", owner_id="p2" + s)],
        "missing_smr": [d("ms1", group_id="g1" + s, location_id="ln2" + s)],
        "asset_custody": [d("cu1", unit_id="au1" + s, custodian_user_id="u3" + s)],
        "warehouse_transactions": [d("wt1", warehouse_id="wh1" + s)],
        "daily_work_logs": [d("dl1", work_type_id="w1" + s)],
        "sales": [d("sa1", item_id="i1" + s, warehouse_id="wh1" + s)],
    }


async def seed(db, org=ORG_A, suffix="", reverse=False):
    for bundle in (legacy_docs(org, suffix), reference_docs(org, suffix)):
        for name, docs in bundle.items():
            for doc in (reversed(docs) if reverse else docs):
                await db[name].insert_one(copy.deepcopy(doc))


async def seeded(org=ORG_A, suffix="", reverse=False, existing_master=True):
    db = new_db()
    await seed(db, org, suffix, reverse)
    if existing_master:
        # a Master organization that already exists in tenant A (e.g. from B3 review)
        m = build_entity(tenant_id=T_A, entity_type=models.ENTITY_ORGANIZATION,
                         display_name="Монтаж АД", entity_id="org-existing", now=NOW)
        m["identifiers"] = [new_identifier(models.ENTITY_ORGANIZATION, "eik", "987 654 321")]
        await db["md_organization"].insert_one(m)
    return db


async def snapshot(db, names):
    out = {}
    for name in names:
        docs = await db[name].find({}, {"_id": 0}).to_list(None)
        out[name] = sorted(docs, key=lambda x: lp.digest(x))
    return out


async def dry(db, ctx=None, **kw):
    ctx = ctx or Ctx(db)
    return await lp.plan(ctx, mode=MODE_ENFORCE, repository=repo(db, ctx.tenant_id), **kw)


async def go(db, token, key="run-1", verifier="trusted", ctx=None, **kw):
    ctx = ctx or Ctx(db)
    return await lm.execute(ctx, plan_token=token, idempotency_key=key, confirmation=True,
                            approval_id="APR-" + key, mode=MODE_ENFORCE,
                            repository=repo(db, ctx.tenant_id),
                            approval_verifier=TrustedTestVerifier() if verifier == "trusted"
                            else verifier, **kw)


def by_id(plan):
    return {(i["collection"], i["legacy_id"]): i for i in plan["items"]}


async def audit(db, tenant=T_A):
    return await db[AUDIT_COLLECTION].find({"tenant_id": tenant}, {"_id": 0}).sort(
        "sequence", 1).to_list(None)


async def migrated(db, **kw):
    p = await dry(db)
    out = await go(db, p["plan_token"], **kw)
    return p, out


# ================================================================ inventory & plan
def test_every_inventoried_source_is_registered_with_its_canonical_type():
    expected = {"users": "person", "persons": "person", "employee_profiles": "person",
                "companies": "organization", "clients": "organization",
                "counterparties": "organization", "subcontractors": "organization",
                "work_types": "activity", "smr_groups": "activity", "items": "item",
                "asset_item_types": "asset_type", "asset_items": "asset_type",
                "asset_units": "physical_asset", "warehouses": "location",
                "location_nodes": "location"}
    assert {s.collection: s.entity_type for s in ls.SOURCES} == expected
    # every identity that other collections point at has its references counted
    # (nothing stores an employee_profiles id; the profile points at its user)
    assert {r.target for r in ls.REFERENCES} == set(expected) - {"employee_profiles"}


def test_the_dry_run_writes_nothing_and_is_deterministic_across_storage_order():
    async def body():
        db = await seeded()
        spy = Spy(db, refuse_writes=True)
        before = await snapshot(db, LEGACY + ["md_organization", lp.REFS_COLLECTION])
        first = await dry(spy)
        second = await dry(spy)
        assert spy.writes == []
        assert first == second
        assert await snapshot(db, LEGACY + ["md_organization", lp.REFS_COLLECTION]) == before
        other = await seeded(reverse=True)
        assert (await dry(other))["plan_token"] == first["plan_token"]
        return first
    plan = run(body())
    assert plan["auto_merges"] == 0
    assert plan["inventory"]["users"]["unaddressable"] == 1


def test_the_plan_decides_every_legacy_document_and_never_links_by_name():
    plan = run(dry_seeded())
    items = by_id(plan)
    want = {
        ("users", "u1"): ("create", None), ("users", "u3"): ("create", None),
        ("users", "u2"): ("pending", ls.PENDING_NAME_MATCH),
        ("persons", "p1"): ("pending", ls.PENDING_NAME_MATCH),
        ("persons", "p2"): ("pending", ls.PENDING_DUPLICATE_IN_SOURCE),
        ("persons", "p3"): ("pending", ls.PENDING_DUPLICATE_IN_SOURCE),
        ("persons", "p4"): ("create", None),
        ("employee_profiles", "ep1"): ("attach", None),
        ("employee_profiles", "ep2"): ("blocked", ls.BLOCKED_ORPHAN),
        ("employee_profiles", "ep3"): ("pending", ls.PENDING_PARENT),
        ("companies", "c1"): ("create", None),
        ("clients", "cl1"): ("attach", None),
        ("clients", "cl2"): ("pending", ls.PENDING_ENTITY_TYPE),
        ("counterparties", "cp1"): ("attach", None),
        ("counterparties", "cp2"): ("pending", ls.PENDING_ENTITY_TYPE),
        ("counterparties", "cp3"): ("pending", ls.PENDING_NAME_MATCH),
        ("subcontractors", "s1"): ("pending", ls.PENDING_NAME_MATCH),
        ("counterparties", "cp4"): ("pending", ls.PENDING_IDENTIFIER_CONFLICT),
        ("subcontractors", "s3"): ("pending", ls.PENDING_IDENTIFIER_CONFLICT),
        ("subcontractors", "s2"): ("attach", None),
        ("work_types", "w1"): ("create", None), ("work_types", "w2"): ("create", None),
        ("smr_groups", "g1"): ("pending", ls.PENDING_PROJECT_SCOPED),
        ("items", "i1"): ("create", None), ("items", "i2"): ("create", None),
        ("asset_item_types", "at1"): ("create", None),
        ("asset_items", "ai1"): ("create", None),
        ("asset_units", "au1"): ("create", None), ("asset_units", "au2"): ("create", None),
        ("warehouses", "wh1"): ("create", None),
        ("location_nodes", "ln1"): ("create", None), ("location_nodes", "ln2"): ("create", None),
        ("location_nodes", "ln3"): ("blocked", ls.BLOCKED_ORPHAN),
        ("location_nodes", "ln4"): ("pending", ls.PENDING_PARENT),
    }
    assert {k: (v["decision"], v["reason_code"]) for k, v in items.items()} == want
    # one organization across roles: company anchors, client and supplier attach to it
    assert items[("clients", "cl1")]["target"] == {"anchor": ["companies", "c1"]}
    assert items[("counterparties", "cp1")]["target"] == {"anchor": ["companies", "c1"]}
    assert items[("subcontractors", "s2")]["target"] == {"entity_id": "org-existing"}
    assert items[("employee_profiles", "ep1")]["target"] == {"anchor": ["users", "u1"]}
    # an exact name is only a candidate
    assert {"legacy": ["persons", "p1"]} in items[("users", "u2")]["candidates"]
    assert {"legacy": ["work_types", "w1"]} in items[("smr_groups", "g1")]["candidates"]
    # hierarchy and asset type links
    assert items[("location_nodes", "ln2")]["relations"] == {
        "parent_id": {"anchor": ["location_nodes", "ln1"]}}
    assert items[("asset_units", "au1")]["relations"] == {
        "asset_type_id": {"anchor": ["asset_items", "ai1"]}}
    assert items[("asset_units", "au2")]["attributes"]["asset_type_unresolved"] == [
        "asset_items", "ai-missing"]
    # personal identifiers are masked in what a person sees
    assert all("8001011234" not in str(i["identifiers"]) for i in plan["items"])


async def dry_seeded():
    return await dry(await seeded())


def test_other_orgs_and_ownerless_rows_are_counted_and_never_planned():
    async def body():
        db = await seeded()
        await seed(db, ORG_B, suffix="")          # same legacy ids, another org, same database
        await db["users"].insert_one({"id": "u-noorg", "first_name": "X"})
        return await dry(db)
    plan = run(body())
    assert "other_org" not in plan["inventory"]["users"]           # C03: no count of B's data
    assert plan["inventory"]["users"]["no_org_id"] == 1
    assert all(i["legacy_id"] != "u-noorg" for i in plan["items"])
    assert len([i for i in plan["items"] if i["collection"] == "users"]) == 3


def test_modes_off_and_shadow_read_and_write_nothing():
    class Exploding(Ctx):
        async def db(self, require_operational=False):
            raise AssertionError("tenant database touched")

    async def body():
        db = await seeded()
        spy = Spy(db, refuse_writes=True, refuse_reads=True)
        ctx = Exploding(spy)
        for mode in (MODE_OFF, MODE_SHADOW):
            assert await lp.plan(ctx, mode=mode, repository=repo(spy)) is None
            assert await lm.reconcile(ctx, mode=mode, repository=repo(spy)) is None
            out = await lm.execute(ctx, plan_token="t", idempotency_key="k", confirmation=True,
                                   mode=mode, repository=repo(spy))
            assert not out.performed and out.mode == mode
            assert await la.resolve_legacy(ctx, collection="users", legacy_id="u1", mode=mode) is None
        shadow_bad = await lm.execute(ctx, plan_token="t", idempotency_key="k", mode=MODE_SHADOW,
                                      payload={"tenant_id": "x"}, repository=repo(spy))
        assert shadow_bad.would_perform is False
        return spy
    spy = run(body())
    assert spy.writes == [] and spy.reads == []


def test_the_tenant_is_never_taken_from_the_caller():
    class Legacy(Ctx):
        enforced = False

    async def body():
        db = await seeded()
        with pytest.raises(MasterDataRefused):
            await lm.execute(Ctx(db), plan_token="t", idempotency_key="k", confirmation=True,
                             payload={"org_id": ORG_B}, mode=MODE_ENFORCE, repository=repo(db))
        with pytest.raises(MasterDataTenantContextMissing):
            await dry(db, ctx=Legacy(db))
        with pytest.raises(MasterDataTenantContextMissing):
            await dry(db, ctx=Ctx(db, org_id=None))
        with pytest.raises(la.LegacyOrgMismatch):
            await la.resolve_legacy(Ctx(db), collection="users", legacy_id="u1", org_id=ORG_B,
                                    mode=MODE_ENFORCE, repository=repo(db))
        with pytest.raises(MasterDataInvalid):
            await dry(db, sources=["payments"])
    run(body())


# ================================================================ execute
def test_execute_fails_closed_without_a_trusted_approval_and_audits_the_refusal():
    async def body():
        db = await seeded()
        p = await dry(db)
        before = await snapshot(db, LEGACY + ["md_organization", "md_person", lp.REFS_COLLECTION,
                                              lm.RUNS_COLLECTION])
        for verifier in (None, "forged"):
            with pytest.raises(MasterDataApprovalRequired):
                await go(db, p["plan_token"], verifier=None, key="k-" + str(verifier))
        with pytest.raises(MasterDataRefused):
            await lm.execute(Ctx(db), plan_token=p["plan_token"], idempotency_key="k-noconf",
                             mode=MODE_ENFORCE, repository=repo(db),
                             approval_verifier=TrustedTestVerifier())
        after = await snapshot(db, LEGACY + ["md_organization", "md_person", lp.REFS_COLLECTION,
                                             lm.RUNS_COLLECTION])
        assert after == before
        events = await audit(db)
        assert [e["action"] for e in events] == ["master_data.legacy_migration.execute_refused"] * 2
        assert all(e["result"] == "denied" and e["error_code"] == "APPROVAL_REQUIRED"
                   and e["approval_id"] is None for e in events)
    run(body())


def test_execute_migrates_verifies_reconciles_and_never_touches_legacy_collections():
    async def body():
        db = await seeded()
        legacy_before = await snapshot(db, LEGACY + list(reference_docs(ORG_A)))
        p, out = await migrated(db, batch_size=7)
        assert out.performed and out.status == lm.RUN_COMPLETED and not out.resumed
        assert out.batches == -(-len(p["items"]) // 7)
        assert await snapshot(db, LEGACY + list(reference_docs(ORG_A))) == legacy_before

        rows = await db[lp.REFS_COLLECTION].find({"tenant_id": T_A}).to_list(None)
        assert len(rows) == len(p["items"])
        # one organization, three roles, both identifiers
        c1 = await la.resolve_legacy(Ctx(db), collection="companies", legacy_id="c1",
                                     mode=MODE_ENFORCE, repository=repo(db))
        for coll, lid in (("clients", "cl1"), ("counterparties", "cp1")):
            other = await la.resolve_legacy(Ctx(db), collection=coll, legacy_id=lid,
                                            mode=MODE_ENFORCE, repository=repo(db))
            assert other["canonical_id"] == c1["canonical_id"]
        org = c1["entity"]
        assert sorted({r for e in org["legacy_refs"] for r in e.get("roles", [])}) == ["client", "supplier"]
        assert sorted(i["kind"] for i in org["identifiers"]) == ["eik", "vat"]
        assert org["source"] == lm.SOURCE_LEGACY_MIGRATION and org["tenant_id"] == T_A
        assert all(e["org_id"] == ORG_A for e in org["legacy_refs"])
        # attached to a Master that existed before the run
        s2 = await la.resolve_legacy(Ctx(db), collection="subcontractors", legacy_id="s2",
                                     mode=MODE_ENFORCE, repository=repo(db))
        assert s2["canonical_id"] == "org-existing"
        # employee profile is the same person as its user
        ep1 = await la.resolve_legacy(Ctx(db), collection="employee_profiles", legacy_id="ep1",
                                      mode=MODE_ENFORCE, repository=repo(db))
        u1 = await la.resolve_legacy(Ctx(db), collection="users", legacy_id="u1",
                                     mode=MODE_ENFORCE, repository=repo(db))
        assert ep1["canonical_id"] == u1["canonical_id"]
        # hierarchy and asset type point at migrated Masters
        ln2 = await la.resolve_legacy(Ctx(db), collection="location_nodes", legacy_id="ln2",
                                      mode=MODE_ENFORCE, repository=repo(db))
        ln1 = await la.resolve_legacy(Ctx(db), collection="location_nodes", legacy_id="ln1",
                                      mode=MODE_ENFORCE, repository=repo(db))
        assert ln2["entity"]["parent_id"] == ln1["canonical_id"]
        au1 = await la.resolve_legacy(Ctx(db), collection="asset_units", legacy_id="au1",
                                      mode=MODE_ENFORCE, repository=repo(db))
        ai1 = await la.resolve_legacy(Ctx(db), collection="asset_items", legacy_id="ai1",
                                      mode=MODE_ENFORCE, repository=repo(db))
        assert au1["entity"]["asset_type_id"] == ai1["canonical_id"]
        # pending and blocked ids are accounted for, and resolve to nothing
        u2 = await la.resolve_legacy(Ctx(db), collection="users", legacy_id="u2",
                                     mode=MODE_ENFORCE, repository=repo(db))
        assert u2["status"] == "pending" and u2["canonical_id"] is None
        # exact names never became a person: no Master named "Мария Георгиева"
        assert await db["md_person"].count_documents({"normalized_name": "мария георгиева"}) == 0
        assert await db["md_activity"].count_documents({"legacy_refs.collection": "smr_groups"}) == 0

        report = await lm.reconcile(Ctx(db), mode=MODE_ENFORCE, repository=repo(db))
        assert report["zero_lost"] is True
        assert report["counts"]["unmigrated"] == 0
        # pre-existing, reported, not caused: inv2->cp-gone, ep2->u-missing,
        # ln3->ln-gone, au2->ai-missing
        assert report["counts"]["dangling_references"] == 4
        assert all(r["lost"] == 0 for r in report["references"])
        by_ref = {(r["collection"], r["field"]): r for r in report["references"]}
        assert by_ref[("asset_items", "type")]["accounted"] == 1        # by key, not by id
        run_doc = await lm.run_status(Ctx(db), run_id=out.run_id, mode=MODE_ENFORCE, repository=repo(db))
        assert run_doc["evidence"]["before"]["counts"]["unmigrated"] == len(p["items"])
        assert run_doc["evidence"]["zero_lost"] is True and run_doc["schema_version"] == 1

        events = await audit(db)
        actions = [e["action"] for e in events]
        assert actions.count("master_data.legacy_migration.batch_applied") == out.batches
        assert actions.count("master_data.legacy_migration.completed") == 1
        assert all(e["correlation_id"] == out.run_id and e["approval_id"] == "APR-run-1"
                   for e in events)
        assert verify_chain(events)[0]
        # no hard delete anywhere
        return out
    run(body())


def test_the_same_request_is_replayed_and_a_stale_plan_is_refused():
    async def body():
        db = await seeded()
        p, out = await migrated(db)
        n = await db[lp.REFS_COLLECTION].count_documents({})
        again = await go(db, p["plan_token"])
        assert again.replayed and again.run_id == out.run_id
        assert await db[lp.REFS_COLLECTION].count_documents({}) == n
        # a second run of the same (now executed) plan is stale
        with pytest.raises(lm.MigrationStalePlan):
            await go(db, p["plan_token"], key="run-2")

        fresh = await seeded()
        p2 = await dry(fresh)
        await fresh["companies"].update_one({"id": "c1"}, {"$set": {"name": "Друго"}})
        with pytest.raises(lm.MigrationStalePlan):
            await go(fresh, p2["plan_token"])
        assert await fresh[lp.REFS_COLLECTION].count_documents({}) == 0
        assert (await audit(fresh))[-1]["error_code"] == "STALE_PLAN"
    run(body())


def _state(docs):
    drop = {"created_at", "updated_at", "recorded_at", "attempts"}
    return sorted((lp.digest({k: v for k, v in d.items() if k not in drop and k != "_id"})
                   for d in docs))


@pytest.mark.parametrize("step", ["run_started", "item:0:2", "batch:0", "item:2:0", "verified",
                                  "audited"])
def test_an_interrupted_run_is_resumed_by_the_same_request(step):
    async def body():
        reference = await seeded()
        _p, clean = await migrated(reference, batch_size=5)

        db = await seeded()
        p = await dry(db)
        with pytest.raises(lm._Interrupted):
            await go(db, p["plan_token"], batch_size=5, _fail_after=step)
        run_doc = await db[lm.RUNS_COLLECTION].find_one({})
        assert run_doc["status"] == lm.RUN_INTERRUPTED
        # nothing reports success, and nobody else may start while it is half done
        with pytest.raises((lm.MigrationStalePlan, lm.MigrationBusy)):
            await go(db, p["plan_token"], key="other", batch_size=5)
        out = await go(db, p["plan_token"], batch_size=5)
        assert out.performed and out.resumed and out.status == lm.RUN_COMPLETED
        for name in ("md_person", "md_organization", "md_location", lp.REFS_COLLECTION):
            got = await db[name].find({}, {"_id": 0}).to_list(None)
            want = await reference[name].find({}, {"_id": 0}).to_list(None)
            assert len(got) == len(want), name
        actions = [e["action"] for e in await audit(db)]
        assert actions.count("master_data.legacy_migration.completed") == 1
        assert actions.count("master_data.legacy_migration.batch_applied") == clean.batches
        report = await lm.reconcile(Ctx(db), mode=MODE_ENFORCE, repository=repo(db))
        assert report["zero_lost"]
    run(body())


def test_a_storage_failure_mid_batch_is_recorded_not_reported_as_success():
    async def body():
        db = await seeded()
        p = await dry(db)
        spy = Spy(db)
        spy.fail_on[(lp.REFS_COLLECTION, "insert_one")] = 1
        with pytest.raises(MasterDataAuditFailed) as info:
            await go(spy, p["plan_token"], batch_size=4)
        assert "NOT successful" in str(info.value)
        assert (await db[lm.RUNS_COLLECTION].find_one({}))["status"] == lm.RUN_INTERRUPTED
        out = await go(db, p["plan_token"], batch_size=4)
        assert out.performed and out.resumed
    run(body())


def test_a_legacy_change_during_an_interrupted_run_fails_closed_on_resume():
    async def body():
        db = await seeded()
        p = await dry(db)
        with pytest.raises(lm._Interrupted):
            await go(db, p["plan_token"], batch_size=5, _fail_after="batch:0")
        await db["warehouses"].update_one({"id": "wh1"}, {"$set": {"name": "Преименуван"}})
        with pytest.raises(lm.MigrationStalePlan):
            await go(db, p["plan_token"], batch_size=5)
        assert (await db[lm.RUNS_COLLECTION].find_one({}))["status"] == lm.RUN_INTERRUPTED
        assert await db["md_location"].count_documents({"legacy_refs.legacy_id": "wh1"}) == 0
        assert (await audit(db))[-1]["action"] == "master_data.legacy_migration.execute_refused"
        # the run can be rolled back as a whole
        prev = await lm.preview_rollback(Ctx(db), run_id=lm.run_id_for(T_A, "run-1"),
                                         mode=MODE_ENFORCE, repository=repo(db))
        assert prev["executable"], prev["blocking"]
        await lm.rollback(Ctx(db), run_id=prev["run_id"], preview_token=prev["preview_token"],
                          idempotency_key="rb", reason="source changed", confirmation=True,
                          approval_id="APR-rb", mode=MODE_ENFORCE, repository=repo(db),
                          approval_verifier=TrustedTestVerifier())
    run(body())


def test_a_failed_verification_is_never_a_success(monkeypatch):
    async def fake_verify(*a, **kw):
        return [{"collection": "users", "legacy_id": "u1", "problem": "forced"}]
    monkeypatch.setattr(lm, "verify_items", fake_verify)

    async def body():
        db = await seeded()
        p = await dry(db)
        with pytest.raises(lm.MigrationVerificationFailed):
            await go(db, p["plan_token"])
        assert (await db[lm.RUNS_COLLECTION].find_one({}))["status"] == lm.RUN_VERIFICATION_FAILED
        actions = [e["action"] for e in await audit(db)]
        assert "master_data.legacy_migration.completed" not in actions
        assert actions[-1] == "master_data.legacy_migration.execute_refused"
    run(body())


# ================================================================ isolation
def test_same_legacy_id_and_name_in_two_tenants_never_meet():
    async def body():
        shared = await seeded()                      # a shared legacy database, two orgs
        await seed(shared, ORG_B)
        pa = await dry(shared)
        a = await go(shared, pa["plan_token"])
        b_ctx = Ctx(shared, tenant_id=T_B, org_id=ORG_B, user_id="owner-b")
        pb = await dry(shared, ctx=b_ctx)
        assert len(pb["items"]) == len(pa["items"])             # B unaffected by A's run
        b = await go(shared, pb["plan_token"], ctx=b_ctx)
        ra = await la.resolve_legacy(Ctx(shared), collection="users", legacy_id="u1",
                                     mode=MODE_ENFORCE, repository=repo(shared))
        rb = await la.resolve_legacy(b_ctx, collection="users", legacy_id="u1",
                                     mode=MODE_ENFORCE, repository=repo(shared, T_B))
        assert ra["canonical_id"] != rb["canonical_id"]
        assert ra["entity"]["tenant_id"] == T_A and rb["entity"]["tenant_id"] == T_B
        assert a.run_id != b.run_id
        # database-per-tenant: a tenant database without B's data knows nothing of B
        only_a = await seeded()
        assert await la.resolve_legacy(Ctx(only_a, tenant_id=T_B, org_id=ORG_B),
                                       collection="users", legacy_id="u1", mode=MODE_ENFORCE,
                                       repository=repo(only_a, T_B)) is None
    run(body())


def test_injected_or_foreign_legacy_refs_are_refused_not_followed():
    async def body():
        db = await seeded()
        _p, _out = await migrated(db)
        # a Master that claims another org's legacy document
        evil = build_entity(tenant_id=T_A, entity_type=models.ENTITY_ORGANIZATION,
                            display_name="Чужда", entity_id="org-evil", now=NOW,
                            legacy_refs=[models.new_legacy_ref("companies", "c-of-b", ORG_B)])
        await db["md_organization"].insert_one(evil)
        report = await lm.reconcile(Ctx(db), mode=MODE_ENFORCE, repository=repo(db))
        assert report["counts"]["foreign_legacy_refs"] == 1 and not report["zero_lost"]
        assert await la.resolve_legacy(Ctx(db), collection="companies", legacy_id="c-of-b",
                                       mode=MODE_ENFORCE, repository=repo(db)) is None
        plan = await dry(db)
        assert {"entity_type": "organization", "entity_id": "org-evil",
                "finding": "FOREIGN_LEGACY_REF", "collection": "companies",
                "legacy_id": "c-of-b"} in plan["integrity_findings"]
        # a reverse-reference row pointing at another org
        await db[lp.REFS_COLLECTION].update_one(
            {"_id": lp.ref_row_id(T_A, "users", "u1")}, {"$set": {"org_id": ORG_B}})
        with pytest.raises(la.LegacyReferenceInconsistent):
            await la.resolve_legacy(Ctx(db), collection="users", legacy_id="u1",
                                    mode=MODE_ENFORCE, repository=repo(db))
        # a row whose Master does not carry the reference back
        row = await db[lp.REFS_COLLECTION].find_one({"_id": lp.ref_row_id(T_A, "items", "i1")})
        await db["md_item"].update_one({"id": row["entity_id"]},
                                       {"$set": {"legacy_refs": []}})
        with pytest.raises(la.LegacyReferenceInconsistent):
            await la.resolve_legacy(Ctx(db), collection="items", legacy_id="i1",
                                    mode=MODE_ENFORCE, repository=repo(db))
        report = await lm.reconcile(Ctx(db), mode=MODE_ENFORCE, repository=repo(db))
        assert report["counts"]["broken_rows"] >= 2 and not report["zero_lost"]
    run(body())


def test_a_legacy_document_deleted_after_migration_still_resolves():
    async def body():
        db = await seeded()
        await migrated(db)
        await db["companies"].delete_one({"id": "c1"})       # e.g. an old route, before enforce
        report = await lm.reconcile(Ctx(db), mode=MODE_ENFORCE, repository=repo(db))
        assert report["sources"]["companies"]["legacy_gone"] == 1 and report["zero_lost"]
        r = await la.resolve_legacy(Ctx(db), collection="companies", legacy_id="c1",
                                    mode=MODE_ENFORCE, repository=repo(db))
        assert r["canonical_id"]
    run(body())


# ================================================================ merge & history
def test_old_ids_follow_merge_redirect_unmerge_and_history():
    async def body():
        db = await seeded()
        await migrated(db)
        ctx = Ctx(db)
        u1 = await la.resolve_legacy(ctx, collection="users", legacy_id="u1", mode=MODE_ENFORCE,
                                     repository=repo(db))
        u3 = await la.resolve_legacy(ctx, collection="users", legacy_id="u3", mode=MODE_ENFORCE,
                                     repository=repo(db))
        prev = await mm.preview_merge(ctx, entity_type="person", source_id=u1["canonical_id"],
                                      target_id=u3["canonical_id"], mode=MODE_ENFORCE,
                                      repository=repo(db))
        merged = await mm.merge(ctx, entity_type="person", source_id=u1["canonical_id"],
                                target_id=u3["canonical_id"], preview_token=prev["preview_token"],
                                idempotency_key="m1", confirmation=True, approval_id="APR-m1",
                                mode=MODE_ENFORCE, repository=repo(db),
                                approval_verifier=TrustedTestVerifier())
        for coll, lid in (("users", "u1"), ("employee_profiles", "ep1")):
            r = await la.resolve_legacy(ctx, collection=coll, legacy_id=lid, mode=MODE_ENFORCE,
                                        repository=repo(db))
            assert r["canonical_id"] == u3["canonical_id"] and r["redirected"]
            assert r["chain"] == [u1["canonical_id"], u3["canonical_id"]]
        assert (await lm.reconcile(ctx, mode=MODE_ENFORCE, repository=repo(db)))["zero_lost"]
        up = await mm.preview_unmerge(ctx, entity_type="person", source_id=u1["canonical_id"],
                                      mode=MODE_ENFORCE, repository=repo(db))
        await mm.unmerge(ctx, entity_type="person", source_id=u1["canonical_id"],
                         merge_event_id=merged.event_id, preview_token=up["preview_token"],
                         idempotency_key="um1", reason="wrong person", confirmation=True,
                         approval_id="APR-um1", mode=MODE_ENFORCE, repository=repo(db),
                         approval_verifier=TrustedTestVerifier())
        back = await la.resolve_legacy(ctx, collection="users", legacy_id="u1", mode=MODE_ENFORCE,
                                       repository=repo(db))
        assert back["canonical_id"] == u1["canonical_id"] and not back["redirected"]
        hist = await mm.history(ctx, entity_type="person", entity_id=u1["canonical_id"],
                                mode=MODE_ENFORCE, repository=repo(db))
        assert [h["kind"] for h in hist] == ["merge", "unmerge"]
        # a run whose record was merged into cannot be rolled back
        await mm.merge(ctx, entity_type="person", source_id=u1["canonical_id"],
                       target_id=u3["canonical_id"],
                       preview_token=(await mm.preview_merge(
                           ctx, entity_type="person", source_id=u1["canonical_id"],
                           target_id=u3["canonical_id"], mode=MODE_ENFORCE,
                           repository=repo(db)))["preview_token"],
                       idempotency_key="m2", confirmation=True, approval_id="APR-m2",
                       mode=MODE_ENFORCE, repository=repo(db), approval_verifier=TrustedTestVerifier())
        rb = await lm.preview_rollback(ctx, run_id=lm.run_id_for(T_A, "run-1"), mode=MODE_ENFORCE,
                                       repository=repo(db))
        assert not rb["executable"] and any("merge" in b or "merged" in b for b in rb["blocking"])
        with pytest.raises(MasterDataRefused):
            await lm.rollback(ctx, run_id=rb["run_id"], preview_token=rb["preview_token"],
                              idempotency_key="rb", reason="x", confirmation=True,
                              approval_id="APR-rb", mode=MODE_ENFORCE, repository=repo(db),
                              approval_verifier=TrustedTestVerifier())
    run(body())


# ================================================================ rollback
def test_rollback_archives_and_detaches_and_never_deletes():
    async def body():
        db = await seeded()
        p, out = await migrated(db)
        counts = {n: await db[n].count_documents({}) for n in
                  ("md_person", "md_organization", "md_location", lp.REFS_COLLECTION)}
        ctx = Ctx(db)
        prev = await lm.preview_rollback(ctx, run_id=out.run_id, mode=MODE_ENFORCE,
                                         repository=repo(db))
        assert prev["executable"] and "org-existing" in prev["legacy_refs_to_detach"]
        with pytest.raises(MasterDataApprovalRequired):
            await lm.rollback(ctx, run_id=out.run_id, preview_token=prev["preview_token"],
                              idempotency_key="rb", reason="test", confirmation=True,
                              approval_id="APR-forged", mode=MODE_ENFORCE, repository=repo(db))
        done = await lm.rollback(ctx, run_id=out.run_id, preview_token=prev["preview_token"],
                                 idempotency_key="rb", reason="test", confirmation=True,
                                 approval_id="APR-rb", mode=MODE_ENFORCE, repository=repo(db),
                                 approval_verifier=TrustedTestVerifier())
        assert done.performed and done.status == lm.RUN_ROLLED_BACK
        assert {n: await db[n].count_documents({}) for n in counts} == counts     # nothing deleted
        assert await db["md_person"].count_documents({"status": "active",
                                                      "migration_run_id": out.run_id}) == 0
        existing = await db["md_organization"].find_one({"id": "org-existing"})
        assert existing["status"] == "active" and existing["legacy_refs"] == []
        assert await la.resolve_legacy(ctx, collection="users", legacy_id="u1", mode=MODE_ENFORCE,
                                       repository=repo(db)) is None
        rows = await db[lp.REFS_COLLECTION].find({}).to_list(None)
        assert {r["status"] for r in rows} == {"rolled_back"} and all(r["history"] for r in rows)
        again = await lm.rollback(ctx, run_id=out.run_id, preview_token=prev["preview_token"],
                                  idempotency_key="rb", reason="test", confirmation=True,
                                  approval_id="APR-rb", mode=MODE_ENFORCE, repository=repo(db),
                                  approval_verifier=TrustedTestVerifier())
        assert again.replayed
        # the tenant can be migrated again, under a new key, into fresh records
        p2 = await dry(db)
        assert p2["totals"]["create"] == p["totals"]["create"]
        out2 = await go(db, p2["plan_token"], key="run-2")
        assert out2.performed
        assert (await lm.reconcile(ctx, mode=MODE_ENFORCE, repository=repo(db)))["zero_lost"]
        rows = await db[lp.REFS_COLLECTION].find({"status": "mapped"}).to_list(None)
        assert all(r["run_id"] == out2.run_id and r["history"] for r in rows)
    run(body())


# ================================================================ human mapping
def test_pending_legacy_records_are_decided_only_by_a_person_with_approval():
    async def body():
        db = await seeded()
        await migrated(db)
        ctx = Ctx(db, user_id="office-1")
        pending = await lm.list_mappings(ctx, mode=MODE_ENFORCE, repository=repo(db))
        assert {(r["collection"], r["legacy_id"]) for r in pending} >= {
            ("users", "u2"), ("persons", "p1")}
        u3 = await la.resolve_legacy(ctx, collection="users", legacy_id="u3", mode=MODE_ENFORCE,
                                     repository=repo(db))

        async def decide(**kw):
            kw.setdefault("confirmation", True)
            kw.setdefault("approval_verifier", TrustedTestVerifier())
            return await lm.resolve_mapping(ctx, mode=MODE_ENFORCE, repository=repo(db), **kw)

        with pytest.raises(MasterDataApprovalRequired):
            await decide(collection="users", legacy_id="u2", decision="map", idempotency_key="d0",
                         canonical_entity_id=u3["canonical_id"], approval_id="forged",
                         approval_verifier=None)
        assert (await audit(db))[-1]["action"] == "master_data.legacy_mapping.resolve_refused"
        out = await decide(collection="users", legacy_id="u2", decision="create_new",
                           idempotency_key="d1", approval_id="APR-d1")
        assert out.performed and out.status == "mapped"
        again = await decide(collection="users", legacy_id="u2", decision="create_new",
                             idempotency_key="d1", approval_id="APR-d1")
        assert again.replayed
        person = await la.resolve_legacy(ctx, collection="users", legacy_id="u2",
                                         mode=MODE_ENFORCE, repository=repo(db))
        assert person["entity"]["display_name"] == "Мария Георгиева"
        # the person who shares that name is mapped onto it only because a human says so
        mapped = await decide(collection="persons", legacy_id="p1", decision="map",
                              idempotency_key="d2", canonical_entity_id=person["canonical_id"],
                              approval_id="APR-d2")
        assert mapped.entity_id == person["canonical_id"]
        with pytest.raises(MasterDataInvalid):          # ambiguous type must be chosen
            await decide(collection="clients", legacy_id="cl2", decision="create_new",
                         idempotency_key="d3", approval_id="APR-d3")
        cl2 = await decide(collection="clients", legacy_id="cl2", decision="create_new",
                           entity_type="person", idempotency_key="d4", approval_id="APR-d4")
        assert (await db["md_person"].find_one({"id": cl2.entity_id}))["display_name"] == "Петър Петров"
        with pytest.raises(MasterDataRefused):          # a project group is never a Master
            await decide(collection="smr_groups", legacy_id="g1", decision="create_new",
                         idempotency_key="d5", approval_id="APR-d5")
        w1 = await la.resolve_legacy(ctx, collection="work_types", legacy_id="w1",
                                     mode=MODE_ENFORCE, repository=repo(db))
        g1 = await decide(collection="smr_groups", legacy_id="g1", decision="map",
                          canonical_entity_id=w1["canonical_id"], idempotency_key="d6",
                          approval_id="APR-d6")
        assert g1.entity_id == w1["canonical_id"]
        with pytest.raises(MasterDataInvalid):
            await decide(collection="counterparties", legacy_id="cp2", decision="decline",
                         idempotency_key="d7", approval_id="APR-d7")
        declined = await decide(collection="counterparties", legacy_id="cp2", decision="decline",
                                reason="private person, not a supplier", idempotency_key="d8",
                                approval_id="APR-d8")
        assert declined.status == "declined"
        with pytest.raises(MasterDataRefused):          # already decided
            await decide(collection="users", legacy_id="u2", decision="decline", reason="x",
                         idempotency_key="d9", approval_id="APR-d9")
        report = await lm.reconcile(ctx, mode=MODE_ENFORCE, repository=repo(db))
        assert report["zero_lost"]
        assert report["sources"]["counterparties"]["rows"].get("declined") == 1
        events = [e for e in await audit(db) if e["action"] == "master_data.legacy_mapping.resolved"]
        assert len(events) == 5 and all(e["actor_id"] == "office-1" for e in events)
    run(body())


# ================================================================ AI/OCR/Excel & advances
def test_ai_ocr_excel_proposals_never_become_official_master_records():
    from app.master_data import pending
    from app.master_data.pending import SOURCE_AI, SOURCE_EXCEL, SOURCE_OCR

    async def body():
        db = await seeded()
        ctx = Ctx(db)
        for channel, extra in ((SOURCE_AI, {"model_and_version": "m/1"}), (SOURCE_OCR, {}),
                               (SOURCE_EXCEL, {})):
            out = await pending.propose(ctx, entity_type="organization", raw_value="Баумит ЕООД",
                                        source_channel=channel, mode=MODE_ENFORCE,
                                        repository=repo(db), **extra)
            assert out.performed
        before = await db["md_organization"].count_documents({})
        p, _out = await migrated(db)
        # the migration reads only legacy identity collections — never the pending queue
        assert all(i["collection"] in LEGACY for i in p["items"])
        assert await db["md_organization"].count_documents(
            {"source": {"$ne": lm.SOURCE_LEGACY_MIGRATION}}) == before
        assert await db["md_pending_mapping"].count_documents({"status": "pending"}) == 1
    run(body())


def test_the_advance_mapping_report_is_read_only_and_proposes_only():
    async def body():
        db = await seeded()
        await migrated(db)
        spy = Spy(db, refuse_writes=True)
        before = await snapshot(db, ["advances"])
        report = await la.advance_mapping_report(spy, tenant_id=T_A, org_id=ORG_A)
        assert spy.writes == [] and await snapshot(db, ["advances"]) == before
        assert report["read_only"] and report["auto_mapped"] == 0 and report["total"] == 1
        row = report["advances"][0]
        assert row["advance_id"] == "adv2" and row["decision"] == "requires_human_mapping"
        legacy = {tuple(c["legacy"]) for c in row["candidates"] if "legacy" in c}
        assert legacy == {("users", "u2"), ("persons", "p1")}      # exact names: proposals only
        adv = await db["advances"].find_one({"id": "adv2"})
        assert adv["guest_name"] == "Мария Георгиева" and "master_person_id" not in adv
    run(body())
