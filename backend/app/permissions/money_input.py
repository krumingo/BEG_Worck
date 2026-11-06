"""
SEC-01-C03 — the amount and the repeated request of a money write.

Package: ``docs/architecture/tasks/SEC-01-C03_PAYMENT_AMOUNT_IDEMPOTENCY.md`` (CLAUDE.md
§14: validation/DQ and an idempotency key on every consequential write; FLOW-006; R14,
R16). The audit of PR #69 @ f33b2ba proved two defects on ``POST /subcontractor-payments``:

1. ``amount: "nan" | "inf" | "1e309"`` passed ``float(...) <= 0`` and a NaN/Infinity
   Outflow row was written to ``finance_payments``, then the response failed with 500;
2. two identical POSTs wrote two Outflow rows (a plain retry = a double payment).

``money_value`` — a money/quantity field must be a FINITE number > 0 (``allow_zero`` for
an optional tax part). Anything else -> 422 ``AMOUNT_INVALID``, raised before any write.
The canon and the models define no upper limit, so only finiteness is required.

``MoneyWrite`` — the ``Idempotency-Key`` header on the canonical W0-04 registry
(``app.audit.idempotency``, collection ``audit_idempotency``) through the same
``RecoverableWrite`` the migrated enforce paths use (``app.permissions.workflow``,
``PUT /users/{id}``):

  same key + same body      -> the original response, no new row;
  same key + different body -> 409 ``IDEMPOTENCY_CONFLICT``, nothing written;
  same key while the first request still runs -> 409 ``IDEMPOTENCY_IN_PROGRESS``;
  a FAILED attempt          -> the same request finishes it: the ids of a keyed write are
                               derived from the key and an insert already done is skipped, so
                               nothing is written twice;
  no key                    -> accepted as before (every request is a new command).

The key is scoped per tenant, per action and per user: another user's key never
replays (or reveals) someone else's response.
"""
import math
import uuid
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import HTTPException

from app.audit.idempotency import (
    IDEMPOTENCY_DUPLICATE, IDEMPOTENCY_STARTED, request_fingerprint,
)
from app.db import db
from app.permissions.workflow import RecoverableWrite

ERROR_AMOUNT_INVALID = "AMOUNT_INVALID"
ERROR_IDEMPOTENCY_IN_PROGRESS = "IDEMPOTENCY_IN_PROGRESS"
ERROR_MONEY_WRITE_FAILED = "MONEY_WRITE_FAILED"
MAX_KEY_LENGTH = 200

_NS = uuid.UUID("7d6c3f0e-5c1a-4f43-9a51-5ec01c03a001")


def _invalid(field: str, allow_zero: bool) -> HTTPException:
    rule = "≥ 0" if allow_zero else "> 0"
    return HTTPException(status_code=422, detail={
        "error_code": ERROR_AMOUNT_INVALID, "field": field,
        "message": "„%s“ трябва да е крайно число %s" % (field, rule)})


def money_value(value: Any, field: str = "amount", *, allow_zero: bool = False) -> float:
    """``value`` as a finite float > 0 (``>= 0`` with ``allow_zero``), else 422.

    Accepts a JSON number or a numeric string (the forms send strings); refuses
    booleans, None, "", NaN, ±Infinity and anything that overflows a float (1e309).
    """
    if value is None or isinstance(value, bool):
        raise _invalid(field, allow_zero)
    try:
        if isinstance(value, (int, float)):
            number = float(value)
        elif isinstance(value, str) and value.strip():
            number = float(value.strip())
        else:
            raise _invalid(field, allow_zero)
    except (ValueError, OverflowError):
        raise _invalid(field, allow_zero) from None
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        raise _invalid(field, allow_zero)
    return number


class MoneyWrite:
    """One money POST under an optional ``Idempotency-Key``.

    Usage in a handler (after validation and the reads, right before the writes)::

        mw = await MoneyWrite.begin(user, "finance.x.create", idempotency_key, body)
        if mw.replay_id:
            return await tenant.x.find_one({"id": mw.replay_id}, {"_id": 0})
        async with mw:
            doc = {"id": mw.new_id("row"), ...}
            if await mw.needs_insert(tenant.x, doc["id"]):
                await tenant.x.insert_one(doc)
            mw.result_id = doc["id"]
        return doc
    """

    def __init__(self, user: Dict[str, Any], action: str, key: Optional[str]):
        self.user = user
        self.action = action
        self.key = key
        self.wf: Optional[RecoverableWrite] = None
        self.replay_id: Optional[str] = None
        self.result_id: Optional[str] = None

    @classmethod
    async def begin(cls, user: Dict[str, Any], action: str, raw_key: Optional[str],
                    body: Any) -> "MoneyWrite":
        key = (raw_key or "").strip()
        if len(key) > MAX_KEY_LENGTH:
            raise HTTPException(status_code=422, detail={
                "error_code": "IDEMPOTENCY_KEY_INVALID",
                "message": "Idempotency-Key is longer than %d characters" % MAX_KEY_LENGTH})
        mw = cls(user, action, ("%s:%s" % (user["id"], key)) if key else None)
        if mw.key is None:
            return mw                                    # no key: the legacy behaviour
        mw.wf = await RecoverableWrite(
            db, tenant_id=user["org_id"], action=action, key=mw.key,
            fingerprint=request_fingerprint(body)).begin()   # 409 on a different body
        state = mw.wf.state
        if mw.wf.already_completed:
            mw.replay_id = mw.wf.completed_reference
        elif (state.get("status") == IDEMPOTENCY_DUPLICATE
              and state.get("prior_status") == IDEMPOTENCY_STARTED):
            raise HTTPException(status_code=409, detail={
                "error_code": ERROR_IDEMPOTENCY_IN_PROGRESS,
                "message": "Същата заявка още се изпълнява; опитайте отново след малко",
                **mw.wf.record_ref})
        return mw

    def new_id(self, name: str) -> str:
        """A fresh id, or — under a key — the SAME id on every attempt of that key."""
        if self.key is None:
            return str(uuid.uuid4())
        return str(uuid.uuid5(_NS, "%s\x1f%s\x1f%s\x1f%s" % (
            self.user["org_id"], self.action, self.key, name)))

    async def needs_insert(self, collection, record_id: str) -> bool:
        """False when a resumed attempt of the same key already inserted ``record_id``.

        The route keeps its own ``insert_one`` (visible to the W0-03E-A1 guard)::

            if await mw.needs_insert(tenant.x, doc["id"]):
                await tenant.x.insert_one(doc)
        """
        if self.key is None:
            return True
        return not await collection.find_one({"id": record_id}, {"_id": 0, "id": 1})

    async def step(self, name: str, fn: Callable[[], Awaitable[Any]]) -> None:
        """A non-insert side effect (audit row, totals) done once per key."""
        if self.wf is None:
            await fn()
            return
        await self.wf.step(name, fn)

    async def __aenter__(self) -> "MoneyWrite":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if self.wf is None:
            return False
        if exc is None:
            await self.wf.complete(self.result_id)
            return False
        await self.wf.fail(ERROR_MONEY_WRITE_FAILED)     # the same request may finish it
        return False
