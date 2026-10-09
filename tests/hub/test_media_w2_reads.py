"""W2 media (2026-10-09): reads that used to scan or 500. The film page's diary dates are one SELECT and find a watch
older than the newest 500 diary rows (M-36); a failing play query degrades instead of 500ing the Media home (M-52);
the watchlist prune is one DELETE (M-38)."""
import sqlite3
from contextlib import closing

import pytest

from hub import media_db, media_item, media_plays_db, media_watchlist_db as wl


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))


def _bulk_diary(n: int, owner: str = "you"):
    with closing(media_db.connect()) as conn, conn:
        conn.executemany("INSERT INTO diary(item_key, kind, title, watched_on, source, owner) VALUES (?,?,?,?,?,?)",
                         [(f"tmdb:{9000 + i}", "movie", f"Film {i}", f"2026-0{1 + i % 9}-{1 + i % 28:02d}",
                           "manual", owner) for i in range(n)])


def test_diary_dates_find_a_watch_older_than_the_newest_500_rows(db):
    media_db.add_manual_watch(item_key="tmdb:603", kind="movie", title="The Matrix", watched_on="2001-05-04")
    media_db.add_manual_watch(item_key="jf:mov1", kind="movie", title="The Matrix", watched_on="2003-01-02")
    _bulk_diary(520)
    item = {"kind": "movie", "id": "mov1", "tmdb": 603}
    assert media_item._diary_dates(item, "you") == ["2 Jan 2003", "4 May 2001"]
    assert media_item._diary_dates(item, "her") == []


def test_diary_dates_by_show_and_season_key(db):
    with closing(media_db.connect()) as conn, conn:
        conn.executemany("INSERT INTO diary(item_key, kind, title, watched_on, source, owner, show_key, season_key)"
                         " VALUES (?,?,?,?,?,?,?,?)",
                         [("jf:ser1", "tv", "Show", "2026-01-03", "jellyfin", "you", "jf:ser1", "jf:sea1"),
                          ("jf:ser1", "tv", "Show", "2026-01-05", "jellyfin", "you", "jf:ser1", "jf:sea2"),
                          ("jf:other", "tv", "Other", "2026-01-06", "jellyfin", "you", "jf:other", "jf:x")])
    assert media_db.diary_dates("you", show_key="jf:ser1") == ["2026-01-05", "2026-01-03"]
    assert media_db.diary_dates("you", season_key="jf:sea1") == ["2026-01-03"]
    assert media_db.diary_dates("you") == []                         # nothing asked, nothing read
    assert media_item._diary_dates({"kind": "series", "id": "ser1"}, "you") == ["5 Jan 2026", "3 Jan 2026"]


def test_diary_dates_never_raise(db, monkeypatch):
    class Broken:
        def execute(self, *a):
            raise sqlite3.OperationalError("disk I/O error")

        def close(self):
            pass

    monkeypatch.setattr(media_db, "_read", lambda: Broken())
    assert media_db.diary_dates("you", item_keys=["tmdb:1"]) == []


class _BrokenConn:
    def execute(self, *a):
        raise sqlite3.OperationalError("database disk image is malformed")

    def close(self):
        pass


def test_play_queries_degrade_instead_of_raising(db, monkeypatch):
    monkeypatch.setattr(media_plays_db, "_read", lambda: _BrokenConn())
    assert media_plays_db.most_played_30("you") == ([], [])
    assert media_plays_db.stats(30)["plays"] == 0
    assert media_plays_db.first_run_date() is None
    assert media_plays_db.watch_count("mov1") == 0


def test_prune_played_is_one_delete(db, monkeypatch):
    for i in (1, 2, 3):
        wl.add("you", {"tmdb_id": i, "kind": "movie", "title": f"T{i}"})
    monkeypatch.setattr(wl, "remove", lambda *a: pytest.fail("prune must not delete row by row"))
    assert wl.prune_played("you", {"tmdb:1", "tmdb:3", "tmdb:99"}, "movie") == 2
    assert [r["item_key"] for r in wl.rows("you")] == ["tmdb:2"]
    assert not hasattr(wl, "list")                                   # the builtin is no longer shadowed
