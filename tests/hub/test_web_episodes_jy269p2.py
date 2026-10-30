"""JY-269 P2 (B. 2026-10-29, pick A): on the web and phone a show / season / episode page leads with the Episodes row -
"Episodes", the season chips (one sideways line, the shown season lit), "n of m watched", then 16:9 episode tiles in a
sideways row (wheel, drag and arrows on desktop; a swipe on touch). The viewer's own watch words; the TV unchanged.
docs/specs/JY-269-web-title-layout.md (tests 4-6)."""
import re
from pathlib import Path

from tests.hub.fake_jellyfin import OTHER_ID
from tests.hub.guest_pages import sign_in
from tests.hub.test_tv_series_episodes import E1, S1, S2, SHOW, TV, text, tvc  # noqa: F401 - the show fixture

CSS = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")


def row(html):
    m = re.search(r'<section class="sec tl-eps" aria-label="Episodes">(.*?)</section>', html, flags=re.S)
    assert m, "no web Episodes row"
    return m.group(1)


def tiles(r):
    return re.findall(r'<div class="tl-ep ep-[^"]+"[^>]*>.*?\n    </div>', r, flags=re.S)


def test_show_page_draws_episodes_then_season_chips(tvc):
    html = tvc.get(f"/media/item/{SHOW}").text
    r = row(html)
    head, body = r.split('<div class="tl-row">', 1)
    assert '<h2 class="seclabel">Episodes</h2>' in head
    chips = re.findall(r'<a class="chip( on)?" href="([^"]+)"[^>]*>([^<]+)</a>', head)
    assert chips[0] == (" on", f"/media/item/{S1}", "Season 1") and len(chips) == 2
    assert "0 of 3 watched" in head
    t = tiles(body)
    assert len(t) == 3 and f'href="/media/item/{E1}"' in t[0] and f"/img/jf:{E1}?h=240" in t[0]
    assert 'class="tl-arrow tl-prev"' in body and 'class="tl-arrow tl-next"' in body
    # straight under the hero: before the part-of banner, the numbers and the old Seasons list
    assert html.index('class="sec tl-eps"') < html.index('class="sec seasons"')
    assert html.index("</header>") < html.index('class="sec tl-eps"')
    assert re.search(r"\.tl-chips \{[^}]*flex-wrap: nowrap;[^}]*overflow-x: auto", CSS)
    assert re.search(r"\.tl-track \{[^}]*overflow-x: auto", CSS)


def test_a_season_page_lights_its_own_chip(tvc):
    html = tvc.get(f"/media/item/{S1}").text
    assert re.search(r'<a class="chip on" href="/media/item/' + S1 + '" aria-current="true">Season 1</a>', row(html))


def test_each_friend_sees_only_their_own_episodes_and_chips_on_the_web(tvc):
    r = row(tvc.get(f"/media/item/{SHOW}").text)
    assert "0 of 3 watched" in r and ">Watched<" not in r                  # the household watched E1 + E2
    assert "In progress" in text(tiles(r)[0])                              # the friend is 20 min into E1
    sign_in(tvc, tvc.fake, OTHER_ID)
    r = row(tvc.get(f"/media/item/{SHOW}").text)
    assert "1 of 3 watched" in r and ">Watched<" in tiles(r)[0] and ">Watched<" not in tiles(r)[1]


def test_episode_rows_keep_state_words_and_play_handoff(tvc):
    t = tiles(row(tvc.get(f"/media/item/{SHOW}").text))
    for x in t:
        assert re.search(r'<span class="epstate st-[a-z]+">(Watched|In progress[^<]*|Not aired|Not watched)</span>', x)
    play = re.findall(r'<a class="btn btn-secondary btn-sm tl-epplay" href="([^"]+)"', t[0])
    assert play, "the JY-054 Play / Resume hand-off under an aired tile"


def test_tv_bytes_never_carry_the_web_row(tvc):
    html = tvc.get(f"/media/item/{SHOW}", headers=TV).text
    assert "tl-eps" not in html and "tl-track" not in html
