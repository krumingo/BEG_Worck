"""
W0-03E-A2C — tenant-safe identity for the fixed-``_id`` settings rows.

Why it exists. Three settings documents were stored under a GLOBAL literal
``_id`` in the one shared ``settings`` collection:

* ``worker_rates``            (``app/routes/extra_works.py``, ``app/routes/labor_smr.py``)
* ``employee_cost_config``    (``app/routes/full_cost.py``)
* ``overtime_config``         (``app/routes/work_sessions.py``)

``_id`` is unique per collection, so the collection can hold exactly ONE
``worker_rates`` document for the whole installation. The reads already carried
``org_id``, which makes the failure worse rather than better: the first tenant
to save owns the row, a second tenant's upsert fails with a duplicate-key error,
and its scoped read then returns nothing, so it silently falls back to defaults
and can never store its own rates, employee cost config or overtime rule. The
W0-03E-A2B review recorded this as an unclosed second-tenant limitation
(``coordination/REVIEWS/W0-03E-A2B.md`` §"Independent checks and residual debt").

The fix is identity, not a new business rule: the document id becomes
``"<key>:<org_id>"``, so every tenant owns its own row of each setting type and
no two tenants can collide on ``_id``. Each row ALSO carries ``org_id`` as a
normal field, so :class:`app.tenancy.data_access.TenantData` filters it like
every other tenant-owned record and the id is never the only thing separating
two tenants.

This is the convention the codebase already uses, not a new one:
``app/routes/sales.py`` stores ``sales_margins_<org_id>`` and
``app/master_data/legacy_migration.py`` stores ``state:<tenant_id>``. Those two
are already per-tenant and are deliberately left on their existing ids — this
module is the canonical helper for the three that were global, and for any
settings row added later.

Migration of the current BEG rows is
``scripts/w0_03e_a2c_settings_identity_migration.py``: it copies each legacy
global row to its tenant-scoped id with every field preserved (``_id`` is
immutable in MongoDB, so it is a copy plus a delete of the legacy row), is
idempotent and resumable, and never overwrites a tenant row that already exists.
No setting value, default or user-facing behaviour changes.

Pure and stdlib-only: no database, no FastAPI, no application import, so the
static guard and the migration can both read it.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Tuple

#: The collection these rows live in.
SETTINGS_COLLECTION = "settings"

#: Separator between the setting key and the tenant. A colon cannot be confused
#: with a key name (the keys themselves contain ``_``) and matches the
#: ``state:<tenant_id>`` form already used by the Master Data migration state.
SEPARATOR = ":"

#: The three setting keys, named once so no route spells one as a bare string.
WORKER_RATES = "worker_rates"
EMPLOYEE_COST_CONFIG = "employee_cost_config"
OVERTIME_CONFIG = "overtime_config"

#: The setting keys that were stored under a global ``_id`` and are now
#: per-tenant. Kept as an explicit tuple so the migration, the guard and the
#: tests all read ONE list; adding a settings row means adding it here.
LEGACY_GLOBAL_KEYS: Tuple[str, ...] = (
    WORKER_RATES,
    EMPLOYEE_COST_CONFIG,
    OVERTIME_CONFIG,
)

#: Settings rows that were ALREADY per-tenant before W0-03E-A2C and keep their
#: existing ``_id`` form, so the migration leaves their stored data alone.
#: ``app/routes/sales.py`` (``sales_margins_<org_id>``) is the only one.
ALREADY_SCOPED_PREFIXES: FrozenSet[str] = frozenset({"sales_margins_"})


def settings_id(key: str, org_id: str) -> str:
    """The tenant-scoped ``_id`` of one settings row.

    Both parts are required: an empty key or an empty/non-string tenant is a
    programming error and must fail closed rather than produce a global id that
    two tenants would share.
    """
    if not isinstance(key, str) or not key.strip():
        raise ValueError("settings key is required")
    if not isinstance(org_id, str) or not org_id.strip():
        raise ValueError("no server-resolved tenant for settings row %r" % key)
    if SEPARATOR in key:
        raise ValueError("settings key %r may not contain %r" % (key, SEPARATOR))
    return "%s%s%s" % (key, SEPARATOR, org_id)


def split_settings_id(value: str) -> Tuple[str, str]:
    """``("worker_rates", "<org>")`` for a tenant-scoped id; ``(value, "")`` otherwise.

    A legacy global id (no separator) reports an empty tenant, which is how the
    migration recognises a row that still has to be moved.
    """
    if not isinstance(value, str):
        return "", ""
    key, sep, org = value.partition(SEPARATOR)
    return (key, org) if sep else (value, "")


def is_legacy_global_id(value: str) -> bool:
    """True for exactly the three pre-A2C global ids, nothing else."""
    return value in LEGACY_GLOBAL_KEYS


def legacy_migration_plan(org_id: str) -> Dict[str, str]:
    """``{legacy global _id: tenant-scoped _id}`` for one tenant.

    The migration's whole plan: deterministic, derived from
    :data:`LEGACY_GLOBAL_KEYS`, with nothing inferred from the database.
    """
    return {key: settings_id(key, org_id) for key in LEGACY_GLOBAL_KEYS}
