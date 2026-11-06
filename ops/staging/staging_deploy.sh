#!/usr/bin/env bash
# ST-02 — W0-09A deploy / smoke / exact-image rollback on the ISOLATED staging compose project.
#
#   BEGWORK_BASE=<staging layout root> bash ops/staging/staging_deploy.sh --bundle <bundle> --initial
#   BEGWORK_BASE=<staging layout root> bash ops/staging/staging_deploy.sh --bundle <bundle> --deploy [--force-smoke-fail]
#
# The logic is release_deploy.sh's: it SOURCES the release's own tools/synology/lib.sh (unchanged)
# and calls the same verifier, verify_tree, compose_up, smoke, restore_runtime, runtime_snapshot,
# protect_images and write_record. What differs for staging, and only here:
#
#   * compose runs as `docker compose -p $ST02_PROJECT -f docker-compose.yml -f docker-compose.staging.yml`
#     (the production compose file stays byte-identical; the overlay renames containers, replaces the
#     port, adds an own network and an own MongoDB replica set) and refuses to run unless
#     `compose config` proves that isolation (assert_isolated);
#   * the manifest's container names, smoke base URL and flag expectation describe the production
#     layout; staging_overrides() maps them to the staging containers/port and to the staging
#     PERMISSION_SERVICE_MODE parameter, after EVERY copy into S_* (plan, current, rollback);
#   * RC-01 build identity: write_build_info.py --from-bundle stamps backend/ and frontend/
#     BUILD_INFO.json into the staged tree (declared as the only allowed extra files of the tree)
#     and every service is rebuilt, so the UI and /api/version carry the bundle commit;
#   * PERMISSION_SERVICE_MODE defaults to shadow (R15) when staging.env does not set it; enforce/off
#     only as an explicit staging parameter (ST-02-C02, FG-2);
#   * FG-3: after the smoke the flag value really running in the backend is read and must equal the
#     staging parameter (unset = refused); staging-deployment.json next to record.json keeps the
#     manifest expectation, the staging parameter and the observed value side by side;
#   * FG-4: ST02_DEPLOYED_BY and ST02_APPROVED_BY are mandatory (refused otherwise); the deployer is
#     the record's actor, both are in staging-deployment.json;
#   * a gzip mongodump of the staging database is the pre-deploy backup;
#   * --force-smoke-fail adds a controlled extra smoke path that must fail (rollback rehearsal);
#     the post-rollback smoke never includes it.
#
# Refuses (exit 3) a production layout root, a non-staging project name or a compose model that
# still contains a production container name or port. Exit codes as release_deploy.sh:
# 0 deployed, 1 rolled back, 2 precheck failed (no change), 3 usage/isolation, 4 rollback failed.
set -u

MODE=""; BUNDLE_ARG=""; FORCE_SMOKE_FAIL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --bundle) BUNDLE_ARG="${2:-}"; shift ;;
    --initial) MODE=initial ;;
    --deploy) MODE=deploy ;;
    --force-smoke-fail) FORCE_SMOKE_FAIL=1 ;;
    *) echo "usage: BEGWORK_BASE=<staging root> $0 --bundle <bundle> (--initial|--deploy) [--force-smoke-fail]" >&2; exit 3 ;;
  esac; shift
done
[ -n "$MODE" ] && [ -n "$BUNDLE_ARG" ] && [ -d "$BUNDLE_ARG/tools/synology" ] \
  || { echo "usage: BEGWORK_BASE=<staging root> $0 --bundle <bundle> (--initial|--deploy) [--force-smoke-fail]" >&2; exit 3; }
[ "$MODE" = deploy ] || [ "$FORCE_SMOKE_FAIL" = 0 ] || { echo "--force-smoke-fail is only for --deploy" >&2; exit 3; }

ST02_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STAGING_BASE="${BEGWORK_BASE:-}"
STAGING_BASE="${STAGING_BASE%/}"
PRODUCTION_BASE="/volume1/docker/begwork"
case "$STAGING_BASE" in
  ""|"$PRODUCTION_BASE"|"$PRODUCTION_BASE"/*) echo "refused: BEGWORK_BASE must be an own staging layout root, never $PRODUCTION_BASE" >&2; exit 3 ;;
esac
[ -f "$STAGING_BASE/.st02-staging-root" ] || { echo "refused: $STAGING_BASE has no .st02-staging-root marker (create it with staging_up.py)" >&2; exit 3; }

# --- the release's own shared functions (unchanged) --------------------------------------------
SCRIPT_DIR="$(cd "$BUNDLE_ARG/tools/synology" && pwd)"
# shellcheck source=/dev/null
. "$SCRIPT_DIR/lib.sh"
# read_kv before rel_setup: it only logs on failure
read_kv "$STAGING_BASE/staging.env" ST || { echo "refused: $STAGING_BASE/staging.env is unreadable" >&2; exit 3; }
[[ "${ST_ST02_PROJECT:-}" =~ ^begwork-staging[a-z0-9-]*$ ]] || { echo "refused: ST02_PROJECT must start with begwork-staging" >&2; exit 3; }
[[ "${ST_ST02_HTTP_PORT:-}" =~ ^[0-9]{4,5}$ ]] && [ "$ST_ST02_HTTP_PORT" != 8080 ] || { echo "refused: ST02_HTTP_PORT must be a free port other than 8080" >&2; exit 3; }
# R15: staging = shadow unless staging.env sets another mode explicitly (ST-02-C02 / FG-2)
ST02_DEFAULT_MODE=shadow
MODE_SOURCE="explicit staging parameter"
[ -n "${ST_ST02_PERMISSION_SERVICE_MODE:-}" ] || { ST_ST02_PERMISSION_SERVICE_MODE="$ST02_DEFAULT_MODE"; MODE_SOURCE="R15 default"; }
case "$ST_ST02_PERMISSION_SERVICE_MODE" in off|shadow|enforce) ;; *) echo "refused: ST02_PERMISSION_SERVICE_MODE must be off, shadow or enforce" >&2; exit 3 ;; esac
# FG-4 (FLOW-050: deployed_by / approved_by): named people, never the "unknown" fallback
PERSON_RE='^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'
for _who in ST02_DEPLOYED_BY ST02_APPROVED_BY; do
  _val="${!_who:-}"
  if ! [[ "$_val" =~ $PERSON_RE ]] || [[ "${_val,,}" =~ ^(unknown|none|root)$ ]]; then
    echo "refused: $_who is required (plain identifier of the person, never unknown/none/root; FLOW-050 deployed_by/approved_by)" >&2; exit 3
  fi
done
unset _who _val
# lib.sh takes the record actor from SUDO_USER/USER; the named deployer replaces the login name
unset SUDO_USER; export USER="$ST02_DEPLOYED_BY"
PROJECT="$ST_ST02_PROJECT"
export COMPOSE_BIN="docker compose -p $PROJECT -f docker-compose.yml -f docker-compose.staging.yml"
export BEGWORK_BASE="$STAGING_BASE"
rel_setup deploy
trap 'lock_release' EXIT
lock_acquire
log "ST-02 staging $MODE: project=$PROJECT port=$ST_ST02_HTTP_PORT PERMISSION_SERVICE_MODE=$ST_ST02_PERMISSION_SERVICE_MODE ($MODE_SOURCE) force_smoke_fail=$FORCE_SMOKE_FAIL"
log "  deployed_by=$ST02_DEPLOYED_BY approved_by=$ST02_APPROVED_BY"

FORCED_PATH="/api/st02-forced-smoke-failure"
staging_overrides() { # staging_overrides [forced] : S_* production layout values -> staging project
  S_SERVICE_CONTAINERS="backend:$PROJECT-backend,frontend:$PROJECT-frontend"
  S_CONTAINERS="$PROJECT-backend,$PROJECT-frontend"
  S_LOG_CONTAINER="$PROJECT-backend"
  S_HEALTH_BASE_URL="http://127.0.0.1:$ST_ST02_HTTP_PORT"
  S_FLAG_EXPECT_PERMISSION_SERVICE_MODE="$ST_ST02_PERMISSION_SERVICE_MODE"
  [ -z "${ST_ST02_RESTART_SAMPLE_SEC:-}" ] || S_RESTART_SAMPLE_SEC="$ST_ST02_RESTART_SAMPLE_SEC"
  if [ "${1:-}" = forced ]; then
    S_HTTP_PATHS="$S_HTTP_PATHS,$FORCED_PATH"
    log "  CONTROLLED SMOKE FAILURE armed: smoke also requires GET $FORCED_PATH (does not exist -> 404)"
  fi
}

# FG-3: the flag value the staging backend really runs with (the mode is not a secret).
OBSERVED_FLAG=""; FLAG_FAIL=""
observe_flag() {
  if OBSERVED_FLAG="$("$DOCKER" exec "$PROJECT-backend" printenv PERMISSION_SERVICE_MODE 2>/dev/null)"; then
    OBSERVED_FLAG="${OBSERVED_FLAG//$'\r'/}"
  else
    OBSERVED_FLAG="UNSET"
  fi
  [[ "$OBSERVED_FLAG" =~ ^(off|shadow|enforce|UNSET)$ ]] || OBSERVED_FLAG="INVALID"
  [ "$OBSERVED_FLAG" = "$ST_ST02_PERMISSION_SERVICE_MODE" ] || {
    FLAG_FAIL="PERMISSION_SERVICE_MODE running in $PROJECT-backend is $OBSERVED_FLAG, staging parameter is $ST_ST02_PERMISSION_SERVICE_MODE"; return 1; }
  log "  flag PERMISSION_SERVICE_MODE observed in $PROJECT-backend = $OBSERVED_FLAG (= staging parameter, $MODE_SOURCE; manifest expectation ${P_FLAG_EXPECT_PERMISSION_SERVICE_MODE:-?} is the production layout's)"
}

# staging_record STATUS : staging-deployment.json next to lib.sh's record.json (FG-3 + FG-4)
staging_record() {
  local eq=false
  [ "${OBSERVED_FLAG:-}" = "$ST_ST02_PERMISSION_SERVICE_MODE" ] && eq=true
  cat > "$EVID/staging-deployment.json" <<JSON
{
  "schema": "beg.st02-staging-deployment/v1",
  "status": "$1",
  "release_id": "${P_RELEASE_ID:-}",
  "deployment_id": "${P_DEPLOYMENT_ID:-}",
  "environment": "${P_ENVIRONMENT:-}",
  "project": "$PROJECT",
  "deployed_by": "$ST02_DEPLOYED_BY",
  "approved_by": "$ST02_APPROVED_BY",
  "feature_flags": {
    "PERMISSION_SERVICE_MODE": {
      "manifest_expected": "${P_FLAG_EXPECT_PERMISSION_SERVICE_MODE:-}",
      "manifest_expected_scope": "production layout (ops/release/synology/layout.json); staging overlay = staging_parameter",
      "staging_parameter": "$ST_ST02_PERMISSION_SERVICE_MODE",
      "staging_parameter_source": "$MODE_SOURCE",
      "observed_in_backend": "${OBSERVED_FLAG:-NOT_OBSERVED}",
      "observed_equals_parameter": $eq
    }
  }
}
JSON
}

STAGE_FAIL=""
staging_fail() { # precheck-type refusal: nothing was changed
  log "STAGING PRECHECK FAILED: $1"
  log "NOTHING WAS CHANGED (no source swap, no container action)."
  [ -n "${P_RELEASE_ID:-}" ] && write_record deploy PRECHECK_FAILED P "" FAIL SKIPPED "$1" "${C_RELEASE_ID:-NONE}" "${C_RELEASE_ID:-NONE}" "${C_RUNTIME_IMAGES:-}" NOT_APPLICABLE
  exit 2
}

# assert_isolated: the merged compose model must be the staging project and nothing else
# (ST-02-C01: incl. the backend database target, bind mounts, docker socket and privileges).
assert_isolated() {
  local out root
  root="$(cd "$BASE" && pwd)" || return 1   # the path compose resolves ./uploads etc. against
  out="$( (cd "$BASE" && "${COMPOSE_CMD[@]}" config --format json) 2>/dev/null \
    | "$DOCKER" run --rm -i --pull never --network none --read-only --security-opt no-new-privileges \
        -e ST02_PROJECT="$PROJECT" -e ST02_HTTP_PORT="$ST_ST02_HTTP_PORT" -e ST02_MODE="$ST_ST02_PERMISSION_SERVICE_MODE" \
        -e ST02_BASE="$root" -e ST02_ALLOWED_MONGO_HOSTS="${ST_ST02_ALLOWED_MONGO_HOSTS:-}" \
        -v "$ST02_DIR/isolation_check.py:/isolation_check.py:ro" \
        "$VERIFIER_IMAGE" python3 /isolation_check.py 2>&1 | tr -d '\r')"
  printf '%s\n' "$out" | sed 's/^/    /'
  printf '%s\n' "$out" | grep -q '^ISOLATION PASS$'
}

git_blob() { { printf 'blob %s\0' "$(wc -c < "$1" | tr -d ' ')"; cat "$1"; } | sha1sum | cut -c1-40; }

# stamp_build_info DIR (host path) -> STAMP_EXTRAS "backend/BUILD_INFO.json=<blob>,frontend/...=<blob>"
stamp_build_info() {
  local dir="$1" f out
  out="$("$DOCKER" run --rm --pull never --network none --read-only --security-opt no-new-privileges \
      -e PYTHONDONTWRITEBYTECODE=1 -v "$BUNDLE:/bundle:ro" -v "$dir:/target" \
      "$VERIFIER_IMAGE" python3 /bundle/tools/write_build_info.py --from-bundle /bundle --target /target 2>&1 | tr -d '\r')" \
    || { STAGE_FAIL="write_build_info.py --from-bundle failed: $(sanitize "$out")"; return 1; }
  printf '%s\n' "$out" | sed 's/^/    /'
  STAMP_EXTRAS=""
  for f in backend/BUILD_INFO.json frontend/BUILD_INFO.json; do
    [ -f "$dir/$f" ] && grep -q "\"build_sha\": *\"$P_COMMIT\"" "$dir/$f" \
      || { STAGE_FAIL="$f does not carry the bundle commit $P_COMMIT"; return 1; }
    STAMP_EXTRAS="${STAMP_EXTRAS:+$STAMP_EXTRAS,}$f=$(git_blob "$dir/$f")"
  done
  log "  RC-01 build identity stamped: $STAMP_EXTRAS"
}

staging_backup() { # gzip mongodump of the staging replica set into $BASE/backups (pre-deploy backup)
  local f="$BASE/backups/st02-$(stamp).archive.gz"
  mkdir -p "$BASE/backups"
  "$DOCKER" exec "$PROJECT-mongo" mongodump --quiet --archive --gzip > "$f" 2>/dev/null && gzip -t "$f" \
    || { rm -f "$f"; return 1; }
  log "  staging backup: $(basename "$f") ($(wc -c < "$f" | tr -d ' ') bytes)"
}

# ============================================================== A) PRECHECK
log "=== A) PRECHECK (read-only) ==="
if [ "$MODE" = initial ]; then
  [ ! -f "$STATE/current.env" ] || { log "refused: $STATE/current.env exists (use --deploy)"; exit 3; }
else
  [ -f "$STATE/current.env" ] || { log "refused: no current release recorded (use --initial)"; exit 3; }
  read_kv "$STATE/current.env" C || { log "refused: current.env is unreadable"; exit 3; }
fi

PYV_BUNDLE="$BUNDLE"
pyv bundle --bundle "$(vbundle)" --base "$(vbase)" --mode deploy \
    --plan-out "$(vpath "$EVID/plan.env")" --report-out "$(vpath "$EVID/verify.json")" 2>&1 | tr -d '\r' | sed 's/^/    /'
grep -q '"result": "PASS"' "$EVID/verify.json" 2>/dev/null || staging_fail "bundle/layout verification failed (see verify.json)"
read_kv "$EVID/plan.env" P || staging_fail "plan.env is unreadable"
copy_prefix P S
staging_overrides
[ "$P_ENVIRONMENT" = staging ] || staging_fail "manifest environment is $P_ENVIRONMENT; the staging stack only runs environment=staging bundles"
[ "$P_MIGRATIONS_DECLARED" = 0 ] || staging_fail "manifest declares migrations; W0-09A never runs migrations"
log "  isolation of the merged compose model:"
assert_isolated || { log "REFUSED: compose model is not isolated (see above)"; exit 3; }
REBUILD="$P_ALL_SERVICES"   # RC-01: each release stamps its own BUILD_INFO.json into every image
log "  manifest services_to_rebuild=${P_SERVICES_TO_REBUILD:-none}; staging rebuilds $REBUILD (build identity in every image)"
st="$(cstate "$PROJECT-mongo")"; [ "${st%%|*}" = running ] || staging_fail "staging MongoDB $PROJECT-mongo is not running"
MONGO_CONTAINER_ID="$("$DOCKER" inspect -f '{{.Id}}' "$PROJECT-mongo" 2>/dev/null)"
log "  staging MongoDB container $PROJECT-mongo id=${MONGO_CONTAINER_ID:0:12} (not part of any release)"

if [ "$MODE" = initial ]; then
  [ ! -e "$BASE/repo" ] || staging_fail "$BASE/repo already exists"
  C_RELEASE_ID=NONE
else
  [ "$P_DEPLOYMENT_ID" = "$C_DEPLOYMENT_ID" ] || staging_fail "manifest deployment $P_DEPLOYMENT_ID != recorded $C_DEPLOYMENT_ID"
  [ "$P_ENVIRONMENT" = "$C_ENVIRONMENT" ] || staging_fail "manifest environment $P_ENVIRONMENT != recorded $C_ENVIRONMENT"
  [ "$P_RELEASE_ID" != "$C_RELEASE_ID" ] || staging_fail "release $P_RELEASE_ID is already the current release"
  [ "$P_PREVIOUS_RELEASE_ID" = "$C_RELEASE_ID" ] && [ "$P_PREVIOUS_TREE" = "$C_TREE" ] \
    || staging_fail "version mismatch: manifest expects previous $P_PREVIOUS_RELEASE_ID/${P_PREVIOUS_TREE:0:12}, live is $C_RELEASE_ID/${C_TREE:0:12}"
  [ "$C_TREE_DIR" = repo ] || staging_fail "current.env TREE_DIR is $C_TREE_DIR, expected repo"
  log "  state: current $C_RELEASE_ID (${C_COMMIT:0:12}) -> target $P_RELEASE_ID (${P_COMMIT:0:12})"
  log "  live source tree must be exactly the recorded current release (+ its BUILD_INFO.json):"
  verify_tree repo "$C_TREE" "$C_LEGACY_EXTRAS" "${C_BUNDLE_DIR:-}" || staging_fail "live $BASE/repo does not match recorded tree $C_TREE"
  ROLLBACK_DIR="repo.rollback-$C_RELEASE_ID"
  [ ! -e "$BASE/$ROLLBACK_DIR" ] || staging_fail "rollback anchor name $ROLLBACK_DIR already exists"
  for c in ${S_CONTAINERS//,/ }; do
    st="$(cstate "$c")"; [ "${st%%|*}" = running ] || staging_fail "container $c is not running before deploy (${st%%|*})"
  done
  [ -n "${C_RUNTIME_IMAGES:-}" ] || staging_fail "current release has no recorded runtime images"
  runtime_snapshot || staging_fail "$RUNTIME_FAIL"
  [ "$SNAP_IMAGES" = "$C_RUNTIME_IMAGES" ] \
    || staging_fail "runtime drift: running images [$SNAP_IMAGES] are not the recorded runtime of $C_RELEASE_ID [$C_RUNTIME_IMAGES]"
  log "  running images are the recorded runtime of $C_RELEASE_ID"
  for p in ${S_HTTP_PATHS//,/ }; do
    code="$(http_code "$p")"
    case "$code" in 2??|3??) ;; *) staging_fail "pre-deploy GET $p returned $code" ;; esac
  done
  log "  containers running and endpoints healthy before deploy"
  staging_backup || staging_fail "staging mongodump backup failed"
  backup_check || staging_fail "$PRE_FAIL"
fi
STAGE_DIR="repo.staging-$P_RELEASE_ID"
[ ! -e "$BASE/$STAGE_DIR" ] || staging_fail "staging name $STAGE_DIR already exists"
log "=== PRECHECK PASSED ==="

# ============================================================== B) DEPLOY
log "=== B) DEPLOY ==="
DEPLOY_SINCE="$(now)"
mkdir "$BASE/$STAGE_DIR" || staging_fail "cannot create staging directory $STAGE_DIR"
STAGE_HOST="$BASE/$STAGE_DIR"
pyv bundle --bundle "$(vbundle)" --mode deploy --stage "$(vpath "$STAGE_HOST/tree")" \
    --probe-dir "$(vpath "$STAGE_HOST")" --report-out "$(vpath "$EVID/stage.json")" 2>&1 | tr -d '\r' | sed 's/^/    /'
STAGE_HOST=""
if ! grep -q '"result": "PASS"' "$EVID/stage.json" 2>/dev/null || [ ! -d "$BASE/$STAGE_DIR/tree" ]; then
  rm -rf -- "${BASE:?}/$STAGE_DIR"; staging_fail "staged extraction did not verify against tree $P_TREE"
fi
stamp_build_info "$BASE/$STAGE_DIR/tree" || { rm -rf -- "${BASE:?}/$STAGE_DIR"; staging_fail "$STAGE_FAIL"; }
NEW_EXTRAS="$STAMP_EXTRAS"
if [ "$MODE" = deploy ]; then
  protect_images "$C_RUNTIME_IMAGES" "$C_RELEASE_ID" || { rm -rf -- "${BASE:?}/$STAGE_DIR"; staging_fail "$RUNTIME_FAIL"; }
fi
record_base_images

auto_rollback() {
  local reason="$1" failed="repo.failed-$P_RELEASE_ID-$(stamp)" rb_since
  log "!!! AUTO-ROLLBACK: $reason"
  # evidence of what the failed release really ran and served (allowlisted /api/version field only)
  local failed_sha
  if runtime_snapshot; then log "  failed release $P_RELEASE_ID was running: $SNAP_IMAGES"
    printf 'release_id=%s\ncommit=%s\nruntime_images=%s\n' "$P_RELEASE_ID" "$P_COMMIT" "$SNAP_IMAGES" > "$EVID/failed-release-runtime.txt"
  fi
  failed_sha="$("$CURL" -s --max-time 10 "${S_HEALTH_BASE_URL}/api/version" 2>/dev/null | grep -oE '"build_sha": *"[0-9a-f]{40}"' | grep -oE '[0-9a-f]{40}' || true)"
  log "  failed release was serving /api/version build_sha=${failed_sha:-unreadable}"
  [ -z "$failed_sha" ] || printf 'served_build_sha=%s\n' "$failed_sha" >> "$EVID/failed-release-runtime.txt"
  copy_prefix C S
  staging_overrides            # the post-rollback smoke never carries the forced failure
  if [ -d "$BASE/repo" ]; then mv "$BASE/repo" "$BASE/$failed" && log "  failed tree kept as $failed"; fi
  if ! mv "$BASE/$ROLLBACK_DIR" "$BASE/repo"; then
    log "ROLLBACK FAILED: cannot restore $ROLLBACK_DIR"
    write_record deploy ROLLBACK_FAILED P "$REBUILD" PASS FAIL "$reason; restore failed" "$C_RELEASE_ID" "$C_RELEASE_ID" "" FAILED; exit 4
  fi
  if ! verify_tree repo "$C_TREE" "$C_LEGACY_EXTRAS" "${C_BUNDLE_DIR:-}"; then
    write_record deploy ROLLBACK_FAILED P "$REBUILD" PASS FAIL "$reason; restored tree mismatch" "$C_RELEASE_ID" "$C_RELEASE_ID" "" FAILED; exit 4
  fi
  rb_since="$(now)"
  if ! restore_runtime C "$REBUILD" compose-rollback 1; then
    log "ROLLBACK FAILED: $RUNTIME_FAIL"
    write_record deploy ROLLBACK_FAILED P "$REBUILD" PASS FAIL "$reason; runtime restore: $RUNTIME_FAIL" "$C_RELEASE_ID" "$C_RELEASE_ID" "" FAILED; exit 4
  fi
  log "  post-rollback smoke:"
  if ! smoke "$rb_since" "$REBUILD" "$C_RUNTIME_IMAGES"; then
    log "ROLLBACK FAILED: post-rollback smoke: $SMOKE_FAIL"
    write_record deploy ROLLBACK_FAILED P "$REBUILD" PASS FAIL "$reason; post-rollback smoke: $SMOKE_FAIL" "$C_RELEASE_ID" "$C_RELEASE_ID" "" "$RUNTIME_ROLLBACK"; exit 4
  fi
  runtime_snapshot || true
  observe_flag || log "  WARNING after rollback: $FLAG_FAIL"
  staging_record ROLLED_BACK
  if [ "$RUNTIME_ROLLBACK" = SOURCE_REBUILD ]; then
    log "ROLLED BACK (source-exact, NOT runtime-exact: recorded image was unavailable)"
  else
    log "ROLLED BACK (source-exact and runtime-exact: recorded images restored)"
  fi
  [ "$("$DOCKER" inspect -f '{{.Id}}' "$PROJECT-mongo" 2>/dev/null)" = "$MONGO_CONTAINER_ID" ] \
    && log "  staging MongoDB container unchanged (${MONGO_CONTAINER_ID:0:12}): data was not touched"
  log "ROLLED BACK: live release is still $C_RELEASE_ID (${C_COMMIT:0:12}); state unchanged"
  write_record deploy ROLLED_BACK P "$REBUILD" PASS FAIL "$reason" "$C_RELEASE_ID" "$C_RELEASE_ID" "$SNAP_IMAGES" "$RUNTIME_ROLLBACK"
  exit 1
}

initial_fail() { # first release: there is nothing to roll back to; keep everything for inspection
  log "STAGING INITIAL DEPLOY FAILED: $1"
  log "  containers and $BASE/repo are left as they are for inspection; nothing to roll back to"
  printf 'failed_at=%s\nreason=%s\n' "$(now)" "$(sanitize "$1")" > "$EVID/initial-failure.txt"
  staging_record INITIAL_FAILED
  exit 4
}

if [ "$MODE" = initial ]; then
  mv "$BASE/$STAGE_DIR/tree" "$BASE/repo" || { rm -rf -- "${BASE:?}/$STAGE_DIR"; staging_fail "could not move the staged tree to repo"; }
  rmdir "$BASE/$STAGE_DIR" 2>/dev/null || true
  verify_tree repo "$P_TREE" "$NEW_EXTRAS" "$BUNDLE" || initial_fail "active source tree does not match manifest tree $P_TREE"
  compose_up "$REBUILD" compose-deploy || initial_fail "docker compose up failed for $REBUILD"
else
  mv "$BASE/repo" "$BASE/$ROLLBACK_DIR" || { rm -rf -- "${BASE:?}/$STAGE_DIR"; staging_fail "could not create rollback anchor"; }
  if ! mv "$BASE/$STAGE_DIR/tree" "$BASE/repo"; then
    mv "$BASE/$ROLLBACK_DIR" "$BASE/repo"; rm -rf -- "${BASE:?}/$STAGE_DIR"
    staging_fail "source swap failed; original repo restored"
  fi
  rmdir "$BASE/$STAGE_DIR" 2>/dev/null || true
  log "  rollback anchor: $ROLLBACK_DIR; repo now holds $P_RELEASE_ID"
  verify_tree repo "$P_TREE" "$NEW_EXTRAS" "$BUNDLE" || auto_rollback "active source tree does not match manifest tree $P_TREE (version mismatch)"
  compose_up "$REBUILD" compose-deploy || auto_rollback "docker compose up failed for $REBUILD (startup failure)"
fi

# ============================================================== C) SMOKE
log "=== C) SMOKE ==="
if [ "$FORCE_SMOKE_FAIL" = 1 ]; then staging_overrides forced; fi
if [ "$MODE" = initial ]; then
  smoke "$DEPLOY_SINCE" "$REBUILD" "" || initial_fail "$SMOKE_FAIL"
  observe_flag || initial_fail "$FLAG_FAIL"
  runtime_snapshot || initial_fail "cannot record the runtime images: $RUNTIME_FAIL"
else
  smoke "$DEPLOY_SINCE" "$REBUILD" "$C_RUNTIME_IMAGES" || auto_rollback "$SMOKE_FAIL"
  observe_flag || auto_rollback "$FLAG_FAIL"
  runtime_snapshot || auto_rollback "cannot record the runtime images of the new release: $RUNTIME_FAIL"
fi
NEW_IMAGES="$SNAP_IMAGES"; NEW_REFS="$SNAP_REFS"
protect_images "$NEW_IMAGES" "$P_RELEASE_ID" || { [ "$MODE" = initial ] && initial_fail "$RUNTIME_FAIL"; auto_rollback "$RUNTIME_FAIL"; }
log "=== SMOKE PASSED === runtime: $NEW_IMAGES"

# ============================================================== D) RECORD
if [ "$MODE" = deploy ]; then
  if [ -f "$STATE/previous.env" ]; then
    read_kv "$STATE/previous.env" OLD || true
    if [ -n "${OLD_TREE_DIR:-}" ] && [[ "$OLD_TREE_DIR" =~ $TREE_DIR_RE ]] && [ "$OLD_TREE_DIR" != repo ] && [ -d "$BASE/$OLD_TREE_DIR" ]; then
      mv "$BASE/$OLD_TREE_DIR" "$STATE/retired/$OLD_TREE_DIR-retired-$(stamp)" && log "  retired older rollback tree $OLD_TREE_DIR"
    fi
  fi
  dump_prefix C "$STATE/previous.env" "TREE_DIR=$ROLLBACK_DIR"
fi
dump_prefix P "$STATE/current.env" "TREE_DIR=repo" "SERVICES_REBUILT=$REBUILD" \
  "DEPLOYED_AT=$(now)" "BUNDLE_DIR=$BUNDLE" "LEGACY_EXTRAS=$NEW_EXTRAS" "PREVIOUS_RELEASE_ID=$C_RELEASE_ID" \
  "RUNTIME_IMAGES=$NEW_IMAGES" "RUNTIME_REFS=$NEW_REFS" "STAGING_PROJECT=$PROJECT"
cp "$BUNDLE/manifest.json" "$STATE/manifests/$P_RELEASE_ID.json"
cp "$BUNDLE/manifest.json" "$STATE/current.json.tmp" && mv -f "$STATE/current.json.tmp" "$STATE/current.json"
[ "$MODE" = initial ] || { [ -f "$STATE/manifests/$C_RELEASE_ID.json" ] && cp "$STATE/manifests/$C_RELEASE_ID.json" "$STATE/previous.json"; }
write_markers P "${C_COMMIT:-NONE}" "${ROLLBACK_DIR:-NONE}" "$NEW_IMAGES"
write_record deploy DEPLOYED P "$REBUILD" PASS PASS "" "$C_RELEASE_ID" "$C_RELEASE_ID" "$NEW_IMAGES" NOT_APPLICABLE
staging_record DEPLOYED
log "=== DEPLOYED $P_RELEASE_ID (${P_COMMIT}) on $PROJECT — rollback target ${C_RELEASE_ID}; migrations NOT_RUN ==="
exit 0
