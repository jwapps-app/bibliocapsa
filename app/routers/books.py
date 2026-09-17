"""Books endpoints — full metadata including series."""

from fastapi import APIRouter, Query, HTTPException, Request
from typing import Optional, Literal
from ..database import get_conn
from ..schemas import BookDetail, BookSummary, PaginatedBooks
from ..queries import row_to_summary, row_to_detail, summaries_for_rows, native_cover_url
from .. import access
from .. import calibre_overlay as overlay
from .. import calibre_custom
from datetime import datetime, timezone
import math


# The ONLY strings that may follow ORDER BY <expr>. `Query(enum=...)` is OpenAPI
# documentation, not validation -- sort_dir used to reach the SQL verbatim, which
# let any signed-in user append expressions to ORDER BY. The parameter is now a
# validated Literal AND is only ever used as a key into this table.
_SQL_DIR = {"asc": "ASC", "desc": "DESC"}


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
        # One effective status per book (calibre_read.effective): the mapped
        # Calibre column -- including edits still waiting to sync -- over our own
        # record, with the column's date filling in when ours has none. Clients
        # that order locally (iOS) rely on status and date agreeing with the
        # server's `date_read` sort.
        eff = calibre_read.effective(cal_ids)
        for it in items:
            if getattr(it, "book_source", None) != "native":
                if ratings.get(it.id) is not None:
                    it.community_rating = ratings[it.id]
                st = eff.get(it.id)
                if st:
                    it.reading_status = st["status"]
                    it.date_read = st.get("date_read") or ""
    return items


def _read_filter_clause(read_filter, conn):
    """SQL fragment + params for filtering Calibre books (alias `b`) by read
    status -- built from calibre_read.effective(), the SAME calculation that
    fills `reading_status` in the payload, so a book can never sit in a filter
    its own card contradicts (Calibre's mapped column, edits still waiting to
    sync, and Bibliocapsa's own record are all folded in there).
    Book ids are integer PKs from our own data, so they're inlined directly --
    avoiding SQLite's 999-bound-parameter limit on large read/unread sets.
    Returns (sql, params) or None."""
    # No filter requested: nothing to do (and nothing to load).
    if read_filter not in ("read", "reading", "unread"):
        return None
    from .. import calibre_read

    def _in(ids):
        return "(" + ",".join(str(int(i)) for i in sorted(ids)) + ")"

    eff = calibre_read.effective(None)
    read_ids = {bid for bid, st in eff.items() if st["status"] == "read"}
    reading_ids = {bid for bid, st in eff.items() if st["status"] == "reading"}
    if read_filter == "read":
        return (f"b.id IN {_in(read_ids)}", []) if read_ids else ("1=0", [])
    if read_filter == "reading":
        return (f"b.id IN {_in(reading_ids)}", []) if reading_ids else ("1=0", [])
    busy = read_ids | reading_ids
    return (f"b.id NOT IN {_in(busy)}", []) if busy else ("1=1", [])


def _native_read_clause(read_filter):
    """SQL fragment for filtering native_books (no alias) by reading status."""
    if read_filter == "read":
        return "reading_status = 'read'"
    if read_filter == "reading":
        return "reading_status = 'reading'"
    if read_filter == "unread":
        return "(reading_status IS NULL OR reading_status = '')"
    return None


# Sorts the merged (Calibre + native) list supports. Anything else is sorted by
# title -- explicitly, here, rather than by falling through a chain of elifs.
_MERGED_SORTS = {"title", "author", "added", "date_read", "pubdate", "last_modified",
                 "series", "series_index"}


def _text_key(v) -> str:
    """Case- and accent-insensitive text key, identical for both stores."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(v or ""))
    return "".join(c for c in t if not unicodedata.combining(c)).casefold().strip()


def _sort_key(sort_by, v):
    """Normalise one raw sort value. None = "has no value" (always sorted last)."""
    if v is None or v == "":
        return None
    if sort_by in ("added", "last_modified"):
        k = float(v) if isinstance(v, (int, float)) or hasattr(v, "__float__") else _cal_epoch(v)
        return k or None
    if sort_by in ("date_read", "pubdate"):
        d = str(v)[:10]
        return None if d.startswith("0101-01-01") else d  # Calibre's "undefined date"
    if sort_by == "series_index":
        return float(v)
    return _text_key(v) or None


def _ordered(light, reverse, by_title_within_ties=False):
    """ONE ordering rule for (source, id, key, title_key) rows: by key in the
    requested direction; rows without a key always last; ties -- and the keyless
    tail -- by (source, id), so the order is total and a book can neither repeat
    nor vanish between pages. (source, id) is also the order equal keys have
    always come back in, which matters: the iOS app ranks "date added" from
    this list, and a bulk import shares one timestamp across hundreds of books.)
    Text sorts pass by_title_within_ties so one author's books run A-Z."""
    tie = (lambda t: (t[3], t[0], t[1])) if by_title_within_ties else (lambda t: (t[0], t[1]))
    have = sorted((t for t in light if t[2] is not None), key=tie)
    have.sort(key=lambda t: t[2], reverse=reverse)  # stable: keeps the tie order
    return have + sorted((t for t in light if t[2] is None), key=tie)


def _calibre_light(conn, where, params, sort_by):
    """(source, id, key, title_key) for every Calibre book matching `where`."""
    key_sql = {
        "title":         "b.sort",
        "author":        "b.author_sort",
        "added":         "b.timestamp",
        "last_modified": "b.last_modified",
        "pubdate":       "b.pubdate",
        "series_index":  "b.series_index",
        "series":        "(SELECT s.name FROM series s JOIN books_series_link bsl ON bsl.series=s.id "
                         "WHERE bsl.book=b.id LIMIT 1)",
    }.get(sort_by, "NULL")
    rows = conn.execute(
        f"SELECT b.id, b.sort, b.title, b.series_index, {key_sql} AS k FROM books b WHERE {where}", params
    ).fetchall()
    if sort_by == "date_read":
        # The effective read date -- Calibre's column, edits waiting to sync and
        # our own record -- i.e. exactly the `date_read` the payload reports.
        from .. import calibre_read
        eff = calibre_read.effective(None)
        dates = {bid: st.get("date_read") for bid, st in eff.items() if st["status"] == "read"}
        key = lambda r: _sort_key(sort_by, dates.get(r["id"]))
    elif sort_by == "series":
        # Within a series, by position.
        key = lambda r: (_text_key(r["k"]), float(r["series_index"] or 0)) if r["k"] else None
    else:
        key = lambda r: _sort_key(sort_by, r["k"] or (r["title"] if sort_by == "title" else None))
    return [("calibre", r["id"], key(r), _text_key(r["sort"] or r["title"])) for r in rows]


router = APIRouter()


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


from ..pg_database import get_pg as _pg


def _native_to_summary(nb: dict, base_url: str) -> BookSummary:
    """Convert a native_books row to BookSummary. Native books always report a
    cover — the cover endpoint serves the uploaded image when present, otherwise
    a generated (Calibre-style) one."""
    return BookSummary(
        id=nb["id"],
        title=nb["title"] or "Unknown",
        sort=nb["title"] or "Unknown",
        authors=[{"id": 0, "name": nb["author"], "sort": nb["author"]}] if nb.get("author") else [],
        series=None,
        tags=[],
        pubdate=None,
        cover_url=native_cover_url(base_url, nb),
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
    if sort_by not in _MERGED_SORTS:
        sort_by = "title"
    by_date = sort_by == "added"

    nat_pred, nat_pred_params = access.native_predicate(allowed)
    cal_pred, cal_pred_params = access.calibre_predicate(allowed, "b")

    # ── Lightweight native rows: (source, id, sort key, title key) ──
    # EVERY matching row, not the first offset+page_size per source: the two
    # stores collate differently (SQLite NOCASE is ASCII-only, Postgres lower()
    # is locale-aware, and the read date isn't a column in either), so a
    # per-source LIMIT ranked by one rule and merged by another silently dropped
    # books. The rows are two or three scalars each; the ordering is decided
    # once, here, by _ordered().
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
    native_key_sql = {
        # "Date added" = when the book entered the collection — the Goodreads
        # "Date Added" for imports (stored in date_added), falling back to the
        # Bibliocapsa row-creation time for manually-added books.
        "added":         "EXTRACT(EPOCH FROM COALESCE(date_added, created_at))",
        "last_modified": "EXTRACT(EPOCH FROM updated_at)",
        "date_read":     "CASE WHEN reading_status='read' THEN date_read END",
        "author":        "author",
        "pubdate":       "published_date",
        "title":         "title",
    }.get(sort_by, "NULL")  # series / series_index: native books have neither
    cur.execute(f"SELECT id, title, {native_key_sql} AS k FROM native_books WHERE {native_where}", native_params)
    native_light = [("native", r["id"], _sort_key(sort_by, r["k"]), _text_key(r["title"])) for r in cur.fetchall()]
    native_total = len(native_light)
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
        calibre_light = _calibre_light(conn, cal_where, cal_params, sort_by)
        calibre_total = len(calibre_light)

        # ── Merge by key, take this page's slice ──
        merged = _ordered(calibre_light + native_light, reverse, by_title_within_ties=sort_by in ("author", "series"))
        page_slice = [(src, bid, k) for src, bid, k, _ in merged[offset:offset + page_size]]

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
            for summary in summaries_for_rows(conn, rows, base_url, ownership_map):
                cal_map[summary.id] = summary

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
    # The date-added sort key IS the real "entered the collection" timestamp, so
    # hand it back rather than making clients guess order-only.
    added_key = {(src, bid): k for src, bid, k in page_slice} if by_date else {}
    for src, bid, _ in page_slice:
        summary = cal_map.get(bid) if src == "calibre" else nat_map.get(bid)
        if summary is not None:
            if by_date:
                k = added_key.get((src, bid))
                if isinstance(k, (int, float)) and k > 0:
                    summary.added = float(k)
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
    sort_dir: Literal["asc", "desc"] = Query("asc"),
    collapse_series: bool = Query(False),
    format_filter: Literal["all", "digital", "physical"] = Query("digital"),
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

        if format_filter == "physical":
            # The Physical view normally runs through _merged_all, but an author /
            # series / tag / custom filter or custom sort lands here -- and this
            # branch had no ownership predicate, so "physical books by this author"
            # returned digital-only books. (Ids are integer PKs from our own DB.)
            from ..pg_database import get_pg as _getpg
            _pgx = _getpg()
            try:
                _c = _pgx.cursor()
                _c.execute("SELECT book_id FROM book_ownership WHERE has_physical=TRUE AND book_source='calibre'")
                _phys = [int(r["book_id"]) for r in _c.fetchall()]
            finally:
                _pgx.close()
            conditions.append("b.id IN (" + ",".join(map(str, _phys)) + ")" if _phys else "1=0")

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
        sort_map = {
            "title":         "b.sort",
            "author":        "b.author_sort",
            "pubdate":       "b.pubdate",
            "last_modified": "b.last_modified",
            "added":         "b.timestamp",
            "series_index":  "b.series_index",
            "series":        "(SELECT s.name FROM series s JOIN books_series_link bsl ON bsl.series=s.id WHERE bsl.book=b.id LIMIT 1)",
        }
        read_order = None
        if sort_by == "date_read":
            # The read date lives in three places (Calibre's column, edits waiting
            # to sync, our own record), so it can't be an ORDER BY. Rank the
            # matching ids by the effective date -- the same rule as the merged
            # list -- and page through that.
            read_order = [bid for _, bid, _, _ in
                          _ordered(_calibre_light(conn, where, params, "date_read"), sort_dir == "desc")]
            order = "b.sort"
        elif custom_sort:
            label = sort_by.split(":", 1)[1]
            col = conn.execute("SELECT id, normalized FROM custom_columns WHERE label = ?", (label,)).fetchone()
            if col and col["normalized"]:
                # Normalized columns (text/enumeration/series-like) keep values in
                # custom_column_N and link books through books_custom_column_N_link;
                # there is no `book` column to correlate on, so the simple form
                # below was a SQL error (HTTP 500) for them.
                cid = int(col["id"])
                order = (f"(SELECT MIN(v.value) FROM books_custom_column_{cid}_link l "
                         f"JOIN custom_column_{cid} v ON v.id = l.value WHERE l.book = b.id) "
                         f"{_SQL_DIR[sort_dir]} NULLS LAST")
            elif col:
                order = f"(SELECT cc.value FROM custom_column_{int(col['id'])} cc WHERE cc.book=b.id) {_SQL_DIR[sort_dir]} NULLS LAST"
            else:
                order = f"b.sort {_SQL_DIR[sort_dir]} NULLS LAST"
        else:
            order = f"{sort_map.get(sort_by, 'b.sort')} {_SQL_DIR[sort_dir]} NULLS LAST"

        cols = ("b.id, b.title, b.sort, b.pubdate, b.last_modified, "
                "b.has_cover, b.uuid, b.path, b.series_index, b.author_sort")
        if read_order is not None:
            total = len(read_order)
            page_ids = read_order[offset:offset + page_size]
            by_id = {}
            if page_ids:
                ph = ",".join("?" * len(page_ids))
                by_id = {r["id"]: r for r in conn.execute(
                    f"SELECT {cols} FROM books b WHERE b.id IN ({ph})", page_ids).fetchall()}
            rows = [by_id[i] for i in page_ids if i in by_id]
        else:
            total = conn.execute(f"SELECT COUNT(*) FROM books b WHERE {where}", params).fetchone()[0]
            # `b.sort, b.id` makes the order total: without a unique tie-breaker
            # SQLite may return equal-key rows in a different order per query, so
            # a book could repeat on one page and never appear on the next.
            rows = conn.execute(
                f"SELECT {cols} FROM books b WHERE {where} "
                f"ORDER BY {order}, b.sort COLLATE NOCASE, b.id LIMIT ? OFFSET ?",
                params + [page_size, offset],
            ).fetchall()

        # Batch ownership
        book_ids = [row["id"] for row in rows]
        ownership_map = {}
        if book_ids:
            try:
                from ..pg_database import get_pg
                pg = get_pg()
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

        items = summaries_for_rows(conn, rows, base_url, ownership_map)

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
        st = calibre_read.get_status(book_id)  # same rule as the list payload
        status = st["status"]
        date_read = st.get("date_read") or ""
        detail.reading_status = status
        detail.date_read = date_read
        return detail
