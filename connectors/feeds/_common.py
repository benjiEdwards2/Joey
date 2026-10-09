"""Helpers more than one feed module shares: the pinned clock, ISO parsing, "ago" words,
the one duration format and the fixture host."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from connectors.base import _now_iso, home_tz

GIB = 1024 ** 3
FIXTURE_MEDIA_HOST = "nas.local"  # fixture mode never reads the real host


def _now() -> datetime:
    """The clock every feed reads — pinned in fixture mode, so output is stable."""
    return datetime.fromisoformat(_now_iso())


def _dt(value) -> datetime:
    """ISO timestamp (Z suffix, >6 fractional digits tolerated) -> aware datetime."""
    text = re.sub(r"(\.\d{6})\d+", r"\1", str(value).replace("Z", "+00:00"))
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _ago(dt: datetime, now: datetime) -> str:
    seconds = (now - dt).total_seconds()
    if seconds < 3600:
        return "just now"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hour{'' if hours == 1 else 's'} ago"
    tz = home_tz()  # a day or more: count the household's calendar days (C-08)
    days = (now.astimezone(tz).date() - dt.astimezone(tz).date()).days
    return "yesterday" if days == 1 else f"{days} days ago"


def _duration_words(minutes) -> str:
    """The one duration format (C-14): '12m' / '1h 05m' / '5h 20m' / '12d 4h'."""
    minutes = max(0, int(minutes or 0))
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h {minutes % 60:02d}m"
    return f"{hours // 24}d {hours % 24}h"
