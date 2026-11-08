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

5C-C25 (Р17, Крум 06.11.2026 — replaces "cost at consumption" of 5C-C18…C24):
project material cost is recognised when the material is ACCEPTED on the
project — the whole accepted quantity, at the exact FIFO layers of 5C-C24
(and on a direct supplier delivery to the project). A return to a warehouse
(or a transfer to another project) reduces it when the lot is accepted at
its destination (Р18). CONSUME_TO_SMR is NOT cost: it only ALLOCATES the
project's cost to SMR / execution packages for reports and budgets. A
write-off from the project („фира", Р10) is already part of the accepted
cost; it stays its own line by reclassifying that value out of „material".

FG-17 (5C-C25, made exact by 5C-C26 per FLOW-043 D-04 / FLOW-009): Path B —
the quantity of a supplier invoice line allocated straight to the project —
is part of THIS helper too, summed with Path A as separate lots. A quantity
allocated to a warehouse is Path A (cost at ACCEPT). A canonical supplier
receipt of the same line (``invoice_line_id``) is the same lot: the canon
wins for the quantity it covers (``invoice_linked_excluded_cost``); an
overlap the data cannot prove is warned, never silently changed. Full rule:
``path_b_split``. The P&L no longer takes ``max(invoice, warehouse)``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

CANONICAL_SOURCE = "canonical_warehouse_service"

# 5C-C25 (Р17) — the `material_entries` kinds that ARE project cost
# (signed `total_value`): acceptance / direct delivery (+), a lot accepted
# away from the project (−).
COST_KINDS: Tuple[str, ...] = ("accept", "return", "transfer_out")
# Allocation-only kinds (value in `movement_value`): consumption per SMR and
# the „фира" line (Р10). Never added to the cost a second time.
ALLOCATION_KINDS: Tuple[str, ...] = ("consume", "write_off")
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
    """Canonical rows of a project, tenant-scoped: the R17 cost rows
    (accept / return / transfer_out) and the allocation rows (consume /
    write_off)."""
    cursor = tenant.material_entries.find(
        {"org_id": org_id, "project_id": project_id,
         "projection_source": CANONICAL_SOURCE,
         "movement_kind": {"$in": list(COST_KINDS) + list(ALLOCATION_KINDS)}},
        {"_id": 0},
    )
    return [row async for row in cursor]


# ─────────────── Path B (FG-17, 5C-C26 — FLOW-043 D-04, FLOW-009) ───────────────
#
# FLOW-009 „Разход по обект — без двойно броене": Path A (supplier →
# warehouse → project, cost at ACCEPT, Р17) and Path B (supplier invoice
# line allocated straight to the project). ONE lot can never become cost
# along both paths.
#
# 5C-C26 rule, applied per invoice line L and project P (read time,
# nothing stored):
#   1. Only the quantity of L allocated DIRECTLY to P is Path B
#      (``allocations[]`` entries ``type=project, ref_id=P``; a line without
#      ``allocations[]`` keeps its deprecated single allocation
#      ``allocation_type/allocation_ref_id`` for its whole qty). A quantity
#      allocated to a warehouse is Path A — cost only at ACCEPT (Р17). A
#      stale deprecated ``allocation_type=project`` on a line whose
#      ``allocations[]`` says otherwise is NOT Path B (``/allocate`` replaces
#      ``allocations[]`` only).
#   2. PROVEN LINK — a canonical supplier receipt (``receive_from_supplier``
#      to a warehouse, ``receive_from_supplier_to_project``) whose
#      ``invoice_line_id`` is L. That receipt is the lot of L; the warehouse
#      (canonical) side wins and L counts only for the quantity no receipt
#      covers:
#        covered(P) = direct receipts of L to P
#                   + receipts of L into a warehouse beyond L's own
#                     warehouse allocation (goods L allocated to projects but
#                     that physically went through the warehouse) — only
#                     when P is L's ONLY project allocation;
#        Path B(P)  = (allocated(P) − covered(P), ≥ 0) × L's own unit price
#                     (line_total_ex_vat / qty — no averaging across lots).
#      Other canonical rows that reference L (no receipt does) prove the
#      link but not the quantity: the whole P part goes through the canon.
#      Quantities are compared only when L's unit equals the receipts'
#      unit; otherwise (or when L has no qty) the link wins for the whole P
#      part. No link → the two records are different lots and are summed.
#   3. NO PROVABLE LINK where an overlap is possible — the line stays
#      counted (no silent change of the sum) and an integrity warning is
#      raised (``path_b_warnings``; shown by GET
#      /warehouse/canonical/integrity-warnings):
#        PATH_B_LEGACY_OVERLAP_UNPROVEN — a counted Path B line and a counted
#          pre-cutover legacy issue (Р13) of the same project with the same
#          material name: legacy issues carry no invoice-line / lot
#          reference, so the data cannot prove or refute the overlap;
#        PATH_B_LINK_QTY_UNVERIFIED — a link exists but the quantity cannot
#          be compared (unit differs / no qty / non-receipt reference): the
#          canon won for the whole P part, a remainder may be missing;
#        PATH_B_LINK_AMBIGUOUS — warehouse receipts of L exceed its warehouse
#          allocation but L is split over several projects: which project's
#          part went through the warehouse is not in the data.
#        PATH_B_LINK_PROJECT_CONFLICT (5C-C26l, Codex F-55-C26-02) — L was
#          delivered directly into ANOTHER project than it is allocated to
#          (legacy data; new ones are refused 422): the lot counts once, on
#          the canonical destination; raised on both projects.
#        PATH_B_LINK_OVER_LINE (5C-C26l Addendum L, FG-108) — the linked
#          supplier receipts of L (warehouse + direct) exceed L's quantity
#          (legacy data; new ones are refused 422 INVOICE_LINE_QTY_EXCEEDED):
#          the excess is the same lot a second time. It is taken off the
#          direct deliveries of L, newest first (the warehouse lot is stock
#          with FIFO layers, accepted / issued through the canon), as a
#          negative ``over_link_exclusion`` line at the delivery's moment —
#          the lot counts once. Warehouse-only excess changes no project
#          cost (stock) and is warned on the integrity screen.

PATH_B_RECEIPT_ACTIONS: Tuple[str, ...] = (
    "receive_from_supplier", "receive_from_supplier_to_project")
PATH_B_RULE = "C26_one_path_per_lot"


def _norm_unit(unit: Any) -> str:
    return " ".join(str(unit or "").lower().split())


def _norm_name(name: Any) -> str:
    return " ".join(str(name or "").casefold().split())


def effective_allocations(line: dict) -> List[dict]:
    """``allocations[]`` of an invoice line; a line without it keeps its
    deprecated single allocation for the whole qty (``qty`` None = whole
    line, quantity unknown) — the same reading as
    ``routes.invoice_lines.normalize_allocations``."""
    allocs = line.get("allocations") or []
    if allocs:
        out = []
        for a in allocs:
            out.append({"type": a.get("type"),
                        "ref_id": a.get("ref_id") or a.get("refId"),
                        "qty": _f(a.get("qty"))})
        return out
    if line.get("allocation_type") and line.get("allocation_ref_id"):
        return [{"type": line["allocation_type"],
                 "ref_id": line["allocation_ref_id"],
                 "qty": _f(line.get("qty"))}]
    return []


async def project_invoice_lines(tenant, org_id: str, project_id: str) -> List[dict]:
    """Path B candidates: supplier invoice lines with ANY allocation to the
    project (``allocations[]`` or the deprecated single allocation)."""
    cursor = tenant.invoice_lines.find(
        {"org_id": org_id,
         "$or": [
             {"allocations": {"$elemMatch": {"type": "project", "ref_id": project_id}}},
             {"allocation_type": "project", "allocation_ref_id": project_id},
         ]},
        {"_id": 0, "id": 1, "line_total_ex_vat": 1, "description": 1, "unit": 1,
         "qty": 1, "created_at": 1, "invoice_id": 1, "allocations": 1,
         "allocation_type": 1, "allocation_ref_id": 1},
    )
    return [row async for row in cursor]


async def project_input_vat(tenant, org_id: str, project_id: str) -> float:
    """5C-C26 Addendum B — input VAT of the supplier invoice lines allocated
    to the project, selected by the SAME rule as Path B (``allocations[]``,
    or the deprecated single allocation for a line without it): the line's
    ``vat_amount`` × the share of its qty allocated to the project. A stale
    deprecated ``allocation_type=project`` on a line re-allocated elsewhere
    adds nothing. VAT is a tax fact of the allocation, not a cost lot, so a
    canonical receipt of the line does not change it."""
    cursor = tenant.invoice_lines.find(
        {"org_id": org_id,
         "$or": [
             {"allocations": {"$elemMatch": {"type": "project", "ref_id": project_id}}},
             {"allocation_type": "project", "allocation_ref_id": project_id},
         ]},
        {"_id": 0, "qty": 1, "vat_amount": 1, "allocations": 1,
         "allocation_type": 1, "allocation_ref_id": 1},
    )
    total = 0.0
    async for line in cursor:
        vat = float(line.get("vat_amount", 0) or 0)
        mine = [a for a in effective_allocations(line)
                if a["type"] == "project" and a["ref_id"] == project_id]
        if not mine:
            continue
        qty = _f(line.get("qty"))
        if qty and qty > 0 and all(a["qty"] is not None for a in mine):
            total += vat * min(sum(a["qty"] for a in mine), qty) / qty
        else:
            total += vat
    # INV-CN-01 FG-247(c): supplier credit / debit notes correct the input VAT pro rata
    from app.services.invoice_corrections import supplier_note_input_vat
    total += float(await supplier_note_input_vat(tenant, project_id))
    return round(total, 2)


async def ledger_invoice_line_links(tenant, org_id: str, ids: List[str]) -> Dict[str, List[dict]]:
    """Canonical ledger rows that reference each invoice line
    (``invoice_line_id``), tenant-scoped."""
    out: Dict[str, List[dict]] = {}
    if not ids:
        return out
    cursor = tenant.warehouse_transactions.find(
        {"org_id": org_id, "action": {"$exists": True}, "invoice_line_id": {"$in": ids}},
        {"_id": 0, "invoice_line_id": 1, "action": 1, "quantity": 1, "unit": 1,
         "destination": 1, "movement_id": 1,
         # 5C-C26l Addendum L (FG-108): order + value of an over-linked lot.
         "ledger_sequence": 1, "unit_value": 1, "total_value": 1, "recorded_at": 1,
         # 5C-C26k (F-55-C26-01): the server-bound project of the movement —
         # for a subproject destination, its DB-resolved parent (FG-38).
         "project_id": 1},
    )
    async for row in cursor:
        out.setdefault(row["invoice_line_id"], []).append(row)
    return out


async def ledger_invoice_line_ids(tenant, org_id: str, ids: List[str]) -> set:
    """Invoice line ids that a canonical ledger row references."""
    return set((await ledger_invoice_line_links(tenant, org_id, ids)).keys())


def path_b_split(line: dict, project_id: str, links: List[dict]) -> Dict[str, Any]:
    """5C-C26 — the Path B part of one invoice line for one project.

    Returns ``counted_value`` / ``covered_value`` (linked, through the
    canon) / ``path_a_value`` (allocated elsewhere, e.g. a warehouse) and
    ``warning`` (code or None). Pure function of the line and its links."""
    total_value = float(line.get("line_total_ex_vat", 0) or 0)
    line_qty = _f(line.get("qty"))
    allocs = effective_allocations(line)
    proj_allocs = [a for a in allocs if a["type"] == "project"]
    mine = [a for a in proj_allocs if a["ref_id"] == project_id]
    wh_alloc = sum(a["qty"] or 0.0 for a in allocs if a["type"] == "warehouse")
    path_a_value = (total_value / line_qty * wh_alloc
                    if line_qty is not None and line_qty > 0 else 0.0)
    if not mine:
        return {"counted_value": 0.0, "covered_value": 0.0,
                "path_a_value": path_a_value, "allocated_qty": 0.0,
                "counted_qty": 0.0, "warning": None, "link": "none"}
    unit_known = line_qty is not None and line_qty > 0 \
        and all(a["qty"] is not None for a in mine)
    if unit_known:
        unit_price = total_value / line_qty
        alloc_qty = sum(a["qty"] for a in mine)
        alloc_value = unit_price * alloc_qty
    else:
        unit_price = None
        alloc_qty = line_qty or 0.0
        alloc_value = total_value

    def _out(counted_value, warning=None, link="none", counted_qty=None):
        counted_value = max(min(counted_value, alloc_value), 0.0)
        return {"counted_value": counted_value,
                "covered_value": alloc_value - counted_value,
                "path_a_value": path_a_value, "allocated_qty": alloc_qty,
                "counted_qty": alloc_qty if counted_qty is None else counted_qty,
                "warning": warning, "link": link}

    if not links:
        return _out(alloc_value)                     # different lot: summed
    receipts = [r for r in links if r.get("action") in PATH_B_RECEIPT_ACTIONS]
    line_unit = _norm_unit(line.get("unit"))
    comparable = (unit_known and receipts
                  and all(_norm_unit(r.get("unit")) == line_unit for r in receipts))
    if not comparable:
        # Proven link, quantity not comparable: the canon wins the whole part.
        return _out(0.0, "PATH_B_LINK_QTY_UNVERIFIED", "proven", 0.0)

    def _is_to(row, pid):
        dst = row.get("destination") or {}
        if dst.get("location_type") == "project":
            return dst.get("location_id") == pid
        if dst.get("location_type") == "subproject":
            # 5C-C26k (Codex F-55-C26-01): a subproject's id is not its
            # project's id — the movement carries the server-bound parent
            # (CommandService._bind_subproject_parent, FG-38).
            return row.get("project_id") == pid
        return False

    direct_to_me = sum(_f(r.get("quantity")) or 0.0 for r in receipts
                       if r.get("action") == "receive_from_supplier_to_project"
                       and _is_to(r, project_id))
    to_warehouse = sum(_f(r.get("quantity")) or 0.0 for r in receipts
                       if r.get("action") == "receive_from_supplier")
    excess = max(to_warehouse - wh_alloc, 0.0)
    covered = direct_to_me
    warning = None
    only_me = all(a["ref_id"] == project_id for a in proj_allocs)
    if excess > 0:
        if only_me:
            covered += excess
        else:
            warning = "PATH_B_LINK_AMBIGUOUS"
    # 5C-C26l — Codex F-55-C26-02 (legacy data, D-04): direct deliveries of L
    # into ANOTHER project Q beyond Q's own allocation of L are the lot L
    # allocated here — counted once, on the canonical destination Q. When this
    # project is L's only project allocation the covered quantity leaves its
    # Path B; otherwise which project's part went to Q is not in the data. In
    # both cases PATH_B_LINK_PROJECT_CONFLICT is raised (and on Q, see
    # project_link_conflicts). New deliveries like this are refused (422).
    to_other: Dict[Any, float] = {}
    for r in receipts:
        if r.get("action") == "receive_from_supplier_to_project" and not _is_to(r, project_id):
            q = r.get("project_id") or (r.get("destination") or {}).get("location_id")
            to_other[q] = to_other.get(q, 0.0) + (_f(r.get("quantity")) or 0.0)
    excess_other = sum(
        max(qty - sum(a["qty"] or 0.0 for a in proj_allocs if a["ref_id"] == q), 0.0)
        for q, qty in to_other.items())
    if excess_other > 0:
        if only_me:
            covered += excess_other
        warning = "PATH_B_LINK_PROJECT_CONFLICT"
    covered = min(covered, alloc_qty)
    uncovered = alloc_qty - covered
    return _out(uncovered * unit_price, warning,
                "proven" if covered > 0 else "none", uncovered)


async def project_link_conflicts(tenant, org_id: str, project_id: str) -> List[dict]:
    """5C-C26l (Codex F-55-C26-02) — the destination side: canonical direct
    deliveries into THIS project that carry an invoice line allocated to it
    for less than was delivered (or not at all). The lot is counted here (the
    canon); the warning makes the conflicting allocation visible."""
    delivered: Dict[str, float] = {}
    units: Dict[str, set] = {}
    async for row in tenant.warehouse_transactions.find(
            {"org_id": org_id, "action": "receive_from_supplier_to_project",
             "project_id": project_id, "invoice_line_id": {"$nin": [None, ""]}},
            {"_id": 0, "invoice_line_id": 1, "quantity": 1, "unit": 1}):
        lid = row["invoice_line_id"]
        delivered[lid] = delivered.get(lid, 0.0) + (_f(row.get("quantity")) or 0.0)
        units.setdefault(lid, set()).add(_norm_unit(row.get("unit")))
    if not delivered:
        return []
    out = []
    async for line in tenant.invoice_lines.find(
            {"org_id": org_id, "id": {"$in": sorted(delivered)}}, {"_id": 0}):
        lid = line.get("id")
        mine = [a for a in effective_allocations(line)
                if a["type"] == "project" and a["ref_id"] == project_id]
        if mine and any(a["qty"] is None for a in mine):
            continue                       # whole-line allocation: not comparable
        allocated = sum(a["qty"] or 0.0 for a in mine)
        comparable = units.get(lid, set()) <= {_norm_unit(line.get("unit")), ""}
        if allocated == 0 or (comparable and delivered[lid] > allocated):
            out.append({"code": "PATH_B_LINK_PROJECT_CONFLICT", "project_id": project_id,
                        "invoice_line_id": lid, "invoice_id": line.get("invoice_id"),
                        "description": line.get("description"),
                        "delivered_qty": delivered[lid], "allocated_qty": allocated,
                        "rule": PATH_B_RULE})
    missing = set(delivered) - {w["invoice_line_id"] for w in out} - {
        ln_id async for ln_id in _existing_line_ids(tenant, org_id, delivered)}
    for lid in sorted(missing):            # line unknown in this tenant
        out.append({"code": "PATH_B_LINK_PROJECT_CONFLICT", "project_id": project_id,
                    "invoice_line_id": lid, "delivered_qty": delivered[lid],
                    "allocated_qty": 0.0, "rule": PATH_B_RULE})
    return out


def over_linked_lines(line: dict, links: List[dict]) -> Optional[Dict[str, Any]]:
    """5C-C26l Addendum L (FG-108) — for one invoice line and its canonical
    links: None, or {excess_qty, exclusions: [{row, qty}]} when the linked
    supplier receipts exceed the line's quantity (comparable units only).
    The excess is assigned to the direct deliveries, newest first."""
    line_qty = _f(line.get("qty"))
    if line_qty is None or line_qty <= 0:
        return None
    unit = _norm_unit(line.get("unit"))
    receipts = [r for r in links if r.get("action") in PATH_B_RECEIPT_ACTIONS]
    if not receipts or any(_norm_unit(r.get("unit")) not in ("", unit) for r in receipts):
        return None
    excess = sum(_f(r.get("quantity")) or 0.0 for r in receipts) - line_qty
    if excess <= 1e-9:
        return None
    out = {"excess_qty": excess, "exclusions": []}
    directs = sorted((r for r in receipts
                      if r.get("action") == "receive_from_supplier_to_project"),
                     key=lambda r: (r.get("ledger_sequence") or 0, r.get("movement_id") or ""),
                     reverse=True)
    left = excess
    for r in directs:
        if left <= 1e-9:
            break
        take = min(left, _f(r.get("quantity")) or 0.0)
        if take > 0:
            out["exclusions"].append({"row": r, "qty": take})
            left -= take
    return out


def _row_unit_value(row: dict) -> float:
    uv = _f(row.get("unit_value"))
    if uv is not None:
        return uv
    qty, total = _f(row.get("quantity")), _f(row.get("total_value"))
    return (total / qty) if qty and total is not None else 0.0


async def project_over_link_exclusions(tenant, org_id: str, project_id: str):
    """FG-108 legacy data — (exclusion lines, warnings) of THIS project: the
    over-linked quantity of its linked direct deliveries."""
    ids = sorted({lid for lid in await tenant.warehouse_transactions.distinct(
        "invoice_line_id", {"org_id": org_id, "action": "receive_from_supplier_to_project",
                            "project_id": project_id,
                            "invoice_line_id": {"$nin": [None, ""]}}) if lid})
    if not ids:
        return [], []
    links = await ledger_invoice_line_links(tenant, org_id, ids)
    exclusions, warnings = [], []
    async for line in tenant.invoice_lines.find(
            {"org_id": org_id, "id": {"$in": ids}},
            {"_id": 0, "id": 1, "qty": 1, "unit": 1, "invoice_id": 1, "description": 1}):
        over = over_linked_lines(line, links.get(line["id"], []))
        if not over:
            continue
        mine = [e for e in over["exclusions"] if e["row"].get("project_id") == project_id]
        for e in mine:
            r = e["row"]
            at = canonical_moment(r)
            exclusions.append({
                "source": "dq_correction", "kind": "over_link_exclusion", "waste": False,
                "value": -round(e["qty"] * _row_unit_value(r), 4), "qty": -e["qty"],
                "item_id": None, "unit": r.get("unit"),
                "material_name": line.get("description") or "", "package_id": None,
                "at": at, "period": period_of(at), "ref": line["id"],
                "movement_id": r.get("movement_id"),
            })
        warnings.append({
            "code": "PATH_B_LINK_OVER_LINE", "project_id": project_id,
            "invoice_line_id": line["id"], "invoice_id": line.get("invoice_id"),
            "description": line.get("description"),
            "line_qty": _f(line.get("qty")), "excess_qty": round(over["excess_qty"], 4),
            "excluded_qty": round(sum(e["qty"] for e in mine), 4),
            "linked_movement_ids": sorted(r.get("movement_id") for r in links.get(line["id"], [])
                                          if r.get("movement_id")),
            "rule": PATH_B_RULE,
        })
    return exclusions, warnings


async def tenant_over_linked_warnings(tenant, org_id: str) -> List[dict]:
    """FG-108 — every over-linked invoice line of the tenant (integrity
    screen), including warehouse-only excess (no project cost changed)."""
    ids = sorted({lid for lid in await tenant.warehouse_transactions.distinct(
        "invoice_line_id", {"org_id": org_id, "action": {"$in": list(PATH_B_RECEIPT_ACTIONS)},
                            "invoice_line_id": {"$nin": [None, ""]}}) if lid})
    if not ids:
        return []
    links = await ledger_invoice_line_links(tenant, org_id, ids)
    out = []
    async for line in tenant.invoice_lines.find(
            {"org_id": org_id, "id": {"$in": ids}},
            {"_id": 0, "id": 1, "qty": 1, "unit": 1, "invoice_id": 1, "description": 1}):
        over = over_linked_lines(line, links.get(line["id"], []))
        if over:
            out.append({"code": "PATH_B_LINK_OVER_LINE", "project_id": None,
                        "invoice_line_id": line["id"], "invoice_id": line.get("invoice_id"),
                        "description": line.get("description"),
                        "line_qty": _f(line.get("qty")),
                        "excess_qty": round(over["excess_qty"], 4),
                        "rule": PATH_B_RULE})
    return out


async def _existing_line_ids(tenant, org_id, ids):
    async for line in tenant.invoice_lines.find(
            {"org_id": org_id, "id": {"$in": sorted(ids)}}, {"_id": 0, "id": 1}):
        yield line["id"]


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
    """THE project material cost (5C-C22, 5C-C25/Р17): one helper for every
    finance report — project, package and period.

    ``lines`` — every COUNTED cost line (all totals and the period / day
    splits are sums over it):
      * canonical acceptance / direct delivery (+) and a lot accepted away
        from the project (−) — Р17;
      * „фира" (Р10): a write-off moves its value from „material" to the
        „фира" line — a pair (+V waste, −V material) with total effect 0;
      * legacy issue rows dated BEFORE the tenant cutover (Р13);
      * Path B invoice lines allocated to the project (FG-17).

    ``package_lines`` — the ALLOCATION of the cost to SMR / execution
    packages (consumption per SMR, „фира", pre-cutover legacy issues by
    name). ``by_package`` sums them; ``unallocated_cost`` is the rest of the
    project cost (material on site, not yet consumed, or unmapped).
    """
    rows = await project_cost_rows(tenant, org_id, project_id)
    by_item, by_name = await load_planned_mapping(tenant, org_id, project_id)
    cut = await tenant_cutover(tenant, org_id)
    cutover = _moment(cut["cutover_at"])

    lines: List[dict] = []
    package_lines: List[dict] = []
    accepted_cost = returned_cost = 0.0
    consumed_value = 0.0
    for row in rows:
        at = canonical_moment(row)
        kind = row.get("movement_kind")
        pm = resolve_planned(row.get("item_id"), by_item, by_name)
        common = {
            "source": "canonical", "kind": kind,
            "qty": _f(row.get("quantity")) or 0.0,
            "item_id": row.get("item_id"), "unit": row.get("unit"),
            "material_name": row.get("material_name") or (pm or {}).get("material_name")
            or row.get("item_id") or "",
            "at": at, "period": period_of(at), "ref": row.get("id"),
            # 5C-C23 F-15 — shown by the „Материални отклонения" card.
            "movement_id": row.get("movement_id"), "reason": row.get("reason"),
        }
        if kind in COST_KINDS:
            value = _f(row.get("total_value"))
            lines.append(dict(common, waste=False, value=value, package_id=None,
                              direct_delivery=bool(row.get("direct_delivery"))))
            if value is not None:
                if value >= 0:
                    accepted_cost += value
                else:
                    returned_cost += -value
            continue
        value = _f(row.get("movement_value"))
        package_id = resolve_execution_package(row, by_item, by_name)
        if kind in WASTE_KINDS:
            # Р10 „фира": a reclassification inside the accepted cost.
            lines.append(dict(common, waste=True, value=value, package_id=package_id))
            lines.append(dict(common, kind="write_off_reclass", waste=False,
                              value=None if value is None else -value,
                              package_id=None))
            package_lines.append(dict(common, waste=True, value=value,
                                      package_id=package_id))
        else:
            # Consumption: allocation per SMR / package only (Р17).
            package_lines.append(dict(common, waste=False, value=value,
                                      package_id=package_id))
            if value is not None:
                consumed_value += value

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
            line = {
                "source": "legacy", "kind": "issue", "waste": False,
                "value": round(value, 4), "qty": qty, "item_id": None,
                "unit": ln.get("unit"), "material_name": name,
                "package_id": (pm or {}).get("execution_package_id"),
                "at": at, "period": period_of(at), "ref": txn.get("id"),
            }
            lines.append(line)
            package_lines.append(line)

    # FG-17 / 5C-C26 — Path B: the quantity of an invoice line allocated
    # directly to the project, minus what a canonical receipt of the same
    # line already brought (Path A wins on a proven link).
    inv_rows = await project_invoice_lines(tenant, org_id, project_id)
    links = await ledger_invoice_line_links(
        tenant, org_id, [r.get("id") for r in inv_rows if r.get("id")])
    invoice_cost = invoice_linked_excluded = invoice_path_a = 0.0
    path_b_warnings: List[dict] = []
    counted_invoice: List[dict] = []
    counted_by_line: Dict[str, float] = {}
    for il in inv_rows:
        split = path_b_split(il, project_id, links.get(il.get("id"), []))
        if il.get("id"):
            counted_by_line[il["id"]] = max(split["counted_value"], 0.0)
        invoice_linked_excluded += split["covered_value"]
        invoice_path_a += split["path_a_value"]
        if split["warning"]:
            path_b_warnings.append({
                "code": split["warning"], "project_id": project_id,
                "invoice_line_id": il.get("id"), "invoice_id": il.get("invoice_id"),
                "description": il.get("description"),
                "counted_value": round(split["counted_value"], 2),
                "linked_movement_ids": sorted(
                    r.get("movement_id") for r in links.get(il.get("id"), [])
                    if r.get("movement_id")),
                "rule": PATH_B_RULE,
            })
        value = split["counted_value"]
        if value <= 0:
            continue
        invoice_cost += value
        at = _moment(il.get("created_at"))
        line = {
            "source": "invoice", "kind": "invoice_line", "waste": False,
            "value": round(value, 4), "qty": split["counted_qty"],
            "item_id": None, "unit": il.get("unit"),
            "material_name": il.get("description") or "",
            "package_id": None, "at": at, "period": period_of(at),
            "ref": il.get("id"), "link": split["link"],
        }
        lines.append(line)
        counted_invoice.append(line)

    # INV-CN-01 / Р52(1) (D8, FG-247): supplier credit / debit notes WITHOUT a receipt
    # reversal, on Path B lines of this project — dated by the note (its period), never
    # below the line's counted value. Here, so every reader sees the same cost.
    from app.services.invoice_corrections import supplier_note_cost_lines
    note_lines = await supplier_note_cost_lines(tenant, project_id, counted_by_line)
    lines.extend(note_lines)
    supplier_note_cost = sum(ln["value"] for ln in note_lines)

    # 5C-C26l (F-55-C26-02) — the destination side of a cross-project link.
    seen_conflicts = {(w["code"], w.get("invoice_line_id")) for w in path_b_warnings}
    for w in await project_link_conflicts(tenant, org_id, project_id):
        if (w["code"], w["invoice_line_id"]) not in seen_conflicts:
            path_b_warnings.append(w)

    # 5C-C26l Addendum L (FG-108) — an over-linked lot counts once.
    over_lines, over_warnings = await project_over_link_exclusions(tenant, org_id, project_id)
    lines.extend(over_lines)
    path_b_warnings.extend(over_warnings)
    over_link_excluded = -sum(ln["value"] for ln in over_lines)

    # 5C-C26 point 3 — legacy issues carry no invoice-line / lot reference:
    # an overlap with a counted Path B line of the same material cannot be
    # proven or refuted from the data. Warn; never change the sum silently.
    legacy_by_name: Dict[str, List[dict]] = {}
    for ln in lines:
        if ln["source"] == "legacy" and _norm_name(ln["material_name"]):
            legacy_by_name.setdefault(_norm_name(ln["material_name"]), []).append(ln)
    for inv in counted_invoice:
        matches = legacy_by_name.get(_norm_name(inv["material_name"]))
        if not matches:
            continue
        path_b_warnings.append({
            "code": "PATH_B_LEGACY_OVERLAP_UNPROVEN", "project_id": project_id,
            "invoice_line_id": inv["ref"], "description": inv["material_name"],
            "counted_value": round(inv["value"], 2),
            "legacy_issue_ids": sorted({m["ref"] for m in matches if m.get("ref")}),
            "legacy_value": round(sum(m["value"] or 0 for m in matches), 2),
            "rule": PATH_B_RULE,
            "note": "Фактурен ред към обекта и старо изписване от склада за същия "
                    "материал — няма връзка в данните; и двата се броят. Проверете.",
        })

    total = waste = 0.0
    canonical_cost = 0.0
    partial = False
    for ln in lines:
        value = ln["value"]
        if value is None:
            partial = True
            continue
        total += value
        if ln["source"] == "canonical":
            canonical_cost += value
        if ln["waste"]:
            waste += value

    qty = waste_qty = 0.0
    by_package: Dict[str, float] = {}
    waste_by_package: Dict[str, float] = {}
    qty_by_package: Dict[str, float] = {}
    for ln in package_lines:
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
        if pkg_id:
            by_package[pkg_id] = by_package.get(pkg_id, 0.0) + value
            if ln["waste"]:
                waste_by_package[pkg_id] = waste_by_package.get(pkg_id, 0.0) + value
    allocated = sum(by_package.values())

    has_canonical = len(rows) > 0
    has_legacy = any(ln["source"] == "legacy" for ln in lines)
    source = ("mixed" if has_canonical and has_legacy else
              "canonical" if has_canonical else
              "legacy" if has_legacy or legacy_rows else "none")
    return {
        # total_cost = accepted − returned (canonical, Р17) + pre-cutover
        # legacy (Р13) + Path B invoice lines (FG-17), each lot once.
        # „фира" is a part of it, never added on top.
        "total_cost": round(total, 2),
        "consumption_cost": round(total - waste, 2),   # „material" (non-фира) part
        "material_cost": round(total - waste, 2),
        "waste_cost": round(waste, 2),
        "waste_qty": round(waste_qty, 4),
        "waste_label": WASTE_LABEL,
        "waste_by_package": {k: round(v, 2) for k, v in waste_by_package.items()},
        "consumed_qty": round(qty, 4),
        "consumed_value": round(consumed_value, 2),     # allocation, not cost
        "accepted_cost": round(accepted_cost, 2),
        "returned_cost": round(returned_cost, 2),
        "invoice_cost": round(invoice_cost, 2),
        "supplier_note_cost": round(supplier_note_cost, 2),     # INV-CN-01 Р52(1): − credit, + debit
        "invoice_linked_excluded_cost": round(invoice_linked_excluded, 2),
        # 5C-C26 — selected lines' quantity allocated elsewhere (warehouse →
        # Path A, cost at ACCEPT; client); never project cost here.
        "invoice_path_a_cost": round(invoice_path_a, 2),
        # 5C-C26l Addendum L (FG-108) — the over-linked part of direct deliveries.
        "over_link_excluded_cost": round(over_link_excluded, 2),
        "path_b_rule": PATH_B_RULE,
        "path_b_warnings": path_b_warnings,
        "allocated_cost": round(allocated, 2),
        "unallocated_cost": round(total - allocated, 2),
        "mapped_cost": round(allocated, 2),
        "unmapped_cost": round(total - allocated, 2),
        "by_package": {k: round(v, 2) for k, v in by_package.items()},
        "qty_by_package": {k: round(v, 4) for k, v in qty_by_package.items()},
        "partial_cost_data": partial,
        "has_data": len(lines) > 0 or len(package_lines) > 0,
        "cost_rule": COST_RULE,
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
        "package_lines": package_lines,
        "rows": rows,
        "by_item": by_item,
        "by_name": by_name,
    }


COST_RULE = "R17_cost_at_acceptance"


async def path_b_integrity_warnings(tenant, org_id: str) -> List[dict]:
    """5C-C26 point 3 — the Path B warnings of every project of the tenant
    that has a supplier invoice line allocated to it (read-only; the same
    ``project_material_cost`` every report uses, so the screen and the
    reports cannot disagree)."""
    project_ids = set()
    cursor = tenant.invoice_lines.find(
        {"org_id": org_id,
         "$or": [{"allocations.type": "project"}, {"allocation_type": "project"}]},
        {"_id": 0, "allocations": 1, "allocation_type": 1, "allocation_ref_id": 1},
    )
    async for line in cursor:
        for a in effective_allocations(line):
            if a["type"] == "project" and a["ref_id"]:
                project_ids.add(a["ref_id"])
    # 5C-C26l — destination projects of linked direct deliveries too.
    for pid in await tenant.warehouse_transactions.distinct(
            "project_id", {"org_id": org_id, "action": "receive_from_supplier_to_project",
                           "invoice_line_id": {"$nin": [None, ""]}}):
        if pid:
            project_ids.add(pid)
    out: List[dict] = []
    for pid in sorted(project_ids):
        cost = await project_material_cost(tenant, org_id, pid)
        out.extend(cost["path_b_warnings"])
    # FG-108 — over-linked lines no project shows (warehouse-only excess).
    shown = {w.get("invoice_line_id") for w in out if w["code"] == "PATH_B_LINK_OVER_LINE"}
    out.extend(w for w in await tenant_over_linked_warnings(tenant, org_id)
               if w["invoice_line_id"] not in shown)
    return out


def cost_basis(cost: Dict[str, Any]) -> Dict[str, Any]:
    """The JSON-safe Р13 basis of a cost result (for report payloads)."""
    keys = ("total_cost", "consumption_cost", "waste_cost", "source",
            "canonical_cost", "legacy_cost", "legacy_excluded_cost",
            "legacy_undated_cost", "cutover_at", "cutover_source",
            "partial_cost_data",
            # 5C-C25 (Р17, FG-17)
            "cost_rule", "accepted_cost", "returned_cost", "invoice_cost",
            "invoice_linked_excluded_cost", "allocated_cost", "supplier_note_cost",
            # 5C-C26 (FG-17 per D-04)
            "invoice_path_a_cost", "path_b_rule", "path_b_warnings",
            "unallocated_cost", "consumed_value")
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


def waste_lines(cost: Dict[str, Any]) -> List[dict]:
    """5C-C23 F-15 — the counted „фира" lines (canonical write-offs from the
    project) of a ``project_material_cost`` result. Read-only view over the
    same list every finance report sums; no second register."""
    return [ln for ln in cost["lines"] if ln["waste"]]


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
    """Material actual of one execution package (read time): the project
    cost ALLOCATED to the package — consumption + фира (+ pre-cutover
    legacy) — Р17: allocation, not a second cost."""
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
        "invoice_cost": cost["invoice_cost"],
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
