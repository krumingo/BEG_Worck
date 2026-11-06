#!/usr/bin/env python3
"""
AUTH-01 / AUTH-02 — break-glass owner access recovery: set the OWNER's password
from a server shell, attributed to a named human operator with a reason (Р19).

For the case the web flows cannot cover: the owner cannot log in, Admin Reset
cannot be used on oneself, and e-mail delivery may not be configured yet. This is
an OPERATOR tool run inside the backend container / on the backend host. It is
not, and must never become, an HTTP endpoint.

    # 1) look first — no write, no password needed
    python scripts/reset_user_password.py --email Krum@begfull.bg \
        --operator "Иван Петров" --reason "Owner locked out, ticket 123" --dry-run

    # 2) set it — the password is asked twice, hidden (needs a terminal:
    #    docker exec -it ...). There is deliberately NO way to pass the password
    #    as an argument or through a pipe (AUTH-01 C01, F-07): it would land in
    #    shell history, process listings or CI logs.
    python scripts/reset_user_password.py --email Krum@begfull.bg \
        --operator "Иван Петров" --reason "Owner locked out, ticket 123"

AUTH-02 (Р19, FLOW-040 L5 break-glass): ``--operator`` (the person at the shell)
and ``--reason`` are REQUIRED — non-empty, bounded, no control characters, never
containing the new password or a password hash. Without them the command stops
before any prompt or lookup and nothing is written. No prior Approval (the Owner
cannot log in to give one); instead the Owner is told afterwards.

What it guarantees:

* the email is compared ``strip().lower()`` with the R0-03 identity helper
  (``app.tenancy.identity``, the same rule as login); the command requires EXACTLY ONE matching user and that user must be active —
  zero matches, a case-only duplicate, or a disabled user stop it with a
  non-zero exit and nothing written;
* AUTH-02 (FG-8): the target must be an ``Owner`` — any other role is refused
  (exit 8, nothing written); those users are reset by their Owner/Admin in the
  app (Admin Reset). The role is re-checked inside the transaction;
* the password passes the same ``validate_password_strength`` the API uses and
  is hashed with the same ``hash_password``;
* ONE MongoDB transaction (AUTH-01 C01, F-01) updates exactly that one user
  document (filter on its ``id`` AND ``org_id``) — new hash,
  ``password_reset_at``, the recovery marker ``password_reset_by =
  LOCAL_RECOVERY_CLI`` and ``$inc auth_version`` (F-02: every session issued
  before the recovery stops working) — revokes the user's open self-service
  reset links and writes the legacy audit row and the canonical W0-04
  AuditEvent ``user.password_recovery_cli`` (R0-04). AUTH-02: that event names
  the human (``actor_type=human``, ``actor_id=break_glass:<operator>``), carries
  the reason, ``source_channel=break_glass_cli`` and retention class **R1**
  (FLOW-040: break-glass is R1; FG-9), and in the SAME transaction an in-app
  notification is written for every active Owner of the tenant (shown on their
  next login). All of it commits or none of it does;
* after the commit the Owners are also e-mailed when outbound e-mail is
  configured (best effort — the committed in-app notification is the record);
* neither the password nor any hash is ever printed or stored in the audit.

Exit codes: 0 ok · 1 usage / no terminal · 2 not found · 3 ambiguous ·
4 inactive / unusable record · 5 invalid password · 6 nothing changed (the
transaction did not commit) · 7 nothing changed (this MongoDB cannot run
transactions — a replica set is required) · 8 the user is not an Owner (nothing
changed). Usage (1) also covers a missing/invalid ``--operator``/``--reason``.
"""
import argparse
import asyncio
import getpass
import socket
import sys
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.auth_tx import TransactionsUnavailable, run_in_transaction  # noqa: E402
from app.tenancy.identity import normalize_email, users_with_email  # noqa: E402

EXIT_OK, EXIT_USAGE, EXIT_NOT_FOUND, EXIT_AMBIGUOUS = 0, 1, 2, 3
EXIT_INACTIVE, EXIT_INVALID_PASSWORD, EXIT_WRITE_FAILED, EXIT_NO_TRANSACTIONS = 4, 5, 6, 7
EXIT_NOT_OWNER = 8

RECOVERY_MARKER = "LOCAL_RECOVERY_CLI"
SOURCE_CHANNEL = "break_glass_cli"
OWNER_ROLE = "Owner"
NOTIFICATION_TYPE = "security_break_glass_password_reset"
OPERATOR_MIN, OPERATOR_MAX = 2, 120
REASON_MIN, REASON_MAX = 10, 500
_HASH_MARKERS = ("$2a$", "$2b$", "$2y$", "$argon2", "pbkdf2")
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
    """Inside the transaction: the target is no longer exactly one active Owner."""


class AttributionInvalid(ValueError):
    """``--operator`` / ``--reason`` are missing or unusable (AUTH-02, Р19)."""


def _clean_text(value, label: str, low: int, high: int) -> str:
    if not isinstance(value, str):
        raise AttributionInvalid(f"{label} is required")
    text = value.strip()
    if not text:
        raise AttributionInvalid(f"{label} is required and cannot be blank")
    if any(unicodedata.category(ch).startswith("C") for ch in text):
        raise AttributionInvalid(f"{label} cannot contain control characters")
    if not low <= len(text) <= high:
        raise AttributionInvalid(f"{label} must be {low}-{high} characters")
    lowered = text.lower()
    if any(marker in lowered for marker in _HASH_MARKERS):
        raise AttributionInvalid(f"{label} looks like it contains a password hash")
    return text


def validate_attribution(operator, reason) -> tuple:
    """The named human and the reason — stripped, bounded, printable (AUTH-02)."""
    return (_clean_text(operator, "--operator", OPERATOR_MIN, OPERATOR_MAX),
            _clean_text(reason, "--reason", REASON_MIN, REASON_MAX))


def attribution_contains_password(password: str, *texts: str) -> bool:
    """True when the new password appears inside the operator or reason text."""
    probe = (password or "").lower()
    return bool(probe) and any(probe in (t or "").lower() for t in texts)


def _notification_text(target: dict, operator: str, reason: str, host: str, stamp: str):
    title = "Аварийна смяна на паролата на собственика"
    message = (f"Паролата на {target.get('email')} е сменена от сървъра (break-glass) "
               f"на {stamp} от {operator} (хост {host}). Причина: {reason}. "
               "Ако не сте поискали това, сменете паролата си веднага и проверете "
               "журнала за одит.")
    return title, message


async def apply_reset(db, target: dict, password_hash: str, *, operator: str,
                      reason: str) -> list:
    """Write the new hash to exactly ``target`` — in ONE transaction, or not at all.

    The same transaction writes the attributed R1 AuditEvent and one in-app
    notification per active Owner of the tenant. Returns those Owners
    (``id``/``email``) for the post-commit e-mail.

    Raises :class:`_NotExactlyOne` / :class:`TransactionsUnavailable` / any driver
    error; in every one of those cases nothing was committed.
    """
    from app.audit.envelope import ACTOR_HUMAN, RETENTION_R1_CRITICAL_BUSINESS
    from app.services.user_role_policy import audit_user_change
    from app.tenancy.data_access import TenantData
    uid, org_id = target["id"], target["org_id"]
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    host = socket.gethostname()
    tenant = TenantData.for_resolved_org(db, org_id)
    title, message = _notification_text(target, operator, reason, host, stamp)

    async def body(session):
        if await db.users.count_documents({"id": uid, "org_id": org_id},
                                          session=session) != 1:
            raise _NotExactlyOne()
        result = await db.users.update_one(
            {"id": uid, "org_id": org_id, "is_active": {"$ne": False}, "role": OWNER_ROLE},
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
        owners = await tenant.users.find(
            {"role": OWNER_ROLE, "is_active": {"$ne": False}},
            {"_id": 0, "id": 1, "email": 1}, session=session).sort("id", 1).to_list(None)
        await db.audit_logs.insert_one({
            "id": str(uuid.uuid4()),
            "org_id": org_id,
            "user_id": "system",
            "user_email": "system",
            "action": "password_recovery_cli",
            "entity_type": "user",
            "entity_id": uid,
            "changes": {"method": RECOVERY_MARKER, "host": host,
                        "operator": operator, "reason": reason},
            "timestamp": stamp,
        }, session=session)
        # R0-04 / AUTH-02: the canonical W0-04 AuditEvent in the same transaction —
        # the named human, the reason, R1 (break-glass). No password, no hash.
        event = await audit_user_change(
            db, tenant_id=org_id, actor_id=f"break_glass:{operator}", actor_type=ACTOR_HUMAN,
            action="user.password_recovery_cli", target_id=uid, reason=reason,
            diff={"operator": operator, "host": host, "target_role": OWNER_ROLE,
                  "method": RECOVERY_MARKER,
                  "notified_owner_ids": [o["id"] for o in owners]},
            retention_class=RETENTION_R1_CRITICAL_BUSINESS, source_channel=SOURCE_CHANNEL,
            tool_or_endpoint="scripts/reset_user_password.py", session=session)
        # AUTH-02 (Р19): the Owner is told. Committed together with the reset, so a
        # notification exists exactly when the reset happened.
        for owner in owners:
            await tenant.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "org_id": org_id,
                "user_id": owner["id"],
                "type": NOTIFICATION_TYPE,
                "title": title,
                "message": message,
                "data": {"target_user_id": uid, "operator": operator, "reason": reason,
                         "host": host, "audit_event_id": (event or {}).get("event_id")},
                "is_read": False,
                "created_at": stamp,
            }, session=session)
        return owners

    return await run_in_transaction(db, body)


def email_owners(owners: list, target: dict, operator: str, reason: str) -> str:
    """Post-commit, best effort: e-mail each notified Owner. Returns the outcome.

    Never raises — the reset and the in-app notification are already committed.
    """
    from app.services.mailer import get_mail_provider
    provider = get_mail_provider()
    if provider is None:
        return "not_configured"
    title, message = _notification_text(target, operator, reason, socket.gethostname(),
                                        datetime.now(timezone.utc).isoformat())
    failed = 0
    for owner in owners:
        to = (owner.get("email") or "").strip()
        if not to:
            continue
        try:
            provider.send(to, "BEG_Work: " + title, message)
        except Exception:
            failed += 1
    return "sent" if not failed else "failed"


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

    # AUTH-02 (Р19): a named human and a reason, checked before any prompt or lookup.
    try:
        operator, reason = validate_attribution(getattr(args, "operator", None),
                                                getattr(args, "reason", None))
    except AttributionInvalid as exc:
        _out(f"ERROR: {exc}. Break-glass recovery needs --operator \"<your name>\" and "
             "--reason \"<why>\". Nothing changed.")
        return EXIT_USAGE

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
        if attribution_contains_password(password, operator, reason):
            _out("ERROR: --operator/--reason contain the new password; it would be stored in "
                 "the audit trail. Choose another password. Nothing changed.")
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
    if target.get("role") != OWNER_ROLE:
        _out("NOT AN OWNER: break-glass recovery is only for the Owner. Reset this user from "
             "the app (Admin Reset by the Owner/Admin). Nothing changed.\n  " + _describe(target))
        return EXIT_NOT_OWNER

    if args.dry_run:
        _out("DRY RUN — exactly one active user matches; nothing written:\n  " + _describe(target))
        return EXIT_OK

    try:
        owners = await apply_reset(db, target, hash_password(password),
                                   operator=operator, reason=reason)
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
    _out(f"Recorded: operator={operator!r} reason={reason!r} (AuditEvent R1).")
    _out(f"Owner notified in the app: {len(owners)} notification(s).")
    outcome = email_owners(owners, target, operator, reason)
    if outcome == "sent":
        _out("Owner e-mail: sent.")
    elif outcome == "not_configured":
        _out("Owner e-mail: not configured (SMTP) — the in-app notification is the notice.")
    else:
        _out("WARNING: Owner e-mail failed — the in-app notification is still recorded.")
    _out("The user can log in with the new password now.")
    return EXIT_OK


def parse_args(argv):
    p = argparse.ArgumentParser(
        description="Break-glass: reset the Owner's password from the server shell "
                    "(AUTH-01/AUTH-02).")
    p.add_argument("--email", required=True, help="the Owner's email (letter case ignored)")
    p.add_argument("--operator", required=True,
                   help=f"the person running this command ({OPERATOR_MIN}-{OPERATOR_MAX} chars)")
    p.add_argument("--reason", required=True,
                   help=f"why the recovery is needed ({REASON_MIN}-{REASON_MAX} chars; "
                        "never a password)")
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
