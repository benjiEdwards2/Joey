"""F6 (2026-10-06) - Watchlist: per-owner storage, add/remove routes, the Movies / TV Shows
Watchlist pages (status words, sorts, auto-leave), title-page button and Discover "+".
Nothing touches the network; snapshots are written with write_envelope."""
import re
from datetime import date

import pytest
from fastapi.testclient import TestClient

from hub import media_db, media_watchlist_db as wl
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.test_media_discover import FORM, HX, env as discover_env  # noqa: F401
from tests.hub.test_media_frame import current, env  # noqa: F401  (frame env fixture)
from tests.hub.test_media_library_pages import MOVIES, SHOWS, jelly

REQS = {"summary": "x", "requests": [
    {"tmdb_id": 101, "kind": "movie", "status_text": "Pending", "item_key": "tmdb:101"},
    {"tmdb_id": 102, "kind": "movie", "status_text": "Approved", "item_key": "tmdb:102"},
    {"tmdb_id": 103, "kind": "movie", "status_text": "Partly available", "item_key": "tmdb:103"},
    {"tmdb_id": 104, "kind": "movie", "status_text": "Declined", "item_key": "tmdb:104"},
    {"tmdb_id": 22, "kind": "movie", "status_text": "Pending", "item_key": "tmdb:22"},  # wrong kind for the show
]}


def put(tmdb, kind="movie", title="T", year=2020, poster=None, owner="you"):
    wl.add(owner, {"tmdb_id": tmdb, "kind": kind, "title": title, "year": year, "poster": poster})


def form(**f):
    return "&".join(f"{k}={v}" for k, v in f.items())


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))


# ---- storage ----

def test_add_remove_contains_and_owner_isolation(db):
    put(1, title="One")
    put(1, title="One again")                      # idempotent: no duplicate row
    put(2, kind="tv", title="Two", owner="her")
    assert [r["item_key"] for r in wl.rows("you")] == ["tmdb:1"] and len(wl.rows("you")) == 1
    assert wl.contains("you", ["tmdb:1", "tmdb:2"]) == {"tmdb:1"}
    assert wl.contains("her", ["tmdb:1", "tmdb:2"]) == {"tmdb:2"}
    assert [r["title"] for r in wl.rows("her", "tv")] == ["Two"] and wl.rows("her", "movie") == []
    wl.remove("her", "tmdb:1")                     # not hers: yours stays
    assert wl.contains("you", ["tmdb:1"]) == {"tmdb:1"}
    wl.remove("you", "tmdb:1")
    assert wl.rows("you") == [] and wl.contains("you", []) == set()


def test_reads_never_create_the_db_file(db):
    assert wl.rows("you") == [] and wl.contains("you", ["tmdb:1"]) == set()
    assert not media_db.db_path().exists()


def test_count_not_on_server(db):
    put(1); put(2); put(3, kind="tv")
    assert wl.count_not_on_server("you", "movie", {"tmdb:1"}) == 1
    assert wl.count_not_on_server("you", "tv", set()) == 1


def test_prune_played_removes_watched_and_reports(db):
    put(1); put(2); put(3)
    assert wl.prune_played("you", {"tmdb:1", "tmdb:3", "tmdb:99"}) == 2
    assert [r["item_key"] for r in wl.rows("you")] == ["tmdb:2"]
    assert wl.prune_played("you", set()) == 0


def test_sorts_and_deterministic_shuffle():
    rows = [{"item_key": f"tmdb:{i}", "title": t, "year": y, "added_at": a} for i, (t, y, a) in enumerate(
        [("Bravo", 2020, "2026-01-02"), ("alpha", 2024, "2026-01-03"), ("Charlie", None, "2026-01-01")])]
    names = lambda s: [r["title"] for r in wl.sort_rows(rows, s)]
    assert names("title") == ["alpha", "Bravo", "Charlie"]
    assert names("newest") == ["alpha", "Bravo", "Charlie"]
    assert names("oldest") == ["Charlie", "Bravo", "alpha"] or names("oldest") == ["Bravo", "alpha", "Charlie"]
    assert names("added") == ["alpha", "Bravo", "Charlie"]
    many = [{"item_key": f"tmdb:{i}", "title": str(i), "year": 2000, "added_at": "x"} for i in range(30)]
    day = date(2026, 10, 6)
    a = [r["item_key"] for r in wl.sort_rows(many, "shuffle", "you", "movie", day)]
    assert a == [r["item_key"] for r in wl.sort_rows(many, "shuffle", "you", "movie", day)]
    assert a != [r["item_key"] for r in wl.sort_rows(many, "shuffle", "you", "movie", date(2026, 10, 7))]
    assert a != sorted(a)


def test_status_words():
    words = wl.request_words(REQS["requests"])
    row = lambda i, kind="movie": {"item_key": f"tmdb:{i}", "kind": kind, "tmdb_id": i}
    on = {"tmdb:11"}
    assert wl.status_word(row(11), on, words) == "On disk"
    assert wl.status_word(row(101), on, words) == "Requested"
    assert wl.status_word(row(102), on, words) == "Processing"
    assert wl.status_word(row(103), on, words) == "Partly available"
    assert wl.status_word(row(104), on, words) == "Not on server"        # declined
    assert wl.status_word(row(22, "tv"), on, words) == "Not on server"   # request was for a film


# ---- routes ----

def test_add_remove_routes_htmx_and_plain(env):
    main = env(jellyfin=jelly(), jellyseerr=REQS)
    body = form(tmdb_id=555, kind="movie", title="New+Film", year=2021, poster="")
    with TestClient(main.app) as c:
        hx = c.post("/media/watchlist/add", content=body, headers={**HX, **FORM})
        assert "On your watchlist" in hx.text and 'id="wl-movie-555"' in hx.text
        assert wl.contains("you", ["tmdb:555"]) == {"tmdb:555"}
        gone = c.post("/media/watchlist/remove", content=body + "&item_key=tmdb:555", headers={**HX, **FORM})
        assert 'aria-label="Add to watchlist"' in gone.text and wl.rows("you") == []
        plain = c.post("/media/watchlist/add", content=body, headers=FORM, follow_redirects=False)
        assert plain.status_code == 303 and plain.headers["location"] == "/media/movies/watchlist"
        back = c.post("/media/watchlist/remove", content=body, follow_redirects=False,
                      headers={**FORM, "Referer": "http://testserver/media/tv/watchlist?sort=title"})
        assert back.headers["location"] == "/media/tv/watchlist?sort=title"
        away = c.post("/media/watchlist/add", content=body, follow_redirects=False,
                      headers={**FORM, "Referer": "https://evil.example/x"})
        assert away.headers["location"] == "/media/movies/watchlist"
        assert c.post("/media/watchlist/add", content=form(tmdb_id="x", kind="movie", title="T"),
                      headers=FORM).status_code == 422


def test_foreign_origin_is_refused(env):
    main = env(jellyfin=jelly(), jellyseerr=REQS)
    with TestClient(main.app) as c:
        for path in ("add", "remove"):
            r = c.post(f"/media/watchlist/{path}", content=form(tmdb_id=1, kind="movie", title="T"),
                       headers={**FORM, "Origin": "https://evil.example"})
            assert r.status_code == 403
    assert wl.rows("you") == []


# ---- pages ----

def page(c, path):
    html = c.get(path).text
    return html, html.split("<main", 1)[1]


def test_movies_page_frame_status_words_and_head(env):
    main = env(jellyfin=jelly(), jellyseerr=REQS)
    put(12, title="Bravo Film", year=2022)   # on disk, unplayed
    put(101, title="Req Film")
    put(102, title="Proc Film")
    put(103, title="Part Film")
    put(999, title="Nowhere Film")
    with TestClient(main.app) as c:
        html, b = page(c, "/media/movies/watchlist")
    assert current(html, "sectabs sectabs-page") == ["Movies"]
    assert current(html, "sectabs sub") == ["My films"]   # nav-tidy (2026-10-13): no Watchlist tab; My films holds it
    assert "5 on your watchlist · 4 not on the server" in b
    for word in ("On disk", "Requested", "Processing", "Partly available", "Not on server"):
        assert f">{word}</span>" in b
    assert b.count(">Request</a>") == 1 and 'class="poster-grid"' in b and "h=300" in b
    assert 'class="btn-mini"' in b and 'href="/media/title/movie/999"' in b


def test_tv_page_and_empty_state(env):
    main = env(jellyfin=jelly(), jellyseerr=REQS)
    with TestClient(main.app) as c:
        html, b = page(c, "/media/tv/watchlist")
        assert current(html, "sectabs sectabs-page") == ["TV shows"] and current(html, "sectabs sub") == ["My shows"]
        assert '<p class="empty">Nothing on the watchlist.</p>' in b
        put(22, kind="tv", title="Foxtrot Show")     # on the server list; wrong-kind request ignored
        _, b = page(c, "/media/tv/watchlist")
    assert "1 on your watchlist · 0 not on the server" in b and ">On disk</span>" in b


def test_sorts_on_the_page(env):
    main = env(jellyfin=jelly(), jellyseerr=REQS)
    put(901, title="Bravo", year=2010); put(902, title="Alpha", year=2024); put(903, title="Charlie", year=2000)
    order = lambda c, s: re.findall(r'class="row-title">([^<]+)', page(c, f"/media/movies/watchlist?sort={s}")[1])
    with TestClient(main.app) as c:
        assert order(c, "title") == ["Alpha", "Bravo", "Charlie"]
        assert order(c, "newest") == ["Alpha", "Bravo", "Charlie"]
        assert order(c, "oldest") == ["Charlie", "Bravo", "Alpha"]
        assert order(c, "shuffle") == order(c, "shuffle")
        assert sorted(order(c, "bogus")) == ["Alpha", "Bravo", "Charlie"]


def test_watched_titles_leave_the_list_and_it_says_so(env):
    main = env(jellyfin=jelly(), jellyseerr=REQS)
    put(11, title="Alpha Film")      # played in the library: leaves
    put(12, title="Bravo Film")      # unplayed: stays
    with TestClient(main.app) as c:
        _, b = page(c, "/media/movies/watchlist")
        assert "1 watched title left the list" in b and "Alpha Film" not in b and "Bravo Film" in b
        _, b2 = page(c, "/media/movies/watchlist")
        assert "left the list" not in b2
    assert wl.contains("you", ["tmdb:11", "tmdb:12"]) == {"tmdb:12"}


def test_finished_show_leaves_but_a_started_one_stays(env):
    main = env(jellyfin=jelly(), jellyseerr=REQS)
    put(23, kind="tv", title="Golf Show")     # fully watched
    put(21, kind="tv", title="Echo Show")     # 6 unplayed
    with TestClient(main.app) as c:
        _, b = page(c, "/media/tv/watchlist")
    assert "Golf Show" not in b and "Echo Show" in b and "1 watched title left the list" in b


def test_watchlist_left_the_nav_but_its_pages_still_serve(env):
    """nav-tidy (2026-10-13, B.): no Watchlist tab (so no "to get" count) on Movies or TV shows; the pages, routes and
    the title-page button stay, reachable by URL."""
    main = env(jellyfin=jelly(), jellyseerr=REQS)
    put(12); put(555); put(556)
    with TestClient(main.app) as c:
        for list_path, wl_path in (("/media/movies", "/media/movies/watchlist"), ("/media/tv", "/media/tv/watchlist")):
            sub = re.search(r'<nav class="sectabs sub".*?</nav>', c.get(list_path).text, re.S).group(0)
            assert "Watchlist" not in sub and wl_path not in sub and "to get" not in sub
            assert c.get(wl_path).status_code == 200


# ---- title page + Discover ----

def test_title_page_button_states(discover_env):
    client, fake = discover_env()
    with client:
        off = main_of(client.get("/media/title/movie/603").text)
        assert 'aria-label="Add to watchlist"' in off and "On your watchlist" not in off
        client.post("/media/watchlist/add", content=form(tmdb_id=603, kind="movie", title="The+Matrix"),
                    headers={**HX, **FORM})
        on = main_of(client.get("/media/title/movie/603").text)
    assert "On your watchlist" in on and 'aria-label="Add to watchlist"' not in on and 'aria-pressed="true"' in on
    assert on.index('id="wl-movie-603"') < on.index('id="request-block"')   # F10 button row: Watchlist, then Request


def test_discover_plus_hidden_when_already_on_the_list(discover_env):
    client, fake = discover_env()
    with client:
        before = main_of(client.get("/media/discover").text)
        assert 'class="btn-mini"' in before and 'name="tmdb_id" value="1"' in before
        client.post("/media/watchlist/add", content=form(tmdb_id=1, kind="movie", title="Film+Five"),
                    headers={**HX, **FORM})
        after = main_of(client.get("/media/discover").text)
    assert 'name="tmdb_id" value="1"' not in after and 'name="tmdb_id" value="2"' in after
    assert "Film Five" in after


def test_discover_search_partial_has_plus(discover_env):
    client, fake = discover_env()
    fake.search_results = {"results": [{"id": 5, "mediaType": "movie", "title": "Found", "releaseDate": "2020-01-01"}]}
    with client:
        html = client.get("/media/discover/search?q=found").text
    assert 'name="tmdb_id" value="5"' in html and 'hx-post="/media/watchlist/add"' in html


def test_watchlist_card_is_one_whole_card_link(env):
    """B., 2026-10-06: every row/card is selectable as a whole. Poster + title sit inside ONE
    a.rowlink (stretched over the card); the x form and Request link stay outside it, on top."""
    main = env(jellyfin=jelly(), jellyseerr=REQS)
    put(999, title="Nowhere Film")
    with TestClient(main.app) as c:
        _, b = page(c, "/media/movies/watchlist")
    cell = re.search(r'<div class="card-cell">.*?<span class="st-', b, re.S).group(0)
    link = re.search(r'<a class="rowlink" href="/media/title/movie/999">(.*?)</a>', cell, re.S)
    assert link and '<img class="poster' in link.group(1) and '<span class="row-title">Nowhere Film</span>' in link.group(1)
    assert "<form" not in link.group(1) and cell.count("<a ") == 1 and "<form" in cell
    assert 'class="row-title" href' not in b
