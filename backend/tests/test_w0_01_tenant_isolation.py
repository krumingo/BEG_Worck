"""
W0-01 — Tenant isolation tests.

These are the tests that must stay green forever. Each one encodes a rule
from D-15 / TENANCY_MODEL.md that, if broken, leaks one company's financial
data into another company's screens.

Run:  pytest tests/test_w0_01_tenant_isolation.py -v
"""
import pytest
from fastapi import HTTPException

from app.tenancy.guard import TenantContext
from app.tenancy import registry


TENANT_A = {"id": "tenant-a", "name": "Building Express", "status": "active",
            "database_name": "begwork_tenant_a", "schema_version": 1}
TENANT_B = {"id": "tenant-b", "name": "Interior Express", "status": "active",
            "database_name": "begwork_tenant_b", "schema_version": 1}
TENANT_SUSPENDED = {"id": "tenant-c", "name": "Overdue Ltd", "status": "suspended",
                    "database_name": "begwork_tenant_c", "schema_version": 1}

USER_A = {"id": "user-1", "email": "krum@example.com", "org_id": "tenant-a"}


def ctx_a() -> TenantContext:
    return TenantContext(tenant=TENANT_A, user=USER_A,
                         membership={"user_id": "user-1", "tenant_id": "tenant-a"})


def test_record_of_own_tenant_is_owned():
    assert ctx_a().owns({"id": "inv-1", "tenant_id": "tenant-a"}) is True


def test_record_of_foreign_tenant_is_denied():
    """The core leak scenario: an invoice belonging to another company."""
    assert ctx_a().owns({"id": "inv-9", "tenant_id": "tenant-b"}) is False


def test_legacy_org_id_still_recognised():
    """Records written before the migration carry org_id, not tenant_id."""
    assert ctx_a().owns({"id": "prj-1", "org_id": "tenant-a"}) is True


def test_record_without_owner_is_denied_not_assumed():
    """Unknown ownership must never default to 'mine'."""
    assert ctx_a().owns({"id": "orphan-1"}) is False


def test_missing_record_is_denied():
    assert ctx_a().owns(None) is False


def test_assert_owns_raises_404_for_foreign_record():
    """404, not 403: a foreign id must not be confirmed as existing."""
    with pytest.raises(HTTPException) as exc:
        ctx_a().assert_owns({"id": "inv-9", "tenant_id": "tenant-b"}, "Invoice")
    assert exc.value.status_code == 404


def test_assert_owns_passes_own_record():
    record = {"id": "inv-1", "tenant_id": "tenant-a"}
    assert ctx_a().assert_owns(record) is record


def test_active_tenant_is_operational():
    assert ctx_a().is_operational is True


def test_suspended_tenant_is_not_operational():
    ctx = TenantContext(tenant=TENANT_SUSPENDED, user=USER_A)
    assert ctx.is_operational is False


def test_grace_and_restricted_still_operational():
    """Unpaid subscription must not stop day-to-day work during grace."""
    for status in (registry.TENANT_STATUS_GRACE, registry.TENANT_STATUS_RESTRICTED):
        tenant = dict(TENANT_A, status=status)
        assert TenantContext(tenant=tenant, user=USER_A).is_operational is True


def test_database_name_comes_only_from_registry():
    assert registry.resolve_database_name(TENANT_A) == "begwork_tenant_a"


def test_tenant_without_database_name_raises():
    """A registry record without a database must fail loudly, not silently
    fall back to a shared default database."""
    with pytest.raises(ValueError):
        registry.resolve_database_name({"id": "tenant-x"})


def test_two_tenants_never_resolve_to_the_same_database():
    assert registry.resolve_database_name(TENANT_A) != registry.resolve_database_name(TENANT_B)


def test_tenant_id_property_matches_registry_record():
    assert ctx_a().tenant_id == "tenant-a"
