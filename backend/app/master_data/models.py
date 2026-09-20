"""
W0-03B1 — Master Data canonical models (minimal slice).

Only what the approved contract fixes, nothing invented on top:
canonical id, tenant_id, entity type, lifecycle/status and the legacy_refs
bridge. Aliases, normalized names, identifiers, uniqueness and merge belong
to W0-03C/D and are deliberately absent here.

Canon: FLOW-032 (Златно правило — nine entity types), TENANCY_MODEL.md §6
(Master Data is always per tenant), docs/architecture/
W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md §5.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

# --- the nine canonical types of FLOW-032 "Златно правило" -----------------
ENTITY_PERSON = "person"
ENTITY_ORGANIZATION = "organization"
ENTITY_ACTIVITY = "activity"            # Master СМР, never a project-specific row
ENTITY_ITEM = "item"
ENTITY_ASSET_TYPE = "asset_type"
ENTITY_PHYSICAL_ASSET = "physical_asset"
ENTITY_UNIT = "unit"
ENTITY_LOCATION = "location"
ENTITY_TAG = "tag"

ENTITY_TYPES = frozenset({
    ENTITY_PERSON, ENTITY_ORGANIZATION, ENTITY_ACTIVITY, ENTITY_ITEM,
    ENTITY_ASSET_TYPE, ENTITY_PHYSICAL_ASSET, ENTITY_UNIT, ENTITY_LOCATION,
    ENTITY_TAG,
})

# --- lifecycle -------------------------------------------------------------
STATUS_ACTIVE = "active"
STATUS_MERGED = "merged"        # redirect target lives in merged_into (W0-03D)
STATUS_ARCHIVED = "archived"
STATUSES = frozenset({STATUS_ACTIVE, STATUS_MERGED, STATUS_ARCHIVED})

# Keys a caller must never be able to smuggle in as the tenant. The tenant is
# decided server-side by the W0-01 resolver and nowhere else (D-15).
RESERVED_TENANT_KEYS = frozenset({
    "tenant_id", "tenantId", "org_id", "orgId", "organization_id",
})


class MasterDataInvalid(Exception):
    """A document does not satisfy the canonical shape."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_legacy_ref(collection: str, legacy_id: str, org_id: Optional[str] = None) -> Dict[str, Any]:
    """One entry of the migration bridge: where this identity came from.

    No old id is ever discarded (contract §5.2), so every legacy document keeps
    resolving after W0-03E.
    """
    if not collection or not isinstance(collection, str):
        raise MasterDataInvalid("legacy_ref.collection is required")
    if not legacy_id or not isinstance(legacy_id, str):
        raise MasterDataInvalid("legacy_ref.legacy_id is required")
    ref: Dict[str, Any] = {"collection": collection, "legacy_id": legacy_id}
    if org_id:
        ref["org_id"] = org_id
    return ref


def build_entity(
    *,
    tenant_id: str,
    entity_type: str,
    display_name: str,
    legacy_refs: Optional[List[Dict[str, Any]]] = None,
    entity_id: Optional[str] = None,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a canonical Master Data document.

    ``tenant_id`` is expected to come from the resolver-backed context; this
    function does not and cannot obtain one by itself.
    """
    if not tenant_id or not isinstance(tenant_id, str):
        raise MasterDataInvalid("tenant_id is required and must come from the server-side resolver")
    if entity_type not in ENTITY_TYPES:
        raise MasterDataInvalid(
            "unknown entity_type '%s'; FLOW-032 fixes: %s"
            % (entity_type, ", ".join(sorted(ENTITY_TYPES)))
        )
    if not display_name or not isinstance(display_name, str) or not display_name.strip():
        raise MasterDataInvalid("display_name is required")

    stamp = now or _now()
    doc = {
        "id": entity_id or str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "entity_type": entity_type,
        "display_name": display_name.strip(),
        "status": STATUS_ACTIVE,
        "merged_into": None,          # W0-03D fills this; never a hard delete
        "legacy_refs": list(legacy_refs or []),
        "created_at": stamp,
        "updated_at": stamp,
    }
    validate_entity(doc)
    return doc


def validate_entity(doc: Dict[str, Any]) -> None:
    """Raise MasterDataInvalid unless the document is canonically shaped."""
    if not isinstance(doc, dict):
        raise MasterDataInvalid("entity must be a document")
    for field in ("id", "tenant_id", "entity_type", "display_name", "status"):
        if not doc.get(field):
            raise MasterDataInvalid("missing required field: %s" % field)
    if doc["entity_type"] not in ENTITY_TYPES:
        raise MasterDataInvalid("unknown entity_type: %s" % doc["entity_type"])
    if doc["status"] not in STATUSES:
        raise MasterDataInvalid("unknown status: %s" % doc["status"])
    if doc["status"] == STATUS_MERGED and not doc.get("merged_into"):
        raise MasterDataInvalid("a merged entity must point at its canonical target")
    if doc["status"] != STATUS_MERGED and doc.get("merged_into"):
        raise MasterDataInvalid("merged_into is only valid for a merged entity")
    refs = doc.get("legacy_refs", [])
    if not isinstance(refs, list):
        raise MasterDataInvalid("legacy_refs must be a list")
    for ref in refs:
        if not isinstance(ref, dict) or not ref.get("collection") or not ref.get("legacy_id"):
            raise MasterDataInvalid("each legacy_ref needs collection and legacy_id")
