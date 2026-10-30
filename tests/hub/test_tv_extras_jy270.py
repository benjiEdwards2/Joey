"""JY-270 P5/P6 (B. 2026-10-29, the recommended answers: TV stays public-only, chips only): the TV title pages' facts -
scores as name + number pills, where to watch in words, crew as person links, the film series as a poster shelf - drawn
BELOW the episodes / cast rows, and the episode ratings in words on the season chips and episode tiles. TV only."""
import re

import pytest

from tests.hub.film_page import whole
from tests.hub.test_tv_p3_jy259 import after_header, eps, tv_whole
from tests.hub.test_tv_p3_jy259 import film_friend as _ff  # noqa: F401 - the film fixture, enriched below
from tests.hub.test_tv_series_episodes import E1, E2, E3, S1, SHOW, tvc  # noqa: F401 - the show fixture


@pytest.fixture()
def rich(_ff):
    t = _ff.seerr.titles[("movie", 603)]
    t["voteAverage"] = 7.4
    t["runtime"] = 112
    t["credits"]["crew"] = [{"id": 21, "name": "Dee Director", "job": "Director"},
                            {"id": None, "name": "Wy Writer", "job": "Screenplay"}]
    t["watchProviders"] = [{"iso_3166_1": "AU", "flatrate": [{"name": "Netflix"}], "rent": [{"name": "Apple TV"}]}]
    t["collection"] = {"id": 9, "name": "Harbour Collection"}
    col = {"id": 9, "name": "Harbour Collection", "parts": [
        {"id": 603, "title": t.get("title", "This"), "releaseDate": "2019-05-05", "posterPath": "/a.jpg", "mediaType": "movie"},
        {"id": 604, "title": "Harbour Lights II", "releaseDate": "2022-05-05", "posterPath": "/b.jpg", "mediaType": "movie"}]}
    real = _ff.seerr.get

    def get(url, **kw):   # the fake answers titles only; the series read is this test's
        if "/api/v1/collection/9" in str(url):
            from tests.hub.fake_seerr import Resp
            return Resp(col)
        return real(url, **kw)
    _ff.seerr.get = get
    return _ff


def test_film_facts_sit_below_the_cast_on_the_tv(rich):
    html = tv_whole(rich, "/media/title/movie/603")
    body = after_header(html)
    cast = body.index("tv-cast")
    for cls in ("tv-facts", "tv-providers", "tv-crew", "tv-collection"):
        assert f"tv-extras {cls}" in body, cls
        assert body.index(cls) > cast, f"{cls} must sit below the cast row"
    facts = re.search(r'class="sec tv-extras tv-facts".*?</section>', body, flags=re.S).group(0)
    assert 'sp-name">TMDB' in facts and "sp-val" in facts               # the source's word and its number
    assert "Runtime" in facts
    prov = re.search(r'tv-providers.*?</section>', body, flags=re.S).group(0)
    assert "Netflix" in prov and "Apple TV" in prov and "<a " not in prov   # words, no off-site links
    crew = re.search(r'tv-crew.*?</section>', body, flags=re.S).group(0)
    assert 'href="/media/person/21"' in crew and "Dee Director" in crew and "Wy Writer" in crew
    col = re.search(r'tv-collection.*?</section>', body, flags=re.S).group(0)
    assert "Part of Harbour Collection" in col and col.count("tvt-poster") == 2 and "This film" in col and "on Joey" in col
    for name in ("scores", "crew", "providers", "collection"):   # each placeholder id at most once
        assert html.count(f'id="fp-{name}"') <= 1


def test_web_film_page_has_no_tv_extras(rich):
    html = whole(rich, "/media/title/movie/603")
    assert "tv-extras" not in html and "tv-chipavg" not in html


def test_show_ratings_on_chips_and_tiles(tvc, monkeypatch):
    from hub import media_episode_ratings as mer
    real = mer.build_ratings

    def fake(*a, **k):
        r, later = real(*a, **k)
        r = r or {"source": "TMDB", "current": 1, "seasons": []}
        r["seasons"] = [{"n": 1, "avg": 8.0, "eps": [{"number": 1, "rating": 8.4}, {"number": 2, "rating": 7.1}]}]
        return r, later
    monkeypatch.setattr(mer, "build_ratings", fake)
    html = tv_whole(tvc, f"/media/item/{SHOW}")
    row = eps(html)
    assert "8.0 avg" in row
    assert "8.4 above avg" in row and "7.1 below avg" in row
