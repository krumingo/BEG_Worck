#!/usr/bin/env python3
"""
R0-01 — billing exposure report (AUD-009 / AUD-045). READ-ONLY, dry run only.

What it answers. Before R0-01, ``/billing/create-checkout-session`` upgraded a
plan without payment whenever Stripe keys were missing (mock mode switched on
by itself), and ``/billing/webhook`` accepted unsigned JSON when
``STRIPE_WEBHOOK_SECRET`` was missing. This report lists what those paths may
have left behind, so Krum can decide on any correction (step 1.9) from facts:

* ``mock_subscriptions`` — subscriptions whose ``stripe_subscription_id`` is
  ``mock_sub_*`` (or ``stripe_customer_id`` is ``mock_cus_*``): written only by
  the mock checkout.
* ``checkout_mock_audit`` — ``audit_logs`` rows with action ``checkout_mock``.
* ``unverified_paid_plan_candidates`` — subscriptions on a paid plan with a
  real-looking Stripe subscription id and NO ``checkout_started`` audit row for
  that organization. The old unsigned webhook wrote no record of its own, so
  this is a candidate list ("a paid plan BEG_Work never saw a checkout for"),
  not proof of a forged event.

It never writes. There is no apply mode. The database handle is wrapped in an
ALLOWLIST (R0-01-C01 F-06): only ``find``, ``find_one``, ``count_documents``,
``distinct``, ``aggregate``, ``list_indexes`` and ``list_collection_names``
reach the server; every other attribute raises before it does. ``aggregate``
refuses any pipeline that contains ``$out`` or ``$merge`` at any depth.
``build_report`` itself contains no write call (the A2C guard proves it —
READ_ONLY_DIAGNOSTIC). No e-mail addresses, secrets or connection strings are
printed.

The wrapper is the inner boundary. The OUTER boundary for any non-local run is
the credential: connect with a MongoDB user that has only the ``read`` role on
the target database, so that even a defect in this script cannot write.

Running it against PRODUCTION needs Krum's approval (R0-01 step 1.0) and that
read-only user. A non-local target is refused unless ``--allow-remote`` is
given.

Usage:
    python scripts/r0_01_billing_exposure_report.py --db begwork [--mongo-url URL] \
        [--allow-remote] [--out report.json]

``--mongo-url`` defaults to the ``MONGO_URL`` environment variable.
Exit 0 = report produced; 2 = target refused or not given.
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

#: The only collection methods that reach the server. Everything else is refused.
READ_METHODS = frozenset({"find", "find_one", "count_documents", "distinct", "aggregate",
                          "list_indexes"})
#: Aggregation stages that write. Refused wherever they appear in a pipeline.
WRITE_STAGES = frozenset({"$out", "$merge"})

PAID_PLAN_IDS = ("pro", "enterprise")
ROW_LIMIT = 10000


class ReadOnlyDb:
    """Hands out read-only collection proxies; nothing else of the database."""

    def __init__(self, db):
        self._db = db

    def __getitem__(self, name):
        return _ReadOnlyColl(self._db[name], name)

    def __getattr__(self, attr):
        raise PermissionError("read-only report: database attribute %r refused" % attr)

    @property
    def name(self):
        return self._db.name

    async def list_collection_names(self):
        return await self._db.list_collection_names()


def _write_stage_in(node) -> bool:
    """True when ``$out``/``$merge`` appears anywhere inside a pipeline value."""
    if isinstance(node, dict):
        return any(k in WRITE_STAGES or _write_stage_in(v) for k, v in node.items())
    if isinstance(node, (list, tuple)):
        return any(_write_stage_in(v) for v in node)
    return False


class _ReadOnlyColl:
    """Allowlist proxy: only READ_METHODS reach the collection."""

    def __init__(self, coll, name):
        self._coll, self._name = coll, name

    def __getattr__(self, attr):
        if attr not in READ_METHODS:
            raise PermissionError("read-only report: %s.%s refused" % (self._name, attr))
        if attr == "aggregate":
            return self._aggregate
        return getattr(self._coll, attr)

    def _aggregate(self, pipeline, *args, **kwargs):
        if _write_stage_in(pipeline):
            raise PermissionError("read-only report: %s.aggregate with $out/$merge refused"
                                  % self._name)
        return self._coll.aggregate(pipeline, *args, **kwargs)


def _sub_row(doc):
    return {k: doc.get(k) for k in ("org_id", "plan_id", "status", "stripe_customer_id",
                                    "stripe_subscription_id", "current_period_end", "updated_at")}


async def build_report(db):
    """Everything the report says, read through a write-refusing handle."""
    ro = ReadOnlyDb(db)
    subs, audit = ro["subscriptions"], ro["audit_logs"]

    mock_subs = await subs.find(
        {"$or": [{"stripe_subscription_id": {"$regex": "^mock_sub_"}},
                 {"stripe_customer_id": {"$regex": "^mock_cus_"}}]},
        {"_id": 0}).to_list(ROW_LIMIT)

    mock_audit = await audit.find({"action": "checkout_mock"}, {"_id": 0}).to_list(ROW_LIMIT)

    started_orgs = set(await audit.distinct("org_id", {"action": "checkout_started"}))
    paid = await subs.find(
        {"plan_id": {"$in": list(PAID_PLAN_IDS)},
         "stripe_subscription_id": {"$nin": [None, ""], "$not": {"$regex": "^mock_sub_"}}},
        {"_id": 0}).to_list(ROW_LIMIT)
    candidates = [d for d in paid if d.get("org_id") not in started_orgs]

    return {
        "schema": "beg.r0-01-billing-exposure-report/v1",
        "read_only": True,
        "dry_run": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": db.name,
        "counts": {
            "mock_subscriptions": len(mock_subs),
            "checkout_mock_audit": len(mock_audit),
            "unverified_paid_plan_candidates": len(candidates),
        },
        "mock_subscriptions": [_sub_row(d) for d in mock_subs],
        "checkout_mock_audit": [
            {"org_id": d.get("org_id"), "user_id": d.get("user_id"),
             "session_id": d.get("entity_id"),
             "plan_id": (d.get("changes") or {}).get("plan_id"),
             "timestamp": d.get("timestamp")}
            for d in mock_audit],
        "unverified_paid_plan_candidates": [_sub_row(d) for d in candidates],
        "notes": [
            "The pre-R0-01 unsigned webhook stored no record of its own; "
            "unverified_paid_plan_candidates is a candidate list, not proof.",
            "No correction is made here. Any fix is a separate, approved step (R0-01 step 1.9).",
        ],
    }


def build_parser():
    p = argparse.ArgumentParser(description="R0-01 read-only billing exposure report")
    p.add_argument("--mongo-url", default="", help="defaults to $MONGO_URL; never printed")
    p.add_argument("--db", required=True, help="database name")
    p.add_argument("--allow-remote", action="store_true",
                   help="allow a non-local server (production needs Krum's approval)")
    p.add_argument("--out", default="")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    url = args.mongo_url or os.environ.get("MONGO_URL", "")
    if not url:
        print("refused: no --mongo-url and no MONGO_URL", file=sys.stderr)
        return 2
    if not args.allow_remote:
        from app.master_data import index_bootstrap as ib
        from scripts.w0_03c_master_data_uniqueness import parse_mongo_url
        try:
            scheme, hosts = parse_mongo_url(url)
            ib.check_local(hosts=hosts, scheme=scheme)
        except (ib.TargetRefused, ValueError) as exc:
            print("refused: %s (use --allow-remote only with approval)" % exc, file=sys.stderr)
            return 2
    from motor.motor_asyncio import AsyncIOMotorClient

    async def run():
        client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=5000)
        try:
            return await build_report(client[args.db])
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
