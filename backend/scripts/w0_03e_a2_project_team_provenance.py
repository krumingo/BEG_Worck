#!/usr/bin/env python3
"""
W0-03E-A2 — ``project_team`` tenant-provenance dry run. READ-ONLY.

A DEVELOPMENT / OPERATIONS tool. Never imported by the application, and it
executes nothing: the database handle refuses every write method before it
reaches the server, so the report proves by construction that it wrote nothing.
No live or production migration happens here, and none is authorized by it.

Runs against a restored copy on a LOCAL MongoDB only (the W0-03C local-only
guard: no Atlas, no NAS, no ``mongodb+srv``).

What it answers. ``project_team`` is a tenant-bound authorization relation
(``app.tenancy.project_team``), but the legacy rows predate the tenant key. For
each row this report says whether its tenant is **PROVEN_TENANT** or
**UNRESOLVED_PROVENANCE**, and why. The only evidence accepted for a
deterministic backfill is that the row's SOURCE DATABASE is provably
single-tenant, verified against the W0-01 Tenant Registry — see
``verify_source_provenance``. Nothing is inferred from a project id, a user id,
a name, a role or a coincident record: two tenants in one shared legacy
database can have all of those equal, which is the collision that blocked A1.

An UNRESOLVED row keeps no tenant and therefore authorizes nothing: the tenant
predicate simply does not match it. The deny side needs no queue — it is already
fail-closed — so this report never has to write anywhere to be safe.

Usage:
    python scripts/w0_03e_a2_project_team_provenance.py \
        --mongo-url mongodb://127.0.0.1:27017 --db begwork_restored \
        [--system-db begwork_system] [--out report.json]

Exit 0 when the report was produced, 2 when the target was refused.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.master_data import index_bootstrap as ib  # noqa: E402
from app.tenancy import project_team as pt  # noqa: E402
from app.tenancy.data_access import TENANT_KEY  # noqa: E402
from scripts.w0_03e_legacy_migration_report import ReadOnlyDb  # noqa: E402

#: Collections whose documents carry the legacy tenant key. Their distinct
#: ``org_id`` values are what makes a source database provably single-tenant
#: (or proves it is not). ``project_team`` is NOT among them: the question is
#: who owns its rows, so it cannot be its own evidence.
TENANT_KEYED_COLLECTIONS = (
    "projects", "clients", "companies", "users", "warehouses", "invoices",
    "counterparties", "persons", "finance_payments", "payment_allocations",
    "financial_accounts", "offers", "subcontractors",
)


async def observed_org_ids(ro_db, collections=TENANT_KEYED_COLLECTIONS):
    """Every distinct non-empty ``org_id`` actually present in the source."""
    seen = set()
    for name in collections:
        for value in await ro_db[name].distinct(TENANT_KEY):
            if isinstance(value, str) and value:
                seen.add(value)
    return sorted(seen)


async def registry_claims(ro_system_db, database: str):
    """The Tenant Registry records that name ``database`` as their own.

    Read from the SEPARATE system database (W0-01): the registry is never
    inside a tenant's operational database.
    """
    return await ro_system_db["tenant_registry"].find(
        {"database_name": database}, {"_id": 0}).to_list(100)


def dq_representation():
    """Can the existing DQ/pending mapping hold an unresolved provenance row?

    Checked against the real model rather than assumed, because the A2
    assignment says to STOP with the exact blocker instead of inventing a new
    approval flow. It cannot, for three independent reasons, each a deliberate
    invariant of ``app/master_data/pending.py`` that A2 must not weaken.
    """
    from app.master_data import models
    from app.master_data import pending
    blockers = []
    # (1) tenant_id is mandatory — and it is the very unknown.
    try:
        pending.build_pending(tenant_id="", entity_type=models.ENTITY_PERSON,
                              raw_value="x", source_channel=pending.SOURCE_IMPORT,
                              created_by="report")
    except Exception as exc:                                        # noqa: BLE001
        blockers.append({
            "invariant": "md_pending_mapping.tenant_id is required",
            "refusal": str(exc),
            "why_it_blocks": "an UNRESOLVED_PROVENANCE row has no known tenant; "
                             "supplying one would be the guess A2 forbids, and "
                             "supplying a placeholder would put a row of unknown "
                             "ownership inside one tenant's queue"})
    # (2) entity_type is one of the FLOW-032 Master Data types; a membership is
    #     an authorization relation, not a Master Data entity.
    if "project_team_membership" not in models.ENTITY_TYPES:
        blockers.append({
            "invariant": "md_pending_mapping.entity_type is one of %s"
                         % ", ".join(sorted(models.ENTITY_TYPES)),
            "refusal": "no entity_type represents an authorization relation",
            "why_it_blocks": "project_team membership is not a Master Data entity; "
                             "adding a type would change the FLOW-032 Master Data "
                             "model, which is a locked business decision"})
    # (3) source_channel is an automated proposal channel; a legacy row is none.
    if not (pending.PENDING_SOURCES & {"legacy", "migration"}):
        blockers.append({
            "invariant": "md_pending_mapping.source_channel is one of %s"
                         % ", ".join(sorted(pending.PENDING_SOURCES)),
            "refusal": "a legacy row's provenance is not an ai/ocr/excel/import proposal",
            "why_it_blocks": "the pending model exists so automated channels may "
                             "propose Master Data; it does not model an unowned "
                             "authorization row"})
    return {
        "collection": pending.PENDING_COLLECTION,
        "can_represent_unresolved_provenance": not blockers,
        "blockers": blockers,
        "consequence": "This report records UNRESOLVED_PROVENANCE rows and writes "
                       "nothing. The authorization outcome is unaffected and already "
                       "safe: an unresolved row carries no tenant, so the tenant "
                       "predicate never matches it and it authorizes nothing (deny, "
                       "fail closed). What is missing is only the human WORKLIST "
                       "record. A2 does not invent one — that is an architectural "
                       "decision for GPT/Krum (see HANDOFF).",
    }


async def build_report(db, system_db, *, collections=TENANT_KEYED_COLLECTIONS):
    """The whole read-only provenance report for one source database."""
    ro, ro_sys = ReadOnlyDb(db), ReadOnlyDb(system_db)
    observed = await observed_org_ids(ro, collections)
    claims = await registry_claims(ro_sys, db.name)
    provenance = pt.verify_source_provenance(db.name, claims, observed)
    rows = await ro[pt.COLLECTION].find({}, {"_id": 0}).to_list(None)
    classified = pt.classify_rows(rows, provenance)
    counts = classified["counts"]
    return {
        "schema": "beg.project-team-tenant-provenance/v1",
        "task": "W0-03E-A2",
        "read_only": True,
        "executed_migration": False,
        "database": db.name,
        "system_database": system_db.name,
        "registry_claims": [{"id": c.get("id"), "legacy_org_id": c.get("legacy_org_id"),
                             "database_name": c.get("database_name"),
                             "status": c.get("status")} for c in claims],
        "provenance": classified["provenance"],
        "counts": counts,
        "reasons": classified["reasons"],
        "decisions": classified["decisions"],
        # The plan a migration WOULD apply. Deterministic, and only ever the
        # row's own proven source tenant. Empty whenever provenance is not proven.
        "backfill_plan": [{"id": d["id"], TENANT_KEY: d["backfill"]}
                          for d in classified["decisions"] if d["backfill"]],
        "dq_pending_mapping": dq_representation(),
        "authorization_effect": (
            "%d row(s) carry a proven tenant and authorize only that tenant. "
            "%d row(s) are UNRESOLVED_PROVENANCE: they keep no tenant, so every "
            "tenant-scoped membership query misses them and they authorize nothing."
            % (counts["proven"], counts["unresolved"])),
    }


def build_parser():
    p = argparse.ArgumentParser(
        description="W0-03E-A2 read-only project_team tenant-provenance dry run")
    p.add_argument("--mongo-url", required=True, help="a LOCAL mongodb:// server")
    p.add_argument("--db", required=True, help="the restored copy's database name")
    p.add_argument("--system-db", default="begwork_system",
                   help="the Tenant Registry's system database (W0-01)")
    p.add_argument("--out", default="")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    from scripts.w0_03c_master_data_uniqueness import parse_mongo_url
    try:
        scheme, hosts = parse_mongo_url(args.mongo_url)
        ib.check_local(hosts=hosts, scheme=scheme)
    except (ib.TargetRefused, ValueError) as exc:
        print("refused: %s" % exc, file=sys.stderr)
        return 2
    from motor.motor_asyncio import AsyncIOMotorClient

    async def run():
        client = AsyncIOMotorClient(args.mongo_url, serverSelectionTimeoutMS=5000)
        try:
            return await build_report(client[args.db], client[args.system_db])
        finally:
            client.close()
    report = asyncio.run(run())
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
