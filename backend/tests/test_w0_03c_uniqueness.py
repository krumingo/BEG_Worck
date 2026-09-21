"""
W0-03C — duplicate report and index bootstrap.

Contract: docs/architecture/W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md §6 "W0-03C".

  * the duplicate report is read-only and names exactly the records that block each
    planned unique index — per tenant, without merging or fixing anything;
  * the bootstrap builds an index only after a fresh, clean report, refuses on
    duplicates, keeps tenants apart, is safe to run twice, undoes a half-built run and
    hands back a rollback plan that can only drop what it created;
  * it never builds anything outside a disposable local MongoDB.

The database here is an in-memory double that enforces unique indexes the way MongoDB
does (``IndexDb``). The same flows against a real ``mongod`` are in
``test_w0_03c_real_mongo.py``, which runs only when a disposable local server is given.
"""
import asyncio
import copy
import json

import pytest
from pymongo.errors import DuplicateKeyError, OperationFailure

from app.master_data import index_bootstrap as ib
from app.master_data import models, uniqueness as uq
from app.master_data.models import MasterDataInvalid, build_entity, new_alias, new_identifier
from app.master_data.pending import PENDING_COLLECTION, STATUS_PENDING

T_A = "tenant-a"
T_B = "tenant-b"
NOW = "2026-09-21T10:00:00+00:00"
LOCAL = {"hosts": ["localhost"], "scheme": "mongodb", "confirm_database": "w003c_scratch"}
SCRATCH = "w003c_scratch"
NO_ENV = {}


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- an index-aware Mongo double

class Cursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return list(self._docs)


def _project(doc, projection):
    out = copy.deepcopy(doc)
    if projection and projection.get("_id") == 0:
        out.pop("_id", None)
    return out


class IndexCollection:
    """Stores documents and enforces unique indexes with MongoDB's key rules
    (``uq.index_keys``): partial filter, multikey arrays, null for a missing field."""

    def __init__(self, db, name):
        self.db, self.name = db, name
        self.docs = []
        self.indexes = {"_id_": {"key": [("_id", 1)], "v": 2}}
        self.calls = []

    # -- writes
    async def insert_one(self, doc):
        self.calls.append("insert_one")
        doc = copy.deepcopy(doc)
        doc.setdefault("_id", "oid-%d" % self.db.next_oid())
        if any(d.get("_id") == doc["_id"] for d in self.docs):
            raise DuplicateKeyError("E11000 duplicate key error collection: %s index: _id_" % self.name)
        for name, info in self.indexes.items():
            if name == "_id_" or not info.get("unique"):
                continue
            mine = set(repr(k) for k in uq.index_keys(doc, self._key_of(name, info)))
            for other in self.docs:
                theirs = set(repr(k) for k in uq.index_keys(other, self._key_of(name, info)))
                if mine & theirs:
                    raise DuplicateKeyError("E11000 duplicate key error collection: %s index: %s"
                                            % (self.name, name))
        self.docs.append(doc)
        self.db.touch(self.name)

    async def update_one(self, filter, update):
        """Equality on ``_id`` and ``$set`` — all the run ledger needs."""
        self.calls.append("update_one")
        if self.name in self.db.fail_update:
            raise OperationFailure("write to %s refused" % self.name)
        for d in self.docs:
            if all(d.get(k) == v for k, v in filter.items()):
                d.update(copy.deepcopy(update.get("$set", {})))
                return

    async def create_index(self, keys, name=None, unique=False, partialFilterExpression=None):
        self.calls.append("create_index:%s" % name)
        if name in self.db.fail_on:
            raise OperationFailure("index build of %s interrupted" % name)
        info = {"key": list(keys), "v": 2}
        if unique:
            info["unique"] = True
        if partialFilterExpression:
            info["partialFilterExpression"] = partialFilterExpression
        if unique:
            _, groups = uq.blocking_groups(self.docs, self._key_of(name, info))
            if groups:
                raise DuplicateKeyError("E11000 duplicate key error collection: %s index: %s"
                                        % (self.name, name))
        self.indexes[name] = info
        self.db.touch(self.name)
        return name

    async def drop_index(self, name):
        self.calls.append("drop_index:%s" % name)
        if name in self.db.fail_drop:
            raise OperationFailure("cannot drop %s" % name)
        if name not in self.indexes:
            raise OperationFailure("index not found with name [%s]" % name)
        del self.indexes[name]

    # -- reads
    def find(self, filter=None, projection=None):
        self.calls.append("find")
        return Cursor([_project(d, projection) for d in self.docs])

    async def index_information(self):
        self.calls.append("index_information")
        return copy.deepcopy(self.indexes)

    @staticmethod
    def _key_of(name, info):
        return uq.UniqueKey(name=name, collection="-", fields=tuple(f for f, _ in info["key"]),
                            partial=info.get("partialFilterExpression"), description="")


class IndexDb:
    def __init__(self):
        self.collections = {}
        self.present = set()
        self.fail_on = set()
        self.fail_drop = set()
        self.fail_update = set()
        self._oid = 0

    def next_oid(self):
        self._oid += 1
        return self._oid

    def touch(self, name):
        self.present.add(name)

    def __getitem__(self, name):
        if name not in self.collections:
            self.collections[name] = IndexCollection(self, name)
        return self.collections[name]

    async def list_collection_names(self):
        return sorted(self.present)

    def indexes(self, name):
        return set(self.collections[name].indexes) if name in self.collections else set()

    def all_calls(self):
        return [c for coll in self.collections.values() for c in coll.calls]

    def snapshot(self):
        return {n: copy.deepcopy(c.docs) for n, c in self.collections.items()}


def seed(db, collection, *docs):
    for d in docs:
        db[collection].docs.append(copy.deepcopy(d))
        db.touch(collection)


def org(tenant, name, eik=None, *, status="active", aliases=(), entity_id=None):
    doc = build_entity(tenant_id=tenant, entity_type="organization", display_name=name,
                       entity_id=entity_id, now=NOW)
    if eik:
        doc["identifiers"] = [new_identifier("organization", "eik", eik)]
    doc["aliases"] = [new_alias(a, "office-1", now=NOW) for a in aliases]
    doc["status"] = status
    if status == "merged":
        doc["merged_into"] = "somewhere"
    return doc


def tag(tenant, name, *, status="active"):
    doc = build_entity(tenant_id=tenant, entity_type="tag", display_name=name, now=NOW)
    doc["status"] = status
    return doc


def pending(tenant, entity_type, normalized, *, status=STATUS_PENDING, pid=None):
    return {"id": pid or "p-%s-%s-%s" % (tenant, normalized, status), "tenant_id": tenant,
            "entity_type": entity_type, "normalized_value": normalized, "raw_value": normalized,
            "status": status}


def index_of(report, collection, name):
    for i in report["canonical"]["indexes"]:
        if i["collection"] == collection and i["name"] == name:
            return i
    raise AssertionError("no %s.%s in report" % (collection, name))


def report_of(db, **kw):
    return run(uq.duplicate_report(db, database=SCRATCH, now=NOW, **kw))


def boot(db, **kw):
    kw.setdefault("env", NO_ENV)
    return run(ib.bootstrap(db, database=SCRATCH, now=NOW, **kw))


# ================================================================ the plan itself

def test_every_planned_key_is_per_tenant_and_prefixed():
    assert len(uq.CANONICAL_KEYS) == 25
    for key in uq.CANONICAL_KEYS:
        assert key.fields[0] == "tenant_id", key
        assert key.name.startswith(uq.INDEX_PREFIX)
    names = [(k.collection, k.name) for k in uq.CANONICAL_KEYS]
    assert len(names) == len(set(names))


def test_the_plan_covers_all_nine_canonical_types_and_the_pending_queue():
    colls = {k.collection for k in uq.CANONICAL_KEYS}
    assert colls == {uq.collection_for(t) for t in models.ENTITY_TYPES} | {PENDING_COLLECTION}
    by_coll = {}
    for k in uq.CANONICAL_KEYS:
        by_coll.setdefault(k.collection, set()).add(k.name)
    assert by_coll["md_organization"] == {"md_uq_id", "md_uq_alias", "md_uq_identifier"}
    assert by_coll["md_tag"] == {"md_uq_id", "md_uq_alias", "md_uq_name"}
    assert by_coll["md_activity"] == {"md_uq_id", "md_uq_alias"}
    assert by_coll[PENDING_COLLECTION] == {"md_uq_open_pending"}


def test_module_literals_match_the_pending_queue():
    assert uq.PENDING_COLLECTION == PENDING_COLLECTION
    assert uq.PENDING_STATUS_OPEN == STATUS_PENDING


def test_merged_and_archived_records_are_outside_the_business_keys():
    for key in uq.CANONICAL_KEYS:
        if key.name in ("md_uq_alias", "md_uq_name", "md_uq_identifier"):
            assert key.partial["status"] == models.STATUS_ACTIVE
        if key.name == "md_uq_id":
            assert key.partial is None      # an id is never reused, whatever the status


# ================================================================ the report

def test_clean_database_gives_a_clean_report():
    db = IndexDb()
    seed(db, "md_organization", org(T_A, "Строй ЕООД", "123456789"), org(T_A, "Бетон АД", "987654321"))
    r = report_of(db)
    assert r["schema"] == uq.REPORT_SCHEMA
    assert r["canonical"]["clean"] is True
    assert r["canonical"]["blocked_indexes"] == []
    assert r["source"] == {"kind": "mongo", "database": SCRATCH, "read_only": True}
    ident = index_of(r, "md_organization", "md_uq_identifier")
    assert ident["documents_considered"] == 2 and ident["clean"]


def test_duplicate_eik_names_exactly_the_blocking_records():
    db = IndexDb()
    a = org(T_A, "Строй ЕООД", "123 456 789", entity_id="org-1")
    b = org(T_A, "СТРОЙ еоод", "BG-123456789".replace("BG-", ""), entity_id="org-2")
    c = org(T_A, "Друга фирма", "111111111", entity_id="org-3")
    seed(db, "md_organization", a, b, c)
    r = report_of(db)
    assert r["canonical"]["clean"] is False
    assert r["canonical"]["blocked_indexes"] == ["md_organization.md_uq_identifier"]
    groups = index_of(r, "md_organization", "md_uq_identifier")["blocking_groups"]
    assert len(groups) == 1
    g = groups[0]
    assert g["tenant_id"] == T_A
    assert g["key"] == {"tenant_id": T_A, "identifiers.key": "eik:123456789"}
    assert sorted(x["id"] for x in g["records"]) == ["org-1", "org-2"]
    assert {x["display_name"] for x in g["records"]} == {"Строй ЕООД", "СТРОЙ еоод"}


def test_the_report_changes_nothing():
    db = IndexDb()
    seed(db, "md_organization", org(T_A, "А", "1234"), org(T_A, "Б", "1234"))
    before = db.snapshot()
    report_of(db, include_legacy=True)
    assert db.snapshot() == before
    assert set(db.all_calls()) <= {"find", "index_information"}
    assert db.indexes("md_organization") == {"_id_"}


def test_any_write_through_the_report_handle_is_refused():
    ro = uq.ReadOnlyDatabase(IndexDb())
    for method in ("insert_one", "update_one", "update_many", "delete_one", "delete_many",
                   "replace_one", "create_index", "drop_index", "drop", "find_one_and_update",
                   "bulk_write", "aggregate"):
        with pytest.raises(uq.ReadOnlyViolation):
            getattr(ro["md_organization"], method)
    for method in ("drop_collection", "create_collection", "command"):
        with pytest.raises(uq.ReadOnlyViolation):
            getattr(ro, method)


def test_same_key_in_two_tenants_is_not_a_duplicate():
    db = IndexDb()
    seed(db, "md_organization", org(T_A, "Строй ЕООД", "123456789", aliases=["Строй"]),
         org(T_B, "Строй ЕООД", "123456789", aliases=["Строй"]))
    seed(db, "md_tag", tag(T_A, "спешно"), tag(T_B, "спешно"))
    r = report_of(db)
    assert r["canonical"]["clean"] is True


def test_a_dirty_tenant_is_reported_alone():
    db = IndexDb()
    seed(db, "md_tag", tag(T_A, "спешно"), tag(T_B, "Спешно"), tag(T_B, "  СПЕШНО "))
    r = report_of(db)
    assert r["canonical"]["blocked_indexes"] == ["md_tag.md_uq_name"]
    groups = index_of(r, "md_tag", "md_uq_name")["blocking_groups"]
    assert [g["tenant_id"] for g in groups] == [T_B]
    assert all(T_A not in json.dumps(g) for g in groups)


def test_merged_and_archived_records_do_not_block():
    db = IndexDb()
    seed(db, "md_organization",
         org(T_A, "Строй ЕООД", "123456789", aliases=["Строй"]),
         org(T_A, "Строй ЕООД (стар)", "123456789", aliases=["Строй"], status="merged"),
         org(T_A, "Строй ЕООД (архив)", "123456789", aliases=["Строй"], status="archived"))
    assert report_of(db)["canonical"]["clean"] is True


def test_a_reused_id_blocks_whatever_the_status():
    db = IndexDb()
    seed(db, "md_organization", org(T_A, "А", entity_id="same"),
         org(T_A, "Б", entity_id="same", status="archived"))
    r = report_of(db)
    assert r["canonical"]["blocked_indexes"] == ["md_organization.md_uq_id"]


def test_empty_alias_lists_do_not_collide():
    db = IndexDb()
    seed(db, "md_activity", *[build_entity(tenant_id=T_A, entity_type="activity",
                                           display_name="Дейност %d" % i, now=NOW) for i in range(3)])
    r = report_of(db)
    assert r["canonical"]["clean"] is True
    assert index_of(r, "md_activity", "md_uq_alias")["documents_considered"] == 0


def test_the_same_alias_twice_in_one_record_is_not_a_duplicate():
    db = IndexDb()
    seed(db, "md_organization", org(T_A, "Строй ЕООД", aliases=["Строй", "строй", "СТРОЙ"]))
    assert report_of(db)["canonical"]["clean"] is True


def test_one_alias_on_two_active_records_blocks():
    db = IndexDb()
    seed(db, "md_organization", org(T_A, "Строй ЕООД", aliases=["Строй"], entity_id="o1"),
         org(T_A, "Строй Инвест ООД", aliases=["строй"], entity_id="o2"))
    r = report_of(db)
    groups = index_of(r, "md_organization", "md_uq_alias")["blocking_groups"]
    assert len(groups) == 1 and groups[0]["key"]["aliases.normalized"] == "строй"
    assert sorted(x["id"] for x in groups[0]["records"]) == ["o1", "o2"]


def test_an_alias_without_normalized_value_indexes_as_null_and_is_reported():
    # MongoDB gives an array element without the field a null key. Two such records in one
    # tenant would break the build, so the report must say so rather than stay silent.
    db = IndexDb()
    for oid in ("o1", "o2"):
        doc = org(T_A, "Фирма " + oid, aliases=["Истински"] if oid == "o1" else ["Друг"], entity_id=oid)
        doc["aliases"].append({"value": "стар запис", "added_by": "legacy"})
        seed(db, "md_organization", doc)
    groups = index_of(report_of(db), "md_organization", "md_uq_alias")["blocking_groups"]
    assert [g["key"]["aliases.normalized"] for g in groups] == [None]


def test_two_open_proposals_for_one_text_block_but_decided_ones_do_not():
    db = IndexDb()
    seed(db, PENDING_COLLECTION,
         pending(T_A, "unit", "м2", pid="p1"),
         pending(T_A, "unit", "м2", status="resolved", pid="p2"),
         pending(T_A, "unit", "м2", status="rejected", pid="p3"),
         pending(T_A, "activity", "м2", pid="p4"),
         pending(T_B, "unit", "м2", pid="p5"))
    assert report_of(db)["canonical"]["clean"] is True
    seed(db, PENDING_COLLECTION, pending(T_A, "unit", "м2", pid="p6"))
    r = report_of(db)
    groups = index_of(r, PENDING_COLLECTION, "md_uq_open_pending")["blocking_groups"]
    assert len(groups) == 1
    assert sorted(x["id"] for x in groups[0]["records"]) == ["p1", "p6"]


def test_a_canonical_record_without_tenant_blocks_everything():
    db = IndexDb()
    doc = org(T_A, "Без tenant")
    del doc["tenant_id"]
    seed(db, "md_organization", doc)
    r = report_of(db)
    assert r["canonical"]["clean"] is False
    assert r["canonical"]["tenantless_records"][0]["collection"] == "md_organization"


def test_egn_is_masked_in_the_report():
    db = IndexDb()
    for pid in ("p1", "p2"):
        doc = build_entity(tenant_id=T_A, entity_type="person", display_name="Иван " + pid,
                           entity_id=pid, now=NOW)
        doc["identifiers"] = [new_identifier("person", "egn", "8001011234")]
        seed(db, "md_person", doc)
    r = report_of(db)
    assert "8001011234" not in json.dumps(r, ensure_ascii=False)
    g = index_of(r, "md_person", "md_uq_identifier")["blocking_groups"][0]
    assert g["key"]["identifiers.key"] == "egn:80****34"


def test_absent_collections_are_reported_as_absent_not_as_clean_data():
    r = report_of(IndexDb())
    assert r["canonical"]["clean"] is True
    assert all(i["collection_present"] is False for i in r["canonical"]["indexes"])


# ---------------------------------------------------------------- legacy projection (W0-03E preview)

def test_legacy_projection_separates_merge_cases_from_one_company_many_roles():
    db = IndexDb()
    seed(db, "companies", {"id": "c1", "org_id": "org-1", "name": "Строй ЕООД", "eik": "123456789"})
    seed(db, "clients", {"id": "k1", "org_id": "org-1", "name": "Строй", "eik": "123 456 789"})
    seed(db, "counterparties",
         {"id": "x1", "org_id": "org-1", "name": "Бетон", "eik": "555"},
         {"id": "x2", "org_id": "org-1", "name": "Бетон АД", "eik": "555"},
         {"id": "x3", "org_id": "org-2", "name": "Бетон", "eik": "555"})
    r = report_of(db, include_legacy=True)
    eik = [lp for lp in r["legacy_projection"] if lp["kind"] == "eik"][0]
    by_key = {g["key"]: g for g in eik["groups"]}
    assert by_key["eik:123456789"]["across_collections"] is True
    assert by_key["eik:123456789"]["within_collection"] == []
    assert by_key["eik:555"]["within_collection"] == ["counterparties"]
    assert by_key["eik:555"]["org_id"] == "org-1"          # org-2's record is its own tenant
    assert eik["within_collection_groups"] == 1
    # informational only: legacy groups never make the canonical report dirty
    assert r["canonical"]["clean"] is True


def test_legacy_egn_is_masked_and_only_listed_fields_are_read():
    db = IndexDb()
    seed(db, "persons", {"id": "p1", "org_id": "o", "first_name": "Иван", "egn": "8001011234",
                         "iban": "BG00SECRET"},
         {"id": "p2", "org_id": "o", "first_name": "Иван", "egn": "8001011234"})
    r = report_of(db, include_legacy=True)
    text = json.dumps(r, ensure_ascii=False)
    assert "8001011234" not in text and "BG00SECRET" not in text
    assert "egn:80****34" in text


# ---------------------------------------------------------------- report from an export (NAS path)

def restored(databases, scanned=None):
    """An export the way w0_03c_export.js writes it."""
    return {"schema": uq.EXPORT_SCHEMA, "exported_at": NOW,
            "scanned_databases": sorted(scanned if scanned is not None else databases),
            "databases": {n: {"collections": c} for n, c in databases.items()}}


def test_report_from_a_multi_database_export():
    export = restored({
        "begwork_beg": {
            "md_tag": [tag(T_A, "спешно"), tag(T_A, "СПЕШНО")],
            "companies": [{"id": "c1", "org_id": "o", "eik": "1"}, {"id": "c2", "org_id": "o", "eik": "1"}],
        },
        "tenant_two": {"md_tag": [tag(T_B, "спешно")]},
    })
    rs = uq.report_set_from_export(export, now=NOW)
    assert rs["schema"] == uq.REPORT_SET_SCHEMA
    assert rs["verdict"] == uq.VERDICT_BLOCKED and rs["clean"] is False
    assert rs["evidence"]["complete"] is True
    by_db = {s["database"]: s for s in rs["summary"]}
    assert by_db["begwork_beg"]["blocked_indexes"] == ["md_tag.md_uq_name"]
    assert by_db["tenant_two"]["canonical_clean"] is True
    legacy = {x["key"]: x for x in by_db["begwork_beg"]["legacy"]}
    assert legacy["organization.eik"]["within_collection_groups"] == 1


def test_a_complete_export_without_duplicates_is_clean():
    rs = uq.report_set_from_export(restored({"begwork_beg": {"companies": [], "md_tag": []}},
                                            scanned=["begwork_beg", "begwork_system"]),
                                   expected_databases=["begwork_beg"],
                                   expected_collections=["begwork_beg.companies"], now=NOW)
    assert rs["verdict"] == uq.VERDICT_CLEAN and rs["clean"] is True


@pytest.mark.parametrize("export, why", [
    ({"databases": {}}, "no scanned database"),
    ({}, "no scanned database"),
    (restored({}, scanned=["begwork_beg", "begwork_system"]), "no database with a planned collection"),
    (restored({}, scanned=[]), "no scanned database"),
    (dict(restored({"begwork_beg": {"companies": []}}), schema="something/else"), "schema"),
    (restored({"begwork_beg": {"payments": [{"id": 1}]}}), "none of the planned collections"),
    (restored({"begwork_beg": {"companies": {"not": "a list"}}}), "not a list"),
    (restored({"begwork_beg": {"companies": []}}, scanned=["other"]), "not among the scanned"),
    (restored({"begwork_beg": {"companies": ["x", 1]}}), "not documents"),
])
def test_an_empty_or_malformed_export_is_incomplete_never_clean_or_blocked(export, why):
    rs = uq.report_set_from_export(export, now=NOW)
    assert rs["verdict"] == uq.VERDICT_INCOMPLETE
    assert rs["clean"] is False and rs["evidence"]["complete"] is False
    assert any(why in p for p in rs["evidence"]["problems"]), rs["evidence"]["problems"]


def test_a_restored_database_without_any_planned_collection_is_incomplete():
    # what w0_03c_export.js writes when begwork_beg was restored but holds none of the
    # planned collections: it is scanned, but absent from "databases"
    export = restored({"tenant_two": {"md_tag": []}}, scanned=["begwork_beg", "begwork_system", "tenant_two"])
    rs = uq.report_set_from_export(export, expected_databases=["begwork_beg"], now=NOW)
    assert rs["verdict"] == uq.VERDICT_INCOMPLETE
    assert rs["evidence"]["problems"] == ["expected database begwork_beg holds none of the planned collections"]


def test_an_expected_database_that_was_not_restored_is_incomplete():
    rs = uq.report_set_from_export(restored({"tenant_two": {"md_tag": []}}),
                                   expected_databases=["begwork_beg"], now=NOW)
    assert rs["verdict"] == uq.VERDICT_INCOMPLETE
    assert "expected database begwork_beg was not found in the restored copy" in rs["evidence"]["problems"]


def test_a_missing_expected_collection_is_incomplete_even_if_the_rest_has_duplicates():
    export = restored({"begwork_beg": {"md_tag": [tag(T_A, "x"), tag(T_A, "X")], "clients": []}})
    rs = uq.report_set_from_export(export, expected_databases=["begwork_beg"],
                                   expected_collections=["begwork_beg.companies", "begwork_beg.clients"],
                                   now=NOW)
    assert rs["verdict"] == uq.VERDICT_INCOMPLETE          # not BLOCKED: the evidence is partial
    assert rs["evidence"]["problems"] == ["expected collection begwork_beg.companies is missing from the export"]
    assert rs["summary"][0]["blocked_indexes"] == ["md_tag.md_uq_name"]    # still shown, for reading


def test_an_empty_but_present_collection_is_evidence():
    rs = uq.report_set_from_export(restored({"begwork_beg": {"companies": [], "items": []}}),
                                   expected_collections=["begwork_beg.items"], now=NOW)
    assert rs["verdict"] == uq.VERDICT_CLEAN


def test_the_export_plan_lists_every_field_a_key_or_partial_needs():
    plan = uq.export_plan()
    for key in uq.CANONICAL_KEYS:
        fields = plan["canonical"][key.collection]
        assert set(key.fields) <= set(fields)
        assert set((key.partial or {}).keys()) <= set(fields)
    assert "iban" not in json.dumps(plan)


def test_a_report_computed_from_the_export_plan_equals_the_live_one():
    db = IndexDb()
    seed(db, "md_organization", org(T_A, "Строй ЕООД", "123456789", aliases=["Строй"]),
         org(T_A, "Строй 2", "123456789"))
    seed(db, "companies", {"id": "c1", "org_id": "o", "name": "А", "eik": "1", "iban": "x"},
         {"id": "c2", "org_id": "o", "name": "Б", "eik": "1"})
    live = report_of(db, include_legacy=True)
    plan = uq.export_plan()

    def cut(doc, fields):
        out = {}
        for f in fields:
            head, _, rest = f.partition(".")
            if head not in doc:
                continue
            if rest and isinstance(doc[head], list):
                out[head] = [{rest: e[rest]} for e in doc[head] if isinstance(e, dict) and rest in e]
            elif not rest:
                out[head] = doc[head]
        return out

    colls = {}
    for c, fields in list(plan["canonical"].items()) + list(plan["legacy"].items()):
        if c in db.present:
            colls[c] = [cut(d, fields) for d in db[c].docs]
    exported = uq.report_from_export({"database": SCRATCH, "collections": colls}, now=NOW)
    assert exported["canonical"] == live["canonical"]
    assert exported["legacy_projection"] == live["legacy_projection"]


# ================================================================ the bootstrap

def test_dry_run_plans_every_index_and_creates_none():
    db = IndexDb()
    run_ = boot(db)
    assert run_["status"] == ib.STATUS_PLANNED
    assert len(run_["to_create"]) == 25
    assert not any(c.startswith("create_index") for c in db.all_calls())


def test_apply_builds_every_index_on_clean_data():
    db = IndexDb()
    seed(db, "md_organization", org(T_A, "Строй ЕООД", "123456789"))
    r = boot(db, apply=True, target=LOCAL)
    assert r["status"] == ib.STATUS_APPLIED, r.get("reason")
    assert len(r["created"]) == 25
    assert db.indexes("md_organization") == {"_id_", "md_uq_id", "md_uq_alias", "md_uq_identifier"}
    info = db["md_organization"].indexes["md_uq_identifier"]
    assert info["unique"] is True
    assert info["key"] == [("tenant_id", 1), ("identifiers.key", 1)]
    assert info["partialFilterExpression"] == {"status": "active", "identifiers.key": {"$exists": True}}
    assert r["report"]["canonical"]["clean"] is True


def test_apply_is_refused_on_duplicates_and_builds_nothing():
    db = IndexDb()
    seed(db, "md_organization", org(T_A, "Строй ЕООД", "123456789", entity_id="o1"),
         org(T_A, "Строй", "123456789", entity_id="o2"))
    before = db.snapshot()
    r = boot(db, apply=True, target=LOCAL)
    assert r["status"] == ib.STATUS_REFUSED_DUPLICATES
    assert "md_organization.md_uq_identifier" in r["reason"]
    assert not any(c.startswith("create_index") for c in db.all_calls())
    assert db.snapshot() == before                     # nothing merged, fixed or deleted
    g = index_of(r["report"], "md_organization", "md_uq_identifier")["blocking_groups"][0]
    assert sorted(x["id"] for x in g["records"]) == ["o1", "o2"]


def test_one_blocked_index_refuses_the_whole_run_not_just_that_index():
    db = IndexDb()
    seed(db, "md_tag", tag(T_A, "x"), tag(T_A, "X"))
    r = boot(db, apply=True, target=LOCAL)
    assert r["status"] == ib.STATUS_REFUSED_DUPLICATES
    assert all(db.indexes(c) <= {"_id_"} for c in db.collections)


def test_tenant_isolation_same_values_in_two_tenants_build_fine():
    db = IndexDb()
    seed(db, "md_organization", org(T_A, "Строй ЕООД", "123456789", aliases=["Строй"]),
         org(T_B, "Строй ЕООД", "123456789", aliases=["Строй"]))
    assert boot(db, apply=True, target=LOCAL)["status"] == ib.STATUS_APPLIED
    # and the index keeps them apart afterwards: the same EIK again in tenant B is refused,
    # in a third tenant it is accepted
    with pytest.raises(DuplicateKeyError):
        run(db["md_organization"].insert_one(org(T_B, "Копие", "123456789")))
    run(db["md_organization"].insert_one(org("tenant-c", "Строй ЕООД", "123456789")))


def test_tenant_isolation_a_dirty_tenant_blocks_and_is_the_only_one_named():
    db = IndexDb()
    seed(db, "md_organization", org(T_A, "Строй ЕООД", "123456789", entity_id="a1"),
         org(T_B, "Бетон", "555", entity_id="b1"), org(T_B, "Бетон АД", "555", entity_id="b2"))
    r = boot(db, apply=True, target=LOCAL)
    assert r["status"] == ib.STATUS_REFUSED_DUPLICATES
    groups = index_of(r["report"], "md_organization", "md_uq_identifier")["blocking_groups"]
    assert [g["tenant_id"] for g in groups] == [T_B]
    assert {x["id"] for g in groups for x in g["records"]} == {"b1", "b2"}


def test_rerun_is_already_applied_and_changes_nothing():
    db = IndexDb()
    first = boot(db, apply=True, target=LOCAL)
    assert first["status"] == ib.STATUS_APPLIED
    calls_before = len([c for c in db.all_calls() if c.startswith(("create_index", "drop_index"))])
    again = boot(db, apply=True, target=LOCAL)
    assert again["status"] == ib.STATUS_ALREADY_APPLIED
    assert again["created"] == [] and again["rollback_plan"] == []
    assert len(again["kept"]) == 25
    calls_after = len([c for c in db.all_calls() if c.startswith(("create_index", "drop_index"))])
    assert calls_after == calls_before
    assert boot(db)["status"] == ib.STATUS_PLANNED and boot(db)["to_create"] == []


def test_a_partial_earlier_run_is_completed_not_duplicated():
    db = IndexDb()
    key = [k for k in uq.CANONICAL_KEYS if k.collection == "md_tag" and k.name == "md_uq_name"][0]
    spec = key.index_spec()
    run(db["md_tag"].create_index(spec["keys"], name=key.name, unique=True,
                                  partialFilterExpression=spec["partialFilterExpression"]))
    r = boot(db, apply=True, target=LOCAL)
    assert r["status"] == ib.STATUS_APPLIED
    assert "md_tag.md_uq_name" in r["kept"]
    assert "md_tag.md_uq_name" not in r["created"]
    assert len(r["created"]) == 24
    assert {e["index"] for e in r["rollback_plan"]} >= {"md_uq_id"}
    assert ("md_tag", "md_uq_name") not in {(e["collection"], e["index"]) for e in r["rollback_plan"]}


def test_a_same_named_index_with_another_definition_is_a_conflict():
    db = IndexDb()
    run(db["md_tag"].create_index([("tenant_id", 1), ("normalized_name", 1)], name="md_uq_name",
                                  unique=True))     # no partial filter: archived tags would collide
    r = boot(db, apply=True, target=LOCAL)
    assert r["status"] == ib.STATUS_REFUSED_CONFLICT
    assert "md_tag.md_uq_name exists with a different definition" in r["reason"]
    assert db.indexes("md_tag") == {"_id_", "md_uq_name"}       # nothing dropped to make room
    assert not any(c.startswith("create_index:md_uq_id") for c in db.all_calls())


def test_the_same_definition_under_another_name_is_a_conflict():
    db = IndexDb()
    run(db["md_unit"].create_index([("tenant_id", 1), ("normalized_name", 1)], name="handmade",
                                   unique=True, partialFilterExpression={"status": "active"}))
    r = boot(db, apply=True, target=LOCAL)
    assert r["status"] == ib.STATUS_REFUSED_CONFLICT
    assert "handmade" in r["reason"]


def test_a_failed_build_drops_what_this_run_created():
    db = IndexDb()
    db.fail_on.add("md_uq_open_pending")          # the last index in plan order
    r = boot(db, apply=True, target=LOCAL)
    assert r["status"] == ib.STATUS_FAILED_ROLLED_BACK
    assert len(r["undone"]) == 24 and all(u["result"] == "dropped" for u in r["undone"])
    assert all(db.indexes(c) <= {"_id_"} for c in db.collections)
    assert r["rollback_plan"] == []


def test_a_failed_build_leaves_indexes_that_existed_before():
    db = IndexDb()
    key = [k for k in uq.CANONICAL_KEYS if k.collection == "md_tag" and k.name == "md_uq_id"][0]
    run(db["md_tag"].create_index(key.index_spec()["keys"], name=key.name, unique=True))
    run(db["md_tag"].create_index([("display_name", 1)], name="unrelated"))
    db.fail_on.add("md_uq_open_pending")
    r = boot(db, apply=True, target=LOCAL)
    assert r["status"] == ib.STATUS_FAILED_ROLLED_BACK
    assert db.indexes("md_tag") == {"_id_", "md_uq_id", "unrelated"}


def test_a_duplicate_written_after_the_report_fails_the_build_and_is_undone():
    db = IndexDb()
    seed(db, PENDING_COLLECTION, pending(T_A, "unit", "м2", pid="p1"))
    original = uq.duplicate_report

    async def report_then_race(*a, **kw):
        out = await original(*a, **kw)
        seed(db, PENDING_COLLECTION, pending(T_A, "unit", "м2", pid="p2"))   # written after the read
        return out

    ib.duplicate_report = report_then_race
    try:
        r = boot(db, apply=True, target=LOCAL)
    finally:
        ib.duplicate_report = original
    assert r["status"] == ib.STATUS_FAILED_ROLLED_BACK
    assert "md_uq_open_pending" in r["reason"]
    assert all(db.indexes(c) <= {"_id_"} for c in db.collections)


def test_an_undo_that_itself_fails_is_reported_as_such():
    db = IndexDb()
    db.fail_on.add("md_uq_open_pending")
    db.fail_drop.add("md_uq_id")
    r = boot(db, apply=True, target=LOCAL)
    assert r["status"] == ib.STATUS_ROLLBACK_FAILED
    assert any(u["result"].startswith("failed") for u in r["undone"])


# ---------------------------------------------------------------- the target guard

@pytest.mark.parametrize("target, why", [
    ({"hosts": ["cluster0.abcde.mongodb.net"], "scheme": "mongodb+srv", "confirm_database": SCRATCH}, "scheme"),
    ({"hosts": ["cluster0-shard-00-00.abcde.mongodb.net"], "scheme": "mongodb", "confirm_database": SCRATCH}, "host"),
    ({"hosts": ["192.168.1.112"], "scheme": "mongodb", "confirm_database": SCRATCH}, "host"),
    ({"hosts": ["localhost", "10.0.0.5"], "scheme": "mongodb", "confirm_database": SCRATCH}, "host"),
    ({"hosts": [], "scheme": "mongodb", "confirm_database": SCRATCH}, "host"),
    ({"hosts": ["localhost"], "scheme": "mongodb", "confirm_database": None}, "confirmation"),
    ({"hosts": ["localhost"], "scheme": "mongodb", "confirm_database": "w003c_other"}, "confirmation"),
    (None, "scheme"),
])
def test_apply_refuses_any_target_but_a_confirmed_local_scratch_database(target, why):
    db = IndexDb()
    r = boot(db, apply=True, target=target)
    assert r["status"] == ib.STATUS_REFUSED_TARGET
    assert why in r["reason"]
    assert db.all_calls() == []               # refused before the first read


@pytest.mark.parametrize("name", ["begwork", "begwork_beg", "begwork_system", "BEGWORK_copy",
                                  "begwork_restore_test", ""])
def test_production_database_names_are_refused_even_on_localhost(name):
    db = IndexDb()
    r = run(ib.bootstrap(db, database=name, apply=True, env=NO_ENV,
                         target={"hosts": ["localhost"], "scheme": "mongodb", "confirm_database": name}))
    assert r["status"] == ib.STATUS_REFUSED_TARGET
    assert db.all_calls() == []


def test_the_configured_production_names_are_refused_too():
    env = {"DB_NAME": "firma_prod", "BEG_SYSTEM_DB": "sys_prod"}
    for name in ("firma_prod", "sys_prod"):
        with pytest.raises(ib.TargetRefused):
            ib.check_target(database=name, hosts=["localhost"], scheme="mongodb",
                            confirm_database=name, env=env)


def test_local_hosts_are_accepted_in_every_spelling():
    for host in ("localhost", "LOCALHOST", "127.0.0.1", "[::1]", "::1"):
        ib.check_target(database=SCRATCH, hosts=[host], scheme="mongodb",
                        confirm_database=SCRATCH, env=NO_ENV)


def test_a_dry_run_needs_no_target_because_it_only_reads():
    db = IndexDb()
    assert boot(db)["status"] == ib.STATUS_PLANNED
    assert set(db.all_calls()) <= {"find", "index_information"}


# ---------------------------------------------------------------- rollback: the run ledger decides

def ledger_of(db, run_id):
    return [d for d in db[ib.LEDGER_COLLECTION].docs if d["_id"] == run_id][0]


def undo(db, applied, plan="saved", **kw):
    kw.setdefault("target", LOCAL)
    kw.setdefault("env", NO_ENV)
    if plan == "saved":
        plan = applied["rollback_plan"]
    return run(ib.rollback(db, applied["run_id"], database=SCRATCH, plan=plan, **kw))


def md_tag_key(name):
    return [k for k in uq.CANONICAL_KEYS if k.collection == "md_tag" and k.name == name][0]


def prebuild(db, key):
    spec = key.index_spec()
    opts = {"partialFilterExpression": spec["partialFilterExpression"]} if "partialFilterExpression" in spec else {}
    run(db[key.collection].create_index(spec["keys"], name=key.name, unique=True, **opts))


def test_apply_records_every_created_index_in_the_run_ledger():
    db = IndexDb()
    applied = boot(db, apply=True, target=LOCAL)
    entry = ledger_of(db, applied["run_id"])
    assert entry["status"] == ib.RUN_APPLIED and entry["database"] == SCRATCH
    assert len(entry["created"]) == 25
    assert {(c["collection"], c["index"]) for c in entry["created"]} == \
        {(e["collection"], e["index"]) for e in applied["rollback_plan"]}


def test_only_apply_writes_the_ledger():
    db = IndexDb()
    boot(db)                                                             # dry run
    seed(db, "md_tag", tag(T_A, "x"), tag(T_A, "X"))
    boot(db, apply=True, target=LOCAL)                                   # refused: duplicates
    assert ib.LEDGER_COLLECTION not in db.collections


def test_rollback_drops_exactly_what_the_run_created():
    db = IndexDb()
    prebuild(db, md_tag_key("md_uq_id"))
    run(db["md_tag"].create_index([("display_name", 1)], name="unrelated"))
    applied = boot(db, apply=True, target=LOCAL)
    assert applied["status"] == ib.STATUS_APPLIED
    assert len(applied["rollback_plan"]) == 24
    assert all(e["command"] == "db.getCollection(%r).dropIndex(%r)" % (e["collection"], e["index"])
               for e in applied["rollback_plan"])
    json.dumps(applied)                                   # the CLI saves it as JSON

    rb = undo(db, applied)
    assert rb["status"] == ib.STATUS_ROLLED_BACK
    assert sum(1 for x in rb["results"] if x["result"] == "dropped") == 24
    assert db.indexes("md_tag") == {"_id_", "md_uq_id", "unrelated"}     # what existed before stays
    assert db.indexes("md_organization") == {"_id_"}
    entry = ledger_of(db, applied["run_id"])
    assert entry["status"] == ib.RUN_ROLLED_BACK and entry["created"] == [] and len(entry["released"]) == 24


def test_a_saved_plan_with_another_planned_name_is_refused():
    """Review of 25394418: an APPLIED JSON could name a planned md_uq_* index the run did NOT
    create (here one that existed before and was only kept). The ledger now decides; the
    edited plan is refused and nothing is dropped."""
    db = IndexDb()
    prebuild(db, md_tag_key("md_uq_id"))                  # not this run's index
    applied = boot(db, apply=True, target=LOCAL)
    forged = applied["rollback_plan"] + [{"collection": "md_tag", "index": "md_uq_id",
                                          "command": "db.getCollection('md_tag').dropIndex('md_uq_id')"}]
    before = {c: db.indexes(c) for c in db.collections}
    rb = undo(db, applied, plan=forged)
    assert rb["status"] == ib.STATUS_REFUSED_TARGET
    assert "does not match" in rb["reason"]
    assert {c: db.indexes(c) for c in db.collections} == before
    assert ledger_of(db, applied["run_id"])["status"] == ib.RUN_APPLIED


def test_a_saved_plan_with_a_name_removed_or_foreign_is_refused():
    db = IndexDb()
    run(db["users"].create_index([("email", 1)], name="email_1", unique=True))
    applied = boot(db, apply=True, target=LOCAL)
    for forged in (applied["rollback_plan"][1:],
                   applied["rollback_plan"] + [{"collection": "users", "index": "email_1"}],
                   [{"collection": "users", "index": "email_1"}]):
        rb = undo(db, applied, plan=forged)
        assert rb["status"] == ib.STATUS_REFUSED_TARGET
    assert db.indexes("users") == {"_id_", "email_1"}
    assert len([c for c in db.collections if "md_uq_id" in db.indexes(c)]) == 9


def test_a_run_id_that_is_not_in_the_ledger_is_refused():
    db = IndexDb()
    applied = boot(db, apply=True, target=LOCAL)
    rb = run(ib.rollback(db, "0" * 32, database=SCRATCH, target=LOCAL, env=NO_ENV))
    assert rb["status"] == ib.STATUS_REFUSED_TARGET and "not in the run ledger" in rb["reason"]
    assert "md_uq_id" in db.indexes("md_organization")
    other = dict(applied, run_id="0" * 32)
    assert undo(db, other)["status"] == ib.STATUS_REFUSED_TARGET


def test_a_ledger_entry_of_another_database_is_refused():
    """A scratch database copied or restored under another name carries the ledger of
    the original; its runs did not build anything in THIS database."""
    db = IndexDb()
    applied = boot(db, apply=True, target=LOCAL)
    ledger_of(db, applied["run_id"])["database"] = "w003c_original"
    rb = undo(db, applied)
    assert rb["status"] == ib.STATUS_REFUSED_TARGET and "not in the run ledger" in rb["reason"]
    assert "md_uq_id" in db.indexes("md_organization")


def test_without_a_saved_plan_the_ledger_alone_is_enough():
    db = IndexDb()
    applied = boot(db, apply=True, target=LOCAL)
    assert undo(db, applied, plan=None)["status"] == ib.STATUS_ROLLED_BACK
    assert all(db.indexes(c) <= {"_id_"} for c in db.collections if c != ib.LEDGER_COLLECTION)


def test_rollback_twice_is_safe():
    db = IndexDb()
    applied = boot(db, apply=True, target=LOCAL)
    undo(db, applied)
    again = undo(db, applied)
    assert again["status"] == ib.STATUS_ROLLED_BACK
    assert again["results"] == [] and "nothing to undo" in again["reason"]


def test_an_index_rebuilt_by_a_later_run_is_released_not_dropped():
    """Run A built md_tag.md_uq_name; it was dropped; run B built it again. The instance
    that exists now is B's: undoing A must leave it, undoing B must drop it."""
    db = IndexDb()
    a = boot(db, apply=True, target=LOCAL)
    run(db["md_tag"].drop_index("md_uq_name"))
    b = boot(db, apply=True, target=LOCAL)
    assert b["created"] == ["md_tag.md_uq_name"]

    rb_a = undo(db, a)
    assert rb_a["status"] == ib.STATUS_ROLLED_BACK
    released = [r for r in rb_a["results"] if r["index"] == "md_tag.md_uq_name"][0]
    assert released["result"].startswith("released: rebuilt later by run %s" % b["run_id"])
    assert "md_uq_name" in db.indexes("md_tag")
    assert sum(1 for r in rb_a["results"] if r["result"] == "dropped") == 24

    rb_b = undo(db, b)
    assert rb_b["results"] == [{"index": "md_tag.md_uq_name", "result": "dropped"}]
    assert "md_uq_name" not in db.indexes("md_tag")


def test_two_runs_that_raced_on_the_same_indexes_drop_them_exactly_once():
    """A concurrent apply: run B checked before run A's indexes existed, so its
    createIndex calls were no-ops on A's indexes (MongoDB accepts an identical re-create).
    Both ledgers claim all 25. The later run owns them: undoing A drops nothing,
    undoing B drops each exactly once."""
    db = IndexDb()
    a = boot(db, apply=True, target=LOCAL)
    original = ib._index_information

    async def saw_nothing_yet(db_, collection, present):
        return {}

    ib._index_information = saw_nothing_yet
    try:
        b = boot(db, apply=True, target=LOCAL)
    finally:
        ib._index_information = original
    assert b["status"] == ib.STATUS_APPLIED and len(b["created"]) == 25

    rb_a = undo(db, a)
    assert rb_a["status"] == ib.STATUS_ROLLED_BACK
    assert all(r["result"].startswith("released: rebuilt later by run %s" % b["run_id"]) for r in rb_a["results"])
    assert len([c for c in db.collections if "md_uq_id" in db.indexes(c)]) == 9
    rb_b = undo(db, b)
    assert sum(1 for r in rb_b["results"] if r["result"] == "dropped") == 25
    assert all(db.indexes(c) <= {"_id_"} for c in db.collections if c != ib.LEDGER_COLLECTION)


def test_a_changed_definition_is_kept_and_reported():
    db = IndexDb()
    applied = boot(db, apply=True, target=LOCAL)
    run(db["md_unit"].drop_index("md_uq_name"))
    run(db["md_unit"].create_index([("tenant_id", 1), ("normalized_name", 1)], name="md_uq_name", unique=True))
    rb = undo(db, applied)
    assert rb["status"] == ib.STATUS_ROLLBACK_FAILED
    assert [r for r in rb["results"] if r["index"] == "md_unit.md_uq_name"][0]["result"] == \
        "refused: its definition changed since the run"
    assert "md_uq_name" in db.indexes("md_unit")
    entry = ledger_of(db, applied["run_id"])
    assert entry["status"] == ib.RUN_ROLLBACK_INCOMPLETE
    assert entry["created"] == [{"collection": "md_unit", "index": "md_uq_name"}]


def test_limit_an_index_recreated_outside_the_tool_cannot_be_told_apart():
    """THE HONEST BOUNDARY. MongoDB keeps no identity or creation time for an index. If
    an index the run created is dropped and re-created by hand with the same name and
    definition — not through the bootstrap, so not in the ledger — rolling the run back
    drops the hand-made one. The ledger cannot see it; nothing in the server can."""
    db = IndexDb()
    applied = boot(db, apply=True, target=LOCAL)
    run(db["md_tag"].drop_index("md_uq_name"))
    prebuild(db, md_tag_key("md_uq_name"))                # by hand, outside the tool
    rb = undo(db, applied)
    assert [r for r in rb["results"] if r["index"] == "md_tag.md_uq_name"][0]["result"] == "dropped"
    assert "md_uq_name" not in db.indexes("md_tag")


def test_a_ledger_that_cannot_be_opened_builds_nothing():
    db = IndexDb()
    original = IndexCollection.insert_one

    async def refuse(self, doc):
        if self.name == ib.LEDGER_COLLECTION:
            raise OperationFailure("not authorized")
        return await original(self, doc)

    IndexCollection.insert_one = refuse
    try:
        r = boot(db, apply=True, target=LOCAL)
    finally:
        IndexCollection.insert_one = original
    assert r["status"] == ib.STATUS_FAILED_ROLLED_BACK and "nothing was built" in r["reason"]
    assert not any(c.startswith("create_index") for c in db.all_calls())


def test_a_ledger_that_stops_recording_undoes_the_build():
    db = IndexDb()
    db.fail_update.add(ib.LEDGER_COLLECTION)
    r = boot(db, apply=True, target=LOCAL)
    assert r["status"] == ib.STATUS_FAILED_ROLLED_BACK
    assert all(db.indexes(c) <= {"_id_"} for c in db.collections)


def test_a_failed_build_leaves_a_ledger_with_nothing_claimed():
    db = IndexDb()
    db.fail_on.add("md_uq_open_pending")
    r = boot(db, apply=True, target=LOCAL)
    entry = ledger_of(db, r["run_id"])
    assert entry["status"] == ib.RUN_FAILED and entry["created"] == []
    assert len(entry["undone"]) == 24


def test_rollback_is_guarded_like_apply():
    db = IndexDb()
    applied = boot(db, apply=True, target=LOCAL)
    atlas = {"hosts": ["cluster0.abcde.mongodb.net"], "scheme": "mongodb+srv", "confirm_database": SCRATCH}
    rb = undo(db, applied, target=atlas)
    assert rb["status"] == ib.STATUS_REFUSED_TARGET
    assert "md_uq_id" in db.indexes("md_organization")


def test_after_rollback_a_clean_rerun_builds_again():
    db = IndexDb()
    applied = boot(db, apply=True, target=LOCAL)
    undo(db, applied)
    again = boot(db, apply=True, target=LOCAL)
    assert again["status"] == ib.STATUS_APPLIED and len(again["created"]) == 25


# ---------------------------------------------------------------- after apply: the database enforces it

def test_after_apply_the_index_refuses_what_the_report_would_flag():
    db = IndexDb()
    assert boot(db, apply=True, target=LOCAL)["status"] == ib.STATUS_APPLIED
    run(db[PENDING_COLLECTION].insert_one(pending(T_A, "unit", "м2", pid="p1")))
    with pytest.raises(DuplicateKeyError):
        run(db[PENDING_COLLECTION].insert_one(pending(T_A, "unit", "м2", pid="p2")))
    run(db[PENDING_COLLECTION].insert_one(pending(T_A, "unit", "м2", status="resolved", pid="p3")))
    run(db[PENDING_COLLECTION].insert_one(pending(T_B, "unit", "м2", pid="p4")))

    run(db["md_tag"].insert_one(tag(T_A, "спешно")))
    run(db["md_tag"].insert_one(tag(T_A, "Спешно", status="archived")))
    with pytest.raises(DuplicateKeyError):
        run(db["md_tag"].insert_one(tag(T_A, "СПЕШНО")))


# ================================================================ identifiers on the canonical model

def test_identifier_key_is_the_normalized_value_with_its_kind():
    assert models.identifier_key("eik", " 123 456-789 ") == "eik:123456789"
    assert models.identifier_key("vat", "bg123456789") == "vat:BG123456789"
    assert models.identifier_key("eik", "  ") == ""
    ident = new_identifier("organization", "eik", " 123 456 789 ")
    assert ident == {"kind": "eik", "value": "123 456 789", "key": "eik:123456789"}


def test_identifier_kinds_are_per_type():
    with pytest.raises(MasterDataInvalid):
        new_identifier("organization", "egn", "8001011234")
    with pytest.raises(MasterDataInvalid):
        new_identifier("tag", "sku", "1")
    with pytest.raises(MasterDataInvalid):
        new_identifier("item", "sku", " - ")


def test_validate_entity_refuses_a_forged_or_foreign_identifier():
    doc = org(T_A, "Строй ЕООД", "123456789")
    models.validate_entity(doc)
    forged = copy.deepcopy(doc)
    forged["identifiers"][0]["key"] = "eik:999"
    with pytest.raises(MasterDataInvalid):
        models.validate_entity(forged)
    foreign = copy.deepcopy(doc)
    foreign["identifiers"] = [{"kind": "egn", "value": "8001011234", "key": "egn:8001011234"}]
    with pytest.raises(MasterDataInvalid):
        models.validate_entity(foreign)
    not_a_list = copy.deepcopy(doc)
    not_a_list["identifiers"] = {"kind": "eik"}
    with pytest.raises(MasterDataInvalid):
        models.validate_entity(not_a_list)


def test_records_without_identifiers_stay_valid():
    doc = build_entity(tenant_id=T_A, entity_type="organization", display_name="Стара фирма", now=NOW)
    assert "identifiers" not in doc
    models.validate_entity(doc)


# ================================================================ the CLI

from scripts import w0_03c_master_data_uniqueness as cli  # noqa: E402


@pytest.mark.parametrize("url, scheme, hosts", [
    ("mongodb://localhost:27017", "mongodb", ["localhost"]),
    ("mongodb://user:p%40ss@127.0.0.1:27017/db?authSource=admin", "mongodb", ["127.0.0.1"]),
    ("mongodb://[::1]:27017", "mongodb", ["::1"]),
    ("mongodb://a:1,b:2,localhost:3/x", "mongodb", ["a", "b", "localhost"]),
    ("mongodb+srv://u:secret@cluster0.abcde.mongodb.net/begwork", "mongodb+srv", ["cluster0.abcde.mongodb.net"]),
])
def test_cli_parses_urls_without_a_driver(url, scheme, hosts):
    assert cli.parse_mongo_url(url) == (scheme, hosts)


@pytest.mark.parametrize("argv", [
    ["bootstrap", "--mongo-url", "mongodb+srv://u:secret@cluster0.abcde.mongodb.net", "--db", SCRATCH],
    ["bootstrap", "--mongo-url", "mongodb://192.168.1.112:27017", "--db", SCRATCH],
    ["bootstrap", "--mongo-url", "mongodb://localhost:27017", "--db", SCRATCH, "--apply"],
    ["bootstrap", "--mongo-url", "mongodb://localhost:27017", "--db", "begwork_beg", "--apply",
     "--confirm-db", "begwork_beg"],
    ["report", "--mongo-url", "mongodb://cluster0-shard-00-00.abcde.mongodb.net:27017", "--db", "x"],
    ["rollback", "--mongo-url", "mongodb://localhost:27017", "--db", SCRATCH, "--plan", "x.json",
     "--confirm-db", "other"],
])
def test_cli_refuses_before_opening_any_connection(argv, monkeypatch, capsys):
    def no_connection(*a, **kw):
        raise AssertionError("a connection was attempted")
    monkeypatch.setattr(cli, "_connect", no_connection)
    assert cli.main(argv) == 2
    err = capsys.readouterr().err
    assert "refused" in err and "secret" not in err


def test_cli_report_from_export_exit_codes_and_masking(tmp_path, capsys):
    person = build_entity(tenant_id=T_A, entity_type="person", display_name="Иван", now=NOW)
    person["identifiers"] = [new_identifier("person", "egn", "8001011234")]
    export = restored({"begwork_beg": {
        "md_person": [person], "persons": [{"id": "p", "org_id": "o", "egn": "8001011234"},
                                           {"id": "q", "org_id": "o", "egn": "8001011234"}]}})
    src, out = tmp_path / "export.json", tmp_path / "report.json"
    args = ["report", "--from-export", str(src), "--out", str(out), "--expect-db", "begwork_beg",
            "--expect-collection", "begwork_beg.persons"]
    src.write_text(json.dumps(export, ensure_ascii=False), encoding="utf-8")
    assert cli.main(args) == 0
    err = capsys.readouterr().err
    assert "verdict=CLEAN" in err and "8001011234" not in err
    assert "8001011234" not in out.read_text(encoding="utf-8")

    dup = copy.deepcopy(person)
    dup["id"] = "p-2"
    export["databases"]["begwork_beg"]["collections"]["md_person"].append(dup)
    src.write_text(json.dumps(export, ensure_ascii=False), encoding="utf-8")
    assert cli.main(args) == 1
    err = capsys.readouterr().err
    assert "md_person.md_uq_identifier" in err and "verdict=BLOCKED" in err

    src.write_text("{broken", encoding="utf-8")
    assert cli.main(args) == 2


@pytest.mark.parametrize("export, extra", [
    ({"databases": {}}, []),
    (restored({}, scanned=["begwork_beg", "begwork_system"]), ["--expect-db", "begwork_beg"]),
    (restored({"tenant_two": {"md_tag": []}}), ["--expect-db", "begwork_beg"]),
    (restored({"begwork_beg": {"clients": []}}), ["--expect-collection", "begwork_beg.companies"]),
])
def test_cli_an_incomplete_export_exits_5_not_1(export, extra, tmp_path, capsys):
    src, out = tmp_path / "export.json", tmp_path / "report.json"
    src.write_text(json.dumps(export), encoding="utf-8")
    assert cli.main(["report", "--from-export", str(src), "--out", str(out)] + extra) == 5
    err = capsys.readouterr().err
    assert "verdict=INCOMPLETE" in err and "not evidence:" in err
    assert json.loads(out.read_text(encoding="utf-8"))["verdict"] == "INCOMPLETE"


def test_cli_expectations_are_for_exports_only(capsys):
    assert cli.main(["report", "--mongo-url", "mongodb://localhost:27017", "--db", SCRATCH,
                     "--expect-db", "x"]) == 2


def test_cli_rollback_needs_an_applied_run_of_the_same_database(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_connect", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("connected")))
    plan = tmp_path / "run.json"
    for saved in ({"status": ib.STATUS_PLANNED, "database": SCRATCH, "run_id": "r", "rollback_plan": []},
                  {"status": ib.STATUS_APPLIED, "database": "w003c_other", "run_id": "r", "rollback_plan": []},
                  {"status": ib.STATUS_APPLIED, "database": SCRATCH, "rollback_plan": []}):
        plan.write_text(json.dumps(saved), encoding="utf-8")
        assert cli.main(["rollback", "--mongo-url", "mongodb://localhost:27017", "--db", SCRATCH,
                         "--plan", str(plan), "--confirm-db", SCRATCH]) == 2


def test_cli_rollback_passes_the_run_id_and_the_saved_plan_to_the_ledger_check(tmp_path, monkeypatch):
    db = IndexDb()
    applied = boot(db, apply=True, target=LOCAL)

    class Client:
        def close(self):
            pass

    monkeypatch.setattr(cli, "_connect", lambda url, name: (Client(), db))
    for var in ("DB_NAME", "BEG_SYSTEM_DB"):
        monkeypatch.delenv(var, raising=False)
    plan = tmp_path / "run.json"
    forged = dict(applied, rollback_plan=applied["rollback_plan"] + [{"collection": "md_tag", "index": "md_uq_x"}])
    plan.write_text(json.dumps(forged), encoding="utf-8")
    base = ["rollback", "--mongo-url", "mongodb://localhost:27017", "--db", SCRATCH, "--plan", str(plan),
            "--confirm-db", SCRATCH]
    assert cli.main(base) == 2
    assert "md_uq_id" in db.indexes("md_organization")
    plan.write_text(json.dumps(applied), encoding="utf-8")
    assert cli.main(base) == 0
    assert db.indexes("md_organization") == {"_id_"}


def test_cli_exit_code_for_every_status():
    statuses = {v for k, v in vars(ib).items() if k.startswith("STATUS_")}
    assert statuses == set(cli.EXIT_BY_STATUS)
