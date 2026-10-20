#!/usr/bin/env python3
"""
AUTH-01 — local owner access recovery: set one user's password from a server shell.

For the case the web flows cannot cover: the owner cannot log in, Admin Reset
cannot be used on oneself, and e-mail delivery may not be configured yet. This is
an OPERATOR tool run inside the backend container / on the backend host. It is
not, and must never become, an HTTP endpoint.

    # 1) look first — no write, no password needed
    python scripts/reset_user_password.py --email Krum@begfull.bg --dry-run

    # 2) set it — the password is asked twice, hidden (needs a terminal:
    #    docker exec -it ...). There is deliberately NO way to pass the password
    #    as an argument or through a pipe (AUTH-01 C01, F-07): it would land in
    #    shell history, process listings or CI logs.
    python scripts/reset_user_password.py --email Krum@begfull.bg

What it guarantees:

* the email is compared ``strip().lower()`` with the R0-03 identity helper
  (``app.tenancy.identity``, the same rule as login); the command requires EXACTLY ONE matching user and that user must be active —
  zero matches, a case-only duplicate, or a disabled user stop it with a
  non-zero exit and nothing written;
* the password passes the same ``validate_password_strength`` the API uses and
  is hashed with the same ``hash_password``;
* ONE MongoDB transaction (AUTH-01 C01, F-01) updates exactly that one user
  document (filter on its ``id`` AND ``org_id``) — new hash,
  ``password_reset_at``, the recovery marker ``password_reset_by =
  LOCAL_RECOVERY_CLI`` and ``$inc auth_version`` (F-02: every session issued
  before the recovery stops working) — revokes the user's open self-service
  reset links and writes the legacy audit row and the canonical W0-04
  AuditEvent ``user.password_recovery_cli`` (R0-04). All of it commits or none
  of it does;
* neither the password nor any hash is ever printed.

Exit codes: 0 ok · 1 usage / no terminal · 2 not found · 3 ambiguous ·
4 inactive / unusable record · 5 invalid password · 6 nothing changed (the
transaction did not commit) · 7 nothing changed (this MongoDB cannot run
transactions — a replica set is required).
"""
import argparse
import asyncio
import getpass
import socket
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.auth_tx import TransactionsUnavailable, run_in_transaction  # noqa: E402
from app.tenancy.identity import normalize_email, users_with_email  # noqa: E402

EXIT_OK, EXIT_USAGE, EXIT_NOT_FOUND, EXIT_AMBIGUOUS = 0, 1, 2, 3
EXIT_INACTIVE, EXIT_INVALID_PASSWORD, EXIT_WRITE_FAILED, EXIT_NO_TRANSACTIONS = 4, 5, 6, 7

RECOVERY_MARKER = "LOCAL_RECOVERY_CLI"
_PROJECTION = {"_id": 0, "id": 1, "org_id": 1, "email": 1, "role": 1, "is_active": 1,
               "first_name": 1, "last_name": 1}


def _out(msg: str) -> None:
    print(msg, flush=True)


def _describe(doc: dict) -> str:
    return (f"id={doc.get('id')} org_id={doc.get('org_id')} email={doc.get('email')!r} "
            f"role={doc.get('role')} active={doc.get('is_active', True)}")


async def find_candidates(db, email: str):
    """Every user whose email equals ``email`` up to case/surrounding whitespace.

    The login registry (global ``users``), through the one R0-03 helper; only the
    fields in ``_PROJECTION`` are kept (no hash leaves this function).
    """
    normalized = normalize_email(email)
    if not normalized:
        return None, []
    rows = await users_with_email([db], normalized)
    return normalized, [{k: r[k] for k in _PROJECTION if k != "_id" and k in r} for r in rows]


class _NotExactlyOne(Exception):
    """Inside the transaction: the target is no longer exactly one active user."""


async def apply_reset(db, target: dict, password_hash: str) -> None:
    """Write the new hash to exactly ``target`` — in ONE transaction, or not at all.

    Raises :class:`_NotExactlyOne` / :class:`TransactionsUnavailable` / any driver
    error; in every one of those cases nothing was committed.
    """
    from app.services.user_role_policy import audit_user_change
    uid, org_id = target["id"], target["org_id"]
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()

    async def body(session):
        if await db.users.count_documents({"id": uid, "org_id": org_id},
                                          session=session) != 1:
            raise _NotExactlyOne()
        result = await db.users.update_one(
            {"id": uid, "org_id": org_id, "is_active": {"$ne": False}},
            {"$set": {
                "password_hash": password_hash,
                "updated_at": stamp,
                "password_reset_at": stamp,
                "password_reset_by": RECOVERY_MARKER,
            }, "$inc": {"auth_version": 1}}, session=session)
        if result.matched_count != 1:
            raise _NotExactlyOne()
        # Any self-service reset link still in flight for this user is now stale.
        await db.password_reset_tokens.update_many(
            {"org_id": org_id, "user_id": uid, "used_at": None},
            {"$set": {"used_at": now, "revoked_reason": "local_recovery_cli"}},
            session=session)
        await db.audit_logs.insert_one({
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "user_id": "system",
            "user_email": "system",
            "action": "password_recovery_cli",
            "entity_type": "user",
            "entity_id": uid,
            "changes": {"method": RECOVERY_MARKER, "host": socket.gethostname()},
            "timestamp": stamp,
        }, session=session)
        # R0-04: the canonical W0-04 AuditEvent in the same transaction (no password/hash).
        await audit_user_change(
            db, tenant_id=org_id, actor_id=RECOVERY_MARKER, actor_type="system",
            action="user.password_recovery_cli", target_id=uid,
            reason="password set by the local owner-recovery command (no hash recorded)",
            tool_or_endpoint="scripts/reset_user_password.py", session=session)

    await run_in_transaction(db, body)


class _NoTerminal(Exception):
    pass


def _read_password() -> str:
    """Hidden interactive entry, twice. Refused without a terminal (no echo/pipe path)."""
    if not sys.stdin.isatty():
        raise _NoTerminal()
    first = getpass.getpass("New password: ")
    second = getpass.getpass("Repeat new password: ")
    if first != second:
        raise ValueError("The two passwords do not match")
    return first


async def run(db, args) -> int:
    from app.deps.auth import hash_password
    from app.routes.auth import validate_password_strength

    password = None
    if not args.dry_run:
        try:
            password = _read_password()
        except _NoTerminal:
            _out("ERROR: the new password is entered only at a hidden prompt. Run this in a "
                 "terminal, e.g. `docker exec -it begwork-backend python "
                 "scripts/reset_user_password.py --email ...`. Nothing changed.")
            return EXIT_USAGE
        except (ValueError, EOFError, KeyboardInterrupt) as exc:
            _out(f"ERROR: {exc or 'no password entered'}")
            return EXIT_INVALID_PASSWORD
        ok, message = validate_password_strength(password)
        if not ok:
            _out(f"ERROR: password rejected — {message}")
            return EXIT_INVALID_PASSWORD

    normalized, found = await find_candidates(db, args.email)
    if normalized is None:
        _out("ERROR: that is not a usable email")
        return EXIT_USAGE
    if not found:
        _out(f"NOT FOUND: no user with email {normalized!r} (case-insensitive). Nothing changed.")
        return EXIT_NOT_FOUND
    if len(found) > 1:
        _out(f"AMBIGUOUS: {len(found)} users match {normalized!r} (normalized). "
             "Nothing changed — resolve the duplicate first:")
        for doc in found:
            _out("  - " + _describe(doc))
        return EXIT_AMBIGUOUS
    target = found[0]
    if not target.get("is_active", True):
        _out("INACTIVE: the only matching user is disabled. Nothing changed.\n  " + _describe(target))
        return EXIT_INACTIVE
    if not isinstance(target.get("id"), str) or not target["id"] \
            or not isinstance(target.get("org_id"), str) or not target["org_id"]:
        _out("UNUSABLE: the matching user has no id/org_id. Nothing changed.\n  " + _describe(target))
        return EXIT_INACTIVE

    if args.dry_run:
        _out("DRY RUN — exactly one active user matches; nothing written:\n  " + _describe(target))
        return EXIT_OK

    try:
        await apply_reset(db, target, hash_password(password))
    except TransactionsUnavailable:
        _out("ERROR: this MongoDB cannot run transactions (a replica set is required), so "
             "the reset was refused. NOTHING CHANGED.")
        return EXIT_NO_TRANSACTIONS
    except _NotExactlyOne:
        _out("ERROR: the user changed while resetting (no longer exactly one active match). "
             "NOTHING CHANGED.")
        return EXIT_WRITE_FAILED
    except Exception as exc:
        _out(f"ERROR: the reset did not commit ({type(exc).__name__}). NOTHING CHANGED.")
        return EXIT_WRITE_FAILED
    _out("OK: password reset for\n  " + _describe(target))
    _out("The user can log in with the new password now.")
    return EXIT_OK


def parse_args(argv):
    p = argparse.ArgumentParser(
        description="Reset ONE active user's password from the server shell (AUTH-01).")
    p.add_argument("--email", required=True, help="the user's email (letter case ignored)")
    p.add_argument("--dry-run", action="store_true", help="look the user up, write nothing")
    return p.parse_args(argv)


def main(argv=None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as exc:      # argparse already printed the usage
        return EXIT_USAGE if exc.code else EXIT_OK
    from app.db import client, db, db_name
    _out(f"Database: {db_name}")
    try:
        return asyncio.run(run(db, args))
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
