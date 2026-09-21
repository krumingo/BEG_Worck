"""
W0-03C — build the planned per-tenant unique indexes, but only on clean data and never
in production.

The order is the contract (docs/architecture/W0-03_MASTER_DATA_INVENTORY_AND_CONTRACT.md
§6 "W0-03C"):

  1. **target guard** — an ``apply`` or ``rollback`` runs only against a disposable local
     MongoDB (localhost, not ``mongodb+srv``, not a production database name) and only
     when the operator repeats the database name. Planning (dry run) needs no guard: it
     only reads.
  2. **a fresh duplicate report** of the same database — not a report handed in from
     somewhere else. Any blocking group refuses the whole run and returns the report.
  3. **existing indexes** — an index of the same name and the same definition is kept
     (a re-run changes nothing); the same name with a different definition, or the same
     definition under another name, refuses the run. Nothing is dropped to "make room".
  4. **build** — each missing index in plan order. If any build fails (for example a
     duplicate written after the report), the indexes THIS run created are dropped again
     and the run reports ``FAILED_ROLLED_BACK``: no half-built plan is left behind.
  5. **rollback plan** — the exact indexes this run created, and nothing else, so undoing
     it cannot touch an index that existed before.

Nothing here reads or writes documents: the report reads, the bootstrap only creates and
drops indexes named ``md_uq_*`` from ``uniqueness.CANONICAL_KEYS``.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from app.master_data.uniqueness import CANONICAL_KEYS, INDEX_PREFIX, UniqueKey, duplicate_report

STATUS_PLANNED = "PLANNED"                      # dry run: what an apply would do
STATUS_APPLIED = "APPLIED"
STATUS_ALREADY_APPLIED = "ALREADY_APPLIED"      # a re-run: every index already there
STATUS_REFUSED_TARGET = "REFUSED_TARGET"
STATUS_REFUSED_DUPLICATES = "REFUSED_DUPLICATES"
STATUS_REFUSED_CONFLICT = "REFUSED_CONFLICT"
STATUS_FAILED_ROLLED_BACK = "FAILED_ROLLED_BACK"
STATUS_ROLLBACK_FAILED = "ROLLBACK_FAILED"
STATUS_ROLLED_BACK = "ROLLED_BACK"

#: Database names that are production by definition: the legacy default, the first
#: tenant's database (``begwork_beg``, what W0-10A restores) and the system database. The
#: environment adds whatever the running service is configured with, and any name in the
#: ``begwork`` family is refused as well, so a copy-pasted production name never passes.
PRODUCTION_DATABASES = frozenset({"begwork", "begwork_beg", "begwork_system"})
PRODUCTION_PREFIX = "begwork"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class TargetRefused(Exception):
    """The target is not a disposable local database."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def production_databases(env: Optional[Dict[str, str]] = None) -> frozenset:
    import os
    env = os.environ if env is None else env
    names = set(PRODUCTION_DATABASES)
    for var in ("DB_NAME", "BEG_SYSTEM_DB"):
        if env.get(var):
            names.add(env[var])
    return frozenset(names)


def check_local(*, hosts: Iterable[str], scheme: str) -> None:
    """Raise ``TargetRefused`` unless the server is a plain local ``mongodb://`` one.

    Every W0-03C tool that connects to a server applies at least this: the duplicate
    report of real data runs on a restored copy (contract Q3), never on Atlas."""
    hosts = [h.strip("[]").lower() for h in hosts]
    if scheme != "mongodb":
        raise TargetRefused("scheme %r refused: only a plain local mongodb:// target" % scheme)
    if not hosts or any(h not in LOCAL_HOSTS for h in hosts):
        raise TargetRefused("host(s) %s refused: W0-03C connects only to a local disposable "
                            "MongoDB, never to Atlas or the NAS" % (", ".join(hosts) or "-"))


def check_target(*, database: str, hosts: Iterable[str], scheme: str,
                 confirm_database: Optional[str],
                 env: Optional[Dict[str, str]] = None) -> None:
    """Raise ``TargetRefused`` unless this is a disposable local database the operator
    named twice. Deliberately strict: W0-03C builds no index outside a throwaway MongoDB."""
    check_local(hosts=hosts, scheme=scheme)
    if (not database or database in production_databases(env)
            or database.lower().startswith(PRODUCTION_PREFIX)):
        raise TargetRefused("database %r is a production name" % database)
    if confirm_database != database:
        raise TargetRefused("confirmation %r does not repeat the database name %r"
                            % (confirm_database, database))


def _existing_spec(info: Dict[str, Any]) -> Dict[str, Any]:
    return {"keys": [(k, int(v)) for k, v in info.get("key", [])],
            "unique": bool(info.get("unique")),
            "partial": info.get("partialFilterExpression")}


def _wanted_spec(key: UniqueKey) -> Dict[str, Any]:
    return {"keys": [(f, 1) for f in key.fields], "unique": True, "partial": key.partial}


async def _index_information(db, collection: str, present: set) -> Dict[str, Any]:
    if collection not in present:
        return {}
    return await db[collection].index_information()


def _rollback_entry(key: UniqueKey) -> Dict[str, Any]:
    return {"collection": key.collection, "index": key.name,
            "command": "db.getCollection(%r).dropIndex(%r)" % (key.collection, key.name)}


async def bootstrap(db, *, database: str, apply: bool = False,
                    target: Optional[Dict[str, Any]] = None,
                    keys: Sequence[UniqueKey] = CANONICAL_KEYS,
                    env: Optional[Dict[str, str]] = None,
                    now: Optional[str] = None) -> Dict[str, Any]:
    """Plan (default) or build the unique indexes of ``keys`` in ``db``.

    ``target`` is ``{"hosts": [...], "scheme": "mongodb", "confirm_database": "<name>"}``
    and is required — and checked — only when ``apply`` is True.
    """
    run: Dict[str, Any] = {"database": database, "apply": bool(apply), "started_at": now or _now(),
                           "created": [], "kept": [], "to_create": [], "rollback_plan": []}

    if apply:
        try:
            check_target(database=database, hosts=(target or {}).get("hosts", []),
                         scheme=(target or {}).get("scheme", ""),
                         confirm_database=(target or {}).get("confirm_database"), env=env)
        except TargetRefused as exc:
            return dict(run, status=STATUS_REFUSED_TARGET, reason=str(exc))

    report = await duplicate_report(db, database=database, keys=keys, now=now)
    run["report"] = report
    if not report["canonical"]["clean"]:
        return dict(run, status=STATUS_REFUSED_DUPLICATES,
                    reason="duplicate report is not clean; blocked: %s"
                    % (", ".join(report["canonical"]["blocked_indexes"]) or "tenantless records"))

    present = set(await db.list_collection_names())
    conflicts = []
    for key in keys:
        info = await _index_information(db, key.collection, present)
        wanted = _wanted_spec(key)
        same_name = info.get(key.name)
        if same_name is not None:
            if _existing_spec(same_name) == wanted:
                run["kept"].append("%s.%s" % (key.collection, key.name))
            else:
                conflicts.append("%s.%s exists with a different definition" % (key.collection, key.name))
            continue
        for other_name, other in info.items():
            spec = _existing_spec(other)
            if spec["keys"] == wanted["keys"] and spec["partial"] == wanted["partial"]:
                conflicts.append("%s already has %s with the definition of %s"
                                 % (key.collection, other_name, key.name))
        run["to_create"].append("%s.%s" % (key.collection, key.name))
    if conflicts:
        return dict(run, status=STATUS_REFUSED_CONFLICT, reason="; ".join(conflicts))

    if not apply:
        return dict(run, status=STATUS_PLANNED,
                    reason="dry run: %d to create, %d already present"
                    % (len(run["to_create"]), len(run["kept"])))
    if not run["to_create"]:
        return dict(run, status=STATUS_ALREADY_APPLIED, reason="every planned index is present")

    created: List[UniqueKey] = []
    for key in keys:
        if "%s.%s" % (key.collection, key.name) not in run["to_create"]:
            continue
        spec = key.index_spec()
        try:
            options = {"name": spec["name"], "unique": True}
            if "partialFilterExpression" in spec:
                options["partialFilterExpression"] = spec["partialFilterExpression"]
            await db[key.collection].create_index(spec["keys"], **options)
        except Exception as exc:                        # noqa: BLE001 — reported and undone
            undone = await _drop(db, created)
            run["created"] = ["%s.%s" % (k.collection, k.name) for k in created]
            run["undone"] = undone
            failed = [u for u in undone if u["result"] != "dropped"]
            return dict(run, status=STATUS_ROLLBACK_FAILED if failed else STATUS_FAILED_ROLLED_BACK,
                        reason="building %s.%s failed (%s); %d index(es) created by this run were "
                               "dropped again" % (key.collection, key.name, exc,
                                                  sum(1 for u in undone if u["result"] == "dropped")))
        created.append(key)

    run["created"] = ["%s.%s" % (k.collection, k.name) for k in created]
    run["rollback_plan"] = [_rollback_entry(k) for k in created]
    return dict(run, status=STATUS_APPLIED, reason="%d index(es) created" % len(created))


async def _drop(db, created: Sequence[UniqueKey]) -> List[Dict[str, Any]]:
    out = []
    for key in reversed(list(created)):
        try:
            await db[key.collection].drop_index(key.name)
            out.append({"index": "%s.%s" % (key.collection, key.name), "result": "dropped"})
        except Exception as exc:                        # noqa: BLE001 — surfaced in the result
            out.append({"index": "%s.%s" % (key.collection, key.name), "result": "failed: %s" % exc})
    return out


async def rollback(db, plan: Sequence[Dict[str, Any]], *, database: str,
                   target: Optional[Dict[str, Any]] = None,
                   keys: Sequence[UniqueKey] = CANONICAL_KEYS,
                   env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Undo an ``APPLIED`` run: drop exactly the indexes in its rollback plan.

    Only names that are both ``md_uq_*`` and part of ``keys`` for that collection are
    touched, so a plan edited by hand cannot drop an unrelated index. A missing index is
    reported as already absent — running the rollback twice is safe.
    """
    try:
        check_target(database=database, hosts=(target or {}).get("hosts", []),
                     scheme=(target or {}).get("scheme", ""),
                     confirm_database=(target or {}).get("confirm_database"), env=env)
    except TargetRefused as exc:
        return {"status": STATUS_REFUSED_TARGET, "reason": str(exc), "results": []}
    allowed = {(k.collection, k.name) for k in keys}
    present = set(await db.list_collection_names())
    results = []
    for entry in plan:
        coll, name = entry.get("collection"), entry.get("index")
        if (coll, name) not in allowed or not str(name).startswith(INDEX_PREFIX):
            results.append({"index": "%s.%s" % (coll, name), "result": "refused: not a planned index"})
            continue
        info = await _index_information(db, coll, present)
        if name not in info:
            results.append({"index": "%s.%s" % (coll, name), "result": "already absent"})
            continue
        try:
            await db[coll].drop_index(name)
            results.append({"index": "%s.%s" % (coll, name), "result": "dropped"})
        except Exception as exc:                        # noqa: BLE001
            results.append({"index": "%s.%s" % (coll, name), "result": "failed: %s" % exc})
    bad = [r for r in results if r["result"].startswith(("failed", "refused"))]
    return {"status": STATUS_ROLLBACK_FAILED if bad else STATUS_ROLLED_BACK,
            "reason": "%d dropped, %d issue(s)" % (sum(1 for r in results if r["result"] == "dropped"),
                                                   len(bad)),
            "results": results}
