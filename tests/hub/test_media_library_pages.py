"""F3b (2026-10-06) - Movies + TV Shows hub pages, Tonight deal, By-year kind filter.
Snapshots are written here with write_envelope; the committed sample is never relied on."""
import random
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from hub import media_db, media_library
from tests.hub.conftest import main_raw as main_of  # noqa: F401
from tests.hub.helpers import JELLY, LINK
from tests.hub.test_media_frame import current, env, env as frame_env  # noqa: F401
from tests.hub.test_media_rate import HX, env as rate_env  # noqa: F401


NOW = datetime.now(timezone.utc)


def iso(days):
    return (NOW - timedelta(days=days)).isoformat()


def movie(title, year, key, played=False, runtime=100, cr=None, added=100, last=None, genres=None, jf="j"):
    return {"title": title, "year": year, "jf_id": jf + key.replace(":", "-"), "item_key": key, "poster": "jf:" + key,
            "backdrop": None, "runtime_min": runtime, "played": played, "last_played_at": last,
            "added_at": iso(added), "community_rating": cr, "genres": genres or []}


def show(title, year, key, eps, unplayed, status="Continuing", cr=None, added=100, last=None):
    return {"title": title, "year": year, "jf_id": "j" + key.replace(":", "-"), "item_key": key, "poster": "jf:" + key,
            "backdrop": None, "status_word": status, "episodes": eps, "unplayed": unplayed,
            "played": unplayed == 0, "last_played_at": last, "added_at": iso(added),
            "community_rating": cr, "genres": []}


MOVIES = [
    movie("Alpha Film", 2020, "tmdb:11", played=True, runtime=112, cr=7.84, last=iso(3), genres=["Drama", "Crime"]),
    movie("Bravo Film", 2022, "tmdb:12", played=False, runtime=90, cr=6.1, added=2),
    movie("Charlie Film", 2018, "jf:13", played=False, runtime=45, cr=None, added=50),
    movie("Delta Film", 2024, "tmdb:14", played=True, runtime=140, cr=8.6, last=iso(40)),
]
SHOWS = [
    show("Echo Show", 2019, "tmdb:21", 26, 6, cr=8.0, last=iso(1)),
    show("Foxtrot Show", 2021, "tmdb:22", 10, 10, status="Ended"),
    show("Golf Show", 2015, "tmdb:23", 8, 0, status="Ended", cr=9.0, last=iso(20)),
]
HER_MOVIES = [movie("Alpha Film", 2020, "tmdb:11", played=False, runtime=112, cr=7.84),
              movie("Bravo Film", 2022, "tmdb:12", played=True, runtime=90, cr=6.1, last=iso(1))]
ARRV = {"summary": "x", "arrived": [
    {"title": "Fresh Movie", "item_key": "tmdb:31", "kind": "movie", "poster": "radarr:1", "when": "yesterday"},
    {"title": "Old Movie", "item_key": "tmdb:32", "kind": "movie", "poster": None, "when": "9 days ago"},
    {"title": "New Series - S01 - 3 episodes", "item_key": "tvdb:41", "kind": "season", "poster": "sonarr:1",
     "when": "today"}]}


def jelly(**extra):
    return {**JELLY, "server_id": "srv", "movies": MOVIES, "shows": SHOWS, **extra}


def body(client, path):
    html = client.get(path).text
    return html, html.split("<main", 1)[1]


def row_titles(main_html):
    """Titles of the library rows only (after the controls form)."""
    rows = main_html.split('class="toolbar"', 1)[1].split("</form>", 1)[1]   # media-ux2: To rate forms may sit above
    return re.findall(r'class="row-title">([^<(\n]+?)\s*(?:\(|\n|<)', rows)


def test_movies_page_in_frame_with_head_groups_and_words(env):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        html, b = body(c, "/media/movies?view=list")   # media-ux4: grid is the default; the row words live in List
    assert current(html, "sectabs") == ["Movies"] and current(html, "sectabs sub") == ["My films"]
    assert "4 films · 2 watched · 2 to watch" in b
    assert b.index(">Watched · 2<") < b.index(">Not yet watched · 2<")
    assert "1h 52m" in b and "Watched 3d ago" in b and "Not watched" in b and "45m" in b
    assert "7.8" in b and "TMDB" in b and "Drama, Crime" in b
    assert 'class="poster row-poster' in b


def test_row_links_item_page_over_title_page(env):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        _, b = body(c, "/media/movies")
    assert 'href="/media/item/jtmdb-11"' in b and 'href="/media/item/jjf-13"' in b
    assert "/web/#/details" not in b and 'href="/media/title/movie/11"' not in b


def test_default_sort_is_score_then_year_then_title_and_other_sorts(env):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        media_db.set_rating("tmdb:11", 7, "movie", "Alpha Film", year=2020)
        media_db.set_rating("tmdb:14", 9, "movie", "Delta Film", year=2024)

        def order(q):
            return row_titles(body(c, "/media/movies?" + q + "&group=0")[1])
        assert order("") == ["Delta Film", "Alpha Film", "Bravo Film", "Charlie Film"]
        assert order("sort=title") == ["Alpha Film", "Bravo Film", "Charlie Film", "Delta Film"]
        assert order("sort=year") == ["Delta Film", "Bravo Film", "Alpha Film", "Charlie Film"]
        assert order("sort=added") == ["Bravo Film", "Charlie Film", "Alpha Film", "Delta Film"]
        assert order("sort=rating") == ["Delta Film", "Alpha Film", "Bravo Film", "Charlie Film"]
        b = body(c, "/media/movies?view=list")[1]   # media-ux4: grid is the default; the row words live in List
        assert 'class="row-score score-9' in b and "Your rating: 9 out of 10" in b


def test_search_and_group_off(env):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        _, b = body(c, "/media/movies?q=DELTA&group=0")
        assert row_titles(b) == ["Delta Film"] and ">Watched ·" not in b
        assert "Nothing matches that search" in body(c, "/media/movies?q=zzz")[1]


def test_new_this_week_strip_present_and_absent(env):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        _, m = body(c, "/media/movies")
        _, t = body(c, "/media/tv")
    assert ">New this week</h2>" in m and "Fresh Movie" in m and "yesterday" in m and "Old Movie" not in m
    assert "New Series" in t and "Fresh Movie" not in t
    main = env(jellyfin=jelly(), arr={"summary": "x", "arrived": []})
    with TestClient(main.app) as c:
        assert "New this week" not in body(c, "/media/movies")[1]


def test_tv_page_groups_words_and_head(env):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        html, b = body(c, "/media/tv?view=list")   # media-ux4: grid is the default; the row words live in List
    assert current(html, "sectabs") == ["TV Shows"] and current(html, "sectabs sub") == ["My shows"]
    assert "3 shows · 1 watching · 1 not started · 1 finished" in b
    assert b.index(">Watching · 1<") < b.index(">Not started · 1<") < b.index(">Finished · 1<")
    assert "Continuing" in b and "26 episodes · 6 to watch" in b and "8 episodes · All watched" in b
    assert "Last watched 24h ago" in b and 'href="/media/item/jtmdb-21"' in b


def test_her_view_uses_her_list_or_hides_marks(env):
    d = jelly(her={"up_next": [], "history": {}, "movies": HER_MOVIES, "shows": []})
    main = env(jellyfin=d, arr=ARRV)
    with TestClient(main.app) as c:
        media_db.set_rating("tmdb:11", 9, "movie", "Alpha Film", year=2020)
        media_db.set_rating("tmdb:11", 4, "movie", "Alpha Film", year=2020, owner="her")
        _, b = body(c, "/media/movies?owner_view=her")
    assert "2 films · 1 watched · 1 to watch" in b and "Delta Film" not in b
    assert "Your rating: 4" in b and "Your rating: 9" not in b
    main = env(jellyfin=jelly(her=None), arr=ARRV)
    with TestClient(main.app) as c:
        media_db.set_rating("tmdb:11", 9, "movie", "Alpha Film", year=2020)
        _, b = body(c, "/media/movies?owner_view=her")
        _, tonight = body(c, "/media/movies/tonight?owner_view=her")
    assert "4 films<" in b and "watched" not in b.split('<p class="metaline">')[1].split("</p>")[0]
    assert "Not watched" not in b and 'title="Your rating' not in b and "Grouped" not in b
    assert "nothing to deal" in tonight


def test_absent_arrays_are_quiet_words(env):
    main = env(jellyfin=dict(JELLY), arr=ARRV)
    with TestClient(main.app) as c:
        for p in ("/media/movies", "/media/tv", "/media/movies/tonight", "/media/tv/tonight"):
            assert "Library list not available yet" in body(c, p)[1]


# ---- Tonight ----

def film_rows(items, ratings=None):
    return media_library.film_rows(items, ratings or {}, lambda v: "x ago", lambda r, k: (None, False))


def pool():
    return film_rows([
        movie("Short", 2020, "tmdb:1", runtime=80, cr=5.0),
        movie("Best", 2021, "tmdb:2", runtime=130, cr=9.0),
        movie("Good", 2021, "tmdb:3", runtime=130, cr=8.0),
        movie("Meh", 2021, "tmdb:4", runtime=130, cr=4.0),
        movie("New", 2021, "tmdb:5", runtime=130, cr=3.0, added=1),
        movie("Fave", 2010, "tmdb:6", played=True, runtime=130, cr=7.0, last=iso(300)),
        movie("Seen", 2010, "tmdb:7", played=True, runtime=130, cr=7.0, last=iso(300)),
    ])


def test_deal_three_distinct_piles_unplayed_except_old_favourite():
    rows = pool()
    ratings = {"tmdb:6": 9, "tmdb:7": 5}
    seen_piles = set()
    for seed in range(60):
        cards = media_library.deal_tonight(rows, ratings, "movie", random.Random(seed))
        assert len(cards) == 3 and len({c["pile"] for c in cards}) == 3
        assert len({c["row"]["item_key"] for c in cards}) == 3
        for c in cards:
            seen_piles.add(c["pile"])
            assert c["row"]["title"] != "Seen"
            assert c["row"]["played"] is False or c["pile"] == "Watch again"
            if c["pile"] == "Watch again":
                assert c["row"]["title"] == "Fave"
            if c["pile"] == "A short one":
                assert c["row"]["title"] == "Short"
            if c["pile"] == "Just arrived":
                assert c["row"]["title"] == "New"
    assert seen_piles == {"A short one", "Acclaimed", "Just arrived", "Watch again", "Wildcard"}


def test_deal_is_deterministic_and_shuffles_per_seed():
    rows, ratings = pool(), {"tmdb:6": 9}

    def deal(s):
        return [(c["pile"], c["row"]["title"])
                for c in media_library.deal_tonight(rows, ratings, "movie", random.Random(s))]
    assert deal(5) == deal(5)
    assert len({tuple(deal(s)) for s in range(20)}) > 1


def test_deal_fewer_than_three():
    rows = film_rows([movie("Only", 2020, "tmdb:1"), movie("Two", 2020, "tmdb:2", played=True)])
    cards = media_library.deal_tonight(rows, {}, "movie", random.Random(1))
    assert [c["row"]["title"] for c in cards] == ["Only"]
    assert media_library.deal_tonight([], {}, "movie", random.Random(1)) == []


def test_tv_deal_piles():
    rows = media_library.show_rows(
        [show("W", 2020, "tmdb:1", 10, 4), show("N", 2020, "tmdb:2", 10, 10),
         show("A", 2020, "tmdb:3", 10, 10, added=1), show("F", 2020, "tmdb:4", 10, 0)],
        {}, lambda v: "", lambda r, k: (None, False))
    for seed in range(20):
        cards = media_library.deal_tonight(rows, {}, "tv", random.Random(seed))
        assert len(cards) == 3 and all(c["row"]["title"] != "F" for c in cards)
        for c in cards:
            if c["pile"] == "Pick up where you left off":
                assert c["row"]["title"] == "W"
            if c["pile"] == "A fresh start":
                assert c["row"]["state"] == "not_started"


def test_tonight_routes_render_cards_and_deal_again(env):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        html, b = body(c, "/media/movies/tonight")
        tv_html, tv = body(c, "/media/tv/tonight")
    assert current(html, "sectabs") == ["Movies"] and current(html, "sectabs sub") == ["Tonight"]
    assert "Three for tonight" in b and 'href="/media/movies/tonight">Deal again' in b
    assert b.count('class="card-poster tcard"') == 2 and "Nothing else to deal" in b   # 2 unplayed films
    assert current(tv_html, "sectabs") == ["TV Shows"] and tv.count('class="card-poster tcard"') == 2


def test_arrived_this_week_prefers_the_timestamp_over_the_text():
    from datetime import datetime, timedelta, timezone
    from hub import media_library as ml
    now = datetime.now(timezone.utc)
    iso = lambda d: (now - timedelta(days=d)).isoformat()
    rows = [{"title": "Fresh", "kind": "movie", "when": "9 days ago", "at": iso(1)},   # at wins over text
            {"title": "Stale", "kind": "movie", "when": "yesterday", "at": iso(8)},
            {"title": "Old text", "kind": "movie", "when": "9 days ago"},               # no `at`: text rule
            {"title": "New text", "kind": "movie", "when": "3 days ago"},
            {"title": "Show", "kind": "season", "when": "yesterday", "at": iso(1)}]
    assert [r["title"] for r in ml.arrived_this_week(rows, "movie")] == ["Fresh", "New text"]


def test_whole_row_is_one_anchor_wrapping_the_title(env):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        _, m = body(c, "/media/movies?group=0&view=list")   # media-ux4: grid is the default; the row words live in List
        _, t = body(c, "/media/tv?group=0&view=list")
    for b, jf, title in ((m, "jtmdb-11", "Alpha Film"), (t, "jtmdb-21", "Echo Show")):
        anchors = re.findall(r'<a class="row" href="/media/item/%s">(.*?)</a>' % jf, b, re.S)
        assert len(anchors) == 1 and title in anchors[0] and "<a" not in anchors[0]
    assert 'title="Your rating' not in m and 'row-score score-none' in m  # no rating: "—", row still a link


ARRL = {"summary": "x", "arrived": [
    {"title": "In Library", "item_key": "tmdb:11", "kind": "movie", "poster": "radarr:1", "when": "today"},
    {"title": "Title Only", "item_key": "tmdb:77", "kind": "movie", "poster": "radarr:2", "when": "today"},
    {"title": "No Link", "item_key": "jf:abc", "kind": "movie", "poster": None, "when": "today"},
    {"title": "Show In Lib", "item_key": "tmdb:21", "kind": "season", "poster": "sonarr:1", "when": "today"},
    {"title": "Show Tvdb Only", "item_key": "tvdb:41", "kind": "season", "poster": "sonarr:2", "when": "today"},
    {"title": "Show Tmdb Only", "item_key": "tmdb:88", "kind": "season", "poster": "sonarr:3", "when": "today"}]}


def strip(b):
    # media-ux4: ends where the toolbar starts (the toolbar now holds the Grid / List links)
    return b.split('<div class="carousel">', 1)[1].split('<form class="toolbar"', 1)[0] if "New this week" in b else ""


def test_new_this_week_items_link_item_title_or_nothing(env):
    main = env(jellyfin=jelly(), arr=ARRL)
    with TestClient(main.app) as c:
        _, m = body(c, "/media/movies")
        _, t = body(c, "/media/tv")
    s = strip(m)
    assert re.search(r'<a class="card-poster" href="/media/item/jtmdb-11">.*?In Library', s, re.S)
    assert re.search(r'<a class="card-poster" href="/media/title/movie/77">.*?Title Only', s, re.S)
    assert '<div class="card-poster">' in s and "No Link" in s
    assert "href" not in s.split("No Link")[1].split("</div>")[0] and "<a" not in s.split('<div class="card-poster">', 1)[1].split("</div>")[0]
    s = strip(t)
    assert 'href="/media/item/jtmdb-21"' in s and 'href="/media/title/tv/88"' in s
    assert "Show Tvdb Only" in s and s.count("<a ") == 2
    assert 'class="row-meta">today' in s


def test_link_arrivals_is_pure():
    from hub import media_library as ml
    rows = [{"item_key": "tmdb:5"}, {"item_key": "tvdb:9"}, {"item_key": "tmdb:6"}]
    items = [{"item_key": "tmdb:5", "jf_id": "J5"}]
    got = ml.link_arrivals(rows, items, "movie", lambda jf: f"/media/item/{jf}")
    assert [r["href"] for r in got] == ["/media/item/J5", None, "/media/title/movie/6"]
    assert ml.link_arrivals(rows[2:], None, "tv", lambda jf: None)[0]["href"] == "/media/title/tv/6"


def test_link_arrivals_title_fallback():
    from hub import media_library as ml
    items = [{"title": "The Watchmen", "year": 2019, "item_key": "tmdb:1", "jf_id": "J1"},
             {"title": "Twin", "year": 1990, "item_key": "tmdb:2", "jf_id": "J2"},
             {"title": "Twin", "year": 2020, "item_key": "tmdb:3", "jf_id": "J3"}]
    rows = [{"title": "Watchmen · S01 · 9 episodes", "item_key": "tvdb:9"},
            {"title": "Twin · S01 · 2 episodes", "item_key": "tvdb:8", "year": 2020},
            {"title": "Twin · S01 · 2 episodes", "item_key": "tvdb:7"},
            {"title": "Nothing Here · S01", "item_key": "tvdb:6"}]
    got = ml.link_arrivals(rows, items, "tv", lambda jf: f"/media/item/{jf}")
    assert [r["href"] for r in got] == ["/media/item/J1", "/media/item/J3", "/media/item/J2", None]


# ---- merged from test_media_ux4_posters.py ----
# media-ux4 item 1 (2026-10-08): the TV Shows list, the To rate rows and every Diary list use the SAME poster size
# as the Movies list (media-ux2: `.listbox.libposters`, 55 px phone / 66 px from 640 px, fetched at h=240).


CSS = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")


def boxes(html):
    """{class attribute: [listbox inner html]} for every .listbox on the page."""
    out = {}
    for cls, inner in re.findall(r'<div (?:id="[^"]+" )?class="(listbox[^"]*)">(.*?)</div>\s*(?:</section>|$)', html, re.S):
        out.setdefault(cls, []).append(inner)
    return out


def posters(html):
    return re.findall(r'<img class="poster row-poster[^"]*" src="/img/[^"?]+\?h=(\d+)&amp;', html)


def test_tv_list_uses_the_movies_list_poster(frame_env):
    main = frame_env(jellyfin=jelly())
    with TestClient(main.app) as c:
        _, mv = body(c, "/media/movies?view=list")    # the List view (item 6 made Grid the default)
        _, tv = body(c, "/media/tv?view=list")
    for page, items in ((mv, MOVIES), (tv, SHOWS)):
        rows = "".join(boxes(page).get("listbox libposters", []))
        assert posters(rows) == ["240"] * len(items)


def test_to_rate_rows_use_the_movies_list_poster(rate_env):
    build, _ = rate_env
    with build() as client:
        hist = main_of(client.get("/media/history").text)
    inbox = hist.split(">To rate</h2>", 1)[1].split("</section>", 1)[0]
    assert '<div class="listbox libposters">' in inbox
    assert posters(inbox) and set(posters(inbox)) == {"240"}


def test_every_diary_list_uses_the_movies_list_poster(rate_env):
    build, _ = rate_env
    media_db.add_manual_watch("tmdb:1", "movie", "Heat", watched_on="2025-03-01")
    with build() as client:
        diary = main_of(client.get("/media/diary").text)
        logged = client.post("/media/log", headers=HX, data={
            "pick": '{"item_key": "tmdb:603", "kind": "movie", "title": "The Matrix", "year": 1999}',
            "watched_on": date.today().isoformat(), "place": "", "note": ""}).text
    otd = diary.split(">On this day</h2>", 1)[1].split("</section>", 1)[0]
    assert '<div class="listbox libposters">' in otd and set(posters(otd)) == {"240"}
    assert '<div id="diary-new" class="listbox libposters"></div>' in diary       # htmx-logged rows land here
    months = diary.split('<div id="diary-new"', 1)[1]
    assert months.count('<div class="listbox libposters">') >= 1 and '<div class="listbox">' not in months
    assert posters(months) and set(posters(months)) == {"240"}
    assert set(posters(logged)) == {"240"}                                          # the logged row partial too


def test_recently_watched_on_history_keeps_the_small_poster(rate_env):
    build, _ = rate_env
    with build() as client:
        hist = main_of(client.get("/media/history").text)
    recent = hist.split(">Recently watched</h2>", 1)[1].split("</section>", 1)[0]
    assert "libposters" not in recent and set(posters(recent)) == {"120"}


def test_a_picker_under_a_big_poster_row_lines_up_with_the_title():
    assert ".listbox.libposters .row .ratepick, .listbox.libposters .row .rated { padding-left: 69px; }" in CSS
    assert re.search(r"@media \(min-width: 640px\) \{ \.listbox\.libposters \.row \.ratepick, "
                     r"\.listbox\.libposters \.row \.rated \{ padding-left: 84px; \} \}", CSS)


def test_a_diary_rows_title_and_facts_stay_beside_the_bigger_poster():
    # a long facts line ("TV · S4 E7 · The Final Whistle · 2026-10-08 · Jellyfin") wrapped the whole body under the
    # 55 px poster on a phone; the body now shrinks from a zero basis like the Requests rows
    assert ".diaryrow .row-body { flex-basis: 0; }" in CSS and ".reqrow .row-body { flex-basis: 0; }" in CSS


# ---- merged from test_media_ux4_grid.py ----
# media-ux4 item 6 (2026-10-08): a grid view on /media/movies and /media/tv, the DEFAULT — poster cards at the Media home
# shelf card size (.card-poster, poster h=240) in responsive columns, each card poster · title · year · state word
# (Watched / Not watched / In progress); a Grid / List switch in the toolbar remembered per device in a cookie (the server
# draws the right view, no flash); grouping, search and sort work in both views.


COOKIE = "media_libview"


def grids(b):
    return re.findall(r'<div class="poster-grid libgrid">(.*?)</div>\s*</section>', b, re.S)


def cards(b):
    """[(href, poster h, title, meta words)] of every grid card."""
    out = []
    for g in grids(b):
        for href, h, title, meta in re.findall(
                r'<a class="card-poster" href="([^"]+)">\s*<span class="card-pic"><img class="poster [^"]*" src="/img/[^"?]+\?h=(\d+)&amp;'
                r'.*?<span class="row-title">([^<]+)</span>\s*<span class="row-meta">(.*?)</span>\s*</a>', g, re.S):
            out.append((href, h, title, re.sub(r"<[^>]+>", "", meta).strip()))
    return out


def seg(b):
    nav = b.split('<nav class="seg" aria-label="Layout">', 1)[1].split("</nav>", 1)[0]
    return re.findall(r'<a href="([^"]+)"( aria-current="true")?><svg class="ic"[^>]*>.*?</svg>(\w+)</a>', nav, re.S)


def test_grid_is_the_default_with_shelf_sized_cards_and_state_words(env):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        resp = c.get("/media/movies")
    b = resp.text.split("<main", 1)[1]
    assert COOKIE not in resp.headers.get("set-cookie", "")                 # the default sets nothing
    assert "listbox libposters" not in b and 'class="poster row-poster' not in b
    got = {title: (href, h, meta) for href, h, title, meta in cards(b)}
    assert set(got) == {m["title"] for m in MOVIES}
    assert got["Alpha Film"] == ("/media/item/jtmdb-11", "240", "2020 · Watched")
    assert got["Bravo Film"] == ("/media/item/jtmdb-12", "240", "2022 · Not watched")
    assert b.index(">Watched · 2<") < b.index(">Not yet watched · 2<")    # grouping kept
    assert 'width="160" height="240"' in b


def test_a_film_in_the_resume_list_is_in_progress(env):
    resume = [{"title": "Bravo Film", "kind": "movie", "remaining_text": "32 min left", "jf_id": "jtmdb-12"},
              {"title": "Charlie Film", "kind": "movie", "remaining_text": "Next episode", "jf_id": "jjf-13"}]
    main = env(jellyfin=jelly(up_next=resume), arr=ARRV)
    with TestClient(main.app) as c:
        _, b = body(c, "/media/movies")
    words = {title: meta for _, _, title, meta in cards(b)}
    assert words["Bravo Film"] == "2022 · In progress" and words["Charlie Film"] == "2018 · Not watched"
    assert '<span class="st-progress">In progress</span>' in b and '<span class="st-good">Watched</span>' in b


def test_tv_cards_say_watched_in_progress_not_watched(env):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        _, b = body(c, "/media/tv")
    words = {title: meta for _, _, title, meta in cards(b)}
    assert words == {"Echo Show": "2019 · In progress", "Foxtrot Show": "2021 · Not watched", "Golf Show": "2015 · Watched"}
    assert b.index(">Watching · 1<") < b.index(">Not started · 1<") < b.index(">Finished · 1<")


def test_switch_links_keep_search_sort_and_grouping(env):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        _, b = body(c, "/media/movies?q=film&sort=title&group=0")
    links = seg(b)
    assert [(label, bool(cur)) for _, cur, label in links] == [("Grid", True), ("List", False)]
    assert links[0][0] == "/media/movies?q=film&amp;sort=title&amp;group=0&amp;view=grid"
    assert links[1][0] == "/media/movies?q=film&amp;sort=title&amp;group=0&amp;view=list"
    assert [t for _, _, t, _ in cards(b)] == ["Alpha Film", "Bravo Film", "Charlie Film", "Delta Film"]   # sorted A-Z


def test_list_choice_is_remembered_in_a_cookie_and_drawn_server_side(env):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        r = c.get("/media/movies?view=list")
        cookie = r.headers.get("set-cookie", "")
        again = c.get("/media/tv").text.split("<main", 1)[1]                # no query: the cookie decides
        back = c.get("/media/movies?view=grid")
        after = c.get("/media/movies").text.split("<main", 1)[1]
    assert f"{COOKIE}=list" in cookie and "Path=/media" in cookie and "Max-Age=31536000" in cookie and "SameSite=lax" in cookie
    lst = r.text.split("<main", 1)[1]
    assert "listbox libposters" in lst and not grids(lst) and [cur for _, cur, _ in seg(lst)] == ["", ' aria-current="true"']
    assert "listbox libposters" in again and not grids(again)
    assert f"{COOKIE}=grid" in back.headers.get("set-cookie", "") and grids(after)


def test_junk_view_is_ignored(env):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        c.cookies.set(COOKIE, "bogus")
        r = c.get("/media/movies?view=mosaic")
    assert COOKIE not in r.headers.get("set-cookie", "") and grids(r.text)


def test_search_and_empty_state_in_grid(env):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        _, b = body(c, "/media/movies?q=DELTA&group=0")
        empty = body(c, "/media/movies?q=zzz")[1]
    assert [t for _, _, t, _ in cards(b)] == ["Delta Film"] and ">Watched ·" not in b
    assert "Nothing matches that search" in empty


def test_cards_are_whole_links_with_the_score_badge(env):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        media_db.set_rating("tmdb:14", 10, "movie", "Delta Film", year=2024)
        _, b = body(c, "/media/movies?group=0")
    card = re.search(r'<a class="card-poster" href="/media/item/jtmdb-14">(.*?)</a>', b, re.S).group(1)
    assert "<a" not in card and 'class="poster-score score-9 gold-text-glow"' in card and ">10<" in card
    assert "gold-glow" in card


def test_her_view_without_her_list_shows_no_state_words(env):
    main = env(jellyfin=jelly(her={"up_next": [], "history": {}, "movies": None, "shows": None}), arr=ARRV)
    with TestClient(main.app) as c:
        _, b = body(c, "/media/movies?owner_view=her")
    words = [meta for _, _, _, meta in cards(b)]
    assert words and all("watched" not in w.lower() and "progress" not in w.lower() for w in words)
    main = env(jellyfin=jelly(her={"up_next": [], "history": {}, "movies": HER_MOVIES, "shows": []}), arr=ARRV)
    with TestClient(main.app) as c:
        _, b = body(c, "/media/movies?owner_view=her")
    assert {t: m for _, _, t, m in cards(b)}["Bravo Film"] == "2022 · Watched"


def test_card_state_is_pure():
    cs = media_library.card_state
    assert cs({"kind": "movie", "played": True, "jf_id": "a"}, {"a"})["word"] == "Watched"
    assert cs({"kind": "movie", "played": False, "jf_id": "a"}, {"a"}) == {"word": "In progress", "cls": "st-progress"}
    assert cs({"kind": "movie", "played": False, "jf_id": "b"}, {"a"}) == {"word": "Not watched", "cls": "st-todo"}
    assert cs({"kind": "tv", "played": False, "state": "watching"})["word"] == "In progress"
    assert cs({"kind": "tv", "played": True, "state": "finished"})["word"] == "Watched"
    assert cs({"kind": "movie", "played": None}) is None


def test_grid_css_matches_the_shelf_card_size_and_the_switch_is_a_segmented_control():
    assert ".poster-grid.libgrid { grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: 20px 12px; }" in CSS
    assert "@media (min-width: 640px) { .poster-grid.libgrid { grid-template-columns: repeat(auto-fill, minmax(136px, 1fr)); } }" in CSS
    assert ".carousel > * { flex: 0 0 104px; width: 104px;" in CSS and "flex-basis: 144px; width: 144px;" in CSS
    assert ".seg a[aria-current] { background: var(--pill-on); color: var(--text-1); }" in CSS


def test_tv_shows_list_counts_match_both_views(env):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        _, g = body(c, "/media/tv")
        _, lst = body(c, "/media/tv?view=list")
    assert len(cards(g)) == len(SHOWS) and lst.count('class="poster row-poster') == len(SHOWS)
    assert "3 shows · 1 watching · 1 not started · 1 finished" in g and "3 shows" in lst
