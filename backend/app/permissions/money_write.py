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

    async def dependency(request: Request, ctx: TenantContext = Depends(permission)) -> dict:
        await _legacy_data_path_guard(ctx)
        request.state.sec_money_ctx = ctx    # SEC-02-F (FG-75): for audit_money_write
        return ctx.user

    dependency.sec01_action = action      # inspected by tests/test_sec_01_*.py
    return dependency


async def audit_money_write(request: Request, user: dict, *, action: str, source_flow: str,
                            entity_type: str, entity_id: Optional[str],
                            before: Any = None, after: Any = None,
                            scope_type: Optional[str] = None, scope_id: Optional[str] = None,
                            reason: str) -> dict:
    """SEC-02-F (FLOW Guard FG-75; CLAUDE.md §14, FLOW-040): the canonical AuditEvent of a
    money write that went through ``require_money_write`` — R1, success, the before/after
    of the changed fields, the request's Idempotency-Key, endpoint and request id.

    Written in the SAME database as the business write (the context's ``db()``: the
    legacy handle in off/shadow, the guarded tenant handle in enforce). The event is
    labelled with the tenant that owns the record: in off/shadow the legacy org of the
    write (as ``audit_permission_change``, PR-06), in enforce the context's tenant. A
    failure is raised, never swallowed (the write must not be reported as audited).
    """
    from app.audit.envelope import (build_event, ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS,
                                    RESULT_SUCCESS)
    from app.audit.store import record_event
    ctx = getattr(request.state, "sec_money_ctx", None)
    if ctx is None:
        raise RuntimeError("audit_money_write needs a route guarded by require_money_write")
    event = build_event(
        tenant_id=ctx.tenant_id if ctx.enforced else user["org_id"],
        actor_type=ACTOR_HUMAN, actor_id=user["id"], action=action,
        source_flow=source_flow, retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        result=RESULT_SUCCESS, entity_type=entity_type, entity_id=entity_id,
        scope_type=scope_type, scope_id=scope_id,
        structured_diff={"before": before, "after": after}, reason=reason,
        source_channel="api", tool_or_endpoint="%s %s" % (request.method, request.url.path),
        request_id=request.headers.get("x-request-id"),
        idempotency_key=request.headers.get("idempotency-key"))
    return await record_event(await ctx.db(), event)


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


async def _site_id_from_path(request: Request) -> Optional[str]:
    value = request.path_params.get("site_id")       # SEC-02-E: a site IS a project
    return value if isinstance(value, str) and value else None


async def _project_id_from_body(request: Request) -> Optional[str]:
    try:
        payload: Any = await request.json()      # already read and cached by FastAPI
    except Exception:                            # noqa: BLE001 — no/invalid body: no project
        return None
    value = payload.get("project_id") if isinstance(payload, dict) else None
    return value if isinstance(value, str) and value else None


_PROJECT_SOURCES = {"path": _project_id_from_path, "body": _project_id_from_body,
                    "site": _site_id_from_path}


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


def require_project_budget_read(action: str, *, module: Optional[str], resource_type: str,
                                project_from: str = "path"):
    """R20-2B: finance roles everywhere; SiteManager only on a current member project.
    ``project_from="site"`` (SEC-02-E): the project is the ``{site_id}`` path parameter."""
    dependency = require_field_cost_write(action, module=module, resource_type=resource_type,
                                          project_from=project_from,
                                          member_roles=("SiteManager",))
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


def strip_for_budget_view(fn=None, *, labor_source: str = "sessions"):
    """SEC-02-B (R20-5B, FG-43) decorator, under ``@router.get``: finance roles get the full
    response; a Technical Manager member of ``{project_id}`` gets budget + spent +
    remaining without client / subcontractor prices; every other caller no money.
    ``labor_source`` (FG-63): where the screen's "spent" comes from (``LABOR_SOURCES``)."""
    if fn is None:
        return lambda f: strip_for_budget_view(f, labor_source=labor_source)
    import functools
    import inspect
    from fastapi.encoders import jsonable_encoder
    from app.permissions.finance_read import strip_money, without_budget_view_forbidden

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
                                         without_budget_view_forbidden(body),  # SEC-02-G
                                         source=labor_source)
        return strip_money(body)

    wrapper.__signature__ = sig.replace(parameters=params)
    wrapper.sec02_strips_money = True
    wrapper.sec02_labor_source = labor_source
    wrapper.sec02_budget_view = True
    wrapper.sec02_keep = ()
    return wrapper


# SEC-02-C (R20, R31; B-D2): what a Technical Manager keeps of a site pulse of HIS site —
# the site's budget snapshot (budget / spent / remaining), the per-SMR totals and the site
# labor total. Never the per-worker labor cost (FLOW-037 §3.4) or material values.
PULSE_BUDGET_VIEW_KEYS = ("budget_snapshot", "smr_summary", "total_labor_cost")


def pulse_paid_workers(pulse: dict):
    """SEC-02-G (Codex SEC71-02; FG-74 on the pulse path): the PAID workers of one site
    pulse, per SMR and of the day, for the R31 2+ rule (``finance_read.r31_view``).

    A worker counts only with a non-zero ``labor_cost`` that day. The pulse keeps one cost
    per worker, not per SMR, so he counts for an SMR only when it is his ONLY SMR that
    day — else his pay cannot be attributed and could lift another worker's SMR over the
    rule. Every SMR of ``smr_summary`` is listed, so an SMR with fewer than 2 counted
    workers loses its ``total_cost``; a day with fewer than 2 paid workers loses
    ``total_labor_cost``."""
    from app.permissions.finance_read import _norm
    workers = [w for w in pulse.get("workers") or [] if isinstance(w, dict)]
    paid = set()
    for w in workers:
        try:
            if w.get("worker_id") and round(float(w.get("labor_cost") or 0), 2):
                paid.add(w["worker_id"])
        except (TypeError, ValueError):
            pass
    day = {_norm(r.get("smr_type")): set() for r in pulse.get("smr_summary") or []
           if isinstance(r, dict)}
    for w in workers:
        types = {_norm(t) for t in w.get("smr_types") or []}
        if w.get("worker_id") in paid and len(types) == 1:
            day.setdefault(types.pop(), set()).add(w["worker_id"])
    return day, len(paid)


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
                from app.permissions.finance_read import (r31_view, _norm,
                                                          without_budget_view_forbidden)
                day, n_paid = pulse_paid_workers(pulse)   # SEC-02-G (Codex SEC71-02)
                kept = {k: pulse[k] for k in ("smr_summary", "total_labor_cost") if k in pulse}
                out.update(without_budget_view_forbidden(r31_view(kept, day, n_paid)))
                if isinstance(pulse.get("budget_snapshot"), dict):
                    # SEC-02-E (audit SEC02D-1 b): the snapshot is the site's CUMULATIVE
                    # spent at generation time — two stored days differ by one day's labor,
                    # i.e. one worker's pay on a single-worker day. The Technical Manager
                    # keeps the budget and its status only; spent stays on the budget
                    # screens (current, per SMR / project, R31 rules).
                    snap = pulse["budget_snapshot"]
                    out["budget_snapshot"] = {k: snap[k] for k in ("total_budget", "status")
                                              if k in snap}
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


# SEC-02-E (FLOW Guard FG-63): the workers behind a "spent" figure are counted from the SAME
# source, filter and date window as that figure — a wider count (all history, or another
# source) could say "2+" while the money shown comes from one person.
LABOR_SOURCES = ("sessions", "centralized", "daily_logs")


def _window(field: str, date_from: Optional[str], date_to: Optional[str]) -> dict:
    rng = {}
    if date_from:
        rng["$gte"] = "%sT00:00:00" % date_from
    if date_to:
        rng["$lte"] = "%sT23:59:59" % date_to
    return {field: rng} if rng else {}


async def project_labor_workers(user: dict, project_id: str, source: str = "sessions",
                                date_from: Optional[str] = None,
                                date_to: Optional[str] = None,
                                entries: Optional[list] = None):
    """Distinct PAID workers per SMR, and of the whole project, behind a "spent" figure.

    ``source`` — what the screen sums (same filters and the same pay as its handler):
      sessions     ended work sessions of the site, pay = ``labor_cost`` (expected-actual,
                   activities-overview, budget-health, the activity burn);
      centralized  the entries of ``build_centralized_reports`` — Draft/Submitted daily
                   reports + ended, unflagged work sessions, pay = ``amount_clean_labor``
                   (centralized-reports/activities); ``entries`` passes the handler's own;
      daily_logs   daily work log entries, pay = hours x the work type's
                   ``default_hourly_rate`` (25 when unset), SMR = its activity type
                   (activity-budget-summary).
    ``date_from`` / ``date_to`` — the same window as the money, when the screen has one.

    SEC-02-F (FG-74): a worker counts only with a NON-ZERO pay in that window (per SMR:
    in that SMR). A worker with zero cost adds nothing to "spent", so counting him would
    let one paid worker's pay pass the 2+ rule.
    """
    from collections import defaultdict
    from app.tenancy.data_access import TenantData
    from app.permissions.finance_read import _norm
    if source not in LABOR_SOURCES:
        raise ValueError(source)
    tenant = TenantData.for_user(db, user)
    org = user["org_id"]
    pay_by_smr = defaultdict(lambda: defaultdict(float))     # smr -> worker -> pay
    pay = defaultdict(float)                                 # worker -> pay

    def add(worker, smr, amount):
        try:
            amount = float(amount or 0)
        except (TypeError, ValueError):
            amount = 0.0
        if worker:
            pay[worker] += amount
            pay_by_smr[_norm(smr)][worker] += amount

    if source == "sessions":
        q = {"org_id": org, "site_id": project_id, "ended_at": {"$ne": None},
             **_window("started_at", date_from, date_to)}
        async for s_ in tenant.work_sessions.find(
                q, {"_id": 0, "worker_id": 1, "smr_type_id": 1, "smr_type": 1,
                    "labor_cost": 1}):
            add(s_.get("worker_id"), s_.get("smr_type_id") or s_.get("smr_type"),
                s_.get("labor_cost", 0))
    if source == "centralized":
        if entries is None:
            from app.services.centralized_reports import build_centralized_reports
            entries = (await build_centralized_reports(org, project_id,
                                                       with_entries=True))["entries"]
        for e in entries:
            add(e.get("worker_id"), e.get("smr_type"), e.get("amount_clean_labor", 0))
    if source == "daily_logs":
        types = {wt["id"]: wt async for wt in tenant.work_types.find({"org_id": org},
                                                                     {"_id": 0})}
        async for log in tenant.daily_work_logs.find(
                {"org_id": org, "site_id": project_id}, {"_id": 0, "entries": 1,
                                                         "work_type_id": 1}):
            wt = types.get(log.get("work_type_id"), {})
            smr = wt.get("activity_type", wt.get("name", "Общо"))
            rate = wt.get("default_hourly_rate", 25)
            for e in log.get("entries") or []:
                try:
                    amount = float(e.get("hours", 0) or 0) * float(rate or 0)
                except (TypeError, ValueError):
                    amount = 0.0
                add(e.get("user_id"), smr, amount)

    def paid(m):
        return {w for w, v in m.items() if round(v, 2) != 0}
    by_smr = {k: paid(m) for k, m in pay_by_smr.items()}
    return by_smr, len(paid(pay))


async def r31_budget_view(user: dict, project_id: str, body, *, source: str = "sessions",
                          date_from: Optional[str] = None, date_to: Optional[str] = None,
                          entries: Optional[list] = None):
    """The Technical Manager's budget view of ``body`` (SEC-02-D), with the workers counted
    from the money's own source and window (SEC-02-E, FG-63)."""
    from app.permissions.finance_read import r31_view
    by_smr, n = await project_labor_workers(user, project_id, source, date_from, date_to,
                                            entries=entries)
    return r31_view(body, by_smr, n)
