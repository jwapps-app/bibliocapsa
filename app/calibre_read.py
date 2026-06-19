"""
Digital (Calibre) read/unread status — Bibliocapsa's own per-library store.

Calibre's database is read-only, so we keep read status for Calibre books in
PostgreSQL (`calibre_read_status`). This is the single source of truth for the
UI and for the unified Read/Unread filter, and works even when a library has no
relevant Calibre column at all.

Optionally, when an admin maps a Calibre Yes/No column (Settings → Reading
columns: `reading_col_read` / `reading_col_date`), marking a book read is ALSO
queued as an overlay edit — so the status exports back into Calibre on the next
Sync to Calibre. That write-back is one-way (an export convenience); the Postgres
table above remains authoritative for Bibliocapsa.
"""

VALID = {"read", "reading"}


def _pg():
    from .pg_database import get_database_url
    import psycopg2
    from psycopg2.extras import RealDictCursor
    return psycopg2.connect(get_database_url(), cursor_factory=RealDictCursor)


def get_status(book_id: int) -> dict:
    """{'status': 'read'|'reading'|None, 'date_read': str|None} for one book.

    Falls back to the mapped Calibre read/date columns when Bibliocapsa has no
    record yet — so a book already marked read in Calibre shows as Read."""
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("SELECT status, date_read FROM calibre_read_status WHERE book_id = %s", (book_id,))
        r = cur.fetchone()
        if r:
            return {"status": r["status"], "date_read": r["date_read"]}
    finally:
        conn.close()
    return _status_from_calibre(book_id)


def _status_from_calibre(book_id: int) -> dict:
    """Read status derived from the mapped Calibre columns (read bool + date)."""
    try:
        from .routers.settings import get_setting
        col_read = get_setting("reading_col_read")
        if not col_read:
            return {"status": None, "date_read": None}
        from .database import get_conn
        from . import calibre_custom
        with get_conn() as cal:
            cur = {c["label"]: c["value"] for c in calibre_custom.fetch_for_book(cal, book_id)}
        if not cur.get(col_read):
            return {"status": None, "date_read": None}
        col_date = get_setting("reading_col_date")
        d = cur.get(col_date) if col_date else None
        return {"status": "read", "date_read": str(d)[:10] if d else None}
    except Exception:
        return {"status": None, "date_read": None}


def statuses(book_ids=None) -> dict:
    """{book_id: {'status', 'date_read'}} for the given ids (or all if None)."""
    conn = _pg()
    try:
        cur = conn.cursor()
        if book_ids is None:
            cur.execute("SELECT book_id, status, date_read FROM calibre_read_status")
        else:
            ids = list(book_ids)
            if not ids:
                return {}
            cur.execute("SELECT book_id, status, date_read FROM calibre_read_status WHERE book_id = ANY(%s)", (ids,))
        return {r["book_id"]: {"status": r["status"], "date_read": r["date_read"]} for r in cur.fetchall()}
    finally:
        conn.close()


def calibre_column_statuses(book_ids) -> dict:
    """{book_id: {'status':'read','date_read':...}} derived from the mapped Calibre
    read (bool) + date columns, for books whose read flag is true. Used to seed
    list summaries so books read in Calibre show their status/date. {} if no
    read column is mapped."""
    ids = [int(i) for i in (book_ids or [])]
    if not ids:
        return {}
    try:
        from .routers.settings import get_setting
        col_read = get_setting("reading_col_read")
        if not col_read:
            return {}
        from .database import get_conn
        with get_conn() as cal:
            rc = cal.execute("SELECT id FROM custom_columns WHERE label=?", (col_read,)).fetchone()
            if not rc:
                return {}
            rcid = int(rc["id"])
            col_date = get_setting("reading_col_date")
            dcid = None
            if col_date:
                dc = cal.execute("SELECT id FROM custom_columns WHERE label=?", (col_date,)).fetchone()
                dcid = int(dc["id"]) if dc else None
            ph = ",".join(str(i) for i in ids)
            reads = {r["book"] for r in cal.execute(
                f"SELECT book FROM custom_column_{rcid} WHERE book IN ({ph}) AND value=1").fetchall()}
            dates = {}
            if dcid:
                for r in cal.execute(f"SELECT book, value FROM custom_column_{dcid} WHERE book IN ({ph})").fetchall():
                    dates[r["book"]] = str(r["value"])[:10] if r["value"] else None
            return {bid: {"status": "read", "date_read": dates.get(bid)} for bid in reads}
    except Exception:
        return {}


def read_book_ids(book_ids) -> set:
    """The subset of `book_ids` marked 'read' — via our own store OR a mapped
    Calibre read column. Used to drop finished books out of 'Currently Reading'
    without touching their progress/stats (marking a book Read should remove it
    from the reading list, not require a reset-to-unread)."""
    ids = [int(i) for i in (book_ids or [])]
    if not ids:
        return set()
    out = {bid for bid, s in statuses(ids).items() if s.get("status") == "read"}
    out |= set(calibre_column_statuses(ids).keys())
    return out


def ids_by_status() -> dict:
    """{'read': set(book_id), 'reading': set(book_id)} across the whole library —
    used to build the unified Read/Unread filter."""
    out = {"read": set(), "reading": set()}
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("SELECT book_id, status FROM calibre_read_status WHERE status IN ('read','reading')")
        for r in cur.fetchall():
            out.setdefault(r["status"], set()).add(r["book_id"])
        return out
    finally:
        conn.close()


def set_status(book_id: int, status, date_read=None) -> dict:
    """Upsert a Calibre book's read status. `status` None/'' clears it (unread).
    Also queues a Calibre-column overlay edit when a read column is mapped."""
    status = status if status in VALID else None
    if status != "read":
        date_read = None  # only 'read' carries a finish date
    conn = _pg()
    try:
        cur = conn.cursor()
        if status is None:
            cur.execute("DELETE FROM calibre_read_status WHERE book_id = %s", (book_id,))
        else:
            cur.execute(
                """INSERT INTO calibre_read_status (book_id, status, date_read, updated_at)
                   VALUES (%s, %s, %s, NOW())
                   ON CONFLICT (book_id) DO UPDATE
                     SET status = EXCLUDED.status, date_read = EXCLUDED.date_read, updated_at = NOW()""",
                (book_id, status, date_read),
            )
        conn.commit()
    finally:
        conn.close()
    _writeback(book_id, status, date_read)
    return {"status": status, "date_read": date_read}


def _writeback(book_id: int, status, date_read) -> None:
    """If a Calibre Yes/No 'read' column (and optional date column) is mapped,
    queue an overlay edit so this status syncs back into Calibre. No-op otherwise.

    The Date Read column is only written when it is currently EMPTY — so an
    existing date (e.g. a Goodreads import, or a first read) is preserved and a
    re-read never overwrites it. Bibliocapsa's per-user read_log keeps the full
    history; Calibre's single column stays the original/first date."""
    try:
        from .routers.settings import get_setting
        from . import calibre_overlay as overlay
        col_read = get_setting("reading_col_read")
        col_date = get_setting("reading_col_date")
        edits: dict = {}
        if col_read:
            edits[f"custom:{col_read}"] = (status == "read")
        if col_date and status == "read" and date_read and not _calibre_has_date(book_id, col_date):
            edits[f"custom:{col_date}"] = date_read
        if edits:
            overlay.set_edits(book_id, edits)
    except Exception:
        pass  # write-back is best-effort; the Postgres status above is authoritative


def _calibre_has_date(book_id: int, col_date: str) -> bool:
    """True if the mapped Calibre Date Read column already holds a value for this
    book (in Calibre itself or a pending overlay edit) — so we never overwrite it."""
    try:
        from . import calibre_overlay as overlay
        pending = overlay.get_edits([book_id]).get(book_id) or {}
        if pending.get(f"custom:{col_date}"):
            return True
        from .database import get_conn
        from . import calibre_custom
        with get_conn() as cal:
            cur = {c["label"]: c["value"] for c in calibre_custom.fetch_for_book(cal, book_id)}
        return bool(cur.get(col_date))
    except Exception:
        return False  # if unsure, allow the write (better to record than lose a date)
