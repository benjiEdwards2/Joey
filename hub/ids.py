"""Shared hub-core constants (T3, 2026-10-09; H-19, H-26): snapshot ids, the home time zone and the default
areas.yaml path — each defined once. Snapshot ids are connector ids from the frozen D13 namespace (hub/registry.py),
never area names. The media modules keep their own copies until the media WP moves them here.
"""

from __future__ import annotations

import os
from datetime import datetime, tzinfo
from pathlib import Path

# ---- snapshot ids ----
WEATHER_SNAPSHOT_ID = "open_meteo"
GCAL_SNAPSHOT_ID = "gcal"
JELLYFIN_SNAPSHOT_ID = "jellyfin"
MEDIA_STATUS_SNAPSHOT_ID = "media_status"
ARR_SNAPSHOT_ID = "arr"
JELLYSEERR_SNAPSHOT_ID = "jellyseerr"
QBIT_SNAPSHOT_ID = "qbittorrent"
SYSTEM_SNAPSHOT_ID = "system"
WUD_SNAPSHOT_ID = "wud"
UPTIME_KUMA_SNAPSHOT_ID = "uptime_kuma"

# ---- home clock: wall-clock at home, not the container's zone ----
HOME_TZ_NAME = "Australia/Melbourne"


def home_tz() -> tzinfo | None:
    """The home zone; None when the image has no tz database (callers then use the container's local time)."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(HOME_TZ_NAME)
    except Exception:
        return None


def home_now() -> datetime:
    tz = home_tz()
    return datetime.now(tz) if tz is not None else datetime.now().astimezone()


# ---- registry ----
DEFAULT_AREAS_PATH = Path(__file__).resolve().parents[1] / "config" / "areas.yaml"


def areas_path() -> str:
    """AREAS_PATH, else the repo's config/areas.yaml."""
    return os.environ.get("AREAS_PATH") or str(DEFAULT_AREAS_PATH)
