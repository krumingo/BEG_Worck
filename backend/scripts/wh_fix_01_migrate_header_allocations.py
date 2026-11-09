#!/usr/bin/env python3
"""
WH-FIX-01 Addendum A4 #11 (Р45) — migrate legacy HEADER-allocated invoices of
ONE tenant to line allocations.

  * one header destination → written explicitly on every unallocated line
    (canonical AuditEvent per line, one transaction per invoice);
  * a split / percentage header → left „чака разпределение" and the DQ issue
    is opened for the Accountant (A3 #7).

Idempotent (an allocated line is never touched; a second run writes nothing),
per tenant, never deletes. Rollback = the reverse correction from the
AuditEvents (`finance.invoice_line.allocation_corrected`, before = []).

    cd backend && PYTHONPATH=. python scripts/wh_fix_01_migrate_header_allocations.py \
        --tenant <org_id> --actor <user_id> [--apply]

Without --apply it is a DRY RUN: it prints the report and writes nothing.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys


async def _main(tenant_id: str, actor_id: str, apply: bool) -> dict:
    from app.db import db
    from app.services.invoice_allocation import migrate_header_allocations
    from app.tenancy.data_access import TenantData
    tenant = TenantData.for_resolved_org(db, tenant_id)
    actor = await db["users"].find_one({"id": actor_id, "org_id": tenant_id},
                                       {"_id": 0, "id": 1, "role": 1, "org_id": 1})
    if not actor:
        raise SystemExit("actor %r is not a user of tenant %r" % (actor_id, tenant_id))
    if actor.get("role") not in ("Owner", "Admin", "Accountant"):
        raise SystemExit("actor must be Owner / Admin / Accountant (Р14 / Р20)")
    return await migrate_header_allocations(tenant, tenant_id, actor, dry_run=not apply)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--actor", required=True, help="the finance user the AuditEvents name")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = ap.parse_args(argv)
    report = asyncio.run(_main(args.tenant, args.actor, args.apply))
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
