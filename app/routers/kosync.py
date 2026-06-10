"""
KOReader sync server (the "KOSync" protocol), implemented natively on
PostgreSQL — replaces the abandoned koreader/kosync:latest container.

Mounted at the application ROOT (no /api prefix) so KOReader's "Custom sync
server" can point at the same base URL as the rest of Bibliocapsa, e.g.
https://bibliocapsa.example/ — the Next.js front-end also rewrites
/healthcheck, /users/* and /syncs/* to this backend so the public origin
serves them too.

Protocol reference: https://github.com/koreader/koreader-sync-server
KOReader hashes the password with MD5 client-side before sending it as both
the registration `password` and the `x-auth-key` header, so we simply store
and compare that hash — the server never handles a plaintext password.
"""

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import time
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


def _pg():
    from ..pg_database import get_database_url
    import psycopg2
    from psycopg2.extras import RealDictCursor
    return psycopg2.connect(get_database_url(), cursor_factory=RealDictCursor)


def _err(status: int, code: int, message: str) -> JSONResponse:
    """KOSync-style error body: {"code": <int>, "message": <str>}."""
    return JSONResponse(status_code=status, content={"code": code, "message": message})


def _check_auth(username: Optional[str], key: Optional[str]) -> bool:
    """KOReader sends md5(password) as x-auth-key; compare it to the shared
    `kosync_key` on the unified users account (case-insensitive username)."""
    if not username or not key:
        return False
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT kosync_key FROM users WHERE LOWER(username) = LOWER(%s)",
            (username,),
        )
        row = cur.fetchone()
        import hmac
        return bool(row) and row["kosync_key"] is not None and hmac.compare_digest(str(row["kosync_key"]), str(key))
    finally:
        conn.close()


# ── Health ──────────────────────────────────────────────────────────────────
@router.get("/healthcheck", tags=["KOSync"], summary="KOReader sync healthcheck")
def healthcheck():
    return {"state": "OK"}


# ── User accounts ─────────────────────────────────────────────────────────────
class UserCreate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None  # MD5 hash from the client


@router.post("/users/create", tags=["KOSync"], summary="(Disabled) register a KOReader sync account")
def users_create(body: UserCreate):
    # Accounts are unified with Bibliocapsa and created in the web app (so the
    # same password can be hashed strongly for web login). KOReader only ever
    # sends md5(password), which can't seed a web password — so we refuse here
    # and direct the user to register in Bibliocapsa, then *Login* in KOReader.
    return _err(403, 2005, "Create your account in Bibliocapsa, then log in here with the same username and password.")


@router.get("/users/auth", tags=["KOSync"], summary="Verify KOReader sync credentials")
def users_auth(
    x_auth_user: Optional[str] = Header(None),
    x_auth_key: Optional[str] = Header(None),
):
    if not _check_auth(x_auth_user, x_auth_key):
        return _err(401, 2001, "Unauthorized")
    return {"authorized": "OK"}


# ── Reading progress ──────────────────────────────────────────────────────────
class ProgressBody(BaseModel):
    document: Optional[str] = None
    progress: Optional[str] = None
    percentage: Optional[float] = None
    device: Optional[str] = None
    device_id: Optional[str] = None


@router.put("/syncs/progress", tags=["KOSync"], summary="Upload reading progress")
def put_progress(
    body: ProgressBody,
    x_auth_user: Optional[str] = Header(None),
    x_auth_key: Optional[str] = Header(None),
):
    if not _check_auth(x_auth_user, x_auth_key):
        return _err(401, 2001, "Unauthorized")
    if not body.document:
        return _err(400, 2003, "Invalid request")

    ts = int(time.time())
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO kosync_progress
                (username, document, progress, percentage, device, device_id, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, to_timestamp(%s))
            ON CONFLICT (username, document) DO UPDATE SET
                progress    = EXCLUDED.progress,
                percentage  = EXCLUDED.percentage,
                device      = EXCLUDED.device,
                device_id   = EXCLUDED.device_id,
                updated_at  = EXCLUDED.updated_at
            """,
            (x_auth_user, body.document, body.progress, body.percentage,
             body.device, body.device_id, ts),
        )
        conn.commit()
    finally:
        conn.close()
    return {"document": body.document, "timestamp": ts}


@router.get("/syncs/progress/{document}", tags=["KOSync"], summary="Fetch reading progress")
def get_progress(
    document: str,
    x_auth_user: Optional[str] = Header(None),
    x_auth_key: Optional[str] = Header(None),
):
    if not _check_auth(x_auth_user, x_auth_key):
        return _err(401, 2001, "Unauthorized")
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT document, progress, percentage, device, device_id,
                   EXTRACT(EPOCH FROM updated_at)::bigint AS timestamp
            FROM kosync_progress
            WHERE username = %s AND document = %s
            """,
            (x_auth_user, document),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return {}  # KOReader treats an empty object as "no saved progress"
    return {
        "document": row["document"],
        "progress": row["progress"],
        "percentage": row["percentage"],
        "device": row["device"],
        "device_id": row["device_id"],
        "timestamp": row["timestamp"],
    }
