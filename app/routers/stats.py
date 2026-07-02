"""Reading statistics from KOReader's synced statistics.sqlite3 (per user)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from .. import koreader_stats as ks

router = APIRouter()

# Tags that are Goodreads shelves / formats / status, not genres — excluded from
# the year-in-review "top genres".
_NON_GENRE = {
    "read", "to-read", "currently-reading", "did-not-finish", "dnf", "unread",
    "kindle", "ebook", "ebooks", "audiobook", "audiobooks", "paperback", "hardcover",
    "paid", "free", "owned", "owned-books", "have", "wishlist", "favorites", "favourites",
    "default", "books", "calibre", "library", "my-books",
}


def _username(request: Request) -> str:
    from .. import auth
    u = auth.authenticate_request(request)
    if not u or not u.get("username"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return u["username"]


def _user(request: Request) -> dict:
    from .. import auth
    u = auth.authenticate_request(request)
    if not u:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return u


def _finished_in_year(user_id: int, year: int) -> list[dict]:
    """Books finished in `year`, as [{book_id, book_source, date_read}], merging
    TWO sources of the read date so it doesn't matter where it came from:
      1. the mapped Calibre "date read" column (where Calibre/Goodreads/KOReader
         read dates all live — this is the library's source of truth), and
      2. the per-user read_log (native/physical books, manual marks, re-reads).
    Deduped by (source, book_id)."""
    seen: dict = {}  # (source, book_id) -> date_read
    # 1) The mapped Calibre "date read" column. The DATE is the signal — any book
    #    with a read date in `year` counts, regardless of a separate read flag
    #    (Goodreads/KOReader/Calibre all write the date here).
    try:
        from .settings import get_setting
        from ..database import get_conn
        col_date = get_setting("reading_col_date")
        if col_date:
            with get_conn() as cal:
                dc = cal.execute("SELECT id FROM custom_columns WHERE label = ?", (col_date,)).fetchone()
                if dc:
                    for r in cal.execute(
                        f"SELECT book, value FROM custom_column_{int(dc['id'])} WHERE value IS NOT NULL"
                    ).fetchall():
                        d = str(r["value"])[:10]
                        if d[:4] == str(year):
                            seen[("calibre", r["book"])] = d
    except Exception:
        pass
    from .settings import _pg
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("SELECT book_id, book_source, date_read FROM read_log "
                    "WHERE user_id=%s AND date_read LIKE %s", (user_id, f"{year}-%"))
        for r in cur.fetchall():
            seen[(r["book_source"], r["book_id"])] = r["date_read"]
    finally:
        conn.close()
    return [{"book_id": bid, "book_source": src, "date_read": d} for (src, bid), d in seen.items()]


# ── Annual reading goal ───────────────────────────────────────────────────────
class GoalBody(BaseModel):
    year: int
    target: int


def _goal_state(user_id: int, year: int) -> dict:
    """The user's target (if any) + how many books they've finished that year
    (from read_log, which logs each dated finish incl. re-reads)."""
    from .settings import _pg
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("SELECT target FROM reading_goals WHERE user_id=%s AND year=%s", (user_id, year))
        row = cur.fetchone()
        target = row["target"] if row else None
    finally:
        conn.close()
    count = len(_finished_in_year(user_id, year))
    return {"year": year, "target": target, "count": count}


@router.get("/goal", summary="Reading goal + progress for a year (defaults to this year)")
def get_goal(request: Request, year: int = 0):
    u = _user(request)
    if not year:
        year = datetime.now(timezone.utc).year
    return _goal_state(u["id"], year)


@router.put("/goal", summary="Set the reading goal for a year (target 0 clears it)")
def set_goal(body: GoalBody, request: Request):
    u = _user(request)
    if body.target < 0 or body.target > 100000 or body.year < 2000 or body.year > 3000:
        raise HTTPException(status_code=400, detail="Invalid goal")
    from .settings import _pg
    conn = _pg()
    try:
        cur = conn.cursor()
        if body.target == 0:
            cur.execute("DELETE FROM reading_goals WHERE user_id=%s AND year=%s", (u["id"], body.year))
        else:
            cur.execute(
                "INSERT INTO reading_goals (user_id, year, target) VALUES (%s,%s,%s) "
                "ON CONFLICT (user_id, year) DO UPDATE SET target=EXCLUDED.target, updated_at=NOW()",
                (u["id"], body.year, body.target),
            )
        conn.commit()
    finally:
        conn.close()
    return _goal_state(u["id"], body.year)


@router.get("/year", summary="Year-in-review summary for the current user")
def year_review(request: Request, year: int = 0):
    u = _user(request)
    if not year:
        year = datetime.now(timezone.utc).year
    from collections import Counter
    from .settings import _pg
    from ..database import get_conn

    rows = _finished_in_year(u["id"], year)

    by_month = [0] * 12
    by_format = {"digital": 0, "physical": 0}
    cal_ids, nat_ids = [], []
    for r in rows:
        try:
            m = int(r["date_read"][5:7]) - 1
            if 0 <= m < 12:
                by_month[m] += 1
        except Exception:
            pass
        if r["book_source"] == "calibre":
            by_format["digital"] += 1
            cal_ids.append(r["book_id"])
        else:
            by_format["physical"] += 1
            nat_ids.append(r["book_id"])

    authors: Counter = Counter()
    genres: Counter = Counter()
    author_ids: dict = {}   # name -> calibre author id (for linking)
    genre_ids: dict = {}    # name -> calibre tag id
    date_by = {(r["book_source"], r["book_id"]): r["date_read"] for r in rows}
    books: list = []        # the actual read books, for display + links

    if cal_ids:
        try:
            with get_conn() as cal:
                ph = ",".join("?" * len(cal_ids))
                brows = {r["id"]: r for r in cal.execute(
                    f"SELECT id, title, has_cover FROM books WHERE id IN ({ph})", cal_ids).fetchall()}
                auth_by_book: dict = {}
                for r in cal.execute(
                    f"SELECT bal.book AS book, a.id AS aid, a.name AS name FROM books_authors_link bal "
                    f"JOIN authors a ON a.id=bal.author WHERE bal.book IN ({ph}) ORDER BY bal.id", cal_ids).fetchall():
                    auth_by_book.setdefault(r["book"], []).append((r["aid"], r["name"]))
                tag_by_book: dict = {}
                for r in cal.execute(
                    f"SELECT btl.book AS book, t.id AS tid, t.name AS name FROM books_tags_link btl "
                    f"JOIN tags t ON t.id=btl.tag WHERE btl.book IN ({ph})", cal_ids).fetchall():
                    tag_by_book.setdefault(r["book"], []).append((r["tid"], r["name"]))
            for bid in cal_ids:
                b = brows.get(bid)
                if not b:
                    continue
                auths = auth_by_book.get(bid, [])
                for aid, aname in auths:
                    authors[aname] += 1
                    author_ids[aname] = aid
                for tid, tname in tag_by_book.get(bid, []):
                    if tname and tname.strip().lower() not in _NON_GENRE:
                        genres[tname] += 1
                        genre_ids[tname] = tid
                books.append({
                    "book_id": bid, "book_source": "calibre", "title": b["title"],
                    "author": auths[0][1] if auths else None,
                    "author_id": auths[0][0] if auths else None,
                    "author_ids": [aid for aid, _ in auths],
                    "has_cover": bool(b["has_cover"]),
                    "date_read": date_by.get(("calibre", bid)),
                })
        except Exception:
            pass
    if nat_ids:
        conn2 = _pg()
        try:
            cur2 = conn2.cursor()
            cur2.execute("SELECT id, title, author FROM native_books WHERE id = ANY(%s)", (nat_ids,))
            for r in cur2.fetchall():
                if r["author"]:
                    authors[r["author"]] += 1
                books.append({
                    "book_id": r["id"], "book_source": "native", "title": r["title"],
                    "author": r["author"], "author_id": None, "author_ids": [],
                    "has_cover": True,
                    "date_read": date_by.get(("native", r["id"])),
                })
        finally:
            conn2.close()

    books.sort(key=lambda x: x["date_read"] or "", reverse=True)
    return {
        "year": year,
        "total_books": len(rows),
        "by_month": by_month,
        "by_format": by_format,
        "top_authors": [{"name": n, "count": c, "id": author_ids.get(n)} for n, c in authors.most_common(5)],
        "top_genres": [{"name": n, "count": c, "id": genre_ids.get(n)} for n, c in genres.most_common(6)],
        "books": books,
    }


@router.get("/summary", summary="Reading-statistics dashboard for the current user")
def stats_summary(request: Request, days: int = 0):
    username = _username(request)
    since = None
    if days and days > 0:
        import time
        since = int(time.time()) - days * 86400
    data = ks.summary(username, since)
    if not data:
        return {"available": False}

    # Map each KOReader book to a Calibre book (md5 → document_map, else title) for
    # covers/links. Best-effort; KOReader-only books still show with their title.
    from ..database import get_conn
    from .settings import _pg
    base = str(request.base_url).rstrip("/")
    books = data["books"]

    md5s = [b["md5"] for b in books if b.get("md5")]
    by_md5 = {}
    if md5s:
        pg = _pg()
        try:
            cur = pg.cursor()
            cur.execute("SELECT document, book_id FROM document_map WHERE document = ANY(%s) AND book_source='calibre'", (md5s,))
            by_md5 = {r["document"]: r["book_id"] for r in cur.fetchall()}
        finally:
            pg.close()

    out = []
    with get_conn() as cal:
        # Batch the title→id fallback and the has_cover lookups (this used to be
        # two queries per book ever read).
        titles = [b["title"] for b in books if b.get("title") and not by_md5.get(b.get("md5"))]
        by_title = {}
        for i in range(0, len(titles), 400):
            chunk = titles[i:i + 400]
            ph = ",".join("?" * len(chunk))
            for r in cal.execute(
                f"SELECT id, title FROM books WHERE title IN ({ph}) COLLATE NOCASE", chunk
            ).fetchall():
                by_title.setdefault(r["title"].lower(), r["id"])
        all_ids = list({*by_md5.values(), *by_title.values()})
        covers = {}
        for i in range(0, len(all_ids), 500):
            chunk = all_ids[i:i + 500]
            ph = ",".join("?" * len(chunk))
            for r in cal.execute(f"SELECT id, has_cover FROM books WHERE id IN ({ph})", chunk).fetchall():
                covers[r["id"]] = bool(r["has_cover"])
        for b in books:
            cal_id = by_md5.get(b.get("md5"))
            if not cal_id and b.get("title"):
                cal_id = by_title.get(b["title"].lower())
            has_cover = covers.get(cal_id, False) if cal_id else False
            out.append({
                "title": b["title"], "authors": (b.get("authors") or "").replace("\n", ", "),
                "seconds": b["secs"] or 0, "pages_read": b["pages_read"] or 0,
                "pages": b["pages"] or 0, "last_open": b["last_open"] or 0,
                "calibre_book_id": cal_id,
                "cover_url": f"{base}/api/covers/{cal_id}" if (cal_id and has_cover) else None,
            })

    return {
        "available": True,
        "total_seconds": data["total_seconds"], "total_pages": data["total_pages"],
        "book_count": data["book_count"], "days_read": data["days_read"],
        "activity": data["activity"], "books": out,
    }


@router.get("/book/{book_id}", summary="Reading sessions for one Calibre book (current user)")
def stats_for_book(book_id: int, request: Request):
    username = _username(request)
    from ..database import get_conn
    with get_conn() as cal:
        md5s = ks.calibre_md5s(cal, book_id)
    res = ks.book_stats(username, md5s)
    return res or {"found": False}
