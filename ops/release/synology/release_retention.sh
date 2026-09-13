#!/usr/bin/env bash
# W0-09A — retention of retired source trees. DRY RUN by default.
#
#   sudo bash <bundle>/tools/synology/release_retention.sh [--keep N] [--apply]
#
# Policy
#   * NEVER removed: the active tree (repo), the recorded immediate rollback target
#     (previous.env TREE_DIR), bundles, manifests and evidence (release-state/history).
#   * Candidates: repo.rollback-*, repo.failed-*, repo.rolledback-*, repo_before_*,
#     stale repo.staging-* (only when no release lock is held) and release-state/retired/*.
#   * The newest N candidates are kept (default 1); older ones are removed only with --apply.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib.sh"

KEEP=1; APPLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --keep) KEEP="${2:-}"; shift 2 ;;
    --apply) APPLY=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 3 ;;
  esac
done
[[ "$KEEP" =~ ^[0-9]+$ ]] || { echo "--keep must be a number" >&2; exit 3; }
rel_setup retention
trap 'lock_release' EXIT

PROTECT_A="repo"; PROTECT_B=""; PROTECT_C=""
if [ -f "$STATE/current.env" ]; then read_kv "$STATE/current.env" C && PROTECT_B="$C_TREE_DIR"; fi
if [ -f "$STATE/previous.env" ]; then read_kv "$STATE/previous.env" V && PROTECT_C="$V_TREE_DIR"; fi
log "protected: $PROTECT_A ${PROTECT_B:+$PROTECT_B }${PROTECT_C:+$PROTECT_C (rollback target)}"

LOCK_HELD=0; [ -d "$STATE/lock" ] && LOCK_HELD=1
candidates=()
while IFS= read -r d; do
  [ -n "$d" ] || continue
  name="$(basename "$d")"
  [ -d "$d" ] && [ ! -L "$d" ] || continue
  if [ "$(dirname "$d")" = "$BASE" ]; then
    case "$name" in repo|"$PROTECT_B"|"$PROTECT_C") continue ;; esac
    case "$name" in
      repo.staging-*) [ "$LOCK_HELD" = 0 ] || continue ;;
      repo.rollback-*|repo.failed-*|repo.rolledback-*|repo_before_*) ;;
      *) continue ;;
    esac
  fi
  candidates+=("$d")
done < <(ls -1dt "$BASE"/repo.rollback-* "$BASE"/repo.failed-* "$BASE"/repo.rolledback-* \
                 "$BASE"/repo_before_* "$BASE"/repo.staging-* "$STATE"/retired/* 2>/dev/null)

removed=0
for i in "${!candidates[@]}"; do
  d="${candidates[$i]}"
  if [ "$i" -lt "$KEEP" ]; then log "keep   : $d"; continue; fi
  if [ "$APPLY" = 1 ]; then
    [ "${LOCKED:-0}" = 1 ] || lock_acquire
    case "$(dirname "$d")" in "$BASE"|"$STATE/retired") ;; *) log "skip (unexpected parent): $d"; continue ;; esac
    rm -rf -- "$d" && removed=$((removed + 1)) && log "REMOVED: $d"
  else
    log "remove : $d (dry run)"
  fi
done
log "candidates=${#candidates[@]} keep=$KEEP removed=$removed apply=$APPLY; evidence/manifests/bundles are never removed"
exit 0
