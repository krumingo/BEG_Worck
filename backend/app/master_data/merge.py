"""
W0-03D — Master Data merge, redirect history and immutable references.

FLOW-032 §"Merge и архивиране": duplicates are joined by a merge, never by a
deletion; who, when, which records and into which official Master is kept.
FLOW-032 §"Какво НЕ трябва да позволява": no merge without a preview and an
AuditEvent. Contract §6 W0-03D: preview first; a critical merge needs Approval;
old ids keep resolving; a redirect cycle is refused before any write;
rollback/unmerge keeps the history; a merge never deletes a record.

What a merge IS here — and deliberately nothing more:

  * the **source** record stays where it is, with every field it had. Only its
    lifecycle moves: ``status`` active -> merged and ``merged_into`` -> target;
  * the **target** record is not modified at all;
  * **references are not rewritten.** A pending row resolved to the source, a
    record that was earlier merged into the source, a legacy_ref on the source —
    each keeps the id it carries and reaches the target through the redirect
    (``resolve``). That is what makes the references immutable and the old ids
    keep resolving;
  * **conflicting fields are reported, never resolved.** Nothing is copied from
    source to target — no alias, no identifier, no name. Deciding which value
    wins would be heuristic conflict resolution, which W0-03D excludes; the
    preview shows the conflict and the human decides whether to merge at all;
  * one immutable event per merge and per unmerge in ``md_merge_history``,
    insert-only. An unmerge is a *new* event that names the merge it reverses;
    the merge event is never edited or removed.

**Approval — fail closed.** FLOW-032 §"Права" makes the Owner approve critical
changes with financial or historical weight. Which merges carry that weight is
not defined anywhere yet, so every merge and every unmerge is treated as
critical. Approval is proven only by an ``ApprovalVerifier`` that returns
``ApprovalEvidence`` bound to this exact tenant, action, records and preview
token. W0-07 (the Approval runtime) is NOT STARTED, so the only verifier this
build has is ``ApprovalRuntimeUnavailable``, which refuses everything. A
caller-supplied ``approval_id``, a role, or a dict shaped like evidence is not
proof. Consequently **merge and unmerge cannot execute in this build** — the
preview, the resolution of old ids and the refusal path are what is live.

**Atomicity — stated plainly.** The source record, the history event, the
AuditEvent and the idempotency registry are separate documents with no shared
transaction. The write is therefore a *recoverable* sequence, not an atomic
one, built from primitives that already exist:

    idempotency key reserved (W0-04 registry)
    -> per-(tenant, entity type) merge lock taken (``_id`` compare-and-set)
    -> source compare-and-set: still exactly the record the preview saw
    -> history event inserted under an id derived from the idempotency key
    -> canonical AuditEvent appended (skipped when this key already has one)
    -> idempotency completed, lock released

Every step can be re-run by retrying the SAME request: the source carries the
derived event id, so a retry recognises its own write; the history insert is
keyed by the same id; the audit step looks for its own event first. A failure
after the source write keeps the lock, so no other merge or unmerge of that
entity type can interleave with a half-finished one; the retry finishes it.
A crash that is never retried leaves the lock held and the key ``started`` —
visible reconciliation work, never a silent inconsistency.

Canon: FLOW-032, contract §5.2 / §6 W0-03D, TENANCY_MODEL.md §2/§6 (D-15),
FLOW-040 (AuditEvent), CLAUDE.md §7/§8/§14.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.master_data import models
from app.master_data.deps import (
    MODE_ENFORCE,
    MODE_OFF,
    MODE_SHADOW,
    MasterDataTenantContextMissing,
    require_tenant_context,
    resolve_mode,
)
from app.master_data.models import MasterDataInvalid
from app.master_data.service import (
    SOURCE_FLOW,
    MasterDataAuditFailed,
    MasterDataRefused,
    _reject_tenant_override,
    _require_actor,
)

HISTORY_COLLECTION = "md_merge_history"
LOCK_COLLECTION = "md_merge_locks"

KIND_MERGE = "merge"
KIND_UNMERGE = "unmerge"

ACTION_MERGE = "master_data.merge"
ACTION_UNMERGE = "master_data.unmerge"

#: Bumped when the preview's content or token recipe changes, so a token from an
#: older recipe can never match a newer one.
PREVIEW_VERSION = 1

#: A preview lists references one by one; beyond this it refuses to be
#: executable rather than summarise what a human cannot inspect.
REFERENCE_LIMIT = 500

#: Longest redirect chain ``resolve`` follows before refusing.
MAX_REDIRECT_DEPTH = 32

MAX_REASON = 500

#: Fields that describe the record's lifecycle or bookkeeping, not its identity.
#: They are not reported as conflicts.
_BOOKKEEPING = frozenset({
    "_id", "id", "tenant_id", "entity_type", "status", "merged_into",
    "created_at", "updated_at", "normalization_version",
    "merge_event_id", "merged_at", "merged_by", "merge_preview_token",
    "last_unmerge_event_id", "unmerged_at", "unmerged_by",
    "aliases", "identifiers", "legacy_refs",
})

_EVENT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://beg.work/master-data/merge")


# ---------------------------------------------------------------- exceptions
class MasterDataApprovalRequired(MasterDataRefused):
    """A critical operation without trusted Approval evidence. Fails closed."""


class MasterDataStalePreview(MasterDataRefused):
    """The records changed since the preview the human looked at."""


class MasterDataRedirectCycle(MasterDataRefused):
    """The redirect would form, or already forms, a cycle."""


class MasterDataMergeBusy(MasterDataRefused):
    """Another merge/unmerge of the same entity type holds the lock."""


# ------------------------------------------------------------------ approval
class ApprovalEvidence:
    """What a *trusted* Approval runtime hands back after checking an approval.

    Only an ``ApprovalVerifier`` constructs this. The merge accepts it only when
    every binding matches the operation it is about to perform.
    """

    __slots__ = ("approval_id", "tenant_id", "subject", "approver_id", "decided_at", "verifier")

    def __init__(self, *, approval_id: str, tenant_id: str, subject: Dict[str, Any],
                 approver_id: str, decided_at: str, verifier: str):
        self.approval_id = approval_id
        self.tenant_id = tenant_id
        self.subject = dict(subject)
        self.approver_id = approver_id
        self.decided_at = decided_at
        self.verifier = verifier

    def as_record(self) -> Dict[str, Any]:
        return {"approval_id": self.approval_id, "approver_id": self.approver_id,
                "decided_at": self.decided_at, "verifier": self.verifier}


class ApprovalRuntimeUnavailable:
    """The only verifier in this build. W0-07 is NOT STARTED: nothing can be
    checked, so nothing is approved. Pure — no read, no write."""

    name = "w0-07-not-started"

    async def verify(self, ctx: Any, *, approval_id: str, subject: Dict[str, Any]) -> ApprovalEvidence:
        raise MasterDataApprovalRequired(
            "approval %r cannot be verified: the W0-07 Approval runtime is NOT STARTED, and a "
            "caller-supplied approval id or role is not proof of approval — failing closed"
            % (approval_id,))


DEFAULT_APPROVAL_VERIFIER = ApprovalRuntimeUnavailable()


def _approval_subject(action: str, tenant_id: str, entity_type: str, source_id: str,
                      target_id: Optional[str], preview_token: str) -> Dict[str, Any]:
    """The exact thing an approval must be about (CLAUDE.md §8: exact version)."""
    return {"action": action, "tenant_id": tenant_id, "entity_type": entity_type,
            "source_id": source_id, "target_id": target_id, "preview_token": preview_token}


async def _verify_approval(ctx: Any, verifier: Any, approval_id: Optional[str],
                           subject: Dict[str, Any]) -> ApprovalEvidence:
    if not approval_id or not isinstance(approval_id, str) or not approval_id.strip():
        raise MasterDataApprovalRequired(
            "a merge or unmerge is a critical Master Data change and requires a trusted "
            "Approval (FLOW-032 §Права); none was given")
    try:
        evidence = await (verifier or DEFAULT_APPROVAL_VERIFIER).verify(
            ctx, approval_id=approval_id, subject=subject)
    except MasterDataRefused:
        raise
    except Exception as exc:                          # noqa: BLE001 — unknown is not approved
        raise MasterDataApprovalRequired(
            "approval %r could not be verified (%s); failing closed" % (approval_id, exc)) from exc
    # A verifier that answers with anything but evidence bound to THIS operation
    # has not approved it — whatever it says.
    if not isinstance(evidence, ApprovalEvidence):
        raise MasterDataApprovalRequired("approval %r: the verifier returned no evidence" % approval_id)
    if evidence.approval_id != approval_id:
        raise MasterDataApprovalRequired("approval evidence names a different approval")
    if evidence.tenant_id != ctx.tenant_id:
        raise MasterDataApprovalRequired("approval evidence belongs to another tenant")
    if evidence.subject != subject:
        raise MasterDataApprovalRequired(
            "approval %r was given for a different operation or preview version" % approval_id)
    if not evidence.approver_id or not evidence.decided_at:
        raise MasterDataApprovalRequired("approval evidence has no approver or decision time")
    return evidence


# ------------------------------------------------------------------- helpers
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def derived_event_id(tenant_id: str, kind: str, idempotency_key: str) -> str:
    """The history event id of one operation — the same on every retry."""
    return str(uuid.uuid5(_EVENT_NAMESPACE, "%s:%s:%s" % (tenant_id, kind, idempotency_key)))


def _lock_id(tenant_id: str, entity_type: str) -> str:
    key = "\x1f".join((tenant_id, entity_type)).encode("utf-8")
    return "merge-lock:" + hashlib.sha256(key).hexdigest()


def _is_duplicate_key(exc: BaseException) -> bool:
    return (type(exc).__name__ == "DuplicateKeyError"
            or getattr(exc, "code", None) == 11000
            or "duplicate key" in str(exc).lower())


def _require_entity_type(entity_type: Any) -> str:
    if entity_type not in models.ENTITY_TYPES:
        raise MasterDataInvalid("unknown entity_type: %s" % (entity_type,))
    return entity_type


def _require_id(value: Any, name: str) -> str:
    if not value or not isinstance(value, str) or not value.strip():
        raise MasterDataInvalid("%s is required" % name)
    return value


def _validate_reason(reason: Optional[str], required: bool) -> Optional[str]:
    if reason is None or (isinstance(reason, str) and not reason.strip()):
        if required:
            raise MasterDataInvalid("an unmerge must say why")
        return None
    if not isinstance(reason, str) or len(reason) > MAX_REASON:
        raise MasterDataInvalid("reason must be text of at most %d characters" % MAX_REASON)
    return reason.strip()


def _repository_for(ctx: Any):
    from app.master_data.repository import MasterDataRepository
    return MasterDataRepository(ctx.tenant_id)


async def _handle(repo) -> Any:
    return await repo.db()


async def _find_one(db, collection: str, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return await db[collection].find_one(query, {"_id": 0})


async def _find_all(db, collection: str, query: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    return await db[collection].find(query, {"_id": 0}).to_list(length=limit)


# ================================================================ resolution
async def _chain(db, tenant_id: str, entity_type: str, entity_id: str) -> List[Dict[str, Any]]:
    """The documents from ``entity_id`` to its canonical record, in order.

    Every hop is read inside the same tenant and the same type collection, so a
    redirect can never leave either. A hop that is missing there, a cycle, or a
    chain longer than ``MAX_REDIRECT_DEPTH`` is refused — never guessed.
    Returns ``[]`` when ``entity_id`` itself is not in this tenant/type.
    """
    coll = models_collection(entity_type)
    chain: List[Dict[str, Any]] = []
    seen = set()
    current = entity_id
    while True:
        if current in seen:
            raise MasterDataRedirectCycle(
                "redirect cycle in %s: %s" % (entity_type, " -> ".join([d["id"] for d in chain] + [current])))
        if len(chain) >= MAX_REDIRECT_DEPTH:
            raise MasterDataRefused("redirect chain from %s exceeds %d hops" % (entity_id, MAX_REDIRECT_DEPTH))
        seen.add(current)
        doc = await _find_one(db, coll, {"id": current, "tenant_id": tenant_id})
        if doc is None:
            if not chain:
                return []
            raise MasterDataRefused(
                "broken redirect: %s points at %s, which is not a %s of this tenant"
                % (chain[-1]["id"], current, entity_type))
        chain.append(doc)
        if doc.get("status") != models.STATUS_MERGED:
            return chain
        nxt = doc.get("merged_into")
        if not nxt or not isinstance(nxt, str):
            raise MasterDataRefused("record %s is merged but names no target" % current)
        current = nxt


def models_collection(entity_type: str) -> str:
    from app.master_data.repository import collection_name
    return collection_name(entity_type)


async def resolve(ctx: Any, *, entity_type: str, entity_id: str, mode: Any = None,
                  repository=None) -> Optional[Dict[str, Any]]:
    """Resolve any id — including an old, merged one — to its canonical record.

    ``off`` and ``shadow`` answer ``None`` without a read, like ``get_entity``:
    the canonical store is not a source of truth before ``enforce``.
    """
    effective = resolve_mode(mode)
    if effective in (MODE_OFF, MODE_SHADOW):
        return None
    ctx = require_tenant_context(ctx)
    _require_entity_type(entity_type)
    _require_id(entity_id, "entity_id")
    repo = repository if repository is not None else _repository_for(ctx)
    db = await _handle(repo)
    chain = await _chain(db, ctx.tenant_id, entity_type, entity_id)
    if not chain:
        return None
    return {"requested_id": entity_id, "canonical_id": chain[-1]["id"],
            "redirected": len(chain) > 1, "chain": [d["id"] for d in chain],
            "entity": chain[-1]}


async def history(ctx: Any, *, entity_type: str, entity_id: str, mode: Any = None,
                  repository=None, limit: int = 200) -> List[Dict[str, Any]]:
    """Every merge/unmerge event naming this record as source or target."""
    effective = resolve_mode(mode)
    if effective in (MODE_OFF, MODE_SHADOW):
        return []
    ctx = require_tenant_context(ctx)
    _require_entity_type(entity_type)
    repo = repository if repository is not None else _repository_for(ctx)
    db = await _handle(repo)
    events = await _find_all(db, HISTORY_COLLECTION, {
        "tenant_id": ctx.tenant_id, "entity_type": entity_type,
        "$or": [{"source_id": entity_id}, {"target_id": entity_id}]}, min(int(limit), 500))
    return sorted(events, key=lambda e: (e.get("recorded_at") or "", e.get("id") or ""))


# =================================================================== preview
def _alias_report(source: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, List[str]]:
    s = {a.get("normalized"): a.get("value") for a in (source.get("aliases") or []) if isinstance(a, dict)}
    t = {a.get("normalized"): a.get("value") for a in (target.get("aliases") or []) if isinstance(a, dict)}
    return {"source_only": sorted(s[k] for k in s if k not in t),
            "target_only": sorted(t[k] for k in t if k not in s),
            "shared": sorted(s[k] for k in s if k in t)}


def _identifier_report(source: Dict[str, Any], target: Dict[str, Any]):
    def by_kind(doc):
        out: Dict[str, set] = {}
        for ident in doc.get("identifiers") or []:
            if isinstance(ident, dict) and ident.get("key"):
                out.setdefault(ident.get("kind"), set()).add(ident["key"])
        return out
    s, t = by_kind(source), by_kind(target)
    s_keys = set().union(*s.values()) if s else set()
    t_keys = set().union(*t.values()) if t else set()
    report = {"source_only": sorted(s_keys - t_keys), "target_only": sorted(t_keys - s_keys),
              "shared": sorted(s_keys & t_keys)}
    conflicts = []
    for kind in sorted(set(s) & set(t)):
        if s[kind] != t[kind]:
            conflicts.append({"field": "identifiers.%s" % kind,
                              "source_value": sorted(s[kind]), "target_value": sorted(t[kind])})
    return report, conflicts


def _field_conflicts(source: Dict[str, Any], target: Dict[str, Any]) -> List[Dict[str, Any]]:
    conflicts = []
    for field in sorted((set(source) | set(target)) - _BOOKKEEPING):
        sv, tv = source.get(field), target.get(field)
        if sv is None or tv is None or sv == tv:
            continue
        conflicts.append({"field": field, "source_value": sv, "target_value": tv})
    return conflicts


_NO_RESOLUTION = ("none — the target keeps its value; the source value stays on the preserved "
                  "source record and is not copied")


async def _references(db, tenant_id: str, entity_type: str, source: Dict[str, Any]):
    from app.master_data.pending import PENDING_COLLECTION
    pending = await _find_all(db, PENDING_COLLECTION, {
        "tenant_id": tenant_id, "entity_type": entity_type,
        "resolved_entity_id": source["id"]}, REFERENCE_LIMIT + 1)
    redirected = await _find_all(db, models_collection(entity_type), {
        "tenant_id": tenant_id, "merged_into": source["id"]}, REFERENCE_LIMIT + 1)
    legacy = sorted(({"collection": r.get("collection"), "legacy_id": r.get("legacy_id")}
                     for r in (source.get("legacy_refs") or []) if isinstance(r, dict)),
                    key=_canonical_json)
    refs = {
        "pending_resolved_to_source": sorted(p["id"] for p in pending if p.get("id")),
        "records_redirected_into_source": sorted(d["id"] for d in redirected if d.get("id")),
        "legacy_refs_of_source": legacy,
        "handling": "not rewritten — each keeps the source id and resolves to the target "
                    "through the redirect",
    }
    truncated = len(pending) > REFERENCE_LIMIT or len(redirected) > REFERENCE_LIMIT
    return refs, truncated


def _record_view(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": doc.get("id"), "display_name": doc.get("display_name"),
            "normalized_name": doc.get("normalized_name"), "status": doc.get("status"),
            "merged_into": doc.get("merged_into"), "updated_at": doc.get("updated_at")}


def _approval_view(verifier: Any) -> Dict[str, Any]:
    unavailable = verifier is None or isinstance(verifier, ApprovalRuntimeUnavailable)
    return {"required": True, "critical": True,
            "why": "every merge/unmerge is treated as a critical Master Data change until a "
                   "canonical rule says which ones are not (FLOW-032 §Права); fail closed",
            "runtime_available": not unavailable,
            "runtime": ("W0-07 Approval runtime NOT STARTED — execution fails closed"
                        if unavailable else getattr(verifier, "name", "injected verifier"))}


async def _build_preview(db, tenant_id: str, entity_type: str, source_id: str, target_id: str,
                         verifier: Any = None) -> Dict[str, Any]:
    if source_id == target_id:
        raise MasterDataInvalid("a record cannot be merged into itself")
    coll = models_collection(entity_type)
    source = await _find_one(db, coll, {"id": source_id, "tenant_id": tenant_id})
    target = await _find_one(db, coll, {"id": target_id, "tenant_id": tenant_id})
    # Another tenant's record and a record of another type are simply not here:
    # the lookups are pinned to this tenant and this type's collection.
    if source is None:
        raise MasterDataRefused("source %s is not a %s of this tenant" % (source_id, entity_type))
    if target is None:
        raise MasterDataRefused("target %s is not a %s of this tenant" % (target_id, entity_type))

    blocking: List[str] = []
    if source.get("status") != models.STATUS_ACTIVE:
        blocking.append("source is %s, not active" % source.get("status"))
    try:
        target_chain = await _chain(db, tenant_id, entity_type, target_id)
        if source_id in [d["id"] for d in target_chain]:
            blocking.append("redirect cycle: the target already resolves through the source "
                            "(%s)" % " -> ".join(d["id"] for d in target_chain))
    except MasterDataRedirectCycle as exc:
        blocking.append(str(exc))
    if target.get("status") != models.STATUS_ACTIVE and not any("cycle" in b for b in blocking):
        blocking.append("target is %s, not an active canonical record%s" % (
            target.get("status"),
            "; it resolves to %s" % target.get("merged_into") if target.get("merged_into") else ""))

    references, truncated = await _references(db, tenant_id, entity_type, source)
    if truncated:
        blocking.append("more than %d references — too many for a preview a person can inspect"
                        % REFERENCE_LIMIT)
    identifiers, ident_conflicts = _identifier_report(source, target)
    conflicts = _field_conflicts(source, target)
    if source.get("display_name") != target.get("display_name") and not any(
            c["field"] == "display_name" for c in conflicts):
        conflicts.append({"field": "display_name", "source_value": source.get("display_name"),
                          "target_value": target.get("display_name")})
    conflicts = sorted(conflicts + ident_conflicts, key=lambda c: c["field"])
    for c in conflicts:
        c["resolution"] = _NO_RESOLUTION

    coll_label = "%s/%s" % (coll, source_id)
    effects = [
        {"write": coll_label, "change": {"status": [source.get("status"), models.STATUS_MERGED],
                                          "merged_into": [source.get("merged_into"), target_id]},
         "also_set": ["merge_event_id", "merged_at", "merged_by", "merge_preview_token", "updated_at"]},
        {"write": HISTORY_COLLECTION, "change": "append one immutable '%s' event" % KIND_MERGE},
        {"write": "audit_events", "change": "append one canonical AuditEvent master_data.%s.merged"
                                            % entity_type},
        {"write": "audit_idempotency, %s" % LOCK_COLLECTION, "change": "operation bookkeeping"},
    ]
    not_changed = [
        "the target record %s" % target_id,
        "aliases and identifiers of either record (nothing is copied)",
        "pending rows and records that reference the source (resolved through the redirect)",
        "every other record; nothing is deleted",
    ]
    token_basis = {"preview_version": PREVIEW_VERSION, "tenant_id": tenant_id,
                   "entity_type": entity_type, "source": source, "target": target,
                   "references": references}
    preview = {
        "preview_version": PREVIEW_VERSION,
        "kind": KIND_MERGE,
        "entity_type": entity_type,
        "source": _record_view(source),
        "target": _record_view(target),
        "references": references,
        "aliases": _alias_report(source, target),
        "identifiers": identifiers,
        "conflicts": conflicts,
        "effects": effects,
        "not_changed": not_changed,
        "blocking": blocking,
        "approval": _approval_view(verifier),
        "executable": not blocking and _approval_view(verifier)["runtime_available"],
        "preview_token": _digest(token_basis),
    }
    return preview


async def preview_merge(ctx: Any, *, entity_type: str, source_id: str, target_id: str,
                        mode: Any = None, repository=None,
                        approval_verifier: Any = None) -> Optional[Dict[str, Any]]:
    """What merging ``source_id`` into ``target_id`` would do. Never writes.

    Deterministic: the same records give the same preview and the same
    ``preview_token``; any change to either record or to the references the
    preview lists gives a different token, which the merge then refuses.
    ``off`` and ``shadow`` answer ``None`` without a read.
    """
    effective = resolve_mode(mode)
    if effective in (MODE_OFF, MODE_SHADOW):
        return None
    ctx = require_tenant_context(ctx)
    _require_entity_type(entity_type)
    _require_id(source_id, "source_id")
    _require_id(target_id, "target_id")
    repo = repository if repository is not None else _repository_for(ctx)
    db = await _handle(repo)
    return await _build_preview(db, ctx.tenant_id, entity_type, source_id, target_id,
                                approval_verifier)


async def _build_unmerge_preview(db, tenant_id: str, entity_type: str, source_id: str,
                                 verifier: Any = None) -> Dict[str, Any]:
    coll = models_collection(entity_type)
    source = await _find_one(db, coll, {"id": source_id, "tenant_id": tenant_id})
    if source is None:
        raise MasterDataRefused("record %s is not a %s of this tenant" % (source_id, entity_type))
    blocking: List[str] = []
    event = None
    if source.get("status") != models.STATUS_MERGED:
        blocking.append("record is %s; only a merged record can be unmerged" % source.get("status"))
    else:
        event = await _find_one(db, HISTORY_COLLECTION, {
            "id": source.get("merge_event_id"), "tenant_id": tenant_id, "kind": KIND_MERGE})
        if event is None:
            blocking.append("the merge that redirected this record has no history event "
                            "(interrupted merge — retry it first)")
    before = (event or {}).get("source_before") or {}
    restored = before.get("status") or models.STATUS_ACTIVE
    token_basis = {"preview_version": PREVIEW_VERSION, "kind": KIND_UNMERGE,
                   "tenant_id": tenant_id, "entity_type": entity_type,
                   "source": source, "merge_event": event}
    return {
        "preview_version": PREVIEW_VERSION,
        "kind": KIND_UNMERGE,
        "entity_type": entity_type,
        "source": _record_view(source),
        "reverses_event_id": source.get("merge_event_id"),
        "effects": [
            {"write": "%s/%s" % (coll, source_id),
             "change": {"status": [source.get("status"), restored],
                        "merged_into": [source.get("merged_into"), None]},
             "also_set": ["last_unmerge_event_id", "unmerged_at", "unmerged_by", "updated_at"]},
            {"write": HISTORY_COLLECTION,
             "change": "append one immutable '%s' event naming the merge it reverses" % KIND_UNMERGE},
            {"write": "audit_events",
             "change": "append one canonical AuditEvent master_data.%s.unmerged" % entity_type},
        ],
        "not_changed": ["the merge event stays in the history, unedited",
                        "the former target record", "every other record; nothing is deleted"],
        "blocking": blocking,
        "approval": _approval_view(verifier),
        "executable": not blocking and _approval_view(verifier)["runtime_available"],
        "preview_token": _digest(token_basis),
    }


async def preview_unmerge(ctx: Any, *, entity_type: str, source_id: str, mode: Any = None,
                          repository=None, approval_verifier: Any = None) -> Optional[Dict[str, Any]]:
    """What reversing the current merge of ``source_id`` would do. Never writes."""
    effective = resolve_mode(mode)
    if effective in (MODE_OFF, MODE_SHADOW):
        return None
    ctx = require_tenant_context(ctx)
    _require_entity_type(entity_type)
    _require_id(source_id, "source_id")
    repo = repository if repository is not None else _repository_for(ctx)
    db = await _handle(repo)
    return await _build_unmerge_preview(db, ctx.tenant_id, entity_type, source_id,
                                        approval_verifier)


# ================================================================== outcome
class MergeOutcome:
    """What a merge/unmerge did. ``performed`` only after the write AND its
    canonical AuditEvent; ``replayed`` when an identical, already completed
    request was answered from the idempotency registry."""

    __slots__ = ("mode", "performed", "kind", "event_id", "source_id", "target_id",
                 "reason", "would_perform", "replayed", "resumed")

    def __init__(self, mode: str, performed: bool, kind: str, *, event_id: Optional[str] = None,
                 source_id: Optional[str] = None, target_id: Optional[str] = None,
                 reason: Optional[str] = None, would_perform: Optional[bool] = None,
                 replayed: bool = False, resumed: bool = False):
        self.mode = mode
        self.performed = performed
        self.kind = kind
        self.event_id = event_id
        self.source_id = source_id
        self.target_id = target_id
        self.reason = reason
        self.would_perform = would_perform
        self.replayed = replayed
        self.resumed = resumed

    def as_dict(self) -> Dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}

    def __repr__(self) -> str:                                   # pragma: no cover
        return "MergeOutcome(%r)" % (self.as_dict(),)


# ==================================================================== audit
async def _audit(ctx: Any, *, action: str, result: str, entity_type: str, entity_id: str,
                 actor_id: str, reason: str, idempotency_key: Optional[str] = None,
                 approval_id: Optional[str] = None, before: Optional[str] = None,
                 after: Optional[str] = None, diff: Optional[Dict[str, Any]] = None,
                 entity_version: Optional[str] = None, error_code: Optional[str] = None,
                 correlation_id: Optional[str] = None) -> Dict[str, Any]:
    from app.audit.envelope import ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    event = build_event(
        tenant_id=ctx.tenant_id, actor_type=ACTOR_HUMAN, actor_id=actor_id, action=action,
        source_flow=SOURCE_FLOW, retention_class=RETENTION_R1_CRITICAL_BUSINESS, result=result,
        entity_type="master_data.%s" % entity_type, entity_id=entity_id,
        entity_version=entity_version, before_reference=before, after_reference=after,
        structured_diff=diff, reason=reason, approval_id=approval_id,
        idempotency_key=idempotency_key, error_code=error_code, correlation_id=correlation_id,
    )
    return await record_event(await ctx.db(), event)


async def _audit_refusal(ctx: Any, *, kind: str, entity_type: str, source_id: str,
                         target_id: Optional[str], actor_id: str, exc: Exception,
                         idempotency_key: Optional[str], approval_id: Optional[str]) -> None:
    """A refused merge/unmerge in ``enforce`` leaves evidence. If the evidence
    itself cannot be written the refusal still stands and says so."""
    from app.audit.envelope import RESULT_DENIED, RESULT_FAILURE
    denied = isinstance(exc, MasterDataApprovalRequired)
    code = {MasterDataApprovalRequired: "APPROVAL_REQUIRED", MasterDataStalePreview: "STALE_PREVIEW",
            MasterDataRedirectCycle: "REDIRECT_CYCLE", MasterDataMergeBusy: "MERGE_BUSY"}.get(
                type(exc), "REFUSED")
    try:
        await _audit(ctx, action="master_data.%s.%s_refused" % (entity_type, kind),
                     result=RESULT_DENIED if denied else RESULT_FAILURE, entity_type=entity_type,
                     entity_id=source_id, actor_id=actor_id, reason=str(exc)[:MAX_REASON],
                     idempotency_key=idempotency_key, after=target_id, error_code=code,
                     # never in the envelope's approval_id: it was not verified
                     diff={"claimed_approval_id": approval_id} if approval_id else None)
    except Exception as audit_exc:                    # noqa: BLE001
        raise MasterDataAuditFailed(
            "%s of %s was refused (%s) and the refusal's AuditEvent also failed (%s)"
            % (kind, source_id, exc, audit_exc)) from exc


async def _audit_once(ctx: Any, db, *, action: str, idempotency_key: str, **kwargs) -> None:
    """Append the success event unless this operation already has one — the
    retry of an attempt that died after auditing must not audit twice."""
    from app.audit.store import AUDIT_COLLECTION
    existing = await db[AUDIT_COLLECTION].find_one(
        {"tenant_id": ctx.tenant_id, "action": action, "idempotency_key": idempotency_key,
         "result": "success"}, {"_id": 0})
    if existing is None:
        await _audit(ctx, action=action, idempotency_key=idempotency_key, **kwargs)


# ============================================================ lock / registry
async def _take_lock(db, tenant_id: str, entity_type: str, holder: str, attempt: str,
                     now: str) -> None:
    """Serialise merges and unmerges of one entity type in one tenant.

    Two concurrent merges A->B and B->A would each pass a cycle check that the
    other has not yet invalidated; the lock makes the check and the write one
    critical section. Built on the unique ``_id`` every collection already has
    — no new index, and no lock document is ever deleted.

    ``holder`` is the operation (derived from its idempotency key), ``attempt``
    is this call. A second call of the SAME operation gets in only when the
    attempt holding the lock recorded that it was interrupted; a double click
    that arrives while the first call is still working is refused, because
    nothing can tell a live caller from a dead one. An attempt that dies without
    reaching its own error handler leaves the lock held — reconciliation work,
    never two callers in the critical section.
    """
    locks = db[LOCK_COLLECTION]
    lock_id = _lock_id(tenant_id, entity_type)
    try:
        await locks.update_one(
            {"_id": lock_id, "tenant_id": tenant_id, "holder": None},
            {"$set": {"holder": holder, "attempt": attempt, "interrupted": False, "taken_at": now},
             "$setOnInsert": {"entity_type": entity_type}},
            upsert=True)
    except Exception as exc:                          # noqa: BLE001 — only a duplicate is expected
        if not _is_duplicate_key(exc):
            raise
    current = await locks.find_one({"_id": lock_id, "tenant_id": tenant_id}) or {}
    if current.get("holder") == holder and current.get("attempt") != attempt \
            and current.get("interrupted") is True:
        await locks.update_one(
            {"_id": lock_id, "tenant_id": tenant_id, "holder": holder,
             "attempt": current.get("attempt"), "interrupted": True},
            {"$set": {"attempt": attempt, "interrupted": False, "retaken_at": now}})
        current = await locks.find_one({"_id": lock_id, "tenant_id": tenant_id}) or {}
    if current.get("holder") != holder or current.get("attempt") != attempt:
        busy = MasterDataMergeBusy(
            "another merge/unmerge of %s is in progress or was interrupted (%s); retry that "
            "operation with its own key first" % (entity_type, current.get("holder")))
        busy.same_operation = current.get("holder") == holder
        raise busy


async def _release_lock(db, tenant_id: str, entity_type: str, holder: str, attempt: str,
                        now: str) -> None:
    await db[LOCK_COLLECTION].update_one(
        {"_id": _lock_id(tenant_id, entity_type), "tenant_id": tenant_id, "holder": holder,
         "attempt": attempt},
        {"$set": {"holder": None, "attempt": None, "interrupted": False, "released_at": now}})


async def _mark_lock_interrupted(db, tenant_id: str, entity_type: str, holder: str,
                                 attempt: str, now: str) -> None:
    """Keep the lock with the operation, but let ITS retry take it over."""
    await db[LOCK_COLLECTION].update_one(
        {"_id": _lock_id(tenant_id, entity_type), "tenant_id": tenant_id, "holder": holder,
         "attempt": attempt},
        {"$set": {"interrupted": True, "interrupted_at": now}})


async def _idempotency_state(db, tenant_id: str, action: str, key: str,
                             fingerprint: str) -> Optional[Dict[str, Any]]:
    """Read-only look at the registry before anything is written."""
    from app.audit.idempotency import IDEMPOTENCY_COLLECTION, _record_id
    record = await db[IDEMPOTENCY_COLLECTION].find_one({"id": _record_id(tenant_id, action, key)},
                                                       {"_id": 0})
    if record and record.get("request_fingerprint") not in (None, fingerprint):
        raise MasterDataRefused(
            "idempotency key %r was already used for a different %s request" % (key, action))
    return record




# ============================================================ the recoverable run
class _Interrupted(RuntimeError):
    """Raised by ``_fail_after`` to model a crash between two steps."""


def _maybe_fail(fail_after: Optional[str], step: str) -> None:
    if fail_after == step:
        raise _Interrupted("simulated interruption after %s" % step)


class _Plan:
    """What differs between a merge and an unmerge; ``_run`` does the rest."""

    def __init__(self, *, kind, action, entity_type, source_id, target_id, key, event_id,
                 preview_token, check, is_own, cas, history_doc, audit_kwargs):
        self.kind = kind
        self.action = action
        self.entity_type = entity_type
        self.source_id = source_id
        self.target_id = target_id
        self.key = key
        self.event_id = event_id
        self.preview_token = preview_token
        self.check = check                  # async (db) -> state; read-only; raises a refusal
        self.is_own = is_own                # (state) -> True when this operation already wrote
        self.cas = cas                      # async (db, state, now, actor) -> bool
        self.history_doc = history_doc      # async (db, state, now, actor, evidence) -> dict
        self.audit_kwargs = audit_kwargs    # (state, evidence) -> dict


async def _run(ctx: Any, db, plan: _Plan, *, actor_id: str, approval_id: Optional[str],
               verifier: Any, subject: Dict[str, Any], fingerprint: str,
               fail_after: Optional[str]) -> MergeOutcome:
    from app.audit.idempotency import (
        IDEMPOTENCY_COMPLETED, IDEMPOTENCY_DUPLICATE, begin_idempotent, complete_idempotent,
        fail_idempotent, mark_idempotent_step)
    tenant_id = ctx.tenant_id

    def outcome(event_id, **kw):
        return MergeOutcome(MODE_ENFORCE, True, plan.kind, event_id=event_id,
                            source_id=plan.source_id, target_id=plan.target_id, **kw)

    # 1. an identical request that already completed is answered, not redone
    prior = await _idempotency_state(db, tenant_id, plan.action, plan.key, fingerprint)
    if prior and prior.get("status") == IDEMPOTENCY_COMPLETED:
        return outcome(prior.get("result_reference"), replayed=True,
                       reason="already completed under this idempotency key")

    async def refuse(exc: Exception):
        await _audit_refusal(ctx, kind=plan.kind, entity_type=plan.entity_type,
                             source_id=plan.source_id, target_id=plan.target_id,
                             actor_id=actor_id, exc=exc, idempotency_key=plan.key,
                             approval_id=approval_id)
        raise exc

    async def fail(code: str):
        await fail_idempotent(db, tenant_id=tenant_id, key=plan.key, action=plan.action,
                              error_code=code)

    # 2. read-only checks BEFORE any write: records, cycle, preview token, approval
    try:
        await plan.check(db)
        evidence = await _verify_approval(ctx, verifier, approval_id, subject)
    except MasterDataRefused as exc:
        await refuse(exc)

    # 3. bookkeeping: reserve the key, take the lock
    state = await begin_idempotent(db, tenant_id=tenant_id, key=plan.key, action=plan.action,
                                   request_fingerprint=fingerprint)
    if state.get("status") == IDEMPOTENCY_DUPLICATE and state.get("prior_status") == IDEMPOTENCY_COMPLETED:
        return outcome(state.get("result_reference"), replayed=True)
    resumed = state.get("status") == IDEMPOTENCY_DUPLICATE or bool(state.get("retry_of_failed"))
    attempt = uuid.uuid4().hex
    try:
        await _take_lock(db, tenant_id, plan.entity_type, plan.event_id, attempt, _now())
    except MasterDataMergeBusy as exc:
        if not getattr(exc, "same_operation", False):
            await fail("MERGE_BUSY")        # our own key; a live duplicate's is left alone
        await refuse(exc)

    written = False
    try:
        # 4. re-check under the lock: nothing may have changed since step 2
        try:
            current = await plan.check(db)
        except MasterDataRefused as exc:
            await fail("REFUSED_UNDER_LOCK")
            await _release_lock(db, tenant_id, plan.entity_type, plan.event_id, attempt, _now())
            await refuse(exc)
        now = _now()
        # 5. the compare-and-set on the source — the only change to a Master record
        if not plan.is_own(current):
            if not await plan.cas(db, current, now, actor_id):
                await fail("STALE_PREVIEW")
                await _release_lock(db, tenant_id, plan.entity_type, plan.event_id, attempt, _now())
                await refuse(MasterDataStalePreview(
                    "%s changed while the %s was being written" % (plan.source_id, plan.kind)))
            await mark_idempotent_step(db, tenant_id=tenant_id, key=plan.key, action=plan.action,
                                       step="source_written", reference=plan.event_id)
        written = True
        _maybe_fail(fail_after, "source_written")

        # 6. the immutable history event, keyed by the derived id
        await _insert_history(db, await plan.history_doc(db, current, now, actor_id, evidence))
        _maybe_fail(fail_after, "history_recorded")

        # 7. the canonical AuditEvent — once per operation, also across retries
        await _audit_once(ctx, db, action="master_data.%s.%sd" % (plan.entity_type, plan.kind),
                          idempotency_key=plan.key, result="success", entity_type=plan.entity_type,
                          entity_id=plan.source_id, actor_id=actor_id,
                          approval_id=evidence.approval_id, entity_version=plan.preview_token,
                          **plan.audit_kwargs(current, evidence))
        _maybe_fail(fail_after, "audited")

        await complete_idempotent(db, tenant_id=tenant_id, key=plan.key, action=plan.action,
                                  result_reference=plan.event_id)
        await _release_lock(db, tenant_id, plan.entity_type, plan.event_id, attempt, _now())
    except (MasterDataRefused, MasterDataInvalid, MasterDataAuditFailed):
        raise
    except Exception as exc:                          # noqa: BLE001 — recorded, then re-raised
        await _record_interruption(db, tenant_id, plan, attempt, written)
        if isinstance(exc, _Interrupted):
            raise
        raise MasterDataAuditFailed(
            "%s of %s was interrupted after %s (%s: %s); the operation is NOT successful and its "
            "state is recorded — repeat the SAME request to finish it"
            % (plan.kind, plan.source_id, "the record was written" if written else "no write",
               type(exc).__name__, exc)) from exc

    return outcome(plan.event_id, resumed=resumed)


async def _record_interruption(db, tenant_id: str, plan: _Plan, attempt: str, written: bool) -> None:
    from app.audit.idempotency import fail_idempotent
    try:
        await fail_idempotent(db, tenant_id=tenant_id, key=plan.key, action=plan.action,
                              error_code="WRITE_INCOMPLETE" if written else "INTERRUPTED")
        if written:
            # The lock stays with this operation; only its own retry may take it.
            await _mark_lock_interrupted(db, tenant_id, plan.entity_type, plan.event_id,
                                         attempt, _now())
        else:
            await _release_lock(db, tenant_id, plan.entity_type, plan.event_id, attempt, _now())
    except Exception:                                 # noqa: BLE001 — the original error wins
        pass


async def _insert_history(db, event: Dict[str, Any]) -> None:
    """Insert-only. A retry that finds its own event (same derived id) is done."""
    try:
        await db[HISTORY_COLLECTION].insert_one(dict(event))
    except Exception as exc:                          # noqa: BLE001 — only a duplicate is expected
        if not _is_duplicate_key(exc):
            raise
        existing = await _find_one(db, HISTORY_COLLECTION, {"id": event["id"],
                                                            "tenant_id": event["tenant_id"]})
        if not existing or existing.get("kind") != event["kind"] \
                or existing.get("source_id") != event["source_id"]:
            raise MasterDataRefused("history event %s exists with other content" % event["id"])


# ===================================================================== merge
def _check_merge_args(entity_type, source_id, target_id, preview_token, idempotency_key,
                      confirmation, reason) -> Optional[str]:
    _require_entity_type(entity_type)
    _require_id(source_id, "source_id")
    _require_id(target_id, "target_id")
    if source_id == target_id:
        raise MasterDataInvalid("a record cannot be merged into itself")
    _require_id(preview_token, "preview_token (a merge without a preview is refused)")
    _require_id(idempotency_key, "idempotency_key")
    if confirmation is not True:
        raise MasterDataRefused("a merge requires explicit human confirmation of the preview")
    return _validate_reason(reason, required=False)


async def _check_merge_state(db, tenant_id, entity_type, source_id, target_id, preview_token,
                             event_id) -> Dict[str, Any]:
    """Refuse unless the records are exactly what the preview showed — or the
    source already carries THIS operation's redirect (an interrupted retry)."""
    source = await _find_one(db, models_collection(entity_type),
                             {"id": source_id, "tenant_id": tenant_id})
    if source is None:
        raise MasterDataRefused("source %s is not a %s of this tenant" % (source_id, entity_type))
    if source.get("merge_event_id") == event_id:
        if source.get("merged_into") != target_id or source.get("merge_preview_token") != preview_token:
            raise MasterDataStalePreview("source %s carries this operation with other data" % source_id)
        return source
    preview = await _build_preview(db, tenant_id, entity_type, source_id, target_id)
    if preview["blocking"]:
        cls = MasterDataRedirectCycle if any("cycle" in b for b in preview["blocking"]) \
            else MasterDataRefused
        raise cls("merge refused before any write: " + "; ".join(preview["blocking"]))
    if preview["preview_token"] != preview_token:
        raise MasterDataStalePreview(
            "the records changed since the preview (token mismatch); preview again and review "
            "the new effects")
    return source


async def merge(
    ctx: Any,
    *,
    entity_type: str,
    source_id: str,
    target_id: str,
    preview_token: str,
    idempotency_key: str,
    confirmation: bool = False,
    approval_id: Optional[str] = None,
    reason: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    mode: Any = None,
    repository=None,
    approval_verifier: Any = None,
    _fail_after: Optional[str] = None,
) -> MergeOutcome:
    """Merge ``source_id`` into ``target_id`` exactly as the preview described.

    ``off`` is inert; ``shadow`` validates what it can without a read and
    writes nothing; ``enforce`` writes only with a verified Approval — which in
    this build means never (see the module docstring). ``_fail_after`` exists
    only for the interrupted-write tests: it names a step after which the call
    raises, the way a crash would.
    """
    effective = resolve_mode(mode)
    if effective == MODE_OFF:
        return MergeOutcome(MODE_OFF, False, KIND_MERGE, reason="master data is off")

    if effective == MODE_SHADOW:
        try:
            validated = require_tenant_context(ctx)
            _reject_tenant_override(payload)
            _require_actor(validated)
            _check_merge_args(entity_type, source_id, target_id, preview_token,
                              idempotency_key, confirmation, reason)
            if approval_verifier is None:           # the default verifier is pure
                await _verify_approval(validated, None, approval_id, _approval_subject(
                    ACTION_MERGE, validated.tenant_id, entity_type, source_id, target_id,
                    preview_token))
        except (MasterDataRefused, MasterDataInvalid, MasterDataTenantContextMissing) as exc:
            return MergeOutcome(MODE_SHADOW, False, KIND_MERGE, source_id=source_id,
                                target_id=target_id, reason=str(exc), would_perform=False)
        return MergeOutcome(MODE_SHADOW, False, KIND_MERGE, source_id=source_id, target_id=target_id,
                            reason="shadow: nothing written; records are checked only in enforce",
                            would_perform=None)

    # --- enforce -------------------------------------------------------------
    ctx = require_tenant_context(ctx)
    _reject_tenant_override(payload)
    actor_id = _require_actor(ctx)
    reason = _check_merge_args(entity_type, source_id, target_id, preview_token,
                               idempotency_key, confirmation, reason)
    repo = repository if repository is not None else _repository_for(ctx)
    db = await _handle(repo)
    tenant_id = ctx.tenant_id
    event_id = derived_event_id(tenant_id, KIND_MERGE, idempotency_key)
    from app.audit.idempotency import request_fingerprint

    async def check(handle):
        return await _check_merge_state(handle, tenant_id, entity_type, source_id, target_id,
                                        preview_token, event_id)

    async def cas(handle, source, now, actor):
        result = await handle[models_collection(entity_type)].update_one(
            {"id": source_id, "tenant_id": tenant_id, "status": models.STATUS_ACTIVE,
             "merged_into": None, "updated_at": source.get("updated_at")},
            {"$set": {"status": models.STATUS_MERGED, "merged_into": target_id,
                      "merge_event_id": event_id, "merged_at": now, "merged_by": actor,
                      "merge_preview_token": preview_token, "updated_at": now}})
        return getattr(result, "modified_count", 0) == 1

    async def history_doc(handle, source, now, actor, evidence):
        return {"_id": event_id, "id": event_id, "tenant_id": tenant_id,
                "entity_type": entity_type, "kind": KIND_MERGE, "source_id": source_id,
                "target_id": target_id, "preview_token": preview_token,
                "source_before": await _source_before(handle, tenant_id, event_id, source),
                "actor_id": actor, "approval": evidence.as_record(), "reason": reason,
                "idempotency_key": idempotency_key, "recorded_at": now}

    plan = _Plan(
        kind=KIND_MERGE, action=ACTION_MERGE, entity_type=entity_type, source_id=source_id,
        target_id=target_id, key=idempotency_key, event_id=event_id, preview_token=preview_token,
        check=check, is_own=lambda source: source.get("merge_event_id") == event_id, cas=cas,
        history_doc=history_doc,
        audit_kwargs=lambda source, evidence: {
            "reason": reason or "Master Data merge after preview and approval",
            "after": target_id, "correlation_id": event_id,
            "diff": {"status": [models.STATUS_ACTIVE, models.STATUS_MERGED],
                     "merged_into": [None, target_id], "merge_event_id": event_id}})
    fingerprint = request_fingerprint({
        "entity_type": entity_type, "source_id": source_id, "target_id": target_id,
        "preview_token": preview_token, "approval_id": approval_id, "reason": reason})
    return await _run(ctx, db, plan, actor_id=actor_id, approval_id=approval_id,
                      verifier=approval_verifier,
                      subject=_approval_subject(ACTION_MERGE, tenant_id, entity_type, source_id,
                                                target_id, preview_token),
                      fingerprint=fingerprint, fail_after=_fail_after)


async def _source_before(db, tenant_id: str, event_id: str, source: Dict[str, Any]) -> Dict[str, Any]:
    """The source exactly as it was before this merge.

    On a first attempt that is the document the compare-and-set just changed.
    On a retry after the redirect was written but the history was not, the
    pre-merge document is reconstructed from the fields the compare-and-set
    set — nothing else was changed — and marked as reconstructed.
    """
    if source.get("merge_event_id") != event_id:
        return dict(source)
    existing = await _find_one(db, HISTORY_COLLECTION, {"id": event_id, "tenant_id": tenant_id})
    if existing is not None:
        return existing.get("source_before") or {}
    restored = {k: v for k, v in source.items()
                if k not in ("merge_event_id", "merged_at", "merged_by", "merge_preview_token",
                             "updated_at")}
    restored.update({"status": models.STATUS_ACTIVE, "merged_into": None,
                     "reconstructed_after_interruption": True})
    return restored


# =================================================================== unmerge
def _check_unmerge_args(entity_type, source_id, merge_event_id, preview_token, idempotency_key,
                        confirmation, reason) -> str:
    _require_entity_type(entity_type)
    _require_id(source_id, "source_id")
    _require_id(merge_event_id, "merge_event_id")
    _require_id(preview_token, "preview_token (an unmerge without a preview is refused)")
    _require_id(idempotency_key, "idempotency_key")
    if confirmation is not True:
        raise MasterDataRefused("an unmerge requires explicit human confirmation of the preview")
    return _validate_reason(reason, required=True)


async def _check_unmerge_state(db, tenant_id, entity_type, source_id, merge_event_id,
                               preview_token, event_id):
    source = await _find_one(db, models_collection(entity_type),
                             {"id": source_id, "tenant_id": tenant_id})
    if source is None:
        raise MasterDataRefused("record %s is not a %s of this tenant" % (source_id, entity_type))
    merge_event = await _find_one(db, HISTORY_COLLECTION, {
        "id": merge_event_id, "tenant_id": tenant_id, "kind": KIND_MERGE})
    if merge_event is None or merge_event.get("source_id") != source_id \
            or merge_event.get("entity_type") != entity_type:
        raise MasterDataRefused("merge event %s did not merge %s %s in this tenant"
                                % (merge_event_id, entity_type, source_id))
    if source.get("last_unmerge_event_id") == event_id:
        return {"source": source, "merge_event": merge_event}   # our own interrupted retry
    preview = await _build_unmerge_preview(db, tenant_id, entity_type, source_id)
    if preview["blocking"]:
        raise MasterDataRefused("unmerge refused before any write: " + "; ".join(preview["blocking"]))
    if preview["reverses_event_id"] != merge_event_id:
        raise MasterDataStalePreview(
            "record %s is currently merged by event %s, not %s"
            % (source_id, preview["reverses_event_id"], merge_event_id))
    if preview["preview_token"] != preview_token:
        raise MasterDataStalePreview("the record changed since the unmerge preview (token mismatch)")
    return {"source": source, "merge_event": merge_event}


async def unmerge(
    ctx: Any,
    *,
    entity_type: str,
    source_id: str,
    merge_event_id: str,
    preview_token: str,
    idempotency_key: str,
    reason: str,
    confirmation: bool = False,
    approval_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    mode: Any = None,
    repository=None,
    approval_verifier: Any = None,
    _fail_after: Optional[str] = None,
) -> MergeOutcome:
    """Reverse one merge by APPENDING an unmerge event. The merge event stays.

    The source returns to the lifecycle it had before the merge (``active`` —
    only an active record can be merged) and ``merged_into`` is cleared.
    Records that were redirected into the source keep pointing at it and so
    follow it back. Same approval, preview-token, idempotency and recovery
    guarantees as ``merge``.
    """
    effective = resolve_mode(mode)
    if effective == MODE_OFF:
        return MergeOutcome(MODE_OFF, False, KIND_UNMERGE, reason="master data is off")

    if effective == MODE_SHADOW:
        try:
            validated = require_tenant_context(ctx)
            _reject_tenant_override(payload)
            _require_actor(validated)
            _check_unmerge_args(entity_type, source_id, merge_event_id, preview_token,
                                idempotency_key, confirmation, reason)
            if approval_verifier is None:
                await _verify_approval(validated, None, approval_id, _approval_subject(
                    ACTION_UNMERGE, validated.tenant_id, entity_type, source_id, None,
                    preview_token))
        except (MasterDataRefused, MasterDataInvalid, MasterDataTenantContextMissing) as exc:
            return MergeOutcome(MODE_SHADOW, False, KIND_UNMERGE, source_id=source_id,
                                reason=str(exc), would_perform=False)
        return MergeOutcome(MODE_SHADOW, False, KIND_UNMERGE, source_id=source_id,
                            reason="shadow: nothing written", would_perform=None)

    ctx = require_tenant_context(ctx)
    _reject_tenant_override(payload)
    actor_id = _require_actor(ctx)
    reason = _check_unmerge_args(entity_type, source_id, merge_event_id, preview_token,
                                 idempotency_key, confirmation, reason)
    repo = repository if repository is not None else _repository_for(ctx)
    db = await _handle(repo)
    tenant_id = ctx.tenant_id
    event_id = derived_event_id(tenant_id, KIND_UNMERGE, idempotency_key)
    from app.audit.idempotency import request_fingerprint
    # Read-only: which record the merge had redirected to, for the outcome and
    # the evidence. ``check`` verifies the event properly under the lock.
    named = await _find_one(db, HISTORY_COLLECTION, {"id": merge_event_id, "tenant_id": tenant_id,
                                                     "kind": KIND_MERGE, "source_id": source_id})
    former_target = (named or {}).get("target_id")

    async def check(handle):
        return await _check_unmerge_state(handle, tenant_id, entity_type, source_id,
                                          merge_event_id, preview_token, event_id)

    def restored_status(state):
        return (state["merge_event"].get("source_before") or {}).get("status") or models.STATUS_ACTIVE

    async def cas(handle, state, now, actor):
        result = await handle[models_collection(entity_type)].update_one(
            {"id": source_id, "tenant_id": tenant_id, "status": models.STATUS_MERGED,
             "merge_event_id": merge_event_id, "updated_at": state["source"].get("updated_at")},
            {"$set": {"status": restored_status(state), "merged_into": None,
                      "merge_event_id": None, "merge_preview_token": None,
                      "last_unmerge_event_id": event_id, "unmerged_at": now,
                      "unmerged_by": actor, "updated_at": now}})
        return getattr(result, "modified_count", 0) == 1

    async def history_doc(handle, state, now, actor, evidence):
        return {"_id": event_id, "id": event_id, "tenant_id": tenant_id,
                "entity_type": entity_type, "kind": KIND_UNMERGE, "source_id": source_id,
                "target_id": state["merge_event"].get("target_id"),
                "reverses_event_id": merge_event_id, "preview_token": preview_token,
                "restored_status": restored_status(state), "actor_id": actor,
                "approval": evidence.as_record(), "reason": reason,
                "idempotency_key": idempotency_key, "recorded_at": now}

    def audit_kwargs(state, evidence):
        former = state["merge_event"].get("target_id")
        return {"reason": reason, "before": former, "after": source_id,
                "correlation_id": merge_event_id,
                "diff": {"status": [models.STATUS_MERGED, restored_status(state)],
                         "merged_into": [former, None], "reverses_event_id": merge_event_id,
                         "unmerge_event_id": event_id}}

    plan = _Plan(
        kind=KIND_UNMERGE, action=ACTION_UNMERGE, entity_type=entity_type, source_id=source_id,
        target_id=former_target, key=idempotency_key, event_id=event_id,
        preview_token=preview_token,
        check=check, is_own=lambda state: state["source"].get("last_unmerge_event_id") == event_id,
        cas=cas, history_doc=history_doc, audit_kwargs=audit_kwargs)
    fingerprint = request_fingerprint({
        "entity_type": entity_type, "source_id": source_id, "merge_event_id": merge_event_id,
        "preview_token": preview_token, "approval_id": approval_id, "reason": reason})
    return await _run(ctx, db, plan, actor_id=actor_id, approval_id=approval_id,
                      verifier=approval_verifier,
                      subject=_approval_subject(ACTION_UNMERGE, tenant_id, entity_type, source_id,
                                                None, preview_token),
                      fingerprint=fingerprint, fail_after=_fail_after)
