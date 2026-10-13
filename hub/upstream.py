"""Keep-alive HTTP, one `requests.Session` per upstream (E1, 2026-10-13).

Every outbound call used to be a module-level `requests.get` / `post`, which opens (and for TMDB / OMDb, TLS-handshakes)
a new connection each time. The Media modules now call `session(<upstream>)`, so calls to the same app reuse a pooled
connection. Upstreams: "jellyfin", "seerr", "arr" (Radarr + Sonarr), "omdb", "tmdb" (the poster CDN). The sessions are
stateless - they keep no cookies - and carry nothing but the pool: each call still passes its own headers, params and
timeout, and errors still log by exception type only (the callers' rule). The Server side (stackctl, WUD, Discord)
keeps plain `requests` calls: rare, and not on a page's path.
"""

from __future__ import annotations

import threading
from http.cookiejar import DefaultCookiePolicy

import requests
from requests.adapters import HTTPAdapter

UPSTREAMS = ("jellyfin", "seerr", "arr", "omdb", "tmdb")
POOL = 8   # connections kept per host (Discover reads six shelves side by side; a burst past it opens extra ones)

_sessions: dict[str, requests.Session] = {}
_lock = threading.Lock()


def _new() -> requests.Session:
    s = requests.Session()
    s.cookies.set_policy(DefaultCookiePolicy(allowed_domains=[]))   # stateless: no upstream cookie is ever kept
    adapter = HTTPAdapter(pool_connections=4, pool_maxsize=POOL)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def session(name: str) -> requests.Session:
    """The kept Session for one upstream (created on first use)."""
    if name not in UPSTREAMS:
        raise ValueError("unknown upstream")
    s = _sessions.get(name)
    if s is None:
        with _lock:
            s = _sessions.get(name)
            if s is None:
                s = _sessions[name] = _new()
    return s


def close_all() -> None:
    """Drop every kept Session (their pooled connections close)."""
    with _lock:
        kept = list(_sessions.values())
        _sessions.clear()
    for s in kept:
        s.close()
