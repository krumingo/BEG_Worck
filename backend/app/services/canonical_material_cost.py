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

Legacy rule (F-9, "не се броят два пъти"): legacy ``warehouse_transactions``
rows (``type`` + ``lines``, no ``action``) predate the canon — their writers
are retired (410). A project that has ANY canonical cost row reads its
warehouse material cost from the canon ONLY; legacy issue rows are then
reported as ``excluded`` and never added. A project with no canonical cost
row keeps its historical legacy figure. This is the same rule
``/project-profit`` (``revenue_expense``) already applies via
``get_material_summary_for_project().has_data``.

5C-C21 F-12 (Р10, Крум 06.11.2026): a write-off (брак / загуба) FROM A
PROJECT bucket is project cost — recognised once, by the projector row the
command service writes inside the write-off transaction — and is reported as
its own line, „фира" (``waste_cost``). Readers keep ``material`` = consumption
and add ``waste`` beside it; every total includes both exactly once. A
write-off from a warehouse is not project cost (no row is written).
"""
from __future__ import annotations

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


# ───────────────────────────── cost (F-9/F-10) ─────────────────────────────

async def project_cost_rows(tenant, org_id: str, project_id: str) -> List[dict]:
    """Canonical cost rows (consumptions) of one project, tenant-scoped."""
    cursor = tenant.material_entries.find(
        {"org_id": org_id, "project_id": project_id,
         "projection_source": CANONICAL_SOURCE,
         "movement_kind": {"$in": list(COST_KINDS)},
         "cost_recognized": True},
        {"_id": 0},
    )
    return [row async for row in cursor]


async def project_material_cost(tenant, org_id: str, project_id: str) -> Dict[str, Any]:
    """Canonical material cost of a project, with package attribution."""
    rows = await project_cost_rows(tenant, org_id, project_id)
    by_item, by_name = await load_planned_mapping(tenant, org_id, project_id)
    total = 0.0
    waste = 0.0
    qty = 0.0
    waste_qty = 0.0
    partial = False
    by_package: Dict[str, float] = {}
    waste_by_package: Dict[str, float] = {}
    qty_by_package: Dict[str, float] = {}
    unmapped_cost = 0.0
    for row in rows:
        value = _f(row.get("total_value"))
        q = _f(row.get("quantity")) or 0.0
        is_waste = row.get("movement_kind") in WASTE_KINDS
        pkg_id = resolve_execution_package(row, by_item, by_name)
        if is_waste:
            waste_qty += q
        else:
            qty += q
            if pkg_id:
                qty_by_package[pkg_id] = qty_by_package.get(pkg_id, 0.0) + q
        if value is None:
            partial = True
            continue
        total += value
        if is_waste:
            waste += value
        if pkg_id:
            by_package[pkg_id] = by_package.get(pkg_id, 0.0) + value
            if is_waste:
                waste_by_package[pkg_id] = waste_by_package.get(pkg_id, 0.0) + value
        else:
            unmapped_cost += value
    return {
        # total_cost = consumption + фира (each recognised once).
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
        "has_data": len(rows) > 0,
        "rows": rows,
        "by_item": by_item,
        "by_name": by_name,
    }


async def package_material_actual(tenant, org_id: str, pkg: dict) -> float:
    """Canonical material actual of one execution package (read time):
    consumption + фира of the package."""
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


def legacy_issue_cost(txns: Iterable[dict]) -> float:
    total = 0.0
    for txn in txns:
        for line in txn.get("lines", []) or []:
            total += float(line.get("unit_cost", 0) or 0) * float(line.get("qty_issued", 0) or 0)
    return round(total, 2)


async def project_warehouse_material_cost(tenant, org_id: str, project_id: str) -> Dict[str, Any]:
    """Warehouse-path material cost for the project P&L (F-9).

    Canonical consumption when the project has any; otherwise the legacy
    (pre-canon) issue figure. Never both.
    """
    canonical = await project_material_cost(tenant, org_id, project_id)
    legacy_txns = [t async for t in tenant.warehouse_transactions.find(
        {"org_id": org_id, "project_id": project_id, "type": "issue"},
        {"_id": 0, "lines": 1},
    )]
    legacy = legacy_issue_cost(legacy_txns)
    if canonical["has_data"]:
        return {"material_cost": canonical["total_cost"], "source": "canonical",
                "canonical_cost": canonical["total_cost"],
                "consumption_cost": canonical["consumption_cost"],
                "waste_cost": canonical["waste_cost"],
                "waste_qty": canonical["waste_qty"],
                "legacy_cost": 0.0, "legacy_excluded_cost": legacy,
                "consumed_qty": canonical["consumed_qty"],
                "partial_cost_data": canonical["partial_cost_data"]}
    return {"material_cost": legacy, "source": "legacy" if legacy_txns else "none",
            "canonical_cost": 0.0, "legacy_cost": legacy,
            "consumption_cost": legacy, "waste_cost": 0.0, "waste_qty": 0.0,
            "legacy_excluded_cost": 0.0, "consumed_qty": 0.0,
            "partial_cost_data": False}


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
