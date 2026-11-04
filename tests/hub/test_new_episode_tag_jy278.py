"""JY-278: the "New episode" tag on Recently added show tiles. Spec docs/specs/JY-278-new-episode-tag.md."""
import re
from datetime import timedelta

from fastapi.testclient import TestClient

from hub import media_home
from tests.hub.helpers import JELLY, NOW
from tests.hub.test_media_shelves import env, main_html  # noqa: F401  (env: the shelves fixture)

AGO = lambda h: (NOW - timedelta(hours=h)).isoformat()   # noqa: E731


def ep(n, hours):
    return {"title": f"Billions · S07E0{n}", "show_title": "Billions", "type": "Episode", "item_key": "jf:" + str(n) * 32,
            "jf_id": str(n) * 32, "poster": None, "added_at": AGO(hours)}


SERIES = {"title": "Billions", "type": "Series", "item_key": "tmdb:62852", "jf_id": "b" * 32, "poster": "jf:" + "b" * 32,
          "added_at": AGO(1)}
NEW_SHOW = {"title": "Brand New Show", "type": "Series", "item_key": "tmdb:77", "jf_id": "a" * 32,
            "poster": "jf:" + "a" * 32, "added_at": AGO(4)}


def jelly(*latest):
    return {**JELLY, "server_id": "srv", "now_playing": [], "up_next": [], "latest": list(latest)}


def added_html(main):
    with TestClient(main.app) as client:
        html = main_html(client.get("/a/alpha").text)
    return html.split('class="seclabel">Recently added', 1)[1].split("</section>", 1)[0]


def test_existing_show_with_three_episodes_is_one_tagged_tile_and_new_show_untagged(env):
    main = env(jellyfin=jelly(SERIES, ep(1, 2), ep(2, 2), ep(3, 3), NEW_SHOW), arr={"summary": "x", "arrived": []})
    added = added_html(main)
    assert re.findall(r'class="row-title">([^<]+)<', added) == ["Billions", "Brand New Show"]
    assert added.count('class="newep"') == 1 and ">3 new episodes<" in added
    tiles = added.split('class="card-poster"')[1:]
    assert "new episodes" in tiles[0] and "newep" not in tiles[1]


def test_one_new_episode_is_singular(env):
    main = env(jellyfin=jelly(SERIES, ep(1, 2), NEW_SHOW), arr={"summary": "x", "arrived": []})
    added = added_html(main)
    assert ">New episode<" in added and "1 new episode" not in added


def test_arr_arrival_count_and_whole_show_rules():
    now = NOW
    arr = {"item_key": "tvdb:259", "kind": "season", "title": "Billions · 3 episodes", "when": "3 hours ago", "poster": None}
    rows = media_home.added_rows([SERIES], [arr], now)
    assert [r["new_episodes"] for r, _, _ in rows] == [3]            # the arrival's own count
    assert media_home.added_rows([NEW_SHOW], [], now)[0][0]["new_episodes"] == 0    # a whole new show: no tag
    movie = {"title": "Fresh Film", "type": "Movie", "item_key": "tmdb:5", "jf_id": "f" * 32, "added_at": AGO(3)}
    assert media_home.added_rows([movie], [], now)[0][0]["new_episodes"] == 0
    assert media_home.new_episode_words(0) == "" and media_home.new_episode_words(2) == "2 new episodes"


def test_kept_tile_is_the_jellyfin_series_row():
    arr = {"item_key": "tvdb:259", "kind": "season", "title": "Billions · 3 episodes", "when": "3 hours ago", "poster": None}
    for latest in ([ep(1, 3), SERIES, ep(2, 2)], [SERIES, ep(1, 3)]):   # the series row wins even behind its episodes
        rows = media_home.added_rows(latest, [arr], NOW)
        kept, _, from_jf = rows[0]
        assert len(rows) == 1 and from_jf is True
        assert kept["type"] == "Series" and kept["poster"] == "jf:" + "b" * 32


def test_tv_caption_carries_the_words(env):
    main = env(jellyfin=jelly(SERIES, ep(1, 2), ep(2, 2)), arr={"summary": "x", "arrived": []})
    added = added_html(main)
    assert 'class="row-meta newep-cap">2 new episodes<' in added   # css shows it on the TV, the pill off it


def test_friends_tv_home_added_collapses_a_show_and_carries_the_count():
    from hub import media_guest_home
    out = media_guest_home._added(jelly(ep(1, 3), SERIES, ep(2, 2), NEW_SHOW))
    assert [(t["title"], t["new_episodes"]) for t in out] == [("Billions", 2), ("Brand New Show", 0)]
    assert out[0]["poster"] == "jf:" + "b" * 32
