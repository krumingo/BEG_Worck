"""
W0-06B — the one HTTP path of every storage provider adapter.

Every customer-managed provider BEG_Work supports is an HTTP API (S3, Google
Drive, Synology File Station, WebDAV). This module is the single place where an
adapter's request becomes a network call, and the single place where an HTTP
answer becomes one of the FLOW-016 states the registry has to tell apart:

* 401 — the provider does not accept these credentials
  (:class:`~app.files.providers.base.ProviderCredentialsInvalid`);
* 403 — the account is known but may not do this (``permission_denied``);
* 404 — there is no object here (``missing``);
* 408 / 429 / 5xx / a connection or timeout error — the provider cannot be
  reached right now (``provider_unreachable``).

The transport is INJECTED. Production passes nothing and gets ``httpx``'s
network transport; the W0-06B tests pass an in-process ``httpx.MockTransport``
fake, so this task never reaches a real NAS, Drive or bucket. Error messages
never carry the URL or a header: a pre-signed URL or a bearer token in an
exception text would leak through logs.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

import httpx

from app.files.models import AVAILABILITY_PROVIDER_UNREACHABLE
from app.files.providers.base import (
    ProviderCredentialsInvalid,
    ProviderError,
    ProviderObjectMissing,
    ProviderPermissionDenied,
)

DEFAULT_TIMEOUT_SECONDS = 30.0


class ProviderHttp:
    """A small async HTTP client bound to one adapter instance."""

    def __init__(self, transport: Any = None, *, timeout: float = DEFAULT_TIMEOUT_SECONDS):
        self._client = httpx.AsyncClient(transport=transport, timeout=timeout,
                                         follow_redirects=False)

    async def request(self, method: str, url: str, *, headers: Optional[Mapping[str, str]] = None,
                      params: Any = None, content: Optional[bytes] = None, data: Any = None,
                      files: Any = None, json: Any = None) -> httpx.Response:
        try:
            return await self._client.request(method, url, headers=dict(headers or {}),
                                              params=params, content=content, data=data,
                                              files=files, json=json)
        except httpx.TimeoutException:
            raise ProviderError("provider timed out", code="TIMEOUT") from None
        except httpx.HTTPError:
            raise ProviderError("provider unreachable", code="UNREACHABLE") from None

    async def aclose(self) -> None:
        await self._client.aclose()


def raise_for_status(response: httpx.Response, *, what: str = "request") -> httpx.Response:
    """Turn a non-success answer into the FLOW-016 state it means. 2xx/3xx pass."""
    status = response.status_code
    if status < 400:
        return response
    if status == 401:
        raise ProviderCredentialsInvalid("%s: credentials rejected" % what, code="HTTP_401")
    if status == 403:
        raise ProviderPermissionDenied("%s: permission denied" % what, code="HTTP_403")
    if status == 404:
        raise ProviderObjectMissing("%s: not found" % what, code="HTTP_404")
    if status in (408, 429) or status >= 500:
        raise ProviderError("%s: provider unavailable" % what,
                            availability=AVAILABILITY_PROVIDER_UNREACHABLE, code="HTTP_%d" % status)
    raise ProviderError("%s: provider refused" % what, code="HTTP_%d" % status)
