"""Second batch of audit regressions (A05a A08 A09 A11 A17 A19 A20 A28 A29 A30 A39 A43)."""
import os, sqlite3, types, threading
import pytest


# ── A19 + identifier wipe ────────────────────────────────────────────────────
def _pairs(args): return dict(a.split(":", 1) for a in args[1::2])

def test_explicit_clears_produce_operations():
    from app.calibre_sync import _field_args
    got = _pairs(_field_args({"rating": None, "pubdate": None, "series": None, "series_index": None, "isbn": None},
                             identifiers={"isbn": "978", "goodreads": "55"}))
    assert got == {"rating": "0", "pubdate": "", "series": "", "series_index": "1", "identifiers": "goodreads:55"}

def test_absent_fields_produce_nothing():
    from app.calibre_sync import _field_args
    assert _field_args({}) == []

def test_editing_isbn_keeps_the_other_identifiers():
    from app.calibre_sync import _field_args
    got = _pairs(_field_args({"isbn": "9781111111111"}, identifiers={"isbn": "old", "goodreads": "55", "amazon": "B0"}))
    assert set(got["identifiers"].split(",")) == {"isbn:9781111111111", "goodreads:55", "amazon:B0"}


# ── A05a: an unreadable settings store must not become "write to the folder" ─
def test_unreadable_settings_refuse_to_pick_a_write_target(monkeypatch):
    import app.calibre_sync as cs, app.routers.settings as st
    monkeypatch.setattr(st, "settings_readable", lambda key: False)
    with pytest.raises(cs.TargetUnknown):
        cs._target_args("/calibre")
    ran = []
    monkeypatch.setattr(cs, "_run", lambda cmd: ran.append(cmd) or (True, "ok"))
    ok, out = cs.sync_book(1, {"title": "X"}, "/calibre")
    assert ok is False and not ran and "nothing was written" in out

def test_readable_settings_with_no_server_still_use_the_folder(monkeypatch):
    import app.calibre_sync as cs, app.routers.settings as st
    monkeypatch.setattr(st, "settings_readable", lambda key: True)
    monkeypatch.setattr(st, "get_setting", lambda key: None)
    assert cs._target_args("/calibre") == ["--with-library", "/calibre"]


# ── A08 (native): a book that already has a cover is never re-downloaded ─────
def test_enrichment_does_not_overwrite_an_existing_cover(monkeypatch):
    import app.routers.native_books as nb, app.metadata as md
    wrote = []
    monkeypatch.setattr(nb, "_cache_cover", lambda *a: wrote.append(a))
    monkeypatch.setattr(md, "fetch_metadata", lambda *a, **k: types.SimpleNamespace(
        cover_url="http://x/c.jpg", description="d", page_count=1, publisher="p", published_date="2020", rating=None, source="ol"))
    monkeypatch.setattr(md, "download_cover", lambda url: (b"NEW", "image/jpeg"))
    class Cur:
        def execute(self, q, p=None): self.q = q
        def fetchone(self): return {"cover_url": "manual:9"}
    nb._enrich_one(Cur(), {"id": 9, "isbn": None, "isbn13": None}, None)
    assert wrote == [], "a manual cover's bytes were overwritten"


# ── A09: a forged X-Forwarded-For can't make a public socket look local ──────
def _req(peer, headers=None):
    return types.SimpleNamespace(client=types.SimpleNamespace(host=peer), headers={k.lower(): v for k, v in (headers or {}).items()})

def test_bootstrap_locality_trusts_the_socket_first():
    from app.routers.auth import _is_local_client
    assert _is_local_client(_req("8.8.8.8", {"X-Forwarded-For": "127.0.0.1"})) is False       # exposed backend, forged header
    assert _is_local_client(_req("172.18.0.3", {"X-Forwarded-For": "192.168.1.20"})) is True   # behind Caddy, LAN client
    assert _is_local_client(_req("172.18.0.3", {"X-Forwarded-For": "8.8.8.8"})) is False       # behind Caddy, internet client
    assert _is_local_client(_req("172.18.0.3", {"X-Forwarded-For": "192.168.1.20", "CF-Connecting-IP": "8.8.8.8"})) is False


# ── A11: a sync page never ends mid-second ───────────────────────────────────
def test_limited_sync_does_not_skip_books_sharing_a_second(client):
    lib = os.environ["CALIBRE_DB_PATH"]
    c = sqlite3.connect(lib)
    c.execute("UPDATE books SET last_modified='2026-01-01 10:00:00.100000+00:00' WHERE id=1")
    for bid, frac in ((2, "10:00:05.100000"), (3, "10:00:05.900000"), (4, "10:00:09.000000")):
        c.execute("INSERT OR REPLACE INTO books (id, title, sort, path, last_modified) VALUES (?,?,?,?,?)",
                  (bid, f"B{bid}", f"B{bid}", f"p/{bid}", f"2026-01-01 {frac}+00:00"))
    c.commit(); c.close()
    from app import ttlcache; ttlcache._STORE.clear()
    seen, since = [], None
    for _ in range(6):
        r = client.get("/api/sync", params={"limit": 2, **({"since": since} if since else {})}).json()
        seen += [b["id"] for b in r["items"]]
        if not r["items"] or since == r["until"]: break
        since = r["until"]
    assert sorted(set(seen)) == [1, 2, 3, 4], f"books skipped at a same-second boundary: {sorted(set(seen))}"


# ── A17: a reread in the same year is a second completion ────────────────────
def test_rereads_count_and_a_double_recorded_finish_counts_once(monkeypatch):
    import app.routers.stats as st, app.access as access
    monkeypatch.setattr(access, "get_restriction", lambda u: None)
    rows = [{"book_id": 5, "book_source": "calibre", "date_read": "2026-02-01"},
            {"book_id": 5, "book_source": "calibre", "date_read": "2026-09-01"},   # the reread
            {"book_id": 8, "book_source": "native",  "date_read": "2026-03-03"}]
    class PG:
        def cursor(self): return self
        def execute(self, *a): pass
        def fetchall(self): return rows
        def close(self): pass
    import app.routers.settings as settings
    monkeypatch.setattr(settings, "_pg", lambda: PG())
    monkeypatch.setattr(settings, "get_setting", lambda k: None)   # no Calibre date column mapped
    ev = st._finished_in_year({"id": 1, "role": "admin"}, 2026)
    assert len(ev) == 3, ev


# ── A20: results beyond the old 500-row window ───────────────────────────────
def test_search_pages_past_500(monkeypatch, tmp_path):
    import app.search_index as si
    idx = tmp_path / "fts.db"; monkeypatch.setattr(si, "INDEX_PATH", str(idx))
    conn = si._connect(); si._ensure_docs(conn)
    for i in range(1, 521):
        conn.execute("INSERT INTO docs (rowid, searchable_text) VALUES (?, ?)", (i, "whale " * (1 + i % 3)))
        conn.execute("INSERT INTO doc_meta (rowid_ref, book, format) VALUES (?,?,?)", (i, i, "EPUB"))
    conn.commit(); conn.close()
    monkeypatch.setattr(si, "_sql_excerpt", lambda *a, **k: "")
    monkeypatch.setattr(si.sqlite3, "connect", (lambda real: lambda *a, **k: real(str(idx)) if "mode=ro" in str(a[0]) and "fts.db" not in str(a[0]) else real(*a, **k))(si.sqlite3.connect))
    total, hits = si.search("whale", None, limit=10, offset=505)
    assert total == 520 and len(hits) == 10


# ── A28: progress is stored under the account's canonical username ───────────
def test_kosync_progress_uses_the_canonical_username(client, monkeypatch):
    import app.routers.kosync as ko
    monkeypatch.setattr(ko, "_check_auth", lambda request, u, k: True)
    monkeypatch.setattr(ko, "_canonical", lambda u: "alice")
    wrote = []
    class PG:
        def cursor(self): return self
        def execute(self, q, p=None): wrote.append(p)
        def commit(self): pass
        def close(self): pass
    monkeypatch.setattr(ko, "_pg", lambda: PG())
    r = client.put("/syncs/progress", json={"document": "d1", "percentage": 0.5},
                   headers={"x-auth-user": "ALICE", "x-auth-key": "k"})
    assert r.status_code == 200 and wrote[-1][0] == "alice"


# ── A29: reserved characters in the DB password ──────────────────────────────
def test_database_url_escapes_credentials(monkeypatch):
    from urllib.parse import urlparse, unquote
    import app.pg_database as pg
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss?w#rd/%")
    monkeypatch.setenv("POSTGRES_HOST", "db")
    u = urlparse(pg.get_database_url())
    assert u.hostname == "db" and unquote(u.password) == "p@ss?w#rd/%" and "connect_timeout=5" in u.query


# ── A30: checks allocate nothing; the global count is not a lockout ──────────
def test_throttle_checks_do_not_grow_state_and_global_failures_do_not_lock_out_real_users():
    import app.auth as auth
    auth._basic_fail.clear()
    for i in range(3000):
        auth._basic_throttled(f"u{i}|9.9.9.{i % 250}", f"9.9.9.{i % 250}")
    assert len(auth._basic_fail) == 0
    for i in range(auth._BASIC_FAIL_MAX_GLOBAL + 5):
        auth._note_basic_failure(f"x{i}|10.{i % 200}.0.1", f"10.{i % 200}.0.1")
    assert auth.under_attack() is True
    assert auth._basic_throttled("alice|192.168.1.5", "192.168.1.5") is False
    auth._basic_fail.clear()

def test_rejected_requests_do_not_grow_a_rate_limit_bucket():
    from fastapi import HTTPException
    import app.ratelimit as rl
    rl._BUCKETS.clear()
    for _ in range(5): rl.check("k", limit=5, window=60)
    for _ in range(50):
        with pytest.raises(HTTPException): rl.check("k", limit=5, window=60)
    assert len(rl._BUCKETS["k"]) == 5


# ── A39: overflow connections are bounded ────────────────────────────────────
def test_overflow_connections_have_a_budget(monkeypatch):
    import app.pg_database as pg
    n = pg._overflow._initial_value
    held = [pg._overflow.acquire(blocking=False) for _ in range(n)]
    assert all(held) and pg._overflow.acquire(blocking=False) is False
    for _ in held: pg._overflow.release()


# ── A43: bearer sessions are recognised as "the current session" ─────────────
def test_session_token_reads_cookie_then_bearer():
    import app.auth as auth
    r = types.SimpleNamespace(cookies={}, headers={"authorization": "Bearer abc"})
    assert auth.session_token(r) == "abc"
    r = types.SimpleNamespace(cookies={auth.SESSION_COOKIE: "cook"}, headers={"authorization": "Bearer abc"})
    assert auth.session_token(r) == "cook"
