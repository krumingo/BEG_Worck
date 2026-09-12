#!/usr/bin/env bash
# Explicit isolated validation only. Run on Synology ONLY after Krum authorizes it.
# Usage: bash w0_02_validate_synology.sh /volume1/docker/begwork/w002_val_<...> FULL_SHA
set -Eeuo pipefail
umask 077
[[ $# == 2 ]] || { echo "Usage: $0 SNAPSHOT_PARENT FULL_SHA" >&2; exit 2; }
PARENT=$(cd -- "$1" && pwd -P)
SHA=$2
[[ $SHA =~ ^[0-9a-f]{40}$ ]] || { echo "Need full SHA" >&2; exit 2; }
# Override exists only to allow LOCAL fake-docker tests in a temporary directory.
BASE=${W002_VALIDATION_ROOT:-/volume1/docker/begwork}
BASE=$(cd -- "$BASE" && pwd -P)
[[ $PARENT == "$BASE"/w002_val_* && $PARENT != *:* ]] || { echo "Unapproved source path" >&2; exit 2; }
[[ -f $PARENT/COMMIT && $(cat "$PARENT/COMMIT") == "$SHA" ]] || { echo "Commit mismatch" >&2; exit 2; }
[[ -f $PARENT/code/backend/scripts/w0_02_validation_run.py ]] || exit 2
RUN_ID="w002-${SHA:0:12}-$(date -u +%Y%m%dT%H%M%SZ)-$$"
EVID="$BASE/${RUN_ID}-evidence"
mkdir -- "$EVID" # atomic: refuse an existing directory
CONTAINERS=(); VOLUMES=(); NETWORKS=()
LABEL="begwork.w002.run=$RUN_ID"

# Do not infer 'absent' from any arbitrary docker error. A successful inventory
# command must prove absence; daemon/access errors are cleanup failures.
present() {
  local kind=$1 id=$2 listing
  case $kind in
    container) listing=$(docker container ls -a -q --no-trunc) || return 2 ;;
    volume) listing=$(docker volume ls -q) || return 2 ;;
    network) listing=$(docker network ls -q --no-trunc) || return 2 ;;
    *) return 2 ;;
  esac
  [[ $'\n'"$listing"$'\n' == *$'\n'"$id"$'\n'* ]]
}
remove_owned() {
  local kind=$1 id=$2 status owner template
  if present "$kind" "$id"; then
    if [[ $kind == container ]]; then template='{{index .Config.Labels "begwork.w002.run"}}';
    else template='{{index .Labels "begwork.w002.run"}}'; fi
    owner=$(docker "$kind" inspect --format "$template" "$id") || return 1
    [[ $owner == "$RUN_ID" ]] || { echo "Refuse cleanup of foreign $kind $id"; return 1; }
    if [[ $kind == container ]]; then docker container rm -f -v "$id" || return 1;
    else docker "$kind" rm "$id" || return 1; fi
  else
    status=$?; [[ $status == 1 ]] || return 1
  fi
  if present "$kind" "$id"; then return 1; else status=$?; [[ $status == 1 ]]; fi
}
cleanup() {
  local original=$? failed=0 id
  trap - EXIT INT TERM
  set +e
  for id in "${CONTAINERS[@]}"; do remove_owned container "$id" >>"$EVID/cleanup.log" 2>&1 || failed=1; done
  for id in "${VOLUMES[@]}"; do remove_owned volume "$id" >>"$EVID/cleanup.log" 2>&1 || failed=1; done
  for id in "${NETWORKS[@]}"; do remove_owned network "$id" >>"$EVID/cleanup.log" 2>&1 || failed=1; done
  printf 'original_exit=%s\ncleanup_failed=%s\n' "$original" "$failed" >>"$EVID/cleanup.log"
  [[ $original != 0 || $failed == 0 ]] || original=70
  printf '%s\n' "$original" >"$EVID/final.exit"
  echo "Validation finished: exit=$original; evidence=$EVID"
  # Intentionally retain the source snapshot and images. No rm -rf/prune/image rm.
  exit "$original"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
create_container() {
  local key=$1; shift
  NEW_CID=$(docker create --name "$RUN_ID-$key" --label "$LABEL" "$@")
  [[ $NEW_CID =~ ^[0-9a-f]{64}$ ]] || { echo "Invalid container ID"; exit 2; }
  CONTAINERS+=("$NEW_CID")
  printf 'container\t%s\t%s\n' "$key" "$NEW_CID" >>"$EVID/resources.tsv"
}
run_container() {
  local cid=$1 log=$2 cli=0 state code
  docker start -a "$cid" >"$EVID/$log" 2>&1 || cli=$?
  state=$(docker container inspect --format '{{.State.Running}}' "$cid")
  code=$(docker container inspect --format '{{.State.ExitCode}}' "$cid")
  [[ $state == false && $code =~ ^[0-9]+$ ]] || { echo "Unknown container result"; return 2; }
  printf '\ncli_exit=%s container_exit=%s\n' "$cli" "$code" >>"$EVID/$log"
  [[ $cli == 0 ]] || return "$cli"
  return "$code" # never lose the status through tee/echo
}
new_volume() {
  local name="$RUN_ID-$1" listing
  listing=$(docker volume ls --format '{{.Name}}')
  [[ $'\n'"$listing"$'\n' != *$'\n'"$name"$'\n'* ]] || { echo "Pre-existing volume"; exit 2; }
  NEW_VOLUME=$(docker volume create --label "$LABEL" "$name")
  [[ $NEW_VOLUME == "$name" ]] || exit 2
  VOLUMES+=("$NEW_VOLUME")
  printf 'volume\t%s\n' "$NEW_VOLUME" >>"$EVID/resources.tsv"
}

docker version >"$EVID/docker.version" 2>&1
# Resolve mutable tags ONCE; use returned immutable image IDs for this run.
# Mongo 7 is the agreed test major, NOT proof of matching production patch version.
docker pull "${W002_MONGO_IMAGE:-mongo:7}" >"$EVID/mongo.pull.log" 2>&1
docker pull python:3.11-slim >"$EVID/python.pull.log" 2>&1
MONGO_IMAGE=$(docker image inspect --format '{{.Id}}' "${W002_MONGO_IMAGE:-mongo:7}")
PYTHON_IMAGE=$(docker image inspect --format '{{.Id}}' python:3.11-slim)
printf 'commit=%s\nmongo=%s\npython=%s\n' "$SHA" "$MONGO_IMAGE" "$PYTHON_IMAGE" >"$EVID/versions.txt"
create_container scan --network none --mount "type=bind,src=$PARENT,dst=/snapshot,readonly" \
  "$PYTHON_IMAGE" python /snapshot/code/backend/scripts/w0_02_validation_snapshot.py /snapshot "$SHA"
run_container "$NEW_CID" snapshot-check.log

# Install dependencies BEFORE connecting a runtime to the isolated DB network.
new_volume deps; DEPS=$NEW_VOLUME
create_container deps --mount "type=bind,src=$PARENT/code,dst=/code,readonly" \
  --mount "type=volume,src=$DEPS,dst=/venv" "$PYTHON_IMAGE" bash -ec '
    python -m venv /venv
    /venv/bin/python -m pip install -r /code/backend/requirements.txt -r /code/backend/requirements-dev.txt
    /venv/bin/python --version
    /venv/bin/python -m pip freeze
  '
run_container "$NEW_CID" dependencies.log

NET=$(docker network create --internal --label "$LABEL" "$RUN_ID-net")
NETWORKS+=("$NET"); printf 'network\t%s\n' "$NET" >>"$EVID/resources.tsv"
new_volume db; DBVOL=$NEW_VOLUME
new_volume configdb; CONFIGVOL=$NEW_VOLUME
create_container mongo --network "$NET" --network-alias begwork-w002-testmongo \
  --mount "type=volume,src=$DBVOL,dst=/data/db" --mount "type=volume,src=$CONFIGVOL,dst=/data/configdb" "$MONGO_IMAGE"
MONGO=$NEW_CID
docker start "$MONGO" >>"$EVID/mongo.start.log"
ready=0
for ((attempt=0; attempt<60; attempt++)); do
  if docker exec "$MONGO" mongosh 'mongodb://127.0.0.1:27017/?serverSelectionTimeoutMS=1000' --quiet \
       --eval 'quit(db.runCommand({ping:1}).ok === 1 ? 0 : 1)' >>"$EVID/mongo.readiness.log" 2>&1; then ready=1; break; fi
  sleep 1
done
[[ $ready == 1 ]] || { echo "Mongo did not become ready"; exit 2; }
docker exec "$MONGO" mongosh --quiet --eval 'db.version()' >"$EVID/mongo.version"
create_container test --network "$NET" --mount "type=bind,src=$PARENT/code,dst=/code,readonly" \
  --mount "type=bind,src=$EVID,dst=/evidence" --mount "type=volume,src=$DEPS,dst=/venv,readonly" \
  -e MONGO_URL=mongodb://begwork-w002-testmongo:27017 -e DB_NAME=w002_op_test -e BEG_SYSTEM_DB=w002_sys_test \
  -e BEG_VALIDATION_MODE=1 -e W0_02_VALIDATION=1 -e PYTHONDONTWRITEBYTECODE=1 -e PYTHON_DOTENV_DISABLED=1 \
  "$PYTHON_IMAGE" /venv/bin/python /code/backend/scripts/w0_02_validation_run.py --only all --evidence /evidence/runner
if run_container "$NEW_CID" runner.log; then rc=0; else rc=$?; fi
docker logs "$MONGO" >"$EVID/mongo.log" 2>&1 || { [[ $rc != 0 ]] || rc=71; }
exit "$rc"
