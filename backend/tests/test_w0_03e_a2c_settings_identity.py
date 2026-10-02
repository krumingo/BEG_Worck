"""
W0-03E-A2C — per-tenant settings identity, and the migration onto it.

The defect this closes (recorded as unclosed second-tenant debt by the
W0-03E-A2B review): ``worker_rates``, ``employee_cost_config`` and
``overtime_config`` lived in the shared ``settings`` collection under a GLOBAL
literal ``_id``. ``_id`` is unique per collection, so the installation can hold
exactly one of each. The reads already carried ``org_id``, which makes it worse
rather than better: the first tenant to save owns the row, a second tenant's
upsert fails with a duplicate key, and its scoped read then returns nothing — so
it silently falls back to defaults and can never store its own values.

Three things are proven here:

1. the identity helper is total and fails closed;
2. the collision is REAL on the legacy shape and GONE on the new one, shown
   against a database rather than argued;
3. the migration is a dry run by default, idempotent, resumable, never
   overwrites a differing tenant row, and refuses an ownerless row.

In-process against ``mongomock_motor``; no server, no real MongoDB.

    pytest tests/test_w0_03e_a2c_settings_identity.py -v --noconftest
"""
import asyncio

import pytest

from app.tenancy.settings_identity import (
    ALREADY_SCOPED_PREFIXES,
    EMPLOYEE_COST_CONFIG,
    LEGACY_GLOBAL_KEYS,
    OVERTIME_CONFIG,
    SEPARATOR,
    SETTINGS_COLLECTION,
    WORKER_RATES,
    is_legacy_global_id,
    legacy_migration_plan,
    settings_id,
    split_settings_id,
)

ORG_A, ORG_B = "org-aaaa", "org-bbbb"


def _db():
    from mongomock_motor import AsyncMongoMockClient
    return AsyncMongoMockClient()["w0_03e_a2c_settings"]


# ═══════════════════════════════════════════════════════════ 1. the identity
def test_the_three_legacy_keys_are_exactly_the_global_ones():
    assert LEGACY_GLOBAL_KEYS == (WORKER_RATES, EMPLOYEE_COST_CONFIG, OVERTIME_CONFIG)
    assert all(is_legacy_global_id(k) for k in LEGACY_GLOBAL_KEYS)
    assert not is_legacy_global_id("sales_margins_org-aaaa")
    assert not is_legacy_global_id(settings_id(WORKER_RATES, ORG_A))


def test_an_id_is_per_tenant_and_round_trips():
    a = settings_id(WORKER_RATES, ORG_A)
    b = settings_id(WORKER_RATES, ORG_B)
    assert a != b
    assert a == WORKER_RATES + SEPARATOR + ORG_A
    assert split_settings_id(a) == (WORKER_RATES, ORG_A)
    assert split_settings_id(b) == (WORKER_RATES, ORG_B)
    # a legacy global id reports no tenant, which is how the migration spots it
    assert split_settings_id(WORKER_RATES) == (WORKER_RATES, "")


@pytest.mark.parametrize("key,org", [
    (WORKER_RATES, ""), (WORKER_RATES, "   "), (WORKER_RATES, None), (WORKER_RATES, 7),
    ("", ORG_A), ("   ", ORG_A), (None, ORG_A),
    ("bad" + SEPARATOR + "key", ORG_A),
])
def test_an_incomplete_identity_fails_closed(key, org):
    """A missing tenant must never silently produce a global id again."""
    with pytest.raises(ValueError):
        settings_id(key, org)


def test_the_migration_plan_is_deterministic():
    plan = legacy_migration_plan(ORG_A)
    assert set(plan) == set(LEGACY_GLOBAL_KEYS)
    assert plan == legacy_migration_plan(ORG_A)
    assert all(v.endswith(SEPARATOR + ORG_A) for v in plan.values())
    assert legacy_migration_plan(ORG_A) != legacy_migration_plan(ORG_B)


def test_the_already_scoped_rows_are_left_alone():
    """``sales_margins_<org>`` was already per-tenant and is not migrated."""
    assert ALREADY_SCOPED_PREFIXES
    for prefix in ALREADY_SCOPED_PREFIXES:
        assert not any(k.startswith(prefix) for k in LEGACY_GLOBAL_KEYS)


# ═════════════════════════════════════════ 2. the collision, against a database
def test_the_legacy_shape_really_blocks_a_second_tenant():
    """The defect, demonstrated: with a global _id, tenant B cannot save at all."""
    from pymongo.errors import DuplicateKeyError

    async def body():
        db = _db()
        coll = db[SETTINGS_COLLECTION]
        await coll.insert_one({"_id": WORKER_RATES, "org_id": ORG_A, "rates": {"a": 1}})
        # B's scoped read finds nothing — the row exists but belongs to A
        assert await coll.find_one({"_id": WORKER_RATES, "org_id": ORG_B}) is None
        # ...and B's upsert cannot create its own row
        with pytest.raises(DuplicateKeyError):
            await coll.insert_one({"_id": WORKER_RATES, "org_id": ORG_B, "rates": {"b": 2}})
        return await coll.count_documents({})

    assert asyncio.run(body()) == 1


def test_the_new_shape_lets_both_tenants_own_their_row():
    async def body():
        db = _db()
        coll = db[SETTINGS_COLLECTION]
        for org, rates in ((ORG_A, {"a": 1}), (ORG_B, {"b": 2})):
            await coll.update_one(
                {"_id": settings_id(WORKER_RATES, org)},
                {"$set": {"_id": settings_id(WORKER_RATES, org), "org_id": org,
                          "rates": rates}},
                upsert=True)
        a = await coll.find_one({"_id": settings_id(WORKER_RATES, ORG_A), "org_id": ORG_A})
        b = await coll.find_one({"_id": settings_id(WORKER_RATES, ORG_B), "org_id": ORG_B})
        # each tenant sees its own, and neither sees the other's
        assert a["rates"] == {"a": 1} and b["rates"] == {"b": 2}
        assert await coll.find_one({"_id": settings_id(WORKER_RATES, ORG_A),
                                    "org_id": ORG_B}) is None
        return await coll.count_documents({})

    assert asyncio.run(body()) == 2


def test_every_setting_type_is_independent_per_tenant():
    async def body():
        db = _db()
        coll = db[SETTINGS_COLLECTION]
        for key in LEGACY_GLOBAL_KEYS:
            for org in (ORG_A, ORG_B):
                await coll.insert_one({"_id": settings_id(key, org), "org_id": org,
                                       "value": key + org})
        return await coll.count_documents({})

    assert asyncio.run(body()) == len(LEGACY_GLOBAL_KEYS) * 2


# ═══════════════════════════════════════════════════════════ 3. the migration
def _migration():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "scripts" / \
        "w0_03e_a2c_settings_identity_migration.py"
    spec = importlib.util.spec_from_file_location("a2c_settings_migration", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_migration_dry_run_writes_nothing():
    m = _migration()

    async def body():
        db = _db()
        await db[SETTINGS_COLLECTION].insert_one(
            {"_id": WORKER_RATES, "org_id": ORG_A, "rates": {"a": 1}})
        report = await m.migrate(db, apply=False)
        still_there = await db[SETTINGS_COLLECTION].find_one({"_id": WORKER_RATES})
        moved = await db[SETTINGS_COLLECTION].find_one(
            {"_id": settings_id(WORKER_RATES, ORG_A)})
        return report, still_there, moved

    report, still_there, moved = asyncio.run(body())
    assert report["applied"] is False and report["reconciled"] is True
    assert still_there is not None and moved is None
    states = {r["key"]: r["state"] for r in report["results"]}
    assert states[WORKER_RATES] == m.STATE_MIGRATED
    assert states[EMPLOYEE_COST_CONFIG] == m.STATE_ABSENT


def test_the_migration_moves_the_row_and_preserves_every_field():
    m = _migration()

    async def body():
        db = _db()
        row = {"_id": WORKER_RATES, "org_id": ORG_A, "rates": {"майстор": 12.5},
               "updated_at": "2026-04-01T00:00:00", "updated_by": "u1", "extra": [1, 2]}
        await db[SETTINGS_COLLECTION].insert_one(dict(row))
        report = await m.migrate(db, apply=True)
        legacy = await db[SETTINGS_COLLECTION].find_one({"_id": WORKER_RATES})
        new = await db[SETTINGS_COLLECTION].find_one(
            {"_id": settings_id(WORKER_RATES, ORG_A)})
        return report, legacy, new, row

    report, legacy, new, row = asyncio.run(body())
    assert report["applied"] is True and report["reconciled"] is True
    assert legacy is None, "the legacy global row must be gone"
    assert new is not None
    for k, v in row.items():
        if k == "_id":
            continue
        assert new[k] == v, "field %s was not preserved" % k


def test_the_migration_is_idempotent_and_resumable():
    m = _migration()

    async def body():
        db = _db()
        await db[SETTINGS_COLLECTION].insert_one(
            {"_id": WORKER_RATES, "org_id": ORG_A, "rates": {"a": 1}})
        first = await m.migrate(db, apply=True)
        after_first = await db[SETTINGS_COLLECTION].find().to_list(None)
        second = await m.migrate(db, apply=True)
        after_second = await db[SETTINGS_COLLECTION].find().to_list(None)

        # resumable: the copy exists but the legacy row is still there
        await db[SETTINGS_COLLECTION].insert_one(
            {"_id": OVERTIME_CONFIG, "org_id": ORG_A, "coefficients": {"x": 1}})
        await db[SETTINGS_COLLECTION].insert_one(
            {"_id": settings_id(OVERTIME_CONFIG, ORG_A), "org_id": ORG_A,
             "coefficients": {"x": 1}})
        third = await m.migrate(db, apply=True)
        legacy_left = await db[SETTINGS_COLLECTION].find_one({"_id": OVERTIME_CONFIG})
        return first, second, after_first, after_second, third, legacy_left

    first, second, af, asec, third, legacy_left = asyncio.run(body())
    assert first["reconciled"] and second["reconciled"]
    assert af == asec, "a second apply changed the database"
    states = {r["key"]: r["state"] for r in third["results"]}
    assert states[OVERTIME_CONFIG] == m.STATE_ALREADY
    assert legacy_left is None, "the resumed run must remove the leftover legacy row"


def test_the_migration_never_overwrites_a_differing_tenant_row():
    m = _migration()

    async def body():
        db = _db()
        await db[SETTINGS_COLLECTION].insert_one(
            {"_id": WORKER_RATES, "org_id": ORG_A, "rates": {"legacy": 1}})
        await db[SETTINGS_COLLECTION].insert_one(
            {"_id": settings_id(WORKER_RATES, ORG_A), "org_id": ORG_A,
             "rates": {"already-there": 2}})
        report = await m.migrate(db, apply=True)
        legacy = await db[SETTINGS_COLLECTION].find_one({"_id": WORKER_RATES})
        kept = await db[SETTINGS_COLLECTION].find_one(
            {"_id": settings_id(WORKER_RATES, ORG_A)})
        return report, legacy, kept

    report, legacy, kept = asyncio.run(body())
    states = {r["key"]: r["state"] for r in report["results"]}
    assert states[WORKER_RATES] == m.STATE_CONFLICT
    assert legacy is not None, "a conflict must leave the legacy row untouched"
    assert kept["rates"] == {"already-there": 2}, "the existing tenant row was overwritten"


def test_the_migration_refuses_an_ownerless_row():
    """W0-03E-A2B's backfill gives legacy rows an owner; this never guesses one."""
    m = _migration()

    async def body():
        db = _db()
        await db[SETTINGS_COLLECTION].insert_one({"_id": WORKER_RATES, "rates": {"a": 1}})
        report = await m.migrate(db, apply=True)
        still = await db[SETTINGS_COLLECTION].find_one({"_id": WORKER_RATES})
        return report, still, await db[SETTINGS_COLLECTION].count_documents({})

    report, still, total = asyncio.run(body())
    states = {r["key"]: r["state"] for r in report["results"]}
    assert states[WORKER_RATES] == m.STATE_OWNERLESS
    assert still is not None and total == 1


def test_the_migration_handles_two_tenants_at_once():
    """Only ONE legacy global row can exist per key, so the second tenant's row is
    whatever the backfill gave it — the migration must cope with either tenant."""
    m = _migration()

    async def body():
        db = _db()
        await db[SETTINGS_COLLECTION].insert_many([
            {"_id": WORKER_RATES, "org_id": ORG_A, "rates": {"a": 1}},
            {"_id": EMPLOYEE_COST_CONFIG, "org_id": ORG_B, "additional_cost_percent": 5},
        ])
        report = await m.migrate(db, apply=True)
        return (report,
                await db[SETTINGS_COLLECTION].find_one(
                    {"_id": settings_id(WORKER_RATES, ORG_A)}),
                await db[SETTINGS_COLLECTION].find_one(
                    {"_id": settings_id(EMPLOYEE_COST_CONFIG, ORG_B)}),
                await db[SETTINGS_COLLECTION].count_documents(
                    {"_id": {"$in": list(LEGACY_GLOBAL_KEYS)}}))

    report, a_row, b_row, legacy_left = asyncio.run(body())
    assert report["reconciled"] and report["moved"] == 2
    assert a_row["org_id"] == ORG_A and b_row["org_id"] == ORG_B
    assert legacy_left == 0
