"""
W0-06B — file upload, open, download and share through the tenant's provider.

FLOW-016 §"Права и сигурност" / FLOW-002: the browser never receives storage
credentials; access is a short-lived, protected operation preceded by a
permission check; a permanent URL is never an access right; and upload, open,
download and share are each recorded in an AuditEvent.

Upload
    Only to the tenant's ACTIVE Primary provider (an unactivated tenant cannot
    store an original). The object key is opaque (``objects/<xx>/<random>``) so
    the provider learns nothing about the business record; the sha256 is
    computed by the server from the bytes it received; a duplicate checksum is
    reported BEFORE anything is written. The registry then records the file,
    its version and its provider location.

Access grants
    :meth:`FileAccessService.issue_access` runs FLOW-002 for the purpose
    (``file.open`` / ``file.download`` / ``file.share``) at the requested scope
    — and, for a scoped request, requires the file to be related to that very
    record — plus the file's sensitivity action. The original must be servable:
    a cached preview never stands in for it. The grant is then either

    * a provider pre-signed URL (only for a download, only where the provider
      supports expiring links, capped at 15 minutes), or
    * a BEG_Work grant: a random token returned ONCE, stored only as its
      sha256, bound to tenant, user, file, version, location and purpose,
      expiring, single-use and revocable.

    :meth:`redeem` re-runs FLOW-002 at the moment of use, re-checks expiry and
    use count atomically, reads the original and verifies its sha256 before a
    single byte is returned: an original changed outside BEG_Work is refused,
    not served.

Every denial is audited as ``file.access.denied`` (permission failure).
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from app.audit.envelope import (
    RESULT_DENIED,
    RETENTION_R1_CRITICAL_BUSINESS,
    RETENTION_R3_SECURITY_ACCESS,
)
from app.audit.idempotency import (
    IDEMPOTENCY_DUPLICATE,
    begin_idempotent,
    complete_idempotent,
    fail_idempotent,
    request_fingerprint,
)
from app.files import audit_trail
from app.files import models as m
from app.files.authorization import FileAccessDenied, authorize, sensitivity_action
from app.files.providers.base import (
    ACCESS_READ,
    MAX_TEMPORARY_ACCESS_SECONDS,
    ProviderError,
    ProviderObjectRef,
    sha256_checksum,
)
from app.files.registry import (
    ON_DUPLICATE_REPORT,
    STATUS_DUPLICATE,
    FileNotFound,
    FileRegistry,
)
from app.files.storage import StorageProviderService

GRANTS_COLLECTION = "storage_access_grants"

PURPOSE_OPEN = "open"
PURPOSE_DOWNLOAD = "download"
PURPOSE_SHARE = "share"
PURPOSE_ACTIONS = {PURPOSE_OPEN: "file.open", PURPOSE_DOWNLOAD: "file.download",
                   PURPOSE_SHARE: "file.share"}
REDEEM_AUDIT = {PURPOSE_OPEN: audit_trail.ACTION_FILE_OPENED,
                PURPOSE_DOWNLOAD: audit_trail.ACTION_FILE_DOWNLOADED,
                PURPOSE_SHARE: audit_trail.ACTION_FILE_SHARED}

MODE_PROVIDER_PRESIGNED = "provider_presigned"
MODE_BEG_GRANT = "beg_grant"

#: The scope types a request may name, and the relation that proves the file
#: belongs to that record (FLOW-002 "exact resource scope").
SCOPE_RELATIONS = {"project": (m.RELATION_PROJECT, m.RELATION_SUB_PROJECT)}


class OriginalUnavailable(RuntimeError):
    """The canonical original cannot be served; nothing substitutes for it."""

    def __init__(self, availability: str):
        super().__init__("canonical original is %s" % availability)
        self.availability = availability


class GrantInvalid(PermissionError):
    """Unknown, expired, used, revoked or foreign grant."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(("beg-grant|" + token).encode()).hexdigest()


class FileAccessService:
    def __init__(self, registry: FileRegistry, storage: StorageProviderService):
        if registry.org_id != storage.org_id:
            raise ValueError("registry and storage service belong to different tenants")
        self._registry = registry
        self._storage = storage
        self._tenant = registry._tenant
        self.org_id = registry.org_id

    @property
    def grants(self):
        return self._tenant.collection(GRANTS_COLLECTION)

    async def _audit(self, **kw):
        kw.setdefault("retention_class", RETENTION_R3_SECURITY_ACCESS)
        kw.setdefault("entity_type", "file")
        return await audit_trail.record(self._tenant, **kw)

    async def _denied(self, ctx, action: str, file_id: str, reason_code: str):
        await self._audit(action=audit_trail.ACTION_PERMISSION_FAILED,
                          actor_id=getattr(ctx, "user_id", None) or "anonymous",
                          entity_id=file_id, result=RESULT_DENIED, error_code=reason_code,
                          related_file_ids=[file_id], reason="%s denied" % action,
                          structured_diff={"requested_action": action,
                                           "reason_code": reason_code})

    async def _authorize_file(self, ctx, action: str, file_doc: Mapping[str, Any],
                              scope_type: Optional[str], scope_id: Optional[str]) -> None:
        file_id = file_doc["id"]
        try:
            if scope_type is not None:
                if scope_type not in SCOPE_RELATIONS or not scope_id:
                    raise FileAccessDenied(action, "UNKNOWN_SCOPE")
                related = {r["record_id"] for r in await self._registry.list_relations(file_id)
                           if r["relation_type"] in SCOPE_RELATIONS[scope_type]}
                if scope_id not in related:
                    raise FileAccessDenied(action, "FILE_NOT_IN_SCOPE")
            await authorize(ctx, action, org_id=self.org_id, scope_type=scope_type,
                            scope_id=scope_id)
            extra = sensitivity_action(file_doc.get("sensitivity"))
            if extra:
                await authorize(ctx, extra, org_id=self.org_id, scope_type=scope_type,
                                scope_id=scope_id)
        except FileAccessDenied as exc:
            await self._denied(ctx, action, file_id, exc.reason_code)
            raise

    # ================================================================ upload
    async def upload(self, ctx, *, data: bytes, display_name: str, original_name: str,
                     category: str, mime_type: str, sensitivity: str = m.SENSITIVITY_STANDARD,
                     relations: Sequence[Mapping[str, Any]] = (),
                     idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        await authorize(ctx, "file.upload", org_id=self.org_id)
        extra = sensitivity_action(sensitivity)
        if extra:
            await authorize(ctx, extra, org_id=self.org_id)
        checksum = sha256_checksum(bytes(data))
        db = self._tenant.audit_store_db()
        if idempotency_key:
            state = await begin_idempotent(
                db, tenant_id=self.org_id, key=idempotency_key, action=audit_trail.ACTION_FILE_UPLOADED,
                request_fingerprint=request_fingerprint(
                    {"checksum": checksum["value"], "name": original_name, "category": category,
                     "relations": [dict(r) for r in relations]}))
            if state["status"] == IDEMPOTENCY_DUPLICATE:
                return {"status": "replayed", "file_id": state.get("result_reference")}
        try:
            existing = await self._registry.find_by_checksum(checksum)
            if existing:
                out = await self._registry.register_file(
                    actor_id=ctx.user_id, display_name=display_name, original_name=original_name,
                    category=category, checksum_value=checksum, size_bytes=len(data),
                    mime_type=mime_type, sensitivity=sensitivity, relations=relations,
                    on_duplicate=ON_DUPLICATE_REPORT)
                if out["status"] != STATUS_DUPLICATE:
                    raise RuntimeError("duplicate check and registration disagree")
                if idempotency_key:
                    await complete_idempotent(db, tenant_id=self.org_id, key=idempotency_key,
                                              action=audit_trail.ACTION_FILE_UPLOADED,
                                              result_reference=out["file_id"])
                return {"status": "duplicate", "file_id": out["file_id"],
                        "candidates": out["candidates"], "provider_written": False}
            # Verify every relation target before a byte reaches the provider.
            for relation in relations:
                await self._registry._assert_relation_target(relation["relation_type"],
                                                             relation["record_id"])
            adapter = await self._storage.adapter(m.LOCATION_ROLE_PRIMARY)
            try:
                token = uuid.uuid4().hex
                key = "objects/%s/%s" % (token[:2], token)
                ref = await adapter.put(object_key=key, data=bytes(data), mime_type=mime_type)
                try:
                    out = await self._registry.register_file(
                        actor_id=ctx.user_id, display_name=display_name,
                        original_name=original_name, category=category, checksum_value=checksum,
                        size_bytes=len(data), mime_type=mime_type, sensitivity=sensitivity,
                        relations=relations,
                        provider_location={
                            "provider_kind": adapter.provider_kind,
                            "provider_binding_id": adapter.binding.binding_id,
                            "container": ref.container, "object_key": ref.object_key,
                            "provider_file_id": ref.provider_file_id,
                            "provider_version_id": ref.provider_version_id,
                            "size_bytes": len(data)})
                except Exception:
                    # The object was written by THIS call seconds ago and never
                    # became a registered original: remove it rather than leave an
                    # orphan in the customer's storage.
                    await adapter.request_delete(ref, reason="upload not registered")
                    raise
                # A successful write is not proof of a stored original: check the
                # object through the provider now and record what it says, so the
                # file is "available" only when the provider confirmed it.
                verified = await self._registry.verify_with_adapter(
                    actor_id=ctx.user_id, file_id=out["file_id"], version_no=1,
                    adapter=adapter)
            finally:
                await adapter.aclose()
            await self._audit(action=audit_trail.ACTION_FILE_UPLOADED, actor_id=ctx.user_id,
                              entity_id=out["file_id"], related_file_ids=[out["file_id"]],
                              retention_class=RETENTION_R1_CRITICAL_BUSINESS,
                              idempotency_key=idempotency_key, entity_version="1",
                              reason="original stored at the tenant's primary provider",
                              structured_diff={"provider_kind": adapter.provider_kind,
                                               "provider_binding_id": adapter.binding.binding_id,
                                               "size_bytes": len(data),
                                               "checksum": checksum["value"],
                                               "sensitivity": sensitivity})
            if idempotency_key:
                await complete_idempotent(db, tenant_id=self.org_id, key=idempotency_key,
                                          action=audit_trail.ACTION_FILE_UPLOADED,
                                          result_reference=out["file_id"])
            return {"status": "registered", "file_id": out["file_id"], "version_no": 1,
                    "provider_written": True, "availability": verified["availability"]}
        except Exception as exc:                                     # noqa: BLE001
            if idempotency_key:
                await fail_idempotent(db, tenant_id=self.org_id, key=idempotency_key,
                                      action=audit_trail.ACTION_FILE_UPLOADED,
                                      error_code=type(exc).__name__)
            raise

    # ================================================================ grants
    async def issue_access(self, ctx, *, file_id: str, purpose: str,
                           scope_type: Optional[str] = None, scope_id: Optional[str] = None,
                           seconds: int = 300) -> Dict[str, Any]:
        if purpose not in PURPOSE_ACTIONS:
            raise ValueError("unknown access purpose %r" % purpose)
        if not isinstance(seconds, int) or seconds <= 0 or seconds > MAX_TEMPORARY_ACCESS_SECONDS:
            raise ValueError("an access grant lives 1..%d seconds" % MAX_TEMPORARY_ACCESS_SECONDS)
        action = PURPOSE_ACTIONS[purpose]
        file_doc = await self._registry.get_file(file_id)
        if not file_doc:
            # Absent and foreign look the same; still a recorded refusal.
            await self._denied(ctx, action, file_id, "NOT_FOUND")
            raise FileNotFound("no file %r in this tenant" % file_id)
        await self._authorize_file(ctx, action, file_doc, scope_type, scope_id)
        answer = await self._registry.canonical_original(file_id)
        if not answer["original_servable"]:
            raise OriginalUnavailable(answer["availability"])
        location = answer["location"]
        adapter = await self._storage.adapter_for_binding(location["provider_binding_id"])
        try:
            ref = ProviderObjectRef(container=location["container"],
                                    object_key=location["object_key"],
                                    provider_file_id=location.get("provider_file_id"))
            if purpose == PURPOSE_DOWNLOAD and adapter.capabilities().temporary_links:
                grant = await adapter.temporary_access(ref, purpose=ACCESS_READ, seconds=seconds)
                result = {"mode": MODE_PROVIDER_PRESIGNED, "url": grant.provider_url,
                          "expires_at": grant.expires_at, "grant_id": None}
            else:
                token = secrets.token_urlsafe(32)
                grant_id = "sag_" + uuid.uuid4().hex
                expires_at = (_now() + timedelta(seconds=seconds)).isoformat()
                await self.grants.insert_one({
                    "id": grant_id, m.ORG_KEY: self.org_id, "token_sha256": _token_hash(token),
                    "file_id": file_id, "version_no": answer["version_no"],
                    "location_id": location["id"], "purpose": purpose,
                    "user_id": ctx.user_id, "scope_type": scope_type, "scope_id": scope_id,
                    "expires_at": expires_at, "max_uses": 1, "uses": 0, "revoked_at": None,
                    "created_at": _now().isoformat()})
                result = {"mode": MODE_BEG_GRANT, "token": token, "expires_at": expires_at,
                          "grant_id": grant_id}
        finally:
            await adapter.aclose()
        await self._audit(action=audit_trail.ACTION_ACCESS_GRANTED, actor_id=ctx.user_id,
                          entity_id=file_id, related_file_ids=[file_id],
                          entity_version=str(answer["version_no"]),
                          reason="%s access granted" % purpose,
                          structured_diff={"purpose": purpose, "mode": result["mode"],
                                           "grant_id": result["grant_id"],
                                           "expires_at": result["expires_at"],
                                           "scope_type": scope_type, "scope_id": scope_id})
        return result

    async def revoke(self, ctx, *, grant_id: str) -> None:
        grant = await self.grants.find_one({"id": grant_id}, {"_id": 0})
        if not grant:
            raise GrantInvalid("no such grant")
        if grant["user_id"] != ctx.user_id:
            await authorize(ctx, "file.share", org_id=self.org_id)
        await self.grants.update_one({"id": grant_id}, {"$set": {"revoked_at": _now().isoformat()}})

    async def redeem(self, ctx, *, token: str) -> Tuple[bytes, str, str]:
        """``(bytes, mime_type, file_id)`` — after FLOW-002 and an integrity re-check."""
        if not isinstance(token, str) or not token:
            raise GrantInvalid("no token")
        grant = await self.grants.find_one({"token_sha256": _token_hash(token)}, {"_id": 0})
        if not grant:
            # Unknown here — including a real token of ANOTHER tenant.
            raise GrantInvalid("unknown grant")
        file_id = grant["file_id"]
        action = PURPOSE_ACTIONS[grant["purpose"]]
        if grant.get("revoked_at"):
            raise GrantInvalid("grant revoked")
        if datetime.fromisoformat(grant["expires_at"]) <= _now():
            raise GrantInvalid("grant expired")
        if grant["purpose"] != PURPOSE_SHARE and grant["user_id"] != getattr(ctx, "user_id", None):
            await self._denied(ctx, action, file_id, "GRANT_OF_ANOTHER_USER")
            raise GrantInvalid("grant belongs to another user")
        file_doc = await self._registry.require_file(file_id)
        # FLOW-002 at the moment of use, not only when the grant was minted.
        check_action = "file.open" if grant["purpose"] == PURPOSE_SHARE else action
        await self._authorize_file(ctx, check_action, file_doc, grant.get("scope_type"),
                                   grant.get("scope_id"))
        claimed = await self.grants.find_one_and_update(
            {"id": grant["id"], "uses": {"$lt": grant["max_uses"]}, "revoked_at": None},
            {"$inc": {"uses": 1}, "$set": {"last_used_at": _now().isoformat(),
                                           "last_used_by": ctx.user_id}})
        if not claimed:
            raise GrantInvalid("grant already used")
        location = await self._registry.locations.find_one(
            {"id": grant["location_id"], "file_id": file_id}, {"_id": 0})
        if not location or not m.is_usable(location) or location.get("superseded_at"):
            raise OriginalUnavailable((location or {}).get("availability", m.AVAILABILITY_MISSING))
        version = await self._registry.versions.find_one(
            {"file_id": file_id, "version_no": grant["version_no"]}, {"_id": 0})
        adapter = await self._storage.adapter_for_binding(location["provider_binding_id"])
        try:
            data = await adapter.read(ProviderObjectRef(
                container=location["container"], object_key=location["object_key"],
                provider_file_id=location.get("provider_file_id")))
        except ProviderError as exc:
            raise OriginalUnavailable(exc.availability) from None
        finally:
            await adapter.aclose()
        if sha256_checksum(data) != (location.get("expected_checksum") or version["checksum"]):
            # Never serve bytes that are not the recorded original.
            raise OriginalUnavailable(m.AVAILABILITY_CHECKSUM_MISMATCH)
        await self._audit(action=REDEEM_AUDIT[grant["purpose"]], actor_id=ctx.user_id,
                          entity_id=file_id, related_file_ids=[file_id],
                          entity_version=str(grant["version_no"]),
                          reason="original served through a BEG_Work grant",
                          structured_diff={"grant_id": grant["id"], "purpose": grant["purpose"],
                                           "size_bytes": len(data)})
        return data, version["mime_type"], file_id
