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


from .pg_database import get_pg as _pg


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
    """Predicate: the book has a tag whose name is in the allow-list.

    Deliberately NON-correlated. The previous form was a correlated
    EXISTS(... WHERE _btl.book = b.id AND LOWER(name) IN (...)), which SQLite
    evaluated once per candidate row -- an index range on the link table plus
    a LOWER() per tag, for every row of a list, count or feed, and two to four
    times per page load for a restricted member. This shape resolves the
    allowed tag ids once, then the allowed book ids once (both materialised as
    ephemeral indexes), and the outer query is a plain IN lookup.
    Same semantics: allowed if ANY of the book's tags is on the list."""
    if allowed is None:
        return None, []
    qs = ",".join("?" * len(allowed))
    sql = (
        f"{alias}.id IN (SELECT _btl.book FROM books_tags_link _btl "
        f"WHERE _btl.tag IN (SELECT _t.id FROM tags _t WHERE LOWER(_t.name) IN ({qs})))"
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
