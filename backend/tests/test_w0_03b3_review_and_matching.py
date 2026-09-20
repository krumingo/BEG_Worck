"""
W0-03B3 + minimal W0-03C — human review, normalization, matching.

The promises under test:
  * a **person** decides; an automated caller cannot approve;
  * an exact match is shown, never applied;
  * reject leaves Master Data untouched;
  * two simultaneous approvals produce **one** canonical record, not two;
  * every decision carries exactly one canonical W0-04 AuditEvent;
  * off is inert and shadow changes no official data.

Pure logic plus spies — no database, no live application.

Run:  pytest tests/test_w0_03b3_review_and_matching.py -v --noconftest
"""
import asyncio

import pytest

from app.master_data import matching, models, review
from app.master_data.deps import (
    MODE_ENFORCE,
    MODE_OFF,
    MODE_SHADOW,
    MasterDataConfigError,
    MasterDataTenantContextMissing,
)
from app.master_data.models import MasterDataInvalid
from app.master_data.normalize import (
    NORMALIZATION_VERSION,
    normalize_identifier,
    normalize_name,
    strip_legal_suffix,
)
from app.master_data.pending import (
    PENDING_COLLECTION,
    SOURCE_OCR,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_RESOLVED,
    STATUS_RESOLVING,
    build_pending,
)
from app.master_data.repository import MasterDataRepository
from app.master_data.review import approve, list_pending, reject, suggest_matches
from app.master_data.service import MasterDataAuditFailed, MasterDataRefused, create_entity


def run(coro):
    return asyncio.run(coro)


class Result:
    def __init__(self, modified, upserted_id=None):
        self.modified_count = modified
        self.upserted_id = upserted_id


class Cursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return self._docs[:length] if length else list(self._docs)


class SpyCollection:
    def __init__(self, fail_on_insert=False):
        self.docs = []
        self.queries = []
        self.fail_on_insert = fail_on_insert

    def _match(self, query):
        return [d for d in self.docs if _doc_matches(d, query)]

    async def insert_one(self, doc):
        if self.fail_on_insert:
            raise RuntimeError("simulated storage failure")
        self.docs.append(dict(doc))

    async def find_one(self, query, projection=None, sort=None):
        self.queries.append(query)
        found = self._match(query)
        if not found:
            return None
        return found[-1] if sort else found[0]

    def find(self, query, projection=None):
        self.queries.append(query)
        return Cursor(self._match(query))

    async def update_one(self, query, update, upsert=False):
        found = self._match(query)
        upserted = None
        if not found:
            if not upsert:
                return Result(0)
            if self.fail_on_insert:
                raise RuntimeError("simulated storage failure")
            # Mongo builds the new document from the operators, and reports it
            # as upserted rather than modified.
            doc = dict(update.get("$setOnInsert", {}))
            self.docs.append(doc)
            found = [doc]
            upserted = doc.get("id", True)
        doc = found[0]
        for k, v in update.get("$set", {}).items():
            doc[k] = v
        for k, v in update.get("$push", {}).items():
            doc.setdefault(k, []).append(v)
        for k, v in update.get("$inc", {}).items():
            doc[k] = doc.get(k, 0) + v
        return Result(0 if upserted is not None else 1, upserted_id=upserted)

    @property
    def inserted(self):
        return self.docs


def _doc_matches(doc, query):
    for key, value in (query or {}).items():
        if key == "$or":
            if not any(_doc_matches(doc, clause) for clause in value):
                return False
            continue
        if not _field_match(doc, key, value):
            return False
    return True


def _field_match(doc, key, value):
    if isinstance(value, dict) and "$regex" in value:
        import re
        flags = re.IGNORECASE if "i" in (value.get("$options") or "") else 0
        pattern = re.compile(value["$regex"], flags)
        if "." in key:
            head, tail = key.split(".", 1)
            return any(isinstance(i, dict) and isinstance(i.get(tail), str)
                       and pattern.search(i[tail])
                       for i in (doc.get(head) or []))
        target = doc.get(key)
        return isinstance(target, str) and bool(pattern.search(target))
    if isinstance(value, dict) and "$ne" in value:
        # Mongo semantics: for a dotted path, matches when NO element equals
        # the value — including a document with no such field at all.
        return not _field_match(doc, key, value["$ne"])
    if "." in key:                      # e.g. aliases.normalized
        head, tail = key.split(".", 1)
        items = doc.get(head) or []
        return any(isinstance(i, dict) and i.get(tail) == value for i in items)
    return doc.get(key) == value


class SpyDb:
    def __init__(self, failing=()):
        self.collections = {}
        self.failing = set(failing)

    def __getitem__(self, name):
        if name not in self.collections:
            self.collections[name] = SpyCollection(fail_on_insert=name in self.failing)
        return self.collections[name]

    def audit(self):
        return self.collections.get("audit_events")

    def master(self, entity_type):
        return self.collections.get("md_" + entity_type)


class Ctx:
    enforced = True

    def __init__(self, tenant_id="tenant-a", user_id="office-1", db=None):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self._db = db if db is not None else SpyDb()

    async def db(self, require_operational: bool = False):
        return self._db


class ActorlessCtx(Ctx):
    def __init__(self):
        super().__init__(user_id=None)


class LegacyCtx:
    enforced = False
    tenant_id = "org-legacy"


def seeded(tenant="tenant-a", raw="Баумит леп. бяло 25", entity_type=models.ENTITY_ITEM):
    """A tenant with one pending row waiting for review."""
    db = SpyDb()
    ctx = Ctx(tenant, db=db)
    repo = MasterDataRepository(tenant, db=db)
    row = build_pending(tenant_id=tenant, entity_type=entity_type, raw_value=raw,
                        source_channel=SOURCE_OCR, created_by="ocr-bot")
    db[PENDING_COLLECTION].docs.append(dict(row))
    return db, ctx, repo, row


# ================================================================ normalization
@pytest.mark.parametrize("a,b", [
    ("Баумит ЕООД", "  баумит   еоод "),
    ("СТРОЙ ООД", "строй ООД"),
    ("Фирма Е.О.О.Д.", "фирма еоод"),
    ('Фирма "Име" ЕООД', "фирма име еоод"),
    ("Фирма ЕООД", "фирма еоод"),
])
def test_the_same_company_normalizes_the_same(a, b):
    assert normalize_name(a) == normalize_name(b)


def test_normalization_is_idempotent():
    for value in ("Баумит ЕООД", "  СТРОЙ   ООД  ", 'Фирма "Име"'):
        once = normalize_name(value)
        assert normalize_name(once) == once


def test_different_legal_forms_stay_different():
    """Строй ЕООД and Строй АД are two companies, not one."""
    assert normalize_name("Строй ЕООД") != normalize_name("Строй АД")


def test_transliteration_is_not_performed():
    """Q7b is undecided; Cyrillic and Latin must not silently collapse."""
    assert normalize_name("Stroy") != normalize_name("Строй")


def test_identifier_normalization_ignores_separators():
    assert normalize_identifier("BG 123-456 789") == "BG123456789"
    assert normalize_identifier("123.456.789") == "123456789"


def test_strip_legal_suffix_is_display_only():
    assert strip_legal_suffix(normalize_name("Строй ЕООД")) == "строй"


def test_entity_carries_its_normalized_name_and_version():
    e = models.build_entity(tenant_id="t", entity_type=models.ENTITY_ORGANIZATION,
                            display_name="  Баумит   ЕООД ")
    assert e["normalized_name"] == "баумит еоод"
    assert e["normalization_version"] == NORMALIZATION_VERSION
    assert e["aliases"] == []


# ================================================================ matching
def test_find_candidates_reports_an_exact_match_without_touching_it():
    db = SpyDb()
    repo = MasterDataRepository("tenant-a", db=db)
    ctx = Ctx(db=db)
    run(create_entity(ctx, entity_type=models.ENTITY_ORGANIZATION, display_name="Баумит ЕООД",
                      source="explicit_confirmation", mode=MODE_ENFORCE, repository=repo))
    found = run(matching.find_candidates(repo, entity_type=models.ENTITY_ORGANIZATION,
                                         raw_value="баумит   еоод"))
    assert len(found) == 1
    assert found[0]["match_type"] == matching.MATCH_EXACT_NORMALIZED
    assert found[0]["score"] == 1.0
    stored = db.master(models.ENTITY_ORGANIZATION).docs[0]
    assert stored["aliases"] == [], "a lookup modified the record"


def test_find_candidates_is_empty_for_an_unknown_name():
    repo = MasterDataRepository("tenant-a", db=SpyDb())
    assert run(matching.find_candidates(repo, entity_type=models.ENTITY_ITEM,
                                        raw_value="нещо ново")) == []


def test_candidates_never_cross_tenants():
    db = SpyDb()
    run(create_entity(Ctx("tenant-a", db=db), entity_type=models.ENTITY_ITEM,
                      display_name="Лепило", source="explicit_confirmation",
                      mode=MODE_ENFORCE, repository=MasterDataRepository("tenant-a", db=db)))
    other = MasterDataRepository("tenant-b", db=db)
    assert run(matching.find_candidates(other, entity_type=models.ENTITY_ITEM,
                                        raw_value="Лепило")) == []


# ================================================================ review: off / shadow
def test_off_is_inert_for_every_review_operation():
    db, ctx, repo, row = seeded()
    assert run(list_pending(ctx, mode=MODE_OFF, repository=repo)) == []
    assert run(suggest_matches(ctx, pending_id=row["id"], mode=MODE_OFF, repository=repo)) == []
    assert run(approve(ctx, pending_id=row["id"], confirmation=True, create_new=True,
                       mode=MODE_OFF, repository=repo)).performed is False
    assert run(reject(ctx, pending_id=row["id"], reason="x", mode=MODE_OFF,
                      repository=repo)).performed is False
    assert db[PENDING_COLLECTION].docs[0]["status"] == STATUS_PENDING
    assert db.audit() is None


def test_shadow_changes_no_official_data():
    db, ctx, repo, row = seeded()
    a = run(approve(ctx, pending_id=row["id"], confirmation=True, create_new=True,
                    mode=MODE_SHADOW, repository=repo))
    r = run(reject(ctx, pending_id=row["id"], reason="не е доставчик", mode=MODE_SHADOW,
                   repository=repo))
    assert a.performed is False and a.would_perform is True
    assert r.performed is False and r.would_perform is True
    assert db[PENDING_COLLECTION].docs[0]["status"] == STATUS_PENDING
    assert db.master(models.ENTITY_ITEM) is None
    assert db.audit() is None


def test_shadow_reports_a_missing_confirmation_instead_of_raising():
    db, ctx, repo, row = seeded()
    outcome = run(approve(ctx, pending_id=row["id"], confirmation=False, create_new=True,
                          mode=MODE_SHADOW, repository=repo))
    assert outcome.would_perform is False
    assert "confirmation" in outcome.reason


# ================================================================ approve
def test_approve_requires_explicit_human_confirmation():
    db, ctx, repo, row = seeded()
    with pytest.raises(MasterDataRefused) as exc:
        run(approve(ctx, pending_id=row["id"], confirmation=False, create_new=True,
                    mode=MODE_ENFORCE, repository=repo))
    assert "confirmation" in str(exc.value)
    assert db[PENDING_COLLECTION].docs[0]["status"] == STATUS_PENDING
    assert db.master(models.ENTITY_ITEM) is None


@pytest.mark.parametrize("bad", [None, 0, "", "true", 1])
def test_only_a_real_true_counts_as_confirmation(bad):
    db, ctx, repo, row = seeded()
    with pytest.raises(MasterDataRefused):
        run(approve(ctx, pending_id=row["id"], confirmation=bad, create_new=True,
                    mode=MODE_ENFORCE, repository=repo))


def test_approve_as_new_creates_exactly_one_master_and_one_event():
    db, ctx, repo, row = seeded()
    outcome = run(approve(ctx, pending_id=row["id"], confirmation=True, create_new=True,
                          display_name="Баумит лепило бяло 25 кг",
                          mode=MODE_ENFORCE, repository=repo))
    assert outcome.performed is True and outcome.created_master is True
    masters = db.master(models.ENTITY_ITEM).docs
    assert len(masters) == 1
    assert masters[0]["display_name"] == "Баумит лепило бяло 25 кг"
    assert db[PENDING_COLLECTION].docs[0]["status"] == STATUS_RESOLVED
    assert db[PENDING_COLLECTION].docs[0]["resolved_entity_id"] == outcome.entity_id
    assert db[PENDING_COLLECTION].docs[0]["resolved_by"] == "office-1"
    # one event for creating the Master, one for the human decision
    actions = [e["action"] for e in db.audit().docs]
    assert actions.count("master_data.item.created") == 1
    assert actions.count("master_data.pending.approved") == 1


def test_approve_to_existing_adds_an_alias_and_creates_no_master():
    db, ctx, repo, row = seeded()
    created = run(create_entity(ctx, entity_type=models.ENTITY_ITEM,
                                display_name="Баумит лепило", source="explicit_confirmation",
                                mode=MODE_ENFORCE, repository=repo))
    before = len(db.master(models.ENTITY_ITEM).docs)
    outcome = run(approve(ctx, pending_id=row["id"], confirmation=True,
                          canonical_entity_id=created.entity["id"],
                          mode=MODE_ENFORCE, repository=repo))
    assert outcome.performed is True and outcome.created_master is False
    assert len(db.master(models.ENTITY_ITEM).docs) == before, "a second Master appeared"
    stored = db.master(models.ENTITY_ITEM).docs[0]
    assert stored["aliases"][0]["value"] == row["raw_value"]
    assert stored["aliases"][0]["added_by"] == "office-1"
    assert db[PENDING_COLLECTION].docs[0]["resolved_entity_id"] == created.entity["id"]


def test_the_confirmed_alias_makes_the_same_text_findable_next_time():
    db, ctx, repo, row = seeded()
    created = run(create_entity(ctx, entity_type=models.ENTITY_ITEM,
                                display_name="Баумит лепило", source="explicit_confirmation",
                                mode=MODE_ENFORCE, repository=repo))
    assert run(matching.find_candidates(repo, entity_type=models.ENTITY_ITEM,
                                        raw_value=row["raw_value"])) == []
    run(approve(ctx, pending_id=row["id"], confirmation=True,
                canonical_entity_id=created.entity["id"], mode=MODE_ENFORCE, repository=repo))
    again = run(matching.find_candidates(repo, entity_type=models.ENTITY_ITEM,
                                         raw_value=row["raw_value"]))
    assert len(again) == 1
    assert again[0]["match_type"] == matching.MATCH_ALIAS


def test_approve_needs_exactly_one_target():
    db, ctx, repo, row = seeded()
    with pytest.raises(MasterDataInvalid):
        run(approve(ctx, pending_id=row["id"], confirmation=True, mode=MODE_ENFORCE,
                    repository=repo))
    with pytest.raises(MasterDataInvalid):
        run(approve(ctx, pending_id=row["id"], confirmation=True, create_new=True,
                    canonical_entity_id="x", mode=MODE_ENFORCE, repository=repo))


def test_approve_to_a_missing_record_is_refused_and_releases_the_row():
    db, ctx, repo, row = seeded()
    with pytest.raises(MasterDataRefused):
        run(approve(ctx, pending_id=row["id"], confirmation=True,
                    canonical_entity_id="does-not-exist", mode=MODE_ENFORCE, repository=repo))
    assert db[PENDING_COLLECTION].docs[0]["status"] == STATUS_PENDING, "the row stayed claimed"


# ================================================================ concurrency
def test_two_simultaneous_approvals_create_one_canonical_record():
    """The reason the claim is a compare-and-set."""
    db, ctx, repo, row = seeded()
    first = run(approve(ctx, pending_id=row["id"], confirmation=True, create_new=True,
                        mode=MODE_ENFORCE, repository=repo))
    with pytest.raises(MasterDataRefused) as exc:
        run(approve(ctx, pending_id=row["id"], confirmation=True, create_new=True,
                    mode=MODE_ENFORCE, repository=repo))
    assert "another reviewer" in str(exc.value)
    assert first.performed is True
    assert len(db.master(models.ENTITY_ITEM).docs) == 1, "two canonical records were created"
    assert [e["action"] for e in db.audit().docs].count("master_data.pending.approved") == 1


def test_a_resolved_row_cannot_be_rejected_afterwards():
    db, ctx, repo, row = seeded()
    run(approve(ctx, pending_id=row["id"], confirmation=True, create_new=True,
                mode=MODE_ENFORCE, repository=repo))
    with pytest.raises(MasterDataRefused):
        run(reject(ctx, pending_id=row["id"], reason="късно", mode=MODE_ENFORCE, repository=repo))
    assert db[PENDING_COLLECTION].docs[0]["status"] == STATUS_RESOLVED


# ================================================================ reject
def test_reject_touches_no_master_data():
    db, ctx, repo, row = seeded()
    outcome = run(reject(ctx, pending_id=row["id"], reason="не е артикул",
                         mode=MODE_ENFORCE, repository=repo))
    assert outcome.performed is True and outcome.decision == STATUS_REJECTED
    assert db.master(models.ENTITY_ITEM) is None, "reject created a Master record"
    stored = db[PENDING_COLLECTION].docs[0]
    assert stored["status"] == STATUS_REJECTED
    assert stored["rejection_reason"] == "не е артикул"
    assert stored["resolved_entity_id"] is None
    events = [e for e in db.audit().docs if e["action"] == "master_data.pending.rejected"]
    assert len(events) == 1
    assert events[0]["actor_id"] == "office-1"
    assert events[0]["tenant_id"] == "tenant-a"


@pytest.mark.parametrize("reason", ["", "   ", None, "x" * 501])
def test_reject_needs_a_real_reason(reason):
    db, ctx, repo, row = seeded()
    with pytest.raises(MasterDataInvalid):
        run(reject(ctx, pending_id=row["id"], reason=reason, mode=MODE_ENFORCE, repository=repo))
    assert db[PENDING_COLLECTION].docs[0]["status"] == STATUS_PENDING


# ================================================================ audit / actor / tenant
def test_approve_audit_failure_is_not_a_false_success():
    db, ctx, repo, row = seeded()
    db.collections["audit_events"] = SpyCollection(fail_on_insert=True)
    with pytest.raises(MasterDataAuditFailed):
        run(approve(ctx, pending_id=row["id"], confirmation=True, create_new=True,
                    mode=MODE_ENFORCE, repository=repo))


def test_reject_audit_failure_is_not_a_false_success():
    db, ctx, repo, row = seeded()
    db.collections["audit_events"] = SpyCollection(fail_on_insert=True)
    with pytest.raises(MasterDataAuditFailed):
        run(reject(ctx, pending_id=row["id"], reason="x", mode=MODE_ENFORCE, repository=repo))


@pytest.mark.parametrize("ctx", [None, LegacyCtx(), ActorlessCtx()])
def test_review_refuses_a_bad_context(ctx):
    db, _, repo, row = seeded()
    with pytest.raises(MasterDataTenantContextMissing):
        run(approve(ctx, pending_id=row["id"], confirmation=True, create_new=True,
                    mode=MODE_ENFORCE, repository=repo))
    with pytest.raises(MasterDataTenantContextMissing):
        run(reject(ctx, pending_id=row["id"], reason="x", mode=MODE_ENFORCE, repository=repo))


def test_another_tenant_cannot_see_or_resolve_the_row():
    db, ctx, repo, row = seeded()
    other_ctx = Ctx("tenant-b", db=db)
    other_repo = MasterDataRepository("tenant-b", db=db)
    assert run(list_pending(other_ctx, mode=MODE_ENFORCE, repository=other_repo)) == []
    with pytest.raises(MasterDataRefused):
        run(reject(other_ctx, pending_id=row["id"], reason="x", mode=MODE_ENFORCE,
                   repository=other_repo))
    with pytest.raises(MasterDataRefused):
        run(approve(other_ctx, pending_id=row["id"], confirmation=True, create_new=True,
                    mode=MODE_ENFORCE, repository=other_repo))
    assert db[PENDING_COLLECTION].docs[0]["status"] == STATUS_PENDING


# ================================================================ queue + mode guard
def test_the_queue_shows_only_this_tenant_and_only_open_rows():
    db, ctx, repo, row = seeded()
    items = run(list_pending(ctx, mode=MODE_ENFORCE, repository=repo))
    assert [i["id"] for i in items] == [row["id"]]
    run(reject(ctx, pending_id=row["id"], reason="не", mode=MODE_ENFORCE, repository=repo))
    assert run(list_pending(ctx, mode=MODE_ENFORCE, repository=repo)) == []
    assert len(run(list_pending(ctx, status=STATUS_REJECTED, mode=MODE_ENFORCE,
                                repository=repo))) == 1


@pytest.mark.parametrize("bad", ["offf", "", 1, object()])
def test_invalid_mode_refuses_every_review_operation_before_mongo(bad):
    db, ctx, repo, row = seeded()
    for call in (
        lambda: list_pending(ctx, mode=bad, repository=repo),
        lambda: suggest_matches(ctx, pending_id=row["id"], mode=bad, repository=repo),
        lambda: approve(ctx, pending_id=row["id"], confirmation=True, create_new=True,
                        mode=bad, repository=repo),
        lambda: reject(ctx, pending_id=row["id"], reason="x", mode=bad, repository=repo),
    ):
        with pytest.raises(MasterDataConfigError):
            run(call())
    assert db[PENDING_COLLECTION].docs[0]["status"] == STATUS_PENDING


def test_suggest_matches_for_an_unknown_row_is_refused():
    db, ctx, repo, _ = seeded()
    with pytest.raises(MasterDataRefused):
        run(suggest_matches(ctx, pending_id="nope", mode=MODE_ENFORCE, repository=repo))
