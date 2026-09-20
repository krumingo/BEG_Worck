"""
W0-03 Master Data (FLOW-032) — canonical identity layer.

**Slice W0-03B1: foundation only.** The package is additive and inert: with
``MASTER_DATA_MODE`` unset or ``off`` — the default — importing it changes no
behaviour, creates no collection, performs no read or write, emits no
AuditEvent and writes no pending record. No existing route is wired to it.

What is deliberately NOT here (later slices):
  * aliases, normalization and unique indexes — W0-03C;
  * merge, redirect history and immutable references — W0-03D;
  * legacy migration and route adapters — W0-03E;
  * pending-mapping records — W0-03B2.

Canon: FLOW-032, TENANCY_MODEL.md §2/§6 (D-15),
docs/architecture/W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md.
"""
from app.master_data.deps import (  # noqa: F401
    ENV_MODE,
    MODE_ENFORCE,
    MODE_OFF,
    MODE_SHADOW,
    VALID_MODES,
    MasterDataConfigError,
    MasterDataTenantContextMissing,
    current_mode,
    is_off,
    require_tenant_context,
    resolve_mode,
    validate_config,
    validate_mode,
)
from app.master_data.models import (  # noqa: F401
    ENTITY_ACTIVITY,
    ENTITY_ASSET_TYPE,
    ENTITY_ITEM,
    ENTITY_LOCATION,
    ENTITY_ORGANIZATION,
    ENTITY_PERSON,
    ENTITY_PHYSICAL_ASSET,
    ENTITY_TAG,
    ENTITY_TYPES,
    ENTITY_UNIT,
    STATUS_ACTIVE,
    STATUS_ARCHIVED,
    STATUS_MERGED,
    MasterDataInvalid,
    build_entity,
    new_legacy_ref,
    validate_entity,
)
from app.master_data.pending import (  # noqa: F401
    PENDING_COLLECTION,
    PENDING_SOURCES,
    SOURCE_AI,
    SOURCE_EXCEL,
    SOURCE_IMPORT,
    SOURCE_OCR,
    STATUS_PENDING,
    PendingOutcome,
    build_pending,
    build_suggestion,
    get_pending,
    propose,
    validate_pending,
)
from app.master_data.service import (  # noqa: F401
    PERSON_CREATION_SOURCES,
    SOURCE_EXPLICIT_CONFIRMATION,
    SOURCE_FLOW,
    MasterDataAuditFailed,
    MasterDataOutcome,
    MasterDataRefused,
    create_entity,
    get_entity,
)

__all__ = [
    "ENV_MODE", "MODE_OFF", "MODE_SHADOW", "MODE_ENFORCE", "VALID_MODES",
    "MasterDataConfigError", "MasterDataTenantContextMissing",
    "current_mode", "validate_config", "validate_mode", "resolve_mode", "is_off",
    "require_tenant_context",
    "ENTITY_TYPES", "ENTITY_PERSON", "ENTITY_ORGANIZATION", "ENTITY_ACTIVITY",
    "ENTITY_ITEM", "ENTITY_ASSET_TYPE", "ENTITY_PHYSICAL_ASSET", "ENTITY_UNIT",
    "ENTITY_LOCATION", "ENTITY_TAG",
    "STATUS_ACTIVE", "STATUS_MERGED", "STATUS_ARCHIVED",
    "MasterDataInvalid", "build_entity", "validate_entity", "new_legacy_ref",
    "MasterDataOutcome", "MasterDataRefused", "MasterDataAuditFailed",
    "create_entity", "get_entity", "SOURCE_FLOW",
    "SOURCE_EXPLICIT_CONFIRMATION", "PERSON_CREATION_SOURCES",
    "PENDING_COLLECTION", "PENDING_SOURCES", "STATUS_PENDING",
    "SOURCE_AI", "SOURCE_OCR", "SOURCE_EXCEL", "SOURCE_IMPORT",
    "PendingOutcome", "propose", "get_pending",
    "build_pending", "validate_pending", "build_suggestion",
]
