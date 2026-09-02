"""
Authentication primitives for Bibliocapsa.

One account per person serves both the web/API login and KOReader sync. Because
KOReader sends md5(password) as its auth key (and we can never recover plaintext
from that), every password is stored as TWO derivations, computed when the
plaintext is briefly in hand (register / login / change):

  * password_hash — PBKDF2-HMAC-SHA256, salted   → web + API login (strong)
  * kosync_key    — hmac(secret, md5(password))   → KOReader endpoints only

Sessions are server-side rows in `sessions` (revocable, no signing secret).
All crypto here is Python stdlib — no extra dependencies.
"""

import base64
import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

PBKDF2_ITERATIONS = 200_000
SESSION_TTL_DAYS = 30
SESSION_COOKIE = "bibliocapsa_session"


from .pg_database import get_pg as _pg


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


# Devices using HTTP Basic (OPDS readers) resend credentials on EVERY request,
# and each verification costs 200k PBKDF2 iterations (~100ms of CPU — that's the
# point of a KDF). Cache successful verifications in-memory, keyed by a SHA-256
# of (plaintext + stored hash): a password change alters `stored`, so the key
# rotates naturally; failures are never cached (each wrong guess still pays the
# full KDF, preserving brute-force cost). In-process only, bounded, short TTL.
_verify_cache: dict = {}
_VERIFY_TTL = 600.0
_VERIFY_MAX = 200


def verify_password(plaintext: str, stored: Optional[str]) -> bool:
    if not stored:
        return False
    import time
    key = hashlib.sha256((plaintext + "\x00" + stored).encode()).hexdigest()
    hit = _verify_cache.get(key)
    if hit is not None and (time.monotonic() - hit) < _VERIFY_TTL:
        return True
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", plaintext.encode(), salt, int(iters))
        ok = hmac.compare_digest(dk, expected)
        if ok:
            if len(_verify_cache) >= _VERIFY_MAX:
                _verify_cache.clear()
            _verify_cache[key] = time.monotonic()
        return ok
    except Exception:
        return False


def client_ip(request) -> str:
    """Best-effort client IP for rate-limit keys.

    Trust model: the shipped Caddy sets X-Forwarded-For from the real socket
    peer and never forwards a client-supplied value, so XFF is authoritative
    for the hop into Caddy. CF-Connecting-IP is set (and overwritten) by
    Cloudflare when traffic arrives through it, and is the real client in that
    case; a client that reaches Caddy directly could forge it. So this value is
    good enough to KEY throttles on, but every throttle also carries a global
    ceiling that no header can evade, and nothing security-critical (the
    first-admin bootstrap) trusts it alone -- see routers/auth._is_local_client."""
    h = request.headers
    cf = h.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = h.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if getattr(request, "client", None) else "?"


def via_cloudflare(request) -> bool:
    """True if the request carries Cloudflare's client-IP header. Cloudflare
    always sets it on proxied traffic, so its PRESENCE means 'arrived from the
    internet through Cloudflare' -- a LAN client never sends it."""
    return bool(request.headers.get("cf-connecting-ip"))


# Failed HTTP-Basic credential throttle. OPDS/API devices resend Basic creds on
# EVERY request, so counting all attempts would lock out legitimate devices —
# we count only FAILURES. Correct creds are never counted (a real device is
# never throttled); a password sprayer sending wrong passwords across usernames
# is. Closes the gap where the /login limiter didn't cover the Basic path.
_basic_fail: dict = {}
_BASIC_FAIL_WINDOW = 300
# Three nested ceilings. Per (user, ip) catches one host guessing one account.
# Per ip catches one host spraying many usernames -- which the per-(user,ip)
# key alone cannot, since every new username is a fresh key. The GLOBAL
# ceiling is the backstop for a client that can forge its apparent IP: past
# it, every failed credential is refused before any hashing, so an attacker
# can at most make the instance refuse bad passwords, never make it spend CPU.
_BASIC_FAIL_MAX = 20          # per (user, ip)
_BASIC_FAIL_MAX_IP = 40       # per ip
_BASIC_FAIL_MAX_GLOBAL = 300  # across all sources


def _fail_count(key: str, now: float) -> int:
    b = [t for t in _basic_fail.get(key, []) if now - t < _BASIC_FAIL_WINDOW]
    _basic_fail[key] = b
    return len(b)


def _basic_throttled(key: str, ip: str = "", scope: str = "basic") -> bool:
    now = time.time()
    if _fail_count(f"{scope}|{key}", now) >= _BASIC_FAIL_MAX:
        return True
    if ip and _fail_count(f"{scope}|ip|{ip}", now) >= _BASIC_FAIL_MAX_IP:
        return True
    return _fail_count(f"{scope}|global", now) >= _BASIC_FAIL_MAX_GLOBAL


def _note_basic_failure(key: str, ip: str = "", scope: str = "basic") -> None:
    now = time.time()
    keys = [f"{scope}|{key}", f"{scope}|global"] + ([f"{scope}|ip|{ip}"] if ip else [])
    for k in keys:
        b = [t for t in _basic_fail.get(k, []) if now - t < _BASIC_FAIL_WINDOW]
        b.append(now)
        _basic_fail[k] = b
    if len(_basic_fail) > 5000:  # crude cap so the dict can't grow unbounded
        for k in [k for k, v in _basic_fail.items() if not v or now - v[-1] > _BASIC_FAIL_WINDOW]:
            _basic_fail.pop(k, None)


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


# Resolved sessions, token -> (user dict, resolved_at). Every /api and /opds
# request resolves its session in the auth middleware; a page render is ~50
# requests, so without this each one is a Postgres round trip. Short TTL, and
# EXPLICITLY invalidated wherever a session or user row changes (logout,
# password change/reset, profile edits), so revocation is immediate rather
# than "within a minute". Bounded; in-process only.
_session_cache: dict = {}
_SESSION_CACHE_TTL = 60.0
_SESSION_CACHE_MAX = 500


def invalidate_session(token: str) -> None:
    _session_cache.pop(token, None)


def invalidate_user_sessions(user_id: int) -> None:
    """Drop every cached session for a user (password/profile changed)."""
    for t in [t for t, (u, _) in _session_cache.items() if u.get("id") == user_id]:
        _session_cache.pop(t, None)


def destroy_session(token: str) -> None:
    invalidate_session(token)
    conn = _pg()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM sessions WHERE token = %s", (token,))
        conn.commit()
    finally:
        conn.close()


def _user_from_session(token: str) -> Optional[dict]:
    hit = _session_cache.get(token)
    if hit is not None and (time.monotonic() - hit[1]) < _SESSION_CACHE_TTL:
        return dict(hit[0])
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
        user = cur.fetchone()
    finally:
        conn.close()
    if user:
        if len(_session_cache) >= _SESSION_CACHE_MAX:
            _session_cache.clear()
        _session_cache[token] = (dict(user), time.monotonic())
    return user


# A throwaway hash used to spend one PBKDF2 when the username doesn't exist, so
# response time can't distinguish "no such user" from "wrong password". Computed
# once at import; the decoy never matches, so it's never cached and always costs
# the full KDF.
_DECOY_HASH = hash_password(secrets.token_hex(16))


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
    if row:
        if verify_password(password, row.get("password_hash")):
            row.pop("password_hash", None)
            return row
        return None
    verify_password(password, _DECOY_HASH)  # equalize timing (no user-enumeration oracle)
    return None


def authenticate_request(request) -> Optional[dict]:
    """Resolve the current user from (in order) the session cookie, an
    Authorization: Bearer <session-token>, or HTTP Basic credentials.
    Returns a user dict (id, name, username, email, role) or None.

    The auth middleware already resolved the user once and stashed it on
    request.state — reuse it so per-route admin checks don't re-run the whole
    session/credential lookup (a second DB round trip per request)."""
    cached = getattr(getattr(request, "state", None), "user", None)
    if cached:
        return cached
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
        except Exception:
            return None
        # Throttle failed Basic attempts (password spraying via any /api or /opds
        # endpoint, which bypasses the /login limiter). Correct creds never count.
        ip = client_ip(request)
        fkey = f"{username.lower()}|{ip}"
        if _basic_throttled(fkey, ip):
            return None
        user = _user_by_credentials(username, password)
        if not user:
            _note_basic_failure(fkey, ip)
        return user

    return None


def require_admin(request) -> dict:
    """403 unless the requester is an admin; returns the user dict. The single
    admin gate — routers import it as their _require_admin."""
    u = authenticate_request(request)
    if not u or u.get("role") != "admin":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Admin only")
    return u
