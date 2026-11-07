#!/usr/bin/env bash
# ST-02 — SANDBOX ONLY. Never on Synology, never for production or a real release.
#
# The Claude Code cloud container that runs the ST-02 rehearsal cannot build the production
# Dockerfiles against the official base images:
#   * Docker Hub answers 429 (rate limit)            -> official images come from mirror.gcr.io;
#   * egress TLS is re-terminated by the session proxy -> pip/yarn inside a build need its CA;
#   * Debian apt mirrors are not reachable             -> `apt-get install build-essential curl`
#     in Dockerfile.backend cannot download anything.
#
# This script makes LOCAL images under the tags the Dockerfiles name (python:3.11-slim,
# node:20-alpine, nginx:alpine) so that the byte-identical production Dockerfiles build here:
#   python:3.11-slim  := official python:3.11 (full Debian image: gcc/g++/make/libc6-dev/curl
#                        already installed) + session CA + PIP_CERT + a local `build-essential`
#                        metapackage that only depends on that installed toolchain
#   node:20-alpine    := official node:20-alpine + session CA + NODE_EXTRA_CA_CERTS
#   nginx:alpine      := official nginx:alpine (re-tagged, unchanged)
# The resulting image IDs and their parents are written to --report. They are NOT the images a
# Synology build uses; the rehearsal proves deploy/smoke/exact-image-rollback mechanics, not the
# production base images.
#
#   bash ops/staging/sandbox-base/prepare_sandbox_base_images.sh --sandbox --ca /root/.ccr/ca-bundle.crt --report <file>
set -euo pipefail
CA=""; REPORT=""; SANDBOX=0
MIRROR="${SANDBOX_IMAGE_MIRROR:-mirror.gcr.io/library}"
while [ $# -gt 0 ]; do
  case "$1" in
    --sandbox) SANDBOX=1 ;;
    --ca) CA="$2"; shift ;;
    --report) REPORT="$2"; shift ;;
    *) echo "usage: $0 --sandbox --ca <pem bundle> --report <file>" >&2; exit 3 ;;
  esac; shift
done
[ "$SANDBOX" = 1 ] || { echo "refused: pass --sandbox (this script only exists for the cloud rehearsal container)" >&2; exit 2; }
[ ! -e /volume1 ] || { echo "refused: /volume1 exists (Synology). Never replace base images there." >&2; exit 2; }
[ -n "$CA" ] && [ -f "$CA" ] || { echo "refused: --ca <pem bundle> is required" >&2; exit 2; }
[ -n "$REPORT" ] || { echo "refused: --report <file> is required" >&2; exit 2; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
cp "$CA" "$WORK/sandbox-ca.crt"
for img in python:3.11 python:3.11-slim node:20-alpine nginx:alpine; do
  docker image inspect "$MIRROR/$img" >/dev/null 2>&1 || docker pull -q "$MIRROR/$img" >/dev/null
done

mkdir -p "$WORK/py" "$WORK/node"
cp "$WORK/sandbox-ca.crt" "$WORK/py/"; cp "$WORK/sandbox-ca.crt" "$WORK/node/"
cat > "$WORK/py/Dockerfile" <<DOCKER
FROM $MIRROR/python:3.11
COPY sandbox-ca.crt /usr/local/share/ca-certificates/st02-sandbox-ca.crt
RUN update-ca-certificates >/dev/null \\
 && mkdir -p /tmp/be/DEBIAN \\
 && printf 'Package: build-essential\nVersion: 12.12~st02sandbox\nArchitecture: all\nMaintainer: ST-02 sandbox <st02@sandbox.test>\nDepends: gcc, g++, make, libc6-dev, dpkg-dev\nDescription: ST-02 sandbox stand-in; depends only on the toolchain of the official image\n' > /tmp/be/DEBIAN/control \\
 && dpkg-deb --build /tmp/be /tmp/build-essential.deb >/dev/null && dpkg -i /tmp/build-essential.deb >/dev/null \\
 && rm -rf /tmp/be /tmp/build-essential.deb /var/lib/apt/lists/*
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt
LABEL org.begwork.st02.sandbox-base="python:3.11-slim stand-in; NOT for Synology/production"
DOCKER
cat > "$WORK/node/Dockerfile" <<DOCKER
FROM $MIRROR/node:20-alpine
COPY sandbox-ca.crt /usr/local/share/st02-sandbox-ca.crt
ENV NODE_EXTRA_CA_CERTS=/usr/local/share/st02-sandbox-ca.crt
LABEL org.begwork.st02.sandbox-base="node:20-alpine + sandbox CA; NOT for Synology/production"
DOCKER
docker build -q -t python:3.11-slim "$WORK/py" >/dev/null
docker build -q -t node:20-alpine "$WORK/node" >/dev/null
docker tag "$MIRROR/nginx:alpine" nginx:alpine

{
  echo "# ST-02 sandbox base images (cloud container only; NOT Synology/production)"
  for pair in "python:3.11-slim=$MIRROR/python:3.11" "node:20-alpine=$MIRROR/node:20-alpine" "nginx:alpine=$MIRROR/nginx:alpine"; do
    tag="${pair%%=*}"; parent="${pair#*=}"
    printf '%s id=%s parent=%s parent_id=%s parent_digest=%s\n' "$tag" \
      "$(docker image inspect -f '{{.Id}}' "$tag")" "$parent" \
      "$(docker image inspect -f '{{.Id}}' "$parent")" \
      "$(docker image inspect -f '{{join .RepoDigests ","}}' "$parent")"
  done
} > "$REPORT"
cat "$REPORT"
