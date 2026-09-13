#!/usr/bin/env bash
# W0-09A — adopt the already-running deployment as the recorded current release.
# Verification and state files only: no source swap, no container action.
#
#   sudo bash <baseline-bundle>/tools/synology/release_adopt.sh \
#        [--previous-bundle <bundle-of-previous-release> --previous-tree-dir <dir under base>]
#
# Proves that $BASE/repo is exactly the baseline manifest tree (plus the declared legacy
# extras, e.g. the hand-copied nginx.conf) and, optionally, that an existing anchor
# directory is exactly the previous release, then writes release-state/current.env
# (and previous.env). Refuses when state already exists.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib.sh"

PREV_BUNDLE=""; PREV_DIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --previous-bundle) PREV_BUNDLE="${2:-}"; shift 2 ;;
    --previous-tree-dir) PREV_DIR="${2:-}"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 3 ;;
  esac
done
rel_setup adopt
trap 'lock_release' EXIT
lock_acquire

adopt_fail() { log "ADOPT FAILED: $1"; log "NOTHING WAS CHANGED."; exit 2; }

[ ! -f "$STATE/current.env" ] || adopt_fail "release-state already has a current release; adoption is a one-time step"
if [ -n "$PREV_BUNDLE$PREV_DIR" ] && { [ -z "$PREV_BUNDLE" ] || [ -z "$PREV_DIR" ]; }; then
  adopt_fail "--previous-bundle and --previous-tree-dir go together"
fi

PYV_BUNDLE="$BUNDLE"
pyv bundle --bundle "$(vbundle)" --base "$(vbase)" --mode adopt \
    --plan-out "$(vpath "$EVID/plan.env")" --report-out "$(vpath "$EVID/verify.json")" 2>&1 | tr -d '\r' | sed 's/^/    /'
grep -q '"result": "PASS"' "$EVID/verify.json" 2>/dev/null || adopt_fail "baseline bundle/layout verification failed"
read_kv "$EVID/plan.env" P || adopt_fail "plan unreadable"
[ "$P_MIGRATIONS_DECLARED" = 0 ] || adopt_fail "baseline manifest declares migrations"
log "  live repo must be exactly $P_RELEASE_ID (${P_COMMIT:0:12}) + legacy extras [$P_LEGACY_EXTRAS]:"
verify_tree repo "$P_TREE" "$P_LEGACY_EXTRAS" "$BUNDLE" || adopt_fail "live $BASE/repo is not the baseline release"

if [ -n "$PREV_BUNDLE" ]; then
  [[ "$PREV_DIR" =~ $TREE_DIR_RE ]] && [ "$PREV_DIR" != repo ] && [ -d "$BASE/$PREV_DIR" ] || adopt_fail "invalid previous tree dir $PREV_DIR"
  PREV_BUNDLE="$(cd "$PREV_BUNDLE" && pwd)" || adopt_fail "previous bundle not found"
  mkdir "$EVID/previous"
  PYV_BUNDLE="$PREV_BUNDLE" pyv bundle --bundle "$(PYV_BUNDLE="$PREV_BUNDLE" vbundle)" --mode adopt \
      --plan-out "$(vpath "$EVID/previous/plan.env")" --report-out "$(vpath "$EVID/previous/verify.json")" 2>&1 | tr -d '\r' | sed 's/^/    /'
  grep -q '"result": "PASS"' "$EVID/previous/verify.json" 2>/dev/null || adopt_fail "previous bundle verification failed"
  read_kv "$EVID/previous/plan.env" Q || adopt_fail "previous plan unreadable"
  [ "$Q_DEPLOYMENT_ID" = "$P_DEPLOYMENT_ID" ] && [ "$Q_ENVIRONMENT" = "$P_ENVIRONMENT" ] || adopt_fail "previous bundle belongs to another deployment"
  log "  $PREV_DIR must be exactly $Q_RELEASE_ID (${Q_COMMIT:0:12}) + legacy extras [$Q_LEGACY_EXTRAS]:"
  PYV_BUNDLE="$PREV_BUNDLE" verify_tree "$PREV_DIR" "$Q_TREE" "$Q_LEGACY_EXTRAS" "$PREV_BUNDLE" || adopt_fail "$PREV_DIR is not the previous release"
fi

printf 'DEPLOYMENT_ID=%s\nENVIRONMENT=%s\nLAYOUT=%s\n' "$P_DEPLOYMENT_ID" "$P_ENVIRONMENT" "$P_LAYOUT" > "$STATE/DEPLOYMENT"
if [ -n "$PREV_BUNDLE" ]; then
  dump_prefix Q "$STATE/previous.env" "TREE_DIR=$PREV_DIR" "SERVICES_REBUILT=" "DEPLOYED_AT=unknown-adopted" "BUNDLE_DIR=$PREV_BUNDLE"
  cp "$PREV_BUNDLE/manifest.json" "$STATE/manifests/$Q_RELEASE_ID.json"
  cp "$PREV_BUNDLE/manifest.json" "$STATE/previous.json"
fi
dump_prefix P "$STATE/current.env" "TREE_DIR=repo" "SERVICES_REBUILT=" "DEPLOYED_AT=adopted-$(now)" "BUNDLE_DIR=$BUNDLE"
cp "$BUNDLE/manifest.json" "$STATE/manifests/$P_RELEASE_ID.json"
cp "$BUNDLE/manifest.json" "$STATE/current.json"
write_markers P "${Q_COMMIT:-NONE}" "${PREV_DIR:-NONE}"
write_record adopt ADOPTED P "" PASS SKIPPED "" "${Q_RELEASE_ID:-NONE}" "${Q_RELEASE_ID:-NONE}"
log "=== ADOPTED $P_RELEASE_ID as current$( [ -n "$PREV_BUNDLE" ] && printf ' with rollback target %s at %s' "$Q_RELEASE_ID" "$PREV_DIR") ==="
exit 0
