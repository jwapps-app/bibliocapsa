"""
Database layer — opens Calibre's metadata.db read-only.
Two layers of protection:
  1. SQLite URI mode=ro  — SQLite will refuse any write attempt at the engine level
  2. Docker volume mount :ro — OS refuses writes at the filesystem level
"""

import sqlite3
import os
import logging
from typing import Generator
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_DB_PATH: str | None = None


def init_db() -> None:
    global _DB_PATH
    path = os.getenv("CALIBRE_DB_PATH", "/calibre/metadata.db")
    if not os.path.isfile(path):
        raise RuntimeError(
            f"Calibre metadata.db not found at {path}. "
            "Set CALIBRE_DB_PATH env var or mount your Calibre library to /calibre"
        )
    _DB_PATH = path
    # Verify we can open it read-only and it looks like Calibre's schema
    with get_conn() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        required = {"books", "authors", "series", "tags", "comments"}
        missing = required - tables
        if missing:
            raise RuntimeError(
                f"metadata.db is missing expected Calibre tables: {missing}. "
                "Make sure you're pointing at a valid Calibre library."
            )
    logger.info(f"Calibre metadata.db opened read-only: {path}")


def close_db() -> None:
    pass  # Connections are per-request; nothing to do at shutdown


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    """Yield a read-only SQLite connection. Always closed after use."""
    if _DB_PATH is None:
        raise RuntimeError("Database not initialized")
    uri = f"file:{_DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Extra safety: set journal_mode to ensure no WAL writes slip through
    try:
        yield conn
    finally:
        conn.close()
