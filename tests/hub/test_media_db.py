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
