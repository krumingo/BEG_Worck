#!/usr/bin/env python3
"""
W0-03E — legacy migration dry run, reconciliation and advance mapping report.

A DEVELOPMENT / OPERATIONS tool, READ-ONLY. Never imported by the application.

Runs against a restored copy on a LOCAL MongoDB only (the W0-03C local-only
guard: no Atlas, no NAS, no ``mongodb+srv``). The database handle is wrapped so
that any write method raises before it reaches the server; the report proves
by construction that it wrote nothing. It never executes a migration — that is
an approval-bound operation of the application (W0-07).

Usage:
    python scripts/w0_03e_legacy_migration_report.py --mongo-url mongodb://127.0.0.1:27017 \
        --db begwork_restored --tenant-id <tenant id> --org-id <legacy org id> [--sources users,persons] \
        [--out report.json]

Output (JSON): the deterministic plan with personal identifiers masked, its
``plan_token``, the reconciliation counts (zero lost references or not) and the
"advances needing manual mapping" report (proposals only; ``auto_mapped`` is 0).
Exit 0 when the report was produced; 2 when the target was refused.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.master_data import index_bootstrap as ib  # noqa: E402

WRITE_METHODS = ("insert_one", "insert_many", "update_one", "update_many", "replace_one",
                 "delete_one", "delete_many", "find_one_and_update", "find_one_and_delete",
                 "find_one_and_replace", "bulk_write", "create_index", "create_indexes",
                 "drop", "drop_index", "drop_indexes", "rename")


class ReadOnlyDb:
    """Refuses every write method before it reaches the server."""

    def __init__(self, db):
        self._db = db

    def __getitem__(self, name):
        return _ReadOnlyColl(self._db[name], name)

    @property
    def name(self):
        return self._db.name


class _ReadOnlyColl:
    def __init__(self, coll, name):
        self._coll, self._name = coll, name

    def __getattr__(self, attr):
        if attr in WRITE_METHODS:
            raise PermissionError("read-only report: %s.%s refused" % (self._name, attr))
        return getattr(self._coll, attr)


class _Ctx:
    enforced = True

    def __init__(self, tenant_id, org_id, db):
        self.tenant_id, self.org_id, self.user_id, self._db = tenant_id, org_id, "report", db

    async def db(self, require_operational=False):
        return self._db


class _Repo:
    def __init__(self, db):
        self._db = db

    async def db(self):
        return self._db


async def build_report(db, tenant_id, org_id, sources=None):
    from app.master_data import legacy_adapter, legacy_migration, legacy_plan
    ro = ReadOnlyDb(db)
    ctx, repo = _Ctx(tenant_id, org_id, ro), _Repo(ro)
    plan = await legacy_plan.plan(ctx, sources=sources, mode="enforce", repository=repo)
    reconciliation = await legacy_migration.reconcile(ctx, sources=sources, mode="enforce",
                                                      repository=repo)
    advances = await legacy_adapter.advance_mapping_report(ro, tenant_id=tenant_id, org_id=org_id)
    return {"schema": "beg.master-data-legacy-migration-report/v1", "read_only": True,
            "database": db.name, "plan": plan, "reconciliation": reconciliation,
            "advances": advances}


def build_parser():
    p = argparse.ArgumentParser(description="W0-03E read-only legacy migration report")
    p.add_argument("--mongo-url", required=True, help="a LOCAL mongodb:// server")
    p.add_argument("--db", required=True, help="the restored copy's database name")
    p.add_argument("--tenant-id", required=True)
    p.add_argument("--org-id", required=True, help="the tenant's legacy org_id (registry mapping)")
    p.add_argument("--sources", default="", help="comma-separated legacy collections")
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
            return await build_report(client[args.db], args.tenant_id, args.org_id,
                                      [s for s in args.sources.split(",") if s] or None)
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
