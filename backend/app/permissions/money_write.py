"""
SEC-01 (decision R14, Krum 06.11.2026) — money writes only for the finance roles.

Source of the rule: PM-01 §5.1 (``docs/architecture/PM-01_PERMISSION_MODE_REPORT.md``)
proved on real Mongo that Viewer/Driver/Technician/Warehousekeeper could WRITE cash,
bonus and overhead transactions, overhead snapshots, project price modifiers, labor
entries, material waste and the paying client of a project. The established rule of
the sibling write endpoints in the same domain is Owner/Admin/Accountant:

  * ``app/routes/clients.py:27-29``  ``finance_permission`` (used at :177, :243, :282);
  * ``app/routes/finance.py:36-38``  ``finance_permission``;
  * ``app/routes/overhead.py:36-41``  ``check_overhead_access(write=True)``.

``require_money_write`` is the SAME W0-02 mechanism the migrated routes already use
(``require_permission`` with a legacy check in off/shadow, the Permission Service in
enforce — ``app/permissions/deps.py``), so the three modes give one answer:

  off      legacy role check only -> 403 before the handler runs;
  shadow   legacy role check decides, the catalog is evaluated in parallel (parity);
  enforce  Tenant Guard -> Permission Service decides (catalog action below), a denial
           writes the canonical "permission denied" AuditEvent, never a business row.

The handlers still read and write through the legacy global handle with
``user["org_id"]``; in enforce that is only correct when the active tenant's database
IS that handle and the identity's org is that tenant — the exact guard
``require_admin`` applies (``app/deps/auth.py:59-87``). Otherwise 409, before any write.

The dependency is declared BEFORE the module (subscription) dependency of each route,
so a denied role is refused before any read of tenant data.

SEC-01-C01 (R14 + R16, Krum 06.11.2026) extends the same mechanism to EVERY write route
on the same resources:

  * ``require_money_write(..., roles=...)`` — also used with the narrower Owner/Admin
    rule of ``PUT /price-modifiers/org`` (the rule already in that handler);
  * ``require_field_cost_write`` — R16 for labor entries and material waste:
    Owner/Admin/Accountant everywhere; SiteManager/Technician ONLY on a project they are
    a member of (``project_team``, the same membership as ``can_access_project``);
    Viewer/Driver/any other role 403. In enforce the Permission Service decides with
    scope ``project``: a company assignment (Accountant/Owner/Admin) covers every
    project; a SiteManager/Technician has the action only on the project-scope
    assignment that mirrors their membership (``catalog.project_membership_actions``);
  * ``check_money_write`` — the same decision from inside a handler, for writes that
    touch the resource only for some bodies (``owner_*`` of PUT/POST /projects).
"""
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request

from app.db import db
from app.permissions.deps import require_permission, require_legacy_data_path
from app.tenancy.guard import TenantContext

# Legacy role strings of the finance roles (same list as the sibling rule above).
FINANCE_WRITE_ROLES = ("Admin", "Owner", "Accountant")
# SEC-01-C01: PUT /price-modifiers/org keeps its existing, narrower rule.
OWNER_ADMIN_ROLES = ("Admin", "Owner")
# R16: the legacy role strings that may write field costs on MEMBER projects only.
FIELD_MEMBER_ROLES = ("SiteManager", "Technician")


def _legacy_role_check(roles):
    def check(user: dict, request) -> bool:
        return user.get("role") in roles
    return check


_legacy_finance_role = _legacy_role_check(FINANCE_WRITE_ROLES)


async def _legacy_data_path_guard(ctx: TenantContext) -> None:
    if ctx.enforced:
        await require_legacy_data_path(ctx, db)
        if ctx.user.get("org_id") != ctx.org_id:
            raise HTTPException(status_code=409, detail={
                "error_code": "TENANT_DATA_PATH_NOT_MIGRATED",
                "message": "This operation is not yet available when the active tenant "
                           "differs from the identity's legacy organization"})


def require_money_write(action: str, *, module: str, resource_type: str,
                        roles=FINANCE_WRITE_ROLES):
    """Dependency for one money-write endpoint. Returns the session user."""
    permission = require_permission(
        action, module=module, scope="company", resource_type=resource_type,
        legacy_check=_legacy_role_check(tuple(roles)),
    )

    async def dependency(ctx: TenantContext = Depends(permission)) -> dict:
        await _legacy_data_path_guard(ctx)
        return ctx.user

    dependency.sec01_action = action      # inspected by tests/test_sec_01_*.py
    return dependency


async def check_money_write(request: Request, user: dict, action: str, *, module: str,
                            resource_type: str) -> dict:
    """The require_money_write decision, called from inside a handler BEFORE its write."""
    permission = require_permission(
        action, module=module, scope="company", resource_type=resource_type,
        legacy_check=_legacy_finance_role,
    )
    ctx = await permission(request, user)
    await _legacy_data_path_guard(ctx)
    return ctx.user


# ── R16: labor entries and material waste ───────────────────────────────────────
async def _project_id_from_path(request: Request) -> Optional[str]:
    value = request.path_params.get("project_id")
    return value if isinstance(value, str) and value else None


async def _project_id_from_body(request: Request) -> Optional[str]:
    try:
        payload: Any = await request.json()      # already read and cached by FastAPI
    except Exception:                            # noqa: BLE001 — no/invalid body: no project
        return None
    value = payload.get("project_id") if isinstance(payload, dict) else None
    return value if isinstance(value, str) and value else None


_PROJECT_SOURCES = {"path": _project_id_from_path, "body": _project_id_from_body}


def require_field_cost_write(action: str, *, module: str, resource_type: str,
                             project_from: str, member_roles=FIELD_MEMBER_ROLES):
    """R16 dependency. ``project_from``: "path" ({project_id}) or "body" (JSON project_id).

    ``member_roles`` (SEC-02): the legacy roles that get the action on a project they are
    a CURRENT member of (date-aware ``project_team.membership_filter``). R16 default:
    SiteManager + Technician. SEC-02 R20-2B passes ("SiteManager",).
    """
    get_project = _PROJECT_SOURCES[project_from]
    member_roles = tuple(member_roles)

    async def legacy_check(user: dict, request: Request) -> bool:
        role = user.get("role")
        if role in FINANCE_WRITE_ROLES:
            return True
        if role not in member_roles:
            return False
        project_id = await get_project(request)
        if not project_id:
            return False
        from app.tenancy import project_team
        # The tenant is the session user's own (server-loaded), never a request value:
        # another tenant's project id is never a membership of this user.
        return await project_team.is_member(project_team.tenant_for(db, user),
                                            user["id"], project_id)

    permission = require_permission(
        action, module=module, scope="project", resource_type=resource_type,
        scope_id_getter=get_project, legacy_check=legacy_check,
    )

    async def dependency(ctx: TenantContext = Depends(permission)) -> dict:
        await _legacy_data_path_guard(ctx)
        return ctx.user

    dependency.sec01_action = action
    dependency.sec01_rule = "R16"
    return dependency


# ── SEC-02 (R20): reading money ─────────────────────────────────────────────────
# The registry (endpoint -> action -> rule -> canon) is app/permissions/finance_read.py.
# Nothing below is a second mechanism: R20-1/R20-2 IS require_money_write with a read
# action, R20-2B IS the R16 member dependency with the Technical Manager only.

def require_finance_read(action: str, *, module: Optional[str], resource_type: str,
                         roles=FINANCE_WRITE_ROLES):
    """R20-1 / R20-2: Owner/Admin/Accountant only, company scope, all three modes.

    ``roles`` (SEC-02-A, D9): the employee file also admits SiteManager, whose handler
    then serves the no-money version."""
    dependency = require_money_write(action, module=module, resource_type=resource_type,
                                     roles=roles)
    dependency.sec02_action = action
    return dependency


def require_project_budget_read(action: str, *, module: Optional[str], resource_type: str):
    """R20-2B: finance roles everywhere; SiteManager only on a current member project."""
    dependency = require_field_cost_write(action, module=module, resource_type=resource_type,
                                          project_from="path", member_roles=("SiteManager",))
    dependency.sec02_action = action
    dependency.sec01_rule = "R20-2B"
    return dependency


async def money_values_visible(request: Request, user: dict, *, action: Optional[str] = None,
                               roles=FINANCE_WRITE_ROLES) -> bool:
    """R20-5: may this caller see money VALUES on a shared screen?

    off/shadow: the legacy finance roles (same list as the money writes). enforce: the
    Permission Service decides ``finance.money_values.read`` at company scope (Owner/Admin
    full set, Accountant) — never a fallback to ``users.role``. No denial audit: a hidden
    value is not a refused action.
    """
    from app.permissions.deps import current_mode, MODE_ENFORCE
    from app.permissions.finance_read import MONEY_VALUES_READ
    if current_mode() != MODE_ENFORCE:
        return user.get("role") in tuple(roles)
    from app.tenancy.guard import get_tenant_context
    from app.permissions.service import evaluate_permission
    ctx = await get_tenant_context(request, user)
    decision = await evaluate_permission(ctx, action or MONEY_VALUES_READ, module=None,
                                         scope_type="company", scope_id=None)
    return bool(decision.allowed)


def without_keys(value: Any, keys) -> Any:
    """A copy of ``value`` with every dict key in ``keys`` removed, at any depth."""
    if isinstance(value, dict):
        return {k: without_keys(v, keys) for k, v in value.items() if k not in keys}
    if isinstance(value, list):
        return [without_keys(v, keys) for v in value]
    return value


def _session_user(kwargs) -> dict:
    """The session user of a handler: its ``user`` parameter, or its W0-02 ``ctx``."""
    if "user" in kwargs:
        return kwargs["user"]
    return kwargs["ctx"].user


def _request_param(sig):
    """FastAPI injects ONE Request per endpoint: reuse the handler's own Request
    parameter if it has one, else add a keyword-only ``_sec02_request``."""
    import inspect
    for name, p in sig.parameters.items():
        if p.annotation is Request:
            return name, list(sig.parameters.values())
    extra = inspect.Parameter("_sec02_request", inspect.Parameter.KEYWORD_ONLY,
                              annotation=Request)
    return None, list(sig.parameters.values()) + [extra]


def strip_money_for_non_finance(fn=None, *, keep=()):
    """SEC-02-A (R20-5M, D1): decorator for a GET whose response MIXES money with
    quantities / statuses. Placed under ``@router.get``. The handler runs as before; for a
    caller without ``finance.money_values.read`` (off/shadow: legacy finance roles;
    enforce: the Permission Service) every money key is removed from the response
    (``finance_read.strip_money``). The handler must take the session user as ``user``.
    ``keep``: key names that are counts, not money, in this response
    (``@strip_money_for_non_finance(keep=("total",))``).
    """
    if fn is None:
        return lambda f: strip_money_for_non_finance(f, keep=keep)
    import functools
    import inspect
    from fastapi.encoders import jsonable_encoder
    from app.permissions.finance_read import strip_money

    sig = inspect.signature(fn)
    if "user" not in sig.parameters and "ctx" not in sig.parameters:
        raise TypeError("%s: strip_money_for_non_finance needs 'user' or 'ctx'" % fn.__name__)
    own_request, params = _request_param(sig)

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        request = kwargs[own_request] if own_request else kwargs.pop("_sec02_request")
        result = await fn(*args, **kwargs)
        if await money_values_visible(request, _session_user(kwargs)):
            return result
        return strip_money(jsonable_encoder(result), keep)

    wrapper.__signature__ = sig.replace(parameters=params)
    wrapper.sec02_strips_money = True
    wrapper.sec02_keep = tuple(keep)
    return wrapper


async def budget_view_visible(request: Request, user: dict, project_id: str) -> bool:
    """SEC-02-B (R20-5B, FG-43): is this a Technical Manager who is a CURRENT member of the
    project? off/shadow: legacy SiteManager + date-aware project_team membership; enforce:
    the R20-2B budget action on the project-scope assignment mirroring that membership."""
    from app.permissions.deps import current_mode, MODE_ENFORCE
    if current_mode() != MODE_ENFORCE:
        if user.get("role") != "SiteManager" or not project_id:
            return False
        from app.tenancy import project_team
        return await project_team.is_member(project_team.tenant_for(db, user), user["id"],
                                            project_id)
    from app.tenancy.guard import get_tenant_context
    from app.permissions.service import evaluate_permission
    ctx = await get_tenant_context(request, user)
    decision = await evaluate_permission(ctx, "finance.project_budget_burn.read", module=None,
                                         scope_type="project", scope_id=project_id)
    return bool(decision.allowed)


def strip_for_budget_view(fn):
    """SEC-02-B (R20-5B, FG-43) decorator, under ``@router.get``: finance roles get the full
    response; a Technical Manager member of ``{project_id}`` gets budget + spent +
    remaining without client / subcontractor prices; every other caller no money."""
    import functools
    import inspect
    from fastapi.encoders import jsonable_encoder
    from app.permissions.finance_read import strip_money, BUDGET_VIEW_HIDDEN_FIELDS

    sig = inspect.signature(fn)
    own_request, params = _request_param(sig)

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        request = kwargs[own_request] if own_request else kwargs.pop("_sec02_request")
        result = await fn(*args, **kwargs)
        user = _session_user(kwargs)
        if await money_values_visible(request, user):
            return result
        body = jsonable_encoder(result)
        if await budget_view_visible(request, user, kwargs.get("project_id")):
            return await r31_budget_view(user, kwargs.get("project_id"),
                                         without_keys(body, BUDGET_VIEW_HIDDEN_FIELDS))
        return strip_money(body)

    wrapper.__signature__ = sig.replace(parameters=params)
    wrapper.sec02_strips_money = True
    wrapper.sec02_budget_view = True
    wrapper.sec02_keep = ()
    return wrapper


# SEC-02-C (R20, R31; B-D2): what a Technical Manager keeps of a site pulse of HIS site —
# the site's budget snapshot (budget / spent / remaining), the per-SMR totals and the site
# labor total. Never the per-worker labor cost (FLOW-037 §3.4) or material values.
PULSE_BUDGET_VIEW_KEYS = ("budget_snapshot", "smr_summary", "total_labor_cost")


def strip_pulse_for_non_finance(fn):
    """SEC-02-C decorator for the site pulse GETs (one pulse, or {"items": [pulses]}):
    finance roles — everything; SiteManager, current member of the pulse's site — the
    R20/R31 budget view of that site; every other caller (and SiteManager on other
    sites) — no money."""
    import functools
    import inspect
    from fastapi.encoders import jsonable_encoder
    from app.permissions.finance_read import strip_money

    sig = inspect.signature(fn)
    own_request, params = _request_param(sig)

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        request = kwargs[own_request] if own_request else kwargs.pop("_sec02_request")
        result = await fn(*args, **kwargs)
        user = _session_user(kwargs)
        if await money_values_visible(request, user):
            return result
        body = jsonable_encoder(result)
        own: dict = {}

        async def view(pulse):
            if not isinstance(pulse, dict):
                return strip_money(pulse)
            site = pulse.get("site_id")
            if site not in own:
                own[site] = await budget_view_visible(request, user, site)
            out = strip_money(pulse)
            if own[site]:
                from collections import defaultdict
                from app.permissions.finance_read import r31_view, _norm
                # the day: workers per SMR from the pulse itself (then dropped)
                day = defaultdict(set)
                for w in pulse.get("workers") or []:
                    for t in w.get("smr_types") or []:
                        day[_norm(t)].add(w.get("worker_id"))
                n_day = len({w.get("worker_id") for w in pulse.get("workers") or []})
                kept = {k: pulse[k] for k in ("smr_summary", "total_labor_cost") if k in pulse}
                out.update(r31_view(kept, dict(day), n_day))
                if "budget_snapshot" in pulse:        # cumulative: all workers of the site
                    view = await r31_budget_view(user, site,
                                                 {"budget_snapshot": pulse["budget_snapshot"]})
                    out["budget_snapshot"] = view["budget_snapshot"]
            out.pop("workers", None)
            return out

        if isinstance(body, dict) and isinstance(body.get("items"), list):
            items = [await view(p) for p in body["items"]]
            return {**strip_money({k: v for k, v in body.items() if k != "items"}),
                    "items": items}
        return await view(body)

    wrapper.__signature__ = sig.replace(parameters=params)
    wrapper.sec02_strips_money = True
    wrapper.sec02_budget_view = True
    wrapper.sec02_keep = ()
    return wrapper


async def project_labor_workers(user: dict, project_id: str):
    """SEC-02-D (R31): distinct workers per SMR of a project, and of the whole project —
    from the work sessions and the daily reports (both feed the "spent" figures)."""
    from collections import defaultdict
    from app.tenancy.data_access import TenantData
    from app.permissions.finance_read import _norm
    tenant = TenantData.for_user(db, user)
    org = user["org_id"]
    by_smr, everyone = defaultdict(set), set()
    async for s_ in tenant.work_sessions.find(
            {"org_id": org, "site_id": project_id},
            {"_id": 0, "worker_id": 1, "smr_type_id": 1, "smr_type": 1}):
        w = s_.get("worker_id")
        if w:
            everyone.add(w)
            by_smr[_norm(s_.get("smr_type_id") or s_.get("smr_type"))].add(w)
    async for r in tenant.employee_daily_reports.find(
            {"org_id": org, "project_id": project_id},
            {"_id": 0, "worker_id": 1, "smr_type": 1, "activity_type": 1}):
        w = r.get("worker_id")
        if w:
            everyone.add(w)
            by_smr[_norm(r.get("smr_type") or r.get("activity_type"))].add(w)
    return dict(by_smr), len(everyone)


async def r31_budget_view(user: dict, project_id: str, body):
    """The Technical Manager's budget view of ``body`` (SEC-02-D)."""
    from app.permissions.finance_read import r31_view
    by_smr, n = await project_labor_workers(user, project_id)
    return r31_view(body, by_smr, n)
