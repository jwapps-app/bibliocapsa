"""
App settings — key/value config stored in PostgreSQL.

Holds the Hardcover API token and the SMTP config (for Send-to-Kindle and
lending reminders). Secrets are never returned in full: reads report only
whether they're set (plus a masked preview for the Hardcover token).
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from .. import mailer, koreader_stats, calibre_sync
from .. import timezone as tzmod

router = APIRouter()

HARDCOVER_TOKEN_KEY = "hardcover_token"
AUTO_ENRICH_KEY = "auto_enrich_metadata"


def auto_enrich_enabled() -> bool:
    """Whether new/imported books should auto-fetch covers & metadata. Default on."""
    return (get_setting(AUTO_ENRICH_KEY) or "true").strip().lower() in ("1", "true", "yes")


from ..pg_database import get_pg as _pg


# Settings change only when an admin edits them, but hot paths (read-status
# merge, reading-column filters) read the same keys several times per request —
# each read used to be its own DB query. Short TTL cache; set_setting updates it
# immediately so admin edits apply without waiting out the TTL (single worker).
_settings_cache: dict = {}
_SETTINGS_TTL = 30.0


def get_setting(key: str) -> Optional[str]:
    """Read a raw setting value. Returns None if unset or DB unavailable."""
    import time
    hit = _settings_cache.get(key)
    if hit is not None and (time.monotonic() - hit[1]) < _SETTINGS_TTL:
        return hit[0]
    try:
        conn = _pg()
        cur = conn.cursor()
        cur.execute("SELECT value FROM app_settings WHERE key = %s", (key,))
        row = cur.fetchone()
        conn.close()
        val = row["value"] if row else None
        _settings_cache[key] = (val, time.monotonic())
        return val
    except Exception:
        return None


def set_setting(key: str, value: Optional[str]) -> None:
    import time
    conn = _pg()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (%s, %s, NOW())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
        """,
        (key, value),
    )
    conn.commit()
    conn.close()
    _settings_cache[key] = (value, time.monotonic())


def _int_setting(key: str) -> int:
    try:
        return max(0, int(get_setting(key) or 0))
    except (TypeError, ValueError):
        return 0


def _mask(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    if len(token) <= 8:
        return "•" * len(token)
    return f"{token[:4]}…{token[-4:]}"


from ..auth import require_admin as _require_admin


class SettingsView(BaseModel):
    hardcover_token_set: bool = False
    hardcover_token_preview: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[str] = None
    smtp_user: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_tls: bool = True
    smtp_password_set: bool = False
    smtp_configured: bool = False
    auto_enrich: bool = True
    # Reading-stats noise filters (seconds; 0 = off) — see app/koreader_stats.py
    stats_min_session_secs: int = 0
    stats_min_book_secs: int = 0
    # Optional Calibre content server for the write path (see calibre_sync.py)
    calibre_server_url: Optional[str] = None
    calibre_server_user: Optional[str] = None
    calibre_server_password_set: bool = False
    calibre_auto_sync: bool = False
    # Server local time zone (read-only; set via TZ on the container). Decides
    # where a 'day' begins for stats and read dates.
    timezone: str = "UTC"
    timezone_configured: bool = False


class SettingsUpdate(BaseModel):
    hardcover_token: Optional[str] = None  # "" clears it; None leaves unchanged
    smtp_host: Optional[str] = None
    smtp_port: Optional[str] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_tls: Optional[bool] = None
    auto_enrich: Optional[bool] = None
    stats_min_session_secs: Optional[int] = None
    stats_min_book_secs: Optional[int] = None
    calibre_server_url: Optional[str] = None
    calibre_server_user: Optional[str] = None
    calibre_server_password: Optional[str] = None  # "" clears it
    calibre_auto_sync: Optional[bool] = None


class TestEmail(BaseModel):
    to: str


@router.get("", response_model=SettingsView, summary="Get app settings (admin; secrets masked)")
def get_settings(request: Request):
    _require_admin(request)
    token = get_setting(HARDCOVER_TOKEN_KEY)
    return SettingsView(
        hardcover_token_set=bool(token),
        hardcover_token_preview=_mask(token),
        smtp_host=get_setting(mailer.SMTP_HOST),
        smtp_port=get_setting(mailer.SMTP_PORT),
        smtp_user=get_setting(mailer.SMTP_USER),
        smtp_from=get_setting(mailer.SMTP_FROM),
        smtp_tls=(get_setting(mailer.SMTP_TLS) or "true").lower() in ("1", "true", "yes"),
        smtp_password_set=bool(get_setting(mailer.SMTP_PASSWORD)),
        smtp_configured=mailer.is_configured(),
        auto_enrich=auto_enrich_enabled(),
        stats_min_session_secs=_int_setting(koreader_stats.SETTING_MIN_SESSION),
        stats_min_book_secs=_int_setting(koreader_stats.SETTING_MIN_BOOK),
        calibre_server_url=get_setting(calibre_sync.SETTING_SERVER_URL),
        calibre_server_user=get_setting(calibre_sync.SETTING_SERVER_USER),
        calibre_server_password_set=bool(get_setting(calibre_sync.SETTING_SERVER_PASSWORD)),
        calibre_auto_sync=calibre_sync.auto_sync_enabled(),
        timezone=tzmod.current(),
        timezone_configured=tzmod.is_configured(),
    )


@router.get("/kindle-info", summary="Send-to-Kindle sender address to approve (any signed-in user)")
def kindle_info(request: Request):
    # Member-readable (no admin gate): each user needs to know which sender address
    # to add to their Amazon "Approved Personal Document E-mail List". Only the
    # public From address + configured flag are returned — never the SMTP secret.
    sender = get_setting(mailer.SMTP_FROM) or get_setting(mailer.SMTP_USER)
    return {"sender": sender, "configured": mailer.is_configured()}


@router.put("", response_model=SettingsView, summary="Update app settings (admin)")
def update_settings(updates: SettingsUpdate, request: Request):
    _require_admin(request)
    try:
        # Auto-sync requires the content server. Validate against the URL this
        # request LEAVES in place, not the one it started with, so enabling both
        # in a single call still works and clearing the URL still wins.
        if updates.calibre_server_url is not None:
            resulting_url = updates.calibre_server_url.strip()
        else:
            resulting_url = (get_setting(calibre_sync.SETTING_SERVER_URL) or "").strip()

        if updates.calibre_auto_sync:
            if not resulting_url:
                raise HTTPException(
                    status_code=400,
                    detail="Automatic syncing needs a Calibre content server. Without one, changes "
                           "are written straight to the library folder, which is only safe while "
                           "Calibre is closed — and auto-sync can fire at any time. Set a server "
                           "URL first.",
                )
            set_setting(calibre_sync.SETTING_AUTO_SYNC, "true")
        elif updates.calibre_auto_sync is not None:
            set_setting(calibre_sync.SETTING_AUTO_SYNC, "false")

        # Removing the server takes auto-sync down with it, so the stored flag
        # never disagrees with what the server actually does.
        if updates.calibre_server_url is not None and not resulting_url:
            set_setting(calibre_sync.SETTING_AUTO_SYNC, "false")
        if updates.hardcover_token is not None:
            set_setting(HARDCOVER_TOKEN_KEY, updates.hardcover_token.strip() or None)
        if updates.smtp_host is not None:
            set_setting(mailer.SMTP_HOST, updates.smtp_host.strip() or None)
        if updates.smtp_port is not None:
            set_setting(mailer.SMTP_PORT, str(updates.smtp_port).strip() or None)
        if updates.smtp_user is not None:
            set_setting(mailer.SMTP_USER, updates.smtp_user.strip() or None)
        if updates.smtp_password is not None:
            # Empty string clears; otherwise store as-is (passwords may have spaces).
            set_setting(mailer.SMTP_PASSWORD, updates.smtp_password or None)
        if updates.smtp_from is not None:
            set_setting(mailer.SMTP_FROM, updates.smtp_from.strip() or None)
        if updates.smtp_tls is not None:
            set_setting(mailer.SMTP_TLS, "true" if updates.smtp_tls else "false")
        if updates.auto_enrich is not None:
            set_setting(AUTO_ENRICH_KEY, "true" if updates.auto_enrich else "false")
        if updates.stats_min_session_secs is not None:
            set_setting(koreader_stats.SETTING_MIN_SESSION, str(max(0, updates.stats_min_session_secs)))
        if updates.stats_min_book_secs is not None:
            set_setting(koreader_stats.SETTING_MIN_BOOK, str(max(0, updates.stats_min_book_secs)))
        if updates.calibre_server_url is not None:
            set_setting(calibre_sync.SETTING_SERVER_URL, updates.calibre_server_url.strip() or None)
        if updates.calibre_server_user is not None:
            set_setting(calibre_sync.SETTING_SERVER_USER, updates.calibre_server_user.strip() or None)
        if updates.calibre_server_password is not None:
            set_setting(calibre_sync.SETTING_SERVER_PASSWORD, updates.calibre_server_password or None)
        return get_settings(request)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Database error")


@router.post("/smtp-test", summary="Send a test email (admin)")
def smtp_test(body: TestEmail, request: Request):
    _require_admin(request)
    try:
        mailer.send_email(
            to=body.to.strip(),
            subject="Bibliocapsa test email",
            body="This is a test email from Bibliocapsa. SMTP is working.",
        )
        return {"ok": True}
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("smtp test failed: %s", e)
        raise HTTPException(status_code=400, detail="Test email failed to send. Check the SMTP settings and try again.")


@router.post("/calibre-server-test", summary="Check the Calibre content server (admin)")
def calibre_server_test(request: Request):
    """Verify Bibliocapsa can actually WRITE through the configured server.
    A read would succeed even when writes are disabled (the common
    misconfiguration), so this runs calibredb's own connectivity check and
    reports the distinct failure modes plainly."""
    _require_admin(request)
    import subprocess
    url, user, _pw = calibre_sync.server_config()
    if not url:
        return {"ok": False, "detail": "No Calibre server URL configured — syncing writes to the library folder (Calibre must be closed)."}
    try:
        proc = subprocess.run(
            [calibre_sync.CALIBREDB, "list", "--limit", "1", *calibre_sync._target_args()],
            capture_output=True, text=True, timeout=45,
        )
    except Exception as e:
        return {"ok": False, "detail": f"Could not run calibredb: {e}"}
    if proc.returncode == 0:
        return {"ok": True, "detail": f"Connected to {url}" + (f" as {user}" if user else ""),
                "writable": None}
    out = (proc.stderr or proc.stdout or "calibredb failed").strip()
    return {"ok": False, "detail": calibre_sync._explain(out)}
