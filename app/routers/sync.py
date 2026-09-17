"""
Delta sync endpoint for the Bibliocapsa iOS app.
GET /api/sync?since=<ISO8601>
Returns all books modified after the given timestamp.
On first sync (no since param), returns everything.
"""

from fastapi import APIRouter, Query, Request, HTTPException
from typing import Optional
from datetime import datetime, timezone
from ..database import get_conn
from ..schemas import SyncResponse
from ..queries import details_for_rows, fetch_ownership_map
from .. import access
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/ids", summary="All visible Calibre book ids (deletion reconcile)")
def sync_ids(request: Request):
    """Every Calibre id the caller can see.

    The delta feed reports adds and changes but never deletions: it reads
    Calibre's `books` table, and a deleted book simply stops existing there, so
    there is nothing to report. A client syncing incrementally therefore kept
    showing books that had been removed on the server until it did a full
    re-pull. Ids alone are tiny (a few tens of KB for a large library) and let a
    client reconcile deletions on every sync.
    """
    allowed = access.restriction_for_request(request)
    conds, params = [], []
    if allowed is not None:
        pred, pp = access.calibre_predicate(allowed, "b")
        conds.append(pred)
        params += list(pp)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    with get_conn() as conn:
        rows = conn.execute(f"SELECT b.id FROM books b {where}", params).fetchall()
    return {"ids": [r["id"] for r in rows]}


@router.get("", response_model=SyncResponse, summary="Delta sync for iOS app")
def sync(
    request: Request,
    since: Optional[datetime] = Query(
        None,
        description="ISO 8601 timestamp. Returns books modified after this time. "
                    "Omit for full sync.",
    ),
    limit: Optional[int] = Query(
        None, ge=1, le=5000,
        description="Optional page size. Omitted = everything, as before (the "
                    "iOS app's existing behaviour). When set, the response is "
                    "ordered by last_modified and `until` is the last item's "
                    "timestamp, so the next call can pass it as `since`.",
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

    lim = f" LIMIT {int(limit) + 1}" if limit else ""
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT b.id, b.title, b.sort, b.pubdate, b.last_modified, b.timestamp,
                   b.has_cover, b.uuid, b.path, b.series_index, b.author_sort
            FROM books b {where}
            ORDER BY b.last_modified ASC{lim}
            """,
            params,
        ).fetchall()
        truncated = bool(limit) and len(rows) > limit
        if truncated:
            rows = rows[:limit]
            # The cursor compares at whole-SECOND precision (SQLite datetime()),
            # so a page must never end in the middle of a second: the rest of
            # that second would be skipped by the next `since`. Pull in every
            # remaining book modified in the same second as the last one.
            have = {r["id"] for r in rows}
            tail = conn.execute(
                f"""
                SELECT b.id, b.title, b.sort, b.pubdate, b.last_modified, b.timestamp,
                       b.has_cover, b.uuid, b.path, b.series_index, b.author_sort
                FROM books b {where}{" AND " if where else " WHERE "}datetime(b.last_modified) = datetime(?)
                ORDER BY b.last_modified ASC
                """,
                params + [rows[-1]["last_modified"]],
            ).fetchall()
            rows += [r for r in tail if r["id"] not in have]

        # One ownership query for the whole batch. If Postgres is down this is
        # a hard error: the per-book builder used to substitute defaults and
        # return 200, and the client then persisted blank ownership and
        # advanced its cursor past those books.
        try:
            ownership = fetch_ownership_map([r["id"] for r in rows])
        except Exception as e:
            logger.warning("sync: ownership lookup failed: %s", e)
            raise HTTPException(status_code=503, detail="Database unavailable; retry the sync")

        # Batched: one query per related table instead of 8 per book plus a
        # Postgres round trip each (a full sync of ~7,000 books was ~56,000
        # SQLite queries). Output is field-for-field identical.
        items = details_for_rows(conn, rows, base_url, ownership)

    # With a page limit, `until` must not skip books: point it at the last
    # returned book's own timestamp so the next `since` resumes exactly there.
    until = now
    if truncated and items:
        stamps = [i.last_modified for i in items if i.last_modified]
        if stamps:
            # Whole second, matching the comparison: everything in it was sent.
            until = max(stamps).replace(microsecond=0)

    return SyncResponse(
        since=since,
        until=until,
        total=len(items),
        items=items,
    )
