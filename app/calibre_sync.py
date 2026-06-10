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
        ok, out = _run([CALIBREDB, "set_metadata", str(book_id), *field_args, "--with-library", library])
        if not ok:
            return False, out
        outputs.append(out)

    valid_labels = _valid_custom_labels(library)
    for label, val in custom.items():
        # Skip edits for columns deleted/renamed in Calibre — don't fail the book.
        if valid_labels is not None and label not in valid_labels:
            outputs.append(f"skipped #{label} (no such column)")
            continue
        ok, out = _run([CALIBREDB, "set_custom", label, str(book_id), _format_custom(val), "--with-library", library])
        if not ok:
            return False, out
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
        proc = subprocess.run([CALIBREDB, "add", path, "--with-library", library],
                              capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            return False, (proc.stderr or proc.stdout or "calibredb add failed").strip()
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
                subprocess.run([CALIBREDB, "set_metadata", new_id, *fields, "--with-library", library],
                               capture_output=True, text=True, timeout=120)
        return True, out
    except Exception as e:
        return False, str(e)


def run_sync(library: str = LIBRARY) -> dict:
    """Apply all pending edits AND import all pending uploads. Successful items
    are cleared from the overlay/upload queue."""
    from . import calibre_overlay as overlay
    synced, added, failed = 0, 0, []

    for item in overlay.pending():
        ok, out = sync_book(item["book_id"], item["fields"], library)
        if ok:
            overlay.discard(item["book_id"])
            synced += 1
        else:
            logger.warning("Calibre sync failed for book %s: %s", item["book_id"], out)
            failed.append({"book_id": item["book_id"], "error": out})

    for up in overlay.list_uploads():
        ok, out = add_upload_to_calibre(up, library)
        if ok:
            overlay.discard_upload(up["id"])
            added += 1
        else:
            logger.warning("Calibre add failed for upload %s: %s", up["id"], out)
            failed.append({"upload_id": up["id"], "error": out})

    return {"synced": synced, "added": added, "failed": failed, "remaining": len(failed)}
