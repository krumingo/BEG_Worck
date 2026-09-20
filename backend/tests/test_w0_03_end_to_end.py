"""
W0-03 — end-to-end: OCR text to an official Master record, through a human.

One test walks the whole chain the package was built for:

    OCR detects "Баумит ЕООД"
      → the legacy intake hook observes it (shadow: nothing written)
      → enforce: a pending proposal is recorded, no Master
      → the review queue shows it
      → matching finds no candidate yet
      → a person approves it as a NEW Master record
      → a second, differently spelled OCR text arrives
      → matching now finds nothing (different spelling)
      → the person maps it to the existing record
      → the spelling becomes a confirmed alias
      → the same text now resolves itself next time

Plus the two properties the legacy wiring must have: it is a no-op while the
feature is off, and it cannot fail the invoice upload it hangs off.

Run:  pytest tests/test_w0_03_end_to_end.py -v --noconftest
"""
import asyncio

import pytest

from app.master_data import intake_hooks, matching, models
from app.master_data.deps import ENV_MODE, MODE_ENFORCE, MODE_SHADOW
from app.master_data.pending import PENDING_COLLECTION, SOURCE_OCR, STATUS_RESOLVED, propose
from app.master_data.repository import MasterDataRepository
from app.master_data.review import approve, list_pending, suggest_matches

from tests.test_w0_03b3_review_and_matching import Ctx, SpyDb, run


def test_end_to_end_ocr_text_becomes_a_master_record_through_a_human():
    db = SpyDb()
    ctx = Ctx("tenant-a", user_id="office-1", db=db)
    repo = MasterDataRepository("tenant-a", db=db)

    # 1. shadow: the intake path measures, writes nothing
    shadow = run(propose(ctx, entity_type=models.ENTITY_ORGANIZATION,
                         raw_value="Баумит ЕООД", source_channel=SOURCE_OCR,
                         source_ref="ocr-intake:inv-1", mode=MODE_SHADOW))
    assert shadow.performed is False and shadow.would_perform is True
    assert db.collections == {}

    # 2. enforce: a proposal, and only a proposal
    first = run(propose(ctx, entity_type=models.ENTITY_ORGANIZATION,
                        raw_value="Баумит ЕООД", source_channel=SOURCE_OCR,
                        source_ref="ocr-intake:inv-1", mode=MODE_ENFORCE, repository=repo))
    assert first.performed is True
    assert db.master(models.ENTITY_ORGANIZATION) is None, "OCR created a Master record"

    # 3. the queue shows it
    queue = run(list_pending(ctx, mode=MODE_ENFORCE, repository=repo))
    assert [q["id"] for q in queue] == [first.pending["id"]]

    # 4. nothing to match against yet
    assert run(suggest_matches(ctx, pending_id=first.pending["id"],
                               mode=MODE_ENFORCE, repository=repo)) == []

    # 5. a person approves it as a new official record
    approved = run(approve(ctx, pending_id=first.pending["id"], confirmation=True,
                           create_new=True, display_name="Баумит България ЕООД",
                           mode=MODE_ENFORCE, repository=repo))
    assert approved.performed is True and approved.created_master is True
    masters = db.master(models.ENTITY_ORGANIZATION).docs
    assert len(masters) == 1
    assert db[PENDING_COLLECTION].docs[0]["status"] == STATUS_RESOLVED

    # 6. a second invoice, the supplier spelled differently
    second = run(propose(ctx, entity_type=models.ENTITY_ORGANIZATION,
                         raw_value="БАУМИТ БЪЛГАРИЯ Е.О.О.Д.", source_channel=SOURCE_OCR,
                         source_ref="ocr-intake:inv-2", mode=MODE_ENFORCE, repository=repo))
    candidates = run(suggest_matches(ctx, pending_id=second.pending["id"],
                                     mode=MODE_ENFORCE, repository=repo))
    # the dotted spelling normalizes to the same thing, so it IS found —
    # and it is still only a candidate until a person says so
    assert len(candidates) == 1
    assert candidates[0]["entity_id"] == approved.entity_id
    assert candidates[0]["score"] == 1.0
    assert db[PENDING_COLLECTION].docs[1]["resolved_entity_id"] is None, \
        "an exact match resolved itself"

    # 7. the person maps it to the existing record; no second Master appears
    mapped = run(approve(ctx, pending_id=second.pending["id"], confirmation=True,
                         canonical_entity_id=approved.entity_id,
                         mode=MODE_ENFORCE, repository=repo))
    assert mapped.created_master is False
    assert len(db.master(models.ENTITY_ORGANIZATION).docs) == 1

    # 8. a third invoice with a spelling that only the alias can explain
    third = run(propose(ctx, entity_type=models.ENTITY_ORGANIZATION,
                        raw_value="БАУМИТ БЪЛГАРИЯ Е.О.О.Д.", source_channel=SOURCE_OCR,
                        mode=MODE_ENFORCE, repository=repo))
    again = run(suggest_matches(ctx, pending_id=third.pending["id"],
                                mode=MODE_ENFORCE, repository=repo))
    assert [c["entity_id"] for c in again] == [approved.entity_id]

    # 9. the evidence: every step left exactly the events it should
    actions = [e["action"] for e in db.audit().docs]
    assert actions.count("master_data.pending.proposed") == 3
    assert actions.count("master_data.organization.created") == 1
    assert actions.count("master_data.pending.approved") == 2
    assert all(e["tenant_id"] == "tenant-a" for e in db.audit().docs)
    human = [e for e in db.audit().docs if e["action"] == "master_data.pending.approved"]
    assert all(e["actor_id"] == "office-1" for e in human)


def test_the_legacy_intake_hook_is_a_no_op_while_off(monkeypatch):
    monkeypatch.delenv(ENV_MODE, raising=False)

    async def boom(*a, **kw):
        raise AssertionError("the hook called propose while off")

    monkeypatch.setattr("app.master_data.pending.propose", boom)
    assert run(intake_hooks.observe_ocr_supplier(
        {"id": "u1"}, {"supplier_name": "Баумит ЕООД"})) is None


def test_the_legacy_intake_hook_cannot_fail_the_upload(monkeypatch):
    """An invoice upload must never fail because an observation could not be
    recorded — that would be a worse bug than the one the hook helps with."""
    monkeypatch.setenv(ENV_MODE, "shadow")

    async def boom(*a, **kw):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(intake_hooks, "_context_for", boom)
    assert run(intake_hooks.observe_ocr_supplier(
        {"id": "u1"}, {"supplier_name": "Баумит ЕООД"})) is None


def test_the_hook_ignores_an_invoice_without_a_detected_supplier(monkeypatch):
    monkeypatch.setenv(ENV_MODE, "shadow")
    for detected in (None, {}, {"supplier_name": ""}, {"supplier_name": "   "}):
        assert run(intake_hooks.observe_ocr_supplier({"id": "u1"}, detected)) is None


def test_an_unusable_mode_does_not_break_the_intake_path(monkeypatch):
    """A typo in MASTER_DATA_MODE refuses Master Data operations — but it must
    not take an invoice upload down with it."""
    monkeypatch.setenv(ENV_MODE, "offf")
    assert run(intake_hooks.observe_ocr_supplier(
        {"id": "u1"}, {"supplier_name": "Баумит ЕООД"})) is None
