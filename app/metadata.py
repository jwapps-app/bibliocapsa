"""
Metadata enrichment for native (physical) books.

Looks up cover art and bibliographic metadata for books that only exist in the
native PostgreSQL library (not in Calibre). Primary source is Hardcover's GraphQL
API (richest data, requires a personal bearer token); falls back to Open Library
(free, no auth) when Hardcover misses or no token is configured.

Uses only the Python standard library (urllib) — no extra dependencies.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse, urljoin

logger = logging.getLogger(__name__)


def _is_public_url(url: str) -> bool:
    """SSRF guard: allow only http(s) URLs whose host resolves entirely to
    public IPs. Rejects localhost, private ranges, link-local (cloud metadata
    169.254.169.254), reserved/multicast — so a user-supplied cover URL can't
    make the server reach into its own network."""
    try:
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname:
            return False
        port = p.port or (443 if p.scheme == "https" else 80)
        infos = socket.getaddrinfo(p.hostname, port, proto=socket.IPPROTO_TCP)
        if not infos:
            return False
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                    or ip.is_multicast or ip.is_unspecified):
                return False
        return True
    except Exception:
        return False

HARDCOVER_ENDPOINT = "https://api.hardcover.app/v1/graphql"
OPENLIBRARY_ISBN_API = "https://openlibrary.org/isbn/{isbn}.json"
OPENLIBRARY_COVER = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"

USER_AGENT = "Bibliocapsa/1.0 (self-hosted personal library)"
TIMEOUT = 15


@dataclass
class Metadata:
    """Normalized metadata gathered from an external source."""
    cover_url: Optional[str] = None
    description: Optional[str] = None
    page_count: Optional[int] = None
    publisher: Optional[str] = None
    published_date: Optional[str] = None
    rating: Optional[float] = None  # community rating, normalized to 0–5
    source: Optional[str] = None  # "hardcover" | "openlibrary"

    def is_useful(self) -> bool:
        """A result is worth saving if it has a cover or a description."""
        return bool(self.cover_url or self.description)


def _clean_isbn(isbn: Optional[str]) -> Optional[str]:
    if not isbn:
        return None
    cleaned = re.sub(r"[^0-9Xx]", "", isbn).upper()
    return cleaned or None


# ── Hardcover ────────────────────────────────────────────────────────────────

_HARDCOVER_QUERY = """
query BookByIsbn($isbn: String!) {
  editions(where: {isbn_13: {_eq: $isbn}}, limit: 1) {
    title
    pages
    release_date
    image { url }
    publisher { name }
    book {
      description
      rating
      image { url }
    }
  }
}
"""


def _http_post_json(url: str, payload: dict, headers: dict) -> Optional[dict]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")[:300]
        except Exception:
            pass
        logger.warning("Hardcover HTTP %s: %s", e.code, body)
        return None
    except Exception as e:
        logger.warning("Hardcover request failed: %s", e)
        return None


def _http_get_json(url: str) -> Optional[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code != 404:
            logger.warning("Open Library HTTP %s for %s", e.code, url)
        return None
    except Exception as e:
        logger.warning("Open Library request failed: %s", e)
        return None


def lookup_hardcover(isbn13: Optional[str], token: str) -> Optional[Metadata]:
    isbn = _clean_isbn(isbn13)
    if not isbn or len(isbn) != 13:
        return None

    token = token.strip()
    # Hardcover tokens are JWTs; accept with or without an explicit "Bearer " prefix.
    auth = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": auth,
        "User-Agent": USER_AGENT,
    }
    result = _http_post_json(
        HARDCOVER_ENDPOINT,
        {"query": _HARDCOVER_QUERY, "variables": {"isbn": isbn}},
        headers,
    )
    if not result:
        return None
    if result.get("errors"):
        logger.warning("Hardcover GraphQL errors: %s", result["errors"])
        return None

    editions = (result.get("data") or {}).get("editions") or []
    if not editions:
        return None
    ed = editions[0]
    book = ed.get("book") or {}

    cover = (ed.get("image") or {}).get("url") or (book.get("image") or {}).get("url")
    return Metadata(
        cover_url=cover,
        description=(book.get("description") or None),
        page_count=ed.get("pages"),
        publisher=(ed.get("publisher") or {}).get("name"),
        published_date=ed.get("release_date"),
        rating=book.get("rating"),  # Hardcover community rating (0–5)
        source="hardcover",
    )


# ── Open Library ─────────────────────────────────────────────────────────────

def _ol_description(data: dict) -> Optional[str]:
    desc = data.get("description")
    if isinstance(desc, dict):
        return desc.get("value")
    if isinstance(desc, str):
        return desc
    return None


def lookup_openlibrary(isbn: Optional[str]) -> Optional[Metadata]:
    clean = _clean_isbn(isbn)
    if not clean:
        return None

    data = _http_get_json(OPENLIBRARY_ISBN_API.format(isbn=clean))
    # Even without an edition record, Open Library may have a cover by ISBN.
    cover = OPENLIBRARY_COVER.format(isbn=clean)

    if not data:
        # Return cover-only metadata; the cover endpoint 404s (default=false) if missing,
        # which the downloader will detect.
        return Metadata(cover_url=cover, source="openlibrary")

    pages = data.get("number_of_pages")
    publishers = data.get("publishers")
    publisher = publishers[0] if isinstance(publishers, list) and publishers else None

    return Metadata(
        cover_url=cover,
        description=_ol_description(data),
        page_count=pages if isinstance(pages, int) else None,
        publisher=publisher,
        published_date=data.get("publish_date"),
        source="openlibrary",
    )


# ── Candidate search (by title/author, for filling missing metadata) ──────────

OPENLIBRARY_SEARCH = "https://openlibrary.org/search.json"

_HARDCOVER_SEARCH = """
query SearchBooks($q: String!) {
  search(query: $q, query_type: "Book", per_page: 5) { results }
}
"""

_HARDCOVER_DESCS = """
query Descs($ids: [Int!]!) {
  books(where: {id: {_in: $ids}}) { id description rating image { url } }
}
"""


def _ol_work_description(key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    data = _http_get_json(f"https://openlibrary.org{key}.json")
    return _ol_description(data) if data else None


def search_openlibrary(title: str, author: Optional[str], limit: int = 5) -> list[dict]:
    import urllib.parse
    params = {"title": title or "", "limit": str(limit),
              "fields": "key,title,author_name,first_publish_year,isbn,publisher"}
    if author:
        params["author"] = author
    data = _http_get_json(OPENLIBRARY_SEARCH + "?" + urllib.parse.urlencode(params))
    docs = (data or {}).get("docs") or []
    out = []
    for d in docs[:limit]:
        out.append({
            "source": "openlibrary",
            "title": d.get("title"),
            "authors": d.get("author_name") or [],
            "description": None,  # filled for the top few below (needs a work fetch)
            "published_date": str(d["first_publish_year"]) if d.get("first_publish_year") else None,
            "publisher": (d.get("publisher") or [None])[0],
            "isbn": (d.get("isbn") or [None])[0],
            "series": None, "series_index": None, "page_count": None, "cover_url": None,
            "_key": d.get("key"),
        })
    for c in out[:3]:
        c["description"] = _ol_work_description(c.get("_key"))
    for c in out:
        c.pop("_key", None)
    return out


def search_hardcover(title: str, token: Optional[str], limit: int = 5) -> list[dict]:
    if not title or not token:
        return []
    token = token.strip()
    auth = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    headers = {"Content-Type": "application/json", "Authorization": auth, "User-Agent": USER_AGENT}

    result = _http_post_json(HARDCOVER_ENDPOINT, {"query": _HARDCOVER_SEARCH, "variables": {"q": title}}, headers)
    if not result or result.get("errors"):
        if result and result.get("errors"):
            logger.warning("Hardcover search errors: %s", result["errors"])
        return []
    res = ((result.get("data") or {}).get("search") or {}).get("results") or {}
    hits = res.get("hits") if isinstance(res, dict) else None
    if not hits:
        return []

    out, ids = [], []
    for h in hits[:limit]:
        d = h.get("document") or {}
        try:
            bid = int(d.get("id"))
            ids.append(bid)
        except (TypeError, ValueError):
            bid = None
        isbns = d.get("isbns") or []
        out.append({
            "source": "hardcover", "_id": bid,
            "title": d.get("title"),
            "authors": d.get("author_names") or [],
            "description": None,
            "published_date": None, "publisher": None,
            "isbn": next((i for i in isbns if len(re.sub(r"[^0-9Xx]", "", i)) == 13), isbns[0] if isbns else None),
            "series": (d.get("series_names") or [None])[0],
            "series_index": None, "page_count": None, "rating": None,
            "cover_url": (d.get("image") or {}).get("url"),
        })

    # One follow-up call for descriptions + community rating (search index has neither).
    if ids:
        dres = _http_post_json(HARDCOVER_ENDPOINT, {"query": _HARDCOVER_DESCS, "variables": {"ids": ids}}, headers)
        descs = {}
        if dres and not dres.get("errors"):
            for b in (dres.get("data") or {}).get("books") or []:
                descs[b["id"]] = {"description": b.get("description"), "image": (b.get("image") or {}).get("url"), "rating": b.get("rating")}
        for c in out:
            info = descs.get(c.get("_id"))
            if info:
                c["description"] = info["description"] or None
                c["cover_url"] = c["cover_url"] or info["image"]
                c["rating"] = info["rating"]
    for c in out:
        c.pop("_id", None)
    return out


def search_candidates(title: str, author: Optional[str], token: Optional[str]) -> list[dict]:
    """Candidate matches for a book by title/author, Hardcover first then Open Library."""
    candidates: list[dict] = []
    if token:
        try:
            candidates += search_hardcover(title, token)
        except Exception as e:
            logger.warning("Hardcover search failed: %s", e)
    try:
        candidates += search_openlibrary(title, author)
    except Exception as e:
        logger.warning("Open Library search failed: %s", e)
    return candidates


# ── Cover download ───────────────────────────────────────────────────────────

def download_cover(url: str) -> Optional[tuple[bytes, str]]:
    """Download a cover image. Returns (bytes, content_type) or None.

    Open Library returns a 1x1 placeholder for missing covers unless
    `default=false` is set (which 404s instead) — we use that, so any
    successful small-but-real image is genuine.
    """
    if not url:
        return None
    # SSRF-safe fetch: validate every hop (redirects can point back inside the
    # network), don't auto-follow, and cap redirects + download size.
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    opener = urllib.request.build_opener(_NoRedirect)
    MAX_BYTES = 15 * 1024 * 1024
    try:
        for _ in range(5):  # at most 5 redirects
            if not _is_public_url(url):
                logger.info("Cover URL blocked (non-public): %s", url)
                return None
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            try:
                resp = opener.open(req, timeout=TIMEOUT)
            except urllib.error.HTTPError as e:
                if e.code in (301, 302, 303, 307, 308) and e.headers.get("Location"):
                    url = urljoin(url, e.headers["Location"])
                    continue
                logger.info("Cover download HTTP %s for %s", e.code, url)
                return None
            with resp:
                content_type = resp.headers.get("Content-Type", "image/jpeg")
                blob = resp.read(MAX_BYTES + 1)
            break
        else:
            return None  # too many redirects
    except Exception as e:
        logger.info("Cover download failed for %s: %s", url, e)
        return None

    if not blob or len(blob) < 100 or len(blob) > MAX_BYTES or not content_type.startswith("image"):
        return None
    return blob, content_type


# ── Orchestration ────────────────────────────────────────────────────────────

def fetch_metadata(
    isbn: Optional[str],
    isbn13: Optional[str],
    hardcover_token: Optional[str],
) -> Optional[Metadata]:
    """Try Hardcover first (if a token is set), then Open Library.

    Merges: if Hardcover returns a record but is missing a cover, Open Library's
    cover is grafted in (and vice-versa for the description).
    """
    primary: Optional[Metadata] = None
    if hardcover_token:
        primary = lookup_hardcover(isbn13 or isbn, hardcover_token)

    fallback = lookup_openlibrary(isbn13 or isbn)

    if primary and fallback:
        # Fill gaps in the Hardcover record from Open Library.
        if not primary.cover_url:
            primary.cover_url = fallback.cover_url
        if not primary.description:
            primary.description = fallback.description
        if not primary.page_count:
            primary.page_count = fallback.page_count
        if not primary.publisher:
            primary.publisher = fallback.publisher
        return primary

    return primary or fallback
