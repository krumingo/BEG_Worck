#!/usr/bin/env python3
"""
W0-03C — Master Data uniqueness: duplicate report, index bootstrap, rollback.

A DEVELOPMENT / OPERATIONS tool. Never imported by the application.

  report     read-only; names exactly the records that block each planned unique index
  bootstrap  dry run by default; ``--apply`` builds the indexes only after a fresh clean
             report, and only on a disposable local MongoDB whose name is typed twice
  rollback   drops exactly the indexes an APPLIED run lists in its rollback plan

Usage:
    # the NAS path: a report from an export of a restored copy, no driver, no network
    python scripts/w0_03c_master_data_uniqueness.py report --from-export export.json --out report.json

    # a local disposable MongoDB
    python scripts/w0_03c_master_data_uniqueness.py report    --mongo-url mongodb://localhost:27017 --db w003c_scratch [--legacy]
    python scripts/w0_03c_master_data_uniqueness.py bootstrap --mongo-url mongodb://localhost:27017 --db w003c_scratch
    python scripts/w0_03c_master_data_uniqueness.py bootstrap --mongo-url mongodb://localhost:27017 --db w003c_scratch \\
        --apply --confirm-db w003c_scratch --out run.json
    python scripts/w0_03c_master_data_uniqueness.py rollback  --mongo-url mongodb://localhost:27017 --db w003c_scratch \\
        --plan run.json --confirm-db w003c_scratch

Deliberately NOT read: ``.env`` and ``MONGO_URL``. The server is always named on the
command line, and anything but a plain local ``mongodb://`` server is refused BEFORE a
connection is made — Atlas, the NAS and production are unreachable from this tool.

Exit codes:
    0  clean report · PLANNED · APPLIED · ALREADY_APPLIED · ROLLED_BACK
    1  duplicates block at least one index (report, REFUSED_DUPLICATES)
    2  refused: target, conflict, bad arguments or input
    3  FAILED_ROLLED_BACK — a build failed and this run's indexes were dropped again
    4  ROLLBACK_FAILED — something could not be undone; read the output
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.master_data import index_bootstrap as ib  # noqa: E402
from app.master_data import uniqueness as uq  # noqa: E402

EXIT_BY_STATUS = {
    ib.STATUS_PLANNED: 0, ib.STATUS_APPLIED: 0, ib.STATUS_ALREADY_APPLIED: 0,
    ib.STATUS_ROLLED_BACK: 0,
    ib.STATUS_REFUSED_DUPLICATES: 1,
    ib.STATUS_REFUSED_TARGET: 2, ib.STATUS_REFUSED_CONFLICT: 2,
    ib.STATUS_FAILED_ROLLED_BACK: 3,
    ib.STATUS_ROLLBACK_FAILED: 4,
}


def parse_mongo_url(url: str) -> Tuple[str, List[str]]:
    """``(scheme, hosts)`` of a MongoDB URL, without a driver and without printing the
    credentials that may be in it."""
    if "://" not in url:
        raise ib.TargetRefused("not a MongoDB URL")
    scheme, rest = url.split("://", 1)
    netloc = rest.split("/", 1)[0].split("?", 1)[0]
    netloc = netloc.rsplit("@", 1)[-1]                 # drop user:password@
    hosts = []
    for part in netloc.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("["):                       # [::1]:27017
            hosts.append(part[1:part.index("]")] if "]" in part else part)
        else:
            hosts.append(part.rsplit(":", 1)[0] if part.count(":") == 1 else part)
    return scheme.lower(), hosts


def write_json(path: str, data: Dict[str, Any]) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)
    if path:
        Path(path).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def _connect(url: str, database: str):
    from motor.motor_asyncio import AsyncIOMotorClient   # only for the live modes
    client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=5000)
    return client, client[database]


def _target(url: str, confirm: str) -> Dict[str, Any]:
    scheme, hosts = parse_mongo_url(url)
    return {"scheme": scheme, "hosts": hosts, "confirm_database": confirm}


def _guard_connection(url: str) -> None:
    scheme, hosts = parse_mongo_url(url)
    ib.check_local(hosts=hosts, scheme=scheme)


def _print_report_summary(summaries: List[Dict[str, Any]]) -> None:
    for s in summaries:
        state = "CLEAN" if s["canonical_clean"] else "BLOCKED"
        print("database=%s canonical=%s blocked_indexes=%d blocking_groups=%d tenantless=%d"
              % (s["database"], state, len(s["blocked_indexes"]), s["blocking_groups"],
                 s["tenantless_canonical_records"]), file=sys.stderr)
        for name in s["blocked_indexes"]:
            print("  blocked: %s" % name, file=sys.stderr)
        for lg in s.get("legacy", []):
            print("  legacy %-26s groups=%d within_collection=%d tenantless=%d"
                  % (lg["key"], lg["groups"], lg["within_collection_groups"], lg["tenantless_records"]),
                  file=sys.stderr)


def cmd_report(args) -> int:
    if args.from_export:
        export = json.loads(Path(args.from_export).read_text(encoding="utf-8"))
        result = uq.report_set_from_export(export)
        write_json(args.out, result)
        _print_report_summary(result["summary"])
        return 0 if result["clean"] else 1
    _guard_connection(args.mongo_url)
    client, db = _connect(args.mongo_url, args.db)
    try:
        report = asyncio.run(uq.duplicate_report(db, database=args.db, include_legacy=args.legacy))
    finally:
        client.close()
    write_json(args.out, report)
    _print_report_summary([uq.summarize(report)])
    return 0 if report["canonical"]["clean"] else 1


def cmd_bootstrap(args) -> int:
    _guard_connection(args.mongo_url)
    if args.apply:
        # the full guard runs again inside bootstrap(); checking here too means a refused
        # target never even opens a connection
        ib.check_target(database=args.db, **_target(args.mongo_url, args.confirm_db))
    client, db = _connect(args.mongo_url, args.db)
    try:
        result = asyncio.run(ib.bootstrap(db, database=args.db, apply=args.apply,
                                          target=_target(args.mongo_url, args.confirm_db)))
    finally:
        client.close()
    write_json(args.out, result)
    print("status=%s %s" % (result["status"], result.get("reason", "")), file=sys.stderr)
    return EXIT_BY_STATUS[result["status"]]


def cmd_rollback(args) -> int:
    _guard_connection(args.mongo_url)
    ib.check_target(database=args.db, **_target(args.mongo_url, args.confirm_db))
    saved = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    if saved.get("status") != ib.STATUS_APPLIED or saved.get("database") != args.db:
        raise ib.TargetRefused("the plan file is not an APPLIED run of database %r" % args.db)
    client, db = _connect(args.mongo_url, args.db)
    try:
        result = asyncio.run(ib.rollback(db, saved.get("rollback_plan") or [], database=args.db,
                                         target=_target(args.mongo_url, args.confirm_db)))
    finally:
        client.close()
    write_json(args.out, result)
    print("status=%s %s" % (result["status"], result.get("reason", "")), file=sys.stderr)
    return EXIT_BY_STATUS[result["status"]]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[1] if __doc__ else None)
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("report", help="read-only duplicate report")
    src = r.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-export", help="export JSON of a restored copy (NAS path)")
    src.add_argument("--mongo-url", help="a LOCAL mongodb:// server")
    r.add_argument("--db", help="database name (with --mongo-url)")
    r.add_argument("--legacy", action="store_true", help="also project the keys onto legacy collections")
    r.add_argument("--out", default="", help="write the JSON here instead of stdout")

    b = sub.add_parser("bootstrap", help="plan or build the unique indexes")
    b.add_argument("--mongo-url", required=True)
    b.add_argument("--db", required=True)
    b.add_argument("--apply", action="store_true")
    b.add_argument("--confirm-db", default=None, help="repeat --db; required with --apply")
    b.add_argument("--out", default="")

    rb = sub.add_parser("rollback", help="drop exactly the indexes of an APPLIED run")
    rb.add_argument("--mongo-url", required=True)
    rb.add_argument("--db", required=True)
    rb.add_argument("--plan", required=True, help="the JSON an APPLIED bootstrap wrote")
    rb.add_argument("--confirm-db", required=True)
    rb.add_argument("--out", default="")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "report" and args.mongo_url and not args.db:
        print("refused: --db is required with --mongo-url", file=sys.stderr)
        return 2
    try:
        return {"report": cmd_report, "bootstrap": cmd_bootstrap, "rollback": cmd_rollback}[args.command](args)
    except ib.TargetRefused as exc:
        print("refused: %s" % exc, file=sys.stderr)
        return 2
    except (OSError, ValueError) as exc:
        print("refused: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
