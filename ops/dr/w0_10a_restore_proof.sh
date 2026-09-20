#!/usr/bin/env bash
# W0-10A — isolated restore proof.
#
#   sudo bash /volume1/docker/w010a/w0_10a_restore_proof.sh [archive]
#
# Restores a REAL nightly backup archive into a DISPOSABLE MongoDB that lives on an
# `--internal` Docker network, verifies the restored data, then removes everything and
# proves production is byte-for-byte unchanged.
#
# Guarantees, all fail-closed:
#   * the source archive is mounted READ-ONLY and its sha256 is compared before and after;
#   * the temporary Mongo has NO published port, NO production credentials and sits on an
#     `--internal` network, so it cannot reach Atlas even if something tried;
#   * production `.env` is never read, only hashed;
#   * container/network/volume names are `w010a-*`; production names are refused outright;
#   * an M.2 temperature gate aborts before and during the run (the NAS powers itself off at
#     70 C — see docs/ops/INCIDENT_2026-09-13_NAS_THERMAL.md);
#   * cleanup is verified, and a production snapshot taken before and after must match.
#
# Exit codes: 0 PASS · 2 preflight/guard refusal · 3 restore or verification failure ·
#             4 cleanup failure · 5 production changed
set -u
umask 022

PROD="${PROD:-/volume1/docker/begwork}"
BACKUP_DIR="${BACKUP_DIR:-$PROD/backups}"
OUT_ROOT="${OUT_ROOT:-/volume1/docker/w010a-restore-proof}"
MONGO_IMAGE="${MONGO_IMAGE:-mongo:7}"
TEMP_ABORT="${TEMP_ABORT:-62}"        # C; refuse to start / abort mid-run at or above this
READY_TIMEOUT="${READY_TIMEOUT:-90}"  # s to wait for mongod
DOCKER="${DOCKER:-docker}"
M2_GLOB="${M2_GLOB:-/run/synostorage/disks/nvme*/temperature}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERIFY_JS="${VERIFY_JS:-$HERE/verify_restore.js}"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NET="w010a-net-$STAMP"
VOL="w010a-vol-$STAMP"
MONGO_C="w010a-mongo-$STAMP"
OUT="$OUT_ROOT/out-$STAMP"
SAMPLER_PID=""
CREATED_NET=0 CREATED_VOL=0 CREATED_C=0

mkdir -p "$OUT" 2>/dev/null || { echo "cannot create $OUT" >&2; exit 2; }

log()  { printf '[%s] %s\n' "$(date -u +%H:%M:%SZ)" "$*" | tee -a "$OUT/run.log"; }
step() { printf '\n[%s] === %s ===\n' "$(date -u +%H:%M:%SZ)" "$*" | tee -a "$OUT/run.log"; }
say()  { printf '%s=%s\n' "$1" "$2" >> "$OUT/result.env"; }

VERDICT=BLOCKED
fail() { # fail CODE MESSAGE
  local code="$1"; shift
  log "FAIL($code): $*"
  say FAIL_REASON "$*"
  cleanup
  prod_check || log "production DIFFERS before vs after — see prod-diff.txt"
  finish "$code"
}
finish() {
  local code="$1"
  [ "$code" = 0 ] && VERDICT=PASS
  say VERDICT "$VERDICT"
  summary
  log "verdict=$VERDICT exit=$code evidence=$OUT"
  exit "$code"
}

# ---------------------------------------------------------------- M.2 temperature gate
m2_temps() { # prints "nvme0n1=54 nvme1n1=57"
  local f d t out=""
  for f in $M2_GLOB; do
    [ -f "$f" ] || continue
    d="$(basename "$(dirname "$f")")"; t="$(tr -dc '0-9' < "$f")"
    [ -n "$t" ] && out="$out$d=$t "
  done
  printf '%s' "${out% }"
}
m2_max() {
  local max=0 t
  for t in $(m2_temps | tr ' ' '\n' | sed 's/.*=//'); do [ "$t" -gt "$max" ] && max="$t"; done
  printf '%s' "$max"
}
temp_gate() { # temp_gate WHEN -> non-zero when too hot
  local when="$1" temps max
  temps="$(m2_temps)"; max="$(m2_max)"
  printf '%s\t%s\tmax=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${temps:-none}" "$max" >> "$OUT/m2-temps.tsv"
  [ -z "$temps" ] && { log "WARN: no M.2 temperature sensors found ($when)"; return 0; }
  if [ "$max" -ge "$TEMP_ABORT" ]; then
    log "M.2 temperature gate tripped $when: max=${max}C >= ${TEMP_ABORT}C ($temps)"
    return 1
  fi
  log "M.2 temperatures $when: $temps (max ${max}C, abort at ${TEMP_ABORT}C)"
  return 0
}
start_sampler() {
  ( while :; do temp_gate during || touch "$OUT/.too-hot"; sleep 5; done ) >/dev/null 2>&1 &
  SAMPLER_PID=$!
}
stop_sampler() { [ -n "$SAMPLER_PID" ] && kill "$SAMPLER_PID" 2>/dev/null; SAMPLER_PID=""; }
too_hot() { [ -f "$OUT/.too-hot" ]; }

# ---------------------------------------------------------------- production snapshot
snapshot() { # snapshot FILE — everything that must be identical before and after
  {
    echo "# production snapshot (content only — no timestamp, this file is diffed)"
    for c in begwork-backend begwork-frontend kpo-photo-cleaner beg-raboti; do
      printf 'container %s %s\n' "$c" \
        "$($DOCKER inspect -f '{{.Id}} {{.State.Status}} restarts={{.RestartCount}} started={{.State.StartedAt}}' "$c" 2>&1)"
    done
    # .env is hashed, never read
    printf 'env_sha256 %s\n' "$(sha256sum "$PROD/.env" 2>/dev/null | awk '{print $1}')"
    printf 'deployed_commit %s\n' "$(cat "$PROD/DEPLOYED_COMMIT" 2>/dev/null)"
    printf 'release_state_present %s\n' "$([ -d "$PROD/release-state" ] && echo yes || echo no)"
    printf 'repo_files %s\n' "$(find "$PROD/repo" -type f 2>/dev/null | wc -l)"
    echo "# backups"
    ls -la --time-style=full-iso "$BACKUP_DIR" 2>/dev/null | grep 'archive.gz' | awk '{print $5, $6, $7, $9}'
    echo "# volumes/networks named w010a"
    $DOCKER volume ls --format '{{.Name}}' 2>/dev/null | grep '^w010a' || true
    $DOCKER network ls --format '{{.Name}}' 2>/dev/null | grep '^w010a' || true
  } > "$FILE_OUT" 2>&1
}
take_snapshot() { FILE_OUT="$1"; snapshot; }

# ---------------------------------------------------------------- cleanup (idempotent, verified)
cleanup() {
  stop_sampler
  step "cleanup"
  [ "$CREATED_C" = 1 ] && { $DOCKER rm -f "$MONGO_C" >>"$OUT/cleanup.log" 2>&1; }
  $DOCKER ps -a --format '{{.Names}}' 2>/dev/null | grep -E '^w010a-' | while read -r c; do
    [ -n "$c" ] && $DOCKER rm -f "$c" >>"$OUT/cleanup.log" 2>&1
  done
  [ "$CREATED_VOL" = 1 ] && { $DOCKER volume rm -f "$VOL" >>"$OUT/cleanup.log" 2>&1; }
  [ "$CREATED_NET" = 1 ] && { $DOCKER network rm "$NET" >>"$OUT/cleanup.log" 2>&1; }
  local leftover=0
  $DOCKER ps -a --format '{{.Names}}' 2>/dev/null | grep -qE '^w010a-' && leftover=1
  $DOCKER volume ls --format '{{.Name}}' 2>/dev/null | grep -qE '^w010a-' && leftover=1
  $DOCKER network ls --format '{{.Name}}' 2>/dev/null | grep -qE '^w010a-' && leftover=1
  if [ "$leftover" = 1 ]; then
    R_CLEANUP=FAIL; say CLEANUP FAIL
    log "cleanup INCOMPLETE — w010a-* objects remain"
    return 1
  fi
  R_CLEANUP=PASS; say CLEANUP PASS
  log "cleanup verified: no w010a-* container, volume or network remains"
  return 0
}
prod_check() { # sets R_PRODCHANGED; non-zero when production differs
  if [ ! -f "$OUT/prod-before.txt" ]; then R_PRODCHANGED=UNKNOWN; say PRODUCTION_CHANGED UNKNOWN; return 0; fi
  if [ -n "${ARCHIVE:-}" ] && [ -f "${ARCHIVE:-}" ] && [ -n "${ARCHIVE_SHA:-}" ]; then
    if [ "$(sha256sum "$ARCHIVE" | awk '{print $1}')" != "$ARCHIVE_SHA" ]; then
      R_PRODCHANGED=YES; say PRODUCTION_CHANGED YES
      log "the source archive checksum changed during the run"
      return 1
    fi
  fi
  take_snapshot "$OUT/prod-after.txt"
  if diff -u "$OUT/prod-before.txt" "$OUT/prod-after.txt" > "$OUT/prod-diff.txt" 2>&1; then
    R_PRODCHANGED=NO; say PRODUCTION_CHANGED NO; return 0
  fi
  R_PRODCHANGED=YES; say PRODUCTION_CHANGED YES; return 1
}

trap 'stop_sampler' EXIT

summary() {
  {
    echo "W0-10A: $VERDICT"
    echo "BACKUP: ${ARCHIVE_NAME:-?} + sha256 ${ARCHIVE_SHA:-?}"
    echo "RESTORE_TARGET: isolated container $MONGO_C on internal network $NET (image ${IMAGE_ID:-?})"
    echo "RESTORE: ${R_RESTORE:-NOT_RUN}"
    echo "VERIFICATION: ${R_VERIFY:-NOT_RUN}"
    echo "TENANT_CHECK: ${R_TENANT:-NOT_RUN}"
    echo "CLEANUP: ${R_CLEANUP:-NOT_RUN}"
    echo "PRODUCTION_CHANGED: ${R_PRODCHANGED:-UNKNOWN}"
    echo "M2_TEMP_MAX_DURING_RUN: $(awk -F'max=' 'NF>1{if($2+0>m)m=$2+0}END{print m+0}' "$OUT/m2-temps.tsv" 2>/dev/null)C"
    echo "EVIDENCE: $OUT"
  } > "$OUT/SUMMARY.txt"
  cat "$OUT/SUMMARY.txt"
}

# ================================================================ 1. preflight
step "preflight"
say STARTED_AT "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

case "$MONGO_C$NET$VOL" in
  *begwork*|*kpo-photo*|*beg-raboti*) fail 2 "refusing: a production name leaked into the isolated object names" ;;
esac
for n in "$MONGO_C" "$NET" "$VOL"; do
  case "$n" in w010a-*) ;; *) fail 2 "refusing: object name '$n' is not w010a-prefixed" ;; esac
done

command -v "$DOCKER" >/dev/null 2>&1 || fail 2 "docker not found"
$DOCKER image inspect "$MONGO_IMAGE" >/dev/null 2>&1 \
  || fail 2 "image $MONGO_IMAGE is not present locally; pull it first (the run stays offline)"
IMAGE_ID="$($DOCKER image inspect -f '{{.Id}}' "$MONGO_IMAGE" 2>/dev/null)"
say MONGO_IMAGE "$MONGO_IMAGE"
say MONGO_IMAGE_ID "$IMAGE_ID"
[ -r "$VERIFY_JS" ] || fail 2 "verification script not readable: $VERIFY_JS"

if [ "$#" -ge 1 ] && [ -n "${1:-}" ]; then
  ARCHIVE="$1"
  case "$ARCHIVE" in /*) ;; *) ARCHIVE="$BACKUP_DIR/$ARCHIVE" ;; esac
else
  ARCHIVE="$(ls -1 "$BACKUP_DIR"/*.archive.gz 2>/dev/null | LC_ALL=C sort | tail -n1)"
fi
[ -n "$ARCHIVE" ] && [ -f "$ARCHIVE" ] || fail 2 "no backup archive found in $BACKUP_DIR"
ARCHIVE_NAME="$(basename "$ARCHIVE")"
ARCHIVE_DIR="$(cd "$(dirname "$ARCHIVE")" && pwd)"
gzip -t "$ARCHIVE" 2>>"$OUT/run.log" || fail 2 "gzip integrity check failed for $ARCHIVE_NAME"
ARCHIVE_SHA="$(sha256sum "$ARCHIVE" | awk '{print $1}')"
say BACKUP_FILE "$ARCHIVE_NAME"
say BACKUP_SHA256 "$ARCHIVE_SHA"
log "source archive: $ARCHIVE_NAME ($(stat -c %s "$ARCHIVE") bytes, sha256 $ARCHIVE_SHA) — mounted read-only"

temp_gate before || fail 2 "M.2 temperature too high to start; let the NAS cool down first"

take_snapshot "$OUT/prod-before.txt"
log "production snapshot taken (before)"

# ================================================================ 2. isolated environment
step "isolated environment"
start_sampler

$DOCKER network create --internal "$NET" >>"$OUT/run.log" 2>&1 \
  || fail 3 "cannot create internal network $NET"
CREATED_NET=1
log "network $NET created (--internal: no route off the host, Atlas is unreachable by construction)"

$DOCKER volume create "$VOL" >>"$OUT/run.log" 2>&1 || fail 3 "cannot create volume $VOL"
CREATED_VOL=1

$DOCKER run -d --name "$MONGO_C" --network "$NET" \
  --env MONGO_URL= --env MONGODB_URI= \
  -v "$VOL:/data/db" \
  "$MONGO_IMAGE" mongod --bind_ip_all >>"$OUT/run.log" 2>&1 \
  || fail 3 "cannot start $MONGO_C"
CREATED_C=1
log "temporary mongod started: $MONGO_C (no published port, no production credentials)"

waited=0
until $DOCKER run --rm --network "$NET" "$MONGO_IMAGE" \
        mongosh --host "$MONGO_C" --quiet --eval 'db.adminCommand({ping:1}).ok' >/dev/null 2>&1; do
  waited=$((waited + 3)); sleep 3
  too_hot && fail 3 "aborted while waiting for mongod: M.2 temperature gate tripped"
  [ "$waited" -ge "$READY_TIMEOUT" ] && fail 3 "mongod did not become ready in ${READY_TIMEOUT}s"
done
log "mongod ready after ${waited}s"

# ================================================================ 3. restore
step "restore"
RESTORE_CMD="mongorestore --host $MONGO_C --gzip --archive=/backup/$ARCHIVE_NAME --verbose"
say RESTORE_COMMAND "$RESTORE_CMD"
log "$ $RESTORE_CMD   (archive mounted at /backup, read-only)"
$DOCKER run --rm --network "$NET" -v "$ARCHIVE_DIR:/backup:ro" "$MONGO_IMAGE" \
  mongorestore --host "$MONGO_C" --gzip --archive="/backup/$ARCHIVE_NAME" --verbose \
  > "$OUT/restore.out" 2>&1
rc=$?
tail -n 5 "$OUT/restore.out" | tee -a "$OUT/run.log"
[ "$rc" = 0 ] || { R_RESTORE=FAIL; say RESTORE FAIL; fail 3 "mongorestore exited $rc"; }
too_hot && { R_RESTORE=FAIL; fail 3 "M.2 temperature gate tripped during restore"; }

RESTORED_DOCS="$(grep -oE '[0-9]+ document\(s\) restored successfully' "$OUT/restore.out" | tail -n1 | grep -oE '^[0-9]+')"
FAILED_DOCS="$(grep -oE '[0-9]+ document\(s\) failed to restore' "$OUT/restore.out" | tail -n1 | grep -oE '^[0-9]+')"
if [ -z "$RESTORED_DOCS" ]; then
  R_RESTORE=FAIL; say RESTORE FAIL
  fail 3 "mongorestore summary line not found in its output — cannot prove what was written (tool output format changed?)"
fi
: "${FAILED_DOCS:=0}"
say RESTORED_DOCS "$RESTORED_DOCS"
say FAILED_DOCS "$FAILED_DOCS"
[ "$FAILED_DOCS" = 0 ] || { R_RESTORE=FAIL; say RESTORE FAIL; fail 3 "$FAILED_DOCS document(s) failed to restore"; }
R_RESTORE=PASS; say RESTORE PASS
log "restore OK: $RESTORED_DOCS documents, 0 failures"

# ================================================================ 4. verification
step "verification"
$DOCKER run --rm --network "$NET" -v "$VERIFY_JS:/verify.js:ro" "$MONGO_IMAGE" \
  mongosh --host "$MONGO_C" --quiet --file /verify.js > "$OUT/verify.json" 2>"$OUT/verify.err"
rc=$?
[ "$rc" = 0 ] || { R_VERIFY=FAIL; say VERIFICATION FAIL; fail 3 "verification script exited $rc (see verify.err)"; }

read_json() { # read_json KEY — top-level scalar out of verify.json without a JSON parser
  sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\{0,1\}\([^,\"}]*\)\"\{0,1\}.*/\1/p" "$OUT/verify.json" | head -n1
}
V_OK="$(read_json ok)"
V_DOCS="$(read_json total_documents)"
V_COLLS="$(read_json total_collections)"
V_DBS="$(read_json total_databases)"
V_NOIDX="$(read_json collections_without_id_index)"
V_SAMPLES="$(read_json sample_reads_failed)"
V_TENANT="$(read_json tenant_check)"
say VERIFY_DATABASES "$V_DBS"
say VERIFY_COLLECTIONS "$V_COLLS"
say VERIFY_DOCUMENTS "$V_DOCS"
log "restored: $V_DBS databases, $V_COLLS collections, $V_DOCS documents"

[ "$V_OK" = "true" ] || { R_VERIFY=FAIL; say VERIFICATION FAIL; fail 3 "verification reported ok=false"; }
[ "${V_NOIDX:-1}" = 0 ] || { R_VERIFY=FAIL; say VERIFICATION FAIL; fail 3 "$V_NOIDX collection(s) restored without an _id index"; }
[ "${V_SAMPLES:-1}" = 0 ] || { R_VERIFY=FAIL; say VERIFICATION FAIL; fail 3 "$V_SAMPLES sample read(s) failed"; }
# integrity: what mongorestore claims it wrote must equal what the server actually holds
if [ "$RESTORED_DOCS" != "$V_DOCS" ]; then
  R_VERIFY=FAIL; say VERIFICATION FAIL
  fail 3 "document count mismatch: mongorestore reported $RESTORED_DOCS, server holds $V_DOCS"
fi
R_VERIFY=PASS; say VERIFICATION PASS
R_TENANT="${V_TENANT:-NOT_APPLICABLE}"; say TENANT_CHECK "$R_TENANT"
log "verification PASS (counts agree, every collection has _id index, sample reads OK, tenant check $R_TENANT)"

temp_gate after >/dev/null 2>&1 || log "note: M.2 temperature is high after the run"

# ================================================================ 5. cleanup and production proof
cleanup || { prod_check; finish 4; }

step "production unchanged?"
if prod_check; then
  log "production identical before and after (containers, .env hash, DEPLOYED_COMMIT, repo/, backups)"
else
  log "production DIFFERS before vs after — see prod-diff.txt"
  finish 5
fi

finish 0
