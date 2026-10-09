"""Play history (F7, 2026-10-06) — "a watch, not a sitting". One row per watch of a movie or
episode, written by the recorder in hub/media_plays.py and read by the History page and
Home's "Most played" shelf. A play's end is its `last_seen_at`; hours are capped at the
runtime so a paused session left open never inflates them. Own table (DDL below; media_store
creates it with the rest of media.db).
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

from hub import media_store, media_text
from hub.ids import home_tz

log = logging.getLogger("hub.media_plays_db")

DDL = (
    """CREATE TABLE IF NOT EXISTS play(
  id INTEGER PRIMARY KEY, user_name TEXT, owner TEXT, jf_id TEXT, item_key TEXT, show_key TEXT,
  season_key TEXT, episode_key TEXT, title TEXT, show_title TEXT, kind TEXT, season INT, episode INT,
  runtime_min REAL, started_at TEXT, last_seen_at TEXT, position_pct INT, finished INT, poster TEXT)""",
    "CREATE INDEX IF NOT EXISTS play_user_item ON play(user_name, jf_id, last_seen_at)",
)
OPEN_GAP = timedelta(hours=2)
FINISHED_PCT = 90
TOP_N = 10


def _connect():
    return media_store.connect()


def _read():
    """A connection when the DB file exists, else None (media_store: never creates it, never raises)."""
    return media_store.reader()


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_parse = media_text.parse


def _tz():
    """The home zone (hub.ids); None without a tz database, which astimezone() reads as the container's local time
    — no longer a silent UTC (M-15)."""
    return home_tz()


# ---- recorder side ----

def record_sighting(play: dict, now: datetime) -> str:
    """One poll's sighting of one session. `play` carries user_name, owner, jf_id, keys,
    titles, kind, season, episode, runtime_min, poster, position_pct. Returns 'new' or 'updated'."""
    pct = max(0, min(100, int(play.get("position_pct") or 0)))
    stamp = _iso(now)
    with closing(_connect()) as db:
        row = db.execute(
            "SELECT id, position_pct FROM play WHERE user_name IS ? AND jf_id IS ? AND finished = 0"
            " AND last_seen_at >= ? ORDER BY last_seen_at DESC LIMIT 1",
            (play["user_name"], play["jf_id"], _iso(now - OPEN_GAP))).fetchone()
        if row is not None and row["position_pct"] < FINISHED_PCT:
            db.execute("UPDATE play SET last_seen_at = ?, position_pct = ?, finished = ? WHERE id = ?",
                       (stamp, pct, 1 if pct >= FINISHED_PCT else 0, row["id"]))
            db.commit()
            return "updated"
        if row is not None:  # open play already past the finish line: close it, begin a new watch
            db.execute("UPDATE play SET finished = 1 WHERE id = ?", (row["id"],))
        db.execute(
            "INSERT INTO play(user_name, owner, jf_id, item_key, show_key, season_key, episode_key, title,"
            " show_title, kind, season, episode, runtime_min, started_at, last_seen_at, position_pct,"
            " finished, poster) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (play["user_name"], play["owner"], play["jf_id"], play.get("item_key"), play.get("show_key"),
             play.get("season_key"), play.get("episode_key"), play.get("title"), play.get("show_title"),
             play["kind"], play.get("season"), play.get("episode"), play.get("runtime_min"),
             stamp, stamp, pct, 1 if pct >= FINISHED_PCT else 0, play.get("poster")))
        db.commit()
        return "new"


# ---- queries ----

def _since(window, now: datetime) -> str | None:
    if window == "all":
        return None
    if window == "year":
        local = now.astimezone(_tz())
        return _iso(datetime(local.year, 1, 1, tzinfo=local.tzinfo))
    days = int(window) if int(window) in (7, 30, 90) else 30
    return _iso(now - timedelta(days=days))


def _hours(r) -> float:
    start, end = _parse(r["started_at"]), _parse(r["last_seen_at"])
    if not start or not end:
        return 0.0
    minutes = max(0.0, (end - start).total_seconds() / 60)
    if r["runtime_min"]:
        minutes = min(minutes, r["runtime_min"])
    return minutes / 60


def _rows(window, owner, now):
    db = _read()
    if db is None:
        return []
    cut = _since(window, now)
    sql, args = "SELECT * FROM play WHERE 1=1", []
    if cut:
        sql += " AND started_at >= ?"
        args.append(cut)
    if owner in ("you", "her"):
        sql += " AND owner = ?"
        args.append(owner)
    try:   # M-52: a query error degrades (no Most played, an empty History) instead of a 500
        with closing(db):
            return db.execute(sql, args).fetchall()
    except sqlite3.Error as exc:
        log.warning("plays read failed: %s", type(exc).__name__)
        return []


def watch_count(jf_id: str, owner: str | None = None) -> int:
    """Finished watches of one Jellyfin item (a film); 0 on any DB problem."""
    db = _read()
    if db is None:
        return 0
    sql, args = "SELECT COUNT(*) FROM play WHERE jf_id = ? AND finished = 1", [jf_id]
    if owner in ("you", "her"):
        sql, args = sql + " AND owner = ?", [*args, owner]
    try:
        with closing(db):
            return int(db.execute(sql, args).fetchone()[0])
    except sqlite3.Error:
        return 0


def stats(window=30, owner=None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    rows = _rows(window, owner, now)
    shows, movies, days = {}, {}, {}
    by_hour = [0] * 24
    total = 0.0
    for r in rows:
        h = _hours(r)
        total += h
        start = _parse(r["started_at"])
        if start:
            local = start.astimezone(_tz())
            by_hour[local.hour] += 1
            days[local.date().isoformat()] = days.get(local.date().isoformat(), 0) + 1
        if r["kind"] == "episode":
            key, bucket, title = r["show_key"] or r["show_title"], shows, r["show_title"] or r["title"]
        else:
            key, bucket, title = r["item_key"] or r["title"], movies, r["title"]
        e = bucket.setdefault(key, {"key": key, "title": title, "plays": 0, "hours": 0.0, "poster": None,
                                    "jf_id": None if r["kind"] == "episode" else r["jf_id"]})
        e["plays"] += 1
        e["hours"] += h
        e["poster"] = e["poster"] or r["poster"]

    def top(bucket):
        out = sorted(bucket.values(), key=lambda e: (-e["plays"], -e["hours"], str(e["title"])))[:TOP_N]
        return [{**e, "hours": round(e["hours"], 1)} for e in out]
    top_shows = [{**e, "episodes": e["plays"]} for e in top(shows)]
    busiest = max(days.items(), key=lambda kv: (kv[1], kv[0])) if days else None
    return {"plays": len(rows), "hours": round(total, 1), "top_shows": top_shows, "top_movies": top(movies),
            "busiest_day": {"date": busiest[0], "plays": busiest[1]} if busiest else None,
            "by_hour": by_hour}


def most_played_30(owner=None, now: datetime | None = None) -> tuple[list, list]:
    s = stats(30, owner, now)
    return s["top_shows"][:5], s["top_movies"][:5]


def first_run_date() -> str | None:
    """Date of the earliest recorded play (the recorder's first sighting), or None."""
    db = _read()
    if db is None:
        return None
    try:
        with closing(db):
            row = db.execute("SELECT MIN(started_at) AS m FROM play").fetchone()
    except sqlite3.Error as exc:
        log.warning("plays first date failed: %s", type(exc).__name__)
        return None
    return row["m"][:10] if row and row["m"] else None


def hours_text(hours: float) -> str:
    """'12.5 hours' / '1 hour' (Server › History's totals, media_plays)."""
    value = round(float(hours or 0), 1)
    return f"{value:g} hour{'' if value == 1 else 's'}"
