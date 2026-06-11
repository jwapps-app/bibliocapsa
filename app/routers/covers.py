"""
Cover image endpoint — serves cover.jpg from Calibre's folder structure.
Calibre stores covers at: {library_root}/{book_path}/cover.jpg
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
import os

router = APIRouter()

CALIBRE_ROOT = os.getenv("CALIBRE_LIBRARY_PATH", "/calibre")
PLACEHOLDER_COVER = os.path.join(os.path.dirname(__file__), "..", "assets", "no_cover.jpg")


@router.get("/{book_id}", summary="Serve cover image for a book")
def get_cover(book_id: int, request: Request):
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

    return FileResponse(
        cover_path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )
