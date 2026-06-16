#!/usr/bin/env bash
# Build & push Bibliocapsa images to GitHub Container Registry (GHCR).
#
#   GHCR_USER=<your-github-username-lowercase> ./build.sh [version]
#   e.g.  GHCR_USER=yourname ./build.sh 1.0
#
# First run only: docker login ghcr.io  (username = GitHub user, password = a
# Personal Access Token with write:packages). See DEPLOY.md.
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

echo "→ Building ${REG}/bibliocapsa-{backend,web}:${VERSION}  [${PLATFORMS}]"

# Multi-arch-capable builder (created once, reused after).
docker buildx inspect bibliocapsa-builder >/dev/null 2>&1 \
  || docker buildx create --name bibliocapsa-builder
docker buildx use bibliocapsa-builder

# Backend (build context = repo root; the Calibre bundle makes this the slow one)
docker buildx build --platform "${PLATFORMS}" \
  -t "${REG}/bibliocapsa-backend:${VERSION}" \
  -t "${REG}/bibliocapsa-backend:latest" \
  --push .

# Web (build context = ./web) — version is read from package.json at build time
docker buildx build --platform "${PLATFORMS}" \
  -t "${REG}/bibliocapsa-web:${VERSION}" \
  -t "${REG}/bibliocapsa-web:latest" \
  --push ./web

# Proxy (Caddy + baked-in Caddyfile, so the deploy stack needs no host files)
docker buildx build --platform "${PLATFORMS}" \
  -t "${REG}/bibliocapsa-proxy:${VERSION}" \
  -t "${REG}/bibliocapsa-proxy:latest" \
  -f Dockerfile.proxy --push .

echo "✓ Pushed ${REG}/bibliocapsa-{backend,web,proxy}:${VERSION}"
