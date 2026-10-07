"""
W0-06B — tenant storage provider bindings and the onboarding activation gate.

FLOW-016 §"Onboarding gate" / CLAUDE.md §4: a tenant is not activated without
its OWN Primary Storage Provider, valid credentials, a read/write test in a
tenant-specific root and a checksum round-trip. This module is that gate, and
the only way a tenant's provider becomes usable for real files.

Records (all ``org_id``-keyed, in the tenant's operational database)
----------------------------------------------------------------------
``storage_provider_bindings``
    One configured provider account per role (``primary`` mandatory before
    activation, ``backup`` optional): provider kind, endpoint, account,
    container (bucket / share / root folder / collection), tenant root, the
    vault REFERENCE of its encrypted credentials (never a value), declared
    capabilities, connection status, last verification, activation state and
    the accepted customer-vs-BEG_Work responsibility boundary.
``storage_activation_runs``
    One row per activation attempt, with every gate step, its result and its
    error code — the evidence of why a tenant is or is not active.
``storage_credentials``
    The sealed credentials (:mod:`app.files.credentials`).

Tenant Registry (system database)
---------------------------------
A successful PRIMARY activation records ``primary_storage_provider_type``,
``primary_storage_provider_reference`` (the binding id), ``storage_status:
active`` and ``storage_verified_at`` on the tenant's own registry row — the
fields TENANCY_MODEL §4 names. A root fingerprint is recorded there too, so two
tenants can never be activated on the same provider root; the check answers
only "claimed or not" and discloses nothing about the other tenant.

The gate, in order — every step must pass; any failure leaves the binding
``verification_failed``, the tenant's storage NOT active, an activation-run row
naming the failed step, and a ``storage.provider.verification_failed`` event:

 1. ``provider_selected``      a customer-managed kind, the binding of this tenant;
 2. ``responsibility_accepted`` the FLOW-016 boundary text, accepted by THIS user;
 3. ``credentials_valid``      the vault resolves them and the provider accepts them;
 4. ``root_verified``          the tenant root exists, is writable, is claimed by
                               no other tenant (registry fingerprint + root marker);
 5. ``test_object_uploaded``   a random temporary object is written under the root;
 6. ``test_object_read_back``  and read back byte-identical;
 7. ``checksum_round_trip``    the sha256 of what was sent equals what came back
                               (and the provider's own checksum, when it reports one);
 8. ``test_object_cleaned_up`` the provider CONFIRMS deletion and a stat proves it;
 9. ``tenant_registry_updated`` (primary) / ``backup_recorded`` (backup);
10. ``audit_recorded``          ``storage.provider.verified``.

Nothing here activates a real tenant or touches a live provider in this task:
tests run it against disposable fakes with fake credentials.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional

from app.audit.envelope import (
    RESULT_FAILURE,
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
from app.files.authorization import authorize
from app.files.credentials import CREDENTIALS_COLLECTION, CredentialVault, validate_secret
from app.files.providers.base import (
    ProviderBinding,
    ProviderCredentialsInvalid,
    ProviderError,
    ProviderObjectMissing,
    ProviderObjectRef,
    ProviderPermissionDenied,
    StorageProviderAdapter,
    adapter_class,
    adapter_for,
    sha256_checksum,
)

BINDINGS_COLLECTION = "storage_provider_bindings"
ACTIVATION_RUNS_COLLECTION = "storage_activation_runs"
STORAGE_COLLECTIONS = frozenset({BINDINGS_COLLECTION, ACTIVATION_RUNS_COLLECTION,
                                 CREDENTIALS_COLLECTION})

ROLE_PRIMARY = m.LOCATION_ROLE_PRIMARY
ROLE_BACKUP = m.LOCATION_ROLE_BACKUP

BINDING_UNVERIFIED = "unverified"
BINDING_ACTIVE = "active"
BINDING_VERIFICATION_FAILED = "verification_failed"
BINDING_SUPERSEDED = "superseded"

TENANT_STORAGE_ACTIVE = "active"
TENANT_STORAGE_VERIFICATION_FAILED = "verification_failed"

STEPS = ("provider_selected", "responsibility_accepted", "credentials_valid", "root_verified",
         "test_object_uploaded", "test_object_read_back", "checksum_round_trip",
         "test_object_cleaned_up", "registry_recorded", "audit_recorded")

#: The FLOW-016 responsibility boundary the tenant's administrator accepts.
RESPONSIBILITY_VERSION = "FLOW-016/2026-08-03"
RESPONSIBILITY_TEXT_BG = (
    "Оригиналните файлове се съхраняват физически в хранилището на клиента, на негова "
    "сметка и договорна отговорност (капацитет, абонамент, основно съхранение, достъпност). "
    "BEG_Work отговаря за File Registry, metadata, връзки, версии, checksums, проверки, "
    "AuditEvent и ограничения технически кеш.")
RESPONSIBILITY_TEXT_EN = (
    "Original files are stored physically in the customer's own storage, at the customer's "
    "cost and contractual responsibility (capacity, subscription, primary retention, "
    "availability). BEG_Work is responsible for the File Registry, metadata, relations, "
    "versions, checksums, checks, AuditEvents and a limited technical cache.")

ROOT_MARKER_KEY = "_beg_work/tenant-root.json"
ACTIVATION_PREFIX = "_beg_work/activation/"


class StorageNotActive(RuntimeError):
    """The tenant has no ACTIVE binding for this role: real file I/O is refused."""


class StorageConfigurationRefused(ValueError):
    """A binding request violates a FLOW-016 rule."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def root_fingerprint(kind: str, endpoint: str, container: str, root: str) -> str:
    """Identity of one provider root, independent of which tenant asks."""
    norm = "|".join([kind, (endpoint or "").strip().rstrip("/").lower(),
                     container.strip().strip("/"), (root or "").strip().strip("/")])
    return hashlib.sha256(norm.encode()).hexdigest()


def tenant_root_marker(org_id: str) -> bytes:
    return json.dumps({"schema": "beg.storage_root.v1",
                       "tenant": hashlib.sha256(("beg-root|" + org_id).encode()).hexdigest()},
                      sort_keys=True).encode()


@dataclass
class StepFailed(Exception):
    step: str
    code: str
    detail: str = ""


def public_view(binding: Mapping[str, Any]) -> Dict[str, Any]:
    """What an API or the Health Dashboard may show. No credential reference, no secret."""
    keep = ("id", "role", "provider_kind", "endpoint", "account", "container", "root_prefix",
            "status", "connection_status", "capabilities", "last_verified_at",
            "last_verification_error", "activated_at", "responsibility", "created_at")
    return {k: binding.get(k) for k in keep}


class StorageProviderService:
    """One tenant's storage provider configuration and activation gate."""

    def __init__(self, tenant, system_db, *, vault: Optional[CredentialVault] = None,
                 transport_for: Optional[Callable[[Mapping[str, Any]], Any]] = None):
        if tenant is None:
            raise StorageConfigurationRefused("the storage service needs a resolved tenant")
        self._tenant = tenant
        self.org_id = tenant.org_id
        self._system_db = system_db
        self._vault = vault or CredentialVault(tenant)
        #: How a binding reaches its provider. Production: ``None`` (real HTTP).
        #: Tests: the in-process fake backend of that binding.
        self._transport_for = transport_for or (lambda binding: None)

    # ------------------------------------------------------------ handles
    @property
    def bindings(self):
        return self._tenant.collection(BINDINGS_COLLECTION)

    @property
    def runs(self):
        return self._tenant.collection(ACTIVATION_RUNS_COLLECTION)

    async def _audit(self, **kw):
        return await audit_trail.record(self._tenant, retention_class=RETENTION_R3_SECURITY_ACCESS,
                                        entity_type="storage_binding", **kw)

    async def _begin(self, action, key, payload):
        if not key:
            return False, None
        state = await begin_idempotent(self._tenant.audit_store_db(), tenant_id=self.org_id,
                                       key=key, action=action,
                                       request_fingerprint=request_fingerprint(payload))
        if state["status"] == IDEMPOTENCY_DUPLICATE:
            return True, state.get("result_reference")
        return False, None

    async def _complete(self, action, key, ref):
        if key:
            await complete_idempotent(self._tenant.audit_store_db(), tenant_id=self.org_id,
                                      key=key, action=action, result_reference=ref)

    async def _fail(self, action, key, code):
        if key:
            await fail_idempotent(self._tenant.audit_store_db(), tenant_id=self.org_id, key=key,
                                  action=action, error_code=code)

    # =============================================================== read
    async def get_binding(self, binding_id: str) -> Optional[Dict[str, Any]]:
        return await self.bindings.find_one({"id": binding_id}, {"_id": 0})

    async def active_binding(self, role: str = ROLE_PRIMARY) -> Optional[Dict[str, Any]]:
        rows = await self.bindings.find({"role": role, "status": BINDING_ACTIVE},
                                        {"_id": 0}).to_list(None)
        if len(rows) > 1:
            # Two active bindings for one role is a corrupt state: refuse to guess.
            raise StorageNotActive("more than one active %s binding" % role)
        return rows[0] if rows else None

    async def list_bindings(self, ctx) -> List[Dict[str, Any]]:
        await authorize(ctx, "storage.provider.read", org_id=self.org_id)
        rows = await self.bindings.find({}, {"_id": 0}).to_list(None)
        return [public_view(r) for r in sorted(rows, key=m.sort_key)]

    def provider_binding(self, row: Mapping[str, Any]) -> ProviderBinding:
        return ProviderBinding(binding_id=row["id"], org_id=self.org_id,
                               provider_kind=row["provider_kind"], container=row["container"],
                               secret_reference=row["credential_reference"],
                               root_prefix=row.get("root_prefix") or "",
                               endpoint=row.get("endpoint") or "", account=row.get("account") or "")

    async def _adapter_for_row(self, row: Mapping[str, Any]) -> StorageProviderAdapter:
        binding = self.provider_binding(row)
        secret = await self._vault.resolve(reference=row["credential_reference"],
                                           binding_id=row["id"], provider_kind=row["provider_kind"])
        return adapter_for(binding, credentials=secret, transport=self._transport_for(row))

    async def adapter(self, role: str = ROLE_PRIMARY) -> StorageProviderAdapter:
        """The operational adapter of an ACTIVE binding. Anything else is refused."""
        row = await self.active_binding(role)
        if not row:
            raise StorageNotActive("the tenant has no active %s storage provider" % role)
        return await self._adapter_for_row(row)

    async def adapter_for_binding(self, binding_id: str) -> StorageProviderAdapter:
        """The adapter of one ACTIVE binding of this tenant (for an existing location)."""
        row = await self.get_binding(binding_id)
        if not row or row.get("status") != BINDING_ACTIVE:
            raise StorageNotActive("binding %r is not an active binding of this tenant"
                                   % binding_id)
        return await self._adapter_for_row(row)

    # ========================================================== configure
    async def configure_binding(self, ctx, *, role: str, provider_kind: str, container: str,
                                credentials: Mapping[str, Any], endpoint: str = "",
                                account: str = "", root_prefix: str = "",
                                idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """Record a provider account for ``role``. It starts UNVERIFIED and inactive.

        The credentials go straight into the vault; the binding keeps only the
        reference. The AuditEvent names the provider, the account and the
        credential FIELD NAMES — never a value.
        """
        await authorize(ctx, "storage.provider.configure", org_id=self.org_id)
        if role not in (ROLE_PRIMARY, ROLE_BACKUP):
            raise StorageConfigurationRefused("role must be primary or backup")
        if provider_kind not in m.CUSTOMER_MANAGED_PROVIDER_KINDS:
            raise StorageConfigurationRefused(
                "only a customer-managed provider may hold a tenant's originals")
        clean = validate_secret(provider_kind, credentials)
        payload = {"role": role, "provider_kind": provider_kind, "container": container,
                   "endpoint": endpoint, "account": account, "root_prefix": root_prefix,
                   "credential_fields": sorted(clean)}
        replay, prior = await self._begin(audit_trail.ACTION_PROVIDER_CONNECTED,
                                          idempotency_key, payload)
        if replay:
            return {"status": "replayed", "binding_id": prior}
        try:
            binding_id = "sb_" + uuid.uuid4().hex
            # Validate the shape before anything is stored (a bad root, a missing
            # endpoint or account raises here), and read the declared
            # capabilities. No provider is contacted.
            probe = adapter_class(provider_kind)(
                ProviderBinding(binding_id=binding_id, org_id=self.org_id,
                                provider_kind=provider_kind, container=container,
                                root_prefix=root_prefix, endpoint=endpoint, account=account),
                credentials=clean)
            caps = probe.capabilities().as_dict()
            await probe.aclose()
            reference = await self._vault.store(binding_id=binding_id, provider_kind=provider_kind,
                                                secret=clean, created_by=ctx.user_id)
            now = _now()
            row = {
                "id": binding_id, m.ORG_KEY: self.org_id, "role": role,
                "provider_kind": provider_kind, "endpoint": endpoint, "account": account,
                "container": container, "root_prefix": root_prefix,
                "credential_reference": reference, "capabilities": caps,
                "status": BINDING_UNVERIFIED, "connection_status": "not_checked",
                "last_verified_at": None, "last_verification_error": None,
                "activated_at": None, "responsibility": None,
                "created_by": ctx.user_id, "created_at": now, "updated_at": now,
            }
            await self.bindings.insert_one(dict(row))
            await self._audit(action=audit_trail.ACTION_PROVIDER_CONNECTED, actor_id=ctx.user_id,
                              entity_id=binding_id, idempotency_key=idempotency_key,
                              reason="storage provider configured (unverified)",
                              structured_diff={"role": role, "provider_kind": provider_kind,
                                               "endpoint": endpoint, "account": account,
                                               "container": container, "root_prefix": root_prefix,
                                               "credential_field_names": sorted(clean),
                                               "status": BINDING_UNVERIFIED})
            await self._complete(audit_trail.ACTION_PROVIDER_CONNECTED, idempotency_key,
                                 binding_id)
            return {"status": "configured", "binding_id": binding_id,
                    "binding": public_view(row)}
        except Exception as exc:                                     # noqa: BLE001
            await self._fail(audit_trail.ACTION_PROVIDER_CONNECTED, idempotency_key,
                             type(exc).__name__)
            raise

    # ============================================================ activate
    async def activate(self, ctx, *, binding_id: str, responsibility: Mapping[str, Any],
                       idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """Run the onboarding gate for one binding. See the module docstring.

        Returns ``{"activated": bool, "run_id", "steps", "failed_step", "code"}``.
        A refusal is a RESULT, not an exception: the evidence of a failed gate is
        exactly what an administrator needs to see.
        """
        await authorize(ctx, "storage.provider.activate", org_id=self.org_id)
        replay, prior = await self._begin(audit_trail.ACTION_PROVIDER_VERIFIED, idempotency_key,
                                          {"binding_id": binding_id,
                                           "responsibility": dict(responsibility or {})})
        if replay:
            run = await self.runs.find_one({"id": prior}, {"_id": 0})
            return {"status": "replayed", "run_id": prior,
                    "activated": bool(run and run.get("activated"))}
        run_id = "sar_" + uuid.uuid4().hex
        steps: List[Dict[str, Any]] = []
        row: Optional[Dict[str, Any]] = None
        adapter: Optional[StorageProviderAdapter] = None
        test_ref: Optional[ProviderObjectRef] = None

        def passed(step, **detail):
            steps.append({"step": step, "ok": True, "at": _now(), **detail})

        try:
            # 1 ─ provider selected
            row = await self.get_binding(binding_id)
            if not row:
                raise StepFailed("provider_selected", "NO_SUCH_BINDING")
            if row.get("provider_kind") not in m.CUSTOMER_MANAGED_PROVIDER_KINDS:
                raise StepFailed("provider_selected", "NOT_CUSTOMER_MANAGED")
            if row.get("status") == BINDING_SUPERSEDED:
                raise StepFailed("provider_selected", "BINDING_SUPERSEDED")
            passed("provider_selected", provider_kind=row["provider_kind"], role=row["role"])

            # 2 ─ responsibility boundary accepted by THIS user, current text
            r = dict(responsibility or {})
            if not (r.get("accepted") is True and r.get("version") == RESPONSIBILITY_VERSION
                    and r.get("accepted_by") == ctx.user_id):
                raise StepFailed("responsibility_accepted", "RESPONSIBILITY_NOT_ACCEPTED")
            acceptance = {"version": RESPONSIBILITY_VERSION, "accepted_by": ctx.user_id,
                          "accepted_at": _now(), "text_bg": RESPONSIBILITY_TEXT_BG,
                          "text_en": RESPONSIBILITY_TEXT_EN}
            passed("responsibility_accepted", version=RESPONSIBILITY_VERSION)

            # 3 ─ credentials valid
            try:
                adapter = await self._adapter_for_row(row)
                await adapter.validate_credentials()
            except ProviderCredentialsInvalid as exc:
                raise StepFailed("credentials_valid", exc.code or "INVALID_CREDENTIALS")
            except ProviderPermissionDenied as exc:
                raise StepFailed("credentials_valid", exc.code or "PERMISSION_DENIED")
            except ProviderError as exc:
                raise StepFailed("credentials_valid", exc.code or "PROVIDER_ERROR")
            except Exception as exc:                                  # vault refusals
                raise StepFailed("credentials_valid", type(exc).__name__)
            passed("credentials_valid")

            # 4 ─ tenant-specific root: exists, writable, nobody else's
            fingerprint = root_fingerprint(row["provider_kind"], row.get("endpoint") or "",
                                           row["container"], row.get("root_prefix") or "")
            if await self._root_claimed_elsewhere(fingerprint):
                raise StepFailed("root_verified", "ROOT_CLAIMED_BY_ANOTHER_TENANT")
            try:
                await adapter.check_root()
                await self._claim_root_marker(adapter)
            except StepFailed:
                raise
            except ProviderPermissionDenied as exc:
                raise StepFailed("root_verified", exc.code or "PERMISSION_DENIED")
            except ProviderObjectMissing as exc:
                raise StepFailed("root_verified", exc.code or "ROOT_NOT_FOUND")
            except ProviderError as exc:
                raise StepFailed("root_verified", exc.code or "PROVIDER_ERROR")
            passed("root_verified", root_fingerprint=fingerprint)

            # 5–7 ─ temporary object: upload, read back, checksum round-trip
            payload = os.urandom(1024)
            sent = sha256_checksum(payload)
            key = "%s%s.bin" % (ACTIVATION_PREFIX, run_id)
            try:
                test_ref = await adapter.put(object_key=key, data=payload,
                                             mime_type="application/octet-stream")
            except ProviderError as exc:
                raise StepFailed("test_object_uploaded", exc.code or "PUT_FAILED")
            passed("test_object_uploaded", size_bytes=len(payload))
            try:
                back = await adapter.read(test_ref)
            except ProviderError as exc:
                raise StepFailed("test_object_read_back", exc.code or "READ_FAILED")
            if back != payload:
                raise StepFailed("test_object_read_back", "BYTES_DIFFER")
            passed("test_object_read_back")
            received = sha256_checksum(back)
            stat = await adapter.stat(test_ref)
            if received != sent or (stat.checksum and stat.checksum != sent) \
                    or (stat.size_bytes is not None and stat.size_bytes != len(payload)):
                raise StepFailed("checksum_round_trip", "CHECKSUM_MISMATCH")
            passed("checksum_round_trip", sha256=sent["value"],
                   provider_checksum=bool(stat.checksum))

            # 8 ─ cleanup, confirmed by the provider and proven by absence
            receipt = await adapter.request_delete(test_ref, reason="activation test cleanup")
            if receipt.state != m.DELETE_PROVIDER_CONFIRMED:
                raise StepFailed("test_object_cleaned_up", receipt.response_code or receipt.state)
            test_ref = None
            passed("test_object_cleaned_up")

            # 9 ─ Tenant Registry (primary) / backup reference
            await self._record_in_registry(row, fingerprint)
            passed("registry_recorded", role=row["role"])

            # bind: this binding active, a previous active one of the role superseded
            now = _now()
            await self.bindings.update_many(
                {"role": row["role"], "status": BINDING_ACTIVE, "id": {"$ne": binding_id}},
                {"$set": {"status": BINDING_SUPERSEDED, "updated_at": now}})
            await self.bindings.update_one(
                {"id": binding_id},
                {"$set": {"status": BINDING_ACTIVE, "connection_status": "connected",
                          "last_verified_at": now, "last_verification_error": None,
                          "activated_at": now, "responsibility": acceptance,
                          "root_fingerprint": fingerprint, "updated_at": now}})

            # 10 ─ AuditEvent
            await self._audit(action=audit_trail.ACTION_PROVIDER_VERIFIED, actor_id=ctx.user_id,
                              entity_id=binding_id, idempotency_key=idempotency_key,
                              reason="storage provider verified and activated",
                              structured_diff={"run_id": run_id, "role": row["role"],
                                               "provider_kind": row["provider_kind"],
                                               "steps": [s["step"] for s in steps],
                                               "responsibility_version": RESPONSIBILITY_VERSION})
            passed("audit_recorded")
            await self._store_run(run_id, binding_id, steps, activated=True)
            await self._complete(audit_trail.ACTION_PROVIDER_VERIFIED, idempotency_key, run_id)
            return {"status": "activated", "activated": True, "run_id": run_id,
                    "steps": steps, "failed_step": None, "code": None}
        except StepFailed as failure:
            steps.append({"step": failure.step, "ok": False, "code": failure.code, "at": _now()})
            if adapter is not None and test_ref is not None:
                try:   # best effort: never leave the activation object behind
                    await adapter.request_delete(test_ref, reason="activation aborted")
                except ProviderError:
                    pass
            await self._record_failure(row, binding_id, failure)
            await self._audit(action=audit_trail.ACTION_PROVIDER_VERIFICATION_FAILED,
                              actor_id=ctx.user_id, entity_id=binding_id, result=RESULT_FAILURE,
                              error_code=failure.code, idempotency_key=idempotency_key,
                              reason="storage activation blocked at %s" % failure.step,
                              structured_diff={"run_id": run_id, "failed_step": failure.step,
                                               "code": failure.code,
                                               "passed_steps": [s["step"] for s in steps
                                                                if s["ok"]]})
            await self._store_run(run_id, binding_id, steps, activated=False,
                                  failed_step=failure.step, code=failure.code)
            await self._complete(audit_trail.ACTION_PROVIDER_VERIFIED, idempotency_key, run_id)
            return {"status": "blocked", "activated": False, "run_id": run_id, "steps": steps,
                    "failed_step": failure.step, "code": failure.code}
        finally:
            if adapter is not None:
                await adapter.aclose()

    # ------------------------------------------------------------ helpers
    async def _store_run(self, run_id, binding_id, steps, *, activated, failed_step=None,
                         code=None):
        await self.runs.insert_one({"id": run_id, m.ORG_KEY: self.org_id,
                                    "binding_id": binding_id, "activated": activated,
                                    "steps": steps, "failed_step": failed_step, "code": code,
                                    "created_at": _now()})

    async def _record_failure(self, row, binding_id, failure: StepFailed):
        if row is None:
            return
        await self.bindings.update_one(
            {"id": binding_id, "status": {"$ne": BINDING_ACTIVE}},
            {"$set": {"status": BINDING_VERIFICATION_FAILED,
                      "connection_status": failure.code.lower(),
                      "last_verification_error": "%s:%s" % (failure.step, failure.code),
                      "updated_at": _now()}})
        if row.get("role") == ROLE_PRIMARY and not await self.active_binding(ROLE_PRIMARY):
            # Only a tenant WITHOUT an active primary is marked failed; a failed
            # re-verification of a new provider never deactivates the old one.
            await self._system_db["tenant_registry"].update_one(
                {"id": self.org_id, "storage_status": {"$ne": TENANT_STORAGE_ACTIVE}},
                {"$set": {"storage_status": TENANT_STORAGE_VERIFICATION_FAILED,
                          "storage_last_error": "%s:%s" % (failure.step, failure.code),
                          "updated_at": _now()}})

    async def _root_claimed_elsewhere(self, fingerprint: str) -> bool:
        other = await self._system_db["tenant_registry"].find_one(
            {"storage_root_fingerprints": fingerprint, "id": {"$ne": self.org_id}},
            {"_id": 0, "id": 1})
        return other is not None

    async def _claim_root_marker(self, adapter: StorageProviderAdapter) -> None:
        """The provider-side half of 'nobody else's root'.

        A marker object names this tenant (by a hash). Found and naming another
        tenant: refuse. Absent: write it — a root is claimed the first time it
        is activated and can never silently be shared afterwards.
        """
        marker = tenant_root_marker(self.org_id)
        ref = ProviderObjectRef(container=adapter.binding.container, object_key=ROOT_MARKER_KEY)
        stat = await adapter.stat(ref)
        if stat.exists:
            if await adapter.read(ref) != marker:
                raise StepFailed("root_verified", "ROOT_CLAIMED_BY_ANOTHER_TENANT")
            return
        await adapter.put(object_key=ROOT_MARKER_KEY, data=marker, mime_type="application/json")

    async def _record_in_registry(self, row, fingerprint: str) -> None:
        now = _now()
        update: Dict[str, Any] = {"updated_at": now}
        if row["role"] == ROLE_PRIMARY:
            update.update({"primary_storage_provider_type": row["provider_kind"],
                           "primary_storage_provider_reference": row["id"],
                           "storage_provider": row["provider_kind"],
                           "storage_status": TENANT_STORAGE_ACTIVE,
                           "storage_verified_at": now, "storage_last_error": None})
        else:
            update.update({"backup_storage_provider_type": row["provider_kind"],
                           "backup_storage_provider_reference": row["id"],
                           "backup_storage_verified_at": now})
        result = await self._system_db["tenant_registry"].update_one(
            {"id": self.org_id},
            {"$set": update, "$addToSet": {"storage_root_fingerprints": fingerprint}})
        if getattr(result, "matched_count", 0) != 1:
            raise StepFailed("registry_recorded", "TENANT_NOT_REGISTERED")
