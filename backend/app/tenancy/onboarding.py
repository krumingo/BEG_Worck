"""
W0-03E-A2B — the canonical tenant onboarding path.

Issue #38 / docs/architecture/W0-03E-A2B_SINGLE_TENANT_BACKFILL.md §4: when a
second company is created it is onboarded through the normal tenant procedure,
and every one of its records carries its own server-resolved tenant from the
start. Before A2B a company could be created in two places
(``POST /billing/signup`` and ``scripts/create_company.py``), each writing an
``organizations`` row and an owner user, and neither registering the tenant:
the Tenant Registry only learnt about it if somebody re-ran the W0-01
bootstrap. A tenant the registry does not know is invisible to the Tenant
Guard and — decisive for A2B — to the single-tenant backfill precondition.

:func:`onboard_tenant` is now the one path both callers use. In one place it:

* generates the tenant id server-side (never a caller value);
* writes the tenant root (``organizations``) and the owner user, stamped with
  that tenant;
* registers the tenant in the W0-01 Tenant Registry with
  ``is_primary_installation: False`` — so the one-time BEG legacy rule can
  never apply to it, and so the registry now holds two operating tenants and
  :func:`app.tenancy.legacy_backfill.prove_precondition` fails closed for good;
* writes the owner's TenantMembership and an authoritative FLOW-002 company
  RoleAssignment (``owner``) scoped to that tenant.

It never copies or re-reads another tenant's data. Storage onboarding (D-11 /
FLOW-016) is NOT done here: the registry records ``storage_status:
not_configured`` exactly as the W0-01 bootstrap does for a non-primary tenant,
so activation remains a separate, explicit step.

``database_name`` is the operational database the application actually
writes this tenant's records to (the legacy global handle). Writing a
per-tenant name here would point the W0-01 resolver at an empty database while
every route writes elsewhere; physical database-per-tenant is a later W0-01
step, not something onboarding may pretend has happened.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

SCHEMA_VERSION = 1
ONBOARDING_SOURCE = "w0-03e-a2b-onboarding"


class OnboardingRefused(RuntimeError):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(name: str) -> str:
    s = re.sub(r"[\s_]+", "-", name.strip().lower())
    return s[:50]


async def onboard_tenant(op_db, system_db, *, org_name: str, owner_email: str,
                         owner_password_hash: str, owner_first_name: str,
                         owner_last_name: str = "", owner_role: str = "Owner",
                         organization_extra: Optional[Dict[str, Any]] = None,
                         plan: str = "free") -> Dict[str, Any]:
    """Create one new tenant end to end. Returns ``{tenant, organization, owner}``.

    The caller has already authenticated/authorized the request (public signup
    or an operator script) and hashed the password. No tenant value is an input.
    """
    name = (org_name or "").strip()
    email = (owner_email or "").strip().lower()
    if not name:
        raise OnboardingRefused("organization name is required", "BAD_REQUEST")
    if not email:
        raise OnboardingRefused("owner email is required", "BAD_REQUEST")
    if not owner_password_hash:
        raise OnboardingRefused("owner password hash is required", "BAD_REQUEST")
    if await op_db["users"].find_one({"email": email}, {"_id": 1}):
        raise OnboardingRefused("Email already registered", "EMAIL_EXISTS")

    now = _now()
    tenant_id = str(uuid.uuid4())          # server-generated; the only tenant value
    user_id = str(uuid.uuid4())
    slug = _slug(name)

    organization = {
        "id": tenant_id, "name": name, "slug": slug, "email": email,
        "phone": "", "address": "", "logo_url": "", "vat_percent": 20.0,
        "org_timezone": "Europe/Sofia", "created_at": now, "updated_at": now,
        **{k: v for k, v in (organization_extra or {}).items()
           if k not in ("id", "org_id", "tenant_id", "slug", "created_at")},
    }
    await op_db["organizations"].insert_one(dict(organization))

    owner = {
        "id": user_id, "org_id": tenant_id, "email": email,
        "password_hash": owner_password_hash, "first_name": owner_first_name or "",
        "last_name": owner_last_name or "", "role": owner_role, "phone": "",
        "is_active": True, "created_at": now, "updated_at": now,
    }
    await op_db["users"].insert_one(dict(owner))

    tenant = {
        "id": tenant_id, "legacy_org_id": tenant_id, "name": name, "slug": slug,
        "legal_name": name, "eik": "", "vat_number": "", "email": email,
        "timezone": "Europe/Sofia", "currency": "EUR", "vat_percent": 20.0,
        "database_name": op_db.name, "is_primary_installation": False,
        "status": "active", "plan": plan, "subscription_status": "trialing",
        "storage_provider": None, "storage_status": "not_configured",
        "schema_version": SCHEMA_VERSION, "migration_status": "onboarded",
        "onboarded_via": ONBOARDING_SOURCE, "created_at": now, "updated_at": now,
    }
    await system_db["tenant_registry"].insert_one(dict(tenant))
    await system_db["tenant_memberships"].insert_one({
        "id": "tm_%s_%s" % (user_id, tenant_id), "user_id": user_id, "tenant_id": tenant_id,
        "email": email, "status": "active", "is_owner": owner_role == "Owner",
        "created_at": now, "created_by": ONBOARDING_SOURCE})
    from app.permissions.catalog import LEGACY_ROLE_MAP
    await system_db["tenant_role_assignments"].insert_one({
        "id": "ra_%s_%s_onboarding" % (user_id, tenant_id), "user_id": user_id,
        "tenant_id": tenant_id, "role": owner_role,
        "role_id": LEGACY_ROLE_MAP.get(owner_role, "LEGACY_" + owner_role.upper()),
        "scope_type": "company", "scope_id": None, "module": None, "permissions": [],
        "max_amount": None, "valid_from": now, "valid_to": None, "status": "active",
        "created_by": ONBOARDING_SOURCE, "approved_by": None, "revision": 1,
        "created_at": now, "updated_at": now})
    for doc in (organization, owner, tenant):
        doc.pop("_id", None)
    owner.pop("password_hash", None)
    return {"tenant": tenant, "organization": organization, "owner": owner}
