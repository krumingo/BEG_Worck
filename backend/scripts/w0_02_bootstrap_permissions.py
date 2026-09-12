#!/usr/bin/env python3
"""
W0-02 — Upgrade legacy RoleAssignment mirrors to the authoritative FLOW-002 shape.

What it does:
  * reads existing tenant_role_assignments in the SYSTEM database (the legacy
    mirrors written by W0-01, migrated_from="users.role");
  * upgrades each IN PLACE to the authoritative shape (role_id, module,
    permissions, valid_from/valid_to, max_amount, created_by/approved_by,
    scope_id from scope_ids[0]);
  * creates the W0-02 indexes.

What it does NOT do:
  * it never writes to, alters or deletes anything in the OPERATIONAL database;
  * it never invents business meaning: Technician/Viewer become the transitional
    LEGACY_TECHNICIAN / LEGACY_VIEWER, which reproduce today's behavior only.

Invariant: old real behavior -> transitional RoleAssignment (NOT old name ->
invented canonical role).

Idempotent: running twice changes nothing (conditional upgrade of not-yet-
authoritative mirrors only; create-only backfill). Exit codes: 0 ok,
1 verify mismatch, 2 unique-key conflict detected (nothing written), 3 guard.

Usage:
    python scripts/w0_02_bootstrap_permissions.py            # dry run
    python scripts/w0_02_bootstrap_permissions.py --apply    # write
    python scripts/w0_02_bootstrap_permissions.py --verify   # semantic invariants, exit 1 on mismatch
    python scripts/w0_02_bootstrap_permissions.py --revert          # dry-run of revert
    python scripts/w0_02_bootstrap_permissions.py --revert --apply   # actually revert
"""
import asyncio
import sys
import os
import argparse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from w0_02_validation_env import require_runtime_env

# No dotenv, application import or client construction at module import time.
client = op_db = sys_db = None
MONGO_URL = OPERATIONAL_DB = SYSTEM_DB = None


def _configure_databases():
    global client, op_db, sys_db, MONGO_URL, OPERATIONAL_DB, SYSTEM_DB
    _guard()  # must precede ALL dotenv / driver imports
    if op_db is not None and sys_db is not None:
        return  # explicitly injected DBs in unit/integration tests
    if os.environ.get("BEG_VALIDATION_MODE") != "1":
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).parent.parent / ".env")
    MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
    OPERATIONAL_DB = os.environ.get("DB_NAME", "begwork")
    SYSTEM_DB = os.environ.get("BEG_SYSTEM_DB", "begwork_system")
    _guard()
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=5000,
                               connectTimeoutMS=5000, socketTimeoutMS=15000)
    op_db, sys_db = client[OPERATIONAL_DB], client[SYSTEM_DB]


# ---------------------------------------------------------------------------
# PR-01 — migration ownership, idempotency, limited revert.
#
# Provenance is NOT the business marker: `migrated_from="project_team"` is also
# written by app-created project mirrors, so it proves nothing about who owns a
# record. Ownership is recorded in a technical migration journal (system DB,
# collection `migration_journal`, keyed by MIGRATION_ID) with the exact
# before/after image of every document this run changed or created, plus the
# indexes it created. Revert consults ONLY that journal. This is technical
# migration history, not a second business ledger.
# ---------------------------------------------------------------------------
MIGRATION_ID = "w0-02-permissions"
JOURNAL = "migration_journal"
W0_02_INDEXES = ["uniq_assignment", "lookup_active", "by_role", "by_scope"]
UNIQUE_KEY = ("user_id", "tenant_id", "role_id", "scope_type", "scope_id", "module")

EXIT_OK, EXIT_VERIFY_FAILED, EXIT_CONFLICT = 0, 1, 2


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip(doc):
    return None if doc is None else {k: v for k, v in doc.items() if k != "_id"}


def _key(doc: dict) -> tuple:
    return tuple(doc.get(f) for f in UNIQUE_KEY)


def upgrade_assignment(old: dict) -> dict:
    from app.permissions.catalog import LEGACY_ROLE_MAP
    role_id = LEGACY_ROLE_MAP.get(old.get("role", ""), "LEGACY_" + str(old.get("role", "UNKNOWN")).upper())
    scope_ids = old.get("scope_ids") or []
    return {
        **old,
        "role_id": role_id,
        "scope_type": old.get("scope_type", "company"),
        "scope_id": scope_ids[0] if scope_ids else None,
        "module": None,
        "permissions": [],                       # inherit from role catalog
        "max_amount": None,
        "valid_from": old.get("created_at") or now(),
        "valid_to": None,
        "status": old.get("status", "active"),
        "created_by": old.get("created_by", "system:migration"),
        "approved_by": old.get("approved_by"),
        "note": "W0-02 upgrade of legacy mirror. LEGACY_* = compat only, not FLOW-002 canon.",
    }


def _guard() -> None:
    if os.environ.get("BEG_VALIDATION_MODE") == "1":
        require_runtime_env()  # validate LIVE inputs, not expected against itself


def is_upgrade_candidate(doc: dict) -> bool:
    """Only W0-01 legacy mirrors that are not yet authoritative (PR-01 §1).

    App-owned records and already-upgraded mirrors are never rebuilt from the
    old `role` string on a re-run.
    """
    return doc.get("migrated_from") == "users.role" and "role_id" not in doc


async def build_backfill() -> list:
    """Project-scope assignments from active project_team memberships.

    Reproduces legacy membership access: any active member gets project
    budget.read; a member whose role_in_project is SiteManager also gets
    budget.write (matches can_access_project / can_manage_project). Admin/Owner
    are skipped — they already have company-wide access.
    """
    from app.permissions.catalog import (
        LEGACY_ROLE_MAP, PROJECT_MEMBER_ACTIONS, PROJECT_MANAGER_ACTIONS,
    )
    users = {u["id"]: u for u in await op_db.users.find({}, {"_id": 0}).to_list(100000)}
    members = await op_db.project_team.find({"active": True}, {"_id": 0}).to_list(100000)
    out = []
    for m in members:
        u = users.get(m.get("user_id"))
        if not u or u.get("role") in ("Admin", "Owner"):
            continue
        tid = u.get("org_id")
        if not tid or not m.get("project_id"):
            continue
        is_mgr = m.get("role_in_project") == "SiteManager"
        role_id = LEGACY_ROLE_MAP.get(u.get("role", ""), "LEGACY_" + str(u.get("role", "")).upper())
        out.append({
            "id": f"ra_{m['user_id']}_{tid}_proj_{m['project_id']}",
            "user_id": m["user_id"], "tenant_id": tid,
            "role_id": role_id,
            "scope_type": "project", "scope_id": m["project_id"], "module": None,
            "permissions": list(PROJECT_MANAGER_ACTIONS if is_mgr else PROJECT_MEMBER_ACTIONS),
            "max_amount": None, "valid_from": now(), "valid_to": None,
            "status": "active", "created_by": "system:migration", "approved_by": None,
            "migrated_from": "project_team",
            "note": "W0-02 project-scope backfill from project_team membership.",
        })
    return out


def find_conflicts(plan: list, backfill: list, existing: list) -> list:
    """Collisions on the unique compound key BEFORE any write (PR-01 §2).

    An upgrade may only take a key nobody else owns; a backfill row is skipped
    silently when its own id already exists (create-only), but it is a conflict
    when ANOTHER document owns its key or its id with a different key.
    """
    by_key, by_id = {}, {}
    for d in existing:
        by_id[d["id"]] = d
        if "role_id" in d:                       # only authoritative docs carry the key
            by_key.setdefault(_key(d), []).append(d["id"])
    conflicts = []
    seen = {}
    for u in plan:
        k = _key(u)
        owners = [i for i in by_key.get(k, []) if i != u["id"]]
        if owners or k in seen:
            conflicts.append({"kind": "upgrade", "id": u["id"], "key": k,
                              "conflicts_with": owners or [seen[k]]})
        seen[k] = u["id"]
    for b in backfill:
        k = _key(b)
        cur = by_id.get(b["id"])
        if cur is not None:
            if "role_id" in cur and _key(cur) != k:
                conflicts.append({"kind": "backfill", "id": b["id"], "key": k,
                                  "conflicts_with": [f"{b['id']} (same id, different key)"]})
            continue                              # exists -> create-only skip
        owners = by_key.get(k, [])
        if owners or k in seen:
            conflicts.append({"kind": "backfill", "id": b["id"], "key": k,
                              "conflicts_with": owners or [seen[k]]})
        seen[k] = b["id"]
    return conflicts


async def _journal(kind: str, assignment_id, before, after, extra=None):
    entry = {"migration_id": MIGRATION_ID, "kind": kind, "assignment_id": assignment_id,
             "before": _strip(before), "after": _strip(after), "applied_at": now(),
             "reverted_at": None}
    if extra:
        entry.update(extra)
    await sys_db[JOURNAL].insert_one(entry)


async def _apply(plan: list, backfill: list) -> dict:
    stats = {"upgraded": 0, "upgrade_skipped": 0, "backfilled": 0, "backfill_existing": 0,
             "indexes_created": []}
    coll = sys_db.tenant_role_assignments
    for a in plan:
        before = await coll.find_one({"id": a["id"]}, {"_id": 0})
        # Conditional: only the still-legacy mirror is upgraded; a re-run or a
        # concurrent app change cannot be overwritten (PR-01 §1/§3).
        res = await coll.update_one(
            {"id": a["id"], "migrated_from": "users.role", "role_id": {"$exists": False}},
            {"$set": a})
        if res.matched_count == 1:
            after = await coll.find_one({"id": a["id"]}, {"_id": 0})
            await _journal("upgraded", a["id"], before, after)
            stats["upgraded"] += 1
        else:
            stats["upgrade_skipped"] += 1
    for a in backfill:
        # Create-only: an existing assignment keeps status, permissions, limits,
        # validity and revoke fields untouched (PR-01 §3).
        res = await coll.update_one({"id": a["id"]}, {"$setOnInsert": a}, upsert=True)
        if getattr(res, "upserted_id", None) is not None:
            after = await coll.find_one({"id": a["id"]}, {"_id": 0})
            await _journal("created", a["id"], None, after)
            stats["backfilled"] += 1
        else:
            stats["backfill_existing"] += 1
    # Indexes: only the ones this run actually creates are owned by it (§6).
    before_idx = set((await coll.index_information()).keys())
    from app.tenancy import registry
    await registry.ensure_permission_indexes(collection=coll)
    after_idx = set((await coll.index_information()).keys())
    for name in sorted(after_idx - before_idx):
        await _journal("index", None, None, {"name": name}, {"index_name": name})
        stats["indexes_created"].append(name)
    return stats


async def _revert(apply: bool) -> int:
    """Limited rollback: ONLY documents/indexes recorded in this migration's
    journal, and ONLY while their current content is exactly the journaled
    after-image. Anything changed since (revoke, expiry, app edits) is kept
    and reported as SKIPPED_MODIFIED (PR-01 §5/§6). Audit history is never touched."""
    coll = sys_db.tenant_role_assignments
    entries = await sys_db[JOURNAL].find(
        {"migration_id": MIGRATION_ID, "reverted_at": None}).sort("applied_at", -1).to_list(100000)
    print(f"REVERT ({'APPLY' if apply else 'DRY RUN'}): journal entries to consider: {len(entries)}")
    restored = removed = skipped = 0
    for e in entries:
        kind = e["kind"]
        if kind == "index":
            continue
        current = _strip(await coll.find_one({"id": e["assignment_id"]}))
        if current != e["after"]:
            skipped += 1
            print(f"  SKIPPED_MODIFIED id={e['assignment_id']} kind={kind}: current content "
                  f"differs from the migration's after-image (legitimately changed since apply)")
            if apply:
                await sys_db[JOURNAL].update_one(
                    {"_id": e["_id"]}, {"$set": {"revert_skipped_at": now(),
                                                 "revert_skipped_reason": "SKIPPED_MODIFIED"}})
            continue
        if kind == "upgraded":
            print(f"  RESTORE id={e['assignment_id']}: exact before-image")
            if apply:
                await coll.replace_one({"id": e["assignment_id"]}, e["before"])
            restored += 1
        elif kind == "created":
            print(f"  REMOVE id={e['assignment_id']}: created by this migration, untouched since")
            if apply:
                await coll.delete_one({"id": e["assignment_id"]})
            removed += 1
        if apply:
            await sys_db[JOURNAL].update_one({"_id": e["_id"]}, {"$set": {"reverted_at": now()}})
    idx_entries = [e for e in entries if e["kind"] == "index"]
    existing_idx = set((await coll.index_information()).keys())
    for e in idx_entries:
        name = e["index_name"]
        if name in existing_idx:
            print(f"  DROP INDEX {name}: created by this migration")
            if apply:
                await coll.drop_index(name)
        if apply:
            await sys_db[JOURNAL].update_one({"_id": e["_id"]}, {"$set": {"reverted_at": now()}})
    print(f"restored={restored} removed={removed} skipped_modified={skipped} "
          f"indexes={len(idx_entries)}")
    if not apply:
        print("DRY RUN — nothing written. Re-run with --revert --apply to revert.")
    else:
        print("Reverted (limited to this migration's own changes).")
    return EXIT_OK


async def _verify() -> int:
    """Semantic invariants (PR-01 §7). Read-only. Non-zero on any violation.
    A later legitimate revoke/expiry is NOT a violation."""
    from app.permissions.catalog import LEGACY_ROLE_MAP
    coll = sys_db.tenant_role_assignments
    problems = []
    docs = await coll.find({}, {"_id": 0}).to_list(100000)
    # 1. every legacy mirror is authoritative
    for d in docs:
        if d.get("migrated_from") == "users.role" and "role_id" not in d:
            problems.append(f"legacy mirror not upgraded: {d['id']}")
        if "role_id" in d:
            expected = LEGACY_ROLE_MAP.get(d.get("role", ""), d.get("role_id"))
            if d.get("migrated_from") == "users.role" and d.get("role_id") != expected:
                problems.append(f"role mapping mismatch: {d['id']} role={d.get('role')} role_id={d.get('role_id')}")
    # 2. unique compound key holds across ALL documents
    seen = {}
    for d in docs:
        if "role_id" not in d:
            continue
        k = _key(d)
        if k in seen:
            problems.append(f"duplicate unique key: {seen[k]} and {d['id']}")
        seen[k] = d["id"]
    # 3. every active non-admin membership has a project mirror (any status)
    users = {u["id"]: u for u in await op_db.users.find({}, {"_id": 0}).to_list(100000)}
    members = await op_db.project_team.find({"active": True}, {"_id": 0}).to_list(100000)
    mirrors = {(d.get("user_id"), d.get("tenant_id"), d.get("scope_id"))
               for d in docs if d.get("scope_type") == "project"}
    for m in members:
        u = users.get(m.get("user_id"))
        if not u or u.get("role") in ("Admin", "Owner") or not u.get("org_id") or not m.get("project_id"):
            continue
        if (m["user_id"], u["org_id"], m["project_id"]) not in mirrors:
            problems.append(f"missing project mirror for user={m['user_id']} project={m['project_id']}")
    # 4. journal integrity: every non-reverted 'created' entry still exists
    async for e in sys_db[JOURNAL].find({"migration_id": MIGRATION_ID, "reverted_at": None, "kind": "created"}):
        if await coll.find_one({"id": e["assignment_id"]}) is None:
            problems.append(f"journaled created record missing: {e['assignment_id']}")
    # 5. required indexes exist
    have = set((await coll.index_information()).keys())
    for name in W0_02_INDEXES:
        if name not in have:
            problems.append(f"missing index: {name}")
    upgraded = sum(1 for d in docs if "role_id" in d)
    print(f"Authoritative documents: {upgraded}/{len(docs)}; journal entries: "
          f"{await sys_db[JOURNAL].count_documents({'migration_id': MIGRATION_ID})}")
    if problems:
        print("VERIFY FAILED:")
        for p in problems:
            print("  - " + p)
        return EXIT_VERIFY_FAILED
    print("VERIFY OK — all W0-02 invariants hold.")
    return EXIT_OK


async def run(apply: bool, verify_only: bool, revert: bool) -> int:
    _guard()
    _configure_databases()
    all_docs = await sys_db.tenant_role_assignments.find({}, {"_id": 0}).to_list(100000)
    olds = [d for d in all_docs if is_upgrade_candidate(d)]
    before = (await op_db.users.count_documents({}), await op_db.organizations.count_documents({}))

    print(f"System database    : {SYSTEM_DB}")
    print(f"Assignments found  : {len(all_docs)} (upgrade candidates: {len(olds)})")
    print(f"Operational (before): users={before[0]} orgs={before[1]}")
    print()

    if verify_only:
        return await _verify()

    if revert:
        return await _revert(apply)

    plan = [upgrade_assignment(o) for o in olds]
    backfill = await build_backfill()
    print("Planned upgrades (role -> role_id):")
    seen = {}
    for o in plan:
        seen[o["role_id"]] = seen.get(o["role_id"], 0) + 1
    for rid, n in sorted(seen.items()):
        tag = "" if rid in {"owner", "admin", "site_manager", "accountant", "warehouse", "driver"} else "  (transitional)"
        print(f"  - {rid}: {n}{tag}")
    print(f"Planned project-scope backfill (from project_team): {len(backfill)}")

    conflicts = find_conflicts(plan, backfill, all_docs)
    if conflicts:
        print(f"\nCONFLICTS on the unique compound key ({len(conflicts)}) — nothing written:")
        for c in conflicts:
            print(f"  - {c['kind']} id={c['id']} key={c['key']} conflicts_with={c['conflicts_with']}")
        return EXIT_CONFLICT

    if not apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to write.")
        return EXIT_OK

    stats = await _apply(plan, backfill)

    after = (await op_db.users.count_documents({}), await op_db.organizations.count_documents({}))
    assert after == before, f"OPERATIONAL DB CHANGED! before={before} after={after}"
    print(f"\nUpgraded {stats['upgraded']} (skipped {stats['upgrade_skipped']}), "
          f"backfilled {stats['backfilled']} (existing kept {stats['backfill_existing']}), "
          f"indexes created {stats['indexes_created']}")
    print(f"Operational database untouched: users={after[0]} orgs={after[1]}")
    print("W0-02 permission bootstrap complete.")
    return EXIT_OK


def _parse_args(argv):
    p = argparse.ArgumentParser(
        prog="w0_02_bootstrap_permissions.py",
        description=("W0-02: upgrade legacy RoleAssignment mirrors to the authoritative "
                     "FLOW-002 shape and backfill project-scope assignments from project_team. "
                     "Default is a DRY RUN; use --apply to write."),
        epilog=("Examples:\n"
                "  python w0_02_bootstrap_permissions.py            # dry-run\n"
                "  python w0_02_bootstrap_permissions.py --apply    # write upgrades + backfill\n"
                "  python w0_02_bootstrap_permissions.py --verify   # counts only\n"
                "  python w0_02_bootstrap_permissions.py --revert          # dry-run of revert\n"
                "  python w0_02_bootstrap_permissions.py --revert --apply  # actually revert\n"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--apply", action="store_true",
                   help="actually write (without it, everything is a dry run)")
    p.add_argument("--verify", action="store_true",
                   help="check the W0-02 invariants (read-only); exit 1 on any mismatch")
    p.add_argument("--revert", action="store_true",
                   help="revert mode; combine with --apply to actually strip W0-02 changes")
    return p.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args(sys.argv[1:])
    try:
        sys.exit(asyncio.run(run(apply=args.apply, verify_only=args.verify, revert=args.revert)))
    finally:
        if client is not None:
            client.close()
