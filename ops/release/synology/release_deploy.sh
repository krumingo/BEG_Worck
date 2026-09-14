#!/usr/bin/env bash
# W0-09A guarded deploy for the current Synology layout (compose + ./repo build context).
#
#   sudo bash <bundle>/tools/synology/release_deploy.sh
#
# A) PRECHECK — no mutation: bundle integrity + exact tree identity + layout/.env key names +
#    flag expectations + no declared migrations + state/version match + live repo tree +
#    running images = recorded runtime + free rollback/staging names + containers/health/
#    endpoints + backup.                                                  exit 2 on failure
# B) DEPLOY — stage-extract and re-verify, protect the current runtime images, rollback anchor
#    repo.rollback-<current release>, guarded swap, rebuild ONLY manifest.services_to_rebuild,
#    never run migrations.
# C) SMOKE — health, running containers, recreated containers, unchanged images of the other
#    services, restart-loop sample, endpoints, log scan, flag expectations.
#    Any failure => automatic rollback to the recorded source tree AND runtime images.
#                                                                          exit 1 rolled back
#                                                                          exit 4 rollback failed
# D) RECORD — runtime images, current/previous state, markers outside repo/, evidence. exit 0
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib.sh"
rel_setup deploy
trap 'lock_release' EXIT
lock_acquire

PRE_FAIL=""
precheck_fail() {
  log "PRECHECK FAILED: $1"
  log "NOTHING WAS CHANGED (no source swap, no container action)."
  write_record deploy PRECHECK_FAILED P "" FAIL SKIPPED "$1" "${C_RELEASE_ID:-NONE}" "${C_RELEASE_ID:-NONE}" "${C_RUNTIME_IMAGES:-}" NOT_APPLICABLE
  exit 2
}

# ============================================================== A) PRECHECK
log "=== A) PRECHECK (read-only) ==="
[ -f "$STATE/current.env" ] || precheck_fail "no current release recorded in $STATE; adopt the live deployment first (release_adopt.sh)"
read_kv "$STATE/current.env" C || precheck_fail "current.env is unreadable"

PYV_BUNDLE="$BUNDLE"
pyv bundle --bundle "$(vbundle)" --base "$(vbase)" --mode deploy \
    --plan-out "$(vpath "$EVID/plan.env")" --report-out "$(vpath "$EVID/verify.json")" 2>&1 | tr -d '\r' | sed 's/^/    /'
grep -q '"result": "PASS"' "$EVID/verify.json" 2>/dev/null || precheck_fail "bundle/layout verification failed (see verify.json)"
read_kv "$EVID/plan.env" P || precheck_fail "plan.env is unreadable"
copy_prefix P S

[ "$P_DEPLOYMENT_ID" = "$C_DEPLOYMENT_ID" ] || precheck_fail "manifest deployment $P_DEPLOYMENT_ID != recorded $C_DEPLOYMENT_ID"
[ "$P_ENVIRONMENT" = "$C_ENVIRONMENT" ] || precheck_fail "manifest environment $P_ENVIRONMENT != recorded $C_ENVIRONMENT"
[ "$P_RELEASE_ID" != "$C_RELEASE_ID" ] || precheck_fail "release $P_RELEASE_ID is already the current release"
[ "$P_PREVIOUS_RELEASE_ID" = "$C_RELEASE_ID" ] && [ "$P_PREVIOUS_TREE" = "$C_TREE" ] \
  || precheck_fail "version mismatch: manifest expects previous $P_PREVIOUS_RELEASE_ID/${P_PREVIOUS_TREE:0:12}, live is $C_RELEASE_ID/${C_TREE:0:12}"
[ "$P_MIGRATIONS_DECLARED" = 0 ] || precheck_fail "manifest declares migrations; W0-09A never runs migrations (separate approved step)"
[ "$C_TREE_DIR" = repo ] || precheck_fail "current.env TREE_DIR is $C_TREE_DIR, expected repo"
for svc in ${P_SERVICES_TO_REBUILD//,/ }; do
  case ",$P_ALL_SERVICES," in *",$svc,"*) ;; *) precheck_fail "service $svc is not part of the layout" ;; esac
done
log "  state: current $C_RELEASE_ID (${C_COMMIT:0:12}) -> target $P_RELEASE_ID (${P_COMMIT:0:12}); rebuild: ${P_SERVICES_TO_REBUILD:-none}"

log "  live source tree must be exactly the recorded current release:"
verify_tree repo "$C_TREE" "$C_LEGACY_EXTRAS" "${C_BUNDLE_DIR:-}" || precheck_fail "live $BASE/repo does not match recorded tree $C_TREE"
ROLLBACK_DIR="repo.rollback-$C_RELEASE_ID"
STAGE_DIR="repo.staging-$P_RELEASE_ID"
[ ! -e "$BASE/$ROLLBACK_DIR" ] || precheck_fail "rollback anchor name $ROLLBACK_DIR already exists"
[ ! -e "$BASE/$STAGE_DIR" ] || precheck_fail "staging name $STAGE_DIR already exists"

for c in ${P_CONTAINERS//,/ }; do
  st="$(cstate "$c")"; [ "${st%%|*}" = running ] || precheck_fail "container $c is not running before deploy (${st%%|*})"
done
[ -n "${C_RUNTIME_IMAGES:-}" ] || precheck_fail "current release has no recorded runtime images (adopt with this tool version first)"
runtime_snapshot || precheck_fail "$RUNTIME_FAIL"
[ "$SNAP_IMAGES" = "$C_RUNTIME_IMAGES" ] \
  || precheck_fail "runtime drift: running images [$SNAP_IMAGES] are not the recorded runtime of $C_RELEASE_ID [$C_RUNTIME_IMAGES]"
log "  running images are the recorded runtime of $C_RELEASE_ID"
for p in ${P_HTTP_PATHS//,/ }; do
  code="$(http_code "$p")"
  case "$code" in 2??|3??) ;; *) precheck_fail "pre-deploy GET $p returned $code" ;; esac
done
log "  containers running and endpoints healthy before deploy"
backup_check || precheck_fail "$PRE_FAIL"
log "=== PRECHECK PASSED ==="

# ============================================================== B) DEPLOY
log "=== B) DEPLOY ==="
DEPLOY_SINCE="$(now)"
mkdir "$BASE/$STAGE_DIR" || precheck_fail "cannot create staging directory $STAGE_DIR"
STAGE_HOST="$BASE/$STAGE_DIR"
pyv bundle --bundle "$(vbundle)" --mode deploy --stage "$(vpath "$STAGE_HOST/tree")" \
    --probe-dir "$(vpath "$STAGE_HOST")" --report-out "$(vpath "$EVID/stage.json")" 2>&1 | tr -d '\r' | sed 's/^/    /'
STAGE_HOST=""
if ! grep -q '"result": "PASS"' "$EVID/stage.json" 2>/dev/null || [ ! -d "$BASE/$STAGE_DIR/tree" ]; then
  rm -rf -- "${BASE:?}/$STAGE_DIR"
  precheck_fail "staged extraction did not verify against tree $P_TREE"
fi
protect_images "$C_RUNTIME_IMAGES" "$C_RELEASE_ID" || { rm -rf -- "${BASE:?}/$STAGE_DIR"; precheck_fail "$RUNTIME_FAIL"; }
record_base_images

auto_rollback() {
  local reason="$1" failed="repo.failed-$P_RELEASE_ID-$(stamp)" rb_since
  log "!!! AUTO-ROLLBACK: $reason"
  copy_prefix C S
  if [ -d "$BASE/repo" ]; then mv "$BASE/repo" "$BASE/$failed" && log "  failed tree kept as $failed"; fi
  if ! mv "$BASE/$ROLLBACK_DIR" "$BASE/repo"; then
    log "ROLLBACK FAILED: cannot restore $ROLLBACK_DIR"
    write_record deploy ROLLBACK_FAILED P "$P_SERVICES_TO_REBUILD" PASS FAIL "$reason; restore failed" "$C_RELEASE_ID" "$C_RELEASE_ID" "" FAILED; exit 4
  fi
  if ! verify_tree repo "$C_TREE" "$C_LEGACY_EXTRAS" "${C_BUNDLE_DIR:-}"; then
    write_record deploy ROLLBACK_FAILED P "$P_SERVICES_TO_REBUILD" PASS FAIL "$reason; restored tree mismatch" "$C_RELEASE_ID" "$C_RELEASE_ID" "" FAILED; exit 4
  fi
  rb_since="$(now)"
  if ! restore_runtime C "$P_SERVICES_TO_REBUILD" compose-rollback 1; then
    log "ROLLBACK FAILED: $RUNTIME_FAIL"
    write_record deploy ROLLBACK_FAILED P "$P_SERVICES_TO_REBUILD" PASS FAIL "$reason; runtime restore: $RUNTIME_FAIL" "$C_RELEASE_ID" "$C_RELEASE_ID" "" FAILED; exit 4
  fi
  log "  post-rollback smoke:"
  if ! smoke "$rb_since" "$P_SERVICES_TO_REBUILD" "$C_RUNTIME_IMAGES"; then
    log "ROLLBACK FAILED: post-rollback smoke: $SMOKE_FAIL"
    write_record deploy ROLLBACK_FAILED P "$P_SERVICES_TO_REBUILD" PASS FAIL "$reason; post-rollback smoke: $SMOKE_FAIL" "$C_RELEASE_ID" "$C_RELEASE_ID" "" "$RUNTIME_ROLLBACK"; exit 4
  fi
  runtime_snapshot || true
  if [ "$RUNTIME_ROLLBACK" = SOURCE_REBUILD ]; then
    dump_prefix C "$STATE/current.env" "RUNTIME_IMAGES=$SNAP_IMAGES" "RUNTIME_REFS=$SNAP_REFS" \
      && protect_images "$SNAP_IMAGES" "$C_RELEASE_ID" || true
    log "ROLLED BACK (source-exact, NOT runtime-exact: recorded image was unavailable and ${P_SERVICES_TO_REBUILD} was rebuilt)"
  else
    log "ROLLED BACK (source-exact and runtime-exact: recorded images restored)"
  fi
  log "ROLLED BACK: live release is still $C_RELEASE_ID (${C_COMMIT:0:12}); state unchanged"
  write_record deploy ROLLED_BACK P "$P_SERVICES_TO_REBUILD" PASS FAIL "$reason" "$C_RELEASE_ID" "$C_RELEASE_ID" "$SNAP_IMAGES" "$RUNTIME_ROLLBACK"
  exit 1
}

mv "$BASE/repo" "$BASE/$ROLLBACK_DIR" || { rm -rf -- "${BASE:?}/$STAGE_DIR"; precheck_fail "could not create rollback anchor"; }
if ! mv "$BASE/$STAGE_DIR/tree" "$BASE/repo"; then
  mv "$BASE/$ROLLBACK_DIR" "$BASE/repo"; rm -rf -- "${BASE:?}/$STAGE_DIR"
  precheck_fail "source swap failed; original repo restored"
fi
rmdir "$BASE/$STAGE_DIR" 2>/dev/null || true
log "  rollback anchor: $ROLLBACK_DIR; repo now holds $P_RELEASE_ID"
verify_tree repo "$P_TREE" NONE "$BUNDLE" || auto_rollback "active source tree does not match manifest tree $P_TREE (version mismatch)"

compose_up "$P_SERVICES_TO_REBUILD" compose-deploy || auto_rollback "docker compose up failed for ${P_SERVICES_TO_REBUILD} (startup failure)"
[ -n "$P_SERVICES_TO_REBUILD" ] || log "  no service inputs changed: no rebuild/restart"

# ============================================================== C) SMOKE
log "=== C) SMOKE ==="
smoke "$DEPLOY_SINCE" "$P_SERVICES_TO_REBUILD" "$C_RUNTIME_IMAGES" || auto_rollback "$SMOKE_FAIL"
runtime_snapshot || auto_rollback "cannot record the runtime images of the new release: $RUNTIME_FAIL"
NEW_IMAGES="$SNAP_IMAGES"; NEW_REFS="$SNAP_REFS"
protect_images "$NEW_IMAGES" "$P_RELEASE_ID" || auto_rollback "$RUNTIME_FAIL"
log "=== SMOKE PASSED === runtime: $NEW_IMAGES"

# ============================================================== D) RECORD
if [ -f "$STATE/previous.env" ]; then
  read_kv "$STATE/previous.env" OLD || true
  if [ -n "${OLD_TREE_DIR:-}" ] && [[ "$OLD_TREE_DIR" =~ $TREE_DIR_RE ]] && [ "$OLD_TREE_DIR" != repo ] && [ -d "$BASE/$OLD_TREE_DIR" ]; then
    mv "$BASE/$OLD_TREE_DIR" "$STATE/retired/$OLD_TREE_DIR-retired-$(stamp)" && log "  retired older rollback tree $OLD_TREE_DIR"
  fi
fi
dump_prefix C "$STATE/previous.env" "TREE_DIR=$ROLLBACK_DIR"
dump_prefix P "$STATE/current.env" "TREE_DIR=repo" "SERVICES_REBUILT=$P_SERVICES_TO_REBUILD" \
  "DEPLOYED_AT=$(now)" "BUNDLE_DIR=$BUNDLE" "LEGACY_EXTRAS=NONE" "PREVIOUS_RELEASE_ID=$C_RELEASE_ID" \
  "RUNTIME_IMAGES=$NEW_IMAGES" "RUNTIME_REFS=$NEW_REFS"
cp "$BUNDLE/manifest.json" "$STATE/manifests/$P_RELEASE_ID.json"
cp "$BUNDLE/manifest.json" "$STATE/current.json.tmp" && mv -f "$STATE/current.json.tmp" "$STATE/current.json"
[ -f "$STATE/manifests/$C_RELEASE_ID.json" ] && cp "$STATE/manifests/$C_RELEASE_ID.json" "$STATE/previous.json"
write_markers P "$C_COMMIT" "$ROLLBACK_DIR" "$NEW_IMAGES"
write_record deploy DEPLOYED P "$P_SERVICES_TO_REBUILD" PASS PASS "" "$C_RELEASE_ID" "$C_RELEASE_ID" "$NEW_IMAGES" NOT_APPLICABLE
log "=== DEPLOYED $P_RELEASE_ID (${P_COMMIT}) — rollback target $C_RELEASE_ID kept at $ROLLBACK_DIR (runtime $C_RUNTIME_IMAGES); migrations NOT_RUN ==="
exit 0
