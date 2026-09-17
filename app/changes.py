"""
Application change journal for Calibre books.

The iOS delta sync asks "what changed since T?", and the only clock it had was
Calibre's own `last_modified`. But part of what a synced book carries lives in
PostgreSQL -- physical ownership and location, and metadata edits still waiting
to reach Calibre -- and changing those never moves Calibre's clock. A client
syncing incrementally therefore never heard about them.

`calibre_changes` holds one row per book: the last time any of that application
data changed. `/api/sync?since=` returns a book when EITHER clock is newer than
the cursor. Deletions and revoked access are covered separately by
`/api/sync/ids` (the full visible id list, which the client reconciles against).
"""

import logging

from .pg_database import get_pg as _pg

logger = logging.getLogger(__name__)


def touch(book_ids, cur=None) -> None:
    """Record that application data for these Calibre books just changed.

    Pass `cur` to journal inside the caller's transaction. Without it this is
    best-effort on its own connection: a failure here must never fail the edit
    that triggered it (the worst case is one client hearing about it late)."""
    ids = sorted({int(i) for i in (book_ids or [])})
    if not ids:
        return
    sql = ("INSERT INTO calibre_changes (book_id, changed_at) SELECT x, NOW() FROM unnest(%s::int[]) AS x "
           "ON CONFLICT (book_id) DO UPDATE SET changed_at = NOW()")
    if cur is not None:
        cur.execute(sql, (ids,))
        return
    try:
        conn = _pg()
        try:
            conn.cursor().execute(sql, (ids,))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning("change journal: could not record %d book(s): %s", len(ids), e)


def since(ts, overlap_seconds: int = 0) -> dict:
    """{book_id: changed_at (aware datetime)} for changes after `ts`. Raises if
    Postgres is unavailable -- the caller must not advance a sync cursor past
    changes it could not see."""
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT book_id, changed_at FROM calibre_changes "
            # Whole seconds, like the Calibre half of the comparison: a paged
            # cursor is "everything up to and including second S was sent", so
            # S.4 must not come back (it could refill the page and stall it).
            "WHERE date_trunc('second', changed_at) > %s - make_interval(secs => %s)", (ts, overlap_seconds))
        return {r["book_id"]: r["changed_at"] for r in cur.fetchall()}
    finally:
        conn.close()
