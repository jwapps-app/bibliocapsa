# Deploying Bibliocapsa (pre-built images)

The fastest way to run Bibliocapsa: pull the public images, set three values, and start —
no source checkout, no on-host build. Ideal for a NAS (Synology/Portainer/Unraid) or any
Docker host.

> Prefer to build from source instead? See the **Quick start** in the [README](README.md)
> (`git clone` → `docker compose up -d`).

---

## 1. Get the compose file
Grab **`docker-compose.prod.yml`** from this repo (copy its contents, or download the file).
Every service — including the reverse proxy — runs from a published image; the only host
path you provide is your Calibre library.

## 2. Create the data folders
Bibliocapsa keeps its data in a folder you choose (so it's visible and backup-able). Create
it and its subfolders first — most Docker hosts don't auto-create bind-mount paths:
```bash
sudo mkdir -p /your/data/path/db /your/data/path/covers /your/data/path/uploads /your/data/path/webdav /your/data/path/caddy
```
(On Synology, for example, use `/volume1/docker/bibliocapsa` as the base.)

## 3. Set the environment variables
Use a `.env` file next to the compose, or — in Portainer — the stack's **Environment
variables**. Required:
```env
CALIBRE_LIBRARY_PATH=/path/to/your/calibre/library   # the folder containing metadata.db
DATA_PATH=/your/data/path                            # the folder from step 2
POSTGRES_PASSWORD=a-long-random-password
```
Optional (sensible defaults shown): `PROXY_PORT=8090`, `PORT=8000`, `WEB_PORT=3001`,
`COOKIE_SECURE=auto`, `VERSION=latest`.

## 4. Deploy
**Portainer:** Stacks → Add stack → paste `docker-compose.prod.yml` → add the env vars → **Deploy**.

**CLI:**
```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

Open **`http://<host>:8090`** and create the first (admin) account. Point your reverse proxy
or Cloudflare Tunnel at that single port.

## Updating
```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```
Schema migrations run automatically on startup — ~30 seconds, no rebuild.

---

## (Maintainers / forks) Building & publishing your own images
The official images live at `ghcr.io/jwapps-app/bibliocapsa-*`. To build and publish your
own — e.g. for a fork — on a machine with Docker buildx:
```bash
docker login ghcr.io                       # username + a token with write:packages
GHCR_USER=<your-org-or-user> ./build.sh     # version is read from web/package.json
```
Multi-arch: `PLATFORMS=linux/amd64,linux/arm64 GHCR_USER=… ./build.sh`.
Then deploy with `GHCR_USER=<your-org-or-user>` set, so the compose pulls *your* images.
