"""Import a book straight into Calibre (upload?apply=true), plus the two display
fixes that surfaced with it: Calibre's "no date" pubdate and author order."""
import io, os, sqlite3
import pytest


def _upload(client, **params):
    return client.post("/api/calibre/upload", params=params,
                       files={"file": ("My Book.epub", io.BytesIO(b"PK\x03\x04 epub"), "application/epub+zip")})


@pytest.fixture
def calibre(monkeypatch, tmp_path):
    """Stub the two Calibre subprocess calls; keep everything around them real."""
    import app.calibre_sync as cs, app.calibre_overlay as ov
    state = {"queue": {}, "next": 1, "add": (True, "Added book ids: 7", 7), "seen": []}
    monkeypatch.setattr(ov, "UPLOADS_DIR", str(tmp_path))
    monkeypatch.setattr(cs, "extract_book_metadata", lambda path: ("My Book", "Ann Author"))
    def add_upload(stored, orig, title, authors, fmt, size):
        rec = {"id": state["next"], "filename": stored, "orig_name": orig, "title": title, "authors": authors}
        state["queue"][rec["id"]] = rec; state["next"] += 1
        return rec
    def discard_upload(uid):
        rec = state["queue"].pop(uid, None)
        if rec:
            os.remove(os.path.join(str(tmp_path), rec["filename"]))
    monkeypatch.setattr(ov, "add_upload", add_upload)
    monkeypatch.setattr(ov, "discard_upload", discard_upload)
    def fake_add(rec, library=None):
        state["seen"].append(rec["id"])
        return state["add"]
    monkeypatch.setattr(cs, "_add_upload", fake_add)
    state["dir"] = tmp_path
    return state


def test_plain_upload_still_only_queues(client, calibre):
    r = _upload(client)
    assert r.status_code == 200 and "book_id" not in r.json()
    assert len(calibre["queue"]) == 1 and calibre["seen"] == []          # Calibre untouched


def test_apply_adds_now_and_returns_the_book(client, calibre):
    r = _upload(client, apply="true")
    assert r.status_code == 200, r.text
    assert r.json()["book_id"] == 7 and r.json()["applied"] is True and r.json()["duplicate"] is False
    assert calibre["queue"] == {} and os.listdir(calibre["dir"]) == []   # nothing left queued or on disk


def test_apply_failure_leaves_nothing_queued(client, calibre):
    calibre["add"] = (False, "calibredb exploded", None)
    r = _upload(client, apply="true")
    assert r.status_code == 424 and "exploded" in r.json()["detail"]         # the reason reaches the admin
    assert calibre["queue"] == {} and os.listdir(calibre["dir"]) == []   # a stray copy would be added by the next Sync
    calibre["add"] = (False, "Connection refused", None)
    assert _upload(client, apply="true").status_code == 424


def test_apply_is_admin_only(client, calibre, as_user):
    from tests.conftest import MEMBER
    as_user(MEMBER)
    assert _upload(client, apply="true").status_code == 403 and calibre["seen"] == []


def test_duplicate_resolves_to_the_existing_book_or_refuses(client, calibre, monkeypatch):
    import app.calibre_sync as cs
    calibre["add"] = (True, "The following books were not added as they already exist", None)
    monkeypatch.setattr(cs, "_find_existing_book", lambda title, authors: 42)
    r = _upload(client, apply="true")
    assert r.status_code == 200 and r.json()["book_id"] == 42 and r.json()["duplicate"] is True
    monkeypatch.setattr(cs, "_find_existing_book", lambda title, authors: None)   # ambiguous: never guess
    assert _upload(client, apply="true").status_code == 409
    assert calibre["queue"] == {}


def test_the_write_lock_is_released_and_shared(calibre):
    import app.calibre_sync as cs
    assert cs.add_upload_now({"id": 1, "filename": "x", "title": "T", "authors": "A"})["book_id"] == 7
    assert cs._calibre_write_lock.acquire(timeout=0); cs._calibre_write_lock.release()
    calibre["add"] = (False, "boom", None)
    with pytest.raises(cs.UploadNotAdded):
        cs.add_upload_now({"id": 2, "filename": "x"})
    assert cs._calibre_write_lock.acquire(timeout=0); cs._calibre_write_lock.release()


def _lib():
    return sqlite3.connect(os.environ["CALIBRE_DB_PATH"])


def test_find_existing_book_needs_title_and_author_and_uniqueness():
    import app.calibre_sync as cs
    c = _lib()
    c.executescript("""
        INSERT INTO books (id, title, sort, path) VALUES (901, 'Collected Poems', 'Collected Poems', 'x/901'), (902, 'Collected Poems', 'Collected Poems', 'x/902');
        INSERT INTO authors (id, name, sort) VALUES (901, 'Philip Larkin', 'Larkin, Philip'), (902, 'Sylvia Plath', 'Plath, Sylvia');
        INSERT INTO books_authors_link (book, author) VALUES (901, 901), (902, 902);""")
    c.commit(); c.close()
    try:
        assert cs._find_existing_book("collected poems", "Sylvia Plath") == 902
        assert cs._find_existing_book("Collected Poems", "Philip Larkin & Someone Else") == 901
        assert cs._find_existing_book("Collected Poems", "Ted Hughes") is None          # right title, wrong author
        assert cs._find_existing_book("Collected Poems", None) is None                  # two candidates, no way to choose
        assert cs._find_existing_book("???", "Sylvia Plath") is None
    finally:
        c = _lib(); c.executescript("DELETE FROM books WHERE id IN (901,902); DELETE FROM authors WHERE id IN (901,902); DELETE FROM books_authors_link WHERE book IN (901,902);"); c.commit(); c.close()


def test_undefined_pubdate_is_none_and_authors_keep_calibres_order(client):
    c = _lib()
    c.executescript("""
        INSERT INTO books (id, title, sort, path, pubdate, last_modified, timestamp) VALUES
          (911, 'No Date', 'No Date', 'x/911', '0101-01-01 00:00:00+00:00', '2030-01-01 00:00:00+00:00', '2030-01-01 00:00:00+00:00'),
          (912, 'Dated',   'Dated',   'x/912', '1999-05-04 00:00:00+00:00', '2030-01-01 00:00:00+00:00', '2030-01-01 00:00:00+00:00');
        INSERT INTO authors (id, name, sort) VALUES (911, 'Richard Heath', 'Heath, Richard'), (912, 'Michelle Chester', 'Chester, Michelle');
        INSERT INTO books_authors_link (id, book, author) VALUES (9111, 911, 911), (9112, 911, 912);""")   # Heath first, as on the cover
    c.commit(); c.close()
    try:
        one = client.get("/api/books/911").json()
        assert one["pubdate"] is None and [a["name"] for a in one["authors"]] == ["Richard Heath", "Michelle Chester"]
        assert client.get("/api/books/912").json()["pubdate"].startswith("1999-05-04")
        synced = {i["id"]: i for i in client.get("/api/sync").json()["items"]}      # the batched builder agrees
        assert synced[911]["pubdate"] is None and [a["name"] for a in synced[911]["authors"]] == ["Richard Heath", "Michelle Chester"]
        listed = {b["id"]: b for b in client.get("/api/books", params={"page_size": 100}).json()["items"]}
        assert listed[911]["pubdate"] is None and [a["name"] for a in listed[911]["authors"]][0] == "Richard Heath"
    finally:
        c = _lib(); c.executescript("DELETE FROM books WHERE id IN (911,912); DELETE FROM authors WHERE id IN (911,912); DELETE FROM books_authors_link WHERE book IN (911,912);"); c.commit(); c.close()
