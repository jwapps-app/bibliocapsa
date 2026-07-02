"""
Per-member content access control (genre allow-list).

A member can be restricted to a set of genres (Calibre tag names / native
category names). Visibility rule: a book is allowed if ANY of its genres is in
the member's allow-list. Admins, and members with no rows, are unrestricted.

`get_restriction(user)` returns:
  * None        → unrestricted (show everything)
  * set[str]    → restrict to these (lowercased) genres  (never an empty set)

The SQL helpers return (predicate, params) fragments to AND into a WHERE clause,
or (None, []) when unrestricted — callers skip them in that case.
"""

from typing import Optional


def _pg():
    from .pg_database import get_pg
    return get_pg()


def get_restriction(user: Optional[dict]) -> Optional[set]:
    if not user:
        # Should not happen on guarded routes (middleware sets request.state.user).
        return None
    if user.get("role") == "admin":
        return None
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("SELECT genre FROM user_genre_access WHERE user_id = %s", (user["id"],))
        genres = {r["genre"].lower() for r in cur.fetchall() if r["genre"]}
    finally:
        conn.close()
    return genres or None  # no rows → unrestricted


def restriction_for_request(request) -> Optional[set]:
    user = getattr(request.state, "user", None)
    return get_restriction(user)


# ── Calibre (SQLite) ──────────────────────────────────────────────────────────
def calibre_predicate(allowed: Optional[set], alias: str = "b"):
    """EXISTS clause: the book has a tag whose name is in the allow-list."""
    if allowed is None:
        return None, []
    qs = ",".join("?" * len(allowed))
    sql = (
        f"EXISTS (SELECT 1 FROM books_tags_link _btl JOIN tags _t ON _t.id = _btl.tag "
        f"WHERE _btl.book = {alias}.id AND LOWER(_t.name) IN ({qs}))"
    )
    return sql, list(allowed)


def is_calibre_book_allowed(conn, book_id: int, allowed: Optional[set]) -> bool:
    if allowed is None:
        return True
    qs = ",".join("?" * len(allowed))
    row = conn.execute(
        f"SELECT 1 FROM books_tags_link btl JOIN tags t ON t.id = btl.tag "
        f"WHERE btl.book = ? AND LOWER(t.name) IN ({qs}) LIMIT 1",
        [book_id, *allowed],
    ).fetchone()
    return row is not None


def filter_calibre_ids(conn, ids, allowed: Optional[set]) -> set:
    """Return the subset of `ids` that carry an allowed genre."""
    if allowed is None:
        return set(ids)
    if not ids:
        return set()
    id_qs = ",".join("?" * len(ids))
    g_qs = ",".join("?" * len(allowed))
    rows = conn.execute(
        f"SELECT DISTINCT btl.book FROM books_tags_link btl JOIN tags t ON t.id = btl.tag "
        f"WHERE btl.book IN ({id_qs}) AND LOWER(t.name) IN ({g_qs})",
        [*ids, *allowed],
    ).fetchall()
    return {r[0] for r in rows}


# ── Native (PostgreSQL) ───────────────────────────────────────────────────────
def native_predicate(allowed: Optional[set]):
    """EXISTS clause: a native book's categories overlap the allow-list."""
    if allowed is None:
        return None, []
    sql = "EXISTS (SELECT 1 FROM unnest(categories) _c WHERE LOWER(_c) = ANY(%s))"
    return sql, [list(allowed)]


def is_native_allowed(categories, allowed: Optional[set]) -> bool:
    if allowed is None:
        return True
    if not categories:
        return False
    return any((c or "").lower() in allowed for c in categories)
