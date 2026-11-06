"""TV episode flow templates (WP-E2, 2026-10-16). `media_film.html` (its `pagehead` and `content` blocks) and the new
`_episode_flow.html` macros are rendered through the app's own Jinja environment with hand-built contexts for the three
kinds of TV page - series, season, episode. `RATINGS`, `NAV`, `GUESTS` and `CREW_EP` below ARE the contract
(review/2026-10-16-episodes-ux/EPISODES_CONTRACT.md section 2): the Python side (WP-E1 `ratings`, WP-E3 `nav`, `guests`,
`crew_ep`) must produce exactly these shapes on the `film` dict, and the templates read nothing else. The CSS tests pin the
one dated tail block of control-surface.css."""
import copy
import re
from pathlib import Path

import pytest

from hub import media_film, media_home, shell  # noqa: F401  (the imports register the template globals)
from tests.hub.tv_css import design_px

ENV = shell.templates.env
CSS = (Path(shell.__file__).resolve().parent / "static" / "control-surface.css").read_text(encoding="utf-8")
TAIL = CSS.split("/* TV episode flow (2026-10-16) */", 1)[1]


class _Url:
    path = "/media/item/s2e2"


class _Request:
    url = _Url
    cookies: dict = {}
    headers: dict = {}


@pytest.fixture(autouse=True)
def media_nav_stub(monkeypatch):
    """The Media tabs read the request's cookies / queue counts; the pieces under test do not."""
    monkeypatch.setitem(ENV.globals, "media_nav", lambda request: {"sections": [], "tabs": [], "section": {"label": "TV"}})


def ep(number, rating, name=None, seen=False, aired=True, in_progress=False, votes=1000, season=2, href="auto"):
    return {"number": number, "rating": rating, "votes": votes if rating is not None else 0, "aired": aired, "seen": seen,
            "in_progress": in_progress, "jf_id": f"s{season}e{number}",
            "href": f"/media/item/s{season}e{number}" if href == "auto" and aired else (None if href == "auto" else href),
            "name": name or f"Episode {number}"}


RATINGS = {
    "source": "IMDb",
    "seasons": [
        {"n": 1, "year": 2024, "avg": 8.0, "votes": 4400, "seen": 3, "total": 4, "aired": 4,
         "eps": [ep(1, 8.1, "Landman", seen=True, season=1), ep(2, 7.7, "Dancing Rainbows", seen=True, season=1),
                 ep(3, 8.6, "Hell Has a Front Yard", seen=True, season=1), ep(4, 7.6, "The Sting", season=1)]},
        {"n": 2, "year": 2025, "avg": 8.4, "votes": 5000, "seen": 1, "total": 4, "aired": 4,
         "eps": [ep(1, 8.3, seen=True), ep(2, 8.0, votes=1800), ep(3, None), ep(4, 8.9, "The Finale")]},
        {"n": 3, "year": 2026, "avg": None, "votes": 0, "seen": 0, "total": 2, "aired": 0,
         "eps": [ep(1, None, aired=False, season=3), ep(2, None, aired=False, season=3)]},
    ],
    "best": {"season": 2, "number": 4, "name": "The Finale", "rating": 8.9},
    "trend": "S2 up 0.4 on S1",
    "current": 2,
    "episode": None,
}

NAV = {
    "show": {"title": "Landman", "href": "/media/item/show1"},
    "season": {"n": 2, "href": "/media/item/season2", "total": 4},
    "seasons": [{"n": 1, "href": "/media/item/season1", "on": False}, {"n": 2, "href": "/media/item/season2", "on": True},
                {"n": 3, "href": "/media/item/season3", "on": False}],
    "prev": {"number": 1, "name": "Episode 1", "href": "/media/item/s2e1"},
    "next": {"number": 3, "name": "Episode 3", "href": "/media/item/s2e3"},
    "position": "E2 of 4",
}

GUESTS = [{"name": "Colm Feore", "role": "Nathan", "poster": "jf:abc", "href": "/media/person/77", "eps_this_season": 3},
          {"name": "Mark Collie", "role": None, "poster": None, "href": None, "eps_this_season": 1}]

CREW_EP = [{"role": "Directed by", "people": [{"name": "Stephen Kay", "href": "/media/person/5"}]},
           {"role": "Written by", "people": [{"name": "Taylor Sheridan", "href": None}, {"name": "Dave Erickson", "href": None}]}]


def listed(number, season, name=None, played=False):
    """One entry of film.seasons[].episodes (what episode_list() builds)."""
    return {"jf_id": f"s{season}e{number}", "number": number, "name": name or f"Episode {number}", "air_date": "1 Jan",
            "runtime": "58 min", "still": None, "aired": True, "played": played, "in_progress": False, "play": None,
            "state": {"key": "todo", "cls": "st-todo", "word": "Not watched"}}


def film_dict(**over):
    f = {"kind": "tv", "title": "Landman", "year": 2024, "pending": set(), "numbers": {}, "facts": {}, "logos": {},
         "genres": [], "overview": "A crew, a lawsuit and a family.", "episode": None, "watch_owner": None,
         "seasons": [{"n": 1, "name": "Season 1", "watched_text": "3 of 4 watched", "id": "season1", "open": False,
                      "episodes": [listed(1, 1, "Landman", True), listed(2, 1, "Dancing Rainbows", True),
                                   listed(3, 1, "Hell Has a Front Yard", True), listed(4, 1, "The Sting")]},
                     {"n": 2, "name": "Season 2", "watched_text": "1 of 4 watched", "id": "season2", "open": True,
                      "episodes": [listed(1, 2, played=True), listed(2, 2), listed(3, 2), listed(4, 2, "The Finale")]}]}
    f.update(copy.deepcopy(over))
    return f


EPISODE = {"code": "S2E2", "title": "Episode 2", "air_date": "23 Nov 2025", "overview": "Tommy balances a crew.",
           "runtime": "58 min", "play": {"href": "http://jf/play/s2e2", "label": "Play ▶"}, "show_href": "/media/item/show1"}


def series(**over):
    return film_dict(ratings=copy.deepcopy(RATINGS), **over)


def season(**over):
    return film_dict(ratings=copy.deepcopy(RATINGS), nav={**copy.deepcopy(NAV), "season": None, "prev": None, "next": None,
                                                           "position": None}, **over)


def episode(**over):
    r = copy.deepcopy(RATINGS)
    r["episode"] = {"rating": 8.0, "votes": 1800, "vs_avg": "below"}
    base = {"episode": copy.deepcopy(EPISODE), "ratings": r, "nav": copy.deepcopy(NAV), "guests": copy.deepcopy(GUESTS),
            "crew_ep": copy.deepcopy(CREW_EP)}
    return film_dict(**{**base, **over})


def blocks(film):
    t = ENV.get_template("media_film.html")
    c = {"film": film, "request": _Request(), "areas": [], "active_id": None, "status": {}, "src": {}}
    return ("".join(t.blocks["pagehead"](t.new_context(c))), "".join(t.blocks["content"](t.new_context(c))))


def head(film):
    return blocks(film)[0]


def page(film):
    h, c = blocks(film)
    return h + c


def macro(name, *args, **kw):
    mod = ENV.get_template("_episode_flow.html").make_module({})
    return str(getattr(mod, name)(*args, **kw))


def bars(html):
    return re.findall(r'<(?:a|span) class="(rbar[^"]*)"[^>]*>.*?</(?:a|span)>', html, re.S)


def section(html, sid):
    return re.search(rf'<section class="sec" id="{sid}">.*?</section>', html, re.S).group(0)


NEW_MARKUP = ("crumbs", "epeyebrow", "eprating", 'id="compare"', "cmprow", "ratestrip", "rbar", 'id="guests"', 'id="crew-ep"',
              "epnav", "eprow-r", "seasonseg", 'id="rating-strip"', 'id="season-place"', "eflow-hd")


# ---- series: JY-290 (B. 2026-11-02) - no "Seasons compared", no rating bar chart, no bottom Seasons list ----
TV = {"seasons": [{"n": 1, "title": "Season 1", "href": "/media/item/season1"}, {"n": 2, "title": "Season 2", "href": "/media/item/season2"}],
      "eps": {"label": "Season 2"}}


def carousel(html):
    return re.search(r'<section class="sec tl-eps".*?</section>', html, re.S).group(0)


def test_series_and_season_pages_have_no_compare_no_bar_chart_and_no_bottom_list():
    for f in (series(tv=TV), season(tv=TV)):
        p = page(f)
        for gone in ('id="compare"', "Seasons compared", "cmprow", 'id="rating-strip"', "ratestrip", "rbar", 'id="seasons"',
                     "seasonbox", 'id="season-'):
            assert gone not in p, gone
        assert "tl-eps" in p and "A crew, a lawsuit" in p


def test_series_rows_gain_rating_and_above_or_below_the_season_average():
    s2 = carousel(page(series(tv=TV)))                                                 # JY-290: the Episodes row's tiles
    rated = re.findall(r'<span class="eprow-r"><span class="vh">Rated </span>★ ([\d.]+)(?:<small>(\w+) avg</small>)?</span>', s2)
    assert rated == [("8.3", "below"), ("8.0", "below"), ("8.9", "above")]            # avg 8.4; E3 has no rating: no mark
    assert s2.count("eprow-r") == 3
    s1 = carousel(page(series(tv={**TV, "eps": {"label": "Season 1"}})))
    assert re.findall(r'★ ([\d.]+)<small>(\w+) avg', s1) == [("8.1", "above"), ("7.7", "below"), ("8.6", "above"), ("7.6", "below")]
    assert re.search(r'<a class="tl-eplink"[^>]*>(?:(?!</a>).)*class="eprow-r"', s2, re.S)   # inside the tile's link


def test_a_rating_equal_to_the_average_says_neither_above_nor_below():
    r = copy.deepcopy(RATINGS)
    r["seasons"][0]["avg"] = 8.1
    s1 = carousel(page(film_dict(ratings=r, tv={**TV, "eps": {"label": "Season 1"}})))
    assert '<span class="eprow-r"><span class="vh">Rated </span>★ 8.1</span>' in s1


# ---- season: head switch + strip + rated rows ----
def test_season_head_has_no_second_seasons_row_off_the_tv():
    # JY-316 round 2 (B. 2026-11-06: "the seasons would be along the row of pills. And shows would be under that.
    # Allowing the removal of the all seasons row which is not needed."): was the hero's S1 / S2 switch; off the TV the
    # Episodes row's chips are the one season selector, so the season head draws no switch (the TV keeps it)
    h = head(season())
    assert "seasonseg" not in h
    tpl = (Path(media_film.__file__).resolve().parent / "templates" / "media_film.html").read_text(encoding="utf-8")
    assert "{% if epnav and tvm %}{{ ef.seasonswitch(epnav) }}{% endif %}" in tpl
    assert "crumbs" not in h and "S2<span" not in h                                   # crumbs and the episode eyebrow are the episode page's


# JY-116 (2026-10-24, B.: "JY-116: A"): a season page's head says "Season 2 of 4" above the show title, in the episode
# eyebrow's own style. The numbers come from nav.seasons, which the page already holds.
def test_season_head_says_which_season_above_the_title():
    h = head(season())
    assert '<p class="epeyebrow">Season 2 of 3</p>' in h
    assert h.index("epeyebrow") < h.index("hero-detail-title")


def test_a_one_season_show_reads_season_1_of_1_and_has_no_switch():
    n = copy.deepcopy(NAV)
    n["seasons"] = [{"n": 1, "href": "/media/item/season1", "on": True}]
    h = head(film_dict(ratings=copy.deepcopy(RATINGS), nav=n))
    assert '<p class="epeyebrow">Season 1 of 1</p>' in h and "seasonseg" not in h


def test_season_eyebrow_counts_to_the_highest_season_number_not_the_list_length():
    n = copy.deepcopy(NAV)
    n["seasons"] = [{"n": 4, "href": "/media/item/season4", "on": False}, {"n": 5, "href": "/media/item/season5", "on": True}]
    assert '<p class="epeyebrow">Season 5 of 5</p>' in head(film_dict(ratings=copy.deepcopy(RATINGS), nav=n))


def test_season_eyebrow_is_not_drawn_for_specials_or_an_unknown_season():
    n = copy.deepcopy(NAV)
    n["seasons"] = [{"n": 0, "href": "/media/item/sp", "on": True}, {"n": 1, "href": "/media/item/season1", "on": False}]
    assert "epeyebrow" not in head(film_dict(ratings=copy.deepcopy(RATINGS), nav=n))      # Specials: no "Season 0"
    n["seasons"] = [{"n": 1, "href": "/media/item/season1", "on": False}, {"n": 2, "href": "/media/item/season2", "on": False}]
    assert "epeyebrow" not in head(film_dict(ratings=copy.deepcopy(RATINGS), nav=n))      # none marked `on`
    n["seasons"] = []
    assert "epeyebrow" not in head(film_dict(ratings=copy.deepcopy(RATINGS), nav=n))      # the Jellyfin read gave no seasons


def test_season_eyebrow_leaves_show_film_and_episode_pages_alone():
    assert "Season 2 of" not in head(series())                                            # a show page
    assert "epeyebrow" not in head(series())
    assert "epeyebrow" not in head(film_dict(kind="movie", title="A Film"))               # a film
    h = head(episode())
    assert h.count("epeyebrow") == 1 and "Season 2 of" not in h                           # the episode page keeps "S2 · E2 of 4"
    assert re.search(r'<p class="epeyebrow">Landman<span class="sep"> · </span>S2<span class="sep"> · </span>E2 of 4</p>', h)


def test_season_eyebrow_reuses_the_episode_eyebrow_class_with_no_new_css():
    assert ".seasonline" not in CSS and "Season N" not in TAIL
    h = head(season())
    assert 'class="epeyebrow"' in h


def test_tv_show_and_season_pages_have_no_compare_and_no_bar_chart(monkeypatch):
    monkeypatch.setitem(ENV.globals, "tv_mode", lambda request: True)                     # JY-290 Q2 = A: the TV too
    for f in (series(tv=TV), season(tv=TV)):
        p = page(f)
        assert 'id="compare"' not in p and 'id="rating-strip"' not in p and "ratestrip" not in p and 'id="seasons"' not in p


def test_episode_page_keeps_its_mini_strip():
    assert 'id="season-place"' in page(episode()) and "ratestrip" in page(episode())   # JY-290 Q3 = A: kept


def test_season_eyebrow_survives_tv_mode_markup(monkeypatch):
    monkeypatch.setitem(ENV.globals, "tv_mode", lambda request: True)
    h = head(season())
    assert '<p class="epeyebrow">Season 2 of 3</p>' in h                                  # tv.css has no rule hiding .epeyebrow
    tv = design_px((Path(shell.__file__).resolve().parent / "static" / "tv.css").read_text(encoding="utf-8"))
    # JY-250 (2026-10-25): tv.css now sizes .epeyebrow (18 px); no rule may hide it
    rules = [body for sels, body in re.findall(r"([^{}]+)\{([^}]*)\}", re.sub(r"/\*.*?\*/", "", tv, flags=re.S))
             if "epeyebrow" in sels]
    assert rules and not any(re.search(r"display:\s*none|visibility:\s*hidden", b) for b in rules)


def test_season_page_has_rated_tiles_but_no_strip_and_no_compare_block():
    p = page(season(tv=TV))
    assert 'id="compare"' not in p and "Seasons compared" not in p and 'id="rating-strip"' not in p   # JY-290
    assert "eprow-r" in carousel(p)


def test_a_single_season_has_no_switch():
    n = copy.deepcopy(NAV)
    n["seasons"] = n["seasons"][:1]
    assert "seasonseg" not in head(film_dict(ratings=copy.deepcopy(RATINGS), nav=n))


# ---- episode ----
def test_episode_crumbs_have_two_links_back_and_the_eyebrow_says_where():
    f = episode()
    h = head(f)
    cr = re.search(r'<nav class="crumbs" aria-label="Back to">(.*?)</nav>', h, re.S).group(1)
    assert re.findall(r'<a href="([^"]+)">([^<]+)</a>', cr) == [("/media/item/show1", "‹ Landman"), ("/media/item/season2", "Season 2")]
    assert '<span class="here" aria-current="page">E2</span>' in cr
    assert h.index("tl-epstill") < h.index("crumbs") < h.index("epeyebrow")             # JY-315: in the text column, after the still
    assert re.search(r'<p class="epeyebrow">Landman<span class="sep"> · </span>S2<span class="sep"> · </span>E2 of 4</p>', h)
    assert h.index("epeyebrow") < h.index("hero-detail-title")
    assert "seasonseg" not in h                                                        # the switch is the season page's


def test_episode_score_line_and_its_absence():
    h = head(episode())
    assert re.search(r'<p class="eprating"><b>★ 8.0</b><span>1.8K ratings</span><span>below the season average</span>'
                     r'<span class="eprating-src">IMDb</span></p>', h)
    r = copy.deepcopy(episode()["ratings"])
    r["episode"] = {"rating": None, "votes": 0, "vs_avg": None}
    assert "eprating" not in head(episode(ratings=r))
    r["episode"] = None
    assert "eprating" not in head(episode(ratings=r))


def test_episode_keeps_the_existing_play_and_mark_controls():
    h = head(episode(watch_toggle={"jf_id": "s2e2", "played": False, "season": 2}, watch_owner="you"))
    assert 'href="http://jf/play/s2e2"' in h and ">Play ▶</a>" in h                    # the item page's own Play, no new endpoint
    assert "Mark watched" in h                                                         # the item page's own toggle, still there


def test_episode_guests_are_circle_portraits_with_role_and_eps_this_season(monkeypatch):
    monkeypatch.setitem(ENV.globals, "tv_mode", lambda request: True)                   # JY-315: the circles stay the TV's
    sec = section(page(episode()), "guests")
    cards = re.findall(r'<(a|div) class="guest"([^>]*)>(.*?)</\1>', sec, re.S)
    assert len(cards) == 2
    tag, attrs, inner = cards[0]
    assert tag == "a" and 'href="/media/person/77"' in attrs
    assert 'class="poster guest-pic"' in inner and "/img/jf:abc?" in inner
    assert '<span class="guest-name">Colm Feore</span><span class="guest-role">Nathan</span>' in inner
    assert '<span class="guest-eps">3 eps this season</span>' in inner
    tag, attrs, inner = cards[1]
    assert tag == "div" and "href" not in attrs                                        # no person page: a plain card
    assert '<span class="guest-pic initials" aria-hidden="true">MC</span>' in inner    # no portrait: initials
    assert "guest-role" not in inner and '<span class="guest-eps">1 ep this season</span>' in inner   # no role: no line; "1 ep"


def test_episode_crew_rows_link_a_person_with_a_page_else_the_person_find_route():
    sec = section(page(episode()), "crew-ep")
    kv = re.findall(r'<div class="kv"><dt>([^<]+)</dt><dd>(.*?)</dd></div>', sec)
    assert [k for k, _ in kv] == ["Directed by", "Written by"]
    assert kv[0][1] == '<a href="/media/person/5">Stephen Kay</a>'
    assert kv[1][1] == ('<a href="/media/person/find?name=Taylor%20Sheridan">Taylor Sheridan</a>, '
                        '<a href="/media/person/find?name=Dave%20Erickson">Dave Erickson</a>')


def test_episode_mini_strip_has_this_episode_gold_and_no_legend():
    p = page(episode())
    sec = section(p, "season-place")
    assert "Where this sits in Season 2" in sec and "avg 8.4 · this one below" in sec
    assert 'class="ratestrip is-mini"' in sec and "ratelegend" not in sec
    assert bars(sec) == ["rbar is-seen", "rbar is-on", "rbar", "rbar"]               # exactly one gold bar: E2, the page's episode
    assert 'rbar is-on" href="/media/item/s2e2"' in sec
    assert 'id="compare"' not in p and 'id="rating-strip"' not in p                  # the big strip and compare are not on an episode page


def test_episode_prev_next_cards_and_a_missing_side():
    p = page(episode())
    nav = re.search(r'<nav class="epnav" aria-label="Neighbouring episodes">(.*?)</nav>', p, re.S).group(1)
    assert re.findall(r'<a class="epnav-card (is-\w+)" href="([^"]+)"><span class="epnav-k">([^<]+)</span><span class="epnav-t">([^<]+)</span>',
                      nav) == [("is-prev", "/media/item/s2e1", "‹ Previous", "E1 · Episode 1"),
                               ("is-next", "/media/item/s2e3", "Next ›", "E3 · Episode 3")]
    n = copy.deepcopy(NAV)
    n["prev"] = None
    only = re.search(r'<nav class="epnav".*?</nav>', page(episode(nav=n)), re.S).group(0)
    assert "is-prev" not in only and only.count("epnav-card") == 1 and "is-next" in only
    n["next"] = None
    assert "epnav" not in page(episode(nav=n))


def test_episode_sections_come_in_the_contract_order():
    p = page(episode())
    marks = ['id="guests"', 'id="crew-ep"', 'id="season-place"', 'class="epnav"']
    at = [p.index(m) for m in marks]
    assert at == sorted(at)
    # JY-282 (2026-11-03, pick Q2 = A): an episode page says the episode's synopsis only, in the hero, before them all
    assert "A crew, a lawsuit" not in p and p.index("Tommy balances a crew.") < at[0]


def test_episode_with_nothing_known_draws_no_empty_frames():
    f = episode(guests=[], crew_ep=[])
    f["ratings"] = None
    f["nav"] = {**copy.deepcopy(NAV), "prev": None, "next": None}
    p = page(f)
    for gone in ('id="guests"', 'id="crew-ep"', 'id="season-place"', "epnav", "eprating", "ratestrip", "eprow-r"):
        assert gone not in p, gone
    assert "crumbs" in p and "epeyebrow" in p                                         # the way back still draws from nav alone
    f2 = episode()
    del f2["guests"], f2["crew_ep"]                                                   # keys absent altogether
    assert 'id="guests"' not in page(f2) and 'id="crew-ep"' not in page(f2)


# ---- pages that carry none of it ----
def test_a_series_without_ratings_or_nav_carries_none_of_the_new_markup():
    p = page(film_dict())
    for gone in NEW_MARKUP:
        assert gone not in p, gone
    assert 'id="seasons"' not in p and "A crew, a lawsuit" in p and "Landman" in p   # JY-290: no bottom Seasons list


def test_a_movie_page_carries_none_of_the_new_markup():
    movie = {"kind": "movie", "title": "Harbour Lights", "year": 2019, "pending": set(), "numbers": {}, "facts": {}, "logos": {},
             "genres": [], "overview": "A film.", "episode": None, "seasons": []}
    p = page(movie)
    for gone in NEW_MARKUP:
        assert gone not in p, gone


def test_a_series_with_ratings_none_draws_no_compare_or_strip():
    p = page(film_dict(ratings=None))
    assert "compare" not in p and "ratestrip" not in p and "eprow-r" not in p


def test_lazy_season_rows_gain_ratings_only_when_given():
    t = ENV.get_template("_season_episodes.html")
    eps = [{"number": 1, "name": "One", "date_text": "1 Jan", "future": False, "on_disk": False, "overview": None},
           {"number": 2, "name": "Two", "date_text": "8 Jan", "future": False, "on_disk": False, "overview": None}]
    plain = t.render(episodes=eps)
    assert "eprow-r" not in plain and plain.count('class="row"') == 2
    rated = t.render(episodes=eps, rated={1: {"rating": 8.5}}, avg=8.0)
    assert rated.count("eprow-r") == 1 and "★ 8.5<small>above avg</small>" in rated


# ---- macros ----
def test_epnum_reads_the_number_out_of_the_position_text():
    assert macro("epnum", {"position": "E6 of 10"}) == "6" and macro("epnum", {"position": None}) == "0"
    assert macro("votes", 3600) == "3.6K" and macro("votes", 842) == "842" and macro("votes", 0) == ""


def test_macros_draw_nothing_for_empty_input():
    for name, arg in (("crumbs", None), ("eyebrow", None), ("seasonswitch", None), ("guests", []), ("crew", []),
                      ("prevnext", None), ("epscore", None)):
        assert macro(name, arg).strip() == "", name
    assert macro("strip", None).strip() == "" and macro("strip", {"n": 1, "eps": []}).strip() == ""


# ---- CSS: one dated tail block, tokens only, phone-first strip ----
def test_episode_flow_css_is_one_dated_block_at_the_tail_with_tokens_only():
    assert CSS.count("/* TV episode flow (2026-10-16) */") == 1
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", TAIL)               # every colour is a token
    assert "select" not in TAIL.lower()                                                # never the word before a brace in a comment
    assert "var(--good-soft)" in TAIL and "var(--gold)" in TAIL                       # JY-290: --gold-soft left with the compare rows
    for tok in set(re.findall(r"var\((--[a-z0-9-]+)\)", TAIL)):
        assert re.search(rf"(?m)^\s*.*{re.escape(tok)}:", CSS.split(":root {", 1)[1].split("\n}", 1)[0]), tok   # defined in :root


def test_strip_scrolls_sideways_in_its_own_box_on_a_phone_and_bars_are_44px():
    box = re.search(r"\.ratestrip \{([^}]*)\}", TAIL).group(1)
    assert "overflow-x: auto" in box and "margin: 0 -16px" in box and "padding: 0 16px" in box   # the chip row's margin trick
    assert re.search(r"@media \(min-width: 640px\) \{ \.ratestrip \{ margin-inline: -24px; padding-inline: 24px; \} \}", TAIL)
    assert "width: max-content" in re.search(r"\.rbars \{([^}]*)\}", TAIL).group(1)           # wider than the box: it scrolls
    assert "flex: 0 0 44px" in re.search(r"\.rbar \{([^}]*)\}", TAIL).group(1)                # a 44 px bar on a phone
    assert re.search(r"@media \(min-width: 640px\) \{ \.rbar \{ flex: 1 1 0; min-width: 44px; \} \}", TAIL)   # equal columns from 640 px


def test_strip_states_use_the_emerald_and_gold_tokens():
    assert re.search(r"\.rbar\.is-seen > i \{[^}]*var\(--good-soft\)[^}]*var\(--good\)", TAIL)
    assert re.search(r"\.rbar\.is-on > i[^{]*\{[^}]*background: var\(--gold\)", TAIL)
    assert re.search(r"\.rbar\.is-unaired > i \{[^}]*border-style: dashed", TAIL)


def test_guest_crumb_and_nav_css_are_phone_sized():
    assert "border-radius: 50%" in re.search(r"\.guest-pic \{([^}]*)\}", TAIL).group(1)
    assert "min-height: 40px" in re.search(r"\.crumbs a \{([^}]*)\}", TAIL).group(1)
    assert "repeat(2, minmax(0, 1fr))" in re.search(r"\.epnav \{([^}]*)\}", TAIL).group(1)
    assert "grid-column: 2" in re.search(r"\.epnav-card\.is-next \{([^}]*)\}", TAIL).group(1)       # a lone Next keeps its half
    assert re.search(r"@media \(max-width: 767px\) \{ \.seasonseg a \{ height: 40px;", TAIL)


def test_no_existing_class_is_redefined_by_the_block():
    own = set(re.findall(r"^\.([a-z][a-z0-9-]*)", TAIL, re.M))
    before = CSS.split("/* TV episode flow (2026-10-16) */", 1)[0]
    # .seasonseg / .guests-style names are new; the shared recipes (.seg, .chip, .kv) are only reused, never redefined here
    assert not {c for c in own if re.search(rf"(?m)^\.{re.escape(c)}[ ,{{:.>\[]", before)}, own
