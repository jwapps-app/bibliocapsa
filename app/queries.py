"""
Query helpers that translate Calibre's schema into API models.
All queries are SELECT-only. The read-only connection makes writes impossible,
but we also never attempt them.
"""

import sqlite3
from typing import Optional
from datetime import datetime, timezone
from .schemas import (
    Author, SeriesRef, TagRef, FormatRef,
    BookSummary, BookDetail,
)


def _parse_dt(val) -> Optional[datetime]:
    if not val:
        return None
    if isinstance(val, datetime):
        return val
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            dt = datetime.strptime(str(val), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def fetch_authors_for_book(conn: sqlite3.Connection, book_id: int) -> list[Author]:
    rows = conn.execute(
        """
        SELECT a.id, a.name, a.sort
        FROM authors a
        JOIN books_authors_link bal ON bal.author = a.id
        WHERE bal.book = ?
        ORDER BY a.sort
        """,
        (book_id,),
    ).fetchall()
    return [Author(id=r["id"], name=r["name"], sort=r["sort"]) for r in rows]


def fetch_series_for_book(conn: sqlite3.Connection, book_id: int) -> Optional[SeriesRef]:
    row = conn.execute(
        """
        SELECT s.id, s.name, b.series_index
        FROM series s
        JOIN books_series_link bsl ON bsl.series = s.id
        JOIN books b ON b.id = bsl.book
        WHERE bsl.book = ?
        LIMIT 1
        """,
        (book_id,),
    ).fetchone()
    if row:
        return SeriesRef(id=row["id"], name=row["name"], series_index=row["series_index"])
    return None


def fetch_tags_for_book(conn: sqlite3.Connection, book_id: int) -> list[TagRef]:
    rows = conn.execute(
        """
        SELECT t.id, t.name
        FROM tags t
        JOIN books_tags_link btl ON btl.tag = t.id
        WHERE btl.book = ?
        ORDER BY t.name
        """,
        (book_id,),
    ).fetchall()
    return [TagRef(id=r["id"], name=r["name"]) for r in rows]


def fetch_formats_for_book(conn: sqlite3.Connection, book_id: int) -> list[FormatRef]:
    rows = conn.execute(
        "SELECT format, uncompressed_size FROM data WHERE book = ? ORDER BY format",
        (book_id,),
    ).fetchall()
    return [FormatRef(format=r["format"], size=r["uncompressed_size"]) for r in rows]


def fetch_comment_for_book(conn: sqlite3.Connection, book_id: int) -> Optional[str]:
    row = conn.execute(
        "SELECT text FROM comments WHERE book = ? LIMIT 1", (book_id,)
    ).fetchone()
    return row["text"] if row else None


def fetch_rating_for_book(conn: sqlite3.Connection, book_id: int) -> Optional[float]:
    row = conn.execute(
        """
        SELECT r.rating FROM ratings r
        JOIN books_ratings_link brl ON brl.rating = r.id
        WHERE brl.book = ?
        LIMIT 1
        """,
        (book_id,),
    ).fetchone()
    if row and row["rating"] is not None:
        return row["rating"] / 2.0  # Calibre stores 0-10; normalize to 0-5
    return None


def fetch_publisher_for_book(conn: sqlite3.Connection, book_id: int) -> Optional[str]:
    row = conn.execute(
        """
        SELECT p.name FROM publishers p
        JOIN books_publishers_link bpl ON bpl.publisher = p.id
        WHERE bpl.book = ?
        LIMIT 1
        """,
        (book_id,),
    ).fetchone()
    return row["name"] if row else None


def fetch_identifier(conn: sqlite3.Connection, book_id: int, id_type: str) -> Optional[str]:
    row = conn.execute(
        "SELECT val FROM identifiers WHERE book = ? AND type = ? LIMIT 1",
        (book_id, id_type),
    ).fetchone()
    return row["val"] if row else None


def row_to_summary(conn: sqlite3.Connection, row: sqlite3.Row, base_url: str, ownership: dict | None = None) -> BookSummary:
    book_id = row["id"]
    has_cover = bool(row["has_cover"])
    if ownership is None:
        ownership = {"has_digital": True, "has_physical": False, "physical_location": None}
    return BookSummary(
        id=book_id,
        title=row["title"],
        sort=row["sort"],
        authors=fetch_authors_for_book(conn, book_id),
        series=fetch_series_for_book(conn, book_id),
        tags=fetch_tags_for_book(conn, book_id),
        pubdate=_parse_dt(row["pubdate"]),
        last_modified=_parse_dt(row["last_modified"]),
        has_cover=has_cover,
        cover_url=f"{base_url}/api/covers/{book_id}" if has_cover else None,
        rating=fetch_rating_for_book(conn, book_id),
        book_source="calibre",
        has_physical=ownership["has_physical"],
        has_digital=ownership["has_digital"],
        physical_location=ownership["physical_location"],
    )


def row_to_detail(conn: sqlite3.Connection, row: sqlite3.Row, base_url: str) -> BookDetail:
    book_id = row["id"]
    has_cover = bool(row["has_cover"])
    ownership = {"has_digital": True, "has_physical": False, "physical_location": None}
    try:
        from .pg_database import get_database_url
        import psycopg2
        from psycopg2.extras import RealDictCursor
        pg = psycopg2.connect(get_database_url(), cursor_factory=RealDictCursor)
        cur = pg.cursor()
        cur.execute(
            "SELECT has_digital, has_physical, physical_location FROM book_ownership WHERE book_id=%s AND book_source='calibre'",
            (book_id,)
        )
        r = cur.fetchone()
        pg.close()
        if r:
            ownership = {"has_digital": r["has_digital"], "has_physical": r["has_physical"], "physical_location": r["physical_location"]}
    except Exception:
        pass
    return BookDetail(
        id=book_id,
        title=row["title"],
        sort=row["sort"],
        authors=fetch_authors_for_book(conn, book_id),
        series=fetch_series_for_book(conn, book_id),
        tags=fetch_tags_for_book(conn, book_id),
        pubdate=_parse_dt(row["pubdate"]),
        last_modified=_parse_dt(row["last_modified"]),
        has_cover=has_cover,
        cover_url=f"{base_url}/api/covers/{book_id}" if has_cover else None,
        rating=fetch_rating_for_book(conn, book_id),
        comment=fetch_comment_for_book(conn, book_id),
        publisher=fetch_publisher_for_book(conn, book_id),
        isbn=fetch_identifier(conn, book_id, "isbn"),
        uuid=row["uuid"],
        formats=fetch_formats_for_book(conn, book_id),
        path=row["path"],
        series_index=row["series_index"],
        book_source="calibre",
        has_physical=ownership["has_physical"],
        has_digital=ownership["has_digital"],
        physical_location=ownership["physical_location"],
    )
