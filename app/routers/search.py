"""
Full-text search endpoint — searches inside actual book content.

Two tiers: the private BM25 index (app/search_index.py — relevance-ranked,
stemmed, quoted-phrase aware) is the primary path; a plain LIKE scan over
Calibre's full-text-search.db is the fallback while that index is missing or
still building. Search inside book content is a unique differentiator: no other
self-hosted library tool offers it.
"""

from fastapi import APIRouter, Query, Request, HTTPException
from pydantic import BaseModel
from typing import Optional
import os
from ..search_index import FTS_DB


router = APIRouter()


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
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("BM25 index search failed, using LIKE fallback: %s", e)
            hits = None

    if hits is None:
        # The index is still building (first start, or after a library change).
        # The old fallback ran LIKE '%term%' over the ENTIRE books_text table --
        # gigabytes of book text, tens of seconds to minutes per query, and it
        # could be triggered 30x/minute per user. Say so instead.
        raise HTTPException(
            status_code=503,
            detail="Full-text search is building its index — try again in a minute.",
            headers={"Retry-After": "60"},
        )

    if not hits:
        return SearchResponse(query=q, total=0, results=[])

    # Look up book metadata from Calibre -- one query for the books (with the
    # genre predicate in SQL as a defensive re-check) and one for their authors,
    # instead of three queries per hit.
    results = []
    ids = [h["book"] for h in hits]
    ph = ",".join("?" * len(ids))
    pred, pp = access.calibre_predicate(allowed, "b")
    extra = f" AND {pred}" if pred else ""
    with get_conn() as meta_conn:
        books = {r["id"]: r for r in meta_conn.execute(
            f"SELECT b.id, b.title, b.has_cover FROM books b WHERE b.id IN ({ph}){extra}", [*ids, *pp])}
        names: dict = {i: [] for i in ids}
        for r in meta_conn.execute(
            f"SELECT bal.book AS book, a.name FROM books_authors_link bal JOIN authors a ON a.id = bal.author "
            f"WHERE bal.book IN ({ph}) ORDER BY bal.book, a.sort", ids):
            names[r["book"]].append(r["name"])
        for h in hits:
            book = books.get(h["book"])
            if not book:
                continue
            has_cover = bool(book["has_cover"])
            results.append(SearchResult(
                book_id=book["id"],
                title=book["title"],
                authors=names[book["id"]],
                format=h["format"],
                excerpt=h["excerpt"],
                has_cover=has_cover,
                cover_url=f"{base_url}/api/covers/{book['id']}" if has_cover else None,
            ))

    return SearchResponse(query=q, total=total, results=results)


@router.get("/index-status", summary="BM25 search-index status (admin)")
def index_status(request: Request):
    from .. import auth, search_index
    auth.require_admin(request)
    return search_index.status()


@router.post("/reindex", summary="Refresh the BM25 search index (admin)")
def reindex(request: Request):
    from .. import auth, search_index
    auth.require_admin(request)
    search_index.sync_async("manual")
    return {"ok": True, "status": search_index.status()}
