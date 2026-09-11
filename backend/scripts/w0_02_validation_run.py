#!/usr/bin/env python3
"""
W0-02 — one executable validation runner for the isolated Synology test env.

Streams (each labeled; runner exits NON-ZERO if any fails):
  NEGATIVES            migration guard must exit exactly 3 for wrong host / DB /
                       system DB (a success or any other exit is a FAIL).
  MOCK SUITE           full mongomock suite; require passed==collected, 0 failed,
                       0 skipped.
  REAL-MONGO SUITE     Integration+Api tests against the real temp Mongo; list
                       the selected tests and require passed==selected, 0 failed,
                       0 skipped (no unexplained skip counts as coverage).
  MIGRATION CHECKS     seed synthetic -> snapshot operational CONTENT -> dry-run
                       (no change) -> apply -> apply again (idempotent) -> verify
                       -> revert --apply -> snapshot again -> deep-compare content
                       (proves 'untouched' by document, not by count).
  STANDARD APP SUITE   reported NOT RUN (needs the app conftest + Mongo; not run
                       here on purpose — do not drop --noconftest blindly).

Run ONLY inside the isolated container against the temp Mongo. Guarded: refuses
any target that is not the exact sanctioned temp env before touching a client.
"""
import os
import sys
import re
import json
import asyncio
import argparse
import subprocess
from pathlib import Path

BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND))
from app.permissions.validation_env import require_validation_env, VALIDATION_ENV  # noqa: E402

MIG = str(BACKEND / "scripts" / "w0_02_bootstrap_permissions.py")
TESTS = str(BACKEND / "tests" / "test_w0_02_permission_core.py")
PYTEST = [sys.executable, "-m", "pytest", TESTS, "--noconftest", "-p", "no:cacheprovider"]
OP_COLLECTIONS = ["users", "organizations", "projects", "project_team"]


def _sh(cmd, extra_env=None):
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(BACKEND))
    if extra_env:
        env.update(extra_env)
    return subprocess.run(cmd, cwd=str(BACKEND), env=env, capture_output=True, text=True)


def _counts(out):
    def g(word):
        m = re.search(r"(\d+)\s+" + word, out)
        return int(m.group(1)) if m else 0
    return g("passed"), g("failed"), g("error"), g("skipped")


def _sec(t):
    print("\n" + "=" * 72 + f"\n{t}\n" + "=" * 72)


def check_negatives():
    _sec("NEGATIVES — migration guard must exit EXACTLY 3 on wrong env")
    base = {"BEG_VALIDATION_MODE": "1", **VALIDATION_ENV}
    cases = {
        "wrong host":          {**base, "MONGO_URL": "mongodb://evil-not-real-9999:27017"},
        "wrong DB_NAME":       {**base, "DB_NAME": "begwork"},
        "wrong BEG_SYSTEM_DB": {**base, "BEG_SYSTEM_DB": "begwork_system"},
    }
    ok = True
    for label, env in cases.items():
        r = _sh([sys.executable, MIG], env)
        good = r.returncode == 3 and "FAIL-CLOSED" in (r.stdout + r.stderr)
        print(f"  [{'PASS' if good else 'FAIL'}] {label}: exit={r.returncode} (want 3)")
        if not good:
            print("    ---- output ----\n" + (r.stdout + r.stderr)[:800])
        ok = ok and good
    return ok


def check_mock():
    _sec("MOCK SUITE (mongomock, in-process)")
    r = _sh(PYTEST + ["-q"])
    tail = "\n".join(r.stdout.strip().splitlines()[-4:])
    print(tail)
    p, f, e, s = _counts(r.stdout)
    ok = r.returncode == 0 and f == 0 and e == 0 and s == 0 and p > 0
    print(f"  -> passed={p} failed={f} error={e} skipped={s} : {'PASS' if ok else 'FAIL'}")
    return ok


def check_real():
    _sec("REAL-MONGO SUITE (Integration + Api against the temp Mongo)")
    env = {"W0_02_REAL_MONGO": "1", "W0_02_VALIDATION": "1", **VALIDATION_ENV}
    c = _sh(PYTEST + ["-k", "Integration or Api", "--collect-only", "-q"], env)
    selected = [ln for ln in c.stdout.splitlines() if "::" in ln]
    print("selected tests (%d):" % len(selected))
    for s in selected:
        print("   ", s)
    r = _sh(PYTEST + ["-k", "Integration or Api", "-v"], env)
    print("\n".join(r.stdout.strip().splitlines()[-6:]))
    p, f, e, sk = _counts(r.stdout)
    ok = (r.returncode == 0 and f == 0 and e == 0 and sk == 0
          and len(selected) > 0 and p == len(selected))
    print(f"  -> selected={len(selected)} passed={p} failed={f} error={e} skipped={sk} : {'PASS' if ok else 'FAIL'}")
    return ok


async def _snapshot(op):
    snap = {}
    for c in OP_COLLECTIONS:
        docs = await op[c].find({}, {"_id": 0}).to_list(10000)
        snap[c] = sorted((json.dumps(d, sort_keys=True, default=str) for d in docs))
    return snap


async def _authoritative_roleids(sy):
    docs = await sy.tenant_role_assignments.find({}, {"_id": 0}).to_list(10000)
    return {d["user_id"]: d.get("role_id") for d in docs if d.get("scope_type") == "company"}


def _mig(args, env):
    return _sh([sys.executable, MIG] + args, env)


async def check_migration():
    _sec("MIGRATION CHECKS (operational CONTENT compared, not just counts)")
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("w0_02_seed", str(BACKEND / "scripts" / "w0_02_validation_seed.py"))
    seed = ilu.module_from_spec(spec); spec.loader.exec_module(seed)

    url, db, sysdb = VALIDATION_ENV["MONGO_URL"], VALIDATION_ENV["DB_NAME"], VALIDATION_ENV["BEG_SYSTEM_DB"]
    client = seed.guarded_client(url, db, sysdb)          # guard-first
    op, sy = client[db], client[sysdb]
    await seed.reset_docs(op, sy)
    await seed.seed_docs(op, sy)

    env = {"BEG_VALIDATION_MODE": "1", **VALIDATION_ENV}
    before_op = await _snapshot(op)
    before_sys = await _authoritative_roleids(sy)

    r_dry = _mig([], env)                                  # dry-run: writes nothing
    after_dry_sys = await _authoritative_roleids(sy)
    dry_no_change = (before_sys == after_dry_sys)

    _mig(["--apply"], env)                                 # apply
    after_apply_roleids = await _authoritative_roleids(sy)
    n_after_apply = await sy.tenant_role_assignments.count_documents({})

    _mig(["--apply"], env)                                 # idempotent second apply
    n_after_reapply = await sy.tenant_role_assignments.count_documents({})

    r_ver = _mig(["--verify"], env)
    _mig(["--revert", "--apply"], env)                     # bounded revert
    n_after_revert_authoritative = await sy.tenant_role_assignments.count_documents({"role_id": {"$exists": True}})

    after_op = await _snapshot(op)

    expected_map = {"u_admin": "admin", "u_view": "LEGACY_VIEWER",
                    "u_tech": "LEGACY_TECHNICIAN", "u_sm": "site_manager"}
    checks = {
        "dry-run made NO change to authoritative state": dry_no_change,
        "apply mapped legacy roles correctly": after_apply_roleids == expected_map,
        "idempotent re-apply (no duplicates)": n_after_apply == n_after_reapply,
        "operational CONTENT identical before/after (deep compare)": before_op == after_op,
        "revert stripped W0-02 authoritative fields": n_after_revert_authoritative == 0,
    }
    ok = all(checks.values())
    for label, good in checks.items():
        print(f"  [{'PASS' if good else 'FAIL'}] {label}")
    if before_op != after_op:
        print("    operational snapshot diff detected — 'untouched' claim FAILS")
    return ok


def main():
    p = argparse.ArgumentParser(description="W0-02 isolated validation runner")
    p.add_argument("--only", choices=["negatives", "mock", "real", "migration", "all"], default="all")
    args = p.parse_args()

    # Top-level guard: refuse anything that is not the exact sanctioned temp env,
    # BEFORE any DB client is created (except the pure negative subprocess cases,
    # which set their own wrong env deliberately and are asserted to exit 3).
    if args.only in ("real", "migration", "all"):
        require_validation_env(VALIDATION_ENV["MONGO_URL"], VALIDATION_ENV["DB_NAME"], VALIDATION_ENV["BEG_SYSTEM_DB"])

    results = {}
    if args.only in ("negatives", "all"):
        results["NEGATIVES"] = check_negatives()
    if args.only in ("mock", "all"):
        results["MOCK SUITE"] = check_mock()
    if args.only in ("real", "all"):
        results["REAL-MONGO SUITE"] = check_real()
    if args.only in ("migration", "all"):
        results["MIGRATION CHECKS"] = asyncio.run(check_migration())

    _sec("STANDARD APPLICATION SUITE")
    print("  NOT RUN — requires the application conftest + Mongo in a safe env; "
          "not run here (--noconftest is used for the W0-02 suite on purpose).")

    _sec("SUMMARY")
    for k, v in results.items():
        print(f"  {k}: {'PASS' if v else 'FAIL'}")
    print("  STANDARD APPLICATION SUITE: NOT RUN")
    all_ok = all(results.values())
    print(f"\nRESULT: {'ALL PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
