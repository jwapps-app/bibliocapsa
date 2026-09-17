"""
Delta sync endpoint for the Bibliocapsa iOS app.
GET /api/sync?since=<ISO8601>
On first sync (no since param), returns everything.

The contract -- what a client that keeps syncing converges to:
  * Every visible Calibre book's EFFECTIVE metadata (Calibre + edits pending
    sync, merged as /api/books merges them), physical ownership and location.
    A book is re-sent when Calibre's last_modified OR the application change
    journal (app/changes.py) is newer than the cursor.
  * Deletions and revoked genre access: GET /api/sync/ids lists every id the
    caller may see; anything the client holds beyond that list is gone.
  * Read status is NOT part of this feed; clients read it from
    /api/books?read_filter=read.
"""

from fastapi import APIRouter, Query, Request, HTTPException
from typing import Optional
from datetime import datetime, timezone
from ..database import get_conn
from ..schemas import SyncResponse
from ..queries import details_for_rows, fetch_ownership_map
from .. import access, changes
from .. import calibre_overlay as overlay
from .books import _cal_epoch
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

    # Two clocks decide "changed since": Calibre's last_modified, and the
    # application change journal (ownership, pending edits, read status -- data
    # that lives in Postgres and never moves Calibre's clock). See app/changes.py.
    journal: dict = {}
    if since:
        try:
            # Unpaged deltas re-read a few seconds of overlap, so a change
            # committed while the previous sync was running is never missed.
            # Paged ones can't (the repeat could fill the page and stall it).
            journal = changes.since(since, overlap_seconds=0 if limit else 5)
        except Exception as e:
            logger.warning("sync: change journal unavailable: %s", e)
            raise HTTPException(status_code=503, detail="Database unavailable; retry the sync")

    # Honor per-member genre restrictions (same as every other listing endpoint).
    allowed = access.restriction_for_request(request)
    conds, params = [], []
    if since:
        newer = "datetime(b.last_modified) > datetime(?)"
        params.append(since.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
        if journal:  # integer ids from our own table: inlined (no 999-parameter cap)
            newer = f"({newer} OR b.id IN ({','.join(str(int(i)) for i in journal)}))"
        conds.append(newer)
    if allowed is not None:
        pred, pp = access.calibre_predicate(allowed, "b")
        conds.append(pred)
        params += list(pp)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""

    def _stamp(row):
        """A book's effective change time: the later of the two clocks, at the
        whole-second precision the `since` comparison uses."""
        t = _cal_epoch(row["last_modified"])
        j = journal.get(row["id"])
        return int(max(t, j.timestamp() if j else 0))

    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT b.id, b.title, b.sort, b.pubdate, b.last_modified, b.timestamp,
                   b.has_cover, b.uuid, b.path, b.series_index, b.author_sort
            FROM books b {where}
            ORDER BY b.last_modified ASC, b.id ASC
            """,
            params,
        ).fetchall()
        truncated = False
        page_end = None
        if limit and len(rows) > limit:
            # Page by the EFFECTIVE stamp, and never end a page in the middle of
            # a second: the cursor compares whole seconds, so the rest of that
            # second would be skipped by the next `since`.
            rows = sorted(rows, key=lambda r: (_stamp(r), r["id"]))
            page_end = _stamp(rows[limit - 1])
            kept = [r for r in rows if _stamp(r) <= page_end]
            truncated = len(kept) < len(rows)
            rows = kept

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

    # Effective metadata: pending edits merged exactly as /api/books does, so a
    # synced client and the web never show different titles/authors/series for
    # the same book while an edit waits to reach Calibre.
    try:
        edits = overlay.get_edits([i.id for i in items])
    except Exception as e:
        logger.warning("sync: pending edits lookup failed: %s", e)
        raise HTTPException(status_code=503, detail="Database unavailable; retry the sync")
    for item in items:
        if item.id in edits:
            overlay.apply_to_detail(item, edits[item.id])

    # With a page limit, `until` must not skip books: point it at the last
    # returned book's own (effective) second so the next `since` resumes there.
    until = now
    if truncated and page_end:
        until = datetime.fromtimestamp(page_end, tz=timezone.utc)

    return SyncResponse(
        since=since,
        until=until,
        total=len(items),
        items=items,
    )
