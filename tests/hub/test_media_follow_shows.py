"""F5 follow shows + show creators (2026-10-12). A show is followed from its page: Sonarr keeps it monitored with new
seasons (`monitored: true, monitorNewItems: "all"`; requested "all seasons + future" through Jellyseerr first when Sonarr
doesn't have it); unfollow sets `monitorNewItems: "none"` and never deletes. A person followed as a TV maker (dept
"creator") also gets their NEW shows requested by the 6-hourly check. Jellyfin / Jellyseerr / Discord are the film-page
fakes; Sonarr is faked here at requests.get / put / post. No network, no real sleeps."""
import sqlite3
from contextlib import closing
from datetime import date, timedelta

import pytest
import requests

from hub import media_arr_search, media_follow, media_store
from tests.hub.conftest import main_of
from tests.hub.film_page import whole
from tests.hub.helpers import env, FakeResponse as R, SEERR_URL as SEERR, SKEY  # noqa: F401

SONARR = "http://sonarr.secret-host.invalid:8989"
TKEY = "s-SECRET-sonarr-key"
TODAY = date.today()
PAST = (TODAY - timedelta(days=400)).isoformat()
SOON = (TODAY + timedelta(days=90)).isoformat()
ORIGIN_BAD = {"Origin": "https://evil.invalid"}


# ---- schema step 3 ----

OLD_FOLLOWS = """CREATE TABLE media_follows(
  id INTEGER PRIMARY KEY, kind TEXT CHECK(kind IN ('person','collection')), tmdb_id INTEGER, name TEXT,
  followed_at TEXT, poster TEXT, dept TEXT, link TEXT, UNIQUE(kind, tmdb_id))"""
OLD_ADDS = """CREATE TABLE media_follow_adds(
  follow_id INTEGER, tmdb_id INTEGER, title TEXT, release_date TEXT, reason TEXT, outcome TEXT, note TEXT,
  at TEXT, poster TEXT, PRIMARY KEY(follow_id, tmdb_id))"""


def test_step_three_rebuilds_the_follow_tables_and_keeps_rows(tmp_path, monkeypatch):
    path = tmp_path / "media.db"
    monkeypatch.setenv("MEDIA_DB_PATH", str(path))
    with closing(media_store.connect()) as db:      # a current file, then put the follow tables back to their 2026-10-07 shape
        db.execute("DROP TABLE media_follows")
        db.execute("DROP TABLE media_follow_adds")
        db.execute(OLD_FOLLOWS)
        db.execute(OLD_ADDS)
        db.execute("INSERT INTO media_follows VALUES(1,'person',55,'Ada','2026-10-07',NULL,'Acting',NULL)")
        db.execute("INSERT INTO media_follow_adds VALUES(1,603,'Harbour','2027-01-01','top-5 cast','requested',NULL,'x',NULL)")
        db.execute("PRAGMA user_version = 2")
        db.commit()
    media_store.forget()
    assert media_follow.get("person", 55)["name"] == "Ada"                              # the first open migrates
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == media_store.SCHEMA_VERSION == 3
        assert db.execute("SELECT media, tmdb_id, outcome FROM media_follow_adds").fetchall() == [("movie", 603, "requested")]
    media_follow.follow("show", 603, "Same Number Show")                                # 'show' now passes the CHECK
    assert {f["kind"] for f in media_follow.follows()} == {"person", "show"}
    with closing(media_store.connect()) as db:                                           # a film and a show with one number
        media_follow._record(db, 1, {"media": "tv", "tmdb_id": 603, "title": "Show", "date": SOON, "reason": "creator",
                                     "poster": None}, "requested", None)
        assert db.execute("SELECT COUNT(*) FROM media_follow_adds").fetchone()[0] == 2
        media_follow.migrate_shows(db)                                                   # idempotent
        assert db.execute("SELECT COUNT(*) FROM media_follow_adds").fetchone()[0] == 2
