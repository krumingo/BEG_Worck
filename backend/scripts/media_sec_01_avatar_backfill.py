#!/usr/bin/env python3
"""
MEDIA-SEC-01 / R83(4) — mark the LEGACY avatars that ``GET /api/media/avatar/...`` may serve.

Since MEDIA-SEC-01 an avatar is served only from a ``media_files`` row with ``avatar: true``,
which ``POST /media/upload`` sets for a fresh ``context_type="profile"`` upload (R83(3)).
Avatars uploaded before that have no flag, so they show initials until this backfill is
applied. Krum, 10.11.2026 (R83(4)): dry run that only counts; an idempotent apply with an
AuditEvent; never run automatically — the deploy needs Krum's "да".

What is marked — and nothing else is guessed. For every user whose ``avatar_url`` is
``/api/media/avatar/<name>`` or ``/api/media/file/<name>``:

* ``flag`` — a ``media_files`` row of the SAME tenant with that stored name, not retired,
  ``context_type="profile"`` and ``context_id`` = that user: the row gets
  ``avatar: true`` (and the user's ``avatar_url`` its ``/api/media/avatar/`` form when it
  used the ``/file/`` form). One transaction per user with the canonical AuditEvent
  ``media.avatar.backfill`` (actor ``system``, approver in the diff);
* ``already`` — the row is flagged and the URL is in avatar form: nothing to do;
* ``skip:<reason>`` — no such row in the tenant, another context, another user's profile,
  retired, or a URL of another shape. Reported only; a person decides (re-upload).

Properties (the PRJ-01 migration pattern):

* **Dry run by default.** Prints the plan, the counts and its SHA-256; writes nothing.
* ``--apply`` needs ``--approved-by`` and ``--plan-sha`` equal to the plan of the moment
  (else ``PlanMismatch`` / ``NotApproved``, nothing written).
* **Idempotent.** A second apply finds every row ``already`` and writes nothing.

    MONGO_URL=... DB_NAME=... python scripts/media_sec_01_avatar_backfill.py
    MONGO_URL=... DB_NAME=... python scripts/media_sec_01_avatar_backfill.py \\
        --apply --approved-by "Крум" --plan-sha <sha from the dry run>

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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def build_plan(db) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    users = await db.users.find({"avatar_url": {"$nin": [None, ""]}},
                                {"_id": 0, "id": 1, "org_id": 1, "avatar_url": 1}
                                ).sort([("org_id", 1), ("id", 1)]).to_list(None)
    for u in users:
        row = {"org_id": u.get("org_id"), "user_id": u.get("id"), "avatar_url": u.get("avatar_url")}
        m = _URL.fullmatch(u.get("avatar_url") or "")
        if not m or not u.get("org_id"):
            rows.append({**row, "action": "skip:url_shape"})
            continue
        form, name = m.group(1), m.group(2)
        media = await db.media_files.find_one({"stored_filename": name, "org_id": u["org_id"]},
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
        elif media.get("avatar") is True and form == "avatar":
            row["action"] = "already"
        else:
            row["action"] = "flag"
            row["new_avatar_url"] = "/api/media/avatar/%s" % name
        rows.append(row)
    return rows


def plan_sha(rows: List[Dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False)
                          .encode("utf-8")).hexdigest()


def counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in rows:
        out[r["action"]] = out.get(r["action"], 0) + 1
    return dict(sorted(out.items()))


async def _apply_row(db, row: Dict[str, Any], approved_by: str) -> bool:
    """One user, one transaction. Returns whether anything was written."""
    from app.audit.envelope import ACTOR_SYSTEM, RETENTION_R1_CRITICAL_BUSINESS, build_event
    from app.audit.store import record_event
    from app.services.auth_tx import run_in_transaction

    if row["action"] != "flag":
        return False

    async def body(session):
        res = await db.media_files.update_one(
            {"id": row["media_id"], "org_id": row["org_id"], "stored_filename": row["stored_filename"],
             "context_type": "profile", "context_id": row["user_id"],
             "status": {"$ne": "retired"}},
            {"$set": {"avatar": True, "avatar_backfill": MIGRATION, "avatar_backfill_at": _now()}},
            session=session)
        if res.matched_count != 1:
            return False                      # changed since the plan: nothing, a re-run decides
        url_changed = row["avatar_url"] != row["new_avatar_url"]
        if url_changed:
            await db.users.update_one({"id": row["user_id"], "org_id": row["org_id"],
                                       "avatar_url": row["avatar_url"]},
                                      {"$set": {"avatar_url": row["new_avatar_url"]}},
                                      session=session)
        event = build_event(
            tenant_id=row["org_id"], actor_type=ACTOR_SYSTEM, actor_id="migration:%s" % MIGRATION,
            action="media.avatar.backfill", source_flow="FLOW-029",
            retention_class=RETENTION_R1_CRITICAL_BUSINESS, entity_type="media_file",
            entity_id=row["media_id"], reason="legacy avatar marked (R83-4)",
            structured_diff={"user_id": row["user_id"],
                             "before": {"avatar": None, "avatar_url": row["avatar_url"]},
                             "after": {"avatar": True, "avatar_url": row["new_avatar_url"]},
                             "approved_by": approved_by},
            tool_or_endpoint="scripts/media_sec_01_avatar_backfill.py", source_channel="migration")
        await record_event(db, event, session=session)
        return True

    return bool(await run_in_transaction(db, body))


async def migrate(db, apply: bool = False, approved_by: Optional[str] = None,
                  plan_sha: Optional[str] = None) -> Dict[str, Any]:
    rows = await build_plan(db)
    sha = globals()["plan_sha"](rows)
    result = {"plan": rows, "plan_sha": sha, "counts": counts(rows), "applied": False}
    if not apply:
        return result
    if not (approved_by or "").strip():
        raise NotApproved("--apply needs --approved-by")
    if plan_sha != sha:
        raise PlanMismatch("the approved plan is not the current plan — run the dry run again")
    written = 0
    for row in rows:
        written += bool(await _apply_row(db, row, approved_by.strip()))
    result.update({"applied": True, "written": written})
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="MEDIA-SEC-01 legacy avatar backfill (R83-4)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--approved-by")
    ap.add_argument("--plan-sha")
    args = ap.parse_args(argv)
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    try:
        res = asyncio.run(migrate(db, apply=args.apply, approved_by=args.approved_by,
                                  plan_sha=args.plan_sha))
    except (PlanMismatch, NotApproved) as exc:
        print("REFUSED: %s" % exc, file=sys.stderr)
        return 1
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
