"""
Tiny in-process TTL cache for values that are pure functions of slow-changing
inputs -- sidebar counts, tag/author/series listings, smart-shelf badges, the
KOReader statistics summary. Each of those was recomputed on every page load
although nothing they depend on had changed.

Keys should include everything the value depends on (the caller's genre
allow-list, query parameters, and a change marker such as the Calibre
database's mtime), so a stale entry is impossible rather than merely unlikely.
Single-process, bounded, unlocked: entries are replaced wholesale, which is
safe under CPython for this access pattern.
"""

import os
import time

_STORE: dict = {}
_MAX = 2000


def get_or_set(key, ttl: float, fn):
    """Return the cached value for `key` if younger than `ttl` seconds, else
    compute it with `fn()`, store, and return it. Exceptions propagate and
    nothing is cached for them."""
    now = time.monotonic()
    hit = _STORE.get(key)
    if hit is not None and now - hit[1] < ttl:
        return hit[0]
    val = fn()
    if len(_STORE) >= _MAX:
        _STORE.clear()
    _STORE[key] = (val, now)
    return val


def invalidate_prefix(prefix) -> None:
    """Drop every entry whose key (a tuple) starts with `prefix`."""
    for k in [k for k in _STORE if isinstance(k, tuple) and k[:len(prefix)] == prefix]:
        _STORE.pop(k, None)


def calibre_marker() -> tuple:
    """(mtime_ns, size) of Calibre's metadata.db -- changes whenever Calibre
    writes anything, so it is a safe change marker for library-derived values."""
    try:
        from .database import _DB_PATH
        st = os.stat(_DB_PATH)
        return (st.st_mtime_ns, st.st_size)
    except Exception:
        return (0, 0)


def allowed_key(allowed) -> tuple:
    """Hashable form of a genre allow-list (None = unrestricted)."""
    return () if allowed is None else tuple(sorted(allowed))
