"""
W0-06A — the storage provider adapter CONTRACT.

FLOW-016 makes the customer's storage the home of the originals: every tenant
connects its own Google Drive / Shared Drive, Synology NAS, S3-compatible
bucket or on-prem server, and BEG_Work keeps only the registry, the metadata,
the checksums and a technical cache. This module is the one interface those
adapters implement, so that no module above it ever learns which provider a
tenant uses.

W0-06A implements the CONTRACT ONLY. No adapter here opens a network
connection, reads a credential or touches a customer file; the four
customer-managed kinds are declared and deliberately unimplemented, and the
only concrete adapter in the tree is the in-memory double
(:mod:`app.files.providers.fake`) the contract tests run against. Provider
onboarding, credential storage and the live integrity scheduler are later
slices of FLOW-016, not this one.

What the contract has to guarantee
----------------------------------

*Capability reporting.* Providers differ in what they can do — Google Drive
has its own file ids and can be asked for a checksum, a plain SMB share can
offer neither. An adapter therefore DECLARES what it supports
(:class:`ProviderCapabilities`) and the registry adapts instead of assuming.
A capability a provider lacks is a known state, never a silent failure.

*No permanent URL as an access right.* :meth:`StorageProviderAdapter.temporary_access`
returns a short-lived, single-purpose grant with an explicit expiry. There is
no ``public_url`` anywhere in this interface: FLOW-016 forbids a permanent
public URL from acting as a permission, and the FLOW-002 check happens above
this layer on every call. An adapter that cannot issue a time-limited grant
must report the capability as absent rather than hand back a durable link.

*Credentials never leave the server.* An adapter is constructed from a
:class:`ProviderBinding`, which names the tenant's configured account and the
*reference* to its encrypted secret. The secret value is not a field of the
binding, is never logged, and is never part of a result the browser can see.

*A delete is a request with an answer.* :meth:`StorageProviderAdapter.request_delete`
returns a :class:`DeleteReceipt` that says what the provider actually did.
BEG_Work never reports a customer original as destroyed on its own authority.

*An externally mutated object is an integrity problem.*
:meth:`StorageProviderAdapter.verify` compares the expected checksum with what
the provider holds now and returns a verdict; turning that into a new version
would silently accept a change nobody in BEG_Work made, which FLOW-016
forbids. Interpreting the verdict is the registry's job, not the adapter's.

Stdlib-only: no database, no FastAPI, no network client.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple

from app.files.models import (
    AVAILABILITY_AVAILABLE,
    AVAILABILITY_CHECKSUM_MISMATCH,
    AVAILABILITY_MISSING,
    AVAILABILITY_PERMISSION_DENIED,
    AVAILABILITY_PROVIDER_UNREACHABLE,
    CUSTOMER_MANAGED_PROVIDER_KINDS,
    DELETE_PROVIDER_CONFIRMED,
    DELETE_PROVIDER_FAILED,
    DELETE_PROVIDER_REFUSED,
    DELETE_STATES,
    PROVIDER_GOOGLE_DRIVE,
    PROVIDER_KINDS,
    PROVIDER_ON_PREM_SERVER,
    PROVIDER_S3_COMPATIBLE,
    PROVIDER_SYNOLOGY_NAS,
)

#: The longest life a temporary access grant may be given. FLOW-016 asks for
#: "краткотрайни защитени links"; a cap in the contract means no adapter can
#: quietly issue a week-long URL that becomes a de-facto permanent one.
MAX_TEMPORARY_ACCESS_SECONDS = 15 * 60

ACCESS_READ = "read"
ACCESS_WRITE = "write"
ACCESS_PREVIEW = "preview"
ACCESS_PURPOSES: FrozenSet[str] = frozenset({ACCESS_READ, ACCESS_WRITE, ACCESS_PREVIEW})


class ProviderError(RuntimeError):
    """The provider could not answer. Carries the availability state it implies."""

    def __init__(self, message: str, *, availability: str = AVAILABILITY_PROVIDER_UNREACHABLE,
                 code: Optional[str] = None):
        super().__init__(message)
        self.availability = availability
        self.code = code


class ProviderPermissionDenied(ProviderError):
    """The provider refused for lack of rights.

    A distinct class because FLOW-016 requires a permission failure to be
    distinguishable from a physically missing file: the first is a
    configuration incident the tenant can fix, the second means an original is
    gone, and treating them alike hides whichever one is real.
    """

    def __init__(self, message: str, *, code: Optional[str] = None):
        super().__init__(message, availability=AVAILABILITY_PERMISSION_DENIED, code=code)


class ProviderObjectMissing(ProviderError):
    """The provider has no object at this location."""

    def __init__(self, message: str, *, code: Optional[str] = None):
        super().__init__(message, availability=AVAILABILITY_MISSING, code=code)


class ProviderNotActivated(ProviderError):
    """A declared but unimplemented adapter was used.

    W0-06A ships the contract, not the integrations. Raising this — instead of
    returning something plausible — is what keeps "no live provider activation"
    true in code rather than only in the assignment text.
    """

    def __init__(self, provider_kind: str):
        super().__init__(
            "provider %r is declared for a later FLOW-016 slice and is not "
            "activated in W0-06A" % provider_kind,
            availability=AVAILABILITY_PROVIDER_UNREACHABLE, code="NOT_ACTIVATED")
        self.provider_kind = provider_kind


@dataclass(frozen=True)
class ProviderBinding:
    """A tenant's configured provider account — WITHOUT its secret.

    ``secret_reference`` names where the encrypted credential is held; the value
    is resolved, if ever, by the provider-onboarding slice on the server. Keeping
    it a reference means this object can be logged, audited and returned from a
    service without leaking anything (CLAUDE.md §16: no secrets in logs or
    frontend).
    """
    binding_id: str
    org_id: str
    provider_kind: str
    container: str
    secret_reference: Optional[str] = None
    root_prefix: str = ""

    def __post_init__(self):
        if self.provider_kind not in PROVIDER_KINDS:
            raise ValueError("unknown provider kind %r" % self.provider_kind)
        for name in ("binding_id", "org_id", "container"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError("%s is required on a provider binding" % name)


@dataclass(frozen=True)
class ProviderCapabilities:
    """What this provider can actually do.

    Declared per adapter so the registry can degrade knowingly: a provider
    without ``server_side_checksum`` means an integrity check must compare sizes
    and re-read bytes, which is a different (weaker) guarantee — and one the
    Health Dashboard should be able to state rather than imply.
    """
    provider_kind: str
    can_put: bool = True
    can_read: bool = True
    can_stat: bool = True
    can_delete: bool = False
    server_side_checksum: bool = False
    native_file_ids: bool = False
    temporary_links: bool = False
    versioning: bool = False
    max_object_bytes: Optional[int] = None

    def as_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class ProviderObjectRef:
    """Where a stored object is, in the provider's own coordinates.

    Never a business identifier: nothing resolves a file by these fields. The
    registry stores them on a ProviderLocation beside the ``file_id`` that IS
    the identity.
    """
    container: str
    object_key: str
    provider_file_id: Optional[str] = None
    provider_version_id: Optional[str] = None


@dataclass(frozen=True)
class ProviderObjectStat:
    """What the provider says about an object right now."""
    exists: bool
    size_bytes: Optional[int] = None
    checksum: Optional[Dict[str, str]] = None
    modified_at: Optional[str] = None
    provider_version_id: Optional[str] = None


@dataclass(frozen=True)
class IntegrityVerdict:
    """The outcome of one availability/integrity check.

    ``availability`` is one of ``app.files.models.AVAILABILITY_*`` so the result
    drops straight onto the ProviderLocation. The adapter reports; it never
    decides to create a version, raise an alarm or heal anything.
    """
    availability: str
    expected_checksum: Optional[Dict[str, str]] = None
    observed_checksum: Optional[Dict[str, str]] = None
    observed_size_bytes: Optional[int] = None
    checked_at: str = ""
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.availability == AVAILABILITY_AVAILABLE


@dataclass(frozen=True)
class DeleteReceipt:
    """The provider's own answer to a delete request.

    ``state`` is one of ``app.files.models.DELETE_*``. There is no default
    "confirmed": an adapter that cannot prove the object is gone reports
    ``provider_failed``, because FLOW-016 forbids BEG_Work from presenting a
    deletion it did not observe.
    """
    state: str
    provider_kind: str
    response_code: Optional[str] = None
    message: Optional[str] = None
    confirmed_at: Optional[str] = None

    def __post_init__(self):
        if self.state not in DELETE_STATES or self.state not in (
                DELETE_PROVIDER_CONFIRMED, DELETE_PROVIDER_REFUSED, DELETE_PROVIDER_FAILED):
            raise ValueError("a delete receipt must carry a provider answer, got %r" % self.state)


@dataclass(frozen=True)
class TemporaryAccessGrant:
    """A short-lived, single-purpose grant. Never a durable public URL."""
    purpose: str
    expires_at: str
    token: str
    container: str
    object_key: str
    #: Set only by adapters whose provider issues its own pre-signed link. It is
    #: still time-limited by ``expires_at`` and still subject to the FLOW-002
    #: check that happened before this grant was minted.
    provider_url: Optional[str] = None

    def __post_init__(self):
        if self.purpose not in ACCESS_PURPOSES:
            raise ValueError("unknown access purpose %r" % self.purpose)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def expiry_for(seconds: int) -> str:
    """An ISO expiry ``seconds`` from now, capped by :data:`MAX_TEMPORARY_ACCESS_SECONDS`."""
    if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds <= 0:
        raise ValueError("a temporary grant needs a positive lifetime")
    if seconds > MAX_TEMPORARY_ACCESS_SECONDS:
        raise ValueError("a temporary grant may not live longer than %d seconds"
                         % MAX_TEMPORARY_ACCESS_SECONDS)
    return (_utc_now() + timedelta(seconds=seconds)).isoformat()


class StorageProviderAdapter:
    """The interface every storage provider adapter implements.

    Subclasses override the operations; the base raises
    :class:`NotImplementedError` so a half-written adapter fails loudly instead
    of appearing to work. Every method is async because every real provider is
    a network call.
    """

    provider_kind: str = ""

    def __init__(self, binding: ProviderBinding):
        if not isinstance(binding, ProviderBinding):
            raise TypeError("an adapter is constructed from a ProviderBinding")
        if self.provider_kind and binding.provider_kind != self.provider_kind:
            raise ValueError("binding is for %r, adapter is %r"
                             % (binding.provider_kind, self.provider_kind))
        self.binding = binding

    # ------------------------------------------------------------ capability
    def capabilities(self) -> ProviderCapabilities:
        raise NotImplementedError

    # ---------------------------------------------------------------- object
    async def put(self, *, object_key: str, data: bytes,
                  mime_type: str, metadata: Optional[Mapping[str, Any]] = None
                  ) -> ProviderObjectRef:
        """Store bytes and return the provider's coordinates for them."""
        raise NotImplementedError

    async def read(self, ref: ProviderObjectRef) -> bytes:
        """The object's bytes. Raises :class:`ProviderObjectMissing` when absent."""
        raise NotImplementedError

    async def stat(self, ref: ProviderObjectRef) -> ProviderObjectStat:
        """Existence, size and (where supported) checksum, without reading bytes."""
        raise NotImplementedError

    async def verify(self, ref: ProviderObjectRef,
                     expected: Optional[Mapping[str, str]] = None) -> IntegrityVerdict:
        """Compare what is stored with what BEG_Work expects.

        Reports, never heals: a mismatch comes back as
        ``AVAILABILITY_CHECKSUM_MISMATCH`` for the registry to raise as an
        integrity problem.
        """
        raise NotImplementedError

    async def request_delete(self, ref: ProviderObjectRef, *, reason: str) -> DeleteReceipt:
        """Ask the provider to destroy the object and report what it answered."""
        raise NotImplementedError

    async def temporary_access(self, ref: ProviderObjectRef, *, purpose: str,
                               seconds: int = 300) -> TemporaryAccessGrant:
        """A short-lived grant for one purpose. Never a permanent URL."""
        raise NotImplementedError


class DeclaredAdapter(StorageProviderAdapter):
    """A customer-managed provider that W0-06A declares but does NOT activate.

    It exists so the contract names the four providers FLOW-016 requires, and
    so the registry, the tests and the Health Dashboard can already speak about
    them — while every operation raises :class:`ProviderNotActivated`. That is
    the difference between "the contract covers Google Drive" and "we move
    customer files to Google Drive", and W0-06A is only the first.
    """

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(provider_kind=self.provider_kind, can_put=False,
                                    can_read=False, can_stat=False)

    async def put(self, **kwargs):           # noqa: D102
        raise ProviderNotActivated(self.provider_kind)

    async def read(self, ref):               # noqa: D102
        raise ProviderNotActivated(self.provider_kind)

    async def stat(self, ref):               # noqa: D102
        raise ProviderNotActivated(self.provider_kind)

    async def verify(self, ref, expected=None):   # noqa: D102
        raise ProviderNotActivated(self.provider_kind)

    async def request_delete(self, ref, *, reason):  # noqa: D102
        raise ProviderNotActivated(self.provider_kind)

    async def temporary_access(self, ref, *, purpose, seconds=300):  # noqa: D102
        raise ProviderNotActivated(self.provider_kind)


class GoogleDriveAdapter(DeclaredAdapter):
    """Google Drive / Shared Drive. Declared; activated in a later slice."""
    provider_kind = PROVIDER_GOOGLE_DRIVE


class SynologyNasAdapter(DeclaredAdapter):
    """Synology / NAS. Declared; activated in a later slice."""
    provider_kind = PROVIDER_SYNOLOGY_NAS


class S3CompatibleAdapter(DeclaredAdapter):
    """S3-compatible object storage. Declared; activated in a later slice."""
    provider_kind = PROVIDER_S3_COMPATIBLE


class OnPremServerAdapter(DeclaredAdapter):
    """A customer's own on-premise server. Declared; activated in a later slice."""
    provider_kind = PROVIDER_ON_PREM_SERVER


#: Every customer-managed provider kind FLOW-016 names, mapped to its adapter.
#: The test suite proves this covers :data:`CUSTOMER_MANAGED_PROVIDER_KINDS`
#: exactly, so a provider cannot be named in the model vocabulary without an
#: adapter class existing for it.
DECLARED_ADAPTERS: Dict[str, type] = {
    PROVIDER_GOOGLE_DRIVE: GoogleDriveAdapter,
    PROVIDER_SYNOLOGY_NAS: SynologyNasAdapter,
    PROVIDER_S3_COMPATIBLE: S3CompatibleAdapter,
    PROVIDER_ON_PREM_SERVER: OnPremServerAdapter,
}

assert set(DECLARED_ADAPTERS) == set(CUSTOMER_MANAGED_PROVIDER_KINDS)


def adapter_for(binding: ProviderBinding) -> StorageProviderAdapter:
    """The adapter for a binding.

    Only the declared customer-managed kinds resolve here. The in-memory double
    is constructed directly by the tests that need it, so no production path can
    reach a fake provider by configuration.
    """
    try:
        cls = DECLARED_ADAPTERS[binding.provider_kind]
    except KeyError:
        raise ProviderNotActivated(binding.provider_kind) from None
    return cls(binding)
