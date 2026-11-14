#!/usr/bin/env bash
# CI-01 — one entry point for every CI gate, so GitHub Actions and a person
# on a laptop run exactly the same commands.
#
#   ops/ci/run_gate.sh <gate>
#
# Gates mirror the set AUDIT-2 runs before a merge (docs/audit/AUDIT_LOG.md on
# claude/audit-log). Real-MongoDB gates need MONGO_URL pointing at a single-node
# replica set (see ops/ci/start_mongo.sh). No secrets are used by any gate.
#
# Legacy integration tests (tests/test_*.py without a task id, which call a
# live server on REACT_APP_BACKEND_URL) are NOT part of CI: they need a running
# deployment and were never part of the merge gates.
set -euo pipefail

GATE="${1:?usage: run_gate.sh <gate>}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKEND="$ROOT/backend"
OUT="${CI_OUT:-$ROOT/ci-results}"
mkdir -p "$OUT"
PY="${PYTHON:-python}"

cd "$BACKEND"
export PYTHONPATH=.

pytest_gate() {
  # $1 = report name, rest = pytest args
  local name="$1"; shift
  "$PY" -m pytest --noconftest -q -p no:cacheprovider \
    -o junit_family=xunit2 --junitxml="$OUT/$name.xml" "$@"
}

need_mongo() {
  : "${MONGO_URL:?MONGO_URL must point at a replica set for gate $GATE}"
  export W0_03_REAL_MONGO_URL="${W0_03_REAL_MONGO_URL:-$MONGO_URL}"
  export DB_NAME="ci_${GATE//-/_}"
}

case "$GATE" in
  static)
    # Tenant guards: exit 1 on any violation.
    "$PY" scripts/w0_03e_a2c_tenant_boundary_guard.py
    "$PY" scripts/w0_03e_a1_tenant_access_guard.py
    ;;

  w0)
    # W0 runs DB-free. main carries known failures (legacy_routes etc.); the
    # gate fails only on a failure that is NOT in ops/ci/w0_known_failures.txt,
    # and reports known failures that started passing. Nothing is skipped or
    # deselected: every test runs and every failure is in the report.
    set +e
    pytest_gate w0 tests/test_w0_*.py -rf > "$OUT/w0.log" 2>&1
    set -e
    tail -5 "$OUT/w0.log"
    "$PY" "$ROOT/ops/ci/compare_failures.py" "$OUT/w0.xml" "$ROOT/ops/ci/w0_known_failures.txt"
    ;;

  r0)
    need_mongo
    pytest_gate r0 tests/test_rc_01_build_identity.py tests/test_r0_0*.py \
      tests/test_auth_0*.py tests/test_st_01_*.py tests/test_st_02_*.py
    ;;

  sec)
    need_mongo
    export PERMISSION_SERVICE_MODE=enforce
    pytest_gate sec tests/test_sec_01_*.py tests/test_sec_02_*.py tests/test_pm_01_*.py
    ;;

  pay)
    need_mongo
    pytest_gate pay tests/test_pay_*.py
    ;;

  warehouse)
    need_mongo
    export PERMISSION_SERVICE_MODE=enforce WAREHOUSE_CANONICAL_REQUIRE_REAL_MONGO=1
    pytest_gate warehouse tests/test_warehouse_canonical_*.py
    ;;

  tasks)
    # Every task suite (test_<area>_<NN>_*.py) not covered by another gate.
    need_mongo
    mapfile -t files < <(ls tests | grep -E '^test_[a-z]+(_[a-z]+)?_[0-9]{2}.*\.py$' \
      | grep -vE '^test_(sec|pm|pay|st|r0|rc|auth|w0|warehouse)_' | sed 's#^#tests/#')
    files+=(tests/test_codex_c23_independent.py)
    pytest_gate tasks "${files[@]}"
    ;;

  release)
    "$PY" -m pytest -q -p no:cacheprovider -o junit_family=xunit2 \
      --junitxml="$OUT/release.xml" "$ROOT/ops/release/tests"
    ;;

  *)
    echo "unknown gate: $GATE" >&2; exit 2 ;;
esac
