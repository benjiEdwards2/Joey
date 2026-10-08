"""media-ux4 item 6 (2026-10-08): a grid view on /media/movies and /media/tv, the DEFAULT — poster cards at the Media home
shelf card size (.card-poster, poster h=240) in responsive columns, each card poster · title · year · state word
(Watched / Not watched / In progress); a Grid / List switch in the toolbar remembered per device in a cookie (the server
draws the right view, no flash); grouping, search and sort work in both views."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from hub import media_db, media_library
from tests.hub.test_media_frame import env  # noqa: F401  (env fixture)
from tests.hub.test_media_library_pages import ARRV, HER_MOVIES, MOVIES, SHOWS, body, jelly

CSS = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
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
    assert ".carousel > * { flex: 0 0 116px; width: 116px;" in CSS and "flex-basis: 144px; width: 144px;" in CSS
    assert ".seg a[aria-current] { background: var(--pill-on); color: var(--text-1); }" in CSS


def test_tv_shows_list_counts_match_both_views(env):
    main = env(jellyfin=jelly(), arr=ARRV)
    with TestClient(main.app) as c:
        _, g = body(c, "/media/tv")
        _, lst = body(c, "/media/tv?view=list")
    assert len(cards(g)) == len(SHOWS) and lst.count('class="poster row-poster') == len(SHOWS)
    assert "3 shows · 1 watching · 1 not started · 1 finished" in g and "3 shows" in lst
