"""Per-user 'want to read' list — books the user wants but doesn't own yet."""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


def _user(request: Request) -> dict:
    from .. import auth
    u = auth.authenticate_request(request)
    if not u:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return u


def _pg():
    from ..pg_database import get_pg
    return get_pg()


class WishItem(BaseModel):
    title: str
    author: Optional[str] = None
    isbn: Optional[str] = None
    cover_url: Optional[str] = None
    notes: Optional[str] = None
    book_id: Optional[int] = None       # set when bookmarking an owned library book
    book_source: Optional[str] = None   # 'calibre' | 'native'


@router.get("", summary="The current user's want-to-read list")
def list_wishlist(request: Request):
    u = _user(request)
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title, author, isbn, cover_url, notes, book_id, book_source, "
            "EXTRACT(EPOCH FROM added_at)::bigint AS added_ts "
            "FROM wishlist WHERE user_id=%s ORDER BY added_at DESC",
            (u["id"],),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


@router.get("/contains", summary="Is an owned book on the user's want-to-read list?")
def contains(request: Request, book_id: int, book_source: str = "calibre"):
    u = _user(request)
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM wishlist WHERE user_id=%s AND book_id=%s AND book_source=%s LIMIT 1",
            (u["id"], book_id, book_source),
        )
        row = cur.fetchone()
        return {"bookmarked": bool(row), "id": (row["id"] if row else None)}
    finally:
        conn.close()


@router.post("", summary="Add a book to the want-to-read list")
def add_wishlist(body: WishItem, request: Request):
    u = _user(request)
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    conn = _pg()
    try:
        cur = conn.cursor()
        # Bookmarking an owned book that's already listed is a no-op (idempotent).
        if body.book_id is not None:
            cur.execute(
                "SELECT id FROM wishlist WHERE user_id=%s AND book_id=%s AND book_source=%s",
                (u["id"], body.book_id, body.book_source or "calibre"),
            )
            existing = cur.fetchone()
            if existing:
                return {"id": existing["id"]}
        cur.execute(
            "INSERT INTO wishlist (user_id, title, author, isbn, cover_url, notes, book_id, book_source) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (u["id"], title, (body.author or None), (body.isbn or None),
             (body.cover_url or None), (body.notes or None),
             body.book_id, (body.book_source if body.book_id is not None else None)),
        )
        rid = cur.fetchone()["id"]
        conn.commit()
        return {"id": rid}
    finally:
        conn.close()


@router.delete("/{item_id}", summary="Remove a book from the want-to-read list")
def remove_wishlist(item_id: int, request: Request):
    u = _user(request)
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM wishlist WHERE id=%s AND user_id=%s", (item_id, u["id"]))
        conn.commit()
        return {"deleted": cur.rowcount}
    finally:
        conn.close()
