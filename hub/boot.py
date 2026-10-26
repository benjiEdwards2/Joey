"""Boot grace (JY-254, 2026-10-26): the NAS is off 22:00-07:00 and joey-hub starts with it, so the hub's start time is
the boot. Right after it, the `media_status` snapshot is from before the shutdown, or from a sweep taken while the
containers were still starting, so its "Down"s are false alarms. The Discord digest (hub/server_digest.py) and the
Server push alerts (hub/server_alerts.py) both hold their "Down" claims until `settled`: a `media_status` sample taken
since the start with every app up, or BOOT_GRACE since the start, whichever comes first. After the grace nothing is
held, so a service still down is reported as before.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hub.ids import MEDIA_STATUS_SNAPSHOT_ID
from hub.store import data_of, parse_utc

BOOT_GRACE = timedelta(minutes=15)      # the longest a "Down" is held after a hub start
STARTED = datetime.now(timezone.utc)    # the hub start = the NAS boot (joey-hub starts with it)


def settled(snaps, now: datetime | None = None, booted: datetime | None = None) -> bool:
    """True once BOOT_GRACE has passed since `booted` (default STARTED), or a media_status sample taken at or after
    `booted` shows every app up. `now`: aware (default: the clock)."""
    now = now or datetime.now(timezone.utc)
    booted = booted or STARTED
    if now - booted >= BOOT_GRACE:
        return True
    snap = snaps.get(MEDIA_STATUS_SNAPSHOT_ID)
    sampled = parse_utc(snap.updated_at) if snap is not None else None
    apps = [a for a in data_of(snap).get("apps") or [] if isinstance(a, dict)]   # as hub/server.py _apps reads them
    return sampled is not None and sampled >= booted and bool(apps) and all(a.get("up") for a in apps)
