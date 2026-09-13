#!/usr/bin/env bash
# W0-09A guarded deploy for the current Synology layout (compose + ./repo build context).
#
#   sudo bash <bundle>/tools/synology/release_deploy.sh
#
# A) PRECHECK — no mutation: bundle integrity + exact tree identity + layout/.env key names +
#    flag expectations + no declared migrations + state/version match + live repo tree +
#    free rollback/staging names + containers/health/endpoints + backup.      exit 2 on failure
# B) DEPLOY — stage-extract and re-verify, rollback anchor repo.rollback-<current release>,
#    guarded swap, rebuild ONLY manifest.services_to_rebuild, never run migrations.
# C) SMOKE — health, running containers, recreated containers, restart-loop sample, endpoints,
#    log scan, flag expectations. Any failure => automatic rollback.        exit 1 rolled back
#                                                                          exit 4 rollback failed
# D) RECORD — current/previous state, markers outside repo/, evidence.     exit 0 deployed
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
  write_record deploy PRECHECK_FAILED P "" FAIL SKIPPED "$1" "${C_RELEASE_ID:-NONE}" "${C_RELEASE_ID:-NONE}"
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
pyv bundle --bundle "$(vbundle)" --base "$(vbase)" --mode deploy --stage "$(vpath "$BASE/$STAGE_DIR")" \
    --probe-dir "$(vpath "$EVID")" --report-out "$(vpath "$EVID/stage.json")" 2>&1 | tr -d '\r' | sed 's/^/    /'
if ! grep -q '"result": "PASS"' "$EVID/stage.json" 2>/dev/null; then
  rm -rf -- "${BASE:?}/$STAGE_DIR"
  precheck_fail "staged extraction did not verify against tree $P_TREE"
fi

auto_rollback() {
  local reason="$1" failed="repo.failed-$P_RELEASE_ID-$(stamp)"
  log "!!! AUTO-ROLLBACK: $reason"
  copy_prefix C S
  if [ -d "$BASE/repo" ]; then mv "$BASE/repo" "$BASE/$failed" && log "  failed tree kept as $failed"; fi
  if ! mv "$BASE/$ROLLBACK_DIR" "$BASE/repo"; then
    log "ROLLBACK FAILED: cannot restore $ROLLBACK_DIR"
    write_record deploy ROLLBACK_FAILED P "$P_SERVICES_TO_REBUILD" PASS FAIL "$reason; restore failed" "$C_RELEASE_ID" "$C_RELEASE_ID"; exit 4
  fi
  if ! verify_tree repo "$C_TREE" "$C_LEGACY_EXTRAS" "${C_BUNDLE_DIR:-}"; then
    write_record deploy ROLLBACK_FAILED P "$P_SERVICES_TO_REBUILD" PASS FAIL "$reason; restored tree mismatch" "$C_RELEASE_ID" "$C_RELEASE_ID"; exit 4
  fi
  local rb_since; rb_since="$(now)"
  if ! compose_up "$P_SERVICES_TO_REBUILD" compose-rollback; then
    write_record deploy ROLLBACK_FAILED P "$P_SERVICES_TO_REBUILD" PASS FAIL "$reason; rollback rebuild failed" "$C_RELEASE_ID" "$C_RELEASE_ID"; exit 4
  fi
  log "  post-rollback smoke:"
  if ! smoke "$rb_since" "$P_SERVICES_TO_REBUILD"; then
    log "ROLLBACK FAILED: post-rollback smoke: $SMOKE_FAIL"
    write_record deploy ROLLBACK_FAILED P "$P_SERVICES_TO_REBUILD" PASS FAIL "$reason; post-rollback smoke: $SMOKE_FAIL" "$C_RELEASE_ID" "$C_RELEASE_ID"; exit 4
  fi
  log "ROLLED BACK: live release is still $C_RELEASE_ID (${C_COMMIT:0:12}); state unchanged"
  write_record deploy ROLLED_BACK P "$P_SERVICES_TO_REBUILD" PASS FAIL "$reason" "$C_RELEASE_ID" "$C_RELEASE_ID"
  exit 1
}

mv "$BASE/repo" "$BASE/$ROLLBACK_DIR" || { rm -rf -- "${BASE:?}/$STAGE_DIR"; precheck_fail "could not create rollback anchor"; }
if ! mv "$BASE/$STAGE_DIR" "$BASE/repo"; then
  mv "$BASE/$ROLLBACK_DIR" "$BASE/repo"; rm -rf -- "${BASE:?}/$STAGE_DIR"
  precheck_fail "source swap failed; original repo restored"
fi
log "  rollback anchor: $ROLLBACK_DIR; repo now holds $P_RELEASE_ID"
verify_tree repo "$P_TREE" NONE "$BUNDLE" || auto_rollback "active source tree does not match manifest tree $P_TREE (version mismatch)"

compose_up "$P_SERVICES_TO_REBUILD" compose-deploy || auto_rollback "docker compose up failed for ${P_SERVICES_TO_REBUILD} (startup failure)"
[ -n "$P_SERVICES_TO_REBUILD" ] || log "  no service inputs changed: no rebuild/restart"

# ============================================================== C) SMOKE
log "=== C) SMOKE ==="
smoke "$DEPLOY_SINCE" "$P_SERVICES_TO_REBUILD" || auto_rollback "$SMOKE_FAIL"
log "=== SMOKE PASSED ==="

# ============================================================== D) RECORD
if [ -f "$STATE/previous.env" ]; then
  read_kv "$STATE/previous.env" OLD || true
  if [ -n "${OLD_TREE_DIR:-}" ] && [[ "$OLD_TREE_DIR" =~ $TREE_DIR_RE ]] && [ "$OLD_TREE_DIR" != repo ] && [ -d "$BASE/$OLD_TREE_DIR" ]; then
    mv "$BASE/$OLD_TREE_DIR" "$STATE/retired/$OLD_TREE_DIR-retired-$(stamp)" && log "  retired older rollback tree $OLD_TREE_DIR"
  fi
fi
dump_prefix C "$STATE/previous.env" "TREE_DIR=$ROLLBACK_DIR"
dump_prefix P "$STATE/current.env" "TREE_DIR=repo" "SERVICES_REBUILT=$P_SERVICES_TO_REBUILD" \
  "DEPLOYED_AT=$(now)" "BUNDLE_DIR=$BUNDLE" "LEGACY_EXTRAS=NONE" "PREVIOUS_RELEASE_ID=$C_RELEASE_ID"
cp "$BUNDLE/manifest.json" "$STATE/manifests/$P_RELEASE_ID.json"
cp "$BUNDLE/manifest.json" "$STATE/current.json.tmp" && mv -f "$STATE/current.json.tmp" "$STATE/current.json"
[ -f "$STATE/manifests/$C_RELEASE_ID.json" ] && cp "$STATE/manifests/$C_RELEASE_ID.json" "$STATE/previous.json"
write_markers P "$C_COMMIT" "$ROLLBACK_DIR"
write_record deploy DEPLOYED P "$P_SERVICES_TO_REBUILD" PASS PASS "" "$C_RELEASE_ID" "$C_RELEASE_ID"
log "=== DEPLOYED $P_RELEASE_ID (${P_COMMIT}) — rollback target $C_RELEASE_ID kept at $ROLLBACK_DIR; migrations NOT_RUN ==="
exit 0
