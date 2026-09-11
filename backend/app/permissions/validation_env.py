"""
W0-02 — Canonical isolated-validation environment + pure guard.

This module imports NOTHING that opens a database (no motor / pymongo), so
importing it can never create a Mongo client as a side effect. That property is
required: the guard must be callable BEFORE any client is constructed.

The expected values are BAKED IN here — the guard compares the live env to
THESE literals, never to a value copied from the runtime env, so a wrong
MONGO_URL/DB can never satisfy its own check (no tautology).
"""
import sys

VALIDATION_ENV = {
    "MONGO_URL": "mongodb://begwork-w002-testmongo:27017",
    "DB_NAME": "w002_op_test",
    "BEG_SYSTEM_DB": "w002_sys_test",
}


def validation_problems(mongo_url: str, db_name: str, sys_db: str) -> list:
    """Return the list of mismatches against the canonical validation env
    (empty list => the target IS the sanctioned temp environment). Pure — safe
    to call with arbitrary (wrong) values, no DB needed."""
    checks = (("MONGO_URL", mongo_url), ("DB_NAME", db_name), ("BEG_SYSTEM_DB", sys_db))
    return [f"{k}={v!r} != required {VALIDATION_ENV[k]!r}"
            for k, v in checks if v != VALIDATION_ENV[k]]


def require_validation_env(mongo_url: str, db_name: str, sys_db: str, *, exit_code: int = 3) -> None:
    """Fail-closed: exit with `exit_code` (default 3) if the target is not the
    exact sanctioned temp env. Raises SystemExit BEFORE any caller can open a
    client. No side effects other than the exit."""
    problems = validation_problems(mongo_url, db_name, sys_db)
    if problems:
        print("FAIL-CLOSED (validation env) — refusing; target is NOT the sanctioned temp env:")
        for p in problems:
            print("  -", p)
        sys.exit(exit_code)
