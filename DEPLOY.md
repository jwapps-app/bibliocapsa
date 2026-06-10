# Deploying Bibliocapsa from pre-built images (GHCR)

Build the images once on a dev machine, push to GitHub Container Registry, and
have each host (NAS, server, …) just **pull** them. No source, no on-host build.

GHCR packages are **private by default**, so this is private until you choose to
make a package public (GitHub → your profile → Packages → the package →
Package settings → Change visibility).

---

## One-time setup

### 1. Create a GitHub token
GitHub → Settings → Developer settings → **Personal access tokens (classic)** →
Generate new token. Scopes: **`write:packages`** and **`read:packages`**
(`read:packages` alone is enough on hosts that only pull). Copy the token.

### 2. Log in to GHCR (on the build machine AND each host)
```bash
docker login ghcr.io
#   Username: <your GitHub username>
#   Password: <the token from step 1>
```

---

## Build & push (on your Mac)
```bash
GHCR_USER=<your-github-username-lowercase> ./build.sh 1.0
```
- Builds `bibliocapsa-backend` and `bibliocapsa-web` for `linux/amd64` (the NAS).
  To also build for ARM hosts: `PLATFORMS=linux/amd64,linux/arm64 GHCR_USER=… ./build.sh 1.0`.
- The first build is slow (Calibre bundle + a cross-arch web build); later builds reuse cache.
- Bump the version each release (`1.0`, `1.1`, …); `latest` is also updated.

---

## Deploy on a host (e.g. the NAS)
Copy just three files to the host (e.g. `/volume1/docker/bibliocapsa/`):
`docker-compose.prod.yml`, `Caddyfile`, and a `.env`.

`.env` needs at least:
```env
GHCR_USER=<your-github-username-lowercase>
VERSION=1.0                       # or omit for 'latest'
CALIBRE_LIBRARY_PATH=/volume1/docker/calibre-library
POSTGRES_PASSWORD=<a-strong-password>
PROXY_PORT=8090                   # the one port you expose / point Cloudflare at
# PORT=8010  WEB_PORT=3001        # only if those collide with other containers
# COOKIE_SECURE defaults to 'auto' (Secure over HTTPS, fine over http://ip)
```
Then:
```bash
docker login ghcr.io                                   # one-time
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```
Open `http://<host>:8090`, create the first (admin) account.

---

## Updating a host (this is the whole point)
After you `./build.sh <new-version>` on the Mac, on the host:
```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```
Schema migrations run automatically on startup. ~30 seconds, no rebuild, no tarball.
