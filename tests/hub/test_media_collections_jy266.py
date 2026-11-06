"""JY-266 Collections (spec docs/specs/JY-266-collections.md).

P1: the `collection` / `collection_member` tables (media.db step 8), the monthly pass over owned films (Seerr movie and
collection bodies, faked here: no network) and the owned / missing computation."""
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from hub import media_collections as mc, media_discover, media_store

NOW = datetime(2026, 11, 6, 9, 0, tzinfo=timezone.utc)

# 6 owned films over 3 collections: Alpha (complete, 2 films), Bravo (3 parts, 2 owned), Solo (single film);
# film 40 has no collection; film 41 is not on Seerr (404)
MOVIES = {10: 1, 11: 1, 20: 2, 21: 2, 30: 3, 40: None}
COLS = {
    1: {"name": "Alpha Collection", "posterPath": "/a.jpg", "backdropPath": "/ab.jpg",
        "parts": [{"id": 11, "title": "Alpha Two", "releaseDate": "2005-06-01", "posterPath": "/a2.jpg"},
                  {"id": 10, "title": "Alpha", "releaseDate": "2001-03-01", "posterPath": "/a1.jpg"}]},
    2: {"name": "Bravo Collection", "posterPath": None,
        "parts": [{"id": 20, "title": "Bravo", "releaseDate": "1999-01-01", "posterPath": "/b1.jpg"},
                  {"id": 22, "title": "Bravo Three", "releaseDate": "", "posterPath": None},      # unreleased, no date
                  {"id": 21, "title": "Bravo Two", "releaseDate": "2011-01-01", "posterPath": "/b2.jpg"}]},
    3: {"name": "Solo Collection", "parts": [{"id": 30, "title": "Solo", "releaseDate": "2020-01-01"}]},
}
OWNED = set(MOVIES) | {41}


class FakeSeerr:
    def __init__(self):
        self.calls, self.down, self.gone = [], False, set()

    def __call__(self, path, timeout=None):
        self.calls.append(path)
        if self.down:
            return None, None
        kind, _, n = path.rpartition("/")
        n = int(n)
        if kind.endswith("/movie"):
            if n not in MOVIES:
                return None, 404
            col = MOVIES[n]
            return {"id": n, "title": f"Film {n}", "collection": {"id": col, "name": "x"} if col else None}, 200
        if n in self.gone or n not in COLS:
            return None, 404
        return COLS[n], 200


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("JELLYSEERR_URL", "http://seerr.invalid")
    monkeypatch.setenv("JELLYSEERR_API_KEY", "k")
    monkeypatch.delenv("COLLECTIONS", raising=False)
    media_store.reset()
    with closing(media_store.connect()):
        pass
    fake = FakeSeerr()
    monkeypatch.setattr(media_discover, "_fetch", fake)
    yield fake
    media_store.reset()


def _members(path):
    with closing(sqlite3.connect(path)) as conn:
        return dict(conn.execute("SELECT movie_tmdb, collection_id FROM collection_member").fetchall())


def owned_keys():
    return {f"tmdb:{i}" for i in OWNED}


# ---- P1: the pass ----

def test_a_pass_stores_membership_and_collections(db, tmp_path):
    out = mc.run_pass(OWNED, NOW)
    assert out["films"] == 7 and out["collections"] == 3 and not out["more"] and not out["failed"]
    assert _members(tmp_path / "media.db") == {10: 1, 11: 1, 20: 2, 21: 2, 30: 3, 40: None, 41: None}
    assert mc.last_pass() == NOW.isoformat(timespec="seconds")


def test_counts_years_and_order(db):
    mc.run_pass(OWNED, NOW)
    got = {s["name"]: s for s in mc.summaries(owned_keys())}
    assert list(got) == ["Alpha Collection", "Bravo Collection", "Solo Collection"]      # A-Z
    a, b, s = got["Alpha Collection"], got["Bravo Collection"], got["Solo Collection"]
    assert (a["n"], a["on"], a["complete"], a["years"]) == (2, 2, True, "2001-2005")
    assert [p["title"] for p in a["parts"]] == ["Alpha", "Alpha Two"]                       # release order
    assert (b["n"], b["on"], b["complete"], b["years"]) == (3, 2, False, "1999-2011")    # no-date part ignored
    assert [p["title"] for p in b["parts"]][-1] == "Bravo Three" and not b["parts"][-1]["on"]
    assert b["on_line"] == "2 of 3 on Joey" and b["count_line"] == "3 films · 1999-2011"
    assert b["poster"] == "tmdb:/b1.jpg"          # no collection poster: the first owned part's
    assert (s["n"], s["years"], s["count_line"]) == (1, "2020", "1 film · 2020")
    assert a["href"] == "/media/collections/1"


def test_a_collection_with_no_owned_film_is_not_shown(db):
    mc.run_pass(OWNED, NOW)
    got = mc.summaries({"tmdb:10", "tmdb:11"})
    assert [s["name"] for s in got] == ["Alpha Collection"]


def test_monthly_rate_nothing_asked_again_inside_30_days(db):
    mc.run_pass(OWNED, NOW)
    db.calls.clear()
    out = mc.run_pass(OWNED, NOW + timedelta(days=29))
    assert db.calls == [] and out["calls"] == 0
    mc.run_pass(OWNED, NOW + timedelta(days=31))
    assert len(db.calls) == 7 + 3


def test_a_new_film_is_asked_on_the_next_pass_only(db):
    mc.run_pass(OWNED, NOW)
    db.calls.clear()
    MOVIES[50] = None
    try:
        mc.run_pass(OWNED | {50}, NOW + timedelta(hours=1))
    finally:
        del MOVIES[50]
    assert db.calls == ["/api/v1/movie/50"]


def test_the_kick_makes_everything_due(db):
    mc.run_pass(OWNED, NOW)
    db.calls.clear()
    mc.kick(NOW + timedelta(days=1))
    mc.run_pass(OWNED, NOW + timedelta(days=1, minutes=1))
    assert len(db.calls) == 10


def test_per_pass_cap_spreads_the_work(db):
    out = mc.run_pass(OWNED, NOW, limit=4)
    assert out["calls"] == 4 and out["more"] and mc.last_pass() is None
    out = mc.run_pass(OWNED, NOW + timedelta(hours=1), limit=4)
    assert out["calls"] == 4 and out["more"]
    out = mc.run_pass(OWNED, NOW + timedelta(hours=2), limit=4)
    assert out["calls"] == 2 and not out["more"]
    assert len(mc.summaries(owned_keys())) == 3


def test_a_failed_read_stops_the_pass_and_is_retried(db, tmp_path):
    db.down = True
    out = mc.run_pass(OWNED, NOW)
    assert out["failed"] == 1 and out["calls"] == 1 and _members(tmp_path / "media.db") == {}
    db.down = False
    assert mc.run_pass(OWNED, NOW + timedelta(hours=1))["films"] == 7


def test_a_collection_tmdb_drops_is_removed(db, tmp_path):
    mc.run_pass(OWNED, NOW)
    db.gone.add(2)
    out = mc.run_pass(OWNED, NOW + timedelta(days=31))
    # the films were re-read first (still naming 2), then collection 2 answered 404: dropped
    assert out["dropped"] == 1
    assert [s["name"] for s in mc.summaries(owned_keys())] == ["Alpha Collection", "Solo Collection"]
    assert _members(tmp_path / "media.db")[20] is None


def test_kill_switch_and_no_creds(db, monkeypatch):
    snaps = {"jellyfin": SimpleNamespace(data={"movies": [{"item_key": "tmdb:10"}]}),
             "system": SimpleNamespace(data={"ram_free_gb": 4}, age_minutes=1)}
    monkeypatch.setenv("COLLECTIONS", "off")
    assert mc.disabled() and mc.tick(lambda: snaps, NOW) is None and db.calls == []
    monkeypatch.delenv("COLLECTIONS")
    monkeypatch.delenv("JELLYSEERR_API_KEY")
    assert mc.tick(lambda: snaps, NOW) is None and db.calls == []
    monkeypatch.setenv("JELLYSEERR_API_KEY", "k")
    assert mc.tick(lambda: snaps, NOW)["films"] == 1


def test_memory_gate(db):
    lib = SimpleNamespace(data={"movies": [{"item_key": "tmdb:10"}, {"item_key": "jf:abc"}]})
    low = {"jellyfin": lib, "system": SimpleNamespace(data={"ram_free_gb": 0.5}, age_minutes=1)}
    unknown = {"jellyfin": lib}
    assert mc.tick(lambda: low, NOW) is None and mc.tick(lambda: unknown, NOW) is None and db.calls == []


def test_owned_ids_reads_tmdb_keys_only():
    assert mc.owned_ids({"movies": [{"item_key": "tmdb:5"}, {"item_key": "jf:x"}, {}, {"item_key": "tmdb:x"}]}) == {5}
    assert mc.owned_ids(None) == set()


def test_migration_upgrades_a_populated_v7_db(tmp_path, monkeypatch):
    path = tmp_path / "media.db"
    monkeypatch.setenv("MEDIA_DB_PATH", str(path))
    media_store.reset()
    from hub import media_db
    media_db.set_rating("tmdb:1", 8, "movie", "One")
    with closing(sqlite3.connect(path)) as conn:
        for t in ("collection", "collection_member", "collection_state"):
            conn.execute(f"DROP TABLE {t}")
        conn.execute("PRAGMA user_version = 7")       # a live v7 file: JY-264 deployed
        conn.commit()
    media_store.reset()
    media_store.forget()
    with closing(media_store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == media_store.SCHEMA_VERSION == 8
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"collection", "collection_member", "collection_state"} <= names
        assert conn.execute("SELECT score FROM rating WHERE item_key = 'tmdb:1'").fetchone()[0] == 8
    media_store.reset()


def test_summaries_on_an_empty_db_is_empty(db):
    assert mc.summaries(owned_keys()) == [] and mc.one(1, set()) is None
