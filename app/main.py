"""
Bibliocapsa — Self-hosted personal library system
- Read-only Calibre mirror (7,000+ ebooks)
- Native library for physical/scanned books
- Lending, family libraries, reading progress
- Full-text search inside book content
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import logging

from .database import init_db, close_db
from .routers import books, authors, series, tags, covers, sync, opds, health
from .routers import search, files, native_books, lending, reading, shelves, goodreads, settings, kosync
from .routers import auth as auth_router
from .routers import calibre_edit, webdav, stats, wishlist
from . import auth as auth_lib

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _warn_insecure_config():
    """Loud warnings for unsafe defaults — important once exposed beyond localhost."""
    if os.getenv("POSTGRES_PASSWORD", "bibliocapsa") == "bibliocapsa":
        logger.warning("⚠ SECURITY: POSTGRES_PASSWORD is the default 'bibliocapsa'. "
                       "Set a strong POSTGRES_PASSWORD before exposing this instance.")
    if os.getenv("COOKIE_SECURE", "auto").strip().lower() in ("0", "false", "no"):
        logger.warning("⚠ COOKIE_SECURE is forced off — session cookies won't be marked Secure even "
                       "over HTTPS. The default 'auto' handles this correctly; only force it if you must.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Bibliocapsa...")
    _warn_insecure_config()
    init_db()
    # PostgreSQL init (gracefully skipped if not configured)
    try:
        from .pg_database import init_postgres
        init_postgres()
    except Exception as e:
        logger.warning(f"PostgreSQL not initialized: {e}")
    yield
    close_db()
    logger.info("Bibliocapsa stopped.")


# Interactive API docs (Swagger/ReDoc/OpenAPI) are useful in dev but needless
# attack surface on a public instance — enable them only when DEBUG is on.
_DOCS_ENABLED = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")

app = FastAPI(
    title="Bibliocapsa",
    description="Your complete personal library — Calibre ebooks, physical books, lending, and more.",
    version="2.0.0",
    docs_url="/api/docs" if _DOCS_ENABLED else None,
    redoc_url="/api/redoc" if _DOCS_ENABLED else None,
    openapi_url="/api/openapi.json" if _DOCS_ENABLED else None,
    lifespan=lifespan,
)

# Same-origin by default (the web app proxies /api through Next rewrites, and
# OPDS/KOSync are native clients that don't use browser CORS). Only enable
# cross-origin if ALLOWED_ORIGINS is explicitly set — never "*" with credentials.
_cors_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

DEBUG = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")

# ── Authentication gate ─────────────────────────────────────────────────────
# Protect all data routes (/api/*, /opds/*). Exempt: the auth endpoints, the
# health check (used by Docker), CORS preflight, and the KOSync paths (which
# carry KOReader's own x-auth credentials).
from fastapi.responses import JSONResponse  # noqa: E402
from starlette.exceptions import HTTPException as _StarletteHTTPException  # noqa: E402


@app.exception_handler(_StarletteHTTPException)
async def _http_exc_handler(request, exc):
    # Pass through intentional client (4xx) messages, but scrub server-error
    # (5xx) details — those often interpolate DB/path internals (`detail=str(e)`).
    detail = exc.detail
    if exc.status_code >= 500 and not DEBUG:
        logger.warning("HTTP %s on %s: %s", exc.status_code, request.url.path, exc.detail)
        detail = "Internal server error"
    return JSONResponse(status_code=exc.status_code, content={"detail": detail},
                        headers=getattr(exc, "headers", None))


@app.exception_handler(Exception)
async def _unhandled_exc_handler(request, exc):
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# Exempt ONLY the exact KOSync/auth/health paths — not broad /users/ or /syncs/
# wildcards (a future route living under those would otherwise be silently
# unauthenticated). KOSync routes: /users/auth, /users/create, /syncs/progress
# (PUT) and /syncs/progress/{document} (GET); they carry KOReader's own x-auth.
_AUTH_EXEMPT_EXACT = {"/api/health", "/healthcheck", "/users/auth", "/users/create", "/syncs/progress"}
_AUTH_EXEMPT_PREFIXES = ("/api/auth/", "/syncs/progress/")


def _auth_exempt(path: str, method: str) -> bool:
    if method == "OPTIONS":
        return True
    if path in _AUTH_EXEMPT_EXACT or path.startswith(_AUTH_EXEMPT_PREFIXES):
        return True
    # Only the data routes are guarded; KOSync root paths fall through here.
    return not (path.startswith("/api/") or path.startswith("/opds"))


@app.middleware("http")
async def require_auth(request, call_next):
    if not _auth_exempt(request.url.path, request.method):
        user = auth_lib.authenticate_request(request)
        if not user:
            return JSONResponse(status_code=401, content={"detail": "Authentication required"})
        request.state.user = user
    return await call_next(request)

# ── Calibre mirror (read-only) ──────────────────────────────────────────────
app.include_router(health.router,       prefix="/api",               tags=["Health"])
app.include_router(books.router,        prefix="/api/books",         tags=["Books"])
app.include_router(authors.router,      prefix="/api/authors",       tags=["Authors"])
app.include_router(series.router,       prefix="/api/series",        tags=["Series"])
app.include_router(tags.router,         prefix="/api/tags",          tags=["Tags"])
app.include_router(covers.router,       prefix="/api/covers",        tags=["Covers"])
app.include_router(files.router,        prefix="/api/books",         tags=["Files"])
app.include_router(sync.router,         prefix="/api/sync",          tags=["Sync"])
app.include_router(search.router,       prefix="/api/search",        tags=["Full-Text Search"])
app.include_router(opds.router,         prefix="/opds",              tags=["OPDS"])

# ── Native library (read-write, PostgreSQL) ─────────────────────────────────
app.include_router(native_books.router, prefix="/api/native/books",  tags=["Native Library"])
app.include_router(lending.router,      prefix="/api/lending",       tags=["Lending"])
app.include_router(reading.router,      prefix="/api/reading",       tags=["Reading Progress"])
app.include_router(shelves.router,      prefix="/api/shelves",       tags=["Shelves"])
app.include_router(goodreads.router,    prefix="/api/goodreads",     tags=["Goodreads"])
app.include_router(settings.router,     prefix="/api/settings",      tags=["Settings"])
app.include_router(auth_router.router,   prefix="/api/auth",          tags=["Auth"])
app.include_router(calibre_edit.router,  prefix="/api/calibre",       tags=["Calibre Edits"])
app.include_router(stats.router,         prefix="/api/stats",         tags=["Reading Statistics"])
app.include_router(wishlist.router,      prefix="/api/wishlist",      tags=["Want to Read"])

# ── KOReader sync server (KOSync protocol) ──────────────────────────────────
# Mounted at ROOT (no prefix) so devices can use the same base URL as the app.
# The Next.js front-end rewrites /healthcheck, /users/* and /syncs/* here too.
app.include_router(kosync.router,                                     tags=["KOSync"])

# WebDAV for KOReader statistics cloud-sync (auth-exempt at the middleware level;
# the router does its own HTTP Basic auth). Reachable at <base>/dav.
app.include_router(webdav.router,        prefix="/dav",               tags=["WebDAV"])

# Web UI is served by the Next.js standalone container on port 3001
