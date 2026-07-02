"""
Cover image endpoint — serves cover.jpg from Calibre's folder structure.
Calibre stores covers at: {library_root}/{book_path}/cover.jpg

Supports ?w=<px> thumbnails: the library grid renders covers at ~150-250 px but
the originals average ~240 KB (a 48-book page shipped ~11 MB of images). Resized
JPEGs are cached on disk in the covers volume and invalidated when the original
cover changes (mtime check), so a page of grid thumbnails is ~1 MB instead.
"""

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
import logging
import os

logger = logging.getLogger(__name__)
router = APIRouter()

CALIBRE_ROOT = os.getenv("CALIBRE_LIBRARY_PATH", "/calibre")
PLACEHOLDER_COVER = os.path.join(os.path.dirname(__file__), "..", "assets", "no_cover.jpg")
THUMB_DIR = os.path.join(os.getenv("COVER_CACHE_DIR", "/app/cover_cache"), "thumbs")
# Fixed set of widths so the cache can't be ballooned by arbitrary ?w values.
THUMB_WIDTHS = (200, 300, 600)


def _thumb_for(cover_path: str, book_id: int, w: int):
    """Path to a cached thumbnail, (re)generating it if missing or stale.
    Returns None on any failure so the caller falls back to the original."""
    try:
        from PIL import Image
        thumb = os.path.join(THUMB_DIR, f"{book_id}_{w}.jpg")
        src_mtime = os.path.getmtime(cover_path)
        if os.path.isfile(thumb) and os.path.getmtime(thumb) >= src_mtime:
            return thumb
        os.makedirs(THUMB_DIR, exist_ok=True)
        with Image.open(cover_path) as im:
            if im.width <= w:  # never upscale — serve the original
                return None
            im = im.convert("RGB")
            im.thumbnail((w, w * 3), Image.LANCZOS)  # width-bound; 2:3-ish covers
            im.save(thumb, "JPEG", quality=80, optimize=True)
        return thumb
    except Exception as e:
        logger.debug("thumbnail failed for book %s: %s", book_id, e)
        return None


@router.get("/{book_id}", summary="Serve cover image for a book")
def get_cover(book_id: int, request: Request,
              w: int = Query(0, ge=0, le=1200, description="Optional thumbnail width")):
    from ..database import get_conn
    from .. import access

    with get_conn() as conn:
        row = conn.execute(
            "SELECT path, has_cover FROM books WHERE id = ?", (book_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Book {book_id} not found")
        if not access.is_calibre_book_allowed(conn, book_id, access.restriction_for_request(request)):
            raise HTTPException(status_code=404, detail=f"Book {book_id} not found")

    if not row["has_cover"]:
        # Return a 204 or placeholder
        if os.path.isfile(PLACEHOLDER_COVER):
            return FileResponse(PLACEHOLDER_COVER, media_type="image/jpeg")
        raise HTTPException(status_code=404, detail="No cover available")

    cover_path = os.path.join(CALIBRE_ROOT, row["path"], "cover.jpg")

    if not os.path.isfile(cover_path):
        raise HTTPException(status_code=404, detail="No cover available")

    serve_path = cover_path
    if w:
        # Snap to the nearest allowed width (bounded cache), then try the thumb.
        width = min(THUMB_WIDTHS, key=lambda t: abs(t - w))
        thumb = _thumb_for(cover_path, book_id, width)
        if thumb:
            serve_path = thumb

    return FileResponse(
        serve_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )
