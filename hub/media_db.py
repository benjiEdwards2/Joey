"""Ratings + watch diary (2026-10-05) — the hub's FIRST write path, one small SQLite
file (`MEDIA_DB_PATH`, default /data/sqlite/media.db). Ratings and the diary carry an
owner: `you` (B.) or `her` (Georgina's Jellyfin user, 2026-10-05); rankings stay B.'s only.

Reads never create the file: with no DB present the pages render empty and
`get_ratings` answers {}. Only a write (rating, manual log, diary sync with rows
to insert) creates the directory and schema, on first use.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("hub.media_db")

DEFAULT_DB_PATH = "/data/sqlite/media.db"
KEY_RE = re.compile(r"^(tmdb|tvdb|jf):[A-Za-z0-9-]+$")

RATING_DDL = """CREATE TABLE rating(
  item_key TEXT, kind TEXT, title TEXT, year INT, poster TEXT,
  score INT CHECK(score BETWEEN 1 AND 10), rated_at TEXT, owner TEXT NOT NULL DEFAULT 'you',
  PRIMARY KEY(item_key, owner))"""
DIARY_DDL = """CREATE TABLE diary(
  id INTEGER PRIMARY KEY, item_key TEXT, kind TEXT, title TEXT, year INT, poster TEXT,
  watched_on TEXT, source TEXT, place TEXT, note TEXT, owner TEXT NOT NULL DEFAULT 'you', created_at TEXT,
  UNIQUE(item_key, watched_on, source, owner))"""
RATING_COLS = "item_key, kind, title, year, poster, score, rated_at"
DIARY_COLS = "id, item_key, kind, title, year, poster, watched_on, source, place, note, created_at"
SCHEMA = RATING_DDL.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS") + """;
""" + DIARY_DDL.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS") + """;
CREATE TABLE IF NOT EXISTS ranking(
  year INTEGER, item_key TEXT, position INTEGER, kind TEXT, title TEXT, poster TEXT,
  owner TEXT DEFAULT 'you', PRIMARY KEY(year, item_key), UNIQUE(year, position));
"""


def db_path() -> Path:
    return Path(os.environ.get("MEDIA_DB_PATH", DEFAULT_DB_PATH))


def owner_of(view: str) -> str:
    """The data owner behind an owner view: 'her' sees her own rows, anything else is B.'s."""
    return "her" if view == "her" else "you"


def _old_shapes(db) -> tuple[bool, bool]:
    """(rating, diary) still in the pre-owner shape: rating keyed by item_key alone,
    diary UNIQUE without owner. Absent tables count as new."""
    pk = [r["name"] for r in db.execute("PRAGMA table_info(rating)") if r["pk"]]
    row = db.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'diary'").fetchone()
    return pk == ["item_key"], bool(row) and "source, owner)" not in row["sql"]


def _migrate(db) -> None:
    """Idempotent, run on every connect: rebuild a pre-owner rating/diary table in the new
    shape, every row kept as owner 'you'. Cheap no-op once migrated; one transaction."""
    if not any(_old_shapes(db)):
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        old_rating, old_diary = _old_shapes(db)  # re-check under the lock (another process may have won)
        for old, table, ddl, cols in ((old_rating, "rating", RATING_DDL, RATING_COLS),
                                      (old_diary, "diary", DIARY_DDL, DIARY_COLS)):
            if old:
                db.execute(f"ALTER TABLE {table} RENAME TO {table}_old")
                db.execute(ddl)
                db.execute(f"INSERT INTO {table}({cols}, owner) "
                           f"SELECT {cols}, COALESCE(owner, 'you') FROM {table}_old")
                db.execute(f"DROP TABLE {table}_old")
        db.commit()
    except Exception:
        db.rollback()
        raise


def connect() -> sqlite3.Connection:
    """Open the DB, creating the parent dir and schema if missing."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=5000")
    _migrate(db)
    db.executescript(SCHEMA)
    return db


def _read():
    """A connection for reading, or None when there is no DB yet / it can't be opened."""
    if not db_path().is_file():
        return None
    try:
        return connect()
    except (sqlite3.Error, OSError) as exc:
        log.warning("media db unreadable: %s", type(exc).__name__)
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def norm_kind(kind) -> str:
    """Two kinds only: Jellyfin's 'episode' and Jellyseerr's 'tv' both mean TV."""
    return "movie" if kind == "movie" else "tv"


def get_ratings(keys, owner: str = "you") -> dict[str, int]:
    keys = sorted({k for k in keys if k})
    db = _read() if keys else None
    if db is None:
        return {}
    try:
        with closing(db):
            marks = ",".join("?" * len(keys))
            return {r["item_key"]: r["score"] for r in
                    db.execute(f"SELECT item_key, score FROM rating WHERE owner = ? AND item_key IN ({marks})",
                               [owner, *keys])}
    except sqlite3.Error as exc:
        log.warning("get_ratings failed: %s", type(exc).__name__)
        return {}


def get_rating(item_key: str, owner: str = "you") -> dict | None:
    db = _read()
    if db is None:
        return None
    try:
        with closing(db):
            row = db.execute("SELECT * FROM rating WHERE item_key = ? AND owner = ?",
                             (item_key, owner)).fetchone()
            return dict(row) if row else None
    except sqlite3.Error as exc:
        log.warning("get_rating failed: %s", type(exc).__name__)
        return None


def set_rating(item_key: str, score: int, kind: str, title: str, year=None, poster=None,
               owner: str = "you") -> None:
    with closing(connect()) as db, db:
        db.execute(
            "INSERT INTO rating(item_key, kind, title, year, poster, score, rated_at, owner) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(item_key, owner) DO UPDATE SET "
            "kind=excluded.kind, title=excluded.title, year=excluded.year, poster=excluded.poster, "
            "score=excluded.score, rated_at=excluded.rated_at",
            (item_key, norm_kind(kind), title, year, poster, score, _now().isoformat(), owner))


def delete_rating(item_key: str, owner: str = "you") -> None:
    if not db_path().is_file():
        return
    with closing(connect()) as db, db:
        db.execute("DELETE FROM rating WHERE item_key = ? AND owner = ?", (item_key, owner))


def base_title(title: str, kind: str) -> str:
    """A history row title is 'Show · S02E04 · Episode'; the diary is per show."""
    return title.split(" · ")[0] if kind == "tv" else title


def _local_date(stamp: str) -> str:
    text = re.sub(r"(\.\d{6})\d+", r"\1", str(stamp).replace("Z", "+00:00"))
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().date().isoformat()


def sync_diary_from_history(recent_rows, owner: str = "you") -> int:
    """Insert Jellyfin history rows not yet in the diary (idempotent via UNIQUE:
    one entry per item_key per day, so a binge of one show is one line).
    Returns the number inserted; never raises — a bad row or DB just inserts less."""
    rows = []
    for r in recent_rows or []:
        try:
            if not (r.get("item_key") and KEY_RE.match(r["item_key"])):
                continue
            kind = norm_kind(r.get("kind"))
            rows.append((r["item_key"], kind, base_title(r["title"], kind), None, r.get("poster"),
                         _local_date(r["watched_at"])))
        except Exception:
            continue
    if not rows:
        return 0
    try:
        with closing(connect()) as db, db:
            before = db.total_changes
            db.executemany(
                "INSERT OR IGNORE INTO diary(item_key, kind, title, year, poster, watched_on, source, "
                "created_at, owner) VALUES(?,?,?,?,?,?, 'jellyfin', ?, ?)",
                [(*r, _now().isoformat(), owner) for r in rows])
            return db.total_changes - before
    except (sqlite3.Error, OSError) as exc:
        log.warning("diary sync failed: %s", type(exc).__name__)
        return 0


def add_manual_watch(item_key: str, kind: str, title: str, year=None, poster=None,
                     watched_on: str | None = None, place: str | None = None,
                     note: str | None = None, owner: str = "you") -> dict | None:
    """Log a watch by hand. Returns the stored row, or None when it was already logged."""
    watched_on = watched_on or date.today().isoformat()
    with closing(connect()) as db, db:
        cur = db.execute(
            "INSERT OR IGNORE INTO diary(item_key, kind, title, year, poster, watched_on, source, place, "
            "note, created_at, owner) VALUES(?,?,?,?,?,?, 'manual', ?,?,?,?)",
            (item_key, norm_kind(kind), title, year, poster, watched_on, place or None, note or None,
             _now().isoformat(), owner))
        if not cur.rowcount:
            return None
        return dict(db.execute("SELECT * FROM diary WHERE id = ?", (cur.lastrowid,)).fetchone())


def list_diary(limit: int = 50, offset: int = 0, kind: str | None = None,
               owner: str = "you") -> list[dict]:
    """Newest first. `kind` is 'movie' or 'tv' (anything else = all)."""
    db = _read()
    if db is None:
        return []
    where, args = (("WHERE owner = ? AND kind = ?", [owner, kind]) if kind in ("movie", "tv")
                   else ("WHERE owner = ?", [owner]))
    try:
        with closing(db):
            return [dict(r) for r in db.execute(
                f"SELECT * FROM diary {where} ORDER BY watched_on DESC, id DESC LIMIT ? OFFSET ?",
                [*args, limit, offset])]
    except sqlite3.Error as exc:
        log.warning("list_diary failed: %s", type(exc).__name__)
        return []


def diary_stats(now: datetime | None = None, owner: str = "you") -> dict:
    """{this_week, this_month, total, streak_days, milestones}. Week/month are the
    last 7/30 days; the streak is consecutive days with a watch, ending today or
    yesterday; milestones are every 100th watch and the first watch of each year."""
    empty = {"this_week": 0, "this_month": 0, "total": 0, "streak_days": 0, "milestones": []}
    db = _read()
    if db is None:
        return empty
    today = (now or datetime.now().astimezone()).date()
    try:
        with closing(db):
            rows = [(r["watched_on"], r["title"]) for r in
                    db.execute("SELECT watched_on, title FROM diary WHERE owner = ? ORDER BY watched_on, id", (owner,))]
    except sqlite3.Error as exc:
        log.warning("diary_stats failed: %s", type(exc).__name__)
        return empty
    days = {d for d, _ in rows}
    week, month = (today - timedelta(days=7)).isoformat(), (today - timedelta(days=30)).isoformat()
    day = today if today.isoformat() in days else today - timedelta(days=1)
    streak = 0
    while day.isoformat() in days:
        streak += 1
        day -= timedelta(days=1)
    milestones, years = [], set()
    for n, (watched_on, title) in enumerate(rows, 1):
        if watched_on[:4] not in years:
            years.add(watched_on[:4])
            milestones.append(f"First watch of {watched_on[:4]}: {title}")
        if n % 100 == 0:
            milestones.append(f"Watch number {n}: {title}")
    return {"this_week": sum(1 for d, _ in rows if d > week),
            "this_month": sum(1 for d, _ in rows if d > month),
            "total": len(rows), "streak_days": streak, "milestones": milestones[::-1]}



# ---- Year rankings (2026-10-05): B.'s own order per rating year. Positions stay
# contiguous from 1. A rating with no year lives in the year-0 bucket here and is
# reported as year None ("Unknown year") everywhere outside this block.

def _yk(year) -> int:
    return year or 0


def _renumber(db, year: int, keys: list[str]) -> None:
    """Rewrite positions 1..n for `keys` (two passes: the UNIQUE(year, position) can't swap in place)."""
    db.execute("UPDATE ranking SET position = -position WHERE year = ?", (year,))
    db.executemany("UPDATE ranking SET position = ? WHERE year = ? AND item_key = ?",
                   [(n, year, k) for n, k in enumerate(keys, 1)])


def _order(db, year: int) -> list[str]:
    return [r["item_key"] for r in db.execute(
        "SELECT item_key FROM ranking WHERE year = ? ORDER BY position", (year,))]


def years_overview() -> list[dict]:
    """[{year, ranked_count, unranked_count, top}] newest first, year None (unknown) last."""
    db = _read()
    if db is None:
        return []
    try:
        with closing(db):
            rated = {_yk(r["y"]): r["n"] for r in db.execute(
                "SELECT year AS y, COUNT(*) AS n FROM rating WHERE owner = 'you' GROUP BY year")}
            unranked = {_yk(r["y"]): r["n"] for r in db.execute(
                "SELECT year AS y, COUNT(*) AS n FROM rating WHERE owner = 'you' AND item_key NOT IN "
                "(SELECT item_key FROM ranking WHERE ranking.year = COALESCE(rating.year, 0)) GROUP BY year")}
            ranked = {r["year"]: r["n"] for r in db.execute(
                "SELECT year, COUNT(*) AS n FROM ranking GROUP BY year")}
            tops = {r["year"]: {"title": r["title"], "poster": r["poster"], "item_key": r["item_key"]}
                    for r in db.execute("SELECT year, title, poster, item_key FROM ranking WHERE position = 1")}
    except sqlite3.Error as exc:
        log.warning("years_overview failed: %s", type(exc).__name__)
        return []
    years = sorted(set(rated) | set(ranked), key=lambda y: (y == 0, -y))
    return [{"year": y or None, "ranked_count": ranked.get(y, 0), "unranked_count": unranked.get(y, 0),
             "top": tops.get(y)} for y in years]


def year_list(year) -> dict:
    """{ranked: by position, unranked: the year's rated-but-unplaced, best score first}."""
    empty = {"ranked": [], "unranked": []}
    db = _read()
    if db is None:
        return empty
    y = _yk(year)
    try:
        with closing(db):
            ranked = [dict(r) for r in db.execute(
                "SELECT r.item_key, r.kind, r.title, r.poster, r.position, g.score FROM ranking r "
                "LEFT JOIN rating g ON g.item_key = r.item_key AND g.owner = 'you' "
                "WHERE r.year = ? ORDER BY r.position", (y,))]
            unranked = [dict(r) for r in db.execute(
                "SELECT item_key, kind, title, poster, score FROM rating WHERE owner = 'you' AND year IS ? AND item_key NOT IN "
                "(SELECT item_key FROM ranking WHERE year = ?) ORDER BY score DESC, title", (year, y))]
            return {"ranked": ranked, "unranked": unranked}
    except sqlite3.Error as exc:
        log.warning("year_list failed: %s", type(exc).__name__)
        return empty


def place(year, item_key: str, position: int | None = None) -> bool:
    """Rank a rated item of `year` (append, or insert at `position` shifting the rest down).
    False when the item isn't rated in that year; already-placed items are left alone."""
    y = _yk(year)
    with closing(connect()) as db, db:
        row = db.execute("SELECT kind, title, poster FROM rating WHERE item_key = ? AND owner = 'you' AND year IS ?",
                         (item_key, year)).fetchone()
        if row is None:
            return False
        keys = _order(db, y)
        if item_key in keys:
            return True
        at = len(keys) if position is None else max(0, min(position - 1, len(keys)))
        db.execute("INSERT INTO ranking(year, item_key, position, kind, title, poster, owner) "
                   "VALUES(?,?,?,?,?,?, 'you')", (y, item_key, -10**9, row["kind"], row["title"], row["poster"]))
        keys.insert(at, item_key)
        _renumber(db, y, keys)
        return True


def move(year, item_key: str, delta: int) -> None:
    """Swap with the neighbour above (delta<0) or below (delta>0); clamped at the ends."""
    if not db_path().is_file():
        return
    y = _yk(year)
    with closing(connect()) as db, db:
        keys = _order(db, y)
        if item_key not in keys:
            return
        i = keys.index(item_key)
        j = max(0, min(len(keys) - 1, i + (1 if delta > 0 else -1)))
        keys[i], keys[j] = keys[j], keys[i]
        _renumber(db, y, keys)


def unplace(year, item_key: str) -> None:
    if not db_path().is_file():
        return
    y = _yk(year)
    with closing(connect()) as db, db:
        db.execute("DELETE FROM ranking WHERE year = ? AND item_key = ?", (y, item_key))
        _renumber(db, y, _order(db, y))


def reset_year(year) -> None:
    if not db_path().is_file():
        return
    with closing(connect()) as db, db:
        db.execute("DELETE FROM ranking WHERE year = ?", (_yk(year),))
