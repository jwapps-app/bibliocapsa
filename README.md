# Bibliocapsa

**Your whole library — digital *and* physical — in one private, self-hosted home, with the deepest KOReader integration anywhere.**

🌐 **[bibliocapsa.app](https://bibliocapsa.app)** · self-hosted · AGPLv3

Bibliocapsa sits on top of your existing [Calibre](https://calibre-ebook.com/) library (read-only by default — it never touches your files unless you deliberately push a change back) and adds a modern multi-user web experience, physical-book tracking, and a complete, built-in KOReader stack. It runs in Docker on your own hardware, so your reading life stays private, ad-free, and entirely yours.

> _Screenshots go here._

---

## Why it's different

- **One library for everything you own** — ebooks from Calibre *and* the paper books on your shelves, unified, filterable, and searchable together. Read/Unread and "Date Read" span both formats as a single concept.
- **The complete KOReader experience, built in** — catalog (OPDS), reading-position sync (KOSync), *and* reading-statistics sync (WebDAV) — all native, all behind one account and one URL. No pile of half-maintained side services.
- **Built for a household** — individual accounts with optional per-member genre restrictions; everyone keeps their own history, ratings, shelves, and stats.
- **You own your data** — positions, statistics, ratings, and history live on *your* server. Nothing mined, nothing sold.
- **Respects your setup** — Calibre is opened read-only; edits are staged and only written back through a deliberate, confirmed sync.

## Feature highlights

- Cover-forward, responsive grid; browse by series, author, or genre; six themes
- **Full-text search inside your books' content** + in-browser EPUB/PDF readers
- Physical books as first-class citizens — manual add or Goodreads CSV import, auto-generated covers, shelf location, lending tracker
- Per-user read history, reading goals, year-in-review, want-to-read list
- Automatic metadata & cover enrichment (Open Library, optional Hardcover)
- Calibre custom-column support, edited in-app and synced back on your terms

See [ABOUT.md](ABOUT.md) for the full tour.

---

## Quick start

**Requirements:** Docker + Docker Compose, and an existing Calibre library folder.

```bash
git clone https://github.com/jwapps-app/bibliocapsa.git
cd bibliocapsa
cp .env.example .env
#   → edit .env: set CALIBRE_LIBRARY_PATH to your Calibre folder
#                set a strong POSTGRES_PASSWORD
docker compose up -d
```

Open **http://localhost:8090** and create your admin account on first run.

> ⚠️ **Create your admin account before exposing the instance.** The first account to
> register becomes the admin, with no password challenge. Register it locally (on your
> LAN) *before* you attach a Cloudflare Tunnel or forward a port — or set `SETUP_TOKEN`
> in `.env` so only you can claim that first account.

`:8090` is the single front door (a Caddy proxy that serves the web UI and routes the
API, OPDS, and KOReader sync on one port — **point your reverse proxy / Cloudflare at
only this port**). When you build from source, the web UI and API are also bound to
`:3001`/`:8000` for local development — don't forward those to the internet. (The
pre-built **[DEPLOY.md](DEPLOY.md)** images publish *only* the proxy port.)

> **Prefer pre-built images** (no local build)? See **[DEPLOY.md](DEPLOY.md)** for the
> image-based compose — ideal for a NAS / Portainer.

## Configuration

All settings live in `.env` (see `.env.example` for the annotated list). The essentials:

| Variable | What it is |
|---|---|
| `CALIBRE_LIBRARY_PATH` | Host path to your Calibre library (the folder with `metadata.db`) |
| `POSTGRES_PASSWORD` | **Set a strong value.** App data (accounts, progress, shelves) lives in Postgres |
| `COOKIE_SECURE` | `auto` (default) — Secure cookie over HTTPS, fine over plain http on a LAN |
| `ALLOWED_ORIGINS` | Leave empty for the normal same-origin setup |

## KOReader setup

Point KOReader at your Bibliocapsa address with your account credentials:
- **OPDS catalog** → `http(s)://<host>/opds`
- **Progress sync (KOSync)** → the same base URL
- **Statistics (WebDAV)** → `http(s)://<host>/dav`

One account, one address — catalog, sync, and stats all just work.

> **A note on position sync:** your place in a book syncs *exactly* between KOReader
> devices, and between browser sessions. When you switch *between* the in-browser reader
> and KOReader, it resumes at the **nearest chapter** — the two readers track position
> differently, so this is the reliable common ground.

---

## License

Bibliocapsa is licensed under the **GNU Affero General Public License v3.0** — see [LICENSE](LICENSE).
You're free to use, study, modify, and share it; derivative works — including modified versions offered over a network — must remain open under the same license.
