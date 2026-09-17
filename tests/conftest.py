"""Hermetic fixtures: a throwaway Calibre-shaped SQLite file, a fake Postgres,
and a switchable identity. Nothing here touches a real library or database."""
import os, sqlite3, sys, tempfile, pathlib
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_LIB = tempfile.mkdtemp(prefix="bc-testlib-")
_DATA = tempfile.mkdtemp(prefix="bc-testdata-")
os.environ.update({
    "CALIBRE_DB_PATH": os.path.join(_LIB, "metadata.db"),
    "CALIBRE_LIBRARY_PATH": _LIB,
    "COVER_CACHE_DIR": os.path.join(_DATA, "covers"),
    "WEBDAV_DIR": os.path.join(_DATA, "webdav"),
    "SEARCH_INDEX_PATH": os.path.join(_DATA, "fts.db"),
})

BOOK_DIR = "作者/三体 (1)"
BOOK_FILE = "三体 - 刘慈欣"


def _make_library():
    c = sqlite3.connect(os.environ["CALIBRE_DB_PATH"])
    c.executescript("""
        CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT, sort TEXT, path TEXT, has_cover INT DEFAULT 0,
                            pubdate TEXT, last_modified TEXT, timestamp TEXT, uuid TEXT, series_index REAL, author_sort TEXT);
        CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT, sort TEXT);
        CREATE TABLE series (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE comments (id INTEGER PRIMARY KEY, book INT, text TEXT);
        CREATE TABLE data (id INTEGER PRIMARY KEY, book INT, format TEXT, name TEXT, uncompressed_size INT);
        CREATE TABLE books_tags_link (id INTEGER PRIMARY KEY, book INT, tag INT);
        CREATE TABLE books_authors_link (id INTEGER PRIMARY KEY, book INT, author INT);
        CREATE TABLE books_series_link (id INTEGER PRIMARY KEY, book INT, series INT);
        CREATE TABLE ratings (id INTEGER PRIMARY KEY, rating INT);
        CREATE TABLE books_ratings_link (id INTEGER PRIMARY KEY, book INT, rating INT);
        CREATE TABLE publishers (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE books_publishers_link (id INTEGER PRIMARY KEY, book INT, publisher INT);
        CREATE TABLE identifiers (id INTEGER PRIMARY KEY, book INT, type TEXT, val TEXT);
        CREATE TABLE custom_columns (id INTEGER PRIMARY KEY, label TEXT, name TEXT, datatype TEXT, is_multiple INT, normalized INT);
    """)
    c.execute("INSERT INTO books (id, title, sort, path) VALUES (1, '三体', '三体', ?)", (BOOK_DIR,))
    c.execute("INSERT INTO data (book, format, name) VALUES (1, 'EPUB', ?)", (BOOK_FILE,))
    c.commit(); c.close()
    d = os.path.join(_LIB, BOOK_DIR); os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, BOOK_FILE + ".epub"), "wb") as f:
        f.write(b"PK\x03\x04 not really an epub")


_make_library()


class FakePG:
    """Accepts anything, returns nothing. Tests that need rows patch higher up."""
    def cursor(self): return self
    def execute(self, *a, **k): self.rowcount = 0
    def fetchone(self): return None
    def fetchall(self): return []
    def commit(self): pass
    def rollback(self): pass
    def close(self): pass


import app.pg_database as pgdb          # noqa: E402
pgdb.get_pg = lambda: FakePG()
import app.auth as auth                 # noqa: E402
import app.database as database         # noqa: E402
database.init_db()

ADMIN = {"id": 1, "username": "admin", "role": "admin"}
MEMBER = {"id": 2, "username": "kid", "role": "member"}
_identity = {"user": ADMIN}
auth.authenticate_request = lambda request: _identity["user"]


@pytest.fixture
def as_user():
    def _set(u): _identity["user"] = u
    yield _set
    _identity["user"] = ADMIN


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)   # no lifespan: no real startup
