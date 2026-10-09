"""F1 (2026-10-06) — the Media app frame: six sections, per-section sub-tabs.
Shell (restyle Phase 2, 2026-10-06): Media pages sit inside the Joey shell (top bar + phone tab bar);
"Return to Joey" is gone and the sections are section tabs (.sectabs) on the page header.
Bar and tabs are asserted on the whole body (they are chrome, not content)."""
import importlib
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from hub import media_nav
from tests.hub.helpers import ARR, JELLY, make_area, make_tile, shelf_area, write_envelope, write_registry


@pytest.fixture()
def env(tmp_path, monkeypatch):
    area = shelf_area()
    area["tiles"].append(make_tile("disc-t", snapshot="jellyseerr", stale_after_minutes=180, detail="/media/discover"))
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, area, make_area("beta"))))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.delenv("JELLYSEERR_URL", raising=False)   # discover/title stay "Not connected": no network
    monkeypatch.delenv("JELLYSEERR_API_KEY", raising=False)

    def build(**data):
        for cid, d in data.items():
            write_envelope(tmp_path / "snaps", cid, age_minutes=1, data=d)
        import hub.main
        importlib.reload(hub.main)
        return hub.main
    return build


# route -> (section id, sub-tab label that is current or None)
ROUTES = {
    "/a/alpha": ("home", None),
    "/media/movies": ("movies", "My films"),
    "/media/movies/tonight": ("movies", "Tonight"),
    "/media/tv": ("tv", "My shows"),
    "/media/tv/tonight": ("tv", "Tonight"),
    # media-ux2 (2026-10-08): /media/years has no tab of its own now - see test_media_nav.py
    "/media/diary": ("diary", "Diary"),
    "/media/history": ("diary", "To Rate"),
    "/media/playing": ("server", "Live"),
    "/media/library": ("server", "Library"),
    "/media/requests": ("server", "Requests"),
    "/media/apps": ("server", "Health"),
    "/media/discover": ("discover", "Discover"),   # Follow (2026-10-07): Discover / Following sub-tabs
    "/media/following": ("discover", "Following"),
    "/media/title/movie/1": ("discover", None),
}
LABELS = {"home": "Home", "movies": "Movies", "tv": "TV Shows", "diary": "Diary", "server": "Server", "discover": "Discover"}


def nav_html(html, cls):
    return re.search(rf'<nav class="{cls}".*?</nav>', html, re.S).group(0)


def current(html, cls):
    return re.findall(r'aria-current="page">([^<]*?)(?: <span|</a>)', nav_html(html, cls))


@pytest.mark.parametrize("route", list(ROUTES))
def test_media_pages_use_the_frame(env, route):
    main = env(jellyfin=JELLY, arr=ARR)
    section, tab = ROUTES[route]
    with TestClient(main.app) as client:
        r = client.get(route)
    html = r.text
    assert r.status_code == 200
    assert 'class="topbar"' in html and 'class="rail"' not in html   # Joey shell around Media pages
    tabs_bar = html.split('<nav class="tabbar"', 1)[1]                 # Media phone bar (2026-10-07): Media's six
    assert "/a/beta" not in tabs_bar and "<span>Diary</span>" in tabs_bar and "mediatabs" not in html
    assert "Return to Joey" not in html and "returnjoey" not in html
    sections = nav_html(html, "sectabs")
    for label in LABELS.values():
        assert f">{label}" in sections
    assert sections.count('aria-current="page"') == 1
    assert current(html, "sectabs") == [LABELS[section]]
    if tab:
        assert current(html, "sectabs sub") == [tab]
    else:
        assert 'class="sectabs sub"' not in html
    assert 'class="status"' not in html


def test_six_sections_and_home_resolves_via_registry(env):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as client:
        html = client.get("/media/movies").text
    assert len(re.findall(r"<a href=", nav_html(html, "sectabs"))) == 6
    assert '<a href="/a/alpha">Home</a>' in html


@pytest.mark.parametrize("route", ["/", "/weather", "/a/beta"])
def test_non_media_pages_have_the_shell_and_no_media_tabs(env, route):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as client:
        html = client.get(route).text
    assert 'class="topbar"' in html and 'aria-label="Sections (phone)"' in html and "sectabs" not in html
    assert "mediabar" not in html and "returnjoey" not in html


def test_waiting_counts_are_text_and_absent_at_zero(env):
    main = env(jellyfin={**JELLY, "history": {"recent": []}}, arr=ARR)
    from hub import media_db
    with TestClient(main.app) as client:
        assert 'class="waitcount"' not in client.get("/media/movies").text
        media_db.set_rating("m2", 8, "movie", "Rated One", year=2024)
        media_db.set_rating("m3", 7, "movie", "Old One")
        html = client.get("/media/movies").text
    bar = nav_html(html, "sectabs")
    assert "waitcount" not in bar.split("Diary")[1].split("Server")[0]   # nothing to rate: Diary has no count
    assert re.search(r'Movies <span class="waitcount">\d+<span class="vh"> to place</span></span>', bar)
    assert re.search(r'TV Shows <span class="waitcount">\d+<span class="vh"> to place</span></span>', bar)


def test_switcher_links_to_current_media_path(env):
    """2026-10-06: the switcher is gone (the signed-in user picks the view); locally the
    owner view still follows the query on a Media path and is remembered in the cookie."""
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as client:
        html = client.get("/media/diary?owner_view=her").text
        assert client.cookies.get("owner_view") == "her"
        years = client.get("/media/years?kind=tv").text
    assert 'class="switcher"' not in html and "owner_view=" not in html
    assert 'class="switcher"' not in years and "owner_view=" not in years


def test_library_pages_quiet_without_lists_and_years_heading(env):
    main = env(jellyfin=JELLY, arr=ARR)   # the fixture snapshot carries no movies/shows arrays
    with TestClient(main.app) as client:
        for path in ("/media/movies", "/media/movies/tonight", "/media/tv", "/media/tv/tonight"):
            assert "Library list not available yet" in client.get(path).text
            assert "Coming in the next phase" not in client.get(path).text
        def body(p):
            return client.get(p).text.split("<main", 1)[1]
        assert "By year · films" in body("/media/years?kind=movie")
        assert "By year · TV" in body("/media/years?kind=tv")
        assert "By year · " not in body("/media/years")


def test_home_shelf_set_is_trimmed(env):
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as client:
        html = client.get("/a/alpha").text.split("<main", 1)[1]
    titles = re.findall(r'<h2 class="seclabel">([^<]*)', html)   # restyle Phase 3: "LABEL · count"
    assert titles == ["Continue watching", "Recently added", "Downloading"]   # media-ux2: This week + Recently watched gone
    assert "appstrip" not in html and "Discover &amp; Search" not in html


def test_active_section_unit():
    def s(*a, **k):
        return (media_nav.active_section(*a, **k) or {}).get("id")
    assert s("/media/movies") == "movies" and s("/media/movies/tonight") == "movies"
    assert s("/media/tv/tonight") == "tv"
    assert s("/media/years", "kind=tv") == "tv" and s("/media/years", {"kind": "movie"}) == "movies"
    assert s("/media/years") == "movies" and s("/media/years", "kind=junk") == "movies"
    assert s("/media/years/2024", "kind=tv") == "tv"
    assert s("/media/history") == "diary" and s("/media/diary") == "diary"
    assert s("/media/apps") == "server" and s("/media/requests") == "server"
    assert s("/media/title/tv/9") == "discover" and s("/media/discover/search") == "discover"
    assert s("/a/media", home_href="/a/media") == "home"
    assert s("/weather") is None and s("/media/moviesx") is None


def test_nav_context_without_a_shelves_area():
    req = SimpleNamespace(url=SimpleNamespace(path="/media/tv", query=""))
    reg = SimpleNamespace(areas=[SimpleNamespace(layout="grid", id="x")])
    ctx = media_nav.nav_context(req, reg, {"to_rate": 0, "to_place": 3})
    assert ctx["home_href"] == "/" and "accent" not in ctx
    assert [s["count"] for s in ctx["sections"]] == [0, 3, 3, 0, 0, 0]
    assert [t["on"] for t in ctx["tabs"]] == [True, False, False, False, False]   # media-ux2: By year removed; media-ux4: + To rate; Awards (2026-10-08): + Awards


# ---- review fixes (2026-10-06) ----

def test_switcher_keeps_the_query_string(env):
    from hub import media_db
    main = env(jellyfin=JELLY, arr=ARR)
    media_db.set_rating("tmdb:9", 8, "tv", "Show Nine", year=2020)
    with TestClient(main.app) as client:
        disc = client.get("/media/discover?q=foo").text
        rank = client.get("/media/years/2020?mode=rank&kind=tv&owner_view=you").text
    # 2026-10-06: no switcher to carry the query any more; the pages still render their nav
    assert "owner_view=" not in disc and "owner_view=" not in rank
    assert current(disc, "sectabs") == ["Discover"] and current(rank, "sectabs") == ["TV Shows"]


def test_year_pages_carry_kind_and_light_the_right_section(env):
    from hub import media_db
    main = env(jellyfin=JELLY, arr=ARR)
    media_db.set_rating("tmdb:9", 8, "tv", "Show Nine", year=2020)
    media_db.place(2020, "tmdb:9")
    with TestClient(main.app) as client:
        tiles = client.get("/media/years?kind=tv").text
        page = client.get("/media/years/2020?kind=tv").text
        rank = client.get("/media/years/2020?kind=tv&mode=rank").text
        cd = client.get("/media/years/2020/countdown?kind=tv").text
    assert 'href="/media/years/2020?kind=tv"' in tiles
    for html in (page, rank, cd):
        assert current(html, "sectabs") == ["TV Shows"]
    assert 'href="/media/years?kind=tv"' in page
    assert 'href="/media/years/2020?mode=rank&amp;kind=tv"' in page
    assert 'href="/media/years/2020/countdown?kind=tv"' in page
    assert 'name="kind" value="tv"' in page
    assert 'href="/media/years/2020?kind=tv"' in rank          # Done
    assert 'href="/media/years/2020?kind=tv"' in cd and 'data-back="/media/years/2020?kind=tv"' in cd


def test_year_write_routes_preserve_kind(env):
    from hub import media_db
    main = env(jellyfin=JELLY, arr=ARR)
    media_db.set_rating("tmdb:9", 8, "tv", "Show Nine", year=2020)
    media_db.set_rating("tmdb:8", 7, "movie", "Film Eight", year=2020)
    HX = {"HX-Request": "true"}
    with TestClient(main.app) as client:
        r = client.post("/media/years/2020/place", content="item_key=tmdb%3A9&kind=tv&mode=rank",
                        headers=HX)
        assert 'name="kind" value="tv"' in r.text and "Film Eight" not in r.text
        r = client.post("/media/years/2020/move", content="item_key=tmdb%3A9&delta=1&kind=tv",
                        follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/media/years/2020?kind=tv"
        r = client.post("/media/years/2020/unplace", content="item_key=tmdb%3A9&mode=rank&kind=tv",
                        follow_redirects=False)
        assert r.headers["location"] == "/media/years/2020?mode=rank&kind=tv"
        r = client.post("/media/years/2020/reset", content="kind=tv", follow_redirects=False)
        assert r.headers["location"] == "/media/years/2020?kind=tv"
        r = client.post("/media/years/2020/reset", content="kind=junk", follow_redirects=False)
        assert r.headers["location"] == "/media/years/2020"


def test_her_view_has_no_to_place_count(env):
    from hub import media_db
    main = env(jellyfin=JELLY, arr=ARR)
    media_db.set_rating("tmdb:9", 8, "movie", "Film Nine", year=2020)
    with TestClient(main.app) as client:
        you = nav_html(client.get("/media/movies?owner_view=you").text, "sectabs")
        her = nav_html(client.get("/media/movies?owner_view=her").text, "sectabs")
    assert "to place" in you
    assert "to place" not in her


def test_waitcount_has_hidden_words(env):
    main = env(jellyfin=JELLY, arr=ARR)
    from pathlib import Path
    css = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
    assert ".vh {" in css and "clip" in css.split(".vh {")[1].split("}")[0]
    rule = css.split(".badge-wait {")[1].split("}")[0]          # restyle Phase 3: amber outline badge
    assert "#" not in rule and "var(--amber)" in rule
    with TestClient(main.app) as client:
        diary = client.get("/media/history").text
    assert '<span class="vh"> to rate</span>' in diary or "to rate" not in diary


@pytest.mark.parametrize("route", ["/a/alpha", "/media/diary", "/media/playing", "/media/discover"])
def test_media_pages_in_shell_carry_six_labels_and_no_return_link(env, route):
    """Shell: six section labels on the page header (tabs first, title at its foot), no way-out bar."""
    main = env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as client:
        html = client.get(route).text
    body = html.split("<main", 1)[1]
    sections = nav_html(body, "sectabs")                 # in-content, under the page heading
    labels = [x.strip() for x in re.findall(r'<a href="[^"]*"[^>]*>([^<]*)', sections)]
    assert labels == list(LABELS.values())
    assert body.index('<header class="pagehead">') < body.index('<nav class="sectabs"') < body.index("<h1>")
    assert "Return to Joey" not in html and "mediabar" not in html
    assert '<a href="/a/alpha" aria-current="page">Alpha</a>' in html  # the top bar marks Media
