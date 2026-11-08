#!/usr/bin/env python3
"""
INV-CN-01 Addendum A — invoice number migration (FG-217, Р49(1)).

    python scripts/inv_cn_01_migrate.py                       # dry run: JSON report only
    python scripts/inv_cn_01_migrate.py --apply --actor <id>  # after the Owner approves the report

See app/services/invoice_corrections_migration.py for the steps and the rollback.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).parent.parent / ".env")


async def main(apply: bool, actor: str) -> int:
    from motor.motor_asyncio import AsyncIOMotorClient
    from app.services import invoice_corrections_migration as mig
    client = AsyncIOMotorClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
    database = client[os.environ.get("DB_NAME", "begwork")]
    try:
        report = await (mig.apply(database, actor_id=actor) if apply else mig.plan(database))
    finally:
        client.close()
    print(json.dumps({"mode": "apply" if apply else "dry-run", **report}, ensure_ascii=False,
                     indent=2, default=str))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--actor", default="")
    args = parser.parse_args()
    if args.apply and not args.actor:
        parser.error("--apply needs --actor (the approved operator id)")
    sys.exit(asyncio.run(main(args.apply, args.actor)))
