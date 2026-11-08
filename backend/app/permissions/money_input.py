"""
SEC-01-C03 — the amount and the repeated request of a money write.

Package: ``docs/architecture/tasks/SEC-01-C03_PAYMENT_AMOUNT_IDEMPOTENCY.md`` (CLAUDE.md
§14: validation/DQ and an idempotency key on every consequential write; FLOW-006; R14,
R16). The audit of PR #69 @ f33b2ba proved two defects on ``POST /subcontractor-payments``:

1. ``amount: "nan" | "inf" | "1e309"`` passed ``float(...) <= 0`` and a NaN/Infinity
   Outflow row was written to ``finance_payments``, then the response failed with 500;
2. two identical POSTs wrote two Outflow rows (a plain retry = a double payment).

``money_value`` — a money/quantity field must be a JSON number, finite and > 0
(``allow_zero`` for an optional tax part); the rule of PR #70 (``app/services/money_amount``,
FG-47). Anything else -> 422, raised before any write. The canon and the models define no
upper limit, so only finiteness is required.

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
  no key                    -> 428 ``IDEMPOTENCY_KEY_REQUIRED``, nothing written
                               (R29, Krum 06.11.2026: a money write without a key is refused;
                               SEC-01-C03 addendum A).

The key is scoped per tenant, per action and per user: another user's key never
replays (or reveals) someone else's response.
"""
import contextlib
import json
import uuid
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

from app.audit.idempotency import (
    IDEMPOTENCY_DUPLICATE, IDEMPOTENCY_STARTED, request_fingerprint,
)
from app.db import db
from app.permissions.workflow import RecoverableWrite
from app.services.money_amount import is_number, positive_amount

ERROR_IDEMPOTENCY_IN_PROGRESS = "IDEMPOTENCY_IN_PROGRESS"
ERROR_MONEY_WRITE_FAILED = "MONEY_WRITE_FAILED"
_PAYLOAD_PREFIX = "json:"   # a result_reference that carries the whole replay response
ERROR_KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"
MAX_KEY_LENGTH = 200

_NS = uuid.UUID("7d6c3f0e-5c1a-4f43-9a51-5ec01c03a001")


def money_value(value: Any, field: str = "amount", *, allow_zero: bool = False,
                places: Optional[int] = 2) -> float:
    """``value`` as a finite float > 0 (``>= 0`` with ``allow_zero``), else 422.

    SEC-01-C03-B (FG-47): the SAME rule as PR #70 (``app/services/money_amount.py``, copied
    byte for byte so the two PRs merge without conflict): only a JSON number — a string
    (numeric text too), a boolean, None, a list, NaN, ±Infinity and 1e309 are refused.

    SEC-01-C03-H (Codex F-69-04): a MONEY value has at most ``places`` (2) decimal places —
    one canonical amount in whole cents for validation, the certified-cap reservation, the
    allocation and the ledger. A finer amount (``0.004``, ``10.125``) is refused with 422
    before any write — never rounded silently (rounding each sub-cent increment to 0 let
    many of them pass a cap). ``places=None`` for quantities that are not money (hours, qty).
    """
    if allow_zero and is_number(value) and value == 0:
        return 0.0
    amount = positive_amount(value, field)
    if places is not None and Decimal(str(value)).as_tuple().exponent < -places:
        raise HTTPException(status_code=422, detail=(
            "Сумата може да има най-много %d знака след десетичната запетая" % places
            + ("" if field == "amount" else " (%s)" % field)))
    return amount


async def project_in_tenant(tenant, project_id: Any) -> None:
    """SEC-01-C03-B (FG-29): ``project_id`` must name a project of THIS tenant, else nothing
    is written — 422 when it is missing, 404 when no such project exists here (a project of
    another tenant is "missing", never revealed). ``tenant`` is the request's TenantData."""
    if not isinstance(project_id, str) or not project_id.strip():
        raise HTTPException(status_code=422, detail={
            "error_code": "PROJECT_REQUIRED", "message": "Обектът (project_id) е задължителен"})
    if not await tenant.projects.find_one({"id": project_id}, {"_id": 0, "id": 1}):
        raise HTTPException(status_code=404, detail="Project not found")


# SEC-01-C03-B (FG-15): money keys of a labor row (the same set as SEC-02's LABOR_MONEY_FIELDS).
LABOR_MONEY_FIELDS = frozenset({"hourly_rate", "labor_cost"})


async def labor_money_visible(request, user: Dict[str, Any]) -> bool:
    """FG-15 / R20-5: may this caller see the rate and cost of a labor row?

    R16 lets a member SiteManager/Technician WRITE labor, but the employee's rate and the
    cost are money. off/shadow: the legacy finance roles. enforce: the Permission Service on
    ``labor.entry.create`` at COMPANY scope — only a company assignment (Owner/Admin/
    Accountant) holds it there; an R16 member holds it only on the project-scope mirror,
    which never covers a company-level request (``service._scope_covers``). No denial audit:
    a hidden value is not a refused action.
    """
    from app.permissions.deps import current_mode, MODE_ENFORCE
    from app.permissions.money_write import FINANCE_WRITE_ROLES
    if current_mode() != MODE_ENFORCE:
        return user.get("role") in FINANCE_WRITE_ROLES
    from app.tenancy.guard import get_tenant_context
    from app.permissions.service import evaluate_permission
    ctx = await get_tenant_context(request, user)
    decision = await evaluate_permission(ctx, "labor.entry.create", module=None,
                                         scope_type=None, scope_id=None)
    return bool(decision.allowed)


def without_labor_money(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {k: v for k, v in row.items() if k not in LABOR_MONEY_FIELDS}


class MoneyWrite:
    """One money POST under an optional ``Idempotency-Key``.

    Usage in a handler (after validation and the reads, right before the writes)::

        mw = await MoneyWrite.begin(user, "finance.x.create", idempotency_key, body)
        if mw.replay_id:
            return await tenant.x.find_one({"id": mw.replay_id}, {"_id": 0})
        async with mw:
            doc = {"id": mw.new_id("row"), ...}
            async with mw.insert_once():
                await tenant.x.insert_one(mw.unique(doc))
            mw.result_id = doc["id"]
        return doc

    A route whose answer is computed (sync / recompute / compute) sets ``mw.result_payload``
    instead and replays it with ``mw.replay_payload()``.
    """

    def __init__(self, user: Dict[str, Any], action: str, key: Optional[str]):
        self.user = user
        self.action = action
        self.key = key
        self.wf: Optional[RecoverableWrite] = None
        self.replay_id: Optional[str] = None
        self.result_id: Optional[str] = None
        self.result_payload: Any = None

    @classmethod
    async def begin(cls, user: Dict[str, Any], action: str, raw_key: Optional[str],
                    body: Any) -> "MoneyWrite":
        key = (raw_key or "").strip()
        if len(key) > MAX_KEY_LENGTH:
            raise HTTPException(status_code=422, detail={
                "error_code": "IDEMPOTENCY_KEY_INVALID",
                "message": "Idempotency-Key is longer than %d characters" % MAX_KEY_LENGTH})
        if not key:
            # R29 (Krum 06.11.2026): a money write without a key is refused — it could
            # not be told apart from its own retry (a double payment). Nothing is written.
            raise HTTPException(status_code=428, detail={
                "error_code": ERROR_KEY_REQUIRED,
                "message": "Записът на пари изисква заглавие Idempotency-Key"})
        mw = cls(user, action, "%s:%s" % (user["id"], key))
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

    def unique(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """SEC-01-C03-C (F-69-01): the key-derived ``id`` becomes the document's ``_id``.

        ``_id`` is unique in every MongoDB collection, so two attempts of the same key —
        a resumed FAILED one, or several concurrent retries — can never both insert the
        row. No separate "does it exist?" read (that read raced: Codex F-69-01)."""
        doc["_id"] = doc["id"]
        return doc

    @contextlib.asynccontextmanager
    async def insert_once(self):
        """Wrap ONE ``insert_one(mw.unique(doc))``: a duplicate ``_id`` means this key's row
        is already there (an earlier or concurrent attempt) — not an error. Any other
        duplicate (another unique index) is re-raised."""
        try:
            yield
        except DuplicateKeyError as exc:
            pattern = (getattr(exc, "details", None) or {}).get("keyPattern") or {}
            if set(pattern) != {"_id"}:
                raise

    def replay_payload(self) -> Any:
        """The stored response of a completed computed write (``result_payload``)."""
        ref = self.replay_id or ""
        if not ref.startswith(_PAYLOAD_PREFIX):
            return None
        return json.loads(ref[len(_PAYLOAD_PREFIX):])

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
            reference = self.result_id
            if self.result_payload is not None:
                reference = _PAYLOAD_PREFIX + json.dumps(self.result_payload, default=str,
                                                         ensure_ascii=False, sort_keys=True)
            await self.wf.complete(reference)
            return False
        await self.wf.fail(ERROR_MONEY_WRITE_FAILED)     # the same request may finish it
        return False
