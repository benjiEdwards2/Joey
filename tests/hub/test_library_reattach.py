"""JY-264 phases 2-3: after a Jellyfin library rebuild (every item id re-minted), Joey's rows re-attach to the new ids.

B. 2026-10-28 ("Jy 58 all recommended and jy 264"): Q1 A, rewrite old `jf:` keys to the new `jf:` ids; Q2 A, strong
matches (provider id, path) apply on their own with undo, title + year and ambiguous ones only go into the report;
Q3 A, user ids are out of scope.

Every test runs against the fake Jellyfin (tests/hub/fake_jellyfin.py) and a small fake library
(tests/hub/fake_library.py) whose `rebuild()` re-mints every film, series, season and episode id.
"""
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from hub import library_index, library_reattach as reattach, media_db, media_posters, media_store
from tests.hub.fake_jellyfin import KEY, URL, FakeJellyfin
from tests.hub.fake_library import FakeLibrary

STAMPS = [f"2026-10-28T{9 + i // 4:02d}:{(i % 4) * 15:02d}:00+00:00" for i in range(12)]
JOEY_TABLES = ("rating", "diary", "ranking", "nextup_hidden", "rating_skip", "watchlist", "play", "poster",
               "media_follows")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("MEDIA_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("POSTERS_DIR", str(tmp_path / "posters"))
    monkeypatch.setenv("JELLYFIN_URL", URL)
    monkeypatch.setenv("JELLYFIN_API_KEY", KEY)
    monkeypatch.setenv("JELLYFIN_USER", "Sample Admin")
    monkeypatch.delenv("LIBRARY_PATH_PREFIXES", raising=False)
    media_store.reset()
    library_index._pending.clear()
    fj = FakeJellyfin().install(monkeypatch)
    lib = FakeLibrary(fj)
    return {"tmp": tmp_path, "fj": fj, "lib": lib, "db": tmp_path / "media.db",
            "posters": tmp_path / "posters", "stamp": iter(STAMPS)}


def sync(env):
    """One complete library fetch reaching the hub, then the auto step (what library_index.tick does)."""
    data = env["lib"].snapshot(next(env["stamp"]))
    if library_index.sync_from_snapshot(data) is not None:
        return reattach.auto()
    return None


def seed(env) -> None:
    """Rows in every column that holds a Jellyfin item id, for you, her and a friend, plus rows that must not move."""
    i = env["lib"].ids
    jf = lambda name: f"jf:{i[name]}"   # noqa: E731
    with closing(media_store.connect()) as db, db:
        media_posters._ensure(db)
        rate = "INSERT INTO rating(item_key, kind, title, score, rated_at, owner, level, poster) VALUES(?,?,?,?,?,?,?,?)"
        db.execute(rate, (jf("home_video"), "movie", "Home Video", 7, "2026-10-01", "you", "show", jf("home_video")))
        db.execute(rate, (jf("severance"), "tv", "Severance", 9, "2026-10-01", "you", "show", jf("severance")))
        db.execute(rate, (jf("severance"), "tv", "Severance", 8, "2026-10-01", "her", "show", jf("severance")))
        db.execute(rate, (jf("severance/s2"), "tv", "Severance S2", 10, "2026-10-02", "you", "season", jf("severance")))
        db.execute(rate, (jf("severance/s1e2"), "tv", "Half Loop", 6, "2026-10-02", "you", "episode", jf("severance")))
        db.execute(rate, ("tmdb:329865", "movie", "Arrival", 10, "2026-10-01", "you", "show", jf("arrival")))
        diary = ("INSERT INTO diary(item_key, kind, title, watched_on, source, owner, show_key, season_key, season, "
                 "episode, poster) VALUES(?,?,?,?,?,?,?,?,?,?,?)")
        db.execute(diary, (jf("severance/s1e1"), "tv", "Severance · S01E01", "2026-10-03", "jellyfin", "you",
                           jf("severance"), jf("severance/s1"), 1, 1, jf("severance")))
        db.execute(diary, (jf("bluey/s1e2"), "tv", "Bluey · S01E02", "2026-10-04", "jellyfin", "her",
                           jf("bluey"), jf("bluey/s1"), 1, 2, jf("bluey")))
        db.execute(diary, (jf("bluey/s1e1"), "tv", "Bluey · S01E01", "2026-10-04", "jellyfin", "jf:" + "f00d" * 8,
                           jf("bluey"), jf("bluey/s1"), 1, 1, jf("bluey")))
        db.execute(diary, ("tmdb:438631", "movie", "Dune", "2026-10-05", "manual", "you", None, None, None, None,
                           jf("dune")))
        db.execute("INSERT INTO ranking(year, item_key, position, kind, title, owner) VALUES(2026,?,1,'tv','Severance','you')",
                   (jf("severance"),))
        db.execute("INSERT INTO nextup_hidden(owner, series_key, episode_id, hidden_at) VALUES('you',?,?,'2026-10-06')",
                   (jf("bluey"), i["bluey/s1e2"]))
        db.execute("INSERT INTO rating_skip(owner, key, kind, forever, title, poster) VALUES('her',?,'tv',1,'Bluey',?)",
                   (jf("bluey"), jf("bluey")))
        db.execute("INSERT INTO watchlist(owner, item_key, kind, title, poster) VALUES('you',?,'movie','Home Video',?)",
                   (jf("home_video"), jf("home_video")))
        play = ("INSERT INTO play(user_name, owner, jf_id, item_key, show_key, season_key, episode_key, title, show_title, "
                "kind, season, episode, started_at, last_seen_at, position_pct, finished, poster) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
        db.execute(play, ("B", "you", i["severance/s1e3"], jf("severance"), jf("severance"), jf("severance/s1"),
                          jf("severance/s1e3"), "Episode 3", "Severance", "episode", 1, 3, "2026-10-07T10:00:00Z",
                          "2026-10-07T10:50:00Z", 100, 1, jf("severance")))
        db.execute(play, ("B", "you", i["severance/s1e3"], jf("severance"), jf("severance"), jf("severance/s1"),
                          jf("severance/s1e3"), "Episode 3", "Severance", "episode", 1, 3, "2026-10-08T10:00:00Z",
                          "2026-10-08T10:20:00Z", 40, 0, jf("severance")))   # progress: a half-watched re-watch
        db.execute(play, ("B", "you", i["dune"], "tmdb:438631", None, None, None, "Dune", None, "movie", None, None,
                          "2026-10-09T20:00:00Z", "2026-10-09T22:30:00Z", 100, 1, jf("dune")))
        db.execute("INSERT INTO media_follows(kind, tmdb_id, name) VALUES('show', 95396, 'Severance')")
        for name in ("dune", "severance"):
            db.execute("INSERT INTO poster(jf_id, kind, title, ver, status, bytes) VALUES(?,?,?,?,?,?)",
                       (i[name], "movie" if name == "dune" else "series", name, "abc123", "ok", 1234))
    # the season and episode B. rated were opened on their item pages, which index them (phase 1)
    lib = env["lib"]
    library_index.note_item(next(e for e in lib.episodes_of("severance") if e["Id"] == i["severance/s1e2"]))
    library_index.note_item({"Id": i["severance/s2"], "Type": "Season", "Name": "Season 2", "IndexNumber": 2,
                             "SeriesId": i["severance"]})
    for name in ("dune", "severance"):
        folder = env["posters"] / i[name]
        folder.mkdir(parents=True)
        (folder / "abc123.full.jpg").write_bytes(b"jpeg-" + name.encode())
        (folder / "current").write_text("abc123", encoding="utf-8")


def dump(db_path: Path, tables=JOEY_TABLES) -> dict:
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        return {t: sorted(tuple(r) for r in conn.execute(f"SELECT rowid, * FROM {t}")) for t in tables}


def full(db_path: Path) -> list[str]:
    """Every table, row and index of the file, as SQL text (a read-only check: nothing may change)."""
    with closing(sqlite3.connect(db_path)) as conn:
        return list(conn.iterdump())


def one(db_path: Path, sql: str, args=()):
    with closing(sqlite3.connect(db_path)) as conn:
        return conn.execute(sql, args).fetchall()


def rebuilt(env, **kw) -> dict:
    """Index the library, seed Joey rows, rebuild, then two complete fetches. -> {name: (old, new)}."""
    sync(env)
    seed(env)
    sync(env)                      # a fetch with nothing changed
    return env["lib"].rebuild(**kw)


# ---- the whole re-attach ----

def test_a_rebuild_re_attaches_ratings_diary_progress_follows_and_posters(env):
    ids = rebuilt(env)
    before = dump(env["db"])
    new = {n: v[1] for n, v in ids.items()}
    old = {n: v[0] for n, v in ids.items()}
    assert sync(env) is None                   # one fetch alone never applies
    run = sync(env)                            # the second complete fetch: applied on its own (Q2 A)
    assert run and run["mode"] == "apply" and run["trigger"] == "auto"

    you = media_db.get_ratings([f"jf:{new['severance']}", f"jf:{new['home_video']}", f"jf:{new['severance/s2']}",
                                f"jf:{new['severance/s1e2']}", "tmdb:329865"])
    assert you == {f"jf:{new['severance']}": 9, f"jf:{new['home_video']}": 7, f"jf:{new['severance/s2']}": 10,
                   f"jf:{new['severance/s1e2']}": 6, "tmdb:329865": 10}
    assert media_db.get_ratings([f"jf:{new['severance']}"], owner="her") == {f"jf:{new['severance']}": 8}
    diary = one(env["db"], "SELECT item_key, show_key, season_key FROM diary WHERE owner = 'you' AND kind = 'tv'")
    assert diary == [(f"jf:{new['severance/s1e1']}", f"jf:{new['severance']}", f"jf:{new['severance/s1']}")]
    plays = one(env["db"], "SELECT jf_id, show_key, season_key, episode_key, poster, position_pct FROM play "
                           "WHERE kind = 'episode' ORDER BY id")
    assert plays == [(new["severance/s1e3"], f"jf:{new['severance']}", f"jf:{new['severance/s1']}",
                      f"jf:{new['severance/s1e3']}", f"jf:{new['severance']}", 100),
                     (new["severance/s1e3"], f"jf:{new['severance']}", f"jf:{new['severance/s1']}",
                      f"jf:{new['severance/s1e3']}", f"jf:{new['severance']}", 40)]
    assert one(env["db"], "SELECT jf_id FROM play WHERE kind = 'movie'") == [(new["dune"],)]
    assert one(env["db"], "SELECT series_key, episode_id FROM nextup_hidden") == [(f"jf:{new['bluey']}", new["bluey/s1e2"])]
    assert one(env["db"], "SELECT key FROM rating_skip") == [(f"jf:{new['bluey']}",)]
    assert one(env["db"], "SELECT item_key FROM watchlist") == [(f"jf:{new['home_video']}",)]
    assert one(env["db"], "SELECT item_key FROM ranking") == [(f"jf:{new['severance']}",)]
    assert one(env["db"], "SELECT kind, tmdb_id FROM media_follows") == [("show", 95396)]   # TMDB-keyed: untouched
    # posters: the old row and folder stay, the new id gets a copy
    assert {r[0] for r in one(env["db"], "SELECT jf_id FROM poster")} == {old["dune"], old["severance"],
                                                                          new["dune"], new["severance"]}
    for name in ("dune", "severance"):
        assert (env["posters"] / new[name] / "abc123.full.jpg").read_bytes() == b"jpeg-" + name.encode()
        assert (env["posters"] / old[name] / "abc123.full.jpg").exists()
    # no data loss: every table keeps every row it had (poster gains the two copies)
    after = dump(env["db"])
    for t in JOEY_TABLES:
        assert len(after[t]) == len(before[t]) + (2 if t == "poster" else 0), t


def test_no_row_is_deleted_and_only_id_cells_change(env):
    rebuilt(env)
    seeded = dump(env["db"])
    sync(env)
    sync(env)
    after = dump(env["db"])
    changes = one(env["db"], "SELECT table_name, row_ref, column_name, old_value, new_value FROM reattach_change "
                             "WHERE table_name NOT IN ('library_index', 'poster', 'poster_dir')")
    assert changes
    for t in JOEY_TABLES:
        if t == "poster":
            continue
        assert [r[0] for r in after[t]] == [r[0] for r in seeded[t]], t   # same rowids: nothing deleted or added
    with closing(sqlite3.connect(env["db"])) as conn:
        for table, rowid, col, old_v, new_v in changes:
            assert conn.execute(f"SELECT {col} FROM {table} WHERE rowid = ?", (rowid,)).fetchone()[0] == new_v
            assert old_v != new_v


def test_a_backup_is_taken_before_apply(env):
    rebuilt(env)
    sync(env)
    run = sync(env)
    backup = Path(env["tmp"] / "backups" / f"media-pre-reattach-{run['run_id']}.db")
    assert backup.is_file()
    with closing(sqlite3.connect(backup)) as conn:   # the backup holds the pre-apply keys
        assert conn.execute("SELECT COUNT(*) FROM rating WHERE item_key LIKE 'jf:%'").fetchone()[0] == 5


def test_running_it_twice_is_a_no_op(env):
    rebuilt(env)
    sync(env)
    assert sync(env) is not None
    once = dump(env["db"], (*JOEY_TABLES, "reattach_run", "reattach_change"))
    assert reattach.apply(trigger="manual") is None   # nothing left to re-attach
    assert sync(env) is None and sync(env) is None
    assert dump(env["db"], (*JOEY_TABLES, "reattach_run", "reattach_change")) == once


def test_undo_restores_every_cell_and_removes_only_the_copies(env):
    ids = rebuilt(env)
    seeded = dump(env["db"])
    sync(env)
    run = sync(env)
    out = reattach.undo(run["run_id"])
    assert out["restored"] > 0 and out["skipped"] == []
    assert dump(env["db"]) == seeded
    for name in ("dune", "severance"):
        old, new = ids[name]
        assert not (env["posters"] / new).exists() and (env["posters"] / old / "abc123.full.jpg").exists()
    runs = one(env["db"], "SELECT mode, undone_at IS NOT NULL FROM reattach_run ORDER BY id")
    assert ("apply", 1) in runs and ("undo", 0) in runs
    # an undone run is not re-applied by the next fetches (B. undid it on purpose); undo twice is refused
    sync(env)
    sync(env)
    assert dump(env["db"]) == seeded
    with pytest.raises(ValueError):
        reattach.undo(run["run_id"])


def test_undo_skips_a_cell_changed_since_and_lists_it(env):
    ids = rebuilt(env)
    sync(env)
    run = sync(env)
    new_bluey = ids["bluey"][1]
    with closing(media_store.connect()) as db, db:
        db.execute("UPDATE rating_skip SET key = 'jf:" + "9" * 32 + "' WHERE key = ?", (f"jf:{new_bluey}",))
    out = reattach.undo(run["run_id"])
    assert [(s["table"], s["column"]) for s in out["skipped"]] == [("rating_skip", "key")]
    assert one(env["db"], "SELECT key FROM rating_skip") == [("jf:" + "9" * 32,)]
    assert media_db.get_ratings([f"jf:{ids['severance'][0]}"]) == {f"jf:{ids['severance'][0]}": 9}


def test_a_conflicting_row_is_left_alone_and_listed(env):
    ids = rebuilt(env)
    new_sev = ids["severance"][1]
    with closing(media_store.connect()) as db, db:   # B. already rated the new id before the re-attach ran
        db.execute("INSERT INTO rating(item_key, kind, title, score, owner, level) VALUES(?,?,?,?,?,?)",
                   (f"jf:{new_sev}", "tv", "Severance", 5, "you", "show"))
    sync(env)
    run = sync(env)
    assert {"table": "rating", "column": "item_key", "old": f"jf:{ids['severance'][0]}",
            "new": f"jf:{new_sev}"} in [{k: c[k] for k in ("table", "column", "old", "new")} for c in run["conflicts"]]
    assert media_db.get_ratings([f"jf:{new_sev}"]) == {f"jf:{new_sev}": 5}                        # untouched
    assert media_db.get_ratings([f"jf:{ids['severance'][0]}"]) == {f"jf:{ids['severance'][0]}": 9}  # kept, not lost
    assert media_db.get_ratings([f"jf:{new_sev}"], owner="her") == {f"jf:{new_sev}": 8}            # hers moved


# ---- the matching rule and the guards ----

def test_the_dry_run_maps_every_old_id_with_its_tier_and_writes_nothing(env):
    ids = rebuilt(env)
    sync(env)
    before = full(env["db"])
    report = reattach.plan()
    assert full(env["db"]) == before
    tiers = {p["old"]: (p["new"], p["tier"]) for p in report["strong"]}
    assert tiers[ids["arrival"][0]] == (ids["arrival"][1], "tmdb")
    assert tiers[ids["home_video"][0]] == (ids["home_video"][1], "path")   # no provider id: falls to the path
    assert tiers[ids["severance"][0]] == (ids["severance"][1], "tvdb")
    assert tiers[ids["severance/s1e3"][0]] == (ids["severance/s1e3"][1], "series+number")
    assert tiers[ids["severance/s2"][0]] == (ids["severance/s2"][1], "series+number")
    assert report["counts"]["rating.item_key"] == 5 and report["counts"]["play.jf_id"] == 3
    assert report["weak"] == [] and report["ambiguous"] == []


def test_without_provider_ids_the_path_still_matches(env):
    ids = rebuilt(env, drop_provider_ids=("tmdb", "imdb", "tvdb"))
    sync(env)
    run = sync(env)
    assert run is not None
    tiers = {p["old"]: p["tier"] for p in run["strong"]}
    assert tiers[ids["arrival"][0]] == "path" and tiers[ids["severance"][0]] == "path"


def test_a_moved_library_matches_through_the_configured_prefixes(env, monkeypatch):
    monkeypatch.setenv("LIBRARY_PATH_PREFIXES", "/data/media,/mnt/media")
    ids = rebuilt(env, drop_provider_ids=("tmdb", "imdb", "tvdb"), move_prefix="/mnt/media")
    sync(env)
    run = sync(env)
    assert {p["old"]: p["tier"] for p in run["strong"]}[ids["home_video"][0]] == "path"


def test_title_and_year_matches_are_reported_not_applied(env):
    ids = rebuilt(env, drop_provider_ids=("tmdb", "imdb", "tvdb"), move_prefix="/mnt/elsewhere")
    seeded = dump(env["db"])
    sync(env)
    run = sync(env)
    assert dump(env["db"]) == seeded                               # nothing moved
    assert run is not None and run["mode"] == "report"
    weak = {p["old"]: (p["new"], p["tier"]) for p in run["weak"]}
    assert weak[ids["severance"][0]] == (ids["severance"][1], "title+year")
    assert weak[ids["home_video"][0]] == (ids["home_video"][1], "title+year")
    assert run["strong"] == []
    assert sync(env) is None                                       # the same report is not stored again


def test_two_candidates_for_one_old_id_are_ambiguous(env):
    lib = env["lib"]
    lib.add_duplicate_film("dune_copy", "dune", "/movies-4k/Dune (2021)/Dune.mkv")   # a second library's copy
    sync(env)
    seed(env)
    sync(env)
    ids = lib.rebuild(move_prefix="/mnt/elsewhere")                # same TMDB id twice, no path to break the tie
    sync(env)
    run = sync(env)
    assert ids["dune"][0] in [a["old"] for a in run["ambiguous"]]
    assert ids["dune"][0] not in [p["old"] for p in run["strong"]]
    assert one(env["db"], "SELECT jf_id FROM play WHERE kind = 'movie'") == [(ids["dune"][0],)]   # not moved
    assert ids["arrival"][0] in [p["old"] for p in run["strong"]]


def test_a_half_scanned_library_holds_the_run(env):
    rebuilt(env, partial=True)
    seeded = dump(env["db"])
    assert sync(env) is None and sync(env) is None
    assert dump(env["db"]) == seeded


def test_the_cli_dry_run_prints_pass_lines_and_changes_nothing(env, capsys):
    rebuilt(env)
    sync(env)
    before = full(env["db"])
    assert reattach.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out and "strong" in out
    assert full(env["db"]) == before


def test_the_cli_applies_and_undoes(env, capsys):
    rebuilt(env)
    seeded = dump(env["db"])
    sync(env)                                    # one fetch: the auto step holds, the CLI may go ahead (JY-059 move)
    assert reattach.main(["--apply"]) == 0
    run_id = one(env["db"], "SELECT id FROM reattach_run WHERE mode = 'apply'")[0][0]
    assert dump(env["db"]) != seeded
    assert reattach.main(["--undo", str(run_id)]) == 0
    assert dump(env["db"]) == seeded
    assert "FAIL" not in capsys.readouterr().out
