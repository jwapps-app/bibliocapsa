"""Tags / genres endpoints."""

from fastapi import APIRouter, Query, Request
from typing import Optional
from ..database import get_conn
from ..schemas import TagDetail
from .. import access, ttlcache

router = APIRouter()


@router.get("", response_model=list[TagDetail], summary="List all tags")
def list_tags(
    request: Request,
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=5000),
):
    allowed = access.restriction_for_request(request)
    key = ("tags", ttlcache.calibre_marker(), ttlcache.allowed_key(allowed), search, page, page_size)
    return ttlcache.get_or_set(key, 60, lambda: _list_tags(allowed, search, page, page_size))


def _list_tags(allowed, search, page, page_size):
    with get_conn() as conn:
        conditions = ["1=1"]
        params: list = []
        if search:
            conditions.append("t.name LIKE ?")
            params.append(f"%{search}%")

        # Restricted members only see their allowed genres.
        if allowed is not None:
            qs = ",".join("?" * len(allowed))
            conditions.append(f"LOWER(t.name) IN ({qs})")
            params += list(allowed)

        where = " AND ".join(conditions)
        offset = (page - 1) * page_size

        rows = conn.execute(
            f"""
            SELECT t.id, t.name, COUNT(btl.book) as book_count
            FROM tags t
            LEFT JOIN books_tags_link btl ON btl.tag = t.id
            WHERE {where}
            GROUP BY t.id
            ORDER BY t.name ASC
            LIMIT ? OFFSET ?
            """,
            params + [page_size, offset],
        ).fetchall()

        return [
            TagDetail(id=r["id"], name=r["name"], book_count=r["book_count"])
            for r in rows
        ]
