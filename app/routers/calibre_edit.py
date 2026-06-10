"""
Calibre edit overlay endpoints.

Edits to Calibre books are stored in PostgreSQL and merged over Calibre on read
(see app/calibre_overlay.py). They accumulate as "pending" until a deliberate
Sync to Calibre (Phase 2). Admin only — these affect the shared library.
"""

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel
from typing import Optional
import os
import uuid

from .. import calibre_overlay as overlay

router = APIRouter()

ALLOWED_UPLOAD_EXT = {"epub", "pdf", "mobi", "azw3", "azw", "fb2", "txt", "cbz", "cbr", "docx", "rtf"}
MAX_UPLOAD_BYTES = 300 * 1024 * 1024  # 300 MB


def _require_admin(request: Request):
    from .. import auth
    u = auth.authenticate_request(request)
    if not u or u.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")


class CalibreEdit(BaseModel):
    title: Optional[str] = None
    authors: Optional[list[str]] = None
    comment: Optional[str] = None
    series: Optional[str] = None
    series_index: Optional[float] = None
    tags: Optional[list[str]] = None
    publisher: Optional[str] = None
    pubdate: Optional[str] = None
    rating: Optional[int] = None
    isbn: Optional[str] = None
    custom: Optional[dict] = None  # {column_label: value} for Calibre custom columns


@router.put("/books/{book_id}", summary="Save pending Calibre metadata edits (admin)")
def edit_book(book_id: int, body: CalibreEdit, request: Request):
    _require_admin(request)
    # Only fields explicitly provided are recorded (so callers can patch one field).
    fields = body.model_dump(exclude_unset=True)
    custom = fields.pop("custom", None) or {}
    for label, value in custom.items():
        fields[f"custom:{label}"] = value
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to edit")
    if "rating" in fields and fields["rating"] is not None and not (0 <= fields["rating"] <= 5):
        raise HTTPException(status_code=400, detail="Rating must be 0–5")
    overlay.set_edits(book_id, fields)
    return {"ok": True, "book_id": book_id, "fields": list(fields)}


_MISSING_WHERE = {
    "description": "NOT EXISTS (SELECT 1 FROM comments c WHERE c.book = b.id)",
    "pubdate": "(b.pubdate IS NULL OR b.pubdate LIKE '0101%')",
    "series": "NOT EXISTS (SELECT 1 FROM books_series_link l WHERE l.book = b.id)",
    "publisher": "NOT EXISTS (SELECT 1 FROM books_publishers_link l WHERE l.book = b.id)",
    "isbn": "NOT EXISTS (SELECT 1 FROM identifiers i WHERE i.book = b.id AND i.type='isbn')",
    "tags": "NOT EXISTS (SELECT 1 FROM books_tags_link l WHERE l.book = b.id)",
}


@router.get("/missing", summary="Digital books missing a metadata field (admin)")
def missing_books(request: Request, field: str = "description", page: int = 1, page_size: int = 50):
    _require_admin(request)
    where = _MISSING_WHERE.get(field)
    if not where:
        raise HTTPException(status_code=400, detail=f"Unknown field '{field}'")
    from ..database import get_conn
    offset = (page - 1) * page_size
    with get_conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM books b WHERE {where}").fetchone()[0]
        rows = conn.execute(
            f"SELECT b.id, b.title, b.author_sort FROM books b WHERE {where} "
            f"ORDER BY b.timestamp DESC LIMIT ? OFFSET ?",
            (page_size, offset),
        ).fetchall()
    return {"total": total, "field": field, "page": page, "page_size": page_size,
            "items": [{"id": r["id"], "title": r["title"], "author": r["author_sort"]} for r in rows]}


class ReadStatus(BaseModel):
    status: Optional[str] = None     # 'read' | 'reading' | None (unread)
    date_read: Optional[str] = None  # 'YYYY-MM-DD'


@router.get("/read-status/{book_id}", summary="Get a Calibre book's read/unread status")
def get_read_status(book_id: int, request: Request):
    from .. import calibre_read
    return calibre_read.get_status(book_id)


@router.put("/read-status/{book_id}", summary="Set a Calibre book's read/unread status (admin)")
def set_read_status(book_id: int, body: ReadStatus, request: Request):
    _require_admin(request)
    from .. import calibre_read, read_history, auth
    result = calibre_read.set_status(book_id, body.status, body.date_read)
    # Marking Read logs a finish date in the running read history (deduped per
    # day, so toggling doesn't spam). Adjust/add/remove dates via /reading/history.
    if result["status"] == "read":
        user = auth.authenticate_request(request)
        if user:
            from datetime import date as _date
            read_history.add(book_id, "calibre", user["id"],
                             result["date_read"] or _date.today().isoformat(),
                             source="toggle", dedupe=True)
    return result


class CommunityRating(BaseModel):
    rating: Optional[float] = None


@router.post("/community-rating/{book_id}", summary="Store a Calibre book's community rating (admin)")
def set_community_rating(book_id: int, body: CommunityRating, request: Request):
    _require_admin(request)
    from .. import community
    community.set_calibre_rating(book_id, body.rating)
    return {"ok": True}


@router.get("/lookup", summary="Search external sources for metadata candidates (admin)")
def lookup(request: Request, title: str, author: Optional[str] = None):
    _require_admin(request)
    from .. import metadata, ratelimit
    ratelimit.check(ratelimit.client_key(request, "lookup"), limit=20, window=60)
    from .settings import get_setting, HARDCOVER_TOKEN_KEY
    token = get_setting(HARDCOVER_TOKEN_KEY)
    return metadata.search_candidates(title, author, token)


@router.post("/enrich", summary="Start bulk metadata lookup → overlay (admin)")
def start_enrich(request: Request, force: bool = False):
    _require_admin(request)
    from .. import calibre_enrich
    from .settings import get_setting, HARDCOVER_TOKEN_KEY
    token = get_setting(HARDCOVER_TOKEN_KEY)
    if not calibre_enrich.start(token, force):
        raise HTTPException(status_code=409, detail="Enrichment already running")
    return {"status": "started", "hardcover": bool(token)}


@router.get("/enrich/status", summary="Bulk enrichment status (admin)")
def enrich_status(request: Request):
    _require_admin(request)
    from .. import calibre_enrich
    return calibre_enrich.status()


@router.post("/enrich/cancel", summary="Cancel bulk enrichment (admin)")
def enrich_cancel(request: Request):
    _require_admin(request)
    from .. import calibre_enrich
    calibre_enrich.cancel()
    return {"status": "cancelling"}


class ReadingMap(BaseModel):
    read: Optional[str] = None
    progress: Optional[str] = None
    date: Optional[str] = None


@router.get("/reading-map", summary="Reading→column mapping")
def get_reading_map(request: Request):
    # Read-only config (which columns hold read/progress/date) — any signed-in
    # user may read it (the sort menu uses it to de-dupe the Date Read option).
    from .settings import get_setting
    return {"read": get_setting("reading_col_read"),
            "progress": get_setting("reading_col_progress"),
            "date": get_setting("reading_col_date")}


@router.put("/reading-map", summary="Save reading→column mapping (admin)")
def set_reading_map(body: ReadingMap, request: Request):
    _require_admin(request)
    from .settings import set_setting
    set_setting("reading_col_read", body.read or None)
    set_setting("reading_col_progress", body.progress or None)
    set_setting("reading_col_date", body.date or None)
    return {"ok": True}


@router.post("/reading-sync", summary="Queue Calibre column updates from KOReader reading (admin)")
def reading_sync(request: Request):
    _require_admin(request)
    from .. import auth, calibre_custom
    from .settings import get_setting
    from ..database import get_conn
    from datetime import datetime, timezone

    col_read = get_setting("reading_col_read")
    col_prog = get_setting("reading_col_progress")
    col_date = get_setting("reading_col_date")
    if not (col_read or col_prog or col_date):
        raise HTTPException(status_code=400, detail="Configure reading columns first")

    _user = auth.authenticate_request(request) or {}
    username = _user.get("username")
    user_id = _user.get("id")
    conn = overlay._pg()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT dm.book_id AS book_id, kp.percentage AS pct, "
            "EXTRACT(EPOCH FROM kp.updated_at)::bigint AS ts "
            "FROM kosync_progress kp JOIN document_map dm ON dm.document = kp.document "
            "WHERE kp.username = %s AND dm.book_source = 'calibre'",
            (username,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    best: dict = {}  # book_id -> (pct, ts), keeping furthest progress
    for r in rows:
        bid, pct = r["book_id"], (r["pct"] or 0)
        if bid not in best or pct > best[bid][0]:
            best[bid] = (pct, r["ts"])

    from .. import calibre_read, read_history
    queued = 0
    with get_conn() as cal:
        for bid, (pct, ts) in best.items():
            frac = pct if pct <= 1 else pct / 100.0
            pct100 = max(0, min(100, round(frac * 100)))
            read = frac >= 0.99
            date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            # Mirror into Bibliocapsa's own read-status store so KOReader-read
            # books show in the unified Read/Unread filter (read or in-progress).
            cur_status = calibre_read.get_status(bid).get("status")
            if read and cur_status != "read":
                calibre_read.set_status(bid, "read", date_str)
                if user_id:
                    read_history.add(bid, "calibre", user_id, date_str, source="koreader", dedupe=True)
            elif not read and frac > 0.01 and not cur_status:
                calibre_read.set_status(bid, "reading", None)
            cur_custom = {c["label"]: c["value"] for c in calibre_custom.fetch_for_book(cal, bid)}
            edits: dict = {}
            if col_prog and cur_custom.get(col_prog) != pct100:
                edits[f"custom:{col_prog}"] = pct100
            if col_read and read and not bool(cur_custom.get(col_read)):
                edits[f"custom:{col_read}"] = True
            if col_date and read and not cur_custom.get(col_date):
                edits[f"custom:{col_date}"] = date_str
            if edits:
                overlay.set_edits(bid, edits)
                queued += 1
    return {"queued": queued, "books_with_progress": len(best)}


@router.get("/custom-columns", summary="Calibre custom-column definitions")
def custom_columns():
    from ..database import get_conn
    from .. import calibre_custom
    with get_conn() as conn:
        return calibre_custom.list_columns(conn)


@router.get("/pending", summary="Pending Calibre edits + uploads (admin)")
def get_pending(request: Request):
    _require_admin(request)
    items = overlay.pending()
    uploads = overlay.list_uploads()
    return {
        "count": sum(len(i["fields"]) for i in items) + len(uploads),
        "books": len(items),
        "items": items,
        "uploads": uploads,
    }


@router.get("/pending/count", summary="Pending edit + upload count (admin)")
def pending_count(request: Request):
    _require_admin(request)
    return {"count": overlay.pending_count() + overlay.uploads_count()}


@router.post("/upload", summary="Upload a new book to queue for Calibre (admin)")
async def upload_book(request: Request, file: UploadFile = File(...)):
    _require_admin(request)
    from .. import calibre_sync
    ext = os.path.splitext(file.filename or "")[1].lower().lstrip(".")
    if ext not in ALLOWED_UPLOAD_EXT:
        raise HTTPException(status_code=400, detail=f"Unsupported file type .{ext}")
    blob = await file.read()
    if not blob:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(blob) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 300 MB)")

    os.makedirs(overlay.UPLOADS_DIR, exist_ok=True)
    stored = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(overlay.UPLOADS_DIR, stored)
    with open(path, "wb") as f:
        f.write(blob)

    title, authors = calibre_sync.extract_book_metadata(path)
    # ebook-meta echoes the on-disk (uuid) name when a file has no embedded title;
    # fall back to the original upload name in that case.
    if not title or title == os.path.splitext(stored)[0]:
        title = os.path.splitext(file.filename or "Untitled")[0]
    rec = overlay.add_upload(stored, file.filename, title, authors, ext, len(blob))
    return rec


@router.get("/uploads", summary="Pending uploads (admin)")
def get_uploads(request: Request):
    _require_admin(request)
    return overlay.list_uploads()


@router.delete("/uploads/{upload_id}", summary="Discard a pending upload (admin)")
def discard_upload(upload_id: int, request: Request):
    _require_admin(request)
    overlay.discard_upload(upload_id)
    return {"ok": True}


@router.delete("/books/{book_id}", summary="Discard pending edits for a book (admin)")
def discard_book(book_id: int, request: Request, field: Optional[str] = None):
    _require_admin(request)
    overlay.discard(book_id, field)
    return {"ok": True}


class SyncRequest(BaseModel):
    confirm: bool = False


@router.post("/sync", summary="Push pending edits to Calibre via calibredb (admin)")
def sync_to_calibre(body: SyncRequest, request: Request):
    _require_admin(request)
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required (Calibre must be closed)")
    from .. import calibre_sync
    return calibre_sync.run_sync()
