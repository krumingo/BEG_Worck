"""
W0-06B — Google Drive / Shared Drive adapter (Drive API v3, REST).

Binding: ``container`` = the id of the tenant's root FOLDER (in My Drive or in a
Shared Drive); ``account`` = the Google account / drive the credentials belong
to (an identifier, not a secret); ``endpoint`` = empty for Google, or the base
URL of an API-compatible test double. Credentials (vault-resolved, server-side
only): an OAuth ``client_id``, ``client_secret`` and ``refresh_token``. The
access token is minted from the refresh token on the server and held only in
this adapter instance; it is never returned, logged or stored.

Drive is id-based: an object is identified by its Drive file id
(``native_file_ids``), and BEG_Work's own object key is kept on the file as an
``appProperties`` entry so a location can still be found by key. Every call
passes ``supportsAllDrives=true`` so a Shared Drive root works the same way.

Integrity uses Drive's own ``sha256Checksum``; ``headRevisionId`` is the
provider version, so a file replaced or edited in Drive is told apart from one
whose bytes changed. An object outside the tenant root folder is refused, never
followed. Drive has no time-limited download link (``temporary_links=False``):
access is served through a BEG_Work grant (:mod:`app.files.access`).
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Mapping, Optional

from app.files.models import (
    DELETE_PROVIDER_FAILED,
    DELETE_PROVIDER_REFUSED,
    PROVIDER_GOOGLE_DRIVE,
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

GOOGLE_API = "https://www.googleapis.com"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
FOLDER_MIME = "application/vnd.google-apps.folder"
FILE_FIELDS = "id,name,size,sha256Checksum,headRevisionId,trashed,parents,mimeType"
KEY_PROPERTY = "beg_object_key"


class GoogleDriveAdapter(StorageProviderAdapter):
    provider_kind = PROVIDER_GOOGLE_DRIVE

    def __init__(self, binding, *, credentials=None, transport=None):
        super().__init__(binding, credentials=credentials, transport=transport)
        base = (binding.endpoint or GOOGLE_API).rstrip("/")
        self._api = base + "/drive/v3"
        self._upload = base + "/upload/drive/v3"
        self._token_url = (base + "/token") if binding.endpoint else GOOGLE_TOKEN_URL
        self._http = ProviderHttp(transport)
        self._token: Optional[str] = None
        self._token_expiry = 0.0

    def __repr__(self) -> str:                         # never shows the token
        return "<GoogleDriveAdapter binding=%s>" % self.binding.binding_id

    # ------------------------------------------------------------ auth
    async def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expiry - 30:
            return self._token
        client_id, client_secret, refresh = self._credentials.require(
            "client_id", "client_secret", "refresh_token")
        response = await self._http.request(
            "POST", self._token_url,
            data={"grant_type": "refresh_token", "client_id": client_id,
                  "client_secret": client_secret, "refresh_token": refresh})
        if response.status_code in (400, 401):
            raise ProviderCredentialsInvalid("token refresh refused", code="INVALID_GRANT")
        raise_for_status(response, what="token refresh")
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise ProviderCredentialsInvalid("token refresh returned no token")
        self._token = token
        self._token_expiry = time.monotonic() + float(payload.get("expires_in") or 300)
        return token

    async def _call(self, method: str, url: str, *, what: str, params=None, headers=None,
                    content: Optional[bytes] = None):
        token = await self._access_token()
        merged = {"supportsAllDrives": "true", **(params or {})}
        return await self._http.request(method, url, params=merged, content=content,
                                        headers={"authorization": "Bearer " + token,
                                                 **(headers or {})})

    # --------------------------------------------------------- capability
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(provider_kind=self.provider_kind, can_put=True, can_read=True,
                                    can_stat=True, can_delete=True, server_side_checksum=True,
                                    native_file_ids=True, temporary_links=False, versioning=True)

    # --------------------------------------------------------- onboarding
    async def validate_credentials(self) -> None:
        response = await self._call("GET", self._api + "/about", what="about",
                                    params={"fields": "user(emailAddress)"})
        raise_for_status(response, what="about")

    async def check_root(self) -> None:
        response = await self._call("GET", "%s/files/%s" % (self._api, self.binding.container),
                                    what="root folder",
                                    params={"fields": "id,mimeType,trashed,"
                                                      "capabilities(canAddChildren)"})
        raise_for_status(response, what="root folder")
        info = response.json()
        if info.get("trashed") or info.get("mimeType") != FOLDER_MIME:
            raise ProviderObjectMissing("root is not a live folder", code="ROOT_NOT_FOLDER")
        if not (info.get("capabilities") or {}).get("canAddChildren"):
            raise ProviderPermissionDenied("root folder is not writable", code="ROOT_READ_ONLY")

    async def aclose(self) -> None:
        self._token = None
        await self._http.aclose()

    # ------------------------------------------------------------- object
    def _in_root(self, info: Mapping[str, Any]) -> bool:
        return self.binding.container in (info.get("parents") or [])

    async def _find_id(self, ref: ProviderObjectRef) -> Optional[str]:
        if ref.provider_file_id:
            return ref.provider_file_id
        key = self.binding.object_path(ref.object_key).replace("'", "\\'")
        query = ("appProperties has { key='%s' and value='%s' } and '%s' in parents "
                 "and trashed = false" % (KEY_PROPERTY, key, self.binding.container))
        response = await self._call("GET", self._api + "/files", what="find object",
                                    params={"q": query, "fields": "files(id)",
                                            "includeItemsFromAllDrives": "true"})
        raise_for_status(response, what="find object")
        files = response.json().get("files") or []
        if len(files) > 1:
            raise ProviderError("two Drive objects carry one key", code="AMBIGUOUS_KEY")
        return files[0]["id"] if files else None

    async def put(self, *, object_key: str, data: bytes, mime_type: str,
                  metadata: Optional[Mapping[str, Any]] = None) -> ProviderObjectRef:
        path = self.binding.object_path(object_key)
        meta = {"name": path.rsplit("/", 1)[-1], "parents": [self.binding.container],
                "mimeType": mime_type or "application/octet-stream",
                "appProperties": {KEY_PROPERTY: path}}
        boundary = "beg_" + uuid.uuid4().hex
        body = b"".join([
            b"--" + boundary.encode() + b"\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n",
            json.dumps(meta).encode(), b"\r\n",
            b"--" + boundary.encode() + b"\r\nContent-Type: " +
            (mime_type or "application/octet-stream").encode() + b"\r\n\r\n",
            bytes(data), b"\r\n--" + boundary.encode() + b"--\r\n"])
        response = await self._call(
            "POST", self._upload + "/files", what="upload",
            params={"uploadType": "multipart", "fields": FILE_FIELDS},
            headers={"content-type": "multipart/related; boundary=" + boundary}, content=body)
        raise_for_status(response, what="upload")
        info = response.json()
        return ProviderObjectRef(container=self.binding.container, object_key=object_key,
                                 provider_file_id=info["id"],
                                 provider_version_id=info.get("headRevisionId"))

    async def _info(self, file_id: str) -> Optional[Mapping[str, Any]]:
        response = await self._call("GET", "%s/files/%s" % (self._api, file_id),
                                    what="file info", params={"fields": FILE_FIELDS})
        if response.status_code == 404:
            return None
        raise_for_status(response, what="file info")
        return response.json()

    async def stat(self, ref: ProviderObjectRef) -> ProviderObjectStat:
        self._own(ref)
        file_id = await self._find_id(ref)
        info = await self._info(file_id) if file_id else None
        if not info or info.get("trashed"):
            return ProviderObjectStat(exists=False)
        if not self._in_root(info):
            raise ProviderPermissionDenied("object is outside the tenant root folder",
                                           code="OUTSIDE_ROOT")
        checksum = ({"algorithm": "sha256", "value": info["sha256Checksum"].lower()}
                    if info.get("sha256Checksum") else None)
        return ProviderObjectStat(exists=True,
                                  size_bytes=int(info["size"]) if info.get("size") else None,
                                  checksum=checksum, provider_file_id=info.get("id"),
                                  provider_version_id=info.get("headRevisionId"))

    async def read(self, ref: ProviderObjectRef) -> bytes:
        stat = await self.stat(ref)                     # enforces the root
        if not stat.exists:
            raise ProviderObjectMissing("no object at this location", code="NOT_FOUND")
        response = await self._call("GET", "%s/files/%s" % (self._api, stat.provider_file_id),
                                    what="download", params={"alt": "media"})
        raise_for_status(response, what="download")
        return response.content

    async def request_delete(self, ref: ProviderObjectRef, *, reason: str) -> DeleteReceipt:
        try:
            stat = await self.stat(ref)
            if not stat.exists:
                return DeleteReceipt(state=DELETE_PROVIDER_FAILED, provider_kind=self.provider_kind,
                                     response_code="NOT_FOUND", message="no object at this location")
            response = await self._call("DELETE", "%s/files/%s" % (self._api, stat.provider_file_id),
                                        what="delete")
            raise_for_status(response, what="delete")
        except ProviderPermissionDenied as exc:
            return DeleteReceipt(state=DELETE_PROVIDER_REFUSED, provider_kind=self.provider_kind,
                                 response_code=exc.code, message="permission denied")
        except ProviderError as exc:
            return DeleteReceipt(state=DELETE_PROVIDER_FAILED, provider_kind=self.provider_kind,
                                 response_code=exc.code, message="provider error")
        confirm_ref = ProviderObjectRef(container=ref.container, object_key=ref.object_key,
                                        provider_file_id=stat.provider_file_id)
        return await self._confirm_gone(confirm_ref, reason)

    async def temporary_access(self, ref, *, purpose, seconds=300) -> TemporaryAccessGrant:
        raise ProviderError("Google Drive issues no time-limited link; use a BEG_Work grant",
                            code="NO_NATIVE_TEMPORARY_LINKS")

    def _own(self, ref: ProviderObjectRef) -> None:
        if ref.container != self.binding.container:
            raise ProviderPermissionDenied("binding %s cannot reach another root folder"
                                           % self.binding.binding_id, code="WRONG_CONTAINER")
