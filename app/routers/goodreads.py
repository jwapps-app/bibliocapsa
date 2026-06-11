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


def _require_admin(request: Request):
    from .. import auth
    u = auth.authenticate_request(request)
    if not u or u.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")


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


def _pg():
    from ..pg_database import get_database_url
    import psycopg2
    from psycopg2.extras import RealDictCursor
    return psycopg2.connect(get_database_url(), cursor_factory=RealDictCursor)


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

        -- Track which Calibre books are also owned physically
        CREATE TABLE IF NOT EXISTS book_ownership (
            book_id     INTEGER NOT NULL,
            book_source TEXT NOT NULL DEFAULT 'calibre',
            has_digital BOOLEAN DEFAULT FALSE,
            has_physical BOOLEAN DEFAULT FALSE,
            physical_location TEXT,
            PRIMARY KEY (book_id, book_source)
        );
    """)
    conn.commit()


def _run_import(csv_content: str, physical_shelves: Optional[set] = None, auto_enrich: bool = True):
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

            title_map = {}
            for r in cal.execute("SELECT b.id, lower(b.title) as t FROM books b").fetchall():
                title_map[r["t"]] = r["id"]

        def get_or_create_shelf(name: str) -> int:
            cur = pg.cursor()
            cur.execute("SELECT shelf_id FROM goodreads_shelves WHERE name=%s", (name,))
            row = cur.fetchone()
            if row and row["shelf_id"]:
                return row["shelf_id"]
            cur.execute(
                "INSERT INTO shelves (name, is_smart, is_shared) VALUES (%s, FALSE, FALSE) RETURNING id",
                (name,)
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
                if title.lower() in title_map:
                    calibre_id = title_map[title.lower()]
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
                     read_count, owned_copies, is_dual_format)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (goodreads_id) DO UPDATE SET
                    calibre_book_id=EXCLUDED.calibre_book_id,
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
                  my_review, read_count, 0, is_dual))

            # Record ownership for Calibre books
            if calibre_id:
                cur.execute("""
                    INSERT INTO book_ownership (book_id, book_source, has_digital, has_physical, physical_location)
                    VALUES (%s, 'calibre', TRUE, %s, %s)
                    ON CONFLICT (book_id, book_source) DO UPDATE SET
                        has_digital=TRUE,
                        has_physical=EXCLUDED.has_physical,
                        physical_location=EXCLUDED.physical_location
                """, (calibre_id, is_physical, physical_location))

            # Add unmatched physical books to native library
            native_book_id = None
            if not calibre_id and is_physical:
                cur.execute("""
                    INSERT INTO native_books
                        (title, author, isbn, isbn13, publisher, page_count,
                         published_date, format, location, date_added)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING
                    RETURNING id
                """, (title, author, isbn, isbn13, publisher, pages,
                      str(year_pub) if year_pub else None,
                      binding or "physical", physical_location, _parse_gr_date(date_added)))
                nb = cur.fetchone()
                if nb:
                    native_book_id = nb["id"]
                    cur.execute(
                        "UPDATE goodreads_books SET native_book_id=%s WHERE goodreads_id=%s",
                        (native_book_id, gr_id)
                    )

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


@router.post("/preview-shelves", summary="List the shelves found in a Goodreads CSV (admin)")
async def preview_shelves(request: Request, file: UploadFile = File(...)):
    """Distinct bookshelf names (with book counts) so the user can pick which ones
    mean 'physically owned'. Returns the previously-saved selection too."""
    _require_admin(request)
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Must be a .csv file")
    from collections import Counter
    raw = await file.read()
    if len(raw) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="CSV is too large (max 50 MB)")
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
async def import_goodreads(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    physical_shelves: str = Form(""),
    auto_enrich: bool = Form(True),
):
    _require_admin(request)
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Must be a .csv file")
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="CSV is too large (max 50 MB)")
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
    background_tasks.add_task(_run_import, csv_content, phys, auto_enrich)
    return {"status": "started"}


@router.get("/import/status", response_model=ImportStatus, summary="Check import status")
def import_status():
    return ImportStatus(**_import_status)


@router.get("/import/summary", summary="Summary of current import")
def import_summary():
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
    _require_admin(request)
    try:
        pg = _pg()
        cur = pg.cursor()

        cur.execute("SELECT shelf_id FROM goodreads_shelves WHERE shelf_id IS NOT NULL")
        shelf_ids = [r["shelf_id"] for r in cur.fetchall()]

        cur.execute("SELECT native_book_id FROM goodreads_books WHERE native_book_id IS NOT NULL")
        native_ids = [r["native_book_id"] for r in cur.fetchall()]

        if shelf_ids:
            cur.execute("DELETE FROM shelf_books WHERE shelf_id = ANY(%s)", (shelf_ids,))
            cur.execute("DELETE FROM shelves WHERE id = ANY(%s)", (shelf_ids,))

        cur.execute("DELETE FROM goodreads_shelves")
        cur.execute("DELETE FROM book_ratings WHERE source='goodreads'")
        cur.execute("DELETE FROM book_ownership")

        if native_ids:
            cur.execute("DELETE FROM native_books WHERE id = ANY(%s)", (native_ids,))

        cur.execute("DELETE FROM goodreads_books")

        pg.commit()
        pg.close()

        global _import_status
        _import_status = {"status": "idle"}

        return {
            "status": "undone",
            "shelves_removed": len(shelf_ids),
            "native_books_removed": len(native_ids),
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Undo failed: {e}")


@router.get("/ownership/{book_id}", summary="Get ownership info for a Calibre book")
def get_ownership(book_id: int):
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


@router.get("/ratings/{book_id}", summary="Get Goodreads rating for a book")
def get_rating(book_id: int, book_source: str = "calibre"):
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
