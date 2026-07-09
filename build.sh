#!/usr/bin/env bash
# MANUAL FALLBACK — images normally publish via GitHub Actions.
# ============================================================================
# Since v1.18.0, .github/workflows/build.yml builds and pushes all three images
# from CI on every push to main / v* tag. That is the primary path: a git push
# ships a release and nothing here needs to run.
#
# This script stays only as an escape hatch (e.g. CI is down and you must
# publish from a workstation). It needs a `docker login ghcr.io` with a
# write:packages PAT — which this machine normally does NOT have, since the
# shared ghcr.io credential is a read:packages token used for pulling. Expect a
# `denied: write_package` unless you re-login first. Prefer CI.
# ============================================================================
#
#   GHCR_USER=<your-github-username-lowercase> ./build.sh [version] [images…]
#   e.g.  GHCR_USER=yourname ./build.sh 1.0            # all three images
#         GHCR_USER=yourname ./build.sh 1.0 web        # web only
#         GHCR_USER=yourname ./build.sh 1.0 backend web
#
# Building only what changed matters: a web-only release doesn't need the
# backend image (whose calibre layer, if the buildx cache ever evicts it, takes
# 15-40 min to rebuild under amd64 emulation on Apple Silicon).
set -euo pipefail

GHCR_USER="${GHCR_USER:?Set GHCR_USER to your lowercase GitHub username}"
# Default the version from web/package.json (single source of truth — same value
# the UI shows). Override with an explicit arg if needed.
VERSION="${1:-$(python3 -c "import json;print(json.load(open('web/package.json'))['version'])" 2>/dev/null || echo latest)}"
# Multi-arch by default so the same :latest tag runs natively on both x86_64
# hosts (amd64) and Apple-Silicon / ARM hosts (arm64) — no emulation, and no
# "repull didn't update" surprises from single-arch manifests. Override to build
# a single arch (faster) with e.g. PLATFORMS=linux/arm64 ./build.sh
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
REG="ghcr.io/${GHCR_USER}"

# Which images to build: args after the version, defaulting to all three.
shift $(( $# > 0 ? 1 : 0 ))
IMAGES="${*:-backend web proxy}"

echo "→ Building ${REG}/bibliocapsa-{${IMAGES// /,}}:${VERSION}  [${PLATFORMS}]"

# Multi-arch-capable builder (created once, reused after).
docker buildx inspect bibliocapsa-builder >/dev/null 2>&1 \
  || docker buildx create --name bibliocapsa-builder
docker buildx use bibliocapsa-builder

for img in ${IMAGES}; do
  case "${img}" in
    backend)  # build context = repo root; the Calibre bundle makes this the slow one
      docker buildx build --platform "${PLATFORMS}" \
        -t "${REG}/bibliocapsa-backend:${VERSION}" \
        -t "${REG}/bibliocapsa-backend:latest" \
        --push . ;;
    web)      # build context = ./web — version is read from package.json at build time
      docker buildx build --platform "${PLATFORMS}" \
        -t "${REG}/bibliocapsa-web:${VERSION}" \
        -t "${REG}/bibliocapsa-web:latest" \
        --push ./web ;;
    proxy)    # Caddy + baked-in Caddyfile, so the deploy stack needs no host files
      docker buildx build --platform "${PLATFORMS}" \
        -t "${REG}/bibliocapsa-proxy:${VERSION}" \
        -t "${REG}/bibliocapsa-proxy:latest" \
        -f Dockerfile.proxy --push . ;;
    *) echo "unknown image: ${img} (expected backend|web|proxy)"; exit 1 ;;
  esac
done

echo "✓ Pushed ${REG}/bibliocapsa-{${IMAGES// /,}}:${VERSION}"
