"""
W0-03D — Master Data merge, redirect history and immutable references.

The promises under test (contract §6 W0-03D, FLOW-032):

  * the preview is read-only and deterministic: same records -> same preview and
    token; conflicts and references are reported in a stable order;
  * a merge refuses a stale preview, a changed record, another tenant's or
    another type's record, a non-canonical target and a redirect cycle — all
    before any write;
  * a merge fails closed without a TRUSTED Approval. W0-07 is not started, so the
    build's only verifier refuses everything; a forged ``approval_id``, a dict
    that looks like evidence, or evidence for another operation is not proof;
  * off is inert, shadow writes nothing;
  * the source record is preserved, only its lifecycle moves; the target is not
    touched; nothing is ever deleted; history is insert-only;
  * old ids keep resolving; references are not rewritten;
  * the same request retried is answered, not redone; an interrupted write is
    finished by its retry with one history event and one AuditEvent;
  * unmerge appends an event that names the merge it reverses; the merge event
    is never edited;
  * every refusal and success in enforce leaves a canonical AuditEvent.

The happy paths need an Approval that this build cannot produce. They run with
``TrustedTestVerifier`` — a verifier defined ONLY in this file and passed as an
in-process argument, the same seam as ``repository=``. No route and no
production code path can supply one (see the route tests).

No database: an in-memory double of the Mongo calls the package makes. The same
flows against a real disposable MongoDB are in test_w0_03d_real_mongo.py.

Run:  pytest tests/test_w0_03d_merge_redirect.py -v --noconftest
"""
import asyncio
import copy
import random

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.audit.envelope import RESULT_DENIED, RESULT_FAILURE, RESULT_SUCCESS
from app.audit.idempotency import IDEMPOTENCY_COLLECTION, IDEMPOTENCY_COMPLETED
from app.audit.store import AUDIT_COLLECTION, verify_chain
from app.deps.auth import get_current_user
from app.master_data import merge as mm
from app.master_data import models
from app.master_data.deps import ENV_MODE, MODE_ENFORCE, MODE_OFF, MODE_SHADOW, \
    MasterDataConfigError, MasterDataTenantContextMissing
from app.master_data.merge import (
    HISTORY_COLLECTION,
    LOCK_COLLECTION,
    ApprovalEvidence,
    MasterDataApprovalRequired,
    MasterDataMergeBusy,
    MasterDataRedirectCycle,
    MasterDataStalePreview,
)
from app.master_data.models import MasterDataInvalid, build_entity, new_alias, new_identifier, \
    new_legacy_ref
from app.master_data.pending import PENDING_COLLECTION
from app.master_data.repository import MasterDataRepository
from app.master_data.service import MasterDataAuditFailed, MasterDataRefused
from app.permissions import catalog
from app.routes import master_data as routes

ORG = models.ENTITY_ORGANIZATION
PERSON = models.ENTITY_PERSON
T_A, T_B = "tenant-a", "tenant-b"
NOW = "2026-09-27T09:00:00+00:00"


def run(coro):
    return asyncio.run(coro)


# =========================================================== in-memory Mongo
class DuplicateKeyError(Exception):
    code = 11000


class _Result:
    def __init__(self, modified=0, upserted_id=None):
        self.modified_count = modified
        self.matched_count = modified
        self.upserted_id = upserted_id


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return list(self._docs[:length] if length else self._docs)


def _get(doc, path):
    head, _, tail = path.partition(".")
    value = doc.get(head, None) if isinstance(doc, dict) else None
    if not tail:
        return value
    if isinstance(value, list):
        return [_get(v, tail) for v in value if isinstance(v, dict)]
    return _get(value, tail) if isinstance(value, dict) else None


def _match_value(actual, expected):
    if isinstance(expected, dict) and any(str(k).startswith("$") for k in expected):
        for op, arg in expected.items():
            if op == "$ne" and _match_value(actual, arg):
                return False
            if op == "$in" and not any(_match_value(actual, a) for a in arg):
                return False
        return True
    if expected is None:
        return actual is None or actual == []
    if isinstance(actual, list) and not isinstance(expected, list):
        return expected in actual
    return actual == expected


def _matches(doc, query):
    for key, expected in (query or {}).items():
        if key == "$or":
            if not any(_matches(doc, clause) for clause in expected):
                return False
            continue
        if not _match_value(_get(doc, key), expected):
            return False
    return True


class FakeCollection:
    def __init__(self, db, name):
        self.db, self.name, self.docs = db, name, []

    def _log(self, op, *args):
        self.db.writes.append((self.name, op) + args)
        if self.db.explode_on_write:
            raise AssertionError("write attempted: %s.%s" % (self.name, op))
        failing = self.db.fail_writes.get(self.name)
        if failing and failing[0] > 0:
            failing[0] -= 1
            raise RuntimeError("simulated storage failure on %s" % self.name)

    def _read(self):
        self.db.reads.append(self.name)
        if self.db.explode_on_read:
            raise AssertionError("read attempted: %s" % self.name)

    def _unique(self, doc):
        if "_id" in doc and any(d.get("_id") == doc["_id"] for d in self.docs):
            raise DuplicateKeyError("E11000 duplicate key error: _id %r" % (doc["_id"],))

    async def insert_one(self, doc):
        self._log("insert_one", doc.get("id") or doc.get("_id"))
        self._unique(doc)
        self.docs.append(copy.deepcopy(doc))

    async def find_one(self, query, projection=None, sort=None):
        self._read()
        found = [d for d in self.docs if _matches(d, query)]
        if sort:
            key, direction = sort[0]
            found.sort(key=lambda d: d.get(key) or 0, reverse=direction < 0)
        if not found:
            return None
        return self._project(found[0], projection)

    def find(self, query, projection=None):
        self._read()
        return _Cursor([self._project(d, projection) for d in self.docs if _matches(d, query)])

    async def update_one(self, query, update, upsert=False):
        self._log("update_one", query.get("id") or query.get("_id"))
        found = [d for d in self.docs if _matches(d, query)]
        if not found:
            if not upsert:
                return _Result(0)
            doc = {k: v for k, v in query.items()
                   if not k.startswith("$") and not (isinstance(v, dict) and any(
                       str(o).startswith("$") for o in v))}
            doc.update(copy.deepcopy(update.get("$setOnInsert", {})))
            doc.update(copy.deepcopy(update.get("$set", {})))
            self._unique(doc)
            self.docs.append(doc)
            return _Result(0, upserted_id=doc.get("_id", True))
        doc = found[0]
        for k, v in update.get("$set", {}).items():
            doc[k] = copy.deepcopy(v)
        for k, v in update.get("$addToSet", {}).items():
            items = doc.setdefault(k, [])
            if v not in items:
                items.append(v)
        return _Result(1)

    async def delete_one(self, *a, **kw):
        self.db.deletes.append((self.name, a))
        raise AssertionError("hard delete attempted on %s" % self.name)

    delete_many = find_one_and_delete = delete_one

    async def replace_one(self, *a, **kw):
        self.db.deletes.append((self.name, "replace", a))
        raise AssertionError("replace attempted on %s" % self.name)

    @staticmethod
    def _project(doc, projection):
        out = copy.deepcopy(doc)
        if projection and projection.get("_id") == 0:
            out.pop("_id", None)
        return out


class FakeDb:
    def __init__(self):
        self.collections = {}
        self.writes, self.reads, self.deletes = [], [], []
        self.explode_on_write = self.explode_on_read = False
        self.fail_writes = {}

    def __getitem__(self, name):
        if name not in self.collections:
            self.collections[name] = FakeCollection(self, name)
        return self.collections[name]

    def docs(self, name):
        return self[name].docs

    def snapshot(self):
        return copy.deepcopy({k: v.docs for k, v in self.collections.items() if v.docs})

    def business_snapshot(self):
        """Everything except the audit chain — what 'no write' must leave alone."""
        return {k: v for k, v in self.snapshot().items() if k != AUDIT_COLLECTION}


class Ctx:
    enforced = True

    def __init__(self, tenant_id=T_A, db=None, user_id="admin-1"):
        self.tenant_id, self.user_id = tenant_id, user_id
        self._db = db if db is not None else FakeDb()

    async def db(self, require_operational=False):
        return self._db


class LegacyCtx:
    enforced = False
    tenant_id = "org-legacy"
    user_id = "u"


class TrustedTestVerifier:
    """TEST ONLY. Stands in for the W0-07 runtime that does not exist yet."""

    name = "test-only-trusted-verifier"

    def __init__(self, on_verify=None, approver="owner-krum"):
        self.calls = []
        self.on_verify = on_verify
        self.approver = approver

    async def verify(self, ctx, *, approval_id, subject):
        self.calls.append((approval_id, dict(subject)))
        if self.on_verify:
            await self.on_verify()
        return ApprovalEvidence(approval_id=approval_id, tenant_id=ctx.tenant_id, subject=subject,
                                approver_id=self.approver, decided_at=NOW, verifier=self.name)


def _repo(db, tenant=T_A):
    return MasterDataRepository(tenant, db=db)


def _entity(tenant, name, etype=ORG, eid=None, **extra):
    doc = build_entity(tenant_id=tenant, entity_type=etype, display_name=name, entity_id=eid, now=NOW)
    doc.update(extra)
    return doc


def world(shuffle=None):
    """Tenant A with a duplicate pair, references to the source, and tenant B."""
    db = FakeDb()
    src = _entity(T_A, "Баумит ЕООД", eid="org-src",
                  aliases=[new_alias("Баумит", added_by="office-1", now=NOW),
                           new_alias("Baumit BG", added_by="office-1", now=NOW)],
                  identifiers=[new_identifier(ORG, "eik", "123456789")],
                  legacy_refs=[new_legacy_ref("counterparties", "cp-9", "org-1"),
                               new_legacy_ref("clients", "cl-3", "org-1")],
                  phone="+359 1")
    tgt = _entity(T_A, "Баумит България ЕООД", eid="org-tgt",
                  aliases=[new_alias("Баумит", added_by="office-2", now=NOW)],
                  identifiers=[new_identifier(ORG, "eik", "987654321"),
                               new_identifier(ORG, "vat", "BG987654321")],
                  phone="+359 2")
    older = _entity(T_A, "Баумит (стар)", eid="org-older", status=models.STATUS_MERGED,
                    merged_into="org-src", merge_event_id="evt-old")
    other_type = _entity(T_A, "Иван Петров", etype=PERSON, eid="per-1")
    foreign = _entity(T_B, "Баумит ЕООД", eid="org-foreign")
    orgs = [src, tgt, older]
    if shuffle is not None:
        random.Random(shuffle).shuffle(orgs)
    db["md_organization"].docs.extend(copy.deepcopy(orgs) + [copy.deepcopy(foreign)])
    db["md_person"].docs.append(copy.deepcopy(other_type))
    pendings = [{"id": "pm-2", "tenant_id": T_A, "entity_type": ORG, "status": "resolved",
                 "resolved_entity_id": "org-src"},
                {"id": "pm-1", "tenant_id": T_A, "entity_type": ORG, "status": "resolved",
                 "resolved_entity_id": "org-src"},
                {"id": "pm-x", "tenant_id": T_B, "entity_type": ORG, "status": "resolved",
                 "resolved_entity_id": "org-src"}]
    if shuffle is not None:
        random.Random(shuffle + 1).shuffle(pendings)
    db[PENDING_COLLECTION].docs.extend(pendings)
    return db


def org(db, eid):
    return next(d for d in db.docs("md_organization") if d["id"] == eid)


def audit(db, result=None):
    return [e for e in db.docs(AUDIT_COLLECTION) if result is None or e["result"] == result]


async def _preview(db, source="org-src", target="org-tgt", ctx=None, verifier=None):
    return await mm.preview_merge(ctx or Ctx(db=db), entity_type=ORG, source_id=source,
                                  target_id=target, mode=MODE_ENFORCE, repository=_repo(db),
                                  approval_verifier=verifier)


async def _merge(db, token, key="k-1", source="org-src", target="org-tgt", verifier="trusted",
                 approval_id="APR-1", ctx=None, **kw):
    if verifier == "trusted":
        verifier = TrustedTestVerifier()
    return await mm.merge(ctx or Ctx(db=db), entity_type=ORG, source_id=source, target_id=target,
                          preview_token=token, idempotency_key=key, confirmation=True,
                          approval_id=approval_id, mode=MODE_ENFORCE, repository=_repo(db),
                          approval_verifier=verifier, **kw)


async def _merged_world():
    db = world()
    p = await _preview(db)
    out = await _merge(db, p["preview_token"])
    return db, out


# ================================================================== preview
def test_preview_is_read_only_and_reports_everything_a_person_needs():
    db = world()
    before = db.snapshot()
    p = run(_preview(db))

    assert db.writes == [] and db.snapshot() == before, "preview wrote"
    assert p["source"]["id"] == "org-src" and p["target"]["id"] == "org-tgt"
    refs = p["references"]
    assert refs["pending_resolved_to_source"] == ["pm-1", "pm-2"]        # tenant B's pm-x absent
    assert refs["records_redirected_into_source"] == ["org-older"]
    assert [r["legacy_id"] for r in refs["legacy_refs_of_source"]] == ["cl-3", "cp-9"]
    assert "not rewritten" in refs["handling"]
    assert p["aliases"] == {"source_only": ["Baumit BG"], "target_only": [], "shared": ["Баумит"]}
    assert p["identifiers"]["source_only"] == ["eik:123456789"]
    assert p["identifiers"]["target_only"] == sorted(["eik:987654321", "vat:BG987654321"])
    assert p["identifiers"]["shared"] == []
    fields = [c["field"] for c in p["conflicts"]]
    assert fields == sorted(fields)
    assert {"display_name", "identifiers.eik", "normalized_name", "phone"} <= set(fields)
    assert all(c["resolution"].startswith("none") for c in p["conflicts"])
    assert p["effects"][0]["change"] == {"status": ["active", "merged"],
                                         "merged_into": [None, "org-tgt"]}
    assert any("nothing is deleted" in n for n in p["not_changed"])
    assert p["approval"]["required"] and not p["approval"]["runtime_available"]
    assert p["blocking"] == [] and p["executable"] is False
    assert len(p["preview_token"]) == 64


def test_preview_is_deterministic_regardless_of_storage_order():
    first = run(_preview(world()))
    again = run(_preview(world()))
    shuffled = run(_preview(world(shuffle=7)))
    assert first == again == shuffled


@pytest.mark.parametrize("change", ["source", "target", "new_reference", "redirect_into_source"])
def test_any_change_to_what_the_preview_covered_changes_the_token(change):
    db = world()
    token = run(_preview(db))["preview_token"]
    if change == "source":
        org(db, "org-src")["phone"] = "+359 3"
    elif change == "target":
        org(db, "org-tgt")["display_name"] = "Баумит АД"
    elif change == "new_reference":
        db[PENDING_COLLECTION].docs.append({"id": "pm-3", "tenant_id": T_A, "entity_type": ORG,
                                            "resolved_entity_id": "org-src"})
    else:
        db["md_organization"].docs.append(_entity(T_A, "X", eid="org-x", status="merged",
                                                  merged_into="org-src"))
    assert run(_preview(db))["preview_token"] != token


def test_preview_in_off_and_shadow_reads_nothing():
    db = world()
    db.explode_on_read = db.explode_on_write = True
    for mode in (MODE_OFF, MODE_SHADOW):
        assert run(mm.preview_merge(Ctx(db=db), entity_type=ORG, source_id="org-src",
                                    target_id="org-tgt", mode=mode, repository=_repo(db))) is None
        assert run(mm.preview_unmerge(Ctx(db=db), entity_type=ORG, source_id="org-src",
                                      mode=mode, repository=_repo(db))) is None
        assert run(mm.resolve(Ctx(db=db), entity_type=ORG, entity_id="org-src", mode=mode,
                              repository=_repo(db))) is None
        assert run(mm.history(Ctx(db=db), entity_type=ORG, entity_id="org-src", mode=mode,
                              repository=_repo(db))) == []
    assert db.reads == [] and db.writes == []


@pytest.mark.parametrize("source,target,why", [
    ("org-foreign", "org-tgt", "another tenant's record"),
    ("org-src", "org-foreign", "another tenant's target"),
    ("per-1", "org-tgt", "another type"),
    ("org-src", "per-1", "another type as target"),
    ("org-missing", "org-tgt", "nonexistent"),
])
def test_preview_refuses_records_outside_this_tenant_and_type(source, target, why):
    db = world()
    with pytest.raises(MasterDataRefused, match="not a organization of this tenant"):
        run(_preview(db, source, target))
    assert db.writes == [], why


def test_a_record_cannot_be_previewed_or_merged_into_itself():
    db = world()
    with pytest.raises(MasterDataInvalid):
        run(_preview(db, "org-src", "org-src"))
    with pytest.raises(MasterDataInvalid):
        run(_merge(db, "t" * 64, source="org-src", target="org-src"))
    assert db.writes == []


def test_preview_marks_a_non_canonical_target_and_a_cycle_as_blocking():
    db = world()
    p = run(_preview(db, "org-src", "org-older"))           # older -> src: a cycle
    assert any("cycle" in b for b in p["blocking"]) and not p["executable"]
    p = run(_preview(db, "org-older", "org-tgt"))           # source already merged
    assert any("source is merged" in b for b in p["blocking"])


# ======================================================== approval fails closed
@pytest.mark.parametrize("approval_id", [None, "", "APR-FORGED-123", "approved", "owner"])
def test_the_default_build_refuses_every_merge_before_any_write(approval_id):
    db = world()
    token = run(_preview(db))["preview_token"]
    before = db.business_snapshot()

    with pytest.raises(MasterDataApprovalRequired) as exc:
        run(_merge(db, token, verifier=None, approval_id=approval_id))

    if approval_id:
        assert "not proof" in str(exc.value) and "W0-07" in str(exc.value)
    assert db.business_snapshot() == before, "a refused merge changed data"
    assert db.docs(HISTORY_COLLECTION) == [] and db.docs(IDEMPOTENCY_COLLECTION) == []
    assert db.docs(LOCK_COLLECTION) == []
    [event] = audit(db)
    assert event["result"] == RESULT_DENIED and event["error_code"] == "APPROVAL_REQUIRED"
    assert event["action"] == "master_data.organization.merge_refused"
    assert event["entity_id"] == "org-src" and event["actor_id"] == "admin-1"
    assert event["approval_id"] is None, "an unverified id is not an approval reference"
    assert (event["structured_diff"] or {}).get("claimed_approval_id") == (approval_id or None)


class _LyingVerifier:
    def __init__(self, answer):
        self.answer = answer

    async def verify(self, ctx, *, approval_id, subject):
        return self.answer(ctx, approval_id, subject)


def _evidence(**over):
    def make(ctx, approval_id, subject):
        fields = dict(approval_id=approval_id, tenant_id=ctx.tenant_id, subject=subject,
                      approver_id="owner", decided_at=NOW, verifier="x")
        for k, v in over.items():
            fields[k] = v(fields) if callable(v) else v
        return ApprovalEvidence(**fields)
    return make


@pytest.mark.parametrize("answer", [
    lambda ctx, a, s: {"approval_id": a, "tenant_id": ctx.tenant_id, "subject": s,
                       "approver_id": "owner", "decided_at": NOW},     # a dict is not evidence
    lambda ctx, a, s: None,
    lambda ctx, a, s: True,
    _evidence(approval_id="APR-OTHER"),
    _evidence(tenant_id=T_B),
    _evidence(subject=lambda f: dict(f["subject"], target_id="org-older")),
    _evidence(subject=lambda f: dict(f["subject"], preview_token="0" * 64)),
    _evidence(subject=lambda f: dict(f["subject"], action="master_data.unmerge")),
    _evidence(approver_id=""),
])
def test_evidence_that_is_not_bound_to_this_exact_operation_is_refused(answer):
    db = world()
    token = run(_preview(db))["preview_token"]
    before = db.business_snapshot()
    with pytest.raises(MasterDataApprovalRequired):
        run(_merge(db, token, verifier=_LyingVerifier(answer)))
    assert db.business_snapshot() == before


def test_a_verifier_that_errors_is_a_refusal_not_an_approval():
    class Broken:
        async def verify(self, ctx, **kw):
            raise ConnectionError("approval service unreachable")
    db = world()
    token = run(_preview(db))["preview_token"]
    with pytest.raises(MasterDataApprovalRequired, match="could not be verified"):
        run(_merge(db, token, verifier=Broken()))
    assert db.docs(HISTORY_COLLECTION) == []


def test_confirmation_is_required():
    db = world()
    token = run(_preview(db))["preview_token"]
    with pytest.raises(MasterDataRefused, match="confirmation"):
        run(mm.merge(Ctx(db=db), entity_type=ORG, source_id="org-src", target_id="org-tgt",
                     preview_token=token, idempotency_key="k", confirmation=False,
                     approval_id="A", mode=MODE_ENFORCE, repository=_repo(db),
                     approval_verifier=TrustedTestVerifier()))
    assert db.writes == []


@pytest.mark.parametrize("missing", ["preview_token", "idempotency_key"])
def test_a_merge_without_a_preview_token_or_idempotency_key_is_refused(missing):
    db = world()
    kwargs = dict(preview_token="t" * 64, idempotency_key="k")
    kwargs[missing] = ""
    with pytest.raises(MasterDataInvalid, match=missing):
        run(mm.merge(Ctx(db=db), entity_type=ORG, source_id="org-src", target_id="org-tgt",
                     confirmation=True, approval_id="A", mode=MODE_ENFORCE,
                     repository=_repo(db), approval_verifier=TrustedTestVerifier(), **kwargs))
    assert db.writes == []


# =============================================================== off / shadow
def test_off_is_inert():
    db = world()
    db.explode_on_read = db.explode_on_write = True
    for fn, extra in ((mm.merge, dict(target_id="org-tgt")),
                      (mm.unmerge, dict(merge_event_id="e", reason="r"))):
        out = run(fn(object(), entity_type=ORG, source_id="org-src", preview_token="t",
                     idempotency_key="k", confirmation=True, approval_id="A", mode=MODE_OFF,
                     repository=_repo(db), **extra))
        assert out.mode == MODE_OFF and out.performed is False
    assert db.reads == [] and db.writes == []


def test_shadow_writes_nothing_and_reports_that_approval_would_be_refused():
    db = world()
    db.explode_on_read = db.explode_on_write = True
    out = run(mm.merge(Ctx(db=db), entity_type=ORG, source_id="org-src", target_id="org-tgt",
                       preview_token="t" * 64, idempotency_key="k", confirmation=True,
                       approval_id="APR-FORGED", mode=MODE_SHADOW, repository=_repo(db)))
    assert out.mode == MODE_SHADOW and out.performed is False and out.would_perform is False
    assert "W0-07" in out.reason
    out = run(mm.unmerge(Ctx(db=db), entity_type=ORG, source_id="org-src", merge_event_id="e",
                         preview_token="t", idempotency_key="k", reason="wrong",
                         confirmation=True, mode=MODE_SHADOW, repository=_repo(db)))
    assert out.performed is False and out.would_perform is False
    bad = run(mm.merge(LegacyCtx(), entity_type=ORG, source_id="a", target_id="b",
                       preview_token="t", idempotency_key="k", confirmation=True,
                       mode=MODE_SHADOW))
    assert bad.would_perform is False and "legacy" in bad.reason
    assert db.reads == [] and db.writes == []


def test_an_unusable_mode_refuses_before_anything():
    db = world()
    db.explode_on_read = db.explode_on_write = True
    with pytest.raises(MasterDataConfigError):
        run(mm.merge(Ctx(db=db), entity_type=ORG, source_id="a", target_id="b",
                     preview_token="t", idempotency_key="k", mode="enforse"))
    with pytest.raises(MasterDataConfigError):
        run(mm.preview_merge(Ctx(db=db), entity_type=ORG, source_id="a", target_id="b", mode=""))


def test_enforce_refuses_a_legacy_context_a_missing_actor_and_a_tenant_in_the_payload():
    db = world()
    token = run(_preview(db))["preview_token"]
    with pytest.raises(MasterDataTenantContextMissing):
        run(_merge(db, token, ctx=LegacyCtx()))
    with pytest.raises(MasterDataTenantContextMissing):
        run(_merge(db, token, ctx=Ctx(db=db, user_id=None)))
    with pytest.raises(MasterDataRefused, match="tenant identity"):
        run(_merge(db, token, payload={"tenant_id": T_B}))
    assert db.writes == []


# ============================================================== the merge itself
def test_a_trusted_merge_redirects_preserves_and_records_everything_once():
    db = world()
    src_before, tgt_before = copy.deepcopy(org(db, "org-src")), copy.deepcopy(org(db, "org-tgt"))
    pending_before = copy.deepcopy(db.docs(PENDING_COLLECTION))
    older_before = copy.deepcopy(org(db, "org-older"))
    p = run(_preview(db))
    verifier = TrustedTestVerifier()
    out = run(_merge(db, p["preview_token"], verifier=verifier))

    assert out.performed and out.mode == MODE_ENFORCE and not out.replayed
    src = org(db, "org-src")
    assert src["status"] == models.STATUS_MERGED and src["merged_into"] == "org-tgt"
    assert src["merge_event_id"] == out.event_id and src["merged_by"] == "admin-1"
    for field in ("display_name", "aliases", "identifiers", "legacy_refs", "phone", "created_at"):
        assert src[field] == src_before[field], "source field %s changed" % field
    models.validate_entity(src)
    assert org(db, "org-tgt") == tgt_before, "the target must not be touched"
    assert org(db, "org-older") == older_before and db.docs(PENDING_COLLECTION) == pending_before

    [event] = db.docs(HISTORY_COLLECTION)
    assert event["kind"] == "merge" and event["source_id"] == "org-src"
    assert event["target_id"] == "org-tgt" and event["preview_token"] == p["preview_token"]
    assert {k: v for k, v in event["source_before"].items() if k != "_id"} == src_before
    assert event["approval"]["approver_id"] == "owner-krum"

    [success] = audit(db, RESULT_SUCCESS)
    assert success["action"] == "master_data.organization.merged"
    assert success["approval_id"] == "APR-1" and success["idempotency_key"] == "k-1"
    assert success["entity_version"] == p["preview_token"]
    assert success["structured_diff"]["merged_into"] == [None, "org-tgt"]
    assert verify_chain(db.docs(AUDIT_COLLECTION)) == (True, None)
    [record] = db.docs(IDEMPOTENCY_COLLECTION)
    assert record["status"] == IDEMPOTENCY_COMPLETED and record["result_reference"] == out.event_id
    [lock] = db.docs(LOCK_COLLECTION)
    assert lock["holder"] is None
    assert db.deletes == []
    assert verifier.calls[0][1] == {"action": "master_data.merge", "tenant_id": T_A,
                                    "entity_type": ORG, "source_id": "org-src",
                                    "target_id": "org-tgt", "preview_token": p["preview_token"]}


def test_old_ids_keep_resolving_through_the_redirect_and_references_are_not_rewritten():
    db, out = run(_merged_world())
    ctx = Ctx(db=db)
    for old, chain in (("org-src", ["org-src", "org-tgt"]),
                       ("org-older", ["org-older", "org-src", "org-tgt"]),
                       ("org-tgt", ["org-tgt"])):
        r = run(mm.resolve(ctx, entity_type=ORG, entity_id=old, mode=MODE_ENFORCE,
                           repository=_repo(db)))
        assert r["canonical_id"] == "org-tgt" and r["chain"] == chain
        assert r["redirected"] is (len(chain) > 1)
    assert [p["resolved_entity_id"] for p in db.docs(PENDING_COLLECTION)] == ["org-src"] * 3
    # still readable as it is — the preserved record, not a tombstone
    assert run(mm.resolve(ctx, entity_type=ORG, entity_id="org-foreign", mode=MODE_ENFORCE,
                          repository=_repo(db))) is None
    assert run(mm.resolve(ctx, entity_type=PERSON, entity_id="org-src", mode=MODE_ENFORCE,
                          repository=_repo(db))) is None


def test_resolution_never_leaves_the_tenant_or_the_type_and_refuses_cycles():
    db = world()
    db["md_organization"].docs.extend([
        _entity(T_A, "cross", eid="org-cross", status="merged", merged_into="org-foreign"),
        _entity(T_A, "type", eid="org-type", status="merged", merged_into="per-1"),
        _entity(T_A, "c1", eid="org-c1", status="merged", merged_into="org-c2"),
        _entity(T_A, "c2", eid="org-c2", status="merged", merged_into="org-c1"),
    ])
    ctx = Ctx(db=db)
    for bad in ("org-cross", "org-type"):
        with pytest.raises(MasterDataRefused, match="broken redirect"):
            run(mm.resolve(ctx, entity_type=ORG, entity_id=bad, mode=MODE_ENFORCE,
                           repository=_repo(db)))
    with pytest.raises(MasterDataRedirectCycle):
        run(mm.resolve(ctx, entity_type=ORG, entity_id="org-c1", mode=MODE_ENFORCE,
                       repository=_repo(db)))


def test_a_merge_back_into_the_source_is_refused_as_a_cycle_before_any_write():
    db, _ = run(_merged_world())
    # tgt -> src would close src -> tgt into a loop
    p = run(_preview(db, "org-tgt", "org-src"))
    assert any("cycle" in b for b in p["blocking"])
    before = db.business_snapshot()
    with pytest.raises(MasterDataRedirectCycle):
        run(_merge(db, p["preview_token"], key="k-back", source="org-tgt", target="org-src"))
    assert db.business_snapshot() == before
    assert audit(db, RESULT_FAILURE)[-1]["error_code"] == "REDIRECT_CYCLE"


def test_a_merge_into_a_record_that_is_itself_merged_is_refused():
    db, _ = run(_merged_world())
    db["md_organization"].docs.append(_entity(T_A, "Нов", eid="org-new"))
    p = run(_preview(db, "org-new", "org-src"))
    assert any("not an active canonical record" in b and "org-tgt" in b for b in p["blocking"])
    with pytest.raises(MasterDataRefused):
        run(_merge(db, p["preview_token"], key="k-2", source="org-new", target="org-src"))
    assert org(db, "org-new")["status"] == "active"


def test_a_stale_preview_is_refused_before_any_write():
    db = world()
    token = run(_preview(db))["preview_token"]
    org(db, "org-src")["display_name"] = "Баумит ЕООД (коригирано)"
    before = db.business_snapshot()
    with pytest.raises(MasterDataStalePreview):
        run(_merge(db, token))
    assert db.business_snapshot() == before
    [event] = audit(db)
    assert event["result"] == RESULT_FAILURE and event["error_code"] == "STALE_PREVIEW"


def test_a_record_that_changes_after_the_checks_is_caught_under_the_lock():
    db = world()
    token = run(_preview(db))["preview_token"]

    async def someone_edits_the_target():
        org(db, "org-tgt")["phone"] = "+359 9"

    with pytest.raises(MasterDataStalePreview):
        run(_merge(db, token, verifier=TrustedTestVerifier(on_verify=someone_edits_the_target)))
    assert org(db, "org-src")["status"] == "active" and db.docs(HISTORY_COLLECTION) == []
    [lock] = db.docs(LOCK_COLLECTION)
    assert lock["holder"] is None, "a refused attempt must release the lock"
    [record] = db.docs(IDEMPOTENCY_COLLECTION)
    assert record["status"] == "failed" and record["error_code"] == "REFUSED_UNDER_LOCK"


def test_the_same_request_retried_is_answered_not_redone():
    db, first = run(_merged_world())
    token = db.docs(HISTORY_COLLECTION)[0]["preview_token"]
    snapshot = db.snapshot()
    again = run(_merge(db, token))
    assert again.performed and again.replayed and again.event_id == first.event_id
    assert db.snapshot() == snapshot, "a replay wrote"


def test_the_same_key_for_a_different_request_is_refused():
    db, _ = run(_merged_world())
    with pytest.raises(MasterDataRefused, match="different"):
        run(_merge(db, "f" * 64))
    assert len(db.docs(HISTORY_COLLECTION)) == 1


# ============================================================ interrupted writes
@pytest.mark.parametrize("crash_after", ["source_written", "history_recorded", "audited"])
def test_an_interrupted_merge_is_finished_by_its_retry_with_one_event_and_one_audit(crash_after):
    db = world()
    src_before = copy.deepcopy(org(db, "org-src"))
    token = run(_preview(db))["preview_token"]

    with pytest.raises(mm._Interrupted):
        run(_merge(db, token, _fail_after=crash_after))
    src = org(db, "org-src")
    assert src["status"] == "merged", "the crash came after the source write"
    [lock] = db.docs(LOCK_COLLECTION)
    assert lock["interrupted"] is True and lock["holder"], "the lock stays with the operation"

    # nobody else can merge or unmerge organizations meanwhile
    db["md_organization"].docs.append(_entity(T_A, "Трети", eid="org-3"))
    p3 = run(_preview(db, "org-3", "org-tgt"))
    with pytest.raises(MasterDataMergeBusy):
        run(_merge(db, p3["preview_token"], key="k-other", source="org-3"))
    assert org(db, "org-3")["status"] == "active"

    out = run(_merge(db, token))                    # the SAME request, retried
    assert out.performed and out.resumed
    [event] = db.docs(HISTORY_COLLECTION)
    assert event["source_id"] == "org-src"
    before = {k: v for k, v in event["source_before"].items()
              if k not in ("reconstructed_after_interruption",)}
    if crash_after == "source_written":
        # rebuilt from the fields the compare-and-set wrote, and marked as such
        assert event["source_before"]["reconstructed_after_interruption"] is True
        src_before_cmp = {k: v for k, v in src_before.items() if k != "updated_at"}
        assert before == src_before_cmp
    else:
        assert before == src_before
    assert len(audit(db, RESULT_SUCCESS)) == 1
    assert verify_chain(db.docs(AUDIT_COLLECTION)) == (True, None)
    assert db.docs(LOCK_COLLECTION)[0]["holder"] is None
    [record] = [r for r in db.docs(IDEMPOTENCY_COLLECTION) if r["key"] == "k-1"]
    assert record["status"] == IDEMPOTENCY_COMPLETED and "source_written" in record["steps_done"]
    [other] = [r for r in db.docs(IDEMPOTENCY_COLLECTION) if r["key"] == "k-other"]
    assert other["status"] == "failed" and other["error_code"] == "MERGE_BUSY"
    # and the other merge can now proceed
    p3 = run(_preview(db, "org-3", "org-tgt"))
    assert run(_merge(db, p3["preview_token"], key="k-other-2", source="org-3")).performed
    assert db.deletes == []


def test_a_failed_audit_is_not_success_and_its_retry_completes():
    db = world()
    token = run(_preview(db))["preview_token"]
    db.fail_writes[AUDIT_COLLECTION] = [1]
    with pytest.raises(MasterDataAuditFailed, match="NOT successful"):
        run(_merge(db, token))
    assert org(db, "org-src")["status"] == "merged"
    assert audit(db, RESULT_SUCCESS) == []
    out = run(_merge(db, token))
    assert out.performed and len(audit(db, RESULT_SUCCESS)) == 1
    assert len(db.docs(HISTORY_COLLECTION)) == 1


def test_a_failure_before_the_source_write_releases_the_lock_and_writes_nothing():
    db = world()
    token = run(_preview(db))["preview_token"]
    db.fail_writes["md_organization"] = [1]
    with pytest.raises(MasterDataAuditFailed, match="no write"):
        run(_merge(db, token))
    assert org(db, "org-src")["status"] == "active" and db.docs(HISTORY_COLLECTION) == []
    assert db.docs(LOCK_COLLECTION)[0]["holder"] is None
    assert run(_merge(db, token)).performed          # a clean retry


def test_a_live_duplicate_of_the_same_request_cannot_enter_the_critical_section():
    """A double click is two callers. The lock is held by a live attempt (not
    marked interrupted), so the second one is refused, not let in."""
    db = world()
    token = run(_preview(db))["preview_token"]
    holder = mm.derived_event_id(T_A, "merge", "k-1")
    db[LOCK_COLLECTION].docs.append({"_id": mm._lock_id(T_A, ORG), "tenant_id": T_A,
                                     "holder": holder, "attempt": "live-attempt",
                                     "interrupted": False})
    with pytest.raises(MasterDataMergeBusy):
        run(_merge(db, token))
    assert org(db, "org-src")["status"] == "active"
    assert db.docs(LOCK_COLLECTION)[0]["attempt"] == "live-attempt"


def test_crossing_merges_cannot_both_pass_the_cycle_check():
    """A->B and B->A in flight together: the lock serialises them, so the second
    sees the first's redirect and refuses the cycle."""
    db = world()
    db["md_organization"].docs.append(_entity(T_A, "B", eid="org-b"))
    t_ab = run(_preview(db, "org-tgt", "org-b"))["preview_token"]
    t_ba = run(_preview(db, "org-b", "org-tgt"))["preview_token"]
    results = []

    async def both():
        async def one(src, tgt, token, key):
            try:
                results.append(await _merge(db, token, key=key, source=src, target=tgt))
            except MasterDataRefused as exc:
                results.append(exc)
        await asyncio.gather(one("org-tgt", "org-b", t_ab, "k-ab"),
                             one("org-b", "org-tgt", t_ba, "k-ba"))
    run(both())
    performed = [r for r in results if not isinstance(r, Exception)]
    assert len(performed) == 1
    statuses = {org(db, i)["status"] for i in ("org-tgt", "org-b")}
    assert statuses == {"active", "merged"}, "exactly one direction won; no cycle"


# ================================================================== unmerge
def _unmerge(db, preview_token, merge_event_id, key="u-1", verifier="trusted", approval_id="APR-U",
             **kw):
    if verifier == "trusted":
        verifier = TrustedTestVerifier()
    return run(mm.unmerge(Ctx(db=db), entity_type=ORG, source_id="org-src",
                          merge_event_id=merge_event_id, preview_token=preview_token,
                          idempotency_key=key, reason="merged by mistake", confirmation=True,
                          approval_id=approval_id, mode=MODE_ENFORCE, repository=_repo(db),
                          approval_verifier=verifier, **kw))


def _unmerge_preview(db):
    return run(mm.preview_unmerge(Ctx(db=db), entity_type=ORG, source_id="org-src",
                                  mode=MODE_ENFORCE, repository=_repo(db)))


def test_unmerge_preview_is_read_only():
    db, out = run(_merged_world())
    writes = list(db.writes)
    p = _unmerge_preview(db)
    assert db.writes == writes
    assert p["reverses_event_id"] == out.event_id and p["blocking"] == []
    assert p["effects"][0]["change"] == {"status": ["merged", "active"],
                                         "merged_into": ["org-tgt", None]}
    assert p == _unmerge_preview(db)


def test_unmerge_fails_closed_without_trusted_approval():
    db, out = run(_merged_world())
    p = _unmerge_preview(db)
    before = db.business_snapshot()
    with pytest.raises(MasterDataApprovalRequired):
        _unmerge(db, p["preview_token"], out.event_id, verifier=None)
    assert db.business_snapshot() == before
    assert audit(db)[-1]["action"] == "master_data.organization.unmerge_refused"


def test_unmerge_appends_history_and_never_edits_the_merge_event():
    db, out = run(_merged_world())
    merge_event = copy.deepcopy(db.docs(HISTORY_COLLECTION)[0])
    p = _unmerge_preview(db)
    result = _unmerge(db, p["preview_token"], out.event_id)

    assert result.performed and result.target_id == "org-tgt"
    src = org(db, "org-src")
    assert src["status"] == "active" and src["merged_into"] is None
    models.validate_entity(src)
    merge_now, unmerge_event = db.docs(HISTORY_COLLECTION)
    assert merge_now == merge_event, "the merge event must stay unedited"
    assert unmerge_event["kind"] == "unmerge" and unmerge_event["reverses_event_id"] == out.event_id
    assert unmerge_event["reason"] == "merged by mistake"
    actions = [e["action"] for e in audit(db, RESULT_SUCCESS)]
    assert actions == ["master_data.organization.merged", "master_data.organization.unmerged"]
    assert verify_chain(db.docs(AUDIT_COLLECTION)) == (True, None)
    r = run(mm.resolve(Ctx(db=db), entity_type=ORG, entity_id="org-older", mode=MODE_ENFORCE,
                       repository=_repo(db)))
    assert r["canonical_id"] == "org-src", "records redirected into the source follow it back"
    hist = run(mm.history(Ctx(db=db), entity_type=ORG, entity_id="org-tgt", mode=MODE_ENFORCE,
                          repository=_repo(db)))
    assert [e["kind"] for e in hist] == ["merge", "unmerge"]
    assert db.deletes == []


def test_a_record_can_be_merged_again_after_an_unmerge_and_all_history_stays():
    db, out = run(_merged_world())
    _unmerge(db, _unmerge_preview(db)["preview_token"], out.event_id)
    p = run(_preview(db))
    again = run(_merge(db, p["preview_token"], key="k-2"))
    assert again.performed and again.event_id != out.event_id
    assert [e["kind"] for e in db.docs(HISTORY_COLLECTION)] == ["merge", "unmerge", "merge"]


def test_unmerge_refuses_a_stale_preview_a_wrong_event_and_an_active_record():
    db, out = run(_merged_world())
    p = _unmerge_preview(db)
    with pytest.raises(MasterDataRefused, match="did not merge"):
        _unmerge(db, p["preview_token"], "evt-unknown")
    org(db, "org-src")["phone"] = "+359 7"
    with pytest.raises(MasterDataStalePreview):
        _unmerge(db, p["preview_token"], out.event_id, key="u-2")
    assert org(db, "org-src")["status"] == "merged"
    p = _unmerge_preview(db)
    _unmerge(db, p["preview_token"], out.event_id, key="u-3")
    with pytest.raises(MasterDataRefused, match="only a merged record"):
        _unmerge(db, p["preview_token"], out.event_id, key="u-4")


@pytest.mark.parametrize("crash_after", ["source_written", "history_recorded", "audited"])
def test_an_interrupted_unmerge_is_finished_by_its_retry(crash_after):
    db, out = run(_merged_world())
    p = _unmerge_preview(db)
    with pytest.raises(mm._Interrupted):
        _unmerge(db, p["preview_token"], out.event_id, _fail_after=crash_after)
    done = _unmerge(db, p["preview_token"], out.event_id)
    assert done.performed and done.resumed
    assert [e["kind"] for e in db.docs(HISTORY_COLLECTION)] == ["merge", "unmerge"]
    assert [e["action"] for e in audit(db, RESULT_SUCCESS)][-1] == "master_data.organization.unmerged"
    assert len(audit(db, RESULT_SUCCESS)) == 2
    assert org(db, "org-src")["status"] == "active"
    assert db.docs(LOCK_COLLECTION)[0]["holder"] is None


def test_unmerge_requires_a_reason():
    db, out = run(_merged_world())
    with pytest.raises(MasterDataInvalid, match="why"):
        run(mm.unmerge(Ctx(db=db), entity_type=ORG, source_id="org-src", merge_event_id=out.event_id,
                       preview_token="t", idempotency_key="u", reason="  ", confirmation=True,
                       approval_id="A", mode=MODE_ENFORCE, repository=_repo(db),
                       approval_verifier=TrustedTestVerifier()))


# ==================================================================== routes
OWNER = {"id": "u-owner", "role": "Owner"}
ADMIN = {"id": "u-admin", "role": "Admin"}
OFFICE = {"id": "u-office", "role": "office"}
DRIVER = {"id": "u-driver", "role": "Driver"}
WAREHOUSE = {"id": "u-wh", "role": "Warehousekeeper"}

MERGE_BODY = {"entity_type": ORG, "source_id": "org-src", "target_id": "org-tgt",
              "preview_token": "t" * 64, "idempotency_key": "k-1", "confirmation": True,
              "approval_id": "APR-FORGED"}
UNMERGE_BODY = {"entity_type": ORG, "source_id": "org-src", "merge_event_id": "e",
                "preview_token": "t", "idempotency_key": "u", "reason": "r",
                "confirmation": True, "approval_id": "APR-FORGED"}


def _call(client, name):
    return {
        "preview": lambda: client.post("/api/master-data/merge/preview",
                                       json={"entity_type": ORG, "source_id": "org-src",
                                             "target_id": "org-tgt"}),
        "merge": lambda: client.post("/api/master-data/merge", json=MERGE_BODY),
        "unmerge_preview": lambda: client.post("/api/master-data/merge/unmerge/preview",
                                               json={"entity_type": ORG, "source_id": "org-src"}),
        "unmerge": lambda: client.post("/api/master-data/merge/unmerge", json=UNMERGE_BODY),
        "resolve": lambda: client.get("/api/master-data/organization/org-src/resolve"),
        "history": lambda: client.get("/api/master-data/organization/org-src/merge-history"),
    }[name]()


ENDPOINTS = ("preview", "merge", "unmerge_preview", "unmerge", "resolve", "history")


def _client(user):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")

    async def _session_user():
        return dict(user)

    app.dependency_overrides[get_current_user] = _session_user
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def armed(monkeypatch):
    touched = []

    def landmine(label):
        async def _boom(*a, **kw):
            touched.append(label)
            raise AssertionError("touched: %s" % label)
        return _boom

    monkeypatch.setattr(routes, "get_tenant_context", landmine("tenant resolver"))
    monkeypatch.setattr("app.tenancy.registry.get_tenant", landmine("tenant registry"))
    monkeypatch.setattr("app.audit.store.record_event", landmine("audit store"))
    for fn in ("preview_merge", "merge", "preview_unmerge", "unmerge", "resolve", "history"):
        monkeypatch.setattr(routes.merge_mod, fn, landmine("merge." + fn))
    monkeypatch.setattr("app.permissions.audit_hooks.audit_permission_denied",
                        landmine("denial audit"))
    return touched


def test_off_answers_every_merge_endpoint_without_touching_anything(monkeypatch, armed):
    monkeypatch.delenv(ENV_MODE, raising=False)
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    for name in ENDPOINTS:
        response = _call(_client(OWNER), name)
        assert response.status_code == 200, (name, response.text)
        assert response.json()["mode"] == "off"
    assert armed == []


def test_new_actions_are_owner_and_admin_only():
    new = {routes.ACTION_MERGE_PREVIEW, routes.ACTION_MERGE_EXECUTE, routes.ACTION_UNMERGE_EXECUTE}
    assert new <= catalog.ACTIONS
    for role_id in list(catalog.CANONICAL_ROLES) + list(catalog.LEGACY_ROLES):
        granted = catalog.role_actions(role_id) & new
        assert granted == (new if role_id in ("owner", "admin") else set()), role_id
    assert catalog.is_significant_action(routes.ACTION_MERGE_EXECUTE)
    assert catalog.is_significant_action(routes.ACTION_UNMERGE_EXECUTE)


@pytest.mark.parametrize("user", [OFFICE, DRIVER, WAREHOUSE, {"id": "u-none"}])
def test_every_other_role_is_refused_before_any_machinery(monkeypatch, armed, user):
    monkeypatch.setenv(ENV_MODE, "shadow")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    for name in ("preview", "merge", "unmerge_preview", "unmerge", "history"):
        response = _call(_client(user), name)
        assert response.status_code == 403, (name, response.status_code)
        assert "PERMISSION_DENIED" in response.text
    assert armed == [], "a forbidden request reached: %s" % armed


def test_a_refused_merge_is_audited_when_master_data_enforces(monkeypatch):
    monkeypatch.setenv(ENV_MODE, "enforce")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    db = world()
    ctx = Ctx(db=db, user_id="u-office")

    async def resolved(request, user):
        return ctx
    monkeypatch.setattr(routes, "get_tenant_context", resolved)

    for name, action in (("merge", routes.ACTION_MERGE_EXECUTE),
                         ("unmerge", routes.ACTION_UNMERGE_EXECUTE)):
        response = _call(_client(OFFICE), name)
        assert response.status_code == 403
        assert response.json()["detail"]["denial_audit"] == "recorded"
        event = audit(db)[-1]
        assert event["action"] == "permission.denied" and event["result"] == RESULT_DENIED
        assert action in event["reason"] and event["tenant_id"] == T_A
    assert db.business_snapshot() == world().business_snapshot()


def test_the_route_fails_closed_on_a_forged_approval_and_never_supplies_a_verifier(monkeypatch):
    monkeypatch.setenv(ENV_MODE, "enforce")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    db = world()
    ctx = Ctx(db=db, user_id="u-owner")

    async def resolved(request, user):
        return ctx
    monkeypatch.setattr(routes, "get_tenant_context", resolved)
    monkeypatch.setattr(mm, "_repository_for", lambda c: _repo(db, c.tenant_id))

    preview = _call(_client(OWNER), "preview").json()["preview"]
    assert preview["executable"] is False and preview["blocking"] == []
    body = dict(MERGE_BODY, preview_token=preview["preview_token"])
    response = _client(OWNER).post("/api/master-data/merge", json=body)
    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "APPROVAL_REQUIRED"
    assert org(db, "org-src")["status"] == "active" and db.docs(HISTORY_COLLECTION) == []

    seen = []
    real_merge = routes.merge_mod.merge

    async def spy(*a, **kw):
        seen.append(kw)
        return await real_merge(*a, **kw)
    monkeypatch.setattr(routes.merge_mod, "merge", spy)
    _client(ADMIN).post("/api/master-data/merge", json=body)
    assert seen and "approval_verifier" not in seen[0] and "_fail_after" not in seen[0]

    resolved_body = _call(_client(OWNER), "resolve").json()
    assert resolved_body["canonical_id"] == "org-src" and resolved_body["redirected"] is False


def test_a_tenant_in_a_merge_body_is_refused_not_ignored(monkeypatch, armed):
    monkeypatch.setenv(ENV_MODE, "enforce")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    db = world()
    db.explode_on_write = True

    async def resolved(request, user):
        return Ctx(db=db, user_id="u-owner")
    monkeypatch.setattr(routes, "get_tenant_context", resolved)
    for path, body in (("/api/master-data/merge", MERGE_BODY),
                       ("/api/master-data/merge/unmerge", UNMERGE_BODY),
                       ("/api/master-data/merge/preview",
                        {"entity_type": ORG, "source_id": "a", "target_id": "b"})):
        response = _client(OWNER).post(path, json=dict(body, tenant_id=T_B))
        assert response.status_code == 422, response.text
        assert "tenant_id" in response.text
    assert armed == [] and db.writes == []


def test_shadow_routes_write_nothing(monkeypatch):
    monkeypatch.setenv(ENV_MODE, "shadow")
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", "off")
    db = world()
    db.explode_on_read = db.explode_on_write = True

    async def resolved(request, user):
        return Ctx(db=db, user_id="u-owner")
    monkeypatch.setattr(routes, "get_tenant_context", resolved)
    monkeypatch.setattr(mm, "_repository_for", lambda c: _repo(db, c.tenant_id))
    for name in ENDPOINTS:
        response = _call(_client(OWNER), name)
        assert response.status_code == 200, (name, response.text)
        body = response.json()
        assert body["mode"] == "shadow" and body.get("performed") in (None, False)
    assert db.reads == [] and db.writes == []
