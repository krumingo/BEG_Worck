"""
W0-06B — shared test support: tenants, FLOW-002 assignments, a configured world.

Permissions are decided by the REAL W0-02 Permission Service
(``app.permissions.service.evaluate_permission``); only its assignment loader is
replaced by an in-memory table, so the role → action catalog, deny-by-default
and the cross-tenant rule are exercised exactly as in production.
"""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace
from typing import Dict, List, Tuple

from app.files import models as m
from app.files.credentials import CredentialVault
from app.files.storage import RESPONSIBILITY_VERSION, StorageProviderService
from app.tenancy.data_access import TenantData
from tests import w0_06b_fake_backends as fb

A, B = "BEG", "TCB"
OWNER_A, OWNER_B, WORKER_A = "owner-a", "owner-b", "worker-a"
MASTER_KEY = os.urandom(32)

#: (user, tenant) -> assignments. Owner = full set; worker = canonical worker role.
ASSIGNMENTS: Dict[Tuple[str, str], List[dict]] = {
    (OWNER_A, A): [{"id": "ra-oa", "status": "active", "role_id": "owner",
                    "scope_type": "company"}],
    (OWNER_B, B): [{"id": "ra-ob", "status": "active", "role_id": "owner",
                    "scope_type": "company"}],
    (WORKER_A, A): [{"id": "ra-wa", "status": "active", "role_id": "worker",
                     "scope_type": "company"}],
}


def install_permissions(monkeypatch, extra: Dict[Tuple[str, str], List[dict]] = None):
    from app.permissions import service
    table = dict(ASSIGNMENTS)
    table.update(extra or {})

    async def load(user_id, tenant_id):
        return [dict(a) for a in table.get((user_id, tenant_id), [])]
    monkeypatch.setattr(service, "_load_assignments", load)
    return table


def ctx(user: str, tenant: str):
    return SimpleNamespace(user_id=user, tenant_id=tenant)


def accepted(user: str) -> dict:
    return {"accepted": True, "version": RESPONSIBILITY_VERSION, "accepted_by": user}


async def world(db=None, sysdb=None):
    """A shared operational db + a system db with both tenants registered."""
    from mongomock_motor import AsyncMongoMockClient
    client = AsyncMongoMockClient()
    db = db if db is not None else client["w006b_" + uuid.uuid4().hex[:6]]
    sysdb = sysdb if sysdb is not None else client["w006b_sys_" + uuid.uuid4().hex[:6]]
    for org in (A, B):
        await sysdb["tenant_registry"].insert_one(
            {"id": org, "legacy_org_id": org, "status": "active", "storage_provider": None,
             "storage_status": "not_configured"})
    return db, sysdb


def service_for(db, sysdb, org, backends: Dict[str, object]):
    """A storage service whose bindings reach the fake backend registered for them."""
    tenant = TenantData(db, org)

    def transport_for(row):
        backend = backends.get(row["id"]) or backends.get(row["provider_kind"])
        return backend.transport if backend is not None else None
    return StorageProviderService(tenant, sysdb, vault=CredentialVault(tenant, master_key=MASTER_KEY),
                                  transport_for=transport_for)


async def configure(svc, user, kind, role=m.LOCATION_ROLE_PRIMARY, **backend_kw):
    """Configure one binding against a fresh fake backend. Returns (binding_id, backend)."""
    backend, binding, creds = fb.build(kind, org_id=svc.org_id, **backend_kw)
    out = await svc.configure_binding(
        ctx(user, svc.org_id), role=role, provider_kind=kind, container=binding.container,
        root_prefix=binding.root_prefix, endpoint=binding.endpoint, account=binding.account,
        credentials=creds)
    return out["binding_id"], backend
