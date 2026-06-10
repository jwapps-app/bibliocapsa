"""Books endpoints — full metadata including series."""

from fastapi import APIRouter, Query, HTTPException, Request
from typing import Optional
from ..database import get_conn
from ..schemas import BookDetail, BookSummary, PaginatedBooks
from ..queries import row_to_summary, row_to_detail
from .. import access
from .. import calibre_overlay as overlay
from .. import calibre_custom
from datetime import datetime, timezone
import math


def _cal_epoch(ts) -> float:
    """Parse a Calibre timestamp string to epoch seconds (for date-added sort)."""
    if not ts:
        return 0.0
    try:
        dt = datetime.fromisoformat(str(ts))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def _merge_overlay(items):
    """Merge pending Calibre edits + community ratings + read status over items."""
    cal_ids = [it.id for it in items if getattr(it, "book_source", None) != "native"]
    overlay.apply_to_items(items, overlay.get_edits(cal_ids))
    if cal_ids:
        from .. import community, calibre_read
        ratings = community.get_calibre_ratings(cal_ids)
        rstat = calibre_read.statuses(cal_ids)
        # Seed read status from the mapped Calibre column for books without a
        # Bibliocapsa record (e.g. existing Goodreads-imported read books).
        missing = [bid for bid in cal_ids if bid not in rstat]
        colstat = calibre_read.calibre_column_statuses(missing)
        for it in items:
            if getattr(it, "book_source", None) != "native":
                if ratings.get(it.id) is not None:
                    it.community_rating = ratings[it.id]
                st = rstat.get(it.id) or colstat.get(it.id)
                if st:
                    it.reading_status = st["status"]
                    it.date_read = st["date_read"]
    return items


def _read_filter_clause(read_filter, conn):
    """SQL fragment + params for filtering Calibre books (alias `b`) by the
    unified read status. A book counts as read from EITHER source:
      • Bibliocapsa's own calibre_read_status store, OR
      • the mapped Calibre Yes/No column (Settings → Reading columns) — so books
        already marked read in Calibre (e.g. a Goodreads import) show up too.
    Book ids are integer PKs from our own DB, so they're inlined directly —
    avoiding SQLite's 999-bound-parameter limit on large read/unread sets.
    `conn` is the Calibre (SQLite) connection. Returns (sql, params) or None."""
    from .. import calibre_read, calibre_custom
    from .settings import get_setting

    def _in(ids):
        return "(" + ",".join(str(int(i)) for i in ids) + ")"

    sets = calibre_read.ids_by_status()
    read_ids = sets["read"]
    reading_ids = sets["reading"]
    busy_ids = read_ids | reading_ids

    # The mapped Calibre read column, as a `b.id` predicate over real Calibre data.
    col_read = get_setting("reading_col_read")
    col_pred = None
    if col_read:
        p = calibre_custom.filter_predicate(conn, col_read, "1")  # bool → no params
        if p:
            col_pred = p[0]

    def _read_expr():
        parts = []
        if read_ids:
            parts.append(f"b.id IN {_in(read_ids)}")
        if col_pred:
            parts.append(col_pred)
        return "(" + " OR ".join(parts) + ")" if parts else "1=0"

    def _busy_expr():
        # "read or reading" — for the unread filter to exclude.
        parts = []
        if busy_ids:
            parts.append(f"b.id IN {_in(busy_ids)}")
        if col_pred:
            parts.append(col_pred)
        return "(" + " OR ".join(parts) + ")" if parts else None

    if read_filter == "read":
        return (_read_expr(), [])
    if read_filter == "reading":
        return ("1=0", []) if not reading_ids else (f"b.id IN {_in(reading_ids)}", [])
    if read_filter == "unread":
        be = _busy_expr()
        return ("1=1", []) if be is None else (f"NOT {be}", [])
    return None


def _native_read_clause(read_filter):
    """SQL fragment for filtering native_books (no alias) by reading status."""
    if read_filter == "read":
        return "reading_status = 'read'"
    if read_filter == "reading":
        return "reading_status = 'reading'"
    if read_filter == "unread":
        return "(reading_status IS NULL OR reading_status = '')"
    return None


def _date_col_id(conn):
    """custom_column_<id> table id for the mapped Calibre 'Date read' column, or None."""
    return _mapped_col_id(conn, "reading_col_date")


def _read_col_id(conn):
    """custom_column_<id> table id for the mapped Calibre 'Read' (bool) column, or None."""
    return _mapped_col_id(conn, "reading_col_read")


def _mapped_col_id(conn, setting_key):
    try:
        from .settings import get_setting
        lbl = get_setting(setting_key)
        if not lbl:
            return None
        r = conn.execute("SELECT id FROM custom_columns WHERE label = ?", (lbl,)).fetchone()
        return int(r["id"]) if r else None
    except Exception:
        return None


def _calibre_read_date_expr(conn):
    """A SQL expression (over alias `b`) giving a Calibre book's read date, but
    ONLY when the book is actually marked read — so unread books with a stray
    Date Read value don't rank in the 'Date read' sort. Falls back sensibly when
    columns aren't mapped."""
    dcid = _date_col_id(conn)
    rcid = _read_col_id(conn)
    if dcid and rcid:
        return (f"(CASE WHEN EXISTS (SELECT 1 FROM custom_column_{rcid} rc WHERE rc.book=b.id AND rc.value=1) "
                f"THEN (SELECT value FROM custom_column_{dcid} dc WHERE dc.book=b.id) END)")
    if dcid:
        return f"(SELECT value FROM custom_column_{dcid} dc WHERE dc.book=b.id)"
    return "b.timestamp"

router = APIRouter()


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _pg():
    from ..pg_database import get_database_url
    import psycopg2
    from psycopg2.extras import RealDictCursor
    return psycopg2.connect(get_database_url(), cursor_factory=RealDictCursor)


def _native_to_summary(nb: dict, base_url: str) -> BookSummary:
    """Convert a native_books row to BookSummary. Native books always report a
    cover — the cover endpoint serves the uploaded image when present, otherwise
    a generated (Calibre-style) one. `?v` busts the browser cache after a
    regenerate/upload."""
    ver = nb.get("cover_variant") or 0
    return BookSummary(
        id=nb["id"],
        title=nb["title"] or "Unknown",
        sort=nb["title"] or "Unknown",
        authors=[{"id": 0, "name": nb["author"], "sort": nb["author"]}] if nb.get("author") else [],
        series=None,
        tags=[],
        pubdate=None,
        cover_url=f"{base_url}/api/native/books/{nb['id']}/cover?v={ver}",
        has_cover=True,
        rating=nb.get("rating"),
        community_rating=nb.get("community_rating"),
        reading_status=nb.get("reading_status"),
        date_read=nb.get("date_read"),
        last_modified=nb.get("updated_at"),
        book_source="native",
        has_physical=True,
        has_digital=False,
        physical_location=nb.get("location"),
    )


def _merged_all(request, base_url, page, page_size, offset, search, sort_dir, allowed=None, sort_by="title", read_filter=None, collapse=False, physical_only=False):
    """Merge of all Calibre books + all native books, by title or date-added.
    With physical_only=True, restricts to physically-owned books (native + the
    Calibre books flagged has_physical) — so the Physical view sorts identically.

    Only lightweight (id, key) rows are fetched up to offset+page_size from each
    source; full summaries are built solely for the page_size items on this page.
    """
    reverse = sort_dir.lower() == "desc"
    by_date = sort_by == "added"
    by_read_date = sort_by == "date_read"
    by_author = sort_by == "author"
    fetch_n = offset + page_size
    sql_dir = "DESC" if reverse else "ASC"

    nat_pred, nat_pred_params = access.native_predicate(allowed)
    cal_pred, cal_pred_params = access.calibre_predicate(allowed, "b")

    # ── Lightweight native rows ──
    pg = _pg()
    cur = pg.cursor()
    native_params: list = []
    native_conds = ["1=1"]
    if search:
        native_conds.append("(title ILIKE %s OR author ILIKE %s)")
        native_params += [f"%{search}%", f"%{search}%"]
    if nat_pred:
        native_conds.append(nat_pred)
        native_params += nat_pred_params
    nat_read = _native_read_clause(read_filter)
    if nat_read:
        native_conds.append(nat_read)
    if physical_only:
        native_conds.append("(format != 'digital' OR format IS NULL)")
    native_where = " AND ".join(native_conds)
    cur.execute(f"SELECT COUNT(*) AS c FROM native_books WHERE {native_where}", native_params)
    native_total = cur.fetchone()["c"]
    if by_date:
        # "Date added" = when the book entered the collection — the Goodreads
        # "Date Added" for imports (stored in date_added), falling back to the
        # Bibliocapsa row-creation time for manually-added books.
        cur.execute(
            f"SELECT id, EXTRACT(EPOCH FROM COALESCE(date_added, created_at)) AS ek FROM native_books WHERE {native_where} "
            f"ORDER BY COALESCE(date_added, created_at) {sql_dir} NULLS LAST LIMIT %s",
            native_params + [fetch_n],
        )
        native_light = [("native", r["id"], float(r["ek"] or 0)) for r in cur.fetchall()]
    elif by_read_date:
        cur.execute(
            f"SELECT id, CASE WHEN reading_status='read' THEN COALESCE(date_read, '') ELSE '' END AS dr "
            f"FROM native_books WHERE {native_where} "
            f"ORDER BY (CASE WHEN reading_status='read' THEN date_read END) {sql_dir} NULLS LAST LIMIT %s",
            native_params + [fetch_n],
        )
        native_light = [("native", r["id"], (r["dr"] or "")[:10]) for r in cur.fetchall()]
    elif by_author:
        cur.execute(
            f"SELECT id, COALESCE(author, '') AS ak FROM native_books WHERE {native_where} "
            f"ORDER BY lower(author) {sql_dir} NULLS LAST LIMIT %s",
            native_params + [fetch_n],
        )
        native_light = [("native", r["id"], (r["ak"] or "").casefold()) for r in cur.fetchall()]
    else:
        cur.execute(
            f"SELECT id, title FROM native_books WHERE {native_where} "
            f"ORDER BY lower(title) {sql_dir} LIMIT %s",
            native_params + [fetch_n],
        )
        native_light = [("native", r["id"], (r["title"] or "").casefold()) for r in cur.fetchall()]
    pg.close()

    # ── Lightweight Calibre rows ──
    with get_conn() as conn:
        cal_params: list = []
        cal_conds = ["1=1"]
        if search:
            cal_conds.append("(b.title LIKE ? OR EXISTS ("
                             "SELECT 1 FROM authors a JOIN books_authors_link bal ON bal.author=a.id "
                             "WHERE bal.book=b.id AND a.name LIKE ?))")
            cal_params += [f"%{search}%", f"%{search}%"]
        if cal_pred:
            cal_conds.append(cal_pred)
            cal_params += cal_pred_params
        cal_read = _read_filter_clause(read_filter, conn)
        if cal_read:
            cal_conds.append(cal_read[0])
            cal_params += cal_read[1]
        if physical_only:
            # Only Calibre books also owned physically (book_ownership lives in PG;
            # inline the ids since they're integer PKs from our own DB).
            pgx = _pg(); curx = pgx.cursor()
            curx.execute("SELECT book_id FROM book_ownership WHERE has_physical=TRUE AND book_source='calibre'")
            phys_ids = [r["book_id"] for r in curx.fetchall()]
            pgx.close()
            cal_conds.append("b.id IN (" + ",".join(str(int(i)) for i in phys_ids) + ")" if phys_ids else "1=0")
        if collapse:
            # Keep only the first book of each series (Calibre-only; native books
            # have no series so they're unaffected).
            cal_conds.append(
                "(NOT EXISTS (SELECT 1 FROM books_series_link bsl WHERE bsl.book = b.id) "
                "OR b.id = (SELECT b2.id FROM books b2 JOIN books_series_link bsl2 ON bsl2.book = b2.id "
                "WHERE bsl2.series = (SELECT series FROM books_series_link WHERE book = b.id LIMIT 1) "
                "ORDER BY b2.series_index ASC, b2.id ASC LIMIT 1))"
            )
        cal_where = " AND ".join(cal_conds)
        calibre_total = conn.execute(f"SELECT COUNT(*) FROM books b WHERE {cal_where}", cal_params).fetchone()[0]
        if by_date:
            light_rows = conn.execute(
                f"SELECT b.id, b.timestamp FROM books b WHERE {cal_where} "
                f"ORDER BY b.timestamp {sql_dir} LIMIT ?",
                cal_params + [fetch_n],
            ).fetchall()
            calibre_light = [("calibre", r["id"], _cal_epoch(r["timestamp"])) for r in light_rows]
        elif by_read_date:
            # Sort by the read date — but only for books actually marked read
            # (the expr is NULL for unread books). Fall back to Bibliocapsa's own
            # read date for books read only there.
            from .. import calibre_read
            rstat = calibre_read.statuses()
            date_expr = _calibre_read_date_expr(conn)
            light_rows = conn.execute(
                f"SELECT b.id, ({date_expr}) AS dr FROM books b WHERE {cal_where} "
                f"ORDER BY dr {sql_dir} NULLS LAST LIMIT ?",
                cal_params + [fetch_n],
            ).fetchall()

            def _rk(r):
                if r["dr"]:
                    return str(r["dr"])[:10]
                st = rstat.get(r["id"])
                return (st["date_read"] or "")[:10] if st and st.get("status") == "read" and st.get("date_read") else ""
            calibre_light = [("calibre", r["id"], _rk(r)) for r in light_rows]
        elif by_author:
            light_rows = conn.execute(
                f"SELECT b.id, b.author_sort FROM books b WHERE {cal_where} "
                f"ORDER BY b.author_sort COLLATE NOCASE {sql_dir} LIMIT ?",
                cal_params + [fetch_n],
            ).fetchall()
            calibre_light = [("calibre", r["id"], (r["author_sort"] or "").casefold()) for r in light_rows]
        else:
            light_rows = conn.execute(
                f"SELECT b.id, b.sort, b.title FROM books b WHERE {cal_where} "
                f"ORDER BY b.sort COLLATE NOCASE {sql_dir} LIMIT ?",
                cal_params + [fetch_n],
            ).fetchall()
            calibre_light = [("calibre", r["id"], (r["sort"] or r["title"] or "").casefold()) for r in light_rows]

        # ── Merge by key, take this page's slice ──
        merged = sorted(calibre_light + native_light, key=lambda t: t[2], reverse=reverse)
        page_slice = merged[offset:offset + page_size]

        cal_ids = [bid for src, bid, _ in page_slice if src == "calibre"]
        nat_ids = [bid for src, bid, _ in page_slice if src == "native"]

        # ── Build Calibre summaries for the slice ──
        cal_map: dict = {}
        if cal_ids:
            placeholders = ",".join("?" * len(cal_ids))
            rows = conn.execute(
                f"""SELECT b.id, b.title, b.sort, b.pubdate, b.last_modified,
                          b.has_cover, b.uuid, b.path, b.series_index, b.author_sort
                    FROM books b WHERE b.id IN ({placeholders})""",
                cal_ids,
            ).fetchall()
            ownership_map: dict = {}
            try:
                pg2 = _pg()
                cur2 = pg2.cursor()
                cur2.execute(
                    "SELECT book_id, has_digital, has_physical, physical_location "
                    "FROM book_ownership WHERE book_id = ANY(%s) AND book_source='calibre'",
                    (cal_ids,),
                )
                for r in cur2.fetchall():
                    ownership_map[r["book_id"]] = {"has_digital": r["has_digital"], "has_physical": r["has_physical"], "physical_location": r["physical_location"]}
                pg2.close()
            except Exception:
                pass
            for row in rows:
                cal_map[row["id"]] = row_to_summary(conn, row, base_url, ownership_map.get(row["id"]))

    # ── Build native summaries for the slice ──
    nat_map: dict = {}
    if nat_ids:
        pg3 = _pg()
        cur3 = pg3.cursor()
        cur3.execute("SELECT * FROM native_books WHERE id = ANY(%s)", (nat_ids,))
        for r in cur3.fetchall():
            nat_map[r["id"]] = _native_to_summary(dict(r), base_url)
        pg3.close()

    items = []
    for src, bid, _ in page_slice:
        summary = cal_map.get(bid) if src == "calibre" else nat_map.get(bid)
        if summary is not None:
            items.append(summary)

    total = calibre_total + native_total
    return PaginatedBooks(
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
        items=_merge_overlay(items),
    )


@router.get("", response_model=PaginatedBooks, summary="List all books")
def list_books(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: Optional[str] = Query(None),
    author_id: Optional[int] = Query(None),
    series_id: Optional[int] = Query(None),
    tag_id: Optional[int] = Query(None),
    sort_by: str = Query("title", description="One of the built-ins, or 'custom:<label>' for a custom column"),
    sort_dir: str = Query("asc", enum=["asc", "desc"]),
    collapse_series: bool = Query(False),
    format_filter: str = Query("digital", enum=["all", "digital", "physical"]),
    custom_filter: Optional[str] = Query(None, description="Filter by a Calibre custom column: 'label:value'"),
    read_filter: Optional[str] = Query(None, description="Unified read status: 'read' | 'reading' | 'unread'"),
):
    base_url = _base_url(request)
    offset = (page - 1) * page_size
    allowed = access.restriction_for_request(request)
    custom_sort = sort_by.startswith("custom:")  # sorting by a Calibre custom column

    # ── All filter: alphabetical merge of every Calibre book + native books ────
    # (Only when no Calibre-specific filter is active; native books can't match
    #  an author/series/tag/custom filter or a custom-column sort, so those fall
    #  through to the Calibre query.)
    if (format_filter in ("all", "physical") and author_id is None and series_id is None
            and tag_id is None and not custom_filter and not custom_sort):
        try:
            return _merged_all(request, base_url, page, page_size, offset, search, sort_dir, allowed,
                               sort_by, read_filter, collapse_series, physical_only=(format_filter == "physical"))
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # (The Physical view is handled above by _merged_all(physical_only=True), so it
    #  sorts identically to the All view.)

    # ── Standard Calibre query (all / digital) ────────────────────────────────
    with get_conn() as conn:
        conditions = ["1=1"]
        params: list = []

        if search:
            conditions.append(
                "(b.title LIKE ? OR EXISTS ("
                "  SELECT 1 FROM authors a JOIN books_authors_link bal ON bal.author=a.id"
                "  WHERE bal.book=b.id AND a.name LIKE ?"
                "))"
            )
            like = f"%{search}%"
            params += [like, like]

        if author_id is not None:
            conditions.append("EXISTS (SELECT 1 FROM books_authors_link WHERE book=b.id AND author=?)")
            params.append(author_id)

        if series_id is not None:
            conditions.append("EXISTS (SELECT 1 FROM books_series_link WHERE book=b.id AND series=?)")
            params.append(series_id)

        if tag_id is not None:
            conditions.append("EXISTS (SELECT 1 FROM books_tags_link WHERE book=b.id AND tag=?)")
            params.append(tag_id)

        if custom_filter and ":" in custom_filter:
            label, value = custom_filter.split(":", 1)
            pred = calibre_custom.filter_predicate(conn, label, value)
            if pred:
                conditions.append(pred[0])
                params += pred[1]

        cal_pred, cal_pred_params = access.calibre_predicate(allowed, "b")
        if cal_pred:
            conditions.append(cal_pred)
            params += cal_pred_params

        cal_read = _read_filter_clause(read_filter, conn)
        if cal_read:
            conditions.append(cal_read[0])
            params += cal_read[1]

        where = " AND ".join(conditions)

        if collapse_series:
            where = f"""({where}) AND (
                NOT EXISTS (SELECT 1 FROM books_series_link bsl WHERE bsl.book = b.id)
                OR b.id = (
                    SELECT b2.id FROM books b2
                    JOIN books_series_link bsl2 ON bsl2.book = b2.id
                    WHERE bsl2.series = (
                        SELECT series FROM books_series_link WHERE book = b.id LIMIT 1
                    )
                    ORDER BY b2.series_index ASC, b2.id ASC
                    LIMIT 1
                )
            )"""

        # Digital filter — all Calibre books (they're all downloadable, including dual-format)
        # No additional filtering needed; the standard Calibre query already covers this
        if format_filter == "digital":
            pass  # show all Calibre books

        sort_map = {
            "title":         "b.sort",
            "author":        "b.author_sort",
            "pubdate":       "b.pubdate",
            "last_modified": "b.last_modified",
            "added":         "b.timestamp",
            "series_index":  "b.series_index",
            "series":        "(SELECT s.name FROM series s JOIN books_series_link bsl ON bsl.series=s.id WHERE bsl.book=b.id LIMIT 1)",
        }
        if sort_by == "date_read":
            order = f"({_calibre_read_date_expr(conn)}) {sort_dir.upper()} NULLS LAST"
        elif custom_sort:
            label = sort_by.split(":", 1)[1]
            col = conn.execute("SELECT id FROM custom_columns WHERE label = ?", (label,)).fetchone()
            if col:
                order = f"(SELECT cc.value FROM custom_column_{int(col['id'])} cc WHERE cc.book=b.id) {sort_dir.upper()} NULLS LAST"
            else:
                order = f"b.sort {sort_dir.upper()} NULLS LAST"
        else:
            order = f"{sort_map.get(sort_by, 'b.sort')} {sort_dir.upper()} NULLS LAST"

        total = conn.execute(f"SELECT COUNT(*) FROM books b WHERE {where}", params).fetchone()[0]

        rows = conn.execute(
            f"""
            SELECT b.id, b.title, b.sort, b.pubdate, b.last_modified,
                   b.has_cover, b.uuid, b.path, b.series_index, b.author_sort
            FROM books b
            WHERE {where}
            ORDER BY {order}
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset],
        ).fetchall()

        # Batch ownership
        book_ids = [row["id"] for row in rows]
        ownership_map = {}
        if book_ids:
            try:
                from ..pg_database import get_database_url
                import psycopg2
                from psycopg2.extras import RealDictCursor
                pg = psycopg2.connect(get_database_url(), cursor_factory=RealDictCursor)
                cur = pg.cursor()
                cur.execute(
                    "SELECT book_id, has_digital, has_physical, physical_location FROM book_ownership WHERE book_id = ANY(%s) AND book_source='calibre'",
                    (book_ids,)
                )
                for r in cur.fetchall():
                    ownership_map[r["book_id"]] = {
                        "has_digital": r["has_digital"],
                        "has_physical": r["has_physical"],
                        "physical_location": r["physical_location"],
                    }
                pg.close()
            except Exception:
                pass

        items = [row_to_summary(conn, row, base_url, ownership_map.get(row["id"])) for row in rows]

    return PaginatedBooks(
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
        items=_merge_overlay(items),
    )


@router.get("/{book_id}", response_model=BookDetail, summary="Get a single book")
def get_book(book_id: int, request: Request):
    base_url = _base_url(request)
    with get_conn() as conn:
        row = conn.execute(
            """SELECT b.id, b.title, b.sort, b.pubdate, b.last_modified,
                      b.has_cover, b.uuid, b.path, b.series_index, b.author_sort
               FROM books b WHERE b.id = ?""",
            (book_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Book {book_id} not found")
        allowed = access.restriction_for_request(request)
        if not access.is_calibre_book_allowed(conn, book_id, allowed):
            raise HTTPException(status_code=404, detail=f"Book {book_id} not found")
        detail = row_to_detail(conn, row, base_url)
        edits = overlay.get_edits([book_id]).get(book_id) or {}
        if edits:
            overlay.apply_to_detail(detail, edits)
        from .. import calibre_custom
        detail.custom = calibre_custom.fetch_for_book(conn, book_id)
        custom_edits = {k[len("custom:"):]: v for k, v in edits.items() if k.startswith("custom:")}
        if custom_edits:
            detail.custom = calibre_custom.merge_overlay(conn, detail.custom, custom_edits)
        from .. import community, calibre_read
        detail.community_rating = community.get_calibre_ratings([book_id]).get(book_id)
        st = calibre_read.get_status(book_id)
        detail.reading_status = st["status"]
        detail.date_read = st["date_read"]
        return detail
