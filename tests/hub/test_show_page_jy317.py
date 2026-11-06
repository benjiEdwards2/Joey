"""JY-317 (Plan 2 phase 2.5; B. 2026-11-06, Sweep 34: "Remember the rating column sitting on the right hand side as a
smaller side bar. Can you please implement that. Instead of having it as a row of things." and "Please change all
headshots of cast members to 2:3. Stop placing them in circles. For shows and movies."): web show and season pages take
the film's parts - Creator / Director chips under the facts line, the 2:3 cast tiles, a narrower right-hand column with
Scores, Details and the owner's File drawer beside the Episodes row and cast (stacked on a phone). The TV is untouched.
Upstreams are the helpers fakes; no network."""
import re
from pathlib import Path

import pytest

from hub import media_film
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.film_page import whole
from tests.hub.helpers import env, EPISODES, ITEMS, SOURCES  # noqa: F401
from tests.hub.test_tv_p3_jy259 import tv_whole
from tests.hub.test_tv_series_episodes import tvc  # noqa: F401

SEASON = {"Id": "sea1", "Type": "Season", "Name": "Season 4", "SeriesId": "ser1", "SeriesName": "Quiet Show",
          "IndexNumber": 4, "UserData": {}}
CSS = (Path(media_film.__file__).resolve().parent / "static" / "control-surface.css").read_text(encoding="utf-8")


@pytest.fixture()
def season(monkeypatch):
    monkeypatch.setitem(ITEMS, "sea1", dict(SEASON))


def with_cast(monkeypatch):
    monkeypatch.setitem(ITEMS["ser1"], "People", [{"Name": f"Cast {c}", "Type": "Actor", "Role": "Role"} for c in "ABCD"])


def with_files(monkeypatch):
    for e in EPISODES[:3]:
        monkeypatch.setitem(e, "MediaSources", [{**SOURCES[0], "Path": f"/tv/Quiet.Show.S04E0{e['IndexNumber']}.mkv"}])


def hero_and_body(b):
    """(hero, body) of a show / season page. JY-316 r3 replaced JY-317's right-hand column: no columns at all."""
    hero, body = b.split("</header>", 1)
    return hero, body


def strip_of(hero):
    """The hero's compact scores strip (JY-316 r3)."""
    return hero.split('<div class="scorepills hero-scores" aria-label="Scores">', 1)[1].split("\n        </div>", 1)[0]


@pytest.mark.parametrize("path", ["/media/item/ser1", "/media/item/sea1", "/media/title/tv/100"])
def test_round3_scores_in_the_hero_body_spans_details_and_file_under_the_cast(env, season, monkeypatch, path):
    with_files(monkeypatch)
    with_cast(monkeypatch)
    client, _ = env()
    with client:
        b = main_of(whole(client, path))
    hero, body = hero_and_body(b)
    assert "filmcol-side" not in b and "tlcols" not in b and "filmcols" not in b and "<aside" not in body
    assert b.count("hero-scores") == 1 and '<div class="stats numbers">' not in b and ">Scores<" not in b
    assert body.index(">Episodes</h2>") < body.index('class="sec castsec casttiles"') < body.index(">Details</h2>")
    assert body.index(">Details</h2>") < body.index('class="sec filedrawer"') and b.count('class="sec filedrawer"') == 1
    assert b.count('<h2 class="seclabel">Cast</h2>') == 1


@pytest.mark.parametrize("path", ["/media/item/ser1", "/media/item/sea1", "/media/title/tv/100"])
def test_round3_hero_strip_is_at_most_imdb_tmdb_yours_in_that_order(env, season, monkeypatch, path):
    monkeypatch.setattr(media_film, "parse_ratings", lambda *a, **k: {"imdb": "8.1", "rt": "93%"})
    client, _ = env()
    with client:
        b = main_of(whole(client, path))
    strip = strip_of(hero_and_body(b)[0])
    pills = re.findall(r'class="scorepill(?: scorelink)? sp-(\w+)', strip)
    assert 1 <= len(pills) <= 3 and set(pills) <= {"imdb", "tmdb", "you"}
    assert pills == [p for p in ("imdb", "tmdb", "you") if p in pills]          # IMDb, TMDB, Yours - in that order
    assert "sp-rt" not in strip and "sp-mc" not in strip and "sp-lbxd" not in strip and "sitepill" not in strip


def test_round3_rt_moves_to_the_details_links_row(env, monkeypatch):
    monkeypatch.setattr(media_film, "parse_ratings", lambda *a, **k: {"imdb": "8.1", "rt": "93%"})
    client, _ = env()
    with client:
        b = main_of(whole(client, "/media/title/tv/100"))
    hero, body = hero_and_body(b)
    assert "sp-imdb" in strip_of(hero) and "sp-rt" not in hero
    links = body.split("<dt>Links</dt>", 1)[1].split("</dd>", 1)[0]
    assert 'class="scorepill scorelink sp-rt"' in links and "93%" in links and "sp-imdb" not in links


def test_season_page_keeps_rate_in_the_strip_and_the_banner_in_the_body(env, season):
    client, _ = env()
    with client:
        b = main_of(whole(client, "/media/item/sea1"))
    hero, body = hero_and_body(b)
    assert 'class="scorepill sp-you"' in strip_of(hero)              # Rate / Yours is the strip's last pill
    assert 'class="sec partof-sec"' in body and "All seasons</a>" in body


def test_show_hero_takes_the_film_chips_not_circle_cards(env):
    client, _ = env()
    with client:
        b = main_of(whole(client, "/media/title/tv/100"))
    h = b.split("</header>", 1)[0]
    assert '<div class="makerchips"><a class="chip makerchip" href="/media/person/' in h
    assert '<span class="makerchip-role">Creator</span>' in h
    assert "makercard" not in b and "makerpic" not in b and "seasonseg" not in b


def test_owner_file_drawer_not_for_her_view(env, monkeypatch):
    with_files(monkeypatch)
    client, _ = env()
    with client:
        b = main_of(whole(client, "/media/title/tv/100?owner_view=her"))
    assert "filedrawer" not in b and "Quiet.Show.S04E01" not in b
    assert "hero-scores" in hero_and_body(b)[0]


def test_tv_show_page_has_no_columns_chips_or_web_tiles(tvc):
    from tests.hub.test_tv_series_episodes import S1
    html = tv_whole(tvc, f"/media/item/{S1}")
    assert "tlcols" not in html and "filmcol-side" not in html and "makerchip" not in html and "casttiles" not in html
    assert "hero-scores" not in html                                  # JY-316 r3: the strip is web-only


def test_round3_css_strip_is_smaller_web_only_and_the_300px_column_is_gone():
    assert "tlcols" not in CSS
    assert "html:not(.tv) .hero-scores .scorepill { height: 26px;" in CSS              # .scorepill is 30 px
    assert "html:not(.tv) .hero-scores .sp-logo { width: 14px; height: 14px; }" in CSS
    assert "html:not(.tv) .hero-scores { gap: 6px; margin-top: 2px; justify-content: center; }" in CSS   # phone: centred
    assert "@media (min-width: 640px) { html:not(.tv) .hero-scores { justify-content: flex-start; } }" in CSS
    assert not re.search(r"(^|\n)\s*html\.tv[^{]*hero-scores", CSS)
    assert "html:not(.tv) .details .kv:has(> dd.sitepills):not(:has(.scorepill)) { display: none; }" in CSS   # empty Links row


def test_round3_episode_page_has_no_aside_and_film_page_keeps_its_column(env):
    """JY-316 r3 Q1: the film keeps its JY-280 side column; an episode page has none (its score line is JY-315's)."""
    client, _ = env()
    with client:
        ep = main_of(whole(client, "/media/item/ep3"))
        mov = main_of(whole(client, "/media/title/movie/603"))
    assert "<aside" not in ep and "filmcol" not in ep and "hero-scores" not in ep
    assert '<div class="filmcols">' in mov and '<aside class="filmcol-side" aria-label="Scores and details">' in mov
    assert "hero-scores" not in mov


def test_cast_tiles_are_2_3_two_line_names_and_3_5_across_a_phone():
    """JY-283 / JY-317: the TV's JY-323 tile scaled for the web; no circle rule left on any web cast selector."""
    assert "html:not(.tv) .castsec.casttiles .castcard { flex: 0 0 calc((100% - 48px) / 3.5);" in CSS
    assert "@media (min-width: 640px) { html:not(.tv) .castsec.casttiles .castcard { flex-basis: 88px; } }" in CSS
    assert re.search(r"\.castsec\.casttiles \.castname \{[^}]*-webkit-line-clamp: 2;", CSS)
    assert re.search(r"\.castsec\.casttiles \.castrole \{[^}]*white-space: nowrap;[^}]*text-overflow: ellipsis;", CSS)
    web_cast = re.findall(r"html:not\(\.tv\) \.castsec[^{]*\{[^}]*\}", CSS)
    assert web_cast and not any("50%" in r for r in web_cast)


def test_round3_episode_page_has_no_circle_headshots_off_the_tv(env, monkeypatch):
    """JY-316 round 3 (B. 2026-11-06: "Stop placing them in circles."): an episode page's Created by is chips and its
    guests are 2:3 cast tiles - no .makerpic / .guest-pic circles off the TV."""
    monkeypatch.setitem(ITEMS["ep3"], "People", [{"Name": "Gus Guest", "Type": "GuestStar", "Role": "Visitor"}])
    client, _ = env()
    with client:
        b = main_of(whole(client, "/media/item/ep3"))
    assert "makerpic" not in b and "guest-pic" not in b and "makercard" not in b
    assert '<span class="makerchip-role">Creator</span>' in b
    assert "Gus Guest" in b and 'class="sec castsec casttiles" id="guests"' in b


def test_round3_details_runtime_row_keeps_the_ends_time():
    """JY-316 r3 review: the Runtime row in Details keeps the old stat's "ends HH:MM if you start now"."""
    from types import SimpleNamespace
    from hub.shell import templates
    film = {"title": "Bare", "year": 2001, "kind": "tv", "tmdb": 9, "pending": set(), "facts": {},
            "numbers": {"runtime": "45m", "ends": "21:40"}, "official": "M",
            "logos": {"imdb": "/i.svg", "tmdb": "/t.svg", "lbxd": "/l.svg"}, "rating": None, "watch_count": 0}
    src = templates.env.get_template("media_film.html")
    ctx = src.new_context({"film": film, "request": SimpleNamespace(url=SimpleNamespace(path="/media/title/tv/9")),
                           "img_letters": lambda s: s, "status_of": lambda w: {"cls": ""}})
    html = "".join(src.blocks["content"](ctx))
    assert "<dt>Runtime</dt><dd>45m · ends 21:40 if you start now</dd>" in html
    assert "<dt>Rated</dt><dd>M</dd>" in html and '<div class="stats numbers">' not in html
