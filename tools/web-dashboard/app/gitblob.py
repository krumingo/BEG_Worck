"""Git blob object identity.

CONTROL_STATE cites its sources by Git *blob* SHA. Trusting the SHA the GitHub API
reports alongside the content would only prove that the API is self-consistent with
itself; it would not prove that the bytes this dashboard actually received are the
bytes that were cited. So the bytes are re-hashed here.

The hash is computed over the exact octets of the blob -- the canonical committed
content. It is never computed over a working-tree file, because a checkout may have
had its line endings rewritten (``core.autocrlf``), which changes the bytes and
therefore the SHA while the commit is untouched. Fixtures must read committed bytes
via ``git cat-file blob``; production reads them from the API, which also serves
canonical blob bytes.
"""

from __future__ import annotations

import hashlib


def blob_sha1(content: bytes) -> str:
    """Return the Git blob SHA-1 of ``content`` as lowercase hex.

    Git hashes ``b"blob <bytelength>\\0" + content``.
    """
    if not isinstance(content, (bytes, bytearray)):
        raise TypeError("blob_sha1 requires bytes; text would depend on an encoding")
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(b"blob %d\0" % len(content))
    digest.update(content)
    return digest.hexdigest()


def sha_equal(left: str | None, right: str | None) -> bool:
    """Case-insensitive comparison that treats a missing SHA as 'not equal'."""
    if not left or not right:
        return False
    return left.strip().lower() == right.strip().lower()


def short(sha: str | None, width: int = 8) -> str:
    if not sha:
        return "—"
    text = sha.strip()
    return text if len(text) <= width else text[:width]
