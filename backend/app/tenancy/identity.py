"""
R0-03 — one email = one User in the whole installation (decision Р6, AUTH-01 F-03).

Where the User registry is
--------------------------
* ``off`` / ``shadow``: every User lives in the legacy global database
  (``app.db.db``, collection ``users``). Login (``POST /auth/login``) and the
  session loader (``get_current_user``) read only that collection.
* ``enforce``: ``POST /users`` writes into the database the Tenant Registry
  resolves for the active tenant (``ctx.db()``). Today every registered tenant
  resolves to the legacy database (onboarding writes ``database_name`` =
  the operational database), but the registry may name another one. So in
  enforce the check covers the global database AND every database the
  registry names — the whole installation, not one tenant.

Access to companies is a TenantMembership question (R0-04); the identity
itself is unique by its normalized email.

Normalization is ``strip().lower()``. Existing rows were stored without it, so
lookups match case-insensitively with surrounding whitespace tolerated and
re-check the normalized value in Python. No row is rewritten here and no index
is created on import: :func:`ensure_user_email_unique_index` exists for the
separate, approved step after the duplicates report (R0-09).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

ERROR_EMAIL_EXISTS = "EMAIL_EXISTS"
ERROR_DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"

#: Case-insensitive collation for the future unique index (strength 2: case
#: differences are equal, accents are not).
EMAIL_COLLATION = {"locale": "en", "strength": 2}
EMAIL_UNIQUE_INDEX_NAME = "r0_03_email_unique_ci"


def normalize_email(value: Any) -> str:
    """``strip().lower()``; anything that is not a string is the empty email."""
    return value.strip().lower() if isinstance(value, str) else ""


def email_match_filter(email: Any) -> Dict[str, Any]:
    """Filter matching every stored spelling of this normalized email."""
    return {"email": {"$regex": r"^\s*%s\s*$" % re.escape(normalize_email(email)),
                      "$options": "i"}}


async def users_with_email(databases: Iterable[Any], email: Any) -> List[Dict[str, Any]]:
    """Every User whose normalized email is ``email``, across ``databases``.

    Each database is searched once (by name). Returns ``id``, ``org_id``,
    ``email``, ``is_active``, ``is_platform_admin`` and ``password_hash`` (the
    login needs it; callers never return it) plus the database name.
    """
    norm = normalize_email(email)
    if not norm:
        return []
    seen, found = set(), []
    for database in databases:
        if database is None or database.name in seen:
            continue
        seen.add(database.name)
        rows = await database.users.find(email_match_filter(norm), {"_id": 0}).to_list(50)
        for row in rows:
            if normalize_email(row.get("email")) == norm:
                found.append(dict(row, _database=database.name))
    return found


async def installation_databases(global_db, mode: str) -> List[Any]:
    """The databases that hold Users in this mode (see the module docstring).

    ``off``/``shadow`` never touch the Tenant Registry (W0-02 PR-05).
    """
    from app.permissions.deps import MODE_ENFORCE
    out = [global_db]
    if mode != MODE_ENFORCE:
        return out
    # Fail closed: a registry record the resolver cannot open raises here, so the
    # creation stops instead of skipping a database it could not check.
    from app.tenancy import registry, resolver
    for tenant in await registry.list_tenants():
        out.append(await resolver.get_tenant_db(tenant["id"]))
    return out


async def ensure_user_email_unique_index(database) -> str:  # pragma: no cover - not run in R0-03
    """Prepared, NOT called: a unique, case-insensitive index on ``users.email``.

    A collation index (not a second ``email_normalized`` field) because it needs
    no backfill and no extra field every creation path must keep in sync. It does
    not fold surrounding whitespace; the duplicates report lists such rows, and
    they are cleaned before this runs. Run only after the report is clean and
    Krum's "да" (R0-09). Fails on existing duplicates, by design.
    """
    return await database.users.create_index(
        "email", name=EMAIL_UNIQUE_INDEX_NAME, unique=True, collation=EMAIL_COLLATION)


def mask_email(value: Optional[str]) -> str:
    """``iv***@abv.bg`` — enough to recognise, not enough to reuse."""
    norm = normalize_email(value)
    if "@" not in norm:
        return "***"
    local, domain = norm.split("@", 1)
    return "%s***@%s" % (local[:2], domain)
