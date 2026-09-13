#!/usr/bin/env bash
# W0-09A shared functions for the Synology release tools. Sourced, never executed.
#
# Configuration (environment; defaults are the production values):
#   BEGWORK_BASE      deployment layout root            (/volume1/docker/begwork)
#   RELEASE_PY_MODE   docker | local                    (docker: verifier runs in VERIFY_IMAGE, --network none)
#   RELEASE_PYTHON    python executable for local mode
#   VERIFY_IMAGE      verifier image                    (python:3.11-slim, never pulled)
#   DOCKER CURL SLEEP COMPOSE_BIN                       (docker, curl, sleep, docker-compose|"docker compose")
#   REQUIRE_BACKUP    1 = precheck needs a gzip-valid backup in $BEGWORK_BASE/backups (1)
#
# Secrets: nothing here prints .env values. Compose output is redacted against .env before
# it reaches the evidence directory; log scans report counts only; flag values are compared,
# never echoed.

SAFE_VALUE_RE='^[A-Za-z0-9._:/@%+=,-]*$'
KEY_RE='^[A-Z][A-Z0-9_]*$'
TREE_DIR_RE='^repo([._][A-Za-z0-9._-]+)?$'
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
  RELEASE_PY_MODE="${RELEASE_PY_MODE:-docker}"
  REQUIRE_BACKUP="${REQUIRE_BACKUP:-1}"
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
  mkdir -p "$STATE/history" "$STATE/manifests" "$STATE/retired" || { log "FATAL: cannot create $STATE"; exit 3; }
  STARTED_AT="$(now)"
  EVID="$STATE/history/$(stamp)-$ACTION-$$"
  mkdir "$EVID" || { log "FATAL: evidence dir $EVID exists"; exit 3; }
  exec > >(tee -a "$EVID/$ACTION.log") 2>&1
  log "W0-09A $ACTION: base=$BASE bundle=$BUNDLE actor=$ACTOR evidence=$EVID"
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

# ---- verifier invocation -----------------------------------------------------------
# PYV_BUNDLE selects which bundle is mounted at /bundle and PYV_HINT which bundle is mounted
# at /hint (docker mode); paths passed to the verifier must go through vpath/vbundle so they
# are valid inside the container.
vbundle() { if [ "$RELEASE_PY_MODE" = local ]; then native "${PYV_BUNDLE:-$BUNDLE}"; else printf '/bundle'; fi; }
vbase()   { if [ "$RELEASE_PY_MODE" = local ]; then native "$BASE"; else printf '/base'; fi; }
vpath() {
  local p="$1"
  case "$p" in
    "$BASE"|"$BASE"/*) if [ "$RELEASE_PY_MODE" = local ]; then native "$p"; else printf '/base%s' "${p#$BASE}"; fi ;;
    *) log "FATAL: verifier path outside base: $p"; return 1 ;;
  esac
}
pyv() {
  if [ "$RELEASE_PY_MODE" = local ]; then
    "$RELEASE_PYTHON" "$(native "${PYV_BUNDLE:-$BUNDLE}/tools/release_verify.py")" "$@"
  else
    local -a hint_mount=()
    [ -n "${PYV_HINT:-}" ] && hint_mount=(-v "$PYV_HINT:/hint:ro")
    "$DOCKER" run --rm --pull never --network none \
      -v "${PYV_BUNDLE:-$BUNDLE}:/bundle:ro" -v "$BASE:/base" ${hint_mount[@]+"${hint_mount[@]}"} \
      "$VERIFY_IMAGE" python3 /bundle/tools/release_verify.py "$@"
  fi
}

# verify_tree DIRNAME TREE EXTRAS_CSV [BUNDLE_OF_THAT_RELEASE]
#   -> 0 when $BASE/DIRNAME is exactly TREE (+ declared extras). The verifier checks exec
#      bits on disk when the filesystem keeps them (chmod probe in the evidence dir); only
#      where it cannot (NTFS, ACL-mapped shares) are they taken from that release's artifact.
verify_tree() {
  local dir="$1" tree="$2" extras="$3" hint="${4:-}" item out rc hint_dir=""
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
  out="$(PYV_HINT="$hint_dir" PYV_BUNDLE="${PYV_BUNDLE:-$BUNDLE}" pyv "${args[@]}" 2>&1 | tr -d '\r')"; rc=$?
  printf '%s\n' "$out" | sed 's/^/    /'
  printf '%s\n' "$out" | grep -q '^RESULT PASS$'
}

redact_into() { # redact_into RAW OUT : evidence copy with .env values replaced
  if pyv redact --env "$(vpath "$BASE/.env")" --in "$(vpath "$1")" --out "$(vpath "$2")" >/dev/null 2>&1; then
    rm -f "$1"
  else
    rm -f "$1"; printf 'output withheld: redaction failed\n' > "$2"
  fi
}

# ---- runtime probes -----------------------------------------------------------------
http_code() { "$CURL" -s -o /dev/null -w '%{http_code}' --max-time 10 "${S_HEALTH_BASE_URL}$1" 2>/dev/null | tr -d '\r' || true; }
cstate()    { "$DOCKER" inspect -f '{{.State.Status}}|{{.RestartCount}}|{{.Created}}' "$1" 2>/dev/null | tr -d '\r' | head -n1; }

container_of() { # service -> container via S_SERVICE_CONTAINERS
  local pair
  IFS=',' read -r -a _pairs <<< "$S_SERVICE_CONTAINERS"
  for pair in "${_pairs[@]}"; do [ "${pair%%:*}" = "$1" ] && { printf '%s' "${pair#*:}"; return 0; }; done
  return 1
}

compose_up() { # compose_up CSV LOGNAME
  local csv="$1" name="$2" rc
  local -a svcs=()
  IFS=',' read -r -a svcs <<< "$csv"
  [ "${#svcs[@]}" -gt 0 ] || return 0
  ( cd "$BASE" && "${COMPOSE_CMD[@]}" up -d --build "${svcs[@]}" ) > "$EVID/$name.raw" 2>&1; rc=$?
  redact_into "$EVID/$name.raw" "$EVID/$name.log"
  log "compose up -d --build ${svcs[*]} -> exit $rc (output: $EVID/$name.log)"
  return $rc
}

# smoke SINCE REBUILT_CSV  (uses S_* smoke config); sets SMOKE_FAIL on failure
smoke() {
  local since="$1" rebuilt="$2" code="000" i tries c st status created svc n r1 r2 p val
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

sanitize() { printf '%s' "$1" | tr -c 'A-Za-z0-9 ._:/@%+=,-' '_' | cut -c1-400; }

# write_record ACTION STATUS PREFIX SERVICES VERIFICATION SMOKE FAILURE PREV_ID ROLLBACK_ID
write_record() {
  local action="$1" status="$2" pfx="$3" services="$4" verification="$5" smk="$6" failure prev="$8" rb="$9"
  failure="$(sanitize "$7")"
  local rid="${pfx}_RELEASE_ID" rsha="${pfx}_RELEASE_SHA256" cm="${pfx}_COMMIT" tr="${pfx}_TREE" en="${pfx}_ENVIRONMENT" di="${pfx}_DEPLOYMENT_ID"
  [ -n "${!rid:-}" ] || { log "record skipped: release not identified"; return 0; }
  local svc_json="" s
  for s in ${services//,/ }; do svc_json="${svc_json:+$svc_json,}\"$s\""; done
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
  "migrations": "NOT_RUN",
  "verification": "$verification",
  "smoke": "$smk",
  "failure": "$failure",
  "evidence_dir": "$EVID"
}
EOF
  log "record: $status ($EVID/record.json)"
}

write_markers() { # write_markers PREFIX PREVIOUS_COMMIT ROLLBACK_DIR
  local pfx="$1" cm="${1}_COMMIT" rid="${1}_RELEASE_ID" rsha="${1}_RELEASE_SHA256"
  printf '%s\n' "${!cm}" > "$BASE/DEPLOYED_COMMIT.tmp" && mv -f "$BASE/DEPLOYED_COMMIT.tmp" "$BASE/DEPLOYED_COMMIT"
  printf 'deployed=%s\nrelease_id=%s\nrelease_sha256=%s\nprevious=%s\nrollback_dir=%s\nstate=%s\nat=%s\n' \
    "${!cm}" "${!rid}" "${!rsha}" "${2:-NONE}" "${3:-NONE}" "$STATE/current.env" "$(now)" > "$BASE/DEPLOYED_VERSION.txt.tmp" \
    && mv -f "$BASE/DEPLOYED_VERSION.txt.tmp" "$BASE/DEPLOYED_VERSION.txt"
}
