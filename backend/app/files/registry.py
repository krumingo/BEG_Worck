"""
W0-06A — the File Registry service: the ONE write path for file identity.

Every rule FLOW-016 states about files is enforced here, in one place, rather
than at each of the fifteen call sites the inventory found:

* a file is registered ONCE and gets a stable ``file_id``; a provider path is
  never its identity and nothing in this module resolves a file by one;
* a new version never overwrites an old one — the old row stays and becomes
  read-only, and exactly one version of a family carries ``is_current``;
* an approved or signed version is never replaced in place, only followed;
* a file reaches many business records through many relation rows and stays one
  registry record with one physical original;
* unlinking removes ONE relation and nothing else — not the file, not the
  provider object, not the other relations;
* an externally mutated provider object is an INTEGRITY PROBLEM, never an
  automatic new version;
* a missing original is reported as missing even when a preview is cached;
* removing a record from the registry is not a claim that the customer's
  original was destroyed: a physical delete is a separate request with a
  recorded provider answer.

Tenancy. The service is constructed from a :class:`~app.tenancy.data_access.TenantData`,
which the caller built from server-side state only. Every read and every write
goes through that view, so a registry record, a relation and a provider location
of another tenant are not merely hidden — they are unreachable, including when
ids collide across tenants in one shared legacy database (W0-03E-A2C).

Audit and idempotency. Every consequential write records a canonical FLOW-040
AuditEvent and accepts an idempotency key; a replay of the same key with the
same payload returns the first result without performing the write again
(CLAUDE.md §14). The two are deliberately ordered: the idempotency key is
reserved BEFORE the write and completed after the AuditEvent, so a retry that
arrives between the two finds a reservation rather than a half-done action.

What is NOT here, by assignment. No HTTP route, no live provider, no
credential, no customer file movement and no Approval runtime: W0-06A is the
foundation and the inventory. FLOW-002 permission checks belong at the route
layer that a later slice adds; this service assumes its caller has already
authorized the action and never widens access by itself.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.audit.envelope import (
    ACTOR_HUMAN,
    RESULT_FAILURE,
    RESULT_SUCCESS,
    RETENTION_R1_CRITICAL_BUSINESS,
    RETENTION_R2_PROJECT_OPERATIONAL,
    RETENTION_R5_TECHNICAL_DIAGNOSTIC,
    build_event,
)
from app.audit.idempotency import (
    IDEMPOTENCY_DUPLICATE,
    begin_idempotent,
    complete_idempotent,
    fail_idempotent,
    request_fingerprint,
)
from app.audit.store import record_event
from app.files import models as m
from app.files.providers.base import (
    IntegrityVerdict,
    ProviderObjectRef,
    StorageProviderAdapter,
)

# --------------------------------------------------------------- audit actions
ACTION_REGISTER = "file.registered"
ACTION_VERSION_ADDED = "file.version.added"
ACTION_VERSION_SEALED = "file.version.sealed"
ACTION_RELATION_ADDED = "file.relation.added"
ACTION_RELATION_REMOVED = "file.relation.removed"
ACTION_LOCATION_SET = "file.provider_location.set"
ACTION_INTEGRITY_CHECKED = "file.integrity.checked"
ACTION_DERIVED_CACHED = "file.derived.cached"
ACTION_DELETE_REQUESTED = "file.physical_delete.requested"
ACTION_DELETE_RESULT = "file.physical_delete.result"

#: Retention class per action (FLOW-040 §6). Registration, versioning and the
#: delete trail are evidential (R1); relations and integrity results follow the
#: project's operational history (R2); a cache entry is diagnostic (R5).
_RETENTION = {
    ACTION_REGISTER: RETENTION_R1_CRITICAL_BUSINESS,
    ACTION_VERSION_ADDED: RETENTION_R1_CRITICAL_BUSINESS,
    ACTION_VERSION_SEALED: RETENTION_R1_CRITICAL_BUSINESS,
    ACTION_RELATION_ADDED: RETENTION_R2_PROJECT_OPERATIONAL,
    ACTION_RELATION_REMOVED: RETENTION_R2_PROJECT_OPERATIONAL,
    ACTION_LOCATION_SET: RETENTION_R1_CRITICAL_BUSINESS,
    ACTION_INTEGRITY_CHECKED: RETENTION_R2_PROJECT_OPERATIONAL,
    ACTION_DERIVED_CACHED: RETENTION_R5_TECHNICAL_DIAGNOSTIC,
    ACTION_DELETE_REQUESTED: RETENTION_R1_CRITICAL_BUSINESS,
    ACTION_DELETE_RESULT: RETENTION_R1_CRITICAL_BUSINESS,
}

#: What to do when a file with the same checksum is already registered. The
#: behaviour is a CALLER decision and is recorded in the audit event; there is
#: no implicit answer, because "the system silently made a second copy" and
#: "the system silently refused to store my file" are both wrong by default.
ON_DUPLICATE_REPORT = "report"        # default: do not write, name the existing file
ON_DUPLICATE_NEW_FILE = "new_file"    # register anyway, linked to the original
ON_DUPLICATE_CHOICES = frozenset({ON_DUPLICATE_REPORT, ON_DUPLICATE_NEW_FILE})

STATUS_REGISTERED = "registered"
STATUS_DUPLICATE = "duplicate"
STATUS_REPLAYED = "replayed"


class FileRegistryError(RuntimeError):
    """A FLOW-016 rule was violated by a caller. Fail closed, never guess."""


class FileNotFound(FileRegistryError):
    """No such file IN THIS TENANT. A foreign file is indistinguishable from an absent one."""


class RelationTargetNotFound(FileRegistryError):
    """The business record a relation points at does not exist in this tenant."""


class VersionSealed(FileRegistryError):
    """An approved/signed version cannot be replaced in place — add a new version."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FileRegistry:
    """One tenant's view of the File Registry.

    Build it from a :class:`~app.tenancy.data_access.TenantData` the caller
    already resolved server-side. The service never takes an ``org_id``
    argument: the only tenant it can act for is the one inside that view.
    """

    def __init__(self, tenant):
        if tenant is None:
            raise FileRegistryError("the File Registry needs a resolved tenant")
        self._tenant = tenant
        self.org_id = tenant.org_id

    # ------------------------------------------------------------ handles
    @property
    def files(self):
        return self._tenant.collection(m.FILES_COLLECTION)

    @property
    def versions(self):
        return self._tenant.collection(m.VERSIONS_COLLECTION)

    @property
    def relations(self):
        return self._tenant.collection(m.RELATIONS_COLLECTION)

    @property
    def locations(self):
        return self._tenant.collection(m.LOCATIONS_COLLECTION)

    @property
    def derived(self):
        return self._tenant.collection(m.DERIVED_COLLECTION)

    @property
    def delete_requests(self):
        return self._tenant.collection(m.DELETE_REQUESTS_COLLECTION)

    @property
    def sequences(self):
        return self._tenant.collection(m.SEQUENCES_COLLECTION)

    async def _next_registration_seq(self) -> int:
        """The tenant's next file registration number — atomic, never reused.

        ``$inc`` on one document is atomic on the server, so concurrent
        registrations get distinct numbers. The counter document's ``_id`` is
        deterministic per tenant: two first-ever upserts racing each other
        cannot create two counters (the loser hits the built-in ``_id`` index
        and simply retries onto the winner's document).
        """
        counter_id = "file_registration:%d:%s" % (len(self.org_id), self.org_id)
        for _ in range(8):
            try:
                doc = await self.sequences.find_one_and_update(
                    {"_id": counter_id, "counter": "file_registration"},
                    {"$inc": {"value": 1}}, upsert=True, return_document=True,
                    projection={"_id": 0, "value": 1})
            except Exception as exc:                                # noqa: BLE001
                if type(exc).__name__ == "DuplicateKeyError" or getattr(exc, "code", None) == 11000:
                    continue
                raise
            return int(doc["value"])
        raise FileRegistryError("could not allocate a registration number")

    # -------------------------------------------------------------- audit
    async def _audit(self, *, action: str, actor_id: str, entity_id: str,
                     entity_type: str = "file", result: str = RESULT_SUCCESS,
                     reason: Optional[str] = None,
                     structured_diff: Optional[Dict[str, Any]] = None,
                     entity_version: Optional[str] = None,
                     related_file_ids: Optional[List[str]] = None,
                     idempotency_key: Optional[str] = None,
                     actor_type: str = ACTOR_HUMAN,
                     correlation_id: Optional[str] = None) -> Dict[str, Any]:
        """Append one canonical FLOW-040 event for a registry action.

        ``tenant_id`` is this view's tenant, and the event is written to the
        same database the record went into, so the tenant's hash chain and its
        records never live apart.
        """
        event = build_event(
            tenant_id=self.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            source_flow=m.SOURCE_FLOW,
            retention_class=_RETENTION[action],
            result=result,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_version=entity_version,
            reason=reason,
            structured_diff=structured_diff,
            related_file_ids=related_file_ids or ([entity_id] if entity_type == "file" else []),
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
        )
        return await record_event(self._tenant.audit_store_db(), event)

    # -------------------------------------------------------- idempotency
    async def _begin(self, action: str, key: Optional[str], payload: Any
                     ) -> Tuple[bool, Optional[str]]:
        """``(is_replay, prior_result_reference)``.

        No key means the caller accepted that a retry may act twice; the
        registry does not invent one, because a generated key would make every
        retry look new and give a false sense of protection.
        """
        if not key:
            return False, None
        state = await begin_idempotent(
            self._tenant.audit_store_db(), tenant_id=self.org_id, key=key, action=action,
            request_fingerprint=request_fingerprint(payload))
        if state["status"] == IDEMPOTENCY_DUPLICATE:
            return True, state.get("result_reference")
        return False, None

    async def _complete(self, action: str, key: Optional[str], reference: str) -> None:
        if key:
            await complete_idempotent(self._tenant.audit_store_db(), tenant_id=self.org_id,
                                      key=key, action=action, result_reference=reference)

    async def _fail(self, action: str, key: Optional[str], error_code: str) -> None:
        if key:
            await fail_idempotent(self._tenant.audit_store_db(), tenant_id=self.org_id,
                                  key=key, action=action, error_code=error_code)

    # =================================================================== read
    async def get_file(self, file_id: str) -> Optional[Dict[str, Any]]:
        """This tenant's file, or ``None``. Another tenant's file is ``None`` too."""
        return await self.files.find_one({"id": file_id}, {"_id": 0})

    async def require_file(self, file_id: str) -> Dict[str, Any]:
        doc = await self.get_file(file_id)
        if not doc:
            raise FileNotFound("no file %r in this tenant" % file_id)
        return doc

    async def list_versions(self, file_id: str) -> List[Dict[str, Any]]:
        """Every version of the family, oldest first. Old versions remain visible."""
        rows = await self.versions.find({"file_id": file_id}, {"_id": 0}).to_list(None)
        return sorted(rows, key=lambda r: r.get("version_no", 0))

    async def current_version(self, file_id: str) -> Optional[Dict[str, Any]]:
        return await self.versions.find_one({"file_id": file_id, "is_current": True}, {"_id": 0})

    async def list_relations(self, file_id: str, *, include_removed: bool = False
                             ) -> List[Dict[str, Any]]:
        flt: Dict[str, Any] = {"file_id": file_id}
        if not include_removed:
            flt["active"] = True
        rows = await self.relations.find(flt, {"_id": 0}).to_list(None)
        return sorted(rows, key=m.sort_key)

    async def files_for_record(self, relation_type: str, record_id: str) -> List[Dict[str, Any]]:
        """Every file of this tenant attached to one business record.

        The screen that shows a project's photos, an act's attachments or a
        defect's evidence reads this. It returns FILES, not copies: two screens
        showing the same file show the same ``file_id``.
        """
        rows = await self.relations.find(
            {"relation_type": relation_type, "record_id": record_id, "active": True},
            {"_id": 0}).to_list(None)
        file_ids = sorted({r["file_id"] for r in rows})
        if not file_ids:
            return []
        docs = await self.files.find({"id": {"$in": file_ids}}, {"_id": 0}).to_list(None)
        return sorted(docs, key=m.file_order_key)

    async def current_location(self, file_id: str, version_no: int,
                               role: str = m.LOCATION_ROLE_PRIMARY) -> Optional[Dict[str, Any]]:
        """The location in force now — never a superseded one.

        A provider migration keeps the previous row as history, so a bare
        ``find_one`` by ``(file_id, version_no, role)`` returns whichever of
        them the database reaches first: after a migration that is as likely to
        be the OLD provider as the new one. The superseded rows are excluded
        and the remainder is ordered totally, so this answers the same way on
        every run.
        """
        rows = await self.locations.find(
            {"file_id": file_id, "version_no": version_no, "role": role},
            {"_id": 0}).to_list(None)
        live = [r for r in rows if r.get("superseded_at") is None]
        return sorted(live, key=m.sort_key)[-1] if live else None

    async def primary_location(self, file_id: str, version_no: int) -> Optional[Dict[str, Any]]:
        """The current PRIMARY location of one version."""
        return await self.current_location(file_id, version_no, m.LOCATION_ROLE_PRIMARY)

    async def find_by_checksum(self, checksum_value: Mapping[str, Any]
                               ) -> List[Dict[str, Any]]:
        """Files of this tenant whose CURRENT version has this checksum.

        Ordered by :func:`app.files.models.file_order_key` — the atomic
        registration sequence first — so the duplicate decision names the FIRST
        registered file on every run and every server, even when two files
        share a timestamp.
        """
        key = m.checksum_key(checksum_value)
        if not key:
            return []
        rows = await self.versions.find(
            {"checksum_key": key, "is_current": True}, {"_id": 0}).to_list(None)
        file_ids = sorted({r["file_id"] for r in rows})
        if not file_ids:
            return []
        docs = await self.files.find({"id": {"$in": file_ids}}, {"_id": 0}).to_list(None)
        return sorted(docs, key=m.file_order_key)

    async def canonical_original(self, file_id: str) -> Dict[str, Any]:
        """Can the canonical original be served, and from where?

        FLOW-016 §"Снимки и технически производни": a cached thumbnail, preview
        or OCR text may NEVER answer for a missing original. This returns the
        availability truthfully and lists the cached derivatives separately, so
        a caller that wants to show a stale preview must do so knowingly and can
        never mistake it for the original.
        """
        await self.require_file(file_id)
        version = await self.current_version(file_id)
        if not version:
            return {"file_id": file_id, "available": False, "reason": "no version registered",
                    "availability": m.AVAILABILITY_UNVERIFIED, "location": None,
                    "derived": [], "original_servable": False}
        location = await self.primary_location(file_id, version["version_no"])
        availability = (location or {}).get("availability", m.AVAILABILITY_UNVERIFIED)
        derived = await self.derived.find({"file_id": file_id}, {"_id": 0}).to_list(None)
        usable = m.is_usable(location)
        return {
            "file_id": file_id,
            "version_no": version["version_no"],
            "available": usable,
            "availability": availability,
            "reason": None if usable else "canonical original is %s" % availability,
            "location": location,
            # Present for diagnostics and preview, and explicitly NOT a stand-in:
            # the caller sees ``available=False`` whatever the cache holds.
            "derived": sorted(derived, key=m.sort_key),
            # Named for what it answers. ``is_canonical_original`` is reserved
            # for the stored flag on a DerivedArtifact, which is always False;
            # reusing the name for a computed answer would let a reader — and
            # the static guard — mistake one for the other.
            "original_servable": usable,
        }

    # ================================================================ register
    async def register_file(
        self, *,
        actor_id: str,
        display_name: str,
        original_name: str,
        category: str,
        checksum_value: Mapping[str, Any],
        size_bytes: int,
        mime_type: str,
        sensitivity: str = m.SENSITIVITY_STANDARD,
        relations: Sequence[Mapping[str, Any]] = (),
        provider_location: Optional[Mapping[str, Any]] = None,
        on_duplicate: str = ON_DUPLICATE_REPORT,
        idempotency_key: Optional[str] = None,
        legacy_reference: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Register one physical file and give it its stable business identity.

        Returns ``{"status": ..., "file_id": ..., "version_no": ...}``.
        ``status`` is ``registered``, ``duplicate`` (nothing was written; the
        existing ``file_id`` is named) or ``replayed`` (this idempotency key
        already did the work).
        """
        if on_duplicate not in ON_DUPLICATE_CHOICES:
            raise FileRegistryError("unknown on_duplicate %r" % on_duplicate)
        payload = {
            "display_name": display_name, "original_name": original_name,
            "category": category, "checksum": m.checksum_key(checksum_value),
            "size_bytes": size_bytes, "mime_type": mime_type, "sensitivity": sensitivity,
            "relations": [dict(r) for r in relations], "on_duplicate": on_duplicate,
            "legacy_reference": legacy_reference,
        }
        replay, prior = await self._begin(ACTION_REGISTER, idempotency_key, payload)
        if replay:
            return {"status": STATUS_REPLAYED, "file_id": prior, "version_no": None}

        try:
            existing = await self.find_by_checksum(checksum_value)
            if existing and on_duplicate == ON_DUPLICATE_REPORT:
                # Deterministic: the first REGISTERED matching file
                # (registration_seq), never "the smaller random id".
                duplicate_of = existing[0]["id"]
                await self._audit(
                    action=ACTION_REGISTER, actor_id=actor_id, entity_id=duplicate_of,
                    result=RESULT_SUCCESS, reason="duplicate checksum; no second record created",
                    idempotency_key=idempotency_key,
                    structured_diff={"duplicate_of": duplicate_of,
                                     "candidates": [d["id"] for d in existing],
                                     "checksum": m.checksum_key(checksum_value)})
                await self._complete(ACTION_REGISTER, idempotency_key, duplicate_of)
                return {"status": STATUS_DUPLICATE, "file_id": duplicate_of,
                        "version_no": None, "duplicate_of": duplicate_of,
                        "candidates": [d["id"] for d in existing]}

            # Every relation target is verified IN THIS TENANT, always. There is
            # no caller switch to skip it (W0-06A review finding 2): a flag a
            # caller can set is a flag a caller can set wrongly, and the link it
            # would let through is exactly the cross-tenant or dangling
            # relation the boundary exists to refuse.
            for relation in relations:
                await self._assert_relation_target(relation["relation_type"],
                                                   relation["record_id"])

            file_doc = m.build_file(
                org_id=self.org_id, display_name=display_name, original_name=original_name,
                category=category, sensitivity=sensitivity, uploaded_by=actor_id,
                registration_seq=await self._next_registration_seq())
            if legacy_reference:
                # Provenance of a migrated row: where it CAME from. Deliberately
                # not an identity — nothing resolves a file by this value.
                file_doc["legacy_reference"] = legacy_reference
            await self.files.insert_one(dict(file_doc))
            file_id = file_doc["id"]

            version = m.build_version(
                org_id=self.org_id, file_id=file_id, version_no=1,
                checksum_value=checksum_value, size_bytes=size_bytes, mime_type=mime_type,
                original_name=original_name, created_by=actor_id)
            await self.versions.insert_one(dict(version))
            await self.files.update_one({"id": file_id},
                                        {"$set": {"current_version_no": 1, "version_count": 1,
                                                  "updated_at": _now_iso()}})

            if provider_location:
                await self._write_location(file_id, 1, provider_location, checksum_value)

            created_relations = []
            for relation in relations:
                row = m.build_relation(
                    org_id=self.org_id, file_id=file_id,
                    relation_type=relation["relation_type"], record_id=relation["record_id"],
                    created_by=actor_id, role=relation.get("role"))
                await self.relations.insert_one(dict(row))
                created_relations.append(row["id"])

            await self._audit(
                action=ACTION_REGISTER, actor_id=actor_id, entity_id=file_id,
                entity_version="1", idempotency_key=idempotency_key,
                reason="file registered",
                structured_diff={"category": category, "sensitivity": sensitivity,
                                 "checksum": m.checksum_key(checksum_value),
                                 "size_bytes": size_bytes, "mime_type": mime_type,
                                 "relations": created_relations,
                                 "duplicate_of": existing[0]["id"] if existing else None,
                                 "legacy_reference": legacy_reference})
            await self._complete(ACTION_REGISTER, idempotency_key, file_id)
            return {"status": STATUS_REGISTERED, "file_id": file_id, "version_no": 1,
                    "relation_ids": created_relations,
                    "duplicate_of": existing[0]["id"] if existing else None}
        except Exception as exc:                                    # noqa: BLE001
            await self._fail(ACTION_REGISTER, idempotency_key, type(exc).__name__)
            raise

    # ================================================================= version
    async def add_version(
        self, *,
        actor_id: str,
        file_id: str,
        checksum_value: Mapping[str, Any],
        size_bytes: int,
        mime_type: str,
        original_name: str,
        reason: str,
        provider_location: Optional[Mapping[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add the next version of a family. The previous one is kept, read-only.

        The old row is not rewritten — only the two fields that record that a
        successor arrived (``is_current`` and ``superseded_by_version_no``) are
        set, which :func:`app.files.models.assert_version_update_allowed`
        enforces. The sealed states (approved/signed) are a different rule:
        they prevent a REPLACEMENT, not a successor, so a signed version can be
        followed by a new version but can never be edited.
        """
        payload = {"file_id": file_id, "checksum": m.checksum_key(checksum_value),
                   "size_bytes": size_bytes, "mime_type": mime_type, "reason": reason}
        replay, prior = await self._begin(ACTION_VERSION_ADDED, idempotency_key, payload)
        if replay:
            return {"status": STATUS_REPLAYED, "file_id": file_id, "version_no": None,
                    "version_id": prior}
        try:
            file_doc = await self.require_file(file_id)
            previous = await self.current_version(file_id)
            if previous is None:
                raise FileRegistryError("file %r has no current version to follow" % file_id)
            next_no = int(previous["version_no"]) + 1

            new_version = m.build_version(
                org_id=self.org_id, file_id=file_id, version_no=next_no,
                checksum_value=checksum_value, size_bytes=size_bytes, mime_type=mime_type,
                original_name=original_name, created_by=actor_id, reason=reason,
                supersedes_version_no=previous["version_no"])
            await self.versions.insert_one(dict(new_version))

            # Close the previous version. Only the two successor fields move;
            # anything else would be rewriting history.
            closing = {"$set": {"is_current": False,
                                "superseded_by_version_no": next_no,
                                "superseded_at": _now_iso()}}
            m.assert_version_update_allowed(closing["$set"])
            await self.versions.update_one(
                {"id": previous["id"], "file_id": file_id}, closing)

            await self.files.update_one(
                {"id": file_id},
                {"$set": {"current_version_no": next_no,
                          "version_count": int(file_doc.get("version_count", 0)) + 1,
                          "updated_at": _now_iso()}})

            if provider_location:
                await self._write_location(file_id, next_no, provider_location, checksum_value)

            await self._audit(
                action=ACTION_VERSION_ADDED, actor_id=actor_id, entity_id=file_id,
                entity_version=str(next_no), reason=reason, idempotency_key=idempotency_key,
                structured_diff={"from_version": previous["version_no"], "to_version": next_no,
                                 "checksum": m.checksum_key(checksum_value),
                                 "previous_checksum": previous.get("checksum_key"),
                                 "previous_approval_state": previous.get("approval_state")})
            await self._complete(ACTION_VERSION_ADDED, idempotency_key, new_version["id"])
            return {"status": STATUS_REGISTERED, "file_id": file_id, "version_no": next_no,
                    "version_id": new_version["id"],
                    "previous_version_no": previous["version_no"]}
        except Exception as exc:                                    # noqa: BLE001
            await self._fail(ACTION_VERSION_ADDED, idempotency_key, type(exc).__name__)
            raise

    async def seal_version(self, *, actor_id: str, file_id: str, version_no: int,
                           approval_state: str, reason: str,
                           idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """Mark a version approved or signed, making it evidential.

        From then on the registry refuses any change to it. Sealing is itself a
        one-way step: a sealed version cannot be un-sealed or re-sealed into
        another state, because that would quietly rewrite what a reviewer
        already relied on.
        """
        if approval_state not in m.SEALED_APPROVAL_STATES:
            raise FileRegistryError("seal_version takes %s" % sorted(m.SEALED_APPROVAL_STATES))
        replay, prior = await self._begin(
            ACTION_VERSION_SEALED, idempotency_key,
            {"file_id": file_id, "version_no": version_no, "state": approval_state})
        if replay:
            return {"status": STATUS_REPLAYED, "version_id": prior}
        try:
            row = await self.versions.find_one({"file_id": file_id, "version_no": version_no},
                                               {"_id": 0})
            if not row:
                raise FileNotFound("no version %s of %r in this tenant" % (version_no, file_id))
            if row.get("approval_state") in m.SEALED_APPROVAL_STATES:
                raise VersionSealed("version %s of %r is already %s"
                                    % (version_no, file_id, row["approval_state"]))
            update = {"approval_state": approval_state}
            m.assert_version_update_allowed(update)
            await self.versions.update_one({"id": row["id"], "file_id": file_id},
                                           {"$set": update})
            await self._audit(action=ACTION_VERSION_SEALED, actor_id=actor_id, entity_id=file_id,
                              entity_version=str(version_no), reason=reason,
                              idempotency_key=idempotency_key,
                              structured_diff={"approval_state": approval_state})
            await self._complete(ACTION_VERSION_SEALED, idempotency_key, row["id"])
            return {"status": STATUS_REGISTERED, "version_id": row["id"],
                    "approval_state": approval_state}
        except Exception as exc:                                    # noqa: BLE001
            await self._fail(ACTION_VERSION_SEALED, idempotency_key, type(exc).__name__)
            raise

    # =============================================================== relations
    async def _assert_relation_target(self, relation_type: str, record_id: str) -> None:
        """The business record must exist IN THIS TENANT.

        This is what makes a relation tenant-safe in both directions: the file
        is reached through this tenant's view, and so is the record it is being
        attached to. A record id that belongs to another tenant — including one
        that collides with a real id here — resolves to nothing and the link is
        refused rather than created across the boundary.
        """
        if relation_type not in m.RELATION_TYPES:
            raise FileRegistryError("unknown relation type %r" % relation_type)
        target = m.RELATION_TARGETS[relation_type]
        found = await self._tenant.collection(target).find_one({"id": record_id}, {"_id": 0, "id": 1})
        if not found:
            raise RelationTargetNotFound(
                "no %s %r in this tenant" % (relation_type, record_id))

    async def add_relation(self, *, actor_id: str, file_id: str, relation_type: str,
                           record_id: str, role: Optional[str] = None,
                           idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """Attach an existing file to one more business record.

        No byte is copied and no second registry record is created: the same
        ``file_id`` simply appears on one more screen, which is the whole point
        of FLOW-016 §"Един файл, много връзки".
        """
        replay, prior = await self._begin(
            ACTION_RELATION_ADDED, idempotency_key,
            {"file_id": file_id, "relation_type": relation_type, "record_id": record_id})
        if replay:
            return {"status": STATUS_REPLAYED, "relation_id": prior}
        try:
            await self.require_file(file_id)
            # Unconditional — see register_file. A missing or foreign target is
            # refused before anything is written.
            await self._assert_relation_target(relation_type, record_id)
            existing = await self.relations.find_one(
                {"file_id": file_id, "relation_type": relation_type,
                 "record_id": record_id, "active": True}, {"_id": 0})
            if existing:
                # Already linked: report the existing relation rather than
                # writing a second row that would make an unlink ambiguous.
                await self._complete(ACTION_RELATION_ADDED, idempotency_key, existing["id"])
                return {"status": STATUS_DUPLICATE, "relation_id": existing["id"]}

            row = m.build_relation(org_id=self.org_id, file_id=file_id,
                                   relation_type=relation_type, record_id=record_id,
                                   created_by=actor_id, role=role)
            await self.relations.insert_one(dict(row))
            await self._audit(action=ACTION_RELATION_ADDED, actor_id=actor_id, entity_id=file_id,
                              reason="file linked to %s %s" % (relation_type, record_id),
                              idempotency_key=idempotency_key,
                              structured_diff={"relation_id": row["id"],
                                               "relation_type": relation_type,
                                               "record_id": record_id, "role": role})
            await self._complete(ACTION_RELATION_ADDED, idempotency_key, row["id"])
            return {"status": STATUS_REGISTERED, "relation_id": row["id"]}
        except Exception as exc:                                    # noqa: BLE001
            await self._fail(ACTION_RELATION_ADDED, idempotency_key, type(exc).__name__)
            raise

    async def remove_relation(self, *, actor_id: str, file_id: str, relation_type: str,
                              record_id: str, reason: str,
                              idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """Unlink ONE relation. Nothing else changes.

        FLOW-016 §"Премахване на връзка и изтриване": removing a file from one
        screen removes the relation only. The file stays registered, its other
        relations stay, and the customer's original is NOT touched — this method
        has no provider call in it at all. The relation row is kept and marked
        removed rather than deleted, so the history of what the file was once
        attached to survives (CLAUDE.md §2 rule 9).
        """
        replay, prior = await self._begin(
            ACTION_RELATION_REMOVED, idempotency_key,
            {"file_id": file_id, "relation_type": relation_type, "record_id": record_id})
        if replay:
            return {"status": STATUS_REPLAYED, "relation_id": prior}
        try:
            row = await self.relations.find_one(
                {"file_id": file_id, "relation_type": relation_type,
                 "record_id": record_id, "active": True}, {"_id": 0})
            if not row:
                raise FileNotFound("no active %s relation from %r to %r in this tenant"
                                   % (relation_type, file_id, record_id))
            await self.relations.update_one(
                {"id": row["id"], "file_id": file_id},
                {"$set": {"active": False, "removed_by": actor_id,
                          "removed_at": _now_iso(), "removed_reason": reason}})
            remaining = await self.list_relations(file_id)
            await self._audit(
                action=ACTION_RELATION_REMOVED, actor_id=actor_id, entity_id=file_id,
                reason=reason, idempotency_key=idempotency_key,
                structured_diff={"relation_id": row["id"], "relation_type": relation_type,
                                 "record_id": record_id,
                                 "remaining_relations": len(remaining),
                                 "physical_original_touched": False})
            await self._complete(ACTION_RELATION_REMOVED, idempotency_key, row["id"])
            return {"status": STATUS_REGISTERED, "relation_id": row["id"],
                    "remaining_relations": len(remaining)}
        except Exception as exc:                                    # noqa: BLE001
            await self._fail(ACTION_RELATION_REMOVED, idempotency_key, type(exc).__name__)
            raise

    # ======================================================= provider location
    async def _write_location(self, file_id: str, version_no: int,
                              spec: Mapping[str, Any],
                              expected_checksum: Optional[Mapping[str, Any]] = None
                              ) -> Dict[str, Any]:
        row = m.build_provider_location(
            org_id=self.org_id, file_id=file_id, version_no=version_no,
            provider_kind=spec["provider_kind"],
            provider_binding_id=spec["provider_binding_id"],
            container=spec["container"], object_key=spec["object_key"],
            provider_file_id=spec.get("provider_file_id"),
            role=spec.get("role", m.LOCATION_ROLE_PRIMARY),
            expected_checksum=spec.get("expected_checksum") or expected_checksum,
            availability=spec.get("availability", m.AVAILABILITY_UNVERIFIED))
        await self.locations.insert_one(dict(row))
        return row

    async def set_provider_location(self, *, actor_id: str, file_id: str, version_no: int,
                                    provider_kind: str, provider_binding_id: str,
                                    container: str, object_key: str,
                                    provider_file_id: Optional[str] = None,
                                    role: str = m.LOCATION_ROLE_PRIMARY,
                                    reason: str = "provider location set",
                                    idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """Record where one version physically lives, or move it to a new provider.

        A provider migration replaces the location and leaves ``file_id``, the
        versions and every relation untouched — FLOW-016 §"Какво НЕ трябва да
        позволява" forbids a migration that breaks them. The previous location
        row of the same role is superseded, not deleted, so the history of where
        a file has lived stays auditable.
        """
        replay, prior = await self._begin(
            ACTION_LOCATION_SET, idempotency_key,
            {"file_id": file_id, "version_no": version_no, "provider_kind": provider_kind,
             "container": container, "object_key": object_key, "role": role})
        if replay:
            return {"status": STATUS_REPLAYED, "location_id": prior}
        try:
            await self.require_file(file_id)
            version = await self.versions.find_one(
                {"file_id": file_id, "version_no": version_no}, {"_id": 0})
            if not version:
                raise FileNotFound("no version %s of %r in this tenant" % (version_no, file_id))
            previous = await self.current_location(file_id, version_no, role)
            if previous:
                await self.locations.update_one(
                    {"id": previous["id"], "file_id": file_id},
                    {"$set": {"superseded_at": _now_iso(), "updated_at": _now_iso()}})
            row = await self._write_location(
                file_id, version_no,
                {"provider_kind": provider_kind, "provider_binding_id": provider_binding_id,
                 "container": container, "object_key": object_key,
                 "provider_file_id": provider_file_id, "role": role},
                version.get("checksum"))
            await self._audit(
                action=ACTION_LOCATION_SET, actor_id=actor_id, entity_id=file_id,
                entity_version=str(version_no), reason=reason, idempotency_key=idempotency_key,
                structured_diff={"location_id": row["id"], "provider_kind": provider_kind,
                                 "role": role, "replaced": (previous or {}).get("id"),
                                 "file_id_unchanged": True})
            await self._complete(ACTION_LOCATION_SET, idempotency_key, row["id"])
            return {"status": STATUS_REGISTERED, "location_id": row["id"],
                    "replaced": (previous or {}).get("id")}
        except Exception as exc:                                    # noqa: BLE001
            await self._fail(ACTION_LOCATION_SET, idempotency_key, type(exc).__name__)
            raise

    # ================================================================ integrity
    async def record_integrity_check(self, *, actor_id: str, file_id: str, version_no: int,
                                     verdict: IntegrityVerdict,
                                     role: str = m.LOCATION_ROLE_PRIMARY,
                                     idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """Record one availability/checksum verdict against a provider location.

        An externally changed object becomes ``checksum_mismatch`` — an
        integrity problem — and NOT a new version: BEG_Work never adopts a
        change nobody here made. The result also names every business record
        the file is attached to, because FLOW-016 forbids reporting a missing
        or altered file without the list of what it affects, and the severity
        follows that list rather than the error.
        """
        replay, prior = await self._begin(
            ACTION_INTEGRITY_CHECKED, idempotency_key,
            {"file_id": file_id, "version_no": version_no, "availability": verdict.availability,
             "checked_at": verdict.checked_at})
        if replay:
            return {"status": STATUS_REPLAYED, "location_id": prior}
        try:
            await self.require_file(file_id)
            location = await self.current_location(file_id, version_no, role)
            if not location:
                raise FileNotFound("no %s location for version %s of %r"
                                   % (role, version_no, file_id))
            await self.locations.update_one(
                {"id": location["id"], "file_id": file_id},
                {"$set": {"availability": verdict.availability,
                          "observed_checksum": verdict.observed_checksum,
                          "observed_size_bytes": verdict.observed_size_bytes,
                          "last_verified_at": verdict.checked_at or _now_iso(),
                          "last_check_error": verdict.error,
                          "updated_at": _now_iso()}})
            affected = await self.list_relations(file_id)
            severity = m.severity_of(verdict.availability, len(affected))
            await self._audit(
                action=ACTION_INTEGRITY_CHECKED, actor_id=actor_id, entity_id=file_id,
                entity_version=str(version_no),
                result=RESULT_SUCCESS if verdict.ok else RESULT_FAILURE,
                reason="integrity check: %s" % verdict.availability,
                idempotency_key=idempotency_key,
                structured_diff={
                    "availability": verdict.availability, "severity": severity,
                    "expected_checksum": verdict.expected_checksum,
                    "observed_checksum": verdict.observed_checksum,
                    "error": verdict.error,
                    # The list FLOW-016 requires: what is affected, by name.
                    "affected_records": [{"relation_type": r["relation_type"],
                                          "record_id": r["record_id"]} for r in affected],
                    "treated_as_new_version": False})
            await self._complete(ACTION_INTEGRITY_CHECKED, idempotency_key, location["id"])
            return {"status": STATUS_REGISTERED, "location_id": location["id"],
                    "availability": verdict.availability, "severity": severity,
                    "affected_records": [{"relation_type": r["relation_type"],
                                          "record_id": r["record_id"]} for r in affected]}
        except Exception as exc:                                    # noqa: BLE001
            await self._fail(ACTION_INTEGRITY_CHECKED, idempotency_key, type(exc).__name__)
            raise

    async def verify_with_adapter(self, *, actor_id: str, file_id: str, version_no: int,
                                  adapter: StorageProviderAdapter,
                                  role: str = m.LOCATION_ROLE_PRIMARY,
                                  idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """Run one check through a provider adapter and record its verdict.

        The registry builds the object reference from the stored location, so
        the adapter is told WHERE to look and never which business record it is
        looking for — the provider learns nothing about the tenant's business.
        """
        location = await self.current_location(file_id, version_no, role)
        if not location:
            raise FileNotFound("no %s location for version %s of %r" % (role, version_no, file_id))
        ref = ProviderObjectRef(container=location["container"],
                                object_key=location["object_key"],
                                provider_file_id=location.get("provider_file_id"))
        verdict = await adapter.verify(ref, location.get("expected_checksum"))
        return await self.record_integrity_check(
            actor_id=actor_id, file_id=file_id, version_no=version_no, verdict=verdict,
            role=role, idempotency_key=idempotency_key)

    # ================================================================== derived
    async def register_derived(self, *, actor_id: str, file_id: str, source_version_no: int,
                               kind: str, cache_reference: str,
                               expires_at: Optional[str] = None,
                               idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """Record a cached thumbnail / preview / OCR text / PDF render.

        It is a technical derivative of ONE version of ONE file, it is
        regenerable from the original, and it is never a business version:
        nothing here writes into the version collection, and
        :func:`app.files.models.build_derived` hard-codes
        ``is_canonical_original=False``.
        """
        replay, prior = await self._begin(
            ACTION_DERIVED_CACHED, idempotency_key,
            {"file_id": file_id, "version_no": source_version_no, "kind": kind})
        if replay:
            return {"status": STATUS_REPLAYED, "derived_id": prior}
        try:
            await self.require_file(file_id)
            row = m.build_derived(org_id=self.org_id, file_id=file_id,
                                  source_version_no=source_version_no, kind=kind,
                                  cache_reference=cache_reference, expires_at=expires_at)
            await self.derived.insert_one(dict(row))
            await self._audit(action=ACTION_DERIVED_CACHED, actor_id=actor_id, entity_id=file_id,
                              entity_version=str(source_version_no),
                              reason="derived %s cached" % kind,
                              idempotency_key=idempotency_key,
                              structured_diff={"derived_id": row["id"], "kind": kind,
                                               "is_canonical_original": False})
            await self._complete(ACTION_DERIVED_CACHED, idempotency_key, row["id"])
            return {"status": STATUS_REGISTERED, "derived_id": row["id"]}
        except Exception as exc:                                    # noqa: BLE001
            await self._fail(ACTION_DERIVED_CACHED, idempotency_key, type(exc).__name__)
            raise

    # =================================================================== delete
    async def request_physical_delete(self, *, actor_id: str, file_id: str, reason: str,
                                      version_no: Optional[int] = None,
                                      whole_file: bool = False,
                                      location_id: Optional[str] = None,
                                      approval_id: Optional[str] = None,
                                      idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """Open an explicit request to destroy the customer's original.

        This method deletes NOTHING. It records that a destruction was asked
        for, by whom and why. Only :meth:`record_delete_result`, carrying a
        provider's own answer, can close it — FLOW-016 forbids BEG_Work from
        presenting a File Registry removal as a guaranteed physical deletion at
        the customer.

        Scope (W0-06A review finding 3). Exactly one of:

        * ``version_no=N`` — the live locations of version N only (optionally
          narrowed to one ``location_id``). Every other version, and the file
          itself, stays as it is.
        * ``whole_file=True`` — every live location of every version, and the
          file moves to ``delete_requested``. Destroying a whole family is a
          separate, explicit choice; it is never what an absent argument means.

        The exact location ids are frozen into the request, so the provider's
        answer can only ever be applied to what was asked for.
        """
        if whole_file and version_no is not None:
            raise FileRegistryError("a delete is either one version or the whole file, not both")
        if not whole_file and version_no is None:
            raise FileRegistryError(
                "name the version to delete, or pass whole_file=True explicitly")
        if whole_file and location_id is not None:
            raise FileRegistryError("a whole-file delete covers every location; "
                                    "narrow it with version_no instead")
        scope = m.DELETE_SCOPE_FILE if whole_file else m.DELETE_SCOPE_VERSION
        replay, prior = await self._begin(
            ACTION_DELETE_REQUESTED, idempotency_key,
            {"file_id": file_id, "scope": scope, "version_no": version_no,
             "location_id": location_id, "reason": reason})
        if replay:
            return {"status": STATUS_REPLAYED, "request_id": prior}
        try:
            await self.require_file(file_id)
            flt: Dict[str, Any] = {"file_id": file_id}
            if scope == m.DELETE_SCOPE_VERSION:
                version = await self.versions.find_one(
                    {"file_id": file_id, "version_no": version_no}, {"_id": 0, "id": 1})
                if not version:
                    raise FileNotFound("no version %s of %r in this tenant" % (version_no, file_id))
                flt["version_no"] = version_no
            rows = await self.locations.find(flt, {"_id": 0}).to_list(None)
            live = [r for r in rows if r.get("superseded_at") is None
                    and r.get("destroyed_at_provider") is None]
            if location_id is not None:
                live = [r for r in live if r["id"] == location_id]
                if not live:
                    raise FileNotFound("no live location %r for version %s of %r"
                                       % (location_id, version_no, file_id))
            if not live:
                raise FileRegistryError("nothing to delete: no live provider location in scope")
            location_ids = tuple(sorted(r["id"] for r in live))
            row = m.build_delete_request(org_id=self.org_id, file_id=file_id,
                                         requested_by=actor_id, reason=reason, scope=scope,
                                         location_ids=location_ids, version_no=version_no,
                                         approval_id=approval_id)
            await self.delete_requests.insert_one(dict(row))
            if scope == m.DELETE_SCOPE_FILE:
                await self.files.update_one({"id": file_id},
                                            {"$set": {"status": m.FILE_DELETE_REQUESTED,
                                                      "updated_at": _now_iso()}})
            affected = await self.list_relations(file_id)
            await self._audit(
                action=ACTION_DELETE_REQUESTED, actor_id=actor_id, entity_id=file_id,
                entity_version=str(version_no) if version_no is not None else None,
                reason=reason, idempotency_key=idempotency_key,
                structured_diff={"request_id": row["id"], "scope": scope,
                                 "version_no": version_no,
                                 "location_ids": list(location_ids),
                                 "approval_id": approval_id,
                                 "affected_records": [{"relation_type": r["relation_type"],
                                                       "record_id": r["record_id"]}
                                                      for r in affected],
                                 "original_destroyed": False})
            await self._complete(ACTION_DELETE_REQUESTED, idempotency_key, row["id"])
            return {"status": STATUS_REGISTERED, "request_id": row["id"], "scope": scope,
                    "version_no": version_no, "location_ids": list(location_ids),
                    "affected_records": len(affected)}
        except Exception as exc:                                    # noqa: BLE001
            await self._fail(ACTION_DELETE_REQUESTED, idempotency_key, type(exc).__name__)
            raise

    async def record_delete_result(self, *, actor_id: str, request_id: str,
                                   receipt, idempotency_key: Optional[str] = None
                                   ) -> Dict[str, Any]:
        """Close a delete request with the PROVIDER's own answer.

        The answer applies to the request's frozen ``location_ids`` and to
        nothing else. A confirmed version-scoped delete marks exactly those
        locations destroyed; the other versions, their locations and the
        file's own status are untouched. Only a confirmed WHOLE-FILE request
        moves the file to ``deleted_at_provider``; a refusal or a failure of a
        whole-file request returns it to ``active``, because an original that
        still exists must not be shown as gone. The registry record is kept
        either way. A request is answered once: a second receipt is refused
        rather than allowed to flip a recorded outcome.
        """
        replay, prior = await self._begin(
            ACTION_DELETE_RESULT, idempotency_key,
            {"request_id": request_id, "state": receipt.state})
        if replay:
            return {"status": STATUS_REPLAYED, "request_id": prior}
        try:
            request = await self.delete_requests.find_one({"id": request_id}, {"_id": 0})
            if not request:
                raise FileNotFound("no delete request %r in this tenant" % request_id)
            if request.get("state") != m.DELETE_REQUESTED:
                raise FileRegistryError("delete request %r was already answered (%s)"
                                        % (request_id, request.get("state")))
            scope = request.get("scope")
            location_ids = list(request.get("location_ids") or [])
            if scope not in m.DELETE_SCOPES or not location_ids:
                # A request without a recorded scope cannot be applied safely:
                # refusing is the only answer that cannot over-delete.
                raise FileRegistryError("delete request %r has no recorded scope" % request_id)
            result = m.build_provider_result(
                provider_kind=receipt.provider_kind, state=receipt.state,
                response_code=receipt.response_code, message=receipt.message,
                confirmed_at=receipt.confirmed_at)
            claimed = await self.delete_requests.update_one(
                {"id": request_id, "state": m.DELETE_REQUESTED},
                {"$set": {"state": receipt.state, "provider_result": result,
                          "resolved_at": _now_iso()}})
            if getattr(claimed, "modified_count", 1) != 1:
                raise FileRegistryError("delete request %r was answered concurrently" % request_id)
            confirmed = receipt.state == m.DELETE_PROVIDER_CONFIRMED
            file_id = request["file_id"]
            if scope == m.DELETE_SCOPE_FILE:
                await self.files.update_one(
                    {"id": file_id},
                    {"$set": {"status": m.FILE_DELETED_AT_PROVIDER if confirmed else m.FILE_ACTIVE,
                              "updated_at": _now_iso()}})
            if confirmed:
                now = _now_iso()
                await self.locations.update_many(
                    {"file_id": file_id, "id": {"$in": location_ids}},
                    {"$set": {"availability": m.AVAILABILITY_MISSING,
                              "destroyed_at_provider": now,
                              "destroyed_by_request_id": request_id,
                              "last_check_error": "destroyed at provider on request",
                              "updated_at": now}})
            await self._audit(
                action=ACTION_DELETE_RESULT, actor_id=actor_id, entity_id=file_id,
                entity_version=(str(request["version_no"])
                                if request.get("version_no") is not None else None),
                result=RESULT_SUCCESS if confirmed else RESULT_FAILURE,
                reason="provider answered %s" % receipt.state,
                idempotency_key=idempotency_key,
                structured_diff={"request_id": request_id, "provider_result": result,
                                 "scope": scope, "version_no": request.get("version_no"),
                                 "location_ids": location_ids,
                                 "original_destroyed": confirmed,
                                 "file_status_changed": scope == m.DELETE_SCOPE_FILE})
            await self._complete(ACTION_DELETE_RESULT, idempotency_key, request_id)
            return {"status": STATUS_REGISTERED, "request_id": request_id,
                    "state": receipt.state, "original_destroyed": confirmed,
                    "scope": scope, "version_no": request.get("version_no"),
                    "location_ids": location_ids}
        except Exception as exc:                                    # noqa: BLE001
            await self._fail(ACTION_DELETE_RESULT, idempotency_key, type(exc).__name__)
            raise
