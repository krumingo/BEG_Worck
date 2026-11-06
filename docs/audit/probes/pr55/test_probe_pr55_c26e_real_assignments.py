"""CLAUDE AUDIT probe — #55 C26e Р28 "same decision in all three modes", with the RoleAssignments the
product REALLY creates. app/permissions/sync.py grant_company_role (called by auth.py on user create/update
and by the W0-02 bootstrap) gives a legacy SiteManager a COMPANY-scope site_manager assignment with
permissions [] → role_actions(site_manager) (warehouse.accept_delivery / consume_smr / ...), and
_scope_covers("company", ...) covers every project. The project_team mirror only adds budget.*.
The C26e matrix used hand-built PROJECT-scope assignments for SiteManager instead.
Question: SiteManager who is NOT a member of P1 — consume / accept / return on P1 in off vs enforce."""
from decimal import Decimal
import pytest
from app.services.warehouse_movements.errors import PermissionDeniedError
from app.services.warehouse_movements.service import CommandService
from tests.test_warehouse_canonical_c22_all_reports_cutover import PROJECT, T, _inp, _patch_dbs, _seed
from tests.test_warehouse_canonical_c25_cost_at_accept_transit import _Run
from tests.test_warehouse_canonical_c26a_writeoff_rights_values import USER, _loader
from tests.test_warehouse_canonical_c26e_r28_all_modes import _command, _ctx, _prepare, _count

pytest_plugins = ["tests.warehouse_canonical_conftest"]
REAL_SM = [{"id": "ra-company-sm", "user_id": USER, "tenant_id": T, "role_id": "site_manager",
            "scope_type": "company", "scope_id": None, "module": None, "permissions": [],
            "max_amount": None, "valid_from": "2020-01-01T00:00:00+00:00", "valid_to": None,
            "status": "active"}]


@pytest.mark.parametrize("command", ["accept", "consume", "return_to_warehouse"])
@pytest.mark.parametrize("mode", ["off", "enforce"])
async def test_sm_non_member_real_assignment(canonical_mongo_db, allow_always_gate, monkeypatch, mode, command):
    from app.permissions import service as perm
    client, db = canonical_mongo_db
    _patch_dbs(monkeypatch, db); await _seed(db)
    run = _Run(client, allow_always_gate, db)
    pending = await _prepare(run)
    monkeypatch.setattr(perm, "_load_assignments", _loader(REAL_SM))
    monkeypatch.setenv("PERMISSION_SERVICE_MODE", mode)
    action, kw = _command(command, pending)
    before = await _count(db)
    try:
        await CommandService(client).execute(_ctx(mode, "SiteManager"), db, run.coll, _inp(action, T, quantity=Decimal("1"), **kw))
        outcome = "ALLOWED (+%d rows)" % (await _count(db) - before)
    except PermissionDeniedError as e:
        outcome = "DENIED (%s)" % e.context.get("reason_code")
    print("\nRESULT mode=%s command=%s non-member SiteManager → %s" % (mode, command, outcome))
