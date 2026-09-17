"""Third batch of audit regressions (A04 A12 A13 A14 A15 A16 A18 A22 A34)."""
import inspect
from datetime import datetime, timezone
import pytest


# ── A14: matching never assigns another book's data ──────────────────────────
def test_normalisation_keeps_non_latin_titles_distinct():
    from app.textmatch import norm
    assert norm("红楼梦") and norm("西游记") and norm("红楼梦") != norm("西游记")
    assert norm("Émile, ou De l’éducation") == norm("emile ou de l'education")
    assert norm("The Hobbit") == norm("hobbit")

def test_authors_must_agree():
    from app.textmatch import authors_agree
    assert authors_agree(["Tolkien, J. R. R."], ["J.R.R. Tolkien"]) is True
    assert authors_agree(["Jane Smith"], ["Robert Jones"]) is False
    assert authors_agree(["曹雪芹"], ["曹雪芹 著"]) is True
    assert authors_agree([], ["Anyone"]) is None

def test_enrichment_refuses_lookalikes():
    from app.calibre_enrich import _best_match
    assert _best_match("红楼梦", "曹雪芹", [{"title": "西游记", "authors": ["吴承恩"], "description": "x"}]) is None
    same_title = [{"title": "Collected Poems", "authors": ["Philip Larkin"], "description": "x"}]
    assert _best_match("Collected Poems", "Sylvia Plath", same_title) is None        # exact title, wrong author
    assert _best_match("Collected Poems", "Larkin, Philip", same_title) is not None
    assert _best_match("???", None, [{"title": "!!!", "authors": []}]) is None       # nothing left to compare


# ── A22: one total order, keyless rows last, no repeats ──────────────────────
def test_ordering_is_total_and_blank_keys_come_last_both_ways():
    from app.routers.books import _ordered
    light = [("calibre", 1, "2024-01-01", "b"), ("native", 1, "2024-01-01", "a"), ("calibre", 2, None, "z"),
             ("calibre", 3, "2025-05-05", "c"), ("native", 2, None, "y")]
    for rev in (False, True):
        out = _ordered(light, rev)
        assert [t[2] for t in out][-2:] == [None, None]
        assert len({(t[0], t[1]) for t in out}) == len(light)
    assert [(t[0], t[1]) for t in _ordered(light, True)][:3] == [("calibre", 3), ("calibre", 1), ("native", 1)]
    assert _ordered(list(reversed(light)), True) == _ordered(light, True)            # input order is irrelevant

def test_sort_keys_are_store_independent():
    from app.routers.books import _sort_key, _text_key
    assert _text_key("Émile") == _text_key("emile")
    assert _sort_key("pubdate", "0101-01-01 00:00:00+00:00") is None                  # Calibre's "undefined"
    assert _sort_key("date_read", "") is None and _sort_key("date_read", "2024-02-03T10:00") == "2024-02-03"

def test_unknown_merged_sort_is_title_not_an_accident(client):
    a = client.get("/api/books", params={"format_filter": "all", "sort_by": "nonsense"})
    b = client.get("/api/books", params={"format_filter": "all", "sort_by": "title"})
    assert a.status_code == 200 and a.json()["items"] == b.json()["items"]


# ── A18: explicit unread/reading beats a stale Calibre "read" ────────────────
@pytest.fixture
def read_state(monkeypatch):
    import app.calibre_read as cr, app.calibre_overlay as ov, app.routers.settings as st
    state = {"own": {}, "edits": {}}
    monkeypatch.setattr(st, "get_setting", lambda k, d=None: {"reading_col_read": "read", "reading_col_date": "dr"}.get(k, d))
    monkeypatch.setattr(cr, "statuses", lambda ids=None: {b: s for b, s in state["own"].items() if ids is None or b in ids})
    monkeypatch.setattr(ov, "field_edits", lambda f: {b: v for (b, ff), v in state["edits"].items() if ff == f})
    return state

def _with_read_column(value_rows, date_rows=()):
    """Give the throwaway library a mapped bool column (#read) + date column (#dr)."""
    import os, sqlite3
    c = sqlite3.connect(os.environ["CALIBRE_DB_PATH"])
    c.executescript("""DELETE FROM custom_columns;
        INSERT INTO custom_columns (id,label,name,datatype,is_multiple,normalized) VALUES (1,'read','Read','bool',0,0),(2,'dr','Date','datetime',0,0);
        DROP TABLE IF EXISTS custom_column_1; DROP TABLE IF EXISTS custom_column_2;
        CREATE TABLE custom_column_1 (id INTEGER PRIMARY KEY, book INT, value INT);
        CREATE TABLE custom_column_2 (id INTEGER PRIMARY KEY, book INT, value TEXT);""")
    c.executemany("INSERT INTO custom_column_1 (book,value) VALUES (?,?)", value_rows)
    c.executemany("INSERT INTO custom_column_2 (book,value) VALUES (?,?)", date_rows)
    c.commit(); c.close()

def test_pending_unread_wins_over_calibre_read_everywhere(read_state, client):
    import app.calibre_read as cr
    _with_read_column([(1, 1)], [(1, "2020-05-05 00:00:00+00:00")])
    assert cr.effective([1]) == {1: {"status": "read", "date_read": "2020-05-05"}}
    read_state["edits"][(1, "custom:read")] = False                 # marked unread here; sync not run
    assert cr.effective([1]) == {} and cr.get_status(1)["status"] is None and cr.read_book_ids([1]) == set()
    ids = lambda f: [b["id"] for b in client.get("/api/books", params={"read_filter": f}).json()["items"]]
    assert 1 not in ids("read") and 1 in ids("unread")
    read_state["own"][1] = {"status": "reading", "date_read": None}  # ...then "reading"
    assert cr.effective([1])[1]["status"] == "reading" and ids("reading") == [1] and 1 not in ids("unread")
    assert client.get("/api/books/1").json()["reading_status"] == "reading"

def test_calibre_read_still_outranks_a_stale_reading_record(read_state, client):
    import app.calibre_read as cr                                    # the v1.20.8 rule must survive
    _with_read_column([(1, 1)], [(1, "2021-01-02 00:00:00+00:00")])
    read_state["own"][1] = {"status": "reading", "date_read": None}
    assert cr.effective([1]) == {1: {"status": "read", "date_read": "2021-01-02"}}
    assert [b["id"] for b in client.get("/api/books", params={"read_filter": "reading"}).json()["items"]] == []


# ── A16: someone else's finish is not mine ───────────────────────────────────
def test_currently_reading_is_personal(monkeypatch):
    import app.calibre_read as cr
    monkeypatch.setattr(cr, "library_owner_id", lambda: 1)
    monkeypatch.setattr(cr, "read_book_ids", lambda ids: {7, 8})            # shared state: 7 and 8 are "read"
    monkeypatch.setattr(cr, "others_only_logged", lambda uid, ids: {7} & set(ids))   # 7 was finished by someone else
    class PG:
        def cursor(self): return self
        def execute(self, q, p=None): self.p = p
        def fetchall(self): return [{"book_id": 9, "last": "2026-09-10"}] if self.p[0] == 2 else []
        def close(self): pass
    monkeypatch.setattr(cr, "_pg", lambda: PG())
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc).timestamp()
    assert cr.finished_for(1, {7: now, 8: now, 9: now}) == {8}              # owner: shared marks, minus other people's
    assert cr.finished_for(2, {7: now, 8: now, 9: now}) == {9}              # anyone else: their own log only
    later = datetime(2026, 12, 1, tzinfo=timezone.utc).timestamp()
    assert cr.finished_for(2, {9: later}) == set()                           # finished, then reading it again

def test_calibre_dates_are_only_the_owners_year(monkeypatch):
    src = inspect.getsource(__import__("app.routers.stats", fromlist=["x"])._finished_in_year)
    assert "library_owner_id" in src and "others_only_logged" in src


# ── A12: the delta has a second clock, and merges pending edits ──────────────
def test_delta_includes_journalled_books_and_effective_metadata(monkeypatch, client):
    import app.routers.sync as sy, app.changes as ch, app.calibre_overlay as ov
    when = datetime(2031, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(ch, "since", lambda ts, overlap_seconds=0: {1: when})
    monkeypatch.setattr(sy, "fetch_ownership_map", lambda ids: {1: {"has_digital": True, "has_physical": True, "physical_location": "Den"}})
    monkeypatch.setattr(ov, "get_edits", lambda ids: {1: {"title": "Pending Title"}})
    j = client.get("/api/sync", params={"since": "2030-06-01T00:00:00Z"}).json()   # newer than Calibre's clock
    assert [i["id"] for i in j["items"]] == [1]
    assert j["items"][0]["title"] == "Pending Title" and j["items"][0]["physical_location"] == "Den"
    monkeypatch.setattr(ch, "since", lambda ts, overlap_seconds=0: {})
    assert client.get("/api/sync", params={"since": "2030-06-01T00:00:00Z"}).json()["items"] == []

def test_delta_refuses_to_advance_past_changes_it_cannot_see(monkeypatch, client):
    import app.changes as ch
    def down(ts, overlap_seconds=0): raise RuntimeError("pg down")
    monkeypatch.setattr(ch, "since", down)
    assert client.get("/api/sync", params={"since": "2030-06-01T00:00:00Z"}).status_code == 503

def test_application_writes_are_journalled():
    import app.calibre_overlay as ov, app.calibre_read as cr, app.routers.goodreads as gr
    for fn in (ov.set_edits, ov.discard, cr.set_status, gr.set_ownership, gr._run_import, gr.undo_import):
        assert "changes.touch(" in inspect.getsource(fn), fn.__name__


# ── A04 / A13 / A15: import provenance (behaviour is covered end-to-end against
#    a real Postgres before release; these pin the statements that matter) ─────
def test_undo_never_wipes_a_whole_table():
    import app.routers.goodreads as gr
    src = " ".join(inspect.getsource(gr.undo_import).split())
    assert 'DELETE FROM book_ownership")' not in src and "DELETE FROM book_ownership WHERE" in src
    assert "native_created IS NOT FALSE" in src and "NATIVE_REFERENCE_TABLES" in src and "rollback()" in src

def test_import_is_attributed_and_idempotent():
    import app.routers.goodreads as gr
    assert "user_id" in inspect.signature(gr._run_import).parameters
    src = " ".join(inspect.getsource(gr._run_import).split())
    assert "ON CONFLICT DO NOTHING RETURNING id" not in src          # the no-op "idempotency"
    assert "owner_id) VALUES (%s, FALSE, FALSE, %s)" in src          # private shelves have an owner
    assert "has_physical=EXCLUDED.has_physical" not in src           # never flips manual ownership off

def test_native_delete_and_undo_share_one_cleanup_list():
    from app.routers.native_books import NATIVE_REFERENCE_TABLES as T
    assert {"shelf_books", "read_log", "book_ratings", "wishlist", "lending"} <= set(T)


# ── A34: one cover URL, versioned by a persisted revision ────────────────────
def test_every_serializer_uses_the_canonical_native_cover_url():
    from app.queries import native_cover_url
    assert native_cover_url("http://h", {"id": 5, "cover_rev": 3}) == "http://h/api/native/books/5/cover?v=3"
    import app.routers.shelves as sh, app.routers.books as bk
    assert 'cover_url=nb.get("cover_url")' not in inspect.getsource(sh)      # the raw manual:/provider value
    assert "native_cover_url(" in inspect.getsource(bk._native_to_summary)

def test_generated_cover_revalidates(client, monkeypatch):
    import app.routers.native_books as nb
    class PG:
        def cursor(self): return self
        def execute(self, q, p=None): pass
        def fetchone(self): return {"cover_url": None, "title": "T", "author": "A", "cover_variant": None, "categories": []}
        def close(self): pass
    monkeypatch.setattr(nb, "_pg", lambda: PG())
    r = client.get("/api/native/books/424242/cover?v=1")
    assert r.status_code == 200 and "no-cache" in r.headers["cache-control"] and r.headers["etag"]
    assert client.get("/api/native/books/424242/cover", headers={"If-None-Match": r.headers["etag"]}).status_code == 304

def test_unchanged_cover_url_does_not_destroy_the_cached_cover():
    import app.routers.native_books as nb
    src = " ".join(inspect.getsource(nb.update_native_book).split())
    assert "cover_changed" in src and src.index("conn.commit()") < src.index("os.remove(")
