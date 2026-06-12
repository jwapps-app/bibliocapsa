"""Authors endpoints."""

from fastapi import APIRouter, Query, HTTPException, Request
from typing import Optional
from ..database import get_conn
from ..schemas import Author, AuthorDetail
from ..queries import row_to_summary
from .. import access

router = APIRouter()


@router.get("", response_model=list[Author], summary="List all authors")
def list_authors(
    request: Request,
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=5000),
):
    allowed = access.restriction_for_request(request)
    offset = (page - 1) * page_size
    with get_conn() as conn:
        search_clause = "a.name LIKE ?" if search else "1=1"
        search_params = [f"%{search}%"] if search else []

        if allowed is None:
            rows = conn.execute(
                f"""
                SELECT a.id, a.name, a.sort, COUNT(bal.book) as book_count
                FROM authors a
                LEFT JOIN books_authors_link bal ON bal.author = a.id
                WHERE {search_clause}
                GROUP BY a.id
                ORDER BY a.sort ASC
                LIMIT ? OFFSET ?
                """,
                search_params + [page_size, offset],
            ).fetchall()
        else:
            # Restricted: count only allowed books; hide authors with none.
            pred, pp = access.calibre_predicate(allowed, "b")
            rows = conn.execute(
                f"""
                SELECT a.id, a.name, a.sort,
                       (SELECT COUNT(*) FROM books b JOIN books_authors_link bal ON bal.book=b.id
                        WHERE bal.author=a.id AND {pred}) as book_count
                FROM authors a
                WHERE {search_clause}
                  AND EXISTS (SELECT 1 FROM books b JOIN books_authors_link bal ON bal.book=b.id
                              WHERE bal.author=a.id AND {pred})
                ORDER BY a.sort ASC
                LIMIT ? OFFSET ?
                """,
                pp + search_params + pp + [page_size, offset],
            ).fetchall()

        return [
            Author(id=r["id"], name=r["name"], sort=r["sort"], book_count=r["book_count"])
            for r in rows
        ]


@router.get("/{author_id}", response_model=AuthorDetail, summary="Get author with their books")
def get_author(author_id: int, request: Request):
    base_url = str(request.base_url).rstrip("/")
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT a.id, a.name, a.sort, COUNT(bal.book) as book_count
            FROM authors a
            LEFT JOIN books_authors_link bal ON bal.author = a.id
            WHERE a.id = ?
            GROUP BY a.id
            """,
            (author_id,),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Author {author_id} not found")

        book_rows = conn.execute(
            """
            SELECT b.id, b.title, b.sort, b.pubdate, b.last_modified,
                   b.has_cover, b.uuid, b.path, b.series_index, b.author_sort
            FROM books b
            JOIN books_authors_link bal ON bal.book = b.id
            WHERE bal.author = ?
            ORDER BY b.sort ASC
            """,
            (author_id,),
        ).fetchall()

        allowed = access.restriction_for_request(request)
        if allowed is not None:
            book_rows = [br for br in book_rows
                         if access.is_calibre_book_allowed(conn, br["id"], allowed)]
            if not book_rows:
                raise HTTPException(status_code=404, detail=f"Author {author_id} not found")

        books = [row_to_summary(conn, br, base_url) for br in book_rows]

        return AuthorDetail(
            id=row["id"],
            name=row["name"],
            sort=row["sort"],
            book_count=len(books) if allowed is not None else row["book_count"],
            books=books,
        )
