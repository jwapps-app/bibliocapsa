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


from .pg_database import get_pg as _pg


def get_status(book_id: int) -> dict:
    """{'status': 'read'|'reading'|None, 'date_read': str|None} for one book --
    the same effective answer every list, filter and shelf gives (see
    `effective`)."""
    return effective([book_id]).get(book_id) or {"status": None, "date_read": None}


def _truthy(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y")
    return bool(v)


def effective(book_ids) -> dict:
    """{book_id: {'status', 'date_read'}} -- THE read status of each book, for
    every endpoint. Books with no status at all are absent. `None` = whole library.

    Precedence, in one place so the detail page, lists, filters, shelves and
    Currently Reading can never disagree:
      1. The mapped Calibre read column, *as it will be after the pending edits
         land* (see calibre_column_statuses). True there means read, and its
         date fills in when our own record has none.
      2. Otherwise Bibliocapsa's own record (read / reading).
    Marking a book unread or reading queues "read column = No", so that choice
    shows immediately and survives a restart even while Calibre still says Yes
    (sync off, failing, or simply not run yet)."""
    ids = None if book_ids is None else [int(i) for i in book_ids]
    if ids is not None and not ids:
        return {}
    own = statuses(ids)
    col = calibre_column_statuses(ids)
    out: dict = {}
    for bid in (ids if ids is not None else set(own) | set(col)):
        st, c = own.get(bid), col.get(bid)
        if c:
            date = (st or {}).get("date_read") if (st or {}).get("status") == "read" else None
            out[bid] = {"status": "read", "date_read": date or c.get("date_read")}
        elif st and st.get("status"):
            out[bid] = {"status": st["status"], "date_read": st.get("date_read")}
    return out


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
    read (bool) + date columns, for books whose read flag is true -- with the
    pending (not yet synced) edits to those columns applied on top. `None` means
    the whole library. {} if no read column is mapped."""
    ids = None if book_ids is None else [int(i) for i in book_ids]
    if ids is not None and not ids:
        return {}
    try:
        from .routers.settings import get_setting
        col_read = get_setting("reading_col_read")
        if not col_read:
            return {}
        from .database import get_conn
        from . import calibre_overlay as overlay
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
            scope = "" if ids is None else " AND book IN (" + ",".join(str(i) for i in ids) + ")"
            reads = {r["book"] for r in cal.execute(
                f"SELECT book FROM custom_column_{rcid} WHERE value=1{scope}").fetchall()}
            dates = {}
            if dcid:
                for r in cal.execute(
                        f"SELECT book, value FROM custom_column_{dcid} WHERE value IS NOT NULL{scope}").fetchall():
                    dates[r["book"]] = str(r["value"])[:10] if r["value"] else None
        # Pending edits are part of the truth: a queued "No" means the user
        # already un-read the book here, a queued "Yes"/date means they read
        # it -- whether or not Calibre has been told yet.
        wanted = None if ids is None else set(ids)
        for bid, v in overlay.field_edits(f"custom:{col_read}").items():
            if wanted is None or bid in wanted:
                (reads.add if _truthy(v) else reads.discard)(bid)
        if col_date:
            for bid, v in overlay.field_edits(f"custom:{col_date}").items():
                if wanted is None or bid in wanted:
                    dates[bid] = str(v)[:10] if v else None
        return {bid: {"status": "read", "date_read": dates.get(bid)} for bid in reads}
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug("calibre column statuses unavailable: %s", e)
        return {}


def read_book_ids(book_ids) -> set:
    """The subset of `book_ids` that are effectively 'read'."""
    return {bid for bid, st in effective(book_ids).items() if st["status"] == "read"}


def library_owner_id():
    """The account the SHARED read state belongs to.

    Calibre has one read column and one date per book, so that state can only
    describe one person's reading: the library owner -- the first account, which
    is also who a Goodreads import's history is credited to. Everyone else's
    personal views (Currently Reading, goals, year in review) come from their
    own read log and progress only. Override with the `reading_owner_user_id`
    setting."""
    try:
        from .routers.settings import get_setting
        v = get_setting("reading_owner_user_id")
        if v and str(v).isdigit():
            return int(v)
    except Exception:
        pass
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE password_hash IS NOT NULL ORDER BY id LIMIT 1")
        r = cur.fetchone()
        return r["id"] if r else None
    finally:
        conn.close()


def others_only_logged(user_id, book_ids) -> set:
    """Calibre books whose finishes were logged by OTHER accounts and never by
    `user_id` -- i.e. shared read marks that are somebody else's reading."""
    ids = [int(i) for i in (book_ids or [])]
    if not ids:
        return set()
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT book_id, BOOL_OR(user_id = %s) AS mine FROM read_log "
            "WHERE book_source = 'calibre' AND book_id = ANY(%s) GROUP BY book_id",
            (user_id, ids))
        return {r["book_id"] for r in cur.fetchall() if not r["mine"]}
    finally:
        conn.close()


def finished_for(user_id, progress: dict) -> set:
    """Which of a user's in-progress Calibre books THEY have finished.
    `progress` maps book_id -> epoch seconds of their latest progress update.

    Personal, not library-wide: another person marking a book read must not pull
    it out of this user's Currently Reading.
      * Anyone: a finish in their own read log, dated on/after their latest
        progress (an older finish + newer progress is a reread in flight).
      * The library owner additionally: the shared read state, except marks that
        only other accounts logged."""
    from datetime import datetime
    ids = [int(i) for i in progress]
    if not ids or not user_id:
        return set()
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT book_id, MAX(date_read) AS last FROM read_log "
            "WHERE user_id = %s AND book_source = 'calibre' AND book_id = ANY(%s) GROUP BY book_id",
            (user_id, ids))
        mine = {r["book_id"]: (r["last"] or "") for r in cur.fetchall()}
    finally:
        conn.close()
    out = set()
    for bid, last in mine.items():
        ts = progress.get(bid)
        day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else ""
        if last and last[:10] >= day:
            out.add(bid)
    if user_id == library_owner_id():
        shared = read_book_ids(ids)
        out |= shared - others_only_logged(user_id, shared)
    return out


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
        from . import changes
        changes.touch([book_id], cur)
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
            from . import calibre_sync
            calibre_sync.queue_auto_sync(book_id)
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
