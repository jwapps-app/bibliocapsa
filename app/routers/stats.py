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
        cur.execute("SELECT COUNT(*) AS c FROM read_log WHERE user_id=%s AND date_read LIKE %s",
                    (user_id, f"{year}-%"))
        count = cur.fetchone()["c"]
        return {"year": year, "target": (row["target"] if row else None), "count": count}
    finally:
        conn.close()


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

    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("SELECT book_id, book_source, date_read FROM read_log "
                    "WHERE user_id=%s AND date_read LIKE %s", (u["id"], f"{year}-%"))
        rows = cur.fetchall()
    finally:
        conn.close()

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
    if cal_ids:
        try:
            with get_conn() as cal:
                ph = ",".join("?" * len(cal_ids))
                for row in cal.execute(
                    f"SELECT a.name FROM books_authors_link bal JOIN authors a ON a.id=bal.author "
                    f"WHERE bal.book IN ({ph})", cal_ids).fetchall():
                    authors[row[0]] += 1
                for row in cal.execute(
                    f"SELECT t.name FROM books_tags_link btl JOIN tags t ON t.id=btl.tag "
                    f"WHERE btl.book IN ({ph})", cal_ids).fetchall():
                    if row[0] and row[0].strip().lower() not in _NON_GENRE:
                        genres[row[0]] += 1
        except Exception:
            pass
    if nat_ids:
        conn2 = _pg()
        try:
            cur2 = conn2.cursor()
            cur2.execute("SELECT author FROM native_books WHERE id = ANY(%s)", (nat_ids,))
            for r in cur2.fetchall():
                if r["author"]:
                    authors[r["author"]] += 1
        finally:
            conn2.close()

    return {
        "year": year,
        "total_books": len(rows),
        "by_month": by_month,
        "by_format": by_format,
        "top_authors": [{"name": n, "count": c} for n, c in authors.most_common(5)],
        "top_genres": [{"name": n, "count": c} for n, c in genres.most_common(6)],
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
        for b in books:
            cal_id = by_md5.get(b.get("md5"))
            if not cal_id and b.get("title"):
                row = cal.execute("SELECT id FROM books WHERE title = ? COLLATE NOCASE LIMIT 1", (b["title"],)).fetchone()
                cal_id = row["id"] if row else None
            has_cover = False
            if cal_id:
                r = cal.execute("SELECT has_cover FROM books WHERE id = ?", (cal_id,)).fetchone()
                has_cover = bool(r["has_cover"]) if r else False
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
