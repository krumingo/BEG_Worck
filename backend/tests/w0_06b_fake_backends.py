"""
W0-06B — disposable, in-process fake provider BACKENDS for the four adapters.

Each fake speaks the provider's real wire protocol closely enough for the
adapter to be exercised end to end through ``httpx.MockTransport`` — no socket,
no network, no real account. Each one also CHECKS what a real provider checks:

* FakeS3 verifies AWS SigV4 on every request (header and pre-signed query), with
  its own implementation written from the specification, and rejects a wrong
  key, a wrong secret, a tampered or expired pre-signed URL and a body whose
  ``x-amz-content-sha256`` / ``x-amz-checksum-sha256`` does not match;
* FakeDrive mints access tokens only for the right refresh token and refuses a
  bearer it did not issue;
* FakeSynology runs a DSM-style login and answers with File Station error codes;
* FakeWebDAV checks Basic/Bearer auth and refuses to create a collection whose
  parent is missing (409) or to overwrite under ``If-None-Match: *`` (412).

Failure injection is uniform across the four: ``offline`` (unreachable),
``deny(key)`` (permission), ``mutate(key, data)`` (edited outside BEG_Work),
``remove(key)`` (deleted outside BEG_Work) and ``replace(key)`` (same bytes,
new provider object/version). ``requests`` records every request so tests can
prove a secret never appears in a URL.

Test support only. Nothing here is importable from ``app/``.
"""
from __future__ import annotations

import base64
import email.parser
import hashlib
import hmac
import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qsl, quote, unquote

import httpx


class _Base:
    def __init__(self):
        self.offline = False
        self.denied: Set[str] = set()
        self.requests: List[httpx.Request] = []

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._dispatch)

    def _dispatch(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.offline:
            raise httpx.ConnectError("fake provider offline", request=request)
        return self.handle(request)

    def deny(self, key: str) -> None:
        self.denied.add(key)

    def seen_urls(self) -> List[str]:
        return [str(r.url) for r in self.requests]

    def seen_everything(self) -> List[bytes]:
        """URL + headers + body of every request, for secret-leak scans of URLs."""
        return [str(r.url).encode() for r in self.requests]


# ═════════════════════════════════════════════════════════════════════ S3
def _s3_enc(value: str, slash: bool) -> str:
    return quote(value, safe="/-_.~" if slash else "-_.~")


def _s3_hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


class FakeS3(_Base):
    """Path-style S3 at ``https://s3.fake.local``."""

    HOST = "s3.fake.local"
    ENDPOINT = "https://s3.fake.local"

    def __init__(self, *, bucket="tenant-bucket", access_key="AKIAFAKEBEG0001",
                 secret_key="fake-secret-key-0001/please-never-log-me", checksum_support=True):
        super().__init__()
        self.bucket = bucket
        self.keys = {access_key: secret_key}
        self.access_key, self.secret_key = access_key, secret_key
        self.checksum_support = checksum_support
        self.objects: Dict[str, Dict[str, Any]] = {}

    def credentials(self, **override):
        creds = {"access_key_id": self.access_key, "secret_access_key": self.secret_key,
                 "region": "eu-central-1"}
        creds.update(override)
        return creds

    # ------------------------------------------------------ signature check
    def _scope_ok(self, credential: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        parts = credential.split("/")
        if len(parts) != 5:
            return None, None, None
        return parts[0], parts[1], parts[2]

    def _signature(self, secret, date, region, request, query_pairs, signed_names, payload_hash,
                   amz_date):
        canon_query = "&".join("%s=%s" % (_s3_enc(k, False), _s3_enc(v, False))
                               for k, v in sorted(query_pairs))
        lowered = {k.lower(): " ".join(v.strip().split()) for k, v in request.headers.items()}
        if "host" in signed_names:
            lowered["host"] = request.url.netloc.decode()
        canon_headers = "".join("%s:%s\n" % (n, lowered.get(n, "")) for n in signed_names)
        creq = "\n".join([request.method, _s3_enc(unquote(request.url.path), True), canon_query,
                          canon_headers, ";".join(signed_names), payload_hash])
        scope = "%s/%s/s3/aws4_request" % (date, region)
        sts = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope,
                         hashlib.sha256(creq.encode()).hexdigest()])
        k = _s3_hmac(("AWS4" + secret).encode(), date)
        for part in (region, "s3", "aws4_request"):
            k = _s3_hmac(k, part)
        return hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()

    def _error(self, status, code):
        return httpx.Response(status, content=b"<Error><Code>%s</Code></Error>" % code.encode(),
                              headers={"content-type": "application/xml"})

    def _authenticate(self, request) -> Optional[httpx.Response]:
        query = parse_qsl(request.url.query.decode(), keep_blank_values=True)
        qd = dict(query)
        if "X-Amz-Signature" in qd:                                    # pre-signed
            access, date, region = self._scope_ok(qd.get("X-Amz-Credential", ""))
            if access not in self.keys:
                return self._error(403, "InvalidAccessKeyId")
            amz_date = qd["X-Amz-Date"]
            started = datetime.strptime(amz_date, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            if time.time() > started.timestamp() + int(qd["X-Amz-Expires"]):
                return self._error(403, "AccessDenied")               # expired
            pairs = [(k, v) for k, v in query if k != "X-Amz-Signature"]
            expected = self._signature(self.keys[access], date, region, request, pairs,
                                       qd["X-Amz-SignedHeaders"].split(";"), "UNSIGNED-PAYLOAD",
                                       amz_date)
            if not hmac.compare_digest(expected, qd["X-Amz-Signature"]):
                return self._error(403, "SignatureDoesNotMatch")
            return None
        auth = request.headers.get("authorization", "")
        m = re.match(r"AWS4-HMAC-SHA256 Credential=([^,]+), SignedHeaders=([^,]+), "
                     r"Signature=([0-9a-f]+)$", auth)
        if not m:
            return self._error(403, "AccessDenied")
        access, date, region = self._scope_ok(m.group(1))
        if access not in self.keys:
            return self._error(403, "InvalidAccessKeyId")
        payload_hash = request.headers.get("x-amz-content-sha256", "")
        if payload_hash != hashlib.sha256(request.content).hexdigest():
            return self._error(400, "XAmzContentSHA256Mismatch")
        expected = self._signature(self.keys[access], date, region, request, query,
                                   m.group(2).split(";"), payload_hash,
                                   request.headers.get("x-amz-date", ""))
        if not hmac.compare_digest(expected, m.group(3)):
            return self._error(403, "SignatureDoesNotMatch")
        return None

    # ------------------------------------------------------------ routing
    def handle(self, request: httpx.Request) -> httpx.Response:
        refused = self._authenticate(request)
        if refused is not None:
            return refused
        path = unquote(request.url.path).lstrip("/")
        bucket, _, key = path.partition("/")
        if bucket != self.bucket:
            return self._error(404, "NoSuchBucket")
        if not key:
            return httpx.Response(200, content=b"<ListBucketResult/>")
        if key in self.denied:
            return self._error(403, "AccessDenied")
        obj = self.objects.get(key)
        if request.method == "PUT":
            b64 = request.headers.get("x-amz-checksum-sha256")
            if b64 and base64.b64decode(b64) != hashlib.sha256(request.content).digest():
                return self._error(400, "BadDigest")
            self.objects[key] = {"data": request.content, "version": uuid.uuid4().hex}
            return httpx.Response(200, headers={"etag": '"%s"' % hashlib.md5(
                request.content).hexdigest(), "x-amz-version-id": self.objects[key]["version"]})
        if obj is None:
            return httpx.Response(404) if request.method == "HEAD" else self._error(404, "NoSuchKey")
        if request.method == "HEAD":
            headers = {"content-length": str(len(obj["data"])),
                       "x-amz-version-id": obj["version"]}
            if self.checksum_support and request.headers.get("x-amz-checksum-mode") == "ENABLED":
                headers["x-amz-checksum-sha256"] = base64.b64encode(
                    hashlib.sha256(obj["data"]).digest()).decode()
            return httpx.Response(200, headers=headers)
        if request.method == "GET":
            return httpx.Response(200, content=obj["data"])
        if request.method == "DELETE":
            del self.objects[key]
            return httpx.Response(204)
        return self._error(405, "MethodNotAllowed")

    # ---------------------------------------------------- failure injection
    def _full(self, key):
        return next(k for k in self.objects if k == key or k.endswith("/" + key))

    def mutate(self, key, data):
        k = self._full(key)
        self.objects[k]["data"] = data
        self.objects[k]["version"] = uuid.uuid4().hex

    def remove(self, key):
        self.objects.pop(self._full(key), None)

    def replace(self, key):
        self.objects[self._full(key)]["version"] = uuid.uuid4().hex

    def deny(self, key):
        self.denied.add(self._full(key))


# ═══════════════════════════════════════════════════════════════════ Drive
class FakeDrive(_Base):
    ENDPOINT = "https://drive.fake.local"

    def __init__(self, *, root_id="root-folder-1", client_id="beg-client",
                 client_secret="fake-client-secret-please-never-log",
                 refresh_token="fake-refresh-token-please-never-log", root_writable=True):
        super().__init__()
        self.root_id = root_id
        self.client = (client_id, client_secret, refresh_token)
        self.tokens: Set[str] = set()
        self.files: Dict[str, Dict[str, Any]] = {
            root_id: {"id": root_id, "name": "BEG", "mimeType": "application/vnd.google-apps.folder",
                      "parents": [], "trashed": False, "canAddChildren": root_writable}}

    def credentials(self, **override):
        creds = dict(zip(("client_id", "client_secret", "refresh_token"), self.client))
        creds.update(override)
        return creds

    def _info(self, f):
        out = {k: f[k] for k in ("id", "name", "mimeType", "parents", "trashed")}
        if "data" in f:
            out.update(size=str(len(f["data"])), sha256Checksum=hashlib.sha256(f["data"]).hexdigest(),
                       headRevisionId=f["rev"])
        if f.get("mimeType") == "application/vnd.google-apps.folder":
            out["capabilities"] = {"canAddChildren": f.get("canAddChildren", True)}
        return out

    def _key_of(self, f):
        return (f.get("appProperties") or {}).get("beg_object_key")

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/token":
            form = dict(parse_qsl(request.content.decode()))
            if (form.get("client_id"), form.get("client_secret"), form.get("refresh_token")) \
                    != self.client:
                return httpx.Response(400, json={"error": "invalid_grant"})
            token = "ya29.fake-" + uuid.uuid4().hex
            self.tokens.add(token)
            return httpx.Response(200, json={"access_token": token, "expires_in": 3600})
        bearer = request.headers.get("authorization", "")[len("Bearer "):]
        if bearer not in self.tokens:
            return httpx.Response(401, json={"error": "unauthenticated"})
        params = dict(request.url.params)
        if path == "/drive/v3/about":
            return httpx.Response(200, json={"user": {"emailAddress": "beg@fake.local"}})
        if path == "/upload/drive/v3/files" and request.method == "POST":
            ctype = request.headers["content-type"]
            msg = email.parser.BytesParser().parsebytes(
                b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + request.content)
            meta_part, media_part = msg.get_payload()
            meta = json.loads(meta_part.get_payload(decode=True))
            if not self.files[self.root_id].get("canAddChildren", True):
                return httpx.Response(403, json={"error": "forbidden"})
            fid = "drv_" + uuid.uuid4().hex[:16]
            self.files[fid] = {"id": fid, "name": meta["name"], "mimeType": meta["mimeType"],
                               "parents": meta["parents"], "trashed": False,
                               "appProperties": meta.get("appProperties") or {},
                               "data": media_part.get_payload(decode=True), "rev": "rev1"}
            return httpx.Response(200, json=self._info(self.files[fid]))
        if path == "/drive/v3/files" and request.method == "GET":
            q = params.get("q", "")
            m = re.search(r"value='((?:[^'\\]|\\.)*)'", q)
            parent = re.search(r"'([^']+)' in parents", q)
            want = m.group(1).replace("\\'", "'") if m else None
            hits = [{"id": f["id"]} for f in self.files.values()
                    if self._key_of(f) == want and not f["trashed"]
                    and parent and parent.group(1) in f["parents"]]
            return httpx.Response(200, json={"files": hits})
        m = re.match(r"^/drive/v3/files/([^/]+)$", path)
        if m:
            f = self.files.get(m.group(1))
            if f is None:
                return httpx.Response(404, json={"error": "notFound"})
            if self._key_of(f) in self.denied:
                return httpx.Response(403, json={"error": "forbidden"})
            if request.method == "DELETE":
                del self.files[f["id"]]
                return httpx.Response(204)
            if params.get("alt") == "media":
                return httpx.Response(200, content=f["data"])
            return httpx.Response(200, json=self._info(f))
        return httpx.Response(404)

    def _by_key(self, key):
        return next(f for f in self.files.values() if (self._key_of(f) or "").endswith(key))

    def mutate(self, key, data):
        f = self._by_key(key)
        f["data"], f["rev"] = data, "rev-" + uuid.uuid4().hex[:6]

    def remove(self, key):
        self.files.pop(self._by_key(key)["id"])

    def replace(self, key):
        f = self._by_key(key)
        f["rev"] = "rev-" + uuid.uuid4().hex[:6]

    def deny(self, key):
        self.denied.add(self._key_of(self._by_key(key)))


# ═════════════════════════════════════════════════════════════════ Synology
class FakeSynology(_Base):
    ENDPOINT = "https://nas.fake.local:5001"

    def __init__(self, *, share="BEG_Work", root="tenant-beg", account="beg-sync",
                 password="fake-nas-password-please-never-log"):
        super().__init__()
        self.account, self.password = account, password
        self.sids: Set[str] = set()
        self.dirs: Set[str] = {"/" + share, "/%s/%s" % (share, root)} if root else {"/" + share}
        self.files: Dict[str, Dict[str, Any]] = {}
        self.expire_next_session = False

    def credentials(self, **override):
        creds = {"password": self.password}
        creds.update(override)
        return creds

    def _ok(self, data=None):
        return httpx.Response(200, json={"success": True, "data": data or {}})

    def _err(self, code):
        return httpx.Response(200, json={"success": False, "error": {"code": code}})

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/webapi/auth.cgi":
            if request.method == "POST":
                form = dict(parse_qsl(request.content.decode()))
                if form.get("account") != self.account or form.get("passwd") != self.password:
                    return self._err(400)
                sid = "sid-" + uuid.uuid4().hex
                self.sids.add(sid)
                return self._ok({"sid": sid})
            self.sids.discard(dict(request.url.params).get("_sid"))
            return self._ok()
        params = dict(request.url.params)
        if params.get("_sid") not in self.sids:
            return self._err(119)
        if self.expire_next_session:
            self.expire_next_session = False
            self.sids.discard(params["_sid"])
            return self._err(119)
        api = params.get("api")
        if api == "SYNO.FileStation.List":
            path = json.loads(params["path"])[0]
            if path in self.denied:
                return self._ok({"files": [{"path": path, "code": 407}]})
            if path in self.dirs:
                return self._ok({"files": [{"path": path, "isdir": True, "additional": {}}]})
            f = self.files.get(path)
            if f is None:
                return self._ok({"files": [{"path": path, "code": 408}]})
            return self._ok({"files": [{"path": path, "isdir": False, "additional": {
                "size": len(f["data"]), "time": {"mtime": f["mtime"]}}}]})
        if api == "SYNO.FileStation.Upload":
            ctype = request.headers["content-type"]
            msg = email.parser.BytesParser().parsebytes(
                b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + request.content)
            fields, payload, name = {}, None, None
            for part in msg.get_payload():
                disp = part.get("content-disposition", "")
                pname = re.search(r'name="([^"]+)"', disp).group(1)
                if pname == "file":
                    payload = part.get_payload(decode=True)
                    name = re.search(r'filename="([^"]+)"', disp).group(1)
                else:
                    fields[pname] = part.get_payload(decode=True).decode()
            folder = fields["path"]
            if folder in self.denied or not folder.startswith(min(self.dirs, key=len)):
                return self._err(407)
            target = folder + "/" + name
            if target in self.files and fields.get("overwrite") == "false":
                return self._err(414)
            parts = folder.split("/")
            for i in range(2, len(parts) + 1):
                self.dirs.add("/".join(parts[:i]))
            self.files[target] = {"data": payload, "mtime": int(time.time() * 1000)}
            return self._ok()
        if api == "SYNO.FileStation.Download":
            path = params["path"]
            if path in self.denied:
                return self._err(407)
            f = self.files.get(path)
            if f is None:
                return self._err(408)
            return httpx.Response(200, content=f["data"],
                                  headers={"content-type": "application/octet-stream"})
        if api == "SYNO.FileStation.Delete":
            path = json.loads(params["path"])[0]
            if path in self.denied:
                return self._err(407)
            if self.files.pop(path, None) is None:
                return self._err(408)
            return self._ok()
        return self._err(102)

    def _path(self, key):
        return next(p for p in self.files if p.endswith("/" + key))

    def mutate(self, key, data):
        p = self._path(key)
        self.files[p] = {"data": data, "mtime": self.files[p]["mtime"] + 1}

    def remove(self, key):
        self.files.pop(self._path(key))

    def replace(self, key):
        self.files[self._path(key)]["mtime"] += 7

    def deny(self, key):
        self.denied.add(self._path(key))


# ═══════════════════════════════════════════════════════════════════ WebDAV
class FakeWebDAV(_Base):
    ENDPOINT = "https://files.fake.local/dav"

    def __init__(self, *, collection="beg", root="tenant-beg", account="beg-sync",
                 password="fake-dav-password-please-never-log", oc_checksum=False):
        super().__init__()
        self.account, self.password = account, password
        self.collections: Set[str] = {collection, "%s/%s" % (collection, root)} if root \
            else {collection}
        self.files: Dict[str, Dict[str, Any]] = {}
        self.oc_checksum = oc_checksum

    def credentials(self, **override):
        creds = {"password": self.password}
        creds.update(override)
        return creds

    def handle(self, request: httpx.Request) -> httpx.Response:
        expected = "Basic " + base64.b64encode(
            ("%s:%s" % (self.account, self.password)).encode()).decode()
        if request.headers.get("authorization") != expected:
            return httpx.Response(401)
        path = unquote(request.url.path)[len("/dav/"):]
        if path in self.denied:
            return httpx.Response(403)
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        if request.method == "PROPFIND":
            return httpx.Response(207) if path in self.collections or path in self.files \
                else httpx.Response(404)
        if request.method == "MKCOL":
            if path in self.collections:
                return httpx.Response(405)
            if parent not in self.collections:
                return httpx.Response(409)
            self.collections.add(path)
            return httpx.Response(201)
        if request.method == "PUT":
            if parent not in self.collections:
                return httpx.Response(409)
            if path in self.files and request.headers.get("if-none-match") == "*":
                return httpx.Response(412)
            self.files[path] = {"data": request.content, "etag": uuid.uuid4().hex}
            return httpx.Response(201, headers={"etag": '"%s"' % self.files[path]["etag"]})
        f = self.files.get(path)
        if f is None:
            return httpx.Response(404)
        if request.method == "HEAD":
            headers = {"content-length": str(len(f["data"])), "etag": '"%s"' % f["etag"]}
            if self.oc_checksum:
                headers["oc-checksum"] = "SHA256:" + hashlib.sha256(f["data"]).hexdigest()
            return httpx.Response(200, headers=headers)
        if request.method == "GET":
            return httpx.Response(200, content=f["data"])
        if request.method == "DELETE":
            del self.files[path]
            return httpx.Response(204)
        return httpx.Response(405)

    def _path(self, key):
        return next(p for p in self.files if p.endswith("/" + key))

    def mutate(self, key, data):
        self.files[self._path(key)] = {"data": data, "etag": uuid.uuid4().hex}

    def remove(self, key):
        self.files.pop(self._path(key))

    def replace(self, key):
        self.files[self._path(key)]["etag"] = uuid.uuid4().hex

    def deny(self, key):
        self.denied.add(self._path(key))


# ══════════════════════════════════════════════════════════════ the matrix
def build(kind: str, org_id: str = "BEG", binding_id: str = "bind-1", **backend_kw):
    """``(backend, ProviderBinding, credentials)`` for one provider kind."""
    from app.files import models as m
    from app.files.providers.base import ProviderBinding
    if kind == m.PROVIDER_S3_COMPATIBLE:
        be = FakeS3(**backend_kw)
        b = ProviderBinding(binding_id=binding_id, org_id=org_id, provider_kind=kind,
                            container=be.bucket, root_prefix="tenants/beg", endpoint=be.ENDPOINT,
                            account=be.access_key, secret_reference="cred_test")
    elif kind == m.PROVIDER_GOOGLE_DRIVE:
        be = FakeDrive(**backend_kw)
        b = ProviderBinding(binding_id=binding_id, org_id=org_id, provider_kind=kind,
                            container=be.root_id, endpoint=be.ENDPOINT, account="beg@fake.local",
                            secret_reference="cred_test")
    elif kind == m.PROVIDER_SYNOLOGY_NAS:
        be = FakeSynology(**backend_kw)
        b = ProviderBinding(binding_id=binding_id, org_id=org_id, provider_kind=kind,
                            container="BEG_Work", root_prefix="tenant-beg", endpoint=be.ENDPOINT,
                            account=be.account, secret_reference="cred_test")
    elif kind == m.PROVIDER_ON_PREM_SERVER:
        be = FakeWebDAV(**backend_kw)
        b = ProviderBinding(binding_id=binding_id, org_id=org_id, provider_kind=kind,
                            container="beg", root_prefix="tenant-beg", endpoint=be.ENDPOINT,
                            account=be.account, secret_reference="cred_test")
    else:
        raise KeyError(kind)
    return be, b, be.credentials()


SECRET_MARKERS = ("please-never-log", "fake-secret-key")
