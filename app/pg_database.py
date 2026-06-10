"""
PostgreSQL database layer for Bibliocapsa native library.
Handles: native books, users, family members, shelves, lending, reading progress.
Completely separate from Calibre's SQLite database.
"""

import os
import logging

logger = logging.getLogger(__name__)

_DATABASE_URL: str | None = None


def get_database_url() -> str:
    return (
        os.getenv("DATABASE_URL")
        or f"postgresql://{os.getenv('POSTGRES_USER', 'bibliocapsa')}:"
           f"{os.getenv('POSTGRES_PASSWORD', 'bibliocapsa')}@"
           f"{os.getenv('POSTGRES_HOST', 'db')}:"
           f"{os.getenv('POSTGRES_PORT', '5432')}/"
           f"{os.getenv('POSTGRES_DB', 'bibliocapsa')}"
    )


def init_postgres():
    """Create tables if they don't exist."""
    try:
        import psycopg2

        url = get_database_url()
        conn = psycopg2.connect(url)
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          SERIAL PRIMARY KEY,
                name        TEXT NOT NULL,
                email       TEXT UNIQUE,
                role        TEXT NOT NULL DEFAULT 'member',  -- admin, member
                avatar_url  TEXT,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS native_books (
                id              SERIAL PRIMARY KEY,
                title           TEXT NOT NULL,
                author          TEXT,
                isbn            TEXT,
                isbn13          TEXT,
                cover_url       TEXT,
                description     TEXT,
                page_count      INTEGER,
                publisher       TEXT,
                published_date  TEXT,
                categories      TEXT[],
                language        TEXT DEFAULT 'en',
                format          TEXT NOT NULL DEFAULT 'physical',  -- physical, digital
                location        TEXT,  -- shelf, room, etc.
                owner_id        INTEGER REFERENCES users(id),
                added_by        INTEGER REFERENCES users(id),
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                updated_at      TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS shelves (
                id          SERIAL PRIMARY KEY,
                name        TEXT NOT NULL,
                description TEXT,
                is_smart    BOOLEAN DEFAULT FALSE,  -- smart (saved-query) vs manual shelf
                smart_rules JSONB,                  -- rules for smart shelves
                owner_id    INTEGER REFERENCES users(id),
                is_shared   BOOLEAN DEFAULT FALSE,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS shelf_books (
                shelf_id    INTEGER REFERENCES shelves(id) ON DELETE CASCADE,
                book_id     INTEGER,
                book_source TEXT NOT NULL DEFAULT 'native',  -- native, calibre
                added_at    TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (shelf_id, book_id, book_source)
            );

            -- Which Calibre books are also owned physically (+ location). The
            -- Goodreads import populates it, but core book-listing code reads it,
            -- so it must exist on a fresh database (created here, not just lazily
            -- on first import).
            CREATE TABLE IF NOT EXISTS book_ownership (
                book_id           INTEGER NOT NULL,
                book_source       TEXT NOT NULL DEFAULT 'calibre',
                has_digital       BOOLEAN DEFAULT FALSE,
                has_physical      BOOLEAN DEFAULT FALSE,
                physical_location TEXT,
                PRIMARY KEY (book_id, book_source)
            );

            CREATE TABLE IF NOT EXISTS lending (
                id              SERIAL PRIMARY KEY,
                book_id         INTEGER NOT NULL,
                book_source     TEXT NOT NULL DEFAULT 'native',  -- native, calibre
                borrower_name   TEXT NOT NULL,
                borrower_email  TEXT,
                borrower_phone  TEXT,
                lent_by         INTEGER REFERENCES users(id),
                loan_date       TIMESTAMPTZ DEFAULT NOW(),
                due_date        TIMESTAMPTZ,
                returned_date   TIMESTAMPTZ,
                notes           TEXT,
                created_at      TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS reading_progress (
                id              SERIAL PRIMARY KEY,
                book_id         INTEGER NOT NULL,
                book_source     TEXT NOT NULL DEFAULT 'calibre',  -- native, calibre
                user_id         INTEGER REFERENCES users(id),
                device          TEXT,
                progress        REAL DEFAULT 0,  -- 0.0 to 1.0
                current_page    INTEGER,
                total_pages     INTEGER,
                cfi             TEXT,  -- EPUB CFI position
                percentage      REAL,
                last_read_at    TIMESTAMPTZ DEFAULT NOW(),
                created_at      TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(book_id, book_source, user_id, device)
            );

            -- Key/value app settings (Hardcover API token, etc.)
            CREATE TABLE IF NOT EXISTS app_settings (
                key         TEXT PRIMARY KEY,
                value       TEXT,
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            );

            -- ── Authentication ──────────────────────────────────────────────
            -- One account per person, used for the web/API login AND KOReader
            -- sync. `password_hash` is PBKDF2 (web login); `kosync_key` is the
            -- MD5 KOReader sends (same password, two derivations — see auth.py).
            ALTER TABLE users ADD COLUMN IF NOT EXISTS username TEXT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS kosync_key TEXT;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS kindle_email TEXT;  -- Send-to-Kindle target
            ALTER TABLE users ADD COLUMN IF NOT EXISTS theme TEXT;  -- UI colour theme
            ALTER TABLE users ADD COLUMN IF NOT EXISTS font TEXT;   -- UI font scheme
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(LOWER(username));

            -- Server-side sessions (revocable; no signing secret needed).
            CREATE TABLE IF NOT EXISTS sessions (
                token       TEXT PRIMARY KEY,
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                expires_at  TIMESTAMPTZ NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

            -- Per-member content access: allow-list of genres (lowercased tag /
            -- category names). A user with NO rows is unrestricted; admins are
            -- always unrestricted. A book is visible if ANY of its genres match.
            CREATE TABLE IF NOT EXISTS user_genre_access (
                user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                genre    TEXT NOT NULL,
                PRIMARY KEY (user_id, genre)
            );

            -- The earlier standalone KOSync account table is superseded by the
            -- unified users table above.
            DROP TABLE IF EXISTS kosync_users;

            -- Pending Calibre metadata edits (the "edit overlay"). Each row is a
            -- field change not yet pushed to Calibre; merged over Calibre data on
            -- read, and applied via calibredb on the deliberate "Sync to Calibre".
            CREATE TABLE IF NOT EXISTS calibre_edits (
                book_id     INTEGER NOT NULL,
                field       TEXT NOT NULL,
                value       JSONB,
                updated_at  TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (book_id, field)
            );

            -- Records the outcome of the bulk missing-metadata scan per Calibre
            -- book, so future scans skip ones already tried (status: filled|no_match).
            CREATE TABLE IF NOT EXISTS calibre_enrich_log (
                book_id     INTEGER PRIMARY KEY,
                status      TEXT,
                scanned_at  TIMESTAMPTZ DEFAULT NOW()
            );

            -- Pending new-book uploads: files added in Bibliocapsa, queued to be
            -- imported into Calibre via `calibredb add` on the next sync.
            CREATE TABLE IF NOT EXISTS calibre_uploads (
                id          SERIAL PRIMARY KEY,
                filename    TEXT NOT NULL,   -- stored name under the uploads volume
                orig_name   TEXT,
                title       TEXT,
                authors     TEXT,
                format      TEXT,
                size        BIGINT,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );

            -- Maps a KOReader document hash (partial MD5 of the file) to the
            -- Bibliocapsa book it belongs to. Populated when a file is served,
            -- so KOSync progress can be tied back to a specific book.
            CREATE TABLE IF NOT EXISTS document_map (
                document     TEXT PRIMARY KEY,
                book_id      INTEGER NOT NULL,
                book_source  TEXT NOT NULL DEFAULT 'calibre',
                format       TEXT,
                updated_at   TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_document_map_book ON document_map(book_id, book_source);

            -- Reading position per (user, document). `document` is KOReader's
            -- opaque content/filename hash; `progress` is its position string.
            CREATE TABLE IF NOT EXISTS kosync_progress (
                username    TEXT NOT NULL,
                document    TEXT NOT NULL,
                progress    TEXT,
                percentage  DOUBLE PRECISION,
                device      TEXT,
                device_id   TEXT,
                updated_at  TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (username, document)
            );

            -- Metadata enrichment columns on existing native_books table.
            -- (CREATE TABLE IF NOT EXISTS above won't add columns to an existing table.)
            ALTER TABLE native_books ADD COLUMN IF NOT EXISTS metadata_source TEXT;
            ALTER TABLE native_books ADD COLUMN IF NOT EXISTS enriched_at TIMESTAMPTZ;
            ALTER TABLE native_books ADD COLUMN IF NOT EXISTS enrich_status TEXT;  -- NULL=never, ok, no_match, error, manual
            ALTER TABLE native_books ADD COLUMN IF NOT EXISTS rating INTEGER;  -- personal rating 1-5, NULL=unrated
            ALTER TABLE native_books ADD COLUMN IF NOT EXISTS community_rating REAL;  -- Hardcover community avg (0-5)
            ALTER TABLE native_books ADD COLUMN IF NOT EXISTS reading_status TEXT;  -- NULL=unread, 'reading', 'read'
            ALTER TABLE native_books ADD COLUMN IF NOT EXISTS date_read TEXT;  -- 'YYYY-MM-DD' when finished
            ALTER TABLE native_books ADD COLUMN IF NOT EXISTS cover_variant INTEGER;  -- chosen generated-cover style (NULL = auto from title)
            ALTER TABLE native_books ADD COLUMN IF NOT EXISTS date_added TIMESTAMPTZ;  -- when added to the collection (e.g. Goodreads "Date Added"); falls back to created_at for sorting

            -- Community (Hardcover) rating for Calibre books, captured during lookups.
            CREATE TABLE IF NOT EXISTS calibre_community_rating (
                book_id    INTEGER PRIMARY KEY,
                rating     REAL,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );

            -- Read/Unread status for Calibre (digital) books. Calibre is read-only,
            -- so Bibliocapsa keeps its own status here — the single source of truth
            -- for the UI and the unified Read/Unread filter. When an admin maps a
            -- Calibre Yes/No column (Settings → Reading columns), marking a book read
            -- is ALSO queued as an overlay edit so it exports back into Calibre.
            CREATE TABLE IF NOT EXISTS calibre_read_status (
                book_id    INTEGER PRIMARY KEY,
                status     TEXT,        -- 'read' | 'reading' | NULL (unread)
                date_read  TEXT,        -- 'YYYY-MM-DD'
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_calibre_read_status ON calibre_read_status(status);

            -- Per-user read history: one row per time a user finished a book
            -- (digital or physical). Powers the running "read N times" list and
            -- lets users add / adjust / delete dates manually (e.g. to fix a date
            -- KOReader didn't capture). Independent of Calibre's single Date Read
            -- column, which only ever holds the original/first date.
            CREATE TABLE IF NOT EXISTS read_log (
                id          SERIAL PRIMARY KEY,
                book_id     INTEGER NOT NULL,
                book_source TEXT NOT NULL DEFAULT 'calibre',  -- 'calibre' | 'native'
                user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
                date_read   TEXT,        -- 'YYYY-MM-DD'
                source      TEXT,        -- 'manual' | 'koreader' | 'toggle'
                created_at  TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_read_log_book ON read_log(book_id, book_source, user_id);

            -- Per-user annual reading goal ("read N books this year").
            CREATE TABLE IF NOT EXISTS reading_goals (
                user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
                year       INTEGER NOT NULL,
                target     INTEGER NOT NULL,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (user_id, year)
            );

            -- Per-user "want to read" list — un-owned books (book_id NULL) AND
            -- owned library books bookmarked to read (book_id/book_source set).
            CREATE TABLE IF NOT EXISTS wishlist (
                id          SERIAL PRIMARY KEY,
                user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
                title       TEXT NOT NULL,
                author      TEXT,
                isbn        TEXT,
                cover_url   TEXT,
                notes       TEXT,
                book_id     INTEGER,   -- set when bookmarking an owned library book
                book_source TEXT,      -- 'calibre' | 'native' (with book_id)
                added_at    TIMESTAMPTZ DEFAULT NOW()
            );
            ALTER TABLE wishlist ADD COLUMN IF NOT EXISTS book_id     INTEGER;
            ALTER TABLE wishlist ADD COLUMN IF NOT EXISTS book_source TEXT;
            CREATE INDEX IF NOT EXISTS idx_wishlist_user ON wishlist(user_id, added_at DESC);

            -- Indexes
            CREATE INDEX IF NOT EXISTS idx_native_books_isbn ON native_books(isbn);
            CREATE INDEX IF NOT EXISTS idx_native_books_enrich ON native_books(enrich_status);
            CREATE INDEX IF NOT EXISTS idx_lending_book ON lending(book_id, book_source);
            CREATE INDEX IF NOT EXISTS idx_lending_active ON lending(returned_date) WHERE returned_date IS NULL;
            CREATE INDEX IF NOT EXISTS idx_reading_progress_book ON reading_progress(book_id, book_source, user_id);
        """)

        # Backfill date_added for physical books imported before this column
        # existed — idempotent (only fills NULLs) and guarded (only runs if the
        # Goodreads table is present). Keeps upgrades hands-off: no manual SQL.
        cur.execute("SELECT to_regclass('public.goodreads_books')")
        if cur.fetchone()[0] is not None:
            cur.execute("""
                UPDATE native_books nb
                SET date_added = to_timestamp(gb.date_added, 'YYYY/MM/DD')
                FROM goodreads_books gb
                WHERE gb.native_book_id = nb.id
                  AND gb.date_added ~ '^[0-9]{4}/[0-9]{2}/[0-9]{2}$'
                  AND nb.date_added IS NULL
            """)
            # Sync Goodreads "Date Read" history into read_log (the per-user read
            # history that powers reading goals / year-in-review). Idempotent via
            # NOT EXISTS; attributed to the first/admin account (single-user case).
            cur.execute("""
                INSERT INTO read_log (book_id, book_source, user_id, date_read, source)
                SELECT COALESCE(gb.calibre_book_id, gb.native_book_id),
                       CASE WHEN gb.calibre_book_id IS NOT NULL THEN 'calibre' ELSE 'native' END,
                       u.id,
                       to_char(to_date(gb.date_read, 'YYYY/MM/DD'), 'YYYY-MM-DD'),
                       'goodreads'
                FROM goodreads_books gb
                CROSS JOIN (SELECT id FROM users WHERE password_hash IS NOT NULL ORDER BY id LIMIT 1) u
                WHERE gb.date_read ~ '^[0-9]{4}/[0-9]{2}/[0-9]{2}$'
                  AND COALESCE(gb.calibre_book_id, gb.native_book_id) IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM read_log rl
                      WHERE rl.book_id = COALESCE(gb.calibre_book_id, gb.native_book_id)
                        AND rl.book_source = CASE WHEN gb.calibre_book_id IS NOT NULL THEN 'calibre' ELSE 'native' END
                        AND rl.user_id = u.id
                        AND rl.date_read = to_char(to_date(gb.date_read, 'YYYY/MM/DD'), 'YYYY-MM-DD')
                  )
            """)

        conn.commit()
        cur.close()
        conn.close()
        logger.info("PostgreSQL tables initialized")

    except Exception as e:
        logger.warning(f"PostgreSQL not available: {e}. Native library features disabled.")


def get_pg_conn():
    """Get a PostgreSQL connection."""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    conn = psycopg2.connect(get_database_url(), cursor_factory=RealDictCursor)
    try:
        yield conn
    finally:
        conn.close()
