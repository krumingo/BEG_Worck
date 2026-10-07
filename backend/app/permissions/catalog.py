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
    # W0-06B File Registry / storage providers (FLOW-016 "Права и сигурност").
    # Granted to no role below except through Owner/Admin's full set; any other
    # role needs an explicit assignment. Connecting a provider and activating
    # it are security/credential actions; opening, downloading and sharing a
    # file are checked on every call, and a restricted / confidential file
    # additionally needs its sensitivity action ("the narrower right wins").
    "storage.provider.configure",
    "storage.provider.activate",
    "storage.provider.read",
    "file.upload",
    "file.open",
    "file.download",
    "file.share",
    "file.integrity.check",
    # W0-06C periodic integrity monitoring (FLOW-016 "Периодична проверка").
    # Granted to no role below except through Owner/Admin's full set. The
    # periodic runner's tenant-scoped service principal needs an EXPLICIT
    # assignment carrying "file.integrity.monitor"; the runner never grants
    # itself anything and fails closed before any provider access.
    "file.integrity.monitor",
    "file.integrity.monitor.read",
    "file.sensitivity.restricted",
    "file.sensitivity.confidential",
}

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
CANONICAL_ROLES: Dict[str, dict] = {
    "owner":           {"label_bg": "Owner / Крум",          "actions": set(_ALL)},
    "admin":           {"label_bg": "Администратор",          "actions": set(_ALL)},
    "site_manager":    {"label_bg": "Технически ръководител", "actions": {"user.read", "asset_intake.submit",
                                                                      "master_data.pending.propose",
                                                                      "master_data.pending.read",
                                                                      "master_data.entity.read"}},
    "project_manager": {"label_bg": "Проектен мениджър",      "actions": {"user.read", "asset_intake.submit",
                                                                      "master_data.pending.propose",
                                                                      "master_data.pending.read",
                                                                      "master_data.entity.read"}},
    "accountant":      {"label_bg": "Счетоводство",           "actions": {"user.read",
                                                                      "master_data.pending.read",
                                                                      "master_data.entity.read"}},
    "warehouse":       {"label_bg": "Склад",                  "actions": {"asset_intake.submit",
                                                                      "master_data.pending.propose",
                                                                      "master_data.entity.read"}},
    "procurement":     {"label_bg": "Снабдител",              "actions": {"asset_intake.submit",
                                                                      "master_data.pending.propose",
                                                                      "master_data.entity.read"}},
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

# Project data actions granted per project_team membership (explicit permissions
# on a project-scope assignment). Reproduces can_access_project / can_manage_project.
PROJECT_MEMBER_ACTIONS = ["budget.read"]
PROJECT_MANAGER_ACTIONS = ["budget.read", "budget.write"]

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
