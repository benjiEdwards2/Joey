"""JY-264 phase 1: the `library_index` table (media.db step 6), filled from the Jellyfin snapshot, the play recorder
and item reads. No new live polling: the index only reads what the hub already has."""
import sqlite3
from contextlib import closing

import pytest

from hub import library_index, media_store
from tests.hub.fake_library import FakeLibrary

T0 = "2026-10-28T09:00:00+00:00"
T1 = "2026-10-28T09:15:00+00:00"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    media_store.reset()
    with closing(media_store.connect()):   # an existing media.db (a page read never creates one)
        pass
    library_index._pending.clear()
    return tmp_path / "media.db"


def _rows(db, where="1=1", args=()):
    with closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        return {r["jf_id"]: dict(r) for r in conn.execute(f"SELECT * FROM library_index WHERE {where}", args)}


def test_step_6_creates_the_index_and_the_audit_tables(db):
    with closing(media_store.connect()):
        pass
    with closing(sqlite3.connect(db)) as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        assert conn.execute("PRAGMA user_version").fetchone()[0] == media_store.SCHEMA_VERSION == 7
    assert {"library_index", "library_index_state", "reattach_run", "reattach_change"} <= names


def test_a_snapshot_sync_fills_movies_and_series_with_ids_and_paths(db):
    lib = FakeLibrary()
    out = library_index.sync_from_snapshot(lib.snapshot(T0))
    assert out is not None
    rows = _rows(db)
    arrival = rows[lib.ids["arrival"]]
    assert (arrival["kind"], arrival["title"], arrival["year"]) == ("movie", "Arrival", 2016)
    assert (arrival["tmdb_id"], arrival["imdb_id"]) == ("329865", "tt2543164")
    assert arrival["path"] == "/data/media/movies/Arrival (2016)/Arrival.mkv"
    sev = rows[lib.ids["severance"]]
    assert (sev["kind"], sev["tvdb_id"], sev["tmdb_id"]) == ("series", "371980", "95396")
    home = rows[lib.ids["home_video"]]
    assert home["tmdb_id"] is None and home["path"].endswith("Home Video.mkv")
    assert all(r["first_seen_at"] and r["last_seen_at"] and r["gone_since"] is None for r in rows.values())


def test_the_same_library_stamp_syncs_nothing(db):
    lib = FakeLibrary()
    assert library_index.sync_from_snapshot(lib.snapshot(T0)) is not None
    assert library_index.sync_from_snapshot(lib.snapshot(T0)) is None
    assert library_index.sync_from_snapshot({"movies": [], "shows": []}) is None   # no stamp: never synced


def test_episodes_and_seasons_come_from_the_snapshot_rows_and_joey_play_rows(db):
    lib = FakeLibrary()
    ids = lib.ids
    snap = lib.snapshot(T0)
    snap["up_next"] = [{"title": "Severance", "kind": "episode", "jf_id": ids["severance/s2e1"],
                        "show_key": f"jf:{ids['severance']}", "season_key": f"jf:{ids['severance/s2']}",
                        "episode_key": f"jf:{ids['severance/s2e1']}", "season": 2, "episode": 1}]
    with closing(media_store.connect()) as conn, conn:
        conn.execute("INSERT INTO play(jf_id, item_key, show_key, season_key, episode_key, kind, season, episode, "
                     "title, show_title) VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (ids["bluey/s1e2"], f"jf:{ids['bluey']}", f"jf:{ids['bluey']}", f"jf:{ids['bluey/s1']}",
                      f"jf:{ids['bluey/s1e2']}", "episode", 1, 2, "Episode 2", "Bluey"))
    library_index.sync_from_snapshot(snap)
    rows = _rows(db)
    ep = rows[ids["severance/s2e1"]]
    assert (ep["kind"], ep["series_jf_id"], ep["season"], ep["episode"]) == ("episode", ids["severance"], 2, 1)
    assert rows[ids["severance/s2"]]["kind"] == "season" and rows[ids["severance/s2"]]["season"] == 2
    played = rows[ids["bluey/s1e2"]]
    assert (played["series_jf_id"], played["season"], played["episode"]) == (ids["bluey"], 1, 2)
    assert rows[ids["bluey/s1"]]["series_jf_id"] == ids["bluey"]


def test_a_missing_item_is_marked_gone_only_after_a_complete_fetch(db):
    lib = FakeLibrary()
    library_index.sync_from_snapshot(lib.snapshot(T0))
    snap = lib.snapshot(T1)
    snap["movies"] = [m for m in snap["movies"] if m["title"] != "Dune"]
    library_index.sync_from_snapshot(snap)
    dune = _rows(db)[lib.ids["dune"]]
    assert dune["gone_since"] and dune["gone_fetches"] == 1
    # it comes back: cleared
    library_index.sync_from_snapshot(lib.snapshot("2026-10-28T09:30:00+00:00"))
    dune = _rows(db)[lib.ids["dune"]]
    assert dune["gone_since"] is None and dune["gone_fetches"] == 0


def test_a_truncated_or_failed_list_marks_nothing_gone(db, monkeypatch):
    lib = FakeLibrary()
    library_index.sync_from_snapshot(lib.snapshot(T0))
    monkeypatch.setattr(library_index, "LIBRARY_FETCH_LIMIT", 2)   # a full page = maybe more: not complete
    snap = lib.snapshot(T1)
    snap["movies"] = snap["movies"][:2]
    snap.pop("shows")                                               # the shows call failed: key absent
    library_index.sync_from_snapshot(snap)
    assert all(r["gone_since"] is None for r in _rows(db).values())


def test_known_values_are_never_blanked_by_a_thinner_sighting(db):
    lib = FakeLibrary()
    library_index.sync_from_snapshot(lib.snapshot(T0))
    library_index.note_item({"Id": lib.ids["arrival"], "Type": "Movie", "Name": "Arrival"})   # no ids, no path
    library_index.flush()
    row = _rows(db)[lib.ids["arrival"]]
    assert row["tmdb_id"] == "329865" and row["path"].endswith("Arrival.mkv") and row["year"] == 2016


def test_an_item_read_and_a_recorder_sighting_index_the_item(db):
    sid, season, ep = "a1" * 16, "b2" * 16, "c3" * 16
    library_index.note_item({"Id": ep, "Type": "Episode", "Name": "Pilot", "SeriesId": sid, "SeasonId": season,
                             "ParentIndexNumber": 1, "IndexNumber": 1, "Path": "/data/media/tv/X/S01E01.mkv",
                             "ProviderIds": {"Tvdb": "777"}})
    assert _rows(db) == {}                     # a sighting is only remembered: the page opened no write connection
    assert library_index.flush() == 3
    rows = _rows(db)
    assert rows[ep]["series_jf_id"] == sid and rows[ep]["path"].endswith("S01E01.mkv")
    assert rows[season]["kind"] == "season" and rows[season]["series_jf_id"] == sid
    assert rows[sid]["kind"] == "series"


def test_the_recorder_notes_what_it_sees(db, monkeypatch):
    from hub import media_plays
    seen = []
    monkeypatch.setattr(media_plays, "_creds", lambda: ("http://jf.test", {}))
    monkeypatch.setattr(media_plays.jellyfin, "get", lambda *a, **k: [
        {"UserId": None, "NowPlayingItem": {"Id": "d4" * 16, "Type": "Movie", "Name": "Film"}}])
    monkeypatch.setattr(library_index, "note_item", lambda item: seen.append(item["Id"]))
    media_plays.poll_once()
    assert seen == ["d4" * 16]


def test_the_media_front_never_writes_the_index(db, monkeypatch):
    from hub import guest
    monkeypatch.setattr(guest, "is_media", lambda: True)
    library_index.note_item({"Id": "e5" * 16, "Type": "Movie", "Name": "Film"})
    library_index.flush()
    assert _rows(db) == {}


def test_a_read_never_creates_media_db(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "none" / "media.db"))
    library_index._pending.clear()
    library_index.note_item({"Id": "e5" * 16, "Type": "Movie", "Name": "Film"})
    assert library_index.flush() == 0
    assert not (tmp_path / "none" / "media.db").exists()


def test_note_item_never_raises(db, monkeypatch):
    monkeypatch.setattr(library_index, "row_from_item", lambda *a, **k: (_ for _ in ()).throw(ValueError()))
    library_index.note_item({"Id": "f6" * 16, "Type": "Movie"})


def test_tick_never_raises_and_flushes(db, monkeypatch):
    library_index.note_item({"Id": "f6" * 16, "Type": "Movie", "Name": "Film"})
    library_index.tick(lambda: (_ for _ in ()).throw(OSError()))   # the snapshot read fails: the sightings still land
    assert "f6" * 16 in _rows(db)


def test_an_item_page_read_indexes_the_item(db, monkeypatch):
    from hub import media_item
    from tests.hub.fake_jellyfin import KEY, URL, FakeJellyfin
    monkeypatch.setenv("JELLYFIN_URL", URL)
    monkeypatch.setenv("JELLYFIN_API_KEY", KEY)
    monkeypatch.setenv("JELLYFIN_USER", "Sample Admin")
    fj = FakeJellyfin().install(monkeypatch)
    film = "ab" * 16
    fj.items[film] = {"Id": film, "Type": "Movie", "Name": "Arrival", "ProductionYear": 2016,
                      "ProviderIds": {"Tmdb": "329865"}, "Path": "/data/media/movies/Arrival (2016)/Arrival.mkv"}
    assert media_item._data(film) is not None
    library_index.flush()
    row = _rows(db)[film]
    assert (row["kind"], row["tmdb_id"], row["year"]) == ("movie", "329865", 2016)
    assert row["path"].endswith("Arrival.mkv")


def test_the_media_front_never_sees_a_library_file_path():
    from hub import guest
    data = {"movies": [{"title": "Arrival", "jf_id": "ab" * 16, "path": "/data/media/movies/Arrival.mkv",
                        "imdb": "tt2543164"}],
            "shows": [{"title": "Severance", "jf_id": "cd" * 16, "path": "/data/media/tv/Severance", "tvdb": "371980"}]}
    out = guest.scrub_data("jellyfin", data)
    assert "path" not in out["movies"][0] and "path" not in out["shows"][0]
    assert out["movies"][0]["imdb"] == "tt2543164" and out["shows"][0]["tvdb"] == "371980"


def test_a_v6_file_with_jy265s_table_upgrades_to_v7_and_keeps_every_row(tmp_path, monkeypatch):
    """JY-264 step 7 lands after JY-265's step 6 (media_removals) in deploy order: a live v6 file gains the index and
    audit tables, and every existing row (JY-265's included) is unchanged."""
    path = tmp_path / "media.db"
    monkeypatch.setenv("MEDIA_DB_PATH", str(path))
    media_store.reset()
    media_store.forget()
    from hub import media_db
    media_db.set_rating("tmdb:603", 9, "movie", "Harbour Lights", year=2019)
    with closing(sqlite3.connect(path)) as conn:
        for t in ("library_index", "library_index_state", "reattach_run", "reattach_change"):
            conn.execute(f"DROP TABLE {t}")
        conn.execute("INSERT INTO media_removals(at, owner, front, kind, tmdb_id, title, scope, outcome) "
                     "VALUES('2026-10-28T09:00:00Z', 'you', 'hub', 'movie', 603, 'Harbour Lights', 'request', 'removed')")
        conn.execute("PRAGMA user_version = 6")                          # a live v6 file: JY-265 deployed
        conn.commit()
        tables = sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        before = {t: conn.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall()
                  for t in tables if t != "sqlite_sequence"}
    assert before["media_removals"] and before["rating"] and "library_index" not in before
    media_store.reset()
    media_store.forget()
    with closing(media_store.connect()) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == media_store.SCHEMA_VERSION == 7
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"library_index", "library_index_state", "reattach_run", "reattach_change"} <= names
        for t, rows in before.items():
            assert [tuple(r) for r in conn.execute(f'SELECT * FROM "{t}" ORDER BY rowid')] == rows, t
    media_store.reset()
