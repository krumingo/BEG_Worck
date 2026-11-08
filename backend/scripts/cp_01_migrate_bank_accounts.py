#!/usr/bin/env python3
"""
CP-01 — migration: IBANs already stored on counterparties / subcontractors become
VerifiedBankAccount rows in status „за проверка“ (pending_verification) — NEVER
„проверена“ automatically (package §1, FLOW-010 §8.1). Dry-run by default.

    python scripts/cp_01_migrate_bank_accounts.py --mongo-url URL --db NAME            # dry run
    python scripts/cp_01_migrate_bank_accounts.py --mongo-url URL --db NAME --apply    # write

* per tenant (``org_id``), idempotent: the row id is uuid5(org, party type, party id, IBAN),
  written with ``$setOnInsert`` — a second run adds nothing;
* an invalid IBAN is not migrated; it is listed in the report (masked) for a human;
* the report never prints a full IBAN or ЕГН;
* FG-226: project ``invoice_details`` that still hold a full ЕГН copied before CP-01 are
  reported, and with ``--apply`` masked (``******1234``) — the original stays in ``persons``.

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
    report["projects_to_mask"] = []
    async for p in db.projects.find({"invoice_details": {"$type": "object"}},
                                    {"_id": 0, "id": 1, "org_id": 1, "owner_type": 1, "invoice_details": 1}):
        masked = mask_invoice_details(p["invoice_details"], p.get("owner_type"))
        if masked != p["invoice_details"]:
            report["projects_with_full_egn"] += 1
            report["projects_to_mask"].append({"id": p["id"], "org_id": p.get("org_id"),
                                               "before": p["invoice_details"], "after": masked})
    return report


def mask_invoice_details(details, owner_type):
    """The same rule as the project readers/writers (FG-226): a person's ЕГН in
    ``invoice_details`` is a copy — the original stays in ``persons``."""
    import re
    out = dict(details)
    for field in ("eik", "egn", "tax_id"):
        value = out.get(field)
        if not value or str(value).startswith(cr.EGN_MASK_PREFIX):
            continue
        digits = re.sub(r"\D", "", str(value))
        if field == "egn" or owner_type == "person" or len(digits) == 10:
            out[field] = cr.mask_egn(value)
    return out


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
        written += res.modified_count
    return written


def printable(report):
    out = dict(report)
    out["to_create"] = [dict({k: v for k, v in r.items() if k != "iban"},
                             iban_masked=cr.mask_iban(r["iban"])) for r in report["to_create"]]
    out["projects_to_mask"] = [{"id": p["id"], "org_id": p["org_id"]}
                               for p in report.get("projects_to_mask", [])]
    return out


async def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mongo-url", required=True)
    ap.add_argument("--db", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args(argv)
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(args.mongo_url, serverSelectionTimeoutMS=5000)
    db = client[args.db]
    report = await plan(db)
    result = {"mode": "apply" if args.apply else "dry-run", **printable(report)}
    if args.apply:
        result["written"] = await apply(db, report)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    client.close()
    return result


if __name__ == "__main__":
    asyncio.run(main())
