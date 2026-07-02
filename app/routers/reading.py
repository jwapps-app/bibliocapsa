"""
Reading progress — tracks position per book per user per device.
Works with KOSync for cross-device sync.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter()


class ProgressUpdate(BaseModel):
    user_id: Optional[int] = None
    device: Optional[str] = None
    book_source: str = "calibre"
    progress: Optional[float] = None   # 0.0 to 1.0
    current_page: Optional[int] = None
    total_pages: Optional[int] = None
    cfi: Optional[str] = None          # EPUB CFI position string
    percentage: Optional[float] = None


class ReadingProgress(BaseModel):
    id: int
    book_id: int
    book_source: str
    user_id: Optional[int] = None
    device: Optional[str] = None
    progress: Optional[float] = None
    current_page: Optional[int] = None
    total_pages: Optional[int] = None
    cfi: Optional[str] = None
    percentage: Optional[float] = None
    last_read_at: Optional[datetime] = None


def _pg():
    from ..pg_database import get_pg
    return get_pg()


@router.get("/current", summary="Books the current user is reading (from KOReader sync)")
def current_reading(request: Request):
    """Join the user's KOSync progress → document_map → Calibre book."""
    user = getattr(request.state, "user", None)
    username = user.get("username") if user else None
    if not username:
        return []
    base_url = str(request.base_url).rstrip("/")
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT dm.book_id, dm.book_source, kp.percentage, kp.progress, kp.device,
                   EXTRACT(EPOCH FROM kp.updated_at)::bigint AS updated_at
            FROM kosync_progress kp
            JOIN document_map dm ON dm.document = kp.document
            WHERE kp.username = %s AND dm.book_source = 'calibre'
            ORDER BY kp.updated_at DESC
            """,
            (username,),
        )
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")

    from ..database import get_conn
    from .. import access, calibre_read
    allowed = access.restriction_for_request(request)
    # A finished book (marked Read) should leave Currently Reading on its own,
    # keeping its progress/stats — so exclude books that are now 'read'.
    finished = calibre_read.read_book_ids([r["book_id"] for r in rows])

    # One batched lookup (title/cover + genre predicate in SQL) instead of two
    # queries per progress row — the progress table grows with reading history.
    ids, seen = [], set()
    for r in rows:
        bid = r["book_id"]
        if bid not in seen and bid not in finished:
            seen.add(bid)
            ids.append(bid)
    meta = {}
    with get_conn() as cal:
        pred, cp = access.calibre_predicate(allowed, "b")
        extra = f" AND {pred}" if pred else ""
        for i in range(0, len(ids), 500):  # stay under SQLite's parameter cap
            chunk = ids[i:i + 500]
            ph = ",".join("?" * len(chunk))
            for b in cal.execute(
                f"SELECT b.id, b.title, b.has_cover FROM books b WHERE b.id IN ({ph}){extra}",
                chunk + cp,
            ).fetchall():
                meta[b["id"]] = (b["title"], bool(b["has_cover"]))

    out, emitted = [], set()
    for r in rows:  # preserve most-recent-first order, one entry per book
        bid = r["book_id"]
        if bid in emitted or bid not in meta:
            continue
        emitted.add(bid)
        title, has_cover = meta[bid]
        out.append({
            "book_id": bid,
            "book_source": "calibre",
            "title": title,
            "has_cover": has_cover,
            "cover_url": f"{base_url}/api/covers/{bid}" if has_cover else None,
            "percentage": r["percentage"],
            "device": r["device"],
            "updated_at": r["updated_at"],
        })
    return out


class WebProgress(BaseModel):
    percentage: float
    cfi: Optional[str] = None          # exact browser position (epub.js CFI, or PDF page)
    ko_progress: Optional[str] = None  # KOReader value: crengine xpointer (epub) or page (pdf)
    format: Optional[str] = "epub"     # which format is being read (epub | pdf)


def _doc_for_book(cur, book_id: int, fmt: Optional[str] = None) -> Optional[str]:
    """Document hash for a book, preferring the given format (else EPUB)."""
    prefer = (fmt or "epub").lower()
    cur.execute(
        """SELECT document FROM document_map
           WHERE book_id = %s AND book_source = 'calibre'
           ORDER BY (format = %s) DESC, updated_at DESC LIMIT 1""",
        (book_id, prefer),
    )
    r = cur.fetchone()
    return r["document"] if r else None


def _web_device(fmt: Optional[str]) -> str:
    # Per-format browser device so EPUB and PDF progress don't collide.
    return f"bibliocapsa-web-{(fmt or 'epub').lower()}"


@router.get("/book/{book_id}", summary="Reading progress for one book (browser + synced)")
def get_book_progress(book_id: int, request: Request, format: Optional[str] = "epub"):
    """Returns the browser's exact position and the latest synced position for
    the given format. The reader opens at whichever is newer."""
    user = getattr(request.state, "user", None)
    if not user:
        return {"browser": None, "synced": None}
    fmt = (format or "epub").lower()
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute(
            """SELECT cfi, percentage, EXTRACT(EPOCH FROM last_read_at)::bigint AS ts
               FROM reading_progress
               WHERE book_id = %s AND book_source = 'calibre' AND user_id = %s
                 AND device = %s""",
            (book_id, user["id"], _web_device(fmt)),
        )
        br = cur.fetchone()
        # Latest sync for this format's document (falls back to any if no
        # format-specific document hash is mapped yet).
        cur.execute(
            """SELECT kp.percentage, kp.progress, kp.device, EXTRACT(EPOCH FROM kp.updated_at)::bigint AS ts
               FROM kosync_progress kp JOIN document_map dm ON dm.document = kp.document
               WHERE dm.book_id = %s AND dm.book_source = 'calibre' AND kp.username = %s
               ORDER BY (dm.format = %s) DESC, kp.updated_at DESC LIMIT 1""",
            (book_id, user.get("username"), fmt),
        )
        sy = cur.fetchone()
        conn.close()
        return {"browser": dict(br) if br else None, "synced": dict(sy) if sy else None}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")


@router.post("/book/{book_id}", summary="Save browser reading progress for one book")
def save_book_progress(book_id: int, body: WebProgress, request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        conn = _pg()
        cur = conn.cursor()
        # Exact browser position (CFI) for same-device resume.
        cur.execute(
            """INSERT INTO reading_progress
                   (book_id, book_source, user_id, device, cfi, percentage, last_read_at)
               VALUES (%s, 'calibre', %s, %s, %s, %s, NOW())
               ON CONFLICT (book_id, book_source, user_id, device) DO UPDATE SET
                   cfi = EXCLUDED.cfi, percentage = EXCLUDED.percentage, last_read_at = NOW()""",
            (book_id, user["id"], _web_device(body.format), body.cfi, body.percentage),
        )
        # Mirror into KOSync so it shows in Currently Reading and syncs to
        # KOReader. KOReader applies `progress` per format: a crengine xpointer
        # for EPUB (chapter-level `/body/DocFragment[N]/body`) or a page number
        # for PDF — never an epub.js CFI. The client supplies the right value.
        doc = _doc_for_book(cur, book_id, body.format)
        if doc and user.get("username"):
            cur.execute(
                """INSERT INTO kosync_progress
                       (username, document, progress, percentage, device, device_id, updated_at)
                   VALUES (%s, %s, %s, %s, 'bibliocapsa-web', 'web', NOW())
                   ON CONFLICT (username, document) DO UPDATE SET
                       progress = EXCLUDED.progress, percentage = EXCLUDED.percentage,
                       device = EXCLUDED.device, updated_at = NOW()""",
                (user["username"], doc, body.ko_progress or "", body.percentage),
            )
        conn.commit()
        conn.close()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")


@router.delete("/book/{book_id}", summary="Clear reading progress (remove from Currently Reading / mark unread)")
def reset_book_progress(book_id: int, request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    # All document hashes that map to this book: those recorded in document_map,
    # plus the partial-MD5 of the actual Calibre file(s) (covers un-mapped books).
    docs = set()
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("SELECT document FROM document_map WHERE book_id = %s AND book_source='calibre'", (book_id,))
        docs.update(r["document"] for r in cur.fetchall())
        try:
            from ..database import get_conn
            from .. import koreader_stats as ks
            with get_conn() as cal:
                docs.update(ks.calibre_md5s(cal, book_id))
        except Exception:
            pass
        cleared_sync = 0
        if docs and user.get("username"):
            cur.execute("DELETE FROM kosync_progress WHERE username = %s AND document = ANY(%s)",
                        (user["username"], list(docs)))
            cleared_sync = cur.rowcount
        cur.execute("DELETE FROM reading_progress WHERE book_id = %s AND book_source='calibre' AND user_id = %s",
                    (book_id, user["id"]))
        cleared_browser = cur.rowcount
        conn.commit()
        conn.close()
        return {"ok": True, "cleared_sync": cleared_sync, "cleared_browser": cleared_browser}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")


# ── Read history (running list of finish dates, per user) ────────────────────
class ReadDate(BaseModel):
    date_read: Optional[str] = None  # 'YYYY-MM-DD'


@router.get("/history/{book_source}/{book_id}", summary="A user's read dates for a book")
def get_read_history(book_source: str, book_id: int, request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        return []
    from .. import read_history
    return read_history.list_for(book_id, book_source, user["id"])


@router.post("/history/{book_source}/{book_id}", summary="Add a read date (manual)")
def add_read_date(book_source: str, book_id: int, body: ReadDate, request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from .. import read_history
    from datetime import date as _date
    d = body.date_read or _date.today().isoformat()
    return read_history.add(book_id, book_source, user["id"], d, source="manual", dedupe=False)


@router.put("/history/entry/{entry_id}", summary="Adjust a read date")
def edit_read_date(entry_id: int, body: ReadDate, request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from .. import read_history
    if not read_history.update(entry_id, user["id"], body.date_read):
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"ok": True}


@router.delete("/history/entry/{entry_id}", summary="Delete a read date")
def delete_read_date(entry_id: int, request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    from .. import read_history
    if not read_history.delete(entry_id, user["id"]):
        raise HTTPException(status_code=404, detail="Entry not found")
    return {"ok": True}


@router.get("/{book_id}", response_model=list[ReadingProgress], summary="Get reading progress for a book")
def get_progress(book_id: int, request: Request, book_source: str = "calibre"):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        conn = _pg()
        cur = conn.cursor()
        # Scoped to the caller — never expose other users' progress.
        cur.execute(
            "SELECT * FROM reading_progress WHERE book_id = %s AND book_source = %s AND user_id = %s "
            "ORDER BY last_read_at DESC",
            (book_id, book_source, user["id"])
        )
        rows = cur.fetchall()
        conn.close()
        return [ReadingProgress(**dict(r)) for r in rows]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")


@router.post("/{book_id}", response_model=ReadingProgress, summary="Update reading progress")
def update_progress(book_id: int, progress: ProgressUpdate, request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO reading_progress
                (book_id, book_source, user_id, device, progress, current_page,
                 total_pages, cfi, percentage, last_read_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
            ON CONFLICT (book_id, book_source, user_id, device)
            DO UPDATE SET
                progress      = EXCLUDED.progress,
                current_page  = EXCLUDED.current_page,
                total_pages   = EXCLUDED.total_pages,
                cfi           = EXCLUDED.cfi,
                percentage    = EXCLUDED.percentage,
                last_read_at  = NOW()
            RETURNING *
            """,
            (book_id, progress.book_source, user["id"], progress.device,
             progress.progress, progress.current_page, progress.total_pages,
             progress.cfi, progress.percentage)
        )
        row = cur.fetchone()
        conn.commit()
        conn.close()
        return ReadingProgress(**dict(row))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")
