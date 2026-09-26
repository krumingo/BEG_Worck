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
  4. **build** — each missing index in plan order. When a build raises, the server is
     asked what it actually has for that index BEFORE anything is undone, because
     ``create_index`` can raise after the server already built it. Only when the index is
     provably absent are the indexes THIS run created dropped again
     (``FAILED_ROLLED_BACK``): no half-built plan is left behind. If the index is there,
     if the server cannot be asked, or if another definition holds that name, the run
     fails closed — it drops nothing, keeps every ledger claim and reports
     ``FAILED_BUILD_INDEX_PRESENT``, ``FAILED_RECONCILIATION_REQUIRED`` or
     ``BLOCKED_INDEX_CONFLICT`` (§"a failed build" below).
  5. **rollback** — driven by the run ledger, not by a file.

The run ledger (``md_uniqueness_runs``, in the same disposable database) is the only
document this module writes. An ``apply`` opens one entry before it builds and, for each
index, claims the name in the ledger BEFORE asking the server to build it — not after.
A crash (killed process, not just a caught exception) between the server confirming an
index and the run's next line of Python still leaves that claim in the ledger, so
``rollback(run_id)`` finds it instead of stranding an untracked index; a claim whose
index was never actually built is later found absent and skipped, not treated as an
error. The final ``status: applied`` write is best-effort like any ledger update: if it
fails, ``bootstrap`` does not report ``APPLIED`` — it reports ``APPLIED_LEDGER_UNCONFIRMED``
instead, because the indexes are real but the ledger cannot confirm the run finished.
``rollback(run_id)`` drops only what the entry records; a saved plan, if given, must
match the entry exactly, so an edited plan is refused instead of obeyed.

**A failed build is never assumed to have failed.** ``create_index`` raising means only
that the CALLER saw an error — a dropped connection or a timeout on the reply leaves the
index built on the server. So the exception is followed by a read-back of the real index
state (name, keys, uniqueness and the options that make an index a different index) and
one of four outcomes, of which only the second undoes anything:

  * **present** with the planned definition → ``FAILED_BUILD_INDEX_PRESENT``: ambiguous,
    not rolled back. The claim stays, nothing is dropped, and ``rollback(run_id)`` can
    finish the run deterministically later.
  * **provably absent** → this run's optimistic claim on it is retracted and the indexes
    it really built are dropped again: ``FAILED_ROLLED_BACK`` / ``ROLLBACK_FAILED``.
  * **unreadable** (connection loss) → ``FAILED_RECONCILIATION_REQUIRED``: fail closed,
    keep every claim, drop nothing.
  * **conflicting** definition on that name → ``BLOCKED_INDEX_CONFLICT`` for a human. A
    foreign or conflicting index is never deleted, here or in ``rollback``.

MongoDB keeps no identity or creation time for an index, so two cases are resolved from
the ledger alone:
  * the same index claimed by two runs (a concurrent apply, or a later run that rebuilt an
    index dropped in between): the LATER run owns the instance that exists now. Rolling
    back the earlier run releases its claim without dropping anything; rolling back the
    later run drops it.
  * **the honest limit:** an index dropped and re-created OUTSIDE this tool, with the same
    name and definition, cannot be told apart from the one the run created — rolling that
    run back drops it. ``test_w0_03c_uniqueness`` pins this boundary.
"""
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.master_data.uniqueness import CANONICAL_KEYS, INDEX_PREFIX, UniqueKey, duplicate_report

STATUS_PLANNED = "PLANNED"                      # dry run: what an apply would do
STATUS_APPLIED = "APPLIED"
STATUS_APPLIED_UNCONFIRMED = "APPLIED_LEDGER_UNCONFIRMED"  # built; final ledger write failed
STATUS_ALREADY_APPLIED = "ALREADY_APPLIED"      # a re-run: every index already there
STATUS_REFUSED_TARGET = "REFUSED_TARGET"
STATUS_REFUSED_DUPLICATES = "REFUSED_DUPLICATES"
STATUS_REFUSED_CONFLICT = "REFUSED_CONFLICT"
STATUS_FAILED_ROLLED_BACK = "FAILED_ROLLED_BACK"
STATUS_ROLLBACK_FAILED = "ROLLBACK_FAILED"
STATUS_ROLLED_BACK = "ROLLED_BACK"
#: ``create_index`` raised, but the server HAS the planned index: ambiguous, NOT rolled
#: back. The claim stays in the ledger and ``rollback(run_id)`` finishes the run later.
STATUS_FAILED_INDEX_PRESENT = "FAILED_BUILD_INDEX_PRESENT"
#: ``create_index`` raised and the server could not be asked what it actually has:
#: fail closed, drop nothing, keep every claim.
STATUS_FAILED_RECONCILE_REQUIRED = "FAILED_RECONCILIATION_REQUIRED"
#: ``create_index`` raised and something else now holds that index name: for a human,
#: never for this tool — a foreign or conflicting index is never deleted.
STATUS_BLOCKED_CONFLICT = "BLOCKED_INDEX_CONFLICT"

#: Statuses whose run still holds ledger claims on indexes that exist, or whose existence
#: is unproven. ``rollback(run_id)`` is the deterministic way to finish such a run, so the
#: CLI accepts a saved plan with any of them — not only a plain ``APPLIED`` one.
ROLLBACKABLE_STATUSES = frozenset({
    STATUS_APPLIED, STATUS_APPLIED_UNCONFIRMED, STATUS_FAILED_INDEX_PRESENT,
    STATUS_FAILED_RECONCILE_REQUIRED, STATUS_BLOCKED_CONFLICT,
})

#: The run ledger — the only documents this module writes, and only in the disposable
#: database the guard accepted.
LEDGER_COLLECTION = "md_uniqueness_runs"
RUN_BUILDING = "building"                          # entry opened, indexes being built
RUN_APPLIED = "applied"
RUN_FAILED = "failed_rolled_back"                  # the build failed and undid itself
RUN_ROLLBACK_INCOMPLETE = "rollback_incomplete"    # some claims could not be released
RUN_ROLLED_BACK = "rolled_back"
RUN_INDEX_PRESENT_UNCONFIRMED = "failed_index_present"   # built, then raised: claim kept
RUN_RECONCILE_REQUIRED = "reconciliation_required"       # server unreachable: claim kept
RUN_BLOCKED_CONFLICT = "blocked_index_conflict"          # foreign index on that name

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


#: Options that make an index a DIFFERENT index even with the same keys, uniqueness and
#: partial filter. No planned key uses any of them, so any of these on the server means
#: the index is not the one this module builds: it is foreign, and a foreign index is
#: never kept as "ours", never dropped and never rolled back.
DISCRIMINATING_OPTIONS = ("collation", "expireAfterSeconds", "sparse", "hidden", "weights",
                          "wildcardProjection", "storageEngine")


def _existing_spec(info: Dict[str, Any]) -> Dict[str, Any]:
    """The comparable signature of an index as the server describes it."""
    return {"keys": [(k, int(v)) for k, v in info.get("key", [])],
            "unique": bool(info.get("unique")),
            "partial": info.get("partialFilterExpression"),
            "options": {o: info[o] for o in DISCRIMINATING_OPTIONS if o in info}}


def _wanted_spec(key: UniqueKey) -> Dict[str, Any]:
    return {"keys": [(f, 1) for f in key.fields], "unique": True, "partial": key.partial,
            "options": {}}


def _signature(spec: Optional[Dict[str, Any]]) -> Optional[str]:
    """One storable line describing an index definition.

    Text on purpose: a partial filter holds ``$``-prefixed and dotted field names, which
    have no business being written into a stored document."""
    if spec is None:
        return None
    parts = ["keys=" + ",".join("%s:%d" % (f, d) for f, d in spec["keys"]),
             "unique=%s" % spec["unique"],
             "partial=%s" % (json.dumps(spec["partial"], sort_keys=True, ensure_ascii=False)
                             if spec["partial"] else "-")]
    if spec.get("options"):
        parts.append("options=" + json.dumps(spec["options"], sort_keys=True,
                                             ensure_ascii=False, default=str))
    return " ".join(parts)


class ReconcileUnavailable(Exception):
    """The server could not be asked what it actually has — so nothing may be assumed."""


async def _reconcile(db, key: UniqueKey) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Read back what the server really holds for ``key``.

    Returns ``("present"|"absent"|"conflict", <the existing spec, or None>)``, comparing
    name, keys, uniqueness and the options that make an index a different index. Raises
    ``ReconcileUnavailable`` when the state cannot be established at all; the caller then
    fails closed instead of guessing.
    """
    try:
        info = await db[key.collection].index_information()
    except Exception as exc:                            # noqa: BLE001 — a collection that is
        try:                                            # provably absent is an answer; any
            present = set(await db.list_collection_names())   # other error is not
        except Exception as why:                        # noqa: BLE001
            raise ReconcileUnavailable("%s (the collection list is unreadable too: %s)"
                                       % (exc, why)) from exc
        if key.collection not in present:
            return "absent", None
        raise ReconcileUnavailable(str(exc)) from exc
    found = info.get(key.name)
    if found is None:
        return "absent", None
    spec = _existing_spec(found)
    return ("present" if spec == _wanted_spec(key) else "conflict"), spec


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

    run_id = uuid.uuid4().hex
    run["run_id"] = run_id
    ledger = db[LEDGER_COLLECTION]
    try:
        await ledger.insert_one({
            "_id": run_id, "run_id": run_id, "database": database, "status": RUN_BUILDING,
            "started_at": _now(), "started_ns": time.time_ns(),
            "planned": list(run["to_create"]), "created": [], "released": [],
        })
    except Exception as exc:                            # noqa: BLE001 — nothing built yet
        return dict(run, status=STATUS_FAILED_ROLLED_BACK,
                    reason="could not open the run ledger (%s); nothing was built" % exc)

    created: List[UniqueKey] = []
    for key in keys:
        if "%s.%s" % (key.collection, key.name) not in run["to_create"]:
            continue
        spec = key.index_spec()
        # claimed BEFORE the build is attempted: a crash during create_index (a killed
        # process, not merely a caught exception) still leaves the ledger naming this
        # index, so rollback finds it instead of stranding it untracked. If create_index
        # then turns out to have failed or never run, the claim is retracted below — the
        # window this closes is the one AFTER the server confirms the build.
        try:
            await ledger.update_one({"_id": run_id}, {"$set": {"created": _claims(created + [key])}})
        except Exception as exc:                        # noqa: BLE001 — nothing built for this key
            undone = await _drop(db, created)
            left = [k for k, u in zip(reversed(created), undone) if u["result"] != "dropped"]
            await _ledger_set(ledger, run_id, {
                "status": RUN_FAILED if not left else RUN_ROLLBACK_INCOMPLETE,
                "created": _claims(list(reversed(left))), "undone": undone,
                "finished_at": _now(), "failure": str(exc)})
            run["created"] = _labels(created)
            run["undone"] = undone
            return dict(run, status=STATUS_ROLLBACK_FAILED if left else STATUS_FAILED_ROLLED_BACK,
                        reason="could not claim %s.%s in the run ledger (%s); %d index(es) created "
                               "by this run were dropped again"
                               % (key.collection, key.name, exc,
                                  sum(1 for u in undone if u["result"] == "dropped")))
        try:
            options = {"name": spec["name"], "unique": True}
            if "partialFilterExpression" in spec:
                options["partialFilterExpression"] = spec["partialFilterExpression"]
            await db[key.collection].create_index(spec["keys"], **options)
            created.append(key)
        except Exception as exc:                        # noqa: BLE001 — reconciled, then reported
            # the exception alone says NOTHING about whether the index exists: ask the
            # server before retracting a claim or dropping anything (see the C02 finding)
            return await _after_failed_build(db, ledger, run, run_id, key, created, exc)

    run["created"] = _labels(created)
    run["rollback_plan"] = [_rollback_entry(k) for k in created]
    try:
        await ledger.update_one({"_id": run_id}, {"$set": {"status": RUN_APPLIED, "finished_at": _now()}})
    except Exception as exc:                            # noqa: BLE001 — built, but not confirmed
        # fail closed: every index is real and rollback(run_id) still works from the
        # claims already recorded per index, but this run never reports plain APPLIED
        # unless the ledger itself says so
        return dict(run, status=STATUS_APPLIED_UNCONFIRMED,
                    reason="%d index(es) created (run %s) but the final ledger status write "
                           "failed (%s); the ledger still shows '%s' — the indexes exist and "
                           "rollback(%s) still works from the recorded claims; confirm and "
                           "correct the ledger status by hand"
                           % (len(created), run_id, exc, RUN_BUILDING, run_id))
    return dict(run, status=STATUS_APPLIED,
                reason="%d index(es) created (run %s)" % (len(created), run_id))


def _claims(keys: Sequence[UniqueKey]) -> List[Dict[str, str]]:
    return [{"collection": k.collection, "index": k.name} for k in keys]


def _labels(keys: Sequence[UniqueKey]) -> List[str]:
    return ["%s.%s" % (k.collection, k.name) for k in keys]


async def _after_failed_build(db, ledger, run: Dict[str, Any], run_id: str, key: UniqueKey,
                              created: List[UniqueKey], exc: Exception) -> Dict[str, Any]:
    """Decide what a failed ``create_index`` means — from the server, not from the exception.

    ``create_index`` can raise AFTER the server has built the index: a dropped connection,
    a timeout while reading the reply, a client-side error. The exception therefore proves
    nothing about the index, and the C02 review of PR #20 named exactly that: an
    acknowledged index must never be reported as ``FAILED_ROLLED_BACK`` while it survives.
    So nothing is dropped and no claim is retracted before the actual state is read back.

    Four outcomes, and only the second one undoes anything:

      1. **present** — the index is there with the definition this run planned. The claim
         written before the build stays, nothing is dropped, and the run reports
         ``FAILED_BUILD_INDEX_PRESENT`` with a rollback plan that matches the ledger, so
         ``rollback(run_id)`` can finish the run deterministically later.
      2. **absent** — the server proves the index was not created. Only THIS run's
         optimistic claim on it is retracted, then the indexes this run really built are
         dropped again: the behaviour from before, now backed by evidence.
      3. **unavailable** — the server cannot be asked at all (connection loss). Fail
         closed: keep every claim, drop nothing, report
         ``FAILED_RECONCILIATION_REQUIRED``.
      4. **conflict** — something else holds that index name. Keep the evidence and the
         claim, report ``BLOCKED_INDEX_CONFLICT`` for a human, and never delete that
         index — ``rollback`` refuses it too.
    """
    label = "%s.%s" % (key.collection, key.name)
    run["created"] = _labels(created)
    run["undone"] = []
    try:
        state, found = await _reconcile(db, key)
        unavailable = ""
    except ReconcileUnavailable as why:
        state, found, unavailable = "unavailable", None, str(why)
    evidence = {"index": label, "state": state, "found": _signature(found),
                "wanted": _signature(_wanted_spec(key)), "build_error": str(exc), "at": _now()}
    if unavailable:
        evidence["reason"] = unavailable
    run["reconciliation"] = evidence

    if state == "absent":
        # proven not created: retract this key's optimistic claim first, so the ledger
        # never claims an index that does not exist, then undo what this run did build
        await _ledger_set(ledger, run_id, {"created": _claims(created), "reconciliation": evidence})
        undone = await _drop(db, created)
        left = [k for k, u in zip(reversed(created), undone) if u["result"] != "dropped"]
        await _ledger_set(ledger, run_id, {
            "status": RUN_FAILED if not left else RUN_ROLLBACK_INCOMPLETE,
            "created": _claims(list(reversed(left))), "undone": undone,
            "finished_at": _now(), "failure": str(exc)})
        run["undone"] = undone
        return dict(run, status=STATUS_ROLLBACK_FAILED if left else STATUS_FAILED_ROLLED_BACK,
                    reason="building %s failed (%s) and the server confirms it was not created; "
                           "%d index(es) created by this run were dropped again"
                           % (label, exc, sum(1 for u in undone if u["result"] == "dropped")))

    # present / unavailable / conflict — fail closed. Every claim this run wrote stays in
    # the ledger, this key's included, and the rollback plan lists exactly the same
    # indexes, so a saved plan still matches the ledger and a later rollback is
    # deterministic instead of a guess.
    run["unconfirmed"] = [label]
    run["rollback_plan"] = [_rollback_entry(k) for k in created + [key]]
    if state == "present":
        status, ledger_status = STATUS_FAILED_INDEX_PRESENT, RUN_INDEX_PRESENT_UNCONFIRMED
        reason = ("building %s raised (%s), but the server HAS that index with exactly the "
                  "planned definition: this run is ambiguous, NOT rolled back. Nothing was "
                  "dropped, run %s keeps the claim on it and on %d earlier index(es), and "
                  "rollback(%s) undoes all of them when a human decides to"
                  % (label, exc, run_id, len(created), run_id))
    elif state == "unavailable":
        status, ledger_status = STATUS_FAILED_RECONCILE_REQUIRED, RUN_RECONCILE_REQUIRED
        reason = ("building %s raised (%s) and the server could not be asked what it actually "
                  "has (%s): failing closed. Nothing was dropped, run %s keeps every claim, "
                  "and %s must be reconciled by hand before rollback(%s) is trusted"
                  % (label, exc, unavailable, run_id, label, run_id))
    else:
        status, ledger_status = STATUS_BLOCKED_CONFLICT, RUN_BLOCKED_CONFLICT
        reason = ("building %s raised (%s) and that name is held by an index with another "
                  "definition (found: %s; planned: %s): BLOCKED for a human. Nothing was "
                  "dropped, run %s keeps its claims, and neither this run nor rollback(%s) "
                  "ever deletes a foreign or conflicting index"
                  % (label, exc, evidence["found"], evidence["wanted"], run_id, run_id))
    await _ledger_set(ledger, run_id, {"status": ledger_status, "finished_at": _now(),
                                       "failure": str(exc), "reconciliation": evidence})
    return dict(run, status=status, reason=reason)


async def _ledger_set(ledger, run_id: str, fields: Dict[str, Any]) -> None:
    try:
        await ledger.update_one({"_id": run_id}, {"$set": fields})
    except Exception:                                   # noqa: BLE001 — best effort, see result
        pass


async def _drop(db, created: Sequence[UniqueKey]) -> List[Dict[str, Any]]:
    out = []
    for key in reversed(list(created)):
        try:
            await db[key.collection].drop_index(key.name)
            out.append({"index": "%s.%s" % (key.collection, key.name), "result": "dropped"})
        except Exception as exc:                        # noqa: BLE001 — surfaced in the result
            out.append({"index": "%s.%s" % (key.collection, key.name), "result": "failed: %s" % exc})
    return out


async def _ledger_entries(db) -> List[Dict[str, Any]]:
    return await db[LEDGER_COLLECTION].find({}).to_list(length=None)


def _pairs(entries: Iterable[Dict[str, Any]]) -> List[Tuple[str, str]]:
    return sorted((str(e.get("collection")), str(e.get("index"))) for e in entries)


async def rollback(db, run_id: str, *, database: str,
                   target: Optional[Dict[str, Any]] = None,
                   plan: Optional[Sequence[Dict[str, Any]]] = None,
                   keys: Sequence[UniqueKey] = CANONICAL_KEYS,
                   env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Undo run ``run_id``: drop exactly what its ledger entry records, nothing else.

    ``plan`` is the ``rollback_plan`` the operator saved. When given it must name exactly
    the indexes the ledger records for that run, so an edited file is refused, never
    obeyed. Claims are released one by one: a second rollback is safe, a partial one can
    be retried.
    """
    try:
        check_target(database=database, hosts=(target or {}).get("hosts", []),
                     scheme=(target or {}).get("scheme", ""),
                     confirm_database=(target or {}).get("confirm_database"), env=env)
    except TargetRefused as exc:
        return {"status": STATUS_REFUSED_TARGET, "reason": str(exc), "results": []}

    entries = await _ledger_entries(db)
    mine = next((e for e in entries if e.get("_id") == run_id), None)
    if mine is None or mine.get("database") != database:
        return {"status": STATUS_REFUSED_TARGET, "results": [],
                "reason": "run %r is not in the run ledger of %r — nothing to undo" % (run_id, database)}
    claims = list(mine.get("created") or [])
    released = list(mine.get("released") or [])
    if plan is not None and _pairs(plan) != _pairs(claims + released):
        return {"status": STATUS_REFUSED_TARGET, "results": [],
                "reason": "the saved plan does not match what run %s recorded in the ledger "
                          "(edited?) — nothing dropped" % run_id}
    if not claims:
        return {"status": STATUS_ROLLED_BACK, "run_id": run_id, "results": [],
                "reason": "run %s holds no index any more (ledger status %s) — nothing to undo"
                          % (run_id, mine.get("status"))}

    planned = {(k.collection, k.name): k for k in keys}
    mine_order = (mine.get("started_ns") or 0, str(run_id))
    later: Dict[Tuple[str, str], str] = {}
    for e in entries:
        if e.get("_id") != run_id and (e.get("started_ns") or 0, str(e.get("_id"))) > mine_order:
            for c in e.get("created") or []:
                later.setdefault((c.get("collection"), c.get("index")), e.get("_id"))
    present = set(await db.list_collection_names())

    results, kept = [], []
    for claim in claims:
        coll, name = claim.get("collection"), claim.get("index")
        label = "%s.%s" % (coll, name)
        key = planned.get((coll, name))
        if key is None or not str(name).startswith(INDEX_PREFIX):
            results.append({"index": label, "result": "refused: not a planned index"})
            kept.append(claim)
            continue
        if (coll, name) in later:
            outcome = "released: rebuilt later by run %s, which owns it now — not dropped" % later[(coll, name)]
        else:
            info = await _index_information(db, coll, present)
            if name not in info:
                outcome = "already absent"
            elif _existing_spec(info[name]) != _wanted_spec(key):
                results.append({"index": label, "result": "refused: its definition changed since the run"})
                kept.append(claim)
                continue
            else:
                try:
                    await db[coll].drop_index(name)
                    outcome = "dropped"
                except Exception as exc:                # noqa: BLE001
                    results.append({"index": label, "result": "failed: %s" % exc})
                    kept.append(claim)
                    continue
        results.append({"index": label, "result": outcome})
        released.append({"collection": coll, "index": name, "result": outcome, "at": _now()})

    await _ledger_set(db[LEDGER_COLLECTION], run_id, {
        "created": kept, "released": released,
        "status": RUN_ROLLED_BACK if not kept else RUN_ROLLBACK_INCOMPLETE})
    dropped = sum(1 for r in results if r["result"] == "dropped")
    return {"status": STATUS_ROLLBACK_FAILED if kept else STATUS_ROLLED_BACK, "run_id": run_id,
            "reason": "%d dropped, %d released without a drop, %d kept"
                      % (dropped, len(results) - dropped - len(kept), len(kept)),
            "results": results}
