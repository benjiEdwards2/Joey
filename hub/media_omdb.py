"""Metacritic via OMDb (media-ux4, 2026-10-08): the film page's Metacritic pill. Optional env `OMDB_API_KEY` (the hub
reads it from deploy/.env through compose `env_file`, like the Jellyseerr keys). One lookup by IMDb id —
`GET https://www.omdbapi.com/?i=tt…&apikey=…` — server-side only; `Metascore`, else the `Ratings` entry whose Source is
"Metacritic" ("74/100").

Budget (OMDb's free tier is 1,000 calls a day): every answer for a title — a score, "N/A", not found, or a failed call
— is remembered for TTL (7 days) in memory and on disk beside the Jellyseerr meta cache (`media_discover.meta_dir()`,
key `omdb:<imdb id>`), so a title costs at most one call per 7 days, restarts included. A process makes at most
DAILY_CAP calls per UTC day. A refused key or OMDb's own limit stops calls for the rest of the day without marking
any title. No key, a bad id, the cap, or any failure ⇒ None and the pill is simply not drawn.

The request URL carries the key, so nothing here ever logs a URL, an exception message or a response body: logs carry
the HTTP status or the exception TYPE only.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import datetime, timezone

import requests

from hub import media_discover as md

log = logging.getLogger("hub.media_omdb")

URL = "https://www.omdbapi.com/"
TTL = 7 * 24 * 3600
DAILY_CAP = 800
TIMEOUT = 5
IMDB_RE = re.compile(r"^tt\d{5,10}$")
KEY_ERRORS = ("invalid api key", "no api key", "request limit reached")

_lock = threading.Lock()
_mem: dict[str, tuple[float, int | None]] = {}
_day: list = ["", 0, False]   # [UTC date, calls made today, stopped for today]


def clear_cache() -> None:
    _mem.clear()
    _day[:] = ["", 0, False]


def _key() -> str | None:
    return os.environ.get("OMDB_API_KEY", "").strip() or None


def parse(body) -> int | None:
    """The Metascore (0-100) from an OMDb title body: `Metascore`, else the Ratings "Metacritic" entry; None for N/A."""
    if not isinstance(body, dict):
        return None
    raw = str(body.get("Metascore") or "")
    if raw.isdigit() and 0 <= int(raw) <= 100:
        return int(raw)
    for r in body.get("Ratings") or []:
        if isinstance(r, dict) and r.get("Source") == "Metacritic":
            m = re.match(r"^(\d{1,3})/100$", str(r.get("Value") or ""))
            if m and int(m.group(1)) <= 100:
                return int(m.group(1))
    return None


def _cached(imdb: str) -> tuple[bool, int | None]:
    hit = _mem.get(imdb)
    if hit is None:
        disk = md._meta_disk(f"omdb:{imdb}")
        if disk is not None and isinstance(disk[1], dict):
            score = disk[1].get("metascore")
            hit = (disk[0], score if isinstance(score, int) and not isinstance(score, bool) else None)
            _mem[imdb] = hit
    if hit is not None and time.time() - hit[0] < TTL:
        return True, hit[1]
    return False, None


def _remember(imdb: str, score: int | None) -> None:
    now = time.time()
    _mem[imdb] = (now, score)
    md._meta_store(f"omdb:{imdb}", now, {"metascore": score})


def _budget() -> bool:
    """One call allowed now? Counts it. False when the day's cap is used up or OMDb refused the key today."""
    today = datetime.now(timezone.utc).date().isoformat()
    if _day[0] != today:
        _day[:] = [today, 0, False]
    if _day[2] or _day[1] >= DAILY_CAP:
        return False
    _day[1] += 1
    return True


def metascore(imdb_id) -> int | None:
    """The title's Metascore, or None (no key, bad id, N/A, over budget, any failure)."""
    key = _key()
    imdb = str(imdb_id or "").strip()
    if not key or not IMDB_RE.match(imdb):
        return None
    with _lock:   # one lookup per title at a time: a burst of opens never doubles a call
        found, score = _cached(imdb)
        if found:
            return score
        if not _budget():
            return None
        try:
            resp = requests.get(URL, params={"i": imdb, "apikey": key}, timeout=TIMEOUT)
        except Exception as exc:  # type only — the exception text holds the URL, which holds the key
            log.warning("omdb lookup failed: %s", type(exc).__name__)
            _remember(imdb, None)
            return None
        if resp.status_code == 401:
            log.warning("omdb lookup refused: HTTP 401")
            _day[2] = True
            return None
        if not 200 <= resp.status_code < 300:
            log.warning("omdb lookup failed: HTTP %s", resp.status_code)
            _remember(imdb, None)
            return None
        try:
            body = resp.json()
        except Exception as exc:
            log.warning("omdb lookup failed: %s", type(exc).__name__)
            _remember(imdb, None)
            return None
        error = str(body.get("Error") or "").lower() if isinstance(body, dict) else ""
        if any(e in error for e in KEY_ERRORS):
            log.warning("omdb lookup refused: key or daily limit")
            _day[2] = True
            return None
        score = parse(body)
        _remember(imdb, score)
        return score
