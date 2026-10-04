"""
W0-06A/W0-06B — storage provider adapters.

:mod:`app.files.providers.base` is the contract every adapter implements. The
four customer-managed providers FLOW-016 names are implemented in W0-06B —
:mod:`.s3`, :mod:`.google_drive`, :mod:`.synology` and :mod:`.on_prem` — each
over an injected HTTP transport, and are reached only through
:func:`~app.files.providers.base.adapter_for` with server-resolved credentials.
:mod:`app.files.providers.fake` is the in-memory double; configuration can never
select it.
"""
from app.files.providers.base import (
    ACCESS_PREVIEW,
    ACCESS_READ,
    ACCESS_WRITE,
    ADAPTER_CLASSES,
    DeleteReceipt,
    IntegrityVerdict,
    MAX_TEMPORARY_ACCESS_SECONDS,
    ProviderBinding,
    ProviderCapabilities,
    ProviderCredentialsInvalid,
    ProviderError,
    ProviderNotActivated,
    ProviderObjectMissing,
    ProviderObjectRef,
    ProviderObjectStat,
    ProviderPermissionDenied,
    StorageProviderAdapter,
    TemporaryAccessGrant,
    adapter_class,
    adapter_for,
    expiry_for,
    safe_object_key,
    sha256_checksum,
)

__all__ = [
    "ACCESS_PREVIEW", "ACCESS_READ", "ACCESS_WRITE", "ADAPTER_CLASSES",
    "DeleteReceipt", "IntegrityVerdict", "MAX_TEMPORARY_ACCESS_SECONDS",
    "ProviderBinding", "ProviderCapabilities", "ProviderCredentialsInvalid",
    "ProviderError", "ProviderNotActivated", "ProviderObjectMissing",
    "ProviderObjectRef", "ProviderObjectStat", "ProviderPermissionDenied",
    "StorageProviderAdapter", "TemporaryAccessGrant", "adapter_class", "adapter_for",
    "expiry_for", "safe_object_key", "sha256_checksum",
]
