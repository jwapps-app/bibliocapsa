"""
Authentication primitives for Bibliocapsa.

One account per person serves both the web/API login and KOReader sync. Because
KOReader sends md5(password) as its auth key (and we can never recover plaintext
from that), every password is stored as TWO derivations, computed when the
plaintext is briefly in hand (register / login / change):

  * password_hash — PBKDF2-HMAC-SHA256, salted   → web + API login (strong)
  * kosync_key    — md5(password)                 → KOReader endpoints only

Sessions are server-side rows in `sessions` (revocable, no signing secret).
All crypto here is Python stdlib — no extra dependencies.
"""

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from .pg_database import get_database_url

PBKDF2_ITERATIONS = 200_000
SESSION_TTL_DAYS = 30
SESSION_COOKIE = "bibliocapsa_session"


def _pg():
    return psycopg2.connect(get_database_url(), cursor_factory=RealDictCursor)


# ── Password hashing ──────────────────────────────────────────────────────────
def hash_password(plaintext: str) -> str:
    """PBKDF2-SHA256, formatted as pbkdf2_sha256$iters$salt_b64$hash_b64."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", plaintext.encode(), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(dk).decode(),
    )


def verify_password(plaintext: str, stored: Optional[str]) -> bool:
    if not stored:
        return False
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", plaintext.encode(), salt, int(iters))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def _kosync_secret() -> bytes:
    """Server-side secret used to HMAC-wrap the KOReader md5 key. Kept OUT of the
    database (env only) so a DB-only leak can't be rainbow-tabled or brute-forced
    back to passwords. Prefer an explicit SECRET_KEY; fall back to
    POSTGRES_PASSWORD (also env-only). Must stay stable, or KOReader logins need a
    password reset to re-derive the stored key."""
    secret = os.getenv("SECRET_KEY") or os.getenv("POSTGRES_PASSWORD") or "bibliocapsa-insecure-default"
    return secret.encode()


def kosync_wrap(md5_hex: str) -> str:
    """HMAC-wrap the md5 KOReader sends (or that we derive from a plaintext
    password) with the server secret, so the value stored in `users.kosync_key`
    is never a bare, crackable md5(password)."""
    return hmac.new(_kosync_secret(), md5_hex.encode(), hashlib.sha256).hexdigest()


def kosync_key(plaintext: str) -> str:
    """Stored KOReader auth key. KOReader computes md5(password) client-side and
    sends it as x-auth-key; we wrap that md5 with a server secret so the DB holds
    hmac(secret, md5) — not the rainbow-table-able md5 itself."""
    return kosync_wrap(hashlib.md5(plaintext.encode()).hexdigest())


# ── Sessions ──────────────────────────────────────────────────────────────────
def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (%s, %s, %s)",
            (token, user_id, expires),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def destroy_session(token: str) -> None:
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE token = %s", (token,))
        conn.commit()
    finally:
        conn.close()


def _user_from_session(token: str) -> Optional[dict]:
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT u.id, u.name, u.username, u.email, u.role, u.kindle_email, u.theme, u.font
            FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token = %s AND s.expires_at > NOW()
            """,
            (token,),
        )
        return cur.fetchone()
    finally:
        conn.close()


def _user_by_credentials(username: str, password: str) -> Optional[dict]:
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, username, email, role, kindle_email, password_hash FROM users WHERE LOWER(username) = LOWER(%s)",
            (username,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if row and verify_password(password, row.get("password_hash")):
        row.pop("password_hash", None)
        return row
    return None


def authenticate_request(request) -> Optional[dict]:
    """Resolve the current user from (in order) the session cookie, an
    Authorization: Bearer <session-token>, or HTTP Basic credentials.
    Returns a user dict (id, name, username, email, role) or None."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        user = _user_from_session(token)
        if user:
            return user

    authz = request.headers.get("authorization", "")
    if authz.lower().startswith("bearer "):
        user = _user_from_session(authz[7:].strip())
        if user:
            return user
    elif authz.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(authz[6:].strip()).decode()
            username, _, password = decoded.partition(":")
            return _user_by_credentials(username, password)
        except Exception:
            return None

    return None
