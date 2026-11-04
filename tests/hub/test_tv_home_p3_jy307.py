"""JY-307 phase 3 (option B, 2026-11-04; spec docs/specs/JY-307-tv-ui-phase3.md): the Home hero's Resume / Play and
More info, every Home row one 16:9 tile (backdrop + JY-267 logo, else backdrop + caption, else the poster cropped,
never blank), Down from the hero buttons to the first tile, and the P3 CSS."""
import re

from hub import media_posters, tv_home
from tests.hub.test_tv_home_jy259 import _item, _kit, _shelf, jelly
from tests.hub.tv_css import root_px

ID1 = "0001" * 8
PLAY = lambda jf: f"https://jf.example/web/#/details?id={jf}"   # noqa: E731


def test_hero_play_resumes_the_continue_item_and_more_info_opens_its_page():
    cont = [{**_item(1), "pct": 40, "episode_key": None}]
    out = tv_home.build([_shelf("continue", cont)], cont, [], [], jelly(), PLAY)
    hero = out["hero"]
    assert hero["play"] == {"href": PLAY(ID1), "label": "Resume", "jf_id": ID1}
    assert hero["info"] == f"/media/item/{ID1}" and hero["data"]["title"] == "T1"


def test_hero_play_is_play_when_not_started_and_absent_without_a_hand_off():
    added = [_item(1)]
    out = tv_home.build([_shelf("added", added)], [], [], added, jelly(), PLAY)
    assert out["hero"]["play"]["label"] == "Play"
    assert tv_home.build([_shelf("added", added)], [], [], added, jelly())["hero"]["play"] is None
    ep = {**_item(1), "pct": 10, "episode_key": "jf:" + "e001" * 8}
    assert tv_home.hero_play(ep, True, PLAY)["jf_id"] == "e001" * 8            # an episode resumes itself


def test_the_hero_buttons_render_with_the_hand_off_and_the_hero_data():
    cont = [{**_item(1), "pct": 40, "episode_key": None}]
    hero = tv_home.build([_shelf("continue", cont)], cont, [], [], jelly(), PLAY)["hero"]
    html = str(_kit().hero(hero))
    acts = re.search(r'<div class="tv-hero-acts"[^>]*>(.*?)</div>', html).group(1)
    assert f'href="{PLAY(ID1)}"' in acts and f'data-jf-id="{ID1}"' in acts and ">Resume</a>" in acts
    assert f'href="/media/item/{ID1}"' in acts and ">More info</a>" in acts and acts.count("data-hero=") == 2


def test_every_home_row_is_one_16x9_tile_row():
    cont = [{**_item(1), "pct": 40, "episode_key": None}]
    shelves = [_shelf("continue", cont), _shelf("added", [_item(2)]), _shelf("top", [_item(1), _item(2)])]
    out = tv_home.build(shelves, cont, [], shelves[1]["items"], jelly(2), PLAY)
    assert all(r["wide"] for r in out["rows"])
    for r in out["rows"]:
        html = str(_kit().row(r))
        assert 'class="carousel tvt-row tvt-row-land"' in html and "tvt-poster" not in html


def test_a_tile_without_a_backdrop_falls_back_to_the_cropped_poster(monkeypatch):
    j = jelly(2)
    j["movies"][1]["backdrop"] = None                                         # Film 02: no backdrop, nothing cached
    out = tv_home.build([_shelf("added", [_item(1), _item(2)])], [], [], [_item(1)], j)
    a, b = out["rows"][0]["items"]
    assert (a["still"], a["still_h"], a["crop"]) == ("jfb:" + ID1, 1280, False)   # the warmed hero size: no new fetch
    assert (b["still"], b["still_h"], b["crop"]) == ("jf:" + "0002" * 8, 600, True)
    html = str(_kit().land(b))
    assert "tvt-crop" in html and f"/img/jf:{'0002' * 8}?h=600" in html and '<span class="row-title">T2</span>' in html


def test_a_tile_with_a_logo_draws_it_over_the_backdrop_in_place_of_the_caption(monkeypatch):
    monkeypatch.setattr(media_posters, "stored_logo", lambda jf: {"src": f"/logo/{jf}.png", "w": 400, "h": 100} if jf == ID1 else None)
    out = tv_home.build([_shelf("added", [_item(1), _item(2)])], [], [], [_item(1)], jelly(2))
    with_logo, plain = (str(_kit().land(i)) for i in out["rows"][0]["items"])
    assert f'<img class="tvt-logo" src="/logo/{ID1}.png" alt="T1"' in with_logo and "row-title" not in with_logo
    assert "tvt-logo" not in plain and '<span class="row-title">T2</span>' in plain


def test_p3_css_tile_width_and_hero_buttons():
    css = open("hub/static/tv.css", encoding="utf-8").read()
    w = float(re.search(r"\.page:has\(> \.tv-hero\) \.carousel\.tvt-row-land > \* \{ flex: 0 0 14\.6667rem; width: ([\d.]+)rem; \}",
                        css.split("/* JY-307 P3 (2026-11-04", 1)[1]).group(1))
    assert round(w * root_px(css, 1920, 1080)) == 352
    assert "html.tv .tv-hero-acts .btn.tv-focus" in css
    assert "html.tv body:has(.tv-bd) .topbar:not(.tv-rail-on) .topbar-in { background: none; }" in css   # no rail edge


def test_down_from_the_hero_buttons_lands_on_the_first_rows_first_tile():
    js = open("hub/static/tv.js", encoding="utf-8").read()
    assert "if (dir === 'ArrowDown' && a.closest('.tv-hero-acts'))" in js
    assert "best = firstIn(row1) || best;" in js
