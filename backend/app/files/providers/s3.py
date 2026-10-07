"""
W0-06B — S3-compatible object storage adapter (AWS S3, MinIO, Wasabi, Ceph RGW...).

Path-style addressing (``{endpoint}/{bucket}/{root}/{key}``) because it works on
every S3-compatible server, and AWS Signature Version 4 implemented here from
the published specification with the standard library only — the signer is
checked against AWS's own published test vectors and against botocore in
``tests/test_w0_06b_provider_adapters.py``.

Binding: ``endpoint`` = the S3 endpoint URL, ``container`` = the bucket,
``root_prefix`` = the tenant-specific key prefix, ``account`` = the access key
id (an identifier, not a secret). Credentials (vault-resolved, server-side only):
``access_key_id``, ``secret_access_key`` and optionally ``region``.

Integrity: uploads send ``x-amz-checksum-sha256``; ``stat`` asks for it back
(``x-amz-checksum-mode: ENABLED``), so the check is the provider's own sha256
when the server supports it, and BEG_Work re-reads and hashes when it does not.
Temporary access is a pre-signed URL, capped at
:data:`~app.files.providers.base.MAX_TEMPORARY_ACCESS_SECONDS`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import quote, urlsplit

from app.files.models import (
    DELETE_PROVIDER_FAILED,
    DELETE_PROVIDER_REFUSED,
    PROVIDER_S3_COMPATIBLE,
)
from app.files.providers.base import (
    ACCESS_PREVIEW,
    ACCESS_PURPOSES,
    ACCESS_READ,
    ACCESS_WRITE,
    MAX_TEMPORARY_ACCESS_SECONDS,
    DeleteReceipt,
    ProviderCapabilities,
    ProviderCredentialsInvalid,
    ProviderError,
    ProviderObjectMissing,
    ProviderObjectRef,
    ProviderObjectStat,
    ProviderPermissionDenied,
    StorageProviderAdapter,
    TemporaryAccessGrant,
    expiry_for,
    sha256_hex,
)
from app.files.providers.http import ProviderHttp, raise_for_status

ALGORITHM = "AWS4-HMAC-SHA256"
SERVICE = "s3"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
UNSIGNED_PAYLOAD = "UNSIGNED-PAYLOAD"


# ───────────────────────────────────────────────────── SigV4 (pure functions)
def _uri_encode(value: str, *, keep_slash: bool) -> str:
    return quote(value, safe="/-_.~" if keep_slash else "-_.~")


def canonical_query(params: Mapping[str, str]) -> str:
    pairs = sorted((_uri_encode(str(k), keep_slash=False), _uri_encode(str(v), keep_slash=False))
                   for k, v in params.items())
    return "&".join("%s=%s" % kv for kv in pairs)


def signing_key(secret: str, date: str, region: str, service: str = SERVICE) -> bytes:
    k = hmac.new(("AWS4" + secret).encode(), date.encode(), hashlib.sha256).digest()
    for part in (region, service, "aws4_request"):
        k = hmac.new(k, part.encode(), hashlib.sha256).digest()
    return k


def canonical_request(method: str, path: str, query: Mapping[str, str],
                      headers: Mapping[str, str], payload_hash: str) -> Tuple[str, str]:
    """``(canonical_request, signed_headers)`` per the SigV4 specification."""
    lowered = {k.lower().strip(): " ".join(str(v).strip().split()) for k, v in headers.items()}
    names = sorted(lowered)
    signed = ";".join(names)
    canon_headers = "".join("%s:%s\n" % (n, lowered[n]) for n in names)
    request = "\n".join([method.upper(), _uri_encode(path, keep_slash=True) or "/",
                         canonical_query(query), canon_headers, signed, payload_hash])
    return request, signed


def sign(*, method: str, path: str, query: Mapping[str, str], headers: Mapping[str, str],
         payload_hash: str, access_key: str, secret_key: str, region: str,
         amz_date: str) -> str:
    """The ``Authorization`` header value for one request."""
    date = amz_date[:8]
    scope = "%s/%s/%s/aws4_request" % (date, region, SERVICE)
    creq, signed = canonical_request(method, path, query, headers, payload_hash)
    to_sign = "\n".join([ALGORITHM, amz_date, scope,
                         hashlib.sha256(creq.encode()).hexdigest()])
    signature = hmac.new(signing_key(secret_key, date, region), to_sign.encode(),
                         hashlib.sha256).hexdigest()
    return "%s Credential=%s/%s, SignedHeaders=%s, Signature=%s" % (
        ALGORITHM, access_key, scope, signed, signature)


def presign(*, method: str, host: str, path: str, access_key: str, secret_key: str,
            region: str, amz_date: str, expires: int,
            extra_query: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """The query parameters of a pre-signed URL (signature included)."""
    date = amz_date[:8]
    scope = "%s/%s/%s/aws4_request" % (date, region, SERVICE)
    query = dict(extra_query or {})
    query.update({"X-Amz-Algorithm": ALGORITHM,
                  "X-Amz-Credential": "%s/%s" % (access_key, scope),
                  "X-Amz-Date": amz_date, "X-Amz-Expires": str(int(expires)),
                  "X-Amz-SignedHeaders": "host"})
    creq, _ = canonical_request(method, path, query, {"host": host}, UNSIGNED_PAYLOAD)
    to_sign = "\n".join([ALGORITHM, amz_date, scope,
                         hashlib.sha256(creq.encode()).hexdigest()])
    query["X-Amz-Signature"] = hmac.new(signing_key(secret_key, date, region),
                                        to_sign.encode(), hashlib.sha256).hexdigest()
    return query


def _amz_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


_ERROR_CODE = re.compile(rb"<Code>([^<]+)</Code>")
_CREDENTIAL_ERRORS = {b"InvalidAccessKeyId", b"SignatureDoesNotMatch", b"InvalidToken",
                      b"ExpiredToken", b"AuthorizationHeaderMalformed"}


# ──────────────────────────────────────────────────────────────── the adapter
class S3CompatibleAdapter(StorageProviderAdapter):
    provider_kind = PROVIDER_S3_COMPATIBLE

    def __init__(self, binding, *, credentials=None, transport=None):
        super().__init__(binding, credentials=credentials, transport=transport)
        parts = urlsplit(binding.endpoint or "")
        if parts.scheme not in ("https", "http") or not parts.netloc:
            raise ValueError("an S3 binding needs an http(s) endpoint")
        self._scheme, self._host = parts.scheme, parts.netloc
        self._base_path = parts.path.rstrip("/")
        self._http = ProviderHttp(transport)

    # ------------------------------------------------------------ helpers
    def _keys(self) -> Tuple[str, str, str]:
        access, secret = self._credentials.require("access_key_id", "secret_access_key")
        return access, secret, self._credentials.get("region") or "us-east-1"

    def _path(self, object_key: Optional[str] = None) -> str:
        bucket = self.binding.container
        if object_key is None:
            return "%s/%s" % (self._base_path, bucket)
        return "%s/%s/%s" % (self._base_path, bucket, self.binding.object_path(object_key))

    async def _call(self, method: str, path: str, *, query: Optional[Mapping[str, str]] = None,
                    body: bytes = b"", headers: Optional[Mapping[str, str]] = None, what: str):
        access, secret, region = self._keys()
        amz_date = _amz_now()
        payload_hash = sha256_hex(body)
        signed_headers = {"host": self._host, "x-amz-date": amz_date,
                          "x-amz-content-sha256": payload_hash, **(headers or {})}
        auth = sign(method=method, path=path, query=query or {}, headers=signed_headers,
                    payload_hash=payload_hash, access_key=access, secret_key=secret,
                    region=region, amz_date=amz_date)
        url = "%s://%s%s" % (self._scheme, self._host, _uri_encode(path, keep_slash=True))
        if query:
            # Send exactly the query string that was signed.
            url += "?" + canonical_query(query)
        response = await self._http.request(
            method, url, headers={**signed_headers, "authorization": auth},
            content=body if body else None)
        if response.status_code == 403 and _ERROR_CODE.search(response.content or b""):
            code = _ERROR_CODE.search(response.content).group(1)
            if code in _CREDENTIAL_ERRORS:
                raise ProviderCredentialsInvalid("%s: credentials rejected" % what,
                                                 code=code.decode("ascii", "replace"))
        return response

    @staticmethod
    def _checksum_from(headers) -> Optional[Dict[str, str]]:
        b64 = headers.get("x-amz-checksum-sha256")
        if not b64:
            return None
        try:
            return {"algorithm": "sha256", "value": base64.b64decode(b64).hex()}
        except (ValueError, TypeError):
            return None

    # --------------------------------------------------------- capability
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(provider_kind=self.provider_kind, can_put=True, can_read=True,
                                    can_stat=True, can_delete=True, server_side_checksum=True,
                                    native_file_ids=False, temporary_links=True, versioning=True,
                                    max_object_bytes=5 * 1024 ** 3)

    # --------------------------------------------------------- onboarding
    async def validate_credentials(self) -> None:
        response = await self._call("GET", self._path(), what="list bucket",
                                    query={"list-type": "2", "max-keys": "1",
                                           "prefix": (self.binding.root + "/")
                                           if self.binding.root else ""})
        if response.status_code == 404:
            raise ProviderObjectMissing("bucket not found", code="NO_SUCH_BUCKET")
        raise_for_status(response, what="list bucket")

    async def check_root(self) -> None:
        # A prefix needs no creation; the bucket and the right to list it under
        # the prefix are what validate_credentials proved. The write half is the
        # activation's own upload.
        await self.validate_credentials()

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------- object
    async def put(self, *, object_key: str, data: bytes, mime_type: str,
                  metadata: Optional[Mapping[str, Any]] = None) -> ProviderObjectRef:
        digest = hashlib.sha256(data).digest()
        headers = {"content-type": mime_type or "application/octet-stream",
                   "x-amz-checksum-sha256": base64.b64encode(digest).decode()}
        response = await self._call("PUT", self._path(object_key), body=bytes(data),
                                    headers=headers, what="put object")
        raise_for_status(response, what="put object")
        version = response.headers.get("x-amz-version-id") or \
            (response.headers.get("etag") or "").strip('"') or None
        return ProviderObjectRef(container=self.binding.container, object_key=object_key,
                                 provider_version_id=version)

    async def read(self, ref: ProviderObjectRef) -> bytes:
        self._own(ref)
        response = await self._call("GET", self._path(ref.object_key), what="get object")
        raise_for_status(response, what="get object")
        return response.content

    async def stat(self, ref: ProviderObjectRef) -> ProviderObjectStat:
        self._own(ref)
        response = await self._call("HEAD", self._path(ref.object_key), what="head object",
                                    headers={"x-amz-checksum-mode": "ENABLED"})
        if response.status_code == 404:
            return ProviderObjectStat(exists=False)
        raise_for_status(response, what="head object")
        size = response.headers.get("content-length")
        version = response.headers.get("x-amz-version-id") or \
            (response.headers.get("etag") or "").strip('"') or None
        return ProviderObjectStat(exists=True, size_bytes=int(size) if size else None,
                                  checksum=self._checksum_from(response.headers),
                                  modified_at=response.headers.get("last-modified"),
                                  provider_version_id=version)

    async def request_delete(self, ref: ProviderObjectRef, *, reason: str) -> DeleteReceipt:
        self._own(ref)
        try:
            before = await self.stat(ref)
            if not before.exists:
                return DeleteReceipt(state=DELETE_PROVIDER_FAILED, provider_kind=self.provider_kind,
                                     response_code="NOT_FOUND",
                                     message="no object at this location")
            response = await self._call("DELETE", self._path(ref.object_key),
                                        what="delete object")
            raise_for_status(response, what="delete object")
        except ProviderPermissionDenied as exc:
            return DeleteReceipt(state=DELETE_PROVIDER_REFUSED, provider_kind=self.provider_kind,
                                 response_code=exc.code, message="permission denied")
        except ProviderError as exc:
            return DeleteReceipt(state=DELETE_PROVIDER_FAILED, provider_kind=self.provider_kind,
                                 response_code=exc.code, message="provider error")
        return await self._confirm_gone(ref, reason)

    async def temporary_access(self, ref: ProviderObjectRef, *, purpose: str,
                               seconds: int = 300) -> TemporaryAccessGrant:
        self._own(ref)
        if purpose not in ACCESS_PURPOSES:
            raise ValueError("unknown access purpose %r" % purpose)
        expires_at = expiry_for(seconds)          # enforces the 15-minute cap
        access, secret, region = self._keys()
        method = "PUT" if purpose == ACCESS_WRITE else "GET"
        path = self._path(ref.object_key)
        query = presign(method=method, host=self._host, path=path, access_key=access,
                        secret_key=secret, region=region, amz_date=_amz_now(),
                        expires=min(seconds, MAX_TEMPORARY_ACCESS_SECONDS))
        url = "%s://%s%s?%s" % (self._scheme, self._host, _uri_encode(path, keep_slash=True),
                                canonical_query(query))
        return TemporaryAccessGrant(purpose=purpose, expires_at=expires_at,
                                    token="s3-presigned", container=ref.container,
                                    object_key=ref.object_key, provider_url=url)

    def _own(self, ref: ProviderObjectRef) -> None:
        if ref.container != self.binding.container:
            raise ProviderPermissionDenied("binding %s cannot reach another bucket"
                                           % self.binding.binding_id, code="WRONG_CONTAINER")


__all__ = ["S3CompatibleAdapter", "sign", "presign", "canonical_request", "signing_key",
           "ACCESS_READ", "ACCESS_PREVIEW"]
