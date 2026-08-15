"""
The server's local time zone — which decides where a "day" begins for
everything date-bucketed: reading-statistics days (the heatmap, the weekly
panel), the date stamped on a book when it's marked read, and log times.

Why this matters: the container has no zone of its own and defaults to UTC,
where midnight is early evening in the Americas. A page read at 8 pm Central
would be filed under TOMORROW, while the KOReader device — which knows local
time — files it under today. Setting the zone makes the two agree.

Configured ONE way, like every other container: the TZ environment variable
(docker-compose `TZ: "${TZ:-UTC}"`, value in .env). Both Python's date
functions and SQLite's 'localtime' modifier read it, so one variable keeps
every consumer consistent. Settings shows the effective zone read-only so a
UTC misfiling looks like a config gap, not a mystery bug.
"""

import os

DEFAULT_TIMEZONE = "UTC"


def current() -> str:
    """The zone the process is running in (TZ, else UTC)."""
    return (os.environ.get("TZ") or "").strip() or DEFAULT_TIMEZONE


def is_configured() -> bool:
    """True if TZ was set on the container (as opposed to falling back to UTC)."""
    return bool((os.environ.get("TZ") or "").strip())
