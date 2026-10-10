"""
W0-06A — the storage provider adapter CONTRACT.

FLOW-016 makes the customer's storage the home of the originals: every tenant
connects its own Google Drive / Shared Drive, Synology NAS, S3-compatible
bucket or on-prem server, and BEG_Work keeps only the registry, the metadata,
the checksums and a technical cache. This module is the one interface those
adapters implement, so that no module above it ever learns which provider a
tenant uses.

W0-06A shipped the CONTRACT; W0-06B implements it for the four
customer-managed kinds — :mod:`.s3` (S3-compatible), :mod:`.google_drive`
(Google Drive / Shared Drive), :mod:`.synology` (Synology / NAS, File Station
API) and :mod:`.on_prem` (a generic customer server over WebDAV). Every adapter
speaks to its provider through an injected HTTP transport, so this task runs
them only against disposable in-process fakes (``tests/w0_06b_fake_backends.py``)
with fake credentials: no live NAS, Drive or bucket is touched. An adapter is
built only from a binding plus the credentials the server-side vault resolved
for it (:func:`adapter_for`); whether a tenant may USE it for real files is the
onboarding gate's decision (:mod:`app.files.storage`), not the adapter's.

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

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple

from app.files.models import (
    AVAILABILITY_AVAILABLE,
    AVAILABILITY_CHECKSUM_MISMATCH,
    AVAILABILITY_EXTERNALLY_CHANGED,
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
    #: W0-06B. The provider's address (S3 endpoint, NAS / server base URL) and
    #: the account the credentials belong to. Neither is secret; both are part
    #: of the provider/account identity FLOW-016 asks BEG_Work to keep.
    endpoint: str = ""
    account: str = ""

    def __post_init__(self):
        if self.provider_kind not in PROVIDER_KINDS:
            raise ValueError("unknown provider kind %r" % self.provider_kind)
        for name in ("binding_id", "org_id", "container"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError("%s is required on a provider binding" % name)
        normalize_root(self.root_prefix)

    @property
    def root(self) -> str:
        """The tenant-specific root inside the container, normalized (no slashes at the ends)."""
        return normalize_root(self.root_prefix)

    def object_path(self, object_key: str) -> str:
        """``root/object_key`` — the provider-side path of one object. Validated."""
        key = safe_object_key(object_key)
        return "%s/%s" % (self.root, key) if self.root else key


def _bad_segment(segment: str) -> bool:
    return (segment in ("", ".", "..") or "\\" in segment
            or any(ord(c) < 32 or ord(c) == 127 for c in segment))


def normalize_root(root: str) -> str:
    """A root prefix with no traversal, no backslash and no control character."""
    if root is None:
        return ""
    if not isinstance(root, str):
        raise ValueError("root_prefix must be text")
    stripped = root.strip().strip("/")
    if not stripped:
        return ""
    if any(_bad_segment(part) for part in stripped.split("/")):
        raise ValueError("unsafe root_prefix %r" % root)
    return stripped


def safe_object_key(object_key: str) -> str:
    """An object key that cannot escape the tenant root.

    Refuses an absolute key, ``..``/``.`` segments, empty segments, backslashes
    and control characters — the shapes a key would need to reach another
    tenant's root on a shared NAS or server.
    """
    if not isinstance(object_key, str) or not object_key or object_key.startswith("/"):
        raise ValueError("unsafe object key %r" % (object_key,))
    if any(_bad_segment(part) for part in object_key.split("/")):
        raise ValueError("unsafe object key %r" % (object_key,))
    return object_key


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
    #: W0-06B. The provider's own id of the object found at the location, when
    #: it has one (Drive file id, NAS/WebDAV etag-less paths have none).
    provider_file_id: Optional[str] = None


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
    #: W0-06B. How the content was judged — ``server_checksum`` (the provider
    #: reported a sha256), ``read_and_hash`` (BEG_Work read the bytes and hashed
    #: them) or ``none`` (nothing could be compared) — and what the provider
    #: says the object IS now, so an object replaced behind BEG_Work's back is
    #: told apart from one whose bytes changed.
    method: str = "none"
    observed_provider_file_id: Optional[str] = None
    observed_provider_version_id: Optional[str] = None

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


VERIFY_SERVER_CHECKSUM = "server_checksum"
VERIFY_READ_AND_HASH = "read_and_hash"
VERIFY_SIZE_ONLY = "size_only"
VERIFY_NONE = "none"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_checksum(data: bytes) -> Dict[str, str]:
    """The checksum form the registry stores, for bytes in hand."""
    return {"algorithm": "sha256", "value": sha256_hex(data)}


class _Credentials:
    """Server-side credential values. Never printed, never serialized.

    ``repr``/``str`` are masked so an exception, a log line or a debugger dump
    of an adapter cannot reveal a secret (CLAUDE.md §16).
    """

    __slots__ = ("_values",)

    def __init__(self, values: Optional[Mapping[str, Any]]):
        self._values = dict(values or {})

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def require(self, *keys: str) -> Tuple[Any, ...]:
        missing = [k for k in keys if not self._values.get(k)]
        if missing:
            raise ProviderCredentialsInvalid("credentials incomplete: missing %s" % missing)
        return tuple(self._values[k] for k in keys)

    def __bool__(self) -> bool:
        return bool(self._values)

    def __repr__(self) -> str:
        return "<credentials ***MASKED***>"

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError("credentials cannot be serialized")


class ProviderCredentialsInvalid(ProviderPermissionDenied):
    """The provider rejected the credentials (or they are incomplete)."""

    def __init__(self, message: str, *, code: Optional[str] = "INVALID_CREDENTIALS"):
        super().__init__(message, code=code)


class StorageProviderAdapter:
    """The interface every storage provider adapter implements.

    Subclasses override the operations; the base raises
    :class:`NotImplementedError` so a half-written adapter fails loudly instead
    of appearing to work. Every method is async because every real provider is
    a network call.

    W0-06B additions. An adapter is built from a binding, the credentials the
    server-side vault resolved for THAT binding, and an HTTP transport (tests
    inject an in-process fake; nothing in this task reaches a real provider).
    :meth:`validate_credentials` and :meth:`check_root` are the first two
    onboarding steps; :meth:`verify` is shared, so every adapter tells the five
    FLOW-016 failure states apart the same way.
    """

    provider_kind: str = ""

    def __init__(self, binding: ProviderBinding, *, credentials: Optional[Mapping[str, Any]] = None,
                 transport: Any = None):
        if not isinstance(binding, ProviderBinding):
            raise TypeError("an adapter is constructed from a ProviderBinding")
        if self.provider_kind and binding.provider_kind != self.provider_kind:
            raise ValueError("binding is for %r, adapter is %r"
                             % (binding.provider_kind, self.provider_kind))
        self.binding = binding
        self._credentials = _Credentials(credentials)
        self._transport = transport

    def __repr__(self) -> str:
        return "<%s binding=%s>" % (type(self).__name__, self.binding.binding_id)

    # ------------------------------------------------------------ capability
    def capabilities(self) -> ProviderCapabilities:
        raise NotImplementedError

    # ------------------------------------------------------------ onboarding
    async def validate_credentials(self) -> None:
        """Prove the credentials work. Raises :class:`ProviderCredentialsInvalid`."""
        raise NotImplementedError

    async def check_root(self) -> None:
        """Prove the tenant root exists and is writable for this account."""
        raise NotImplementedError

    async def aclose(self) -> None:
        """Release a provider session (logout), if the provider has one."""
        return None

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
                     expected: Optional[Mapping[str, str]] = None, *,
                     expected_size: Optional[int] = None,
                     expected_provider_file_id: Optional[str] = None,
                     expected_provider_version_id: Optional[str] = None) -> IntegrityVerdict:
        """Compare what is stored with what BEG_Work expects.

        Reports, never heals. The order is what keeps the states distinct:

        1. ``stat`` — a permission failure, an outage and an absent object are
           three different answers, never one;
        2. content — the provider's own sha256 when it has one, otherwise the
           bytes are READ and hashed (a weaker but still exact check), and a
           size difference alone already proves the content changed;
        3. identity — the same bytes under another provider id / version is an
           object replaced outside BEG_Work (``externally_changed``).

        A business-visible failure is a returned verdict, never an exception:
        the caller that runs checks must not lose the distinction.
        """
        checked = _utc_now().isoformat()
        exp = dict(expected) if expected else None

        def verdict(availability, **kw):
            return IntegrityVerdict(availability=availability, expected_checksum=exp,
                                    checked_at=checked, **kw)
        try:
            stat = await self.stat(ref)
        except ProviderPermissionDenied as exc:
            return verdict(AVAILABILITY_PERMISSION_DENIED, error=_safe_error(exc))
        except ProviderError as exc:
            return verdict(exc.availability, error=_safe_error(exc))
        if not stat.exists:
            return verdict(AVAILABILITY_MISSING, error="object not found")
        ids = dict(observed_provider_file_id=stat.provider_file_id,
                   observed_provider_version_id=stat.provider_version_id)
        if expected_size is not None and stat.size_bytes is not None \
                and stat.size_bytes != expected_size:
            return verdict(AVAILABILITY_CHECKSUM_MISMATCH, observed_size_bytes=stat.size_bytes,
                           method=VERIFY_SIZE_ONLY, error="size mismatch", **ids)
        observed, method = None, VERIFY_NONE
        if stat.checksum and (not exp or stat.checksum.get("algorithm") == exp.get("algorithm")):
            observed, method = stat.checksum, VERIFY_SERVER_CHECKSUM
        elif exp and self.capabilities().can_read:
            try:
                data = await self.read(ref)
            except ProviderPermissionDenied as exc:
                return verdict(AVAILABILITY_PERMISSION_DENIED, error=_safe_error(exc), **ids)
            except ProviderObjectMissing as exc:
                return verdict(AVAILABILITY_MISSING, error=_safe_error(exc), **ids)
            except ProviderError as exc:
                return verdict(exc.availability, error=_safe_error(exc), **ids)
            observed, method = sha256_checksum(data), VERIFY_READ_AND_HASH
        if exp and observed and observed.get("value") != exp.get("value"):
            return verdict(AVAILABILITY_CHECKSUM_MISMATCH, observed_checksum=observed,
                           observed_size_bytes=stat.size_bytes, method=method,
                           error="checksum mismatch", **ids)
        replaced = ((expected_provider_file_id and stat.provider_file_id
                     and stat.provider_file_id != expected_provider_file_id)
                    or (expected_provider_version_id and stat.provider_version_id
                        and stat.provider_version_id != expected_provider_version_id))
        if replaced:
            return verdict(AVAILABILITY_EXTERNALLY_CHANGED, observed_checksum=observed,
                           observed_size_bytes=stat.size_bytes, method=method,
                           error="object replaced outside BEG_Work", **ids)
        return verdict(AVAILABILITY_AVAILABLE, observed_checksum=observed,
                       observed_size_bytes=stat.size_bytes, method=method, **ids)

    async def request_delete(self, ref: ProviderObjectRef, *, reason: str) -> DeleteReceipt:
        """Ask the provider to destroy the object and report what it answered."""
        raise NotImplementedError

    async def temporary_access(self, ref: ProviderObjectRef, *, purpose: str,
                               seconds: int = 300) -> TemporaryAccessGrant:
        """A short-lived grant for one purpose. Never a permanent URL.

        An adapter whose provider cannot issue a time-limited link reports
        ``temporary_links=False`` and raises :class:`ProviderError`; access is
        then served through a BEG_Work grant (:mod:`app.files.access`).
        """
        raise NotImplementedError

    # --------------------------------------------------------- shared helpers
    async def _confirm_gone(self, ref: ProviderObjectRef, reason: str) -> DeleteReceipt:
        """CONFIRMED only when a fresh ``stat`` says the object is absent."""
        try:
            after = await self.stat(ref)
        except ProviderError as exc:
            return DeleteReceipt(state=DELETE_PROVIDER_FAILED, provider_kind=self.provider_kind,
                                 response_code=exc.code or "UNVERIFIED",
                                 message="delete sent but absence could not be verified")
        if after.exists:
            return DeleteReceipt(state=DELETE_PROVIDER_FAILED, provider_kind=self.provider_kind,
                                 response_code="STILL_PRESENT",
                                 message="provider accepted the delete but the object remains")
        return DeleteReceipt(state=DELETE_PROVIDER_CONFIRMED, provider_kind=self.provider_kind,
                             response_code="OK", message=reason,
                             confirmed_at=_utc_now().isoformat())


def _safe_error(exc: BaseException) -> str:
    """An error text safe to store: the class and code, never a URL or a header."""
    code = getattr(exc, "code", None)
    return "%s%s" % (type(exc).__name__, (" [%s]" % code) if code else "")


#: provider kind -> "module:Class" of its adapter. Resolved lazily so this
#: contract module stays stdlib-only and importable by the static guard.
ADAPTER_CLASSES: Dict[str, str] = {
    PROVIDER_GOOGLE_DRIVE: "app.files.providers.google_drive:GoogleDriveAdapter",
    PROVIDER_SYNOLOGY_NAS: "app.files.providers.synology:SynologyNasAdapter",
    PROVIDER_S3_COMPATIBLE: "app.files.providers.s3:S3CompatibleAdapter",
    PROVIDER_ON_PREM_SERVER: "app.files.providers.on_prem:OnPremServerAdapter",
}

assert set(ADAPTER_CLASSES) == set(CUSTOMER_MANAGED_PROVIDER_KINDS)


def adapter_class(provider_kind: str) -> type:
    """The adapter class of a customer-managed provider kind."""
    try:
        target = ADAPTER_CLASSES[provider_kind]
    except KeyError:
        raise ProviderNotActivated(provider_kind) from None
    module_name, _, cls_name = target.partition(":")
    import importlib
    return getattr(importlib.import_module(module_name), cls_name)


def adapter_for(binding: ProviderBinding, *, credentials: Optional[Mapping[str, Any]] = None,
                transport: Any = None) -> StorageProviderAdapter:
    """The adapter for a binding, with its server-resolved credentials.

    Only the customer-managed kinds resolve here. The in-memory double is
    constructed directly by the tests that need it, so no production path can
    reach a fake provider by configuration. Without credentials there is no
    adapter at all: a provider is never contacted anonymously.
    """
    cls = adapter_class(binding.provider_kind)
    if not credentials:
        raise ProviderCredentialsInvalid("no credentials resolved for binding %s"
                                         % binding.binding_id, code="NO_CREDENTIALS")
    return cls(binding, credentials=credentials, transport=transport)
