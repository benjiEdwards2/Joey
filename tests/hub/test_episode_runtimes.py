"""JY-104 (2026-10-24): episode runtimes from Jellyfin item data. The hours in a show's progress words ("2 left · ~1h")
come from the average RunTimeTicks of the show's episodes in the item read the hub already makes (the show page's
/Shows/{id}/Episodes read; elsewhere the cached read via media_item.peek, never a new Jellyfin call). The recorded
plays' average stays the fallback. Jellyfin is faked (tests/hub/helpers)."""
import html
import re
from contextlib import closing

from hub import media_home, media_item, media_store
from tests.hub import helpers
from tests.hub.helpers import TICKS, env  # noqa: F401  (env: the film-page fixture)


def status(page):
    return html.unescape(re.search(r'id="status-line">([^<]*)<', page).group(1))


def recorded(show_key, runtime):
    with closing(media_store.connect()) as db, db:
        db.execute("INSERT INTO play(user_name, owner, jf_id, show_key, kind, runtime_min, started_at, last_seen_at,"
                   " position_pct, finished) VALUES('u', 'you', 'epx', ?, 'episode', ?, '2026-10-11T10:00:00Z',"
                   " '2026-10-11T10:45:00Z', 100, 1)", (show_key, runtime))


def timed(monkeypatch, minutes=30):
    """The fake show's aired episodes carry RunTimeTicks; the unaired one (ep6) has none, as Jellyfin's often do."""
    eps = [dict(e, RunTimeTicks=minutes * TICKS) if e["Id"] != "ep6" else e for e in helpers.EPISODES]
    monkeypatch.setattr(helpers, "EPISODES", eps)


def test_episode_runtime_averages_episodes_with_a_runtime():
    seasons = [{"episodes": [{"runtime_min": 30}, {"runtime_min": None}]}, {"episodes": [{"runtime_min": 50}]}]
    assert media_item.episode_runtime(seasons) == 40
    assert media_item.episode_runtime([{"episodes": [{"runtime_min": None}]}]) is None
    assert media_item.episode_runtime(None) is None and media_item.episode_runtime([]) is None


def test_show_hero_hours_from_jellyfin_without_plays(env, monkeypatch):
    timed(monkeypatch)
    client, _ = env()
    with client:
        assert status(client.get("/media/item/ser1").text) == "On server · 6 episodes · 2 left · ~1h · S4 E4 next"


def test_jellyfin_runtimes_beat_recorded_plays(env, monkeypatch):
    timed(monkeypatch)
    client, _ = env()
    with client:
        recorded("jf:ser1", 45)
        assert status(client.get("/media/item/ser1").text) == "On server · 6 episodes · 2 left · ~1h · S4 E4 next"


def test_library_rows_use_the_cached_item_read(env, monkeypatch):
    timed(monkeypatch)
    shows = [{**helpers.LIB_SHOWS[0], "episodes": 6, "unplayed": 2}]
    client, fake = env(jelly_extra={"shows": shows})
    with client:
        page = client.get("/media/tv?view=list").text
        assert "6 episodes · 2 left" in page and "2 left · ~" not in page        # nothing cached yet: no hours
        client.get("/media/item/ser1")                                          # the show's page fills the cache
        before = len(fake.jf.calls)
        assert "6 episodes · 2 left · ~1h" in client.get("/media/tv?view=list").text
        assert len(fake.jf.calls) == before                                     # the list made no Jellyfin read


def test_show_runtimes_prefers_item_data_then_plays(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    cached = {"s1": {"seasons": [{"episodes": [{"runtime_min": 42}]}]},
              "s3": {"seasons": [{"episodes": [{"runtime_min": None}]}]}}
    monkeypatch.setattr(media_item, "peek", lambda jf: cached.get(jf))
    recorded("jf:s1", 60)
    recorded("jf:s2", 50)
    recorded("jf:s3", 20)
    assert media_item.show_runtimes(k for k in ["jf:s1", "jf:s2", "jf:s3", "jf:s4", None]) == {
        "jf:s1": 42, "jf:s2": 50.0, "jf:s3": 20.0}


def test_continue_progress_uses_item_data(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setattr(media_item, "peek",
                        lambda jf: {"seasons": [{"episodes": [{"runtime_min": 30}]}]} if jf == "s1" else None)
    data = {"shows": [{"jf_id": "s1", "unplayed": 4, "episodes": 10}]}
    assert media_home.continue_progress(data, "you", [{"show_key": "jf:s1"}]) == {"jf:s1": "4 left · ~2h"}
