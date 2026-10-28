"""JY-264 phase 1: the library index (spec docs/specs/JY-264-engine-seam.md, section 2).

One row per Jellyfin item Joey has seen: its kind, title, year, path and provider ids, its series / season / episode
numbers, when it was first and last seen, and `gone_since` once a complete library fetch no longer lists it. Rows are
never deleted: a vanished id keeps its row, which is what the re-attach (hub/library_reattach.py) needs after a
Jellyfin library rebuild re-mints every item id.

Filled from what the hub already has, with no new live polling:
  * the Jellyfin snapshot (`sync_from_snapshot`): the movie and series library lists (yours and hers), and the
    episode rows of up next / now playing / recent history; run by the hub loop (`tick`) only when the snapshot's
    `library_fetched_at` moved on (at most every JELLYFIN_LIBRARY_EVERY_S, 15 min);
  * Joey's own `play` and `diary` rows (their episode, season and series ids and numbers);
  * the play recorder's /Sessions sightings and the item page's Jellyfin read (`note_item` remembers them in memory,
    the loop writes them with `flush`; never on the media front).

Absence rule: a movie or series is marked gone only when it is missing from a list that is complete: the list is
present (the call did not fail) and shorter than LIBRARY_FETCH_LIMIT (a full page may be truncated). Seasons and
episodes are never marked gone (the lists hold none); they re-attach through their series.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
from collections import deque
from contextlib import closing
from datetime import datetime, timezone

from hub import media_store

log = logging.getLogger("hub.library_index")

FIRST_DELAY_S = 45
EVERY_S = 60                 # a look at the snapshot every minute; a sync only when library_fetched_at moved on
LIBRARY_FETCH_LIMIT = 2000   # connectors/feeds/jellyfin.py LIBRARY_FETCH_LIMIT: a list this long may be truncated
KINDS = {"Movie": "movie", "Series": "series", "Season": "season", "Episode": "episode"}
ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
PENDING_MAX = 500   # sightings kept between two loop ticks (a minute); the oldest drop first
_pending: deque = deque(maxlen=PENDING_MAX)
_pending_lock = threading.Lock()
FIELDS = ("kind", "title", "year", "path", "tmdb_id", "tvdb_id", "imdb_id", "series_jf_id", "season", "episode",
          "version_of")

DDL = (
    """CREATE TABLE IF NOT EXISTS library_index(
  jf_id TEXT PRIMARY KEY, kind TEXT NOT NULL, title TEXT, year INT, path TEXT,
  tmdb_id TEXT, tvdb_id TEXT, imdb_id TEXT, series_jf_id TEXT, season INT, episode INT, version_of TEXT,
  first_seen_at TEXT, last_seen_at TEXT, gone_since TEXT, gone_fetches INT NOT NULL DEFAULT 0, superseded_by TEXT)""",
    "CREATE INDEX IF NOT EXISTS library_index_tmdb ON library_index(tmdb_id)",
    "CREATE INDEX IF NOT EXISTS library_index_tvdb ON library_index(tvdb_id)",
    "CREATE INDEX IF NOT EXISTS library_index_imdb ON library_index(imdb_id)",
    "CREATE INDEX IF NOT EXISTS library_index_path ON library_index(path)",
    "CREATE INDEX IF NOT EXISTS library_index_child ON library_index(series_jf_id, season, episode)",
    "CREATE TABLE IF NOT EXISTS library_index_state(key TEXT PRIMARY KEY, value TEXT)",
    # the re-attach's audit (hub/library_reattach.py): one row per run, one row per changed cell
    """CREATE TABLE IF NOT EXISTS reattach_run(
  id INTEGER PRIMARY KEY, started_at TEXT, mode TEXT NOT NULL, trigger TEXT, summary_json TEXT,
  applied_at TEXT, undone_at TEXT, undo_of INT)""",
    """CREATE TABLE IF NOT EXISTS reattach_change(
  id INTEGER PRIMARY KEY, run_id INT NOT NULL, table_name TEXT NOT NULL, row_ref TEXT, column_name TEXT,
  old_value TEXT, new_value TEXT, detail TEXT)""",   # detail: a copied poster row / folder's fingerprint
    "CREATE INDEX IF NOT EXISTS reattach_change_run ON reattach_change(run_id)",
)


def disabled() -> bool:
    return os.environ.get("LIBRARY_INDEX", "").strip().lower() == "off"


def migrate(db) -> None:
    """media.db step 7 (JY-264; after JY-265's step 6). Idempotent."""
    for ddl in DDL:
        db.execute(ddl)
    db.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _id(v) -> str | None:
    v = str(v) if v is not None else ""
    return v if ID_RE.match(v) else None


def _bare(key) -> str | None:
    """`jf:<id>` -> <id>; anything else None."""
    return _id(key[3:]) if isinstance(key, str) and key.startswith("jf:") else None


def _int(v) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _str(v) -> str | None:
    return str(v) if v not in (None, "") else None


# ---- writing ----

def _upsert(db, row: dict, now: str, seen: bool = True) -> None:
    """Insert or refresh one row. Never blanks a known value with a missing one. `seen` = the item exists right now
    (it clears gone_since); a row learnt from Joey's own tables is not proof the id still exists."""
    vals = [row.get(f) for f in FIELDS]
    sets = ", ".join(f"{f} = COALESCE(excluded.{f}, {f})" for f in FIELDS if f != "kind")
    if seen:
        sets += ", last_seen_at = excluded.last_seen_at, gone_since = NULL, gone_fetches = 0"
    db.execute(f"INSERT INTO library_index(jf_id, {', '.join(FIELDS)}, first_seen_at, last_seen_at) "
               f"VALUES(?, {', '.join('?' * len(FIELDS))}, ?, ?) ON CONFLICT(jf_id) DO UPDATE SET {sets}",
               (row["jf_id"], *vals, now, now if seen else None))


def row_from_item(item: dict) -> list[dict]:
    """A Jellyfin item payload (Movie, Series, Season, Episode) -> index rows: the item, plus its series and season
    as bare rows when it names them."""
    kind = KINDS.get(str(item.get("Type")))
    jf_id = _id(item.get("Id"))
    if kind is None or jf_id is None:
        return []
    ids = item.get("ProviderIds") or {}
    year = _int(item.get("ProductionYear"))
    row = {"jf_id": jf_id, "kind": kind, "title": _str(item.get("Name")), "year": year,
           "path": _str(item.get("Path")), "tmdb_id": _str(ids.get("Tmdb")), "tvdb_id": _str(ids.get("Tvdb")),
           "imdb_id": _str(ids.get("Imdb"))}
    out = [row]
    series = _id(item.get("SeriesId"))
    if kind == "season":
        row.update(series_jf_id=series, season=_int(item.get("IndexNumber")))
    elif kind == "episode":
        season_id = _id(item.get("SeasonId"))
        row.update(series_jf_id=series, season=_int(item.get("ParentIndexNumber")),
                   episode=_int(item.get("IndexNumber")))
        if season_id:
            out.append({"jf_id": season_id, "kind": "season", "series_jf_id": series, "season": row["season"]})
    if series and kind in ("season", "episode"):
        out.append({"jf_id": series, "kind": "series", "title": _str(item.get("SeriesName"))})
    return out


def note_item(item: dict) -> None:
    """Remember one Jellyfin item the hub has just read (an item page, a /Sessions sighting). In memory only: the
    index loop writes it (`flush`), so a page read opens no write connection. Never raises; never on the media front
    (joey-hub is the one background writer of media.db)."""
    try:
        from hub import guest
        if guest.is_media() or not isinstance(item, dict):
            return
        rows = row_from_item(item)
        if rows:
            with _pending_lock:
                _pending.append((_now(), rows))
    except Exception as exc:   # an index miss is never worth a failed page or a lost play
        log.warning("library index note failed: %s", type(exc).__name__)


def flush() -> int:
    """Write the remembered sightings. Never creates media.db (a read never does). -> rows written."""
    with _pending_lock:
        batch = list(_pending)
        _pending.clear()
    if not batch or not media_store.db_path().is_file():
        return 0
    with closing(media_store.connect()) as db, db:
        for now, rows in batch:
            for r in rows:
                _upsert(db, r, now)
    return sum(len(rows) for _now_, rows in batch)


def _library_rows(data: dict, key: str, kind: str):
    """(rows, complete) for one library list across you and her. complete: every list present and under the limit."""
    lists = [data.get(key)]
    her = data.get("her")
    if isinstance(her, dict):
        lists.append(her.get(key))
    rows, complete = [], True
    for lst in lists:
        if not isinstance(lst, list):
            complete = False
            continue
        if len(lst) >= LIBRARY_FETCH_LIMIT:
            complete = False
        for r in lst:
            if not isinstance(r, dict) or not _id(r.get("jf_id")):
                continue
            item_key = str(r.get("item_key") or "")
            rows.append({"jf_id": r["jf_id"], "kind": kind, "title": _str(r.get("title")), "year": _int(r.get("year")),
                         "path": _str(r.get("path")),
                         "tmdb_id": _str(r.get("tmdb")) or (item_key[5:] if item_key.startswith("tmdb:") else None),
                         "tvdb_id": _str(r.get("tvdb")) or (item_key[5:] if item_key.startswith("tvdb:") else None),
                         "imdb_id": _str(r.get("imdb"))})
    return rows, complete


def _episode_rows(data: dict) -> list[dict]:
    """Episode + season rows from the snapshot's episode rows (up next, now playing, recent history; you and her)."""
    blocks = [data]
    if isinstance(data.get("her"), dict):
        blocks.append(data["her"])
    out = []
    for b in blocks:
        rows = list(b.get("up_next") or []) + list(b.get("now_playing") or [])
        hist = b.get("history")
        if isinstance(hist, dict):
            rows += list(hist.get("recent") or [])
        for r in rows:
            if isinstance(r, dict):
                out += _child_rows(r.get("episode_key"), r.get("season_key"), r.get("show_key"),
                                   r.get("season"), r.get("episode"))
    return out


def _child_rows(episode_key, season_key, show_key, season, episode) -> list[dict]:
    ep, sea, show = _bare(episode_key), _bare(season_key), _bare(show_key)
    out = []
    if ep:
        out.append({"jf_id": ep, "kind": "episode", "series_jf_id": show, "season": _int(season),
                    "episode": _int(episode)})
    if sea:
        out.append({"jf_id": sea, "kind": "season", "series_jf_id": show, "season": _int(season)})
    if show and (ep or sea):
        out.append({"jf_id": show, "kind": "series"})
    return out


def _table_rows(db) -> list[dict]:
    """Episode / season / series ids from Joey's own play and diary rows (they carry the series link + numbers)."""
    out = []
    for r in db.execute("SELECT episode_key, season_key, show_key, season, episode, jf_id, kind FROM play"):
        out += _child_rows(r[0] or (f"jf:{r[5]}" if r[6] == "episode" and r[5] else None), r[1], r[2], r[3], r[4])
    for r in db.execute("SELECT item_key, season_key, show_key, season, episode FROM diary "
                        "WHERE show_key LIKE 'jf:%' AND item_key LIKE 'jf:%' AND item_key != show_key"):
        out += _child_rows(*r)
    return out


def _state(db, key: str) -> str | None:
    row = db.execute("SELECT value FROM library_index_state WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def _set_state(db, key: str, value) -> None:
    db.execute("INSERT INTO library_index_state(key, value) VALUES(?, ?) "
               "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, None if value is None else str(value)))


def sync_from_snapshot(data: dict, now: str | None = None) -> dict | None:
    """Bring the index up to date with one `jellyfin` data block. None when its `library_fetched_at` is missing or
    already synced (nothing written); else the counts. Raises on a database error (tick() catches it)."""
    stamp = (data or {}).get("library_fetched_at")
    if not stamp:
        return None
    now = now or _now()
    with closing(media_store.connect()):   # the sync is a writer: media.db exists from here on
        pass
    flush()                                 # the recorder's and item pages' sightings land before the absence rule
    with closing(media_store.connect()) as db, db:
        if _state(db, "synced_fetched_at") == str(stamp):
            return None
        movies, movies_complete = _library_rows(data, "movies", "movie")
        shows, shows_complete = _library_rows(data, "shows", "series")
        for r in movies + shows + _episode_rows(data):
            _upsert(db, r, now)
        for r in _table_rows(db):
            _upsert(db, r, now, seen=False)
        newly_gone = 0
        for kind, rows, complete in (("movie", movies, movies_complete), ("series", shows, shows_complete)):
            if not complete:
                continue
            listed = {r["jf_id"] for r in rows}
            for (jf_id, gone) in db.execute("SELECT jf_id, gone_since FROM library_index WHERE kind = ?",
                                            (kind,)).fetchall():
                if jf_id in listed:
                    continue
                newly_gone += gone is None
                db.execute("UPDATE library_index SET gone_since = COALESCE(gone_since, ?), "
                           "gone_fetches = gone_fetches + 1 WHERE jf_id = ?", (now, jf_id))
        complete = movies_complete and shows_complete
        count = len({r["jf_id"] for r in movies + shows})
        if complete:
            # the rebuild guard's numbers (library_reattach.suspected): this and the previous complete count, and
            # the baseline they are held against. The baseline only moves on a fetch where nothing new went missing,
            # and only after this fetch's guard has read it.
            baseline = _state(db, "count_baseline")
            _set_state(db, "guard_baseline", baseline)
            _set_state(db, "count_prev", _state(db, "count_last"))
            _set_state(db, "count_last", count)
            if newly_gone == 0 or baseline is None:
                _set_state(db, "count_baseline", count)
        _set_state(db, "last_complete", int(complete))
        _set_state(db, "synced_fetched_at", stamp)
    return {"movies": len(movies), "shows": len(shows), "complete": complete, "newly_gone": newly_gone}


def tick(read_snapshots) -> None:
    """The hub loop: write the remembered sightings, sync the index from the latest jellyfin snapshot, then let the
    re-attach decide. Never raises."""
    try:
        flush()
        snap = (read_snapshots() or {}).get("jellyfin")
        data = getattr(snap, "data", None)
        if not isinstance(data, dict) or sync_from_snapshot(data) is None:
            return
        from hub import library_reattach
        library_reattach.auto()
    except Exception as exc:
        log.warning("library index tick failed: %s", type(exc).__name__)
