"""
W0-06B — integrity / availability checks and affected-record resolution.

FLOW-016 §"Периодична проверка": BEG_Work checks that the provider object
exists, that size, checksum and version/ID still match, that the provider still
grants the access needed, and whether the preview/cache could be regenerated
from the original. A missing or changed file must never be reported without
the list of every business record it affects, and a cached preview must never
become the canonical original.

This module is the REUSABLE check. It deliberately has no scheduler and raises
no alarm: the periodic runner and the DQ/Alarm records are W0-07 (FLOW-033/034).
What it gives W0-07 is an explicit, versioned result — :data:`FINDING_SCHEMA` —
returned to the caller and written into the AuditEvent, so the consumer reads a
contract instead of re-deriving one.

The five failure states are kept apart all the way through:

====================  ==============================================  =============
availability          meaning                                          finding type
====================  ==============================================  =============
missing               no object at the recorded location              ``missing_original``
permission_denied     the object may exist; this account may not read ``permission_failure``
checksum_mismatch     the bytes (or size) are proven different        ``checksum_mismatch``
provider_unreachable  the provider (or binding) cannot be used now    ``provider_unavailable``
externally_changed    same bytes, but another provider object/version ``external_change``
====================  ==============================================  =============
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from app.files import models as m
from app.files.authorization import authorize
from app.files.providers.base import IntegrityVerdict, ProviderObjectRef
from app.files.registry import FileNotFound, FileRegistry
from app.files.storage import StorageNotActive, StorageProviderService

FINDING_SCHEMA = "beg.w0-06b.file_integrity_finding/v1"

FINDING_TYPES = {
    m.AVAILABILITY_AVAILABLE: None,
    m.AVAILABILITY_UNVERIFIED: None,
    m.AVAILABILITY_MISSING: "missing_original",
    m.AVAILABILITY_PERMISSION_DENIED: "permission_failure",
    m.AVAILABILITY_CHECKSUM_MISMATCH: "checksum_mismatch",
    m.AVAILABILITY_PROVIDER_UNREACHABLE: "provider_unavailable",
    m.AVAILABILITY_EXTERNALLY_CHANGED: "external_change",
}

#: Who has to act, by finding. The original lives in the CUSTOMER's storage
#: (FLOW-016 responsibility boundary); BEG_Work owns the registry and the check.
RECOVERY = {
    "missing_original": ("customer", "restore the original at the provider location "
                                     "or re-upload it as a new version"),
    "permission_failure": ("customer", "restore the BEG_Work account's access to the object"),
    "checksum_mismatch": ("customer", "restore the recorded original; a changed file is "
                                      "never adopted as a new version automatically"),
    "provider_unavailable": ("customer", "restore provider connectivity or the binding"),
    "external_change": ("customer", "confirm the replaced object or restore the original"),
}

#: relation type -> the business group FLOW-016 asks to be named explicitly.
AFFECTED_GROUPS: Dict[str, str] = {
    m.RELATION_PROJECT: "projects", m.RELATION_SUB_PROJECT: "projects",
    m.RELATION_SITE: "projects",
    m.RELATION_OFFER: "offers_contracts_annexes", m.RELATION_CONTRACT: "offers_contracts_annexes",
    m.RELATION_ANNEX: "offers_contracts_annexes",
    m.RELATION_ACT: "acts_invoices", m.RELATION_INVOICE: "acts_invoices",
    m.RELATION_SUPPLIER_INVOICE: "acts_invoices", m.RELATION_EXPENSE: "acts_invoices",
    m.RELATION_DELIVERY: "deliveries",
    m.RELATION_DAILY_REPORT: "daily_reports", m.RELATION_WORK_REPORT: "daily_reports",
    m.RELATION_ATTENDANCE: "daily_reports",
    m.RELATION_TASK: "tasks", m.RELATION_SMR: "tasks", m.RELATION_EXTRA_WORK: "tasks",
    m.RELATION_DEFECT: "defects_warranties", m.RELATION_WARRANTY: "defects_warranties",
    m.RELATION_ASSET: "assets_repairs", m.RELATION_REPAIR: "assets_repairs",
    m.RELATION_MACHINE: "assets_repairs",
    m.RELATION_SUBCONTRACTOR: "other", m.RELATION_USER_PROFILE: "other",
    m.RELATION_OCR_INTAKE: "other",
}
assert set(AFFECTED_GROUPS) == set(m.RELATION_TYPES)

_LABEL_FIELDS = ("name", "title", "number", "invoice_no", "act_number", "code",
                 "offer_no", "date")


class AffectedRecordResolver:
    """Every active FileRelation of a file, resolved IN THIS TENANT, grouped."""

    def __init__(self, registry: FileRegistry):
        self._registry = registry
        self._tenant = registry._tenant

    async def resolve(self, file_id: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for rel in await self._registry.list_relations(file_id):
            target = m.RELATION_TARGETS[rel["relation_type"]]
            projection = {"_id": 0, "id": 1, **{f: 1 for f in _LABEL_FIELDS}}
            doc = await self._tenant.collection(target).find_one({"id": rel["record_id"]},
                                                                 projection)
            label = None
            if doc:
                label = next((str(doc[f]) for f in _LABEL_FIELDS if doc.get(f)), None)
            out.append({"relation_id": rel["id"], "relation_type": rel["relation_type"],
                        "group": AFFECTED_GROUPS[rel["relation_type"]],
                        "target_collection": target, "record_id": rel["record_id"],
                        "role": rel.get("role"), "exists": doc is not None, "label": label})
        return out

    @staticmethod
    def grouped(records: List[Mapping[str, Any]]) -> Dict[str, List[str]]:
        groups: Dict[str, List[str]] = {}
        for r in records:
            groups.setdefault(r["group"], []).append(r["record_id"])
        return {k: sorted(v) for k, v in sorted(groups.items())}


class FileIntegrityService:
    """Check one file's original at its provider; record and describe the result."""

    def __init__(self, registry: FileRegistry, storage: StorageProviderService):
        if registry.org_id != storage.org_id:
            raise ValueError("registry and storage service belong to different tenants")
        self._registry = registry
        self._storage = storage
        self.org_id = registry.org_id
        self.resolver = AffectedRecordResolver(registry)

    async def check(self, ctx, *, file_id: str, version_no: Optional[int] = None,
                    role: str = m.LOCATION_ROLE_PRIMARY,
                    idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """Run one check and return the :data:`FINDING_SCHEMA` result."""
        await authorize(ctx, "file.integrity.check", org_id=self.org_id)
        await self._registry.require_file(file_id)
        if version_no is None:
            current = await self._registry.current_version(file_id)
            if not current:
                raise FileNotFound("file %r has no version" % file_id)
            version_no = current["version_no"]
        version = await self._registry.versions.find_one(
            {"file_id": file_id, "version_no": version_no}, {"_id": 0})
        if not version:
            raise FileNotFound("no version %s of %r in this tenant" % (version_no, file_id))
        location = await self._registry.current_location(file_id, version_no, role)
        if not location:
            raise FileNotFound("no %s location for version %s of %r" % (role, version_no, file_id))

        verdict = await self._verify(location, version)
        recorded = await self._registry.record_integrity_check(
            actor_id=ctx.user_id, file_id=file_id, version_no=version_no, verdict=verdict,
            role=role, idempotency_key=idempotency_key)
        affected = await self.resolver.resolve(file_id)
        derived = await self._registry.derived.find({"file_id": file_id}, {"_id": 0}).to_list(None)
        finding_type = FINDING_TYPES.get(verdict.availability)
        owner, action = RECOVERY.get(finding_type, (None, None))
        return {
            "schema": FINDING_SCHEMA,
            "tenant_id": self.org_id,
            "file_id": file_id,
            "version_no": version_no,
            "location_id": location["id"],
            "role": role,
            "provider_kind": location["provider_kind"],
            "provider_binding_id": location["provider_binding_id"],
            "availability": verdict.availability,
            "ok": verdict.ok,
            "finding_type": finding_type,
            "severity": recorded.get("severity"),
            "checked_at": verdict.checked_at,
            "method": verdict.method,
            "expected": {"checksum": location.get("expected_checksum"),
                         "size_bytes": location.get("expected_size_bytes") or version.get(
                             "size_bytes"),
                         "provider_file_id": location.get("provider_file_id"),
                         "provider_version_id": location.get("provider_version_id")},
            "observed": {"checksum": verdict.observed_checksum,
                         "size_bytes": verdict.observed_size_bytes,
                         "provider_file_id": verdict.observed_provider_file_id,
                         "provider_version_id": verdict.observed_provider_version_id,
                         "error": verdict.error},
            "affected_records": affected,
            "affected_by_group": AffectedRecordResolver.grouped(affected),
            # Preview/cache: regenerable only from a usable original, and never
            # promoted to one, whatever it holds.
            "derived_cache": [{"derived_id": d["id"], "kind": d["kind"],
                               "source_version_no": d["source_version_no"],
                               "recoverable": bool(verdict.ok
                                                   and d["source_version_no"] == version_no),
                               "is_canonical_original": False}
                              for d in sorted(derived, key=m.sort_key)],
            "original_servable": verdict.ok,
            "treated_as_new_version": False,
            "recovery": {"owner": owner, "action": action} if finding_type else None,
            "audit_event_ids": recorded.get("audit_event_ids", []),
            # The W0-07 hand-off: a contract to consume, not a DQ record created
            # here. W0-07's runtime decides issue, owner, deadline and alarm.
            "dq_handoff": {"consumer": "W0-07", "state": "not_consumed",
                           "blocking": bool(finding_type) and bool(affected)},
        }

    async def _verify(self, location: Mapping[str, Any],
                      version: Mapping[str, Any]) -> IntegrityVerdict:
        try:
            adapter = await self._storage.adapter_for_binding(location["provider_binding_id"])
        except StorageNotActive:
            # A binding that is not active cannot be used: the original is not
            # reachable through BEG_Work right now. A configuration problem, not
            # a missing file — so it is NOT reported as missing.
            return IntegrityVerdict(availability=m.AVAILABILITY_PROVIDER_UNREACHABLE,
                                    expected_checksum=location.get("expected_checksum"),
                                    checked_at=_now(), error="BINDING_NOT_ACTIVE")
        try:
            ref = ProviderObjectRef(container=location["container"],
                                    object_key=location["object_key"],
                                    provider_file_id=location.get("provider_file_id"))
            return await adapter.verify(
                ref, location.get("expected_checksum"),
                expected_size=location.get("expected_size_bytes") or version.get("size_bytes"),
                expected_provider_file_id=location.get("provider_file_id"),
                expected_provider_version_id=location.get("provider_version_id"))
        finally:
            await adapter.aclose()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
