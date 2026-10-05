"""Ratings + diary storage (2026-10-05) against a throwaway DB path."""
from datetime import datetime, timezone

import pytest

from hub import media_db as db


@pytest.fixture()
def path(tmp_path, monkeypatch):
    p = tmp_path / "nested" / "media.db"
    monkeypatch.setenv("MEDIA_DB_PATH", str(p))
    return p


def hist(key, title, stamp, kind="movie"):
    return {"item_key": key, "title": title, "kind": kind, "watched_at": stamp, "poster": "jf:x"}


def test_reads_never_create_the_file(path):
    assert db.get_ratings(["tmdb:1"]) == {}
    assert db.list_diary() == [] and db.diary_stats()["total"] == 0
    db.delete_rating("tmdb:1")
    assert not path.exists()


def test_first_write_creates_dir_schema_and_wal(path):
    db.set_rating("tmdb:1", 8, "movie", "Heat", 1995, "tmdb:/h.jpg")
    assert path.is_file()
    c = db.connect()
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert c.execute("SELECT owner FROM rating").fetchone()[0] == "you"
    c.close()


def test_rating_upsert_and_delete(path):
    db.set_rating("tmdb:1", 8, "movie", "Heat", 1995, None)
    db.set_rating("tmdb:1", 10, "movie", "Heat", 1995, None)
    db.set_rating("jf:abc", 4, "episode", "Show", None, None)
    assert db.get_ratings(["tmdb:1", "jf:abc", "tmdb:9"]) == {"tmdb:1": 10, "jf:abc": 4}
    db.delete_rating("tmdb:1")
    assert db.get_ratings(["tmdb:1", "jf:abc"]) == {"jf:abc": 4}


def test_score_check_constraint(path):
    with pytest.raises(Exception):
        db.set_rating("tmdb:1", 11, "movie", "Heat")


def test_sync_is_idempotent_and_collapses_a_show_per_day(path):
    rows = [hist("tmdb:1", "Heat", "2026-10-01T12:00:00Z"),
            hist("jf:s1", "Show · S01E01 · A", "2026-10-02T12:00:00Z", "episode"),
            hist("jf:s1", "Show · S01E02 · B", "2026-10-02T12:30:00Z", "episode"),
            {"title": "No key", "kind": "movie", "watched_at": "2026-10-02T12:00:00Z"}]
    assert db.sync_diary_from_history(rows) == 2
    assert db.sync_diary_from_history(rows) == 0
    got = db.list_diary()
    assert {r["title"] for r in got} == {"Heat", "Show"} and {r["kind"] for r in got} == {"movie", "tv"}
    assert all(r["source"] == "jellyfin" for r in got)


def test_sync_with_nothing_to_insert_creates_nothing(path):
    assert db.sync_diary_from_history([]) == 0 and not path.exists()


def test_manual_add_duplicate_and_filter(path):
    row = db.add_manual_watch("tmdb:2", "movie", "Alien", 1979, "tmdb:/a.jpg", "2026-09-20", "Cinema", "great")
    assert row["source"] == "manual" and row["place"] == "Cinema"
    assert db.add_manual_watch("tmdb:2", "movie", "Alien", watched_on="2026-09-20") is None
    db.add_manual_watch("tmdb:3", "tv", "Severance", watched_on="2026-09-21", place="Netflix")
    assert [r["title"] for r in db.list_diary()] == ["Severance", "Alien"]
    assert [r["title"] for r in db.list_diary(kind="movie")] == ["Alien"]
    assert [r["title"] for r in db.list_diary(limit=1, offset=1)] == ["Alien"]


def test_stats_counts_streak_and_milestones(path):
    now = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
    for i, d in enumerate(["2025-12-30", "2026-09-01", "2026-09-28", "2026-10-03", "2026-10-04", "2026-10-05"]):
        db.add_manual_watch(f"tmdb:{i}", "movie", f"T{i}", watched_on=d)
    s = db.diary_stats(now)
    assert (s["this_week"], s["this_month"], s["total"], s["streak_days"]) == (3, 4, 6, 3)
    assert s["milestones"] == ["First watch of 2026: T1", "First watch of 2025: T0"]


# ---- owners (2026-10-05): 'you' = B., 'her' = Georgina's Jellyfin user ----

def test_owner_of_maps_views():
    assert [db.owner_of(v) for v in ("her", "you", "both", "x")] == ["her", "you", "you", "you"]


def test_ratings_are_isolated_per_owner_on_the_same_key(path):
    db.set_rating("tmdb:1", 8, "movie", "Heat")
    db.set_rating("tmdb:1", 3, "movie", "Heat", owner="her")
    assert db.get_ratings(["tmdb:1"]) == {"tmdb:1": 8}
    assert db.get_ratings(["tmdb:1"], "her") == {"tmdb:1": 3}
    assert db.get_rating("tmdb:1", "her")["score"] == 3
    db.set_rating("tmdb:1", 4, "movie", "Heat", owner="her")  # update touches only hers
    assert (db.get_rating("tmdb:1")["score"], db.get_rating("tmdb:1", "her")["score"]) == (8, 4)
    db.delete_rating("tmdb:1")
    assert db.get_rating("tmdb:1") is None and db.get_rating("tmdb:1", "her")["score"] == 4
    db.delete_rating("tmdb:1", "her")
    assert db.get_rating("tmdb:1", "her") is None


def test_diary_is_isolated_per_owner(path):
    rows = [hist("tmdb:1", "Heat", "2026-03-01T12:00:00Z")]
    assert db.sync_diary_from_history(rows) == 1
    assert db.sync_diary_from_history(rows, "her") == 1   # same item, same day, different owner
    assert db.sync_diary_from_history(rows, "her") == 0   # still idempotent
    assert db.add_manual_watch("tmdb:2", "movie", "Ronin", watched_on="2026-03-02", owner="her")
    assert [r["title"] for r in db.list_diary()] == ["Heat"]
    assert [r["title"] for r in db.list_diary(owner="her")] == ["Ronin", "Heat"]
    assert db.diary_stats()["total"] == 1 and db.diary_stats(owner="her")["total"] == 2


def test_rankings_ignore_her_ratings(path):
    db.set_rating("tmdb:1", 8, "movie", "Heat", 1995)
    db.set_rating("tmdb:1", 2, "movie", "Heat", 1995, owner="her")
    db.set_rating("tmdb:2", 9, "movie", "Hers Only", 1995, owner="her")
    assert db.years_overview() == [{"year": 1995, "ranked_count": 0, "unranked_count": 1, "top": None}]
    assert db.place(1995, "tmdb:2") is False
    assert db.place(1995, "tmdb:1") is True
    assert [r["score"] for r in db.year_list(1995)["ranked"]] == [8]


def _old_shape_db(path):
    import sqlite3
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.executescript("""
    CREATE TABLE rating(
      item_key TEXT PRIMARY KEY, kind TEXT, title TEXT, year INT, poster TEXT,
      score INT CHECK(score BETWEEN 1 AND 10), rated_at TEXT, owner TEXT DEFAULT 'you');
    CREATE TABLE diary(
      id INTEGER PRIMARY KEY, item_key TEXT, kind TEXT, title TEXT, year INT, poster TEXT,
      watched_on TEXT, source TEXT, place TEXT, note TEXT, owner TEXT DEFAULT 'you', created_at TEXT,
      UNIQUE(item_key, watched_on, source));
    INSERT INTO rating VALUES('tmdb:1','movie','Heat',1995,'tmdb:/h.jpg',8,'2026-01-01T00:00:00+00:00','you');
    INSERT INTO rating VALUES('tmdb:2','tv','Show',NULL,NULL,6,'2026-01-02T00:00:00+00:00','you');
    INSERT INTO diary VALUES(7,'tmdb:1','movie','Heat',1995,'tmdb:/h.jpg','2026-02-01','manual','Cinema','n','you','2026-02-01T00:00:00+00:00');
    INSERT INTO diary VALUES(9,'tmdb:2','tv','Show',NULL,NULL,'2026-02-02','jellyfin',NULL,NULL,'you','2026-02-02T00:00:00+00:00');
    """)
    c.commit()
    c.close()


def test_migration_rebuilds_old_shape_keeping_every_row_as_you(path):
    _old_shape_db(path)
    ratings = db.get_ratings(["tmdb:1", "tmdb:2"])     # a plain read connects -> migrates
    assert ratings == {"tmdb:1": 8, "tmdb:2": 6}
    with db.connect() as c:
        assert [r["name"] for r in c.execute("PRAGMA table_info(rating)") if r["pk"]] == ["item_key", "owner"]
        assert "source, owner)" in c.execute("SELECT sql FROM sqlite_master WHERE name='diary'").fetchone()[0]
        rows = [dict(r) for r in c.execute("SELECT * FROM rating ORDER BY item_key")]
        assert [(r["item_key"], r["title"], r["year"], r["owner"]) for r in rows] == [
            ("tmdb:1", "Heat", 1995, "you"), ("tmdb:2", "Show", None, "you")]
        diary = [dict(r) for r in c.execute("SELECT * FROM diary ORDER BY id")]
        assert [(r["id"], r["place"], r["owner"]) for r in diary] == [(7, "Cinema", "you"), (9, None, "you")]
        names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not {"rating_old", "diary_old"} & names
    # the new key now lets her rate the same item, and the migration is a no-op the second time
    db.set_rating("tmdb:1", 5, "movie", "Heat", owner="her")
    assert db.get_rating("tmdb:1")["score"] == 8 and db.get_rating("tmdb:1", "her")["score"] == 5
    assert db.get_ratings(["tmdb:1", "tmdb:2"]) == {"tmdb:1": 8, "tmdb:2": 6}
    assert len(db.list_diary()) == 2 and db.list_diary(owner="her") == []


# ---- Rating level + settings (2026-10-06) ----

def test_setting_get_set_per_owner_with_default(path):
    assert db.get_setting("you", "rating_level", "show") == "show" and not path.exists()
    db.set_setting("you", "rating_level", "episode")
    db.set_setting("you", "rating_level", "season")
    assert db.get_setting("you", "rating_level") == "season"
    assert db.get_setting("her", "rating_level", "show") == "show"
    assert db.rating_level("you") == "season" and db.rating_level("her") == "show"


def test_rating_level_defaults_show_and_is_stored(path):
    db.set_rating("tmdb:1", 8, "movie", "Heat")
    db.set_rating("jf:season1", 6, "tv", "Show · Season 1", level="season")
    db.set_rating("jf:ep1", 5, "tv", "Show", level="bogus")  # unknown level -> show
    levels = {k: db.get_rating(k)["level"] for k in ("tmdb:1", "jf:season1", "jf:ep1")}
    assert levels == {"tmdb:1": "show", "jf:season1": "season", "jf:ep1": "show"}


def test_migration_adds_level_to_a_pre_level_rating_table(path):
    import sqlite3
    path.parent.mkdir(parents=True)
    c = sqlite3.connect(path)
    c.execute("""CREATE TABLE rating(item_key TEXT, kind TEXT, title TEXT, year INT, poster TEXT,
      score INT, rated_at TEXT, owner TEXT NOT NULL DEFAULT 'you', PRIMARY KEY(item_key, owner))""")
    c.execute("INSERT INTO rating VALUES('tmdb:1','movie','Heat',1995,NULL,9,'2026-01-01','you')")
    c.commit()
    c.close()
    assert db.get_rating("tmdb:1")["level"] == "show" and db.get_ratings(["tmdb:1"]) == {"tmdb:1": 9}
    db.set_rating("jf:e", 4, "tv", "S", level="episode")  # second connect: idempotent
    assert db.get_rating("jf:e")["level"] == "episode"


def test_rankings_ignore_episode_level_ratings(path):
    db.set_rating("tmdb:1", 8, "movie", "Heat", 2020)
    db.set_rating("jf:season1", 7, "tv", "Show · Season 1", 2020, level="season")
    db.set_rating("jf:ep1", 9, "tv", "Show · S01E01", 2020, level="episode")
    assert [y["unranked_count"] for y in db.years_overview()] == [2]
    assert {r["item_key"] for r in db.year_list(2020)["unranked"]} == {"tmdb:1", "jf:season1"}
    assert db.place(2020, "jf:ep1") is False and db.place(2020, "jf:season1") is True
