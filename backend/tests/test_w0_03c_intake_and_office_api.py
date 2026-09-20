"""
W0-03C — the real automated intake paths, and the office API behind the screen.

Two halves, both about the same promise: **an automated channel proposes and a
person decides**.

The intake half takes the shapes the existing code really produces — КСС rows
parsed out of a spreadsheet, the JSON an AI returns for a photo of a machine —
and asserts that feeding them through the hooks creates proposals and *only*
proposals: no Master record, no alias, no merge, not even when the text matches
an existing record exactly. It also asserts the properties that make a hook
safe to hang off somebody else's endpoint: off does nothing, shadow writes
nothing, a repeat is counted rather than duplicated, and a failure inside the
hook never reaches the caller.

The API half drives the six endpoints the office screen uses, over HTTP,
through the real guard: the queue, the candidates, mapping to an existing
record, creating a new one, and rejecting. What the screen sends is what these
tests send.

Run:  pytest tests/test_w0_03c_intake_and_office_api.py -v --noconftest
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.deps.auth import get_current_user
from app.master_data import intake_hooks, models, pending as pending_mod, review, service
from app.master_data.deps import ENV_MODE
from app.master_data.pending import PENDING_COLLECTION, STATUS_PENDING, STATUS_RESOLVED
from app.master_data.repository import MasterDataRepository
from app.routes import master_data as routes

from tests.test_w0_03b3_review_and_matching import Ctx, SpyDb, run

ACTIVITY = models.ENTITY_ACTIVITY
UNIT = models.ENTITY_UNIT
ASSET_TYPE = models.ENTITY_ASSET_TYPE
ORG = models.ENTITY_ORGANIZATION
ENV_PERMISSION_MODE = "PERMISSION_SERVICE_MODE"

OFFICE = {"id": "office-1", "role": "office"}

#: The shape ``services/excel_import.import_kss_from_excel`` really returns.
KSS_LINES = [
    {"line_id": "l-1", "smr_type": "Зидария с тухли", "unit": "м2", "qty": 120.0},
    {"line_id": "l-2", "smr_type": "Шпакловка стени", "unit": "м2", "qty": 300.0},
    {"line_id": "l-3", "smr_type": "Зидария с тухли", "unit": "м2", "qty": 40.0},
]

#: The shape ``routes/assets_ai_intake.ai_intake`` really returns.
AI_ASSET = {
    "name": "Ъглошлайф Bosch GWS 750",
    "type": "tool",
    "group": "Ъглошлайфи",
    "brand": "Bosch",
    "confidence": 88,
}


@pytest.fixture
def wired(monkeypatch):
    """A tenant context the hooks resolve to, backed by a spy database."""
    db = SpyDb()
    ctx = Ctx("tenant-a", user_id="office-1", db=db)

    async def resolved(user):
        return ctx

    monkeypatch.setattr(intake_hooks, "_context_for", resolved)
    monkeypatch.setattr(pending_mod, "_repository_for",
                        lambda c: MasterDataRepository(c.tenant_id, db=db))
    monkeypatch.setattr(review, "_repository_for",
                        lambda c: MasterDataRepository(c.tenant_id, db=db))
    monkeypatch.setattr(service, "_repository_for",
                        lambda c: MasterDataRepository(c.tenant_id, db=db))
    return db, ctx


def rows(db, entity_type=None):
    coll = db.collections.get(PENDING_COLLECTION)
    docs = coll.docs if coll else []
    return [d for d in docs if entity_type is None or d["entity_type"] == entity_type]


def actions(db):
    return [e["action"] for e in (db.audit().docs if db.audit() else [])]


def master_docs(db, entity_type):
    coll = db.master(entity_type)
    return coll.docs if coll else []


def no_master_anywhere(db):
    return [name for name in db.collections
            if name.startswith("md_") and name != PENDING_COLLECTION
            and db.collections[name].docs]


# ===========================================================================
# 1. Excel: a spreadsheet names identities in free text
# ===========================================================================

def test_an_excel_import_proposes_the_identities_its_rows_name(monkeypatch, wired):
    monkeypatch.setenv(ENV_MODE, "enforce")
    db, _ = wired

    summary = run(intake_hooks.observe_excel_kss_lines(
        OFFICE, KSS_LINES, source_ref="smr-analysis:a-1"))

    # A КСС row names two of the nine canonical types: the work and its unit.
    assert summary == {"observed": 3, "recorded": 3, "repeated": 0, "failed": 0}
    assert sorted(r["raw_value"] for r in rows(db, ACTIVITY)) == \
        ["Зидария с тухли", "Шпакловка стени"]
    assert [r["raw_value"] for r in rows(db, UNIT)] == ["м2"]
    # The third row repeats the first; one proposal, not two.
    assert all(r["source_channel"] == "excel" for r in rows(db))
    assert all(r["source_ref"] == "smr-analysis:a-1" for r in rows(db))


def test_an_excel_import_creates_no_master_record_and_no_alias(monkeypatch, wired):
    monkeypatch.setenv(ENV_MODE, "enforce")
    db, ctx = wired
    repo = MasterDataRepository("tenant-a", db=db)
    existing = models.build_entity(tenant_id="tenant-a", entity_type=ACTIVITY,
                                   display_name="Зидария с тухли")
    run(repo.create(existing))

    run(intake_hooks.observe_excel_kss_lines(OFFICE, KSS_LINES, source_ref="smr-analysis:a-1"))

    # The text matches the existing record exactly. It is still only a proposal.
    assert len(master_docs(db, ACTIVITY)) == 1
    assert master_docs(db, ACTIVITY)[0]["aliases"] == []
    assert master_docs(db, ACTIVITY)[0]["id"] == existing["id"]
    assert all(r["resolved_entity_id"] is None for r in rows(db, ACTIVITY))
    assert "master_data.activity.created" not in actions(db)


def test_re_importing_the_same_spreadsheet_counts_instead_of_duplicating(monkeypatch, wired):
    monkeypatch.setenv(ENV_MODE, "enforce")
    db, _ = wired

    first = run(intake_hooks.observe_excel_kss_lines(OFFICE, KSS_LINES, source_ref="smr-analysis:a-1"))
    second = run(intake_hooks.observe_excel_kss_lines(OFFICE, KSS_LINES, source_ref="smr-analysis:a-2"))

    assert first["recorded"] == 3 and first["repeated"] == 0
    assert second["recorded"] == 0 and second["repeated"] == 3
    assert len(rows(db)) == 3, "the office was handed the same decision twice"
    assert sorted(r["occurrences"] for r in rows(db)) == [2, 2, 2]
    # One proposal, one event. A repeated sighting is not a new business fact.
    assert actions(db).count("master_data.pending.proposed") == 3


def test_an_excel_import_never_merges_two_different_firms(monkeypatch, wired):
    """FLOW-032 Q7b: no transliteration, no fuzzy. Different names stay different."""
    monkeypatch.setenv(ENV_MODE, "enforce")
    db, _ = wired

    run(intake_hooks.observe_excel_kss_lines(OFFICE, [
        {"smr_type": "Строй ЕООД", "unit": "бр"},
        {"smr_type": "Строй АД", "unit": "бр"},
        {"smr_type": "Stroy", "unit": "бр"},
    ], source_ref="smr-analysis:a-1"))

    proposed = sorted(r["raw_value"] for r in rows(db, ACTIVITY))
    assert proposed == ["Stroy", "Строй АД", "Строй ЕООД"], \
        "two of these were treated as the same identity"
    assert len({r["normalized_value"] for r in rows(db, ACTIVITY)}) == 3


def test_the_historical_import_path_proposes_its_own_field_names(monkeypatch, wired):
    monkeypatch.setenv(ENV_MODE, "enforce")
    db, _ = wired

    run(intake_hooks.observe_excel_historical_lines(OFFICE, [
        {"raw_smr_text": "Полагане на замазка", "unit": "м2"},
    ], source_ref="historical-import:b-1"))

    assert [r["raw_value"] for r in rows(db, ACTIVITY)] == ["Полагане на замазка"]
    assert [r["raw_value"] for r in rows(db, UNIT)] == ["м2"]


def test_one_import_cannot_flood_the_queue(monkeypatch, wired):
    monkeypatch.setenv(ENV_MODE, "enforce")
    db, _ = wired
    huge = [{"smr_type": "Дейност %d" % i, "unit": "бр"} for i in range(500)]

    summary = run(intake_hooks.observe_excel_kss_lines(OFFICE, huge, source_ref="x"))

    assert summary["observed"] == intake_hooks.MAX_PER_IMPORT
    assert len(rows(db)) == intake_hooks.MAX_PER_IMPORT


# ===========================================================================
# 2. AI asset recognition
# ===========================================================================

def test_ai_asset_recognition_proposes_the_kind_of_equipment(monkeypatch, wired):
    monkeypatch.setenv(ENV_MODE, "enforce")
    db, _ = wired

    summary = run(intake_hooks.observe_ai_asset(
        OFFICE, AI_ASSET, source_ref="assets-ai-intake:s-1"))

    assert summary == {"observed": 1, "recorded": 1, "repeated": 0, "failed": 0}
    row = rows(db, ASSET_TYPE)[0]
    assert row["raw_value"] == "Ъглошлайф Bosch GWS 750"
    assert row["source_channel"] == "ai"
    assert not no_master_anywhere(db), "AI recognition created a Master record"


def test_an_ai_proposal_names_its_model(monkeypatch, wired):
    """FLOW-040 §4.4: an ACTOR_AI event without a model is refused, so the hook
    has to carry one rather than let the proposal be attributed to nobody."""
    monkeypatch.setenv(ENV_MODE, "enforce")
    db, _ = wired

    run(intake_hooks.observe_ai_asset(OFFICE, AI_ASSET, source_ref="assets-ai-intake:s-1"))

    event = [e for e in db.audit().docs if e["action"] == "master_data.pending.proposed"][0]
    assert event["actor_type"] == "ai"
    assert event["model_and_version"] == intake_hooks.ASSET_AI_MODEL
    assert event["confirmation_required"] is False


def test_the_same_photo_recognised_twice_leaves_one_proposal(monkeypatch, wired):
    monkeypatch.setenv(ENV_MODE, "enforce")
    db, _ = wired

    run(intake_hooks.observe_ai_asset(OFFICE, AI_ASSET, source_ref="assets-ai-intake:s-1"))
    second = run(intake_hooks.observe_ai_asset(OFFICE, AI_ASSET, source_ref="assets-ai-intake:s-2"))

    assert second["repeated"] == 1 and second["recorded"] == 0
    assert len(rows(db, ASSET_TYPE)) == 1
    assert rows(db, ASSET_TYPE)[0]["occurrences"] == 2


def test_a_recognition_without_a_name_proposes_nothing(monkeypatch, wired):
    monkeypatch.setenv(ENV_MODE, "enforce")
    db, _ = wired
    for suggestion in (None, {}, {"name": ""}, {"name": "   "}):
        assert run(intake_hooks.observe_ai_asset(OFFICE, suggestion)) is None
    assert rows(db) == []


# ===========================================================================
# 3. the properties that make a hook safe to hang off somebody else's endpoint
# ===========================================================================

def test_every_hook_is_inert_while_master_data_is_off(monkeypatch):
    monkeypatch.delenv(ENV_MODE, raising=False)

    async def boom(*a, **kw):
        raise AssertionError("a hook resolved a tenant while off")

    monkeypatch.setattr(intake_hooks, "_context_for", boom)
    monkeypatch.setattr("app.master_data.pending.propose", boom)

    assert run(intake_hooks.observe_excel_kss_lines(OFFICE, KSS_LINES)) is None
    assert run(intake_hooks.observe_excel_historical_lines(OFFICE, [{"raw_smr_text": "x"}])) is None
    assert run(intake_hooks.observe_ai_asset(OFFICE, AI_ASSET)) is None
    assert run(intake_hooks.observe_ocr_supplier(OFFICE, {"supplier_name": "Баумит"})) is None


def test_shadow_observes_the_import_and_writes_nothing(monkeypatch, wired):
    monkeypatch.setenv(ENV_MODE, "shadow")
    db, _ = wired

    summary = run(intake_hooks.observe_excel_kss_lines(OFFICE, KSS_LINES, source_ref="s"))

    assert summary["observed"] == 3
    assert summary["recorded"] == 0, "shadow wrote a proposal"
    assert db.collections == {}, "shadow touched the database"


def test_an_unusable_mode_does_not_break_an_import(monkeypatch):
    monkeypatch.setenv(ENV_MODE, "offf")

    async def boom(*a, **kw):
        raise AssertionError("an unusable mode still resolved a tenant")

    monkeypatch.setattr(intake_hooks, "_context_for", boom)
    assert run(intake_hooks.observe_excel_kss_lines(OFFICE, KSS_LINES)) is None


def test_a_failing_hook_never_reaches_the_importer(monkeypatch, wired):
    """An Excel import must not fail because an observation could not be
    recorded. That would be a worse bug than the one the hook helps with."""
    monkeypatch.setenv(ENV_MODE, "enforce")

    async def boom(*a, **kw):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(intake_hooks, "_context_for", boom)
    assert run(intake_hooks.observe_excel_kss_lines(OFFICE, KSS_LINES)) is None
    assert run(intake_hooks.observe_ai_asset(OFFICE, AI_ASSET)) is None


def test_one_bad_row_does_not_cost_the_rest_of_the_import(monkeypatch, wired):
    monkeypatch.setenv(ENV_MODE, "enforce")
    db, _ = wired
    real_propose = pending_mod.propose

    async def fails_for_one(ctx, **kwargs):
        if kwargs.get("raw_value") == "Непоносим ред":
            raise RuntimeError("simulated storage failure")
        return await real_propose(ctx, **kwargs)

    monkeypatch.setattr(pending_mod, "propose", fails_for_one)
    lines = [{"smr_type": "Зидария", "unit": "м2"},
             {"smr_type": "Непоносим ред", "unit": "м2"},
             {"smr_type": "Шпакловка", "unit": "м2"}]

    summary = run(intake_hooks.observe_excel_kss_lines(OFFICE, lines, source_ref="s"))

    assert summary["failed"] == 1
    assert summary["recorded"] == 3          # two activities plus the unit
    assert sorted(r["raw_value"] for r in rows(db, ACTIVITY)) == ["Зидария", "Шпакловка"]


def test_a_hook_without_a_resolvable_tenant_records_nothing(monkeypatch, wired):
    monkeypatch.setenv(ENV_MODE, "enforce")
    db, _ = wired

    async def unresolved(user):
        return None

    monkeypatch.setattr(intake_hooks, "_context_for", unresolved)
    assert run(intake_hooks.observe_excel_kss_lines(OFFICE, KSS_LINES)) is None
    assert rows(db) == []


# ===========================================================================
# 4. intake -> the office -> an official record
# ===========================================================================

def test_an_excel_row_becomes_a_master_record_only_through_a_person(monkeypatch, wired):
    monkeypatch.setenv(ENV_MODE, "enforce")
    db, ctx = wired

    run(intake_hooks.observe_excel_kss_lines(OFFICE, KSS_LINES, source_ref="smr-analysis:a-1"))
    assert not no_master_anywhere(db)

    queue = run(review.list_pending(ctx, entity_type=ACTIVITY, mode="enforce"))
    target = [q for q in queue if q["raw_value"] == "Зидария с тухли"][0]

    outcome = run(review.approve(ctx, pending_id=target["id"], confirmation=True,
                                 create_new=True, display_name="Зидария с тухли",
                                 mode="enforce"))

    assert outcome.performed and outcome.created_master
    assert len(master_docs(db, ACTIVITY)) == 1
    assert actions(db).count("master_data.activity.created") == 1
    assert [r for r in rows(db, ACTIVITY)
            if r["id"] == target["id"]][0]["status"] == STATUS_RESOLVED


def test_an_ai_asset_proposal_becomes_a_master_record_only_through_a_person(monkeypatch, wired):
    monkeypatch.setenv(ENV_MODE, "enforce")
    db, ctx = wired

    run(intake_hooks.observe_ai_asset(OFFICE, AI_ASSET, source_ref="assets-ai-intake:s-1"))
    row = rows(db, ASSET_TYPE)[0]

    outcome = run(review.approve(ctx, pending_id=row["id"], confirmation=True,
                                 create_new=True, display_name="Ъглошлайф Bosch GWS 750",
                                 mode="enforce"))

    assert outcome.performed and outcome.created_master
    assert len(master_docs(db, ASSET_TYPE)) == 1
    human = [e for e in db.audit().docs if e["action"] == "master_data.pending.approved"]
    assert len(human) == 1 and human[0]["actor_type"] == "human"


def test_an_automated_caller_cannot_approve_its_own_proposal(monkeypatch, wired):
    monkeypatch.setenv(ENV_MODE, "enforce")
    db, ctx = wired
    run(intake_hooks.observe_ai_asset(OFFICE, AI_ASSET, source_ref="s"))
    row = rows(db, ASSET_TYPE)[0]

    with pytest.raises(service.MasterDataRefused):
        run(review.approve(ctx, pending_id=row["id"], confirmation=False,
                           create_new=True, mode="enforce"))
    assert not master_docs(db, ASSET_TYPE)


def test_a_proposal_of_one_tenant_is_invisible_to_another(monkeypatch, wired):
    monkeypatch.setenv(ENV_MODE, "enforce")
    db, _ = wired
    run(intake_hooks.observe_ai_asset(OFFICE, AI_ASSET, source_ref="s"))
    row = rows(db, ASSET_TYPE)[0]

    other = Ctx("tenant-b", user_id="office-b", db=db)
    other_repo = MasterDataRepository("tenant-b", db=db)

    assert run(review.list_pending(other, entity_type=ASSET_TYPE, mode="enforce",
                                   repository=other_repo)) == []
    with pytest.raises(service.MasterDataRefused):
        run(review.approve(other, pending_id=row["id"], confirmation=True, create_new=True,
                           mode="enforce", repository=other_repo))
    assert not master_docs(db, ASSET_TYPE)


# ===========================================================================
# 5. the office API, over HTTP, exactly as the screen calls it
# ===========================================================================

@pytest.fixture
def office_client(monkeypatch, wired):
    db, ctx = wired
    monkeypatch.setenv(ENV_MODE, "enforce")
    monkeypatch.setenv(ENV_PERMISSION_MODE, "off")

    async def resolved(request, user):
        return ctx

    monkeypatch.setattr(routes, "get_tenant_context", resolved)

    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    async def session_user():
        return dict(OFFICE)

    app.dependency_overrides[get_current_user] = session_user
    return TestClient(app, raise_server_exceptions=False), db, ctx


def test_the_screen_can_walk_a_proposal_all_the_way_to_a_record(office_client):
    client, db, _ = office_client
    run(intake_hooks.observe_excel_kss_lines(OFFICE, KSS_LINES, source_ref="smr-analysis:a-1"))

    queue = client.get("/api/master-data/pending?entity_type=activity").json()
    assert queue["mode"] == "enforce" and queue["count"] == 2
    target = [q for q in queue["items"] if q["raw_value"] == "Зидария с тухли"][0]
    # Two rows of the spreadsheet named it; the office gets one thing to decide.
    assert len([l for l in KSS_LINES if l["smr_type"] == "Зидария с тухли"]) == 2
    assert target["occurrences"] == 1 and target["source_channel"] == "excel"

    candidates = client.get("/api/master-data/pending/%s/matches" % target["id"]).json()
    assert candidates["count"] == 0

    approved = client.post("/api/master-data/pending/%s/approve" % target["id"],
                           json={"confirmation": True, "create_new": True,
                                 "display_name": "Зидария с тухли"}).json()
    assert approved["performed"] is True and approved["created_master"] is True

    entity = client.get("/api/master-data/activity/%s" % approved["entity_id"]).json()
    assert entity["display_name"] == "Зидария с тухли"

    still_open = client.get("/api/master-data/pending?entity_type=activity").json()
    assert [q["raw_value"] for q in still_open["items"]] == ["Шпакловка стени"]
    done = client.get("/api/master-data/pending?status=resolved").json()
    assert done["items"][0]["resolved_by"] == "office-1"


def test_the_screen_can_map_a_second_spelling_onto_the_same_record(office_client):
    client, db, _ = office_client
    run(intake_hooks.observe_excel_kss_lines(
        OFFICE, [{"smr_type": "Зидария с тухли", "unit": "м2"}], source_ref="a-1"))
    first = client.get("/api/master-data/pending?entity_type=activity").json()["items"][0]
    created = client.post("/api/master-data/pending/%s/approve" % first["id"],
                          json={"confirmation": True, "create_new": True,
                                "display_name": "Зидария с тухли"}).json()

    run(intake_hooks.observe_excel_kss_lines(
        OFFICE, [{"smr_type": "  ЗИДАРИЯ,  С ТУХЛИ. ", "unit": "м2"}], source_ref="a-2"))
    second = [q for q in client.get("/api/master-data/pending?entity_type=activity").json()["items"]
              if q["raw_value"] != "Зидария с тухли"][0]

    # It normalizes onto the record — and is still only shown, not applied.
    shown = client.get("/api/master-data/pending/%s/matches" % second["id"]).json()
    assert shown["candidates"][0]["entity_id"] == created["entity_id"]
    assert "human decision" in shown["note"]
    assert [r for r in rows(db, ACTIVITY) if r["id"] == second["id"]][0]["status"] == STATUS_PENDING

    mapped = client.post("/api/master-data/pending/%s/approve" % second["id"],
                         json={"confirmation": True,
                               "canonical_entity_id": created["entity_id"]}).json()
    assert mapped["created_master"] is False
    assert len(master_docs(db, ACTIVITY)) == 1
    assert len(master_docs(db, ACTIVITY)[0]["aliases"]) == 1


def test_the_screen_can_look_a_record_up_by_a_spelling_a_person_types(office_client):
    client, db, _ = office_client
    repo = MasterDataRepository("tenant-a", db=db)
    run(repo.create(models.build_entity(tenant_id="tenant-a", entity_type=ACTIVITY,
                                        display_name="Зидария с газобетон")))
    run(intake_hooks.observe_excel_kss_lines(
        OFFICE, [{"smr_type": "Зид. газобетон", "unit": "м2"}], source_ref="a-1"))
    row = [q for q in client.get("/api/master-data/pending?entity_type=activity").json()["items"]
           if q["entity_type"] == ACTIVITY][0]

    # Nothing matches automatically — the spellings do not normalize alike.
    assert client.get("/api/master-data/pending/%s/matches" % row["id"]).json()["count"] == 0

    found = client.get("/api/master-data/pending/%s/matches?q=Зидария" % row["id"]).json()
    assert found["count"] == 1
    assert found["candidates"][0]["match_type"] == "human_lookup"
    assert found["candidates"][0]["score"] is None


def test_the_screen_can_reject_and_master_data_stays_untouched(office_client):
    client, db, _ = office_client
    run(intake_hooks.observe_ai_asset(OFFICE, AI_ASSET, source_ref="s"))
    row = client.get("/api/master-data/pending?entity_type=asset_type").json()["items"][0]

    rejected = client.post("/api/master-data/pending/%s/reject" % row["id"],
                           json={"reason": "не е техника, а консуматив"}).json()

    assert rejected["performed"] is True
    assert not no_master_anywhere(db)
    closed = client.get("/api/master-data/pending?status=rejected").json()["items"][0]
    assert closed["rejection_reason"] == "не е техника, а консуматив"
    assert closed["resolved_by"] == "office-1"


def test_the_queue_can_be_filtered_by_source_the_way_the_screen_does(office_client):
    client, _, _ = office_client
    run(intake_hooks.observe_excel_kss_lines(OFFICE, KSS_LINES, source_ref="a-1"))
    run(intake_hooks.observe_ai_asset(OFFICE, AI_ASSET, source_ref="s-1"))

    excel = client.get("/api/master-data/pending?source_channel=excel").json()
    ai = client.get("/api/master-data/pending?source_channel=ai").json()

    assert excel["count"] == 3 and all(i["source_channel"] == "excel" for i in excel["items"])
    assert ai["count"] == 1 and ai["items"][0]["source_channel"] == "ai"
    assert client.get("/api/master-data/pending?source_channel=carrier-pigeon").status_code == 400


def test_a_role_that_may_not_decide_cannot_reach_the_screens_endpoints(office_client,
                                                                      monkeypatch):
    client, db, _ = office_client
    run(intake_hooks.observe_ai_asset(OFFICE, AI_ASSET, source_ref="s"))
    row = rows(db, ASSET_TYPE)[0]

    driver = FastAPI()
    driver.include_router(routes.router, prefix="/api")

    async def field_user():
        return {"id": "u-driver", "role": "Driver"}

    driver.dependency_overrides[get_current_user] = field_user
    field = TestClient(driver, raise_server_exceptions=False)

    assert field.get("/api/master-data/pending").status_code == 403
    assert field.post("/api/master-data/pending/%s/approve" % row["id"],
                      json={"confirmation": True, "create_new": True}).status_code == 403
    assert field.post("/api/master-data/pending/%s/reject" % row["id"],
                      json={"reason": "x"}).status_code == 403
    assert not master_docs(db, ASSET_TYPE)


def test_a_tenant_in_the_query_string_never_becomes_the_tenant(office_client):
    """The screen sends no tenant; a client that tries anyway is not obeyed."""
    client, db, _ = office_client
    run(intake_hooks.observe_ai_asset(OFFICE, AI_ASSET, source_ref="s"))

    answered = client.get("/api/master-data/pending?tenant_id=tenant-b&entity_type=asset_type")

    assert answered.status_code == 200
    # It answered from the resolved tenant, not the one in the URL.
    assert answered.json()["items"][0]["tenant_id"] == "tenant-a"
