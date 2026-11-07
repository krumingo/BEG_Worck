"""
AUTH-01 C01 (F-04) — the client IP, trusting proxy headers only from trusted proxies.

``X-Forwarded-For`` / ``X-Real-IP`` are plain request headers: any client can
send them. They are honoured ONLY when the TCP peer is a proxy the operator
listed in ``TRUSTED_PROXIES`` (comma-separated IPs or CIDRs, e.g. the docker
network of the nginx container: ``172.16.0.0/12``). Otherwise the socket peer
address is the client.

With a trusted peer, ``X-Forwarded-For`` is walked from the RIGHT (the hop the
trusted proxy itself appended) and the first address that is not a trusted proxy
is the client — the left-most entries are client-controlled and never used.
"""
import ipaddress
import os
from typing import List, Optional

from fastapi import Request

ENV_TRUSTED_PROXIES = "TRUSTED_PROXIES"


def _networks(raw: Optional[str] = None) -> List[ipaddress._BaseNetwork]:
    raw = os.environ.get(ENV_TRUSTED_PROXIES, "") if raw is None else raw
    nets = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            continue                      # an unparsable entry trusts nothing
    return nets


def _parse(value: Optional[str]):
    try:
        return ipaddress.ip_address((value or "").strip())
    except ValueError:
        return None


def _trusted(addr, nets) -> bool:
    return addr is not None and any(addr in n for n in nets)


def client_ip(request: Request, trusted: Optional[str] = None) -> str:
    """The best client address for rate limiting and security events."""
    peer = request.client.host if request.client else ""
    nets = _networks(trusted)
    peer_addr = _parse(peer)
    if not _trusted(peer_addr, nets):
        return peer or "unknown"
    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [h.strip() for h in forwarded.split(",") if h.strip()]
    for hop in reversed(hops):
        addr = _parse(hop)
        if addr is None:
            break                         # malformed chain: stop, use what we trust
        if not _trusted(addr, nets):
            return str(addr)
    real = _parse(request.headers.get("x-real-ip"))
    if real is not None and not _trusted(real, nets):
        return str(real)
    return peer or "unknown"
