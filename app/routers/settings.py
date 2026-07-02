"""
App settings — key/value config stored in PostgreSQL.

Holds the Hardcover API token and the SMTP config (for Send-to-Kindle and
lending reminders). Secrets are never returned in full: reads report only
whether they're set (plus a masked preview for the Hardcover token).
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from .. import mailer

router = APIRouter()

HARDCOVER_TOKEN_KEY = "hardcover_token"
AUTO_ENRICH_KEY = "auto_enrich_metadata"


def auto_enrich_enabled() -> bool:
    """Whether new/imported books should auto-fetch covers & metadata. Default on."""
    return (get_setting(AUTO_ENRICH_KEY) or "true").strip().lower() in ("1", "true", "yes")


def _pg():
    from ..pg_database import get_pg
    return get_pg()


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


def _mask(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    if len(token) <= 8:
        return "•" * len(token)
    return f"{token[:4]}…{token[-4:]}"


def _require_admin(request: Request):
    from .. import auth
    u = auth.authenticate_request(request)
    if not u or u.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")


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


class SettingsUpdate(BaseModel):
    hardcover_token: Optional[str] = None  # "" clears it; None leaves unchanged
    smtp_host: Optional[str] = None
    smtp_port: Optional[str] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_tls: Optional[bool] = None
    auto_enrich: Optional[bool] = None


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
        raise HTTPException(status_code=400, detail=f"Send failed: {e}")
