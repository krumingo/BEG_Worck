"""
W0-06B — encrypted, tenant-specific storage provider credentials.

FLOW-016 §"Права и сигурност": tenant-specific credentials, encrypted secrets,
and no credential may reach another tenant. CLAUDE.md §16: no secret in Git,
logs, prompts or the frontend. This module is the only place a provider secret
exists in readable form, and only for the duration of one server-side call.

How a secret is kept
--------------------
* The installation holds ONE master key, outside the database and outside Git:
  the environment variable :data:`ENV_MASTER_KEY` (base64, >= 32 bytes). There
  is no default; without it the vault refuses to work (fail closed).
* Each tenant gets its OWN data key, derived from the master key with
  HKDF-SHA256 and the tenant id as context. A tenant's ciphertext is useless
  under another tenant's key.
* Each secret is sealed with AES-256-GCM. The authenticated data binds the
  ciphertext to ``tenant | binding | provider kind | reference``: a ciphertext
  copied onto another tenant's or another binding's row fails authentication
  instead of decrypting.
* The binding row stores only the REFERENCE (``cred_<uuid>``). Business
  records, AuditEvents, API views and logs never see the value; the stored row
  lists only the NAMES of the fields it holds.
* A replaced credential is superseded, never deleted (CLAUDE.md §2 rule 9).

Only fake/test credentials are ever stored in this task.
"""
from __future__ import annotations

import base64
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, FrozenSet, Mapping, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.files import models as m

CREDENTIALS_COLLECTION = "storage_credentials"
ENV_MASTER_KEY = "BEG_STORAGE_CREDENTIAL_KEY"
KEY_VERSION = "k1"
_HKDF_SALT = b"beg-work/storage-credentials/v1"
REFERENCE_PREFIX = "cred_"

#: The credential fields each provider kind accepts. Anything else is refused,
#: so the vault cannot become a place to stash arbitrary data.
ALLOWED_FIELDS: Dict[str, FrozenSet[str]] = {
    m.PROVIDER_S3_COMPATIBLE: frozenset({"access_key_id", "secret_access_key", "region"}),
    m.PROVIDER_GOOGLE_DRIVE: frozenset({"client_id", "client_secret", "refresh_token"}),
    m.PROVIDER_SYNOLOGY_NAS: frozenset({"password"}),
    m.PROVIDER_ON_PREM_SERVER: frozenset({"password", "token"}),
}
REQUIRED_FIELDS: Dict[str, FrozenSet[str]] = {
    m.PROVIDER_S3_COMPATIBLE: frozenset({"access_key_id", "secret_access_key"}),
    m.PROVIDER_GOOGLE_DRIVE: frozenset({"client_id", "client_secret", "refresh_token"}),
    m.PROVIDER_SYNOLOGY_NAS: frozenset({"password"}),
    m.PROVIDER_ON_PREM_SERVER: frozenset(),        # password OR token, checked below
}


class CredentialVaultUnavailable(RuntimeError):
    """No usable master key: the vault refuses to store or resolve anything."""


class CredentialRejected(ValueError):
    """The credential set is malformed for its provider kind."""


class CredentialReferenceInvalid(RuntimeError):
    """No such credential for THIS tenant and binding, or it failed authentication."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def master_key_from_environment() -> bytes:
    raw = os.environ.get(ENV_MASTER_KEY, "")
    if not raw:
        raise CredentialVaultUnavailable("%s is not configured" % ENV_MASTER_KEY)
    try:
        key = base64.b64decode(raw, validate=True)
    except (ValueError, TypeError):
        raise CredentialVaultUnavailable("%s is not valid base64" % ENV_MASTER_KEY) from None
    if len(key) < 32:
        raise CredentialVaultUnavailable("%s must hold at least 32 bytes" % ENV_MASTER_KEY)
    return key


def validate_secret(provider_kind: str, secret: Mapping[str, Any]) -> Dict[str, str]:
    if provider_kind not in ALLOWED_FIELDS:
        raise CredentialRejected("no credentials are kept for provider %r" % provider_kind)
    if not isinstance(secret, Mapping) or not secret:
        raise CredentialRejected("credentials are required")
    unknown = sorted(set(secret) - ALLOWED_FIELDS[provider_kind])
    if unknown:
        raise CredentialRejected("unknown credential field(s) %s" % unknown)
    clean: Dict[str, str] = {}
    for k, v in secret.items():
        if not isinstance(v, str) or not v.strip():
            raise CredentialRejected("credential field %r must be non-empty text" % k)
        clean[k] = v
    missing = sorted(REQUIRED_FIELDS[provider_kind] - set(clean))
    if missing:
        raise CredentialRejected("missing credential field(s) %s" % missing)
    if provider_kind == m.PROVIDER_ON_PREM_SERVER and not ({"password", "token"} & set(clean)):
        raise CredentialRejected("an on-premise server needs a password or a token")
    return clean


class CredentialVault:
    """One tenant's credential vault. Build it from the tenant's own view."""

    def __init__(self, tenant, *, master_key: Optional[bytes] = None):
        if tenant is None:
            raise CredentialVaultUnavailable("the vault needs a resolved tenant")
        self._tenant = tenant
        self.org_id = tenant.org_id
        key = master_key if master_key is not None else master_key_from_environment()
        if not isinstance(key, (bytes, bytearray)) or len(key) < 32:
            raise CredentialVaultUnavailable("master key must hold at least 32 bytes")
        self._data_key = HKDF(algorithm=hashes.SHA256(), length=32, salt=_HKDF_SALT,
                              info=("tenant:" + self.org_id).encode()).derive(bytes(key))

    def __repr__(self) -> str:
        return "<CredentialVault tenant=%s>" % self.org_id

    @property
    def _rows(self):
        return self._tenant.collection(CREDENTIALS_COLLECTION)

    def _aad(self, binding_id: str, provider_kind: str, reference: str) -> bytes:
        return json.dumps([self.org_id, binding_id, provider_kind, reference]).encode()

    async def store(self, *, binding_id: str, provider_kind: str, secret: Mapping[str, Any],
                    created_by: str) -> str:
        """Seal ``secret`` and return its reference. The value is never returned."""
        clean = validate_secret(provider_kind, secret)
        reference = REFERENCE_PREFIX + uuid.uuid4().hex
        nonce = os.urandom(12)
        sealed = AESGCM(self._data_key).encrypt(
            nonce, json.dumps(clean, sort_keys=True).encode(),
            self._aad(binding_id, provider_kind, reference))
        await self._rows.insert_one({
            "id": reference, m.ORG_KEY: self.org_id, "binding_id": binding_id,
            "provider_kind": provider_kind, "key_version": KEY_VERSION,
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(sealed).decode(),
            "field_names": sorted(clean), "created_by": created_by, "created_at": _now(),
            "superseded_at": None})
        return reference

    async def resolve(self, *, reference: str, binding_id: str, provider_kind: str) -> Dict[str, str]:
        """The secret values — server-side only, for one adapter construction."""
        row = await self._rows.find_one({"id": reference, "binding_id": binding_id,
                                         "provider_kind": provider_kind,
                                         "superseded_at": None}, {"_id": 0})
        if not row:
            raise CredentialReferenceInvalid("no credential %r for this binding" % reference)
        try:
            plain = AESGCM(self._data_key).decrypt(
                base64.b64decode(row["nonce"]), base64.b64decode(row["ciphertext"]),
                self._aad(binding_id, provider_kind, reference))
        except (InvalidTag, ValueError, KeyError):
            raise CredentialReferenceInvalid("credential failed authentication") from None
        return json.loads(plain)

    async def supersede(self, *, reference: str, binding_id: str) -> None:
        await self._rows.update_one({"id": reference, "binding_id": binding_id},
                                    {"$set": {"superseded_at": _now()}})
