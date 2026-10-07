"""Hide-until-the-next-sweep (2026-10-08): after a write that changes what a connector snapshot lists (a removed
Jellyseerr request, a resume item marked watched or reset), the row must go at once — but the snapshot only
changes at the connector's next sweep (Jellyseerr hourly, Jellyfin every ~2 min). The hub keeps a small in-memory
note per hidden row and drops it from what it renders while the snapshot was taken before the action (plus a
grace period for a sweep already running). A newer snapshot is the truth again: the note is forgotten.

One uvicorn process (hub/Dockerfile), so in-memory is enough; a restart simply shows the snapshot as it is.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

GRACE_S = 90           # a sweep that started just before the action may still carry the row
MAX_AGE_S = 6 * 3600   # a note never outlives this, whatever the snapshot does

_hidden: dict[tuple[str, str], float] = {}
_lock = threading.Lock()


def clear() -> None:
    with _lock:
        _hidden.clear()


def hide(group: str, key) -> None:
    with _lock:
        _hidden[(group, str(key))] = time.time()


def any_in(group: str) -> bool:
    """Cheap pre-check: is anything of this group hidden at all?"""
    with _lock:
        return any(g == group for g, _ in _hidden)


def _stamp(updated_at) -> float | None:
    try:
        return datetime.fromisoformat(str(updated_at).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def is_hidden(group: str, key, updated_at=None) -> bool:
    """True while the snapshot (`updated_at`, its last-success time) predates the hide by less than the grace."""
    if key is None:
        return False
    with _lock:
        at = _hidden.get((group, str(key)))
        if at is None:
            return False
        snap = _stamp(updated_at)
        if time.time() - at > MAX_AGE_S or (snap is not None and snap > at + GRACE_S):
            _hidden.pop((group, str(key)), None)  # a fresh snapshot is the truth again
            return False
        return True


def visible(group: str, rows, key_of, updated_at=None) -> list:
    """`rows` without the hidden ones (`key_of(row)` -> the key that was hidden)."""
    return [r for r in rows or [] if not (isinstance(r, dict) and is_hidden(group, key_of(r), updated_at))]
