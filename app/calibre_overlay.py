"""
Pending Calibre edit overlay.

Edits to Calibre books are written to PostgreSQL (`calibre_edits`) instantly and
merged over the read-only Calibre data when serving — so changes show up at once
without touching Calibre. A later deliberate "Sync to Calibre" (Phase 2) applies
them via calibredb and clears the rows.
"""

import json
import os
from typing import Optional

UPLOADS_DIR = os.getenv("UPLOADS_DIR", "/app/uploads")

# Fields a user may edit (and that map to BookSummary/BookDetail + calibredb later).
EDITABLE_FIELDS = {
    "title", "authors", "comment", "series", "series_index",
    "tags", "publisher", "pubdate", "rating", "isbn",
}


def _pg():
    from .pg_database import get_database_url
    import psycopg2
    from psycopg2.extras import RealDictCursor
    return psycopg2.connect(get_database_url(), cursor_factory=RealDictCursor)


def get_edits(book_ids) -> dict:
    """{book_id: {field: value}} for the given Calibre book ids (native types)."""
    ids = list(book_ids)
    if not ids:
        return {}
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("SELECT book_id, field, value FROM calibre_edits WHERE book_id = ANY(%s)", (ids,))
        out: dict = {}
        for r in cur.fetchall():
            out.setdefault(r["book_id"], {})[r["field"]] = r["value"]
        return out
    finally:
        conn.close()


def set_edits(book_id: int, fields: dict) -> None:
    conn = _pg()
    try:
        cur = conn.cursor()
        for k, v in fields.items():
            # Standard fields, or custom columns keyed "custom:<label>".
            if k not in EDITABLE_FIELDS and not k.startswith("custom:"):
                continue
            cur.execute(
                """INSERT INTO calibre_edits (book_id, field, value, updated_at)
                   VALUES (%s, %s, %s::jsonb, NOW())
                   ON CONFLICT (book_id, field) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()""",
                (book_id, k, json.dumps(v)),
            )
        conn.commit()
    finally:
        conn.close()


def discard(book_id: int, field: Optional[str] = None) -> None:
    conn = _pg()
    try:
        cur = conn.cursor()
        if field:
            cur.execute("DELETE FROM calibre_edits WHERE book_id = %s AND field = %s", (book_id, field))
        else:
            cur.execute("DELETE FROM calibre_edits WHERE book_id = %s", (book_id,))
        conn.commit()
    finally:
        conn.close()


def pending() -> list:
    """Pending edits grouped by book, newest first."""
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT book_id, field, value, EXTRACT(EPOCH FROM updated_at)::bigint AS ts "
            "FROM calibre_edits ORDER BY updated_at DESC"
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    by: dict = {}
    for r in rows:
        b = by.setdefault(r["book_id"], {"book_id": r["book_id"], "fields": {}, "updated_at": r["ts"]})
        b["fields"][r["field"]] = r["value"]
    return list(by.values())


def pending_count() -> int:
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM calibre_edits")
        return cur.fetchone()["c"]
    finally:
        conn.close()


# ── Merge overlay onto Pydantic models (mutates in place) ────────────────────
def apply_to_summary(s, edits: dict):
    from .schemas import Author, SeriesRef, TagRef
    if not edits:
        return s
    if edits.get("title"):
        s.title = edits["title"]
    if isinstance(edits.get("authors"), list):
        s.authors = [Author(id=0, name=n, sort=n) for n in edits["authors"]]
    if edits.get("rating") is not None:
        s.rating = edits["rating"]
    if edits.get("pubdate"):
        s.pubdate = edits["pubdate"]
    if isinstance(edits.get("tags"), list):
        s.tags = [TagRef(id=0, name=n) for n in edits["tags"]]
    if "series" in edits or "series_index" in edits:
        name = edits.get("series") if edits.get("series") is not None else (s.series.name if s.series else None)
        idx = edits.get("series_index", s.series.series_index if s.series else None)
        s.series = SeriesRef(id=0, name=name, series_index=idx) if name else None
    return s


def apply_to_detail(d, edits: dict):
    apply_to_summary(d, edits)
    if not edits:
        return d
    if "comment" in edits:
        d.comment = edits["comment"]
    if "publisher" in edits:
        d.publisher = edits["publisher"]
    if "isbn" in edits:
        d.isbn = edits["isbn"]
    if "series_index" in edits:
        d.series_index = edits["series_index"]
    return d


# ── Pending new-book uploads ─────────────────────────────────────────────────
def add_upload(filename: str, orig_name: str, title: Optional[str], authors: Optional[str],
               fmt: str, size: int) -> dict:
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO calibre_uploads (filename, orig_name, title, authors, format, size)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
            (filename, orig_name, title, authors, fmt, size),
        )
        row = dict(cur.fetchone())
        conn.commit()
        return row
    finally:
        conn.close()


def list_uploads() -> list:
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, filename, orig_name, title, authors, format, size, "
            "EXTRACT(EPOCH FROM created_at)::bigint AS ts FROM calibre_uploads ORDER BY created_at DESC"
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_upload(upload_id: int) -> Optional[dict]:
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM calibre_uploads WHERE id = %s", (upload_id,))
        r = cur.fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def uploads_count() -> int:
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM calibre_uploads")
        return cur.fetchone()["c"]
    finally:
        conn.close()


def discard_upload(upload_id: int) -> None:
    rec = get_upload(upload_id)
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM calibre_uploads WHERE id = %s", (upload_id,))
        conn.commit()
    finally:
        conn.close()
    if rec:
        try:
            os.remove(os.path.join(UPLOADS_DIR, rec["filename"]))
        except OSError:
            pass


def apply_to_items(items, edits_map: dict):
    """Apply overlay to a list of BookSummary (Calibre items only)."""
    if not edits_map:
        return items
    for it in items:
        if getattr(it, "book_source", None) == "native":
            continue
        e = edits_map.get(it.id)
        if e:
            apply_to_summary(it, e)
    return items
