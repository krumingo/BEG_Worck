#!/usr/bin/env bash
# Usage: setup.sh <worktree of the LAB-02 head> — clean stack (Permission Service mode off, the product default)
set -euo pipefail
WT="$(cd "${1:?worktree}" && pwd)"; HERE="$(cd "$(dirname "$0")" && pwd)"
"$HERE/../runner/start_stack.sh" "$WT"
echo "setup done (seeding is done by LAB-02.js through the API + a few synthetic direct inserts)"
