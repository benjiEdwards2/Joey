"""media_store (W2, 2026-10-09; M-11, M-33, M-34): media.db is opened in one place, its schema is versioned with
PRAGMA user_version and brought up to date once per file per process — later opens, reads included, run no DDL."""
import sqlite3
from contextlib import closing

import pytest

from hub import media_db, media_store


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    return tmp_path / "media.db"


@pytest.fixture()
def ddl_log(monkeypatch):
    """Every CREATE / ALTER / DROP statement any media.db connection runs."""
    seen, real = [], sqlite3.connect

    def connect(*a, **k):
        conn = real(*a, **k)
        conn.set_trace_callback(lambda sql: seen.append(sql) if sql.lstrip().upper().startswith(
            ("CREATE", "ALTER", "DROP")) else None)
        return conn
    monkeypatch.setattr(media_store.sqlite3, "connect", connect)
    return seen


def _names(path, kind):
    with closing(sqlite3.connect(path)) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = ?", (kind,))}


def test_a_new_file_gets_every_table_index_and_the_version(db):
    with closing(media_store.connect()):
        pass
    tables = _names(db, "table")
    assert {"rating", "diary", "setting", "ranking", "nextup_hidden", "play", "watchlist", "media_follows",
            "media_follow_adds", "award_body", "award_edition", "award_sync"} <= tables
    assert {"diary_owner_watched", "play_owner_started", "play_jf_finished"} <= _names(db, "index")
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == media_store.SCHEMA_VERSION == 6
        assert conn.execute("SELECT COUNT(*) FROM award_body").fetchone()[0] > 0      # the awards seed


def test_the_schema_runs_once_per_file_then_no_ddl(db, ddl_log):
    media_db.set_rating("tmdb:1", 8, "movie", "One")
    assert ddl_log, "the first open creates the schema"
    ddl_log.clear()
    for _ in range(3):
        media_db.get_ratings(["tmdb:1"])
        with closing(media_store.connect()):
            pass
    assert ddl_log == []


def test_a_fresh_process_reading_an_up_to_date_file_runs_no_ddl(db, ddl_log):
    with closing(media_store.connect()):
        pass
    media_store.forget()                    # a restart: the file is unseen, but already at SCHEMA_VERSION
    ddl_log.clear()
    assert media_db.get_ratings(["tmdb:1"]) == {}
    assert ddl_log == []


def test_each_db_path_is_migrated_on_its_own(tmp_path, monkeypatch):
    for name in ("a.db", "b.db"):
        monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / name))
        media_db.set_rating("tmdb:1", 7, "movie", "One")
        assert media_db.get_ratings(["tmdb:1"]) == {"tmdb:1": 7}
        assert "play_jf_finished" in _names(tmp_path / name, "index")


def test_a_pre_versioning_file_is_brought_up_to_date(db):
    """A live media.db from before W2 (user_version 0, old-shape rating table, no indexes) is upgraded on its first
    open — rows kept — and a reader works on it."""
    from tests.hub.test_media_db import _old_shape_db
    _old_shape_db(db)
    assert media_db.get_ratings(["tmdb:1", "tmdb:2"]) == {"tmdb:1": 8, "tmdb:2": 6}
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == media_store.SCHEMA_VERSION
        assert conn.execute("SELECT COUNT(*) FROM diary WHERE owner = 'you'").fetchone()[0] == 2
    assert "diary_owner_watched" in _names(db, "index")


def test_reads_never_create_the_file(db):
    assert media_store.reader() is None and media_db.get_ratings(["tmdb:1"]) == {}
    assert not db.exists()
