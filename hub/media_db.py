"""Ratings + watch diary (2026-10-05) — the hub's FIRST write path, one small SQLite
file (`MEDIA_DB_PATH`, default /data/sqlite/media.db). Ratings and the diary carry an
owner: `you` (B.) or `her` (Georgina's Jellyfin user, 2026-10-05).

Reads never create the file: with no DB present the pages render empty and
`get_ratings` answers {}. Only a write (rating, manual log, diary sync with rows
to insert) creates the directory and schema, on first use. Opening and the versioned
schema live in hub/media_store.py (W2, 2026-10-09); SCHEMA and _migrate stay here.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from hub import media_store, media_text

log = logging.getLogger("hub.media_db")

DEFAULT_DB_PATH = media_store.DEFAULT_DB_PATH
KEY_RE = re.compile(r"^(tmdb|tvdb|jf):[A-Za-z0-9-]+$")

RATING_DDL = """CREATE TABLE rating(
  item_key TEXT, kind TEXT, title TEXT, year INT, poster TEXT,
  score INT CHECK(score BETWEEN 1 AND 10), rated_at TEXT, owner TEXT NOT NULL DEFAULT 'you',
  level TEXT NOT NULL DEFAULT 'show', PRIMARY KEY(item_key, owner))"""
LEVELS = ("show", "season", "episode")  # what a rating covers; movies record 'show' = the whole title
DIARY_DDL = """CREATE TABLE diary(
  id INTEGER PRIMARY KEY, item_key TEXT, kind TEXT, title TEXT, year INT, poster TEXT,
  watched_on TEXT, source TEXT, place TEXT, note TEXT, owner TEXT NOT NULL DEFAULT 'you', created_at TEXT,
  show_key TEXT, season_key TEXT, season INT, episode INT, show_title TEXT, episode_title TEXT,
  UNIQUE(item_key, watched_on, source, owner))"""
DIARY_EXTRA = (("show_key", "TEXT"), ("season_key", "TEXT"), ("season", "INT"), ("episode", "INT"),
               ("show_title", "TEXT"), ("episode_title", "TEXT"))  # per-episode diary rows (F8)
RATING_COLS = "item_key, kind, title, year, poster, score, rated_at"
DIARY_COLS = "id, item_key, kind, title, year, poster, watched_on, source, place, note, created_at"
SCHEMA = RATING_DDL.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS") + """;
""" + DIARY_DDL.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS") + """;
CREATE TABLE IF NOT EXISTS setting(
  owner TEXT, key TEXT, value TEXT, PRIMARY KEY(owner, key));
CREATE TABLE IF NOT EXISTS ranking(
  year INTEGER, item_key TEXT, position INTEGER, kind TEXT, title TEXT, poster TEXT,
  owner TEXT DEFAULT 'you', PRIMARY KEY(year, item_key), UNIQUE(year, position));
CREATE TABLE IF NOT EXISTS nextup_hidden(
  owner TEXT, series_key TEXT, episode_id TEXT, hidden_at TEXT, PRIMARY KEY(owner, series_key));
"""


# To rate: Skip / Skip show (E5, M3, 2026-10-13; media.db user_version 4, media_store.STEPS). One row per owner + key:
# `key` is the inbox row's rating key (Skip) or the show's key (Skip show, forever = 1: every season and episode of it,
# later ones too). `kind` is movie / tv; title + poster let the To rate page list what was skipped without a read.
SKIP_DDL = """CREATE TABLE IF NOT EXISTS rating_skip(
  owner TEXT NOT NULL, key TEXT NOT NULL, kind TEXT, forever INT NOT NULL DEFAULT 0, created_at TEXT,
  title TEXT, poster TEXT, PRIMARY KEY(owner, key))"""


def migrate_skip(db) -> None:
    """media.db step 4 (E5): the rating_skip table. Idempotent."""
    db.execute(SKIP_DDL)
    db.commit()


def db_path() -> Path:
    return media_store.db_path()


def owner_of(view: str) -> str:
    """The data owner behind an owner view: 'her' sees her own rows, anything else is B.'s."""
    return "her" if view == "her" else "you"


def owner_filter(view: str) -> str | None:
    """The owner a cross-owner read filters on: 'you' / 'her', or None for the 'both' view (everyone's rows)."""
    return view if view in ("you", "her") else None


def _old_shapes(db) -> tuple[bool, bool]:
    """(rating, diary) still in the pre-owner shape: rating keyed by item_key alone,
    diary UNIQUE without owner. Absent tables count as new."""
    pk = [r["name"] for r in db.execute("PRAGMA table_info(rating)") if r["pk"]]
    row = db.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'diary'").fetchone()
    return pk == ["item_key"], bool(row) and "source, owner)" not in row["sql"]


def _add_level_column(db) -> None:
    """Rating gained `level` (2026-10-06): ALTER an existing table that lacks it; existing
    rows read 'show'. A missing table is left for SCHEMA to create. Safe to race: a lost
    race raises 'duplicate column', which is swallowed."""
    cols = [r["name"] for r in db.execute("PRAGMA table_info(rating)")]
    if cols and "level" not in cols:
        try:
            db.execute("ALTER TABLE rating ADD COLUMN level TEXT NOT NULL DEFAULT 'show'")
            db.commit()
        except sqlite3.OperationalError as exc:
            if "duplicate column" not in str(exc):
                raise


def _add_diary_columns(db) -> None:
    """The diary went per-episode (F8, 2026-10-06): ALTER an existing table that lacks the
    episode columns; old rows keep NULLs and render as show-level lines. Race-safe like
    _add_level_column. A missing table is left for SCHEMA to create."""
    cols = [r["name"] for r in db.execute("PRAGMA table_info(diary)")]
    if not cols:
        return
    for name, typ in DIARY_EXTRA:
        if name not in cols:
            try:
                db.execute(f"ALTER TABLE diary ADD COLUMN {name} {typ}")
                db.commit()
            except sqlite3.OperationalError as exc:
                if "duplicate column" not in str(exc):
                    raise


def _migrate(db) -> None:
    """Idempotent, run by media_store's baseline step (once per file per process): rebuild a pre-owner rating/diary table in the new
    shape, every row kept as owner 'you'. Cheap no-op once migrated; one transaction."""
    _add_level_column(db)
    _add_diary_columns(db)
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
    """Open the DB for a write, creating the parent dir and schema if missing (media_store)."""
    return media_store.connect()


def _read():
    """A connection for reading, or None when there is no DB yet / it can't be opened (media_store)."""
    return media_store.reader()


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
               owner: str = "you", level: str = "show") -> None:
    level = level if level in LEVELS else "show"
    with closing(connect()) as db, db:
        db.execute(
            "INSERT INTO rating(item_key, kind, title, year, poster, score, rated_at, owner, level) "
            "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(item_key, owner) DO UPDATE SET "
            "kind=excluded.kind, title=excluded.title, year=excluded.year, poster=excluded.poster, "
            "score=excluded.score, rated_at=excluded.rated_at, level=excluded.level",
            (item_key, norm_kind(kind), title, year, poster, score, _now().isoformat(), owner, level))


def get_setting(owner: str, key: str, default=None):
    db = _read()
    if db is None:
        return default
    try:
        with closing(db):
            row = db.execute("SELECT value FROM setting WHERE owner = ? AND key = ?", (owner, key)).fetchone()
            return row["value"] if row else default
    except sqlite3.Error as exc:
        log.warning("get_setting failed: %s", type(exc).__name__)
        return default


def set_setting(owner: str, key: str, value: str) -> None:
    with closing(connect()) as db, db:
        db.execute("INSERT INTO setting(owner, key, value) VALUES(?,?,?) "
                   "ON CONFLICT(owner, key) DO UPDATE SET value = excluded.value", (owner, key, value))


def hide_next_up(owner: str, series_key: str, episode_id: str) -> None:
    """Hide a Next Up suggestion (media-ux2, 2026-10-08): one row per owner + series, the suggested episode it hid.
    Hiding again (a later suggestion) replaces it."""
    with closing(connect()) as db, db:
        db.execute("INSERT INTO nextup_hidden(owner, series_key, episode_id, hidden_at) VALUES(?,?,?,?) "
                   "ON CONFLICT(owner, series_key) DO UPDATE SET episode_id = excluded.episode_id, "
                   "hidden_at = excluded.hidden_at", (owner, series_key, str(episode_id), _now().isoformat()))


def next_up_hidden() -> dict[tuple[str, str], str]:
    """{(owner, series_key): hidden episode id}; {} with no DB (reads never create it) or on any error."""
    db = _read()
    if db is None:
        return {}
    try:
        with closing(db):
            return {(r["owner"], r["series_key"]): r["episode_id"]
                    for r in db.execute("SELECT owner, series_key, episode_id FROM nextup_hidden")}
    except sqlite3.Error as exc:
        log.warning("next_up_hidden failed: %s", type(exc).__name__)
        return {}


DIARY_SCOPES = ("mine", "everyone")  # the diary's "Show" choice (2026-10-13); only owner 'you' may pick everyone


def diary_scope(owner: str) -> str:
    """The owner's diary scope: 'everyone' only for owner 'you' who set it; 'mine' otherwise (her: always mine)."""
    value = get_setting(owner, "diary_scope", "mine") if owner == "you" else "mine"
    return value if value in DIARY_SCOPES else "mine"


def rating_level(owner: str) -> str:
    """The owner's 'Rate TV by' choice; show unless set to season or episode."""
    value = get_setting(owner, "rating_level", "show")
    return value if value in LEVELS else "show"


def delete_rating(item_key: str, owner: str = "you") -> None:
    if not db_path().is_file():
        return
    with closing(connect()) as db, db:
        db.execute("DELETE FROM rating WHERE item_key = ? AND owner = ?", (item_key, owner))


def skip(owner: str, key: str, kind: str, title: str, poster=None, forever: bool = False) -> None:
    """Skip an inbox entry (forever = the whole show). Skipping again replaces the row (a later Skip show widens it)."""
    with closing(connect()) as db, db:
        db.execute("INSERT INTO rating_skip(owner, key, kind, forever, created_at, title, poster) VALUES(?,?,?,?,?,?,?) "
                   "ON CONFLICT(owner, key) DO UPDATE SET kind = excluded.kind, forever = excluded.forever, "
                   "created_at = excluded.created_at, title = excluded.title, poster = excluded.poster",
                   (owner, key, norm_kind(kind), 1 if forever else 0, _now().isoformat(), title, poster))


def unskip(owner: str, key: str) -> None:
    if not db_path().is_file():
        return
    with closing(connect()) as db, db:
        db.execute("DELETE FROM rating_skip WHERE owner = ? AND key = ?", (owner, key))


def skips(owner: str) -> list[dict]:
    """The owner's skipped entries, newest first; [] with no DB (reads never create it) or on any error."""
    db = _read()
    if db is None:
        return []
    try:
        with closing(db):
            return [dict(r) for r in db.execute(
                "SELECT key, kind, forever, created_at, title, poster FROM rating_skip WHERE owner = ? "
                "ORDER BY created_at DESC, key", (owner,))]
    except sqlite3.Error as exc:
        log.warning("skips read failed: %s", type(exc).__name__)
        return []


def base_title(title: str, kind: str) -> str:
    """A history row title is 'Show · S02E04 · Episode'; the diary is per show."""
    return title.split(" · ")[0] if kind == "tv" else title


def _local_date(stamp: str) -> str:
    dt = media_text.parse(stamp)
    if dt is None:
        raise ValueError("not a timestamp")
    return dt.astimezone().date().isoformat()


def _episode_name(title: str) -> str | None:
    """'Show · S02E04 · Episode' -> 'Episode' (None when the title has no third part)."""
    parts = str(title).split(" · ", 2)
    return parts[2] if len(parts) == 3 and parts[2] else None


def sync_diary_from_history(recent_rows, owner: str = "you") -> int:
    """Insert Jellyfin history rows not yet in the diary (idempotent via UNIQUE).
    An episode row is keyed by its episode_key (one row per episode per day, F8) and
    carries show/season/episode columns; without an episode key it falls back to the
    show key (one row per show per day). Films are unchanged.
    Returns the number inserted; never raises — a bad row or DB just inserts less."""
    rows = []
    for r in recent_rows or []:
        try:
            if not (r.get("item_key") and KEY_RE.match(r["item_key"])):
                continue
            kind = norm_kind(r.get("kind"))
            key = r["item_key"]
            show_key = season_key = season = episode = show_title = ep_title = None
            ek = r.get("episode_key")
            if kind == "tv" and ek and KEY_RE.match(ek):
                key, show_key = ek, r.get("show_key") or r["item_key"]
                season_key, season, episode = r.get("season_key"), r.get("season"), r.get("episode")
                show_title = r.get("show_title") or base_title(r["title"], kind)
                ep_title = _episode_name(r["title"])
            rows.append((key, kind, base_title(r["title"], kind), None, r.get("poster"),
                         _local_date(r["watched_at"]), show_key, season_key, season, episode,
                         show_title, ep_title))
        except Exception:
            continue
    if not rows:
        return 0
    try:
        with closing(connect()) as db, db:
            before = db.total_changes
            db.executemany(
                "INSERT OR IGNORE INTO diary(item_key, kind, title, year, poster, watched_on, "
                "show_key, season_key, season, episode, show_title, episode_title, source, "
                "created_at, owner) VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'jellyfin', ?, ?)",
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
               owner: str | None = "you") -> list[dict]:
    """Newest first. `kind` is 'movie' or 'tv' (anything else = all). `owner` None = every owner's rows (the
    diary's "Show: Everyone" scope, 2026-10-13); each row keeps its own `owner` column."""
    db = _read()
    if db is None:
        return []
    conds, args = [], []
    if owner is not None:
        conds.append("d.owner = ?")
        args.append(owner)
    if kind in ("movie", "tv"):
        conds.append("d.kind = ?")
        args.append(kind)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    try:
        with closing(db):
            return [dict(r) for r in db.execute(
                f"SELECT d.*, CASE WHEN (d.kind = 'movie' OR d.season IS NOT NULL) AND EXISTS("
                f"SELECT 1 FROM diary p WHERE p.owner = d.owner AND p.item_key = d.item_key "
                f"AND p.watched_on < d.watched_on) THEN 1 ELSE 0 END AS rewatch "
                f"FROM diary d {where} ORDER BY d.watched_on DESC, d.id DESC LIMIT ? OFFSET ?",
                [*args, limit, offset])]
    except sqlite3.Error as exc:
        log.warning("list_diary failed: %s", type(exc).__name__)
        return []


def diary_dates(owner: str, item_keys=(), show_key: str | None = None, season_key: str | None = None,
                limit: int = 8) -> list[str]:
    """The newest `limit` watch dates (ISO, newest first) of one title for the film page (M-36): rows whose item_key
    is one of `item_keys`, or whose show_key / season_key matches. One SELECT; [] with no DB or on any error."""
    conds, args = [], [owner]
    keys = [k for k in item_keys if k]
    if keys:
        conds.append(f"item_key IN ({','.join('?' * len(keys))})")
        args += keys
    for col, value in (("show_key", show_key), ("season_key", season_key)):
        if value:
            conds.append(f"{col} = ?")
            args.append(value)
    db = _read() if conds else None
    if db is None:
        return []
    try:
        with closing(db):
            return [r[0] for r in db.execute(
                f"SELECT watched_on FROM diary WHERE owner = ? AND ({' OR '.join(conds)}) AND watched_on IS NOT NULL"
                f" ORDER BY watched_on DESC, id DESC LIMIT ?", [*args, limit])]
    except sqlite3.Error as exc:
        log.warning("diary dates failed: %s", type(exc).__name__)
        return []


def _episode_runs(numbers) -> str:
    """[1, 2, 3, 7] -> 'E1–E3, E7' (runs of consecutive numbers collapse)."""
    nums = sorted(set(numbers))
    parts, i = [], 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        parts.append(f"E{nums[i]}" if j == i else f"E{nums[i]}–E{nums[j]}")
        i = j + 1
    return ", ".join(parts)


def group_diary(rows) -> list[dict]:
    """Fold a day's episode rows of one (show, season) into one line (F8). Films and
    show-level / hand-logged rows stay one line each. Order follows the first row of each
    line. A line carries item_key/show_key/season_key so score_for can pick its chip."""
    lines: dict = {}
    for r in rows:
        ep = r.get("season") is not None and bool(r.get("show_key"))
        gk = (r["watched_on"], r["show_key"], r["season"], r.get("owner")) if ep else ("row", r["id"])
        line = lines.get(gk)
        if line is None:
            line = lines[gk] = {
                "title": (r.get("show_title") or r["title"]) if ep else r["title"],
                "kind": r["kind"], "watched_on": r["watched_on"], "poster": r.get("poster"),
                "year": r.get("year"), "source": r.get("source"), "place": r.get("place"),
                "item_key": r["show_key"] if ep else r["item_key"],
                "show_key": r["show_key"] if ep else None, "season_key": r.get("season_key") if ep else None,
                "season": r.get("season"), "numbers": [], "episodes": [], "count": 0, "rewatch": False,
                "sub": "", "owner": r.get("owner")}
        line["count"] += 1
        line["rewatch"] = line["rewatch"] or bool(r.get("rewatch"))
        if r.get("episode") is not None:
            line["numbers"].append(r["episode"])
        if r.get("episode_title"):
            line["episodes"].append((r.get("episode") or 0, r["episode_title"]))
    for line in lines.values():
        nums = line.pop("numbers")
        line["episodes"] = [name for _, name in sorted(line["episodes"])]
        if line["season"] is not None:
            line["sub"] = f"S{line['season']} {_episode_runs(nums)}" if nums else f"S{line['season']}"
    return list(lines.values())


def diary_signature(owner: str = "you") -> tuple[int, int]:
    """(row count, newest id) of the owner's diary - what changes whenever a row is added (rows are never edited or
    deleted). (0, 0) with no DB or on any error."""
    db = _read()
    if db is None:
        return (0, 0)
    try:
        with closing(db):
            row = db.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM diary WHERE owner = ?", (owner,)).fetchone()
            return (row[0], row[1])
    except sqlite3.Error as exc:
        log.warning("diary_signature failed: %s", type(exc).__name__)
        return (0, 0)


def diary_stats(now: datetime | None = None, owner: str = "you") -> dict:
    """{this_week, this_month, total, streak_days, milestones}. Week/month are the
    last 7/30 days; the streak is consecutive days with a watch, ending today or
    yesterday; milestones are every 100th watch and the first watch of each year."""
    empty = {"this_week": 0, "this_month": 0, "total": 0, "streak_days": 0, "milestones": [],
             "year_films": 0, "year_episodes": 0}
    db = _read()
    if db is None:
        return empty
    today = (now or datetime.now().astimezone()).date()
    try:
        with closing(db):
            full = db.execute("SELECT watched_on, title, kind FROM diary WHERE owner = ? ORDER BY watched_on, id",
                              (owner,)).fetchall()
            rows = [(r["watched_on"], r["title"]) for r in full]
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
    year = str(today.year)
    return {"year_films": sum(1 for r in full if r["kind"] == "movie" and r["watched_on"][:4] == year),
            "year_episodes": sum(1 for r in full if r["kind"] == "tv" and r["watched_on"][:4] == year),
            "this_week": sum(1 for d, _ in rows if d > week),
            "this_month": sum(1 for d, _ in rows if d > month),
            "total": len(rows), "streak_days": streak, "milestones": milestones[::-1]}
