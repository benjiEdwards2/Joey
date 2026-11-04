"""JY-307 phase 4 (option B, 2026-11-05; spec docs/specs/JY-307-tv-ui-phase4.md): backdrop-led TV title pages (film,
show, season, episode, person: no poster card, the backdrop in the top 65 %, else the picture cropped to the band) and
the Discover search line (field + type chips, no Search button, no hint, 8 across, the state word in a foot band).
The film / show / season / episode markup is pinned in test_tv_p3_jy259.py and test_tv_series_episodes.py."""
import re

import pytest

from hub import media_person, shell
from tests.hub.test_tv_shelves_tmdb import ON, friend, page, person, row  # noqa: F401 - the TV friend fixtures
from tests.hub.tv_css import root_px


def _person(friend, monkeypatch, **kw):
    on = row(ON, "Kept Lantern", "/media/item/" + "ab" * 16, True)
    monkeypatch.setattr(media_person, "build_person", lambda tmdb_id, snaps=None: {**person([on], []), **kw})
    b = page(friend, "/media/person/55", tv=True)
    start = b.index('<header class="personhead')
    return b[start:b.index("</header>", start)]


@pytest.mark.parametrize("kw, want", [
    ({"backdrop": "tmdb:/bd.jpg", "ref": "tmdb:/face.jpg"}, "<div class=\"hero-detail-bd\" style=\"--bd: url('/img/tmdb:/bd.jpg?h=1280')\""),
    ({"backdrop": None, "ref": "tmdb:/face.jpg"}, "<div class=\"hero-detail-bd tv-bdcrop\" style=\"--bd: url('/img/tmdb:/face.jpg?h=600')\""),
    ({"backdrop": None, "ref": None}, '<span class="personpic initials"'),
])
def test_tv_person_hero_is_the_backdrop_else_the_photo_cropped_else_initials(friend, monkeypatch, kw, want):
    h = _person(friend, monkeypatch, **kw)
    assert 'class="personhead hero-detail tv-bdpage"' in h and want in h
    assert '<img class="personpic' not in h and "personportrait" not in h          # no round photo, no portrait card
    assert '<h1 class="hero-detail-title">Sample Actor</h1>' in h and "Acting" in h


def test_the_web_person_page_is_unchanged(friend, monkeypatch):
    on = row(ON, "Kept Lantern", "/media/item/" + "ab" * 16, True)
    monkeypatch.setattr(media_person, "build_person",
                        lambda tmdb_id, snaps=None: {**person([on], []), "backdrop": "tmdb:/bd.jpg", "ref": "tmdb:/face.jpg"})
    b = page(friend, "/media/person/55", tv=False)
    assert 'class="personhead hero-detail person-hero"' in b and "tv-bdpage" not in b and "personportrait" in b


def test_the_p4_css_numbers():
    css = (shell.TEMPLATES_DIR.parent / "static" / "tv.css").read_text(encoding="utf-8")
    p4 = css[css.index("/* JY-307 P4 (2026-11-05"):css.index("/* JY-267 (2026-10-29)")]
    band = re.search(r"html\.tv \.tv-bdpage > \.hero-detail-bd \{[^}]*height: ([\d.]+)rem", p4).group(1)
    assert float(band) * root_px(css, 1920, 1080) == 702 == round(.65 * 1080)            # the top 65 % at 1080
    title = re.search(r"html\.tv \.tv-bdpage \.hero-detail-title \{ font-size: ([\d.]+)rem", p4).group(1)
    assert float(title) * root_px(css, 1920, 1080) == 84 and float(title) * 32 == 112     # option B's 112 px, pre-P2b rem
    field = re.search(r'\.discover-search\[action="/media/discover"\] \.input \{ height: ([\d.]+)rem', p4).group(1)
    assert float(field) * 32 == 80 and float(field) * root_px(css, 1920, 1080) == 60      # the 80 px pill, pre-P2b rem
    assert re.search(r'html\.tv main form\.toolbar\.discover-search\[action="/media/discover"\] \{ display: flex', p4)
    assert re.search(r"\.tv-typechips \{ flex: none; flex-wrap: nowrap", p4)              # the chips stay on the line
    assert "html.tv .poster-grid.reqgrid { grid-template-columns: repeat(8, minmax(0, 1fr))" in css   # 8 across
    assert re.search(r"html\.tv \.poster-grid\.reqgrid \.reqchip \{ display: block;[^}]*font-size: 1\.125rem", p4)  # foot band, text floor
