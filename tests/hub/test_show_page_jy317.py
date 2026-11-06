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


def cols(b):
    """(main column, right-hand column, everything after the aside) of the show / season body."""
    rest = b.split('<div class="filmcols tlcols"><div class="filmcol-main">', 1)[1]
    main, side = rest.split('<aside class="filmcol-side" aria-label="Scores and details">', 1)
    side, after = side.split("</aside>", 1)
    return main, side, after


@pytest.mark.parametrize("path", ["/media/item/ser1", "/media/item/sea1", "/media/title/tv/100"])
def test_scores_details_and_file_sit_in_the_right_hand_column(env, season, monkeypatch, path):
    with_files(monkeypatch)
    with_cast(monkeypatch)
    client, _ = env()
    with client:
        b = main_of(whole(client, path))
    main, side, after = cols(b)
    assert '<div class="microlabel">Scores</div>' in side and '<div class="microlabel">Scores</div>' not in main
    assert "filedrawer" not in b and "filepanel" not in main + side + after   # JY-284: the File panel is the hero chip
    assert b.count('id="file"') == 1 and 'id="file"' in b.split("</header>", 1)[0]
    assert 'class="sec castsec casttiles"' in main and "castsec" not in side
    assert b.count('<h2 class="seclabel">Cast</h2>') == 1 and b.count('<div class="stats numbers">') == 1
    # JY-316 r4 (B.: "Move the cast and score to below the episode sessions"): the Episodes row comes full width
    # BEFORE the two-column block, never inside it; no r3 hero strip
    assert ">Episodes</h2>" not in main + side + after
    assert b.index('class="sec tl-eps"') < b.index('<div class="filmcols tlcols">')
    assert "hero-scores" not in b


def test_season_page_keeps_rate_and_puts_the_banner_after_the_episodes(env, season):
    client, _ = env()
    with client:
        b = main_of(whole(client, "/media/item/sea1"))
    main, side, after = cols(b)
    assert 'class="scorepill sp-you"' in side                         # Rate / Yours stays in the Scores card
    before = b[:b.index('<div class="filmcols tlcols">')]
    assert 'class="sec partof-sec"' in before and "All seasons</a>" in before   # JY-316 r4: under the Episodes row, above the columns
    assert before.index(">Episodes</h2>") < before.index('class="sec partof-sec"')


def test_sidebar_runtime_keeps_the_ends_time():
    """JY-316 r3 review, kept in r4: the sidebar's Runtime keeps "ends HH:MM if you start now"."""
    from types import SimpleNamespace
    from hub.shell import templates
    film = {"title": "Bare", "year": 2001, "kind": "tv", "tmdb": 9, "pending": set(), "facts": {},
            "numbers": {"runtime": "45m", "ends": "21:40"}, "official": "M",
            "logos": {"imdb": "/i.svg", "tmdb": "/t.svg", "lbxd": "/l.svg"}, "rating": None, "watch_count": 0}
    src = templates.env.get_template("media_film.html")
    ctx = src.new_context({"film": film, "request": SimpleNamespace(url=SimpleNamespace(path="/media/title/tv/9")),
                           "img_letters": lambda s: s, "status_of": lambda w: {"cls": ""}})
    side = cols("".join(src.blocks["content"](ctx)))[1]
    assert '<div class="stat-word">45m</div><div class="metaline">ends 21:40 if you start now</div>' in side
    assert '<div class="stat-word">M</div>' in side


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
    assert '<div class="microlabel">Scores</div>' in cols(b)[1]


def test_tv_show_page_has_no_columns_chips_or_web_tiles(tvc):
    from tests.hub.test_tv_series_episodes import S1
    html = tv_whole(tvc, f"/media/item/{S1}")
    assert "tlcols" not in html and "filmcol-side" not in html and "makerchip" not in html and "casttiles" not in html
    assert "hero-scores" not in html


def test_css_column_is_260px_from_1024_small_6px_pills_and_web_only():
    """JY-316 r4: the show / season sidebar is 260 px (film 360 px), its pills the small size with 6 px corners; the
    film's sidebar pills take the 6 px corners too. No r3 hero strip rules left."""
    assert "@media (min-width: 1024px) { html:not(.tv) .filmcols.tlcols { grid-template-columns: minmax(0, 1fr) 260px; } }" in CSS
    assert "@media (min-width: 1024px) { html:not(.tv) .filmcols { grid-template-columns: minmax(0, 1fr) 360px; align-items: start; } }" in CSS
    assert "html:not(.tv) .tlcols .filmcol-side .scorepill { height: 26px; gap: 5px; padding: 0 9px 0 5px; font-size: 12px; }" in CSS
    assert "html:not(.tv) .tlcols .filmcol-side .sp-logo { width: 14px; height: 14px; }" in CSS
    assert "html:not(.tv) .filmcol-side .scorepill { border-radius: 6px; }" in CSS
    assert "hero-scores" not in CSS and "html:not(.tv) .tlcols .tl-epshd" not in CSS
    assert not re.search(r"(^|\n)\s*html\.tv[^{]*(tlcols|filmcol)", CSS)


def test_episode_page_has_no_aside_and_film_page_keeps_its_column(env):
    """JY-316 r3 Q1 / r4 change 4: an episode page has no sidebar; the film keeps its JY-280 column."""
    client, _ = env()
    with client:
        ep = main_of(whole(client, "/media/item/ep3"))
        mov = main_of(whole(client, "/media/title/movie/603"))
    assert "<aside" not in ep and "filmcol" not in ep and "hero-scores" not in ep
    assert '<div class="filmcols">' in mov and '<aside class="filmcol-side" aria-label="Scores and details">' in mov
    assert "hero-scores" not in mov and "tlcols" not in mov


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
