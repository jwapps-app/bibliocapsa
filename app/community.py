"""Community (Hardcover) ratings for Calibre books, stored in Postgres and
captured opportunistically during Hardcover lookups (bulk enrich + the per-book
metadata picker)."""

from .calibre_overlay import _pg


def set_calibre_rating(book_id: int, rating) -> None:
    if rating is None:
        return
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO calibre_community_rating (book_id, rating, updated_at) VALUES (%s, %s, NOW()) "
            "ON CONFLICT (book_id) DO UPDATE SET rating = EXCLUDED.rating, updated_at = NOW()",
            (book_id, float(rating)),
        )
        conn.commit()
    finally:
        conn.close()


def get_calibre_ratings(book_ids: list) -> dict:
    if not book_ids:
        return {}
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("SELECT book_id, rating FROM calibre_community_rating WHERE book_id = ANY(%s)", (list(book_ids),))
        return {r["book_id"]: r["rating"] for r in cur.fetchall()}
    finally:
        conn.close()
