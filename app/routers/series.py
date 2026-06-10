"""Series endpoints — the killer feature missing from OPDS."""

from fastapi import APIRouter, Query, HTTPException, Request
from typing import Optional
from pydantic import BaseModel
from ..database import get_conn
from ..schemas import SeriesDetail
from ..queries import row_to_summary
from .. import access

router = APIRouter()


class SeriesSummary(BaseModel):
    id: int
    name: str
    book_count: int
    first_book_id: Optional[int] = None
    first_book_cover_url: Optional[str] = None
    first_book_has_cover: bool = False


@router.get("/next-index", summary="Suggested next series index (max in series + 1)")
def series_next_index(name: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MAX(b.series_index) AS mx FROM books b "
            "JOIN books_series_link bsl ON bsl.book = b.id "
            "JOIN series s ON s.id = bsl.series WHERE LOWER(s.name) = LOWER(?)",
            (name,),
        ).fetchone()
    mx = row["mx"] if row else None
    return {"next_index": (int(mx) + 1) if mx is not None else 1}


@router.get("", response_model=list[SeriesSummary], summary="List all series with cover thumbnails")
def list_series(
    request: Request,
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=5000),
):
    base_url = str(request.base_url).rstrip("/")
    allowed = access.restriction_for_request(request)
    offset = (page - 1) * page_size
    with get_conn() as conn:
        search_clause = "s.name LIKE ?" if search else "1=1"
        search_params = [f"%{search}%"] if search else []

        if allowed is None:
            rows = conn.execute(
                f"""
                SELECT s.id, s.name, COUNT(bsl.book) as book_count,
                       (SELECT b.id FROM books b
                        JOIN books_series_link bsl2 ON bsl2.book = b.id
                        WHERE bsl2.series = s.id
                        ORDER BY b.series_index ASC, b.sort ASC
                        LIMIT 1) as first_book_id,
                       (SELECT b.has_cover FROM books b
                        JOIN books_series_link bsl2 ON bsl2.book = b.id
                        WHERE bsl2.series = s.id
                        ORDER BY b.series_index ASC, b.sort ASC
                        LIMIT 1) as first_book_has_cover
                FROM series s
                LEFT JOIN books_series_link bsl ON bsl.series = s.id
                WHERE {search_clause}
                GROUP BY s.id
                ORDER BY s.name ASC
                LIMIT ? OFFSET ?
                """,
                search_params + [page_size, offset],
            ).fetchall()
        else:
            # Restricted: count only allowed books, pick an allowed cover, and
            # hide series that contain no allowed books.
            pred, pp = access.calibre_predicate(allowed, "b")
            rows = conn.execute(
                f"""
                SELECT s.id, s.name,
                       (SELECT COUNT(*) FROM books b JOIN books_series_link bsl ON bsl.book=b.id
                        WHERE bsl.series=s.id AND {pred}) as book_count,
                       (SELECT b.id FROM books b JOIN books_series_link bsl ON bsl.book=b.id
                        WHERE bsl.series=s.id AND {pred}
                        ORDER BY b.series_index ASC, b.sort ASC LIMIT 1) as first_book_id,
                       (SELECT b.has_cover FROM books b JOIN books_series_link bsl ON bsl.book=b.id
                        WHERE bsl.series=s.id AND {pred}
                        ORDER BY b.series_index ASC, b.sort ASC LIMIT 1) as first_book_has_cover
                FROM series s
                WHERE {search_clause}
                  AND EXISTS (SELECT 1 FROM books b JOIN books_series_link bsl ON bsl.book=b.id
                              WHERE bsl.series=s.id AND {pred})
                ORDER BY s.name ASC
                LIMIT ? OFFSET ?
                """,
                pp + pp + pp + search_params + pp + [page_size, offset],
            ).fetchall()

        result = []
        for r in rows:
            first_id = r["first_book_id"]
            has_cover = bool(r["first_book_has_cover"])
            result.append(SeriesSummary(
                id=r["id"],
                name=r["name"],
                book_count=r["book_count"],
                first_book_id=first_id,
                first_book_has_cover=has_cover,
                first_book_cover_url=f"{base_url}/api/covers/{first_id}" if first_id and has_cover else None,
            ))
        return result


@router.get("/{series_id}", response_model=SeriesDetail, summary="Get series with ordered books")
def get_series(series_id: int, request: Request):
    base_url = str(request.base_url).rstrip("/")
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT s.id, s.name, COUNT(bsl.book) as book_count
            FROM series s
            LEFT JOIN books_series_link bsl ON bsl.series = s.id
            WHERE s.id = ?
            GROUP BY s.id
            """,
            (series_id,),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Series {series_id} not found")

        book_rows = conn.execute(
            """
            SELECT b.id, b.title, b.sort, b.pubdate, b.last_modified,
                   b.has_cover, b.uuid, b.path, b.series_index, b.author_sort
            FROM books b
            JOIN books_series_link bsl ON bsl.book = b.id
            WHERE bsl.series = ?
            ORDER BY b.series_index ASC, b.sort ASC
            """,
            (series_id,),
        ).fetchall()

        allowed = access.restriction_for_request(request)
        if allowed is not None:
            book_rows = [br for br in book_rows
                         if access.is_calibre_book_allowed(conn, br["id"], allowed)]
            if not book_rows:
                raise HTTPException(status_code=404, detail=f"Series {series_id} not found")

        books = [row_to_summary(conn, br, base_url) for br in book_rows]

        return SeriesDetail(
            id=row["id"],
            name=row["name"],
            book_count=len(books) if allowed is not None else row["book_count"],
            books=books,
        )
