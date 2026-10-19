#!/usr/bin/env python3
"""
R0-03 — User email duplicates report (decision Р6, AUTH-01 F-03). READ-ONLY.

Before R0-03 a User email was unique only inside one company and was not
normalized, so the installation may already hold several Users for one person
(``ivan@x.bg`` in two firms, or ``Ivan@X.bg `` next to ``ivan@x.bg``). Such an
email can no longer log in (409 ``DUPLICATE_IDENTITY``) and blocks the unique
index. This report counts them so Krum can decide the cleanup (R0-09) from facts.

Output per duplicated normalized email: the count, the MASKED email
(``iv***@abv.bg``) and the User ids with their ``org_id``. Never a full email, a
name, a password hash, a secret or the connection string.

It never writes. The database handle is the R0-01 allowlist wrapper
(``ReadOnlyDb``): only read methods reach the server. ``build_report`` contains
no write call (the A2C guard proves it — READ_ONLY_DIAGNOSTIC). The outer
boundary for any non-local run is a MongoDB user with only the ``read`` role.
A non-local target is refused unless ``--allow-remote`` is given (production
needs Krum's approval).

Usage:
    python scripts/r0_03_email_duplicates_report.py --db begwork [--mongo-url URL] \
        [--allow-remote] [--out report.json]

Exit 0 = report produced; 2 = target refused or not given.
"""
import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.r0_01_billing_exposure_report import ReadOnlyDb  # noqa: E402
from app.tenancy.identity import mask_email, normalize_email  # noqa: E402

ROW_LIMIT = 200000


async def build_report(db):
    """Duplicated normalized emails in ``users``, read through a write-refusing handle."""
    ro = ReadOnlyDb(db)
    rows = await ro["users"].find({}, {"_id": 0, "id": 1, "org_id": 1, "email": 1}).to_list(ROW_LIMIT)
    groups = defaultdict(list)
    without_email = 0
    for row in rows:
        norm = normalize_email(row.get("email"))
        if not norm:
            without_email += 1
            continue
        groups[norm].append(row)
    duplicates = []
    for norm in sorted(groups):
        users = groups[norm]
        if len(users) < 2:
            continue
        duplicates.append({
            "email_masked": mask_email(norm),
            "count": len(users),
            "spellings_differ": len({u.get("email") for u in users}) > 1,
            "users": sorted(({"id": u.get("id"), "org_id": u.get("org_id")} for u in users),
                            key=lambda u: (str(u["org_id"]), str(u["id"]))),
        })
    return {
        "schema": "beg.r0-03-email-duplicates-report/v1",
        "read_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": db.name,
        "counts": {
            "users": len(rows),
            "users_without_email": without_email,
            "duplicated_emails": len(duplicates),
            "users_in_duplicates": sum(d["count"] for d in duplicates),
        },
        "duplicates": duplicates,
        "notes": [
            "Emails are compared as strip().lower(); only masked emails are printed.",
            "No user is changed or merged here. Cleanup is a separate, approved step (R0-09).",
        ],
    }


def build_parser():
    p = argparse.ArgumentParser(description="R0-03 read-only user email duplicates report")
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
