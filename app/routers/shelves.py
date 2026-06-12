"""
Shelves — manual and smart.
Manual shelves: user-curated lists of books.
Smart shelves: saved queries that auto-populate based on rules.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

router = APIRouter()

# ── Pydantic models ──────────────────────────────────────────────────────────

class ShelfCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_smart: bool = False
    smart_rules: Optional[dict] = None  # JSON rules for smart shelves
    owner_id: Optional[int] = None
    is_shared: bool = False

class Shelf(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_smart: bool
    smart_rules: Optional[dict] = None
    owner_id: Optional[int] = None
    is_shared: bool
    book_count: int = 0
    created_at: Optional[datetime] = None

class ShelfBookAdd(BaseModel):
    book_id: int
    book_source: str = "calibre"  # calibre or native

class ShelfBook(BaseModel):
    book_id: int
    book_source: str
    title: str
    authors: list[str]
    cover_url: Optional[str] = None
    has_cover: bool = False
    series_name: Optional[str] = None
    series_index: Optional[float] = None
    added_at: Optional[datetime] = None
    location: Optional[str] = None
    has_physical: bool = False
    has_digital: bool = True
    percentage: Optional[float] = None  # reading progress (0..1), for Currently Reading


def _pg():
    from ..pg_database import get_database_url
    import psycopg2
    from psycopg2.extras import RealDictCursor
    return psycopg2.connect(get_database_url(), cursor_factory=RealDictCursor)


def _ensure_tables():
    """Create shelf tables if missing (supplement to pg_database init)."""
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS shelves (
                id          SERIAL PRIMARY KEY,
                name        TEXT NOT NULL,
                description TEXT,
                is_smart    BOOLEAN DEFAULT FALSE,
                smart_rules JSONB,
                owner_id    INTEGER,
                is_shared   BOOLEAN DEFAULT FALSE,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS shelf_books (
                shelf_id    INTEGER REFERENCES shelves(id) ON DELETE CASCADE,
                book_id     INTEGER NOT NULL,
                book_source TEXT NOT NULL DEFAULT 'calibre',
                added_at    TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (shelf_id, book_id, book_source)
            );
            -- Self-heal: the base `shelves` table may have been created by the
            -- startup init WITHOUT these columns (CREATE TABLE IF NOT EXISTS above
            -- won't add them to an existing table). On a fresh database this is
            -- what previously caused /api/shelves to 503.
            ALTER TABLE shelves ADD COLUMN IF NOT EXISTS is_smart    BOOLEAN DEFAULT FALSE;
            ALTER TABLE shelves ADD COLUMN IF NOT EXISTS smart_rules JSONB;
            ALTER TABLE shelves ADD COLUMN IF NOT EXISTS owner_id    INTEGER;
            ALTER TABLE shelves ADD COLUMN IF NOT EXISTS is_shared   BOOLEAN DEFAULT FALSE;
        """)
        # Seed default smart shelves if none exist
        cur.execute("SELECT COUNT(*) as c FROM shelves WHERE is_smart = TRUE")
        if cur.fetchone()["c"] == 0:
            defaults = [
                ("Most Recent", "The 50 most recently added books (digital + physical)", True,
                 '{"type": "most_recent", "limit": 50}'),
                ("Highly Rated", "Books rated 4 stars or higher", True,
                 '{"type": "min_rating", "rating": 4}'),
                ("Currently Reading", "Books with reading progress started but not finished", True,
                 '{"type": "reading_status", "status": "reading"}'),
            ]
            for name, desc, is_smart, rules in defaults:
                cur.execute(
                    "INSERT INTO shelves (name, description, is_smart, smart_rules, is_shared) VALUES (%s,%s,%s,%s::jsonb,TRUE)",
                    (name, desc, is_smart, rules)
                )
        # Self-heal: convert the old default "Recently Added / 30 days" shelf to
        # the newer "Most Recent / 50" so existing installs update automatically
        # (matches the seed above; only touches the old default, not custom shelves).
        cur.execute(
            """
            UPDATE shelves SET name='Most Recent',
                description='The 50 most recently added books (digital + physical)',
                smart_rules='{"type":"most_recent","limit":50}'::jsonb
            WHERE is_smart = TRUE AND name='Recently Added'
              AND smart_rules->>'type' = 'recently_added'
            """
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Shelf table init: {e}")


_LINK_FIELDS = {  # field -> (link table, link col, target table, name col)
    "tag":       ("books_tags_link", "tag", "tags", "name"),
    "author":    ("books_authors_link", "author", "authors", "name"),
    "series":    ("books_series_link", "series", "series", "name"),
    "publisher": ("books_publishers_link", "publisher", "publishers", "name"),
}


def _condition_sql(conn, c: dict):
    """One smart-shelf condition → (sql, params) referencing `b.id`. None if invalid."""
    field, op, val = c.get("field"), c.get("op"), c.get("value")

    if field in _LINK_FIELDS:
        lt, lc, tt, nc = _LINK_FIELDS[field]
        inner = f"SELECT 1 FROM {lt} l JOIN {tt} t ON t.id = l.{lc} WHERE l.book = b.id AND t.{nc}"
        if op == "is_not":
            return (f"NOT EXISTS ({inner} = ?)", [val])
        if op == "contains":
            return (f"EXISTS ({inner} LIKE ?)", [f"%{val}%"])
        return (f"EXISTS ({inner} = ?)", [val])

    if field == "title":
        return ("b.title = ?", [val]) if op == "is" else ("b.title LIKE ?", [f"%{val}%"])

    if field == "pubdate":
        return ("b.pubdate <= ?", [val]) if op in ("before", "lte", "lt") else ("b.pubdate >= ?", [val])

    if field == "rating":
        cmp = {"gte": ">=", "lte": "<=", "gt": ">", "lt": "<", "is": "="}.get(op, ">=")
        return (f"EXISTS (SELECT 1 FROM books_ratings_link brl JOIN ratings r ON r.id=brl.rating "
                f"WHERE brl.book=b.id AND r.rating {cmp} ?)", [int(float(val)) * 2])

    if field and field.startswith("custom:"):
        col = conn.execute("SELECT id, datatype, normalized FROM custom_columns WHERE label = ?",
                           (field.split(":", 1)[1],)).fetchone()
        if not col:
            return (None, [])
        cid, dt, norm = int(col["id"]), col["datatype"], col["normalized"]
        val_tbl = f"books_custom_column_{cid}_link l WHERE l.book=b.id" if norm else f"custom_column_{cid} cc WHERE cc.book=b.id"
        if op == "is_set":
            return (f"EXISTS (SELECT 1 FROM {val_tbl})", [])
        if op == "not_set":
            return (f"NOT EXISTS (SELECT 1 FROM {val_tbl})", [])
        if dt == "bool":
            clause = f"EXISTS (SELECT 1 FROM custom_column_{cid} cc WHERE cc.book=b.id AND cc.value=1)"
            return (f"NOT {clause}", []) if op == "is_false" else (clause, [])
        if norm:
            inner = f"SELECT 1 FROM books_custom_column_{cid}_link l JOIN custom_column_{cid} v ON v.id=l.value WHERE l.book=b.id AND v.value"
            if op == "contains":
                return (f"EXISTS ({inner} LIKE ?)", [f"%{val}%"])
            if op == "is_not":
                return (f"NOT EXISTS ({inner} = ?)", [val])
            return (f"EXISTS ({inner} = ?)", [val])
        if op == "contains":
            return (f"EXISTS (SELECT 1 FROM custom_column_{cid} cc WHERE cc.book=b.id AND cc.value LIKE ?)", [f"%{val}%"])
        cmp = {"gte": ">=", "lte": "<=", "gt": ">", "lt": "<", "before": "<", "after": ">", "is": "="}.get(op, "=")
        return (f"EXISTS (SELECT 1 FROM custom_column_{cid} cc WHERE cc.book=b.id AND cc.value {cmp} ?)", [val])

    return (None, [])


def _build_query_where(conn, rules: dict):
    join = "OR" if rules.get("match") == "any" else "AND"
    conds, params = [], []
    for c in rules.get("conditions", []):
        sql, p = _condition_sql(conn, c)
        if sql:
            conds.append(sql)
            params += p
    if not conds:
        return ("1=1", [])
    return ("(" + f" {join} ".join(conds) + ")", params)


def _resolve_smart_shelf(rules: dict, base_url: str, username: str = None, allowed=None) -> list[ShelfBook]:
    """Execute a smart shelf query against Calibre's database."""
    from ..database import get_conn
    from .. import access
    shelf_type = rules.get("type")
    books = []

    # Currently Reading — driven by the signed-in user's KOReader sync progress.
    if shelf_type == "reading_status":
        if not username:
            return []
        try:
            pg = _pg(); pcur = pg.cursor()
            pcur.execute(
                """SELECT dm.book_id, kp.percentage
                   FROM kosync_progress kp JOIN document_map dm ON dm.document = kp.document
                   WHERE kp.username = %s AND dm.book_source = 'calibre'
                   ORDER BY kp.updated_at DESC""",
                (username,),
            )
            prog = pcur.fetchall(); pg.close()
        except Exception:
            return []
        with get_conn() as conn:
            seen = set()
            for p in prog:
                bid = p["book_id"]
                if bid in seen:
                    continue
                if not access.is_calibre_book_allowed(conn, bid, allowed):
                    continue
                row = conn.execute(
                    """SELECT b.id, b.title, b.has_cover, b.series_index,
                              (SELECT GROUP_CONCAT(a.name, ', ') FROM authors a
                               JOIN books_authors_link bal ON bal.author=a.id WHERE bal.book=b.id) as authors,
                              (SELECT s.name FROM series s JOIN books_series_link bsl ON bsl.series=s.id
                               WHERE bsl.book=b.id LIMIT 1) as series_name
                       FROM books b WHERE b.id = ?""",
                    (bid,),
                ).fetchone()
                if not row:
                    continue
                seen.add(bid)
                has_cover = bool(row["has_cover"])
                books.append(ShelfBook(
                    book_id=row["id"], book_source="calibre", title=row["title"],
                    authors=[row["authors"]] if row["authors"] else [],
                    has_cover=has_cover,
                    cover_url=f"{base_url}/api/covers/{row['id']}" if has_cover else None,
                    series_name=row["series_name"], series_index=row["series_index"],
                    percentage=p["percentage"],
                ))
        # Physical books manually marked "currently reading".
        if rules.get("status", "reading") == "reading":
            try:
                pg = _pg(); ncur = pg.cursor()
                ncur.execute("SELECT id, title, author, cover_url FROM native_books WHERE reading_status = 'reading' ORDER BY updated_at DESC")
                for nb in ncur.fetchall():
                    has_cover = bool(nb["cover_url"])
                    books.append(ShelfBook(
                        book_id=nb["id"], book_source="native", title=nb["title"] or "Untitled",
                        authors=[nb["author"]] if nb["author"] else [],
                        has_cover=has_cover,
                        cover_url=f"{base_url}/api/native/books/{nb['id']}/cover" if has_cover else None,
                    ))
                pg.close()
            except Exception:
                pass
        return books

    with get_conn() as conn:
        if shelf_type == "most_recent":
            import datetime as _dt
            limit = rules.get("limit", 50)
            cal = conn.execute(
                """
                SELECT b.id, b.title, b.has_cover, b.series_index, b.timestamp,
                       (SELECT GROUP_CONCAT(a.name, ', ') FROM authors a
                        JOIN books_authors_link bal ON bal.author=a.id WHERE bal.book=b.id) as authors,
                       (SELECT s.name FROM series s JOIN books_series_link bsl ON bsl.series=s.id
                        WHERE bsl.book=b.id LIMIT 1) as series_name
                FROM books b ORDER BY b.timestamp DESC LIMIT ?
                """,
                (limit,)
            ).fetchall()
            native = []
            try:
                pg = _pg(); ncur = pg.cursor()
                # Use the real added-date (Goodreads "Date Added" for imports),
                # falling back to row-creation time — otherwise a bulk import makes
                # every physical book look "added today" and floods this shelf,
                # burying genuinely-recent digital books.
                ncur.execute("SELECT id, title, author, cover_url, "
                             "EXTRACT(EPOCH FROM COALESCE(date_added, created_at)) AS ek "
                             "FROM native_books ORDER BY COALESCE(date_added, created_at) DESC LIMIT %s", (limit,))
                native = ncur.fetchall(); pg.close()
            except Exception:
                pass

            def _cal_epoch(ts):
                try:
                    return _dt.datetime.fromisoformat(str(ts)).timestamp()
                except Exception:
                    return 0.0

            merged = []  # (epoch, ShelfBook)
            for row in cal:
                hc = bool(row["has_cover"])
                merged.append((_cal_epoch(row["timestamp"]), ShelfBook(
                    book_id=row["id"], book_source="calibre", title=row["title"],
                    authors=[row["authors"]] if row["authors"] else [],
                    has_cover=hc, cover_url=f"{base_url}/api/covers/{row['id']}" if hc else None,
                    series_name=row["series_name"], series_index=row["series_index"])))
            for nb in native:
                hc = bool(nb["cover_url"])
                merged.append((float(nb["ek"] or 0), ShelfBook(
                    book_id=nb["id"], book_source="native", title=nb["title"] or "Untitled",
                    authors=[nb["author"]] if nb["author"] else [],
                    has_cover=hc, cover_url=f"{base_url}/api/native/books/{nb['id']}/cover" if hc else None)))
            merged.sort(key=lambda t: t[0], reverse=True)
            books = [b for _, b in merged[:limit]]
            rows = []

        elif shelf_type == "recently_added":
            days = rules.get("days", 30)
            rows = conn.execute(
                """
                SELECT b.id, b.title, b.has_cover, b.series_index,
                       (SELECT GROUP_CONCAT(a.name, ', ') FROM authors a
                        JOIN books_authors_link bal ON bal.author=a.id WHERE bal.book=b.id) as authors,
                       (SELECT s.name FROM series s JOIN books_series_link bsl ON bsl.series=s.id
                        WHERE bsl.book=b.id LIMIT 1) as series_name
                FROM books b
                WHERE substr(b.timestamp, 1, 19) >= strftime('%Y-%m-%d %H:%M:%S', 'now', ?)
                ORDER BY b.timestamp DESC LIMIT 50
                """,
                (f"-{days} days",)
            ).fetchall()

        elif shelf_type == "min_rating":
            raw = rules.get("rating", 4)
            threshold = raw / 2 if raw > 5 else raw  # accept stars (0–5) or Calibre 0–10
            # Effective rating = pending overlay rating if present, else Calibre's.
            eff = {}
            for r in conn.execute(
                "SELECT brl.book AS id, r.rating AS rating FROM books_ratings_link brl JOIN ratings r ON r.id = brl.rating"
            ).fetchall():
                eff[r["id"]] = (r["rating"] or 0) / 2.0
            try:
                pg = _pg(); pc = pg.cursor()
                pc.execute("SELECT book_id, value FROM calibre_edits WHERE field = 'rating'")
                for r in pc.fetchall():
                    try:
                        eff[r["book_id"]] = float(r["value"])
                    except (TypeError, ValueError):
                        pass
                pg.close()
            except Exception:
                pass
            qualifying = sorted([bid for bid, rt in eff.items() if rt is not None and rt >= threshold],
                                key=lambda b: -eff[b])
            if qualifying:
                ph = ",".join("?" * len(qualifying))
                rows = conn.execute(
                    f"""
                    SELECT b.id, b.title, b.has_cover, b.series_index,
                           (SELECT GROUP_CONCAT(a.name, ', ') FROM authors a
                            JOIN books_authors_link bal ON bal.author=a.id WHERE bal.book=b.id) as authors,
                           (SELECT s.name FROM series s JOIN books_series_link bsl ON bsl.series=s.id
                            WHERE bsl.book=b.id LIMIT 1) as series_name
                    FROM books b WHERE b.id IN ({ph})
                    """, qualifying
                ).fetchall()
            else:
                rows = []

        elif shelf_type == "query":
            where_sql, qparams = _build_query_where(conn, rules)
            cal_pred, cp = access.calibre_predicate(allowed, "b")
            if cal_pred:
                where_sql = f"{where_sql} AND {cal_pred}"
                qparams = qparams + cp
            rows = conn.execute(
                f"""
                SELECT b.id, b.title, b.has_cover, b.series_index,
                       (SELECT GROUP_CONCAT(a.name, ', ') FROM authors a
                        JOIN books_authors_link bal ON bal.author=a.id WHERE bal.book=b.id) as authors,
                       (SELECT s.name FROM series s JOIN books_series_link bsl ON bsl.series=s.id
                        WHERE bsl.book=b.id LIMIT 1) as series_name
                FROM books b
                WHERE {where_sql}
                ORDER BY b.sort ASC
                """,
                qparams,
            ).fetchall()

        else:
            return []

        for row in rows:
            has_cover = bool(row["has_cover"])
            books.append(ShelfBook(
                book_id=row["id"],
                book_source="calibre",
                title=row["title"],
                authors=[row["authors"]] if row["authors"] else [],
                has_cover=has_cover,
                cover_url=f"{base_url}/api/covers/{row['id']}" if has_cover else None,
                series_name=row["series_name"],
                series_index=row["series_index"],
            ))

    return books


# ── Ownership helpers ────────────────────────────────────────────────────────
# A shelf belongs to a user when owner_id == their id. Legacy/seeded shelves have
# owner_id IS NULL (or is_shared) and are visible to everyone but only an admin
# may mutate them. This prevents one member from reading/deleting another's shelf.

def _user(request: Request):
    return getattr(request.state, "user", None)


def _can_edit_shelf(cur, shelf_id: int, user) -> bool:
    cur.execute("SELECT owner_id FROM shelves WHERE id = %s", (shelf_id,))
    row = cur.fetchone()
    if not row or not user:
        return False
    return row["owner_id"] == user["id"] or user.get("role") == "admin"


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[Shelf], summary="List the caller's shelves + shared shelves")
def list_shelves(request: Request):
    from .. import access
    _ensure_tables()
    try:
        user = _user(request)
        uid = user["id"] if user else -1
        conn = _pg()
        cur = conn.cursor()
        # Own shelves + shared/legacy (owner_id NULL or is_shared) only.
        cur.execute("""
            SELECT s.*,
                   CASE WHEN s.is_smart THEN 0
                        ELSE (SELECT COUNT(*) FROM shelf_books sb WHERE sb.shelf_id = s.id)
                   END as book_count
            FROM shelves s
            WHERE s.owner_id = %s OR s.owner_id IS NULL OR s.is_shared
            ORDER BY s.is_smart DESC, s.name ASC
        """, (uid,))
        rows = cur.fetchall()
        conn.close()

        username = user.get("username") if user else None
        allowed = access.restriction_for_request(request)

        result = []
        for r in rows:
            count = r["book_count"]
            # Smart shelves have no stored membership — resolve to count them.
            if r["is_smart"] and r["smart_rules"]:
                try:
                    count = len(_resolve_smart_shelf(dict(r["smart_rules"]), "",
                                                     username=username, allowed=allowed))
                except Exception:
                    count = 0
            result.append(Shelf(
                id=r["id"], name=r["name"], description=r["description"],
                is_smart=r["is_smart"], smart_rules=r["smart_rules"],
                owner_id=r["owner_id"], is_shared=r["is_shared"],
                book_count=count, created_at=r["created_at"],
            ))
        return result
    except Exception as e:
        raise HTTPException(status_code=503, detail="Database unavailable")


class PreviewBody(BaseModel):
    smart_rules: dict


@router.post("/preview", summary="Count books matching smart-shelf rules (live preview)")
def preview_shelf(body: PreviewBody, request: Request):
    from ..database import get_conn
    from .. import access
    rules = body.smart_rules or {}
    if rules.get("type") != "query":
        return {"count": 0}
    allowed = access.restriction_for_request(request)
    with get_conn() as conn:
        where_sql, params = _build_query_where(conn, rules)
        cal_pred, cp = access.calibre_predicate(allowed, "b")
        if cal_pred:
            where_sql = f"{where_sql} AND {cal_pred}"
            params = params + cp
        n = conn.execute(f"SELECT COUNT(*) FROM books b WHERE {where_sql}", params).fetchone()[0]
    return {"count": n}


@router.post("", response_model=Shelf, status_code=201, summary="Create a shelf (owned by the caller)")
def create_shelf(shelf: ShelfCreate, request: Request):
    _ensure_tables()
    user = _user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    # owner_id is the session user; only an admin may publish a shared shelf.
    owner_id = user["id"]
    is_shared = bool(shelf.is_shared) and user.get("role") == "admin"
    try:
        import json
        conn = _pg()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO shelves (name, description, is_smart, smart_rules, owner_id, is_shared)
               VALUES (%s,%s,%s,%s::jsonb,%s,%s) RETURNING *""",
            (shelf.name, shelf.description, shelf.is_smart,
             json.dumps(shelf.smart_rules) if shelf.smart_rules else None,
             owner_id, is_shared)
        )
        row = cur.fetchone()
        conn.commit()
        conn.close()
        return Shelf(id=row["id"], name=row["name"], description=row["description"],
                     is_smart=row["is_smart"], smart_rules=row["smart_rules"],
                     owner_id=row["owner_id"], is_shared=row["is_shared"],
                     book_count=0, created_at=row["created_at"])
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Database error")


@router.delete("/{shelf_id}", status_code=204, summary="Delete a shelf (owner or admin)")
def delete_shelf(shelf_id: int, request: Request):
    try:
        conn = _pg()
        cur = conn.cursor()
        if not _can_edit_shelf(cur, shelf_id, _user(request)):
            conn.close()
            raise HTTPException(status_code=403, detail="Not your shelf")
        cur.execute("DELETE FROM shelves WHERE id = %s", (shelf_id,))
        conn.commit()
        conn.close()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Database error")


@router.get("/{shelf_id}/books", response_model=list[ShelfBook], summary="Get books on a shelf")
def get_shelf_books(shelf_id: int, request: Request):
    from .. import access
    base_url = str(request.base_url).rstrip("/")
    allowed = access.restriction_for_request(request)
    _ensure_tables()
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("SELECT * FROM shelves WHERE id = %s", (shelf_id,))
        shelf = cur.fetchone()
        conn.close()
        if not shelf:
            raise HTTPException(status_code=404, detail=f"Shelf {shelf_id} not found")
        # Visibility: own shelf, or a shared / legacy (owner_id NULL) one.
        _vu = _user(request)
        if not (shelf["owner_id"] is None or shelf["is_shared"]
                or (_vu and shelf["owner_id"] == _vu["id"])):
            raise HTTPException(status_code=403, detail="Not your shelf")

        if shelf["is_smart"] and shelf["smart_rules"]:
            _u = getattr(request.state, "user", None)
            smart = _resolve_smart_shelf(dict(shelf["smart_rules"]), base_url,
                                         username=_u.get("username") if _u else None,
                                         allowed=allowed)
            if allowed is not None:
                from ..database import get_conn
                with get_conn() as cc:
                    smart = [b for b in smart
                             if access.is_calibre_book_allowed(cc, b.book_id, allowed)]
            return smart

        # Manual shelf — join with Calibre metadata
        conn = _pg()
        cur = conn.cursor()
        cur.execute(
            "SELECT book_id, book_source, added_at FROM shelf_books WHERE shelf_id = %s ORDER BY added_at DESC",
            (shelf_id,)
        )
        entries = cur.fetchall()
        conn.close()

        books = []
        from ..database import get_conn

        # Batch fetch ownership for calibre books
        calibre_ids = [e["book_id"] for e in entries if e["book_source"] == "calibre"]
        ownership_map = {}
        if calibre_ids:
            try:
                pg2 = _pg()
                cur2 = pg2.cursor()
                cur2.execute(
                    "SELECT book_id, has_physical, physical_location FROM book_ownership WHERE book_id = ANY(%s) AND book_source='calibre'",
                    (calibre_ids,)
                )
                for r in cur2.fetchall():
                    ownership_map[r["book_id"]] = {"has_physical": r["has_physical"], "physical_location": r["physical_location"]}
                pg2.close()
            except Exception:
                pass

        with get_conn() as cal_conn:
            for entry in entries:
                if entry["book_source"] == "calibre":
                    if allowed is not None and not access.is_calibre_book_allowed(cal_conn, entry["book_id"], allowed):
                        continue
                    row = cal_conn.execute(
                        """SELECT b.id, b.title, b.has_cover, b.series_index,
                                  (SELECT GROUP_CONCAT(a.name, ', ') FROM authors a
                                   JOIN books_authors_link bal ON bal.author=a.id WHERE bal.book=b.id) as authors,
                                  (SELECT s.name FROM series s JOIN books_series_link bsl ON bsl.series=s.id
                                   WHERE bsl.book=b.id LIMIT 1) as series_name
                           FROM books b WHERE b.id = ?""",
                        (entry["book_id"],)
                    ).fetchone()
                    if row:
                        has_cover = bool(row["has_cover"])
                        own = ownership_map.get(row["id"], {})
                        books.append(ShelfBook(
                            book_id=row["id"], book_source="calibre",
                            title=row["title"],
                            authors=[row["authors"]] if row["authors"] else [],
                            has_cover=has_cover,
                            cover_url=f"{base_url}/api/covers/{row['id']}" if has_cover else None,
                            series_name=row["series_name"],
                            series_index=row["series_index"],
                            added_at=entry["added_at"],
                            has_physical=own.get("has_physical", False),
                            has_digital=True,
                            location=own.get("physical_location"),
                        ))
                elif entry["book_source"] == "native":
                    pg2 = _pg()
                    cur2 = pg2.cursor()
                    cur2.execute("SELECT * FROM native_books WHERE id = %s", (entry["book_id"],))
                    nb = cur2.fetchone()
                    pg2.close()
                    if nb and (allowed is None or access.is_native_allowed(nb.get("categories"), allowed)):
                        books.append(ShelfBook(
                            book_id=nb["id"], book_source="native",
                            title=nb["title"],
                            authors=[nb["author"]] if nb["author"] else [],
                            has_cover=bool(nb.get("cover_url")),
                            cover_url=nb.get("cover_url"),
                            added_at=entry["added_at"],
                            location=nb.get("location"),
                        ))
        return books
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Error: {e}")


@router.post("/{shelf_id}/books", status_code=201, summary="Add a book to a shelf (owner or admin)")
def add_book_to_shelf(shelf_id: int, book: ShelfBookAdd, request: Request):
    _ensure_tables()
    try:
        conn = _pg()
        cur = conn.cursor()
        if not _can_edit_shelf(cur, shelf_id, _user(request)):
            conn.close()
            raise HTTPException(status_code=403, detail="Not your shelf")
        cur.execute(
            """INSERT INTO shelf_books (shelf_id, book_id, book_source)
               VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""",
            (shelf_id, book.book_id, book.book_source)
        )
        conn.commit()
        conn.close()
        return {"status": "added"}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Database error")


@router.delete("/{shelf_id}/books/{book_id}", status_code=204, summary="Remove a book from a shelf (owner or admin)")
def remove_book_from_shelf(shelf_id: int, book_id: int, request: Request, book_source: str = "calibre"):
    try:
        conn = _pg()
        cur = conn.cursor()
        if not _can_edit_shelf(cur, shelf_id, _user(request)):
            conn.close()
            raise HTTPException(status_code=403, detail="Not your shelf")
        cur.execute(
            "DELETE FROM shelf_books WHERE shelf_id=%s AND book_id=%s AND book_source=%s",
            (shelf_id, book_id, book_source)
        )
        conn.commit()
        conn.close()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Database error")
