"""
INV-CN-01 Addendum A — the one-off, idempotent data/index migration (FG-217, Р49(1)).

Dry run by default (``plan``): a read-only report, nothing written. ``apply`` (after the
Owner's approval of that exact report — CLAUDE.md §8, critical migration):

  1. FG-217: an outgoing or incoming DRAFT whose ``invoice_no`` is null / "" loses the
     field (a draft has no number);
  2. Р49(1): a LEGACY outgoing draft that already carries a number (numbered at creation
     before INV-CN-01) becomes ``Issued`` — locked — with ``issued_number`` and a
     canonical AuditEvent per invoice (``finance.invoice.issued_by_migration``);
  3. FG-217: the legacy unique+sparse ``(org_id, invoice_no)`` index (it indexes a
     missing number as null) is dropped and the partial index of OUR series is built;
  4. FG-231 / Р53(1): every supplier invoice gets ``supplier_key`` (ЕИК, else the
     counterparty record, else the name) and the per-supplier unique index is built —
     two suppliers may use the same number, the same supplier may not. Rows that would
     collide are listed by the dry run and ``apply`` refuses until they are resolved.

Running it again finds nothing to do (each step is conditional). Rollback: the report
lists every invoice id changed; the status can be put back to Draft from it, and the
legacy index re-created — both need the same approval.
"""
from __future__ import annotations

from typing import Dict, List

from app.services import invoice_corrections as ic
from app.tenancy.data_access import TenantData, all_tenant_ids

LEGACY_INDEX_KEY = {"org_id": 1, "invoice_no": 1}
MIGRATION_ACTION = "finance.invoice.issued_by_migration"


def _is_legacy_index(spec: dict) -> bool:
    key = dict(spec.get("key") or [])
    return key == LEGACY_INDEX_KEY and bool(spec.get("unique")) and not spec.get("partialFilterExpression")


async def plan(database) -> Dict:
    """Read-only report: what ``apply`` would change (per tenant), and the index state."""
    indexes = await database.invoices.index_information()
    legacy = sorted(n for n, spec in indexes.items()
                    if _is_legacy_index(spec) or n in ic.SUPERSEDED_INDEX_NAMES)
    targets = [ic.INVOICE_NO_INDEX[2]["name"], ic.SUPPLIER_NO_INDEX[2]["name"]]
    tenants: List[Dict] = []
    for org_id in await all_tenant_ids(database):
        tenant = TenantData.for_resolved_org(database, org_id)
        empty = await tenant.invoices.find(
            {"status": ic.DRAFT, "invoice_no": {"$exists": True, "$in": [None, ""]}},
            {"_id": 0, "id": 1}).to_list(None)
        numbered = await tenant.invoices.find(
            {"status": ic.DRAFT, "direction": "Issued", "invoice_no": {"$gt": ""}},
            {"_id": 0, "id": 1, "invoice_no": 1, "total": 1, "created_at": 1}).to_list(None)
        keys, seen, conflicts, no_tax_id = [], {}, [], []
        async for inv in tenant.invoices.find({"direction": "Received"},
                                              {"_id": 0, "id": 1, "invoice_no": 1, "supplier_key": 1,
                                               "counterparty_eik": 1, "counterparty_name": 1,
                                               "supplier_counterparty_id": 1,
                                               "counterparty_foreign_tax_no": 1}):
            key = ic.supplier_key(inv)
            if ic.supplier_tax_id_refusal(inv) is not None and not await tenant.dq_issues.find_one(
                    {"id": ic.dq_issue_id(ic.DQ_SUPPLIER_TAX_ID_MISSING, inv["id"]), "status": "open"},
                    {"_id": 0, "id": 1}):
                no_tax_id.append(inv["id"])                       # Р55(1): DQ to the Accountant
            if inv.get("supplier_key") != key:
                keys.append({"id": inv["id"], "supplier_key": key})
            if isinstance(inv.get("invoice_no"), str) and inv["invoice_no"].strip():
                ident = (key, inv["invoice_no"])
                if ident in seen:
                    conflicts.append({"supplier_key": key, "invoice_no": inv["invoice_no"],
                                      "ids": [seen[ident], inv["id"]]})
                seen.setdefault(ident, inv["id"])
        if empty or numbered or keys or conflicts or no_tax_id:
            tenants.append({"org_id": org_id,
                            "drafts_number_removed": [d["id"] for d in empty],
                            "legacy_numbered_drafts_to_issue": numbered,
                            "supplier_keys_to_set": keys, "supplier_conflicts": conflicts,
                            "supplier_tax_id_missing": no_tax_id})
    missing = [n for n in targets if n not in indexes]
    return {"legacy_index": legacy, "target_indexes": targets, "missing_indexes": missing,
            "tenants": tenants,
            "supplier_conflicts": sum(len(t["supplier_conflicts"]) for t in tenants),
            "changes": sum(len(t["drafts_number_removed"]) + len(t["legacy_numbered_drafts_to_issue"])
                           + len(t["supplier_keys_to_set"]) + len(t["supplier_tax_id_missing"])
                           for t in tenants)
            + len(legacy) + len(missing)}


async def apply(database, *, actor_id: str) -> Dict:
    """Perform the plan. Idempotent: every write is conditioned on the state it changes."""
    from app.audit.envelope import ACTOR_SYSTEM, RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    report = await plan(database)
    if report["supplier_conflicts"]:
        raise RuntimeError("the same supplier + number exists twice — resolve the rows listed by "
                           "the dry run (supplier_conflicts) first; nothing was changed")
    now = ic.now_iso()
    for t in report["tenants"]:
        tenant = TenantData.for_resolved_org(database, t["org_id"])
        if t["drafts_number_removed"]:
            await tenant.invoices.update_many(
                {"id": {"$in": t["drafts_number_removed"]}, "status": ic.DRAFT,
                 "invoice_no": {"$exists": True, "$in": [None, ""]}}, {"$unset": {"invoice_no": ""}})
        for inv_id in t["supplier_tax_id_missing"]:
            # Р55(1) / FG-249: a legacy supplier invoice without ЕИК / tax number → one
            # canonical dq_issues record for the Accountant (idempotent, deterministic id)
            await ic.open_dq_issue(tenant, dq_type=ic.DQ_SUPPLIER_TAX_ID_MISSING,
                                   entity_type="invoice", entity_id=inv_id,
                                   actor={"id": actor_id},
                                   details={"source": "inv_cn_01_migrate"})
        for row in t["supplier_keys_to_set"]:
            await tenant.invoices.update_one({"id": row["id"], "direction": "Received"},
                                             {"$set": {"supplier_key": row["supplier_key"]}})
        for inv in t["legacy_numbered_drafts_to_issue"]:
            res = await tenant.invoices.update_one(
                {"id": inv["id"], "status": ic.DRAFT, "invoice_no": inv["invoice_no"]},
                {"$set": {"status": ic.ISSUED, "issued_number": inv["invoice_no"],
                          "issued_at": inv.get("created_at") or now, "issued_by": actor_id,
                          "issued_by_migration": True, "updated_at": now}})
            if res.modified_count == 1:
                await record_event(database, build_event(
                    tenant_id=t["org_id"], actor_type=ACTOR_SYSTEM, actor_id=actor_id,
                    action=MIGRATION_ACTION, source_flow="FLOW-006",
                    retention_class=RETENTION_R1_CRITICAL_BUSINESS, entity_type="finance.invoice",
                    entity_id=inv["id"], reason="INV-CN-01 Р49(1): номерирана чернова = издадена",
                    structured_diff={"status": {"before": ic.DRAFT, "after": ic.ISSUED},
                                     "invoice_no": inv["invoice_no"]},
                    effective_role_assignments=["migration"], source_channel="migration"))
    for name in report["legacy_index"]:
        await database.invoices.drop_index(name)
    for _, keys, opts in (ic.INVOICE_NO_INDEX, ic.SUPPLIER_NO_INDEX):
        await database.invoices.create_index(keys, **opts)
    return report
