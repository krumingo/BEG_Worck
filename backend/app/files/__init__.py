"""
W0-06A — the one File Registry (FLOW-016).

Additive package. Importing it changes no existing collection and no existing
route: W0-06A builds the foundation and the inventory, and the legacy upload
paths keep working exactly as they do today until a later slice migrates them.

    app.files.models        the canonical records and the one vocabulary
    app.files.registry      the tenant-bound service: the ONE write path
    app.files.providers     the storage provider adapter CONTRACT (+ a fake)
    app.files.migration_map the deterministic legacy migration plan

Canon: FLOW-016 (Business Lock), FLOW-002 (permissions), FLOW-040 (AuditEvent),
CLAUDE.md v15 rules 6, 7 and 9, IMPLEMENTATION_WAVES.md W0-06.
"""
from app.files.models import (
    CATEGORIES,
    DELETE_REQUESTS_COLLECTION,
    DERIVED_COLLECTION,
    FILES_COLLECTION,
    LOCATIONS_COLLECTION,
    PROVIDER_KINDS,
    REGISTRY_COLLECTIONS,
    RELATIONS_COLLECTION,
    RELATION_TARGETS,
    RELATION_TYPES,
    SOURCE_FLOW,
    VERSIONS_COLLECTION,
    FileRecordInvalid,
    new_file_id,
)
from app.files.registry import (
    FileNotFound,
    FileRegistry,
    FileRegistryError,
    RelationTargetNotFound,
    VersionSealed,
)

__all__ = [
    "CATEGORIES", "DELETE_REQUESTS_COLLECTION", "DERIVED_COLLECTION",
    "FILES_COLLECTION", "LOCATIONS_COLLECTION", "PROVIDER_KINDS",
    "REGISTRY_COLLECTIONS", "RELATIONS_COLLECTION", "RELATION_TARGETS",
    "RELATION_TYPES", "SOURCE_FLOW", "VERSIONS_COLLECTION",
    "FileRecordInvalid", "new_file_id",
    "FileNotFound", "FileRegistry", "FileRegistryError",
    "RelationTargetNotFound", "VersionSealed",
]
