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
        from .pg_database import get_pg
        pg = get_pg()
        cur = pg.cursor()
        cur.execute(
            "SELECT has_digital, has_physical, physical_location FROM book_ownership WHERE book_id=%s AND book_source='calibre'",
            (book_id,)
        )
        r = cur.fetchone()
        pg.close()
        if r:
            ownership = {"has_digital": r["has_digital"], "has_physical": r["has_physical"], "physical_location": r["physical_location"]}
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug("ownership overlay unavailable: %s", e)
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
        date_added=(_parse_dt(row["timestamp"]) if "timestamp" in row.keys() else None),
        book_source="calibre",
        has_physical=ownership["has_physical"],
        has_digital=ownership["has_digital"],
        physical_location=ownership["physical_location"],
    )


# ── Batched builders ──────────────────────────────────────────────────────────
# row_to_summary / row_to_detail issue 4 (summary) or 8 (detail) point queries
# PER BOOK, plus a Postgres round trip each for detail. On a 100-book page that
# is 400 SQLite queries; on the iOS full sync (~7,000 books) it was ~56,000
# SQLite queries and 7,000 Postgres checkouts. These build the same models from
# one query per related table, chunked under SQLite's parameter limit.
#
# Contract: identical output to the per-row builders, field for field, in the
# same order -- the iOS app consumes these payloads verbatim. Verified by
# diffing both builders over the whole library.

_CHUNK = 500


def _chunks(ids):
    ids = list(ids)
    for i in range(0, len(ids), _CHUNK):
        yield ids[i:i + _CHUNK]


def _related(conn: sqlite3.Connection, book_ids) -> dict:
    """{book_id: {"authors": [...], "series": SeriesRef|None, "tags": [...],
                  "rating": float|None}} for every id (missing keys = empty)."""
    out = {bid: {"authors": [], "series": None, "tags": [], "rating": None} for bid in book_ids}
    for chunk in _chunks(book_ids):
        ph = ",".join("?" * len(chunk))
        # Same ORDER BY as the per-book queries, per book.
        for r in conn.execute(
            f"SELECT bal.book AS book, a.id, a.name, a.sort FROM books_authors_link bal "
            f"JOIN authors a ON a.id = bal.author WHERE bal.book IN ({ph}) ORDER BY bal.book, a.sort",
            chunk,
        ):
            out[r["book"]]["authors"].append(Author(id=r["id"], name=r["name"], sort=r["sort"]))
        for r in conn.execute(
            f"SELECT bsl.book AS book, s.id, s.name, b.series_index FROM books_series_link bsl "
            f"JOIN series s ON s.id = bsl.series JOIN books b ON b.id = bsl.book "
            f"WHERE bsl.book IN ({ph}) ORDER BY bsl.book, bsl.id",
            chunk,
        ):
            if out[r["book"]]["series"] is None:   # LIMIT 1 semantics
                out[r["book"]]["series"] = SeriesRef(id=r["id"], name=r["name"], series_index=r["series_index"])
        for r in conn.execute(
            f"SELECT btl.book AS book, t.id, t.name FROM books_tags_link btl "
            f"JOIN tags t ON t.id = btl.tag WHERE btl.book IN ({ph}) ORDER BY btl.book, t.name",
            chunk,
        ):
            out[r["book"]]["tags"].append(TagRef(id=r["id"], name=r["name"]))
        for r in conn.execute(
            f"SELECT brl.book AS book, r.rating FROM books_ratings_link brl "
            f"JOIN ratings r ON r.id = brl.rating WHERE brl.book IN ({ph}) ORDER BY brl.book, brl.id",
            chunk,
        ):
            if out[r["book"]]["rating"] is None and r["rating"] is not None:
                out[r["book"]]["rating"] = r["rating"] / 2.0
    return out


def _related_detail(conn: sqlite3.Connection, book_ids) -> dict:
    """{book_id: {"comment", "publisher", "isbn", "formats": [...]}}."""
    out = {bid: {"comment": None, "publisher": None, "isbn": None, "formats": []} for bid in book_ids}
    for chunk in _chunks(book_ids):
        ph = ",".join("?" * len(chunk))
        for r in conn.execute(f"SELECT book, text FROM comments WHERE book IN ({ph}) ORDER BY book, id", chunk):
            if out[r["book"]]["comment"] is None:
                out[r["book"]]["comment"] = r["text"]
        for r in conn.execute(
            f"SELECT bpl.book AS book, p.name FROM books_publishers_link bpl "
            f"JOIN publishers p ON p.id = bpl.publisher WHERE bpl.book IN ({ph}) ORDER BY bpl.book, bpl.id",
            chunk,
        ):
            if out[r["book"]]["publisher"] is None:
                out[r["book"]]["publisher"] = r["name"]
        for r in conn.execute(
            f"SELECT book, val FROM identifiers WHERE type = 'isbn' AND book IN ({ph}) ORDER BY book, id", chunk
        ):
            if out[r["book"]]["isbn"] is None:
                out[r["book"]]["isbn"] = r["val"]
        for r in conn.execute(
            f"SELECT book, format, uncompressed_size FROM data WHERE book IN ({ph}) ORDER BY book, format", chunk
        ):
            out[r["book"]]["formats"].append(FormatRef(format=r["format"], size=r["uncompressed_size"]))
    return out


def fetch_ownership_map(book_ids) -> dict:
    """{book_id: ownership dict} from Postgres in one query; {} if unavailable.
    Raises nothing -- callers decide whether a missing map is acceptable."""
    ids = list(book_ids)
    if not ids:
        return {}
    from .pg_database import get_pg
    pg = get_pg()
    try:
        cur = pg.cursor()
        cur.execute(
            "SELECT book_id, has_digital, has_physical, physical_location "
            "FROM book_ownership WHERE book_id = ANY(%s) AND book_source='calibre'",
            (ids,),
        )
        return {r["book_id"]: {"has_digital": r["has_digital"], "has_physical": r["has_physical"],
                               "physical_location": r["physical_location"]} for r in cur.fetchall()}
    finally:
        pg.close()


def summaries_for_rows(conn: sqlite3.Connection, rows, base_url: str, ownership_map: dict | None = None) -> list[BookSummary]:
    """Batched equivalent of [row_to_summary(conn, r, base_url, own.get(r['id'])) for r in rows]."""
    rows = list(rows)
    ids = [r["id"] for r in rows]
    rel = _related(conn, ids)
    ownership_map = ownership_map or {}
    default = {"has_digital": True, "has_physical": False, "physical_location": None}
    out = []
    for row in rows:
        bid = row["id"]
        has_cover = bool(row["has_cover"])
        own = ownership_map.get(bid) or default
        x = rel[bid]
        out.append(BookSummary(
            id=bid,
            title=row["title"],
            sort=row["sort"],
            authors=x["authors"],
            series=x["series"],
            tags=x["tags"],
            pubdate=_parse_dt(row["pubdate"]),
            last_modified=_parse_dt(row["last_modified"]),
            has_cover=has_cover,
            cover_url=f"{base_url}/api/covers/{bid}" if has_cover else None,
            rating=x["rating"],
            book_source="calibre",
            has_physical=own["has_physical"],
            has_digital=own["has_digital"],
            physical_location=own["physical_location"],
        ))
    return out


def details_for_rows(conn: sqlite3.Connection, rows, base_url: str, ownership_map: dict) -> list[BookDetail]:
    """Batched equivalent of [row_to_detail(conn, r, base_url) for r in rows].
    `ownership_map` is REQUIRED (from fetch_ownership_map): the per-row builder
    silently substituted defaults when Postgres failed; callers of this one
    decide that explicitly."""
    rows = list(rows)
    ids = [r["id"] for r in rows]
    rel = _related(conn, ids)
    det = _related_detail(conn, ids)
    default = {"has_digital": True, "has_physical": False, "physical_location": None}
    out = []
    for row in rows:
        bid = row["id"]
        has_cover = bool(row["has_cover"])
        own = ownership_map.get(bid) or default
        x, d = rel[bid], det[bid]
        out.append(BookDetail(
            id=bid,
            title=row["title"],
            sort=row["sort"],
            authors=x["authors"],
            series=x["series"],
            tags=x["tags"],
            pubdate=_parse_dt(row["pubdate"]),
            last_modified=_parse_dt(row["last_modified"]),
            has_cover=has_cover,
            cover_url=f"{base_url}/api/covers/{bid}" if has_cover else None,
            rating=x["rating"],
            comment=d["comment"],
            publisher=d["publisher"],
            isbn=d["isbn"],
            uuid=row["uuid"],
            formats=d["formats"],
            path=row["path"],
            series_index=row["series_index"],
            date_added=(_parse_dt(row["timestamp"]) if "timestamp" in row.keys() else None),
            book_source="calibre",
            has_physical=own["has_physical"],
            has_digital=own["has_digital"],
            physical_location=own["physical_location"],
        ))
    return out


def native_cover_url(base_url: str, nb: dict) -> str:
    """THE cover URL for a native book -- every serializer (library, shelves,
    search, detail) uses this one. Always our own endpoint (it serves uploaded,
    downloaded and generated covers alike; the raw `cover_url` column can be a
    `manual:` marker or a third-party URL, neither of which a client can load),
    and versioned by the persisted `cover_rev`, which changes whenever the image
    a client would see changes -- so covers can be cached hard and still update
    the moment they are replaced."""
    return f"{base_url}/api/native/books/{nb['id']}/cover?v={nb.get('cover_rev') or 0}"
