#!/usr/bin/env bash
# W0-03C — Master Data duplicate report on a freshly restored copy.
#
# A POST_VERIFY_HOOK for the W0-10A restore proof. It is never run on its own:
#
#   sudo env DOCKER=/usr/local/bin/docker \
#        POST_VERIFY_HOOK=/volume1/docker/w003c/<sha>/ops/dr/w0_03c_duplicate_report_hook.sh \
#        bash /volume1/docker/w003c/<sha>/ops/dr/w0_10a_restore_proof.sh
#
#   DOCKER=/usr/local/bin/docker is required on DSM: sudo does not carry the operator's
#   PATH, and DSM's docker binary is outside sudo's secure_path, so without it the runner
#   fails "docker not found" (exit 2) before the restore even starts. Confirm the path
#   with `which docker` (no sudo) if the Docker/Container Manager package is installed
#   elsewhere.
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
# Nothing is merged, fixed, deleted or indexed. Three outcomes, and only two of them pass:
#   CLEAN       exit 0 — a complete export, no duplicates
#   BLOCKED     exit 0 — a complete export, duplicates found: a RESULT, not a failure
#   INCOMPLETE  exit 1 — the export is empty or lacks an expected database or collection,
#               so it proves nothing. This is a FAILURE: it blocks the W0-10A PASS.
# Anything else (a missing report, an exit code that disagrees with the verdict the report
# states) is a failure too: the hook passes only on a report it can trust.
#
# What the restored copy must contain (override only with a reason):
#   W003C_EXPECT_DBS          databases that must be restored and hold planned collections
#   W003C_EXPECT_COLLECTIONS  <database>.<collection> pairs that must be in the export
# The defaults are what the restored copy of 20.09.2026 held (W0-10A evidence,
# verify.json): begwork_beg with companies, clients, counterparties, persons, items and
# asset_units (subcontractors was absent, so it is not required).
set -u
umask 077

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE="${W003C_BUNDLE:-$(cd "$HERE/../.." && pwd)}"
EXPORT_JS="${W003C_EXPORT_JS:-$HERE/w0_03c_export.js}"
PYTHON_IMAGE="${W003C_PYTHON_IMAGE:-python:3.11-slim}"
EXPECT_DBS="${W003C_EXPECT_DBS-begwork_beg}"
EXPECT_COLLECTIONS="${W003C_EXPECT_COLLECTIONS-begwork_beg.companies begwork_beg.clients begwork_beg.counterparties begwork_beg.persons begwork_beg.items begwork_beg.asset_units}"
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

EXPECT_ARGS=""
for d in $EXPECT_DBS; do
  case "$d" in *[!A-Za-z0-9_-]*|'') die "invalid W003C_EXPECT_DBS entry '$d'" ;; esac
  EXPECT_ARGS="$EXPECT_ARGS --expect-db $d"
done
for c in $EXPECT_COLLECTIONS; do
  case "$c" in *[!A-Za-z0-9._-]*|.*|*.|*..*) die "invalid W003C_EXPECT_COLLECTIONS entry '$c'" ;; esac
  case "$c" in *.*) ;; *) die "invalid W003C_EXPECT_COLLECTIONS entry '$c' (need <database>.<collection>)" ;; esac
  EXPECT_ARGS="$EXPECT_ARGS --expect-collection $c"
done
[ -n "$EXPECT_DBS" ] || die "W003C_EXPECT_DBS is empty — the report must know which restored database it is judging"

[ -r "$EXPORT_JS" ] || die "export script not readable: $EXPORT_JS"
[ -d "$MASTER_DATA_DIR" ] && [ -r "$MASTER_DATA_DIR/uniqueness.py" ] || die "report code missing under $MASTER_DATA_DIR"
[ -r "$CLI" ] || die "report CLI missing: $CLI"
$DOCKER image inspect "$PYTHON_IMAGE" >/dev/null 2>&1 \
  || die "image $PYTHON_IMAGE is not present locally; pull it first (the run stays offline)"

say W003C_EXPORT_JS_SHA256 "$(sha256sum "$EXPORT_JS" | awk '{print $1}')"
say W003C_UNIQUENESS_PY_SHA256 "$(sha256sum "$MASTER_DATA_DIR/uniqueness.py" | awk '{print $1}')"
say W003C_PYTHON_IMAGE "$PYTHON_IMAGE"
say W003C_EXPECT_DBS "$EXPECT_DBS"
say W003C_EXPECT_COLLECTIONS "$EXPECT_COLLECTIONS"
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
# shellcheck disable=SC2086 — EXPECT_ARGS holds validated tokens only
$DOCKER run --rm --network none --read-only \
  -v "$MASTER_DATA_DIR:/w003c/app/master_data:ro" \
  -v "$CLI:/w003c/scripts/w0_03c_master_data_uniqueness.py:ro" \
  -v "$OUT:/out" \
  "$PYTHON_IMAGE" \
  python -I -B /w003c/scripts/w0_03c_master_data_uniqueness.py report \
    --from-export /out/export.sensitive.json --out /out/report.json $EXPECT_ARGS \
  > "$OUT/report.summary.txt" 2>&1
rc=$?
cat "$OUT/report.summary.txt"
[ -s "$REPORT" ] && chmod 644 "$REPORT" "$OUT/report.summary.txt" 2>/dev/null

# The exit code alone is not trusted: the CLI prints the verdict, and report.json states it.
STATED="$(tr -d '\r' < "$OUT/report.summary.txt" | sed -n 's/^verdict=\([A-Z]*\)$/\1/p' | tail -n 1)"
WRITTEN="$( (tr -d '\r' < "$REPORT") 2>/dev/null | sed -n 's/^  "verdict": "\([A-Z]*\)",\{0,1\}$/\1/p' | head -n 1)"
say W003C_REPORT_EXIT "$rc"
[ -s "$REPORT" ] && say W003C_REPORT_SHA256 "$(sha256sum "$REPORT" | awk '{print $1}')"
case "$rc:$STATED:$WRITTEN" in
  0:CLEAN:CLEAN)       VERDICT=CLEAN ;;
  1:BLOCKED:BLOCKED)   VERDICT=BLOCKED ;;
  5:INCOMPLETE:INCOMPLETE)
    say W003C_REPORT INCOMPLETE
    die "the export is not evidence (INCOMPLETE): $(sed -n 's/^  not evidence: //p' "$OUT/report.summary.txt" | head -n 3 | tr '\n' ';')" ;;
  *)
    [ -s "$REPORT" ] || die "report exited $rc but wrote no report.json"
    die "report exit $rc, stated verdict '${STATED:-none}', report.json verdict '${WRITTEN:-none}' — they must agree" ;;
esac
say W003C_REPORT "$VERDICT"

# ---------------------------------------------------------------- 3. the export goes
drop_export || die "the raw export could not be deleted"
say W003C_EXPORT_DELETED yes
say W003C_RESULT PASS
log "report $VERDICT — $REPORT (the raw export is deleted)"
exit 0
