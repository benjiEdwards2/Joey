"""JY-276 / JY-277 option B / JY-278: the web Home's pill carousel, one tile per show, and the shelves
that left Home (Because you rated, Most played, the follow shelf). Spec docs/specs/JY-277-overview-B.md."""
import re
from datetime import timedelta

from fastapi.testclient import TestClient

from tests.hub.helpers import JELLY, NOW
from tests.hub.test_media_shelves import env, ids, main_html  # noqa: F401  (env: the shelves fixture)

AGO = lambda h: (NOW - timedelta(hours=h)).isoformat()   # noqa: E731

HOME_JELLY = {
    **JELLY, "server_id": "srv", "now_playing": [],
    "latest": [
        {"title": "Billions", "type": "Series", "item_key": "tmdb:62852", "jf_id": "b" * 32, "poster": "jf:" + "b" * 32,
         "added_at": AGO(1)},
        {"title": "Billions", "type": "Season", "item_key": "jf:" + "c" * 32, "jf_id": "c" * 32, "poster": None,
         "added_at": AGO(2)},
        {"title": "Fresh Film", "type": "Movie", "item_key": "tmdb:5", "jf_id": "f" * 32, "poster": "jf:" + "f" * 32,
         "added_at": AGO(3)},
    ],
    "up_next": [
        {"title": "Quiet Show · S01E02", "show_title": "Quiet Show", "remaining_text": "31 min left", "poster": None,
         "jf_id": "e" * 32, "item_key": "jf:" + "9" * 32, "show_key": "jf:" + "9" * 32},
        {"title": "Quiet Show · S01E03", "show_title": "Quiet Show", "remaining_text": "Next up", "poster": None,
         "jf_id": "d" * 32, "item_key": "jf:" + "9" * 32, "show_key": "jf:" + "9" * 32},
    ],
    "movies": [
        {"title": "Unseen Film", "jf_id": "1" * 32, "item_key": "tmdb:11", "poster": None, "played": False,
         "added_at": AGO(5), "community_rating": 8.1},
        {"title": "Seen Film", "jf_id": "2" * 32, "item_key": "tmdb:12", "poster": None, "played": True,
         "added_at": AGO(6), "community_rating": 9.2},
    ],
    "shows": [
        {"title": "New Show", "jf_id": "3" * 32, "item_key": "tmdb:13", "poster": None, "played": False,
         "added_at": AGO(4), "episodes": 8, "unplayed": 8, "community_rating": 7.0},
        {"title": "Started Show", "jf_id": "4" * 32, "item_key": "tmdb:14", "poster": None, "played": False,
         "added_at": AGO(7), "episodes": 8, "unplayed": 3},
    ],
}
ARR_HOME = {"summary": "x", "arrived": [{"item_key": "tvdb:259", "kind": "season", "title": "Billions · 3 episodes",
                                         "when": "3 hours ago", "poster": None}]}


def slide_titles(html):
    return re.findall(r'class="homecar-title"(?: hidden)?>([^<]+)<', html)


def pill_get(client, pill):
    r = client.get(f"/a/alpha/carousel?s={pill}", headers={"HX-Request": "true"})
    assert r.status_code == 200 and "<html" not in r.text and r.text.lstrip().startswith("<section class=\"homecar\"")
    return r


def test_each_pill_returns_its_own_set(env):
    main = env(jellyfin=HOME_JELLY, arr=ARR_HOME)
    with TestClient(main.app) as client:
        new = pill_get(client, "new")
        cont = pill_get(client, "continue")
        unw = pill_get(client, "unwatched")
    assert slide_titles(new.text) == ["Billions", "Fresh Film"]                  # newest first, Billions once
    assert slide_titles(cont.text) == ["Quiet Show"]                             # one slide per show
    assert slide_titles(unw.text) == ["New Show", "Unseen Film"]                 # not started / not played, newest first
    assert "Seen Film" not in unw.text and "Started Show" not in unw.text
    for r, k in ((new, "new"), (cont, "continue"), (unw, "unwatched")):
        assert re.search(rf'class="chip on"[^>]*data-pill="{k}"', r.text.replace("\n", " ")), k
        assert f"media_homepill={k}" in r.headers.get("set-cookie", "")        # the pick is remembered


def test_pills_swap_through_htmx_and_keep_a_plain_link(env):
    main = env(jellyfin=HOME_JELLY, arr=ARR_HOME)
    with TestClient(main.app) as client:
        html = main_html(client.get("/a/alpha").text)
    for k in ("new", "continue", "unwatched"):
        assert f'href="/a/alpha?s={k}"' in html and f'hx-get="/a/alpha/carousel?s={k}"' in html
        assert f'hx-push-url="/a/alpha?s={k}"' in html
    assert 'hx-target="#home-car"' in html and 'hx-swap="outerHTML"' in html
    assert 'data-homecar' in html and 'tabindex="0"' in html                      # keyboard: the track takes focus


def test_load_pill_is_continue_then_query_then_cookie(env):
    main = env(jellyfin=HOME_JELLY, arr=ARR_HOME)
    with TestClient(main.app) as client:
        assert slide_titles(main_html(client.get("/a/alpha").text)) == ["Quiet Show"]     # something to continue
        assert slide_titles(main_html(client.get("/a/alpha?s=unwatched").text))[0] == "New Show"
        assert slide_titles(main_html(client.get("/a/alpha").text))[0] == "New Show"       # the cookie
        assert client.get("/a/alpha/carousel?s=nope").status_code == 404


def test_new_falls_back_when_nothing_to_continue(env):
    main = env(jellyfin={**HOME_JELLY, "up_next": []}, arr=ARR_HOME)
    with TestClient(main.app) as client:
        assert slide_titles(main_html(client.get("/a/alpha").text)) == ["Billions", "Fresh Film"]


def test_recently_added_has_one_tile_per_show(env):
    main = env(jellyfin=HOME_JELLY, arr=ARR_HOME)
    with TestClient(main.app) as client:
        html = main_html(client.get("/a/alpha").text)
    added = html.split('class="seclabel">Recently added', 1)[1].split("</section>", 1)[0]
    titles = re.findall(r'class="row-title">([^<]+)<', added)
    assert titles.count("Billions") == 1 and "Billions · 3 episodes" not in titles and "Fresh Film" in titles


def test_because_most_played_and_follow_left_home(env):
    from tests.hub.test_media_shelves import shelves_for
    main = env(jellyfin=HOME_JELLY, arr=ARR_HOME)
    with TestClient(main.app) as client:
        html = main_html(client.get("/a/alpha").text)
        area = next(a for a in main.shell.registry.areas if a.id == "alpha")
        snaps = main.get_snapshots()
        tiles = [{"tile": t, "st": main.tile_state(t, snaps)} for t in area.tiles]
        sh = main.build_shelves(area, tiles, snaps, "you", home_b=True)
    assert "Because you rated" not in html and "Most played" not in html and "New from people you follow" not in html
    assert ids(sh) == ["continue", "added", "unwatched", "top"]
    assert not {"because", "mostplayed", "following"} & set(ids(sh))
    assert [i["title"] for i in sh["shelves"][-1]["items"]][:2] == ["Seen Film", "Unseen Film"]   # Top rated on Joey
    assert "because" not in ids(shelves_for(main))   # the old builder path is unchanged (no cache: no shelf)
