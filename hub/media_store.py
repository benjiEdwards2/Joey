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
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from pathlib import Path

log = logging.getLogger("hub.media_store")

DEFAULT_DB_PATH = "/data/sqlite/media.db"
BUSY_MS = 5000

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


STEPS = (_baseline, _indexes, _follow_shows)   # STEPS[n] takes a file from user_version n to n + 1
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


def _open(path: Path) -> sqlite3.Connection:
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
                    db.close()
                    raise
                _ready.add(key)
    return db


def connect() -> sqlite3.Connection:
    """An open connection for a write: the folder and the schema are created when missing."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return _open(path)


def reader() -> sqlite3.Connection | None:
    """An open connection for a read, or None when there is no DB file yet (reads never create it) or it can't be
    opened (logged by type)."""
    path = db_path()
    if not path.is_file():
        return None
    try:
        return _open(path)
    except (sqlite3.Error, OSError) as exc:
        log.warning("media db unreadable: %s", type(exc).__name__)
        return None


def forget() -> None:
    """Tests: treat every file as unseen again."""
    with _lock:
        _ready.clear()
