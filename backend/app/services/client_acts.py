"""
ACT-01 — a client act is acted against the offer: price and contracted quantity from the
offer line, a remainder per line, never the same quantity twice (FLOW-004, FG-106).

Package: ``docs/architecture/tasks/ACT-01_CLIENT_ACT_FROM_OFFER.md``. Canon (FLOW-004,
BUSINESS LOCK) — "Какво НЕ трябва да позволява този FLOW":

* "акт над договорения обхват при крайна цена"      -> 409 ``ACT_EXCEEDS_REMAINING``;
* "различна единична цена в акт без анекс"          -> 422 ``UNIT_PRICE_MISMATCH``;
* "акт по допълнително СМР без договорно основание" -> every act line names an offer line
  of an ACCEPTED offer (main or additional, ``offer_type`` "extra") of the SAME project and
  tenant, resolved on the server; anything else -> 422 ``OFFER_LINE_REQUIRED`` /
  ``OFFER_LINE_NOT_FOUND``;
* "стар акт да се редактира тихо след одобрение"    -> only a Draft is edited (400
  ``ACT_NOT_DRAFT``); a correction of an accepted act is debt (no model yet);
* "едно и също количество да се актува два пъти"    -> a reservation per offer line.

The remainder (fixed_price — the only actuation mode the model has; FLOW-004 also names
remeasurement, which has no field anywhere, so fixed_price is assumed and the gap is debt):

    acted(line) = Σ executed_qty of that offer line over EVERY act of the tenant
                  (drafts included; there is no annulment state for an act)
    acted(line) + new ≤ offer qty

How it is kept under concurrency. ``client_act_line_totals`` holds one document per offer
line with the acted quantity in integer units of 1/10 000 (no float drift between 3+3+4 and
10). It is a guard, not a second source of truth: it is created from the acts themselves
the first time a line is touched (so acts made before ACT-01 count), and afterwards it
changes only in the SAME MongoDB transaction that writes the act — a conditional ``$inc``
(``acted ≤ cap − delta``) — so the act and its reservation commit together or not at all.
Two transactions on the same line conflict; the driver retries the loser, which then sees
the winner's total.

The act number comes from one counter per tenant (``org_counters``, ``counter_type``
"client_act_number"), incremented in the same transaction; on first use it starts after
the highest existing ``ACT-NNNN`` of the tenant. A unique index on (org_id, act_number)
for acts numbered by the counter (``number_source`` "counter") backs it.

One canonical W0-04 AuditEvent (``client_act.created`` / ``client_act.updated``, FLOW-004,
retention R1) is appended in the same transaction.

Repeated requests: the ``Idempotency-Key`` (R29) is reserved on the shared W0-04 registry
(``app.audit.idempotency`` through ``app.permissions.workflow.RecoverableWrite``, the same
mechanism PR #69/#70 use): same key + same body -> the stored answer; same key + another
body -> 409 ``IDEMPOTENCY_CONFLICT``; still running -> 409 ``IDEMPOTENCY_IN_PROGRESS``;
no key -> 428 ``IDEMPOTENCY_KEY_REQUIRED``. The id of a created act is derived from the key,
so a retry of a FAILED attempt whose transaction did commit finds that act instead of
writing a second one.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.audit.idempotency import IDEMPOTENCY_DUPLICATE, IDEMPOTENCY_STARTED, request_fingerprint
from app.permissions.workflow import RecoverableWrite
from app.services.auth_tx import TransactionsUnavailable, run_in_transaction
from app.tenancy.data_access import TenantData

TOTALS = "client_act_line_totals"
COUNTER_TYPE = "client_act_number"
NUMBER_SOURCE = "counter"
QTY_SCALE = 10_000                    # quantities are compared in 1/10 000 of a unit
PRICE_TOLERANCE = 0.005               # prices are kept to the cent (offers round to 2)
VAT_PERCENT = 20                      # unchanged from the pre-ACT-01 code
ACCEPTED = "Accepted"
DRAFT = "Draft"
MAX_KEY_LENGTH = 200
MAX_TXN_ATTEMPTS = 5
_NS = uuid.UUID("a0c7f1e2-4b3d-4c5a-9e01-ac7010000001")
_ACT_NO = re.compile(r"^ACT-(\d+)$")

ACTION_CREATE = "revenue.client_act.create"
ACTION_UPDATE = "finance.client_act.update"
ACTION_FROM_OFFER = "finance.client_act_from_offer.execute"
ACTION_REMAINING_READ = "finance.client_act_remaining.read"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _err(status: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(status_code=status, detail={"error_code": code, "message": message,
                                                     **extra})


def q(value: float) -> int:
    """A quantity in integer units of 1/QTY_SCALE."""
    return int(round(float(value) * QTY_SCALE))


def unq(units: int) -> float:
    return round(units / QTY_SCALE, 4)


def _number(value: Any, field: str, *, positive: bool = True) -> float:
    """A JSON number, finite (and > 0 unless ``positive`` is False), else 422."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise _err(422, "QTY_INVALID" if field != "unit_price" else "UNIT_PRICE_INVALID",
                   "Полето %s трябва да е число" % field, field=field)
    if positive and value <= 0:
        raise _err(422, "QTY_INVALID", "Количеството (%s) трябва да е по-голямо от 0" % field,
                   field=field)
    return float(value)


def offer_unit_price(offer_line: Dict[str, Any]) -> float:
    """The unit price of an offer line (the same formula the pre-ACT-01 from-offer used)."""
    return round(float(offer_line.get("material_unit_cost") or 0)
                 + float(offer_line.get("labor_unit_cost") or 0), 2)


# ═══════════════════════════════════════════════════════════════════ idempotency (R29)
def require_key(raw: Optional[str]) -> str:
    key = (raw or "").strip()
    if len(key) > MAX_KEY_LENGTH:
        raise _err(422, "IDEMPOTENCY_KEY_INVALID",
                   "Idempotency-Key е по-дълъг от %d знака" % MAX_KEY_LENGTH)
    if not key:
        # R29 (Krum 06.11.2026): a money write without a key is refused.
        raise _err(428, "IDEMPOTENCY_KEY_REQUIRED",
                   "Записът на акт изисква заглавие Idempotency-Key")
    return key


class KeyedWrite:
    """One ACT-01 write under its Idempotency-Key (W0-04 registry, RecoverableWrite)."""

    _PAYLOAD = "json:"

    def __init__(self, database, user: Dict[str, Any], action: str, raw_key: Optional[str]):
        self.database = database
        self.user = user
        self.action = action
        self.key = "%s:%s" % (user["id"], require_key(raw_key))   # per user (as #69)
        self.wf: Optional[RecoverableWrite] = None

    @property
    def key_ref(self) -> str:
        """A hash of the scoped key, stored on the act an update changed (no raw key)."""
        return hashlib.sha256(("%s\x1f%s" % (self.action, self.key)).encode()).hexdigest()[:32]

    def derived_id(self, name: str) -> str:
        return str(uuid.uuid5(_NS, "%s\x1f%s\x1f%s\x1f%s" % (
            self.user["org_id"], self.action, self.key, name)))

    async def begin(self, fingerprint_payload: Any) -> Optional[Any]:
        """Reserve the key. Returns the stored answer of a completed request, else None."""
        self.wf = await RecoverableWrite(
            self.database, tenant_id=self.user["org_id"], action=self.action, key=self.key,
            fingerprint=request_fingerprint(fingerprint_payload)).begin()   # 409 on a new body
        if self.wf.already_completed:
            ref = self.wf.completed_reference or ""
            if ref.startswith(self._PAYLOAD):
                return json.loads(ref[len(self._PAYLOAD):])
            return None
        state = self.wf.state
        if (state.get("status") == IDEMPOTENCY_DUPLICATE
                and state.get("prior_status") == IDEMPOTENCY_STARTED):
            raise _err(409, "IDEMPOTENCY_IN_PROGRESS",
                       "Същата заявка още се изпълнява; опитайте отново след малко",
                       **self.wf.record_ref)
        return None

    async def run(self, fingerprint_payload: Any, write) -> Any:
        """Reserve the key, perform ``write()`` once, store its answer.

        Any failure — of the write or of storing the answer — marks the key FAILED, so the
        SAME request may be repeated: a committed act is then found by its key-derived id
        (``create_act``) or by its applied key (``update_act``) and nothing is written twice.
        A process killed between the commit and the mark leaves the key STARTED (409
        IDEMPOTENCY_IN_PROGRESS for that key) — the same limit as PR #69 (HANDOFF debt)."""
        replay = await self.begin(fingerprint_payload)
        if replay is not None:
            return replay
        try:
            result = await write()
            await self.complete(result)
        except BaseException as exc:
            await self.fail(exc)
            raise
        return result

    async def complete(self, payload: Any) -> None:
        await self.wf.complete(self._PAYLOAD + json.dumps(payload, default=str,
                                                          ensure_ascii=False, sort_keys=True))

    async def fail(self, exc: BaseException) -> None:
        code = "CLIENT_ACT_WRITE_FAILED"
        if isinstance(exc, HTTPException) and isinstance(exc.detail, dict):
            code = exc.detail.get("error_code") or code
        await self.wf.fail(code)


# ═══════════════════════════════════════════════════════════════════ offer resolution
async def resolve_offer_lines(tenant: TenantData, project_id: str, line_ids: List[str],
                              session=None) -> Dict[str, Tuple[Dict, Dict]]:
    """``{offer_line_id: (offer, offer_line)}`` for lines of ACCEPTED offers of this project
    and tenant. A line found nowhere (another tenant, another project, a draft / sent /
    rejected offer, a typo) is absent — the caller answers 422 without saying which."""
    wanted = sorted(set(line_ids))
    if not wanted:
        return {}
    out: Dict[str, Tuple[Dict, Dict]] = {}
    cursor = tenant.offers.find({"project_id": project_id, "status": ACCEPTED,
                                 "lines.id": {"$in": wanted}}, {"_id": 0}, session=session)
    async for offer in cursor:
        for ol in offer.get("lines") or []:
            if ol.get("id") in wanted and ol.get("id") not in out:
                out[ol["id"]] = (offer, ol)
    return out


def build_lines(raw_lines: List[Dict[str, Any]], resolved: Dict[str, Tuple[Dict, Dict]],
                keep_ids: bool = False) -> List[Dict[str, Any]]:
    """The stored act lines: everything money-relevant from the offer line."""
    lines = []
    for n, raw in enumerate(raw_lines):
        offer, ol = resolved[raw["offer_line_id"]]
        price = offer_unit_price(ol)
        contracted = float(ol.get("qty") or 0)
        executed = raw["executed_qty"]
        line_id = raw.get("id") if keep_ids and isinstance(raw.get("id"), str) and raw.get("id") else None
        lines.append({
            "id": line_id or str(uuid.uuid4()),
            "offer_id": offer["id"],
            "offer_line_id": ol["id"],
            "activity_code": ol.get("activity_code"),
            "activity_name": ol.get("activity_name", ""),
            "unit": ol.get("unit", "m2"),
            "contracted_qty": contracted,
            "executed_qty": executed,
            "executed_percent": round(executed / contracted * 100, 1) if contracted > 0 else 0,
            "unit_price": price,
            "line_total": round(executed * price, 2),
            "note": raw.get("note"),
            "sort_order": n,
        })
    return lines


def validate_raw_lines(raw_lines: Any) -> List[Dict[str, Any]]:
    """Shape-only checks (no database): every line names an offer line and a quantity."""
    if raw_lines is None:
        return []
    if not isinstance(raw_lines, list):
        raise _err(422, "LINES_INVALID", "Редовете на акта трябва да са списък")
    out = []
    for raw in raw_lines:
        if not isinstance(raw, dict):
            raise _err(422, "LINES_INVALID", "Всеки ред на акта трябва да е обект")
        olid = raw.get("offer_line_id")
        if not isinstance(olid, str) or not olid.strip():
            raise _err(422, "OFFER_LINE_REQUIRED",
                       "Всеки ред на акта трябва да е свързан с ред от приета оферта или "
                       "допълнителна оферта на обекта (договорно основание)")
        executed = _number(raw.get("executed_qty"), "executed_qty")
        line = {"offer_line_id": olid, "executed_qty": executed, "note": raw.get("note"),
                "id": raw.get("id")}
        if raw.get("unit_price") is not None:
            line["unit_price"] = _number(raw.get("unit_price"), "unit_price", positive=False)
        if raw.get("contracted_qty") is not None:
            line["contracted_qty"] = _number(raw.get("contracted_qty"), "contracted_qty",
                                             positive=False)
        out.append(line)
    return out


def check_against_offer(raw_lines: List[Dict[str, Any]],
                        resolved: Dict[str, Tuple[Dict, Dict]]) -> None:
    for raw in raw_lines:
        hit = resolved.get(raw["offer_line_id"])
        if hit is None:
            raise _err(422, "OFFER_LINE_NOT_FOUND",
                       "Редът от офертата не е намерен в приета оферта на този обект",
                       offer_line_id=raw["offer_line_id"])
        _offer, ol = hit
        price = offer_unit_price(ol)
        if "unit_price" in raw and abs(raw["unit_price"] - price) > PRICE_TOLERANCE:
            raise _err(422, "UNIT_PRICE_MISMATCH",
                       "Единичната цена в акта (%.2f) се различава от цената в офертата (%.2f). "
                       "Различна цена е възможна само с анекс." % (raw["unit_price"], price),
                       offer_line_id=ol["id"], offer_unit_price=price,
                       requested_unit_price=raw["unit_price"])
        contracted = float(ol.get("qty") or 0)
        if "contracted_qty" in raw and q(raw["contracted_qty"]) != q(contracted):
            raise _err(422, "CONTRACTED_QTY_MISMATCH",
                       "Договореното количество идва от офертата (%s), не от заявката"
                       % unq(q(contracted)), offer_line_id=ol["id"],
                       offer_qty=unq(q(contracted)))


def _deltas(lines: List[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for ln in lines or []:
        olid = ln.get("offer_line_id")
        if olid:
            out[olid] = out.get(olid, 0) + q(float(ln.get("executed_qty") or 0))
    return out


# ═══════════════════════════════════════════════════════════════════ reservation
def _totals_id(org_id: str, offer_line_id: str) -> str:
    return "%s|%s" % (org_id, offer_line_id)


async def _acted_from_acts(tenant: TenantData, offer_line_id: str, session=None) -> int:
    """Σ executed_qty of one offer line over every act of the tenant (source of truth)."""
    total = 0
    cursor = tenant.client_acts.find({"lines.offer_line_id": offer_line_id},
                                     {"_id": 0, "lines": 1}, session=session)
    async for act in cursor:
        for ln in act.get("lines") or []:
            if ln.get("offer_line_id") == offer_line_id:
                total += q(float(ln.get("executed_qty") or 0))
    return total


async def reserve(tenant: TenantData, *, offer: Dict, offer_line: Dict, delta: int,
                  session) -> Dict[str, Any]:
    """Move the acted total of one offer line by ``delta`` units, capped by the offer qty.

    Runs inside the act's transaction. Raises 409 ``ACT_EXCEEDS_REMAINING`` (nothing is
    written — the transaction aborts)."""
    coll = tenant.collection(TOTALS)
    tid = _totals_id(tenant.org_id, offer_line["id"])
    cap = q(float(offer_line.get("qty") or 0))
    current = await coll.find_one({"_id": tid}, {"_id": 0}, session=session)
    if current is None:
        # First touch of this line: start from the acts that already exist (pre-ACT-01
        # acts count). Inside the transaction, so it matches the acts exactly.
        legacy = await _acted_from_acts(tenant, offer_line["id"], session=session)
        await coll.update_one({"_id": tid}, {"$setOnInsert": {
            "id": tid, "offer_id": offer["id"], "offer_line_id": offer_line["id"],
            "project_id": offer.get("project_id"), "acted_units": legacy,
            "units_per_qty": QTY_SCALE, "initialized_from_acts": legacy, "created_at": _now()}},
            upsert=True, session=session)
    flt: Dict[str, Any] = {"_id": tid}
    if delta > 0:
        flt["acted_units"] = {"$lte": cap - delta}
    after = await coll.find_one_and_update(
        flt, {"$inc": {"acted_units": delta},
              "$set": {"offer_qty_units": cap, "updated_at": _now()}},
        return_document=ReturnDocument.AFTER, session=session)
    if after is None:
        now_doc = await coll.find_one({"_id": tid}, {"_id": 0}, session=session) or {}
        acted = int(now_doc.get("acted_units") or 0)
        raise _err(409, "ACT_EXCEEDS_REMAINING",
                   "Актуваното количество по „%s“ ще надхвърли офертното: договорено %s, "
                   "вече актувано %s, остатък %s, заявено %s"
                   % (offer_line.get("activity_name", ""), unq(cap), unq(acted),
                      unq(max(cap - acted, 0)), unq(delta)),
                   offer_line_id=offer_line["id"], contracted_qty=unq(cap),
                   acted_qty=unq(acted), remaining_qty=unq(max(cap - acted, 0)),
                   requested_qty=unq(delta))
    return after


async def next_act_number(tenant: TenantData, session) -> str:
    coll = tenant.org_counters
    cid = "%s|%s" % (COUNTER_TYPE, tenant.org_id)
    if await coll.find_one({"_id": cid}, {"_id": 1}, session=session) is None:
        highest = 0
        cursor = tenant.client_acts.find({}, {"_id": 0, "act_number": 1}, session=session)
        async for act in cursor:
            m = _ACT_NO.match(str(act.get("act_number") or ""))
            if m:
                highest = max(highest, int(m.group(1)))
        await coll.update_one({"_id": cid}, {"$setOnInsert": {
            "counter_type": COUNTER_TYPE, "value": highest, "started_after": highest,
            "created_at": _now()}}, upsert=True, session=session)
    doc = await coll.find_one_and_update({"_id": cid}, {"$inc": {"value": 1}},
                                         return_document=ReturnDocument.AFTER, session=session)
    return "ACT-%04d" % int(doc["value"])


async def ensure_indexes(database) -> None:
    """Unique act number per tenant for counter-numbered acts (pre-ACT-01 duplicates, if
    any, stay as they are and are reported, never rewritten)."""
    await database.client_acts.create_index(
        [("org_id", 1), ("act_number", 1)], unique=True, name="act01_org_act_number_unique",
        partialFilterExpression={"number_source": NUMBER_SOURCE})
    await database.client_acts.create_index(
        [("org_id", 1), ("lines.offer_line_id", 1)], name="act01_org_offer_line")


# ═══════════════════════════════════════════════════════════════════ views
def _line_view(line: Dict[str, Any], totals: Dict[str, int]) -> Dict[str, Any]:
    out = dict(line)
    olid = line.get("offer_line_id")
    if olid and olid in totals:
        cap = q(float(line.get("contracted_qty") or 0))
        acted = totals[olid]
        price = float(line.get("unit_price") or 0)
        out.update({
            "acted_qty_total": unq(acted), "remaining_qty": unq(cap - acted),
            "contracted_value": round(unq(cap) * price, 2),
            "acted_value_total": round(unq(acted) * price, 2),
            "remaining_value": round(unq(cap - acted) * price, 2),
        })
    return out


async def acted_by_line(tenant: TenantData, offer_line_ids: List[str], session=None) -> Dict[str, int]:
    out = {olid: 0 for olid in offer_line_ids}
    if not offer_line_ids:
        return out
    cursor = tenant.client_acts.find({"lines.offer_line_id": {"$in": list(offer_line_ids)}},
                                     {"_id": 0, "lines": 1}, session=session)
    async for act in cursor:
        for ln in act.get("lines") or []:
            if ln.get("offer_line_id") in out:
                out[ln["offer_line_id"]] += q(float(ln.get("executed_qty") or 0))
    return out


async def act_view(tenant: TenantData, act: Dict[str, Any], session=None) -> Dict[str, Any]:
    """The act with contracted / acted / remaining per offer-linked line (FLOW-004)."""
    view = {k: v for k, v in act.items() if k not in ("_id", "applied_update_keys")}
    olids = [ln["offer_line_id"] for ln in act.get("lines") or [] if ln.get("offer_line_id")]
    totals = await acted_by_line(tenant, olids, session=session)
    view["lines"] = [_line_view(ln, totals) for ln in act.get("lines") or []]
    return view


async def remaining_for_project(tenant: TenantData, project_id: str) -> Dict[str, Any]:
    """Per offer line of every accepted offer of the project: contracted / acted / remaining."""
    offers = await tenant.offers.find({"project_id": project_id, "status": ACCEPTED},
                                      {"_id": 0}).to_list(500)
    olines = [(o, ol) for o in offers for ol in o.get("lines") or [] if ol.get("id")]
    totals = await acted_by_line(tenant, [ol["id"] for _o, ol in olines])
    rows = []
    for o, ol in olines:
        cap = q(float(ol.get("qty") or 0))
        acted = totals.get(ol["id"], 0)
        price = offer_unit_price(ol)
        rows.append({
            "offer_id": o["id"], "offer_no": o.get("offer_no"), "offer_type": o.get("offer_type", "main"),
            "offer_line_id": ol["id"], "activity_name": ol.get("activity_name", ""),
            "unit": ol.get("unit", "m2"), "unit_price": price,
            "contracted_qty": unq(cap), "acted_qty": unq(acted), "remaining_qty": unq(cap - acted),
            "contracted_value": round(unq(cap) * price, 2),
            "acted_value": round(unq(acted) * price, 2),
            "remaining_value": round(unq(cap - acted) * price, 2),
            "over_acted": acted > cap,
        })
    return {"project_id": project_id, "actuation_mode": "fixed_price", "lines": rows}


# ═══════════════════════════════════════════════════════════════════ audit
async def _audit(database, *, user: Dict[str, Any], action: str, act: Dict[str, Any],
                 diff: Dict[str, Any], key: KeyedWrite, endpoint: str, session) -> None:
    from app.audit.envelope import RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    event = build_event(
        tenant_id=user["org_id"], actor_type="human", actor_id=user["id"], action=action,
        source_flow="FLOW-004", retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        entity_type="client_act", entity_id=act["id"],
        entity_version=str(act.get("revision", 1)), scope_type="project",
        scope_id=act.get("project_id"), structured_diff=diff, tool_or_endpoint=endpoint,
        source_channel="api", idempotency_key=key.key_ref)
    await record_event(database, event, session=session)


def _lines_digest(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"offer_line_id": ln.get("offer_line_id"), "executed_qty": ln.get("executed_qty"),
             "unit_price": ln.get("unit_price"), "line_total": ln.get("line_total")}
            for ln in lines or []]


def _totals(lines: List[Dict[str, Any]]) -> Dict[str, float]:
    subtotal = round(sum(float(ln.get("line_total") or 0) for ln in lines), 2)
    return {"subtotal": subtotal, "vat_percent": VAT_PERCENT,
            "vat_amount": round(subtotal * VAT_PERCENT / 100, 2),
            "total": round(subtotal * (100 + VAT_PERCENT) / 100, 2)}


# ═══════════════════════════════════════════════════════════════════ transactions
async def _run(database, body):
    """One transaction; a duplicate on the audit chain sequence (a concurrent append) is
    retried like a write conflict. A deployment without transactions is refused (503)."""
    last: Optional[BaseException] = None
    for _attempt in range(MAX_TXN_ATTEMPTS):
        try:
            return await run_in_transaction(database, body)
        except TransactionsUnavailable:
            raise _err(503, "TRANSACTIONS_UNAVAILABLE",
                       "Актът не е записан: базата данни не поддържа транзакции")
        except DuplicateKeyError as exc:
            pattern = (getattr(exc, "details", None) or {}).get("keyPattern") or {}
            if set(pattern) == {"tenant_id", "sequence"}:
                last = exc
                continue
            raise
    raise last  # pragma: no cover — five concurrent audit appends in a row


async def create_act(database, *, user: Dict[str, Any], project_id: str,
                     raw_lines: List[Dict[str, Any]], header: Dict[str, Any],
                     key: KeyedWrite, endpoint: str, source_offer_id: Optional[str] = None
                     ) -> Dict[str, Any]:
    """The whole create (POST /client-acts and from-offer) in one transaction."""
    tenant = TenantData.for_user(database, user)
    act_id = key.derived_id("act")
    if key.wf is not None and key.wf.resumed:
        done = await tenant.client_acts.find_one({"id": act_id}, {"_id": 0})
        if done is not None:              # a FAILED attempt whose transaction committed
            return await act_view(tenant, done)

    async def body(session):
        resolved = await resolve_offer_lines(tenant, project_id,
                                             [ln["offer_line_id"] for ln in raw_lines], session)
        check_against_offer(raw_lines, resolved)
        if source_offer_id is not None and any(resolved[ln["offer_line_id"]][0]["id"] != source_offer_id
                                               for ln in raw_lines):
            raise _err(422, "OFFER_LINE_NOT_IN_SOURCE_OFFER",
                       "Редовете трябва да са от посочената оферта (source_offer_id)")
        lines = build_lines(raw_lines, resolved)
        for olid, delta in sorted(_deltas(lines).items()):
            offer, ol = resolved[olid]
            await reserve(tenant, offer=offer, offer_line=ol, delta=delta, session=session)
        number = await next_act_number(tenant, session)
        now = _now()
        offer_ids = sorted({ln["offer_id"] for ln in lines})
        act = {
            "_id": act_id, "id": act_id, "org_id": user["org_id"], "project_id": project_id,
            "source_offer_id": source_offer_id or (offer_ids[0] if len(offer_ids) == 1 else None),
            "source_offer_ids": offer_ids, "act_number": number,
            "number_source": NUMBER_SOURCE, "actuation_mode": "fixed_price",
            "act_date": header.get("act_date") or now[:10],
            "period_from": header.get("period_from"), "period_to": header.get("period_to"),
            "lines": lines, **_totals(lines), "currency": header.get("currency") or "EUR",
            "notes": header.get("notes"), "status": DRAFT, "revision": 1,
            "created_at": now, "updated_at": now, "created_by": user["id"],
        }
        await tenant.client_acts.insert_one(dict(act), session=session)
        act.pop("_id", None)
        await _audit(database, user=user, action="client_act.created", act=act, key=key,
                     endpoint=endpoint, session=session,
                     diff={"act_number": number, "project_id": project_id,
                           "lines": _lines_digest(lines), "subtotal": act["subtotal"]})
        return await act_view(tenant, act, session=session)

    return await _run(database, body)


async def update_act(database, *, user: Dict[str, Any], act_id: str, update: Dict[str, Any],
                     key: KeyedWrite, endpoint: str) -> Dict[str, Any]:
    """PUT on a Draft: header fields, and lines with the reservation moved by the
    difference, in one transaction."""
    tenant = TenantData.for_user(database, user)
    raw_lines = validate_raw_lines(update["lines"]) if "lines" in update else None

    async def body(session):
        act = await tenant.client_acts.find_one({"id": act_id}, {"_id": 0}, session=session)
        if not act:
            raise HTTPException(status_code=404, detail="Act not found")
        if key.key_ref in (act.get("applied_update_keys") or []):
            return await act_view(tenant, act, session=session)      # resumed, already done
        if act.get("status") != DRAFT:
            raise _err(400, "ACT_NOT_DRAFT",
                       "Само чернова може да се редактира. Приет акт се поправя с корекция "
                       "или сторно, не с редакция.")
        new = {k: v for k, v in update.items() if k != "lines"}
        diff: Dict[str, Any] = {"fields": sorted(new)}
        if raw_lines is not None:
            resolved = await resolve_offer_lines(tenant, act["project_id"],
                                                 [ln["offer_line_id"] for ln in raw_lines], session)
            check_against_offer(raw_lines, resolved)
            lines = build_lines(raw_lines, resolved, keep_ids=True)
            old, nxt = _deltas(act.get("lines") or []), _deltas(lines)
            for olid in sorted(set(old) | set(nxt)):
                delta = nxt.get(olid, 0) - old.get(olid, 0)
                if delta == 0:
                    continue
                if olid in resolved:
                    offer, ol = resolved[olid]
                else:   # a line removed from the act: its offer line may be any offer's
                    offer, ol = await _offer_of_line(tenant, olid, session)
                await reserve(tenant, offer=offer, offer_line=ol, delta=delta, session=session)
            new["lines"] = lines
            new.update(_totals(lines))
            new["source_offer_ids"] = sorted({ln["offer_id"] for ln in lines})
            diff.update({"before": _lines_digest(act.get("lines") or []),
                         "after": _lines_digest(lines), "subtotal_before": act.get("subtotal"),
                         "subtotal_after": new["subtotal"]})
        new["updated_at"] = _now()
        new["updated_by"] = user["id"]
        res = await tenant.client_acts.find_one_and_update(
            {"id": act_id, "status": DRAFT},
            {"$set": new, "$inc": {"revision": 1}, "$addToSet": {"applied_update_keys": key.key_ref}},
            projection={"_id": 0}, return_document=ReturnDocument.AFTER, session=session)
        if res is None:
            raise _err(400, "ACT_NOT_DRAFT", "Само чернова може да се редактира")
        await _audit(database, user=user, action="client_act.updated", act=res, key=key,
                     endpoint=endpoint, session=session, diff=diff)
        return await act_view(tenant, res, session=session)

    return await _run(database, body)


async def _offer_of_line(tenant: TenantData, offer_line_id: str, session):
    offer = await tenant.offers.find_one({"lines.id": offer_line_id}, {"_id": 0}, session=session)
    for ol in (offer or {}).get("lines") or []:
        if ol.get("id") == offer_line_id:
            return offer, ol
    # The offer line is gone from every offer of the tenant: release against a zero cap.
    return {"id": None, "project_id": None}, {"id": offer_line_id, "qty": 0}
