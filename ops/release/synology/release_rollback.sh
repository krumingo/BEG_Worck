#!/usr/bin/env bash
# W0-09A — standalone rollback to the RECORDED immediate rollback target (no hand-written SHA).
#
#   sudo bash <bundle>/tools/synology/release_rollback.sh            # dry run: shows current -> target
#   sudo bash <bundle>/tools/synology/release_rollback.sh --yes      # execute
#
# Target = release-state/previous.env (written by a successful deploy or by adoption).
# The target tree directory is verified to be exactly the recorded Git tree BEFORE anything
# moves. Rebuilds only the services the rolled-back release rebuilt; never runs migrations.
# Exit: 0 rolled back, 2 refused (nothing changed), 4 rollback failed (both trees kept).
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib.sh"

EXECUTE=0
[ "${1:-}" = "--yes" ] && EXECUTE=1
[ $# -le 1 ] && { [ $# -eq 0 ] || [ "$1" = "--yes" ]; } || { echo "usage: release_rollback.sh [--yes]" >&2; exit 3; }
rel_setup rollback
trap 'lock_release' EXIT
lock_acquire

refuse() { log "ROLLBACK REFUSED: $1"; log "NOTHING WAS CHANGED."; exit 2; }

[ -f "$STATE/current.env" ] || refuse "no current release recorded"
[ -f "$STATE/previous.env" ] || refuse "no rollback target recorded (previous.env missing)"
read_kv "$STATE/current.env" C || refuse "current.env unreadable"
read_kv "$STATE/previous.env" V || refuse "previous.env unreadable"
[ "$C_TREE_DIR" = repo ] || refuse "current TREE_DIR is $C_TREE_DIR"
[[ "$V_TREE_DIR" =~ $TREE_DIR_RE ]] && [ "$V_TREE_DIR" != repo ] || refuse "invalid rollback tree dir $V_TREE_DIR"
[ -d "$BASE/$V_TREE_DIR" ] || refuse "rollback target tree $V_TREE_DIR is missing"

log "  current : $C_RELEASE_ID (${C_COMMIT}) rebuilt=[${C_SERVICES_REBUILT}]"
log "  target  : $V_RELEASE_ID (${V_COMMIT}) tree dir $V_TREE_DIR"
log "  rollback target tree must be exactly $V_TREE:"
PYV_BUNDLE="$BUNDLE"
verify_tree "$V_TREE_DIR" "$V_TREE" "$V_LEGACY_EXTRAS" "${V_BUNDLE_DIR:-}" || refuse "rollback target $V_TREE_DIR does not match recorded tree (missing/tampered)"
log "  live repo is the current release:"
verify_tree repo "$C_TREE" "$C_LEGACY_EXTRAS" "${C_BUNDLE_DIR:-}" || refuse "live repo does not match the recorded current release"

if [ "$EXECUTE" != 1 ]; then
  log "DRY RUN: would move repo -> repo.rolledback-$C_RELEASE_ID-<UTC>, $V_TREE_DIR -> repo, rebuild [${C_SERVICES_REBUILT:-none}], smoke. Re-run with --yes."
  exit 0
fi

copy_prefix V S
ROLLED="repo.rolledback-$C_RELEASE_ID-$(stamp)"
SINCE="$(now)"
mv "$BASE/repo" "$BASE/$ROLLED" || refuse "could not move the current tree aside"
if ! mv "$BASE/$V_TREE_DIR" "$BASE/repo"; then
  mv "$BASE/$ROLLED" "$BASE/repo"; refuse "could not move the rollback target into place; current tree restored"
fi
log "  swapped: repo <- $V_TREE_DIR; rolled-back tree kept as $ROLLED"

fail4() {
  log "ROLLBACK FAILED: $1"
  log "Both trees are kept: repo (target $V_RELEASE_ID) and $ROLLED (release $C_RELEASE_ID)."
  log "Manual roll-forward: cd $BASE && mv repo $V_TREE_DIR && mv $ROLLED repo && ${COMPOSE_CMD[*]} up -d --build ${C_SERVICES_REBUILT//,/ }"
  write_record rollback ROLLBACK_FAILED V "$C_SERVICES_REBUILT" PASS FAIL "$1" "$C_RELEASE_ID" "$V_RELEASE_ID"
  exit 4
}
verify_tree repo "$V_TREE" "$V_LEGACY_EXTRAS" "${V_BUNDLE_DIR:-}" || fail4 "restored tree does not match $V_TREE"
compose_up "$C_SERVICES_REBUILT" compose-rollback || fail4 "docker compose up failed"
log "=== POST-ROLLBACK SMOKE ==="
smoke "$SINCE" "$C_SERVICES_REBUILT" || fail4 "post-rollback smoke: $SMOKE_FAIL"

mv "$STATE/previous.env" "$EVID/previous.env.consumed"
[ -f "$STATE/previous.json" ] && mv "$STATE/previous.json" "$EVID/previous.json.consumed"
dump_prefix V "$STATE/current.env" "TREE_DIR=repo" "SERVICES_REBUILT=$C_SERVICES_REBUILT" \
  "DEPLOYED_AT=rollback-$(now)" "PREVIOUS_RELEASE_ID=NONE"
[ -f "$STATE/manifests/$V_RELEASE_ID.json" ] && cp "$STATE/manifests/$V_RELEASE_ID.json" "$STATE/current.json"
write_markers V "$C_COMMIT" "$ROLLED"
write_record rollback ROLLBACK_DONE V "$C_SERVICES_REBUILT" PASS PASS "" "$C_RELEASE_ID" "$V_RELEASE_ID"
log "=== ROLLED BACK to $V_RELEASE_ID (${V_COMMIT}); $ROLLED retained for roll-forward/retention ==="
exit 0
