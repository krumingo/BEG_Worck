#!/usr/bin/env bash
# CLAUDE AUDIT probe RC-01-C01: bypass attempts against the HEAD==commit check.
# Usage: probe_rc01_c01.sh <PR worktree>
set -u; W="$1"; T=$(mktemp -d); cd "$T"
git init -q r && cd r && git config user.email a@b && git config user.name a
mkdir backend frontend && echo 1 > backend/x && git add -A && git commit -qm one; A=$(git rev-parse HEAD)
echo 2 > backend/x && git commit -qam two; B=$(git rev-parse HEAD)
run(){ python3 "$W/ops/release/write_build_info.py" "$@" >/dev/null 2>&1; echo $?; }
f=0
# a) --repo at B, --target = a plain copy of tree A (not git) → must refuse
git worktree add -q ../wtA "$A"; cp -r ../wtA ../plainA; rm -rf ../plainA/.git
[ "$(run --repo . --commit "$B" --target ../plainA)" = 2 ] || { echo "a FAIL plain dir stamped"; f=1; }
# b) --repo at B, --target = linked worktree at A → must refuse
[ "$(run --repo . --commit "$B" --target ../wtA)" = 2 ] || { echo "b FAIL worktree A stamped B"; f=1; }
# c) --target = subdirectory of a repo at B (not toplevel) → must refuse
[ "$(run --repo . --commit "$B" --target backend)" = 2 ] || { echo "c FAIL subdir accepted"; f=1; }
# d) --allow-dirty must NOT allow another commit
git checkout -q "$A"; [ "$(run --repo . --commit "$B" --allow-dirty)" = 2 ] || { echo "d FAIL allow-dirty bypass"; f=1; }
# e) positive: tree at B, --commit B → 0 and stamped B
git checkout -q "$B"; [ "$(run --repo . --commit "$B")" = 0 ] && grep -q "$B" backend/BUILD_INFO.json || { echo "e FAIL positive"; f=1; }
# f) refusal writes nothing: remove files, refuse, check absent
rm -f backend/BUILD_INFO.json frontend/BUILD_INFO.json; git checkout -q "$A"
run --repo . --commit "$B" >/dev/null; [ ! -e backend/BUILD_INFO.json ] && [ ! -e backend/BUILD_INFO.json.tmp ] || { echo "f FAIL wrote on refusal"; f=1; }
[ $f = 0 ] && echo "RC-01-C01 probes PASS" || echo "RC-01-C01 probes FAIL"
