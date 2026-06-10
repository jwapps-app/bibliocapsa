"""
Read KOReader's synced `statistics.sqlite3` (per user, via the WebDAV store) and
turn it into reading analytics. Books are tied to Calibre by the partial-MD5
(the same hash KOReader uses), computed on demand from the Calibre file.

Schema: book(id,title,authors,md5,total_read_time,total_read_pages,pages,last_open)
        page_stat_data(id_book,page,start_time,duration,total_pages)
"""

import os
import glob
import sqlite3

from .kohash import partial_md5

WEBDAV_DIR = os.getenv("WEBDAV_DIR", "/app/webdav")
CALIBRE_ROOT = os.getenv("CALIBRE_LIBRARY_PATH", "/calibre")
SESSION_GAP = 600  # seconds between page events that starts a new "session"


def stats_path(username: str):
    base = os.path.join(WEBDAV_DIR, username)
    if not os.path.isdir(base):
        return None
    cands = glob.glob(os.path.join(base, "**", "statistics.sqlite3"), recursive=True)
    if not cands:
        cands = glob.glob(os.path.join(base, "**", "*.sqlite3"), recursive=True)
    return max(cands, key=os.path.getsize) if cands else None


def _open(username: str):
    p = stats_path(username)
    if not p:
        return None
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def summary(username: str, since: int = None):
    """Reading summary. `since` (epoch) limits totals + per-book ranking to a
    recent window (computed from page_stat_data); None = all time (book totals)."""
    conn = _open(username)
    if not conn:
        return None
    try:
        days = conn.execute(
            "SELECT date(start_time,'unixepoch','localtime') d, SUM(duration) secs, COUNT(*) pages "
            "FROM page_stat_data GROUP BY d ORDER BY d"
        ).fetchall()
        activity = [{"date": r["d"], "seconds": r["secs"] or 0, "pages": r["pages"] or 0} for r in days if r["d"]]

        if since is None:
            books = [{
                "title": b["title"], "authors": b["authors"], "md5": b["md5"],
                "secs": b["total_read_time"] or 0, "pages_read": b["total_read_pages"] or 0,
                "pages": b["pages"] or 0, "last_open": b["last_open"] or 0,
            } for b in conn.execute(
                "SELECT title,authors,md5,total_read_time,total_read_pages,pages,last_open "
                "FROM book WHERE total_read_time > 0 ORDER BY total_read_time DESC"
            ).fetchall()]
            total_seconds = sum(b["secs"] for b in books)
            total_pages = sum(b["pages_read"] for b in books)
            book_count = len(books)
            days_read = len(activity)
        else:
            import datetime
            since_date = datetime.datetime.fromtimestamp(since).strftime("%Y-%m-%d")
            rows = conn.execute(
                "SELECT id_book, SUM(duration) secs, COUNT(*) pages_read, MAX(start_time) last "
                "FROM page_stat_data WHERE start_time >= ? GROUP BY id_book", (since,)
            ).fetchall()
            agg = {r["id_book"]: r for r in rows}
            books = []
            if agg:
                ids = list(agg.keys())
                q = ",".join("?" * len(ids))
                meta = {b["id"]: b for b in conn.execute(
                    f"SELECT id,title,authors,md5,pages FROM book WHERE id IN ({q})", ids
                ).fetchall()}
                for bid, r in agg.items():
                    m = meta.get(bid)
                    if not m or not r["secs"]:
                        continue
                    books.append({
                        "title": m["title"], "authors": m["authors"], "md5": m["md5"],
                        "secs": r["secs"], "pages_read": r["pages_read"], "pages": m["pages"] or 0,
                        "last_open": r["last"] or 0,
                    })
                books.sort(key=lambda x: x["secs"], reverse=True)
            windowed = [a for a in activity if a["date"] >= since_date]
            total_seconds = sum(a["seconds"] for a in windowed)
            total_pages = sum(a["pages"] for a in windowed)
            days_read = len(windowed)
            book_count = len(books)

        return {
            "total_seconds": total_seconds, "total_pages": total_pages, "book_count": book_count,
            "days_read": days_read, "activity": activity, "books": books,
        }
    finally:
        conn.close()


def calibre_md5s(cal_conn, book_id: int):
    """Partial-MD5 of each format file for a Calibre book (the KOReader hash)."""
    row = cal_conn.execute("SELECT path FROM books WHERE id = ?", (book_id,)).fetchone()
    if not row:
        return []
    out = []
    for d in cal_conn.execute("SELECT name, format FROM data WHERE book = ?", (book_id,)).fetchall():
        fp = os.path.join(CALIBRE_ROOT, row["path"], f"{d['name']}.{d['format'].lower()}")
        if os.path.isfile(fp):
            h = partial_md5(fp)
            if h:
                out.append(h)
    return out


def book_stats(username: str, md5s: list):
    """Per-book reading stats + sessions for the given file hashes."""
    if not md5s:
        return None
    conn = _open(username)
    if not conn:
        return None
    try:
        q = ",".join("?" * len(md5s))
        brows = conn.execute(
            f"SELECT id,total_read_time,total_read_pages,pages,last_open FROM book WHERE md5 IN ({q})", md5s
        ).fetchall()
        if not brows:
            return {"found": False}
        ids = [b["id"] for b in brows]
        iq = ",".join("?" * len(ids))
        pages = conn.execute(
            f"SELECT start_time, duration FROM page_stat_data WHERE id_book IN ({iq}) ORDER BY start_time", ids
        ).fetchall()
        sessions, cur = [], None
        for p in pages:
            st, du = p["start_time"], (p["duration"] or 0)
            if cur and st - cur["end"] <= SESSION_GAP:
                cur["end"] = st + du
                cur["seconds"] += du
                cur["pages"] += 1
            else:
                if cur:
                    sessions.append(cur)
                cur = {"start": st, "end": st + du, "seconds": du, "pages": 1}
        if cur:
            sessions.append(cur)
        sessions.reverse()  # most recent first
        return {
            "found": True,
            "total_seconds": sum(b["total_read_time"] or 0 for b in brows),
            "total_pages": sum(b["total_read_pages"] or 0 for b in brows),
            "book_pages": max((b["pages"] or 0) for b in brows),
            "last_open": max((b["last_open"] or 0) for b in brows),
            "sessions": [{"start": s["start"], "seconds": s["seconds"], "pages": s["pages"]} for s in sessions],
        }
    finally:
        conn.close()
