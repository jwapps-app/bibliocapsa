"""
Tiny in-memory sliding-window rate limiter for a single-instance self-host.
Used to throttle expensive endpoints (full-text search, external metadata
lookups) so one client can't hammer them or burn external API quota.
"""

import time
from fastapi import Request, HTTPException

_BUCKETS: dict[str, list] = {}


def check(key: str, limit: int, window: int = 60) -> None:
    """Allow `limit` hits per `window` seconds for `key`; else raise 429."""
    now = time.time()
    bucket = [t for t in _BUCKETS.get(key, []) if now - t < window]
    bucket.append(now)
    _BUCKETS[key] = bucket
    if len(_BUCKETS) > 5000:  # crude cap so the dict can't grow unbounded
        for k in [k for k, v in _BUCKETS.items() if not v or now - v[-1] > window]:
            _BUCKETS.pop(k, None)
    if len(bucket) > limit:
        raise HTTPException(status_code=429, detail="Too many requests — please slow down.")


def client_key(request: Request, name: str) -> str:
    """A per-user (or per-IP, if unauthenticated) bucket key for `name`."""
    user = getattr(request.state, "user", None)
    who = (user or {}).get("id") if user else None
    if who is None:
        who = request.client.host if request.client else "?"
    return f"{name}:{who}"
