"""Migration-readiness: dry-run only; execute always refuses.

TASK 5C hard boundary — the module exists so an owner-approved plan has
all the inventories and reconciliations it needs, but calling
`execute_migration()` is unconditionally refused.
"""
import pytest

from app.services.warehouse_movements.errors import MigrationExecutionRefusedError
from app.services.warehouse_movements.migration_readiness import (
    execute_migration, legacy_writer_inventory_report,
)


@pytest.mark.asyncio
async def test_execute_is_refused_hard():
    with pytest.raises(MigrationExecutionRefusedError):
        await execute_migration()


def test_legacy_writer_inventory_report_runs_dry_run_only():
    report = legacy_writer_inventory_report()
    assert report["dry_run"] is True
    assert "generated_at" in report
    assert "canonical_only_collections_with_other_writers" in report
    # The report lists positions on canonical-only collections outside the
    # service/projector; counts may be nonzero (pre-existing historical
    # writers under fail-close guards) but the structure is stable.
    assert "total_offending_positions" in report
