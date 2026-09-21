#!/usr/bin/env bash
# W0-03C — build the file set the NAS needs for the duplicate report, from ONE exact commit.
#
#   bash ops/dr/w0_03c_make_bundle.sh [<commit>] [<output dir>]
#
# Writes  w0_03c_bundle_<sha12>.tar.gz  and its  .sha256  into the output directory
# (default: ./w0_03c_bundle). Runs on the development PC; it never touches the NAS.
#
# The archive comes from `git archive` of the commit — not from the working tree — with
# line-ending conversion off, so the scripts that run on the NAS are byte-identical to
# the reviewed commit (LF, no CR). Inside, everything sits under <sha12>/:
#
#   ops/dr/w0_10a_restore_proof.sh       the W0-10A runner, with POST_VERIFY_HOOK
#   ops/dr/verify_restore.js             its verification
#   ops/dr/w0_03c_duplicate_report_hook.sh
#   ops/dr/w0_03c_export.js
#   backend/app/master_data/             the stdlib-only report
#   backend/scripts/w0_03c_master_data_uniqueness.py
#   BUNDLE_MANIFEST.txt                  commit + sha256 of every file
set -eu

COMMIT="${1:-HEAD}"
OUT_DIR="${2:-w0_03c_bundle}"
SHA="$(git rev-parse --verify "$COMMIT^{commit}")"
SHORT="${SHA:0:12}"
PATHS="ops/dr/w0_10a_restore_proof.sh ops/dr/verify_restore.js ops/dr/w0_03c_duplicate_report_hook.sh
ops/dr/w0_03c_export.js backend/app/master_data backend/scripts/w0_03c_master_data_uniqueness.py"

mkdir -p "$OUT_DIR"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

# shellcheck disable=SC2086
git -c core.autocrlf=false archive --format=tar --prefix="$SHORT/" "$SHA" $PATHS | tar -x -C "$STAGE"

if grep -rlI $'\r' "$STAGE/$SHORT" >/dev/null 2>&1; then
  echo "refusing: a file in the bundle contains CR — it would not run on the NAS" >&2
  exit 1
fi

{
  echo "W0-03C duplicate report bundle"
  echo "commit $SHA"
  echo "built  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "# sha256 of every file"
  (cd "$STAGE/$SHORT" && find . -type f ! -name BUNDLE_MANIFEST.txt | LC_ALL=C sort | xargs sha256sum)
} > "$STAGE/$SHORT/BUNDLE_MANIFEST.txt"

NAME="w0_03c_bundle_$SHORT.tar.gz"
# written from inside OUT_DIR: GNU tar would read a "C:/..." archive path as a remote host
(cd "$OUT_DIR" && tar -C "$STAGE" -czf "$NAME" "$SHORT" && sha256sum "$NAME" > "$NAME.sha256")
echo "$OUT_DIR/$NAME"
cat "$OUT_DIR/$NAME.sha256"
