"""
W0-03E / C02 — bounded correction of the two C01 review findings.

Finding 1 — financial recipient identity (§4.5). In MASTER_DATA_MODE=enforce a
new advance or loan must refer to ONE proven canonical Master Person. Every
recipient field the caller supplies — ``user_id``, ``person_id``,
``guest_name`` — must describe that person, or the request is refused before
anything (advance or payment) is written, with a canonical denial AuditEvent:

  * an unmapped ``user_id`` plus a different, valid ``person_id``;
  * a ``guest_name`` that is not the person's official name or confirmed alias;
  * a mapped employee versus a different canonical person;
  * an unknown employee id.
Same-person requests and old ``guest_name`` advances keep working unchanged.

Finding 2 — adapter coverage of the identity-bearing import, export, report
and AI-adjacent paths (inventory: docs/architecture/W0-03E_LEGACY_MIGRATION.md
§11). Reports and AI outputs keep every old id and, in enforce only, gain a
tenant-bound ``*_master_ref``; their identity look-ups are scoped to the tenant
in every mode; an identity id handed to the OCR/AI path must belong to the
tenant; imported free text only ever becomes a pending proposal; a legacy
identity created after a migration is accounted for and planned with its old id.

Run:  pytest tests/test_w0_03e_c02_corrections.py -v --noconftest
"""
import json
import sys
import types

import pytest

from app.audit.store import AUDIT_COLLECTION
from app.master_data import intake_hooks
from app.master_data import legacy_adapter as la
from app.master_data import legacy_migration as lm
from app.master_data.deps import ENV_MODE
from app.master_data.models import new_alias
from app.routes import (
    asset_item_types, assets_batch_intake, assets_intake_pending, hr, ocr_invoice, offers,
    projects, reports,
)

from tests.test_w0_03e_legacy_migration import ORG_A, ORG_B, T_A, Ctx, dry, go, repo, run, seeded
from tests.test_w0_03e_legacy_routes import ADMIN, client_for, enforce_with, find_all, landmines


# ================================================================ fixtures
async def _world():
    db = await seeded()
    p = await dry(db)
    await go(db, p["plan_token"])
    await db["financial_accounts"].insert_one({"id": "acc-cash", "org_id": ORG_A, "type": "cash"})
    return db


def world():
    return run(_world())


def canonical(ctx, db, collection, legacy_id):
    return run(la.resolve_legacy(ctx, collection=collection, legacy_id=legacy_id, mode="enforce",
                                 repository=repo(db)))["canonical_id"]


def _advance(monkeypatch, db, body):
    return client_for(monkeypatch, hr, db, ADMIN).post("/api/advances", json=body)


def hooks_into(monkeypatch, db, ctx):
    """Point the intake hooks at this tenant and this database (the W0-01 guard
    and resolver are what the running application would use)."""
    from app.master_data import pending

    async def resolved(user):
        return ctx
    monkeypatch.setattr(intake_hooks, "_context_for", resolved)
    monkeypatch.setattr(pending, "_repository_for", lambda c: repo(db, c.tenant_id))


def _writes(db):
    return (run(db["advances"].count_documents({})),
            run(db["finance_payments"].count_documents({})))


# ================================================================ finding 1
@pytest.mark.parametrize("case", ["unmapped_user_plus_valid_person", "unknown_user_plus_valid_person",
                                  "contradictory_guest_name", "mapped_user_vs_other_person",
                                  "guest_name_vs_mapped_user", "guest_name_alone",
                                  "unmapped_user_alone"])
def test_contradictory_or_unproven_recipients_are_refused_before_any_write(monkeypatch, case):
    db = world()
    ctx = enforce_with(monkeypatch, db)
    u1, u3 = canonical(ctx, db, "users", "u1"), canonical(ctx, db, "users", "u3")
    body, code = {
        "unmapped_user_plus_valid_person": (
            {"type": "Advance", "user_id": "u2", "person_id": u1}, la.REASON_ADVANCE_UNMAPPED),
        "unknown_user_plus_valid_person": (
            {"type": "Advance", "user_id": "u-ghost", "person_id": u1}, la.REASON_ADVANCE_UNMAPPED),
        "contradictory_guest_name": (
            {"type": "Loan", "guest_name": "Different Guest", "person_id": u1},
            la.REASON_ADVANCE_NAME_CONFLICT),
        "mapped_user_vs_other_person": (
            {"type": "Advance", "user_id": "u1", "person_id": u3}, la.REASON_ADVANCE_MISMATCH),
        "guest_name_vs_mapped_user": (
            {"type": "Loan", "user_id": "u1", "guest_name": "Георги Иванов"},
            la.REASON_ADVANCE_NAME_CONFLICT),
        "guest_name_alone": (
            {"type": "Loan", "guest_name": "Мария Георгиева"}, la.REASON_ADVANCE_PERSON),
        "unmapped_user_alone": ({"type": "Advance", "user_id": "u2"}, la.REASON_ADVANCE_UNMAPPED),
    }[case]
    body.update(amount=10, account_id="acc-cash")        # a payment would follow a success
    before = _writes(db)
    old = run(find_all(db, "advances"))
    persons_before = run(db["md_person"].count_documents({}))
    r = _advance(monkeypatch, db, body)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["error_code"] == code
    assert _writes(db) == before, "an advance or a payment was written on refusal"
    assert run(find_all(db, "advances")) == old
    assert run(db["md_person"].count_documents({})) == persons_before   # no person invented
    event = run(find_all(db, AUDIT_COLLECTION))[-1]
    assert event["action"] == "master_data.advance.create_refused"
    assert event["result"] == "denied" and event["error_code"] == code
    assert event["tenant_id"] == T_A and event["actor_id"] == "owner-1"
    assert "Different Guest" not in json.dumps(event, ensure_ascii=False)   # no raw name in audit


def test_the_same_person_through_every_field_is_accepted_with_its_payment(monkeypatch):
    db = world()
    ctx = enforce_with(monkeypatch, db)
    u1 = canonical(ctx, db, "users", "u1")
    run(db["md_person"].update_one({"id": u1}, {"$push": {"aliases": new_alias(
        "Ванката", added_by="office-1")}}))
    accepted = [
        {"type": "Advance", "user_id": "u1", "account_id": "acc-cash"},
        {"type": "Advance", "user_id": "u1", "person_id": u1},
        {"type": "Loan", "person_id": u1},
        {"type": "Loan", "person_id": u1, "guest_name": "  иван   ПЕТРОВ "},   # same normalized name
        {"type": "Loan", "person_id": u1, "guest_name": "Ванката"},            # confirmed alias
    ]
    for body in accepted:
        r = _advance(monkeypatch, db, dict(body, amount=10))
        assert r.status_code == 201, (body, r.text)
        assert r.json()["master_person_id"] == u1
    assert run(db["finance_payments"].count_documents({})) == 1
    old = run(db["advances"].find_one({"id": "adv2"}))
    assert old["guest_name"] == "Мария Георгиева" and "master_person_id" not in old


def test_a_person_id_of_a_merged_record_resolves_to_its_canonical_person(monkeypatch):
    from app.master_data import merge as mm
    from tests.test_w0_03d_merge_redirect import TrustedTestVerifier
    db = world()
    ctx = enforce_with(monkeypatch, db)
    u1, u3 = canonical(ctx, db, "users", "u1"), canonical(ctx, db, "users", "u3")
    prev = run(mm.preview_merge(Ctx(db), entity_type="person", source_id=u3, target_id=u1,
                                mode="enforce", repository=repo(db)))
    run(mm.merge(Ctx(db), entity_type="person", source_id=u3, target_id=u1,
                 preview_token=prev["preview_token"], idempotency_key="m", confirmation=True,
                 approval_id="APR-m", mode="enforce", repository=repo(db),
                 approval_verifier=TrustedTestVerifier()))
    r = _advance(monkeypatch, db, {"type": "Advance", "user_id": "u1", "person_id": u3, "amount": 1})
    assert r.status_code == 201 and r.json()["master_person_id"] == u1


def test_off_and_shadow_keep_the_legacy_advance_behaviour(monkeypatch):
    for mode in ("off", "shadow"):
        db = world()
        monkeypatch.setenv(ENV_MODE, mode)
        touched = landmines(monkeypatch)
        r = _advance(monkeypatch, db, {"type": "Advance", "user_id": "u2", "person_id": "anything",
                                       "amount": 10})
        assert r.status_code == 201 and touched == []
        assert "master_person_id" not in r.json() and r.json()["user_id"] == "u2"
        monkeypatch.undo()


def test_existing_guest_name_advances_stay_readable(monkeypatch):
    db = world()
    enforce_with(monkeypatch, db)
    rows = client_for(monkeypatch, hr, db, ADMIN).get("/api/advances").json()
    adv2 = [a for a in rows if a["id"] == "adv2"][0]
    assert adv2["guest_name"] == "Мария Георгиева" and adv2["user_name"]


# ================================================================ finding 2 — reports
async def _report_world():
    db = await _world()
    await db["counterparties"].insert_one({"id": "cp-b", "org_id": ORG_B, "name": "Чужда фирма",
                                           "type": "client"})
    for inv in ({"id": "inv-a1", "supplier_counterparty_id": "cp1", "direction": "Received"},
                {"id": "inv-a2", "supplier_counterparty_id": "cp3", "direction": "Received"},
                {"id": "inv-a3", "supplier_counterparty_id": "cp-b", "direction": "Received"},
                {"id": "inv-a4", "supplier_counterparty_id": "cp3", "direction": "Issued"}):
        await db["invoices"].insert_one(dict(inv, org_id=ORG_A, issue_date="2026-09-01", total=10,
                                             subtotal=8, vat_amount=2, paid_amount=0,
                                             remaining_amount=10))
    await db["invoice_lines"].insert_one({"id": "l1", "org_id": ORG_A, "invoice_id": "inv-a1",
                                          "description": "Цимент", "purchased_by_user_id": "u1",
                                          "created_at": "2026-09-01", "allocations": []})
    return db


REPORTS = [("/api/reports/turnover-by-counterparty?type=purchases", "items", "counterparty_id"),
           ("/api/reports/turnover-by-client?type=sales", "items", "client_id"),
           ("/api/reports/turnover-by-counterparty/cp1/invoices", "items", "supplier_counterparty_id"),
           ("/api/prices", "items", "supplier_id")]


@pytest.mark.parametrize("url,key,field", REPORTS)
def test_reports_keep_old_ids_and_add_master_refs_only_in_enforce(monkeypatch, url, key, field):
    db = run(_report_world())
    monkeypatch.delenv(ENV_MODE, raising=False)
    touched = landmines(monkeypatch)
    off = client_for(monkeypatch, reports, db, ADMIN).get(url)
    assert off.status_code == 200, off.text
    assert touched == []
    rows = off.json()[key]
    assert rows and all(la.ref_key(field) not in r for r in rows)
    monkeypatch.undo()

    ctx = enforce_with(monkeypatch, db)
    on = client_for(monkeypatch, reports, db, ADMIN).get(url).json()
    by_id = {r[field]: r for r in on[key]}
    assert set(by_id) == {r[field] for r in rows}                    # the old ids, unchanged
    assert {"cp1", "cp3"} & set(by_id)
    if "cp1" in by_id:
        ref = by_id["cp1"][la.ref_key(field)]
        assert ref["status"] == "mapped"
        assert ref["canonical_id"] == canonical(ctx, db, "companies", "c1")
    if "cp3" in by_id:
        assert by_id["cp3"][la.ref_key(field)]["status"] == "pending"
    if "cp-b" in by_id:                         # another org's id: nothing is resolved for it
        assert by_id["cp-b"][la.ref_key(field)] == {"status": "unmigrated"}


def test_report_lookups_never_show_another_orgs_identity(monkeypatch):
    db = run(_report_world())
    for mode in ("off", "enforce"):
        if mode == "enforce":
            enforce_with(monkeypatch, db)
        else:
            monkeypatch.delenv(ENV_MODE, raising=False)
        data = client_for(monkeypatch, reports, db, ADMIN).get(
            "/api/reports/turnover-by-counterparty?type=purchases").json()
        foreign = [r for r in data["items"] if r["counterparty_id"] == "cp-b"][0]
        assert foreign["counterparty_name"] == "(Неизвестен)" and foreign["counterparty_eik"] is None
        client_rows = client_for(monkeypatch, reports, db, ADMIN).get(
            "/api/reports/turnover-by-client?type=purchases").json()["items"]
        assert all(r["client_id"] != "cp-b" for r in client_rows)
        drill = client_for(monkeypatch, reports, db, ADMIN).get(
            "/api/reports/turnover-by-counterparty/cp-b/invoices").json()
        assert drill["counterparty_name"] == "(Неизвестен)"


# ================================================================ finding 2 — OCR / AI
def _ocr_ready(monkeypatch, db):
    async def fake_intake(org_id, media_id, created_by, **kw):
        doc = {"id": "intake-1", "org_id": org_id, "media_id": media_id,
               "supplier_id": kw.get("supplier_id"),
               "detected_data": {"supplier_name": "Баумит ЕООД"}}
        await db["ocr_invoice_intake"].insert_one(dict(doc))
        return doc
    monkeypatch.setattr(ocr_invoice, "create_ocr_intake", fake_intake)
    run(db["media_files"].insert_one({"id": "m1", "org_id": ORG_A, "filename": "f.pdf"}))


def test_ocr_refuses_a_foreign_supplier_id_before_any_write(monkeypatch):
    db = world()
    _ocr_ready(monkeypatch, db)
    run(db["counterparties"].insert_one({"id": "cp-b", "org_id": ORG_B, "name": "B"}))
    enforce_with(monkeypatch, db)
    c = client_for(monkeypatch, ocr_invoice, db, ADMIN)
    for supplier in ("cp-b", "no-such"):
        r = c.post("/api/ocr-invoice/from-media", json={"media_id": "m1", "supplier_id": supplier})
        assert r.status_code == 404 and r.json()["detail"]["error_code"] == "IDENTITY_NOT_IN_TENANT"
    r = c.post("/api/ocr-invoice/upload", files={"file": ("a.pdf", b"x")}, data={"supplier_id": "cp-b"})
    assert r.status_code == 404
    assert run(db["ocr_invoice_intake"].count_documents({})) == 0
    assert run(db["media_files"].count_documents({})) == 1
    events = [e for e in run(find_all(db, AUDIT_COLLECTION))
              if e["action"] == "master_data.legacy.identity_refused"]
    assert len(events) == 3 and all(e["result"] == "denied" for e in events)


def test_ocr_keeps_the_supplier_id_adds_its_master_ref_and_only_proposes(monkeypatch):
    db = world()
    _ocr_ready(monkeypatch, db)
    ctx = enforce_with(monkeypatch, db)

    hooks_into(monkeypatch, db, ctx)
    masters = run(db["md_organization"].count_documents({}))
    r = client_for(monkeypatch, ocr_invoice, db, ADMIN).post(
        "/api/ocr-invoice/from-media", json={"media_id": "m1", "supplier_id": "cp1"})
    assert r.status_code == 201, r.text
    assert r.json()["supplier_id"] == "cp1"
    assert r.json()["supplier_master_ref"]["canonical_id"] == canonical(ctx, db, "companies", "c1")
    # the OCR text "Баумит ЕООД" equals an official name — and still only proposes
    assert run(db["md_organization"].count_documents({})) == masters
    rows = run(find_all(db, "md_pending_mapping"))
    assert [(p["raw_value"], p["source_channel"], p["resolved_entity_id"]) for p in rows] == [
        ("Баумит ЕООД", "ocr", None)]
    monkeypatch.undo()
    monkeypatch.delenv(ENV_MODE, raising=False)
    _ocr_ready(monkeypatch, db)
    r = client_for(monkeypatch, ocr_invoice, db, ADMIN).post(
        "/api/ocr-invoice/from-media", json={"media_id": "m1", "supplier_id": "cp-anything"})
    assert r.status_code == 201 and "supplier_master_ref" not in r.json()


def test_ai_batch_recognition_match_stays_a_suggestion_with_a_master_ref(monkeypatch):
    db = world()
    ctx = enforce_with(monkeypatch, db)

    hooks_into(monkeypatch, db, ctx)

    async def can_submit(user):
        return True
    monkeypatch.setattr(assets_intake_pending, "_can_submit", can_submit)
    monkeypatch.setattr(asset_item_types, "db", db)
    monkeypatch.setenv("EMERGENT_LLM_KEY", "test-only")
    answer = json.dumps({"name": "Bosch GBH", "brand": "Bosch", "model": "GBH",
                         "type_label": "Бормашини", "confidence": 90})

    class Chat:
        def __init__(self, **kw):
            pass

        def with_model(self, *a):
            return self

        async def send_message(self, msg):
            return answer
    fake = types.ModuleType("emergentintegrations.llm.chat")
    fake.LlmChat, fake.UserMessage, fake.ImageContent = Chat, (lambda **kw: kw), (lambda **kw: kw)
    for name in ("emergentintegrations", "emergentintegrations.llm"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "emergentintegrations.llm.chat", fake)
    run(db["asset_items"].update_one({"id": "ai1"}, {"$set": {"is_active": True}}))
    masters = run(db["md_asset_type"].count_documents({}))
    r = client_for(monkeypatch, assets_batch_intake, db, ADMIN).post(
        "/api/assets/batch-intake/recognize", json={"images_base64": ["x" * 200]})
    assert r.status_code == 200, r.text
    match = r.json()["matched_item"]
    assert match["id"] == "ai1"
    assert match["master_ref"]["canonical_id"] == canonical(ctx, db, "asset_items", "ai1")
    assert run(db["md_asset_type"].count_documents({})) == masters     # nothing created or linked
    pend = run(find_all(db, "md_pending_mapping"))
    assert [(p["source_channel"], p["entity_type"]) for p in pend] == [("ai", "asset_type")]


# ================================================================ finding 2 — imports
def test_client_invoice_import_names_the_owner_master_and_stays_scoped(monkeypatch):
    db = world()
    run(db["projects"].insert_one({"id": "pr1", "org_id": ORG_B, "owner_type": "company",
                                   "owner_id": "c-b"}))                  # same id, other org
    monkeypatch.delenv(ENV_MODE, raising=False)
    off = client_for(monkeypatch, projects, db, ADMIN).post("/api/projects/pr1/import-client-invoice")
    assert off.status_code == 200 and "owner_master_ref" not in off.json()
    ctx = enforce_with(monkeypatch, db)
    on = client_for(monkeypatch, projects, db, ADMIN).post("/api/projects/pr1/import-client-invoice")
    assert on.json()["owner_master_ref"]["canonical_id"] == canonical(ctx, db, "companies", "c1")
    assert on.json()["invoice_details"]["eik"] == "123456789"
    theirs = run(db["projects"].find_one({"org_id": ORG_B}))
    assert "invoice_details" not in theirs


def test_offer_import_only_proposes_its_free_text_identities(monkeypatch):
    db = world()
    run(db["projects"].insert_one({"id": "pr9", "org_id": ORG_A, "name": "P"}))
    ctx = enforce_with(monkeypatch, db)

    hooks_into(monkeypatch, db, ctx)
    activities = run(db["md_activity"].count_documents({}))
    body = {"project_id": "pr9", "file_name": "o.xlsx",
            "lines": [{"description": "Боядисване", "unit": "m2", "qty": 1},
                      {"description": "Нова дейност", "unit": "m2", "qty": 2}]}
    r = client_for(monkeypatch, offers, db, ADMIN).post("/api/offers/import-confirm", json=body)
    assert r.status_code == 201, r.text
    assert run(db["md_activity"].count_documents({})) == activities
    raw = sorted((p["entity_type"], p["raw_value"]) for p in run(find_all(db, "md_pending_mapping")))
    assert raw == [("activity", "Боядисване"), ("activity", "Нова дейност"), ("unit", "m2")]
    assert all(p["resolved_entity_id"] is None for p in run(find_all(db, "md_pending_mapping")))
    # an import proposes; it never adds an alias to the existing official activity
    w1 = run(db["md_activity"].find_one({"id": canonical(ctx, db, "work_types", "w1")}))
    assert w1["aliases"] == []


@pytest.mark.parametrize("hook,lines", [
    ("observe_excel_kss_lines", [{"smr_type": "Боядисване", "unit": "m2"}]),
    ("observe_excel_historical_lines", [{"raw_smr_text": "Боядисване", "unit": "m2"}]),
    ("observe_excel_offer_lines", [{"description": "Боядисване", "unit": "m2"}]),
])
def test_excel_import_hooks_stay_pending_only_after_a_migration(monkeypatch, hook, lines):
    db = world()
    ctx = enforce_with(monkeypatch, db)

    hooks_into(monkeypatch, db, ctx)
    before = {n: run(db[n].count_documents({})) for n in ("md_activity", "md_unit")}
    summary = run(getattr(intake_hooks, hook)(ADMIN, lines, source_ref="t"))
    assert summary["recorded"] == 2
    assert {n: run(db[n].count_documents({})) for n in before} == before
    monkeypatch.setenv(ENV_MODE, "off")
    assert run(getattr(intake_hooks, hook)(ADMIN, lines)) is None


def test_a_legacy_identity_created_after_a_migration_is_accounted_and_planned_with_its_old_id():
    async def body():
        db = await _world()
        # e.g. an approved asset intake or any legacy create route, after the run
        await db["asset_items"].insert_one({"id": "ai-new", "org_id": ORG_A, "name": "Makita HR",
                                            "brand": "Makita", "model": "HR"})
        report = await lm.reconcile(Ctx(db), mode="enforce", repository=repo(db))
        assert report["sources"]["asset_items"]["unmigrated"] == 1
        assert report["sources"]["asset_items"]["sample_unmigrated"] == ["ai-new"] and report["zero_lost"]
        plan = await dry(db)
        assert [(i["collection"], i["legacy_id"], i["decision"]) for i in plan["items"]] == [
            ("asset_items", "ai-new", "create")]
        out = await go(db, plan["plan_token"], key="run-2")
        assert out.performed
        r = await la.resolve_legacy(Ctx(db), collection="asset_items", legacy_id="ai-new",
                                    mode="enforce", repository=repo(db))
        assert r["canonical_id"] and r["entity"]["legacy_refs"][0]["legacy_id"] == "ai-new"
    run(body())
