"""
W0-03E — legacy inventory and the deterministic migration plan. Read-only.

Nothing in this module writes. ``plan`` reads the tenant's legacy identity
collections (scoped by the legacy ``org_id`` the **server-resolved** tenant maps
to), the tenant's existing Master records and its reverse-reference rows, and
answers with a plan: for every legacy document exactly one decision.

  ``create``   a new official Master record, anchored on this legacy document;
  ``attach``   this legacy id becomes one more ``legacy_ref`` of a Master record —
               the one another document of the same plan creates, or one that
               already exists — because an **authoritative** identity says they
               are the same: an equal typed identifier (ЕИК, VAT, ЕГН, SKU,
               serial, QR, inventory number) or a foreign key the legacy writer
               maintains (``employee_profiles.user_id``);
  ``pending``  a person must decide. An equal name without an authoritative
               identifier is a *candidate*, never a link — also on an exact match;
  ``blocked``  the document cannot be migrated as it is (no name, a dangling
               parent). It is preserved and reported, never dropped.

The same inputs give the same plan and the same ``plan_token`` on every run; the
token covers every source document's full content, so any change to the legacy
data, to an existing Master record or to a reverse-reference row since the dry
run makes execution refuse the plan as stale.

``org_id`` is compatibility evidence only. It never comes from a caller and it is
never the key of a canonical record: it selects which legacy rows belong to the
tenant the W0-01 resolver already chose, and it is written into ``legacy_refs``
so the old documents keep resolving. Legacy rows of another ``org_id`` in the
same database are neither read nor counted (their volume is that tenant's
data); rows without any ``org_id`` are counted as data quality and excluded —
never guessed.
"""
import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.master_data import legacy_sources as ls
from app.master_data import models
from app.master_data.deps import (
    MODE_OFF,
    MODE_SHADOW,
    MasterDataTenantContextMissing,
    require_tenant_context,
    resolve_mode,
)
from app.master_data.models import MasterDataInvalid, identifier_key
from app.master_data.normalize import normalize_name
from app.tenancy.data_access import count_ownerless

PLAN_VERSION = 1
#: The schema this migration writes. Recorded on every run, every Master record it
#: creates and every reverse-reference row, so a later schema is applied on purpose.
MIGRATION_SCHEMA_VERSION = 1

REFS_COLLECTION = "md_legacy_refs"

DECISION_CREATE = "create"
DECISION_ATTACH = "attach"
DECISION_PENDING = "pending"
DECISION_BLOCKED = "blocked"

REF_MAPPED = "mapped"
REF_PENDING = "pending"
REF_BLOCKED = "blocked"
REF_DECLINED = "declined"
REF_ROLLED_BACK = "rolled_back"
#: Reverse-reference states that still account for the legacy document.
LIVE_REF_STATUSES = frozenset({REF_MAPPED, REF_PENDING, REF_BLOCKED, REF_DECLINED})

#: A plan larger than this is split by domain (``sources=``), per contract
#: "по домейн, с dry-run и отчет преди всяко прилагане".
MAX_PLAN_ITEMS = 20000


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def ref_row_id(tenant_id: str, collection: str, legacy_id: str) -> str:
    """The reverse reference of one legacy document — deterministic, so every
    writer addresses the same row and Mongo's unique ``_id`` decides."""
    key = "\x1f".join((tenant_id, collection, legacy_id)).encode("utf-8")
    return "legacy-ref:" + hashlib.sha256(key).hexdigest()


def legacy_org_id(ctx: Any) -> str:
    """The legacy ``org_id`` of the resolved tenant — from the registry mapping
    carried by the context (``TenantContext.org_id``), never from a request."""
    org = getattr(ctx, "org_id", None)
    if not org or not isinstance(org, str):
        raise MasterDataTenantContextMissing(
            "the tenant context carries no legacy org mapping; refusing to read legacy data")
    return org


def select_sources(sources: Optional[Iterable[str]]) -> List[str]:
    if sources is None:
        return [s.collection for s in ls.SOURCES]
    chosen = list(dict.fromkeys(sources))
    if not chosen:
        raise MasterDataInvalid("at least one legacy source is required")
    for name in chosen:
        if name not in ls.SOURCE_BY_COLLECTION:
            raise MasterDataInvalid("%r is not an inventoried legacy identity source" % (name,))
    return sorted(chosen, key=ls.SOURCE_ORDER.get)


def _mask(kind: str, key: str) -> str:
    from app.master_data.uniqueness import mask_value
    return mask_value(kind, key)


def _fingerprint(doc: Dict[str, Any]) -> str:
    return digest({k: v for k, v in doc.items() if k != "_id"})


# ================================================================== loading
async def load_state(db, tenant_id: str, org_id: str, collections: List[str]) -> Dict[str, Any]:
    """Everything the plan is computed from, read once. Reads only."""
    docs: Dict[str, List[Dict[str, Any]]] = {}
    excluded: Dict[str, Dict[str, int]] = {}
    for name in collections:
        owned = await db[name].find({"org_id": org_id}, {"_id": 0}).to_list(None)
        docs[name] = sorted(owned, key=lambda d: str(d.get("id") or ""))
        # W0-03E/C03: no count of OTHER orgs' documents — in a shared legacy
        # database that would disclose another tenant's data volume. Only the
        # rows that belong to no tenant at all are reported, as data quality.
        unowned = await count_ownerless(db, name)
        excluded[name] = {"no_org_id": unowned}
    masters: Dict[str, List[Dict[str, Any]]] = {}
    for etype in sorted({ls.source(n).entity_type for n in collections}):
        masters[etype] = await db["md_" + etype].find(
            {"tenant_id": tenant_id}, {"_id": 0}).to_list(None)
    rows = await db[REFS_COLLECTION].find({"tenant_id": tenant_id}, {"_id": 0}).to_list(None)
    return {"docs": docs, "excluded": excluded, "masters": masters, "refs": rows}


# ================================================================== planning
class _Rec:
    __slots__ = ("collection", "legacy_id", "doc", "ex", "order", "fingerprint", "group")

    def __init__(self, collection, legacy_id, doc, ex, order):
        self.collection, self.legacy_id, self.doc, self.ex, self.order = (
            collection, legacy_id, doc, ex, order)
        self.fingerprint = _fingerprint(doc)
        self.group = None

    @property
    def key(self) -> Tuple[str, str]:
        return (self.collection, self.legacy_id)

    def id_keys(self) -> List[Tuple[str, str]]:
        return [(k, identifier_key(k, v)) for k, v in self.ex.identifiers]


class _Group:
    def __init__(self, recs: List[_Rec]):
        self.recs = sorted(recs, key=lambda r: r.order)
        self.decision: Optional[str] = None
        self.reason: Optional[str] = None
        self.existing: Optional[str] = None     # existing Master id attached to
        self.candidates: List[Dict[str, Any]] = []
        for r in self.recs:
            r.group = self

    @property
    def anchor(self) -> _Rec:
        return self.recs[0]

    @property
    def keys(self) -> set:
        return {k for r in self.recs for k in r.id_keys()}


def _depths(docs: List[Dict[str, Any]]) -> Dict[str, int]:
    parent = {d.get("id"): d.get("parent_id") for d in docs if d.get("id")}
    out: Dict[str, int] = {}
    for node in parent:
        depth, seen, cur = 0, set(), node
        while parent.get(cur) and cur not in seen and depth < 64:
            seen.add(cur)
            cur = parent[cur]
            depth += 1
        out[node] = depth
    return out


def _canonical_of(masters_by_id: Dict[str, Dict[str, Any]], entity_id: str) -> Optional[Dict[str, Any]]:
    seen, cur = set(), masters_by_id.get(entity_id)
    while cur is not None and cur.get("status") == models.STATUS_MERGED:
        if cur["id"] in seen:
            return None
        seen.add(cur["id"])
        cur = masters_by_id.get(cur.get("merged_into"))
    return cur


def build_plan(*, tenant_id: str, org_id: str, collections: List[str],
               state: Dict[str, Any]) -> Dict[str, Any]:
    """The deterministic plan. Pure: the same ``state`` always gives the same plan."""
    rows = {(r.get("collection"), r.get("legacy_id")): r for r in state["refs"]
            if r.get("status") in LIVE_REF_STATUSES}
    masters = state["masters"]
    masters_by_id = {etype: {m["id"]: m for m in docs if m.get("id")} for etype, docs in masters.items()}

    # --- integrity of what already exists: a legacy_ref of another org is foreign
    integrity: List[Dict[str, Any]] = []
    tainted = set()
    for etype in sorted(masters):
        for m in masters[etype]:
            for ref in m.get("legacy_refs") or []:
                if isinstance(ref, dict) and ref.get("org_id") not in (None, org_id):
                    integrity.append({"entity_type": etype, "entity_id": m.get("id"),
                                      "finding": "FOREIGN_LEGACY_REF",
                                      "collection": ref.get("collection"),
                                      "legacy_id": ref.get("legacy_id")})
                    tainted.add((etype, m.get("id")))

    # --- read every document once, in the plan's deterministic order
    recs: List[_Rec] = []
    by_key: Dict[Tuple[str, str], _Rec] = {}
    already: Dict[str, Dict[str, int]] = {}
    unaddressable: Dict[str, int] = {}
    for name in collections:
        docs = state["docs"].get(name, [])
        depth = _depths(docs) if name == "location_nodes" else {}
        for doc in docs:
            legacy_id = doc.get("id")
            if not isinstance(legacy_id, str) or not legacy_id.strip():
                unaddressable[name] = unaddressable.get(name, 0) + 1
                continue
            row = rows.get((name, legacy_id))
            if row is not None:
                bucket = already.setdefault(name, {})
                bucket[row["status"]] = bucket.get(row["status"], 0) + 1
                continue
            order = (ls.SOURCE_ORDER[name], depth.get(legacy_id, 0), legacy_id)
            rec = _Rec(name, legacy_id, doc, ls.extract(name, doc), order)
            recs.append(rec)
            by_key[rec.key] = rec
    recs.sort(key=lambda r: r.order)

    # --- 1. records whose decision is fixed by the source itself
    groups: List[_Group] = []
    fixed: List[_Rec] = []
    identity: List[_Rec] = []
    for r in recs:
        if r.ex.blocked_reason or r.ex.pending_reason or r.ex.same_as:
            fixed.append(r)
        else:
            identity.append(r)

    # --- 2. authoritative grouping: union by equal typed identifier, per type
    parent_of = {r.key: r.key for r in identity}

    def find(k):
        while parent_of[k] != k:
            parent_of[k] = parent_of[parent_of[k]]
            k = parent_of[k]
        return k

    owner: Dict[Tuple[str, str, str], Tuple[str, str]] = {}
    for r in identity:
        for kind, key in r.id_keys():
            slot = (r.ex.entity_type, kind, key)
            if slot in owner:
                a, b = find(owner[slot]), find(r.key)
                if a != b:
                    parent_of[max(a, b, key=lambda k: by_key[k].order)] = min(
                        a, b, key=lambda k: by_key[k].order)
            else:
                owner[slot] = r.key
    members: Dict[Tuple[str, str], List[_Rec]] = {}
    for r in identity:
        members.setdefault(find(r.key), []).append(r)
    for root in sorted(members, key=lambda k: by_key[k].order):
        groups.append(_Group(members[root]))

    # --- 3. consistency and existing Masters, for each authoritative group
    id_index: Dict[Tuple[str, str], set] = {}
    name_index: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for etype, docs in masters.items():
        for m in docs:
            if m.get("archived_by_run"):
                continue        # archived by a migration rollback: history, not identity
            for ident in m.get("identifiers") or []:
                if isinstance(ident, dict) and ident.get("key"):
                    id_index.setdefault((etype, ident["key"]), set()).add(m["id"])
            if m.get("status") == models.STATUS_ACTIVE:
                names = {m.get("normalized_name")} | {
                    a.get("normalized") for a in (m.get("aliases") or []) if isinstance(a, dict)}
                for n in names - {None, ""}:
                    name_index.setdefault((etype, n), []).append(m)
    for g in groups:
        etype = g.anchor.ex.entity_type
        by_kind: Dict[str, set] = {}
        for kind, key in g.keys:
            by_kind.setdefault(kind, set()).add(key)
        collections_seen = [r.collection for r in g.recs]
        if any(len(v) > 1 for v in by_kind.values()):
            g.decision, g.reason = DECISION_PENDING, ls.PENDING_IDENTIFIER_CONFLICT
        elif len(collections_seen) != len(set(collections_seen)):
            g.decision, g.reason = DECISION_PENDING, ls.PENDING_DUPLICATE_IN_SOURCE
        if g.decision:
            g.candidates = [{"legacy": [r.collection, r.legacy_id]} for r in g.recs]
            continue
        hits = set()
        for _kind, key in g.keys:
            for mid in id_index.get((etype, key), ()):
                canonical = _canonical_of(masters_by_id.get(etype, {}), mid)
                hits.add(canonical["id"] if canonical else "?broken:" + mid)
        if len(hits) > 1:
            g.decision, g.reason = DECISION_PENDING, ls.PENDING_IDENTIFIER_CONFLICT
            g.candidates = [{"entity_id": h} for h in sorted(hits)]
        elif hits:
            mid = next(iter(hits))
            target = masters_by_id.get(etype, {}).get(mid)
            their = {}
            for ident in (target or {}).get("identifiers") or []:
                their.setdefault(ident.get("kind"), set()).add(ident.get("key"))
            conflict = target is None or target.get("status") != models.STATUS_ACTIVE or any(
                kind in their and their[kind] != keys for kind, keys in by_kind.items()) \
                or (etype, mid) in tainted
            if conflict:
                g.decision, g.reason = DECISION_PENDING, ls.PENDING_EXISTING_CONFLICT
                g.candidates = [{"entity_id": mid}]
            else:
                g.decision, g.existing = DECISION_ATTACH, mid

    # --- 4. a name is not an identity: without an identifier it only suggests
    name_keys: Dict[Tuple, List[_Group]] = {}
    for g in groups:
        scope = g.anchor.ex.name_scope
        if g.decision is None and scope is not None:
            name_keys.setdefault((g.anchor.ex.entity_type, scope,
                                  normalize_name(g.anchor.ex.display_name)), []).append(g)
    for (etype, scope, norm), same in name_keys.items():
        # groups WITH an identifier are authoritative; they collide with nobody
        loose = [g for g in same if not g.keys]
        if not loose or not norm:
            continue
        existing = [m for m in name_index.get((etype, norm), [])
                    if (m.get("name_scope") or list(scope)) == list(scope)]
        if len(same) > 1 or existing:
            for g in loose:
                g.decision, g.reason = DECISION_PENDING, ls.PENDING_NAME_MATCH
                g.candidates = sorted(
                    [{"entity_id": m["id"]} for m in existing]
                    + [{"legacy": [o.anchor.collection, o.anchor.legacy_id]} for o in same
                       if o is not g], key=_canonical_json)
    for g in groups:
        if g.decision is None:
            g.decision = DECISION_CREATE

    # --- 5. records fixed by the source, and those tied to another by a key
    by_legacy_group = {r.key: r.group for r in identity}

    def mapped_row(collection, legacy_id):
        row = rows.get((collection, legacy_id))
        return row if row and row.get("status") == REF_MAPPED else None

    items: List[Dict[str, Any]] = []
    decided: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def emit(rec: _Rec, decision, reason=None, target=None, candidates=None, relations=None):
        item = {
            "collection": rec.collection, "legacy_id": rec.legacy_id,
            "entity_type": rec.ex.entity_type, "decision": decision, "reason_code": reason,
            "target": target, "display_name": rec.ex.display_name,
            "identifiers": [{"kind": k, "value": v} for k, v in rec.ex.identifiers],
            "roles": list(rec.ex.roles), "name_scope": list(rec.ex.name_scope)
            if rec.ex.name_scope is not None else None,
            "attributes": dict(rec.ex.attributes), "relations": relations or {},
            "candidates": candidates or [], "candidate_types": list(rec.ex.candidate_types),
            "fingerprint": rec.fingerprint,
        }
        decided[rec.key] = item
        return item

    # identity groups first (their order is the plan order), then dependent records
    pending_order = sorted(recs, key=lambda r: r.order)
    for rec in pending_order:
        g = rec.group
        if g is not None:
            if g.decision == DECISION_PENDING:
                emit(rec, DECISION_PENDING, g.reason, candidates=g.candidates)
            elif g.decision == DECISION_ATTACH:
                emit(rec, DECISION_ATTACH, None, target={"entity_id": g.existing})
            elif rec is g.anchor:
                emit(rec, DECISION_CREATE)
            else:
                emit(rec, DECISION_ATTACH, None,
                     target={"anchor": [g.anchor.collection, g.anchor.legacy_id]})
            continue
        ex = rec.ex
        if ex.blocked_reason:
            emit(rec, DECISION_BLOCKED, ex.blocked_reason)
        elif ex.pending_reason:
            cands = []
            if ex.pending_reason == ls.PENDING_PROJECT_SCOPED:
                norm = normalize_name(ex.display_name)
                cands = [{"entity_id": m["id"]} for m in name_index.get((ex.entity_type, norm), [])]
                cands += [{"legacy": [o.anchor.collection, o.anchor.legacy_id]} for o in groups
                          if o.anchor.ex.entity_type == ex.entity_type
                          and normalize_name(o.anchor.ex.display_name) == norm]
            emit(rec, DECISION_PENDING, ex.pending_reason, candidates=sorted(cands, key=_canonical_json))
        elif ex.same_as:
            other = by_legacy_group.get(ex.same_as)
            row = mapped_row(*ex.same_as)
            if other is not None and other.decision in (DECISION_CREATE, DECISION_ATTACH):
                target = {"entity_id": other.existing} if other.decision == DECISION_ATTACH and \
                    other.existing else {"anchor": [other.anchor.collection, other.anchor.legacy_id]}
                emit(rec, DECISION_ATTACH, None, target=target)
            elif row is not None:
                emit(rec, DECISION_ATTACH, None, target={"entity_id": row["entity_id"]})
            elif other is not None or (ex.same_as in {k for k in rows}):
                emit(rec, DECISION_PENDING, ls.PENDING_PARENT,
                     candidates=[{"legacy": list(ex.same_as)}])
            else:
                emit(rec, DECISION_BLOCKED, ls.BLOCKED_ORPHAN,
                     candidates=[{"legacy": list(ex.same_as)}])

    # --- 6. parents: a location under an unresolved parent is not placed anywhere
    for rec in sorted(recs, key=lambda r: r.order):
        item = decided[rec.key]
        if not rec.ex.parent:
            continue
        rel, pcoll, pid = rec.ex.parent
        parent_item = decided.get((pcoll, pid))
        row = mapped_row(pcoll, pid)
        if parent_item is not None and parent_item["decision"] == DECISION_CREATE:
            ref = {"anchor": [pcoll, pid]}
        elif parent_item is not None and parent_item["decision"] == DECISION_ATTACH:
            ref = dict(parent_item["target"])
        elif row is not None:
            ref = {"entity_id": row["entity_id"]}
        else:
            ref = None
        if item["decision"] not in (DECISION_CREATE, DECISION_ATTACH):
            continue
        if ref is not None:
            item["relations"][rel] = ref
        elif rec.collection == "location_nodes":
            known = parent_item is not None or (pcoll, pid) in rows
            item["decision"] = DECISION_PENDING if known else DECISION_BLOCKED
            item["reason_code"] = ls.PENDING_PARENT if known else ls.BLOCKED_ORPHAN
            item["target"] = None
            item["candidates"] = [{"legacy": [pcoll, pid]}]
        else:
            # a physical asset keeps its identity; its type waits for a person
            item["attributes"]["asset_type_unresolved"] = [pcoll, pid]

    items = [decided[r.key] for r in sorted(recs, key=lambda r: r.order)]
    if len(items) > MAX_PLAN_ITEMS:
        raise MasterDataInvalid(
            "the plan has %d records; split it by domain (sources=) — at most %d per run"
            % (len(items), MAX_PLAN_ITEMS))
    summary: Dict[str, Dict[str, int]] = {}
    for item in items:
        bucket = summary.setdefault(item["collection"], {})
        bucket[item["decision"]] = bucket.get(item["decision"], 0) + 1
    inventory = {name: {"in_scope": len(state["docs"].get(name, [])),
                        **state["excluded"].get(name, {}),
                        "unaddressable": unaddressable.get(name, 0),
                        "already": already.get(name, {}),
                        "planned": summary.get(name, {})} for name in collections}
    basis = {"plan_version": PLAN_VERSION, "schema_version": MIGRATION_SCHEMA_VERSION,
             "tenant_id": tenant_id, "org_id": org_id, "sources": collections, "items": items,
             "masters": {t: [digest(m) for m in sorted(docs, key=lambda d: str(d.get("id")))]
                         for t, docs in sorted(masters.items())},
             "refs": sorted(digest(r) for r in state["refs"]),
             "inventory": inventory}
    return {
        "plan_version": PLAN_VERSION, "schema_version": MIGRATION_SCHEMA_VERSION,
        "tenant_id": tenant_id, "org_id": org_id, "sources": collections,
        "inventory": inventory, "integrity_findings": integrity,
        "items": items,
        "totals": {d: sum(1 for i in items if i["decision"] == d)
                   for d in (DECISION_CREATE, DECISION_ATTACH, DECISION_PENDING, DECISION_BLOCKED)},
        "auto_merges": 0,
        "plan_token": digest(basis),
    }


def public_view(plan: Dict[str, Any]) -> Dict[str, Any]:
    """The plan as a person sees it: personal identifiers masked, fingerprints kept."""
    out = dict(plan)
    out["items"] = [dict(i, identifiers=[{"kind": x["kind"], "value": _mask(
        x["kind"], identifier_key(x["kind"], x["value"]))} for x in i["identifiers"]])
        for i in plan["items"]]
    return out


async def compute(db, tenant_id: str, org_id: str, collections: List[str]) -> Dict[str, Any]:
    state = await load_state(db, tenant_id, org_id, collections)
    return build_plan(tenant_id=tenant_id, org_id=org_id, collections=collections, state=state)


def _repository_for(ctx):
    from app.master_data.repository import MasterDataRepository
    return MasterDataRepository(ctx.tenant_id)


async def plan(ctx: Any, *, sources: Optional[Iterable[str]] = None, mode: Any = None,
               repository=None, masked: bool = True) -> Optional[Dict[str, Any]]:
    """The dry run. Never writes — in any mode.

    ``off`` and ``shadow`` answer ``None`` without a read: before ``enforce`` the
    canonical store is not consulted (same rule as ``get_entity``/``preview_merge``).
    """
    effective = resolve_mode(mode)
    if effective in (MODE_OFF, MODE_SHADOW):
        return None
    ctx = require_tenant_context(ctx)
    org_id = legacy_org_id(ctx)
    collections = select_sources(sources)
    repo = repository if repository is not None else _repository_for(ctx)
    result = await compute(await repo.db(), ctx.tenant_id, org_id, collections)
    return public_view(result) if masked else result
