"""
BM25 full-text search index.

Calibre's own FTS5 tables use a custom 'calibre' tokenizer that stock sqlite3
can't load, so we maintain OUR OWN FTS5 index (standard porter/unicode61) built
from the text Calibre already extracted into books_text. This gives real
relevance ranking (BM25), stemming (run↔running), and good matching.

The index is **contentless** (`content=''`) — it stores only the inverted index,
NOT a second copy of the book text (Calibre already keeps that). So it's small
(~⅓ GB vs the multi-GB text), and excerpts are read back from Calibre's copy.

It's a rebuildable CACHE, never source-of-truth — it lives in the persistent
cover-cache volume. Contentless tables are effectively insert-only on older
SQLite, so instead of per-row updates we rebuild wholesale, but ONLY when a cheap
fingerprint of Calibre's text changes (count + total size + latest timestamp).
Unchanged restarts skip instantly. The rebuild runs in one background thread in
small batches with brief yields, so it never pegs the CPU or blocks requests.
While (re)building, callers fall back to the simpler LIKE search.
"""

import os
import re
import json
import time
import sqlite3
import logging
import threading

logger = logging.getLogger(__name__)

FTS_DB = os.getenv("CALIBRE_FTS_DB_PATH", "/calibre/full-text-search.db")
INDEX_PATH = os.getenv(
    "SEARCH_INDEX_PATH",
    os.path.join(os.getenv("COVER_CACHE_DIR", "/app/cover_cache"), ".search", "fts.db"),
)

_BATCH = 50      # books per commit during a rebuild
_YIELD = 0.05    # seconds slept between batches (keeps CPU/headroom free)
_lock = threading.Lock()

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "had",
    "has", "have", "he", "her", "his", "in", "into", "is", "it", "its", "of", "on",
    "or", "she", "that", "the", "their", "them", "they", "this", "to", "was",
    "were", "will", "with", "you", "your",
}


def _connect(readonly: bool = False) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
    if readonly:
        conn = sqlite3.connect(f"file:{INDEX_PATH}?mode=ro", uri=True, timeout=5)
    else:
        conn = sqlite3.connect(INDEX_PATH, timeout=60)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_docs(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5("
        "  searchable_text, content = '',"
        "  tokenize = 'porter unicode61 remove_diacritics 2')"
    )
    # rowid_ref is the docs rowid; maps an indexed row back to its book/format.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS doc_meta ("
        "  rowid_ref INTEGER PRIMARY KEY, book INTEGER NOT NULL, format TEXT NOT NULL)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_doc_meta_book ON doc_meta(book)")
    conn.execute("CREATE TABLE IF NOT EXISTS index_state (k TEXT PRIMARY KEY, v TEXT)")
    conn.commit()


def _get_state(conn, key, default=None):
    try:
        r = conn.execute("SELECT v FROM index_state WHERE k = ?", (key,)).fetchone()
        return json.loads(r["v"]) if r else default
    except Exception:
        return default


def _set_state(conn, **kv) -> None:
    for k, v in kv.items():
        conn.execute("INSERT INTO index_state (k, v) VALUES (?, ?) "
                     "ON CONFLICT(k) DO UPDATE SET v = excluded.v", (k, json.dumps(v)))
    conn.commit()


def _fingerprint(cal) -> list:
    r = cal.execute("SELECT COUNT(*) AS c, COALESCE(SUM(text_size),0) AS s, "
                    "COALESCE(MAX(timestamp),0) AS m FROM books_text").fetchone()
    return [r["c"], r["s"], r["m"]]


def status() -> dict:
    try:
        conn = _connect(readonly=True)
        rows = {r["k"]: json.loads(r["v"]) for r in conn.execute("SELECT k, v FROM index_state")}
        try:
            n = conn.execute("SELECT COUNT(*) AS c FROM doc_meta").fetchone()["c"]
        except Exception:
            n = 0
        conn.close()
        return {"available": True, "indexed": n, **rows}
    except Exception:
        return {"available": False, "indexed": 0, "state": "absent"}


def is_ready() -> bool:
    s = status()
    return bool(s.get("available")) and s.get("state") == "ready" and s.get("indexed", 0) > 0


def sync(reason: str = "startup") -> None:
    """Rebuild the index from Calibre's books_text — but only if Calibre's content
    changed since the last build (cheap fingerprint check); otherwise return at
    once. Insert-only into a fresh table (no contentless_delete dependency),
    batched + throttled so it never swamps the machine."""
    if not os.path.isfile(FTS_DB):
        logger.info("search index: Calibre FTS db absent, skipping (%s)", reason)
        return
    if not _lock.acquire(blocking=False):
        logger.info("search index: a build is already running, skipping (%s)", reason)
        return
    started = time.time()
    try:
        cal = sqlite3.connect(f"file:{FTS_DB}?mode=ro", uri=True, timeout=10)
        cal.row_factory = sqlite3.Row
        fp = _fingerprint(cal)

        idx = _connect()
        _ensure_docs(idx)
        if _get_state(idx, "fingerprint") == fp and _get_state(idx, "state") == "ready":
            cal.close(); idx.close()
            logger.info("search index: up to date, skipping rebuild (%s)", reason)
            return

        _set_state(idx, state="building")
        idx.execute("DROP TABLE IF EXISTS docs")
        idx.execute("DELETE FROM doc_meta")
        _ensure_docs(idx)

        rid = n = 0
        for row in cal.execute("SELECT book, format, searchable_text FROM books_text"):
            text = row["searchable_text"]
            if not text:
                continue
            rid += 1
            idx.execute("INSERT INTO docs (rowid, searchable_text) VALUES (?, ?)", (rid, text))
            idx.execute("INSERT INTO doc_meta (rowid_ref, book, format) VALUES (?, ?, ?)",
                        (rid, row["book"], row["format"]))
            n += 1
            if n % _BATCH == 0:
                idx.commit()
                time.sleep(_YIELD)

        cal.close()
        _set_state(idx, state="ready", fingerprint=fp, indexed=n, last_sync=int(time.time()))
        idx.commit()
        idx.close()
        logger.info("search index rebuilt (%s): %d docs in %.1fs", reason, n, time.time() - started)
    except Exception:
        logger.exception("search index build failed (%s)", reason)
        try:
            bad = _connect(); _set_state(bad, state="error"); bad.close()
        except Exception:
            pass
    finally:
        _lock.release()


def sync_async(reason: str = "startup") -> None:
    threading.Thread(target=sync, args=(reason,), daemon=True).start()


def start_background(interval: int = 1800) -> None:
    """One daemon thread: build on startup, then re-check every `interval` seconds.
    The periodic check is a cheap fingerprint comparison that returns in <1s when
    Calibre's content is unchanged, so new books get indexed without a restart and
    an idle library costs essentially nothing."""
    def loop():
        sync("startup")
        while True:
            time.sleep(interval)
            sync("periodic")
    threading.Thread(target=loop, daemon=True).start()


def _excerpt(text: str, query: str, context: int = 200) -> str:
    lower = text.lower()
    pos, mlen = -1, len(query)
    for cand in [query, *query.split()]:
        c = cand.lower().strip()
        if not c:
            continue
        p = lower.find(c)
        if p != -1:
            pos, mlen = p, len(cand)
            break
    if pos == -1:
        return text[:context].strip() + "…"
    start = max(0, pos - context // 2)
    end = min(len(text), pos + mlen + context // 2)
    s = text[start:end].strip()
    return ("…" if start > 0 else "") + s + ("…" if end < len(text) else "")


def _build_match(q: str):
    """Build a safe FTS5 MATCH from a user query.

    - "quoted text" → an exact-phrase match (tokens must be adjacent), stop words
      kept (you asked for that phrase verbatim).
    - bare words → individual stemmed terms, stop words dropped, AND-ed.
    We only ever emit quoted tokens/phrases built from \\w+ pieces, so a user can't
    inject FTS5 operators.
    """
    parts = []
    # Each "..." span becomes one FTS5 phrase ("w1 w2 w3" = adjacent).
    for span in re.findall(r'"([^"]+)"', q):
        toks = re.findall(r"\w+", span, flags=re.UNICODE)
        if toks:
            parts.append('"' + " ".join(toks) + '"')
    # Bare words (outside any quotes) → individual terms.
    bare = re.sub(r'"[^"]*"', " ", q)
    raw = re.findall(r"\w+", bare, flags=re.UNICODE)
    words = [t for t in raw if t.lower() not in _STOPWORDS]
    if not parts:                 # no phrase → keep words even if all stop words
        words = words or raw
    parts += ['"' + t + '"' for t in words]
    if not parts:
        return None
    return " AND ".join(parts)


def search(q: str, allowed_ids, limit: int, offset: int):
    """BM25 search. `allowed_ids` None = unrestricted; a list = the only Calibre
    book ids the caller may see (ranking + paging happen only over that set).
    Returns (total_books, [{book, format, excerpt}]). Raises on error so the
    caller can fall back to LIKE."""
    match = _build_match(q)
    if not match:
        return 0, []
    if allowed_ids is not None and not allowed_ids:
        return 0, []

    conn = _connect(readonly=True)
    try:
        where = "docs MATCH ?"
        params = [match]
        if allowed_ids is not None:
            conn.execute("CREATE TEMP TABLE _allowed (book INTEGER PRIMARY KEY)")
            conn.executemany("INSERT OR IGNORE INTO _allowed (book) VALUES (?)",
                             [(i,) for i in allowed_ids])
            where += " AND rowid IN (SELECT rowid_ref FROM doc_meta WHERE book IN (SELECT book FROM _allowed))"

        # Rank-ordered window of matching rows (bm25 is negative; smaller = better).
        # Kept as a plain MATCH query (no JOIN/aggregate) so bm25() is usable.
        fetch_n = min(500, (offset + limit) * 3 + limit)
        ranked = conn.execute(
            f"SELECT rowid AS rid FROM docs WHERE {where} ORDER BY bm25(docs) LIMIT ?",
            params + [fetch_n],
        ).fetchall()

        # Map rowids → book/format, dedupe to one entry per book (best rank first).
        rids = [r["rid"] for r in ranked]
        meta = {}
        if rids:
            qmarks = ",".join("?" * len(rids))
            for m in conn.execute(
                f"SELECT rowid_ref, book, format FROM doc_meta WHERE rowid_ref IN ({qmarks})", rids
            ):
                meta[m["rowid_ref"]] = (m["book"], m["format"])
        seen, deduped = set(), []
        for r in ranked:
            bf = meta.get(r["rid"])
            if not bf or bf[0] in seen:
                continue
            seen.add(bf[0])
            deduped.append(bf)
        page = deduped[offset:offset + limit]

        # Total distinct books across ALL matches (no bm25 here, so a JOIN is fine).
        allowed_join = " AND m.book IN (SELECT book FROM _allowed)" if allowed_ids is not None else ""
        total = conn.execute(
            f"SELECT COUNT(DISTINCT m.book) AS c FROM docs JOIN doc_meta m ON m.rowid_ref = docs.rowid "
            f"WHERE docs MATCH ?{allowed_join}", [match]
        ).fetchone()["c"]
    finally:
        conn.close()

    # Excerpts come from Calibre's stored text (we don't keep a copy).
    results = []
    if page:
        cal = sqlite3.connect(f"file:{FTS_DB}?mode=ro", uri=True, timeout=10)
        cal.row_factory = sqlite3.Row
        try:
            for book, fmt in page:
                row = cal.execute(
                    "SELECT searchable_text FROM books_text WHERE book = ? AND format = ? LIMIT 1",
                    (book, fmt),
                ).fetchone()
                ex = _excerpt(row["searchable_text"], q) if row and row["searchable_text"] else ""
                results.append({"book": book, "format": fmt, "excerpt": ex})
        finally:
            cal.close()
    return total, results
