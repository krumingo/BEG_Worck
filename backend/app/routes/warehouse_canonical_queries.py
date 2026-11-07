"""
Read-only canonical warehouse views (TASK 5C).

These endpoints never write. They project directly off the canonical
ledger (`warehouse_transactions`) so the UI never shows stale projected
numbers inconsistent with the ledger. Permission scope is per project /
location; a user with no read grant for a location receives 403.
"""
from __future__ import annotations

import re

from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.db import db
from app.deps.auth import get_current_user
from app.tenancy.data_access import TenantData
from app.tenancy.guard import TenantContext
from app.permissions.deps import require_permission

from app.services.warehouse_movements import LocationKey, LocationType, MovementState
from app.services.warehouse_movements.queries import (
    item_balance_by_location,
    movement_history,
    stock_at,
    integrity_warnings,
)
from app.services.warehouse_movements.errors import WarehouseMovementError
from app.permissions.service import evaluate_permission


router = APIRouter(prefix="/warehouse/canonical", tags=["warehouse_canonical_queries"])


def _tenant_for(user: dict) -> TenantData:
    return TenantData.for_user(db, user)


async def _authorized_scope_locations(ctx, user) -> Optional[List]:
    """Return the (scope_type, scope_id) tuples the caller is allowed
    to see at project / location granularity, computed via the REAL
    Permission Service decision engine (CODEX C13.5).

    * `None` means the caller holds a company-level (module-wide) grant
      for `warehouse.read_stock` — they see everything.
    * `[]` means the caller holds NO relevant grant — they see
      NOTHING. The caller must deny or return empty; NOT fall back to
      unrestricted (which would be fail-open).
    * `[(scope_type, scope_id), ...]` is the exact authorized set.

    No JWT-embedded assignments; no `role_assignments` on the user
    dict. The Permission Service's own `_evaluate_one` decides each
    assignment under the same semantics `evaluate_permission` uses on
    the write path, so a RoleAssignment that is EXPIRED
    (`valid_to` < now), REVOKED (`status="revoked"`), WRONG MODULE
    (`module != "warehouse"`), or that lacks `warehouse.read_stock`
    is denied by `_evaluate_one` and never contributes to the scope
    set — matching the write-path semantics exactly.

    Required inputs: `ctx.user_id` and `ctx.tenant_id`. If the ctx
    does not carry them, we treat the session as absent and return
    `[]` (deny-closed), never fall back to the user dict's embedded
    identity.
    """
    # 5C-C26f (F-16, Р28) — off / shadow: the legacy role decides with the
    # same rules; a granting role reads company-wide, as the real
    # (company-scope) assignment does in enforce.
    legacy = await _legacy_read(ctx, "warehouse.read_stock")
    if legacy is not _ENFORCE:
        return None
    from app.permissions.service import (
        _load_assignments, _evaluate_one, ALLOWED,
    )
    from datetime import datetime, timezone

    user_id = getattr(ctx, "user_id", None) if ctx is not None else None
    tenant_id = getattr(ctx, "tenant_id", None) if ctx is not None else None
    if not user_id or not tenant_id:
        # No server-resolved session identity → deny-closed. We do
        # NOT fall back to the raw user dict's `id`/`org_id`: the
        # TenantContext is the only authority.
        return []

    assignments = await _load_assignments(user_id, tenant_id)
    if not assignments:
        return []

    now = datetime.now(timezone.utc)
    allowed: List[Tuple[str, str]] = []
    for a in assignments:
        # Walk every assignment through the SAME decision engine the
        # write path uses. We ask it to decide against the exact
        # scope the assignment carries, so a project-scoped grant is
        # tested at ("project", <id>), a location-scoped grant at
        # ("location", <id>), and a company grant at (None, None).
        a_scope_type = a.get("scope_type")
        a_scope_id = a.get("scope_id")
        try:
            reason = _evaluate_one(
                a, "warehouse.read_stock",
                module="warehouse",
                scope_type=a_scope_type if a_scope_type != "company" else None,
                scope_id=a_scope_id if a_scope_type != "company" else None,
                amount=None, now=now,
            )
        except Exception:
            # Malformed assignment: deny itself only. Never a crash
            # of the whole walk.
            continue
        if reason is not ALLOWED:
            continue
        # The assignment is live, in-window, carries the capability,
        # and matches the warehouse module. Its granted scope now
        # enters the authorized set.
        if a_scope_type in (None, "company"):
            # Company-wide grant = unrestricted — short-circuit.
            return None
        if a_scope_type and a_scope_id:
            allowed.append((a_scope_type, a_scope_id))
    # Deny-by-default: empty list means EMPTY RESULT, not unrestricted.
    return allowed


_ENFORCE = object()


async def _legacy_read(ctx, permission: str):
    """5C-C26f (F-16) — in off / shadow the canonical GETs go through the
    same legacy gate as the writes (Р28): 403 unless the legacy role holds
    ``permission``; returns the granting roles. ``_ENFORCE`` in enforce (the
    Permission Service decides)."""
    from app.permissions.deps import MODE_OFF, MODE_SHADOW
    if getattr(ctx, "mode", None) not in (MODE_OFF, MODE_SHADOW):
        return _ENFORCE
    from app.services.warehouse_movements.errors import PermissionDeniedError
    from app.services.warehouse_movements.legacy_gate import legacy_read_roles
    try:
        return await legacy_read_roles(ctx, permission=permission)
    except PermissionDeniedError as exc:
        raise HTTPException(status_code=403, detail={
            "error_code": "PERMISSION_DENIED", "action": permission,
            "reason": exc.context.get("reason_code"), "decided_by": "legacy_role"})


async def _member_scope(ctx, permission: str):
    """5C-C26h (FG-60, FLOW-002 scope, Р20) — what a caller may see of the
    canonical stock. None = company-wide (a company / warehouse role grants
    the read). Otherwise (the read is granted ONLY by project-bound roles:
    SiteManager, Technician, PM) the set of in-date member projects — every
    read is narrowed to them, in every mode."""
    from app.services.warehouse_movements.legacy_gate import (
        PM_ROLES, PROJECT_BOUND_ROLES, enforce_read_roles, member_projects,
    )
    roles = await _legacy_read(ctx, permission)
    if roles is _ENFORCE:
        try:
            roles = await enforce_read_roles(ctx, permission=permission)
        except Exception:                       # registry unreachable → deny
            raise HTTPException(status_code=403, detail={
                "error_code": "PERMISSION_DENIED", "reason": "UNVERIFIED"})
    if not roles:
        raise HTTPException(status_code=403, detail={
            "error_code": "PERMISSION_DENIED", "action": permission})
    if set(roles) - (PROJECT_BOUND_ROLES | PM_ROLES):
        return None
    tenant = _tenant_from_ctx(ctx)
    return await member_projects(tenant._db, ctx.org_id, ctx.user_id, roles)  # pylint: disable=protected-access


async def _bucket_project(ctx, location_type, location_id) -> Optional[str]:
    """The project of a project / subproject bucket (DB-resolved), else None."""
    from app.services.warehouse_movements.errors import WarehouseMovementError
    from app.services.warehouse_movements.service import resolve_subproject_parent
    if location_type == LocationType.PROJECT.value:
        return location_id
    if location_type == LocationType.SUBPROJECT.value and location_id:
        tenant = _tenant_from_ctx(ctx)
        try:
            return await resolve_subproject_parent(tenant._db, ctx.org_id, location_id)  # pylint: disable=protected-access
        except WarehouseMovementError:
            return location_id
    return None


def _loc_fields(loc) -> tuple:
    if not isinstance(loc, dict):
        return (None, None)
    return (loc.get("location_type") or loc.get("type"),
            loc.get("location_id") or loc.get("id"))


async def _row_projects(ctx, row: dict, cache: dict) -> set:
    """Projects a ledger / balance row belongs to (project_id + buckets)."""
    out = set()
    if row.get("project_id"):
        out.add(row["project_id"])
    locs = [row] if "location_type" in row and "location_id" in row else []
    locs += [row.get("source"), row.get("destination")]
    for loc in locs:
        lt, lid = _loc_fields(loc)
        if lt in (LocationType.PROJECT.value, LocationType.SUBPROJECT.value):
            key = (lt, lid)
            if key not in cache:
                cache[key] = await _bucket_project(ctx, lt, lid)
            if cache[key]:
                out.add(cache[key])
    return out


def _forbidden(action: str, **ctx_detail):
    return HTTPException(status_code=403, detail={
        "error_code": "PERMISSION_DENIED", "action": action,
        "reason": "OUTSIDE_MEMBER_SCOPE", **ctx_detail})


async def _authorize_resource_scope(
    ctx: TenantContext, *, action: str,
    location_type: Optional[str], location_id: Optional[str],
    project_id: Optional[str],
) -> None:
    """CODEX C06 — reads enforce RESOURCE scope, not just module.

    If the caller references a specific location or project, the
    Permission Service re-evaluates `action` against that exact scope;
    a module-wide grant is NOT enough to look at every warehouse.
    """
    scopes = []
    if project_id:
        scopes.append(("project", project_id))
    if location_id and location_type not in {
        None, LocationType.IN_TRANSIT.value,
        LocationType.UNRESOLVED.value,
        LocationType.SUPPLIER.value,
    }:
        scopes.append(("location", location_id))
    # 5C-C26f (F-16, Р28) — off / shadow: the legacy role decides the read
    # with the same rules as enforce (catalog action + project relation).
    legacy = await _legacy_read(ctx, action)
    if legacy is not _ENFORCE:
        await _within_member_scope(ctx, action, location_type=location_type,
                                   location_id=location_id, project_id=project_id)
        return
    for scope_type, scope_id in scopes:
        decision = await evaluate_permission(
            ctx, action, module="warehouse",
            scope_type=scope_type, scope_id=scope_id,
        )
        if not decision.allowed:
            raise HTTPException(status_code=403, detail={
                "error_code": "PERMISSION_DENIED",
                "action": action,
                "scope_type": scope_type,
                "scope_id": scope_id,
            })
    # 5C-C26f/h (C26E-1, FG-60) — enforce: the same member scope as
    # off / shadow for a caller whose read is granted only by project-bound
    # roles (the real grant is company-scope, which the scope check alone
    # does not narrow).
    await _within_member_scope(ctx, action, location_type=location_type,
                               location_id=location_id, project_id=project_id)


async def _within_member_scope(ctx, action, *, location_type, location_id, project_id):
    """FG-60: a project-bound reader asks only about its member projects —
    a warehouse / person / vehicle bucket or a foreign project → 403."""
    scope = await _member_scope(ctx, action)
    if scope is None:
        return
    if project_id and project_id not in scope:
        raise _forbidden(action, scope_type="project")
    if location_id and location_type not in {
            None, LocationType.IN_TRANSIT.value, LocationType.UNRESOLVED.value,
            LocationType.SUPPLIER.value}:
        bucket = await _bucket_project(ctx, location_type, location_id)
        if bucket is None or bucket not in scope:
            raise _forbidden(action, scope_type="location")


def _tenant_from_ctx(ctx: TenantContext) -> TenantData:
    """CODEX C13.5 — build the data path from the server-resolved
    TenantContext, NEVER from the raw user dict.

    `require_permission(...)` already resolves `ctx.tenant_id` on the
    server; using it here means the data layer sees exactly the tenant
    the Permission Service decided on, and cross-tenant leakage via a
    forged `user["org_id"]` is impossible.
    """
    return TenantData.for_resolved_org(db, ctx.org_id)


# ───────────── FG-23 (Р20) — money only for finance roles ─────────────
# Р20 (Крум 06.11.2026): the company's money is seen only by Owner / Admin /
# Accountant. Warehouse, site_manager, technician, viewer, driver (and every
# other role) see the canonical stock and history as QUANTITIES only — no
# total_value, unit_value or valued layers. Decided from the caller's active
# RoleAssignments (same records / validity as the Permission Service).
FINANCE_VALUE_ROLES = frozenset({"owner", "admin", "accountant"})
# Package 5C-C26 Addendum A: procurement is NOT in Р20 — left unchanged (it
# keeps seeing values as before); recorded in HANDOFF 5C-C26 for Крум.
UNCHANGED_VALUE_ROLES = frozenset({"procurement"})
# Р32 (Крум 06.11.2026, refines Р20 for the warehouse): the warehousekeeper
# sees the unit prices / values of the WAREHOUSE (stock, balance, history,
# the command response) and enters the price on receive — but no project
# finance: the integrity warnings' Path B amounts stay hidden from them.
WAREHOUSE_VALUE_ROLES = frozenset({"warehouse"})
VALUE_KEYS = frozenset({"unit_value", "total_value", "movement_value", "value",
                        "line_value", "layer_value",
                        # 5C-C26 audit C26A-2 — Path B integrity warnings.
                        "counted_value", "covered_value", "legacy_value"})
# 5C-C26 audit C26A-1/2: any other money-named key is dropped too (the audit
# probe's rule: value / cost / price / amount), so a new field cannot leak.
_MONEY_KEY = re.compile(r"(value|cost|price|amount)", re.I)
_NOT_MONEY = frozenset({"values_hidden"})


def is_money_key(key: Any) -> bool:
    return isinstance(key, str) and key not in _NOT_MONEY and (
        key in VALUE_KEYS or bool(_MONEY_KEY.search(key)))


async def _sees_values(ctx, *, warehouse_values: bool = True) -> bool:
    """True when the caller may see money here. ``warehouse_values`` — the
    payload is warehouse stock / prices (Р32: the warehousekeeper too);
    False for project finance (the Path B integrity warnings)."""
    roles = FINANCE_VALUE_ROLES | UNCHANGED_VALUE_ROLES
    if warehouse_values:
        roles = roles | WAREHOUSE_VALUE_ROLES
    return await _role_in(ctx, roles)


async def _role_in(ctx, roles) -> bool:
    from datetime import datetime, timezone
    from app.permissions import service as perm
    from app.services.warehouse_movements.write_off_policy import _active_assignments
    # 5C-C26d (FG-39) — off / shadow have no RoleAssignments decision: the
    # legacy session role decides, mapped by the catalog's LEGACY_ROLE_MAP
    # onto the same role sets (the C26c Р27 pattern). Shadow does not let
    # the new decision change the outcome.
    from app.permissions.deps import MODE_OFF, MODE_SHADOW
    if getattr(ctx, "mode", None) in (MODE_OFF, MODE_SHADOW):
        from app.permissions.catalog import LEGACY_ROLE_MAP
        user = getattr(ctx, "user", None) or {}
        role_id = LEGACY_ROLE_MAP.get(user.get("role") or "")
        return role_id in roles
    user_id = getattr(ctx, "user_id", None)
    tenant_id = getattr(ctx, "tenant_id", None)
    if not user_id or not tenant_id:
        return False
    try:
        loaded = await perm._load_assignments(user_id, tenant_id)
    except Exception:      # registry unreachable → no money (fail closed)
        return False
    active = _active_assignments(loaded, datetime.now(timezone.utc))
    return any(a.get("role_id") in roles for a in active)


def strip_values(obj: Any) -> Any:
    """Drop every money key (recursively); quantities stay."""
    if isinstance(obj, dict):
        return {k: strip_values(v) for k, v in obj.items() if not is_money_key(k)}
    if isinstance(obj, list):
        return [strip_values(v) for v in obj]
    return obj


async def _values_for(ctx, data: Dict[str, Any], *,
                      warehouse_values: bool = True) -> Dict[str, Any]:
    if await _sees_values(ctx, warehouse_values=warehouse_values):
        return data
    out = strip_values(data)
    out["values_hidden"] = True       # FG-23 / Р20 — the screen shows quantities only
    return out


@router.get("/stock/{item_id}")
async def read_stock(
    item_id: str,
    location_type: str = Query(...),
    location_id: str = Query(...),
    state: str = Query("free"),
    ctx: TenantContext = Depends(require_permission(
        "warehouse.read_stock", module="warehouse")),
) -> Dict[str, Any]:
    try:
        key = LocationKey(
            location_type=LocationType(location_type),
            location_id=location_id,
            state=MovementState(state),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error_code": "BAD_LOCATION",
                                                     "message": str(exc)})
    await _authorize_resource_scope(
        ctx, action="warehouse.read_stock",
        location_type=location_type, location_id=location_id, project_id=None,
    )
    tenant = _tenant_from_ctx(ctx)
    return await _values_for(ctx, await stock_at(
        tenant.warehouse_transactions,
        tenant_id=ctx.tenant_id, item_id=item_id, location=key,
    ))


@router.get("/balance/{item_id}")
async def read_balance_by_location(
    item_id: str,
    ctx: TenantContext = Depends(require_permission(
        "warehouse.read_stock", module="warehouse")),
) -> Dict[str, Any]:
    """CODEX C11.7 + C13.5 — balances are filtered by the caller's
    authorized location/project RoleAssignments, resolved via the
    real Permission Service decision engine against the
    server-resolved TenantContext. A caller permitted on warehouse A
    but not B will not see B's balance here; expired/revoked grants
    deny; empty-grant → empty result.
    """
    tenant = _tenant_from_ctx(ctx)
    allowed = await _authorized_scope_locations(ctx, user=None)
    rows = await item_balance_by_location(
        tenant.warehouse_transactions,
        tenant_id=ctx.tenant_id, item_id=item_id,
        allowed_locations=allowed,
    )
    # 5C-C26h (FG-60): a project-bound reader sees only its member projects.
    scope = await _member_scope(ctx, "warehouse.read_stock")
    if scope is not None:
        cache: dict = {}
        rows = [r for r in rows if (await _row_projects(ctx, r, cache)) & scope]
    from app.services.warehouse_movements.queries import ledger_checkpoint
    checkpoint = await ledger_checkpoint(
        tenant.warehouse_transactions, tenant_id=ctx.tenant_id,
    )
    return await _values_for(ctx, {
        "tenant_id": ctx.tenant_id,
        "item_id": item_id,
        "balances": rows,
        "ledger_checkpoint": checkpoint,
    })


@router.get("/history")
async def read_history(
    item_id: Optional[str] = None,
    location_type: Optional[str] = None,
    location_id: Optional[str] = None,
    project_id: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
    cursor_after: Optional[str] = None,
    ctx: TenantContext = Depends(require_permission(
        "warehouse.read_history", module="warehouse")),
) -> Dict[str, Any]:
    await _authorize_resource_scope(
        ctx, action="warehouse.read_history",
        location_type=location_type, location_id=location_id,
        project_id=project_id,
    )
    tenant = _tenant_from_ctx(ctx)
    data = await movement_history(
        tenant.warehouse_transactions,
        tenant_id=ctx.tenant_id, item_id=item_id,
        location_type=location_type, location_id=location_id,
        project_id=project_id, since_iso=since, until_iso=until,
        limit=limit, cursor_after=cursor_after,
    )
    # 5C-C26h (FG-60): an unfiltered history of a project-bound reader is
    # narrowed to the rows of its member projects.
    scope = await _member_scope(ctx, "warehouse.read_history")
    if scope is not None:
        cache: dict = {}
        data["rows"] = [r for r in data.get("rows", [])
                        if (await _row_projects(ctx, r, cache)) & scope]
        data["scope"] = "member_projects"
    return await _values_for(ctx, data)


PROJECT_SCOPED_WARNING_CODES = frozenset({
    "UNRESOLVED_IN_TRANSIT_AGING",
    # 5C-C26 — Path B overlap warnings are about one project.
    "PATH_B_LEGACY_OVERLAP_UNPROVEN", "PATH_B_LINK_QTY_UNVERIFIED",
    "PATH_B_LINK_AMBIGUOUS",
})


@router.get("/integrity-warnings")
async def read_integrity_warnings(
    ctx: TenantContext = Depends(require_permission(
        "warehouse.read_stock", module="warehouse")),
) -> Dict[str, Any]:
    """CODEX C11.7 + C13.5 — integrity warnings are filtered to the
    caller's authorized locations/projects, resolved via the real
    Permission Service decision engine. Owner/Admin sees everything
    (their scope includes every warehouse); a scoped operator sees
    only warnings in their own scope. Expired/revoked RoleAssignments
    deny.
    """
    tenant = _tenant_from_ctx(ctx)
    data = await integrity_warnings(
        tenant.warehouse_transactions, tenant_id=ctx.tenant_id,
    )
    # 5C-C26 (FG-17 per FLOW-043 D-04) — Path A / Path B overlaps that the
    # data cannot prove (or whose quantity cannot be verified), per project,
    # from the same helper every finance report uses.
    from app.services.canonical_material_cost import path_b_integrity_warnings
    data["warnings"].extend(await path_b_integrity_warnings(tenant, ctx.tenant_id))
    # FG-23 (Р20) / audit C26A-2 — the Path B warnings carry money.
    # Р32: the Path B warnings are project finance — not for the keeper.
    data = await _values_for(ctx, data, warehouse_values=False)
    # 5C-C26h (FG-60): a project-bound reader sees only its member projects'
    # warnings (a warehouse-only warning is outside its scope).
    scope = await _member_scope(ctx, "warehouse.read_stock")
    if scope is not None:
        data["warnings"] = [w for w in data.get("warnings", [])
                            if w.get("project_id") in scope]
        data["scope"] = "member_projects"
    allowed = await _authorized_scope_locations(ctx, user=None)
    if allowed is not None:
        allowed_set = {tuple(x) for x in allowed}
        filtered = []
        for w in data.get("warnings", []):
            loc = w.get("location")
            dispatch_loc = ("warehouse", loc.get("id")) if loc else None
            if loc and (loc.get("type"), loc.get("id")) not in allowed_set:
                continue
            if w.get("code") in PROJECT_SCOPED_WARNING_CODES:
                # scope match on project
                if w.get("project_id") and ("project", w["project_id"]) not in allowed_set:
                    continue
            filtered.append(w)
        data["warnings"] = filtered
        data["scope"] = "authorized_subset"
    return data
