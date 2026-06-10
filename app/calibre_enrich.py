"""
Bulk metadata enrichment for digital (Calibre) books.

Sweeps Calibre books missing a description, looks each up by title/author
(Hardcover + Open Library), and — for confident matches only — writes the empty
fields into the pending edit overlay (`calibre_edits`). Nothing touches Calibre:
the user reviews everything on /sync and pushes deliberately.

Background thread + progress, mirroring the native enrichment job.
"""

import re
import time
import difflib
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_job = {
    "running": False, "total": 0, "processed": 0, "filled": 0, "no_match": 0,
    "skipped": 0, "current": None, "started_at": None, "finished_at": None, "cancel": False,
}


def _scanned_ids() -> set:
    """Book ids already tried by a previous scan (so we don't re-check them)."""
    from .calibre_overlay import _pg
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("SELECT book_id FROM calibre_enrich_log")
        return {r["book_id"] for r in cur.fetchall()}
    finally:
        conn.close()


def _record(book_id: int, status: str) -> None:
    from .calibre_overlay import _pg
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO calibre_enrich_log (book_id, status, scanned_at) VALUES (%s, %s, NOW()) "
            "ON CONFLICT (book_id) DO UPDATE SET status=EXCLUDED.status, scanned_at=NOW()",
            (book_id, status),
        )
        conn.commit()
    finally:
        conn.close()

_ARTICLES = re.compile(r"^(the|a|an)\s+", re.I)


def status() -> dict:
    with _lock:
        return dict(_job)


def cancel() -> None:
    with _lock:
        if _job["running"]:
            _job["cancel"] = True


def _norm(s: Optional[str]) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = _ARTICLES.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def _best_match(title: str, author: Optional[str], cands: list[dict]) -> Optional[dict]:
    """Pick the most confident candidate, or None if nothing is close enough."""
    nt = _norm(title)
    best, best_key = None, 0.0
    for c in cands:
        ratio = difflib.SequenceMatcher(None, nt, _norm(c.get("title"))).ratio()
        if ratio < 0.82:
            continue
        author_ok = True
        if author:
            cand_auth = _norm(" ".join(c.get("authors") or []))
            toks = [w for w in _norm(author).split() if len(w) > 2]
            author_ok = any(w in cand_auth for w in toks) if toks else True
        if not author_ok and ratio < 0.93:
            continue
        key = ratio + (0.05 if c.get("description") else 0)  # prefer richer matches
        if key > best_key:
            best, best_key = c, key
    return best


def _run(token: Optional[str], force: bool = False):
    from .database import get_conn
    from . import metadata, calibre_overlay as overlay

    # Snapshot the work list (books with no description), with flags for other gaps.
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT b.id, b.title, b.author_sort,
                EXISTS(SELECT 1 FROM books_series_link l WHERE l.book=b.id)              AS has_series,
                EXISTS(SELECT 1 FROM books_publishers_link l WHERE l.book=b.id)          AS has_publisher,
                EXISTS(SELECT 1 FROM identifiers i WHERE i.book=b.id AND i.type='isbn')  AS has_isbn,
                (b.pubdate IS NOT NULL AND b.pubdate NOT LIKE '0101%')                   AS has_pubdate
            FROM books b
            WHERE NOT EXISTS(SELECT 1 FROM comments c WHERE c.book=b.id)
            ORDER BY b.timestamp DESC
            """
        ).fetchall()
        books = [dict(r) for r in rows]

    # Skip books a previous scan already tried (unless forcing a full re-scan).
    skipped = 0
    if not force:
        done = _scanned_ids()
        before = len(books)
        books = [b for b in books if b["id"] not in done]
        skipped = before - len(books)

    with _lock:
        _job.update(total=len(books), processed=0, filled=0, no_match=0, skipped=skipped)

    delay = 1.0 if token else 0.4  # pace external APIs

    for b in books:
        with _lock:
            if _job["cancel"]:
                break
            _job["current"] = b["title"]

        try:
            cands = metadata.search_candidates(b["title"], b["author_sort"], token)
            match = _best_match(b["title"], b["author_sort"], cands)
            edits = {}
            if match:
                if match.get("rating"):
                    try:
                        from . import community
                        community.set_calibre_rating(b["id"], match["rating"])
                    except Exception:
                        pass
                if match.get("description"):
                    edits["comment"] = match["description"]
                if not b["has_pubdate"] and match.get("published_date"):
                    edits["pubdate"] = str(match["published_date"])
                if not b["has_publisher"] and match.get("publisher"):
                    edits["publisher"] = match["publisher"]
                if not b["has_isbn"] and match.get("isbn"):
                    edits["isbn"] = match["isbn"]
                if not b["has_series"] and match.get("series"):
                    edits["series"] = match["series"]
            if edits:
                overlay.set_edits(b["id"], edits)
                _record(b["id"], "filled")
                with _lock:
                    _job["filled"] += 1
            else:
                _record(b["id"], "no_match")
                with _lock:
                    _job["no_match"] += 1
        except Exception as e:
            logger.warning("Calibre enrich failed for book %s: %s", b["id"], e)
            with _lock:
                _job["no_match"] += 1

        with _lock:
            _job["processed"] += 1
        time.sleep(delay)

    with _lock:
        _job["running"] = False
        _job["current"] = None
        _job["finished_at"] = datetime.now(timezone.utc).isoformat()


def start(token: Optional[str], force: bool = False) -> bool:
    with _lock:
        if _job["running"]:
            return False
        _job.update(running=True, cancel=False, total=0, processed=0, filled=0,
                    no_match=0, skipped=0, current=None,
                    started_at=datetime.now(timezone.utc).isoformat(), finished_at=None)
    threading.Thread(target=_run, args=(token, force), daemon=True).start()
    return True
