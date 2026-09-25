"""Read-only GitHub client.

Two properties are structural rather than a matter of discipline at call sites:

* **No writes.** ``ReadOnlyTransport`` raises on any method other than GET or HEAD and
  on any request carrying a body. The prohibition lives in the transport, so no future
  code path -- and no mistake in a caller -- can quietly acquire write access. The app
  has no code that would issue a write; this makes that a guarantee instead of an
  observation.
* **The token stays here.** It is attached per request inside this module. It is never
  returned to a caller, never placed in a projection and never logged.

Conditional requests carry ``If-None-Match``; a 304 costs no GitHub rate-limit budget,
which is what makes a 10-30 s cadence sustainable.
"""

from __future__ import annotations

import base64
import dataclasses
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Protocol

from .gitblob import blob_sha1
from .redact import redact

LOGGER = logging.getLogger("begwork.dashboard")

ALLOWED_METHODS = frozenset({"GET", "HEAD"})
API_ACCEPT = "application/vnd.github+json"
API_VERSION = "2022-11-28"
USER_AGENT = "BEG_WORK-web-dashboard (read-only projection)"


class ReadOnlyViolation(RuntimeError):
    """Raised when something attempts a non-read request. Never caught as 'offline'."""


class TransportError(RuntimeError):
    """A read failed for an ordinary reason: network, DNS, timeout, HTTP error."""

    def __init__(self, message: str, *, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after

    @property
    def is_rate_limited(self) -> bool:
        return self.status in {403, 429}


@dataclasses.dataclass(frozen=True, slots=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def header(self, name: str, default: str = "") -> str:
        lowered = name.lower()
        for key, value in self.headers.items():
            if key.lower() == lowered:
                return value
        return default


class Transport(Protocol):
    """The seam tests substitute. Implementations receive only already-guarded reads."""

    def request(self, method: str, url: str, headers: dict[str, str], timeout: float) -> Response:
        ...


class UrllibTransport:
    """The production transport: stdlib only, no third-party HTTP dependency."""

    def request(self, method: str, url: str, headers: dict[str, str], timeout: float) -> Response:
        request = urllib.request.Request(url, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as reply:
                return Response(reply.status, dict(reply.headers.items()), reply.read())
        except urllib.error.HTTPError as error:
            body = b""
            try:
                body = error.read()
            except Exception:  # pragma: no cover - the error body is a nicety
                pass
            if error.code == 304:
                # Not an error: the resource is unchanged. urllib models it as one.
                return Response(304, dict(error.headers.items()), b"")
            raise TransportError(
                f"HTTP {error.code} for {_safe_url(url)}: {redact(body[:200].decode('utf-8', 'replace'))}",
                status=error.code,
                retry_after=_retry_after(dict(error.headers.items())),
            ) from error
        except urllib.error.URLError as error:
            raise TransportError(f"Network error for {_safe_url(url)}: {error.reason}") from error
        except TimeoutError as error:
            raise TransportError(f"Timeout for {_safe_url(url)}") from error


class ReadOnlyTransport:
    """Wraps any transport and refuses anything that is not a read."""

    def __init__(self, inner: Transport) -> None:
        self._inner = inner

    def request(self, method: str, url: str, headers: dict[str, str], timeout: float) -> Response:
        upper = (method or "").upper()
        if upper not in ALLOWED_METHODS:
            raise ReadOnlyViolation(
                f"{upper or '<empty>'} is not a read. This dashboard is a projection and issues no GitHub writes."
            )
        for name in ("content-length", "content-type", "transfer-encoding"):
            if any(key.lower() == name for key in headers):
                raise ReadOnlyViolation(
                    f"A read request must carry no body, but {name} was set."
                )
        return self._inner.request(upper, url, headers, timeout)


def _retry_after(headers: dict[str, str]) -> float | None:
    for key, value in headers.items():
        if key.lower() == "retry-after":
            try:
                return max(0.0, float(value.strip()))
            except ValueError:
                return None
    for key, value in headers.items():
        # Secondary rate limits use an absolute reset instead of a delay.
        if key.lower() == "x-ratelimit-reset":
            try:
                return max(0.0, float(value.strip()) - time.time())
            except ValueError:
                return None
    return None


def _safe_url(url: str) -> str:
    """A URL fit for a log line: no query string, which could carry a credential."""
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


@dataclasses.dataclass(frozen=True, slots=True)
class FetchedFile:
    """One file read from the branch, with its Git blob identity computed locally."""

    path: str
    content: bytes
    blob_sha: str
    api_reported_sha: str
    etag: str
    from_cache: bool

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")

    def json(self) -> object:
        return json.loads(self.text)


@dataclasses.dataclass(frozen=True, slots=True)
class PullRequestInfo:
    number: int
    head_sha: str
    draft: bool
    state: str
    merged: bool
    html_url: str


class GitHubReadOnlyClient:
    """Conditional reads of files and pull-request metadata. No write path exists."""

    def __init__(
        self,
        repository: str,
        token: str = "",
        api_base: str = "https://api.github.com",
        transport: Transport | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._repository = repository.strip("/")
        self._token = token
        self._api_base = api_base.rstrip("/")
        self._transport = ReadOnlyTransport(transport or UrllibTransport())
        self._timeout = timeout
        # url -> (etag, FetchedFile-or-payload). Lets a 304 reuse the previous bytes.
        self._etags: dict[str, str] = {}
        self._cached: dict[str, object] = {}
        self.request_log: list[tuple[str, str]] = []

    @property
    def repository(self) -> str:
        return self._repository

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": API_ACCEPT,
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": USER_AGENT,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _read(self, url: str) -> tuple[Response, bool]:
        """Issue one conditional GET. Returns the response and whether it was a 304."""
        headers = self._headers()
        cached_etag = self._etags.get(url)
        if cached_etag:
            headers["If-None-Match"] = cached_etag
        self.request_log.append(("GET", url))
        response = self._transport.request("GET", url, headers, self._timeout)
        if response.status == 304:
            return response, True
        etag = response.header("ETag")
        if etag:
            self._etags[url] = etag
        return response, False

    def file(self, path: str, ref: str) -> FetchedFile:
        """Read one file from ``ref``, re-hashing the bytes as a Git blob."""
        url = (
            f"{self._api_base}/repos/{self._repository}/contents/"
            f"{urllib.parse.quote(path)}?ref={urllib.parse.quote(ref, safe='')}"
        )
        response, unchanged = self._read(url)
        if unchanged:
            cached = self._cached.get(url)
            if isinstance(cached, FetchedFile):
                return dataclasses.replace(cached, from_cache=True)
            # A 304 with nothing cached cannot be turned into content honestly.
            raise TransportError(f"304 for {path} but nothing is cached to reuse", status=304)

        payload = json.loads(response.body.decode("utf-8", "replace"))
        if not isinstance(payload, dict) or payload.get("type") != "file":
            raise TransportError(f"{path} on {ref} is not a file")
        encoding = payload.get("encoding")
        if encoding != "base64":
            # The contents API omits content for a blob over 1 MB. Inventing bytes, or
            # treating an empty body as an empty file, would corrupt the blob check.
            raise TransportError(f"{path} was returned with encoding {encoding!r}, not base64")
        content = base64.b64decode(payload.get("content") or "")
        fetched = FetchedFile(
            path=payload.get("path") or path,
            content=content,
            blob_sha=blob_sha1(content),
            api_reported_sha=str(payload.get("sha") or ""),
            etag=response.header("ETag"),
            from_cache=False,
        )
        self._cached[url] = fetched
        return fetched

    def pull_request(self, number: int) -> PullRequestInfo:
        url = f"{self._api_base}/repos/{self._repository}/pulls/{int(number)}"
        response, unchanged = self._read(url)
        if unchanged:
            cached = self._cached.get(url)
            if isinstance(cached, PullRequestInfo):
                return cached
            raise TransportError(f"304 for PR #{number} but nothing is cached to reuse", status=304)

        payload = json.loads(response.body.decode("utf-8", "replace"))
        info = PullRequestInfo(
            number=int(payload.get("number") or 0),
            head_sha=str((payload.get("head") or {}).get("sha") or ""),
            draft=bool(payload.get("draft")),
            state=str(payload.get("state") or ""),
            merged=bool(payload.get("merged")),
            html_url=str(payload.get("html_url") or ""),
        )
        self._cached[url] = info
        return info
