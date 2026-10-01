#!/usr/bin/env python3
"""
W0-03E-A2B — single-tenant (BEG) legacy ownership backfill: operator CLI.

A DEVELOPMENT / TEST tool. Never imported by the application. It drives
``app.tenancy.legacy_backfill``:

    --dry-run            (default) precondition + full inventory + plan token.
                         Read-only by construction; allowed on any LOCAL server.
    --verify             zero-ownerless / zero-unknown-owner proof against the
                         registry tenants of the database. Read-only.
    --execute            stamp the planned ownerless rows (needs --plan-token,
                         --idempotency-key, --actor, --approval-id).
    --enforce            install the server-side ownership validators.
    --release-invariant  remove them again (rollback of --enforce).
    --rollback           restore one run's rows (needs --run-id, --idempotency-key,
                         --actor, --approval-id).

Safety. Every mode refuses a non-loopback server (the W0-03C ``check_local``
guard: no Atlas, no NAS, no ``mongodb+srv``). Every WRITE mode additionally
refuses unless BOTH database names start with ``DISPOSABLE_PREFIX``: no
production, restored-production or real BEG database can be migrated by this
build. A production run needs the W0-07 Approval runtime and a separate owner
decision; until then the library's default approval verifier refuses anyway.
Inside a disposable test database the approval is a test-only verifier bound to
the exact plan token, so the approval path is exercised, not skipped.

Usage:
    python scripts/w0_03e_a2b_beg_backfill.py --mongo-url mongodb://127.0.0.1:27017 \\
        --db <db> --system-db <sysdb> [--out report.json]
    python scripts/w0_03e_a2b_beg_backfill.py ... --execute --plan-token T \\
        --idempotency-key K --actor krum --approval-id A

Exit codes: 0 ok; 1 blocked / verification failed / precondition failed;
2 target refused.
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.master_data import index_bootstrap as ib  # noqa: E402
from app.tenancy import legacy_backfill as lb  # noqa: E402

#: Write modes only ever touch databases whose names start with this.
DISPOSABLE_PREFIX = "w003e_a2b_disposable_"

EXIT_OK, EXIT_BLOCKED, EXIT_REFUSED = 0, 1, 2


class DisposableTestApproval:
    """Approval verifier for a DISPOSABLE test database only.

    Constructed by this CLI after the disposable-name and loopback checks. It
    binds the evidence to the exact subject (plan token / run id) it is asked
    about, so a stale or different plan still fails the library's checks.
    """

    name = "disposable-test-only"

    def __init__(self, approver_id: str, tenant_id_hint=None):
        self.approver_id = approver_id

    async def verify(self, *, approval_id, subject):
        return lb.ApprovalEvidence(approval_id, subject["tenant_id"], subject,
                                   self.approver_id,
                                   datetime.now(timezone.utc).isoformat(), self.name)


def check_target(mongo_url: str, *names: str, write: bool) -> None:
    from scripts.w0_03c_master_data_uniqueness import parse_mongo_url
    scheme, hosts = parse_mongo_url(mongo_url)
    ib.check_local(hosts=hosts, scheme=scheme)
    if write:
        bad = [n for n in names if not n.startswith(DISPOSABLE_PREFIX)]
        if bad:
            raise ib.TargetRefused(
                "write refused: %s is not a disposable test database (prefix %r). No "
                "production or real-data migration is authorized by W0-03E-A2B."
                % (", ".join(bad), DISPOSABLE_PREFIX))


def build_parser():
    p = argparse.ArgumentParser(description="W0-03E-A2B single-tenant legacy ownership backfill")
    p.add_argument("--mongo-url", required=True, help="a LOCAL mongodb:// server")
    p.add_argument("--db", required=True)
    p.add_argument("--system-db", required=True)
    mode = p.add_mutually_exclusive_group()
    for flag in ("--dry-run", "--verify", "--execute", "--enforce", "--release-invariant",
                 "--rollback"):
        mode.add_argument(flag, action="store_true")
    p.add_argument("--plan-token", default="")
    p.add_argument("--idempotency-key", default="")
    p.add_argument("--actor", default="")
    p.add_argument("--approval-id", default="")
    p.add_argument("--run-id", default="")
    p.add_argument("--batch-size", type=int, default=None)
    p.add_argument("--out", default="")
    return p


async def run(args) -> dict:
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(args.mongo_url, serverSelectionTimeoutMS=5000)
    op, sys_db = client[args.db], client[args.system_db]
    try:
        if args.verify:
            return await lb.verify_ownership(op, sys_db)
        approval = DisposableTestApproval(args.actor)
        if args.execute:
            return await lb.execute(op, sys_db, plan_token=args.plan_token,
                                    idempotency_key=args.idempotency_key, actor_id=args.actor,
                                    approval_id=args.approval_id, approval_verifier=approval,
                                    batch_size=args.batch_size)
        if args.enforce:
            return await lb.enforce_invariant(op, sys_db, actor_id=args.actor)
        if args.release_invariant:
            return await lb.release_invariant(op, sys_db)
        if args.rollback:
            return await lb.rollback(op, sys_db, run_id=args.run_id,
                                     idempotency_key=args.idempotency_key, actor_id=args.actor,
                                     approval_id=args.approval_id, approval_verifier=approval)
        return await lb.dry_run(op, sys_db)
    finally:
        client.close()


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    write = args.execute or args.enforce or args.release_invariant or args.rollback
    try:
        check_target(args.mongo_url, args.db, args.system_db, write=write)
    except (ib.TargetRefused, ValueError) as exc:
        print("refused: %s" % exc, file=sys.stderr)
        return EXIT_REFUSED
    try:
        result = asyncio.run(run(args))
    except lb.BackfillRefused as exc:
        result = {"refused": True, "code": exc.code, "message": str(exc), "detail": exc.detail}
        code = EXIT_BLOCKED
    else:
        if args.verify:
            code = EXIT_OK if result["ok"] else EXIT_BLOCKED
        elif not write:
            code = EXIT_OK if result.get("executable") else EXIT_BLOCKED
        else:
            code = EXIT_OK
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
