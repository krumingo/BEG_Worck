"""
W0-03B1 — Master Data foundation and off-mode inertness.

These tests encode the promises that make this slice safe to merge while the
rest of W0-03 does not exist yet: that ``off`` changes nothing, that the tenant
can only come from the server-side resolver, and that no domain can create an
official Master Person as a side effect.

Pure logic plus spies — no database, no live application, same style as the
W0-01 and W0-04 tests.

Run:  pytest tests/test_w0_03b1_master_data_foundation.py -v --noconftest
(the repository-wide conftest boots a live app and is not needed here)
"""
import asyncio
import os
import subprocess
import sys

import pytest

from app.master_data import deps, models, service
from app.master_data.deps import (
    ENV_MODE,
    MODE_ENFORCE,
    MODE_OFF,
    MODE_SHADOW,
    MasterDataConfigError,
    MasterDataTenantContextMissing,
    current_mode,
    require_tenant_context,
)
from app.master_data.models import MasterDataInvalid
from app.master_data.repository import MasterDataRepository, collection_name
from app.master_data.service import (
    SOURCE_EXPLICIT_CONFIRMATION,
    MasterDataAuditFailed,
    MasterDataRefused,
    create_entity,
    get_entity,
)

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(coro):
    return asyncio.run(coro)


class Ctx:
    """Stand-in for a resolver-backed TenantContext (``enforced`` True).

    Carries what the canonical AuditEvent needs: the tenant, the acting user
    and the tenant's database handle — exactly the integration model of
    ``app/permissions/audit_hooks.py``.
    """

    enforced = True

    def __init__(self, tenant_id="tenant-a", user_id="user-1", db=None):
        self.tenant_id = tenant_id
        self.user_id = user_id
        self._db = db if db is not None else SpyDb()

    async def db(self, require_operational: bool = False):
        return self._db


class ActorlessCtx(Ctx):
    """Resolved tenant, but no authenticated user — no audit actor exists."""

    def __init__(self, tenant_id="tenant-a"):
        super().__init__(tenant_id=tenant_id, user_id=None)


class LegacyCtx:
    """Stand-in for the off/compat context: carries a legacy org identity."""

    enforced = False

    def __init__(self, tenant_id="org-legacy"):
        self.tenant_id = tenant_id


class ExplodingRepository:
    """Any use at all is a failure."""

    def __init__(self, *a, **kw):
        raise AssertionError("repository was constructed when it must not be")

    async def create(self, *a, **kw):
        raise AssertionError("repository.create was called when it must not be")

    async def get(self, *a, **kw):
        raise AssertionError("repository.get was called when it must not be")


class SpyCollection:
    def __init__(self, fail_on_insert=False):
        self.inserted = []
        self.queries = []
        self.fail_on_insert = fail_on_insert

    async def insert_one(self, doc):
        if self.fail_on_insert:
            raise RuntimeError("simulated storage failure")
        self.inserted.append(doc)
        return None

    async def find_one(self, query, projection=None, sort=None):
        self.queries.append(query)
        if self.inserted and sort:                    # audit chain lookup
            return self.inserted[-1]
        return None


class SpyDb:
    def __init__(self, failing=()):
        self.collections = {}
        self.failing = set(failing)

    def __getitem__(self, name):
        if name not in self.collections:
            self.collections[name] = SpyCollection(fail_on_insert=name in self.failing)
        return self.collections[name]

    def audit_events(self):
        return self.collections.get("audit_events")


class ExplodingDb:
    """Any database access at all is a failure."""

    def __getitem__(self, name):
        raise AssertionError("a database collection was opened when it must not be")


# ---------------------------------------------------------------- 1. default mode
def test_default_mode_is_off():
    assert current_mode({}) == MODE_OFF
    assert deps.is_off(current_mode({}))


def test_valid_modes_are_accepted():
    for mode in (MODE_OFF, MODE_SHADOW, MODE_ENFORCE):
        assert current_mode({ENV_MODE: mode}) == mode
        assert current_mode({ENV_MODE: " " + mode.upper() + " "}) == mode


# ---------------------------------------------------------------- 2. invalid config refuses
@pytest.mark.parametrize("bad", ["on", "true", "1", "enforced", "", "   ", "offf"])
def test_invalid_mode_refuses_instead_of_defaulting(bad):
    with pytest.raises(MasterDataConfigError) as exc:
        current_mode({ENV_MODE: bad})
    assert ENV_MODE in str(exc.value)


def test_empty_value_is_an_operator_mistake_not_an_absent_setting():
    """Unset falls back to off; set-to-empty is refused."""
    assert current_mode({}) == MODE_OFF
    with pytest.raises(MasterDataConfigError):
        current_mode({ENV_MODE: ""})


def test_validate_config_reports_the_mode():
    assert deps.validate_config({ENV_MODE: "shadow"}) == MODE_SHADOW
    with pytest.raises(MasterDataConfigError):
        deps.validate_config({ENV_MODE: "nope"})


# ---------------------------------------------------------------- 3. off mode is inert
def test_off_mode_touches_no_repository(monkeypatch):
    monkeypatch.setattr(service, "_repository_for",
                        lambda ctx: (_ for _ in ()).throw(
                            AssertionError("off mode built a repository")))
    outcome = run(create_entity(Ctx(), entity_type=models.ENTITY_ITEM,
                                display_name="Лепило", source=SOURCE_EXPLICIT_CONFIRMATION,
                                mode=MODE_OFF))
    assert outcome.performed is False
    assert outcome.entity is None
    assert outcome.mode == MODE_OFF


def test_off_mode_read_returns_none_without_touching_anything(monkeypatch):
    monkeypatch.setattr(service, "_repository_for",
                        lambda ctx: (_ for _ in ()).throw(
                            AssertionError("off mode built a repository")))
    assert run(get_entity(Ctx(), entity_type=models.ENTITY_PERSON,
                          entity_id="whatever", mode=MODE_OFF)) is None


def test_off_mode_does_not_even_need_a_tenant_context():
    """Inert means inert: off returns before any guard, so it cannot introduce
    a new failure on a path that used to succeed."""
    outcome = run(create_entity(None, entity_type=models.ENTITY_PERSON,
                                display_name="x", source="ai", mode=MODE_OFF))
    assert outcome.performed is False
    assert run(get_entity(None, entity_type=models.ENTITY_PERSON,
                          entity_id="x", mode=MODE_OFF)) is None


def test_off_mode_emits_no_audit_event(monkeypatch):
    import app.audit.store as store
    import app.audit.envelope as envelope

    def boom(*a, **kw):
        raise AssertionError("off mode emitted an AuditEvent")

    monkeypatch.setattr(store, "record_event", boom)
    monkeypatch.setattr(envelope, "build_event", boom)
    outcome = run(create_entity(Ctx(), entity_type=models.ENTITY_TAG,
                                display_name="Електро", source=SOURCE_EXPLICIT_CONFIRMATION,
                                mode=MODE_OFF))
    assert outcome.performed is False


def test_importing_the_package_does_not_import_the_mongo_resolver():
    """The resolver creates a Mongo client at import time, so off mode must not
    pull it in. Checked in a fresh interpreter, where nothing else has."""
    code = (
        "import sys; import app.master_data; "
        "print('resolver' if 'app.tenancy.resolver' in sys.modules else 'clean')"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=BACKEND_DIR,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "clean", (
        "importing app.master_data pulled in the Mongo resolver: %s" % proc.stdout)


# ---------------------------------------------------------------- 4. baseline behaviour
def test_off_mode_never_raises_for_input_that_enforce_would_refuse():
    """A typo, a forbidden source or a tenant key in the payload must not turn
    into a new error while the feature is off."""
    for kwargs in (
        {"entity_type": "not_a_type", "display_name": "x", "source": "ai"},
        {"entity_type": models.ENTITY_PERSON, "display_name": "", "source": "advance"},
        {"entity_type": models.ENTITY_ITEM, "display_name": "x", "source": None,
         "payload": {"tenant_id": "tenant-b"}},
    ):
        outcome = run(create_entity(Ctx(), mode=MODE_OFF, **kwargs))
        assert outcome.performed is False


# ---------------------------------------------------------------- 5. tenant from body
def test_tenant_in_payload_is_refused_not_ignored():
    for key in ("tenant_id", "org_id", "tenantId", "orgId", "organization_id"):
        with pytest.raises(MasterDataRefused) as exc:
            run(create_entity(Ctx("tenant-a"), entity_type=models.ENTITY_ITEM,
                              display_name="Лепило", source=SOURCE_EXPLICIT_CONFIRMATION,
                              payload={key: "tenant-b"}, mode=MODE_ENFORCE,
                              repository=ExplodingRepository))
        assert "payload" in str(exc.value)


def test_entity_always_carries_the_context_tenant():
    spy = SpyDb()
    repo = MasterDataRepository("tenant-a", db=spy)
    outcome = run(create_entity(Ctx("tenant-a"), entity_type=models.ENTITY_ORGANIZATION,
                                display_name="Фирма ЕООД", source=SOURCE_EXPLICIT_CONFIRMATION,
                                mode=MODE_ENFORCE, repository=repo))
    assert outcome.entity["tenant_id"] == "tenant-a"
    assert spy.collections["md_organization"].inserted[0]["tenant_id"] == "tenant-a"


# ---------------------------------------------------------------- 6. missing tenant context
def test_missing_context_is_refused():
    with pytest.raises(MasterDataTenantContextMissing):
        require_tenant_context(None)


def test_legacy_compat_context_is_refused():
    with pytest.raises(MasterDataTenantContextMissing) as exc:
        require_tenant_context(LegacyCtx())
    assert "legacy" in str(exc.value).lower()


def test_context_without_tenant_id_is_refused():
    class Empty:
        enforced = True
        tenant_id = None

    with pytest.raises(MasterDataTenantContextMissing):
        require_tenant_context(Empty())


def test_enforce_mode_refuses_without_a_context():
    with pytest.raises(MasterDataTenantContextMissing):
        run(create_entity(None, entity_type=models.ENTITY_ITEM, display_name="x",
                          source=SOURCE_EXPLICIT_CONFIRMATION, mode=MODE_ENFORCE,
                          repository=ExplodingRepository))


# ---------------------------------------------------------------- 7. cross-tenant
def test_repository_refuses_an_entity_of_another_tenant():
    other = models.build_entity(tenant_id="tenant-b", entity_type=models.ENTITY_ITEM,
                                display_name="Чужд артикул")
    repo = MasterDataRepository("tenant-a", db=SpyDb())
    with pytest.raises(MasterDataInvalid) as exc:
        run(repo.create(other))
    assert "tenant-b" in str(exc.value) and "tenant-a" in str(exc.value)


def test_repository_pins_every_query_to_its_own_tenant():
    spy = SpyDb()
    repo = MasterDataRepository("tenant-a", db=spy)
    run(repo.get(models.ENTITY_PERSON, "some-id"))
    assert spy.collections["md_person"].queries[0]["tenant_id"] == "tenant-a"


def test_repository_scope_cannot_be_widened_by_a_caller():
    repo = MasterDataRepository("tenant-a", db=SpyDb())
    assert repo._scope({"tenant_id": "tenant-b"})["tenant_id"] == "tenant-a"


def test_repository_requires_a_tenant():
    for bad in (None, "", 0):
        with pytest.raises(MasterDataInvalid):
            MasterDataRepository(bad)


# ---------------------------------------------------------------- 8. no side-effect persons
@pytest.mark.parametrize("source", ["advance", "payroll", "attendance", "brigade",
                                    "ai", "ocr", "excel", "import", "intake"])
def test_no_domain_creates_a_master_person_as_a_side_effect(source):
    with pytest.raises(MasterDataRefused) as exc:
        run(create_entity(Ctx(), entity_type=models.ENTITY_PERSON, display_name="Иван Иванов",
                          source=source, mode=MODE_ENFORCE, repository=ExplodingRepository))
    assert SOURCE_EXPLICIT_CONFIRMATION in str(exc.value)


def test_person_requires_explicit_confirmation_even_for_an_unlisted_source():
    with pytest.raises(MasterDataRefused):
        run(create_entity(Ctx(), entity_type=models.ENTITY_PERSON, display_name="Иван",
                          source="some_new_subsystem", mode=MODE_ENFORCE,
                          repository=ExplodingRepository))


def test_missing_source_is_refused():
    with pytest.raises(MasterDataRefused):
        run(create_entity(Ctx(), entity_type=models.ENTITY_ITEM, display_name="x",
                          source=None, mode=MODE_ENFORCE, repository=ExplodingRepository))


@pytest.mark.parametrize("source", ["ai", "ocr", "excel", "import"])
def test_automated_sources_cannot_create_any_master_record(source):
    with pytest.raises(MasterDataRefused):
        run(create_entity(Ctx(), entity_type=models.ENTITY_ITEM, display_name="Лепило",
                          source=source, mode=MODE_ENFORCE, repository=ExplodingRepository))


def test_explicit_confirmation_creates_a_person():
    spy = SpyDb()
    outcome = run(create_entity(Ctx(), entity_type=models.ENTITY_PERSON,
                                display_name="Иван Иванов",
                                source=SOURCE_EXPLICIT_CONFIRMATION, mode=MODE_ENFORCE,
                                repository=MasterDataRepository("tenant-a", db=spy)))
    assert outcome.performed is True
    assert outcome.entity["entity_type"] == models.ENTITY_PERSON
    assert spy.collections["md_person"].inserted


# ---------------------------------------------------------------- model contract
def test_the_nine_canonical_types_of_flow_032():
    assert models.ENTITY_TYPES == {
        "person", "organization", "activity", "item", "asset_type",
        "physical_asset", "unit", "location", "tag",
    }


def test_collection_per_type():
    assert collection_name(models.ENTITY_PHYSICAL_ASSET) == "md_physical_asset"
    with pytest.raises(MasterDataInvalid):
        collection_name("nope")


def test_entity_starts_active_and_unmerged():
    e = models.build_entity(tenant_id="t", entity_type=models.ENTITY_UNIT, display_name="кг")
    assert e["status"] == models.STATUS_ACTIVE
    assert e["merged_into"] is None
    assert e["legacy_refs"] == []
    assert e["id"]


def test_legacy_refs_are_the_migration_bridge():
    ref = models.new_legacy_ref("counterparties", "old-id-1", org_id="org-7")
    e = models.build_entity(tenant_id="t", entity_type=models.ENTITY_ORGANIZATION,
                            display_name="Фирма", legacy_refs=[ref])
    assert e["legacy_refs"][0] == {"collection": "counterparties",
                                   "legacy_id": "old-id-1", "org_id": "org-7"}
    with pytest.raises(MasterDataInvalid):
        models.new_legacy_ref("", "x")


def test_build_entity_refuses_bad_input():
    with pytest.raises(MasterDataInvalid):
        models.build_entity(tenant_id="", entity_type=models.ENTITY_ITEM, display_name="x")
    with pytest.raises(MasterDataInvalid):
        models.build_entity(tenant_id="t", entity_type="nope", display_name="x")
    with pytest.raises(MasterDataInvalid):
        models.build_entity(tenant_id="t", entity_type=models.ENTITY_ITEM, display_name="   ")


def test_merged_status_must_point_somewhere():
    e = models.build_entity(tenant_id="t", entity_type=models.ENTITY_ITEM, display_name="x")
    e["status"] = models.STATUS_MERGED
    with pytest.raises(MasterDataInvalid):
        models.validate_entity(e)
    e["merged_into"] = "other-id"
    models.validate_entity(e)


def test_merged_into_is_invalid_while_active():
    e = models.build_entity(tenant_id="t", entity_type=models.ENTITY_ITEM, display_name="x")
    e["merged_into"] = "other-id"
    with pytest.raises(MasterDataInvalid):
        models.validate_entity(e)


# ================================================================= review round 1
# Three blockers found at fd5870b6: shadow performed a real write, enforce wrote
# without a canonical AuditEvent, and an explicit mode argument skipped
# validation entirely.

INVALID_MODES = ["offf", "", "   ", "ON", "enforced", "shadowy", "1",
                 0, 1, True, object(), ["off"], {"mode": "off"}, None.__class__]


# ---------------------------------------------------------------- BLOCKER 1: shadow
def test_shadow_performs_no_write(monkeypatch):
    monkeypatch.setattr(service, "_repository_for",
                        lambda ctx: (_ for _ in ()).throw(
                            AssertionError("shadow built a repository")))
    spy = SpyDb()
    outcome = run(create_entity(Ctx(db=spy), entity_type=models.ENTITY_ORGANIZATION,
                                display_name="Фирма ЕООД",
                                source=SOURCE_EXPLICIT_CONFIRMATION, mode=MODE_SHADOW))
    assert outcome.mode == MODE_SHADOW
    assert outcome.performed is False
    assert outcome.would_perform is True
    assert outcome.entity is None
    assert spy.collections == {}, "shadow opened a collection"


def test_shadow_does_not_use_a_supplied_repository():
    outcome = run(create_entity(Ctx(), entity_type=models.ENTITY_ITEM, display_name="Лепило",
                                source=SOURCE_EXPLICIT_CONFIRMATION, mode=MODE_SHADOW,
                                repository=ExplodingRepository))
    assert outcome.performed is False


def test_shadow_emits_no_audit_event(monkeypatch):
    import app.audit.store as store
    import app.audit.envelope as envelope

    def boom(*a, **kw):
        raise AssertionError("shadow emitted an AuditEvent")

    monkeypatch.setattr(store, "record_event", boom)
    monkeypatch.setattr(envelope, "build_event", boom)
    outcome = run(create_entity(Ctx(), entity_type=models.ENTITY_TAG, display_name="Електро",
                                source=SOURCE_EXPLICIT_CONFIRMATION, mode=MODE_SHADOW))
    assert outcome.performed is False


def test_shadow_opens_no_database_at_all():
    outcome = run(create_entity(Ctx(db=ExplodingDb()), entity_type=models.ENTITY_UNIT,
                                display_name="кг", source=SOURCE_EXPLICIT_CONFIRMATION,
                                mode=MODE_SHADOW))
    assert outcome.performed is False


def test_shadow_reports_a_refusal_instead_of_raising():
    """Shadow measures; it must never break a path that used to work."""
    outcome = run(create_entity(Ctx(), entity_type=models.ENTITY_PERSON,
                                display_name="Иван", source="advance", mode=MODE_SHADOW,
                                repository=ExplodingRepository))
    assert outcome.performed is False
    assert outcome.would_perform is False
    assert SOURCE_EXPLICIT_CONFIRMATION in outcome.reason


@pytest.mark.parametrize("ctx,why", [
    (None, "no context"),
    (LegacyCtx(), "legacy context"),
    (ActorlessCtx(), "no audit actor"),
])
def test_shadow_never_raises_for_a_bad_context(ctx, why):
    outcome = run(create_entity(ctx, entity_type=models.ENTITY_ITEM, display_name="x",
                                source=SOURCE_EXPLICIT_CONFIRMATION, mode=MODE_SHADOW,
                                repository=ExplodingRepository))
    assert outcome.performed is False
    assert outcome.would_perform is False, why


def test_shadow_read_returns_none_without_a_read(monkeypatch):
    """Documented behaviour: in shadow the canonical store holds nothing, so
    answering from it would hand the caller data the legacy path does not have."""
    monkeypatch.setattr(service, "_repository_for",
                        lambda ctx: (_ for _ in ()).throw(
                            AssertionError("shadow built a repository for a read")))
    assert run(get_entity(Ctx(), entity_type=models.ENTITY_PERSON, entity_id="x",
                          mode=MODE_SHADOW)) is None


# ---------------------------------------------------------------- BLOCKER 2: canonical audit
def test_enforce_write_emits_exactly_one_canonical_audit_event():
    spy = SpyDb()
    ctx = Ctx(db=spy)
    outcome = run(create_entity(ctx, entity_type=models.ENTITY_PERSON,
                                display_name="Иван Иванов",
                                source=SOURCE_EXPLICIT_CONFIRMATION, mode=MODE_ENFORCE,
                                repository=MasterDataRepository("tenant-a", db=spy)))
    assert outcome.performed is True
    events = spy.audit_events().inserted
    assert len(events) == 1, "expected exactly one canonical AuditEvent"
    event = events[0]
    assert event["tenant_id"] == "tenant-a"
    assert event["actor_id"] == "user-1"
    assert event["action"] == "master_data.person.created"
    assert event["entity_type"] == "master_data.person"
    assert event["entity_id"] == outcome.entity["id"]
    assert event["source_flow"] == service.SOURCE_FLOW
    assert event["source_channel"] == SOURCE_EXPLICIT_CONFIRMATION
    assert event.get("integrity_hash"), "the event was not chained by the canonical store"


def test_enforce_audit_failure_is_not_reported_as_success():
    spy = SpyDb(failing={"audit_events"})
    with pytest.raises(MasterDataAuditFailed) as exc:
        run(create_entity(Ctx(db=spy), entity_type=models.ENTITY_ITEM, display_name="Лепило",
                          source=SOURCE_EXPLICIT_CONFIRMATION, mode=MODE_ENFORCE,
                          repository=MasterDataRepository("tenant-a", db=spy)))
    assert "NOT successful" in str(exc.value)
    # the honest part: the record IS there, unaudited — the caller must not
    # treat the operation as done, and nothing is silently deleted
    assert spy.collections["md_item"].inserted


def test_enforce_refuses_when_the_context_has_no_audit_actor():
    with pytest.raises(MasterDataTenantContextMissing) as exc:
        run(create_entity(ActorlessCtx(), entity_type=models.ENTITY_ITEM, display_name="x",
                          source=SOURCE_EXPLICIT_CONFIRMATION, mode=MODE_ENFORCE,
                          repository=ExplodingRepository))
    assert "actor" in str(exc.value)


def test_no_audit_event_and_no_write_in_off_and_shadow():
    for mode in (MODE_OFF, MODE_SHADOW):
        spy = SpyDb()
        run(create_entity(Ctx(db=spy), entity_type=models.ENTITY_LOCATION,
                          display_name="Обект 1",
                          source=SOURCE_EXPLICIT_CONFIRMATION, mode=mode))
        assert spy.collections == {}, "%s touched a collection" % mode


# ---------------------------------------------------------------- BLOCKER 3: explicit mode
@pytest.mark.parametrize("bad", INVALID_MODES)
def test_invalid_explicit_mode_refuses_create_before_anything_happens(bad):
    with pytest.raises(MasterDataConfigError):
        run(create_entity(Ctx(db=ExplodingDb()), entity_type=models.ENTITY_ITEM,
                          display_name="Лепило", source=SOURCE_EXPLICIT_CONFIRMATION,
                          mode=bad, repository=ExplodingRepository))


@pytest.mark.parametrize("bad", INVALID_MODES)
def test_invalid_explicit_mode_refuses_read(bad):
    with pytest.raises(MasterDataConfigError):
        run(get_entity(Ctx(db=ExplodingDb()), entity_type=models.ENTITY_PERSON,
                       entity_id="x", mode=bad, repository=ExplodingRepository))


@pytest.mark.parametrize("bad", INVALID_MODES)
def test_invalid_explicit_mode_refuses_is_off(bad):
    with pytest.raises(MasterDataConfigError):
        deps.is_off(bad)


def test_is_off_no_longer_answers_false_for_a_typo():
    """The old bypass: is_off("offf") said False and the caller believed the
    feature was switched on."""
    with pytest.raises(MasterDataConfigError):
        deps.is_off("offf")
    assert deps.is_off(MODE_OFF) is True
    assert deps.is_off(MODE_ENFORCE) is False


def test_mode_none_means_read_the_environment(monkeypatch):
    monkeypatch.delenv(ENV_MODE, raising=False)
    assert deps.resolve_mode(None) == MODE_OFF
    monkeypatch.setenv(ENV_MODE, "shadow")
    assert deps.resolve_mode(None) == MODE_SHADOW
    monkeypatch.setenv(ENV_MODE, "offf")
    with pytest.raises(MasterDataConfigError):
        deps.resolve_mode(None)


def test_empty_explicit_mode_is_not_treated_as_absent(monkeypatch):
    """Truthiness was the bug: `mode or current_mode()` let an empty string fall
    through to the environment instead of being refused."""
    monkeypatch.setenv(ENV_MODE, "enforce")
    with pytest.raises(MasterDataConfigError):
        deps.resolve_mode("")
