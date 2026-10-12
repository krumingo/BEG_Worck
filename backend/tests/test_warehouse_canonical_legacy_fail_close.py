"""Legacy writer fail-close smoke.

Each retired warehouse writer route must raise `LegacyWriterRetiredError`
when `LEGACY_WAREHOUSE_WRITERS_ENABLED` is not set — regardless of role
or payload. The exception maps to HTTP 410 Gone at the route layer.

These tests do not go through FastAPI; they call the guard directly,
which is the only path that matters: a legitimate caller who reaches
the route is refused before the body does anything.
"""
import os

import pytest

from app.services.warehouse_movements.errors import LegacyWriterRetiredError
from app.services.warehouse_movements.legacy_inventory import (
    RETIRED_ROUTE_IDS, legacy_writers_enabled, refuse_if_disabled,
)


def test_default_env_disables_legacy_writers():
    os.environ.pop("LEGACY_WAREHOUSE_WRITERS_ENABLED", None)
    assert legacy_writers_enabled() is False


@pytest.mark.parametrize("route_id", sorted(RETIRED_ROUTE_IDS))
def test_each_retired_route_refuses_by_default(route_id):
    os.environ.pop("LEGACY_WAREHOUSE_WRITERS_ENABLED", None)
    with pytest.raises(LegacyWriterRetiredError) as excinfo:
        refuse_if_disabled(route_id, "canonical_replacement")
    assert excinfo.value.context["route_id"] == route_id
    assert excinfo.value.context["canonical_action"] == "canonical_replacement"


def test_escape_hatch_lets_calls_through():
    os.environ["LEGACY_WAREHOUSE_WRITERS_ENABLED"] = "1"
    try:
        refuse_if_disabled("procurement.post_to_warehouse", "receive_from_supplier")
    finally:
        del os.environ["LEGACY_WAREHOUSE_WRITERS_ENABLED"]
