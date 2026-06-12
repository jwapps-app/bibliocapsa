"""
Authentication endpoints (web + API login).

Account model:
  * The FIRST account created (when none exist yet) becomes an admin and is
    logged in immediately — this bootstraps the instance.
  * After that, only an admin may create further accounts (self-signup is off,
    so a public deployment can't be registered into by strangers).
Every account works for both the web UI and KOReader sync (shared password).
"""

import hmac
import os
import re
import time
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from typing import Optional

from .. import auth

router = APIRouter()

# COOKIE_SECURE: "true"/"false" forces the Secure flag; anything else (incl. the
# default "auto") auto-detects per request. Auto means IP/HTTP users are never
# locked out by a Secure cookie they can't use, while HTTPS users still get one.
_COOKIE_SECURE_ENV = os.getenv("COOKIE_SECURE", "auto").strip().lower()


def _cookie_is_secure(request: Request) -> bool:
    if _COOKIE_SECURE_ENV in ("1", "true", "yes"):
        return True
    if _COOKIE_SECURE_ENV in ("0", "false", "no"):
        return False
    # Auto: Secure only if the request actually came in over HTTPS. Honor the
    # proxy header (a reverse proxy / tunnel terminates TLS, so the backend sees
    # HTTP but the original request was HTTPS).
    proto = (request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
             or request.url.scheme)
    return proto == "https"

# ── Simple in-memory login rate limiter (brute-force protection) ──────────────
# Two sliding windows: per-account (source-independent, so an account can't be
# brute-forced from rotating IPs) and per-IP (throttles one host spraying many
# usernames). Good enough for a single-instance self-hosted app.
_LOGIN_BUCKETS: dict[str, list[float]] = {}


def _rate_ok(key: str, limit: int, window: int = 300) -> bool:
    now = time.time()
    bucket = [t for t in _LOGIN_BUCKETS.get(key, []) if now - t < window]
    bucket.append(now)
    _LOGIN_BUCKETS[key] = bucket
    if len(_LOGIN_BUCKETS) > 5000:  # crude cap so the dict can't grow unbounded
        for k in [k for k, v in _LOGIN_BUCKETS.items() if not v or now - v[-1] > window]:
            _LOGIN_BUCKETS.pop(k, None)
    return len(bucket) <= limit


def _pg():
    from ..pg_database import get_database_url
    import psycopg2
    from psycopg2.extras import RealDictCursor
    return psycopg2.connect(get_database_url(), cursor_factory=RealDictCursor)


def _account_count() -> int:
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM users WHERE password_hash IS NOT NULL")
        return cur.fetchone()["c"]
    finally:
        conn.close()


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        auth.SESSION_COOKIE, token,
        max_age=auth.SESSION_TTL_DAYS * 86400,
        httponly=True, samesite="lax", secure=_cookie_is_secure(request), path="/",
    )


class RegisterBody(BaseModel):
    username: str
    password: str
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None  # admin-only; ignored on bootstrap (always admin)
    genres: Optional[list[str]] = None  # allow-list of genres for a restricted member
    setup_token: Optional[str] = None  # required on bootstrap iff SETUP_TOKEN env is set


class AccessBody(BaseModel):
    genres: list[str]


def _set_user_genres(user_id: int, genres: list[str]) -> None:
    cleaned = sorted({g.strip().lower() for g in (genres or []) if g and g.strip()})
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM user_genre_access WHERE user_id = %s", (user_id,))
        for g in cleaned:
            cur.execute(
                "INSERT INTO user_genre_access (user_id, genre) VALUES (%s, %s)",
                (user_id, g),
            )
        conn.commit()
    finally:
        conn.close()


def _get_user_genres(user_id: int) -> list[str]:
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("SELECT genre FROM user_genre_access WHERE user_id = %s ORDER BY genre", (user_id,))
        return [r["genre"] for r in cur.fetchall()]
    finally:
        conn.close()


class LoginBody(BaseModel):
    username: str
    password: str


class PasswordBody(BaseModel):
    current_password: Optional[str] = None
    new_password: str


def _public_user(row: dict) -> dict:
    return {k: row.get(k) for k in ("id", "name", "username", "email", "role", "kindle_email", "theme", "font")}


@router.get("/status", summary="Whether first-run setup (create first admin) is needed")
def status():
    return {"setup_required": _account_count() == 0}


@router.post("/register", summary="Create an account (bootstrap first admin, else admin-only)")
def register(body: RegisterBody, request: Request, response: Response):
    username = body.username.strip()
    password = body.password
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", username) or username in (".", "..") or ".." in username:
        raise HTTPException(status_code=400, detail="Username may only contain letters, numbers, and . _ - (max 64)")
    if len(password) < 12:
        raise HTTPException(status_code=400, detail="Password must be at least 12 characters")

    existing = _account_count()
    bootstrap = existing == 0
    role = "admin"
    if bootstrap:
        # Bootstrap-race guard: if SETUP_TOKEN is set, the very first (admin)
        # account can only be claimed by someone who presents it — so an
        # internet-exposed fresh instance can't be hijacked by a stranger who
        # reaches /register before the owner does.
        required = os.getenv("SETUP_TOKEN")
        if required and not hmac.compare_digest(body.setup_token or "", required):
            raise HTTPException(status_code=403, detail="A valid setup token is required to create the first account")
    if not bootstrap:
        requester = auth.authenticate_request(request)
        if not requester or requester.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Only an admin can create accounts")
        role = body.role if body.role in ("admin", "member") else "member"

    pw_hash = auth.hash_password(password)
    ksync = auth.kosync_key(password)
    name = (body.name or username).strip()

    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM users WHERE LOWER(username) = LOWER(%s)", (username,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="Username already taken")
        cur.execute(
            """
            INSERT INTO users (name, username, email, role, password_hash, kosync_key)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, name, username, email, role
            """,
            (name, username, body.email, role, pw_hash, ksync),
        )
        user = cur.fetchone()
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")
    finally:
        conn.close()

    # Apply a genre allow-list for admin-created members (not the bootstrap admin).
    if not bootstrap and body.genres:
        _set_user_genres(user["id"], body.genres)

    # Only the bootstrap account is auto-logged-in; admin-created accounts are
    # not, so the admin keeps their own session.
    if bootstrap:
        token = auth.create_session(user["id"])
        _set_session_cookie(response, request, token)
    return _public_user(user)


@router.post("/login", summary="Log in")
def login(body: LoginBody, request: Request, response: Response):
    ip = request.client.host if request.client else "?"
    uname = body.username.strip().lower()
    if not _rate_ok(f"u:{uname}", 10) or not _rate_ok(f"ip:{ip}", 40):
        raise HTTPException(status_code=429, detail="Too many login attempts. Please wait a few minutes and try again.")
    user = auth._user_by_credentials(body.username.strip(), body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    # Successful login clears that account's failure window.
    _LOGIN_BUCKETS.pop(f"u:{uname}", None)
    token = auth.create_session(user["id"])
    _set_session_cookie(response, request, token)
    return _public_user(user)


@router.post("/logout", summary="Log out")
def logout(request: Request, response: Response):
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token:
        auth.destroy_session(token)
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/users", summary="List accounts (admin only)")
def list_accounts(request: Request):
    requester = auth.authenticate_request(request)
    if not requester or requester.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT u.id, u.name, u.username, u.email, u.role,
                   COALESCE(ARRAY_AGG(g.genre ORDER BY g.genre) FILTER (WHERE g.genre IS NOT NULL), '{}') AS genres
            FROM users u
            LEFT JOIN user_genre_access g ON g.user_id = u.id
            WHERE u.password_hash IS NOT NULL
            GROUP BY u.id
            ORDER BY u.id
            """
        )
        return cur.fetchall()
    finally:
        conn.close()


def _require_admin(request: Request) -> dict:
    requester = auth.authenticate_request(request)
    if not requester or requester.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return requester


@router.get("/users/{user_id}/access", summary="Get a member's allowed genres (admin only)")
def get_access(user_id: int, request: Request):
    _require_admin(request)
    return {"genres": _get_user_genres(user_id)}


@router.put("/users/{user_id}/access", summary="Set a member's allowed genres (admin only)")
def set_access(user_id: int, body: AccessBody, request: Request):
    _require_admin(request)
    # Note: admins bypass restrictions regardless, so restricting an admin row is
    # harmless; the UI only offers this for members.
    _set_user_genres(user_id, body.genres)
    return {"genres": _get_user_genres(user_id)}


@router.post("/users/{user_id}/password", summary="Reset a member's password (admin only)")
def admin_reset_password(user_id: int, body: PasswordBody, request: Request):
    _require_admin(request)
    if len(body.new_password) < 12:
        raise HTTPException(status_code=400, detail="Password must be at least 12 characters")
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM users WHERE id = %s", (user_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="User not found")
        cur.execute(
            "UPDATE users SET password_hash = %s, kosync_key = %s WHERE id = %s",
            (auth.hash_password(body.new_password), auth.kosync_key(body.new_password), user_id),
        )
        # Force re-login everywhere by clearing the member's existing sessions.
        cur.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")
    finally:
        conn.close()
    return {"ok": True}


@router.get("/me", summary="Current user, or 401")
def me(request: Request):
    user = auth.authenticate_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return _public_user(user)


class MeUpdate(BaseModel):
    kindle_email: Optional[str] = None


@router.put("/me", summary="Update own account (e.g. Kindle email)")
def update_me(body: MeUpdate, request: Request):
    user = auth.authenticate_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if body.kindle_email is not None:
        conn = _pg()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE users SET kindle_email = %s WHERE id = %s",
                        (body.kindle_email.strip() or None, user["id"]))
            conn.commit()
        finally:
            conn.close()
    fresh = auth._user_from_session(request.cookies.get(auth.SESSION_COOKIE) or "") or user
    return _public_user(fresh)


class PrefsBody(BaseModel):
    theme: Optional[str] = None
    font: Optional[str] = None


@router.put("/preferences", summary="Save own UI theme/font preferences")
def update_preferences(body: PrefsBody, request: Request):
    user = auth.authenticate_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    sets, params = [], []
    if body.theme is not None:
        sets.append("theme = %s"); params.append(body.theme[:32] or None)
    if body.font is not None:
        sets.append("font = %s"); params.append(body.font[:32] or None)
    if sets:
        conn = _pg()
        try:
            cur = conn.cursor()
            cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = %s", (*params, user["id"]))
            conn.commit()
        finally:
            conn.close()
    return {"ok": True}


@router.post("/password", summary="Change your own password")
def change_password(body: PasswordBody, request: Request):
    user = auth.authenticate_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if len(body.new_password) < 12:
        raise HTTPException(status_code=400, detail="Password must be at least 12 characters")

    # Verify the current password unless the account never had one set.
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("SELECT password_hash FROM users WHERE id = %s", (user["id"],))
        current_hash = cur.fetchone()["password_hash"]
        if current_hash and not auth.verify_password(body.current_password or "", current_hash):
            raise HTTPException(status_code=403, detail="Current password is incorrect")
        cur.execute(
            "UPDATE users SET password_hash = %s, kosync_key = %s WHERE id = %s",
            (auth.hash_password(body.new_password), auth.kosync_key(body.new_password), user["id"]),
        )
        # Invalidate every OTHER session for this user — a leaked/old session
        # token stops working once the password changes (the current one stays).
        current_token = request.cookies.get(auth.SESSION_COOKIE)
        cur.execute(
            "DELETE FROM sessions WHERE user_id = %s AND token IS DISTINCT FROM %s",
            (user["id"], current_token),
        )
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error: {e}")
    finally:
        conn.close()
    return {"ok": True}
