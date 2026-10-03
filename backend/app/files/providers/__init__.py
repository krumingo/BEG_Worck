"""
W0-06A — storage provider adapters.

:mod:`app.files.providers.base` is the contract every adapter implements;
:mod:`app.files.providers.fake` is the in-memory double the contract tests run
against and the only concrete implementation W0-06A ships. The four
customer-managed providers FLOW-016 names are DECLARED here and raise
``ProviderNotActivated``: W0-06A touches no credential, no NAS, no Drive and no
bucket.
"""
from app.files.providers.base import (
    ACCESS_PREVIEW,
    ACCESS_READ,
    ACCESS_WRITE,
    DECLARED_ADAPTERS,
    DeclaredAdapter,
    DeleteReceipt,
    GoogleDriveAdapter,
    IntegrityVerdict,
    MAX_TEMPORARY_ACCESS_SECONDS,
    OnPremServerAdapter,
    ProviderBinding,
    ProviderCapabilities,
    ProviderError,
    ProviderNotActivated,
    ProviderObjectMissing,
    ProviderObjectRef,
    ProviderObjectStat,
    ProviderPermissionDenied,
    S3CompatibleAdapter,
    StorageProviderAdapter,
    SynologyNasAdapter,
    TemporaryAccessGrant,
    adapter_for,
    expiry_for,
)

__all__ = [
    "ACCESS_PREVIEW", "ACCESS_READ", "ACCESS_WRITE", "DECLARED_ADAPTERS",
    "DeclaredAdapter", "DeleteReceipt", "GoogleDriveAdapter", "IntegrityVerdict",
    "MAX_TEMPORARY_ACCESS_SECONDS", "OnPremServerAdapter", "ProviderBinding",
    "ProviderCapabilities", "ProviderError", "ProviderNotActivated",
    "ProviderObjectMissing", "ProviderObjectRef", "ProviderObjectStat",
    "ProviderPermissionDenied", "S3CompatibleAdapter", "StorageProviderAdapter",
    "SynologyNasAdapter", "TemporaryAccessGrant", "adapter_for", "expiry_for",
]
