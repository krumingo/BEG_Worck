"""
W0-03B2 — Pending Mapping foundation.

The promise under test: an automated channel can propose and nothing else. No
Master record, no link, no merge — **not even when a suggestion matches
exactly**. FLOW-032 §"Импорт, OCR и AI мапване".

Pure logic plus spies — no database, no live application.

Run:  pytest tests/test_w0_03b2_pending_mapping.py -v --noconftest
"""
import asyncio

import pytest

from app.master_data import models, pending as pending_mod
from app.master_data.deps import (
    ENV_MODE,
    MODE_ENFORCE,
    MODE_OFF,
    MODE_SHADOW,
    MasterDataConfigError,
    MasterDataTenantContextMissing,
)
from app.master_data.models import MasterDataInvalid
from app.master_data.pending import (
    PENDING_COLLECTION,
    SOURCE_AI,
    SOURCE_EXCEL,
    SOURCE_IMPORT,
    SOURCE_OCR,
    STATUS_PENDING,
    build_pending,
    build_suggestion,
    get_pending,
    propose,
    validate_pending,
)
from app.master_data.repository import MasterDataRepository
from app.master_data.service import MasterDataAuditFailed, MasterDataRefused

MODEL = "test-model/1.0"


def run(coro):
    return asyncio.run(coro)


class UpdateResult:
    def __init__(self, modified, upserted_id=None):
        self.modified_count = modified
        self.upserted_id = upserted_id


class SpyCollection:
    def __init__(self, fail_on_insert=False):
        self.inserted = []
        self.queries = []
        self.fail_on_insert = fail_on_insert

    async def insert_one(self, doc):
        if self.fail_on_insert:
            raise RuntimeError("simulated storage failure")
        self.inserted.append(doc)

    def _match(self, query):
        return [d for d in self.inserted
                if all(d.get(k) == v for k, v in (query or {}).items())]

    async def find_one(self, query, projection=None, sort=None):
        """Match like a real collection: every key in the query must match.

        The first version only answered when ``sort`` was given — enough for the
        audit chain lookup, wrong for a plain read. A test double that is too
        crude fails the product for its own reasons.
        """
        self.queries.append(query)
        matches = self._match(query)
        if not matches:
            return None
        return matches[-1] if sort else matches[0]

    async def update_one(self, query, update, upsert=False):
        """Enough of Mongo's update semantics for the idempotent proposal:
        an upsert builds the document from ``$setOnInsert`` and reports it as
        upserted, not modified; a match is incremented in place."""
        self.queries.append(query)
        matches = self._match(query)
        upserted = None
        if not matches:
            if not upsert:
                return UpdateResult(0)
            if self.fail_on_insert:
                raise RuntimeError("simulated storage failure")
            doc = dict(update.get("$setOnInsert", {}))
            self.inserted.append(doc)
            matches = [doc]
            upserted = doc.get("id", True)
        doc = matches[0]
        for k, v in update.get("$set", {}).items():
            doc[k] = v
        for k, v in update.get("$inc", {}).items():
            doc[k] = doc.get(k, 0) + v
        return UpdateResult(0 if upserted is not None else 1, upserted_id=upserted)


class SpyDb:
    def __init__(self, failing=()):
        self.collections = {}
        self.failing = set(failing)

    def __getitem__(self, name):
        if name not in self.collections:
            self.collections[name] = SpyCollection(fail_on_insert=name in self.failing)
        return self.collections[name]

    def master_collections(self):
        return [n for n in self.collections if n.startswith("md_") and n != PENDING_COLLECTION]


class ExplodingDb:
    def __getitem__(self, name):
        raise AssertionError("a collection was opened when it must not be")


class ExplodingRepository:
    def __init__(self, *a, **kw):
        raise AssertionError("repository was constructed when it must not be")

    async def create_pending(self, *a, **kw):
        raise AssertionError("create_pending was called when it must not be")

    async def get_pending(self, *a, **kw):
        raise AssertionError("get_pending was called when it must not be")


class Ctx:
    enforced = True

    def __init__(self, tenant_id="tenant-a", user_id="user-1", db=None):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self._db = db if db is not None else SpyDb()

    async def db(self, require_operational: bool = False):
        return self._db


class ActorlessCtx(Ctx):
    def __init__(self, tenant_id="tenant-a"):
        super().__init__(tenant_id=tenant_id, user_id=None)


class LegacyCtx:
    enforced = False
    tenant_id = "org-legacy"


def propose_ok(ctx, **over):
    kwargs = dict(entity_type=models.ENTITY_ITEM, raw_value="Баумит леп. бяло 25",
                  source_channel=SOURCE_OCR, mode=MODE_ENFORCE)
    kwargs.update(over)
    return run(propose(ctx, **kwargs))


# ---------------------------------------------------------------- 1. off is inert
def test_off_writes_nothing_and_opens_nothing(monkeypatch):
    monkeypatch.setattr(pending_mod, "_repository_for",
                        lambda ctx: (_ for _ in ()).throw(AssertionError("off built a repository")))
    spy = SpyDb()
    outcome = run(propose(Ctx(db=spy), entity_type=models.ENTITY_ITEM, raw_value="x",
                          source_channel=SOURCE_EXCEL, mode=MODE_OFF))
    assert outcome.performed is False
    assert outcome.pending is None
    assert spy.collections == {}


def test_off_does_not_need_a_context_or_valid_input():
    outcome = run(propose(None, entity_type="nonsense", raw_value="", source_channel="nope",
                          mode=MODE_OFF))
    assert outcome.performed is False


def test_off_read_returns_none_without_a_read(monkeypatch):
    monkeypatch.setattr(pending_mod, "_repository_for",
                        lambda ctx: (_ for _ in ()).throw(AssertionError("off built a repository")))
    assert run(get_pending(Ctx(), pending_id="x", mode=MODE_OFF)) is None


def test_off_emits_no_audit(monkeypatch):
    import app.audit.store as store
    import app.audit.envelope as envelope

    def boom(*a, **kw):
        raise AssertionError("off emitted an AuditEvent")

    monkeypatch.setattr(store, "record_event", boom)
    monkeypatch.setattr(envelope, "build_event", boom)
    assert run(propose(Ctx(), entity_type=models.ENTITY_ITEM, raw_value="x",
                       source_channel=SOURCE_OCR, mode=MODE_OFF)).performed is False


# ---------------------------------------------------------------- 2. shadow does nothing
def test_shadow_writes_no_pending_and_no_master():
    spy = SpyDb()
    outcome = run(propose(Ctx(db=spy), entity_type=models.ENTITY_ORGANIZATION,
                          raw_value="Фирма ЕООД", source_channel=SOURCE_EXCEL,
                          mode=MODE_SHADOW, repository=ExplodingRepository))
    assert outcome.mode == MODE_SHADOW
    assert outcome.performed is False
    assert outcome.would_perform is True
    assert outcome.pending is None
    assert spy.collections == {}


def test_shadow_opens_no_database():
    outcome = run(propose(Ctx(db=ExplodingDb()), entity_type=models.ENTITY_ITEM,
                          raw_value="Лепило", source_channel=SOURCE_IMPORT, mode=MODE_SHADOW))
    assert outcome.performed is False


def test_shadow_emits_no_audit(monkeypatch):
    import app.audit.store as store
    import app.audit.envelope as envelope

    def boom(*a, **kw):
        raise AssertionError("shadow emitted an AuditEvent")

    monkeypatch.setattr(store, "record_event", boom)
    monkeypatch.setattr(envelope, "build_event", boom)
    assert run(propose(Ctx(), entity_type=models.ENTITY_ITEM, raw_value="x",
                       source_channel=SOURCE_OCR, mode=MODE_SHADOW)).performed is False


@pytest.mark.parametrize("ctx", [None, LegacyCtx(), ActorlessCtx()])
def test_shadow_reports_instead_of_raising(ctx):
    outcome = run(propose(ctx, entity_type=models.ENTITY_ITEM, raw_value="x",
                          source_channel=SOURCE_OCR, mode=MODE_SHADOW,
                          repository=ExplodingRepository))
    assert outcome.performed is False
    assert outcome.would_perform is False
    assert outcome.reason


def test_shadow_does_not_break_the_legacy_path_on_a_policy_refusal():
    """An AI proposal without a model is refused in enforce; in shadow it must
    come back as information, not as an exception."""
    outcome = run(propose(Ctx(), entity_type=models.ENTITY_ITEM, raw_value="x",
                          source_channel=SOURCE_AI, mode=MODE_SHADOW))
    assert outcome.would_perform is False
    assert "model" in outcome.reason


def test_shadow_read_returns_none(monkeypatch):
    monkeypatch.setattr(pending_mod, "_repository_for",
                        lambda ctx: (_ for _ in ()).throw(AssertionError("shadow read")))
    assert run(get_pending(Ctx(), pending_id="x", mode=MODE_SHADOW)) is None


# ---------------------------------------------------------------- 3. enforce: pending only
def test_enforce_creates_a_pending_record_and_no_master():
    spy = SpyDb()
    outcome = propose_ok(Ctx(db=spy), repository=MasterDataRepository("tenant-a", db=spy))
    assert outcome.performed is True
    assert outcome.pending["status"] == STATUS_PENDING
    assert spy.collections[PENDING_COLLECTION].inserted
    assert spy.master_collections() == [], "a Master collection was written"


def test_pending_record_carries_the_required_fields():
    spy = SpyDb()
    outcome = propose_ok(
        Ctx(db=spy), repository=MasterDataRepository("tenant-a", db=spy),
        entity_type=models.ENTITY_ITEM, raw_value="  StarContact White 25kg  ",
        source_channel=SOURCE_OCR, source_ref="ocr-job-42",
        suggested_matches=[build_suggestion("item-1", score=0.91, reason="name similarity")])
    doc = outcome.pending
    assert doc["id"] and doc["tenant_id"] == "tenant-a"
    assert doc["entity_type"] == models.ENTITY_ITEM
    assert doc["raw_value"] == "StarContact White 25kg"
    assert doc["source_channel"] == SOURCE_OCR
    assert doc["source_ref"] == "ocr-job-42"
    assert doc["suggested_matches"][0]["entity_id"] == "item-1"
    assert doc["status"] == STATUS_PENDING
    assert doc["created_by"] == "user-1"
    assert doc["created_at"] and doc["updated_at"]


def test_enforce_read_returns_the_record():
    spy = SpyDb()
    repo = MasterDataRepository("tenant-a", db=spy)
    outcome = propose_ok(Ctx(db=spy), repository=repo)
    spy.collections[PENDING_COLLECTION].inserted.append(outcome.pending)
    found = run(get_pending(Ctx(db=spy), pending_id=outcome.pending["id"],
                            mode=MODE_ENFORCE, repository=repo))
    assert found is not None


# ---------------------------------------------------------------- 4/5. canonical audit
def test_exactly_one_canonical_audit_event():
    spy = SpyDb()
    outcome = propose_ok(Ctx(db=spy), repository=MasterDataRepository("tenant-a", db=spy))
    events = spy.collections["audit_events"].inserted
    assert len(events) == 1
    e = events[0]
    assert e["tenant_id"] == "tenant-a"
    assert e["actor_id"] == "user-1"
    assert e["action"] == "master_data.pending.proposed"
    assert e["entity_type"] == "master_data.pending"
    assert e["entity_id"] == outcome.pending["id"]
    assert e["source_channel"] == SOURCE_OCR
    assert e.get("integrity_hash")


def test_ai_proposal_is_attributed_to_its_model():
    spy = SpyDb()
    propose_ok(Ctx(db=spy), repository=MasterDataRepository("tenant-a", db=spy),
               source_channel=SOURCE_AI, model_and_version=MODEL)
    e = spy.collections["audit_events"].inserted[0]
    assert e["actor_type"] == "ai"
    assert e["model_and_version"] == MODEL
    assert e["retention_class"] == "R4"


def test_ai_proposal_without_a_model_is_refused_before_any_write():
    spy = SpyDb()
    with pytest.raises(MasterDataRefused) as exc:
        propose_ok(Ctx(db=spy), source_channel=SOURCE_AI, repository=ExplodingRepository)
    assert "model" in str(exc.value)
    assert spy.collections == {}


def test_audit_failure_is_not_a_false_success():
    spy = SpyDb(failing={"audit_events"})
    with pytest.raises(MasterDataAuditFailed) as exc:
        propose_ok(Ctx(db=spy), repository=MasterDataRepository("tenant-a", db=spy))
    assert "NOT successful" in str(exc.value)
    assert spy.collections[PENDING_COLLECTION].inserted, "the row is there, unaudited"


# ---------------------------------------------------------------- 6/7. actor and tenant
def test_missing_actor_is_refused_before_the_write():
    spy = SpyDb()
    with pytest.raises(MasterDataTenantContextMissing):
        propose_ok(ActorlessCtx(), repository=ExplodingRepository)
    assert spy.collections == {}


@pytest.mark.parametrize("ctx", [None, LegacyCtx()])
def test_bad_context_is_refused(ctx):
    with pytest.raises(MasterDataTenantContextMissing):
        propose_ok(ctx, repository=ExplodingRepository)


@pytest.mark.parametrize("key", ["tenant_id", "org_id", "tenantId", "orgId", "organization_id"])
def test_tenant_in_payload_is_refused(key):
    with pytest.raises(MasterDataRefused) as exc:
        propose_ok(Ctx(), payload={key: "tenant-b"}, repository=ExplodingRepository)
    assert "payload" in str(exc.value)


def test_pending_always_carries_the_context_tenant():
    spy = SpyDb()
    outcome = propose_ok(Ctx("tenant-a", db=spy), repository=MasterDataRepository("tenant-a", db=spy))
    assert outcome.pending["tenant_id"] == "tenant-a"
    assert spy.collections[PENDING_COLLECTION].inserted[0]["tenant_id"] == "tenant-a"


# ---------------------------------------------------------------- 8. cross-tenant
def test_repository_refuses_a_pending_record_of_another_tenant():
    other = build_pending(tenant_id="tenant-b", entity_type=models.ENTITY_ITEM,
                          raw_value="Чужд", source_channel=SOURCE_EXCEL, created_by="user-9")
    repo = MasterDataRepository("tenant-a", db=SpyDb())
    with pytest.raises(MasterDataInvalid) as exc:
        run(repo.create_pending(other))
    assert "tenant-b" in str(exc.value) and "tenant-a" in str(exc.value)


def test_pending_read_is_pinned_to_its_tenant():
    spy = SpyDb()
    repo = MasterDataRepository("tenant-a", db=spy)
    run(repo.get_pending("some-id"))
    assert spy.collections[PENDING_COLLECTION].queries[0]["tenant_id"] == "tenant-a"


# ---------------------------------------------------------------- 9. invalid input
@pytest.mark.parametrize("entity_type", ["nonsense", "", "Person", "persons"])
def test_invalid_entity_type_is_refused(entity_type):
    with pytest.raises(MasterDataInvalid):
        propose_ok(Ctx(), entity_type=entity_type, repository=ExplodingRepository)


@pytest.mark.parametrize("source", ["explicit_confirmation", "manual", "", "AI ", "api"])
def test_invalid_source_channel_is_refused(source):
    with pytest.raises(MasterDataInvalid):
        propose_ok(Ctx(), source_channel=source, repository=ExplodingRepository)


def test_a_human_source_does_not_belong_in_pending_mapping():
    """explicit_confirmation creates a Master record through the service; it is
    not an automated proposal and must not be smuggled in here."""
    with pytest.raises(MasterDataInvalid):
        propose_ok(Ctx(), source_channel="explicit_confirmation", repository=ExplodingRepository)


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_empty_raw_value_is_refused(raw):
    with pytest.raises(MasterDataInvalid):
        propose_ok(Ctx(), raw_value=raw, repository=ExplodingRepository)


def test_oversized_raw_value_is_refused():
    with pytest.raises(MasterDataInvalid):
        propose_ok(Ctx(), raw_value="x" * 2001, repository=ExplodingRepository)


def test_source_ref_must_be_a_reference_not_a_payload():
    with pytest.raises(MasterDataInvalid):
        propose_ok(Ctx(), source_ref="y" * 201, repository=ExplodingRepository)


def test_source_ref_must_not_carry_credentials():
    with pytest.raises(MasterDataInvalid) as exc:
        propose_ok(Ctx(), source_ref="https://user:secret@example.com/file",
                   repository=ExplodingRepository)
    assert "credentials" in str(exc.value)


def test_status_cannot_be_anything_but_pending():
    doc = build_pending(tenant_id="t", entity_type=models.ENTITY_ITEM, raw_value="x",
                        source_channel=SOURCE_OCR, created_by="u")
    for bad in ("resolved", "rejected", "approved", ""):
        doc["status"] = bad
        with pytest.raises(MasterDataInvalid):
            validate_pending(doc)


def test_a_pending_record_may_not_arrive_already_resolved():
    """Otherwise an automatic mapping could enter through the back door."""
    for field in ("resolved_entity_id", "resolved_by", "resolved_at"):
        doc = build_pending(tenant_id="t", entity_type=models.ENTITY_ITEM, raw_value="x",
                            source_channel=SOURCE_OCR, created_by="u")
        doc[field] = "something"
        with pytest.raises(MasterDataInvalid) as exc:
            validate_pending(doc)
        assert "never resolves" in str(exc.value)


def test_suggestion_needs_a_candidate_and_a_sane_score():
    with pytest.raises(MasterDataInvalid):
        build_suggestion("")
    for bad in (-0.1, 1.5, "high", True):
        with pytest.raises(MasterDataInvalid):
            build_suggestion("item-1", score=bad)


def test_too_many_suggestions_are_refused():
    many = [build_suggestion("item-%d" % i) for i in range(21)]
    with pytest.raises(MasterDataInvalid):
        propose_ok(Ctx(), suggested_matches=many, repository=ExplodingRepository)


# ---------------------------------------------------------------- 10/11. never resolve
def test_suggestions_never_resolve_the_record():
    spy = SpyDb()
    outcome = propose_ok(Ctx(db=spy), repository=MasterDataRepository("tenant-a", db=spy),
                         suggested_matches=[build_suggestion("item-1", score=0.99)])
    doc = outcome.pending
    assert doc["status"] == STATUS_PENDING
    assert doc["resolved_entity_id"] is None
    assert doc["resolved_by"] is None
    assert doc["resolved_at"] is None


def test_an_exact_match_creates_no_link_and_no_master():
    """The whole point of the slice: score 1.0 is still only a score."""
    spy = SpyDb()
    outcome = propose_ok(
        Ctx(db=spy), repository=MasterDataRepository("tenant-a", db=spy),
        raw_value="Лепило фасада Баумит",
        suggested_matches=[build_suggestion("item-exact", score=1.0, reason="exact match")])
    doc = outcome.pending
    assert doc["status"] == STATUS_PENDING
    assert doc["resolved_entity_id"] is None
    assert spy.master_collections() == [], "an exact match wrote into a Master collection"
    written = spy.collections[PENDING_COLLECTION].inserted[0]
    assert written["suggested_matches"][0]["score"] == 1.0
    assert written["resolved_entity_id"] is None


def test_no_master_collection_is_ever_touched_by_a_proposal():
    for source in (SOURCE_AI, SOURCE_OCR, SOURCE_EXCEL, SOURCE_IMPORT):
        spy = SpyDb()
        propose_ok(Ctx(db=spy), repository=MasterDataRepository("tenant-a", db=spy),
                   source_channel=source,
                   model_and_version=MODEL if source == SOURCE_AI else None)
        assert spy.master_collections() == [], "%s touched a Master collection" % source


# ---------------------------------------------------------------- mode validation
@pytest.mark.parametrize("bad", ["offf", "", "   ", "ON", 1, True, object(), ["off"]])
def test_invalid_explicit_mode_refuses_before_anything(bad):
    with pytest.raises(MasterDataConfigError):
        run(propose(Ctx(db=ExplodingDb()), entity_type=models.ENTITY_ITEM, raw_value="x",
                    source_channel=SOURCE_OCR, mode=bad, repository=ExplodingRepository))


@pytest.mark.parametrize("bad", ["offf", "", 1, object()])
def test_invalid_explicit_mode_refuses_read(bad):
    with pytest.raises(MasterDataConfigError):
        run(get_pending(Ctx(db=ExplodingDb()), pending_id="x", mode=bad,
                        repository=ExplodingRepository))


def test_default_mode_is_off(monkeypatch):
    monkeypatch.delenv(ENV_MODE, raising=False)
    spy = SpyDb()
    outcome = run(propose(Ctx(db=spy), entity_type=models.ENTITY_ITEM, raw_value="x",
                          source_channel=SOURCE_OCR))
    assert outcome.mode == MODE_OFF
    assert outcome.performed is False
    assert spy.collections == {}
