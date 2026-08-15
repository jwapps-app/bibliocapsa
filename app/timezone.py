"""
The server's local time zone — which decides where a "day" begins for
everything date-bucketed: reading-statistics days (the heatmap, the weekly
panel), the date stamped on a book when it's marked read, and log times.

Why this matters: the container has no zone of its own and defaults to UTC,
where midnight is early evening in the Americas. A page read at 8 pm Central
would be filed under TOMORROW, while the KOReader device — which knows local
time — files it under today. Setting the zone here makes the two agree.

Resolution order (first wins):
  1. the admin's choice in Settings (stored setting `timezone`)
  2. the TZ environment variable on the container (docker-compose)
  3. UTC

Applied PROCESS-WIDE via TZ + time.tzset(): both Python (datetime.date.today,
fromtimestamp) and SQLite's 'localtime' modifier read the C library's zone
state, so one call keeps every consumer consistent. The API runs a single
uvicorn worker, so a runtime change takes effect everywhere at once — no
restart needed when the setting changes.
"""

import os
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

SETTING_TIMEZONE = "timezone"
DEFAULT_TIMEZONE = "UTC"

# The zone the container was started with, before any setting overrode it —
# so clearing the setting can fall back to it rather than to bare UTC.
_ENV_TIMEZONE: Optional[str] = (os.environ.get("TZ") or "").strip() or None


def is_valid(tz: str) -> bool:
    """True if `tz` is an IANA zone the tz database knows (e.g. America/Chicago)."""
    if not tz or len(tz) > 64:
        return False
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz)
        return True
    except Exception:
        return False


def current() -> str:
    """The zone the process is currently running in."""
    return (os.environ.get("TZ") or "").strip() or DEFAULT_TIMEZONE


def env_default() -> str:
    """What the zone falls back to when no setting is stored."""
    return _ENV_TIMEZONE or DEFAULT_TIMEZONE


def apply(tz: Optional[str]) -> str:
    """Make `tz` the process zone (None/blank -> the env/UTC default).
    Returns the zone actually applied. Invalid input is ignored, not applied."""
    target = (tz or "").strip() or env_default()
    if not is_valid(target):
        logger.warning("Ignoring invalid time zone %r; staying on %s", tz, current())
        return current()
    if target != current():
        os.environ["TZ"] = target
        time.tzset()
        logger.info("Time zone set to %s", target)
    return target


def apply_from_settings() -> str:
    """Startup: apply the stored setting if there is one (else leave the
    container's TZ alone). Never raises — the DB may not be up yet."""
    try:
        from .routers.settings import get_setting
        return apply(get_setting(SETTING_TIMEZONE))
    except Exception as e:
        logger.debug("time zone setting unavailable at startup: %s", e)
        return current()
