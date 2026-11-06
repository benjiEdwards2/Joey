"""JY-266 Collections (spec docs/specs/JY-266-collections.md): film franchises (TMDB collections) from the films on Joey.

P1 (data, no screen):
  * Two media.db tables (media_store STEPS step 8): `collection` (one row per TMDB collection: name, poster, backdrop,
    its parts as compact JSON, fetched_at) and `collection_member` (owned film's TMDB id -> collection id, NULL for a
    film in no collection, checked_at), plus `collection_state` (kick_at, last_pass_at).
  * The pass (`tick`, the hub loop, hourly): the owned films are the jellyfin snapshot's movie library. A film is due
    when it has no member row, was checked over EVERY_DAYS ago, or before the last manual kick; a collection is due when
    a member names it and its row is missing, old or older than the kick. At most PER_PASS Seerr reads a tick. A read
    with no answer (or a 2xx that is not a JSON object) stops the pass (the next tick retries); a 404 is an answer
    (film: NULL; collection: its row goes and a tombstone in `collection_gone` keeps it from being asked again for
    EVERY_DAYS - its films keep their own monthly date, so nothing churns hourly). Memory gate as the posters pass;
    COLLECTIONS=off starts no loop.
  * `summaries(owned_keys)`: the owned / missing computation the pages draw, from the tables only (no network).
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timedelta, timezone

from hub import media_discover as md, media_store, media_text

log = logging.getLogger("hub.media_collections")

FIRST_DELAY_S = 240
TICK_S = 3600
EVERY_DAYS = 30           # monthly: a film's membership and a collection's parts are re-read at most this often
PER_PASS = 40             # Seerr reads per tick
MIN_AVAILABLE_MB = 1200   # the NAS floor (as hub/media_posters.py)
NAME_MAX = 80

DDL = (
    """CREATE TABLE IF NOT EXISTS collection(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, poster TEXT, backdrop TEXT, parts_json TEXT NOT NULL DEFAULT '[]',
  fetched_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS collection_member(
  movie_tmdb INTEGER PRIMARY KEY, collection_id INTEGER, checked_at TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS collection_member_col ON collection_member(collection_id)",
    "CREATE TABLE IF NOT EXISTS collection_state(key TEXT PRIMARY KEY, value TEXT)",
    # a collection Seerr / TMDB answered 404 for: not asked again (nor shown) until gone_at is EVERY_DAYS old
    "CREATE TABLE IF NOT EXISTS collection_gone(id INTEGER PRIMARY KEY, gone_at TEXT NOT NULL)",
)

_running = threading.Lock()   # one pass at a time (the loop and a kick)


def disabled() -> bool:
    return os.environ.get("COLLECTIONS", "").strip().lower() == "off"


def migrate(db) -> None:
    """media.db step 8 (JY-266). Idempotent."""
    for ddl in DDL:
        db.execute(ddl)
    db.commit()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def _int(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


# ---- reading the library ----

def owned_ids(jelly: dict | None) -> set[int]:
    """TMDB ids of the movies in a jellyfin snapshot's library (`tmdb:<id>` keys)."""
    out = set()
    for m in (jelly or {}).get("movies") or []:
        key = str((m or {}).get("item_key") or "")
        if key.startswith("tmdb:") and key[5:].isdigit():
            out.add(int(key[5:]))
    return out


def owned_keys(jelly: dict | None) -> set[str]:
    return {f"tmdb:{i}" for i in owned_ids(jelly)}


# ---- the state table ----

def _state(db, key: str) -> str | None:
    row = db.execute("SELECT value FROM collection_state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def _set_state(db, key: str, value: str) -> None:
    db.execute("INSERT INTO collection_state(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = "
               "excluded.value", (key, value))


def kick(now: datetime | None = None) -> None:
    """The owner's "Check now": everything checked before now is due again."""
    with closing(media_store.connect()) as db:
        _set_state(db, "kick_at", _iso(now or _now()))
        db.commit()


def last_pass() -> str | None:
    db = media_store.reader()
    if db is None:
        return None
    try:
        with closing(db):
            return _state(db, "last_pass_at")
    except sqlite3.Error:
        return None


# ---- parsing Seerr bodies ----

def parts_of(body: dict) -> list[dict]:
    """A Seerr collection body's parts -> [{id, title, date, poster}] (junk rows dropped)."""
    out = []
    for p in body.get("parts") if isinstance(body.get("parts"), list) else []:
        if not isinstance(p, dict) or _int(p.get("id")) is None:
            continue
        title = str(p.get("title") or p.get("name") or "").strip()[:200]
        if not title:
            continue
        date = str(p.get("releaseDate") or "")[:10] or None
        out.append({"id": p["id"], "title": title, "date": date, "poster": md._ref(p.get("posterPath"))})
    return out


# ---- the pass ----

def _due_cut(db, now: datetime) -> str:
    """Rows checked before this ISO time are due: EVERY_DAYS ago, or the last kick when it is later."""
    cut = _iso(now - timedelta(days=EVERY_DAYS))
    kicked = _state(db, "kick_at")
    return max(cut, kicked) if kicked else cut


def run_pass(owned: set[int], now: datetime | None = None, limit: int = PER_PASS) -> dict:
    """One pass over the owned films and their collections, at most `limit` Seerr reads. -> counts. Raises on a
    database error (tick() catches it)."""
    now = now or _now()
    counts = {"films": 0, "collections": 0, "dropped": 0, "failed": 0, "calls": 0, "more": False}
    if not _running.acquire(blocking=False):
        counts["busy"] = True
        return counts
    try:
        with closing(media_store.connect()) as db:
            cut, stamp = _due_cut(db, now), _iso(now)
            checked = {r[0]: r[1] for r in db.execute("SELECT movie_tmdb, checked_at FROM collection_member")}
            films = sorted(t for t in owned if t not in checked or checked[t] < cut)
            for tmdb in films:
                if counts["calls"] >= limit:
                    counts["more"] = True
                    break
                counts["calls"] += 1
                body, code = md._fetch(f"/api/v1/movie/{tmdb}")
                if code != 404 and not isinstance(body, dict):   # no answer, or a 2xx that is not an object
                    counts["failed"] += 1
                    break
                col = body.get("collection") if isinstance(body, dict) else None
                col_id = _int(col.get("id")) if isinstance(col, dict) else None
                db.execute("INSERT INTO collection_member(movie_tmdb, collection_id, checked_at) VALUES(?, ?, ?) "
                           "ON CONFLICT(movie_tmdb) DO UPDATE SET collection_id = excluded.collection_id, "
                           "checked_at = excluded.checked_at", (tmdb, col_id, stamp))
                counts["films"] += 1
                db.commit()
            if not counts["failed"]:
                _collections(db, cut, stamp, limit, counts)
            if not counts["failed"] and not counts["more"]:
                _set_state(db, "last_pass_at", stamp)
            db.commit()
    finally:
        _running.release()
    return counts


def _collections(db, cut: str, stamp: str, limit: int, counts: dict) -> None:
    rows = db.execute("SELECT DISTINCT m.collection_id, c.fetched_at, g.gone_at FROM collection_member m "
                      "LEFT JOIN collection c ON c.id = m.collection_id LEFT JOIN collection_gone g "
                      "ON g.id = m.collection_id WHERE m.collection_id IS NOT NULL").fetchall()
    for col_id, fetched, gone in sorted(rows, key=lambda r: (r[1] is not None, r[1] or "", r[0])):
        if (fetched is not None and fetched >= cut) or (gone is not None and gone >= cut):
            continue
        if counts["calls"] >= limit:
            counts["more"] = True
            return
        counts["calls"] += 1
        body, code = md._fetch(f"/api/v1/collection/{col_id}")
        if code == 404:
            # TMDB dropped it: its row goes, a tombstone keeps it unasked for EVERY_DAYS
            db.execute("DELETE FROM collection WHERE id = ?", (col_id,))
            db.execute("INSERT INTO collection_gone(id, gone_at) VALUES(?, ?) ON CONFLICT(id) DO UPDATE SET "
                       "gone_at = excluded.gone_at", (col_id, stamp))
            counts["dropped"] += 1
            db.commit()
            continue
        if not isinstance(body, dict):   # no answer, or a 2xx that is not an object: try again next tick
            counts["failed"] += 1
            return
        name = str(body.get("name") or "Collection").strip()[:NAME_MAX]
        db.execute("INSERT INTO collection(id, name, poster, backdrop, parts_json, fetched_at) VALUES(?, ?, ?, ?, ?, ?) "
                   "ON CONFLICT(id) DO UPDATE SET name = excluded.name, poster = excluded.poster, "
                   "backdrop = excluded.backdrop, parts_json = excluded.parts_json, fetched_at = excluded.fetched_at",
                   (col_id, name, md._ref(body.get("posterPath")), md._ref(body.get("backdropPath")),
                    json.dumps(parts_of(body), separators=(",", ":")), stamp))
        db.execute("DELETE FROM collection_gone WHERE id = ?", (col_id,))
        counts["collections"] += 1
        db.commit()


def memory_ok(snaps) -> bool:
    from hub import media_posters   # its NAS memory reading (the `system` snapshot)
    free = media_posters.memory_mb(snaps)
    if free is not None and free >= MIN_AVAILABLE_MB:
        return True
    log.warning("collections: pass skipped, NAS available memory %s", "unknown" if free is None else "low")
    return False


def _jelly(snaps) -> dict | None:
    from hub.ids import JELLYFIN_SNAPSHOT_ID
    snap = (snaps or {}).get(JELLYFIN_SNAPSHOT_ID)
    data = getattr(snap, "data", None)
    return data if isinstance(data, dict) else None


def tick(snaps_fn, now: datetime | None = None) -> dict | None:
    """The loop's hourly step (and a kick's one run): a pass over what is due. None when nothing ran. Never raises."""
    if disabled() or md._creds() is None:
        return None
    try:
        snaps = snaps_fn()
        jelly = _jelly(snaps)
        if jelly is None or not memory_ok(snaps):
            return None
        counts = run_pass(owned_ids(jelly), now)
    except (sqlite3.Error, OSError) as exc:
        log.warning("collections tick failed: %s", type(exc).__name__)
        return None
    if counts["calls"]:
        log.info("collections: %(films)s films, %(collections)s collections, %(dropped)s dropped, %(failed)s failed, "
                 "%(calls)s calls", counts)
    return counts


# ---- owned / missing (the pages; tables only) ----

def _years(parts: list[dict]) -> str | None:
    ys = sorted(int(p["date"][:4]) for p in parts if p.get("date") and p["date"][:4].isdigit())
    if not ys:
        return None
    return str(ys[0]) if ys[0] == ys[-1] else f"{ys[0]}-{ys[-1]}"


def _order(parts: list[dict]) -> list[dict]:
    """Release order; a part with no date goes last."""
    return sorted(parts, key=lambda p: (p.get("date") is None, p.get("date") or "", p["title"].lower()))


def summary(row, owned: set[str]) -> dict:
    """One collection row -> the card / page words: parts in release order with `on`, counts, years, poster stack."""
    try:
        raw = json.loads(row["parts_json"] or "[]")
    except (TypeError, ValueError):
        raw = []
    parts = [{**p, "on": f"tmdb:{p['id']}" in owned, "year": media_text.year(p.get("date")),
              "href": f"/media/title/movie/{p['id']}"} for p in _order([p for p in raw if isinstance(p, dict)
                                                                       and _int(p.get("id")) and p.get("title")])]
    n, on = len(parts), sum(1 for p in parts if p["on"])
    newest = max((p["date"] for p in parts if p.get("date")), default="")
    stack = [p["poster"] for p in parts if p["on"] and p.get("poster")][:2]
    return {"id": row["id"], "name": row["name"], "poster": row["poster"] or (stack[0] if stack else None),
            "backdrop": row["backdrop"], "parts": parts, "n": n, "on": on, "years": _years(parts),
            "complete": n > 0 and on == n, "pct": round(100 * on / n) if n else 0, "newest": newest,
            "stack": stack, "href": f"/media/collections/{row['id']}",
            "count_line": media_text.plural(n, "film") + (f" · {_years(parts)}" if _years(parts) else ""),
            "on_line": f"{on} of {n} on Joey"}


def summaries(owned: set[str]) -> list[dict] | None:
    """Every stored collection with at least one part in `owned`, A-Z. None when media.db cannot be read."""
    db = media_store.reader()
    if db is None:
        return []
    try:
        with closing(db):
            rows = db.execute("SELECT id, name, poster, backdrop, parts_json FROM collection").fetchall()
    except sqlite3.Error as exc:
        log.warning("collections read failed: %s", type(exc).__name__)
        return None
    out = [s for s in (summary(r, owned) for r in rows) if s["on"]]
    return sorted(out, key=lambda s: (s["name"].lower(), s["id"]))


def one(col_id: int, owned: set[str]) -> dict | None:
    """One stored collection's summary (owned or not), or None when it is not stored / unreadable."""
    db = media_store.reader()
    if db is None:
        return None
    try:
        with closing(db):
            row = db.execute("SELECT id, name, poster, backdrop, parts_json FROM collection WHERE id = ?",
                             (col_id,)).fetchone()
    except sqlite3.Error as exc:
        log.warning("collection read failed: %s", type(exc).__name__)
        return None
    return summary(row, owned) if row else None
