"""
W0-06B — generic customer on-premise server adapter (WebDAV, RFC 4918).

WebDAV is the one storage protocol a customer's own server can be expected to
speak whatever it runs (IIS, Apache ``mod_dav``, nginx, Nextcloud/ownCloud,
Windows/Linux file servers behind a DAV gateway), so the generic "own server"
provider of FLOW-016 is a WebDAV adapter.

Binding: ``endpoint`` = the DAV base URL; ``container`` = the top collection;
``root_prefix`` = the tenant-specific collection under it; ``account`` = the
user name for Basic authentication (empty when a bearer token is used).
Credentials (vault-resolved, server-side only): ``password`` (with ``account``)
or ``token``.

Writes never overwrite: ``PUT`` carries ``If-None-Match: *`` so an existing
object is refused (412) rather than silently replaced. Missing parent
collections are created with ``MKCOL`` under the tenant root only — the root
itself must already exist (:meth:`check_root`). ``ETag`` is the provider
version; a Nextcloud-style ``OC-Checksum: SHA256:<hex>`` header is used when
present, otherwise integrity is ``read_and_hash``. No time-limited links
(``temporary_links=False``).
"""
from __future__ import annotations

import base64
from typing import Any, Mapping, Optional
from urllib.parse import quote

from app.files.models import (
    DELETE_PROVIDER_FAILED,
    DELETE_PROVIDER_REFUSED,
    PROVIDER_ON_PREM_SERVER,
)
from app.files.providers.base import (
    DeleteReceipt,
    ProviderCapabilities,
    ProviderError,
    ProviderObjectMissing,
    ProviderObjectRef,
    ProviderObjectStat,
    ProviderPermissionDenied,
    StorageProviderAdapter,
    TemporaryAccessGrant,
)
from app.files.providers.http import ProviderHttp, raise_for_status

PROPFIND_BODY = (b'<?xml version="1.0" encoding="utf-8"?>'
                 b'<d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/></d:prop></d:propfind>')


class OnPremServerAdapter(StorageProviderAdapter):
    provider_kind = PROVIDER_ON_PREM_SERVER

    def __init__(self, binding, *, credentials=None, transport=None):
        super().__init__(binding, credentials=credentials, transport=transport)
        if not (binding.endpoint or "").startswith(("https://", "http://")):
            raise ValueError("an on-premise binding needs an http(s) endpoint")
        self._base = binding.endpoint.rstrip("/")
        self._http = ProviderHttp(transport)

    def _auth(self) -> Mapping[str, str]:
        token = self._credentials.get("token")
        if token:
            return {"authorization": "Bearer " + token}
        (password,) = self._credentials.require("password")
        raw = ("%s:%s" % (self.binding.account, password)).encode()
        return {"authorization": "Basic " + base64.b64encode(raw).decode()}

    def _url(self, path: str) -> str:
        return "%s/%s" % (self._base, quote(path, safe="/-_.~"))

    def _root_path(self) -> str:
        top = self.binding.container.strip("/")
        return top + ("/" + self.binding.root if self.binding.root else "")

    def _object_path(self, object_key: str) -> str:
        return self.binding.container.strip("/") + "/" + self.binding.object_path(object_key)

    async def _call(self, method: str, path: str, *, what: str, headers=None,
                    content: Optional[bytes] = None):
        return await self._http.request(method, self._url(path), content=content,
                                        headers={**self._auth(), **(headers or {})})

    # --------------------------------------------------------- capability
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(provider_kind=self.provider_kind, can_put=True, can_read=True,
                                    can_stat=True, can_delete=True, server_side_checksum=False,
                                    native_file_ids=False, temporary_links=False, versioning=False)

    # --------------------------------------------------------- onboarding
    async def _propfind(self, path: str, what: str) -> int:
        response = await self._call("PROPFIND", path, what=what, content=PROPFIND_BODY,
                                    headers={"depth": "0", "content-type": "application/xml"})
        if response.status_code == 404:
            return 404
        raise_for_status(response, what=what)
        return response.status_code

    async def validate_credentials(self) -> None:
        if await self._propfind(self.binding.container.strip("/"), "collection") == 404:
            raise ProviderObjectMissing("top collection not found", code="CONTAINER_NOT_FOUND")

    async def check_root(self) -> None:
        if await self._propfind(self._root_path(), "tenant root") == 404:
            raise ProviderObjectMissing("tenant root collection not found", code="ROOT_NOT_FOUND")

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------- object
    async def _ensure_parents(self, object_key: str) -> None:
        parts = self.binding.object_path(object_key).split("/")[:-1]
        current = self.binding.container.strip("/")
        root_depth = len(self.binding.root.split("/")) if self.binding.root else 0
        for depth, part in enumerate(parts, start=1):
            current += "/" + part
            if depth <= root_depth:
                continue                                # the root exists; never create it
            response = await self._call("MKCOL", current, what="mkcol")
            if response.status_code not in (201, 405):  # 405 = already exists
                raise_for_status(response, what="mkcol")

    async def put(self, *, object_key: str, data: bytes, mime_type: str,
                  metadata: Optional[Mapping[str, Any]] = None) -> ProviderObjectRef:
        await self._ensure_parents(object_key)
        response = await self._call("PUT", self._object_path(object_key), what="put",
                                    content=bytes(data),
                                    headers={"content-type": mime_type or "application/octet-stream",
                                             "if-none-match": "*"})
        if response.status_code == 412:
            raise ProviderError("an object already exists at this key", code="EXISTS")
        raise_for_status(response, what="put")
        etag = (response.headers.get("etag") or "").strip('"') or None
        return ProviderObjectRef(container=self.binding.container, object_key=object_key,
                                 provider_version_id=etag)

    async def stat(self, ref: ProviderObjectRef) -> ProviderObjectStat:
        self._own(ref)
        response = await self._call("HEAD", self._object_path(ref.object_key), what="head")
        if response.status_code == 404:
            return ProviderObjectStat(exists=False)
        raise_for_status(response, what="head")
        size = response.headers.get("content-length")
        checksum = None
        oc = response.headers.get("oc-checksum") or ""
        if oc.upper().startswith("SHA256:"):
            checksum = {"algorithm": "sha256", "value": oc.split(":", 1)[1].strip().lower()}
        etag = (response.headers.get("etag") or "").strip('"') or None
        return ProviderObjectStat(exists=True, size_bytes=int(size) if size else None,
                                  checksum=checksum, modified_at=response.headers.get("last-modified"),
                                  provider_version_id=etag)

    async def read(self, ref: ProviderObjectRef) -> bytes:
        self._own(ref)
        response = await self._call("GET", self._object_path(ref.object_key), what="get")
        raise_for_status(response, what="get")
        return response.content

    async def request_delete(self, ref: ProviderObjectRef, *, reason: str) -> DeleteReceipt:
        try:
            if not (await self.stat(ref)).exists:
                return DeleteReceipt(state=DELETE_PROVIDER_FAILED, provider_kind=self.provider_kind,
                                     response_code="NOT_FOUND", message="no object at this location")
            response = await self._call("DELETE", self._object_path(ref.object_key),
                                        what="delete")
            raise_for_status(response, what="delete")
        except ProviderPermissionDenied as exc:
            return DeleteReceipt(state=DELETE_PROVIDER_REFUSED, provider_kind=self.provider_kind,
                                 response_code=exc.code, message="permission denied")
        except ProviderError as exc:
            return DeleteReceipt(state=DELETE_PROVIDER_FAILED, provider_kind=self.provider_kind,
                                 response_code=exc.code, message="provider error")
        return await self._confirm_gone(ref, reason)

    async def temporary_access(self, ref, *, purpose, seconds=300) -> TemporaryAccessGrant:
        raise ProviderError("a generic server issues no time-limited link; use a BEG_Work grant",
                            code="NO_NATIVE_TEMPORARY_LINKS")

    def _own(self, ref: ProviderObjectRef) -> None:
        if ref.container != self.binding.container:
            raise ProviderPermissionDenied("binding %s cannot reach another collection"
                                           % self.binding.binding_id, code="WRONG_CONTAINER")
