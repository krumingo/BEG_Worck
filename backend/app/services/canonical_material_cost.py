"""
5C-C20 — one read path for project material cost and the project material
trail over the CANONICAL warehouse ledger.

Package: ``docs/architecture/tasks/5C-C20_FINANCE_READS_CANONICAL.md``
(F-9, F-10, F-11). CLAUDE.md §7: material cost is recognised ONCE.

Source of truth (no second one is created here; everything is computed at
read time, nothing is stored):

  * COST — the canonical ``material_entries`` projection rows
    (``projection_source=canonical_warehouse_service``) whose
    ``movement_kind`` is a cost kind (``consume`` — 5C-C19 F-7). The
    command service writes that row inside the consume transaction
    (``projections._project_consumption``), so every reader sees the cost
    the moment the consumption commits — no ``POST /material-entries/sync``
    and no ``POST /execution-packages/recompute-material`` is needed.
  * PACKAGE ATTRIBUTION — the row's own ``execution_package_id`` when the
    deterministic rebuild has set it, else the SAME mapping rule the
    rebuild uses (active ``planned_materials`` by ``item_id``, then by
    name), applied at read time. The stored ``execution_packages.
    actual_material_cost`` cache is no longer read by the package reports.
  * QUANTITY TRAIL — the canonical ``warehouse_transactions`` ledger rows
    themselves (``action`` set), tenant-scoped, by location: material
    arriving at the project (acceptance / direct delivery), material
    leaving it (consume / write-off / transfer / quarantine / return).

Legacy rule — 5C-C22 / Р13 (Крум, 06.11.2026), replaces the C20 "any
canonical row → drop all legacy" rule: legacy ``warehouse_transactions``
issue rows (``type`` + ``lines``, no ``action``; their writers are retired,
410) count when they are dated BEFORE the tenant cutover (the first
canonical ledger row, see ``tenant_cutover``); at/after it only canonical
rows count and the legacy amount is reported as ``legacy_excluded_cost``.
Example: 100 legacy before + 30 canonical after = 130, everywhere.
``project_material_cost`` is the ONE helper every finance report uses for
project, package and period material cost.

5C-C21 F-12 (Р10, Крум 06.11.2026): a write-off (брак / загуба) FROM A
PROJECT bucket is project cost — recognised once, by the projector row the
command service writes inside the write-off transaction — and is reported as
its own line, „фира" (``waste_cost``). Readers keep ``material`` = consumption
and add ``waste`` beside it; every total includes both exactly once. A
write-off from a warehouse is not project cost (no row is written).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

CANONICAL_SOURCE = "canonical_warehouse_service"

# 5C-C19 F-7 — project material cost is recognised ONCE, at consumption.
# 5C-C21 F-12 (Р10) — and at a write-off from a project („фира").
COST_KINDS: Tuple[str, ...] = ("consume", "write_off")
WASTE_KINDS: Tuple[str, ...] = ("write_off",)
WASTE_LABEL = "фира"

PROJECT_LOCATION_TYPES = ("project", "subproject")


def _f(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ───────────────────────── package attribution ─────────────────────────

async def load_planned_mapping(tenant, org_id: str, project_id: str):
    """Active planned materials of the project → (by_item, by_name).

    Same rule as ``material_smr.sync_material_entries`` (first by item_id,
    then by lower-cased name) so read-time and rebuild attribution agree.
    """
    by_item: Dict[str, dict] = {}
    by_name: Dict[str, dict] = {}
    cursor = tenant.planned_materials.find(
        {"org_id": org_id, "project_id": project_id, "status": "active"},
        {"_id": 0, "id": 1, "item_id": 1, "material_name": 1,
         "execution_package_id": 1, "offer_line_id": 1},
    )
    async for pm in cursor:
        if pm.get("item_id"):
            by_item[pm["item_id"]] = pm
        name = (pm.get("material_name") or "").lower().strip()
        if name:
            by_name.setdefault(name, pm)
    return by_item, by_name


def resolve_planned(item_id: Optional[str], by_item: dict, by_name: dict) -> Optional[dict]:
    return by_item.get(item_id) or by_name.get((item_id or "").lower().strip())


def resolve_execution_package(entry: dict, by_item: dict, by_name: dict) -> Optional[str]:
    if entry.get("execution_package_id"):
        return entry["execution_package_id"]
    pm = resolve_planned(entry.get("item_id"), by_item, by_name)
    return pm.get("execution_package_id") if pm else None


# ─────────────────────── cutover (5C-C22, Р13) ───────────────────────
#
# Р13 (Крум, 06.11.2026): with a mixed history the project material cost is
# split by the moment the tenant moved to the canonical warehouse. Legacy
# rows BEFORE that moment count; after it only the canonical rows count.
#
# HOW THE CUTOVER MOMENT IS DETERMINED (one rule, read time, nothing stored):
#   cutover_at = ``recorded_at`` of the tenant's FIRST canonical warehouse
#   ledger row (``warehouse_transactions`` with ``action`` set), any action,
#   any location, tenant-scoped.
# Why this source (and not a new stored setting):
#   * the canonical ledger is append-only and ``recorded_at`` is stamped by
#     the server (envelope ``_now_iso``), never by the client — the moment
#     cannot be edited, back-dated or diverge between readers;
#   * it is per tenant (CLAUDE.md §3, database-per-tenant): the legacy
#     writers are retired (410, v6 §12.1) for the whole tenant, so from the
#     first canonical movement on, material can reach a project only through
#     the canon (Rule B accept / direct delivery) — a canonical consumption
#     can never re-cost a legacy issue, so the split is disjoint by time;
#   * no migration, no backfill, no second source of truth: an explicit,
#     hand-set date would be a new consequential write (permission +
#     Approval + AuditEvent) and is NOT introduced here.
# A tenant with no canonical row has no cutover: all its legacy rows count.

CUTOVER_SOURCE = "first_canonical_ledger_row"


def _moment(value: Any) -> Optional[datetime]:
    """ISO string / date string / datetime → aware UTC datetime (or None)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        try:
            if len(text) == 10:          # YYYY-MM-DD (legacy issue_date)
                dt = datetime.strptime(text, "%Y-%m-%d")
            else:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def tenant_cutover(tenant, org_id: str) -> Dict[str, Any]:
    """Р13 cutover of one tenant: its first canonical ledger row."""
    cursor = tenant.warehouse_transactions.find(
        {"org_id": org_id, "action": {"$exists": True},
         "recorded_at": {"$exists": True}},
        {"_id": 0, "recorded_at": 1, "movement_id": 1, "action": 1},
    ).sort([("recorded_at", 1), ("ledger_sequence", 1), ("movement_id", 1)]).limit(1)
    rows = [row async for row in cursor]
    if not rows:
        return {"cutover_at": None, "cutover_source": CUTOVER_SOURCE,
                "cutover_movement_id": None}
    return {"cutover_at": rows[0].get("recorded_at"),
            "cutover_source": CUTOVER_SOURCE,
            "cutover_movement_id": rows[0].get("movement_id")}


# ───────────────────────────── cost (F-9/F-10, C22) ─────────────────────────────

async def project_cost_rows(tenant, org_id: str, project_id: str) -> List[dict]:
    """Canonical cost rows (consumptions + project write-offs), tenant-scoped."""
    cursor = tenant.material_entries.find(
        {"org_id": org_id, "project_id": project_id,
         "projection_source": CANONICAL_SOURCE,
         "movement_kind": {"$in": list(COST_KINDS)},
         "cost_recognized": True},
        {"_id": 0},
    )
    return [row async for row in cursor]


async def legacy_issue_rows(tenant, org_id: str, project_id: str) -> List[dict]:
    """Legacy (pre-canon) issue rows of a project: ``type=issue``, no ``action``."""
    cursor = tenant.warehouse_transactions.find(
        {"org_id": org_id, "project_id": project_id, "type": "issue",
         "action": {"$exists": False}},
        {"_id": 0, "id": 1, "lines": 1, "created_at": 1, "issue_date": 1},
    )
    return [row async for row in cursor]


def legacy_line_value(line: dict) -> float:
    """Value of one legacy issue line. The retired writer stored
    ``total_price`` (= qty_issued × unit_price); older rows carry
    ``unit_cost``. One rule for every reader."""
    if line.get("total_price") is not None:
        return float(line.get("total_price") or 0)
    unit = line.get("unit_cost")
    if unit is None:
        unit = line.get("unit_price")
    return float(unit or 0) * float(line.get("qty_issued", 0) or 0)


def legacy_issue_cost(txns: Iterable[dict]) -> float:
    total = 0.0
    for txn in txns:
        for line in txn.get("lines", []) or []:
            total += legacy_line_value(line)
    return round(total, 2)


def legacy_moment(txn: dict) -> Optional[datetime]:
    """When a legacy row happened: server ``created_at``, else ``issue_date``."""
    return _moment(txn.get("created_at")) or _moment(txn.get("issue_date"))


def canonical_moment(row: dict) -> Optional[datetime]:
    return (_moment(row.get("recorded_at")) or _moment(row.get("consumed_at"))
            or _moment(row.get("written_off_at")))


def period_of(moment: Optional[datetime]) -> Optional[str]:
    return moment.strftime("%Y-%m") if moment else None


async def project_material_cost(tenant, org_id: str, project_id: str) -> Dict[str, Any]:
    """THE project material cost (5C-C22): one helper for every finance
    report — project, package and period.

    * canonical cost rows (consumption + „фира", recognised once);
    * PLUS legacy issue rows dated BEFORE the tenant cutover (Р13);
    * legacy rows at/after the cutover are reported as ``legacy_excluded_cost``
      and never counted (no double count).

    ``lines`` is the normalised list of every COUNTED cost line; all totals,
    package and period splits are sums over it, so they always agree.
    """
    rows = await project_cost_rows(tenant, org_id, project_id)
    by_item, by_name = await load_planned_mapping(tenant, org_id, project_id)
    cut = await tenant_cutover(tenant, org_id)
    cutover = _moment(cut["cutover_at"])

    lines: List[dict] = []
    for row in rows:
        at = canonical_moment(row)
        pm = resolve_planned(row.get("item_id"), by_item, by_name)
        lines.append({
            "source": "canonical", "kind": row.get("movement_kind"),
            "waste": row.get("movement_kind") in WASTE_KINDS,
            "value": _f(row.get("total_value")),
            "qty": _f(row.get("quantity")) or 0.0,
            "item_id": row.get("item_id"), "unit": row.get("unit"),
            "material_name": row.get("material_name") or (pm or {}).get("material_name")
            or row.get("item_id") or "",
            "package_id": resolve_execution_package(row, by_item, by_name),
            "at": at, "period": period_of(at), "ref": row.get("id"),
        })

    legacy_counted = 0.0
    legacy_excluded = 0.0
    legacy_undated = 0.0
    legacy_qty = 0.0
    legacy_rows = await legacy_issue_rows(tenant, org_id, project_id)
    for txn in legacy_rows:
        at = legacy_moment(txn)
        counted = cutover is None or at is None or at < cutover
        for ln in txn.get("lines", []) or []:
            value = legacy_line_value(ln)
            if not counted:
                legacy_excluded += value
                continue
            legacy_counted += value
            if at is None:
                legacy_undated += value
            qty = float(ln.get("qty_issued", 0) or 0)
            legacy_qty += qty
            name = ln.get("material_name") or ""
            pm = by_name.get(name.lower().strip())
            lines.append({
                "source": "legacy", "kind": "issue", "waste": False,
                "value": round(value, 4), "qty": qty, "item_id": None,
                "unit": ln.get("unit"), "material_name": name,
                "package_id": (pm or {}).get("execution_package_id"),
                "at": at, "period": period_of(at), "ref": txn.get("id"),
            })

    total = waste = qty = waste_qty = unmapped_cost = 0.0
    canonical_cost = 0.0
    partial = False
    by_package: Dict[str, float] = {}
    waste_by_package: Dict[str, float] = {}
    qty_by_package: Dict[str, float] = {}
    for ln in lines:
        q = ln["qty"]
        pkg_id = ln["package_id"]
        if ln["waste"]:
            waste_qty += q
        elif ln["source"] == "canonical":
            qty += q
            if pkg_id:
                qty_by_package[pkg_id] = qty_by_package.get(pkg_id, 0.0) + q
        value = ln["value"]
        if value is None:
            partial = True
            continue
        total += value
        if ln["source"] == "canonical":
            canonical_cost += value
        if ln["waste"]:
            waste += value
        if pkg_id:
            by_package[pkg_id] = by_package.get(pkg_id, 0.0) + value
            if ln["waste"]:
                waste_by_package[pkg_id] = waste_by_package.get(pkg_id, 0.0) + value
        else:
            unmapped_cost += value

    has_canonical = len(rows) > 0
    has_legacy = any(ln["source"] == "legacy" for ln in lines)
    source = ("mixed" if has_canonical and has_legacy else
              "canonical" if has_canonical else
              "legacy" if has_legacy or legacy_rows else "none")
    return {
        # total_cost = consumption + фира + pre-cutover legacy, each once.
        "total_cost": round(total, 2),
        "consumption_cost": round(total - waste, 2),
        "waste_cost": round(waste, 2),
        "waste_qty": round(waste_qty, 4),
        "waste_label": WASTE_LABEL,
        "waste_by_package": {k: round(v, 2) for k, v in waste_by_package.items()},
        "consumed_qty": round(qty, 4),
        "mapped_cost": round(total - unmapped_cost, 2),
        "unmapped_cost": round(unmapped_cost, 2),
        "by_package": {k: round(v, 2) for k, v in by_package.items()},
        "qty_by_package": {k: round(v, 4) for k, v in qty_by_package.items()},
        "partial_cost_data": partial,
        "has_data": len(lines) > 0,
        # Р13 basis — visible on every report that embeds it.
        "source": source,
        "canonical_cost": round(canonical_cost, 2),
        "legacy_cost": round(legacy_counted, 2),
        "legacy_issued_qty": round(legacy_qty, 4),
        "legacy_excluded_cost": round(legacy_excluded, 2),
        "legacy_undated_cost": round(legacy_undated, 2),
        "cutover_at": cut["cutover_at"],
        "cutover_source": cut["cutover_source"],
        "cutover_movement_id": cut["cutover_movement_id"],
        "lines": lines,
        "rows": rows,
        "by_item": by_item,
        "by_name": by_name,
    }


def cost_basis(cost: Dict[str, Any]) -> Dict[str, Any]:
    """The JSON-safe Р13 basis of a cost result (for report payloads)."""
    keys = ("total_cost", "consumption_cost", "waste_cost", "source",
            "canonical_cost", "legacy_cost", "legacy_excluded_cost",
            "legacy_undated_cost", "cutover_at", "cutover_source",
            "partial_cost_data")
    return {k: cost.get(k) for k in keys}


def cost_by_period(cost: Dict[str, Any]) -> Dict[Optional[str], Dict[str, float]]:
    """{'YYYY-MM' | None: {material, waste, total}} over the counted lines."""
    out: Dict[Optional[str], Dict[str, float]] = {}
    for ln in cost["lines"]:
        if ln["value"] is None:
            continue
        p = out.setdefault(ln["period"], {"material": 0.0, "waste": 0.0, "total": 0.0})
        p["total"] += ln["value"]
        if ln["waste"]:
            p["waste"] += ln["value"]
        else:
            p["material"] += ln["value"]
    for p in out.values():
        for k in p:
            p[k] = round(p[k], 2)
    return out


def cost_lines_between(cost: Dict[str, Any], start: Optional[Any],
                       end: Optional[Any]) -> List[dict]:
    """Counted cost lines whose moment lies in [start, end] (inclusive)."""
    lo, hi = _moment(start), _moment(end)
    out = []
    for ln in cost["lines"]:
        at = ln["at"]
        if at is None:
            continue
        if lo is not None and at < lo:
            continue
        if hi is not None and at > hi:
            continue
        out.append(ln)
    return out


async def package_material_actual(tenant, org_id: str, pkg: dict) -> float:
    """Material actual of one execution package (read time):
    consumption + фира (+ pre-cutover legacy) of the package."""
    split = await package_material_split(tenant, org_id, pkg)
    return split["total"]


async def package_material_split(tenant, org_id: str, pkg: dict) -> Dict[str, float]:
    """5C-C21 F-12 — {material (consumption), waste (фира), total} of a package."""
    project_id = pkg.get("project_id")
    if not project_id:
        return {"material": 0.0, "waste": 0.0, "total": 0.0}
    cost = await project_material_cost(tenant, org_id, project_id)
    return split_for_package(cost, pkg["id"])


def split_for_package(cost: Dict[str, Any], pkg_id: str) -> Dict[str, float]:
    total = cost["by_package"].get(pkg_id, 0.0)
    waste = cost["waste_by_package"].get(pkg_id, 0.0)
    return {"material": round(total - waste, 2), "waste": round(waste, 2),
            "total": round(total, 2)}


async def project_warehouse_material_cost(tenant, org_id: str, project_id: str) -> Dict[str, Any]:
    """Warehouse-path material cost for the project P&L — a thin view over
    ``project_material_cost`` (5C-C22: the same number every report shows)."""
    cost = await project_material_cost(tenant, org_id, project_id)
    out = cost_basis(cost)
    out.update({
        "material_cost": cost["total_cost"],
        "waste_qty": cost["waste_qty"],
        "consumed_qty": cost["consumed_qty"],
    })
    return out


# ───────────────────────── quantity trail (F-11) ─────────────────────────

def is_project_location(loc: Optional[dict]) -> bool:
    """A ledger location dict that is a project / subproject bucket."""
    return bool(loc) and loc.get("location_type") in PROJECT_LOCATION_TYPES


def _at_project(loc: Optional[dict], project_id: str) -> bool:
    return bool(loc) and loc.get("location_type") in PROJECT_LOCATION_TYPES \
        and loc.get("location_id") == project_id


async def project_ledger_rows(tenant, org_id: str, project_id: str) -> List[dict]:
    """Canonical ledger rows that touch the project, tenant-scoped, ordered."""
    cursor = tenant.warehouse_transactions.find(
        {"org_id": org_id, "action": {"$exists": True},
         "$or": [
             {"project_id": project_id},
             {"source.location_id": project_id},
             {"destination.location_id": project_id},
         ]},
        {"_id": 0, "layer_allocations": 0},
    ).sort([("ledger_sequence", 1), ("recorded_at", 1), ("movement_id", 1)])
    return [row async for row in cursor]


def _blank(name: str, unit: str, item_id: Optional[str]) -> dict:
    return {"material_name": name, "unit": unit or "", "item_id": item_id,
            "requested": 0, "purchased": 0, "received_to_warehouse": 0,
            "dispatched_to_project": 0, "issued_to_project": 0, "consumed": 0,
            "returned": 0, "written_off": 0, "source": "canonical"}


async def canonical_project_trail(tenant, org_id: str, project_id: str) -> Dict[str, dict]:
    """Per-item quantity trail of a project from the canonical ledger.

    * dispatched_to_project — dispatched towards the project (in transit;
      Rule B: not on the project yet);
    * issued_to_project — accepted on / delivered directly to the project;
    * consumed — consume_to_smr from the project;
    * written_off — write-off from the project (its cost is the „фира"
      line of project_material_cost, 5C-C21 F-12);
    * returned — any other movement leaving the project (transfer to a
      warehouse / project, quarantine entry, return to supplier).
    """
    rows = await project_ledger_rows(tenant, org_id, project_id)
    by_item, by_name = await load_planned_mapping(tenant, org_id, project_id)
    out: Dict[str, dict] = {}
    for row in rows:
        act = row.get("action")
        item_id = row.get("item_id")
        pm = resolve_planned(item_id, by_item, by_name)
        name = (pm or {}).get("material_name") or item_id or ""
        key = item_id or name
        mat = out.setdefault(key, _blank(name, row.get("unit"), item_id))
        qty = _f(row.get("quantity")) or 0.0
        src, dst = row.get("source"), row.get("destination")
        if act == "dispatch_warehouse_to_project" and row.get("project_id") == project_id:
            mat["dispatched_to_project"] += qty
        elif _at_project(dst, project_id):
            accepted = _f(row.get("accepted_quantity"))
            mat["issued_to_project"] += accepted if accepted is not None else qty
        elif _at_project(src, project_id):
            if act == "consume_to_smr":
                mat["consumed"] += qty
            elif act == "write_off":
                mat["written_off"] += qty
            else:
                mat["returned"] += qty
    return out
