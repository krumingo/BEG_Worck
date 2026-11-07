"""
AUTH-01 C01 (F-01) — one MongoDB transaction per multi-document auth change.

A password reset, an owner recovery and a reset-link state change each touch
several documents (the token rows, the user, the audit row). They must commit
together or not at all: a failure leaves the old password, the old tokens and
no audit row — never a changed password with a still-open link or a missing
audit trail.

MongoDB multi-document transactions need a replica set (or a sharded cluster).
Production runs on MongoDB Atlas, which is a replica set. On a deployment that
cannot run transactions — a bare standalone ``mongod`` — these operations are
REFUSED (:class:`TransactionsUnavailable`) before anything is written. There is
deliberately no non-transactional fallback: the whole point is that a partial
outcome cannot happen.

Usage::

    async def body(session):
        await coll.update_one(..., session=session)
        await log_audit(..., session=session)
    await run_in_transaction(db, body)

``body`` may run more than once (the driver retries a transient conflict), so
it must derive everything from the database inside the transaction and must not
have side effects outside it.
"""
from typing import Any, Awaitable, Callable


class TransactionsUnavailable(RuntimeError):
    """The database cannot run multi-document transactions; nothing was written."""


async def transactions_supported(db) -> bool:
    """True on a replica set member or a mongos router."""
    try:
        hello = await db.command("hello")
    except Exception:
        try:
            hello = await db.command("isMaster")
        except Exception:
            return False
    return bool(hello.get("setName")) or hello.get("msg") == "isdbgrid"


async def run_in_transaction(db, body: Callable[[Any], Awaitable[Any]]) -> Any:
    """Run ``body(session)`` inside one transaction and return its result.

    Raises :class:`TransactionsUnavailable` (nothing written) when the
    deployment cannot run transactions. Any exception from ``body`` aborts the
    transaction and propagates unchanged.
    """
    if not await transactions_supported(db):
        raise TransactionsUnavailable(
            "MongoDB multi-document transactions are not available on this deployment "
            "(a replica set is required)")
    async with await db.client.start_session() as session:
        return await session.with_transaction(body)
