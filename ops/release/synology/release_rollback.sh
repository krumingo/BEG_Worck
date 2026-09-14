#!/usr/bin/env bash
# W0-09A — standalone rollback to the RECORDED immediate rollback target (no hand-written SHA).
#
#   sudo bash <bundle>/tools/synology/release_rollback.sh                  # dry run: plan only
#   sudo bash <bundle>/tools/synology/release_rollback.sh --yes            # execute
#   sudo bash <bundle>/tools/synology/release_rollback.sh --yes --allow-source-rebuild
#
# Target = release-state/previous.env (written by a successful deploy or by adoption).
# Source: the target tree directory is verified to be exactly the recorded Git tree BEFORE
# anything moves. Runtime: every service whose recorded image differs is returned to the
# target's recorded image ID (re-tag + recreate without build) and verified by image ID.
# When a recorded image is not available locally the rollback is refused, unless
# --allow-source-rebuild accepts a rebuild from the verified tree (NOT runtime-exact).
# Never runs migrations.
# Exit: 0 rolled back, 2 refused (nothing changed), 4 rollback failed (both trees kept).
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib.sh"

EXECUTE=0; ALLOW_REBUILD=0
for arg in "$@"; do
  case "$arg" in
    --yes) EXECUTE=1 ;;
    --allow-source-rebuild) ALLOW_REBUILD=1 ;;
    *) echo "usage: release_rollback.sh [--yes] [--allow-source-rebuild]" >&2; exit 3 ;;
  esac
done
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
copy_prefix C S

log "  current : $C_RELEASE_ID (${C_COMMIT}) rebuilt=[${C_SERVICES_REBUILT}] runtime=[${C_RUNTIME_IMAGES:-}]"
log "  target  : $V_RELEASE_ID (${V_COMMIT}) tree dir $V_TREE_DIR runtime=[${V_RUNTIME_IMAGES:-unknown}]"
log "  rollback target tree must be exactly $V_TREE:"
PYV_BUNDLE="$BUNDLE"
verify_tree "$V_TREE_DIR" "$V_TREE" "$V_LEGACY_EXTRAS" "${V_BUNDLE_DIR:-}" || refuse "rollback target $V_TREE_DIR does not match recorded tree (missing/tampered)"
log "  live repo is the current release:"
verify_tree repo "$C_TREE" "$C_LEGACY_EXTRAS" "${C_BUNDLE_DIR:-}" || refuse "live repo does not match the recorded current release"

[ -n "${C_RUNTIME_IMAGES:-}" ] || refuse "current release has no recorded runtime images"
runtime_snapshot || refuse "$RUNTIME_FAIL"
[ "$SNAP_IMAGES" = "$C_RUNTIME_IMAGES" ] || refuse "runtime drift: running images [$SNAP_IMAGES] are not the recorded runtime of $C_RELEASE_ID"

# services whose runtime must change: recorded images differ, or the target image is unknown
# for a service the current release rebuilt
RESTORE=""; EXACT_PLAN=""; REBUILD_PLAN=""
for svc in ${C_ALL_SERVICES//,/ }; do
  cid="$(csv_get "$C_RUNTIME_IMAGES" "$svc" || true)"; vid="$(csv_get "${V_RUNTIME_IMAGES:-}" "$svc" || true)"
  if [ -n "$vid" ]; then
    [ "$vid" = "$cid" ] && continue
  else
    case ",$C_SERVICES_REBUILT," in *",$svc,"*) ;; *) continue ;; esac
  fi
  RESTORE="${RESTORE:+$RESTORE,}$svc"
  if [[ "$vid" =~ $IMAGE_ID_RE ]] && [ "$(image_id "$vid")" = "$vid" ]; then
    EXACT_PLAN="${EXACT_PLAN:+$EXACT_PLAN }$svc=$vid"
  else
    REBUILD_PLAN="${REBUILD_PLAN:+$REBUILD_PLAN }$svc"
  fi
done
log "  runtime plan: exact image restore [${EXACT_PLAN:-none}]; source rebuild needed [${REBUILD_PLAN:-none}]"
if [ -n "$REBUILD_PLAN" ] && [ "$ALLOW_REBUILD" != 1 ]; then
  refuse "no recorded runtime image available locally for [$REBUILD_PLAN]: an exact runtime rollback is impossible; re-run with --allow-source-rebuild to rebuild from the verified source tree (not runtime-exact)"
fi

if [ "$EXECUTE" != 1 ]; then
  log "DRY RUN: would move repo -> repo.rolledback-$C_RELEASE_ID-<UTC>, $V_TREE_DIR -> repo, restore runtime [${RESTORE:-nothing}], smoke. Re-run with --yes."
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
  log "Current runtime images of $C_RELEASE_ID (still tagged $RELEASE_IMAGE_REPO/<service>:$C_RELEASE_ID): $C_RUNTIME_IMAGES"
  log "Manual roll-forward: cd $BASE && mv repo $V_TREE_DIR && mv $ROLLED repo, re-tag the images above and ${COMPOSE_CMD[*]} up -d --no-deps --no-build --force-recreate ${RESTORE//,/ }"
  write_record rollback ROLLBACK_FAILED V "$RESTORE" PASS FAIL "$1" "$C_RELEASE_ID" "$V_RELEASE_ID" "" FAILED
  exit 4
}
verify_tree repo "$V_TREE" "$V_LEGACY_EXTRAS" "${V_BUNDLE_DIR:-}" || fail4 "restored tree does not match $V_TREE"
restore_runtime V "$RESTORE" compose-rollback "$ALLOW_REBUILD" || fail4 "runtime restore: $RUNTIME_FAIL"
log "=== POST-ROLLBACK SMOKE ==="
smoke "$SINCE" "$RESTORE" "$C_RUNTIME_IMAGES" || fail4 "post-rollback smoke: $SMOKE_FAIL"
runtime_snapshot || fail4 "cannot record runtime images after rollback: $RUNTIME_FAIL"
[ "$RUNTIME_ROLLBACK" = SOURCE_REBUILD ] && { protect_images "$SNAP_IMAGES" "$V_RELEASE_ID" || true; }

mv "$STATE/previous.env" "$EVID/previous.env.consumed"
[ -f "$STATE/previous.json" ] && mv "$STATE/previous.json" "$EVID/previous.json.consumed"
dump_prefix V "$STATE/current.env" "TREE_DIR=repo" "SERVICES_REBUILT=$RESTORE" \
  "DEPLOYED_AT=rollback-$(now)" "PREVIOUS_RELEASE_ID=NONE" "RUNTIME_IMAGES=$SNAP_IMAGES" "RUNTIME_REFS=$SNAP_REFS"
[ -f "$STATE/manifests/$V_RELEASE_ID.json" ] && cp "$STATE/manifests/$V_RELEASE_ID.json" "$STATE/current.json"
write_markers V "$C_COMMIT" "$ROLLED" "$SNAP_IMAGES"
write_record rollback ROLLBACK_DONE V "$RESTORE" PASS PASS "" "$C_RELEASE_ID" "$V_RELEASE_ID" "$SNAP_IMAGES" "$RUNTIME_ROLLBACK"
if [ "$RUNTIME_ROLLBACK" = EXACT_IMAGE ]; then
  log "=== ROLLED BACK to $V_RELEASE_ID (${V_COMMIT}); source-exact and runtime-exact ($SNAP_IMAGES); $ROLLED retained ==="
else
  log "=== ROLLED BACK to $V_RELEASE_ID (${V_COMMIT}); source-exact, NOT runtime-exact (rebuilt from source); $ROLLED retained ==="
fi
exit 0
