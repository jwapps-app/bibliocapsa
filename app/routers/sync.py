"""
Delta sync endpoint for the Bibliocapsa iOS app.
GET /api/sync?since=<ISO8601>
Returns all books modified after the given timestamp.
On first sync (no since param), returns everything.
"""

from fastapi import APIRouter, Query, Request
from typing import Optional
from datetime import datetime, timezone
from ..database import get_conn
from ..schemas import SyncResponse
from ..queries import row_to_detail
from .. import access

router = APIRouter()


@router.get("", response_model=SyncResponse, summary="Delta sync for iOS app")
def sync(
    request: Request,
    since: Optional[datetime] = Query(
        None,
        description="ISO 8601 timestamp. Returns books modified after this time. "
                    "Omit for full sync.",
    ),
):
    base_url = str(request.base_url).rstrip("/")
    now = datetime.now(tz=timezone.utc)

    # Honor per-member genre restrictions (same as every other listing endpoint).
    allowed = access.restriction_for_request(request)
    conds, params = [], []
    if since:
        conds.append("datetime(b.last_modified) > datetime(?)")
        params.append(since.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    if allowed is not None:
        pred, pp = access.calibre_predicate(allowed, "b")
        conds.append(pred)
        params += list(pp)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""

    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT b.id, b.title, b.sort, b.pubdate, b.last_modified,
                   b.has_cover, b.uuid, b.path, b.series_index, b.author_sort
            FROM books b {where}
            ORDER BY b.last_modified ASC
            """,
            params,
        ).fetchall()

        items = [row_to_detail(conn, row, base_url) for row in rows]

    return SyncResponse(
        since=since,
        until=now,
        total=len(items),
        items=items,
    )
