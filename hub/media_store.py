"""media.db, opened in one place (W2, 2026-10-09; M-11, M-33, M-34).

media_db, media_plays_db, media_watchlist_db, media_follow and media_awards_db used to open the file five ways, and
every open re-ran the schema: media_db's rebuild checks + SCHEMA, then that module's own DDL (awards: 14 statements
and a seed check). Now:

  * `connect()` opens the file (creating its folder) for a write; `reader()` opens it for a read — None when there
    is no file yet (reads never create it) or it can't be opened (a word, never a 500).
  * The schema is versioned with `PRAGMA user_version`. The first open of a file in a process brings it up to
    SCHEMA_VERSION through STEPS (each idempotent, so a pre-versioning file at 0 is simply re-checked) and checks
    the awards seed; later opens of that file run no DDL at all. "That file" is its resolved path + device + inode
    (tests switch MEDIA_DB_PATH per test; a restored backup is a new inode, so it is checked again).
  * The tables' DDL stays beside the code that owns it (media_db.SCHEMA, media_plays_db.DDL, ...); STEPS reads it
    from there.
  * `ranking` (media_db.SCHEMA): retained, unused since 2026-10-09 — the By-year rankings were removed (decision 1);
    its rows stay in media.db so the feature can come back.
  * E1 (2026-10-13): `reader()` hands each thread ONE kept connection, reused across every read of every request that
    thread serves (a Media page used to open 5-10, each paying connect + schema re-read + the WAL close checkpoint).
    Its close() only ends any open transaction, so `with closing(db)` callers are unchanged; it is replaced when the
    file's identity changes (a test's new MEDIA_DB_PATH, a restored backup) and closed when its thread ends or on
    `reset()`. Writes keep `connect()`: a fresh connection each, closed after.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import weakref
from pathlib import Path

log = logging.getLogger("hub.media_store")

DEFAULT_DB_PATH = "/data/sqlite/media.db"
BUSY_MS = 5000
READER_CACHE_KIB = 1024   # page cache per kept reader (SQLite's default is 2000 KiB; up to ~40 threads keep one)

INDEXES = (   # step 2 (M-34): the per-page queries' own indexes
    "CREATE INDEX IF NOT EXISTS diary_owner_watched ON diary(owner, watched_on)",
    "CREATE INDEX IF NOT EXISTS play_owner_started ON play(owner, started_at)",
    "CREATE INDEX IF NOT EXISTS play_jf_finished ON play(jf_id, finished)",
)


def db_path() -> Path:
    return Path(os.environ.get("MEDIA_DB_PATH", DEFAULT_DB_PATH))


def _baseline(db) -> None:
    """Step 1: every table the Media modules own, as they stood before versioning (all IF NOT EXISTS / checked
    ALTERs), plus media_db's pre-owner rebuild."""
    from hub import media_awards_db, media_db, media_follow, media_plays_db, media_watchlist_db

    media_db._migrate(db)
    db.executescript(media_db.SCHEMA)
    for ddl in (*media_plays_db.DDL, media_watchlist_db.DDL, *media_follow.DDL, *media_awards_db.DDL):
        db.execute(ddl)
    db.commit()


def _indexes(db) -> None:
    for ddl in INDEXES:
        db.execute(ddl)
    db.commit()


def _follow_shows(db) -> None:
    from hub import media_follow
    media_follow.migrate_shows(db)


def _rating_skip(db) -> None:
    from hub import media_db
    media_db.migrate_skip(db)


STEPS = (_baseline, _indexes, _follow_shows, _rating_skip)   # STEPS[n] takes a file from user_version n to n + 1
SCHEMA_VERSION = len(STEPS)

_ready: set[tuple] = set()      # files already brought up to date by this process
_lock = threading.Lock()


def _file_key(path: Path) -> tuple:
    st = path.stat()
    return str(path.resolve()), st.st_dev, st.st_ino or st.st_ctime_ns


def migrate(db) -> int:
    """Bring an open connection's file up to SCHEMA_VERSION; returns the version it started at. Idempotent."""
    start = db.execute("PRAGMA user_version").fetchone()[0]
    if start < SCHEMA_VERSION:
        db.execute("PRAGMA journal_mode=WAL")   # persistent in the file: set once, not per open
        for step in STEPS[start:]:
            step(db)
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        db.commit()
    from hub import media_awards_db
    media_awards_db.apply_seed(db)   # a read unless the code's awards seed version moved on
    return start


class _Kept(sqlite3.Connection):
    """A thread's kept reader: close() ends any open transaction and keeps the connection; _shut() really closes."""

    shut = False

    def close(self) -> None:
        if not self.shut:
            try:
                self.rollback()
            except sqlite3.Error:
                pass

    def _shut(self) -> None:
        self.shut = True
        try:
            super().close()
        except sqlite3.Error:
            pass


_local = threading.local()                  # .held = (generation, file key, _Kept)
_all_kept: "weakref.WeakSet[_Kept]" = weakref.WeakSet()   # every live kept reader, for reset(); a dead thread's goes
_gen = [0]


def _open(path: Path, kept: bool = False) -> sqlite3.Connection:
    if kept:   # any thread may _shut() it (reset), so the same-thread check is off; only its own thread queries it
        db = sqlite3.connect(path, timeout=BUSY_MS / 1000, factory=_Kept, check_same_thread=False)
        db.execute(f"PRAGMA cache_size=-{READER_CACHE_KIB}")
    else:
        db = sqlite3.connect(path, timeout=BUSY_MS / 1000)
    db.row_factory = sqlite3.Row
    db.execute(f"PRAGMA busy_timeout={BUSY_MS}")
    key = _file_key(path)
    if key not in _ready:
        with _lock:
            if key not in _ready:
                try:
                    migrate(db)
                except BaseException:
                    db._shut() if kept else db.close()
                    raise
                _ready.add(key)
    return db


def connect() -> sqlite3.Connection:
    """An open connection for a write: the folder and the schema are created when missing."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return _open(path)


def reader() -> sqlite3.Connection | None:
    """This thread's kept connection for a read, or None when there is no DB file yet (reads never create it) or it
    can't be opened (logged by type)."""
    path = db_path()
    if not path.is_file():
        return None
    try:
        key = _file_key(path)
        held = getattr(_local, "held", None)
        if held is not None:
            if held[0] == _gen[0] and held[1] == key and not held[2].shut:
                return held[2]
            held[2]._shut()
            _local.held = None
        db = _open(path, kept=True)
        _local.held = (_gen[0], key, db)
        with _lock:
            _all_kept.add(db)
        return db
    except (sqlite3.Error, OSError) as exc:
        log.warning("media db unreadable: %s", type(exc).__name__)
        return None


def reset() -> None:
    """Close every thread's kept reader (tests between cases; anything that swaps the file under the hub). Each
    thread opens a new one on its next read."""
    with _lock:
        _gen[0] += 1
        kept = list(_all_kept)
        _all_kept.clear()
    for db in kept:
        db._shut()


def forget() -> None:
    """Tests: treat every file as unseen again."""
    with _lock:
        _ready.clear()
