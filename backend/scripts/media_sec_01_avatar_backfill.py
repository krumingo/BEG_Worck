#!/usr/bin/env python3
"""
MEDIA-SEC-01 / R83(4) + FLOW Guard pass 46 (FG-578) — mark the LEGACY avatars that
``GET /api/media/avatar/...`` may serve, and undo that marking if needed.

Since MEDIA-SEC-01 an avatar is served only from a ``media_files`` row with ``avatar: true``,
which ``POST /media/upload`` sets for a fresh ``context_type="profile"`` upload (R83(3)).
Avatars uploaded before that have no flag, so they show initials until this backfill is
applied. Krum, R83(4): a dry run that only counts; an idempotent apply with an AuditEvent;
never run automatically — the deploy needs Krum's "да".

ONE tenant per run: the tenant is the one of the approving Owner (``--approved-by`` is the
Owner's USER ID, checked in the database — not free text). For every user of that tenant
whose ``avatar_url`` is ``/api/media/avatar/<name>`` or ``/api/media/file/<name>``:

* ``flag`` — a ``media_files`` row of the tenant with that stored name, not retired, that was
  UPLOADED as the user's profile photo: ``context_type="profile"``, ``context_id`` = the user,
  and NO ``linked_at`` (a file only LINKED to a profile afterwards is not flagged — FG-578).
  The row gets ``avatar: true`` (and the user's ``avatar_url`` its ``/api/media/avatar/`` form
  when it used ``/file/``); one transaction per user with the AuditEvent
  ``media.avatar.backfill`` (actor ``system``, approver id in the diff). Every write checks
  its ``matched_count``; a mismatch aborts that user's transaction (``conflict``).
* ``already`` — nothing to do. ``skip:<reason>`` — reported only; a person decides.

``--revert``: the plan is every row this script flagged in the tenant
(``avatar_backfill = "MEDIA-SEC-01"``); applying it removes the flag and restores the user's
previous ``avatar_url`` (only while it still is the one the backfill wrote), with the
AuditEvent ``media.avatar.backfill_revert``.

Properties (the PRJ-01 migration pattern):

* **Dry run by default** — plan, counts, SHA-256; nothing written.
* ``--apply`` needs ``--approved-by <Owner user id>`` and ``--plan-sha`` equal to the plan of
  the moment (else ``NotApproved`` / ``PlanMismatch``, nothing written).
* **Idempotent** — a second apply writes 0.

    MONGO_URL=... DB_NAME=... python scripts/media_sec_01_avatar_backfill.py --approved-by <owner id>
    MONGO_URL=... DB_NAME=... python scripts/media_sec_01_avatar_backfill.py \\
        --approved-by <owner id> --plan-sha <sha> --apply
    MONGO_URL=... DB_NAME=... python scripts/media_sec_01_avatar_backfill.py --revert \\
        --approved-by <owner id> [--plan-sha <sha> --apply]

Running it against staging or production is an operator decision outside MEDIA-SEC-01.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MIGRATION = "MEDIA-SEC-01"
_URL = re.compile(r"^/api/media/(avatar|file)/([A-Za-z0-9][A-Za-z0-9_-]{0,127}\.[A-Za-z0-9]{1,10})$")


class PlanMismatch(RuntimeError):
    pass


class NotApproved(RuntimeError):
    pass


class _Conflict(RuntimeError):
    """A write matched nothing — the data changed since the plan; the transaction aborts."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def resolve_owner(db, approved_by: Optional[str]) -> Dict[str, Any]:
    """The approving Owner: an ACTIVE user with role ``Owner`` (FG-578: an id, not free text)."""
    if not isinstance(approved_by, str) or not approved_by.strip():
        raise NotApproved("--approved-by <Owner user id> is required")
    u = await db.users.find_one({"id": approved_by.strip()},
                                {"_id": 0, "id": 1, "org_id": 1, "role": 1, "is_active": 1})
    if not u or u.get("role") != "Owner" or u.get("is_active") is False or not u.get("org_id"):
        raise NotApproved("--approved-by must be the user id of an active Owner")
    return u


async def build_plan(db, org_id: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    users = await db.users.find({"org_id": org_id, "avatar_url": {"$nin": [None, ""]}},
                                {"_id": 0, "id": 1, "org_id": 1, "avatar_url": 1}
                                ).sort("id", 1).to_list(None)
    for u in users:
        row = {"org_id": org_id, "user_id": u.get("id"), "avatar_url": u.get("avatar_url")}
        m = _URL.fullmatch(u.get("avatar_url") or "")
        if not m:
            rows.append({**row, "action": "skip:url_shape"})
            continue
        form, name = m.group(1), m.group(2)
        media = await db.media_files.find_one({"stored_filename": name, "org_id": org_id},
                                              {"_id": 0})
        row.update({"stored_filename": name, "media_id": (media or {}).get("id")})
        if not media:
            row["action"] = "skip:no_media_in_tenant"
        elif media.get("status") == "retired":
            row["action"] = "skip:retired"
        elif media.get("context_type") != "profile":
            row["action"] = "skip:not_a_profile_photo"
        elif media.get("context_id") != u["id"]:
            row["action"] = "skip:another_users_profile"
        elif media.get("linked_at"):
            row["action"] = "skip:linked_not_uploaded_as_profile"
        elif media.get("avatar") is True and form == "avatar":
            row["action"] = "already"
        else:
            row["action"] = "flag"
            row["new_avatar_url"] = "/api/media/avatar/%s" % name
        rows.append(row)
    return rows


async def build_revert_plan(db, org_id: str) -> List[Dict[str, Any]]:
    rows = []
    marked = await db.media_files.find({"org_id": org_id, "avatar_backfill": MIGRATION},
                                       {"_id": 0}).sort("id", 1).to_list(None)
    for media in marked:
        rows.append({"org_id": org_id, "media_id": media.get("id"),
                     "user_id": media.get("context_id"),
                     "stored_filename": media.get("stored_filename"),
                     "restore_avatar_url": media.get("avatar_backfill_prev_url"),
                     "written_avatar_url": media.get("avatar_backfill_url"),
                     "action": "revert"})
    return rows


def plan_sha(rows: List[Dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in rows:
        out[r["action"]] = out.get(r["action"], 0) + 1
    return dict(sorted(out.items()))


async def _event(db, session, row, action, diff):
    from app.audit.envelope import ACTOR_SYSTEM, RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    event = build_event(
        tenant_id=row["org_id"], actor_type=ACTOR_SYSTEM, actor_id="migration:%s" % MIGRATION,
        action=action, source_flow="FLOW-029", retention_class=RETENTION_R1_CRITICAL_BUSINESS,
        entity_type="media_file", entity_id=row["media_id"],
        reason="legacy avatar %s (R83-4)" % ("reverted" if action.endswith("revert") else "marked"),
        structured_diff=diff, tool_or_endpoint="scripts/media_sec_01_avatar_backfill.py",
        source_channel="migration")
    await record_event(db, event, session=session)


async def _apply_flag(db, row: Dict[str, Any], approver: str,
                      approval_ref: Optional[str] = None) -> str:
    from app.services.auth_tx import run_in_transaction

    async def body(session):
        res = await db.media_files.update_one(
            {"id": row["media_id"], "org_id": row["org_id"], "stored_filename": row["stored_filename"],
             "context_type": "profile", "context_id": row["user_id"], "linked_at": None,
             "status": {"$ne": "retired"}, "avatar_backfill": None},
            {"$set": {"avatar": True, "avatar_backfill": MIGRATION, "avatar_backfill_at": _now(),
                      "avatar_backfill_by": approver,
                      "avatar_backfill_prev_url": row["avatar_url"],
                      "avatar_backfill_url": row["new_avatar_url"]}},
            session=session)
        if res.matched_count != 1:
            raise _Conflict("media")
        if row["avatar_url"] != row["new_avatar_url"]:
            res = await db.users.update_one(
                {"id": row["user_id"], "org_id": row["org_id"], "avatar_url": row["avatar_url"]},
                {"$set": {"avatar_url": row["new_avatar_url"]}}, session=session)
            if res.matched_count != 1:
                raise _Conflict("user")
        await _event(db, session, row, "media.avatar.backfill", {
            "user_id": row["user_id"],
            "before": {"avatar": None, "avatar_url": row["avatar_url"]},
            "after": {"avatar": True, "avatar_url": row["new_avatar_url"]},
            "approved_by": approver, "approval_ref": approval_ref})
        return "written"

    try:
        return await run_in_transaction(db, body)
    except _Conflict:
        return "conflict"


async def _apply_revert(db, row: Dict[str, Any], approver: str,
                        approval_ref: Optional[str] = None) -> str:
    from app.services.auth_tx import run_in_transaction

    async def body(session):
        res = await db.media_files.update_one(
            {"id": row["media_id"], "org_id": row["org_id"], "avatar_backfill": MIGRATION},
            {"$unset": {"avatar": "", "avatar_backfill": "", "avatar_backfill_at": "",
                        "avatar_backfill_by": "", "avatar_backfill_prev_url": "",
                        "avatar_backfill_url": ""}}, session=session)
        if res.matched_count != 1:
            raise _Conflict("media")
        restored = False
        if row.get("restore_avatar_url") and row.get("written_avatar_url") \
                and row["restore_avatar_url"] != row["written_avatar_url"]:
            res = await db.users.update_one(
                {"id": row["user_id"], "org_id": row["org_id"],
                 "avatar_url": row["written_avatar_url"]},
                {"$set": {"avatar_url": row["restore_avatar_url"]}}, session=session)
            restored = res.matched_count == 1   # a user who changed the avatar since keeps it
        await _event(db, session, row, "media.avatar.backfill_revert", {
            "user_id": row["user_id"], "before": {"avatar": True},
            "after": {"avatar": None}, "avatar_url_restored": restored,
            "approved_by": approver, "approval_ref": approval_ref})
        return "written"

    try:
        return await run_in_transaction(db, body)
    except _Conflict:
        return "conflict"


def check_approval_ref(value: Optional[str]) -> Optional[str]:
    """FG-692 prep: where Krum's "да" was given (a conversation / message reference), stored
    in every AuditEvent the apply writes. Optional until Krum decides how it is recorded;
    when given: ≤ 500 characters, no control characters."""
    if value is None:
        return None
    ref = value.strip()
    if not ref:
        return None
    if len(ref) > 500 or any(ord(ch) < 32 or ord(ch) == 127 for ch in ref):
        raise NotApproved("--approval-ref: at most 500 characters, no control characters")
    return ref


async def migrate(db, apply: bool = False, approved_by: Optional[str] = None,
                  plan_sha: Optional[str] = None, revert: bool = False,
                  approval_ref: Optional[str] = None) -> Dict[str, Any]:
    approval_ref = check_approval_ref(approval_ref)
    owner = await resolve_owner(db, approved_by)
    rows = await (build_revert_plan if revert else build_plan)(db, owner["org_id"])
    sha = globals()["plan_sha"](rows)
    result = {"mode": "revert" if revert else "backfill", "org_id": owner["org_id"],
              "plan": rows, "plan_sha": sha, "counts": counts(rows), "applied": False,
              "approval_ref": approval_ref}
    if not apply:
        return result
    if plan_sha != sha:
        raise PlanMismatch("the approved plan is not the current plan — run the dry run again")
    outcome: Dict[str, int] = {"written": 0, "conflict": 0}
    for row in rows:
        if revert:
            res = await _apply_revert(db, row, owner["id"], approval_ref)
        elif row["action"] == "flag":
            res = await _apply_flag(db, row, owner["id"], approval_ref)
        else:
            continue
        outcome[res] = outcome.get(res, 0) + 1
    result.update({"applied": True, **outcome})
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="MEDIA-SEC-01 legacy avatar backfill (R83-4)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--revert", action="store_true")
    ap.add_argument("--approved-by", help="the user id of an active Owner of the tenant")
    ap.add_argument("--plan-sha")
    ap.add_argument("--approval-ref",
                    help="optional (FG-692 prep): where Krum's \"да\" was given; stored in the AuditEvent")
    args = ap.parse_args(argv)
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    try:
        res = asyncio.run(migrate(db, apply=args.apply, approved_by=args.approved_by,
                                  plan_sha=args.plan_sha, revert=args.revert,
                                  approval_ref=args.approval_ref))
    except (PlanMismatch, NotApproved) as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
