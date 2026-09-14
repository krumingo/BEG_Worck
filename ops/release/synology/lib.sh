#!/usr/bin/env bash
# W0-09A shared functions for the Synology release tools. Sourced, never executed.
#
# Configuration (environment; defaults are the production values):
#   BEGWORK_BASE        deployment layout root            (/volume1/docker/begwork)
#   RELEASE_PY_MODE     docker | local                    (docker: verifier runs in VERIFY_IMAGE, --network none)
#   RELEASE_PYTHON      python executable for local mode
#   VERIFY_IMAGE        verifier image reference          (python:3.11-slim; resolved once to its immutable
#                                                          image ID, never pulled; every run uses that ID)
#   VERIFY_IMAGE_ID     optional pin: the resolved ID must equal it
#   RELEASE_IMAGE_REPO  local tag namespace that keeps release runtime images from being pruned (beg-release)
#   DOCKER CURL SLEEP COMPOSE_BIN                         (docker, curl, sleep, docker-compose|"docker compose")
#   REQUIRE_BACKUP      1 = precheck needs a gzip-valid backup in $BEGWORK_BASE/backups (1)
#
# Secrets: nothing here prints .env values. Compose output is redacted against .env before
# it reaches the evidence directory; log scans report counts only; flag values are compared,
# never echoed.
#
# Verifier container mounts: bundle and base READ-ONLY; writable only the evidence directory
# of this operation (/evid) and, during deploy, the staging directory (/stage).

SAFE_VALUE_RE='^[A-Za-z0-9._:/@%+=,-]*$'
KEY_RE='^[A-Z][A-Z0-9_]*$'
TREE_DIR_RE='^repo([._][A-Za-z0-9._-]+)?$'
IMAGE_ID_RE='^sha256:[0-9a-f]{64}$'
IMAGE_REF_RE='^[a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9_.-]+)?(@sha256:[0-9a-f]{64})?$'
LOG_ERROR_RE='Traceback \(most recent call last\)|Application startup failed|ServerSelectionTimeoutError|ModuleNotFoundError|ImportError:|CRITICAL|Error response from daemon'

log()   { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
now()   { date -u +%Y-%m-%dT%H:%M:%SZ; }
stamp() { date -u +%Y%m%dT%H%M%SZ; }

native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }

rel_setup() {
  ACTION="$1"
  BASE="${BEGWORK_BASE:-/volume1/docker/begwork}"
  BASE="${BASE%/}"
  STATE="$BASE/release-state"
  DOCKER="${DOCKER:-docker}"
  CURL="${CURL:-curl}"
  SLEEP="${SLEEP:-sleep}"
  VERIFY_IMAGE="${VERIFY_IMAGE:-python:3.11-slim}"
  RELEASE_IMAGE_REPO="${RELEASE_IMAGE_REPO:-beg-release}"
  RELEASE_PY_MODE="${RELEASE_PY_MODE:-docker}"
  REQUIRE_BACKUP="${REQUIRE_BACKUP:-1}"
  STAGE_HOST=""
  if [ -n "${COMPOSE_BIN:-}" ]; then read -r -a COMPOSE_CMD <<< "$COMPOSE_BIN"
  elif command -v docker-compose >/dev/null 2>&1; then COMPOSE_CMD=(docker-compose)
  else COMPOSE_CMD=(docker compose); fi
  ACTOR="$(printf '%s' "${SUDO_USER:-${USER:-unknown}}" | tr -c 'A-Za-z0-9._-' '-' | cut -c1-64)"
  [ -n "$ACTOR" ] || ACTOR=unknown
  TOOLS="$(cd "$SCRIPT_DIR/.." && pwd)"
  BUNDLE="$(cd "$TOOLS/.." && pwd)"
  if [ ! -d "$BASE" ] || [ ! -f "$BASE/docker-compose.yml" ]; then
    log "FATAL: $BASE is not a deployment layout root (docker-compose.yml missing)"; exit 3
  fi
  [[ "$RELEASE_IMAGE_REPO" =~ ^[a-z0-9][a-z0-9._/-]*$ ]] || { log "FATAL: invalid RELEASE_IMAGE_REPO"; exit 3; }
  mkdir -p "$STATE/history" "$STATE/manifests" "$STATE/retired" || { log "FATAL: cannot create $STATE"; exit 3; }
  STARTED_AT="$(now)"
  EVID="$STATE/history/$(stamp)-$ACTION-$$"
  mkdir "$EVID" || { log "FATAL: evidence dir $EVID exists"; exit 3; }
  exec > >(tee -a "$EVID/$ACTION.log") 2>&1
  log "W0-09A $ACTION: base=$BASE bundle=$BUNDLE actor=$ACTOR evidence=$EVID"
  if [ "$RELEASE_PY_MODE" = local ]; then
    VERIFIER_IMAGE="local-python-$("$RELEASE_PYTHON" -c 'import platform; print(platform.python_version())' 2>/dev/null | tr -d '\r')"
  else
    VERIFIER_IMAGE="$(image_id "$VERIFY_IMAGE")"
    [[ "$VERIFIER_IMAGE" =~ $IMAGE_ID_RE ]] || { log "FATAL: verifier image $VERIFY_IMAGE is not present locally (it is never pulled)"; exit 3; }
    if [ -n "${VERIFY_IMAGE_ID:-}" ] && [ "$VERIFIER_IMAGE" != "$VERIFY_IMAGE_ID" ]; then
      log "FATAL: verifier image $VERIFY_IMAGE resolves to $VERIFIER_IMAGE, pinned VERIFY_IMAGE_ID is $VERIFY_IMAGE_ID"; exit 3
    fi
  fi
  log "verifier: $VERIFIER_IMAGE"
}

lock_acquire() {
  if mkdir "$STATE/lock" 2>/dev/null; then
    printf 'pid=%s\naction=%s\nat=%s\n' "$$" "$ACTION" "$(now)" > "$STATE/lock/owner"; LOCKED=1
  else
    log "FATAL: another release operation holds $STATE/lock"; exit 3
  fi
}
lock_release() { [ "${LOCKED:-0}" = 1 ] && rm -rf "$STATE/lock"; LOCKED=0; }

# Strict KEY=VALUE reader (never sourced): read_kv FILE PREFIX
read_kv() {
  local file="$1" prefix="$2" line key val
  [ -f "$file" ] || { log "missing state/plan file $file"; return 1; }
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    [ -z "$line" ] && continue
    key="${line%%=*}"; val="${line#*=}"
    if ! [[ "$key" =~ $KEY_RE ]]; then log "invalid key in $file"; return 1; fi
    if ! [[ "$val" =~ $SAFE_VALUE_RE ]]; then log "unsafe value for $key in $file"; return 1; fi
    printf -v "${prefix}_${key}" '%s' "$val"
  done < "$file"
}

# copy_prefix SRC DST : copies every SRC_* variable to DST_*
copy_prefix() {
  local v
  for v in $(compgen -v "${1}_"); do printf -v "${2}_${v#${1}_}" '%s' "${!v}"; done
}

# dump_prefix PREFIX FILE [KEY=VALUE ...] : atomic write of PREFIX_* (+ overrides)
dump_prefix() {
  local prefix="$1" file="$2" v key val tmp="$2.tmp.$$"; shift 2
  declare -A out=()
  for v in $(compgen -v "${prefix}_"); do out["${v#${prefix}_}"]="${!v}"; done
  for kv in "$@"; do out["${kv%%=*}"]="${kv#*=}"; done
  : > "$tmp"
  for key in $(printf '%s\n' "${!out[@]}" | LC_ALL=C sort); do
    val="${out[$key]}"
    if ! [[ "$key" =~ $KEY_RE && "$val" =~ $SAFE_VALUE_RE ]]; then log "refusing unsafe state value for $key"; rm -f "$tmp"; return 1; fi
    printf '%s=%s\n' "$key" "$val" >> "$tmp"
  done
  mv -f "$tmp" "$file"
}

# csv_get "k1=v1,k2=v2" KEY -> value (exit 1 when absent)
csv_get() {
  local item
  local -a items=()
  IFS=',' read -r -a items <<< "$1"
  for item in ${items[@]+"${items[@]}"}; do
    [ "${item%%=*}" = "$2" ] && { printf '%s' "${item#*=}"; return 0; }
  done
  return 1
}

# ---- verifier invocation -----------------------------------------------------------
# PYV_BUNDLE selects which bundle is mounted at /bundle and PYV_HINT which bundle is mounted
# at /hint (docker mode). Host paths given to the verifier must go through vpath/vbundle.
vbundle() { if [ "$RELEASE_PY_MODE" = local ]; then native "${PYV_BUNDLE:-$BUNDLE}"; else printf '/bundle'; fi; }
vbase()   { if [ "$RELEASE_PY_MODE" = local ]; then native "$BASE"; else printf '/base'; fi; }
vpath() {
  local p="$1"
  if [ "$RELEASE_PY_MODE" = local ]; then
    case "$p" in "$BASE"|"$BASE"/*) native "$p"; return 0 ;; esac
    log "FATAL: verifier path outside base: $p"; return 1
  fi
  case "$p" in
    "$EVID"|"$EVID"/*) printf '/evid%s' "${p#"$EVID"}"; return 0 ;;
  esac
  if [ -n "$STAGE_HOST" ]; then
    case "$p" in "$STAGE_HOST"|"$STAGE_HOST"/*) printf '/stage%s' "${p#"$STAGE_HOST"}"; return 0 ;; esac
  fi
  case "$p" in
    "$BASE"|"$BASE"/*) printf '/base%s' "${p#"$BASE"}" ;;
    *) log "FATAL: verifier path outside base: $p"; return 1 ;;
  esac
}
pyv() {
  if [ "$RELEASE_PY_MODE" = local ]; then
    "$RELEASE_PYTHON" "$(native "${PYV_BUNDLE:-$BUNDLE}/tools/release_verify.py")" "$@"
  else
    local -a mounts=(-v "${PYV_BUNDLE:-$BUNDLE}:/bundle:ro" -v "$BASE:/base:ro" -v "$EVID:/evid")
    [ -n "${PYV_HINT:-}" ] && mounts+=(-v "$PYV_HINT:/hint:ro")
    [ -n "$STAGE_HOST" ] && mounts+=(-v "$STAGE_HOST:/stage")
    "$DOCKER" run --rm --pull never --network none --read-only --security-opt no-new-privileges \
      -e PYTHONDONTWRITEBYTECODE=1 "${mounts[@]}" \
      "$VERIFIER_IMAGE" python3 /bundle/tools/release_verify.py "$@"
  fi
}

# verify_tree DIRNAME TREE EXTRAS_CSV [BUNDLE_OF_THAT_RELEASE]
#   -> 0 when $BASE/DIRNAME is exactly TREE (+ declared extras). The verifier checks exec
#      bits on disk when the filesystem keeps them (chmod probe in the evidence dir); only
#      where it cannot (NTFS, ACL-mapped shares) are they taken from that release's artifact.
verify_tree() {
  local dir="$1" tree="$2" extras="$3" hint="${4:-}" item out hint_dir=""
  local -a args=(tree --dir "$(vpath "$BASE/$dir")" --tree "$tree" --probe-dir "$(vpath "$EVID")")
  if [ -n "$hint" ] && [ -f "$hint/artifact.tar" ]; then
    if [ "$RELEASE_PY_MODE" = local ]; then
      args+=(--mode-hint-tar "$(native "$hint/artifact.tar")")
    else
      args+=(--mode-hint-tar /hint/artifact.tar); hint_dir="$hint"
    fi
  fi
  if [ -n "$extras" ] && [ "$extras" != NONE ]; then
    IFS=',' read -r -a _ex <<< "$extras"
    for item in "${_ex[@]}"; do args+=(--allow-extra "$item"); done
  fi
  out="$(PYV_HINT="$hint_dir" PYV_BUNDLE="${PYV_BUNDLE:-$BUNDLE}" pyv "${args[@]}" 2>&1 | tr -d '\r')"
  printf '%s\n' "$out" | sed 's/^/    /'
  printf '%s\n' "$out" | grep -q '^RESULT PASS$'
}

redact_into() { # redact_into RAW OUT : evidence copy with .env values replaced (both under $EVID)
  if pyv redact --env "$(vpath "$BASE/.env")" --in "$(vpath "$1")" --out "$(vpath "$2")" >/dev/null 2>&1; then
    rm -f "$1"
  else
    rm -f "$1"; printf 'output withheld: redaction failed\n' > "$2"
  fi
}

# ---- runtime probes -----------------------------------------------------------------
http_code() { "$CURL" -s -o /dev/null -w '%{http_code}' --max-time 10 "${S_HEALTH_BASE_URL}$1" 2>/dev/null | tr -d '\r' || true; }
cstate()    { "$DOCKER" inspect -f '{{.State.Status}}|{{.RestartCount}}|{{.Created}}' "$1" 2>/dev/null | tr -d '\r' | head -n1; }
cimage()    { "$DOCKER" inspect -f '{{.Image}}' "$1" 2>/dev/null | tr -d '\r' | head -n1; }
cimageref() { "$DOCKER" inspect -f '{{.Config.Image}}' "$1" 2>/dev/null | tr -d '\r' | head -n1; }
image_id()  { "$DOCKER" image inspect -f '{{.Id}}' "$1" 2>/dev/null | tr -d '\r' | head -n1; }

container_of() { # service -> container via S_SERVICE_CONTAINERS
  local pair
  IFS=',' read -r -a _pairs <<< "$S_SERVICE_CONTAINERS"
  for pair in "${_pairs[@]}"; do [ "${pair%%:*}" = "$1" ] && { printf '%s' "${pair#*:}"; return 0; }; done
  return 1
}

# ---- runtime images (what actually runs) ---------------------------------------------
# runtime_snapshot -> SNAP_IMAGES "svc=sha256:..,..." and SNAP_REFS "svc=<compose image ref>,..."
# for every service of the layout, read from the containers (immutable image IDs).
runtime_snapshot() {
  local pair svc c id ref
  SNAP_IMAGES=""; SNAP_REFS=""; RUNTIME_FAIL=""
  IFS=',' read -r -a _pairs <<< "$S_SERVICE_CONTAINERS"
  for pair in "${_pairs[@]}"; do
    svc="${pair%%:*}"; c="${pair#*:}"
    id="$(cimage "$c")"; ref="$(cimageref "$c")"
    if ! [[ "$id" =~ $IMAGE_ID_RE && "$ref" =~ $IMAGE_REF_RE ]]; then
      RUNTIME_FAIL="cannot read the runtime image of container $c"; return 1
    fi
    SNAP_IMAGES="${SNAP_IMAGES:+$SNAP_IMAGES,}$svc=$id"
    SNAP_REFS="${SNAP_REFS:+$SNAP_REFS,}$svc=$ref"
  done
}

# protect_images IMAGES_CSV RELEASE_ID : tag every image as $RELEASE_IMAGE_REPO/<svc>:<release>
# so a dangling-image prune cannot remove the runtime a rollback may need.
protect_images() {
  local item svc id
  local -a items=()
  IFS=',' read -r -a items <<< "$1"
  for item in ${items[@]+"${items[@]}"}; do
    svc="${item%%=*}"; id="${item#*=}"
    "$DOCKER" tag "$id" "$RELEASE_IMAGE_REPO/$svc:$2" >/dev/null 2>&1 \
      || { RUNTIME_FAIL="could not tag $id as $RELEASE_IMAGE_REPO/$svc:$2"; return 1; }
  done
  log "  runtime images of $2 protected as $RELEASE_IMAGE_REPO/<service>:$2"
}

compose_run() { # compose_run LOGNAME ARGS... (output redacted into the evidence dir)
  local name="$1" rc; shift
  ( cd "$BASE" && "${COMPOSE_CMD[@]}" "$@" ) > "$EVID/$name.raw" 2>&1; rc=$?
  redact_into "$EVID/$name.raw" "$EVID/$name.log"
  log "compose $* -> exit $rc (output: $EVID/$name.log)"
  return $rc
}

compose_up() { # compose_up CSV LOGNAME : build and recreate exactly these services (never their deps)
  local -a svcs=()
  IFS=',' read -r -a svcs <<< "$1"
  [ "${#svcs[@]}" -gt 0 ] || return 0
  compose_run "$2" up -d --no-deps --build "${svcs[@]}"
}

# restore_runtime PREFIX SERVICES_CSV LOGNAME ALLOW_SOURCE_REBUILD
#   Returns SERVICES to the runtime images recorded in PREFIX_RUNTIME_IMAGES:
#   * recorded image present -> re-tag it as the compose image ref, recreate WITHOUT building,
#     then prove the container runs exactly that image ID            (RUNTIME_ROLLBACK=EXACT_IMAGE)
#   * recorded image missing  -> rebuild from the already verified source tree, only when
#     ALLOW_SOURCE_REBUILD=1; this is NOT runtime-exact             (RUNTIME_ROLLBACK=SOURCE_REBUILD)
restore_runtime() {
  local pfx="$1" services="$2" logname="$3" allow="$4" svc id ref got c
  local iv="${1}_RUNTIME_IMAGES" rv="${1}_RUNTIME_REFS"
  local -a exact=() rebuild=()
  RUNTIME_ROLLBACK="EXACT_IMAGE"; RUNTIME_FAIL=""
  for svc in ${services//,/ }; do
    id="$(csv_get "${!iv:-}" "$svc" || true)"; ref="$(csv_get "${!rv:-}" "$svc" || true)"
    if [[ "$id" =~ $IMAGE_ID_RE ]] && [[ "$ref" =~ $IMAGE_REF_RE ]] && [ "$(image_id "$id")" = "$id" ]; then
      "$DOCKER" tag "$id" "$ref" >/dev/null 2>&1 || { RUNTIME_FAIL="could not re-tag $id as $ref"; return 1; }
      log "  $svc: recorded runtime image $id re-tagged as $ref"
      exact+=("$svc")
    else
      rebuild+=("$svc")
    fi
  done
  if [ "${#rebuild[@]}" -gt 0 ]; then
    if [ "$allow" != 1 ]; then
      RUNTIME_FAIL="no recorded runtime image available locally for: ${rebuild[*]} (exact runtime rollback impossible)"; return 1
    fi
    RUNTIME_ROLLBACK="SOURCE_REBUILD"
    log "  NOT runtime-exact: rebuilding ${rebuild[*]} from the verified source tree (recorded image unavailable)"
  fi
  if [ "${#exact[@]}" -gt 0 ]; then
    compose_run "$logname-exact" up -d --no-deps --no-build --force-recreate "${exact[@]}" \
      || { RUNTIME_FAIL="docker compose up --no-build failed"; return 1; }
  fi
  if [ "${#rebuild[@]}" -gt 0 ]; then
    compose_run "$logname-rebuild" up -d --no-deps --build "${rebuild[@]}" \
      || { RUNTIME_FAIL="docker compose up --build failed"; return 1; }
  fi
  for svc in ${exact[@]+"${exact[@]}"}; do
    c="$(container_of "$svc")"; id="$(csv_get "${!iv}" "$svc")"; got="$(cimage "$c")"
    [ "$got" = "$id" ] || { RUNTIME_FAIL="container $c runs ${got:-nothing}, recorded runtime image is $id"; return 1; }
    log "  $svc: container $c runs the recorded runtime image $id"
  done
}

# smoke SINCE REBUILT_CSV [UNCHANGED_IMAGES_CSV]  (uses S_* smoke config); sets SMOKE_FAIL
#   services outside REBUILT_CSV must still run the image recorded in UNCHANGED_IMAGES_CSV
smoke() {
  local since="$1" rebuilt="$2" unchanged="${3:-}" code="000" i tries c st status created svc n r1 r2 p val want
  SMOKE_FAIL=""
  tries=$(( S_HEALTH_TIMEOUT_SEC / 5 ))
  for (( i = 0; i <= tries; i++ )); do
    code="$(http_code "$S_HEALTH_PATH")"
    [ "$code" = 200 ] && break
    for svc in ${rebuilt//,/ }; do
      c="$(container_of "$svc")"; st="$(cstate "$c")"; status="${st%%|*}"
      if [ -n "$st" ] && [ "$status" != running ] && [ "$status" != created ] && [ "$status" != restarting ]; then
        SMOKE_FAIL="container $c is $status (backend/frontend did not start)"; return 1
      fi
    done
    $SLEEP 5
  done
  [ "$code" = 200 ] || { SMOKE_FAIL="health $S_HEALTH_PATH returned $code within ${S_HEALTH_TIMEOUT_SEC}s"; return 1; }
  log "  health $S_HEALTH_PATH -> 200"

  for c in ${S_CONTAINERS//,/ }; do
    st="$(cstate "$c")"; status="${st%%|*}"
    [ "$status" = running ] || { SMOKE_FAIL="container $c is ${status:-missing}"; return 1; }
  done
  for svc in ${rebuilt//,/ }; do
    c="$(container_of "$svc")" || { SMOKE_FAIL="unknown service $svc"; return 1; }
    st="$(cstate "$c")"; created="${st##*|}"
    if [[ "${created:0:19}" < "${since:0:19}" ]]; then
      SMOKE_FAIL="container $c was not recreated by this release (created ${created:0:19} < ${since:0:19}): version mismatch"
      return 1
    fi
  done
  if [ -n "$unchanged" ]; then
    IFS=',' read -r -a _pairs <<< "$S_SERVICE_CONTAINERS"
    for p in "${_pairs[@]}"; do
      svc="${p%%:*}"; c="${p#*:}"
      case ",$rebuilt," in *",$svc,"*) continue ;; esac
      want="$(csv_get "$unchanged" "$svc" || true)"
      [ -z "$want" ] || [ "$(cimage "$c")" = "$want" ] \
        || { SMOKE_FAIL="container $c no longer runs its recorded image $want: runtime version mismatch"; return 1; }
    done
  fi
  log "  containers running: $S_CONTAINERS"

  declare -A before=()
  for c in ${S_CONTAINERS//,/ }; do st="$(cstate "$c")"; r1="${st#*|}"; before[$c]="${r1%%|*}"; done
  $SLEEP "$S_RESTART_SAMPLE_SEC"
  for c in ${S_CONTAINERS//,/ }; do
    st="$(cstate "$c")"; status="${st%%|*}"; r2="${st#*|}"; r2="${r2%%|*}"
    if [ "$status" != running ] || [ "${r2:-0}" -gt "${before[$c]:-0}" ]; then
      SMOKE_FAIL="restart loop: $c status=${status:-missing} restarts ${before[$c]:-?} -> ${r2:-?}"; return 1
    fi
  done
  log "  restart count stable over ${S_RESTART_SAMPLE_SEC}s"

  for p in ${S_HTTP_PATHS//,/ }; do
    code="$(http_code "$p")"
    case "$code" in 2??|3??) log "  GET $p -> $code" ;;
      *) SMOKE_FAIL="GET $p returned $code"; return 1 ;;
    esac
  done

  n="$("$DOCKER" logs --since "$since" "$S_LOG_CONTAINER" 2>&1 | tr -d '\r' | grep -cE "$LOG_ERROR_RE" || true)"
  [ "${n:-0}" = 0 ] || { SMOKE_FAIL="startup/config errors in $S_LOG_CONTAINER log since $since: $n matching line(s), content withheld"; return 1; }
  log "  $S_LOG_CONTAINER log since $since: no startup/config errors"

  for p in ${S_FLAG_KEYS//,/ }; do
    local expect_var="S_FLAG_EXPECT_$p"
    # no pipeline here: printenv's own exit status must decide "unset" (a pipe would mask it)
    if val="$("$DOCKER" exec "$S_LOG_CONTAINER" printenv "$p" 2>/dev/null)"; then
      val="${val//$'\r'/}"
      [ "$val" = "${!expect_var}" ] || { SMOKE_FAIL="flag $p in $S_LOG_CONTAINER differs from the release expectation (value withheld)"; return 1; }
      log "  flag $p set and equal to expectation"
    else
      log "  flag $p unset in container -> app default (release expects ${!expect_var})"
    fi
  done
  unset val
  return 0
}

backup_check() {
  [ "$REQUIRE_BACKUP" = 1 ] || { log "  backup check skipped (REQUIRE_BACKUP=0)"; return 0; }
  local latest
  latest="$(ls -1t "$BASE"/backups/*.archive.gz 2>/dev/null | head -n1)"
  [ -n "$latest" ] || { PRE_FAIL="no backup archive in $BASE/backups"; return 1; }
  gzip -t "$latest" 2>/dev/null || { PRE_FAIL="latest backup $(basename "$latest") fails gzip -t"; return 1; }
  log "  backup OK: $(basename "$latest")"
}

record_base_images() { # evidence only: immutable IDs of the base images present before a build
  local img id
  : > "$EVID/base-images.txt"
  for img in ${S_BASE_IMAGES//,/ }; do
    id="$(image_id "$img")"
    printf '%s %s\n' "$img" "${id:-absent}" >> "$EVID/base-images.txt"
  done
}

sanitize() { printf '%s' "$1" | tr -c 'A-Za-z0-9 ._:/@%+=,-' '_' | cut -c1-400; }

# write_record ACTION STATUS PREFIX SERVICES VERIFICATION SMOKE FAILURE PREV_ID ROLLBACK_ID RUNTIME_IMAGES RUNTIME_ROLLBACK
write_record() {
  local action="$1" status="$2" pfx="$3" services="$4" verification="$5" smk="$6" failure prev="$8" rb="$9"
  local images="${10:-}" runtime_rollback="${11:-NOT_APPLICABLE}"
  failure="$(sanitize "$7")"
  local rid="${pfx}_RELEASE_ID" rsha="${pfx}_RELEASE_SHA256" cm="${pfx}_COMMIT" tr="${pfx}_TREE" en="${pfx}_ENVIRONMENT" di="${pfx}_DEPLOYMENT_ID"
  [ -n "${!rid:-}" ] || { log "record skipped: release not identified"; return 0; }
  local svc_json="" img_json="" s item
  for s in ${services//,/ }; do svc_json="${svc_json:+$svc_json,}\"$s\""; done
  IFS=',' read -r -a _imgs <<< "$images"
  for item in ${_imgs[@]+"${_imgs[@]}"}; do img_json="${img_json:+$img_json, }\"${item%%=*}\": \"${item#*=}\""; done
  cat > "$EVID/record.json" <<EOF
{
  "schema": "beg.deployment-record/v1",
  "action": "$action",
  "status": "$status",
  "release_id": "${!rid}",
  "release_sha256": "${!rsha}",
  "commit": "${!cm}",
  "tree": "${!tr}",
  "environment": "${!en}",
  "deployment_id": "${!di}",
  "started_at": "$STARTED_AT",
  "finished_at": "$(now)",
  "actor": "$ACTOR",
  "previous_release_id": "${prev:-NONE}",
  "rollback_target_release_id": "${rb:-NONE}",
  "services_rebuilt": [${svc_json}],
  "runtime_images": {${img_json}},
  "runtime_rollback": "$runtime_rollback",
  "verifier_image": "$VERIFIER_IMAGE",
  "migrations": "NOT_RUN",
  "verification": "$verification",
  "smoke": "$smk",
  "failure": "$failure",
  "evidence_dir": "$EVID"
}
EOF
  log "record: $status ($EVID/record.json)"
}

write_markers() { # write_markers PREFIX PREVIOUS_COMMIT ROLLBACK_DIR RUNTIME_IMAGES
  local pfx="$1" cm="${1}_COMMIT" rid="${1}_RELEASE_ID" rsha="${1}_RELEASE_SHA256"
  printf '%s\n' "${!cm}" > "$BASE/DEPLOYED_COMMIT.tmp" && mv -f "$BASE/DEPLOYED_COMMIT.tmp" "$BASE/DEPLOYED_COMMIT"
  printf 'deployed=%s\nrelease_id=%s\nrelease_sha256=%s\nprevious=%s\nrollback_dir=%s\nruntime_images=%s\nstate=%s\nat=%s\n' \
    "${!cm}" "${!rid}" "${!rsha}" "${2:-NONE}" "${3:-NONE}" "${4:-NONE}" "$STATE/current.env" "$(now)" > "$BASE/DEPLOYED_VERSION.txt.tmp" \
    && mv -f "$BASE/DEPLOYED_VERSION.txt.tmp" "$BASE/DEPLOYED_VERSION.txt"
}
