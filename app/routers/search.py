"""
Full-text search endpoint — searches inside actual book content.
Uses Calibre's full-text-search.db (books_text table).
This is a unique differentiator: no other self-hosted library tool offers this.
"""

from fastapi import APIRouter, Query, Request, HTTPException
from pydantic import BaseModel
from typing import Optional
import os
import sqlite3

router = APIRouter()

FTS_DB = os.getenv("CALIBRE_FTS_DB_PATH", "/calibre/full-text-search.db")


class SearchResult(BaseModel):
    book_id: int
    title: str
    authors: list[str]
    format: str
    excerpt: str
    cover_url: Optional[str] = None
    has_cover: bool = False


class SearchResponse(BaseModel):
    query: str
    total: int
    results: list[SearchResult]


def _excerpt(text: str, query: str, context: int = 200) -> str:
    """Extract a snippet of text around the first match."""
    lower_text = text.lower()
    lower_query = query.lower()
    pos = lower_text.find(lower_query)
    if pos == -1:
        return text[:context].strip() + "…"
    start = max(0, pos - context // 2)
    end = min(len(text), pos + len(query) + context // 2)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet = snippet + "…"
    return snippet


@router.get("", response_model=SearchResponse, summary="Full-text search inside book content")
def full_text_search(
    request: Request,
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    from .. import ratelimit
    ratelimit.check(ratelimit.client_key(request, "fts"), limit=30, window=60)
    base_url = str(request.base_url).rstrip("/")

    if not os.path.isfile(FTS_DB):
        raise HTTPException(
            status_code=503,
            detail="Full-text search database not found. Enable full-text search in Calibre first."
        )

    from ..database import get_conn
    from .. import access

    # For restricted members, constrain the search to their allowed book IDs at
    # the query level — otherwise the first N content matches (mostly disallowed)
    # would be filtered away to nothing.
    allowed = access.restriction_for_request(request)
    allowed_ids = None
    if allowed is not None:
        with get_conn() as meta_conn:
            qs = ",".join("?" * len(allowed))
            allowed_ids = [r[0] for r in meta_conn.execute(
                f"SELECT DISTINCT btl.book FROM books_tags_link btl JOIN tags t ON t.id=btl.tag "
                f"WHERE LOWER(t.name) IN ({qs})", list(allowed)
            ).fetchall()]
        if not allowed_ids:
            return SearchResponse(query=q, total=0, results=[])

    # Search in the full-text database
    try:
        fts_conn = sqlite3.connect(f"file:{FTS_DB}?mode=ro", uri=True)
        fts_conn.row_factory = sqlite3.Row

        # Use LIKE for broad compatibility — no custom tokenizer needed
        like_query = f"%{q}%"
        where = "searchable_text LIKE ? AND searchable_text IS NOT NULL"
        wparams: list = [like_query]
        if allowed_ids is not None:
            # Stash the allow-list in a TEMP table (SQLite keeps temp objects in a
            # separate temp DB, so this works even on a read-only connection) and
            # join via a subquery — avoids the ~999 host-parameter cap that a
            # literal `book IN (?, ?, …)` would blow past for a broad allow-list
            # (which previously 500'd restricted members).
            fts_conn.execute("CREATE TEMP TABLE _allowed (book INTEGER PRIMARY KEY)")
            fts_conn.executemany("INSERT OR IGNORE INTO _allowed (book) VALUES (?)",
                                 [(i,) for i in allowed_ids])
            where += " AND book IN (SELECT book FROM _allowed)"

        rows = fts_conn.execute(
            f"SELECT book, format, searchable_text FROM books_text WHERE {where} LIMIT ? OFFSET ?",
            wparams + [limit, offset],
        ).fetchall()

        total_row = fts_conn.execute(
            f"SELECT COUNT(*) FROM books_text WHERE {where}", wparams,
        ).fetchone()
        total = total_row[0] if total_row else 0

        fts_conn.close()
    except sqlite3.Error:
        raise HTTPException(status_code=500, detail="Full-text search error")

    if not rows:
        return SearchResponse(query=q, total=0, results=[])

    # Look up book metadata from Calibre
    results = []

    with get_conn() as meta_conn:
        for row in rows:
            book_id = row["book"]
            book = meta_conn.execute(
                "SELECT id, title, has_cover FROM books WHERE id = ?", (book_id,)
            ).fetchone()

            if not book:
                continue

            # Hide content the member isn't allowed to see.
            if not access.is_calibre_book_allowed(meta_conn, book_id, allowed):
                continue

            authors = meta_conn.execute(
                """
                SELECT a.name FROM authors a
                JOIN books_authors_link bal ON bal.author = a.id
                WHERE bal.book = ?
                ORDER BY a.sort
                """,
                (book_id,),
            ).fetchall()

            author_names = [a["name"] for a in authors]
            excerpt = _excerpt(row["searchable_text"], q)
            has_cover = bool(book["has_cover"])

            results.append(SearchResult(
                book_id=book_id,
                title=book["title"],
                authors=author_names,
                format=row["format"],
                excerpt=excerpt,
                has_cover=has_cover,
                cover_url=f"{base_url}/api/covers/{book_id}" if has_cover else None,
            ))

    return SearchResponse(query=q, total=total, results=results)
