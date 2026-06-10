"""
Outbound email (SMTP) — used for Send-to-Kindle and lending reminders.

SMTP config is stored in app_settings (set via the admin Settings UI), so no
.env/restart is needed. Pure stdlib (smtplib + email) — no new dependencies.
"""

import smtplib
import ssl
import logging
from email.message import EmailMessage
from typing import Optional

logger = logging.getLogger(__name__)

# app_settings keys
SMTP_HOST = "smtp_host"
SMTP_PORT = "smtp_port"
SMTP_USER = "smtp_user"
SMTP_PASSWORD = "smtp_password"
SMTP_FROM = "smtp_from"
SMTP_TLS = "smtp_tls"  # "true"/"false"; STARTTLS when true, SMTP_SSL when port 465


def get_config() -> dict:
    from .routers.settings import get_setting
    return {
        "host": get_setting(SMTP_HOST),
        "port": int(get_setting(SMTP_PORT) or 587),
        "user": get_setting(SMTP_USER),
        "password": get_setting(SMTP_PASSWORD),
        "from": get_setting(SMTP_FROM) or get_setting(SMTP_USER),
        "tls": (get_setting(SMTP_TLS) or "true").lower() in ("1", "true", "yes"),
    }


def is_configured() -> bool:
    c = get_config()
    return bool(c["host"] and c["from"])


def send_email(to: str, subject: str, body: str,
               attachment: Optional[bytes] = None,
               attachment_name: Optional[str] = None,
               attachment_mime: str = "application/octet-stream") -> None:
    """Send an email via the configured SMTP server. Raises on failure."""
    c = get_config()
    if not c["host"] or not c["from"]:
        raise RuntimeError("SMTP is not configured")

    msg = EmailMessage()
    msg["From"] = c["from"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    if attachment is not None and attachment_name:
        maintype, _, subtype = attachment_mime.partition("/")
        msg.add_attachment(attachment, maintype=maintype or "application",
                           subtype=subtype or "octet-stream", filename=attachment_name)

    port = c["port"]
    if port == 465:
        with smtplib.SMTP_SSL(c["host"], port, context=ssl.create_default_context(), timeout=30) as s:
            if c["user"]:
                s.login(c["user"], c["password"] or "")
            s.send_message(msg)
    else:
        with smtplib.SMTP(c["host"], port, timeout=30) as s:
            if c["tls"]:
                s.starttls(context=ssl.create_default_context())
            if c["user"]:
                s.login(c["user"], c["password"] or "")
            s.send_message(msg)
    logger.info("Sent email to %s (subject=%s)", to, subject)
