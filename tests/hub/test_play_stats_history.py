"""JY-121 (2026-10-26, built as option A for B.'s pick): Play stats joins Activity > History.

One History tab, two views: a Diary · Play stats switch (`<nav class="seg histseg" aria-label="History view">`) on both pages.
Play stats keeps its URL (private only) but now lights History and its heading reads "History". The friends' front and
the TV's slim diary never show the switch."""
import re

from tests.hub.conftest import main_raw as main_of  # noqa: F401
from tests.hub.fake_jellyfin import FRIEND_ID
from tests.hub.guest_pages import TV_UA, guest_client, sign_in
from tests.hub.helpers import jelly
from tests.hub.test_media_rate import env  # noqa: F401

SWITCH = '<nav class="seg histseg" aria-label="History view">'


def switch_of(html: str) -> str:
    return html.split(SWITCH, 1)[1].split("</nav>", 1)[0]


def sub_tabs_on(html: str) -> list[str]:
    nav = re.search(r'<nav class="sectabs sub".*?</nav>', html, re.S).group(0)
    return re.findall(r'aria-current="page">([^<]*?)(?: <span|</a>)', nav)


def test_play_stats_lights_history_and_is_headed_history(env):
    build, _ = env
    with build() as client:
        html = client.get("/media/server/history").text
    assert sub_tabs_on(html) == ["History"]
    assert re.search(r"<h1[^>]*>\s*History\s*</h1>", html), "the page names itself by the lit tab"


def test_both_history_views_carry_the_switch_with_the_current_one_marked(env):
    build, _ = env
    with build() as client:
        diary = client.get("/media/diary").text
        plays = client.get("/media/server/history?w=7").text
    for html, here in ((diary, "Diary"), (plays, "Play stats")):
        assert html.count(SWITCH) == 1
        sw = switch_of(html)
        assert '<a href="/media/diary"' in sw and '<a href="/media/server/history"' in sw
        assert re.findall(r'aria-current="page">([^<]+)</a>', sw) == [here]
    assert sub_tabs_on(diary) == ["History"]


def test_the_diary_drops_the_old_play_stats_text_link(env):
    build, _ = env
    with build() as client:
        body = main_of(client.get("/media/diary").text)
    assert '<p class="metaline"><a href="/media/server/history">Play stats</a></p>' not in body
    assert body.count('href="/media/server/history"') == 1   # only the switch links it


def test_other_activity_tabs_light_as_before(env):
    build, _ = env
    with build() as client:
        for route, tab in (("/media/playing", "Live"), ("/media/history", "To rate"), ("/media/library", "Library")):
            assert sub_tabs_on(client.get(route).text) == [tab], route


def test_the_friends_diary_has_no_switch_and_no_play_stats(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": jelly()})
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        html = c.get("/media/diary").text
        plays = c.get("/media/server/history", follow_redirects=False)
    assert SWITCH not in html and "/media/server/history" not in html
    assert plays.status_code == 404


def test_the_tv_diary_has_no_switch(monkeypatch, tmp_path):
    client, fake = guest_client(monkeypatch, tmp_path, {"jellyfin": jelly()})
    with client as c:
        sign_in(c, fake, FRIEND_ID)
        html = c.get("/media/diary", headers={"User-Agent": TV_UA}).text
    assert '<html lang="en" class="tv"' in html
    assert SWITCH not in html
