#!/usr/bin/env python3
"""
AUTH-01 — local owner access recovery: set one user's password from a server shell.

For the case the web flows cannot cover: the owner cannot log in, Admin Reset
cannot be used on oneself, and e-mail delivery may not be configured yet. This is
an OPERATOR tool run inside the backend container / on the backend host. It is
not, and must never become, an HTTP endpoint.

    # 1) look first — no write, no password needed
    python scripts/reset_user_password.py --email Krum@begfull.bg --dry-run

    # 2) set it — the password is asked twice, hidden
    python scripts/reset_user_password.py --email Krum@begfull.bg

    # non-interactive alternatives (prefer stdin; an argument lands in shell history)
    printf '%s' "$NEW_PW" | python scripts/reset_user_password.py --email X --password-stdin
    python scripts/reset_user_password.py --email X --new-password '...'

What it guarantees:

* the email is compared ``strip().lower()`` (``app.utils.email_identity``); the
  command requires EXACTLY ONE matching user and that user must be active —
  zero matches, a case-only duplicate, or a disabled user stop it with a
  non-zero exit and nothing written;
* the password passes the same ``validate_password_strength`` the API uses and
  is hashed with the same ``hash_password``;
* exactly that one user document is updated (filter on its ``id`` AND
  ``org_id``); ``password_reset_at`` and an explicit recovery marker
  (``password_reset_by = LOCAL_RECOVERY_CLI``) are recorded, and the user's
  outstanding self-service reset links are invalidated;
* an audit row is written in the user's own tenant;
* neither the password nor any hash is ever printed.

Exit codes: 0 ok · 1 usage · 2 not found · 3 ambiguous · 4 inactive / unusable
record · 5 invalid password · 6 write did not apply.
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

from app.utils.email_identity import (  # noqa: E402
    MATCH_LIMIT, email_match_filter, matching, normalize_email)

EXIT_OK, EXIT_USAGE, EXIT_NOT_FOUND, EXIT_AMBIGUOUS = 0, 1, 2, 3
EXIT_INACTIVE, EXIT_INVALID_PASSWORD, EXIT_WRITE_FAILED = 4, 5, 6

RECOVERY_MARKER = "LOCAL_RECOVERY_CLI"
_PROJECTION = {"_id": 0, "id": 1, "org_id": 1, "email": 1, "role": 1, "is_active": 1,
               "first_name": 1, "last_name": 1}


def _out(msg: str) -> None:
    print(msg, flush=True)


def _describe(doc: dict) -> str:
    return (f"id={doc.get('id')} org_id={doc.get('org_id')} email={doc.get('email')!r} "
            f"role={doc.get('role')} active={doc.get('is_active', True)}")


async def find_candidates(db, email: str):
    """Every user whose email equals ``email`` up to case/surrounding whitespace."""
    normalized = normalize_email(email)
    if normalized is None:
        return None, []
    docs = await db.users.find(email_match_filter(normalized), _PROJECTION) \
        .limit(MATCH_LIMIT).to_list(MATCH_LIMIT)
    return normalized, matching(docs, normalized)


async def apply_reset(db, target: dict, password_hash: str) -> bool:
    """Write the new hash to exactly ``target`` — nothing else."""
    uid, org_id = target["id"], target["org_id"]
    if await db.users.count_documents({"id": uid, "org_id": org_id}) != 1:
        return False
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    result = await db.users.update_one(
        {"id": uid, "org_id": org_id},
        {"$set": {
            "password_hash": password_hash,
            "updated_at": stamp,
            "password_reset_at": stamp,
            "password_reset_by": RECOVERY_MARKER,
        }})
    if result.matched_count != 1:
        return False
    # Any self-service reset link still in flight for this user is now stale.
    await db.password_reset_tokens.update_many(
        {"org_id": org_id, "user_id": uid, "used_at": None},
        {"$set": {"used_at": now, "revoked_reason": "local_recovery_cli"}})
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
    })
    return True


def _read_password(args) -> str:
    if args.new_password is not None:
        _out("WARNING: a password given as an argument can remain in shell history.")
        return args.new_password
    if args.password_stdin:
        return sys.stdin.readline().rstrip("\r\n")
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
            password = _read_password(args)
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
        _out(f"AMBIGUOUS: {len(found)} users match {normalized!r} up to letter case. "
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

    if not await apply_reset(db, target, hash_password(password)):
        _out("ERROR: the update did not apply to exactly that user. Nothing reported as done.")
        return EXIT_WRITE_FAILED
    _out("OK: password reset for\n  " + _describe(target))
    _out("The user can log in with the new password now.")
    return EXIT_OK


def parse_args(argv):
    p = argparse.ArgumentParser(
        description="Reset ONE active user's password from the server shell (AUTH-01).")
    p.add_argument("--email", required=True, help="the user's email (letter case ignored)")
    p.add_argument("--dry-run", action="store_true", help="look the user up, write nothing")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--password-stdin", action="store_true",
                     help="read the new password from the first line of stdin")
    src.add_argument("--new-password", default=None,
                     help="the new password (discouraged: visible in shell history)")
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
