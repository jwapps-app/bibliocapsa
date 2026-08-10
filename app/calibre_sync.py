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
import queue
import logging
import threading
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


# ── Optional: apply edits to Calibre as they're saved ────────────────────────
# Off by default, in which case edits accumulate until the deliberate "Sync to
# Calibre" action, exactly as before. When on, a deliberate edit is pushed to
# Calibre in the background the moment it's saved.
#
# Two properties make this safe to leave on:
#   * A failed auto-apply changes nothing. The edit stays in the overlay, so the
#     manual Sync button remains the backstop and no edit is ever lost.
#   * Writes are serialized through one worker thread. calibredb invocations
#     never overlap each other, and each one pauses the search indexer the same
#     way a manual sync does.
#
# Enrichment proposals deliberately do NOT auto-apply — those are queued for you
# to review on the Sync page, and applying them silently would remove the review.
SETTING_AUTO_SYNC = "calibre_auto_sync"

_auto_q: "queue.Queue[int]" = queue.Queue()
_auto_worker: Optional[threading.Thread] = None
_auto_lock = threading.Lock()

# Serializes ALL Calibre writes in this process — the manual Sync and the
# auto-sync worker share it. They genuinely overlap: pressing Sync first queues
# reading updates (which enqueues auto-sync jobs), then runs the manual sync
# over those same books. Without the lock both would write the same edits
# concurrently; with it, whoever runs second finds the fields already applied
# and discarded, and no-ops.
_calibre_write_lock = threading.Lock()


def _discard_applied(book_id: int, pushed: dict) -> None:
    """Clear pushed fields from the overlay — but only those whose pending value
    is STILL the value we wrote. If the user re-edited a field while calibredb
    was in flight, the newer value must survive to be synced, not be discarded
    on the strength of the older write."""
    from . import calibre_overlay as overlay
    current = (overlay.get_edits([book_id]) or {}).get(book_id) or {}
    for field, value in pushed.items():
        if field in current and current[field] == value:
            overlay.discard(book_id, field)


def auto_sync_enabled() -> bool:
    """Whether a saved edit should be pushed to Calibre immediately. Default off.

    Requires a configured content server, and deliberately re-checks that here
    rather than trusting the stored flag. A manual sync is something you time —
    you close Calibre, then press the button. Auto-sync fires on its own (a
    KOReader sync at 3am will do it), so writing straight to the library folder
    could land while Calibre has the library open. Gating on the server means
    clearing the URL disables auto-sync immediately, with no window where the
    flag is still on but the safe write path is gone."""
    try:
        from .routers.settings import get_setting
        if not (get_setting(SETTING_AUTO_SYNC) or "").strip().lower() in ("1", "true", "yes"):
            return False
        url, _, _ = server_config()
        return bool(url)
    except Exception:
        return False


def queue_auto_sync(book_id: int) -> None:
    """Ask for one book's pending edits to be applied to Calibre in the background.

    Cheap and never raises: the caller is a request handler that has already
    saved the edit, and auto-apply must not be able to fail that request."""
    try:
        if not auto_sync_enabled():
            return
        _ensure_auto_worker()
        _auto_q.put(int(book_id))
    except Exception:
        logger.debug("auto-sync enqueue failed for book %s", book_id, exc_info=True)


def _ensure_auto_worker() -> None:
    global _auto_worker
    with _auto_lock:
        if _auto_worker is None or not _auto_worker.is_alive():
            _auto_worker = threading.Thread(target=_auto_loop, name="calibre-auto-sync", daemon=True)
            _auto_worker.start()


def _auto_loop() -> None:
    while True:
        book_id = _auto_q.get()
        taken = 1  # every item taken needs its own task_done(), or join() hangs
        try:
            # Coalesce: a burst of edits to the same book (the editor patches
            # field by field) should be one calibredb call, not one per field.
            pending_ids = {book_id}
            while True:
                try:
                    pending_ids.add(_auto_q.get_nowait())
                    taken += 1
                except queue.Empty:
                    break
            for bid in sorted(pending_ids):
                _auto_apply_one(bid)
        except Exception:
            logger.warning("auto-sync worker error", exc_info=True)
        finally:
            for _ in range(taken):
                _auto_q.task_done()


def _auto_apply_one(book_id: int) -> None:
    """Apply one book's pending edits. On any failure the edit is left in the
    overlay for the manual sync — auto-apply only ever removes work, never data."""
    from . import calibre_overlay as overlay
    with _calibre_write_lock:
        # Re-read INSIDE the lock: if a manual sync just applied this book,
        # nothing is pending any more and this is a no-op instead of a rewrite.
        fields = (overlay.get_edits([book_id]) or {}).get(book_id) or {}
        if not fields:
            return
        if not _existing_book_ids([book_id], LIBRARY):
            return  # gone from Calibre; the manual sync path handles dropping it

        try:
            from . import search_index
            search_index.pause_for_calibre_write()
        except Exception:
            search_index = None
        try:
            ok, out = sync_book(book_id, fields, LIBRARY)
        except Exception as e:
            ok, out = False, str(e)
        finally:
            if search_index is not None:
                try:
                    search_index.resume_after_calibre_write()
                except Exception:
                    pass

    if ok:
        _discard_applied(book_id, fields)
        logger.info("Auto-synced book %s to Calibre (%s)", book_id, ", ".join(sorted(fields)))
    else:
        logger.warning("Auto-sync failed for book %s (left pending for manual sync): %s", book_id, out)


def run_sync(library: str = LIBRARY) -> dict:
    """Apply all pending edits AND import all pending uploads. Successful items
    are cleared from the overlay/upload queue."""
    from . import calibre_overlay as overlay
    synced, added, dropped, failed = 0, 0, 0, []

    # Calibre's FTS db uses a rollback journal, so a background index rebuild
    # holding it open blocks calibredb from writing (it surfaces as an opaque
    # "fts_db is already in use" / "database is locked"). Ask the indexer to
    # stand down for the duration of the sync. The write lock keeps the
    # auto-sync worker out for the same span — same lock-then-pause order as
    # _auto_apply_one.
    with _calibre_write_lock:
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
            # Value-aware, like the auto path: a field re-edited while this
            # book's calibredb call was in flight keeps its newer pending value
            # instead of being dropped by a blanket per-book discard.
            _discard_applied(bid, item["fields"])
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
