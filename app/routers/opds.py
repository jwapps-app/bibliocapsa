"""
OPDS Catalog — Atom feed for e-reader compatibility (KOReader, KyBook, etc.).

Books carry real acquisition (download) links so e-readers can fetch the file,
and the feed is filtered by the signed-in member's genre access. Navigation by
series and by author is provided so large libraries are browsable on-device.
"""

from fastapi import APIRouter, Request, Query
from fastapi.responses import Response
from datetime import datetime, timezone
from ..database import get_conn
from ..queries import fetch_authors_for_book
from .. import access

router = APIRouter()

OPDS_TYPE = "application/atom+xml;profile=opds-catalog;kind=navigation"
OPDS_ACQUISITION = "application/atom+xml;profile=opds-catalog;kind=acquisition"

# Formats e-readers can open, in rough order of preference.
from .files import MIME_TYPES  # one shared format→MIME map


def _xml(content: str) -> Response:
    return Response(content=content, media_type="application/atom+xml; charset=utf-8")


def _esc(s) -> str:
    return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _book_entries(conn, base: str, rows, now: str) -> str:
    """Entries for many books with ONE authors query and ONE formats query,
    instead of two per book (a 50-book feed page was 100 queries; the whole
    library as a shelf feed, thousands). Same markup as _book_entry."""
    rows = list(rows)
    ids = [r["id"] for r in rows]
    authors: dict = {i: [] for i in ids}
    formats: dict = {i: [] for i in ids}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        ph = ",".join("?" * len(chunk))
        for r in conn.execute(
            f"SELECT bal.book AS book, a.name FROM books_authors_link bal JOIN authors a ON a.id = bal.author "
            f"WHERE bal.book IN ({ph}) ORDER BY bal.book, a.sort", chunk):
            authors[r["book"]].append(r["name"])
        for r in conn.execute(
            f"SELECT book, format FROM data WHERE book IN ({ph}) ORDER BY book, format", chunk):
            formats[r["book"]].append(r["format"])
    return "".join(_entry_markup(base, r, now, authors[r["id"]], formats[r["id"]]) for r in rows)


def _book_entry(conn, base: str, row, now: str) -> str:
    """An acquisition <entry> with author, cover, and per-format download links."""
    book_id = row["id"]
    names = [a.name for a in fetch_authors_for_book(conn, book_id)]
    fmts = [f["format"] for f in conn.execute("SELECT format FROM data WHERE book = ? ORDER BY format", (book_id,)).fetchall()]
    return _entry_markup(base, row, now, names, fmts)


def _entry_markup(base: str, row, now: str, author_names, fmts) -> str:
    book_id = row["id"]
    author_tags = "".join(f"    <author><name>{_esc(n)}</name></author>\n" for n in author_names)

    cover = ""
    if row["has_cover"]:
        cover = (f'    <link rel="http://opds-spec.org/image" href="{base}/api/covers/{book_id}" type="image/jpeg"/>\n'
                 f'    <link rel="http://opds-spec.org/image/thumbnail" href="{base}/api/covers/{book_id}" type="image/jpeg"/>\n')

    acquisitions = ""
    for f in fmts:
        fmt = (f or "").upper()
        mime = MIME_TYPES.get(fmt, "application/octet-stream")
        acquisitions += (f'    <link rel="http://opds-spec.org/acquisition" '
                         f'href="{base}/api/books/{book_id}/file/{fmt.lower()}" type="{mime}"/>\n')

    updated = row["last_modified"] or now
    return f"""  <entry>
    <id>urn:bibliocapsa:book:{row["uuid"] or book_id}</id>
    <title>{_esc(row["title"])}</title>
    <updated>{updated}</updated>
{author_tags}{cover}{acquisitions}    <link rel="alternate" href="{base}/api/books/{book_id}" type="application/json"/>
  </entry>
"""


def _acquisition_feed(feed_id: str, title: str, self_href: str, entries: str,
                      base: str, now: str, next_href: str = None) -> Response:
    nxt = f'  <link rel="next" href="{next_href}" type="{OPDS_ACQUISITION}"/>\n' if next_href else ""
    return _xml(f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opds="http://opds-spec.org/2010/catalog">
  <id>{feed_id}</id>
  <title>{_esc(title)}</title>
  <updated>{now}</updated>
  <link rel="self" href="{self_href}" type="{OPDS_ACQUISITION}"/>
  <link rel="start" href="{base}/opds" type="{OPDS_TYPE}"/>
{nxt}{entries}</feed>""")


def _nav_feed(feed_id: str, title: str, self_href: str, entries: str,
              base: str, now: str, next_href: str = None) -> Response:
    nxt = f'  <link rel="next" href="{next_href}" type="{OPDS_TYPE}"/>\n' if next_href else ""
    return _xml(f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opds="http://opds-spec.org/2010/catalog">
  <id>{feed_id}</id>
  <title>{_esc(title)}</title>
  <updated>{now}</updated>
  <link rel="self" href="{self_href}" type="{OPDS_TYPE}"/>
  <link rel="start" href="{base}/opds" type="{OPDS_TYPE}"/>
{nxt}{entries}</feed>""")


# ── Root ──────────────────────────────────────────────────────────────────────
@router.get("", summary="OPDS root catalog")
def opds_root(request: Request):
    base = ""  # root-relative hrefs so clients resolve against the URL they reached us on
    now = datetime.now(tz=timezone.utc).isoformat()
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opds="http://opds-spec.org/2010/catalog">
  <id>urn:bibliocapsa:root</id>
  <title>Bibliocapsa</title>
  <updated>{now}</updated>
  <link rel="self" href="{base}/opds" type="{OPDS_TYPE}"/>
  <link rel="start" href="{base}/opds" type="{OPDS_TYPE}"/>
  <entry>
    <id>urn:bibliocapsa:all-books</id>
    <title>All Books</title>
    <updated>{now}</updated>
    <link rel="subsection" href="{base}/opds/books" type="{OPDS_ACQUISITION}"/>
    <content type="text">Browse and download your entire library</content>
  </entry>
  <entry>
    <id>urn:bibliocapsa:wishlist</id>
    <title>Want to Read</title>
    <updated>{now}</updated>
    <link rel="subsection" href="{base}/opds/wishlist" type="{OPDS_ACQUISITION}"/>
    <content type="text">Books on your want-to-read list</content>
  </entry>
  <entry>
    <id>urn:bibliocapsa:series</id>
    <title>By Series</title>
    <updated>{now}</updated>
    <link rel="subsection" href="{base}/opds/series" type="{OPDS_TYPE}"/>
    <content type="text">Browse books organized by series</content>
  </entry>
  <entry>
    <id>urn:bibliocapsa:authors</id>
    <title>By Author</title>
    <updated>{now}</updated>
    <link rel="subsection" href="{base}/opds/authors" type="{OPDS_TYPE}"/>
    <content type="text">Browse books organized by author</content>
  </entry>
  <entry>
    <id>urn:bibliocapsa:shelves</id>
    <title>Shelves</title>
    <updated>{now}</updated>
    <link rel="subsection" href="{base}/opds/shelves" type="{OPDS_TYPE}"/>
    <content type="text">Your shelves, including Currently Reading</content>
  </entry>
</feed>"""
    return _xml(xml)


# ── All books (acquisition) ───────────────────────────────────────────────────
@router.get("/books", summary="OPDS all books acquisition feed")
def opds_books(request: Request, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
    base = ""  # root-relative hrefs so clients resolve against the URL they reached us on
    now = datetime.now(tz=timezone.utc).isoformat()
    offset = (page - 1) * page_size
    pred, pp = access.calibre_predicate(access.restriction_for_request(request), "b")
    where = f"WHERE {pred}" if pred else ""

    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT b.id, b.title, b.last_modified, b.has_cover, b.uuid
                FROM books b {where} ORDER BY b.sort ASC LIMIT ? OFFSET ?""",
            pp + [page_size + 1, offset],
        ).fetchall()
        has_more = len(rows) > page_size
        rows = rows[:page_size]
        entries = _book_entries(conn, base, rows, now)

    next_href = f"{base}/opds/books?page={page + 1}" if has_more else None
    return _acquisition_feed(f"urn:bibliocapsa:books:{page}", "All Books",
                             f"{base}/opds/books?page={page}", entries, base, now, next_href)


# ── By series ─────────────────────────────────────────────────────────────────
@router.get("/series", summary="OPDS series navigation feed")
def opds_series(request: Request, page: int = Query(1, ge=1), page_size: int = Query(60, ge=1, le=200)):
    base = ""  # root-relative hrefs so clients resolve against the URL they reached us on
    now = datetime.now(tz=timezone.utc).isoformat()
    offset = (page - 1) * page_size
    allowed = access.restriction_for_request(request)

    with get_conn() as conn:
        if allowed is None:
            rows = conn.execute(
                """SELECT s.id, s.name, COUNT(bsl.book) AS c
                   FROM series s JOIN books_series_link bsl ON bsl.series = s.id
                   GROUP BY s.id ORDER BY s.name ASC LIMIT ? OFFSET ?""",
                (page_size + 1, offset),
            ).fetchall()
        else:
            pred, ppp = access.calibre_predicate(allowed, "b")
            rows = conn.execute(
                f"""SELECT s.id, s.name,
                       (SELECT COUNT(*) FROM books b JOIN books_series_link bsl ON bsl.book=b.id
                        WHERE bsl.series=s.id AND {pred}) AS c
                    FROM series s
                    WHERE EXISTS (SELECT 1 FROM books b JOIN books_series_link bsl ON bsl.book=b.id
                                  WHERE bsl.series=s.id AND {pred})
                    ORDER BY s.name ASC LIMIT ? OFFSET ?""",
                ppp + ppp + [page_size + 1, offset],
            ).fetchall()

        has_more = len(rows) > page_size
        rows = rows[:page_size]
        entries = "".join(
            f"""  <entry>
    <id>urn:bibliocapsa:series:{r["id"]}</id>
    <title>{_esc(r["name"])}</title>
    <updated>{now}</updated>
    <link rel="subsection" href="{base}/opds/series/{r["id"]}" type="{OPDS_ACQUISITION}"/>
    <content type="text">{r["c"]} books</content>
  </entry>
""" for r in rows)

    next_href = f"{base}/opds/series?page={page + 1}" if has_more else None
    return _nav_feed(f"urn:bibliocapsa:series:nav:{page}", "By Series",
                     f"{base}/opds/series?page={page}", entries, base, now, next_href)


@router.get("/series/{series_id}", summary="OPDS books in a series")
def opds_series_books(series_id: int, request: Request):
    base = ""  # root-relative hrefs so clients resolve against the URL they reached us on
    now = datetime.now(tz=timezone.utc).isoformat()
    pred, pp = access.calibre_predicate(access.restriction_for_request(request), "b")
    extra = f" AND {pred}" if pred else ""

    with get_conn() as conn:
        srow = conn.execute("SELECT name FROM series WHERE id = ?", (series_id,)).fetchone()
        title = srow["name"] if srow else "Series"
        rows = conn.execute(
            f"""SELECT b.id, b.title, b.last_modified, b.has_cover, b.uuid
                FROM books b JOIN books_series_link bsl ON bsl.book = b.id
                WHERE bsl.series = ?{extra}
                ORDER BY b.series_index ASC, b.sort ASC""",
            [series_id] + pp,
        ).fetchall()
        entries = _book_entries(conn, base, rows, now)

    return _acquisition_feed(f"urn:bibliocapsa:series:{series_id}:books", title,
                             f"{base}/opds/series/{series_id}", entries, base, now)


# ── By author ─────────────────────────────────────────────────────────────────
@router.get("/authors", summary="OPDS author navigation feed")
def opds_authors(request: Request, page: int = Query(1, ge=1), page_size: int = Query(60, ge=1, le=200)):
    base = ""  # root-relative hrefs so clients resolve against the URL they reached us on
    now = datetime.now(tz=timezone.utc).isoformat()
    offset = (page - 1) * page_size
    allowed = access.restriction_for_request(request)

    with get_conn() as conn:
        if allowed is None:
            rows = conn.execute(
                """SELECT a.id, a.name, COUNT(bal.book) AS c
                   FROM authors a JOIN books_authors_link bal ON bal.author = a.id
                   GROUP BY a.id ORDER BY a.sort ASC LIMIT ? OFFSET ?""",
                (page_size + 1, offset),
            ).fetchall()
        else:
            pred, ppp = access.calibre_predicate(allowed, "b")
            rows = conn.execute(
                f"""SELECT a.id, a.name,
                       (SELECT COUNT(*) FROM books b JOIN books_authors_link bal ON bal.book=b.id
                        WHERE bal.author=a.id AND {pred}) AS c
                    FROM authors a
                    WHERE EXISTS (SELECT 1 FROM books b JOIN books_authors_link bal ON bal.book=b.id
                                  WHERE bal.author=a.id AND {pred})
                    ORDER BY a.sort ASC LIMIT ? OFFSET ?""",
                ppp + ppp + [page_size + 1, offset],
            ).fetchall()

        has_more = len(rows) > page_size
        rows = rows[:page_size]
        entries = "".join(
            f"""  <entry>
    <id>urn:bibliocapsa:author:{r["id"]}</id>
    <title>{_esc(r["name"])}</title>
    <updated>{now}</updated>
    <link rel="subsection" href="{base}/opds/authors/{r["id"]}" type="{OPDS_ACQUISITION}"/>
    <content type="text">{r["c"]} books</content>
  </entry>
""" for r in rows)

    next_href = f"{base}/opds/authors?page={page + 1}" if has_more else None
    return _nav_feed(f"urn:bibliocapsa:authors:nav:{page}", "By Author",
                     f"{base}/opds/authors?page={page}", entries, base, now, next_href)


@router.get("/authors/{author_id}", summary="OPDS books by an author")
def opds_author_books(author_id: int, request: Request):
    base = ""  # root-relative hrefs so clients resolve against the URL they reached us on
    now = datetime.now(tz=timezone.utc).isoformat()
    pred, pp = access.calibre_predicate(access.restriction_for_request(request), "b")
    extra = f" AND {pred}" if pred else ""

    with get_conn() as conn:
        arow = conn.execute("SELECT name FROM authors WHERE id = ?", (author_id,)).fetchone()
        title = arow["name"] if arow else "Author"
        rows = conn.execute(
            f"""SELECT b.id, b.title, b.last_modified, b.has_cover, b.uuid
                FROM books b JOIN books_authors_link bal ON bal.book = b.id
                WHERE bal.author = ?{extra}
                ORDER BY b.sort ASC""",
            [author_id] + pp,
        ).fetchall()
        entries = _book_entries(conn, base, rows, now)

    return _acquisition_feed(f"urn:bibliocapsa:author:{author_id}:books", title,
                             f"{base}/opds/authors/{author_id}", entries, base, now)


def _entries_for_ids(cal, base: str, cal_ids, allowed, now: str) -> str:
    """Entries for an ordered id list (shelf / wishlist order), keeping that
    order, deduped, genre-filtered in SQL, built in batches. Replaces a
    per-id allow-check + SELECT + two sub-queries (4 queries per book)."""
    order, seen = [], set()
    for bid in cal_ids:
        if bid not in seen:
            seen.add(bid); order.append(bid)
    if not order:
        return ""
    pred, pp = access.calibre_predicate(allowed, "b")
    extra = f" AND {pred}" if pred else ""
    by_id = {}
    for i in range(0, len(order), 500):
        chunk = order[i:i + 500]
        ph = ",".join("?" * len(chunk))
        for r in cal.execute(
            f"SELECT b.id, b.title, b.last_modified, b.has_cover, b.uuid FROM books b "
            f"WHERE b.id IN ({ph}){extra}", [*chunk, *pp]):
            by_id[r["id"]] = r
    rows = [by_id[i] for i in order if i in by_id]
    return _book_entries(cal, base, rows, now)


# ── Shelves ───────────────────────────────────────────────────────────────────
@router.get("/shelves", summary="OPDS shelves navigation feed")
def opds_shelves(request: Request):
    base = ""  # root-relative hrefs so clients resolve against the URL they reached us on
    now = datetime.now(tz=timezone.utc).isoformat()
    from .shelves import _pg, _ensure_tables
    _ensure_tables()
    user = getattr(request.state, "user", None) or {}
    conn = _pg()
    try:
        cur = conn.cursor()
        # Same visibility rule as /api/shelves: your own, shared, or legacy
        # (owner_id NULL). This feed used to list EVERY user's private shelves.
        cur.execute(
            """SELECT s.id, s.name, s.is_smart,
                      CASE WHEN s.is_smart THEN NULL
                           ELSE (SELECT COUNT(*) FROM shelf_books sb WHERE sb.shelf_id = s.id) END AS c
               FROM shelves s
               WHERE s.owner_id = %s OR s.owner_id IS NULL OR s.is_shared
               ORDER BY s.is_smart DESC, s.name ASC""",
            (user.get("id"),),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    entries = "".join(
        f"""  <entry>
    <id>urn:bibliocapsa:shelf:{r["id"]}</id>
    <title>{_esc(r["name"])}</title>
    <updated>{now}</updated>
    <link rel="subsection" href="{base}/opds/shelves/{r["id"]}" type="{OPDS_ACQUISITION}"/>
    <content type="text">{"Smart shelf" if r["is_smart"] else str(r["c"]) + " books"}</content>
  </entry>
""" for r in rows)
    return _nav_feed("urn:bibliocapsa:shelves:nav", "Shelves",
                     f"{base}/opds/shelves", entries, base, now)


@router.get("/wishlist", summary="OPDS want-to-read acquisition feed")
def opds_wishlist(request: Request):
    base = ""  # root-relative hrefs so clients resolve against the URL they reached us on
    now = datetime.now(tz=timezone.utc).isoformat()
    allowed = access.restriction_for_request(request)
    user = getattr(request.state, "user", None)

    cal_ids = []
    if user:
        from .wishlist import _pg
        conn = _pg()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT book_id FROM wishlist "
                "WHERE user_id=%s AND book_source='calibre' AND book_id IS NOT NULL "
                "ORDER BY added_at DESC",
                (user["id"],),
            )
            cal_ids = [r["book_id"] for r in cur.fetchall()]
        finally:
            conn.close()

    # Only owned Calibre books are downloadable; render those (access-filtered).
    with get_conn() as cal:
        entries = _entries_for_ids(cal, base, cal_ids, allowed, now)

    return _acquisition_feed("urn:bibliocapsa:wishlist:books", "Want to Read",
                             f"{base}/opds/wishlist", entries, base, now)


@router.get("/shelves/{shelf_id}", summary="OPDS downloadable books on a shelf")
def opds_shelf_books(shelf_id: int, request: Request):
    base = ""  # root-relative hrefs so clients resolve against the URL they reached us on
    now = datetime.now(tz=timezone.utc).isoformat()
    allowed = access.restriction_for_request(request)
    user = getattr(request.state, "user", None)
    username = user.get("username") if user else None

    from .shelves import _pg, _resolve_smart_shelf
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM shelves WHERE id = %s", (shelf_id,))
        shelf = cur.fetchone()
        # Visibility: own shelf, or a shared / legacy (owner_id NULL) one --
        # mirrors /api/shelves/{id}/books. Another user's private shelf is a
        # 404 here, not a 403, so it can't be enumerated by id.
        if shelf and not (shelf["owner_id"] is None or shelf["is_shared"]
                          or (user and shelf["owner_id"] == user["id"])):
            shelf = None
        title = shelf["name"] if shelf else "Shelf"
        cal_ids = []
        if shelf and shelf["is_smart"] and shelf["smart_rules"]:
            for b in _resolve_smart_shelf(dict(shelf["smart_rules"]), base, username=username, allowed=allowed):
                if b.book_source == "calibre":
                    cal_ids.append(b.book_id)
        elif shelf:
            cur.execute(
                "SELECT book_id FROM shelf_books WHERE shelf_id = %s AND book_source = 'calibre' ORDER BY added_at DESC",
                (shelf_id,),
            )
            cal_ids = [r["book_id"] for r in cur.fetchall()]
    finally:
        conn.close()

    # Only Calibre books have downloadable files; render those (access-filtered).
    with get_conn() as cal:
        entries = _entries_for_ids(cal, base, cal_ids, allowed, now)

    return _acquisition_feed(f"urn:bibliocapsa:shelf:{shelf_id}:books", title,
                             f"{base}/opds/shelves/{shelf_id}", entries, base, now)
