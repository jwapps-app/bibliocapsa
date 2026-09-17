"""
Goodreads CSV import.
Matches books to Calibre library by Goodreads ID (primary), ISBN13, then title+author.
Imports: reading status, personal ratings, shelves, dates read.
Physical books (not in Calibre) go into native library.
Books owned in both formats are flagged.
"""

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Form, Request
from pydantic import BaseModel
from typing import Optional
import csv
import io
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

# Which Goodreads shelves mean "I own this physically" is per-user — the names
# come from each person's own library. The selection is chosen at import time and
# remembered in the `goodreads_physical_shelves` setting (comma-separated).
# Skip these system shelves when creating manual shelves / offering as locations.
SKIP_SHELVES = {"read", "currently-reading", "to-read"}


def _saved_physical_shelves() -> set:
    """Lowercased set of shelf names the user marked as 'physically owned'."""
    from .settings import get_setting
    raw = get_setting("goodreads_physical_shelves") or ""
    return {s.strip().lower() for s in raw.split(",") if s.strip()}


class ImportResult(BaseModel):
    total: int
    matched_by_goodreads_id: int
    matched_by_isbn: int
    matched_by_title: int
    unmatched: int
    dual_format: int
    shelves_created: int
    status: str = "complete"


class ImportStatus(BaseModel):
    status: str
    progress: int = 0
    total: int = 0
    result: Optional[ImportResult] = None
    error: Optional[str] = None


_import_status: dict = {"status": "idle"}


from ..auth import require_admin as _require_admin


def _clean_isbn(raw: str) -> Optional[str]:
    return raw.replace('="', '').replace('"', '').strip() or None


def _parse_gr_date(s: Optional[str]):
    """Goodreads exports dates as YYYY/MM/DD. Returns a date or None."""
    if not s:
        return None
    from datetime import datetime
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            continue
    return None


from ..pg_database import get_pg as _pg
from .. import textmatch, changes


def _ensure_goodreads_tables(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS goodreads_books (
            id                  SERIAL PRIMARY KEY,
            goodreads_id        TEXT UNIQUE NOT NULL,
            calibre_book_id     INTEGER,
            native_book_id      INTEGER,
            is_dual_format      BOOLEAN DEFAULT FALSE,
            title               TEXT,
            author              TEXT,
            isbn                TEXT,
            isbn13              TEXT,
            my_rating           INTEGER,
            publisher           TEXT,
            binding             TEXT,
            pages               INTEGER,
            year_published      INTEGER,
            date_read           TEXT,
            date_added          TEXT,
            exclusive_shelf     TEXT,
            bookshelves         TEXT,
            my_review           TEXT,
            read_count          INTEGER DEFAULT 0,
            owned_copies        INTEGER DEFAULT 0,
            imported_at         TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS goodreads_shelves (
            id          SERIAL PRIMARY KEY,
            name        TEXT UNIQUE NOT NULL,
            shelf_id    INTEGER REFERENCES shelves(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS book_ratings (
            id          SERIAL PRIMARY KEY,
            book_id     INTEGER NOT NULL,
            book_source TEXT NOT NULL DEFAULT 'calibre',
            source      TEXT NOT NULL DEFAULT 'goodreads',
            rating      INTEGER,
            review      TEXT,
            date_read   TEXT,
            UNIQUE(book_id, book_source, source)
        );

        -- book_ownership (also-physical tracking) is created by init_postgres
        -- at startup; no duplicate DDL here.

        -- Provenance, so Undo reverts what the import DID rather than wiping
        -- whole tables: who imported, and what the Calibre book's ownership row
        -- looked like before the FIRST import touched it.
        ALTER TABLE goodreads_books ADD COLUMN IF NOT EXISTS imported_by        INTEGER;
        ALTER TABLE goodreads_books ADD COLUMN IF NOT EXISTS own_touched        BOOLEAN DEFAULT FALSE;
        ALTER TABLE goodreads_books ADD COLUMN IF NOT EXISTS own_prev_existed   BOOLEAN;
        ALTER TABLE goodreads_books ADD COLUMN IF NOT EXISTS own_prev_physical  BOOLEAN;
        ALTER TABLE goodreads_books ADD COLUMN IF NOT EXISTS shelved_on         INTEGER[] DEFAULT '{}';
        ALTER TABLE goodreads_books ADD COLUMN IF NOT EXISTS native_created     BOOLEAN;
    """)
    conn.commit()


def _run_import(csv_content: str, physical_shelves: Optional[set] = None, auto_enrich: bool = True,
                user_id: Optional[int] = None):
    global _import_status
    # Lowercased set of shelves that mark physical ownership (from the import
    # selection, falling back to the saved setting).
    physical_shelves = physical_shelves if physical_shelves is not None else _saved_physical_shelves()
    try:
        from ..database import get_conn

        pg = _pg()
        _ensure_goodreads_tables(pg)

        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)
        total = len(rows)

        _import_status = {"status": "running", "progress": 0, "total": total}

        stats = {
            "matched_goodreads": 0,
            "matched_isbn": 0,
            "matched_title": 0,
            "unmatched": 0,
            "dual_format": 0,
            "shelves_created": 0,
        }

        # Build Calibre lookup maps
        with get_conn() as cal:
            gr_map = {}
            for r in cal.execute("SELECT book, val FROM identifiers WHERE type='goodreads'").fetchall():
                gr_map[str(r["val"])] = r["book"]

            isbn_map = {}
            for r in cal.execute("SELECT book, val FROM identifiers WHERE type='isbn'").fetchall():
                isbn_map[r["val"].replace("-", "")] = r["book"]
            for r in cal.execute("SELECT id, isbn FROM books WHERE isbn IS NOT NULL AND isbn != ''").fetchall():
                isbn_map[r["isbn"].replace("-", "")] = r["id"]

            # Title fallback. A title alone is NOT an identity -- "Collected
            # Poems" is a hundred different books -- so each title keeps every
            # candidate with its authors, and _match_by_title() accepts one only
            # when the authors agree and it is the only one that does.
            authors_of: dict = {}
            for r in cal.execute("SELECT bal.book, a.name FROM books_authors_link bal "
                                 "JOIN authors a ON a.id = bal.author").fetchall():
                authors_of.setdefault(r["book"], []).append(r["name"].replace("|", ","))
            title_map: dict = {}
            for r in cal.execute("SELECT b.id, b.title FROM books b").fetchall():
                key = textmatch.norm(r["title"])
                if key:  # a title that normalises to nothing matches nothing
                    title_map.setdefault(key, []).append(r["id"])

        def _match_by_title(title: str, author: str):
            key = textmatch.norm(title)
            if not key or not author:
                return None
            hits = [bid for bid in title_map.get(key, [])
                    if textmatch.authors_agree([author], authors_of.get(bid, [])) is True]
            return hits[0] if len(hits) == 1 else None

        def get_or_create_shelf(name: str) -> int:
            cur = pg.cursor()
            cur.execute("SELECT shelf_id FROM goodreads_shelves WHERE name=%s", (name,))
            row = cur.fetchone()
            if row and row["shelf_id"]:
                return row["shelf_id"]
            cur.execute(
                # Owned by the importer. With no owner the shelf counted as
                # "legacy" and every member could see these private shelf names.
                "INSERT INTO shelves (name, is_smart, is_shared, owner_id) VALUES (%s, FALSE, FALSE, %s) RETURNING id",
                (name, user_id)
            )
            shelf_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO goodreads_shelves (name, shelf_id) VALUES (%s,%s) ON CONFLICT (name) DO UPDATE SET shelf_id=%s",
                (name, shelf_id, shelf_id)
            )
            pg.commit()
            stats["shelves_created"] += 1
            return shelf_id

        for i, row in enumerate(rows):
            _import_status["progress"] = i + 1

            gr_id       = str(row.get("Book Id", "")).strip()
            title       = row.get("Title", "").strip()
            author      = row.get("Author", "").strip()
            isbn13      = _clean_isbn(row.get("ISBN13", ""))
            isbn        = _clean_isbn(row.get("ISBN", ""))
            my_rating   = int(row.get("My Rating", 0) or 0)
            excl_shelf  = row.get("Exclusive Shelf", "").strip()
            bs_raw      = row.get("Bookshelves", "").strip()
            date_read   = row.get("Date Read", "").strip() or None
            date_added  = row.get("Date Added", "").strip() or None
            my_review   = row.get("My Review", "").strip() or None
            read_count  = int(row.get("Read Count", 0) or 0)
            publisher   = row.get("Publisher", "").strip() or None
            binding     = row.get("Binding", "").strip() or None
            pages       = int(row.get("Number of Pages", 0) or 0) or None
            year_pub    = int(row.get("Year Published", 0) or 0) or None

            bookshelves = [s.strip() for s in bs_raw.split(",") if s.strip()]

            # Detect physical ownership from the configured shelves. The shelf is
            # used only to know a copy is owned physically — it is NOT stored as a
            # "location". Location stays empty unless the user sets it explicitly
            # (e.g. via the manual add form).
            is_physical = any(s.lower() in physical_shelves for s in bookshelves)
            physical_location = None

            # Match to Calibre
            calibre_id = None
            if gr_id and gr_id in gr_map:
                calibre_id = gr_map[gr_id]
                stats["matched_goodreads"] += 1
            elif isbn13 and isbn13 in isbn_map:
                calibre_id = isbn_map[isbn13]
                stats["matched_isbn"] += 1
            elif isbn and isbn in isbn_map:
                calibre_id = isbn_map[isbn]
                stats["matched_isbn"] += 1
            else:
                calibre_id = _match_by_title(title, author)
                if calibre_id:
                    stats["matched_title"] += 1
                else:
                    stats["unmatched"] += 1

            # Dual format detection
            is_dual = bool(calibre_id and is_physical)
            if is_dual:
                stats["dual_format"] += 1

            cur = pg.cursor()

            # Upsert goodreads_books
            cur.execute("""
                INSERT INTO goodreads_books
                    (goodreads_id, calibre_book_id, title, author, isbn, isbn13,
                     my_rating, publisher, binding, pages, year_published,
                     date_read, date_added, exclusive_shelf, bookshelves, my_review,
                     read_count, owned_copies, is_dual_format, imported_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (goodreads_id) DO UPDATE SET
                    calibre_book_id=EXCLUDED.calibre_book_id,
                    imported_by=COALESCE(EXCLUDED.imported_by, goodreads_books.imported_by),
                    my_rating=EXCLUDED.my_rating,
                    date_read=EXCLUDED.date_read,
                    exclusive_shelf=EXCLUDED.exclusive_shelf,
                    bookshelves=EXCLUDED.bookshelves,
                    my_review=EXCLUDED.my_review,
                    read_count=EXCLUDED.read_count,
                    is_dual_format=EXCLUDED.is_dual_format
            """, (gr_id, calibre_id, title, author, isbn, isbn13,
                  my_rating, publisher, binding, pages, year_pub,
                  date_read, date_added, excl_shelf, bs_raw,
                  my_review, read_count, 0, is_dual, user_id))

            # Record ownership for Calibre books. The import only ever ADDS
            # physical ownership: a Goodreads row that isn't on a physical shelf
            # says nothing about the copy on your shelf at home, so it must not
            # flip a manual "physical" back off -- and it never touches the
            # location. What the row looked like before the FIRST import is kept
            # on the goodreads_books row so Undo can put exactly that back.
            if calibre_id and is_physical:
                cur.execute("SELECT has_physical FROM book_ownership "
                            "WHERE book_id=%s AND book_source='calibre'", (calibre_id,))
                prev = cur.fetchone()
                if not (prev and prev["has_physical"]):
                    cur.execute("""
                        INSERT INTO book_ownership (book_id, book_source, has_digital, has_physical)
                        VALUES (%s, 'calibre', TRUE, TRUE)
                        ON CONFLICT (book_id, book_source) DO UPDATE SET has_digital=TRUE, has_physical=TRUE
                    """, (calibre_id,))
                    cur.execute("""
                        UPDATE goodreads_books
                        SET own_prev_existed = CASE WHEN own_touched THEN own_prev_existed ELSE %s END,
                            own_prev_physical = CASE WHEN own_touched THEN own_prev_physical ELSE %s END,
                            own_touched = TRUE
                        WHERE goodreads_id=%s
                    """, (prev is not None, bool(prev and prev["has_physical"]), gr_id))
                    changes.touch([calibre_id], cur)  # ownership rides in the iOS delta sync

            # Add unmatched physical books to native library -- ONCE. Re-running
            # an import (a fresh export, or a retry after a failure halfway) must
            # find the book it created last time, not create another: first by
            # this Goodreads row's own mapping, then by ISBN / title+author in
            # case the book was added by hand.
            native_book_id = None
            if not calibre_id and is_physical:
                cur.execute("""
                    SELECT nb.id FROM goodreads_books gb JOIN native_books nb ON nb.id = gb.native_book_id
                    WHERE gb.goodreads_id=%s
                """, (gr_id,))
                hit = cur.fetchone()
                created = False
                if not hit:
                    cur.execute("""
                        SELECT id FROM native_books
                        WHERE (%(i13)s <> '' AND isbn13 = %(i13)s) OR (%(i10)s <> '' AND isbn = %(i10)s)
                           OR (lower(title) = lower(%(t)s) AND lower(COALESCE(author,'')) = lower(%(a)s))
                        ORDER BY id LIMIT 1
                    """, {"i13": isbn13 or "", "i10": isbn or "", "t": title, "a": author or ""})
                    hit = cur.fetchone()
                if hit:
                    native_book_id = hit["id"]
                else:
                    cur.execute("""
                        INSERT INTO native_books
                            (title, author, isbn, isbn13, publisher, page_count,
                             published_date, format, location, date_added, added_by)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        RETURNING id
                    """, (title, author, isbn, isbn13, publisher, pages,
                          str(year_pub) if year_pub else None,
                          binding or "physical", physical_location, _parse_gr_date(date_added), user_id))
                    native_book_id = cur.fetchone()["id"]
                    created = True
                # native_created: TRUE only for books this import made. A book
                # that was already in the library is linked, never owned by the
                # import -- Undo must not delete it. (NULL = a pre-provenance
                # import, where every mapped native book was import-made.)
                cur.execute(
                    "UPDATE goodreads_books SET native_book_id=%s, "
                    "native_created = CASE WHEN native_book_id = %s THEN native_created ELSE %s END "
                    "WHERE goodreads_id=%s",
                    (native_book_id, native_book_id, created, gr_id)
                )

            # The importer's own reading history, recorded now and for THEM --
            # not backfilled at the next restart onto whichever account is first.
            rd = _parse_gr_date(date_read)
            hist_id = calibre_id or native_book_id
            if rd and hist_id and user_id:
                cur.execute("""
                    INSERT INTO read_log (book_id, book_source, user_id, date_read, source)
                    SELECT %(b)s, %(s)s, %(u)s, %(d)s, 'goodreads'
                    WHERE NOT EXISTS (SELECT 1 FROM read_log WHERE book_id=%(b)s AND book_source=%(s)s
                                      AND user_id=%(u)s AND date_read=%(d)s)
                """, {"b": hist_id, "s": "calibre" if calibre_id else "native",
                      "u": user_id, "d": rd.strftime("%Y-%m-%d")})

            # Store personal rating
            if my_rating > 0:
                book_id = calibre_id or native_book_id
                book_source = "calibre" if calibre_id else "native"
                if book_id:
                    cur.execute("""
                        INSERT INTO book_ratings (book_id, book_source, source, rating, review, date_read)
                        VALUES (%s,%s,'goodreads',%s,%s,%s)
                        ON CONFLICT (book_id, book_source, source) DO UPDATE SET
                            rating=EXCLUDED.rating, review=EXCLUDED.review, date_read=EXCLUDED.date_read
                    """, (book_id, book_source, my_rating, my_review, date_read))

            # Add to shelves (skip system shelves)
            book_id = calibre_id or native_book_id
            book_source = "calibre" if calibre_id else "native"
            if book_id:
                for shelf_name in bookshelves:
                    if shelf_name in SKIP_SHELVES:
                        continue
                    shelf_id = get_or_create_shelf(shelf_name)
                    cur.execute("""
                        INSERT INTO shelf_books (shelf_id, book_id, book_source)
                        VALUES (%s,%s,%s) ON CONFLICT DO NOTHING
                    """, (shelf_id, book_id, book_source))
                    if cur.rowcount:  # the import put it there (vs. already shelved by hand)
                        cur.execute("""
                            UPDATE goodreads_books SET shelved_on = array_append(shelved_on, %s)
                            WHERE goodreads_id=%s AND NOT (%s = ANY(COALESCE(shelved_on, '{}')))
                        """, (shelf_id, gr_id, shelf_id))

            pg.commit()

        pg.close()

        result = ImportResult(
            total=total,
            matched_by_goodreads_id=stats["matched_goodreads"],
            matched_by_isbn=stats["matched_isbn"],
            matched_by_title=stats["matched_title"],
            unmatched=stats["unmatched"],
            dual_format=stats["dual_format"],
            shelves_created=stats["shelves_created"],
        )
        _import_status = {"status": "complete", "result": result.model_dump()}
        logger.info(f"Goodreads import complete: {result}")

        # Auto-fetch covers & metadata for the newly-added physical books
        # (background, paced, skip-aware) unless the user opted out.
        if auto_enrich:
            try:
                from .native_books import start_enrich_job
                start_enrich_job(force=False)
            except Exception as e:
                logger.warning(f"Auto-enrich after import failed to start: {e}")

    except Exception as e:
        logger.error(f"Goodreads import error: {e}", exc_info=True)
        _import_status = {"status": "error", "error": str(e)}


def _read_csv_upload(file: UploadFile) -> bytes:
    """Bounded read of an uploaded CSV: refuse by declared size first, then
    never read more than the cap + 1 byte, so an oversize body is rejected
    without ever being held in memory."""
    cap = 50 * 1024 * 1024
    if file.size is not None and file.size > cap:
        raise HTTPException(status_code=413, detail="CSV is too large (max 50 MB)")
    raw = file.file.read(cap + 1)
    if len(raw) > cap:
        raise HTTPException(status_code=413, detail="CSV is too large (max 50 MB)")
    return raw


@router.post("/preview-shelves", summary="List the shelves found in a Goodreads CSV (admin)")
def preview_shelves(request: Request, file: UploadFile = File(...)):
    """Distinct bookshelf names (with book counts) so the user can pick which ones
    mean 'physically owned'. Returns the previously-saved selection too.
    Plain `def`: parsing a 50 MB CSV belongs in the threadpool, not on the loop."""
    _require_admin(request)
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Must be a .csv file")
    from collections import Counter
    raw = _read_csv_upload(file)
    content = raw.decode("utf-8-sig")
    counts: Counter = Counter()
    for row in csv.DictReader(io.StringIO(content)):
        for s in (row.get("Bookshelves", "") or "").split(","):
            s = s.strip()
            if s and s.lower() not in SKIP_SHELVES:
                counts[s] += 1
    shelves = [{"name": k, "count": v} for k, v in counts.most_common()]
    saved = _saved_physical_shelves()
    from .settings import auto_enrich_enabled
    return {"shelves": shelves,
            "saved_physical": [s["name"] for s in shelves if s["name"].lower() in saved],
            "auto_enrich": auto_enrich_enabled()}


@router.post("/import", summary="Import Goodreads CSV export (admin)")
def import_goodreads(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    physical_shelves: str = Form(""),
    auto_enrich: bool = Form(True),
):
    _require_admin(request)
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Must be a .csv file")
    content = _read_csv_upload(file)
    csv_content = content.decode("utf-8-sig")
    global _import_status
    if _import_status.get("status") == "running":
        raise HTTPException(status_code=409, detail="Import already running")
    # Remember the user's choices for next time (shelves + the auto-enrich toggle,
    # which is the same master setting surfaced in Settings).
    from .settings import set_setting, AUTO_ENRICH_KEY
    set_setting("goodreads_physical_shelves", physical_shelves or None)
    set_setting(AUTO_ENRICH_KEY, "true" if auto_enrich else "false")
    phys = {s.strip().lower() for s in physical_shelves.split(",") if s.strip()}
    _import_status = {"status": "running", "progress": 0, "total": 0}
    from .. import auth
    importer = auth.authenticate_request(request) or {}
    background_tasks.add_task(_run_import, csv_content, phys, auto_enrich, importer.get("id"))
    return {"status": "started"}


@router.get("/import/status", response_model=ImportStatus, summary="Check import status")
def import_status(request: Request):
    _require_admin(request)  # import-wide job telemetry, not member data
    return ImportStatus(**_import_status)


@router.get("/import/summary", summary="Summary of current import")
def import_summary(request: Request):
    _require_admin(request)  # import-wide job telemetry, not member data
    try:
        pg = _pg()
        cur = pg.cursor()
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables WHERE table_name='goodreads_books'
            )
        """)
        if not cur.fetchone()["exists"]:
            return {"imported": False}
        cur.execute("SELECT COUNT(*) as c FROM goodreads_books")
        total = cur.fetchone()["c"]
        if total == 0:
            return {"imported": False}
        cur.execute("SELECT COUNT(*) as c FROM goodreads_books WHERE calibre_book_id IS NOT NULL")
        matched = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) as c FROM goodreads_books WHERE native_book_id IS NOT NULL")
        native = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) as c FROM goodreads_books WHERE is_dual_format=TRUE")
        dual = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) as c FROM goodreads_shelves")
        shelves = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) as c FROM book_ratings WHERE source='goodreads'")
        ratings = cur.fetchone()["c"]
        cur.execute("SELECT MAX(imported_at) as last FROM goodreads_books")
        last = cur.fetchone()["last"]
        pg.close()
        return {
            "imported": True,
            "total": total,
            "matched_to_calibre": matched,
            "native_books": native,
            "dual_format": dual,
            "shelves": shelves,
            "ratings": ratings,
            "imported_at": str(last) if last else None,
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.delete("/import", summary="Undo Goodreads import (admin)")
def undo_import(request: Request):
    """Revert what the import DID -- nothing else. It used to `DELETE FROM
    book_ownership` outright (every manually recorded physical copy and location
    in the library, Goodreads or not) and drop imported native books without
    clearing the records that point at them.

      * Ownership: only rows the import switched to "physical", and only if
        nobody has touched them since (still physical, still no location) --
        restored to their pre-import state. Manual work survives.
      * Native books: only ones the import created, removed with the same
        reference cleanup as an ordinary delete.
      * Shelves: only memberships the import added; an import-made shelf is
        removed once empty, so books shelved there by hand keep their shelf.
      * Ratings and reading history that came from Goodreads.
    One transaction: it all reverts, or none of it does."""
    _require_admin(request)
    pg = None
    try:
        pg = _pg()
        _ensure_goodreads_tables(pg)
        cur = pg.cursor()

        # Ownership the import added, unless edited since.
        cur.execute("""
            SELECT DISTINCT ON (calibre_book_id) calibre_book_id AS id, own_prev_existed
            FROM goodreads_books WHERE own_touched AND calibre_book_id IS NOT NULL
            ORDER BY calibre_book_id, id
        """)
        reverted = []
        for r in cur.fetchall():
            if r["own_prev_existed"]:
                cur.execute("UPDATE book_ownership SET has_physical=FALSE WHERE book_id=%s AND book_source='calibre' "
                            "AND has_physical AND physical_location IS NULL", (r["id"],))
            else:
                cur.execute("DELETE FROM book_ownership WHERE book_id=%s AND book_source='calibre' "
                            "AND has_physical AND physical_location IS NULL", (r["id"],))
            if cur.rowcount:
                reverted.append(r["id"])
        changes.touch(reverted, cur)

        # Shelf memberships the import added; then import-made shelves left empty.
        cur.execute("""
            DELETE FROM shelf_books sb USING goodreads_books gb
            WHERE sb.shelf_id = ANY(COALESCE(gb.shelved_on, '{}'))
              AND sb.book_id = COALESCE(gb.calibre_book_id, gb.native_book_id)
              AND sb.book_source = CASE WHEN gb.calibre_book_id IS NOT NULL THEN 'calibre' ELSE 'native' END
        """)
        cur.execute("""
            DELETE FROM shelves s USING goodreads_shelves gs
            WHERE gs.shelf_id = s.id AND NOT EXISTS (SELECT 1 FROM shelf_books sb WHERE sb.shelf_id = s.id)
            RETURNING s.id
        """)
        shelf_ids = [r["id"] for r in cur.fetchall()]
        cur.execute("DELETE FROM goodreads_shelves")

        cur.execute("DELETE FROM book_ratings WHERE source='goodreads'")
        cur.execute("DELETE FROM read_log WHERE source='goodreads'")

        # Native books the import created -- with every record that references
        # them, exactly as deleting the book by hand does.
        cur.execute("SELECT native_book_id FROM goodreads_books "
                    "WHERE native_book_id IS NOT NULL AND native_created IS NOT FALSE")
        native_ids = [r["native_book_id"] for r in cur.fetchall()]
        if native_ids:
            from .native_books import NATIVE_REFERENCE_TABLES
            for tbl in NATIVE_REFERENCE_TABLES:  # hardcoded literals
                cur.execute(f"DELETE FROM {tbl} WHERE book_id = ANY(%s) AND book_source = 'native'", (native_ids,))
            cur.execute("DELETE FROM native_books WHERE id = ANY(%s)", (native_ids,))

        cur.execute("DELETE FROM goodreads_books")
        pg.commit()

        global _import_status
        _import_status = {"status": "idle"}

        return {
            "status": "undone",
            "shelves_removed": len(shelf_ids),
            "native_books_removed": len(native_ids),
            "ownership_reverted": len(reverted),
        }
    except Exception as e:
        if pg is not None:
            try:
                pg.rollback()
            except Exception:
                pass
        logger.error("Goodreads undo failed: %s", e, exc_info=True)
        raise HTTPException(status_code=503, detail="Undo failed; nothing was changed")
    finally:
        if pg is not None:
            pg.close()


@router.get("/ownership/{book_id}", summary="Get ownership info for a Calibre book")
def get_ownership(book_id: int, request: Request):
    from .. import access
    from ..database import get_conn
    with get_conn() as _cal:
        if not access.is_calibre_book_allowed(_cal, book_id, access.restriction_for_request(request)):
            raise HTTPException(status_code=404, detail="Not found")
    try:
        pg = _pg()
        cur = pg.cursor()
        cur.execute(
            "SELECT has_digital, has_physical, physical_location FROM book_ownership WHERE book_id=%s AND book_source='calibre'",
            (book_id,)
        )
        row = cur.fetchone()
        pg.close()
        if not row:
            return {"has_digital": True, "has_physical": False, "physical_location": None}
        return dict(row)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


class OwnershipUpdate(BaseModel):
    has_physical: bool
    physical_location: Optional[str] = None


@router.put("/ownership/{book_id}", summary="Set physical ownership for a Calibre book")
def set_ownership(book_id: int, body: OwnershipUpdate, request: Request):
    """Mark a Calibre (digital) book as also physically owned, so it shows as
    'Digital + Physical' everywhere instead of needing a duplicate native entry.
    Mirrors what the Goodreads import records; `row_to_detail` already surfaces it
    to the iOS delta sync and the web."""
    _require_admin(request)
    try:
        pg = _pg()
        cur = pg.cursor()
        cur.execute(
            """
            INSERT INTO book_ownership (book_id, book_source, has_digital, has_physical, physical_location)
            VALUES (%s, 'calibre', TRUE, %s, %s)
            ON CONFLICT (book_id, book_source) DO UPDATE SET
                has_digital=TRUE,
                has_physical=EXCLUDED.has_physical,
                physical_location=EXCLUDED.physical_location
            """,
            (book_id, body.has_physical, body.physical_location),
        )
        # Ownership rides in the iOS delta sync but never moves Calibre's
        # last_modified -- journal it so the next incremental sync carries it.
        from .. import changes
        changes.touch([book_id], cur)
        pg.commit()
        pg.close()
        return {"has_digital": True, "has_physical": body.has_physical, "physical_location": body.physical_location}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/ratings/{book_id}", summary="Get Goodreads rating for a book")
def get_rating(book_id: int, request: Request, book_source: str = "calibre"):
    from .. import access
    allowed = access.restriction_for_request(request)
    if book_source == "calibre":
        from ..database import get_conn
        with get_conn() as _cal:
            if not access.is_calibre_book_allowed(_cal, book_id, allowed):
                raise HTTPException(status_code=404, detail="Not found")
    elif allowed is not None:
        # Native books get the same genre wall (this branch used to skip it).
        pg = _pg()
        try:
            cur = pg.cursor()
            cur.execute("SELECT categories FROM native_books WHERE id=%s", (book_id,))
            row = cur.fetchone()
        finally:
            pg.close()
        if not row or not access.is_native_allowed(row.get("categories"), allowed):
            raise HTTPException(status_code=404, detail="Not found")
    try:
        pg = _pg()
        cur = pg.cursor()
        cur.execute(
            "SELECT rating, review, date_read FROM book_ratings WHERE book_id=%s AND book_source=%s AND source='goodreads'",
            (book_id, book_source)
        )
        row = cur.fetchone()
        pg.close()
        if not row:
            return {"rating": None, "review": None, "date_read": None}
        return dict(row)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
