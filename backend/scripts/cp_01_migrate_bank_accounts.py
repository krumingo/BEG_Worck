#!/usr/bin/env python3
"""
CP-01 — migration: IBANs already stored on counterparties / subcontractors become
VerifiedBankAccount rows in status „за проверка“ (pending_verification) — NEVER
„проверена“ automatically (package §1, FLOW-010 §8.1). Dry-run by default.

    python scripts/cp_01_migrate_bank_accounts.py --mongo-url URL --db NAME            # dry run
    python scripts/cp_01_migrate_bank_accounts.py --mongo-url URL --db NAME --apply --plan-token T

* per tenant (``org_id``), idempotent: the row id is uuid5(org, party type, party id, IBAN),
  written with ``$setOnInsert`` — a second run adds nothing;
* an invalid IBAN is not migrated; it is listed in the report (masked) for a human;
* the report never prints a full IBAN or ЕГН;
* FG-226 / CP83-03: a project ``invoice_details`` ЕГН copy (person owner, or an ``egn``
  field, or a possible ЕГН without a confirmed company owner — FG-267; never a confirmed
  company's 10-digit tax id) is masked with ``--apply`` ONLY when the canonical
  ``persons`` record holds the same full ЕГН, with one AuditEvent per project; any other copy
  is kept (readers mask it) and a DQ issue „ЕГН копие без каноничен запис“ is opened.
* ``--apply`` runs only with the ``--plan-token`` its dry run printed.

Rollback: the rows carry ``source: "cp01_migration"``; deleting them is a separate,
approved operator decision (CLAUDE.md §2.9) — this script never deletes anything.
"""
import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import counterparty_rules as cr  # noqa: E402

IBAN_FIELDS = ("iban", "IBAN", "bank_iban", "bank_account", "bank_account_iban")
PARTIES = (("counterparty", "counterparties"), ("subcontractor", "subcontractors"))


def row_id(org_id: str, party_type: str, party_id: str, iban: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "beg-cp01-migration:%s:%s:%s:%s" % (
        org_id, party_type, party_id, iban)))


async def plan(db):
    report = {"to_create": [], "already_present": 0, "invalid": [], "projects_with_full_egn": 0}
    for party_type, coll in PARTIES:
        async for doc in db[coll].find({"$or": [{f: {"$nin": [None, ""]}} for f in IBAN_FIELDS]},
                                       {"_id": 0}):
            org = doc.get("org_id")
            if not org:
                continue
            for f in IBAN_FIELDS:
                raw = doc.get(f)
                if not isinstance(raw, str) or not raw.strip():
                    continue
                iban = cr.normalize_iban(raw)
                if not cr.iban_is_valid(iban):
                    report["invalid"].append({"org_id": org, "party_type": party_type,
                                              "party_id": doc.get("id"), "field": f,
                                              "iban_masked": cr.mask_iban(iban)})
                    continue
                rid = row_id(org, party_type, doc["id"], iban)
                if await db.verified_bank_accounts.find_one({"id": rid, "org_id": org}, {"_id": 1}):
                    report["already_present"] += 1
                    continue
                report["to_create"].append({"id": rid, "org_id": org, "party_type": party_type,
                                            "counterparty_id": doc["id"], "iban": iban, "field": f})
    report["projects_to_mask"], report["egn_copies_without_canonical"] = [], []
    async for p in db.projects.find({"invoice_details": {"$type": "object"}},
                                    {"_id": 0, "id": 1, "org_id": 1, "owner_type": 1, "owner_id": 1,
                                     "invoice_details": 1}):
        # FG-267 (pass 28): a company only when its record exists in the same tenant
        company_ok = bool(p.get("owner_type") == "company" and p.get("owner_id") and
                          await db.companies.find_one({"id": p["owner_id"], "org_id": p.get("org_id")},
                                                      {"_id": 1}))
        fields = cr.egn_copy_fields(p["invoice_details"], p.get("owner_type"), p.get("owner_id"),
                                    company_confirmed=company_ok)
        if not fields:
            continue
        report["projects_with_full_egn"] += 1
        person = None
        if p.get("owner_type") == "person" and p.get("owner_id"):
            person = await db.persons.find_one({"id": p["owner_id"], "org_id": p.get("org_id")},
                                               {"_id": 0, "egn": 1})
        # CP83-03 (CLAUDE.md §2): mask only a REDUNDANT copy — the canonical persons record,
        # under its access control, holds the same full ЕГН. Anything else is kept and
        # reported to the Accountant as a DQ issue; the readers mask it on read.
        redundant = [f for f in fields
                     if person and cr.same_egn(p["invoice_details"][f], person.get("egn"))]
        rest = [f for f in fields if f not in redundant]
        if redundant:
            report["projects_to_mask"].append({
                "id": p["id"], "org_id": p.get("org_id"), "fields": redundant,
                "before": p["invoice_details"],
                "after": cr.mask_invoice_details(p["invoice_details"], p.get("owner_type"), redundant)})
        if rest:
            report["egn_copies_without_canonical"].append({"id": p["id"], "org_id": p.get("org_id"),
                                                           "fields": rest})
    return report


def plan_token(report) -> str:
    """The dry run's fingerprint: --apply runs only the plan a human has just seen."""
    import hashlib
    return hashlib.sha256(json.dumps(printable(report), sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()[:16]


async def _audit_mask(db, p):
    """One canonical AuditEvent per masked project (FLOW-040), masked values only."""
    from app.audit.envelope import ACTOR_SYSTEM, RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    event = build_event(
        tenant_id=p["org_id"], actor_type=ACTOR_SYSTEM, actor_id="cp01_migration",
        action="project.invoice_details.egn_copy_masked", source_flow="FLOW-040",
        retention_class=RETENTION_R1_CRITICAL_BUSINESS, entity_type="project", entity_id=p["id"],
        reason="ЕГН копие — каноничното ЕГН е в persons (R48.3, CP83-03)",
        structured_diff={f: {"before": cr.mask_egn(p["before"][f]), "after": p["after"][f],
                             "canonical": "persons"} for f in p["fields"]},
        source_channel="migration")
    await record_event(db, event)


async def apply(db, report):
    now = datetime.now(timezone.utc).isoformat()
    written = 0
    for r in report["to_create"]:
        doc = {"id": r["id"], "org_id": r["org_id"], "party_type": r["party_type"],
               "counterparty_id": r["counterparty_id"], "iban": r["iban"], "status": cr.BA_PENDING,
               "is_change": False, "replaces_account_id": None, "evidence_file_ids": [],
               "entered_by": "cp01_migration", "entered_at": now, "verification": None,
               "approvals": [], "version": 1, "source": "cp01_migration",
               "migrated_from_field": r["field"], "created_at": now, "updated_at": now}
        res = await db.verified_bank_accounts.update_one({"id": r["id"], "org_id": r["org_id"]},
                                                         {"$setOnInsert": doc}, upsert=True)
        written += 1 if res.upserted_id is not None else 0
    for p in report.get("projects_to_mask", []):
        # compare-and-set on the value read: a project edited meanwhile is left for the next run
        res = await db.projects.update_one(
            {"id": p["id"], "org_id": p["org_id"], "invoice_details": p["before"]},
            {"$set": {"invoice_details": p["after"], "egn_masked_by": "cp01_migration"}})
        if res.modified_count:
            await _audit_mask(db, p)
            written += 1
    from app.services.master_write import dq_issue
    from app.tenancy.data_access import TenantData
    for p in report.get("egn_copies_without_canonical", []):
        await dq_issue(TenantData.for_resolved_org(db, p["org_id"]), None,
                       code="EGN_COPY_WITHOUT_CANONICAL", severity="warning",
                       entity_type="project", entity_id=p["id"],
                       message="ЕГН копие без каноничен запис", data={"fields": p["fields"]},
                       created_by="cp01_migration")
    return written


def printable(report):
    out = dict(report)
    out["to_create"] = [dict({k: v for k, v in r.items() if k != "iban"},
                             iban_masked=cr.mask_iban(r["iban"])) for r in report["to_create"]]
    out["projects_to_mask"] = [{"id": p["id"], "org_id": p["org_id"], "fields": p["fields"]}
                               for p in report.get("projects_to_mask", [])]
    return out


async def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mongo-url", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--plan-token", default=None,
                    help="the plan_token printed by the dry run; --apply refuses without it")
    args = ap.parse_args(argv)
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(args.mongo_url, serverSelectionTimeoutMS=5000)
    db = client[args.db]
    report = await plan(db)
    token = plan_token(report)
    result = {"mode": "apply" if args.apply else "dry-run", "plan_token": token, **printable(report)}
    if args.apply:
        if args.plan_token != token:
            # CP83-03: dry run first — apply only the plan that was just reviewed
            print(json.dumps({"refused": "run the dry run first and pass its --plan-token",
                              "plan_token_now": token}, ensure_ascii=False))
            client.close()
            return {"refused": True, "plan_token": token}
        result["written"] = await apply(db, report)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    client.close()
    return result


if __name__ == "__main__":
    asyncio.run(main())
