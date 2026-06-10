"""
Per-user read history — a running list of every time a user finished a book
(digital or physical). Lets users track re-reads ("read 3×: 2021, 2023, 2026")
and manually add / adjust / delete dates (e.g. to fix a date KOReader missed).

Independent of Calibre's single Date Read column, which only ever holds the
original/first date (see calibre_read._writeback, which never overwrites it).
"""


def _pg():
    from .pg_database import get_database_url
    import psycopg2
    from psycopg2.extras import RealDictCursor
    return psycopg2.connect(get_database_url(), cursor_factory=RealDictCursor)


def list_for(book_id: int, book_source: str, user_id: int) -> list:
    """A user's read dates for one book, newest first."""
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, date_read, source, EXTRACT(EPOCH FROM created_at)::bigint AS ts "
            "FROM read_log WHERE book_id=%s AND book_source=%s AND user_id=%s "
            "ORDER BY date_read DESC NULLS LAST, created_at DESC",
            (book_id, book_source, user_id),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def add(book_id: int, book_source: str, user_id: int, date_read, source: str = "manual",
        dedupe: bool = True):
    """Add a read date. With dedupe, a same-date entry for this user+book is a
    no-op (avoids spamming the list when a status is toggled repeatedly)."""
    conn = _pg()
    try:
        cur = conn.cursor()
        if dedupe and date_read:
            cur.execute(
                "SELECT id FROM read_log WHERE book_id=%s AND book_source=%s AND user_id=%s AND date_read=%s",
                (book_id, book_source, user_id, date_read),
            )
            existing = cur.fetchone()
            if existing:
                return {"id": existing["id"], "date_read": date_read, "source": source}
        cur.execute(
            "INSERT INTO read_log (book_id, book_source, user_id, date_read, source) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING id",
            (book_id, book_source, user_id, date_read, source),
        )
        rid = cur.fetchone()["id"]
        conn.commit()
        return {"id": rid, "date_read": date_read, "source": source}
    finally:
        conn.close()


def update(entry_id: int, user_id: int, date_read) -> bool:
    """Adjust a date. Scoped to the owning user. Returns True if a row changed."""
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE read_log SET date_read=%s WHERE id=%s AND user_id=%s",
            (date_read, entry_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete(entry_id: int, user_id: int) -> bool:
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM read_log WHERE id=%s AND user_id=%s", (entry_id, user_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
