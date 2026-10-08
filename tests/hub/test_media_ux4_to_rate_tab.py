"""media-ux4 item 7 (2026-10-08): "To rate" is a TAB next to Tonight in the Movies and TV Shows tab rows
(My films · Watchlist · Tonight · To rate), at /media/movies/to-rate and /media/tv/to-rate, with an amber count when
something waits; the To rate section left the top of the list pages; a plain-form rating returns to the tab."""
import re

import pytest

from hub import media_db, media_nav, media_write
from tests.hub.test_media_rate import HX, TV, env, jelly_data, main_of  # noqa: F401  (env fixture)


def subtabs(html):
    """[(label, href, current, count)] of the second (sub-section) tab row."""
    nav = html.split('<nav class="sectabs sub"', 1)[1].split("</nav>", 1)[0]
    out = []
    for href, cur, inner in re.findall(r'<a href="([^"]+)"( aria-current="page")?>(.*?)</a>', nav, re.S):
        count = re.search(r'<span class="waitcount">(\d+)<span class="vh"> ([a-z ]+)</span>', inner)
        out.append((inner.split("<", 1)[0].strip(), href, bool(cur), (int(count.group(1)), count.group(2)) if count else None))
    return out


def test_sections_list_to_rate_after_tonight():
    tabs = {s["id"]: s["tabs"] for s in media_nav.SECTIONS}
    # Awards (2026-10-08) follows To rate: the pair is read at its place, not at the end of the row
    assert tabs["movies"][2:4] == [("Tonight", "/media/movies/tonight"), ("To rate", "/media/movies/to-rate")]
    assert tabs["tv"][2:4] == [("Tonight", "/media/tv/tonight"), ("To rate", "/media/tv/to-rate")]


def test_tab_row_carries_the_to_rate_count_per_kind(env):
    build, _ = env
    with build() as client:
        films = subtabs(client.get("/media/movies").text)
        tv = subtabs(client.get("/media/tv").text)
    assert [t[0] for t in films] == ["My films", "Watchlist", "Tonight", "To rate", "Awards"]   # + Awards (2026-10-08)
    assert films[3] == ("To rate", "/media/movies/to-rate", False, (2, "to rate"))   # Heat + Already Rated
    assert films[0][2] is True                                                       # My films is current
    assert tv[3] == ("To rate", "/media/tv/to-rate", False, (1, "to rate"))           # Quiet Show (show level)


def test_tab_page_is_current_and_lists_its_kind(env):
    build, _ = env
    with build() as client:
        html = client.get("/media/movies/to-rate").text
    tabs = subtabs(html)
    assert [t[0] for t in tabs if t[2]] == ["To rate"]
    body = main_of(html)
    assert '<div class="listbox libposters">' in body or '<div class="listbox">' in body
    assert body.count('class="ratepick"') == 2 and "Heat" in body and "Quiet Show" not in body
    assert "2 films watched in the last 30 days, not rated yet" in body


def test_tv_tab_count_follows_the_owner_level(env):
    build, _ = env
    media_db.set_setting("you", "rating_level", "episode")
    with build(jelly_data(TV)) as client:
        tv = subtabs(client.get("/media/tv/to-rate").text)
        body = main_of(client.get("/media/tv/to-rate").text)
    assert tv[3][3] == (3, "to rate") and tv[3][2] is True   # [3]: To rate sits before Awards (2026-10-08)
    assert body.count('name="level" value="episode"') == 3 and "3 titles watched" in body


def test_tab_shows_without_a_count_when_nothing_waits(env):
    build, _ = env
    with build(jelly_data([])) as client:
        films = client.get("/media/movies/to-rate").text
        tv = client.get("/media/tv/to-rate").text
    for html in (films, tv):
        assert subtabs(html)[3][0] == "To rate" and subtabs(html)[3][3] is None
        assert '<p class="empty">Nothing to rate.</p>' in main_of(html) and "ratepick" not in main_of(html)


@pytest.mark.parametrize("path", ["/media/movies", "/media/tv"])
def test_list_pages_no_longer_hold_a_to_rate_section(env, path):
    build, _ = env
    with build() as client:
        body = main_of(client.get(path).text)
    assert "ratepick" not in body and ">To rate · " not in body


def test_rate_back_allows_the_tabs_and_keeps_the_list_pages():
    for p in ("/media/movies/to-rate", "/media/tv/to-rate", "/media/movies", "/media/tv", "/media/history"):
        assert media_write.RATE_BACK[p] == p


def test_htmx_rating_on_the_tab_swaps_in_place(env):
    build, _ = env
    with build() as client:
        r = client.post("/media/rate", headers=HX, data={"item_key": "tmdb:1", "kind": "movie", "title": "Heat",
                                                         "score": "8", "back": "/media/movies/to-rate"})
        assert r.status_code == 200 and "Rated 8 out of 10" in r.text and "<html" not in r.text
        films = subtabs(client.get("/media/movies").text)
    assert films[3][3] == (1, "to rate")                                              # one fewer waiting
