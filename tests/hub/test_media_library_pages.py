"""F3b (2026-10-06) - Movies + TV Shows hub pages, Tonight deal, By-year kind filter.
Snapshots are written here with write_envelope; the committed sample is never relied on."""
import random
import re
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from hub import media_db, media_library
from tests.hub.test_media_frame import env, current  # noqa: F401  (env fixture)
from tests.hub.test_media_shelves import JELLY, LINK

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
    rows = main_html.split("</form>", 1)[1]
    return re.findall(r'class="uptitle">([^<(\n]+?)\s*(?:\(|\n|<)', rows)


def test_movies_page_in_frame_with_head_groups_and_words(env):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        html, b = body(c, "/media/movies")
    assert current(html, "sectabs") == ["Movies"] and current(html, "sectabs sub") == ["My films"]
    assert "4 films · 2 watched · 2 to watch" in b
    assert b.index(">Watched · 2<") < b.index(">Not yet watched · 2<")
    assert "1 h 52 m" in b and "Watched 3 days ago" in b and "Not watched" in b and "45 m" in b
    assert "7.8" in b and "TMDB" in b and "Drama, Crime" in b
    assert 'class="poster sm' in b


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
        b = body(c, "/media/movies")[1]
        assert 'class="chip score' in b and "Your rating: 9 out of 10" in b


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
    assert ">New this week</div>" in m and "Fresh Movie" in m and "yesterday" in m and "Old Movie" not in m
    assert "New Series" in t and "Fresh Movie" not in t
    main = env(jellyfin=jelly(), arr={"summary": "x", "arrived": []})
    with TestClient(main.app) as c:
        assert "New this week" not in body(c, "/media/movies")[1]


def test_tv_page_groups_words_and_head(env):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        html, b = body(c, "/media/tv")
    assert current(html, "sectabs") == ["TV Shows"] and current(html, "sectabs sub") == ["My shows"]
    assert "3 shows · 1 watching · 1 not started · 1 finished" in b
    assert b.index(">Watching · 1<") < b.index(">Not started · 1<") < b.index(">Finished · 1<")
    assert "Continuing" in b and "26 episodes · 6 to watch" in b and "8 episodes · All watched" in b
    assert "Last watched yesterday" in b and 'href="/media/item/jtmdb-21"' in b


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
    assert "4 films<" in b and "watched" not in b.split("libline")[1].split("</div>")[0]
    assert "Not watched" not in b and 'class="chip score' not in b and "Grouped" not in b
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
    assert b.count('class="pgitem tcard"') == 2 and "Nothing else to deal" in b   # 2 unplayed films
    assert current(tv_html, "sectabs") == ["TV Shows"] and tv.count('class="pgitem tcard"') == 2


# ---- By year kind filter ----

def seed_years():
    media_db.set_rating("m1", 8, "movie", "Film A", year=2020)
    media_db.set_rating("m2", 6, "movie", "Film B", year=2020)
    media_db.set_rating("t1", 9, "tv", "Show A", year=2020)
    media_db.set_rating("t2", 7, "tv", "Show B", year=2019)
    media_db.place(2020, "t1")
    media_db.place(2020, "m1")


def test_years_db_kind_filter(env):
    env(jellyfin=jelly(), arr=ARRV)
    seed_years()
    allr = {y["year"]: y for y in media_db.years_overview()}
    assert allr[2020]["ranked_count"] == 2 and allr[2020]["unranked_count"] == 1
    mv = {y["year"]: y for y in media_db.years_overview("movie")}
    assert set(mv) == {2020} and mv[2020]["ranked_count"] == 1 and mv[2020]["unranked_count"] == 1
    assert mv[2020]["top"]["title"] == "Film A"
    tv = {y["year"]: y for y in media_db.years_overview(kind="tv")}
    assert set(tv) == {2019, 2020} and tv[2020]["top"]["title"] == "Show A" and tv[2020]["unranked_count"] == 0
    yl = media_db.year_list(2020, "tv")
    assert [r["title"] for r in yl["ranked"]] == ["Show A"] and yl["unranked"] == []
    yl = media_db.year_list(2020, "movie")
    assert [r["title"] for r in yl["ranked"]] == ["Film A"] and [r["title"] for r in yl["unranked"]] == ["Film B"]
    assert len(media_db.year_list(2020)["ranked"]) == 2
    assert media_db.years_overview("junk") == media_db.years_overview()


def test_years_routes_kind_filter(env):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        seed_years()
        _, mv = body(c, "/media/years?kind=movie")
        _, tv = body(c, "/media/years?kind=tv")
        _, y_mv = body(c, "/media/years/2020?kind=movie")
        _, y_tv = body(c, "/media/years/2020?kind=tv")
        _, y_all = body(c, "/media/years/2020")
    assert "#1 — Film A" in mv and "2019" not in mv and 'href="/media/years/2020?kind=movie"' in mv
    assert "#1 — Show A" in tv and "2019" in tv
    assert "Film A" in y_mv and "Show A" not in y_mv and "Film B" in y_mv
    assert "Show A" in y_tv and "Film A" not in y_tv
    assert "Film A" in y_all and "Show A" in y_all


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
        _, m = body(c, "/media/movies?group=0")
        _, t = body(c, "/media/tv?group=0")
    for b, jf, title in ((m, "jtmdb-11", "Alpha Film"), (t, "jtmdb-21", "Echo Show")):
        anchors = re.findall(r'<a class="uprow[^"]*librow[^"]*" href="/media/item/%s">(.*?)</a>' % jf, b, re.S)
        assert len(anchors) == 1 and title in anchors[0] and "<a" not in anchors[0]
        assert "reqrow" in b
    assert 'class="chip score' not in m  # no rating set: chip absent, row still a link


ARRL = {"summary": "x", "arrived": [
    {"title": "In Library", "item_key": "tmdb:11", "kind": "movie", "poster": "radarr:1", "when": "today"},
    {"title": "Title Only", "item_key": "tmdb:77", "kind": "movie", "poster": "radarr:2", "when": "today"},
    {"title": "No Link", "item_key": "jf:abc", "kind": "movie", "poster": None, "when": "today"},
    {"title": "Show In Lib", "item_key": "tmdb:21", "kind": "season", "poster": "sonarr:1", "when": "today"},
    {"title": "Show Tvdb Only", "item_key": "tvdb:41", "kind": "season", "poster": "sonarr:2", "when": "today"},
    {"title": "Show Tmdb Only", "item_key": "tmdb:88", "kind": "season", "poster": "sonarr:3", "when": "today"}]}


def strip(b):
    return b.split('<div class="shelf-row">', 1)[1].split("</form>", 1)[0] if "New this week" in b else ""


def test_new_this_week_items_link_item_title_or_nothing(env):
    main = env(jellyfin=jelly(), arr=ARRL)
    with TestClient(main.app) as c:
        _, m = body(c, "/media/movies")
        _, t = body(c, "/media/tv")
    s = strip(m)
    assert re.search(r'<a class="shelf-item" href="/media/item/jtmdb-11">.*?In Library', s, re.S)
    assert re.search(r'<a class="shelf-item" href="/media/title/movie/77">.*?Title Only', s, re.S)
    assert re.search(r'<div class="shelf-item">\s*<[^>]*>\s*(?:<[^>]*>\s*)*<span class="pgtitle">No Link', s) or \
        ('<div class="shelf-item">' in s and "No Link" in s)
    assert "href" not in s.split("No Link")[1].split("</div>")[0] and "<a" not in s.split('<div class="shelf-item">', 1)[1].split("</div>")[0]
    s = strip(t)
    assert 'href="/media/item/jtmdb-21"' in s and 'href="/media/title/tv/88"' in s
    assert "Show Tvdb Only" in s and s.count("<a ") == 2
    assert 'class="pgsub">today' in s


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
