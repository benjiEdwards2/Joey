"""JY-269 P1 (B. 2026-10-29, pick A): the web and phone title pages take the TV hero - backdrop + scrim (a poster wash
when there is no backdrop), poster, facts, a short synopsis and ONE button row ending in a "…" menu (Request beside
Play, Remove, Follow, the resume pair, Search now). Web only: the TV pages draw what they drew before.
docs/specs/JY-269-web-title-layout.md (tests 1-3)."""
import re
from pathlib import Path

import pytest

from tests.hub.conftest import main_of
from tests.hub.film_page import whole
from tests.hub.guest_pages import TV_UA, movie
from tests.hub.helpers import ITEMS, env  # noqa: F401  (env: the film-page fixture)
from tests.hub.test_tv_series_episodes import E1, S1, SHOW, tvc  # noqa: F401 - the show fixture

CSS = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
ROW = '<div class="hero-detail-btns">'
MENU = '<details class="fold heromore">'


def hero(b):
    return b.split('<header class="pagehead hero-detail">', 1)[1].split("</header>", 1)[0]


def row_of(h):
    return h.split(ROW, 1)[1].split("\n        </div>", 1)[0]


# ---- 1: every kind of title page is the backdrop hero on the web ----

@pytest.mark.parametrize("path", ["/media/item/mov1", "/media/item/ser1", "/media/item/sea1", "/media/item/ep3",
                                  "/media/title/movie/603", "/media/title/movie/701"])
def test_web_title_page_is_a_backdrop_hero_per_kind(env, path):
    client, _ = env()
    with client:
        h = hero(main_of(whole(client, path)))
    assert '<div class="hero-detail-in tl-hero">' in h
    assert 'class="hero-detail-bd' in h                                   # the backdrop, or the poster wash
    assert h.index("hero-detail-poster") < h.index('<h1 class="hero-detail-title">') < h.index(ROW)


def test_a_title_with_no_backdrop_draws_a_poster_wash_not_a_gap(env, monkeypatch):
    monkeypatch.setitem(ITEMS["mov1"], "BackdropImageTags", [])
    client, _ = env()
    with client:
        h = hero(main_of(whole(client, "/media/item/mov1")))
    assert re.search(r'<div class="hero-detail-bd tl-wash" style="--bd: url\(\'/img/[^\']+\?h=240\'\)" aria-hidden="true">', h)
    assert re.search(r"\.hero-detail-bd\.tl-wash \{[^}]*filter: blur", CSS)


def test_web_hero_has_a_short_synopsis_with_more(env):
    client, _ = env()
    with client:
        h = hero(main_of(whole(client, "/media/item/ep3")))
    syn = h.split('<div class="tl-syn">', 1)[1]
    assert "Coins go missing." in syn.split("</div>", 1)[0] and 'class="tl-synmore"' in syn
    assert h.index('class="facts-line"') < h.index('<div class="tl-syn">') < h.index(ROW)
    assert "Your rating</h2>" not in h
    assert re.search(r"\.tl-syntext \{[^}]*-webkit-line-clamp: 2", CSS)
    assert re.search(r"@media \(max-width: 639px\) \{.*?\.tl-syntext \{ -webkit-line-clamp: 2", CSS, re.S)


# ---- 2: one row that never wraps, every action still reachable ----

def test_web_button_row_never_wraps_and_keeps_every_action(env, monkeypatch):
    monkeypatch.setenv("REMOVE_API", "on")
    client, _ = env()
    with client:
        film = hero(main_of(whole(client, "/media/item/mov1")))
        show = hero(main_of(whole(client, "/media/item/ser1")))
        req = hero(main_of(whole(client, "/media/title/movie/701")))
    for h in (film, show):
        row = row_of(h)
        assert MENU in row                                                   # the "…" menu sits in the row
        assert '<summary aria-label="More actions" title="More actions">…</summary>' in row
        assert '<details class="tl-pop tl-rate"' in row      # Rate opens the picker
        assert 'action="/media/rate"' in row.split('class="tl-pop tl-rate"', 1)[1]
    assert 'action="/media/follow/show/' in row_of(show).split(MENU, 1)[1]   # Follow: in the menu, same route
    assert 'class="followform"' not in show.split(ROW, 1)[0]
    assert 'id="request-block"' in req                                     # Request: unchanged block and route
    # the CSS: no wrap from 640 px, Play gives way with an ellipsis
    assert re.search(r"\.tl-hero \.hero-detail-btns \{[^}]*flex-wrap: nowrap", CSS)
    first = re.search(r"\.tl-hero \.hero-detail-btns > a\.btn-white \{([^}]*)\}", CSS).group(1)
    for rule in ("min-width: 0", "overflow: hidden", "text-overflow: ellipsis", "white-space: nowrap"):
        assert rule in first, rule


# ---- 3: the TV draws what it drew before ----

F1, F2 = "f1f1f1f1" * 4, "f2f2f2f2" * 4


def test_tv_title_pages_are_unchanged_by_the_web_layout(tvc):
    tvc.fake.items[F1] = {**movie(F1, "Film One", "603"), "Overview": "A film.", "BackdropImageTags": ["a"]}
    tvc.fake.items[F2] = {**movie(F2, "Film Two"), "Overview": "No backdrop."}
    for p in (SHOW, S1, E1, F1, F2):
        tv = tvc.get(f"/media/item/{p}", headers={"User-Agent": TV_UA}).text
        assert "tl-hero" not in tv and "tl-syn" not in tv and "tl-pop" not in tv and "tl-wash" not in tv, p
        assert '<div class="hero-detail-in">' in tv, p
        if MENU in tv:
            assert "<summary>More</summary>" in tv and "More actions" not in tv
    assert "html.tv" not in CSS.split("JY-269 P1", 1)[1]                    # nothing in the new block styles the TV
    assert all(".tl-" in r or "tl-hero" in r or "not(.tv)" in r
               for r in re.findall(r"^[^\s/@}][^{]*\{", CSS.split("JY-269 P1", 1)[1], re.M))
