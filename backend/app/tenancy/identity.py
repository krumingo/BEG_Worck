"""
R0-03 — one email = one User in the whole installation (decision Р6, AUTH-01 F-03).

Where the User registry is
--------------------------
* ``off`` / ``shadow``: every User lives in the legacy global database
  (``app.db.db``, collection ``users``). Login (``POST /auth/login``) and the
  session loader (``get_current_user``) read only that collection. The email
  check of ``POST /users`` still covers the whole installation here (R0-03-C02),
  reading ``tenant_registry`` directly like onboarding — no resolver, no
  Permission Service (W0-02 PR-05).
* Platform bootstrap, the installation seed and tenant onboarding have no
  permission mode: they always check the whole installation.
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

import inspect
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
        try:
            rows = await database.users.find(email_match_filter(norm), {"_id": 0}).to_list(50)
        except Exception as exc:       # R0-03-C02: an unreadable database is an unknown answer
            raise IdentityCheckUnavailable("a database could not be searched") from exc
        for row in rows:
            if normalize_email(row.get("email")) == norm:
                found.append(dict(row, _database=database.name))
    return found


class IdentityCheckUnavailable(RuntimeError):
    """The installation could not be fully enumerated: the uniqueness check is unknown.

    Fail closed (R0-03-C01 F-03): the caller refuses the creation before its first
    write instead of skipping a database it could not check.
    """


ERROR_IDENTITY_CHECK_UNAVAILABLE = "IDENTITY_CHECK_UNAVAILABLE"


async def _scan(global_db, records: Iterable[Dict[str, Any]], open_database) -> List[Any]:
    """The ONE enumeration: the global database + every registry record's database.

    Every record must name a database (``database_name``) that ``open_database``
    opens; anything else raises :class:`IdentityCheckUnavailable`. All records are
    required, not only active ones — a suspended tenant's users still own their emails.
    """
    out = [global_db]
    for record in records:
        name = record.get("database_name")
        if not isinstance(name, str) or not name.strip():
            raise IdentityCheckUnavailable("a tenant registry record has no database_name")
        try:
            handle = open_database(record)
            if inspect.isawaitable(handle):
                handle = await handle
        except Exception as exc:
            raise IdentityCheckUnavailable("a tenant database cannot be opened") from exc
        if handle is None:
            raise IdentityCheckUnavailable("a tenant database cannot be opened")
        out.append(handle)
    return out


async def installation_databases(global_db, mode: Optional[str] = None) -> List[Any]:
    """Every database that holds Users, from the module Tenant Registry. Fail closed.

    Used by ``POST /users`` in enforce (tenant databases through the resolver),
    platform bootstrap and the installation seed (``mode=None``: the whole
    installation). ``POST /users`` in ``off``/``shadow`` uses
    :func:`installation_databases_for` instead (R0-03-C02): the same read-only
    ``tenant_registry`` enumeration as onboarding, with no resolver and no
    Permission Service, so W0-02 PR-05 still holds. A non-enforce ``mode`` here
    returns the global database only and is no longer used for an email check.
    """
    from app.permissions.deps import MODE_ENFORCE
    if mode is not None and mode != MODE_ENFORCE:
        return [global_db]
    from app.tenancy import registry, resolver
    try:
        records = await registry.list_tenants()
    except Exception as exc:
        raise IdentityCheckUnavailable("the tenant registry cannot be read") from exc
    return await _scan(global_db, records, lambda r: resolver.get_tenant_db(r["id"]))


async def installation_databases_for(op_db, system_db) -> List[Any]:
    """Same enumeration for a caller that holds explicit handles: tenant onboarding,
    and ``POST /users`` in ``off``/``shadow`` (R0-03-C02 — no resolver involved).

    The registry is read from ``system_db``; a record's database is opened by name
    on ``op_db``'s client.
    """
    try:
        records = await system_db["tenant_registry"].find(
            {}, {"_id": 0, "id": 1, "database_name": 1}).to_list(None)
    except Exception as exc:
        raise IdentityCheckUnavailable("the tenant registry cannot be read") from exc
    return await _scan(op_db, records, lambda r: op_db.client[r["database_name"]])


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
