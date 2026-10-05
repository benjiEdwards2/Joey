"""Discover & Search (2026-10-05): live Jellyseerr proxy routes — search, shelves, title page,
two-step Request. `requests` is monkeypatched inside hub.media_discover; nothing hits the network."""
import html as htmllib
import importlib

import pytest
import requests
from fastapi.testclient import TestClient

from tests.hub.test_registry import make_area, make_tile, write_registry
from tests.hub.test_store import write_envelope

FAKE_URL = "http://seerr.secret-host.invalid:5055"
FAKE_KEY = "k-SECRET-0123456789"
HX = {"HX-Request": "true"}
FORM = {"content-type": "application/x-www-form-urlencoded"}


class Resp:
    def __init__(self, body=None, status=200):
        self._body, self.status_code = body, status
        self.ok = 200 <= status < 300

    def json(self):
        return self._body


def res(id, name, year="2020", status=None, media=None, **extra):
    r = {"id": id, "title": name, "releaseDate": f"{year}-01-01", "posterPath": f"/p{id}.jpg",
         "backdropPath": f"/b{id}.jpg", **extra}
    if media:
        r["mediaType"] = media
    if status is not None:
        r["mediaInfo"] = {"status": status}
    return r


MOVIES = {"results": [res(1, "Film Five", status=5), res(2, "Film Four", status=4),
                      res(3, "Film Three", status=3), res(4, "Film Two", status=2), res(5, "Film None")]}
TVS = {"results": [{"id": 9, "name": "Show Nine", "firstAirDate": "2019-05-05", "posterPath": "/t9.jpg"}]}
TRENDING = {"results": [{"id": 77, "mediaType": "person", "name": "Some Person"},
                        res(8, "Trend Film", media="movie")]}
MOVIE = {"id": 603, "title": "The Matrix", "releaseDate": "1999-03-30", "tagline": "Free your mind",
         "overview": "A hacker learns.", "runtime": 136, "voteAverage": 7.82, "posterPath": "/m.jpg",
         "backdropPath": "/mb.jpg", "genres": [{"name": "Action"}, {"name": "Sci-Fi"}],
         "credits": {"cast": [{"name": f"Actor {i}"} for i in range(12)]}, "mediaInfo": {"status": 1}}
TV = {"id": 100, "name": "Big Show", "firstAirDate": "2018-01-01", "numberOfSeasons": 4, "numberOfEpisodes": 30,
      "posterPath": "/tv.jpg", "mediaInfo": {"status": 4, "seasons": [
          {"seasonNumber": 1, "status": 5}, {"seasonNumber": 2, "status": 3}, {"seasonNumber": 3, "status": 2}]},
      "seasons": [{"seasonNumber": 0, "name": "Specials", "episodeCount": 2, "airDate": "2017-01-01"},
                  {"seasonNumber": 1, "name": "Season 1", "episodeCount": 10, "airDate": "2018-01-01"},
                  {"seasonNumber": 2, "name": "Season 2", "episodeCount": 10, "airDate": "2019-01-01"},
                  {"seasonNumber": 3, "name": "Season 3", "episodeCount": 5, "airDate": "2020-01-01"},
                  {"seasonNumber": 4, "name": "Season 4", "episodeCount": 5, "airDate": "2021-01-01"}]}


class Fake:
    def __init__(self):
        self.gets, self.posts, self.fail, self.post_status = [], [], False, 201
        self.table = {"/api/v1/discover/movies": MOVIES, "/api/v1/discover/tv": TVS,
                      "/api/v1/discover/trending": TRENDING, "/api/v1/discover/movies/upcoming": MOVIES,
                      "/api/v1/discover/tv/upcoming": TVS, "/api/v1/movie/603": MOVIE, "/api/v1/tv/100": TV}
        self.search_results = {"results": []}

    def get(self, url, headers=None, timeout=None, **kw):
        assert url.startswith(FAKE_URL) and headers == {"X-Api-Key": FAKE_KEY} and timeout == 8
        path = url[len(FAKE_URL):]
        self.gets.append(path)
        if self.fail:
            raise requests.ConnectionError(url)
        if path.startswith("/api/v1/search"):
            return Resp(self.search_results)
        return Resp(self.table[path]) if path in self.table else Resp({}, 404)

    def post(self, url, json=None, headers=None, timeout=None, **kw):
        self.posts.append((url, json, headers))
        if self.fail:
            raise requests.ConnectionError(url)
        return Resp({}, self.post_status)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    area = make_area("alpha", "play-t", snapshot="jellyfin", stale_after_minutes=10, detail="/media/playing")
    area["layout"] = "shelves"
    area["tiles"].append(make_tile("disc-t", snapshot="jellyseerr", stale_after_minutes=180,
                                   detail="/media/discover"))
    area["tiles"].append(make_tile("req-t", snapshot="jellyseerr", stale_after_minutes=180, detail="/media/requests"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.delenv("JELLYSEERR_URL", raising=False)
    monkeypatch.delenv("JELLYSEERR_API_KEY", raising=False)

    def build(areas=None, connected=True):
        monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, *(areas or [area]))))
        write_envelope(tmp_path / "snaps", "jellyfin", age_minutes=1, data={"summary": "x"})
        write_envelope(tmp_path / "snaps", "jellyseerr", age_minutes=1, data={"summary": "x", "requests": []})
        if connected:
            monkeypatch.setenv("JELLYSEERR_URL", FAKE_URL)
            monkeypatch.setenv("JELLYSEERR_API_KEY", FAKE_KEY)
        import hub.main
        importlib.reload(hub.main)
        from hub import media_discover
        media_discover.clear_cache()
        fake = Fake()
        monkeypatch.setattr(media_discover.requests, "get", fake.get)
        monkeypatch.setattr(media_discover.requests, "post", fake.post)
        return TestClient(hub.main.app), fake

    return build


def main_of(html):
    return html.split("<main", 1)[1]


def assert_no_secrets(html, link_ok=False):
    """The key never appears; the URL appears only as the title page's one outward link."""
    assert FAKE_KEY not in html and (link_ok or "secret-host" not in html)


def test_real_registry_has_discover_tile():
    from hub.registry import load_registry
    media = next(a for a in load_registry("config/areas.yaml").areas if a.id == "media")
    tile = next(t for t in media.tiles if t.id == "discover")
    assert tile.detail == "/media/discover" and tile.snapshot == "jellyseerr"
    ids = [t.id for t in media.tiles]
    assert ids.index("discover") == ids.index("requests") + 1


def test_404_when_no_tile_has_that_detail(env):
    client, fake = env(areas=[make_area("beta")])
    with client:
        assert client.get("/media/discover").status_code == 404
        assert client.get("/media/title/movie/603").status_code == 404
    assert fake.gets == []


def test_not_connected_without_env_makes_no_call(env):
    client, fake = env(connected=False)
    with client:
        resp = client.get("/media/discover")
        page = client.get("/media/title/movie/603")
        search = client.get("/media/discover/search?q=matrix")
    assert resp.status_code == 200 and "Not connected" in main_of(resp.text)
    assert "Not connected" in page.text and "Search unavailable" in search.text
    assert fake.gets == []


def test_shelves_render_with_status_words(env):
    client, fake = env()
    with client:
        resp = client.get("/media/discover")
    body = main_of(resp.text)
    for title in ("Trending", "Popular films", "Popular TV", "Upcoming films", "Upcoming TV"):
        assert f"<h3>{title}</h3>" in body
    for word in ("Available", "Partly available", "Processing", "Requested", "Not in library"):
        assert f">{word}</span>" in body
    assert 'href="/media/title/movie/1"' in body and 'href="/media/title/tv/9"' in body
    assert "Some Person" not in body and "Trend Film" in body
    assert 'hx-get="/media/discover/search"' in body and 'type="search"' in body
    assert "/img/tmdb:/p1.jpg" in body
    assert_no_secrets(resp.text)


def test_cache_hit_and_expiry(env, monkeypatch):
    client, fake = env()
    from hub import media_discover
    with client:
        client.get("/media/discover")
        first = len(fake.gets)
        assert first == 5
        client.get("/media/discover")
        assert len(fake.gets) == first                      # served from cache
        real = media_discover.time.time()
        monkeypatch.setattr(media_discover.time, "time", lambda: real + 601)
        client.get("/media/discover")
        assert len(fake.gets) == first * 2                  # expired -> fetched again


def test_failed_shelf_fetch_says_unavailable_and_is_not_cached(env):
    client, fake = env()
    fake.fail = True
    with client:
        resp = client.get("/media/discover")
        assert resp.status_code == 200 and main_of(resp.text).count("Discover unavailable") == 5
        fake.fail = False
        again = client.get("/media/discover")
    assert "Discover unavailable" not in again.text


def test_search_partial(env):
    client, fake = env()
    fake.search_results = {"results": [{"id": 5, "mediaType": "person", "name": "Nobody"}]
                           + [res(i, f"Hit {i}", media="movie") for i in range(30)]}
    with client:
        short = client.get("/media/discover/search?q=a")
        assert "Type at least two letters" in short.text and fake.gets == []
        got = client.get("/media/discover/search?q=%20hit%20")
        assert got.text.count('class="shelf-item"') == 20 and "Nobody" not in got.text
        assert "poster-grid" in got.text and "<html" not in got.text
        assert fake.gets == ["/api/v1/search?query=hit"]
        fake.search_results = {"results": []}
        assert "No matches" in client.get("/media/discover/search?q=zzzz").text
        fake.fail = True
        assert "Search unavailable" in client.get("/media/discover/search?q=zzzz").text


def test_search_without_js_renders_server_side(env):
    client, fake = env()
    fake.search_results = {"results": [res(1, "Matrix Film", media="movie", status=5)]}
    with client:
        resp = client.get("/media/discover?q=matrix")
    body = main_of(resp.text)
    assert "Matrix Film" in body and ">Available</span>" in body and "Popular films" not in body


def test_movie_title_page(env):
    client, fake = env()
    with client:
        resp = client.get("/media/title/movie/603")
    body = main_of(resp.text)
    assert "The Matrix (1999)" in body and "Free your mind" in body and "A hacker learns." in body
    assert "Action, Sci-Fi" in body and "136 min" in body and "7.8 / 10" in body
    assert "Actor 7" in body and "Actor 8" not in body
    assert "--bd: url('/img/tmdb:/mb.jpg?h=1280')" in resp.text and "hasbackdrop" in body
    assert f'href="{FAKE_URL}/movie/603"' in body and "Open in Jellyseerr" in body
    assert ">Not in library</span>" in body and ">Request</a>" in body
    assert FAKE_KEY not in resp.text


def test_tv_title_page_seasons_and_confirm(env):
    client, fake = env()
    with client:
        page = client.get("/media/title/tv/100")
        body = main_of(page.text)
        assert "4 seasons · 30 episodes" in body
        seasons = body.split("<h3>Seasons</h3>", 1)[1].split("requestblock", 1)[0]
        assert seasons.index("Season 1") < seasons.index("Season 4") < seasons.index("Specials")
        for word in ("Available", "Processing", "Requested", "Not in library"):
            assert f">{word}</span>" in seasons
        assert ">Request</a>" in body                        # partly available: still offered
        confirm = client.get("/media/title/tv/100/request?step=confirm", headers=HX).text
    tags = {chunk.split('"', 1)[0]: chunk.split(">", 1)[0] for chunk in confirm.split('name="seasons" value="')[1:]}
    assert " disabled" in tags["1"] and " checked" not in tags["1"]
    assert " checked" not in tags["2"] and " checked" not in tags["3"]
    assert " checked" in tags["4"] and " disabled" not in tags["4"]
    assert " checked" not in tags["0"]
    assert confirm.index('value="4"') < confirm.index('value="0"')
    assert "Confirm request" in confirm and "Cancel" in confirm and 'hx-post="/media/title/tv/100/request"' in confirm


def test_movie_confirm_and_idle_and_available(env):
    client, fake = env()
    fake.table["/api/v1/movie/603"] = {**MOVIE, "mediaInfo": {"status": 5}}
    with client:
        avail = client.get("/media/title/movie/603/request?step=idle").text
        assert "Request</a>" not in avail and "Available" in avail
        fake.table["/api/v1/movie/603"] = MOVIE
        confirm = client.get("/media/title/movie/603/request?step=confirm").text
        idle = client.get("/media/title/movie/603/request").text
        plain = client.get("/media/title/movie/603?step=confirm").text
        assert client.get("/media/title/anime/1").status_code == 404
    assert "Request The Matrix (1999)?" in confirm and 'type="checkbox"' not in confirm
    assert 'id="request-block"' in idle and 'hx-get="/media/title/movie/603/request?step=confirm"' in idle
    assert "Confirm request" in plain


def test_post_movie_request_sends_exact_payload(env):
    client, fake = env()
    with client:
        resp = client.post("/media/title/movie/603/request", headers=HX)
    assert resp.status_code == 200 and "Requested ✓ — shows in Requests within the hour" in resp.text
    url, payload, headers = fake.posts[0]
    assert url == f"{FAKE_URL}/api/v1/request" and payload == {"mediaType": "movie", "mediaId": 603}
    assert headers["X-Api-Key"] == FAKE_KEY
    assert_no_secrets(resp.text)
    assert "<html" not in resp.text


def test_post_tv_request_sends_seasons(env):
    client, fake = env()
    with client:
        resp = client.post("/media/title/tv/100/request", content="seasons=3&seasons=4&seasons=3",
                           headers={**HX, **FORM})
    assert resp.status_code == 200 and "Requested" in resp.text
    assert fake.posts[0][1] == {"mediaType": "tv", "mediaId": 100, "seasons": [3, 4]}


@pytest.mark.parametrize("body", ["", "seasons=0", "seasons=x", "other=1"])
def test_tv_request_needs_a_season(env, body):
    client, fake = env()
    with client:
        resp = client.post("/media/title/tv/100/request", content=body, headers={**HX, **FORM})
    assert resp.status_code == 422 and "Pick at least one season" in resp.text and fake.posts == []


def test_request_failures_are_words_not_500s(env):
    client, fake = env()
    with client:
        fake.post_status = 409
        assert "Already requested" in client.post("/media/title/movie/603/request", headers=HX).text
        fake.post_status = 403
        assert "Jellyseerr declined the request" in client.post("/media/title/movie/603/request", headers=HX).text
        fake.fail = True
        resp = client.post("/media/title/movie/603/request", headers=HX)
    assert resp.status_code == 200 and "Couldn&#39;t send the request" in resp.text and "Try again" in resp.text
    assert_no_secrets(resp.text)


def test_origin_guard_and_plain_form_redirects(env):
    client, fake = env()
    with client:
        bad = client.post("/media/title/movie/603/request", headers={"Origin": "https://evil.example"})
        ok = client.post("/media/title/movie/603/request", follow_redirects=False)
        fake.post_status = 409
        dup = client.post("/media/title/movie/603/request", follow_redirects=False)
        done = client.get("/media/title/movie/603?requested=1")
        err = client.get("/media/title/movie/603?error=exists")
    assert bad.status_code == 403 and len(fake.posts) == 2
    assert ok.status_code == 303 and ok.headers["location"] == "/media/title/movie/603?requested=1"
    assert dup.headers["location"] == "/media/title/movie/603?error=exists"
    assert "Requested ✓" in done.text and "Already requested" in err.text
    assert_no_secrets(done.text + err.text, link_ok=True)


def test_discover_is_a_section_not_a_home_button(env):
    client, _ = env()
    with client:
        html = client.get("/a/alpha").text
    assert "Discover &amp; Search" not in html            # F1: the header button is gone
    assert '<a href="/media/discover">Discover</a>' in html  # Discover is a Media section now
