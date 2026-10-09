"""Bounded in-memory caches for Media (W2, 2026-10-09; M-42). The Jellyseerr bodies, Jellyfin item reads, file
summaries and OMDb answers used to sit in plain dicts that only grew — the full-library warm-up alone put every title
body in RAM on a NAS that already swaps. Each is now an LRU of at most MAX_ENTRIES; the disk meta cache stays the
long tier. TTLs are unchanged: callers still store (fetched_at, value) and check the age on read.
"""

from __future__ import annotations

import threading
from collections import OrderedDict

MAX_ENTRIES = 256


class LRU(OrderedDict):
    """A dict that keeps at most `maxsize` entries, evicting the least recently read or written. Thread-safe for the
    single operations the Media modules use (get / [] / []= / pop / clear)."""

    def __init__(self, maxsize: int = MAX_ENTRIES):
        super().__init__()
        self.maxsize = maxsize
        self._lock = threading.RLock()

    def __getitem__(self, key):
        with self._lock:
            value = super().__getitem__(key)
            self.move_to_end(key)
            return value

    def get(self, key, default=None):
        with self._lock:
            return self[key] if key in self else default

    def __setitem__(self, key, value):
        with self._lock:
            super().__setitem__(key, value)
            self.move_to_end(key)
            while len(self) > self.maxsize:
                self.popitem(last=False)

    def pop(self, key, *default):
        with self._lock:
            return super().pop(key, *default)

    def clear(self) -> None:
        with self._lock:
            super().clear()
