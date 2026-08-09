"""
Sync the pending edit overlay (Postgres `calibre_edits`) to the Calibre library
via the `calibredb` CLI — the deliberate, confirmed "Sync to Calibre" action.

We use calibredb (not direct metadata.db writes) so all of Calibre's bookkeeping
(linked tables, metadata.opf, author_sort, triggers, folder structure) stays
correct. Each pending field maps to a `calibredb set_metadata --field` value.
calibredb is invoked with an argv list (no shell), so values with spaces/special
characters need no quoting.
"""

import os
import re
import logging
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

LIBRARY = os.getenv("CALIBRE_LIBRARY_PATH", "/calibre")
CALIBREDB = os.getenv("CALIBREDB_BIN", "calibredb")
EBOOK_META = os.getenv("EBOOK_META_BIN", "ebook-meta")

# ── Optional: write through a running Calibre Content server ─────────────────
# By default calibredb writes straight to the library folder, which is only safe
# when the Calibre GUI is closed (an open GUI holds the library and its in-memory
# state would diverge from the file). If a server URL is configured, calibredb is
# pointed at that instead — the running Calibre owns the library and serializes
# the write, so it can stay open.
#
# This changes ONLY the write path. Every read (metadata.db, covers, book files,
# the search index) still comes straight off the filesystem, so the library must
# remain mounted either way. Blank URL = today's behaviour, unchanged.
SETTING_SERVER_URL = "calibre_server_url"
SETTING_SERVER_USER = "calibre_server_user"
SETTING_SERVER_PASSWORD = "calibre_server_password"


def server_config() -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(url, username, password) for the Calibre content server; url None = off."""
    try:
        from .routers.settings import get_setting
        url = (get_setting(SETTING_SERVER_URL) or "").strip()
        if not url:
            return None, None, None
        return url, (get_setting(SETTING_SERVER_USER) or "").strip() or None, \
               get_setting(SETTING_SERVER_PASSWORD) or None
    except Exception:
        return None, None, None


def _target_args(library: str = LIBRARY) -> list[str]:
    """The `--with-library` (and auth) arguments for a calibredb invocation:
    the content-server URL when configured, else the library path."""
    url, user, password = server_config()
    if not url:
        return ["--with-library", library]
    args = ["--with-library", url]
    if user:
        args += ["--username", user]
        if password:
            args += ["--password", password]
    return args


def _explain(out: str) -> str:
    """Add a hint when a failure looks like a server/config problem rather than a
    problem with the book itself — 'Forbidden' in particular is what the content
    server returns when it's running but wasn't started with writes enabled."""
    url, _, _ = server_config()
    if not url:
        return out
    low = (out or "").lower()
    if "forbidden" in low:
        return (f"{out}\n(The Calibre server at {url} refused the write. Start it with "
                f"--enable-local-write, or with authentication and a user that has write access.)")
    if any(k in low for k in ("connection refused", "could not connect", "timed out",
                              "name or service not known", "failed to establish")):
        return f"{out}\n(Could not reach the Calibre server at {url}. Is it running?)"
    if "unauthorized" in low or "401" in low:
        return f"{out}\n(The Calibre server at {url} rejected the credentials.)"
    return out


def extract_book_metadata(path: str) -> tuple[Optional[str], Optional[str]]:
    """Read Title / Author(s) from a book file via Calibre's `ebook-meta`."""
    title, authors = None, None
    try:
        proc = subprocess.run([EBOOK_META, path], capture_output=True, text=True, timeout=60)
        for line in proc.stdout.splitlines():
            k, sep, v = line.partition(":")
            if not sep:
                continue
            k, v = k.strip(), v.strip()
            if k == "Title":
                title = v or None
            elif k.startswith("Author"):
                authors = (v.split("[")[0].strip() or None)  # drop the sort form in [..]
    except Exception as e:
        logger.warning("ebook-meta failed for %s: %s", path, e)
    return title, authors


def _field_args(fields: dict) -> list[str]:
    """Map overlay fields → calibredb `--field name:value` arguments."""
    args: list[str] = []

    def add(name: str, value: str):
        args.extend(["--field", f"{name}:{value}"])

    if "title" in fields and fields["title"]:
        add("title", str(fields["title"]))
    if isinstance(fields.get("authors"), list) and fields["authors"]:
        add("authors", " & ".join(fields["authors"]))  # calibre separates authors with &
    if "comment" in fields:
        add("comments", str(fields["comment"] or ""))
    if "publisher" in fields:
        add("publisher", str(fields["publisher"] or ""))
    if "pubdate" in fields and fields["pubdate"]:
        add("pubdate", str(fields["pubdate"]))
    if "series" in fields:
        add("series", str(fields["series"] or ""))
    if fields.get("series_index") is not None:
        add("series_index", str(fields["series_index"]))
    if isinstance(fields.get("tags"), list):
        add("tags", ",".join(fields["tags"]))
    if fields.get("rating") is not None:
        # Calibre stores rating 0–10 (5 stars × 2); overlay stores 0–5.
        add("rating", str(int(round(float(fields["rating"]) * 2))))
    if fields.get("isbn"):
        add("identifiers", f"isbn:{fields['isbn']}")
    return args


def _run(cmd: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if proc.returncode != 0:
            return False, (proc.stderr or proc.stdout or "calibredb failed").strip()
        return True, (proc.stdout or "ok").strip()
    except Exception as e:
        return False, str(e)


def _valid_custom_labels(library: str) -> Optional[set]:
    """Current custom-column labels in the target library, or None if unreadable
    (in which case we don't filter)."""
    import sqlite3
    db = os.path.join(library, "metadata.db")
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return {r[0] for r in conn.execute("SELECT label FROM custom_columns").fetchall()}
        finally:
            conn.close()
    except Exception:
        return None


def _existing_book_ids(ids, library: str) -> set:
    """Which of `ids` still exist in the target library. If the DB is unreadable,
    assume all exist (don't drop anything — let the normal sync attempt run)."""
    ids = [int(i) for i in ids]
    if not ids:
        return set()
    import sqlite3
    db = os.path.join(library, "metadata.db")
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            out = set()
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                ph = ",".join("?" * len(chunk))
                out |= {r[0] for r in conn.execute(f"SELECT id FROM books WHERE id IN ({ph})", chunk).fetchall()}
            return out
        finally:
            conn.close()
    except Exception:
        return set(ids)


def _format_custom(val) -> str:
    if val is None:
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, list):
        return ",".join(str(x) for x in val)
    return str(val)


def sync_book(book_id: int, fields: dict, library: str = LIBRARY) -> tuple[bool, str]:
    """Apply one book's pending edits via calibredb. Standard fields go through
    set_metadata; custom columns (`custom:<label>`) through set_custom."""
    std = {k: v for k, v in fields.items() if not k.startswith("custom:")}
    custom = {k[len("custom:"):]: v for k, v in fields.items() if k.startswith("custom:")}
    outputs = []

    field_args = _field_args(std)
    if field_args:
        ok, out = _run([CALIBREDB, "set_metadata", str(book_id), *field_args, *_target_args(library)])
        if not ok:
            return False, _explain(out)
        outputs.append(out)

    valid_labels = _valid_custom_labels(library)
    for label, val in custom.items():
        # Skip edits for columns deleted/renamed in Calibre — don't fail the book.
        if valid_labels is not None and label not in valid_labels:
            outputs.append(f"skipped #{label} (no such column)")
            continue
        ok, out = _run([CALIBREDB, "set_custom", label, str(book_id), _format_custom(val), *_target_args(library)])
        if not ok:
            return False, _explain(out)
        outputs.append(out)

    return True, (" | ".join(outputs) or "no-op")


def add_upload_to_calibre(rec: dict, library: str = LIBRARY) -> tuple[bool, str]:
    """Import a pending uploaded file into Calibre via `calibredb add`, then apply
    any user-entered title/authors. Returns (ok, output)."""
    from . import calibre_overlay as overlay
    path = os.path.join(overlay.UPLOADS_DIR, rec["filename"])
    if not os.path.isfile(path):
        return False, "uploaded file missing"
    try:
        proc = subprocess.run([CALIBREDB, "add", path, *_target_args(library)],
                              capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            return False, _explain((proc.stderr or proc.stdout or "calibredb add failed").strip())
        out = (proc.stdout or "").strip()
        m = re.search(r"Added book ids?:\s*([0-9,]+)", out)
        new_id = m.group(1).split(",")[0] if m else None
        # Apply user-edited title/authors on top of what was embedded in the file.
        if new_id and (rec.get("title") or rec.get("authors")):
            fields = []
            if rec.get("title"):
                fields += ["--field", f"title:{rec['title']}"]
            if rec.get("authors"):
                fields += ["--field", f"authors:{rec['authors'].replace(',', ' & ')}"]
            if fields:
                subprocess.run([CALIBREDB, "set_metadata", new_id, *fields, *_target_args(library)],
                               capture_output=True, text=True, timeout=120)
        return True, out
    except Exception as e:
        return False, str(e)


def run_sync(library: str = LIBRARY) -> dict:
    """Apply all pending edits AND import all pending uploads. Successful items
    are cleared from the overlay/upload queue."""
    from . import calibre_overlay as overlay
    synced, added, dropped, failed = 0, 0, 0, []

    # Calibre's FTS db uses a rollback journal, so a background index rebuild
    # holding it open blocks calibredb from writing (it surfaces as an opaque
    # "fts_db is already in use" / "database is locked"). Ask the indexer to
    # stand down for the duration of the sync.
    try:
        from . import search_index
        search_index.pause_for_calibre_write()
    except Exception:
        search_index = None

    try:
        return _run_sync(library)
    finally:
        if search_index is not None:
            try:
                search_index.resume_after_calibre_write()
            except Exception:
                pass


def _run_sync(library: str) -> dict:
    from . import calibre_overlay as overlay
    synced, added, dropped, failed = 0, 0, 0, []

    items = overlay.pending()
    existing = _existing_book_ids([it["book_id"] for it in items], library)
    for item in items:
        bid = item["book_id"]
        if bid not in existing:
            # The book was removed from Calibre — its edit can never apply, so
            # drop it instead of failing forever. Clears orphaned edits (e.g. a
            # reading-progress edit from a deleted/never-synced book) that would
            # otherwise reappear as a permanent "1 failed" on every sync.
            overlay.discard(bid)
            dropped += 1
            logger.info("Dropped pending edit for book %s (no longer in Calibre)", bid)
            continue
        ok, out = sync_book(bid, item["fields"], library)
        if ok:
            overlay.discard(bid)
            synced += 1
        else:
            logger.warning("Calibre sync failed for book %s: %s", bid, out)
            failed.append({"book_id": bid, "error": out})

    for up in overlay.list_uploads():
        ok, out = add_upload_to_calibre(up, library)
        if ok:
            overlay.discard_upload(up["id"])
            added += 1
        else:
            logger.warning("Calibre add failed for upload %s: %s", up["id"], out)
            failed.append({"upload_id": up["id"], "error": out})

    return {"synced": synced, "added": added, "dropped": dropped, "failed": failed, "remaining": len(failed)}
