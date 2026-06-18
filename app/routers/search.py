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

# Common words dropped from multi-word queries so a natural phrase matches on its
# meaningful words rather than every book containing "in"/"of"/"the".
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "had",
    "has", "have", "he", "her", "his", "in", "into", "is", "it", "its", "of", "on",
    "or", "she", "that", "the", "their", "them", "they", "this", "to", "was",
    "were", "will", "with", "you", "your",
}


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
    """Snippet around the best available match: prefer the full phrase, else the
    first individual word that appears (so multi-word searches still show a
    relevant passage rather than the start of the book)."""
    lower_text = text.lower()
    pos, match_len = -1, len(query)
    for cand in [query, *query.split()]:
        c = cand.lower().strip()
        if not c:
            continue
        p = lower_text.find(c)
        if p != -1:
            pos, match_len = p, len(cand)
            break
    if pos == -1:
        return text[:context].strip() + "…"
    start = max(0, pos - context // 2)
    end = min(len(text), pos + match_len + context // 2)
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

    # Prefer the BM25 index (relevance-ranked + stemmed); fall back to the simpler
    # LIKE scan if the index is missing or still building. Both paths produce a
    # normalized `hits` list of {book, format, excerpt}.
    from .. import search_index
    hits = None
    total = 0
    if search_index.is_ready():
        try:
            total, hits = search_index.search(q, allowed_ids, limit, offset)
        except Exception:
            hits = None  # fall back to LIKE

    if hits is None:
        try:
            fts_conn = sqlite3.connect(f"file:{FTS_DB}?mode=ro", uri=True)
            fts_conn.row_factory = sqlite3.Row
            # Match each word separately (any order/distance), exact phrase ranked
            # first. (Calibre's FTS5 uses a custom tokenizer stock sqlite3 can't
            # load, hence LIKE here rather than MATCH.)
            raw_terms = [t for t in q.split() if t.strip()]
            terms = [t for t in raw_terms if t.lower() not in _STOPWORDS] or raw_terms or [q]
            term_conds = " AND ".join("searchable_text LIKE ?" for _ in terms)
            where = f"({term_conds}) AND searchable_text IS NOT NULL"
            wparams: list = [f"%{t}%" for t in terms]
            if allowed_ids is not None:
                fts_conn.execute("CREATE TEMP TABLE _allowed (book INTEGER PRIMARY KEY)")
                fts_conn.executemany("INSERT OR IGNORE INTO _allowed (book) VALUES (?)",
                                     [(i,) for i in allowed_ids])
                where += " AND book IN (SELECT book FROM _allowed)"
            rows = fts_conn.execute(
                f"SELECT book, MIN(format) AS format, searchable_text FROM books_text WHERE {where} "
                f"GROUP BY book ORDER BY (CASE WHEN searchable_text LIKE ? THEN 0 ELSE 1 END), book "
                f"LIMIT ? OFFSET ?",
                wparams + [f"%{q}%", limit, offset],
            ).fetchall()
            total_row = fts_conn.execute(
                f"SELECT COUNT(DISTINCT book) FROM books_text WHERE {where}", wparams,
            ).fetchone()
            total = total_row[0] if total_row else 0
            fts_conn.close()
            hits = [{"book": r["book"], "format": r["format"],
                     "excerpt": _excerpt(r["searchable_text"], q)} for r in rows]
        except sqlite3.Error:
            raise HTTPException(status_code=500, detail="Full-text search error")

    if not hits:
        return SearchResponse(query=q, total=0, results=[])

    # Look up book metadata from Calibre
    results = []

    with get_conn() as meta_conn:
        for h in hits:
            book_id = h["book"]
            book = meta_conn.execute(
                "SELECT id, title, has_cover FROM books WHERE id = ?", (book_id,)
            ).fetchone()

            if not book:
                continue

            # Hide content the member isn't allowed to see (defensive re-check on
            # top of the query-level allow-list).
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
            has_cover = bool(book["has_cover"])

            results.append(SearchResult(
                book_id=book_id,
                title=book["title"],
                authors=author_names,
                format=h["format"],
                excerpt=h["excerpt"],
                has_cover=has_cover,
                cover_url=f"{base_url}/api/covers/{book_id}" if has_cover else None,
            ))

    return SearchResponse(query=q, total=total, results=results)


@router.get("/index-status", summary="BM25 search-index status (admin)")
def index_status(request: Request):
    from .. import auth, search_index
    u = auth.authenticate_request(request)
    if not u or u.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return search_index.status()


@router.post("/reindex", summary="Refresh the BM25 search index (admin)")
def reindex(request: Request):
    from .. import auth, search_index
    u = auth.authenticate_request(request)
    if not u or u.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    search_index.sync_async("manual")
    return {"ok": True, "status": search_index.status()}
