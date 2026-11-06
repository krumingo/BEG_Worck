#!/usr/bin/env bash
# CLAUDE AUDIT probe RC-01/P1: does write_build_info.py stamp a build context with a commit
# that is NOT what the context holds? Usage: probe_rc01_write_build_info.sh <path to PR worktree>
set -u
W="$1"; T=$(mktemp -d); cd "$T"
git init -q r && cd r && git config user.email a@b && git config user.name a
mkdir backend frontend && echo one > backend/x && git add -A && git commit -qm one
A=$(git rev-parse HEAD)
echo two > backend/x && git commit -qam two
B=$(git rev-parse HEAD)
git checkout -q "$A"                       # working tree = commit A
python3 "$W/ops/release/write_build_info.py" --repo . --commit "$B" >/dev/null 2>&1; rc=$?
got=$(python3 -c 'import json;print(json.load(open("backend/BUILD_INFO.json"))["build_sha"])' 2>/dev/null)
echo "tree=A=${A:0:12} requested=B=${B:0:12} exit=$rc stamped=${got:0:12}"
if [ "$rc" = 0 ] && [ "$got" = "$B" ]; then echo "P1 FAIL: tree holds A but is stamped B"; else echo "P1 PASS"; fi
# P1b: dirty tree, ref spelled differently from the resolved HEAD (HEAD vs branch name)
git checkout -q -B main "$B"; echo dirty > backend/x
python3 "$W/ops/release/write_build_info.py" --repo . --commit main >/dev/null 2>&1; rc=$?
echo "P1b dirty tree --commit main exit=$rc ($( [ $rc = 0 ] && echo FAIL || echo PASS ))"
