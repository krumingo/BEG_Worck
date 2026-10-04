"""
W0-03E-A2B — the protected tenant-ownership scope: every collection, classified.

Why it exists. The owner decision of W0-03E-A2B (Issue #38,
docs/architecture/W0-03E-A2B_SINGLE_TENANT_BACKFILL.md) is that every current
ownerless legacy tenant-owned record belongs to the one operating tenant
(BUILDING EXPRESS GROUP / BEG) and must be backfilled to it, and that after the
backfill **no** tenant-owned record may exist or be created without an owner.
Both halves need one answer to "which collections are tenant-owned, and by
which key?". This module is that answer — the single classification the
backfill, the dry-run inventory, the runtime write barrier, the static guard and
the tests all read. There is no second list.

Every collection the application reaches is in exactly ONE class:

* :data:`ORG_KEYED` — legacy operational / authorization collections whose
  documents carry the tenant in ``org_id`` (``app.tenancy.data_access.TENANT_KEY``).
  These are the backfill scope. Grouped by the Issue #38 family for the report.
* :data:`TENANT_ID_KEYED` — the W0-03 Master Data (``md_*``) and W0-04 audit
  stores. Their own writers already require ``tenant_id`` (they refuse a
  document without one), so they are inventoried and an ownerless row there is a
  hard blocker, never backfilled by guess.
* :data:`TENANT_ROOT` — ``organizations``: the tenant itself (its ``id`` IS the
  ``org_id`` of every record above). Inventoried, never stamped.
* :data:`TECHNICAL` — database-level bookkeeping with no tenant meaning.

A collection found in a database that is in none of these classes is
``UNCLASSIFIED`` and makes the dry run fail closed: nothing is ASSUMED SAFE.
``tests/test_w0_03e_a2b_ownership_scope.py`` also proves that every collection
the application code names is classified here, so a new collection cannot slip
past the inventory either.

Pure and stdlib-only: no database, no I/O.
"""
from __future__ import annotations

from typing import Any, Dict, FrozenSet, Iterable, Mapping, Optional, Tuple

#: The tenant key of the legacy operational collections (same value as
#: ``app.tenancy.data_access.TENANT_KEY``; kept literal here so this module has
#: no FastAPI import and the guard can read it without the app).
ORG_KEY = "org_id"
TENANT_ID_KEY = "tenant_id"

# ------------------------------------------------------------------ families
#: Issue #38 minimum families, in report order.
FAMILY_PROJECTS = "projects / project_team / project relations"
FAMILY_PEOPLE = "users / persons / employee_profiles / attendance"
FAMILY_PARTIES = "companies / clients / counterparties / subcontractors"
FAMILY_COMMERCIAL = "offers / contracts / invoices / invoice_lines"
FAMILY_PAYMENTS = "payments / allocations / advances / payroll / overhead"
FAMILY_WAREHOUSE = "warehouses / locations"
FAMILY_MATERIALS = "items / materials / requests"
FAMILY_WORK = "work types / SMR identities"
FAMILY_ASSETS = "asset types / items / units"
FAMILY_TASKS = "tasks / schedules / alarms"
FAMILY_FILES = "file / document metadata"
FAMILY_AUDIT = "audit / business history"
FAMILY_SETTINGS = "tenant settings / counters / subscription"

FAMILIES: Tuple[str, ...] = (
    FAMILY_PROJECTS, FAMILY_PEOPLE, FAMILY_PARTIES, FAMILY_COMMERCIAL, FAMILY_PAYMENTS,
    FAMILY_WAREHOUSE, FAMILY_MATERIALS, FAMILY_WORK, FAMILY_ASSETS, FAMILY_TASKS,
    FAMILY_FILES, FAMILY_AUDIT, FAMILY_SETTINGS,
)


def _family(name: str, *collections: str) -> Dict[str, str]:
    return {c: name for c in collections}


#: collection -> Issue #38 family. Every legacy collection whose writers stamp
#: (or must stamp) ``org_id``. ``project_team`` is here: it is an authorization
#: relation, tenant-bound like every other operational record (W0-03E-A2).
ORG_KEYED: Dict[str, str] = {
    **_family(FAMILY_PROJECTS,
              "projects", "project_team", "project_phases", "project_photos",
              "project_payments", "project_material_ops", "project_overhead_allocations",
              "project_overhead_alloc", "progress_updates", "budget_freezes",
              "activity_budgets", "sites", "site_pulses", "site_daily_rosters"),
    **_family(FAMILY_PEOPLE,
              "users", "persons", "employee_profiles", "brigades", "attendance_entries",
              "work_sessions", "employee_daily_reports", "daily_work_logs", "work_reports",
              "labor_entries", "reminder_logs", "notifications"),
    **_family(FAMILY_PARTIES,
              "companies", "clients", "counterparties", "subcontractors",
              "subcontractor_packages", "subcontractor_package_lines", "subcontractor_acts",
              "subcontractor_payments", "subcontractor_performance"),
    **_family(FAMILY_COMMERCIAL,
              "offers", "offer_versions", "offer_events", "offer_line_budgets",
              "change_orders", "client_acts", "contract_payments", "invoices",
              "invoice_lines", "invoice_versions", "invoice_settings", "supplier_invoices",
              "ocr_invoice_intake", "historical_offer_rows", "historical_import_batches",
              "sales"),
    **_family(FAMILY_PAYMENTS,
              "finance_payments", "payment_allocations", "financial_accounts",
              "cash_transactions", "advances", "payroll_runs", "payslips", "payroll_payments",
              "payroll_payment_allocations", "payroll_entries", "pay_runs",
              "pay_run_allocations", "payment_slips", "bonus_payments", "pending_expenses",
              "fixed_expenses", "overhead_categories", "overhead_costs", "overhead_assets",
              "overhead_snapshots", "overhead_transactions", "revenue_snapshots"),
    **_family(FAMILY_WAREHOUSE,
              "warehouses", "location_nodes", "warehouse_transactions", "warehouse_batches",
              "stock_thresholds", "deliveries"),
    **_family(FAMILY_MATERIALS,
              "items", "material_requests", "material_entries", "material_prices",
              "material_waste_entries", "material_consumption_log", "planned_materials",
              "equipment_requests", "equipment_assignments", "machines"),
    **_family(FAMILY_WORK,
              "work_types", "smr_groups", "smr_group_reports", "smr_analyses", "missing_smr",
              "extra_work_drafts", "execution_packages", "activity_catalog",
              "price_modifiers_config", "resource_model_config"),
    **_family(FAMILY_ASSETS,
              "asset_items", "asset_units", "asset_item_types", "asset_custody",
              "asset_movements", "asset_repairs", "asset_qr_codes", "asset_intake_pending",
              "asset_counters"),
    **_family(FAMILY_TASKS,
              "worker_calendar", "alarm_rules", "alarm_events"),
    **_family(FAMILY_FILES,
              # Legacy per-module file metadata (W0-06A inventory: the records
              # the File Registry replaces as the identity of a file).
              "media_files", "scan_docs", "excel_import_templates",
              # W0-06A canonical File Registry (FLOW-016). ``org_id``-keyed like
              # every other operational collection, because its relations point
              # at ``org_id``-keyed business records: splitting the two keys
              # would put half of each relation on each side of the boundary.
              # The one list in ``app.files.models.REGISTRY_COLLECTIONS`` must
              # equal the names here; ``tests/test_w0_06a_file_registry.py``
              # proves it, so a new collection cannot appear unclassified.
              "file_registry", "file_versions", "file_relations",
              "file_provider_locations", "file_derived_cache",
              "file_delete_requests",
              # W0-06B: the registry's per-tenant registration counter.
              "file_registry_sequences",
              # W0-06B storage providers (FLOW-016 onboarding): the tenant's
              # provider bindings, its sealed credentials, the evidence of each
              # activation attempt and the short-lived BEG_Work access grants.
              "storage_provider_bindings", "storage_credentials",
              "storage_activation_runs", "storage_access_grants"),
    **_family(FAMILY_AUDIT,
              "audit_logs"),
    **_family(FAMILY_SETTINGS,
              "settings", "org_counters", "org_mobile_settings", "mobile_view_configs",
              "feature_flags", "subscriptions", "ai_calibrations", "ai_calibration_events",
              "ai_cache"),
}

#: The authorization relations inside :data:`ORG_KEYED` (zero ownerless rows
#: here is a separate PASS condition of Issue #38 Phase 6).
AUTHORIZATION_COLLECTIONS: FrozenSet[str] = frozenset({"project_team", "users"})

#: Canonical W0-03 / W0-04 stores, keyed by ``tenant_id``. ``md_*`` is matched
#: by prefix because every Master Data entity type has its own collection.
TENANT_ID_KEYED_PREFIXES: Tuple[str, ...] = ("md_",)
TENANT_ID_KEYED: FrozenSet[str] = frozenset({
    "audit_events", "audit_idempotency", "audit_counters",
})

#: The tenant root: one document per organization; its ``id`` is the tenant key.
TENANT_ROOT = "organizations"

#: Database-level bookkeeping with no tenant meaning (W0-03C index ledger).
TECHNICAL: FrozenSet[str] = frozenset({"md_uniqueness_runs"})

#: Collections a PLATFORM principal (not a tenant) legitimately writes rows to:
#: the platform administrator's own user record and its security log
#: (``app/routes/platform.py``). Anywhere else a platform owner is a conflict.
PLATFORM_ROWS_ALLOWED: FrozenSet[str] = frozenset({"users", "audit_logs"})

#: The organization slug the platform bootstrap uses for its own system org
#: (``app/routes/platform.py``; ``scripts/w0_01_bootstrap_tenant_registry.py``
#: already treats it as "never the primary installation").
PLATFORM_ORG_SLUG = "platform-system"
#: The literal owner ``app/routes/platform.py`` writes on bootstrap audit rows.
PLATFORM_SYSTEM_OWNER = "SYSTEM"

CLASS_ORG = "ORG_KEYED"
CLASS_TENANT_ID = "TENANT_ID_KEYED"
CLASS_ROOT = "TENANT_ROOT"
CLASS_TECHNICAL = "TECHNICAL"
CLASS_UNCLASSIFIED = "UNCLASSIFIED"


def classify_collection(name: str) -> str:
    """The ONE class of a collection. Unknown is ``UNCLASSIFIED``, never safe."""
    if name in ORG_KEYED:
        return CLASS_ORG
    if name in TECHNICAL:
        return CLASS_TECHNICAL
    if name in TENANT_ID_KEYED or name.startswith(TENANT_ID_KEYED_PREFIXES):
        return CLASS_TENANT_ID
    if name == TENANT_ROOT:
        return CLASS_ROOT
    return CLASS_UNCLASSIFIED


def tenant_key_of(name: str) -> Optional[str]:
    """The field that carries the owner in this collection, or ``None``."""
    cls = classify_collection(name)
    if cls == CLASS_ORG:
        return ORG_KEY
    if cls == CLASS_TENANT_ID:
        return TENANT_ID_KEY
    return None


def family_of(name: str) -> str:
    cls = classify_collection(name)
    if cls == CLASS_ORG:
        return ORG_KEYED[name]
    if cls == CLASS_TENANT_ID:
        return "W0-03 Master Data / W0-04 audit (tenant_id)"
    if cls == CLASS_ROOT:
        return "tenant root"
    if cls == CLASS_TECHNICAL:
        return "technical bookkeeping"
    return "UNCLASSIFIED"


# --------------------------------------------------------- one document's owner
OWNER_BOUND = "BOUND"            # carries this tenant
OWNER_OWNERLESS = "OWNERLESS"    # carries no tenant at all
OWNER_CONFLICT = "CONFLICT"      # carries another / a malformed / a contradictory owner
OWNER_PLATFORM = "PLATFORM"      # a platform principal's own row, where that is allowed

#: A ``$or`` predicate matching exactly the documents :func:`owner_state` calls
#: OWNERLESS on ``key``: missing, ``null`` or the empty string. A value that is
#: present but not a string is NOT ownerless — it is a malformed owner and a
#: conflict, so a backfill can never paper over it.
def ownerless_predicate(key: str = ORG_KEY) -> Dict[str, Any]:
    return {"$or": [{key: {"$exists": False}}, {key: None}, {key: ""}]}


def is_missing_owner(value: Any) -> bool:
    return value is None or value == ""


def owner_state(doc: Mapping[str, Any], collection: str, *,
                tenant_ids: Iterable[str], platform_owners: Iterable[str] = ()) -> str:
    """Classify ONE document of a tenant-owned collection. Pure.

    ``tenant_ids`` are the values that mean "the resolved tenant" (its registry
    id and its legacy ``org_id``, which are the same value for the bootstrapped
    primary installation). ``platform_owners`` are the platform organization ids
    (plus the literal ``SYSTEM``), honoured only in
    :data:`PLATFORM_ROWS_ALLOWED`.

    A document whose ``org_id`` is ownerless but whose ``tenant_id`` names
    ANOTHER tenant is a conflict, not ownerless: the two fields contradict and
    a contradiction is never resolved by preferring one side.
    """
    key = tenant_key_of(collection)
    if key is None:
        raise ValueError("%r is not a tenant-owned collection" % collection)
    mine = {t for t in tenant_ids if isinstance(t, str) and t}
    if not mine:
        raise ValueError("no resolved tenant")
    platform = {p for p in platform_owners if isinstance(p, str) and p}
    owner = doc.get(key)
    other_key = TENANT_ID_KEY if key == ORG_KEY else ORG_KEY
    other = doc.get(other_key)
    other_conflicts = (not is_missing_owner(other)) and (
        not isinstance(other, str) or (other not in mine and other not in platform))
    if is_missing_owner(owner):
        return OWNER_CONFLICT if other_conflicts else OWNER_OWNERLESS
    if not isinstance(owner, str) or not owner.strip():
        return OWNER_CONFLICT
    if owner in mine:
        return OWNER_CONFLICT if other_conflicts else OWNER_BOUND
    if owner in platform and collection in PLATFORM_ROWS_ALLOWED:
        return OWNER_PLATFORM
    return OWNER_CONFLICT
