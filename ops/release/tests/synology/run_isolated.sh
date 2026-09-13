#!/usr/bin/env bash
# W0-09A isolated validation of the Synology release tools. Explicit validation only.
#
# On the NAS (Krum, interactive SSH):
#   sudo bash /volume1/docker/w009a-isolated/w009a-isolated-<sha12>/runner/run_isolated.sh
# Locally (runner self-test, Git Bash or Linux, no Docker):
#   ISOLATED_MODE=sim RELEASE_PYTHON=python3 bash runner/run_isolated.sh
#
# Phase 1 — every scenario gets its own temporary BEGWORK_BASE under <package>/runs/<stamp>/,
#   the REAL release tools from the bundles, fake docker/docker-compose/curl for containers,
#   images and HTTP, and the REAL verifier: on the NAS the fake hands `docker run` to the real
#   Docker daemon, so release_verify.py runs in python:3.11-slim by image ID with read-only
#   bundle/base mounts on the NAS filesystem.
# Phase 2 (NAS only) — real Docker + real docker-compose on a tiny layout with its own container
#   names (w009a-rt-*) and project directory: adopt, deploy, standalone rollback and an
#   auto-rollback of a crashing release, proving by image ID that rollback runs the recorded image.
#
# Never touches /volume1/docker/begwork, its containers, images, .env or Atlas: production is
# only read (container IDs/start times, file hashes, .env size+mtime) before and after, to prove it.
# No prune, no image removal; phase 2 removes only its own containers/network (compose down).
set -u
umask 022
PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${ISOLATED_MODE:-real}"
PROD="${ISOLATED_PROD_BASE:-/volume1/docker/begwork}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN="$PKG/runs/$STAMP-$$"
RESULTS="$RUN/results.tsv"
FAILS=0

case "$PKG" in
  *w009a-isolated*) ;;
  *) echo "refusing: package path must contain w009a-isolated ($PKG)" >&2; exit 2 ;;
esac
case "$PKG/" in "$PROD"/*) echo "refusing: package inside the production layout $PROD" >&2; exit 2 ;; esac
mkdir -p "$RUN" || exit 2
exec > >(tee -a "$RUN/runner.log") 2>&1

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }
result() { # result PASS|FAIL SCENARIO TEXT
  printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "$RESULTS"
  [ "$1" = PASS ] || { FAILS=$((FAILS + 1)); log "  FAIL [$2] $3"; }
}
expect() { # expect SCENARIO TEXT command...
  local sc="$1" text="$2"; shift 2
  if "$@" >/dev/null 2>&1; then result PASS "$sc" "$text"; else result FAIL "$sc" "$text"; fi
}
kv() { sed -n "s/^$2=//p" "$1" 2>/dev/null | head -n1; }

for k in COMMIT SECRET_JWT SECRET_MONGO NGINX_BLOB B0_RELEASE B0_TREE B1_RELEASE B1_TREE B2_RELEASE B2_TREE \
         BMIG_RELEASE RT0_RELEASE RT0_TREE RT1_RELEASE RT1_TREE RTCRASH_RELEASE; do
  printf -v "$k" '%s' "$(kv "$PKG/expected.env" "$k")"
  [ -n "${!k}" ] || { echo "expected.env lacks $k" >&2; exit 2; }
done

log "W0-09A isolated validation: commit $COMMIT mode=$MODE run=$RUN"
( cd "$PKG" && sha256sum -c --quiet SHA256SUMS ) > "$RUN/package-integrity.txt" 2>&1
expect package "package SHA256SUMS verify" test -z "$(grep -v ': OK$' "$RUN/package-integrity.txt")"

# ------------------------------------------------------------------ environment / verifier
if [ "$MODE" = real ]; then
  REAL_DOCKER="$(command -v docker)" || { echo "docker not found" >&2; exit 2; }
  VERIFIER_ID="$("$REAL_DOCKER" image inspect -f '{{.Id}}' python:3.11-slim 2>/dev/null)"
  [[ "$VERIFIER_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || { echo "python:3.11-slim is not present locally" >&2; exit 2; }
  if command -v docker-compose >/dev/null 2>&1; then COMPOSE="docker-compose"; else COMPOSE="$REAL_DOCKER compose"; fi
else
  REAL_DOCKER=""; COMPOSE=""
  VERIFIER_ID="sha256:$(printf 'c%063x' 785)"
  : "${RELEASE_PYTHON:?RELEASE_PYTHON is required in sim mode}"
fi
{
  echo "mode=$MODE"; echo "commit=$COMMIT"; echo "verifier_image=$VERIFIER_ID"
  uname -a; bash --version | head -n1
  for t in tar gzip sha256sum find stat; do printf '%s: %s\n' "$t" "$("$t" --version 2>&1 | head -n1)"; done
  if [ "$MODE" = real ]; then
    "$REAL_DOCKER" version --format 'docker client {{.Client.Version}} server {{.Server.Version}}'
    $COMPOSE version 2>&1 | head -n1
    "$REAL_DOCKER" image inspect -f 'python:3.11-slim repo digests {{.RepoDigests}}' python:3.11-slim
  fi
} > "$RUN/environment.txt" 2>&1

native() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }

# rv MOUNT_RO_SRC PROBE_RW_DIR ARGS... : run release_verify.py of bundle b0 with /r = MOUNT_RO_SRC
rv() {
  local ro="$1" probe="$2"; shift 2
  if [ "$MODE" = real ]; then
    "$REAL_DOCKER" run --rm --pull never --network none --read-only --security-opt no-new-privileges \
      -e PYTHONDONTWRITEBYTECODE=1 -v "$PKG/bundles:/b:ro" -v "$ro:/r:ro" -v "$probe:/probe" \
      "$VERIFIER_ID" python3 /b/b0/tools/release_verify.py "$@"
  else
    local -a args=() a
    for a in "$@"; do
      case "$a" in /b/*) a="$(native "$PKG/bundles")${a#/b}" ;; /r/*|/r) a="$(native "$ro")${a#/r}" ;; /probe*) a="$(native "$probe")${a#/probe}" ;; esac
      args+=("$a")
    done
    "$RELEASE_PYTHON" "$(native "$PKG/bundles/b0/tools/release_verify.py")" "${args[@]}"
  fi
}
# tree_is SCENARIO_DIR RELDIR TREE BUNDLE [EXTRA] : exact tree identity (real filesystem on the NAS)
tree_is() {
  local s="$1" dir="$2" tree="$3" bundle="$4" extra="${5:-}"
  local -a x=()
  [ -n "$extra" ] && x=(--allow-extra "$extra")
  mkdir -p "$s/probe"
  rv "$s/base" "$s/probe" tree --dir "/r/$dir" --tree "$tree" --probe-dir /probe \
    --mode-hint-tar "/b/$bundle/artifact.tar" ${x[@]+"${x[@]}"} > "$s/tree-check.out" 2>&1
  grep -q '^RESULT PASS$' "$s/tree-check.out"
}
last_record() { ls -1 "$1"/base/release-state/history/*/record.json 2>/dev/null | LC_ALL=C sort | tail -n1; }
record_valid() { # record_valid SCENARIO_DIR
  local rec; rec="$(last_record "$1")"; [ -n "$rec" ] || return 1
  rv "$(dirname "$rec")" "$1/probe" record --record /r/record.json > "$1/record-check.out" 2>&1
  grep -q '^record VALID$' "$1/record-check.out"
}
record_has() { grep -q "\"$2\": \"$3\"" "$(last_record "$1")"; }
snap() { # content snapshot of a layout (+ fake daemon) without evidence/lock/call logs
  local s="$1"
  ( cd "$s" && find base fake \( -path base/release-state/history -o -path base/release-state/lock \) -prune -o -print \
      | LC_ALL=C sort | while IFS= read -r p; do
          case "$p" in fake/calls.log|fake/up_count) continue ;; esac
          if [ -f "$p" ]; then printf 'F %s %s\n' "$(sha256sum < "$p" | cut -d' ' -f1)" "$p"; else printf 'D %s\n' "$p"; fi
        done )
}

# ------------------------------------------------------------------ phase 1 scenario setup
INIT_BACKEND="sha256:$(printf 'a%063x' 176)"
INIT_FRONTEND="sha256:$(printf 'a%063x' 240)"

new_scenario() { # new_scenario NAME -> $S prepared: base with repo = b0 tree + nginx.conf, fakes, running containers
  S="$RUN/$1"
  mkdir -p "$S/base/backups" "$S/fake/images" "$S/fake/refs" "$S/bin" "$S/probe" "$S/stage"
  cp "$PKG/layout/docker-compose.yml" "$PKG/layout/Dockerfile.backend" "$PKG/layout/Dockerfile.frontend" "$S/base/"
  printf 'MONGO_URL=mongodb+srv://beg:%s@cluster.example.invalid/db\nDB_NAME=begwork\nBEG_SYSTEM_DB=begwork_system\nPUBLIC_URL=http://192.0.2.10:8080\nCORS_ORIGINS=*\nJWT_SECRET=%s\n' \
    "$SECRET_MONGO" "$SECRET_JWT" > "$S/base/.env"
  printf 'fake archive' | gzip > "$S/base/backups/begwork_atlas_2026-09-13_0310.archive.gz"
  rv "$S/base" "$S/stage" bundle --bundle /b/b0 --stage /probe/repo --probe-dir /probe > "$S/extract.out" 2>&1
  mv "$S/stage/repo" "$S/base/repo" && cp "$PKG/layout/nginx.conf" "$S/base/repo/nginx.conf"
  cp "$PKG/runner/fakes/docker" "$PKG/runner/fakes/docker-compose" "$PKG/runner/fakes/curl" "$S/bin/"
  chmod 755 "$S/bin/docker" "$S/bin/docker-compose" "$S/bin/curl"
  local F="$S/fake"
  : > "$F/images/${VERIFIER_ID#sha256:}"; printf '%s' "$VERIFIER_ID" > "$F/refs/python+3.11-slim"
  local svc c id
  for svc in backend frontend; do
    c="begwork-$svc"; [ "$svc" = backend ] && id="$INIT_BACKEND" || id="$INIT_FRONTEND"
    printf '%s' "$c" > "$F/svc_$svc"; printf '%s' "begwork-$svc" > "$F/svcref_$svc"
    : > "$F/images/${id#sha256:}"; printf '%s' "$id" > "$F/refs/begwork-$svc+latest"
    printf 'running|0|2026-01-01T00:00:00.000000000Z\n' > "$F/c_$c"
    printf '%s' "$id" > "$F/cimg_$c"; printf '%s' "begwork-$svc" > "$F/cref_$c"
  done
}
tool() { # tool OUTNAME BUNDLE SCRIPT ARGS... -> exit code; output in $S/OUTNAME.out
  local name="$1" bundle="$2" script="$3"; shift 3
  local -a extra=()
  [ "$MODE" = real ] && extra=(FAKE_ALLOWED_ROOT="$PKG" REAL_DOCKER="$REAL_DOCKER")
  env BEGWORK_BASE="$S/base" RELEASE_PY_MODE=docker DOCKER=docker CURL=curl COMPOSE_BIN=docker-compose SLEEP=true \
      FAKE="$S/fake" REQUIRE_BACKUP=1 FAKE_DOCKER_RUN="$MODE" FAKE_VERIFY_IMAGE_ID="$VERIFIER_ID" \
      RELEASE_PYTHON="${RELEASE_PYTHON:-python3}" PATH="$S/bin:$PATH" ${extra[@]+"${extra[@]}"} \
      bash "$PKG/bundles/$bundle/tools/synology/$script" "$@" > "$S/$name.out" 2>&1
  echo $?
}
ups() { grep '^compose up' "$S/fake/calls.log" 2>/dev/null | tr '\n' ';'; }
adopt() { rc="$(tool adopt b0 release_adopt.sh)"; expect "$1" "adopt b0 exit 0" test "$rc" = 0; }

UP_BUILD="compose up -d --no-deps --build backend;"
UP_EXACT="compose up -d --no-deps --no-build --force-recreate backend;"

# ------------------------------------------------------------------ phase 1
log "=== PHASE 1: tools + fake containers + real verifier ==="

SC=env; S="$RUN/env"; mkdir -p "$S/probe" "$S/ro"
rv "$S/ro" "$S/probe" manifest --manifest /b/b1/manifest.json > "$S/verifier-python.out" 2>&1
expect $SC "verifier container validates a manifest" grep -q '^manifest VALID$' "$S/verifier-python.out"
if [ "$MODE" = real ]; then
  "$REAL_DOCKER" run --rm --pull never --network none --read-only "$VERIFIER_ID" python3 -c 'import platform; print(platform.python_version())' > "$S/python-version.txt" 2>&1
  expect $SC "verifier python is 3.11.x ($(cat "$S/python-version.txt"))" grep -q '^3\.11\.' "$S/python-version.txt"
  echo "must not be writable" > "$S/ro/sentinel.txt"
  "$REAL_DOCKER" run --rm --pull never --network none --read-only -v "$S/ro:/base:ro" "$VERIFIER_ID" \
    python3 -c "open('/base/sentinel.txt','w').write('x')" > "$S/ro-write-attempt.out" 2>&1
  expect $SC "read-only /base mount refuses writes (negative control)" test "$(cat "$S/ro/sentinel.txt")" = "must not be writable"
fi
mkdir -p "$S/modes"
rv "$S/ro" "$S/modes" bundle --bundle /b/b1 --stage /probe/tree --probe-dir /probe > "$S/stage-modes.out" 2>&1
expect $SC "staged extraction on this filesystem verifies" grep -q '^RESULT PASS$' "$S/stage-modes.out"
if grep -q 'exec bits from the release artifact' "$S/stage-modes.out"; then FSMODE="not kept (exec bits taken from artifact)"; else FSMODE="kept (exec bits verified on disk)"; fi
if [ "$MODE" = real ]; then
  printf 'filesystem POSIX modes: %s; tools/run.sh on disk: %s\n' "$FSMODE" "$(stat -c '%a' "$S/modes/tree/tools/run.sh" 2>&1)" >> "$RUN/environment.txt"
else
  printf 'filesystem POSIX modes: %s\n' "$FSMODE" >> "$RUN/environment.txt"
fi
result PASS $SC "filesystem mode probe: $FSMODE"

SC=adopt; new_scenario $SC; adopt $SC
expect $SC "current = b0" test "$(kv "$S/base/release-state/current.env" RELEASE_ID)" = "$B0_RELEASE"
expect $SC "runtime images recorded" test "$(kv "$S/base/release-state/current.env" RUNTIME_IMAGES)" = "backend=$INIT_BACKEND,frontend=$INIT_FRONTEND"
expect $SC "live repo = b0 tree + nginx.conf" tree_is "$S" repo "$B0_TREE" b0 "nginx.conf=$NGINX_BLOB"
expect $SC "record valid (python 3.11 verifier)" record_valid "$S"
expect $SC "no compose action" test -z "$(ups)"

SC=deploy; new_scenario $SC; adopt $SC
rc="$(tool deploy b1 release_deploy.sh)"
expect $SC "deploy b1 exit 0" test "$rc" = 0
expect $SC "repo = b1 tree (exact)" tree_is "$S" repo "$B1_TREE" b1
expect $SC "rollback anchor = b0 tree + nginx.conf" tree_is "$S" "repo.rollback-$B0_RELEASE" "$B0_TREE" b0 "nginx.conf=$NGINX_BLOB"
expect $SC "only backend rebuilt" test "$(ups)" = "$UP_BUILD"
expect $SC "current = b1, previous = b0" test "$(kv "$S/base/release-state/current.env" RELEASE_ID)/$(kv "$S/base/release-state/previous.env" RELEASE_ID)" = "$B1_RELEASE/$B0_RELEASE"
expect $SC "marker outside repo/" test "$(cat "$S/base/DEPLOYED_COMMIT" 2>/dev/null)" != "" -a ! -e "$S/base/repo/DEPLOYED_COMMIT"
expect $SC "record DEPLOYED valid" record_valid "$S"
expect $SC "no staging leftovers" test -z "$(ls -d "$S"/base/repo.staging-* 2>/dev/null)"
grep -h '^docker run' "$S/fake/calls.log" > "$S/verifier-runs.txt"
expect $SC "every verifier run: /base read-only" test -z "$(grep -v ':/base:ro ' "$S/verifier-runs.txt")"
expect $SC "every verifier run by image id $VERIFIER_ID" test -z "$(grep -v " $VERIFIER_ID python3 " "$S/verifier-runs.txt")"

precheck_case() { # precheck_case NAME BUNDLE NEEDLE PREPARE_FN
  SC="$1"; new_scenario "$SC"; adopt "$SC"; "$4"
  local before after; before="$(snap "$S")"
  rc="$(tool deploy "$2" release_deploy.sh)"
  after="$(snap "$S")"
  expect "$SC" "precheck exit 2" test "$rc" = 2
  expect "$SC" "reason: $3" grep -qF "$3" "$S/deploy.out"
  expect "$SC" "nothing changed (layout + containers + images)" test "$before" = "$after"
  expect "$SC" "no compose action" test -z "$(ups)"
}
tamper_b1() { rm -rf "$PKG/bundles/b1-tampered-$STAMP"; cp -r "$PKG/bundles/b1" "$PKG/bundles/b1-tampered-$STAMP"
  printf '\x00TAMPER' | dd of="$PKG/bundles/b1-tampered-$STAMP/artifact.tar" bs=1 seek=4096 conv=notrunc 2>/dev/null; }
drift() { printf '%s' "sha256:$(printf 'd%063x' 1)" > "$S/fake/cimg_begwork-backend"; }
noop() { :; }
tamper_b1
precheck_case precheck-tampered "b1-tampered-$STAMP" "sha256sums.match" noop
precheck_case precheck-runtime-drift b1 "runtime drift" drift
precheck_case precheck-migration bmig "[FAIL] migrations.not_declared" noop
precheck_case precheck-version-mismatch b2 "version mismatch" noop
rm -rf "$PKG/bundles/b1-tampered-$STAMP"

auto_case() { # auto_case NAME NEEDLE ON_UP_1 ON_UP_2 [compose_fail]
  SC="$1"; new_scenario "$SC"; adopt "$SC"
  printf '%s\n' "$3" > "$S/fake/on_up_1"; printf '%s\n' "$4" > "$S/fake/on_up_2"
  [ "${5:-}" = compose_fail ] && : > "$S/fake/compose_fail_1"
  rc="$(tool deploy b1 release_deploy.sh)"
  expect "$SC" "auto-rollback exit 1" test "$rc" = 1
  expect "$SC" "trigger: $2" grep -qF "$2" "$S/deploy.out"
  expect "$SC" "repo back to b0 tree + nginx.conf (exact)" tree_is "$S" repo "$B0_TREE" b0 "nginx.conf=$NGINX_BLOB"
  expect "$SC" "state still b0" test "$(kv "$S/base/release-state/current.env" RELEASE_ID)" = "$B0_RELEASE"
  expect "$SC" "backend runs the recorded image again" test "$(cat "$S/fake/cimg_begwork-backend")" = "$INIT_BACKEND"
  expect "$SC" "rollback recreated without build" test "$(ups)" = "$UP_BUILD$UP_EXACT"
  expect "$SC" "record ROLLED_BACK / EXACT_IMAGE" record_has "$S" runtime_rollback EXACT_IMAGE
  expect "$SC" "record valid" record_valid "$S"
}
auto_case auto-compose-failure "docker compose up failed" "" "" compose_fail
auto_case auto-backend-not-starting "did not start" 'touch "$FAKE/crash_backend"; echo "/api/health 000" > "$FAKE/http_codes"' 'rm -f "$FAKE/crash_backend" "$FAKE/http_codes"'
auto_case auto-health "health /api/health returned 502" 'echo "/api/health 502" > "$FAKE/http_codes"' 'rm -f "$FAKE/http_codes"'
auto_case auto-restart-loop "restart loop" 'touch "$FAKE/restart_loop_begwork-backend"' 'rm -f "$FAKE/restart_loop_begwork-backend"'
auto_case auto-5xx "GET /api/roles returned 500" 'echo "/api/roles 500" > "$FAKE/http_codes"' 'rm -f "$FAKE/http_codes"'
auto_case auto-startup-log "startup/config errors" "printf 'Traceback (most recent call last):\\n  bad auth for $SECRET_MONGO\\n' > \"\$FAKE/logs_begwork-backend\"" 'rm -f "$FAKE/logs_begwork-backend"'
auto_case auto-not-recreated "version mismatch" 'touch "$FAKE/no_recreate"' 'rm -f "$FAKE/no_recreate"'
auto_case auto-flag-mismatch "flag PERMISSION_SERVICE_MODE" 'printf enforce > "$FAKE/env_begwork-backend_PERMISSION_SERVICE_MODE"' 'rm -f "$FAKE/env_begwork-backend_PERMISSION_SERVICE_MODE"'

SC=auto-image-missing; new_scenario $SC; adopt $SC
printf 'rm -f "$FAKE/images/%s"; echo "/api/health 502" > "$FAKE/http_codes"\n' "${INIT_BACKEND#sha256:}" > "$S/fake/on_up_1"
printf 'rm -f "$FAKE/http_codes"\n' > "$S/fake/on_up_2"
rc="$(tool deploy b1 release_deploy.sh)"
expect $SC "auto-rollback exit 1" test "$rc" = 1
expect $SC "says NOT runtime-exact" grep -qF "NOT runtime-exact" "$S/deploy.out"
expect $SC "record SOURCE_REBUILD" record_has "$S" runtime_rollback SOURCE_REBUILD
expect $SC "repo back to b0 tree" tree_is "$S" repo "$B0_TREE" b0 "nginx.conf=$NGINX_BLOB"

SC=rollback; new_scenario $SC; adopt $SC
rc="$(tool deploy b1 release_deploy.sh)"; expect $SC "deploy b1 exit 0" test "$rc" = 0
before="$(snap "$S")"; rc="$(tool rollback-dry b1 release_rollback.sh)"; after="$(snap "$S")"
expect $SC "dry run exit 0 and nothing moved" test "$rc/$before" = "0/$after"
rc="$(tool rollback b1 release_rollback.sh --yes)"
expect $SC "rollback --yes exit 0" test "$rc" = 0
expect $SC "repo = recorded target b0 tree + nginx.conf" tree_is "$S" repo "$B0_TREE" b0 "nginx.conf=$NGINX_BLOB"
expect $SC "backend runs the recorded b0 image" test "$(cat "$S/fake/cimg_begwork-backend")" = "$INIT_BACKEND"
expect $SC "no build during rollback" test "$(ups)" = "$UP_BUILD$UP_EXACT"
expect $SC "record ROLLBACK_DONE / EXACT_IMAGE valid" record_has "$S" runtime_rollback EXACT_IMAGE
expect $SC "record valid" record_valid "$S"
expect $SC "rolled-back tree kept = b1 tree" tree_is "$S" "$(cd "$S/base" && ls -d repo.rolledback-* | head -n1)" "$B1_TREE" b1

SC=rollback-tampered; new_scenario $SC; adopt $SC
rc="$(tool deploy b1 release_deploy.sh)"
echo "# tampered" >> "$S/base/repo.rollback-$B0_RELEASE/backend/server.py"
before="$(snap "$S")"; rc="$(tool rollback b1 release_rollback.sh --yes)"; after="$(snap "$S")"
expect $SC "refused exit 2" test "$rc" = 2
expect $SC "reason missing/tampered" grep -qF "missing/tampered" "$S/rollback.out"
expect $SC "nothing changed" test "$before" = "$after"

SC=rollback-image-missing; new_scenario $SC; adopt $SC
rc="$(tool deploy b1 release_deploy.sh)"
rm -f "$S/fake/images/${INIT_BACKEND#sha256:}"
before="$(snap "$S")"; rc="$(tool rollback b1 release_rollback.sh --yes)"; after="$(snap "$S")"
expect $SC "refused without --allow-source-rebuild (exit 2)" test "$rc" = 2
expect $SC "nothing changed" test "$before" = "$after"
rc="$(tool rollback-rebuild b1 release_rollback.sh --yes --allow-source-rebuild)"
expect $SC "with --allow-source-rebuild exit 0" test "$rc" = 0
expect $SC "record SOURCE_REBUILD" record_has "$S" runtime_rollback SOURCE_REBUILD

SC=retention; new_scenario $SC; adopt $SC
rc="$(tool deploy1 b1 release_deploy.sh)"; expect $SC "deploy b1 exit 0" test "$rc" = 0
rc="$(tool deploy2 b2 release_deploy.sh)"; expect $SC "deploy b2 exit 0" test "$rc" = 0
mkdir -p "$S/base/repo.failed-old-1/x" "$S/base/repo_before_0123456789abcdef/x" "$S/base/release-state/retired/repo.rollback-ancient/x"
before="$(snap "$S")"; rc="$(tool retention-dry b2 release_retention.sh --keep 0 --images)"; after="$(snap "$S")"
expect $SC "dry run exit 0, nothing removed" test "$rc/$before" = "0/$after"
rc="$(tool retention b2 release_retention.sh --keep 0 --images --apply)"
expect $SC "apply exit 0" test "$rc" = 0
expect $SC "active repo = b2 tree" tree_is "$S" repo "$B2_TREE" b2
expect $SC "rollback target kept = b1 tree" tree_is "$S" "repo.rollback-$B1_RELEASE" "$B1_TREE" b1
expect $SC "old trees removed" test ! -e "$S/base/repo.failed-old-1" -a ! -e "$S/base/repo_before_0123456789abcdef" -a ! -e "$S/base/release-state/retired/repo.rollback-ancient"
expect $SC "b0 image tags removed" test ! -e "$S/fake/refs/beg-release%backend+$B0_RELEASE"
expect $SC "current/previous image tags kept" test -e "$S/fake/refs/beg-release%backend+$B1_RELEASE" -a -e "$S/fake/refs/beg-release%backend+$B2_RELEASE"
expect $SC "evidence kept" test -n "$(ls "$S/base/release-state/history")"
rc="$(tool rollback-dry b2 release_rollback.sh)"
expect $SC "rollback still possible after retention (dry run exit 0)" test "$rc" = 0

# ------------------------------------------------------------------ phase 2 (real docker + compose)
prod_snapshot() {
  [ -d "$PROD" ] || { echo "production layout $PROD not present"; return 0; }
  local n f
  for n in $("$REAL_DOCKER" ps -a --format '{{.Names}}' | grep '^begwork-' | LC_ALL=C sort); do
    printf '%s %s\n' "$n" "$("$REAL_DOCKER" inspect -f '{{.Id}} {{.Image}} {{.State.Status}} {{.State.StartedAt}} restarts={{.RestartCount}}' "$n")"
  done
  for f in DEPLOYED_COMMIT DEPLOYED_VERSION.txt docker-compose.yml Dockerfile.backend Dockerfile.frontend; do
    [ -f "$PROD/$f" ] && printf '%s %s\n' "$f" "$(sha256sum < "$PROD/$f" | cut -d' ' -f1)"
  done
  printf '.env size+mtime %s\n' "$(stat -c '%s %Y' "$PROD/.env" 2>/dev/null)"
  printf 'repo mtime %s\n' "$(stat -c '%Y' "$PROD/repo" 2>/dev/null)"
  printf 'release-state %s\n' "$([ -e "$PROD/release-state" ] && echo present || echo absent)"
  "$REAL_DOCKER" images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | grep -E '^(begwork|beg-release)' | LC_ALL=C sort
}

if [ "$MODE" = real ]; then
  log "=== PHASE 2: real Docker + docker-compose runtime rollback proof ==="
  prod_snapshot > "$RUN/production-before.txt" 2>&1
  SC=rt; S="$RUN/rt"; P2B="$S/w009art-$(date +%s)"; mkdir -p "$P2B/backups" "$S/bin" "$S/fake" "$S/probe" "$S/stage"
  if [ -n "$("$REAL_DOCKER" ps -a -q --filter name=w009a-rt-)" ]; then
    result FAIL $SC "containers named w009a-rt-* already exist; phase 2 not run"
  else
    cp "$PKG/rt-layout/docker-compose.yml" "$PKG/rt-layout/Dockerfile.backend" "$PKG/rt-layout/Dockerfile.frontend" "$P2B/"
    printf 'PUBLIC_URL=http://127.0.0.1:18080\nJWT_SECRET=%s\n' "$SECRET_JWT" > "$P2B/.env"
    printf 'fake archive' | gzip > "$P2B/backups/begwork_atlas_2026-09-13_0310.archive.gz"
    rv "$P2B" "$S/stage" bundle --bundle /b/rt0 --stage /probe/repo --probe-dir /probe > "$S/extract.out" 2>&1
    mv "$S/stage/repo" "$P2B/repo"
    cp "$PKG/runner/fakes/curl" "$S/bin/curl"; chmod 755 "$S/bin/curl"
    ( cd "$P2B" && $COMPOSE up -d --build ) > "$S/initial-up.log" 2>&1
    expect $SC "initial compose up of the isolated project" test "$?" = 0
    for i in $(seq 1 30); do
      [ "$("$REAL_DOCKER" inspect -f '{{.State.Status}}' w009a-rt-backend 2>/dev/null)" = running ] && break; sleep 2
    done
    IMG0="$("$REAL_DOCKER" inspect -f '{{.Image}}' w009a-rt-backend 2>/dev/null)"
    FIMG0="$("$REAL_DOCKER" inspect -f '{{.Image}}' w009a-rt-frontend 2>/dev/null)"
    rt_tool() { # rt_tool OUTNAME BUNDLE SCRIPT ARGS...
      local name="$1" bundle="$2" script="$3"; shift 3
      env BEGWORK_BASE="$P2B" RELEASE_PY_MODE=docker DOCKER="$REAL_DOCKER" CURL=curl COMPOSE_BIN="$COMPOSE" SLEEP=sleep \
          FAKE="$S/fake" REQUIRE_BACKUP=1 RELEASE_IMAGE_REPO=w009a-rt-release VERIFY_IMAGE="$VERIFIER_ID" PATH="$S/bin:$PATH" \
          bash "$PKG/bundles/$bundle/tools/synology/$script" "$@" > "$S/$name.out" 2>&1
      echo $?
    }
    rt_record() { ls -1 "$P2B"/release-state/history/*/record.json 2>/dev/null | LC_ALL=C sort | tail -n1; }
    rc="$(rt_tool adopt rt0 release_adopt.sh)"
    expect $SC "real: adopt rt0 exit 0 (runtime $IMG0)" test "$rc" = 0
    rc="$(rt_tool deploy rt1 release_deploy.sh)"
    IMG1="$("$REAL_DOCKER" inspect -f '{{.Image}}' w009a-rt-backend 2>/dev/null)"
    expect $SC "real: deploy rt1 exit 0" test "$rc" = 0
    expect $SC "real: backend rebuilt to a new image ($IMG1)" test -n "$IMG1" -a "$IMG1" != "$IMG0"
    expect $SC "real: frontend untouched" test "$("$REAL_DOCKER" inspect -f '{{.Image}}' w009a-rt-frontend)" = "$FIMG0"
    rv "$P2B" "$S/probe" tree --dir /r/repo --tree "$RT1_TREE" --probe-dir /probe --mode-hint-tar /b/rt1/artifact.tar > "$S/tree-rt1.out" 2>&1
    expect $SC "real: repo = rt1 tree" grep -q '^RESULT PASS$' "$S/tree-rt1.out"
    rc="$(rt_tool rollback rt1 release_rollback.sh --yes)"
    expect $SC "real: standalone rollback exit 0" test "$rc" = 0
    expect $SC "real: backend runs EXACTLY the recorded rt0 image id" test "$("$REAL_DOCKER" inspect -f '{{.Image}}' w009a-rt-backend)" = "$IMG0"
    expect $SC "real: rollback recreated without building" test -n "$(ls "$P2B"/release-state/history/*-rollback-*/compose-rollback-exact.log 2>/dev/null)" -a -z "$(ls "$P2B"/release-state/history/*-rollback-*/compose-rollback-rebuild.log 2>/dev/null)"
    expect $SC "real: record EXACT_IMAGE" grep -q '"runtime_rollback": "EXACT_IMAGE"' "$(rt_record)"
    expect $SC "real: rt1 image still available for roll-forward (tagged)" test "$("$REAL_DOCKER" image inspect -f '{{.Id}}' "w009a-rt-release/backend:$RT1_RELEASE" 2>/dev/null)" = "$IMG1"
    rc="$(rt_tool deploy-crash rtcrash release_deploy.sh)"
    expect $SC "real: crashing release auto-rolls back (exit 1)" test "$rc" = 1
    expect $SC "real: trigger detected" grep -qE 'AUTO-ROLLBACK: (container w009a-rt-backend is|restart loop)' "$S/deploy-crash.out"
    expect $SC "real: backend runs EXACTLY the recorded rt0 image id after auto-rollback" test "$("$REAL_DOCKER" inspect -f '{{.Image}}' w009a-rt-backend)" = "$IMG0"
    expect $SC "real: backend running after auto-rollback" test "$("$REAL_DOCKER" inspect -f '{{.State.Status}}' w009a-rt-backend)" = running
    expect $SC "real: record ROLLED_BACK / EXACT_IMAGE" grep -q '"runtime_rollback": "EXACT_IMAGE"' "$(rt_record)"
    rv "$P2B" "$S/probe" tree --dir /r/repo --tree "$RT0_TREE" --probe-dir /probe --mode-hint-tar /b/rt0/artifact.tar > "$S/tree-final.out" 2>&1
    expect $SC "real: repo = rt0 tree after auto-rollback" grep -q '^RESULT PASS$' "$S/tree-final.out"
    "$REAL_DOCKER" images --format '{{.Repository}}:{{.Tag}} {{.ID}}' | grep -E '^(w009a-rt-release|w009art-)' > "$S/images-left.txt" 2>&1
    ( cd "$P2B" && $COMPOSE down ) > "$S/compose-down.log" 2>&1
    expect $SC "real: isolated containers removed (compose down)" test -z "$("$REAL_DOCKER" ps -a -q --filter name=w009a-rt-)"
  fi
  prod_snapshot > "$RUN/production-after.txt" 2>&1
  expect production "production containers, files, .env metadata and images unchanged" cmp -s "$RUN/production-before.txt" "$RUN/production-after.txt"
else
  result PASS rt "phase 2 NOT RUN in sim mode (needs real Docker on the NAS)"
fi

# ------------------------------------------------------------------ secret-leak scan
SC=secrets
grep -rlF -e "$SECRET_JWT" -e "$SECRET_MONGO" "$RUN" --include='*.env' > "$RUN/secret-controls.txt" 2>/dev/null
expect $SC "control: sentinels exist in the dummy .env files" test -s "$RUN/secret-controls.txt"
# scanned: every file of the run except the dummy .env inputs and the fake hooks that inject the
# sentinel on purpose (on_up_* scripts, fake container logs)
find "$RUN" -type f ! -name '.env' ! -name 'on_up_*' ! -name 'logs_*' ! -name 'secret-*.txt' ! -name runner.log \
  -exec grep -lF -e "$SECRET_JWT" -e "$SECRET_MONGO" {} + > "$RUN/secret-leaks.txt" 2>/dev/null
grep -F -e "$SECRET_JWT" -e "$SECRET_MONGO" "$RUN/runner.log" >> "$RUN/secret-leaks.txt" 2>/dev/null
expect $SC "no sentinel secret in tool output, state, evidence, records, markers, compose logs" test ! -s "$RUN/secret-leaks.txt"

# ------------------------------------------------------------------ summary
TOTAL="$(wc -l < "$RESULTS")"
{
  echo "W0-09A isolated validation"
  echo "commit: $COMMIT"; echo "mode: $MODE"; echo "run: $RUN"
  echo "checks: $TOTAL, failed: $FAILS"
  cat "$RUN/environment.txt"
  echo "--- failures ---"; grep '^FAIL' "$RESULTS" || echo "none"
} > "$RUN/summary.txt"
cat "$RUN/summary.txt"
FINAL=0; [ "$FAILS" = 0 ] || FINAL=1
echo "$FINAL" > "$RUN/final.exit"
log "W0-09A isolated validation finished: exit=$FINAL checks=$TOTAL failed=$FAILS evidence=$RUN"
exit "$FINAL"
