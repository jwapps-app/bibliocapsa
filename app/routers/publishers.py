"""Publisher names — for autocomplete in smart-shelf rules and the add-book form."""

from fastapi import APIRouter, Query, Request
from ..database import get_conn

router = APIRouter()


@router.get("", summary="List publisher names (for autocomplete)")
def list_publishers(request: Request, page_size: int = Query(5000, ge=1, le=10000)):
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT p.name, COUNT(bpl.book) AS book_count
               FROM publishers p
               LEFT JOIN books_publishers_link bpl ON bpl.publisher = p.id
               GROUP BY p.id ORDER BY p.name ASC LIMIT ?""",
            (page_size,),
        ).fetchall()
        return [{"name": r["name"], "book_count": r["book_count"]} for r in rows]
