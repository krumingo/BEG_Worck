"""
W0-06A — the in-memory storage provider double.

The contract in :mod:`app.files.providers.base` is only worth something if
something implements it end to end. This adapter does, in process, with no
network, no credential and no disk: it is how the provider-neutrality of the
registry is PROVEN rather than asserted, and it is the only concrete adapter
W0-06A ships.

It is also the only way to test the failure modes FLOW-016 cares about, since
none of them can be produced on demand against a real provider:

* :meth:`FakeStorageProvider.simulate_external_mutation` — somebody edits the
  file in Drive. The bytes change, BEG_Work was not told, and the next check
  must report a checksum mismatch rather than quietly accept a new version.
* :meth:`FakeStorageProvider.simulate_external_delete` — the original is gone
  while the preview is still cached.
* :meth:`FakeStorageProvider.simulate_permission_loss` — the provider is up and
  the object is there, but the account lost its rights. This must NOT look like
  a missing file.
* :meth:`FakeStorageProvider.simulate_outage` — the provider cannot be reached
  at all, which is again a different state.
* :attr:`FakeStorageProvider.fail_next_put` — a put that fails after the caller
  believed it succeeded, so retry/idempotency can be exercised.

Keeping the fake honest. Its storage is keyed by ``(container, object_key)``
and it refuses to serve an object from another binding's container, so a test
that leaks across tenants fails here too instead of passing by accident.

Test-support code. Nothing in ``app/routes`` or ``app/services`` may construct
it; ``adapter_for`` cannot return it, and the W0-06A static guard rejects an
import of this module from the active runtime surface.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Tuple

from app.files.models import (
    AVAILABILITY_AVAILABLE,
    AVAILABILITY_CHECKSUM_MISMATCH,
    AVAILABILITY_MISSING,
    AVAILABILITY_PERMISSION_DENIED,
    AVAILABILITY_PROVIDER_UNREACHABLE,
    CHECKSUM_SHA256,
    DELETE_PROVIDER_CONFIRMED,
    DELETE_PROVIDER_FAILED,
    PROVIDER_FAKE_MEMORY,
)
from app.files.providers.base import (
    ACCESS_PURPOSES,
    DeleteReceipt,
    IntegrityVerdict,
    ProviderBinding,
    ProviderCapabilities,
    ProviderError,
    ProviderObjectMissing,
    ProviderObjectRef,
    ProviderObjectStat,
    ProviderPermissionDenied,
    StorageProviderAdapter,
    TemporaryAccessGrant,
    expiry_for,
)


def sha256_of(data: bytes) -> Dict[str, str]:
    """The checksum form the registry stores, for bytes in hand."""
    return {"algorithm": CHECKSUM_SHA256, "value": hashlib.sha256(data).hexdigest()}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FakeStorageProvider(StorageProviderAdapter):
    """A complete, in-memory implementation of the provider contract."""

    provider_kind = PROVIDER_FAKE_MEMORY

    def __init__(self, binding: ProviderBinding, *, capabilities: Optional[ProviderCapabilities] = None):
        super().__init__(binding)
        self._objects: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._denied: set = set()
        self._capabilities = capabilities or ProviderCapabilities(
            provider_kind=PROVIDER_FAKE_MEMORY, can_put=True, can_read=True, can_stat=True,
            can_delete=True, server_side_checksum=True, native_file_ids=True,
            temporary_links=True, versioning=False)
        #: Flip to make the NEXT put raise. Lets a caller exercise the retry
        #: path without the registry ever learning this is a double.
        self.fail_next_put = False
        #: Flip to make every call report the provider as unreachable.
        self.offline = False
        #: Every call, in order — the contract tests assert the registry does
        #: not read bytes when it only needed a stat, and does not touch the
        #: provider at all on an idempotent replay.
        self.calls: list = []

    # ------------------------------------------------------------- helpers
    def _key(self, ref: ProviderObjectRef) -> Tuple[str, str]:
        if ref.container != self.binding.container:
            # A binding reaches ONE container. Serving another one would hide
            # exactly the cross-tenant mistake these tests exist to catch.
            raise ProviderPermissionDenied(
                "binding %s cannot reach container %r" % (self.binding.binding_id, ref.container),
                code="WRONG_CONTAINER")
        return (ref.container, ref.object_key)

    def _guard(self, key: Tuple[str, str]) -> None:
        if self.offline:
            raise ProviderError("provider unreachable", code="OFFLINE")
        if key in self._denied:
            raise ProviderPermissionDenied("no rights on %r" % (key[1],), code="FORBIDDEN")

    # ---------------------------------------------------------- capability
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    # -------------------------------------------------------------- object
    async def put(self, *, object_key: str, data: bytes, mime_type: str,
                  metadata: Optional[Mapping[str, Any]] = None) -> ProviderObjectRef:
        self.calls.append(("put", object_key))
        if self.offline:
            raise ProviderError("provider unreachable", code="OFFLINE")
        if self.fail_next_put:
            self.fail_next_put = False
            raise ProviderError("write failed", code="PUT_FAILED")
        key = (self.binding.container, object_key)
        self._objects[key] = {
            "data": bytes(data),
            "mime_type": mime_type,
            "metadata": dict(metadata or {}),
            "provider_file_id": "fakeobj_" + uuid.uuid4().hex,
            "modified_at": _now_iso(),
        }
        return ProviderObjectRef(container=self.binding.container, object_key=object_key,
                                 provider_file_id=self._objects[key]["provider_file_id"])

    async def read(self, ref: ProviderObjectRef) -> bytes:
        self.calls.append(("read", ref.object_key))
        key = self._key(ref)
        self._guard(key)
        if key not in self._objects:
            raise ProviderObjectMissing("no object at %r" % (ref.object_key,), code="NOT_FOUND")
        return self._objects[key]["data"]

    async def stat(self, ref: ProviderObjectRef) -> ProviderObjectStat:
        self.calls.append(("stat", ref.object_key))
        key = self._key(ref)
        self._guard(key)
        obj = self._objects.get(key)
        if obj is None:
            return ProviderObjectStat(exists=False)
        return ProviderObjectStat(
            exists=True, size_bytes=len(obj["data"]), checksum=sha256_of(obj["data"]),
            modified_at=obj["modified_at"], provider_version_id=obj["provider_file_id"])

    async def verify(self, ref: ProviderObjectRef,
                     expected: Optional[Mapping[str, str]] = None) -> IntegrityVerdict:
        """Report what is there now against what BEG_Work expected.

        Never raises for a business-visible failure: a missing object, a lost
        permission and an outage are all legitimate OUTCOMES of a check, and
        swallowing them into an exception would make the scheduler that runs
        these checks lose the distinction FLOW-016 requires.
        """
        self.calls.append(("verify", ref.object_key))
        checked = _now_iso()
        try:
            stat = await self.stat(ref)
        except ProviderPermissionDenied as exc:
            return IntegrityVerdict(availability=AVAILABILITY_PERMISSION_DENIED,
                                    expected_checksum=dict(expected) if expected else None,
                                    checked_at=checked, error=str(exc))
        except ProviderError as exc:
            return IntegrityVerdict(availability=exc.availability,
                                    expected_checksum=dict(expected) if expected else None,
                                    checked_at=checked, error=str(exc))
        if not stat.exists:
            return IntegrityVerdict(availability=AVAILABILITY_MISSING,
                                    expected_checksum=dict(expected) if expected else None,
                                    checked_at=checked, error="object not found")
        observed = stat.checksum
        if expected and observed and observed.get("value") != expected.get("value"):
            return IntegrityVerdict(availability=AVAILABILITY_CHECKSUM_MISMATCH,
                                    expected_checksum=dict(expected), observed_checksum=observed,
                                    observed_size_bytes=stat.size_bytes, checked_at=checked,
                                    error="checksum mismatch")
        return IntegrityVerdict(availability=AVAILABILITY_AVAILABLE,
                                expected_checksum=dict(expected) if expected else None,
                                observed_checksum=observed, observed_size_bytes=stat.size_bytes,
                                checked_at=checked)

    async def request_delete(self, ref: ProviderObjectRef, *, reason: str) -> DeleteReceipt:
        self.calls.append(("request_delete", ref.object_key))
        key = self._key(ref)
        try:
            self._guard(key)
        except ProviderError as exc:
            return DeleteReceipt(state=DELETE_PROVIDER_FAILED, provider_kind=self.provider_kind,
                                 response_code=exc.code, message=str(exc))
        if key not in self._objects:
            # Nothing to destroy is not a confirmed destruction: the registry
            # must not record that it removed a customer original it never saw.
            return DeleteReceipt(state=DELETE_PROVIDER_FAILED, provider_kind=self.provider_kind,
                                 response_code="NOT_FOUND", message="no object at this location")
        del self._objects[key]
        return DeleteReceipt(state=DELETE_PROVIDER_CONFIRMED, provider_kind=self.provider_kind,
                             response_code="OK", message=reason, confirmed_at=_now_iso())

    async def temporary_access(self, ref: ProviderObjectRef, *, purpose: str,
                               seconds: int = 300) -> TemporaryAccessGrant:
        self.calls.append(("temporary_access", ref.object_key))
        if purpose not in ACCESS_PURPOSES:
            raise ValueError("unknown access purpose %r" % purpose)
        key = self._key(ref)
        self._guard(key)
        return TemporaryAccessGrant(purpose=purpose, expires_at=expiry_for(seconds),
                                    token="fake_" + uuid.uuid4().hex,
                                    container=ref.container, object_key=ref.object_key)

    # ---------------------------------------------------- failure injection
    def simulate_external_mutation(self, ref: ProviderObjectRef, data: bytes) -> None:
        """Somebody changed the file outside BEG_Work."""
        key = (ref.container, ref.object_key)
        if key not in self._objects:
            raise KeyError(ref.object_key)
        self._objects[key]["data"] = bytes(data)
        self._objects[key]["modified_at"] = _now_iso()

    def simulate_external_delete(self, ref: ProviderObjectRef) -> None:
        """The customer original disappeared from the provider."""
        self._objects.pop((ref.container, ref.object_key), None)

    def simulate_permission_loss(self, ref: ProviderObjectRef) -> None:
        """The object is still there; this account may no longer read it."""
        self._denied.add((ref.container, ref.object_key))

    def simulate_permission_restored(self, ref: ProviderObjectRef) -> None:
        self._denied.discard((ref.container, ref.object_key))

    def simulate_outage(self, offline: bool = True) -> None:
        self.offline = offline

    def object_count(self) -> int:
        return len(self._objects)
