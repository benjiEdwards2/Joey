"""Director / creator column (JY-279, 2026-11-03): the list view's Director cell for every library title.

A film's director (TMDB credits, crew job "Director") or a show's creator (TMDB `createdBy`) is read from the
Jellyseerr title body (the same read a title page makes) and kept in a small media.db table, `library_director`,
keyed by (tmdb id, kind). Pages NEVER read Jellyseerr: `attach` reads the table only, and `later` hands back a
callable the route runs as its response's BackgroundTask, so the first view shows a dash and the next has the name.
The fill is rate limited (PAUSE between reads, at most BATCH per run, one run at a time) and stops on a 429.
A title with no director is stored as '' so it is not asked again before REFRESH_DAYS. Logs carry no URLs.
"""
from __future__ import annotations

import logging
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone

from hub import media_store

log = logging.getLogger("hub.media_directors")

DDL = """CREATE TABLE IF NOT EXISTS library_director(
  tmdb_id INTEGER NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, fetched_at TEXT NOT NULL,
  PRIMARY KEY (tmdb_id, kind))"""
BATCH = 40          # reads per background run
PAUSE = 0.25        # s between reads
REFRESH_DAYS = 90   # a stored answer is asked again after this
NAMES_MAX = 2       # "A, B" when a film has two directors

_running: set = set()
_lock = threading.Lock()


def tmdb_of(row) -> int | None:
    key = str(row.get("item_key") or "")
    return int(key[5:]) if key.startswith("tmdb:") and key[5:].isdigit() else None


def names(body, kind: str) -> str:
    """The director(s) of a film or the creator(s) of a show from a Jellyseerr title body; '' when none."""
    if not isinstance(body, dict):
        return ""
    if kind == "tv":
        people = [c for c in body.get("createdBy") or [] if isinstance(c, dict)]
    else:
        people = [c for c in (body.get("credits") or {}).get("crew") or []
                  if isinstance(c, dict) and c.get("job") == "Director"]
    out: list[str] = []
    for p in people:
        n = str(p.get("name") or "").strip()[:80]
        if n and n not in out:
            out.append(n)
    return ", ".join(out[:NAMES_MAX])


def cached(kind: str) -> dict[int, tuple[str, str]]:
    """{tmdb id: (name, fetched_at)} for this kind; {} without a database or table (never raises)."""
    db = media_store.reader()
    if db is None:
        return {}
    try:
        with closing(db):
            return {r[0]: (r[1], r[2]) for r in db.execute(
                "SELECT tmdb_id, name, fetched_at FROM library_director WHERE kind = ?", (kind,))}
    except Exception as exc:   # no table yet (nothing filled) or a locked file: blank cells, never a 500
        log.debug("director read skipped: %s", type(exc).__name__)
        return {}


def attach(rows, kind: str) -> dict:
    """Set `director` ('' when unknown) on each row in place; returns the cache read (for `later`)."""
    have = cached(kind)
    for r in rows or []:
        hit = have.get(tmdb_of(r))
        r["director"] = hit[0] if hit else ""
    return have


def store(tmdb_id: int, kind: str, name: str, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    with closing(media_store.connect()) as db:
        db.execute(DDL)
        db.execute("INSERT OR REPLACE INTO library_director(tmdb_id, kind, name, fetched_at) VALUES (?, ?, ?, ?)",
                   (tmdb_id, kind, name, now.strftime("%Y-%m-%dT%H:%M:%SZ")))
        db.commit()


def _stale(stamp: str, now: datetime) -> bool:
    try:
        at = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return True
    return now - at > timedelta(days=REFRESH_DAYS)


def todo(rows, kind: str, have: dict, now: datetime | None = None) -> list[int]:
    now = now or datetime.now(timezone.utc)
    out: list[int] = []
    for r in rows or []:
        t = tmdb_of(r)
        if t is not None and t not in out and (t not in have or _stale(have[t][1], now)):
            out.append(t)
    return out


def _fetch(path: str):
    from hub import media_discover   # lazy: keeps this module light for the pure tests
    return media_discover._fetch(path)


def fill(ids, kind: str, fetch=None, pause: float = PAUSE, sleep=time.sleep) -> int:
    """Read and store up to BATCH titles; stops on a 429 or when Jellyseerr does not answer. Returns the count stored."""
    fetch = fetch or _fetch
    seerr_kind = "tv" if kind == "tv" else "movie"
    done = 0
    for i, tmdb in enumerate(list(ids)[:BATCH]):
        if i and pause:
            sleep(pause)
        body, code = fetch(f"/api/v1/{seerr_kind}/{tmdb}")
        if code == 429:
            log.warning("director fill stopped: HTTP 429")
            break
        if body is None and code != 404:
            break   # no answer (no env, down): try again on a later page view
        store(tmdb, kind, names(body, kind))
        done += 1
    return done


def later(rows, kind: str, have: dict, fetch=None):
    """A callable for the response's BackgroundTask, or None when every title is cached (or a run is going)."""
    ids = todo(rows, kind, have)
    if not ids:
        return None

    def run():
        with _lock:
            if kind in _running:
                return
            _running.add(kind)
        try:
            fill(ids, kind, fetch)
        except Exception as exc:   # a background read never fails anything
            log.warning("director fill failed: %s", type(exc).__name__)
        finally:
            with _lock:
                _running.discard(kind)
    return run
