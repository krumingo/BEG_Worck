#!/usr/bin/env python3
"""
ST-01 — synthetic staging fixtures: tenants A and B with every release-gate role.

Source: docs/architecture/tasks/ST-01_STAGING_FIXTURES_SCENARIOS.md and the
"Krum's acceptance scenarios" table of PR #64 ``02-release-gates.md`` (steps 6-7).
FLOW-002 (users/roles), FLOW-050 (tenants), FLOW-040 (AuditEvent), FLOW-042 (QA).

What it writes, and only into a database the operator names explicitly:

* two tenants through the canonical onboarding path
  (:func:`app.tenancy.onboarding.onboard_tenant`) — organization, owner user,
  Tenant Registry record, TenantMembership and the FLOW-002 owner RoleAssignment;
* per tenant one user for each role in ``st01_fixture.json`` (users.role for
  off/shadow, a company-scoped RoleAssignment for enforce, a TenantMembership);
* per tenant a synthetic project, a warehouse and an active subscription row so
  the M2 routes the scenarios use are reachable (no billing provider is called);
* one canonical AuditEvent (FLOW-002, R3) for every user created or changed.

Every record carries ``synthetic_fixture: "st-01"``. Re-running changes nothing
that is already right (no duplicate tenant, user, membership, assignment,
project, warehouse or AuditEvent).

Refusals (exit 2, nothing written):

* no MongoDB URL; a ``--db``/``--system-db`` that is a production name
  (``begwork*``, $DB_NAME/$BEG_SYSTEM_DB of this shell) — even with ``--allow-remote``;
* ``--confirm-db`` does not repeat ``--db``;
* a non-local server (anything but plain ``mongodb://`` on localhost/127.0.0.1/::1)
  unless ``--allow-remote`` is given (an isolated staging server; never production);
* a target database that already holds a single non-synthetic user,
  organization or registry tenant.

The password comes from ``$ST01_SEED_PASSWORD`` (or ``--password-env NAME``) or,
on a terminal, from a hidden prompt. It is never printed, logged or stored
outside the bcrypt hash. Usage: see ops/staging/README.md.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
BACKEND = REPO / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

FIXTURE_PATH = HERE / "st01_fixture.json"
MARKER_FIELD = "synthetic_fixture"
MARKER = "st-01"
ACTOR = "st01.seed_synthetic"
DEFAULT_PASSWORD_ENV = "ST01_SEED_PASSWORD"
MIN_PASSWORD_LENGTH = 12
#: Fixed namespace so record ids are the same on every run and every machine.
NAMESPACE = uuid.UUID("5f0b5a52-57a1-4e1c-9c1e-0000000000a1")

EXIT_OK, EXIT_REFUSED = 0, 2


class SeedRefused(Exception):
    """The target or the input is not acceptable; nothing was written."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_fixture(path: Path = FIXTURE_PATH) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def stable_id(*parts: str) -> str:
    return str(uuid.uuid5(NAMESPACE, ":".join(("st01",) + tuple(parts))))


def user_email(tenant: Dict[str, Any], role: Dict[str, Any]) -> str:
    return "st01.%s@%s" % (role["key"], tenant["email_domain"])


# ═══════════════════════════════════════════════════════════════════ target checks
def check_target(*, url: str, db_name: str, system_db_name: str,
                 confirm_db: Optional[str], allow_remote: bool,
                 env: Optional[Dict[str, str]] = None) -> None:
    """Raise :class:`SeedRefused` unless the target may receive synthetic data."""
    from app.master_data import index_bootstrap as ib
    if not url:
        raise SeedRefused("no --mongo-url and no MONGO_URL")
    prod = ib.production_databases(env)
    for label, name in (("--db", db_name), ("--system-db", system_db_name)):
        if not name or not name.strip():
            raise SeedRefused("%s is required" % label)
        if name in prod or name.lower().startswith(ib.PRODUCTION_PREFIX):
            raise SeedRefused("%s %r is a production name" % (label, name))
    if db_name == system_db_name:
        raise SeedRefused("--db and --system-db must be different databases")
    if confirm_db != db_name:
        raise SeedRefused("--confirm-db does not repeat --db")
    if allow_remote:
        return
    from scripts.w0_03c_master_data_uniqueness import parse_mongo_url
    try:
        scheme, hosts = parse_mongo_url(url)
        ib.check_local(hosts=hosts, scheme=scheme)
    except (ib.TargetRefused, ValueError) as exc:
        raise SeedRefused("%s (a staging server needs --allow-remote; production never)" % exc)


def read_password(env_name: str, env: Optional[Dict[str, str]] = None,
                  interactive: Optional[bool] = None) -> str:
    env = os.environ if env is None else env
    value = env.get(env_name, "")
    if not value:
        if interactive is None:
            interactive = sys.stdin.isatty()
        if not interactive:
            raise SeedRefused("no password: set $%s or run on a terminal" % env_name)
        value = getpass.getpass("ST-01 synthetic password: ")
        if value != getpass.getpass("repeat: "):
            raise SeedRefused("the two passwords differ")
    if len(value) < MIN_PASSWORD_LENGTH:
        raise SeedRefused("the password must have at least %d characters" % MIN_PASSWORD_LENGTH)
    return value


async def _foreign_records(op_db, system_db) -> List[str]:
    """Names of collections holding anything that is NOT an ST-01 synthetic record."""
    not_ours = {MARKER_FIELD: {"$ne": MARKER}}
    found = []
    for label, coll in (("users", op_db["users"]), ("organizations", op_db["organizations"]),
                        ("tenant_registry", system_db["tenant_registry"])):
        if await coll.count_documents(not_ours, limit=1):
            found.append(label)
    return found


# ═══════════════════════════════════════════════════════════════════ seed
async def _audit(op_db, tenant_id: str, action: str, user_id: str, diff: Dict[str, Any],
                 reason: str) -> None:
    from app.services.user_role_policy import audit_user_change
    await audit_user_change(op_db, tenant_id=tenant_id, actor_id=ACTOR, actor_type="system",
                            action=action, target_id=user_id, diff=diff, reason=reason,
                            tool_or_endpoint="ops/staging/seed_synthetic.py")


async def _upsert_marked(coll, key: Dict[str, Any], doc: Dict[str, Any]) -> str:
    """Insert ``doc`` once; afterwards only re-assert the fields that drifted."""
    existing = await coll.find_one(key, {"_id": 0})
    if existing is None:
        await coll.insert_one(dict(doc))
        return "created"
    drift = {k: v for k, v in doc.items()
             if k not in ("created_at", "updated_at") and existing.get(k) != v}
    if not drift:
        return "unchanged"
    drift["updated_at"] = _now()
    await coll.update_one(key, {"$set": drift})
    return "updated"


async def _ensure_tenant(op_db, system_db, t: Dict[str, Any], owner_role: Dict[str, Any],
                         password_hash: str, report: Dict[str, Any]) -> Dict[str, Any]:
    from app.tenancy.onboarding import OnboardingRefused, onboard_tenant
    record = await system_db["tenant_registry"].find_one({"slug": t["slug"]}, {"_id": 0})
    if record is None:
        try:
            out = await onboard_tenant(
                op_db, system_db, org_name=t["name"], owner_email=user_email(t, owner_role),
                owner_password_hash=password_hash, owner_first_name="ST01 %s" % t["key"],
                owner_last_name=owner_role["key"], owner_role=owner_role["legacy_role"],
                plan="enterprise")
        except OnboardingRefused as exc:
            raise SeedRefused("tenant %s: %s (%s) — reset this disposable database"
                              % (t["key"], exc, exc.code))
        tenant_id = out["tenant"]["id"]
        mark = {"$set": {MARKER_FIELD: MARKER, "fixture_key": t["key"]}}
        await system_db["tenant_registry"].update_one({"id": tenant_id}, mark)
        await op_db["organizations"].update_one({"id": tenant_id}, mark)
        await op_db["users"].update_one({"id": out["owner"]["id"], "org_id": tenant_id},
                                        {"$set": {MARKER_FIELD: MARKER, "fixture_role": "owner"}})
        await system_db["tenant_memberships"].update_many({"tenant_id": tenant_id},
                                                          {"$set": {MARKER_FIELD: MARKER}})
        await system_db["tenant_role_assignments"].update_many({"tenant_id": tenant_id},
                                                               {"$set": {MARKER_FIELD: MARKER}})
        await _audit(op_db, tenant_id, "user.seed_synthetic", out["owner"]["id"],
                     {"after": {"role": owner_role["legacy_role"], "is_active": True}},
                     "ST-01 synthetic owner onboarded")
        report["created"]["tenants"] += 1
        report["created"]["users"] += 1
        record = await system_db["tenant_registry"].find_one({"id": tenant_id}, {"_id": 0})
    elif record.get(MARKER_FIELD) != MARKER or record.get("fixture_key") != t["key"]:
        raise SeedRefused("slug %r belongs to a non-ST-01 tenant" % t["slug"])
    return record


async def _ensure_user(op_db, system_db, tenant_id: str, t: Dict[str, Any],
                       role: Dict[str, Any], password: str, password_hash: str,
                       report: Dict[str, Any]) -> Dict[str, Any]:
    from app.deps.auth import verify_password
    from app.permissions.catalog import LEGACY_ROLE_MAP
    from app.tenancy.identity import normalize_email
    email = normalize_email(user_email(t, role))
    rows = await op_db["users"].find({"email": email}, {"_id": 0}).to_list(10)
    if len(rows) > 1 or (rows and rows[0].get("org_id") != tenant_id):
        raise SeedRefused("email of role %s/%s is held by another user" % (t["key"], role["key"]))
    now = _now()
    if not rows:
        user_id = stable_id(t["key"], "user", role["key"])
        user = {"id": user_id, "org_id": tenant_id, "email": email,
                "password_hash": password_hash, "first_name": "ST01 %s" % t["key"],
                "last_name": role["key"], "role": role["legacy_role"], "phone": "",
                "is_active": True, "created_at": now, "updated_at": now,
                MARKER_FIELD: MARKER, "fixture_role": role["key"]}
        await op_db["users"].insert_one(dict(user))
        await _audit(op_db, tenant_id, "user.seed_synthetic", user_id,
                     {"after": {"role": role["legacy_role"], "is_active": True}},
                     "ST-01 synthetic user created")
        report["created"]["users"] += 1
    else:
        user = rows[0]
        user_id = user["id"]
        fix: Dict[str, Any] = {}
        if user.get("role") != role["legacy_role"]:
            fix["role"] = role["legacy_role"]
        if not user.get("is_active", True):
            fix["is_active"] = True
        if user.get(MARKER_FIELD) != MARKER or user.get("fixture_role") != role["key"]:
            fix.update({MARKER_FIELD: MARKER, "fixture_role": role["key"]})
        password_changed = not verify_password(password, user.get("password_hash") or "")
        if password_changed:
            fix["password_hash"] = password_hash
        if fix:
            fix["updated_at"] = now
            await op_db["users"].update_one({"id": user_id, "org_id": tenant_id}, {"$set": fix})
            diff = {"before": {k: user.get(k) for k in ("role", "is_active") if k in fix},
                    "after": {k: fix[k] for k in ("role", "is_active") if k in fix}}
            await _audit(op_db, tenant_id, "user.seed_synthetic_update", user_id, diff,
                         "ST-01 synthetic user re-asserted"
                         + (" (password reset to the seed password)" if password_changed else ""))
            report["updated"]["users"] += 1
        else:
            report["unchanged"]["users"] += 1

    membership = {"id": "tm_%s_%s" % (user_id, tenant_id), "user_id": user_id,
                  "tenant_id": tenant_id, "email": email, "status": "active",
                  "is_owner": role["legacy_role"] == "Owner", "created_at": now,
                  "created_by": ACTOR, MARKER_FIELD: MARKER}
    if role["key"] != "owner":
        state = await _upsert_marked(system_db["tenant_memberships"],
                                     {"user_id": user_id, "tenant_id": tenant_id}, membership)
        report[state]["memberships"] += 1
        role_id = LEGACY_ROLE_MAP.get(role["legacy_role"], role["role_id"])
        assignment = {
            "id": "ra_%s_%s_st01" % (user_id, tenant_id), "user_id": user_id,
            "tenant_id": tenant_id, "role": role["legacy_role"], "role_id": role_id,
            "scope_type": "company", "scope_id": None, "module": None, "permissions": [],
            "max_amount": None, "valid_from": now, "valid_to": None, "status": "active",
            "created_by": ACTOR, "approved_by": None, "revision": 1,
            "created_at": now, "updated_at": now, MARKER_FIELD: MARKER}
        key = {"user_id": user_id, "tenant_id": tenant_id, "created_by": ACTOR}
        existing = await system_db["tenant_role_assignments"].find_one(key, {"_id": 0})
        if existing is None:
            await system_db["tenant_role_assignments"].insert_one(dict(assignment))
            report["created"]["role_assignments"] += 1
        elif existing.get("role_id") != role_id or existing.get("status") != "active":
            await system_db["tenant_role_assignments"].update_one(key, {"$set": {
                "role": role["legacy_role"], "role_id": role_id, "status": "active",
                "revision": int(existing.get("revision") or 1) + 1, "updated_at": now}})
            report["updated"]["role_assignments"] += 1
        else:
            report["unchanged"]["role_assignments"] += 1
    return {"key": role["key"], "id": user_id, "email": email, "role": role["legacy_role"],
            "role_id": role["role_id"], "assumption": bool(role.get("assumption"))}


async def _ensure_baseline(op_db, tenant_id: str, t: Dict[str, Any],
                           report: Dict[str, Any]) -> Dict[str, Any]:
    now = _now()
    project_id = stable_id(t["key"], "project", t["project"]["code"])
    warehouse_id = stable_id(t["key"], "warehouse", t["warehouse"]["code"])
    project = {"id": project_id, "org_id": tenant_id, "code": t["project"]["code"],
               "name": t["project"]["name"], "status": "Active", "type": "Construction",
               "created_at": now, "updated_at": now, MARKER_FIELD: MARKER}
    warehouse = {"id": warehouse_id, "org_id": tenant_id, "code": t["warehouse"]["code"],
                 "name": t["warehouse"]["name"], "type": "central", "active": True,
                 "created_at": now, "updated_at": now, MARKER_FIELD: MARKER}
    subscription = {"id": stable_id(t["key"], "subscription"), "org_id": tenant_id,
                    "plan_id": "enterprise", "status": "active", "provider": "none",
                    "notes": "ST-01 synthetic: no payment provider, no billing write",
                    "created_at": now, "updated_at": now, MARKER_FIELD: MARKER}
    for name, coll, key, doc in (
            ("projects", "projects", {"id": project_id, "org_id": tenant_id}, project),
            ("warehouses", "warehouses", {"id": warehouse_id, "org_id": tenant_id}, warehouse),
            ("subscriptions", "subscriptions", {"org_id": tenant_id}, subscription)):
        state = await _upsert_marked(op_db[coll], key, doc)
        report[state][name] += 1
    return {"project_id": project_id, "project_code": t["project"]["code"],
            "warehouse_id": warehouse_id, "warehouse_code": t["warehouse"]["code"]}


def _empty_counts() -> Dict[str, int]:
    return {k: 0 for k in ("tenants", "users", "memberships", "role_assignments",
                           "projects", "warehouses", "subscriptions")}


async def seed(op_db, system_db, password: str,
               fixture: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create or re-assert tenants A and B. Returns the report (no password, no hash)."""
    from app.deps.auth import hash_password
    fixture = fixture or load_fixture()
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise SeedRefused("the password must have at least %d characters" % MIN_PASSWORD_LENGTH)
    foreign = await _foreign_records(op_db, system_db)
    if foreign:
        raise SeedRefused("the target holds non-synthetic records in %s — ST-01 seeds only "
                          "an empty or ST-01-only database" % ", ".join(foreign))
    roles = fixture["roles"]
    owner_role = next(r for r in roles if r["key"] == "owner")
    password_hash = hash_password(password)
    report: Dict[str, Any] = {
        "schema": "beg.st-01-seed-report/v1", "marker": MARKER, "generated_at": _now(),
        "database": op_db.name, "system_database": system_db.name,
        "created": _empty_counts(), "updated": _empty_counts(), "unchanged": _empty_counts(),
        "tenants": []}
    for t in fixture["tenants"]:
        record = await _ensure_tenant(op_db, system_db, t, owner_role, password_hash, report)
        tenant_id = record["id"]
        users = [await _ensure_user(op_db, system_db, tenant_id, t, role, password,
                                    password_hash, report) for role in roles]
        baseline = await _ensure_baseline(op_db, tenant_id, t, report)
        report["tenants"].append({"key": t["key"], "tenant_id": tenant_id, "name": t["name"],
                                  "slug": t["slug"], "users": users, **baseline})
    report["unchanged"]["tenants"] = len(fixture["tenants"]) - report["created"]["tenants"]
    return report


# ═══════════════════════════════════════════════════════════════════ CLI
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="ST-01 synthetic staging seed (tenants A and B)")
    p.add_argument("--mongo-url", default="", help="defaults to $MONGO_URL; never printed")
    p.add_argument("--db", required=True, help="operational database (the backend's DB_NAME)")
    p.add_argument("--system-db", required=True, help="system database (the backend's BEG_SYSTEM_DB)")
    p.add_argument("--confirm-db", default=None, help="repeat --db to confirm")
    p.add_argument("--allow-remote", action="store_true",
                   help="allow a non-local isolated staging server (never production)")
    p.add_argument("--password-env", default=DEFAULT_PASSWORD_ENV,
                   help="environment variable holding the password (default %(default)s)")
    p.add_argument("--out", default="", help="write the report (no secrets) to this file")
    return p


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    url = args.mongo_url or os.environ.get("MONGO_URL", "")
    try:
        check_target(url=url, db_name=args.db, system_db_name=args.system_db,
                     confirm_db=args.confirm_db, allow_remote=args.allow_remote)
        password = read_password(args.password_env)
    except SeedRefused as exc:
        print("refused: %s" % exc, file=sys.stderr)
        return EXIT_REFUSED
    from motor.motor_asyncio import AsyncIOMotorClient

    async def run():
        client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=5000)
        try:
            return await seed(client[args.db], client[args.system_db], password)
        finally:
            client.close()
    try:
        report = asyncio.run(run())
    except SeedRefused as exc:
        print("refused: %s" % exc, file=sys.stderr)
        return EXIT_REFUSED
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
