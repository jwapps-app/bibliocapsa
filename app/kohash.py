"""
KOReader document hashing.

KOReader identifies a document for sync by a *partial* MD5: it reads 1024-byte
chunks at offsets `lshift(1024, 2*i)` for i = -1..10 and MD5s them together.
`lshift` is LuaJIT's bit.lshift, which masks the shift to 5 bits AND truncates
to 32 bits — so i=-1 (`1024 << -2`) becomes `1024 << 30` mod 2^32 = 0 (the file
header), and i=0..10 give 1024, 4096, 16384, … 1073741824. We must replicate
those exact semantics, otherwise our hash won't equal the one KOReader sends.
Because Bibliocapsa serves the same bytes KOReader downloads, matching the
algorithm yields the identical `document` hash — letting us tie progress to a book.

Reference: koreader/koreader frontend/util.lua  util.partialMD5().
"""

import hashlib
import logging

logger = logging.getLogger(__name__)


def _ko_offset(i: int) -> int:
    # Mirror LuaJIT bit.lshift(1024, 2*i): shift count masked to 5 bits, 32-bit result.
    return (1024 << ((2 * i) & 31)) & 0xFFFFFFFF


def partial_md5(path: str) -> str | None:
    try:
        md5 = hashlib.md5()
        with open(path, "rb") as f:
            for i in range(-1, 11):
                f.seek(_ko_offset(i))
                sample = f.read(1024)
                if not sample:
                    break
                md5.update(sample)
        return md5.hexdigest()
    except Exception as e:
        logger.warning("partial_md5 failed for %s: %s", path, e)
        return None


def record_document(book_id: int, fmt: str, path: str, book_source: str = "calibre") -> None:
    """Compute the served file's KOReader hash and map it to the book."""
    digest = partial_md5(path)
    if not digest:
        return
    try:
        from .pg_database import get_database_url
        import psycopg2
        conn = psycopg2.connect(get_database_url())
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO document_map (document, book_id, book_source, format, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (document) DO UPDATE SET
                    book_id = EXCLUDED.book_id,
                    book_source = EXCLUDED.book_source,
                    format = EXCLUDED.format,
                    updated_at = NOW()
                """,
                (digest, book_id, book_source, (fmt or "").lower()),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning("record_document failed for book %s: %s", book_id, e)
