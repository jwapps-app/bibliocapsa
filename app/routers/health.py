"""Health check endpoint."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from ..database import get_conn
from ..schemas import HealthResponse

router = APIRouter()


@router.get("/counts", summary="Sidebar nav counts (books, series, authors, genres, lending, wishlist)")
def nav_counts(request: Request):
    from .. import access, ttlcache, auth
    allowed = access.restriction_for_request(request)  # None = unrestricted/admin
    u = auth.authenticate_request(request)
    # Fetched on every page load. The Calibre figures are four COUNT(DISTINCT)
    # scans over the link tables (or predicate-filtered, for a member); they
    # only change when Calibre writes, so key on the database's change marker.
    key = ("counts", ttlcache.calibre_marker(), ttlcache.allowed_key(allowed), (u or {}).get("id"))
    return ttlcache.get_or_set(key, 30, lambda: _nav_counts(allowed, u))


def _nav_counts(allowed, u):
    from .. import access
    out = {"books": 0, "series": 0, "authors": 0, "genres": 0, "lending": 0, "wishlist": 0}
    try:
        with get_conn() as cal:
            if allowed is None:
                out["books"] = cal.execute("SELECT COUNT(*) FROM books").fetchone()[0]
                out["series"] = cal.execute("SELECT COUNT(DISTINCT series) FROM books_series_link").fetchone()[0]
                out["authors"] = cal.execute("SELECT COUNT(DISTINCT author) FROM books_authors_link").fetchone()[0]
                out["genres"] = cal.execute("SELECT COUNT(DISTINCT tag) FROM books_tags_link").fetchone()[0]
            else:
                pred, pp = access.calibre_predicate(allowed, "b")
                out["books"] = cal.execute(f"SELECT COUNT(*) FROM books b WHERE {pred}", pp).fetchone()[0]
                out["series"] = cal.execute(f"SELECT COUNT(DISTINCT bsl.series) FROM books_series_link bsl JOIN books b ON b.id=bsl.book WHERE {pred}", pp).fetchone()[0]
                out["authors"] = cal.execute(f"SELECT COUNT(DISTINCT bal.author) FROM books_authors_link bal JOIN books b ON b.id=bal.book WHERE {pred}", pp).fetchone()[0]
                out["genres"] = cal.execute(f"SELECT COUNT(DISTINCT btl.tag) FROM books_tags_link btl JOIN books b ON b.id=btl.book WHERE {pred}", pp).fetchone()[0]
    except Exception:
        pass
    try:
        from ..pg_database import get_pg
        pg = get_pg()
        cur = pg.cursor()
        # Native physical books count toward the library total, scoped by the
        # caller's genre restriction (same predicate the native list uses).
        nat_pred, nat_params = access.native_predicate(allowed)
        where = "(format != 'digital' OR format IS NULL)" + (f" AND {nat_pred}" if nat_pred else "")
        cur.execute(f"SELECT COUNT(*) AS c FROM native_books WHERE {where}", nat_params)
        out["books"] += cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) AS c FROM lending WHERE returned_date IS NULL")
        out["lending"] = cur.fetchone()["c"]
        if u:
            cur.execute("SELECT COUNT(*) AS c FROM wishlist WHERE user_id=%s", (u["id"],))
            out["wishlist"] = cur.fetchone()["c"]
        pg.close()
    except Exception:
        pass
    return out


@router.get("/health", response_model=HealthResponse, summary="Server health check")
def health(request: Request):
    # Public/unauthenticated (the Docker healthcheck hits this). Verify the
    # Calibre DB is reachable; return library counts ONLY to an authenticated
    # caller, so an anonymous internet visitor can't learn how many books are in
    # the library. Never surface raw error strings here.
    from .. import auth, access
    try:
        # This route is auth-exempt (the Docker healthcheck hits it), so the
        # middleware never populated request.state.user -- take the restriction
        # from the user we authenticate here, not from request.state.
        #
        # Counts are scoped to what the caller may actually see: a member limited
        # to certain genres must not be shown a total for books they can't browse
        # (these numbers drive the header and the sidebar's "Library" figure).
        user = auth.authenticate_request(request)
        allowed = access.get_restriction(user)
        # Both stores must answer. This used to return HTTP 200 with
        # status="error" when Calibre was unreadable and never looked at
        # Postgres at all, so the Docker healthcheck and any monitor saw a
        # healthy container that could not serve a single library request.
        from ..pg_database import get_pg
        pg = get_pg()
        try:
            pg.cursor().execute("SELECT 1")
        finally:
            pg.close()
        with get_conn() as conn:
            if user is None:
                conn.execute("SELECT 1").fetchone()
                return HealthResponse(status="ok", calibre_db="connected", book_count=0)
        from .. import ttlcache
        key = ("health-counts", ttlcache.calibre_marker(), ttlcache.allowed_key(allowed))
        calibre_count, native_count = ttlcache.get_or_set(key, 30, lambda: _library_counts(allowed))

        return HealthResponse(
            status="ok",
            calibre_db="connected",
            book_count=calibre_count + native_count,
            calibre_count=calibre_count,
            native_count=native_count,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("health check failed: %s", e)
        return JSONResponse(status_code=503,
                            content=HealthResponse(status="error", calibre_db="error", book_count=0).model_dump())


def _library_counts(allowed) -> tuple:
    from .. import access
    with get_conn() as conn:
        pred, pp = access.calibre_predicate(allowed, "b")
        if pred:
            calibre_count = conn.execute(f"SELECT COUNT(*) FROM books b WHERE {pred}", pp).fetchone()[0]
        else:
            calibre_count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    native_count = 0
    try:
        from ..pg_database import get_pg
        nat_pred, nat_params = access.native_predicate(allowed)
        where = "(format != 'digital' OR format IS NULL)" + (f" AND {nat_pred}" if nat_pred else "")
        pg = get_pg()
        try:
            cur = pg.cursor()
            cur.execute(f"SELECT COUNT(*) AS c FROM native_books WHERE {where}", nat_params)
            native_count = cur.fetchone()["c"]
        finally:
            pg.close()
    except Exception:
        pass
    return calibre_count, native_count
