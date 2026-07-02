"""Health check endpoint."""

from fastapi import APIRouter, Request
from ..database import get_conn
from ..schemas import HealthResponse

router = APIRouter()


@router.get("/counts", summary="Sidebar nav counts (books, series, authors, genres, lending, wishlist)")
def nav_counts(request: Request):
    from .. import access
    out = {"books": 0, "series": 0, "authors": 0, "genres": 0, "lending": 0, "wishlist": 0}
    allowed = access.restriction_for_request(request)  # None = unrestricted/admin
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
        from ..pg_database import get_database_url
        import psycopg2
        from psycopg2.extras import RealDictCursor
        from .. import auth
        from ..pg_database import get_pg
        pg = get_pg()
        cur = pg.cursor()
        # Native physical books count toward the library total (no genre restriction
        # on native books in this build).
        nat_pred, nat_params = access.native_predicate(allowed)
        where = "(format != 'digital' OR format IS NULL)" + (f" AND {nat_pred}" if nat_pred else "")
        cur.execute(f"SELECT COUNT(*) AS c FROM native_books WHERE {where}", nat_params)
        out["books"] += cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) AS c FROM lending WHERE returned_date IS NULL")
        out["lending"] = cur.fetchone()["c"]
        u = auth.authenticate_request(request)
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
    from .. import auth
    try:
        with get_conn() as conn:
            if auth.authenticate_request(request) is None:
                conn.execute("SELECT 1").fetchone()
                return HealthResponse(status="ok", calibre_db="connected", book_count=0)
            calibre_count = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]

        native_count = 0
        try:
            from ..pg_database import get_database_url
            import psycopg2
            pg = psycopg2.connect(get_database_url())
            cur = pg.cursor()
            cur.execute("SELECT COUNT(*) FROM native_books WHERE format != 'digital' OR format IS NULL")
            native_count = cur.fetchone()[0]
            pg.close()
        except Exception:
            pass

        return HealthResponse(
            status="ok",
            calibre_db="connected",
            book_count=calibre_count + native_count,
            calibre_count=calibre_count,
            native_count=native_count,
        )
    except Exception:
        return HealthResponse(status="error", calibre_db="error", book_count=0)
