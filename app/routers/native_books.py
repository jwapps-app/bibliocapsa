"""
Native Bibliocapsa library — books added via iOS scan or manual entry.
Read-write. Backed by PostgreSQL.
"""

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Request
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
import os
import time
import threading
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

COVER_CACHE_DIR = os.getenv("COVER_CACHE_DIR", "/app/cover_cache")


def _require_admin(request: Request):
    """Library writes/enrichment are admin-only (members read-only)."""
    from .. import auth
    u = auth.authenticate_request(request)
    if not u or u.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")


class NativeBookCreate(BaseModel):
    title: str
    author: Optional[str] = None
    isbn: Optional[str] = None
    isbn13: Optional[str] = None
    cover_url: Optional[str] = None
    description: Optional[str] = None
    page_count: Optional[int] = None
    publisher: Optional[str] = None
    published_date: Optional[str] = None
    categories: Optional[list[str]] = []
    language: str = "en"
    format: str = "physical"
    location: Optional[str] = None
    rating: Optional[int] = None
    owner_id: Optional[int] = None


class NativeBookUpdate(BaseModel):
    """Every editable field. Uses exclude_unset semantics in the handler:
    only fields present in the request body are written (allowing null to clear)."""
    title: Optional[str] = None
    author: Optional[str] = None
    isbn: Optional[str] = None
    isbn13: Optional[str] = None
    cover_url: Optional[str] = None
    description: Optional[str] = None
    page_count: Optional[int] = None
    publisher: Optional[str] = None
    published_date: Optional[str] = None
    categories: Optional[list[str]] = None
    language: Optional[str] = None
    format: Optional[str] = None
    location: Optional[str] = None
    rating: Optional[int] = None
    reading_status: Optional[str] = None
    date_read: Optional[str] = None
    owner_id: Optional[int] = None


class NativeBook(BaseModel):
    id: int
    title: str
    author: Optional[str] = None
    isbn: Optional[str] = None
    isbn13: Optional[str] = None
    cover_url: Optional[str] = None
    description: Optional[str] = None
    page_count: Optional[int] = None
    publisher: Optional[str] = None
    published_date: Optional[str] = None
    categories: Optional[list[str]] = []
    language: Optional[str] = None
    format: str
    location: Optional[str] = None
    rating: Optional[int] = None
    community_rating: Optional[float] = None
    reading_status: Optional[str] = None
    date_read: Optional[str] = None
    cover_variant: Optional[int] = None
    owner_id: Optional[int] = None
    created_at: Optional[datetime] = None


def _pg():
    from ..pg_database import get_pg
    return get_pg()


@router.get("", response_model=list[NativeBook], summary="List native library books")
def list_native_books(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: Optional[str] = Query(None),
    format: Optional[str] = Query(None),
    owner_id: Optional[int] = Query(None),
):
    from .. import access
    try:
        conn = _pg()
        cur = conn.cursor()
        conditions = ["1=1"]
        params = []

        if search:
            conditions.append("(title ILIKE %s OR author ILIKE %s)")
            params += [f"%{search}%", f"%{search}%"]
        if format:
            conditions.append("format = %s")
            params.append(format)
        if owner_id:
            conditions.append("owner_id = %s")
            params.append(owner_id)

        nat_pred, nat_pred_params = access.native_predicate(access.restriction_for_request(request))
        if nat_pred:
            conditions.append(nat_pred)
            params += nat_pred_params

        where = " AND ".join(conditions)
        offset = (page - 1) * page_size

        cur.execute(
            f"SELECT * FROM native_books WHERE {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
            params + [page_size, offset]
        )
        rows = cur.fetchall()
        conn.close()
        return [NativeBook(**dict(r)) for r in rows]
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {e}")


@router.post("", response_model=NativeBook, status_code=201, summary="Add a book to native library")
def create_native_book(book: NativeBookCreate, request: Request):
    _require_admin(request)
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO native_books
                (title, author, isbn, isbn13, cover_url, description, page_count,
                 publisher, published_date, categories, language, format, location, rating, owner_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING *
            """,
            (book.title, book.author, book.isbn, book.isbn13, book.cover_url,
             book.description, book.page_count, book.publisher, book.published_date,
             book.categories, book.language, book.format, book.location, book.rating, book.owner_id)
        )
        row = cur.fetchone()
        conn.commit()
        conn.close()
        # Auto-fetch cover & metadata for the new book (background), unless disabled.
        try:
            from ..routers.settings import auto_enrich_enabled
            if not row.get("cover_url") and auto_enrich_enabled():
                _enrich_book_async(row["id"])
        except Exception:
            pass
        return NativeBook(**dict(row))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")


@router.get("/{book_id}", response_model=NativeBook, summary="Get a native book")
def get_native_book(book_id: int, request: Request):
    from .. import access
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("SELECT * FROM native_books WHERE id = %s", (book_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail=f"Book {book_id} not found")
        if not access.is_native_allowed(row.get("categories"), access.restriction_for_request(request)):
            raise HTTPException(status_code=404, detail=f"Book {book_id} not found")
        return NativeBook(**dict(row))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")


# Text fields where an empty/whitespace string should be stored as NULL.
_NULLABLE_TEXT = {
    "author", "isbn", "isbn13", "cover_url", "description", "publisher",
    "published_date", "language", "location",
}


@router.put("/{book_id}", response_model=NativeBook, summary="Update a native book")
def update_native_book(book_id: int, updates: NativeBookUpdate, request: Request):
    _require_admin(request)
    # Only fields the client explicitly sent are written — sending null clears a
    # field, omitting it leaves the stored value untouched.
    fields = updates.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Validation / normalization.
    if "title" in fields:
        title = (fields["title"] or "").strip()
        if not title:
            raise HTTPException(status_code=400, detail="Title cannot be empty")
        fields["title"] = title
    if "rating" in fields and fields["rating"] is not None:
        r = fields["rating"]
        if not isinstance(r, int) or r < 1 or r > 5:
            raise HTTPException(status_code=400, detail="Rating must be 1–5 or null")
    for k in list(fields):
        if k in _NULLABLE_TEXT and isinstance(fields[k], str):
            fields[k] = fields[k].strip() or None

    try:
        conn = _pg()
        cur = conn.cursor()

        # If the cover URL is changing, drop any cached image so the new URL is
        # re-fetched on next request.
        if "cover_url" in fields:
            for ext in ("", ".type"):
                try:
                    os.remove(_cover_path(book_id) + ext)
                except OSError:
                    pass

        set_clause = ", ".join(f"{k} = %s" for k in fields)
        values = list(fields.values()) + [book_id]

        cur.execute(
            f"UPDATE native_books SET {set_clause}, updated_at = NOW() WHERE id = %s RETURNING *",
            values
        )
        row = cur.fetchone()
        conn.commit()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail=f"Book {book_id} not found")
        # Marking a physical book Read logs a finish date in the per-user read
        # history (deduped per day). Dates are managed via /reading/history.
        if fields.get("reading_status") == "read":
            try:
                from .. import auth, read_history
                from datetime import date as _date
                user = auth.authenticate_request(request)
                if user:
                    read_history.add(book_id, "native", user["id"],
                                     fields.get("date_read") or row.get("date_read") or _date.today().isoformat(),
                                     source="toggle", dedupe=True)
            except Exception:
                pass
        return NativeBook(**dict(row))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# Metadata enrichment (Hardcover + Open Library) and cover serving
# ══════════════════════════════════════════════════════════════════════════════

_enrich_lock = threading.Lock()
_enrich_job = {
    "running": False,
    "total": 0,
    "processed": 0,
    "succeeded": 0,
    "no_match": 0,
    "errors": 0,
    "current": None,
    "started_at": None,
    "finished_at": None,
    "cancel": False,
}


def _cover_path(book_id: int) -> str:
    return os.path.join(COVER_CACHE_DIR, str(book_id))


def _cache_cover(book_id: int, blob: bytes, content_type: str) -> None:
    try:
        os.makedirs(COVER_CACHE_DIR, exist_ok=True)
        with open(_cover_path(book_id), "wb") as f:
            f.write(blob)
        with open(_cover_path(book_id) + ".type", "w") as f:
            f.write(content_type)
    except Exception as e:
        logger.warning("Failed to cache cover for book %s: %s", book_id, e)


def _enrich_one(cur, book: dict, token: Optional[str]) -> str:
    """Enrich a single native_books row in place. Returns the enrich_status set.

    `cur` is a live cursor; the caller commits.
    """
    from .. import metadata

    md = metadata.fetch_metadata(book.get("isbn"), book.get("isbn13"), token)

    cover_url = None
    if md and md.cover_url:
        downloaded = metadata.download_cover(md.cover_url)
        if downloaded:
            blob, content_type = downloaded
            _cache_cover(book["id"], blob, content_type)
            cover_url = md.cover_url

    if not md or not (cover_url or md.description):
        cur.execute(
            "UPDATE native_books SET enrich_status='no_match', enriched_at=NOW() WHERE id=%s",
            (book["id"],),
        )
        return "no_match"

    # Only fill fields that are currently empty (never overwrite user-entered data).
    cur.execute(
        """
        UPDATE native_books SET
            cover_url        = COALESCE(cover_url, %s),
            description      = COALESCE(description, %s),
            page_count       = COALESCE(page_count, %s),
            publisher        = COALESCE(publisher, %s),
            published_date   = COALESCE(published_date, %s),
            community_rating = COALESCE(%s, community_rating),
            metadata_source  = %s,
            enrich_status    = 'ok',
            enriched_at      = NOW(),
            updated_at       = NOW()
        WHERE id = %s
        """,
        (
            cover_url, md.description, md.page_count, md.publisher,
            md.published_date, md.rating, md.source, book["id"],
        ),
    )
    return "ok"


def _run_bulk_enrich(force: bool, token: Optional[str]):
    """Background worker: enrich all native books lacking metadata."""
    conn = _pg()
    try:
        cur = conn.cursor()
        if force:
            cur.execute("SELECT id, title, isbn, isbn13 FROM native_books ORDER BY id")
        else:
            cur.execute(
                """
                SELECT id, title, isbn, isbn13 FROM native_books
                WHERE cover_url IS NULL
                  AND (enrich_status IS NULL OR enrich_status = 'error')
                ORDER BY id
                """
            )
        books = cur.fetchall()

        with _enrich_lock:
            _enrich_job.update(total=len(books), processed=0, succeeded=0,
                               no_match=0, errors=0)

        # Hardcover allows ~60 req/min; pace ~1 book/sec to stay safe.
        delay = 1.0 if token else 0.34

        for book in books:
            with _enrich_lock:
                if _enrich_job["cancel"]:
                    break
                _enrich_job["current"] = book["title"]

            status = "error"
            try:
                status = _enrich_one(cur, dict(book), token)
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.warning("Enrich failed for book %s: %s", book["id"], e)
                try:
                    cur.execute(
                        "UPDATE native_books SET enrich_status='error', enriched_at=NOW() WHERE id=%s",
                        (book["id"],),
                    )
                    conn.commit()
                except Exception:
                    conn.rollback()

            with _enrich_lock:
                _enrich_job["processed"] += 1
                if status == "ok":
                    _enrich_job["succeeded"] += 1
                elif status == "no_match":
                    _enrich_job["no_match"] += 1
                else:
                    _enrich_job["errors"] += 1

            time.sleep(delay)
    finally:
        conn.close()
        with _enrich_lock:
            _enrich_job["running"] = False
            _enrich_job["current"] = None
            _enrich_job["finished_at"] = datetime.now(timezone.utc).isoformat()


@router.get("/enrich/status", summary="Metadata enrichment job status")
def enrich_status():
    with _enrich_lock:
        job = dict(_enrich_job)
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) AS total, COUNT(cover_url) AS with_cover, "
            "COUNT(*) FILTER (WHERE enrich_status='no_match') AS no_match "
            "FROM native_books"
        )
        row = cur.fetchone()
        conn.close()
        job["library"] = {
            "total": row["total"],
            "with_cover": row["with_cover"],
            "no_match": row["no_match"],
        }
    except Exception:
        job["library"] = None
    return job


def start_enrich_job(force: bool = False) -> bool:
    """Kick off the background bulk enrichment. Returns False if one's running.
    Callable from endpoints AND from auto-triggers (import / manual add)."""
    from ..routers.settings import get_setting, HARDCOVER_TOKEN_KEY
    with _enrich_lock:
        if _enrich_job["running"]:
            return False
        _enrich_job.update(
            running=True, cancel=False, processed=0, total=0,
            succeeded=0, no_match=0, errors=0, current=None,
            started_at=datetime.now(timezone.utc).isoformat(), finished_at=None,
        )
    token = get_setting(HARDCOVER_TOKEN_KEY)
    threading.Thread(target=_run_bulk_enrich, args=(force, token), daemon=True).start()
    return True


def _enrich_book_async(book_id: int) -> None:
    """Enrich a single new book in the background (used on manual add)."""
    def _job():
        from ..routers.settings import get_setting, HARDCOVER_TOKEN_KEY
        token = get_setting(HARDCOVER_TOKEN_KEY)
        try:
            conn = _pg()
            cur = conn.cursor()
            cur.execute("SELECT id, title, isbn, isbn13 FROM native_books WHERE id=%s", (book_id,))
            b = cur.fetchone()
            if b:
                _enrich_one(cur, dict(b), token)
                conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("Auto-enrich for book %s failed: %s", book_id, e)
    threading.Thread(target=_job, daemon=True).start()


@router.post("/enrich", summary="Start bulk metadata enrichment (background)")
def start_bulk_enrich(request: Request, force: bool = Query(False, description="Re-process every book, even those already matched")):
    _require_admin(request)
    from ..routers.settings import get_setting, HARDCOVER_TOKEN_KEY
    if not start_enrich_job(force):
        raise HTTPException(status_code=409, detail="Enrichment already running")
    return {"status": "started", "hardcover": bool(get_setting(HARDCOVER_TOKEN_KEY))}


@router.post("/enrich/cancel", summary="Cancel a running enrichment job")
def cancel_bulk_enrich(request: Request):
    _require_admin(request)
    with _enrich_lock:
        if not _enrich_job["running"]:
            return {"status": "not_running"}
        _enrich_job["cancel"] = True
    return {"status": "cancelling"}


@router.post("/{book_id}/enrich", response_model=NativeBook, summary="Enrich one book (synchronous)")
def enrich_one_book(book_id: int, request: Request):
    _require_admin(request)
    from ..routers.settings import get_setting, HARDCOVER_TOKEN_KEY

    token = get_setting(HARDCOVER_TOKEN_KEY)
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("SELECT id, title, isbn, isbn13 FROM native_books WHERE id=%s", (book_id,))
        book = cur.fetchone()
        if not book:
            conn.close()
            raise HTTPException(status_code=404, detail=f"Book {book_id} not found")
        _enrich_one(cur, dict(book), token)
        conn.commit()
        cur.execute("SELECT * FROM native_books WHERE id=%s", (book_id,))
        row = cur.fetchone()
        conn.close()
        return NativeBook(**dict(row))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Enrichment error: {e}")


@router.get("/{book_id}/cover", summary="Serve a native book cover (proxied + cached)")
def get_native_cover(book_id: int, request: Request):
    from .. import access
    allowed = access.restriction_for_request(request)
    if allowed is not None:
        try:
            c = _pg(); cc = c.cursor()
            cc.execute("SELECT categories FROM native_books WHERE id=%s", (book_id,))
            r = cc.fetchone(); c.close()
        except Exception:
            r = None
        if not r or not access.is_native_allowed(r.get("categories"), allowed):
            raise HTTPException(status_code=404, detail="No cover")

    # Serve from disk cache if present.
    path = _cover_path(book_id)
    if os.path.exists(path):
        try:
            with open(path, "rb") as f:
                blob = f.read()
            content_type = "image/jpeg"
            tpath = path + ".type"
            if os.path.exists(tpath):
                with open(tpath) as tf:
                    content_type = tf.read().strip() or "image/jpeg"
            return Response(content=blob, media_type=content_type,
                            headers={"Cache-Control": "public, max-age=2592000"})
        except Exception:
            pass

    # Cache miss — fetch the stored external URL, cache, and serve.
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("SELECT cover_url, title, author, cover_variant FROM native_books WHERE id=%s", (book_id,))
        row = cur.fetchone()
        conn.close()
    except Exception:
        row = None

    if not row:
        raise HTTPException(status_code=404, detail="No cover")

    url = row.get("cover_url")
    if url and url.startswith(("http://", "https://")):
        from .. import metadata
        downloaded = metadata.download_cover(url)
        if downloaded:
            blob, content_type = downloaded
            _cache_cover(book_id, blob, content_type)
            return Response(content=blob, media_type=content_type,
                            headers={"Cache-Control": "public, max-age=2592000"})
        # fall through to a generated cover if the external fetch fails

    # No real cover — serve a Calibre-style generated cover (title + author).
    return _generated_cover(row.get("title"), row.get("author"), row.get("cover_variant"))


def _generated_cover(title, author, variant) -> Response:
    from .. import cover_gen
    svg = cover_gen.generate_svg(title or "Untitled", author or "", variant)
    return Response(content=svg.encode("utf-8"), media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


@router.post("/{book_id}/cover/generate", response_model=NativeBook, summary="Cycle the generated cover style")
def regenerate_native_cover(book_id: int, request: Request):
    """Pick the next generated-cover palette for a book with no uploaded cover."""
    _require_admin(request)
    from .. import cover_gen
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("SELECT title, author, cover_variant FROM native_books WHERE id=%s", (book_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail=f"Book {book_id} not found")
        current = (row["cover_variant"] if row["cover_variant"] is not None
                   else cover_gen.variant_index(row["title"], row["author"], None))
        nxt = (current + 1) % cover_gen.NUM_PALETTES
        cur.execute(
            "UPDATE native_books SET cover_variant=%s, updated_at=NOW() WHERE id=%s RETURNING *",
            (nxt, book_id),
        )
        updated = cur.fetchone()
        conn.commit()
        conn.close()
        return NativeBook(**dict(updated))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")


_MAX_COVER_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post("/{book_id}/cover", response_model=NativeBook, summary="Upload a cover image for a native book")
async def upload_native_cover(book_id: int, request: Request, file: UploadFile = File(...)):
    _require_admin(request)
    content_type = file.content_type or "image/jpeg"
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    blob = await file.read()
    if not blob:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(blob) > _MAX_COVER_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 10 MB)")

    try:
        conn = _pg()
        cur = conn.cursor()
        # Sentinel cover_url marks a manually-uploaded cover served from cache.
        cur.execute(
            """
            UPDATE native_books
               SET cover_url = %s, metadata_source = 'manual',
                   enrich_status = 'manual', enriched_at = NOW(), updated_at = NOW()
             WHERE id = %s
            RETURNING *
            """,
            (f"manual:{book_id}", book_id),
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail=f"Book {book_id} not found")
        _cache_cover(book_id, blob, content_type)
        conn.commit()
        conn.close()
        return NativeBook(**dict(row))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")


@router.delete("/{book_id}/cover", response_model=NativeBook, summary="Remove a native book's cover")
def delete_native_cover(book_id: int, request: Request):
    _require_admin(request)
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute(
            "UPDATE native_books SET cover_url = NULL, updated_at = NOW() WHERE id = %s RETURNING *",
            (book_id,),
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            raise HTTPException(status_code=404, detail=f"Book {book_id} not found")
        conn.commit()
        conn.close()
        for ext in ("", ".type"):
            try:
                os.remove(_cover_path(book_id) + ext)
            except OSError:
                pass
        return NativeBook(**dict(row))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")


@router.delete("/{book_id}", status_code=204, summary="Delete a native (physical/digital) book (admin)")
def delete_native_book(book_id: int, request: Request):
    _require_admin(request)
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("SELECT id FROM native_books WHERE id = %s", (book_id,))
        if not cur.fetchone():
            conn.close()
            raise HTTPException(status_code=404, detail=f"Book {book_id} not found")
        # book_id is a plain integer in these tables (not an FK to native_books),
        # so nothing cascades — clear every 'native' reference explicitly, then the
        # book row, in one transaction. Table names are hardcoded literals.
        for tbl in ("shelf_books", "book_ownership", "lending", "reading_progress",
                    "document_map", "read_log", "wishlist"):
            cur.execute(
                f"DELETE FROM {tbl} WHERE book_id = %s AND book_source = 'native'",
                (book_id,),
            )
        cur.execute("DELETE FROM native_books WHERE id = %s", (book_id,))
        conn.commit()
        conn.close()
        # Best-effort: drop any cached/uploaded cover files for this book.
        for ext in ("", ".type"):
            try:
                os.remove(_cover_path(book_id) + ext)
            except OSError:
                pass
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")
