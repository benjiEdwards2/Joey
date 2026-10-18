"""F7 play recorder + History page + Home "Most played" shelf (2026-10-06): a watch, not a sitting."""
import asyncio
import importlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from hub import media_plays as mp, media_plays_db as pdb
from tests.hub.helpers import make_area, shelf_area, write_envelope, write_registry
from tests.hub.test_media_shelves import ids, main_html

T0 = datetime(2026, 10, 6, 2, 0, tzinfo=timezone.utc)
MIN = 600_000_000  # ticks per minute
# Jellyfin user ids (Joey TV WP-A2: plays are attributed by UserId, never by the renamable UserName)
USER_IDS = {"Sample Person": "11111111111111111111111111111111", "Sample Partner": "22222222222222222222222222222222",
            "Sample Friend": "ABCDEF0123456789ABCDEF0123456789"}
USERS = [{"Name": name, "Id": uid.lower()} for name, uid in USER_IDS.items()]
FRIEND_KEY = "jf:abcdef0123456789abcdef0123456789"


def session(user="Sample Person", item_id="m1", kind="Movie", pos_min=10, run_min=100, uid=None, **extra):
    item = {"Id": item_id, "Name": "The Long Road Home", "Type": kind, "RunTimeTicks": run_min * MIN,
            "ProviderIds": {"Tmdb": "101"}}
    if kind == "Episode":
        item.update(SeriesName="Quiet Coast", SeriesId="s1", SeasonId="se1", ParentIndexNumber=2,
                    IndexNumber=4, Name="Late Tide")
    item.update(extra)
    return {"UserName": user, "UserId": uid or USER_IDS.get(user), "NowPlayingItem": item,
            "PlayState": {"PositionTicks": pos_min * MIN}}


class FakeGet:
    def __init__(self, sessions=None, error=None, users=USERS, users_error=None):
        self.sessions, self.error, self.calls = sessions or [], error, 0
        self.users, self.users_error, self.user_calls = users, users_error, 0

    def __call__(self, url, headers=None, timeout=None, **kw):
        self.calls += 1
        assert headers["Authorization"].startswith("MediaBrowser Token=")
        if url.endswith("/Users"):
            self.user_calls += 1
            if self.users_error:
                raise self.users_error
            body = self.users
        else:
            assert url.endswith("/Sessions")
            if self.error:
                raise self.error
            body = self.sessions
        return type("R", (), {"status_code": 200, "json": lambda s: body})()


@pytest.fixture()
def rec(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("JELLYFIN_URL", "http://jf.invalid")
    monkeypatch.setenv("JELLYFIN_API_KEY", "k")
    monkeypatch.setenv("JELLYFIN_USER", "Sample Person")
    monkeypatch.setenv("JELLYFIN_USER_HER", "Sample Partner")
    monkeypatch.delenv("JELLYFIN_USER_ALIASES", raising=False)
    monkeypatch.delenv("PLAY_RECORDER", raising=False)

    def poll(sessions, at, **fake):
        monkeypatch.setattr(mp.jellyfin.requests, "get", FakeGet(sessions, **fake))
        return mp.poll_once(at)
    return poll


def rows(tmp_path):
    with sqlite3.connect(tmp_path / "media.db") as c:
        c.row_factory = sqlite3.Row
        return c.execute("SELECT * FROM play ORDER BY id").fetchall()


def test_insert_then_update_position(rec, tmp_path):
    assert rec([session(pos_min=10)], T0) == 1
    rec([session(pos_min=40)], T0 + timedelta(minutes=1))
    r = rows(tmp_path)
    assert len(r) == 1 and r[0]["position_pct"] == 40 and r[0]["finished"] == 0
    assert r[0]["started_at"] != r[0]["last_seen_at"] and r[0]["runtime_min"] == 100
    assert r[0]["item_key"] == "tmdb:101" and r[0]["poster"] == "jf:m1" and r[0]["kind"] == "movie"


def test_episode_fields(rec, tmp_path):
    rec([session(kind="Episode", item_id="e1")], T0)
    r = rows(tmp_path)[0]
    assert (r["kind"], r["show_key"], r["season_key"], r["episode_key"], r["show_title"],
            r["season"], r["episode"], r["poster"]) == ("episode", "jf:s1", "jf:se1", "jf:e1", "Quiet Coast", 2, 4, "jf:s1")


def test_closes_at_90_and_next_sighting_is_a_new_play(rec, tmp_path):
    rec([session(pos_min=50)], T0)
    rec([session(pos_min=95)], T0 + timedelta(minutes=1))
    assert [(r["position_pct"], r["finished"]) for r in rows(tmp_path)] == [(95, 1)]
    rec([session(pos_min=1)], T0 + timedelta(minutes=2))
    assert len(rows(tmp_path)) == 2


def test_two_hour_gap_starts_a_new_play(rec, tmp_path):
    rec([session(pos_min=10)], T0)
    rec([session(pos_min=12)], T0 + timedelta(hours=2, minutes=1))
    assert len(rows(tmp_path)) == 2


def test_owner_mapping_and_ignored_sessions(rec, tmp_path):
    idle = {"UserName": "Sample Person", "UserId": USER_IDS["Sample Person"], "PlayState": {}}
    music = session(kind="Audio", item_id="a1")
    assert rec([session(user="Sample Partner"), session(user="Sample Person", item_id="m2"), idle, music], T0) == 2
    assert {r["user_name"]: r["owner"] for r in rows(tmp_path)} == {"Sample Partner": "her", "Sample Person": "you"}


# ---- owner keys (Joey TV WP-A2, 2026-10-18): a friend is jf:<id>, never "you" ----

def test_friend_play_is_keyed_by_lowercase_user_id(rec, tmp_path):                         # (a)
    assert rec([session(user="Sample Friend", uid=USER_IDS["Sample Friend"])], T0) == 1
    r = rows(tmp_path)
    assert [(x["owner"], x["user_name"]) for x in r] == [(FRIEND_KEY, "Sample Friend")]


def test_session_without_user_id_is_skipped(rec, tmp_path):                                 # (c)
    no_id = session(item_id="m2")
    del no_id["UserId"]
    blank = {**session(item_id="m3"), "UserId": ""}
    bad = session(item_id="m4", uid="not-a-jellyfin-id")
    assert rec([no_id, blank, bad, session()], T0) == 1
    assert [(x["jf_id"], x["owner"]) for x in rows(tmp_path)] == [("m1", "you")]


def test_renamed_friend_is_one_play(rec, tmp_path):                                         # (d)
    friend = USER_IDS["Sample Friend"]
    rec([session(user="Sample Friend", uid=friend, pos_min=10)], T0)
    rec([session(user="Sample Friend Renamed", uid=friend, pos_min=30)], T0 + timedelta(minutes=1))
    r = rows(tmp_path)
    assert len(r) == 1 and r[0]["owner"] == FRIEND_KEY and r[0]["position_pct"] == 30


def test_unset_jellyfin_user_records_nobody_as_you(rec, tmp_path, monkeypatch):            # (e)
    monkeypatch.delenv("JELLYFIN_USER")
    rec([session(), session(user="Sample Partner", item_id="m2")], T0)
    assert {x["user_name"]: x["owner"] for x in rows(tmp_path)} == {
        "Sample Person": "jf:" + USER_IDS["Sample Person"], "Sample Partner": "her"}


def test_users_read_failing_records_nothing_then_the_next_poll_retries(rec, tmp_path):      # (i)
    assert rec([session()], T0, users_error=ConnectionError("http://jf.invalid secret")) == 0
    assert not (tmp_path / "media.db").exists() or rows(tmp_path) == []
    assert rec([session()], T0 + timedelta(minutes=1)) == 1
    assert [x["owner"] for x in rows(tmp_path)] == ["you"]


def test_household_ids_are_read_once_across_polls(rec, tmp_path, monkeypatch):            # (h, recorder side)
    fake = FakeGet([session()])
    monkeypatch.setattr(mp.jellyfin.requests, "get", fake)
    mp.poll_once(T0)
    fake.users = [{"Name": "Brand New Name", "Id": USER_IDS["Sample Person"]}]          # B. renamed in Jellyfin
    mp.poll_once(T0 + timedelta(minutes=1))
    assert fake.user_calls == 1 and [x["owner"] for x in rows(tmp_path)] == ["you"]


def test_upstream_failure_does_not_crash(rec, tmp_path, monkeypatch):
    monkeypatch.setattr(mp.jellyfin.requests, "get", FakeGet(error=ConnectionError("http://jf.invalid secret")))
    assert mp.poll_once(T0) == 0
    assert not (tmp_path / "media.db").exists() or rows(tmp_path) == []


def test_disabled_means_no_task_and_no_requests(tmp_path, monkeypatch):
    fake = FakeGet([session()])
    monkeypatch.setattr(mp.jellyfin.requests, "get", fake)
    monkeypatch.setenv("JELLYFIN_URL", "http://jf.invalid")
    monkeypatch.setenv("JELLYFIN_API_KEY", "k")
    monkeypatch.setenv("PLAY_RECORDER", "off")
    assert mp.disabled() and mp.start_recorder() is None and fake.calls == 0
    monkeypatch.delenv("PLAY_RECORDER")
    monkeypatch.delenv("JELLYFIN_API_KEY")
    assert mp.disabled() and mp.start_recorder() is None and fake.calls == 0

    async def started():
        monkeypatch.setenv("JELLYFIN_API_KEY", "k")
        task = mp.start_recorder()
        assert task is not None
        task.cancel()
    asyncio.run(started())


# ---- queries ----

def seed(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    now = datetime.now(timezone.utc)

    def play(user, owner, jf, kind, title, show, minutes, ago_days, run=100, pos=100, key=None, hour=None):
        start = (now - timedelta(days=ago_days)).replace(microsecond=0)
        if hour is not None:
            start = start.replace(hour=hour, minute=0, second=0)
        pdb.record_sighting({"user_name": user, "owner": owner, "jf_id": jf, "item_key": key or f"jf:{jf}",
                             "show_key": "jf:" + show if show else None, "title": title, "show_title": show,
                             "kind": kind, "runtime_min": run, "position_pct": 1, "poster": f"jf:{jf}"}, start)
        pdb.record_sighting({"user_name": user, "owner": owner, "jf_id": jf, "item_key": key or f"jf:{jf}",
                             "show_key": "jf:" + show if show else None, "title": title, "show_title": show,
                             "kind": kind, "runtime_min": run, "position_pct": pos, "poster": f"jf:{jf}"},
                            start + timedelta(minutes=minutes))
    play("u", "you", "e1", "episode", "Pilot", "Quiet Coast", 30, 1, run=30)
    play("u", "you", "e2", "episode", "Two", "Quiet Coast", 30, 2, run=30)
    play("u", "you", "m1", "movie", "Long Road", None, 90, 3, run=100, key="tmdb:1")
    play("p", "her", "m2", "movie", "Old Film", None, 110, 60, run=60, key="tmdb:2")  # 110 min seen, capped at its 60-min runtime
    return now


def test_windows_owner_and_hours_cap(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    s30 = pdb.stats(30)
    assert s30["plays"] == 3 and s30["hours"] == 2.5  # 0.5 + 0.5 + 1.5
    assert pdb.stats(7)["plays"] == 3 and pdb.stats(90)["plays"] == 4 and pdb.stats("all")["plays"] == 4
    assert pdb.stats("all")["hours"] == 3.5  # the 110-min sighting is capped at its 60-min runtime
    assert pdb.stats("all", owner="her")["plays"] == 1 and pdb.stats("all", owner="you")["plays"] == 3
    assert pdb.stats("year")["plays"] >= 3
    assert len(pdb.stats(30)["by_hour"]) == 24 and sum(pdb.stats(30)["by_hour"]) == 3
    assert pdb.stats(30)["busiest_day"]["plays"] == 1


def test_top_lists_group_episodes_by_show(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    s = pdb.stats(30)
    assert [(e["title"], e["episodes"], e["hours"]) for e in s["top_shows"]] == [("Quiet Coast", 2, 1.0)]
    assert [(e["title"], e["plays"], e["hours"]) for e in s["top_movies"]] == [("Long Road", 1, 1.5)]
    shows, movies = pdb.most_played_30()
    assert len(shows) == 1 and len(movies) == 1
    assert pdb.hours_text(1) == "1 hour" and pdb.hours_text(12.5) == "12.5 hours"


def seed_with_friend(tmp_path, monkeypatch):
    """One finished film each for you and her, and two for a friend (Joey TV Q15): one of the same film, a day before
    the household's first play, and an episode of a show nobody else watched. Fixed clock (T0)."""
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))

    def play(owner, jf, title, at, kind="movie", show=None):
        base = {"user_name": "u", "owner": owner, "jf_id": jf, "item_key": f"jf:{jf}", "title": title,
                "show_key": f"jf:{show}" if show else None, "show_title": show, "kind": kind, "runtime_min": 60,
                "poster": f"jf:{jf}"}
        pdb.record_sighting({**base, "position_pct": 1}, at)
        pdb.record_sighting({**base, "position_pct": 100}, at + timedelta(minutes=60))
    play("you", "m1", "Long Road", T0)
    play("her", "m2", "Old Film", T0 + timedelta(hours=3))
    play(FRIEND_KEY, "m1", "Long Road", T0 - timedelta(days=1))
    play(FRIEND_KEY, "e9", "Friend Episode", T0 + timedelta(hours=6), kind="episode", show="Friend Show")


def test_private_reads_never_count_a_friends_play(tmp_path, monkeypatch):
    seed_with_friend(tmp_path, monkeypatch)
    later = T0 + timedelta(days=1)
    both, you, her = (pdb.stats("all", o, later) for o in (None, "you", "her"))
    assert (both["plays"], both["hours"]) == (2, 2.0)                                     # History + Hours
    assert [e["title"] for e in both["top_movies"]] == ["Long Road", "Old Film"] and both["top_shows"] == []
    assert both["top_movies"][0]["plays"] == 1
    assert (you["plays"], her["plays"]) == (1, 1) and sum(both["by_hour"]) == 2
    for owner in (None, "you", "her"):                                                    # Most played
        shows, movies = pdb.most_played_30(owner, later)
        assert shows == [] and all(m["plays"] == 1 for m in movies)
    assert (pdb.watch_count("m1"), pdb.watch_count("m1", "you"), pdb.watch_count("m1", "her")) == (1, 1, 0)
    assert pdb.watch_count("e9") == 0
    assert pdb.first_run_date() == "2026-10-06"                                           # the friend's 5 Oct is not it
    assert pdb.show_runtimes(["jf:Friend Show"]) == {}


def test_history_page_never_shows_a_friends_play(env, tmp_path, monkeypatch):
    seed_with_friend(tmp_path, monkeypatch)
    with TestClient(env.app) as client:
        for view in ("both", "you", "her"):
            body = main_html(client.get(f"/media/server/history?w=all&owner_view={view}").text)
            assert "Friend Show" not in body and "Friend Episode" not in body
        both = main_html(client.get("/media/server/history?w=all&owner_view=both").text)
        assert '>Plays</div><div class="stat-number">2</div>' in both


def test_everyone_diary_scope_skips_friend_rows(tmp_path, monkeypatch):
    from hub import media_db
    from tests.hub.helpers import diary
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    diary("tmdb:1", "movie", "Long Road", "2026-10-05")
    diary("tmdb:2", "movie", "Friend Film", "2026-10-05", owner=FRIEND_KEY)
    assert [r["title"] for r in media_db.list_diary(owner=None)] == ["Long Road"]


def test_stats_with_no_db_is_quiet(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "none.db"))
    s = pdb.stats(30)
    assert s["plays"] == 0 and s["top_shows"] == [] and s["busiest_day"] is None
    assert not (tmp_path / "none.db").exists()


# ---- pages ----

@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, shelf_area(), make_area("beta"))))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.setenv("PLAY_RECORDER", "off")
    import hub.main
    importlib.reload(hub.main)
    return hub.main


def test_history_page_empty_in_frame(env, tmp_path):
    with TestClient(env.app) as client:
        r = client.get("/media/server/history")
        assert r.status_code == 200
        body = main_html(r.text)
        assert "No plays recorded yet — the recorder started on" in body
        for chip in ("7 days", "30 days", "90 days", "This year", "All time"):
            assert chip in body
        # nav-tidy (2026-10-13, B.): "Play stats" — under Activity with no tab of its own (History is the diary now)
        assert r.text.split("<title>", 1)[1].split("</title>", 1)[0] == "Play stats · Joey"
        sub = r.text.split('<nav class="sectabs sub"', 1)[1].split("</nav>", 1)[0]
        assert 'href="/media/diary">History<' in sub and 'aria-current="page"' not in sub


def test_history_page_with_data(env, tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    with TestClient(env.app) as client:
        body = main_html(client.get("/media/server/history?w=all").text)
        assert '>Plays</div><div class="stat-number">4</div>' in body and "3.5 hours" in body
        assert "Quiet Coast" in body and "Long Road" in body and "2 episodes" in body
        assert '<a class="row" href=' in body and "Busiest day" in body and body.count('class="hourbar"') == 24
        assert "/media/server/history?w=7" in body
        her = main_html(client.get("/media/server/history?w=all&owner_view=her").text)
        assert "1 play" in her and "Old Film" in her and "Quiet Coast" not in her


def test_home_shelf_present_when_data_and_omitted_when_empty(env, tmp_path, monkeypatch):
    with TestClient(env.app) as client:
        assert "Most played" not in client.get("/a/alpha").text
        seed(tmp_path, monkeypatch)
        body = main_html(client.get("/a/alpha").text)
        assert "Most played · 30 days" in body and "2 episodes · 1.0 h" in body and "1 play · 1.5 h" in body
        assert 'href="/media/server/history"' in body
        sh = None
        area = next(a for a in env.shell.registry.areas if a.id == "alpha")
        snaps = env.get_snapshots()
        tiles = [{"tile": t, "st": env.tile_state(t, snaps)} for t in area.tiles]
        sh = env.build_shelves(area, tiles, snaps, "you")
        assert ids(sh)[-1] == "mostplayed"
