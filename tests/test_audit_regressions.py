"""One regression test per confirmed audit finding. Each failed on the audited
code (v1.22.2) and passes after the fix."""
import os, types
import pytest
from tests.conftest import ADMIN, MEMBER


# ── A37: a route decorator must sit on its handler, not on a helper ──────────
def _operations():
    """{(METHOD, path): handler function name}, read from the generated OpenAPI
    so it doesn't depend on FastAPI's internal route objects (which changed
    shape between 0.115 and 0.141)."""
    from app.main import app
    out = {}
    for path, item in app.openapi()["paths"].items():
        for method, op in item.items():
            slug = path.strip("/").replace("/", "_").replace("-", "_").replace("{", "").replace("}", "")
            oid = op.get("operationId", "")
            cut = oid.rfind("_" + slug) if slug else -1
            out[(method.upper(), path)] = oid[:cut] if cut > 0 else oid
    return out


def test_no_route_is_bound_to_a_private_helper():
    bad = {k: v for k, v in _operations().items() if v.startswith("_")}
    assert not bad, f"routes bound to private helpers: {bad}"


def test_preview_shelves_is_the_registered_handler_and_admin_only(client, as_user):
    assert _operations()[("POST", "/api/goodreads/preview-shelves")] == "preview_shelves"
    as_user(MEMBER)
    r = client.post("/api/goodreads/preview-shelves", files={"file": ("g.csv", b"Title,Bookshelves\nA,owned\n", "text/csv")})
    assert r.status_code == 403
    as_user(ADMIN)
    r = client.post("/api/goodreads/preview-shelves", files={"file": ("g.csv", b"Title,Bookshelves\nA,owned\nB,owned\n", "text/csv")})
    assert r.status_code == 200 and r.json()["shelves"] == [{"name": "owned", "count": 2}]


# ── A02: sort_dir must be validated, and never reach SQL verbatim ────────────
@pytest.mark.parametrize("evil", ["asc, (SELECT 1)", "DESC; --", "asc nulls first", ""])
def test_sort_dir_rejects_anything_but_asc_desc(client, evil):
    assert client.get("/api/books", params={"sort_dir": evil}).status_code == 422


def test_format_filter_is_validated(client):
    assert client.get("/api/books", params={"format_filter": "x' OR 1=1"}).status_code == 422


def test_sort_dir_is_never_interpolated():
    src = open(os.path.join(os.path.dirname(__file__), "..", "app", "routers", "books.py")).read()
    assert "{sort_dir" not in src, "sort_dir must only be used as a key into _SQL_DIR"


# ── A01: the auth gate decides on the ROUTED path, not the Host-derived URL ──
def test_malformed_host_cannot_make_a_protected_path_look_exempt(client, as_user):
    as_user(None)
    r = client.get("/api/books", headers={"Host": "x/api/health?"})
    assert r.status_code == 401


def test_missing_user_is_never_unrestricted():
    from fastapi import HTTPException
    from app import access
    req = types.SimpleNamespace(state=types.SimpleNamespace())
    with pytest.raises(HTTPException) as e:
        access.restriction_for_request(req)
    assert e.value.status_code == 401


# ── A27: non-Latin filenames download instead of 500ing ─────────────────────
def test_non_latin_filename_downloads(client):
    r = client.get("/api/books/1/file/epub")
    assert r.status_code == 200, r.text
    cd = r.headers["content-disposition"]
    assert cd.startswith("attachment") and "filename*=" in cd.lower()
    assert client.get("/api/books/1/file/epub?inline=true").headers["content-disposition"].startswith("inline")


# ── A33: job telemetry is admin-only ─────────────────────────────────────────
@pytest.mark.parametrize("path", ["/api/native/books/enrich/status", "/api/goodreads/import/status", "/api/goodreads/import/summary"])
def test_job_status_is_admin_only(client, as_user, path):
    as_user(MEMBER)
    assert client.get(path).status_code == 403


# ── A26: a failed connection must not strand the running flag ────────────────
def test_native_enrichment_clears_running_when_the_connection_fails(monkeypatch):
    import app.routers.native_books as nb
    monkeypatch.setattr(nb, "_pg", lambda: (_ for _ in ()).throw(RuntimeError("pg down")))
    with nb._enrich_lock:
        nb._enrich_job["running"] = True
    nb._run_bulk_enrich(False, None)
    assert nb._enrich_job["running"] is False and "pg down" in nb._enrich_job.get("error", "")


# ── A10: each upload gets its own temp file ──────────────────────────────────
def test_webdav_temp_files_are_unique_per_upload(client, monkeypatch):
    import app.routers.webdav as wd
    seen, real = [], os.replace
    monkeypatch.setattr(wd.os, "replace", lambda a, b: (seen.append(a), real(a, b))[1])
    for body in (b"one", b"two"):
        assert client.put("/dav/stats.bin", content=body, headers={"Authorization": "Basic x"}).status_code in (201, 204)
    assert len(seen) == 2 and seen[0] != seen[1]
    base = os.path.join(os.environ["WEBDAV_DIR"], "admin")
    assert open(os.path.join(base, "stats.bin"), "rb").read() == b"two"
    assert not [f for f in os.listdir(base) if f.endswith(".uploading")]


# ── A06 / A05: auto-sync pushes USER edits only, and re-checks it is enabled ─
def _overlay(monkeypatch, user_edits, discarded):
    import app.calibre_overlay as ov
    monkeypatch.setattr(ov, "get_user_edits", lambda bid: dict(user_edits.get(bid, {})))
    monkeypatch.setattr(ov, "user_pending_book_ids", lambda: sorted(user_edits))
    monkeypatch.setattr(ov, "discard_if_unchanged", lambda b, f, v: discarded.append((b, f)) or True)


def test_auto_sync_never_pushes_enrichment_proposals(monkeypatch):
    import app.calibre_sync as cs
    pushed, discarded = [], []
    # book 7 has a user edit to `title`; its enrichment proposal (`comment`) is NOT a user edit
    _overlay(monkeypatch, {7: {"title": "Mine"}}, discarded)
    monkeypatch.setattr(cs, "auto_sync_enabled", lambda: True)
    monkeypatch.setattr(cs, "_existing_book_ids", lambda ids, lib: set(ids))
    monkeypatch.setattr(cs, "sync_book", lambda bid, fields, lib, **k: (pushed.append((bid, dict(fields))), (True, "ok"))[1])
    cs._auto_apply_one(7)
    assert pushed == [(7, {"title": "Mine"})]
    assert discarded == [(7, "title")]
    cs._auto_apply_one(8)                      # only proposals pending -> nothing pushed
    assert len(pushed) == 1


def test_startup_requeue_skips_books_with_only_proposals(monkeypatch):
    import app.calibre_sync as cs
    _overlay(monkeypatch, {7: {"title": "Mine"}}, [])
    monkeypatch.setattr(cs, "auto_sync_enabled", lambda: True)
    queued = []
    monkeypatch.setattr(cs, "queue_auto_sync", lambda bid: queued.append(bid))
    assert cs.requeue_pending() == 1 and queued == [7]


def test_a_job_queued_before_auto_sync_was_disabled_does_not_write(monkeypatch):
    import app.calibre_sync as cs
    _overlay(monkeypatch, {7: {"title": "Mine"}}, [])
    monkeypatch.setattr(cs, "auto_sync_enabled", lambda: False)
    monkeypatch.setattr(cs, "sync_book", lambda *a, **k: pytest.fail("wrote to Calibre while disabled"))
    cs._auto_apply_one(7)


def test_enrichment_writes_are_marked_and_cannot_replace_a_user_edit(monkeypatch):
    import app.calibre_overlay as ov
    sql = []
    class C:
        def cursor(self): return self
        def execute(self, q, p=None): sql.append((" ".join(q.split()), p))
        def commit(self): pass
        def close(self): pass
    monkeypatch.setattr(ov, "_pg", lambda: C())
    last_edit = lambda: [x for x in sql if "INTO calibre_edits" in x[0]][-1]  # (the journal write follows it)
    ov.set_edits(1, {"comment": "guess"}, origin="enrich")
    q, p = last_edit()
    assert p[3] == "enrich" and "WHERE calibre_edits.origin <> 'user'" in q
    ov.set_edits(1, {"comment": "mine"})
    q, p = last_edit()
    assert p[3] == "user" and "origin <> 'user'" not in q


# ── A35: a failed follow-up set_metadata keeps the user's title/authors ──────
def test_upload_metadata_failure_is_queued_not_dropped(monkeypatch, tmp_path):
    import app.calibre_sync as cs, app.calibre_overlay as ov
    f = tmp_path / "u.epub"; f.write_bytes(b"x")
    monkeypatch.setattr(ov, "UPLOADS_DIR", str(tmp_path))
    queued = {}
    monkeypatch.setattr(ov, "set_edits", lambda bid, fields, origin="user": queued.update({bid: fields}))
    monkeypatch.setattr(cs.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout="Added book ids: 42", stderr=""))
    monkeypatch.setattr(cs, "_run", lambda cmd: (False, "Forbidden"))
    ok, out = cs.add_upload_to_calibre({"filename": "u.epub", "title": "My Title", "authors": "A One, B Two"})
    assert ok is True, "the book exists in Calibre; the upload must not be retried"
    assert queued == {42: {"title": "My Title", "authors": ["A One", "B Two"]}}
    assert "metadata not applied" in out
