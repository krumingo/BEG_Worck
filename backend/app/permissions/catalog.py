"""
W0-02 — Role & permission catalog (FLOW-002).

Two vocabularies live here:

  CANONICAL_ROLES  — the FLOW-002 role vocabulary (stable role_id codes).
  LEGACY_ROLES     — transitional compatibility roles ONLY. They exist so the
                     migration can reproduce the EXACT current behavior of the
                     legacy 8-role string model. They are NOT part of the
                     canonical FLOW-002 vocabulary and are scheduled for removal
                     once their real permission matrix is mapped onto canonical
                     roles (Krum's decision).

The PERMISSION_MATRIX is seeded to REPRODUCE today's behavior — no more, no
less. Actions not yet needed by a migrated route are simply not listed here;
they are added as routes are migrated (see permission_inventory).

IMPORTANT (guardrail G6): do not widen LEGACY_TECHNICIAN / LEGACY_VIEWER "by
meaning". Their action sets mirror the actual checks in the current code:
  - Technician: grouped with Worker/Warehousekeeper for asset intake submit
    (routes/assets_intake_pending.py); project access is membership-based, not
    role-based; NOT an approver; cannot create users.
  - Viewer: default role; no admin; any read it has today is gated by
    project_team membership, never by a company-wide role. So at company scope
    it grants nothing elevated.
"""
from typing import Dict, Set

# ---------------------------------------------------------------------------
# Action registry. Names are "<domain>.<verb>". Only the actions needed by the
# PR-1 migrated routes plus the coarse admin gate are defined now.
# ---------------------------------------------------------------------------
ACTIONS: Set[str] = {
    "admin.access",          # coarse gate behind the legacy require_admin
    "user.create",
    "user.update",
    "user.delete",
    "user.read",
    "budget.read",
    "budget.write",
    "asset_intake.submit",
    "asset_intake.approve",
    # W0-03 Master Data (FLOW-032 "Права"): the field proposes, the office maps
    # and corrects, the administrator merges and archives, the Owner approves
    # what carries financial or historical weight.
    "master_data.pending.propose",
    "master_data.pending.read",
    "master_data.pending.approve",
    "master_data.pending.reject",
    "master_data.entity.read",
    # W0-03D merge/redirect (FLOW-032 "Права": the administrator merges). Not
    # granted to any role below except through Owner/Admin's full set; every
    # other role is denied. Execution additionally needs a trusted Approval,
    # which the W0-07 runtime does not provide yet — so it fails closed.
    "master_data.merge.preview",
    "master_data.merge.execute",
    "master_data.unmerge.execute",
    # W0-03E legacy migration (FLOW-032 "Права"; CLAUDE.md §8 critical migration).
    # Owner/Admin only through their full set; the office may decide pending
    # legacy mappings. Every write additionally needs trusted Approval (W0-07),
    # so it fails closed in this build.
    "master_data.migration.plan",
    "master_data.migration.execute",
    "master_data.migration.rollback",
    "master_data.migration.map",
    # In MASTER_DATA_MODE=enforce a legacy identity hard delete is a Master Data
    # adapter write and needs this action; default deny for every other role.
    "master_data.legacy.delete",
    # SEC-01 (R14, Krum 06.11.2026; PM-01 §5.1): money writes are for the finance
    # roles only — Owner/Admin (full set) and Accountant. Same rule as the sibling
    # writes (routes/clients.py:27-29, routes/finance.py:36-38). One action per
    # endpoint; no other role is granted any of them.
    "finance.cash_transaction.create",       # POST /api/finance/cash-transactions
    "finance.overhead_transaction.create",   # POST /api/finance/overhead-transactions
    "finance.bonus_payment.create",          # POST /api/finance/bonus-payments
    "finance.overhead_snapshot.create",      # POST /api/overhead-snapshots
    "pricing.project_modifier.update",       # PUT  /api/price-modifiers/project/{project_id}
    "labor.entry.create",                    # POST /api/labor-entries
    "material_waste.entry.create",           # POST /api/projects/{project_id}/material-waste
    "project.client_link.update",            # PATCH /api/projects/{project_id}/client-link
                                             # + PUT/POST /api/projects when owner_* changes (C01)
    # SEC-01-C01 (R14 + R16, Krum 06.11.2026): every other write route on the same
    # resources. One action per endpoint.
    "labor.work_report_sync.execute",        # POST /api/labor-entries/sync-from-work-reports
    "labor.package_recompute.execute",       # POST /api/execution-packages/recompute-labor/{project_id}
    "finance.overhead_snapshot_compute.execute",  # POST /api/overhead/snapshots/compute
    "pricing.project_modifier.delete",       # DELETE /api/price-modifiers/project/{project_id} (refused 409)
    "pricing.org_modifier.update",           # PUT  /api/price-modifiers/org (Owner/Admin only)
    # SEC-01-C02 (R14, Krum 06.11.2026; FLOW Guard FG-27, FG-30): the remaining money
    # writes a Viewer could reach. One action per endpoint; finance roles only.
    "finance.subcontractor_payment.create",  # POST /api/subcontractor-payments (FG-27)
    "revenue.client_act_confirm.execute",    # POST /api/client-acts/{act_id}/confirm
    # ACT-01 (#77, R14): a client act carries client prices and a receivable
    "revenue.client_act.create",             # POST /api/client-acts
    "subcontract.act_confirm.execute",       # POST /api/subcontractor-acts/{act_id}/confirm
    "procurement.supplier_invoice.update",   # PUT  /api/supplier-invoices/{inv_id}
    "overhead.worker_calendar.create",       # POST /api/worker-calendar
    "overhead.worker_calendar.update",       # PUT  /api/worker-calendar/{entry_id}
    "overhead.worker_calendar_bulk.execute", # POST /api/worker-calendar/bulk
    "overhead.worker_calendar_sync.execute", # POST /api/worker-calendar/sync-from-sessions
    "finance.overhead_allocation.execute",   # POST /api/overhead-allocation/compute/{project_id}
    "ocr_invoice.intake.approve",            # PUT  /api/ocr-invoice/{intake_id}/approve
    "sales.sale_commit.execute",             # POST /api/sales/commit
    "pricing.material_price_refresh.execute",  # POST /api/pricing/refresh
    # SUB-ADV-01 (R39 + R40, Krum 07.11.2026; FLOW-021 "аванс без прихващане/остатък"):
    # the advance to a subcontractor and its explicit deduction on an act.
    "finance.subcontractor_advance.create",     # POST /api/subcontractor-packages/{pkg_id}/advances
    "subcontract.advance_deduction.execute",    # POST /api/subcontractor-acts/{act_id}/advance-deduction
    # ------------------------------------------------------------------
    # LIVE-OPS-01 / TASK 5C — Canonical warehouse/stock core (FLOW-009).
    # Every canonical movement command is denied by default and granted
    # only through an explicit RoleAssignment carrying the exact action
    # + object scope. The outer route gate `warehouse.write_command` is
    # a coarse gate kept wide; the per-action gate below is what
    # Permission Service actually evaluates.
    # ------------------------------------------------------------------
    "warehouse.write_command",                      # coarse route gate (outer)
    "warehouse.receive_from_supplier",
    "warehouse.receive_from_supplier_to_project",
    "warehouse.reserve",
    "warehouse.release_reservation",
    "warehouse.dispatch_to_project",
    "warehouse.accept_delivery",
    "warehouse.transfer_project_to_warehouse",
    "warehouse.transfer_project_to_project",
    "warehouse.transfer_warehouse_to_warehouse",
    "warehouse.consume_smr",
    "warehouse.return_to_supplier",
    "warehouse.write_off",
    # 5C-C26 Addendum B — Р27: the dedicated route gate of
    # POST /warehouse/canonical/project-writeoff (write-off „фира" FROM A
    # PROJECT only). Who holds it and on which projects: PROJECT_WRITEOFF_RULE.
    "warehouse.project_writeoff",
    # 5C-C26j — Р35: read the central warehouse (stock + prices, no
    # movements) and the per-project purchase price history. Who and where:
    # CENTRAL_STOCK_READ_ROLES / PRICE_HISTORY_RULE.
    "warehouse.read_central_stock",
    "warehouse.read_price_history",
    "warehouse.revision_adjustment",
    "warehouse.quarantine_entry",
    "warehouse.quarantine_release",
    "warehouse.read_stock",
    "warehouse.read_history",
    # Migration-readiness is read-only / dry-run only; execute always 405.
    "warehouse.migration.readiness",
    "warehouse.migration.execute",
}

# ---------------------------------------------------------------------------
# SEC-02 (R20, Krum 06.11.2026; FLOW-002, FLOW-010; PM-01 §5.2, FG-1/12/14/15):
# reading money. The registry of every guarded GET is app/permissions/finance_read.py
# (endpoint -> action -> rule -> canon source); the actions are listed here so the
# catalog stays the one place that says who holds what.
#
#   FINANCE_READ_ACTIONS     company finance AND project money that only the finance
#                            roles read (R20 rules 1 + 2): Owner/Admin (full set) and
#                            Accountant, company scope. No other role, member or not.
#   PROJECT_BUDGET_READ_ACTIONS
#                            R20: the Technical Manager (canonical role_id
#                            ``site_manager``, FG-14) reads budget + spent + remaining of
#                            the projects they are a MEMBER of — granted only on the
#                            project-scope assignment mirroring that membership
#                            (project_membership_actions below), never company-wide.
#                            Finance roles read it everywhere.
#   MONEY_VALUES_READ        "may this caller see money values" on a shared screen whose
#                            rule is "hide the values" (R20 rule 5; FG-1/FG-15 labor
#                            rates, all-reports). Finance roles only, company scope.
# FG-12: a project-scope assignment never carries a FINANCE_READ action or
# MONEY_VALUES_READ, so combining a company role with project memberships can never
# widen money reads beyond what the company role already gives.
# ---------------------------------------------------------------------------
from app.permissions.finance_read import (                       # noqa: E402
    FINANCE_READ_ACTIONS, PROJECT_BUDGET_READ_ACTIONS, MONEY_VALUES_READ,
    EMPLOYEE_FILE_ACTION, SUBSCRIPTION_PRICE_READ,
)
# SUBSCRIPTION_PRICE_READ (SEC-02-B): Owner/Admin only — through their full set.
ACTIONS |= (FINANCE_READ_ACTIONS | PROJECT_BUDGET_READ_ACTIONS | {MONEY_VALUES_READ}
            | {EMPLOYEE_FILE_ACTION, SUBSCRIPTION_PRICE_READ})
SEC02_ACCOUNTANT_READ_ACTIONS: Set[str] = (
    FINANCE_READ_ACTIONS | PROJECT_BUDGET_READ_ACTIONS | {MONEY_VALUES_READ}
    | {EMPLOYEE_FILE_ACTION})
# SEC-02-A (D9): the Technical Manager opens the employee file at company scope; the
# handler gives him the no-money version of his own projects only.
SEC02_SITE_MANAGER_COMPANY_ACTIONS: Set[str] = {EMPLOYEE_FILE_ACTION}

# SEC-01: the money-write actions above, granted to Accountant (Owner/Admin get them
# through their full set).
MONEY_WRITE_ACTIONS: Set[str] = {
    "finance.cash_transaction.create",
    "finance.overhead_transaction.create",
    "finance.bonus_payment.create",
    "finance.overhead_snapshot.create",
    "pricing.project_modifier.update",
    "labor.entry.create",
    "material_waste.entry.create",
    "project.client_link.update",
    # SEC-01-C01
    "labor.work_report_sync.execute",
    "labor.package_recompute.execute",
    "finance.overhead_snapshot_compute.execute",
    "pricing.project_modifier.delete",
    # ACT-01 (#77): POST /api/client-acts — finance roles only (R14), the C01 rule
    "revenue.client_act.create",
}
# SEC-01-C02 (R14; FG-27, FG-30): same rule, same holders (Owner/Admin/Accountant).
MONEY_WRITE_ACTIONS_C02: Set[str] = {
    "finance.subcontractor_payment.create",
    "revenue.client_act_confirm.execute",
    "subcontract.act_confirm.execute",
    "procurement.supplier_invoice.update",
    "overhead.worker_calendar.create",
    "overhead.worker_calendar.update",
    "overhead.worker_calendar_bulk.execute",
    "overhead.worker_calendar_sync.execute",
    "finance.overhead_allocation.execute",
    "ocr_invoice.intake.approve",
    "sales.sale_commit.execute",
    "pricing.material_price_refresh.execute",
}
MONEY_WRITE_ACTIONS |= MONEY_WRITE_ACTIONS_C02

# SUB-ADV-01 (R39, Krum 07.11.2026): "Дава го само Owner или Accountant" — the advance is
# granted to Owner and Accountant ONLY; Admin is taken out of its full set below (the one
# action Admin does not hold). Kept apart from MONEY_WRITE_ACTIONS (Owner/Admin/Accountant).
SUBCONTRACTOR_ADVANCE_ACTIONS: Set[str] = {"finance.subcontractor_advance.create"}
# The deduction of an advance on an act settles part of what is owed for that act — the
# same holders as the subcontractor payment it accompanies (Owner/Admin/Accountant, R14).
SUBCONTRACTOR_ADVANCE_DEDUCTION_ACTIONS: Set[str] = {"subcontract.advance_deduction.execute"}

# SEC-01-C01 (R16, Krum 06.11.2026): labor entries and material waste. Owner/Admin/
# Accountant everywhere (company scope, above); SiteManager and Technician ONLY on the
# projects they are members of — granted on the project-scope assignment that mirrors
# the project_team membership (app/permissions/sync.py, scripts/w0_02_bootstrap_*),
# never at company scope. Viewer/Driver/every other role: never, member or not.
FIELD_COST_WRITE_ACTIONS: Set[str] = {
    "labor.entry.create",
    "labor.work_report_sync.execute",
    "labor.package_recompute.execute",
    "material_waste.entry.create",
}
# role_id (canonical or legacy) of the company roles R16 lets write on member projects.
FIELD_COST_MEMBER_ROLE_IDS: Set[str] = {"site_manager", "LEGACY_TECHNICIAN"}
# SEC-02 (R20, FG-14): the company role that reads the budget view of member projects.
PROJECT_BUDGET_MEMBER_ROLE_IDS: Set[str] = {"site_manager"}

# SEC-01-C01: Owner/Admin only (the existing rule of PUT /price-modifiers/org,
# routes/price_modifiers.py) — through their full set; granted to no other role.
ORG_PRICING_ACTIONS: Set[str] = {"pricing.org_modifier.update"}

# Verbs whose DENIAL is security/business significant and must be audited
# (guardrail: do not flood the chain with ordinary read/list denials).
SIGNIFICANT_VERBS: Set[str] = {
    "create", "update", "delete", "approve", "execute",
    "pay", "payment", "export", "download", "rollback",
}

# Reason codes that are always audited on denial, regardless of the verb.
ALWAYS_AUDIT_REASONS: Set[str] = {"CROSS_TENANT", "SCOPE_MISMATCH"}


def is_significant_action(action: str) -> bool:
    """A denial of this action is worth an audit event."""
    if action.startswith("permission.") or action.startswith("ai."):
        return True
    verb = action.rsplit(".", 1)[-1]
    return verb in SIGNIFICANT_VERBS


# ---------------------------------------------------------------------------
# Canonical FLOW-002 roles. label_bg is the canonical Bulgarian label.
# ---------------------------------------------------------------------------
_ALL = set(ACTIONS)

# SCOPE RULE (matches legacy `can_access_project`): only Owner/Admin get
# project DATA actions (budget.read/write) company-wide. For every other role
# access to a project's data comes ONLY from a PROJECT-scope assignment created
# from project_team membership (see the migration backfill). So company-scope
# non-admin roles do NOT list budget.* — otherwise a company role would read
# every project, which is broader than today's membership-based access.
# Exception (SEC-02-C, R20, Krum 06.11.2026): Accountant holds budget.read (READ only)
# company-wide — R20 gives the finance roles every project's money.
CANONICAL_ROLES: Dict[str, dict] = {
    "owner":           {"label_bg": "Owner / Крум",          "actions": set(_ALL)},
    "admin":           {"label_bg": "Администратор",          "actions": set(_ALL) - SUBCONTRACTOR_ADVANCE_ACTIONS},
    "site_manager":    {"label_bg": "Технически ръководител", "actions": {"user.read", "asset_intake.submit",
                                                                      "master_data.pending.propose",
                                                                      "master_data.pending.read",
                                                                      "master_data.entity.read",
                                                                      # TASK 5C: site technical lead accepts deliveries
                                                                      # and consumes stock on SMR; project scope is required.
                                                                      "warehouse.write_command",
                                                                      "warehouse.accept_delivery",
                                                                      "warehouse.consume_smr",
                                                                      "warehouse.transfer_project_to_warehouse",
                                                                      "warehouse.transfer_project_to_project",
                                                                      "warehouse.quarantine_entry",
                                                                      # Р27: project write-off, member projects only.
                                                                      "warehouse.project_writeoff",
                                                                      # Р35: central warehouse read + price history.
                                                                      "warehouse.read_central_stock",
                                                                      "warehouse.read_price_history",
                                                                      "warehouse.read_stock",
                                                                      "warehouse.read_history",
                                                                      # SEC-02 (R20, D9): the employee file, no money
                                                                      *SEC02_SITE_MANAGER_COMPANY_ACTIONS}},
    "project_manager": {"label_bg": "Проектен мениджър",      "actions": {"user.read", "asset_intake.submit",
                                                                      "master_data.pending.propose",
                                                                      "master_data.pending.read",
                                                                      "master_data.entity.read",
                                                                      # TASK 5C: PM reads everything in scope; may authorize
                                                                      # revisions and write-offs within their project scope.
                                                                      "warehouse.write_command",
                                                                      "warehouse.consume_smr",
                                                                      "warehouse.transfer_project_to_warehouse",
                                                                      "warehouse.transfer_project_to_project",
                                                                      "warehouse.quarantine_entry",
                                                                      "warehouse.quarantine_release",
                                                                      "warehouse.write_off",
                                                                      # Р27: project write-off, own projects only.
                                                                      "warehouse.project_writeoff",
                                                                      "warehouse.revision_adjustment",
                                                                      "warehouse.read_stock",
                                                                      "warehouse.read_history",
                                                                      "warehouse.migration.readiness"}},
    "accountant":      {"label_bg": "Счетоводство",           "actions": {"user.read",
                                                                      "master_data.pending.read",
                                                                      "master_data.entity.read",
                                                                      # TASK 5C: accounting reads only, no stock writes —
                                                                      # except Р27: project write-off („фира") everywhere.
                                                                      "warehouse.project_writeoff",
                                                                      # Р35: central warehouse + price history.
                                                                      "warehouse.read_central_stock",
                                                                      "warehouse.read_price_history",
                                                                      "warehouse.read_stock",
                                                                      "warehouse.read_history",
                                                                      # SEC-01 (R14): the money writes.
                                                                      *MONEY_WRITE_ACTIONS,
                                                                      # SEC-02 (R20): the finance reads
                                                                      *SEC02_ACCOUNTANT_READ_ACTIONS,
                                                                      # SEC-02-C (R20, B-D1): the
                                                                      # finance role reads every
                                                                      # project's budget — company
                                                                      # scope, read only.
                                                                      "budget.read",
                                                                      # SUB-ADV-01 (R39): the advance and its deduction
                                                                      *SUBCONTRACTOR_ADVANCE_ACTIONS,
                                                                      *SUBCONTRACTOR_ADVANCE_DEDUCTION_ACTIONS}},
    "warehouse":       {"label_bg": "Склад",                  "actions": {"asset_intake.submit",
                                                                      "master_data.pending.propose",
                                                                      "master_data.entity.read",
                                                                      # TASK 5C: warehouse operator — stock-floor commands only.
                                                                      # Not permitted: receive-to-project (procurement decision),
                                                                      # return-to-supplier (procurement decision),
                                                                      # revision (owner/admin), migration (admin).
                                                                      "warehouse.write_command",
                                                                      "warehouse.receive_from_supplier",
                                                                      "warehouse.reserve",
                                                                      "warehouse.release_reservation",
                                                                      "warehouse.dispatch_to_project",
                                                                      "warehouse.accept_delivery",
                                                                      "warehouse.transfer_project_to_warehouse",
                                                                      "warehouse.transfer_warehouse_to_warehouse",
                                                                      "warehouse.quarantine_entry",
                                                                      "warehouse.quarantine_release",
                                                                      "warehouse.read_stock",
                                                                      "warehouse.read_central_stock",
                                                                      "warehouse.read_history"}},
    "procurement":     {"label_bg": "Снабдител",              "actions": {"asset_intake.submit",
                                                                      "master_data.pending.propose",
                                                                      "master_data.entity.read",
                                                                      # TASK 5C: procurement handles supplier side.
                                                                      "warehouse.write_command",
                                                                      "warehouse.receive_from_supplier",
                                                                      "warehouse.receive_from_supplier_to_project",
                                                                      "warehouse.return_to_supplier",
                                                                      "warehouse.read_stock",
                                                                      "warehouse.read_central_stock",
                                                                      "warehouse.read_history"}},
    "office":          {"label_bg": "Офис",                   "actions": {"user.read",
                                                                      "master_data.pending.propose",
                                                                      "master_data.pending.read",
                                                                      "master_data.pending.approve",
                                                                      "master_data.pending.reject",
                                                                      "master_data.entity.read",
                                                                      "master_data.migration.map"}},
    "worker":          {"label_bg": "Работник",               "actions": {"asset_intake.submit",
                                                                      "master_data.pending.propose"}},
    "driver":          {"label_bg": "Шофьор",                 "actions": set()},
    # AI gets no blanket actions; it acts <= the delegating human (FLOW-002).
    "ai_service":      {"label_bg": "AI service role",        "actions": set()},
}

# 5C-C26 Addendum B — Р27 (Крум 06.11.2026, FG-21; follows Р16): who may
# write off „фира" FROM A PROJECT, and where. Decided by
# app/services/warehouse_movements/write_off_policy.py from the caller's
# active RoleAssignments and project_team rows:
#   everywhere  — on every project of the tenant;
#   own_project — a project-scope assignment of the role on that project, or
#                 an active, in-date project_team row;
#   member      — only an active, in-date project_team row on that project.
# The legacy Technician is entitled ONLY through membership (like
# PROJECT_MEMBER_ACTIONS): its company-wide action set stays exactly
# {"asset_intake.submit"} (W0-02 invariant). Every role not listed → 403.
PROJECT_WRITEOFF_ACTION = "warehouse.project_writeoff"
PROJECT_WRITEOFF_RULE: Dict[str, str] = {
    "owner": "everywhere",
    "admin": "everywhere",
    "accountant": "everywhere",
    "project_manager": "own_project",
    "site_manager": "member",
    "LEGACY_TECHNICIAN": "member",
}

# 5C-C26j — Р35 (Крум 07.11.2026): SiteManager and Technician read the central
# warehouse (stock AND prices; movements there stay refused, Р28) and the
# purchase price history of their projects. The legacy Technician is entitled
# through these tables only — its catalog action set stays exact (W0-02).
CENTRAL_STOCK_READ_ACTION = "warehouse.read_central_stock"
CENTRAL_STOCK_READ_ROLES = frozenset({
    "owner", "admin", "accountant", "warehouse", "procurement",
    "site_manager", "LEGACY_TECHNICIAN",
})
PRICE_HISTORY_ACTION = "warehouse.read_price_history"
PRICE_HISTORY_RULE: Dict[str, str] = {
    "owner": "everywhere",
    "admin": "everywhere",
    "accountant": "everywhere",
    "site_manager": "member",
    "LEGACY_TECHNICIAN": "member",
}

# Project data actions granted per project_team membership (explicit permissions
# on a project-scope assignment). Reproduces can_access_project / can_manage_project.
PROJECT_MEMBER_ACTIONS = ["budget.read"]
PROJECT_MANAGER_ACTIONS = ["budget.read", "budget.write"]


def project_membership_actions(role_id: str, role_in_project: str) -> list:
    """Explicit permissions of the project-scope assignment mirroring one membership.

    budget.* as before (SiteManager in the project: +write). SEC-01-C01 (R16): a member
    whose COMPANY role is SiteManager or Technician also gets the field cost writes of
    THIS project. Any other role (Viewer, Driver, ...) gets nothing more, member or not.
    """
    base = list(PROJECT_MANAGER_ACTIONS if role_in_project == "SiteManager"
                else PROJECT_MEMBER_ACTIONS)
    if role_id in FIELD_COST_MEMBER_ROLE_IDS:
        base += sorted(FIELD_COST_WRITE_ACTIONS)
    # SEC-02 (R20, FG-14): budget + spent + remaining of THIS project, for the
    # Technical Manager only (canonical role_id, not role_in_project).
    if role_id in PROJECT_BUDGET_MEMBER_ROLE_IDS:
        base += sorted(PROJECT_BUDGET_READ_ACTIONS)
    return base

# ---------------------------------------------------------------------------
# LEGACY compatibility roles — transitional only, NOT FLOW-002 canon.
# Reproduce the exact current behavior; scheduled for removal.
# ---------------------------------------------------------------------------
LEGACY_ROLES: Dict[str, dict] = {
    "LEGACY_TECHNICIAN": {
        "label_bg": "(legacy) Technician",
        "canonical": False,
        "scheduled_for_removal": True,
        # Current code: may submit asset intake (grouped with Worker/Warehousekeeper).
        # NOT an approver, cannot create users. Project access stays membership-based.
        "actions": {"asset_intake.submit"},
    },
    "LEGACY_VIEWER": {
        "label_bg": "(legacy) Viewer",
        "canonical": False,
        "scheduled_for_removal": True,
        # Current code: default role, read-only, and any read is gated by
        # project_team membership, not by a company-wide role. So at company
        # scope it grants nothing elevated.
        "actions": set(),
    },
}

# Legacy 8-role string -> role_id used at migration time.
LEGACY_ROLE_MAP: Dict[str, str] = {
    "Owner": "owner",
    "Admin": "admin",
    "SiteManager": "site_manager",
    "Accountant": "accountant",
    "Warehousekeeper": "warehouse",
    "Driver": "driver",
    # No exact FLOW-002 equivalent -> transitional (Krum decision).
    "Technician": "LEGACY_TECHNICIAN",
    "Viewer": "LEGACY_VIEWER",
}


def role_actions(role_id: str) -> Set[str]:
    """Actions granted by a role_id (canonical or legacy). Unknown -> empty."""
    if role_id in CANONICAL_ROLES:
        return CANONICAL_ROLES[role_id]["actions"]
    if role_id in LEGACY_ROLES:
        return LEGACY_ROLES[role_id]["actions"]
    return set()


def is_canonical_role(role_id: str) -> bool:
    return role_id in CANONICAL_ROLES


# Convenience: full matrix (role_id -> frozenset(actions)).
PERMISSION_MATRIX: Dict[str, frozenset] = {
    **{rid: frozenset(v["actions"]) for rid, v in CANONICAL_ROLES.items()},
    **{rid: frozenset(v["actions"]) for rid, v in LEGACY_ROLES.items()},
}
