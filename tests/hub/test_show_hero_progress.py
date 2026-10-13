"""Show hero progress words (WP E6, 2026-10-13; E5's M2 words on the show page): the status line of a show on the server
reads "On server · 6 episodes · 2 left · ~1h 30m · S4 E4 next" — the hours from the recorded plays' average episode
runtime of that show (media_plays_db.show_runtimes), "2 left" without one, "all watched" at 0, unchanged on an episode
page. Jellyfin and Jellyseerr are faked (tests/hub/helpers)."""
from contextlib import closing

from hub import media_store
from tests.hub.helpers import env  # noqa: F401  (env: the film-page fixture)
from tests.hub.test_media_film import status


def recorded(show_key, runtime):
    with closing(media_store.connect()) as db, db:
        db.execute("INSERT INTO play(user_name, owner, jf_id, show_key, kind, runtime_min, started_at, last_seen_at,"
                   " position_pct, finished) VALUES('u', 'you', 'epx', ?, 'episode', ?, '2026-10-11T10:00:00Z',"
                   " '2026-10-11T10:45:00Z', 100, 1)", (show_key, runtime))


def test_show_status_line_gains_hours_from_recorded_plays(env):
    client, _ = env()
    with client:
        assert status(client.get("/media/item/ser1").text) == "On server · 6 episodes · 2 left · S4 E4 next"
        recorded("jf:ser1", 45)
        assert status(client.get("/media/item/ser1").text) == "On server · 6 episodes · 2 left · ~1h 30m · S4 E4 next"
        assert status(client.get("/media/title/tv/100").text) == "On server · 6 episodes · 2 left · ~1h 30m · S4 E4 next"


def test_another_shows_plays_lend_no_hours(env):
    client, _ = env()
    with client:
        recorded("jf:other", 45)
        assert "~" not in status(client.get("/media/item/ser1").text)


def test_episode_page_keeps_its_own_line(env):
    client, _ = env()
    with client:
        recorded("jf:ser1", 45)
        line = status(client.get("/media/item/ep3").text)
    assert "left" not in line and "~" not in line
