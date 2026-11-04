"""JY-315 (B.'s pick A + the episode carousel, 2026-11-04): the web and phone episode page - the 16:9 still hero with ONE
button row (Play, Next episode, Rate, ...), the season as a .carousel row under the hero ("This one" ringed, scrolled to,
season chips), guest stars as 2:3 cast tiles capped at 12 with an "All N" fold. One test (or group) per acceptance
criterion; the layout (1440 / 1024 / 390) is CSS, pinned as rules. The TV episode page draws none of it."""
import copy
import re
from pathlib import Path

import pytest

from tests.hub import helpers as tmi
from tests.hub.helpers import env  # noqa: F401  (fixture)
from tests.hub.test_episode_flow_nav import show, film_of  # noqa: F401  (fixtures)
from tests.hub.test_episode_flow_templates import ENV, episode, head, macro, media_nav_stub, page  # noqa: F401

CSS = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
JY315 = CSS.split("/* JY-315 (B.'s pick A", 1)[1]


def cards(html):
    return re.findall(r'<a class="epcard([^"]*)" href="([^"]+)"( aria-current="page")?>.*?<span class="epcard-cap">([^<]*)</span>',
                      html, re.S)


# ---- AC1: the hero (still, crumbs, eyebrow, title, one button row, synopsis under it) ----

def test_hero_leads_with_the_still_and_one_button_row():
    h = head(episode(nav={**episode()["nav"], "next_ep": {"number": 3, "name": "Episode 3", "href": "/media/item/s2e3",
                                                          "season": 2, "code": "S2 E3"}}, rating={"key": "x"}))
    assert '<div class="hero-detail-in tl-hero tl-ephero">' in h
    assert '<img class="tl-epstill" src="/img/none?h=600' in h and "hero-detail-poster" not in h
    order = [h.index(x) for x in ('class="crumbs"', 'class="epeyebrow"', '<h1 class="hero-detail-title">Episode 2</h1>',
                                  'class="eprating"', "Aired 23 Nov 2025", 'class="hero-detail-btns"', 'class="tl-syn"')]
    assert order == sorted(order)
    btns = h.split('class="hero-detail-btns"', 1)[1].split("</div>\n", 1)[0]
    assert "Play ▶" in btns and '<a class="btn btn-glass tl-nextep" href="/media/item/s2e3"' in btns
    assert 'class="facts-line"' not in h          # no "TV · genres" line on an episode


def test_hero_layout_css_still_beside_on_desktop_above_from_1024_down():
    assert "html:not(.tv) .tl-epstill { display: block; flex: none; width: min(46%, 640px);" in JY315
    assert "@media (max-width: 1024px) {\n  html:not(.tv) .tl-ephero { flex-direction: column; align-items: stretch; }" in JY315
    assert "html:not(.tv) .tl-ephero .tl-epstill { width: 100%; max-width: 720px; }" in JY315
    # buttons stay on one row from 640 (the JY-269 rule), wrap on a phone
    assert "html:not(.tv) .tl-hero .hero-detail-btns { position: relative; flex-wrap: nowrap;" in CSS


# ---- AC1-3: the carousel (this one in view, chips, tiles open their episode) ----

def test_carousel_marks_this_episode_and_links_every_tile():
    c = page(episode())
    sec = c.split('<section class="sec epcar-sec" aria-label="Season 2 episodes">', 1)[1].split("</section>", 1)[0]
    got = cards(sec)
    assert [g[3] for g in got] == ["E1 · Episode 1", "E2 · Episode 2", "E3 · Episode 3", "E4 · The Finale"]
    assert [g[1] for g in got] == [f"/media/item/s2e{i}" for i in range(1, 5)]
    this = [g for g in got if g[2]]
    assert len(this) == 1 and this[0][1] == "/media/item/s2e2" and "is-this" in this[0][0]
    assert sec.count('<span class="epcard-chip">This one</span>') == 1
    assert "is-seen" in got[0][0] and sec.count('<span class="vh">Watched</span>') == 1
    assert '<div class="carousel epcar">' in sec                     # the JY-304 cue picks up every .carousel
    # season chips at the row's head: S2 on, S1 / S3 open their season pages
    assert '<a href="/media/item/season1">S1</a><a href="/media/item/season2" class="on" aria-current="page">S2</a>' in sec
    assert "sec tl-eps" not in c                                       # the show / season Episodes row is not drawn too


def test_carousel_script_scrolls_to_this_one_and_walks_with_arrow_keys():
    c = page(episode())
    js = c.split('<section class="sec epcar-sec"', 1)[1].split("</script>", 1)[0]
    assert 'c.querySelector(".is-this")' in js and "c.scrollLeft +=" in js and "setTimeout(centre, 0)" in js
    assert '"ArrowLeft"' in js and '"ArrowRight"' in js and "to.focus()" in js


def test_carousel_css_peeks_half_a_tile_at_every_width():
    for n, bp in ((1.5, None), (2.5, 640), (3.5, 1024), (4.5, 1440), (5.5, 1920)):
        k = int(n - .5)
        gap = "12px" if k == 1 else f"{k} * 12px"
        rule = f"html:not(.tv) .carousel.epcar:not(.prov-row) > * {{ flex-basis: calc((100% - {gap}) / {n}); width: calc((100% - {gap}) / {n}); }}"
        assert rule in JY315, n
        if bp:
            assert f"@media (min-width: {bp}px) {{ {rule}" in JY315, n
    assert "html:not(.tv) .epcard.is-this .epcard-still { outline: 2px solid var(--gold);" in JY315
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", JY315)        # tokens only


def test_no_carousel_on_the_tv(monkeypatch):
    monkeypatch.setitem(ENV.globals, "tv_mode", lambda request: True)
    p = page(episode())
    assert "epcar" not in p and "tl-epstill" not in p and "tl-nextep" not in p and "Guest stars" not in p


# ---- AC4: Next episode = the next by number across the season boundary, none on the last aired ----

def test_next_ep_within_the_season(show, film_of):
    f, _ = film_of("/media/item/ep3")
    assert f["nav"]["next_ep"] == {"number": 4, "name": "Four", "href": "/media/item/ep4", "season": 4, "code": "S4 E4"}


def test_next_ep_crosses_the_season_boundary(show, film_of, monkeypatch):
    eps = copy.deepcopy(tmi.EPISODES)
    eps[5]["PremiereDate"] = tmi.YESTERDAY                            # S4 E6 aired
    monkeypatch.setattr(tmi, "EPISODES", eps)
    f, _ = film_of("/media/item/ep6")
    assert f["nav"]["next"] is None
    assert f["nav"]["next_ep"] == {"number": 1, "name": "Five One", "href": "/media/item/s5e1", "season": 5, "code": "S5 E1"}


def test_no_next_ep_on_the_last_aired_episode(show, film_of, monkeypatch):
    eps = copy.deepcopy(tmi.EPISODES)
    eps[5]["PremiereDate"] = tmi.YESTERDAY
    for e in eps[6:]:
        e["PremiereDate"] = tmi.TOMORROW                              # Season 5 not aired yet
    monkeypatch.setattr(tmi, "EPISODES", eps)
    f, _ = film_of("/media/item/ep6")
    assert f["nav"]["next_ep"] is None
    assert "tl-nextep" not in head(episode(nav={**episode()["nav"], "next_ep": None}))


def test_season_page_has_no_next_ep(show, film_of):
    f, _ = film_of("/media/item/sea1")
    assert f["nav"]["next_ep"] is None


# ---- AC5: guest stars as 2:3 tiles, 12 + "All N", none for no guests ----

def guests(n):
    return [{"name": f"Guest Person{i}", "role": f"Role {i}", "poster": "jf:g" if i % 2 else None, "href": None,
             "eps_this_season": 1} for i in range(n)]


def test_guest_stars_capped_at_12_with_an_all_fold():
    h = macro("guests", guests(14), True)
    assert '<section class="sec castsec casttiles" id="guests">' in h and "Guest stars" in h
    first, fold = h.split('<details class="fold guestfold">', 1)
    assert first.count('class="castcard"') == 12 and fold.count('class="castcard"') == 2
    assert "<summary>All 14</summary>" in fold
    assert '<img class="castpic" src="/img/jf:g?h=270"' in h and '<span class="castpic initials" aria-hidden="true">GP</span>' in h


def test_twelve_guests_or_fewer_have_no_fold_and_none_draw_nothing():
    assert "guestfold" not in macro("guests", guests(12), True)
    assert macro("guests", [], True).strip() == ""
    assert "Guest stars" not in page(episode(guests=[]))
    assert "Guest stars" in page(episode())


def test_tv_guests_markup_unchanged():
    h = macro("guests", guests(2))
    assert '<div class="guests">' in h and "casttiles" not in h and ">Guests<" in h
