"""
Canonical movement action vocabulary (FLOW-009 §"Видове движения").

Every physical fact a warehouse writer may append is one of these values.
Legacy strings `intake`, `issue`, `return` are NOT in this enum: they are
retired, and the compatibility layer in `legacy_inventory.py` maps the
historical rows to their closest canonical reading for read-only views.
"""
from enum import Enum
from typing import FrozenSet


class CanonicalAction(str, Enum):
    # Purchase paths (FLOW-009 §"Вход на материал" + FLOW-020 §"Класификация")
    RECEIVE_FROM_SUPPLIER = "receive_from_supplier"           # supplier -> warehouse
    RECEIVE_FROM_SUPPLIER_TO_PROJECT = "receive_from_supplier_to_project"  # supplier -> project (direct delivery)
    # Multi-destination allocation (FLOW-020 §"Разпределение"): one invoice
    # line split across destinations is implemented as several
    # RECEIVE_FROM_SUPPLIER_* movements, each with destination acceptance.

    # Reservation (FLOW-009 §"Три основни състояния")
    RESERVE = "reserve"
    RELEASE_RESERVATION = "release_reservation"

    # Internal movements with dispatch / in-transit / acceptance split
    # (FLOW-009 §"Прехвърляния"; FLOW-012 §7; Rule B = F-09=B).
    DISPATCH_WAREHOUSE_TO_PROJECT = "dispatch_warehouse_to_project"
    ACCEPT_PROJECT_DELIVERY = "accept_project_delivery"
    TRANSFER_PROJECT_TO_WAREHOUSE = "transfer_project_to_warehouse"
    TRANSFER_PROJECT_TO_PROJECT = "transfer_project_to_project"
    TRANSFER_WAREHOUSE_TO_WAREHOUSE = "transfer_warehouse_to_warehouse"

    # Consumption on SMR (FLOW-009 §"Разход по обект")
    CONSUME_TO_SMR = "consume_to_smr"

    # Reverse / disposition dispositions
    RETURN_TO_SUPPLIER = "return_to_supplier"
    WRITE_OFF = "write_off"                       # loss / theft / scrap

    # Revision = authorized correction (FLOW-009 §"Ревизия")
    REVISION_ADJUSTMENT = "revision_adjustment"

    # Quarantine (FLOW-009 §"Връщане и карантина")
    QUARANTINE_ENTRY = "quarantine_entry"
    QUARANTINE_RELEASE = "quarantine_release"     # -> free stock / return / scrap / redirect


ALL_ACTIONS: FrozenSet[CanonicalAction] = frozenset(a for a in CanonicalAction)

# Actions that remove quantity from an origin stock bucket; FIFO must run
# server-side for these and layer_allocations must be recorded.
OUTBOUND_ACTIONS: FrozenSet[CanonicalAction] = frozenset({
    CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT,
    CanonicalAction.TRANSFER_PROJECT_TO_WAREHOUSE,
    CanonicalAction.TRANSFER_PROJECT_TO_PROJECT,
    CanonicalAction.TRANSFER_WAREHOUSE_TO_WAREHOUSE,
    CanonicalAction.CONSUME_TO_SMR,
    CanonicalAction.RETURN_TO_SUPPLIER,
    CanonicalAction.WRITE_OFF,
})

# Actions that add quantity to a destination stock bucket. Supplier-origin
# receives are inbound; so are the acceptance side of dispatch/transfer.
INBOUND_ACTIONS: FrozenSet[CanonicalAction] = frozenset({
    CanonicalAction.RECEIVE_FROM_SUPPLIER,
    CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT,
    CanonicalAction.ACCEPT_PROJECT_DELIVERY,
})

# Actions that move quantity in/out of the quarantine state (FLOW-009:
# quarantine is a STATE at a real location, never another location).
QUARANTINE_ACTIONS: FrozenSet[CanonicalAction] = frozenset({
    CanonicalAction.QUARANTINE_ENTRY,
    CanonicalAction.QUARANTINE_RELEASE,
})

# Rule B / F-09: destination acceptance costs the accepted quantity only.
# Dispatch has no project cost; unresolved remainder stays in transit.
# Owner decision: https://github.com/krumingo/BEG_Worck/issues/52#issuecomment-6100672841
RULE_B_COSTING_ACTIONS: FrozenSet[CanonicalAction] = frozenset({
    CanonicalAction.ACCEPT_PROJECT_DELIVERY,
    CanonicalAction.CONSUME_TO_SMR,
    CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT,
})

RULE_B_ZERO_COST_ACTIONS: FrozenSet[CanonicalAction] = frozenset({
    CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT,
})

# Reservation actions. Reservations do not move stock, they claim a share
# of the free balance so a parallel issue cannot take it (FLOW-009).
RESERVATION_ACTIONS: FrozenSet[CanonicalAction] = frozenset({
    CanonicalAction.RESERVE,
    CanonicalAction.RELEASE_RESERVATION,
})

# Revision creates a corrective movement with a mandatory reason and
# evidence (FLOW-009 §"Ревизия"; FLOW-040 §2 corrections are a new event).
REVISION_ACTIONS: FrozenSet[CanonicalAction] = frozenset({
    CanonicalAction.REVISION_ADJUSTMENT,
})

# Permission action string per canonical action — the string handed to
# `evaluate_permission`. Catalog in `permissions/catalog.py` must list each
# of these; a missing listing fails closed (deny-by-default).
PERMISSION_ACTION = {
    CanonicalAction.RECEIVE_FROM_SUPPLIER: "warehouse.receive_from_supplier",
    CanonicalAction.RECEIVE_FROM_SUPPLIER_TO_PROJECT: "warehouse.receive_from_supplier_to_project",
    CanonicalAction.RESERVE: "warehouse.reserve",
    CanonicalAction.RELEASE_RESERVATION: "warehouse.release_reservation",
    CanonicalAction.DISPATCH_WAREHOUSE_TO_PROJECT: "warehouse.dispatch_to_project",
    CanonicalAction.ACCEPT_PROJECT_DELIVERY: "warehouse.accept_delivery",
    CanonicalAction.TRANSFER_PROJECT_TO_WAREHOUSE: "warehouse.transfer_project_to_warehouse",
    CanonicalAction.TRANSFER_PROJECT_TO_PROJECT: "warehouse.transfer_project_to_project",
    CanonicalAction.TRANSFER_WAREHOUSE_TO_WAREHOUSE: "warehouse.transfer_warehouse_to_warehouse",
    CanonicalAction.CONSUME_TO_SMR: "warehouse.consume_smr",
    CanonicalAction.RETURN_TO_SUPPLIER: "warehouse.return_to_supplier",
    CanonicalAction.WRITE_OFF: "warehouse.write_off",
    CanonicalAction.REVISION_ADJUSTMENT: "warehouse.revision_adjustment",
    CanonicalAction.QUARANTINE_ENTRY: "warehouse.quarantine_entry",
    CanonicalAction.QUARANTINE_RELEASE: "warehouse.quarantine_release",
}

# Actions whose dispositions require evidence (file_id). Fail CLOSED when
# File Registry (W0-06) is not available: the gate exists even though
# upstream prerequisite is open — never a silent bypass.
EVIDENCE_REQUIRED_ACTIONS: FrozenSet[CanonicalAction] = frozenset({
    CanonicalAction.REVISION_ADJUSTMENT,     # §"Ревизия" protocol/snimki
    CanonicalAction.WRITE_OFF,               # loss / theft / scrap evidence
    CanonicalAction.RETURN_TO_SUPPLIER,      # reclamation evidence
})


def permission_action_for(action: CanonicalAction) -> str:
    """Return the Permission Service action string for a canonical action.

    Deny-by-default: an action absent from the mapping is refused upstream.
    """
    try:
        return PERMISSION_ACTION[action]
    except KeyError as exc:
        raise KeyError(f"no permission action mapped for {action!r}") from exc
