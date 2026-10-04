"""
W0-06B — Synology / NAS adapter (DSM File Station Web API).

Binding: ``endpoint`` = the DSM base URL (``https://nas.example:5001``);
``container`` = the shared folder (``BEG_Work``); ``root_prefix`` = the
tenant-specific directory inside it; ``account`` = the DSM user name (an
identifier). Credentials (vault-resolved, server-side only): ``password``.

Session: ``SYNO.API.Auth`` login with ``session=FileStation`` returns a ``sid``
that is held only by this adapter instance and logged out by :meth:`aclose`.
The password is sent in a POST body, never in a URL that a proxy could log. An
expired session (error 106/107/119) is re-established once.

File Station reports size and modification time but no sha256, so integrity is
checked by READING the bytes and hashing them (``read_and_hash``), and
``mtime:size`` is the provider version — a file touched or replaced on the NAS
behind BEG_Work's back is told apart from one that is fine. Sharing links are
day-granular, so temporary access is a BEG_Work grant (``temporary_links=False``).

Error codes (DSM File Station API guide): 400/401/402 on login = bad account,
disabled account, no permission; 105/407 = permission denied; 408 = no such
file or directory; 414 = file already exists.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from app.files.models import (
    DELETE_PROVIDER_FAILED,
    DELETE_PROVIDER_REFUSED,
    PROVIDER_SYNOLOGY_NAS,
)
from app.files.providers.base import (
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
)
from app.files.providers.http import ProviderHttp, raise_for_status

LOGIN_ERRORS_CREDENTIALS = {400, 401, 402, 403, 404}
SESSION_ERRORS = {106, 107, 119}
PERMISSION_ERRORS = {105, 407}
MISSING_ERRORS = {408}


class SynologyNasAdapter(StorageProviderAdapter):
    provider_kind = PROVIDER_SYNOLOGY_NAS

    def __init__(self, binding, *, credentials=None, transport=None):
        super().__init__(binding, credentials=credentials, transport=transport)
        if not (binding.endpoint or "").startswith(("https://", "http://")):
            raise ValueError("a Synology binding needs an http(s) endpoint")
        if not binding.account:
            raise ValueError("a Synology binding names the DSM account")
        self._base = binding.endpoint.rstrip("/") + "/webapi"
        self._http = ProviderHttp(transport)
        self._sid: Optional[str] = None

    def __repr__(self) -> str:                         # never shows the sid
        return "<SynologyNasAdapter binding=%s>" % self.binding.binding_id

    # ------------------------------------------------------------ session
    async def _login(self) -> str:
        (password,) = self._credentials.require("password")
        response = await self._http.request(
            "POST", self._base + "/auth.cgi",
            data={"api": "SYNO.API.Auth", "version": "6", "method": "login",
                  "account": self.binding.account, "passwd": password,
                  "session": "FileStation", "format": "sid"})
        raise_for_status(response, what="login")
        body = response.json()
        if not body.get("success"):
            code = (body.get("error") or {}).get("code")
            if code in LOGIN_ERRORS_CREDENTIALS:
                raise ProviderCredentialsInvalid("NAS login refused", code="SYNO_%s" % code)
            raise ProviderError("NAS login failed", code="SYNO_%s" % code)
        self._sid = body["data"]["sid"]
        return self._sid

    async def _api(self, method_http: str, params: Mapping[str, Any], *, what: str,
                   files=None, data=None, raw: bool = False, _retry: bool = True):
        sid = self._sid or await self._login()
        query = {**params, "_sid": sid}
        response = await self._http.request(method_http, self._base + "/entry.cgi",
                                            params=query, files=files, data=data)
        raise_for_status(response, what=what)
        is_json = "json" in (response.headers.get("content-type") or "")
        if raw and not is_json:
            return response
        body = response.json()
        if body.get("success"):
            return body.get("data") or {}
        code = (body.get("error") or {}).get("code")
        if code in SESSION_ERRORS and _retry:
            self._sid = None
            return await self._api(method_http, params, what=what, files=files, data=data,
                                   raw=raw, _retry=False)
        self._raise(code, what)

    @staticmethod
    def _raise(code, what):
        if code in PERMISSION_ERRORS:
            raise ProviderPermissionDenied("%s: permission denied" % what, code="SYNO_%s" % code)
        if code in MISSING_ERRORS:
            raise ProviderObjectMissing("%s: no such file" % what, code="SYNO_%s" % code)
        raise ProviderError("%s: NAS error" % what, code="SYNO_%s" % code)

    def _full(self, object_key: Optional[str] = None) -> str:
        base = "/" + self.binding.container.strip("/")
        if object_key is None:
            return base + ("/" + self.binding.root if self.binding.root else "")
        return base + "/" + self.binding.object_path(object_key)

    # --------------------------------------------------------- capability
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(provider_kind=self.provider_kind, can_put=True, can_read=True,
                                    can_stat=True, can_delete=True, server_side_checksum=False,
                                    native_file_ids=False, temporary_links=False, versioning=False)

    # --------------------------------------------------------- onboarding
    async def validate_credentials(self) -> None:
        self._sid = None
        await self._login()

    async def check_root(self) -> None:
        info = await self._getinfo(self._full())
        if info is None:
            raise ProviderObjectMissing("tenant root directory not found", code="ROOT_NOT_FOUND")
        if not info.get("isdir"):
            raise ProviderObjectMissing("tenant root is not a directory", code="ROOT_NOT_DIR")

    async def aclose(self) -> None:
        if self._sid:
            try:
                await self._http.request("GET", self._base + "/auth.cgi",
                                         params={"api": "SYNO.API.Auth", "version": "6",
                                                 "method": "logout", "session": "FileStation",
                                                 "_sid": self._sid})
            except ProviderError:
                pass
        self._sid = None
        await self._http.aclose()

    # ------------------------------------------------------------- object
    async def _getinfo(self, path: str) -> Optional[Mapping[str, Any]]:
        data = await self._api("GET", {"api": "SYNO.FileStation.List", "version": "2",
                                       "method": "getinfo", "path": json.dumps([path]),
                                       "additional": json.dumps(["size", "time"])},
                               what="getinfo")
        files = data.get("files") or []
        if not files:
            return None
        info = files[0]
        code = info.get("code")
        if code in MISSING_ERRORS:
            return None
        if code is not None:
            self._raise(code, "getinfo")
        return info

    async def put(self, *, object_key: str, data: bytes, mime_type: str,
                  metadata: Optional[Mapping[str, Any]] = None) -> ProviderObjectRef:
        full = self._full(object_key)
        folder, name = full.rsplit("/", 1)
        await self._api("POST", {"api": "SYNO.FileStation.Upload", "version": "2",
                                 "method": "upload"}, what="upload",
                        data={"path": folder, "create_parents": "true", "overwrite": "false"},
                        files={"file": (name, bytes(data), mime_type or "application/octet-stream")})
        stat = await self.stat(ProviderObjectRef(container=self.binding.container,
                                                 object_key=object_key))
        return ProviderObjectRef(container=self.binding.container, object_key=object_key,
                                 provider_version_id=stat.provider_version_id)

    async def stat(self, ref: ProviderObjectRef) -> ProviderObjectStat:
        self._own(ref)
        info = await self._getinfo(self._full(ref.object_key))
        if info is None:
            return ProviderObjectStat(exists=False)
        extra = info.get("additional") or {}
        size = extra.get("size")
        mtime = (extra.get("time") or {}).get("mtime")
        return ProviderObjectStat(exists=True, size_bytes=int(size) if size is not None else None,
                                  modified_at=str(mtime) if mtime is not None else None,
                                  provider_version_id=("%s:%s" % (mtime, size))
                                  if mtime is not None else None)

    async def read(self, ref: ProviderObjectRef) -> bytes:
        self._own(ref)
        response = await self._api("GET", {"api": "SYNO.FileStation.Download", "version": "2",
                                           "method": "download", "mode": "download",
                                           "path": self._full(ref.object_key)},
                                   what="download", raw=True)
        return response.content

    async def request_delete(self, ref: ProviderObjectRef, *, reason: str) -> DeleteReceipt:
        try:
            if not (await self.stat(ref)).exists:
                return DeleteReceipt(state=DELETE_PROVIDER_FAILED, provider_kind=self.provider_kind,
                                     response_code="NOT_FOUND", message="no object at this location")
            await self._api("GET", {"api": "SYNO.FileStation.Delete", "version": "2",
                                    "method": "delete", "recursive": "false",
                                    "path": json.dumps([self._full(ref.object_key)])},
                            what="delete")
        except ProviderPermissionDenied as exc:
            return DeleteReceipt(state=DELETE_PROVIDER_REFUSED, provider_kind=self.provider_kind,
                                 response_code=exc.code, message="permission denied")
        except ProviderError as exc:
            return DeleteReceipt(state=DELETE_PROVIDER_FAILED, provider_kind=self.provider_kind,
                                 response_code=exc.code, message="provider error")
        return await self._confirm_gone(ref, reason)

    async def temporary_access(self, ref, *, purpose, seconds=300) -> TemporaryAccessGrant:
        raise ProviderError("File Station sharing links are not time-limited enough; "
                            "use a BEG_Work grant", code="NO_NATIVE_TEMPORARY_LINKS")

    def _own(self, ref: ProviderObjectRef) -> None:
        if ref.container != self.binding.container:
            raise ProviderPermissionDenied("binding %s cannot reach another shared folder"
                                           % self.binding.binding_id, code="WRONG_CONTAINER")
