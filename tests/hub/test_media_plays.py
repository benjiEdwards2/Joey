"""F7 play recorder + History page + Home "Most played" shelf (2026-10-06): a watch, not a sitting."""
import asyncio
import importlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from hub import media_plays as mp, media_plays_db as pdb
from tests.hub.test_media_shelves import ids, main_html, shelf_area
from tests.hub.test_registry import make_area, write_registry
from tests.hub.test_store import write_envelope

T0 = datetime(2026, 10, 6, 2, 0, tzinfo=timezone.utc)
MIN = 600_000_000  # ticks per minute


def session(user="Sample Person", item_id="m1", kind="Movie", pos_min=10, run_min=100, **extra):
    item = {"Id": item_id, "Name": "The Long Road Home", "Type": kind, "RunTimeTicks": run_min * MIN,
            "ProviderIds": {"Tmdb": "101"}}
    if kind == "Episode":
        item.update(SeriesName="Quiet Coast", SeriesId="s1", SeasonId="se1", ParentIndexNumber=2,
                    IndexNumber=4, Name="Late Tide")
    item.update(extra)
    return {"UserName": user, "NowPlayingItem": item, "PlayState": {"PositionTicks": pos_min * MIN}}


class FakeGet:
    def __init__(self, sessions=None, error=None):
        self.sessions, self.error, self.calls = sessions or [], error, 0

    def __call__(self, url, headers=None, timeout=None, **kw):
        self.calls += 1
        assert url.endswith("/Sessions") and headers["Authorization"].startswith("MediaBrowser Token=")
        if self.error:
            raise self.error
        fake = self
        return type("R", (), {"status_code": 200, "json": lambda s: fake.sessions})()


@pytest.fixture()
def rec(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("JELLYFIN_URL", "http://jf.invalid")
    monkeypatch.setenv("JELLYFIN_API_KEY", "k")
    monkeypatch.setenv("JELLYFIN_USER_HER", "Sample Partner")
    monkeypatch.delenv("PLAY_RECORDER", raising=False)

    def poll(sessions, at):
        monkeypatch.setattr(mp.jellyfin.requests, "get", FakeGet(sessions))
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
    idle = {"UserName": "Sample Person", "PlayState": {}}
    music = session(kind="Audio", item_id="a1")
    assert rec([session(user="Sample Partner"), session(user="Sample Person", item_id="m2"), idle, music], T0) == 2
    assert {r["user_name"]: r["owner"] for r in rows(tmp_path)} == {"Sample Partner": "her", "Sample Person": "you"}


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
        assert 'aria-current="page"' in body and ">History<" in body


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
