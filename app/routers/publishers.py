"""Publisher names — for autocomplete in smart-shelf rules and the add-book form."""

from fastapi import APIRouter, Query, Request
from ..database import get_conn
from .. import access

router = APIRouter()


@router.get("", summary="List publisher names (for autocomplete)")
def list_publishers(request: Request, page_size: int = Query(5000, ge=1, le=10000)):
    allowed = access.restriction_for_request(request)
    with get_conn() as conn:
        if allowed is None:
            rows = conn.execute(
                """SELECT p.name, COUNT(bpl.book) AS book_count
                   FROM publishers p
                   LEFT JOIN books_publishers_link bpl ON bpl.publisher = p.id
                   GROUP BY p.id ORDER BY p.name ASC LIMIT ?""",
                (page_size,),
            ).fetchall()
        else:
            # Restricted members: only publishers that have at least one book
            # they're allowed to see, counting only those books.
            pred, params = access.calibre_predicate(allowed, "b")
            rows = conn.execute(
                f"""SELECT p.name, COUNT(b.id) AS book_count
                    FROM publishers p
                    JOIN books_publishers_link bpl ON bpl.publisher = p.id
                    JOIN books b ON b.id = bpl.book
                    WHERE {pred}
                    GROUP BY p.id ORDER BY p.name ASC LIMIT ?""",
                params + [page_size],
            ).fetchall()
        return [{"name": r["name"], "book_count": r["book_count"]} for r in rows]
