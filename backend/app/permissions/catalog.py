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
}

# Verbs whose DENIAL is security/business significant and must be audited
# (guardrail: do not flood the chain with ordinary read/list denials).
SIGNIFICANT_VERBS: Set[str] = {
    "create", "update", "delete", "approve", "execute",
    "pay", "payment", "export", "download",
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

CANONICAL_ROLES: Dict[str, dict] = {
    "owner":           {"label_bg": "Owner / Крум",          "actions": set(_ALL)},
    "admin":           {"label_bg": "Администратор",          "actions": set(_ALL)},
    "site_manager":    {"label_bg": "Технически ръководител", "actions": {"budget.read", "budget.write", "user.read", "asset_intake.submit"}},
    "project_manager": {"label_bg": "Проектен мениджър",      "actions": {"budget.read", "budget.write", "user.read", "asset_intake.submit"}},
    "accountant":      {"label_bg": "Счетоводство",           "actions": {"budget.read", "user.read"}},
    "warehouse":       {"label_bg": "Склад",                  "actions": {"asset_intake.submit"}},
    "procurement":     {"label_bg": "Снабдител",              "actions": {"asset_intake.submit"}},
    "office":          {"label_bg": "Офис",                   "actions": {"user.read", "budget.read"}},
    "worker":          {"label_bg": "Работник",               "actions": {"asset_intake.submit"}},
    "driver":          {"label_bg": "Шофьор",                 "actions": set()},
    # AI gets no blanket actions; it acts <= the delegating human (FLOW-002).
    "ai_service":      {"label_bg": "AI service role",        "actions": set()},
}

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
