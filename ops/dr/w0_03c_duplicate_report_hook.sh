#!/usr/bin/env bash
# W0-03C — Master Data duplicate report on a freshly restored copy.
#
# A POST_VERIFY_HOOK for the W0-10A restore proof. It is never run on its own:
#
#   sudo POST_VERIFY_HOOK=/volume1/docker/w003c/<sha>/ops/dr/w0_03c_duplicate_report_hook.sh \
#        bash /volume1/docker/w003c/<sha>/ops/dr/w0_10a_restore_proof.sh
#
# The runner calls it after the restore is verified and BEFORE cleanup, with:
#   W010A_NET          the --internal network of this run
#   W010A_MONGO_HOST   the temporary mongod holding the restored copy
#   W010A_MONGO_IMAGE  the mongo image the runner already uses (mongosh inside)
#   W010A_HOOK_OUT     this hook's evidence directory ($OUT/hook)
#   DOCKER             the docker CLI
#
# What it does, and nothing else:
#   1. export — mongosh on the internal network reads ONLY the collections and fields of
#      the export plan (w0_03c_export.js) from the RESTORED copy. Atlas and production are
#      out of reach: the network is --internal, and the script never gets a URL for them.
#   2. report — the stdlib-only report (backend/app/master_data/uniqueness.py) runs in a
#      python container with NO network and a read-only root filesystem.
#   3. the export holds raw identifiers, so it is written mode 600, named *.sensitive.*
#      (the runner's cleanup removes such files even if this hook is killed) and deleted
#      here as soon as the report exists. Its sha256 and size stay as evidence.
#
# Nothing is merged, fixed, deleted or indexed. A report that finds duplicates is a
# RESULT, not a failure: the hook exits 0 and says BLOCKED. It exits non-zero only when
# no trustworthy report could be produced.
set -u
umask 077

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE="${W003C_BUNDLE:-$(cd "$HERE/../.." && pwd)}"
EXPORT_JS="${W003C_EXPORT_JS:-$HERE/w0_03c_export.js}"
PYTHON_IMAGE="${W003C_PYTHON_IMAGE:-python:3.11-slim}"
MASTER_DATA_DIR="$BUNDLE/backend/app/master_data"
CLI="$BUNDLE/backend/scripts/w0_03c_master_data_uniqueness.py"

OUT="${W010A_HOOK_OUT:-}"
EXPORT="$OUT/export.sensitive.json"
REPORT="$OUT/report.json"

log() { printf '[%s] w003c: %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
say() { printf '%s=%s\n' "$1" "$2" >> "$OUT/result.env"; }
die() { log "FAIL: $*"; say W003C_RESULT FAIL; say W003C_FAIL_REASON "$*"; exit 1; }

drop_export() {
  [ -n "$OUT" ] || return 0
  rm -f "$EXPORT" 2>/dev/null
  if [ -e "$EXPORT" ]; then
    log "the export could NOT be deleted: $EXPORT"
    return 1
  fi
  return 0
}
trap 'drop_export' EXIT
trap 'drop_export; exit 130' INT TERM

# ---------------------------------------------------------------- preconditions
[ -n "$OUT" ] || { echo "w003c: W010A_HOOK_OUT is not set — this hook runs only from the W0-10A runner" >&2; exit 1; }
mkdir -p "$OUT" 2>/dev/null || { echo "w003c: cannot create $OUT" >&2; exit 1; }
for v in W010A_NET W010A_MONGO_HOST W010A_MONGO_IMAGE DOCKER; do
  eval "val=\${$v:-}"
  [ -n "$val" ] || die "$v is not set — this hook runs only from the W0-10A runner"
done
case "$W010A_NET" in w010a-net-*) ;; *) die "refusing: network '$W010A_NET' is not a W0-10A isolated network" ;; esac
case "$W010A_MONGO_HOST" in w010a-mongo-*) ;; *) die "refusing: host '$W010A_MONGO_HOST' is not a W0-10A temporary mongod" ;; esac

[ -r "$EXPORT_JS" ] || die "export script not readable: $EXPORT_JS"
[ -d "$MASTER_DATA_DIR" ] && [ -r "$MASTER_DATA_DIR/uniqueness.py" ] || die "report code missing under $MASTER_DATA_DIR"
[ -r "$CLI" ] || die "report CLI missing: $CLI"
$DOCKER image inspect "$PYTHON_IMAGE" >/dev/null 2>&1 \
  || die "image $PYTHON_IMAGE is not present locally; pull it first (the run stays offline)"

say W003C_EXPORT_JS_SHA256 "$(sha256sum "$EXPORT_JS" | awk '{print $1}')"
say W003C_UNIQUENESS_PY_SHA256 "$(sha256sum "$MASTER_DATA_DIR/uniqueness.py" | awk '{print $1}')"
say W003C_PYTHON_IMAGE "$PYTHON_IMAGE"
say W003C_PYTHON_IMAGE_ID "$($DOCKER image inspect -f '{{.Id}}' "$PYTHON_IMAGE" 2>/dev/null)"

# ---------------------------------------------------------------- 1. export (read-only)
log "export: planned collections and fields only, from $W010A_MONGO_HOST on $W010A_NET"
: > "$EXPORT" && chmod 600 "$EXPORT"
$DOCKER run --rm --network "$W010A_NET" -v "$EXPORT_JS:/w003c_export.js:ro" "$W010A_MONGO_IMAGE" \
  mongosh --host "$W010A_MONGO_HOST" --quiet --file /w003c_export.js > "$EXPORT" 2>"$OUT/export.err"
rc=$?
[ "$rc" = 0 ] || die "export exited $rc (see export.err)"
[ -s "$EXPORT" ] || die "export is empty"
if [ "$(head -c 11 "$EXPORT")" = '{"ok":false' ]; then
  head -n 1 "$EXPORT" >> "$OUT/export.err"     # the error line only, no data
  die "export reported a fatal error (see export.err)"
fi
EXPORT_SHA="$(sha256sum "$EXPORT" | awk '{print $1}')"
EXPORT_BYTES="$(wc -c < "$EXPORT" | tr -d ' ')"
say W003C_EXPORT_SHA256 "$EXPORT_SHA"
say W003C_EXPORT_BYTES "$EXPORT_BYTES"
log "export: $EXPORT_BYTES bytes, sha256 $EXPORT_SHA (mode 600, deleted after the report)"

# ---------------------------------------------------------------- 2. report (no network)
log "report: stdlib-only, --network none, read-only root filesystem"
$DOCKER run --rm --network none --read-only \
  -v "$MASTER_DATA_DIR:/w003c/app/master_data:ro" \
  -v "$CLI:/w003c/scripts/w0_03c_master_data_uniqueness.py:ro" \
  -v "$OUT:/out" \
  "$PYTHON_IMAGE" \
  python -I -B /w003c/scripts/w0_03c_master_data_uniqueness.py report \
    --from-export /out/export.sensitive.json --out /out/report.json \
  > "$OUT/report.summary.txt" 2>&1
rc=$?
cat "$OUT/report.summary.txt"
case "$rc" in
  0) VERDICT=CLEAN ;;
  1) VERDICT=BLOCKED ;;
  *) die "report exited $rc (see report.summary.txt)" ;;
esac
[ -s "$REPORT" ] || die "report exited $rc but wrote no report.json"
chmod 644 "$REPORT" "$OUT/report.summary.txt" 2>/dev/null
say W003C_REPORT_SHA256 "$(sha256sum "$REPORT" | awk '{print $1}')"
say W003C_REPORT "$VERDICT"

# ---------------------------------------------------------------- 3. the export goes
drop_export || die "the raw export could not be deleted"
say W003C_EXPORT_DELETED yes
say W003C_RESULT PASS
log "report $VERDICT — $REPORT (the raw export is deleted)"
exit 0
