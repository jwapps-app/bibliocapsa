"""
Book file serving — serves EPUB, PDF, MOBI directly from Calibre's folder structure.
Read-only. Never modifies files.
"""

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import FileResponse
import os
import re

router = APIRouter()

CALIBRE_ROOT = os.getenv("CALIBRE_LIBRARY_PATH", "/calibre")

MIME_TYPES = {
    "EPUB": "application/epub+zip",
    "PDF":  "application/pdf",
    "MOBI": "application/x-mobipocket-ebook",
    "AZW3": "application/vnd.amazon.ebook",
    "AZW":  "application/vnd.amazon.ebook",
    "TXT":  "text/plain",
    "RTF":  "application/rtf",
    "LIT":  "application/x-ms-reader",
    "FB2":  "application/x-fictionbook+xml",
    "DOCX": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "CBZ":  "application/x-cbz",
    "CBR":  "application/x-cbr",
}


@router.post("/{book_id}/send-to-kindle", summary="Email a book to the user's Kindle")
def send_to_kindle(book_id: int, request: Request):
    from ..database import get_conn
    from .. import access, mailer

    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    to = (user.get("kindle_email") or "").strip()
    if not to:
        raise HTTPException(status_code=400, detail="Set your Kindle email in Settings first")
    if not mailer.is_configured():
        raise HTTPException(status_code=400, detail="Email isn't configured — ask an admin to set up SMTP in Settings")

    with get_conn() as conn:
        book = conn.execute("SELECT path, title FROM books WHERE id = ?", (book_id,)).fetchone()
        if not book:
            raise HTTPException(status_code=404, detail=f"Book {book_id} not found")
        if not access.is_calibre_book_allowed(conn, book_id, access.restriction_for_request(request)):
            raise HTTPException(status_code=404, detail=f"Book {book_id} not found")
        fmts = {r["format"].upper(): r["name"]
                for r in conn.execute("SELECT format, name FROM data WHERE book = ?", (book_id,)).fetchall()}

    pref = next((f for f in ("EPUB", "AZW3", "MOBI", "PDF") if f in fmts), None)
    if not pref:
        raise HTTPException(status_code=400, detail="No Kindle-compatible format available")

    file_path = os.path.join(CALIBRE_ROOT, book["path"], f"{fmts[pref]}.{pref.lower()}")
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")
    with open(file_path, "rb") as f:
        blob = f.read()

    safe = re.sub(r"[^\w\s.-]", "", book["title"]).strip() or "book"
    try:
        mailer.send_email(
            to=to, subject=book["title"],
            body=f"Sent from Bibliocapsa: {book['title']}",
            attachment=blob, attachment_name=f"{safe}.{pref.lower()}",
            attachment_mime=MIME_TYPES.get(pref, "application/octet-stream"),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Send failed: {e}")
    return {"ok": True, "sent_to": to, "format": pref}


@router.get("/{book_id}/file/{fmt}", summary="Download a book file")
def serve_book_file(book_id: int, fmt: str, request: Request,
                    inline: bool = Query(False, description="Serve inline (for in-browser reading) instead of as a download")):
    from ..database import get_conn
    from .. import access

    fmt_upper = fmt.upper()

    with get_conn() as conn:
        # Get book path and verify format exists
        book = conn.execute(
            "SELECT path, title FROM books WHERE id = ?", (book_id,)
        ).fetchone()

        if not book:
            raise HTTPException(status_code=404, detail=f"Book {book_id} not found")

        if not access.is_calibre_book_allowed(conn, book_id, access.restriction_for_request(request)):
            raise HTTPException(status_code=404, detail=f"Book {book_id} not found")

        data_row = conn.execute(
            "SELECT name FROM data WHERE book = ? AND format = ?",
            (book_id, fmt_upper),
        ).fetchone()

        if not data_row:
            raise HTTPException(
                status_code=404,
                detail=f"Format {fmt_upper} not available for book {book_id}"
            )

    # Construct file path: {library}/{book_path}/{filename}.{ext}
    filename = f"{data_row['name']}.{fmt_upper.lower()}"
    file_path = os.path.join(CALIBRE_ROOT, book["path"], filename)

    if not os.path.isfile(file_path):
        raise HTTPException(
            status_code=404,
            detail=f"File not found on disk: {filename}"
        )

    media_type = MIME_TYPES.get(fmt_upper, "application/octet-stream")

    # Map this file's KOReader document hash → book, so reading progress synced
    # from KOReader can be tied back to it. Cheap (reads ~12 KB).
    try:
        from .. import kohash
        kohash.record_document(book_id, fmt_upper, file_path, "calibre")
    except Exception:
        pass

    disposition = "inline" if inline else "attachment"
    return FileResponse(
        file_path,
        media_type=media_type,
        filename=filename,
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"',
            "Cache-Control": "private, max-age=3600",
        }
    )
