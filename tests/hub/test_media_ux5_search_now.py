"""media-ux5 item 6 (2026-10-09): "Search now" on the film / series page (the Discover title page is the same template).
The hero lazy-loads GET /media/title/{kind}/{tmdb}/arr, which renders the form only when the title is in Radarr /
Sonarr; POST /media/title/{kind}/{tmdb}/search sends MoviesSearch / SeriesSearch and 303s back with a flash.
Jellyfin + Jellyseerr are the film-page fakes; Radarr / Sonarr are faked here at requests.get / post. No network."""
import html as htmllib
import logging
import re

import pytest
import requests

from tests.hub.helpers import env, FakeResponse as R  # noqa: F401  (re-export: defined in tests/hub/helpers.py)

RADARR = "http://radarr.secret-host.invalid:7878"
RKEY = "r-SECRET-radarr-key"
SONARR = "http://sonarr.secret-host.invalid:8989"
TKEY = "s-SECRET-sonarr-key"
HX = {"HX-Request": "true"}


class Arr:
    def __init__(self):
        self.movies = [{"id": 11, "tmdbId": 603, "title": "Harbour Lights", "monitored": True, "hasFile": True}]
        self.series = [{"id": 21, "tmdbId": 100, "tvdbId": 1100, "title": "Quiet Show", "monitored": True}]
        self.calls, self.raise_get, self.raise_post, self.post_status = [], None, None, 201

    def handles(self, url):
        return url.startswith((RADARR, SONARR))

    def _hdr(self, url, headers):
        assert headers == {"X-Api-Key": RKEY if url.startswith(RADARR) else TKEY}

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        self.calls.append(("GET", url, params, None))
        self._hdr(url, headers)
        if self.raise_get:
            raise self.raise_get(f"Max retries exceeded with url: {url}?apikey={RKEY}")
        if url == f"{RADARR}/api/v3/movie":
            return R([m for m in self.movies if m["tmdbId"] == (params or {}).get("tmdbId")])
        if url == f"{SONARR}/api/v3/series":
            if params and "tvdbId" in params:
                return R([s for s in self.series if s["tvdbId"] == params["tvdbId"]])
            return R(self.series)
        return R({}, 404)

    def post(self, url, json=None, headers=None, timeout=None, **kw):
        self.calls.append(("POST", url, None, json))
        self._hdr(url, headers)
        if self.raise_post:
            raise self.raise_post(f"Read timed out: {url} {TKEY}")
        return R({"id": 5, "name": (json or {}).get("name")}, self.post_status)

    def commands(self):
        return [(u, j) for m, u, _, j in self.calls if m == "POST" and u.endswith("/api/v3/command")]


@pytest.fixture()
def arr_env(env, monkeypatch):
    for k, v in (("RADARR_URL", RADARR), ("RADARR_API_KEY", RKEY), ("SONARR_URL", SONARR), ("SONARR_API_KEY", TKEY)):
        monkeypatch.setenv(k, v)

    def build(**kw):
        client, both = env(**kw)
        arr = Arr()
        get, post = requests.get, requests.post
        monkeypatch.setattr(requests, "get", lambda url, *a, **k: arr.get(url, *a, **k) if arr.handles(url) else get(url, *a, **k))
        monkeypatch.setattr(requests, "post", lambda url, *a, **k: arr.post(url, *a, **k) if arr.handles(url) else post(url, *a, **k))
        return client, both, arr
    return build


def lazy(html):
    m = re.search(r'<span id="arr-search" hidden hx-get="([^"]+)" hx-trigger="load" hx-swap="outerHTML"></span>', html)
    return htmllib.unescape(m.group(1)) if m else None


# ---- the lazy hook on the page ----

@pytest.mark.parametrize("path, want", [
    ("/media/item/mov1", "/media/title/movie/603/arr?back=%2Fmedia%2Fitem%2Fmov1"),
    ("/media/title/movie/603", "/media/title/movie/603/arr?back=%2Fmedia%2Ftitle%2Fmovie%2F603"),
    ("/media/title/tv/100", "/media/title/tv/100/arr?back=%2Fmedia%2Ftitle%2Ftv%2F100"),
])
def test_title_pages_lazy_load_the_search_button(arr_env, path, want):
    client, _, arr = arr_env()
    with client:
        html = client.get(path).text
    assert lazy(html) == want
    assert not arr.calls                                   # the page itself never waits on Radarr / Sonarr
    assert RKEY not in html and TKEY not in html and "radarr.secret-host" not in html


def test_no_hook_when_the_app_is_not_connected(env, monkeypatch):
    monkeypatch.delenv("RADARR_URL", raising=False)
    monkeypatch.delenv("RADARR_API_KEY", raising=False)
    client, _ = env()
    with client:
        html = client.get("/media/title/movie/603").text
    assert lazy(html) is None and 'id="arr-search"' not in html


def test_series_hook_carries_the_tvdb_id(arr_env):
    from tests.hub import test_media_film as tf
    client, both, _ = arr_env()
    both.seerr.table["/api/v1/tv/100"] = {**tf.SHOW, "externalIds": {"tvdbId": 1100}}
    with client:
        html = client.get("/media/title/tv/100").text
    assert lazy(html) == "/media/title/tv/100/arr?back=%2Fmedia%2Ftitle%2Ftv%2F100&tvdb=1100"


# ---- the fragment ----

def test_fragment_is_the_form_when_the_film_is_in_radarr(arr_env):
    client, _, arr = arr_env()
    with client:
        frag = client.get("/media/title/movie/603/arr?back=/media/item/mov1", headers=HX).text
    assert '<form id="arr-search" method="post" action="/media/title/movie/603/search">' in frag
    assert '<input type="hidden" name="back" value="/media/item/mov1">' in frag
    assert '<button class="btn btn-glass" type="submit"' in frag and "Search now</button>" in frag
    assert '<svg class="ic"' in frag                       # word beside the icon
    assert arr.calls == [("GET", f"{RADARR}/api/v3/movie", {"tmdbId": 603}, None)]


def test_fragment_is_empty_when_not_in_the_app(arr_env):
    client, _, arr = arr_env()
    arr.movies = []
    with client:
        r = client.get("/media/title/movie/603/arr?back=/media/title/movie/603", headers=HX)
    assert r.status_code == 200 and r.text == ""


def test_fragment_is_empty_and_sanitized_when_the_app_is_down(arr_env, caplog):
    client, _, arr = arr_env()
    arr.raise_get = requests.ConnectionError
    with caplog.at_level(logging.WARNING), client:
        r = client.get("/media/title/movie/603/arr", headers=HX)
    assert r.status_code == 200 and r.text == ""
    assert "radarr lookup failed: ConnectionError" in caplog.text
    assert RKEY not in caplog.text and "secret-host" not in caplog.text


def test_fragment_uses_tvdb_for_sonarr(arr_env):
    client, _, arr = arr_env()
    with client:
        frag = client.get("/media/title/tv/100/arr?tvdb=1100&back=/media/item/ser1", headers=HX).text
    assert 'action="/media/title/tv/100/search"' in frag and '<input type="hidden" name="tvdb" value="1100">' in frag
    assert "its monitored episodes" in frag
    assert arr.calls == [("GET", f"{SONARR}/api/v3/series", {"tvdbId": 1100}, None)]


# ---- the POST ----

def test_search_now_sends_movies_search_and_flashes(arr_env):
    client, _, arr = arr_env()
    with client:
        r = client.post("/media/title/movie/603/search", data={"back": "/media/item/mov1"}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/media/item/mov1?search=started&app=radarr"
        page = client.get(r.headers["location"]).text
    assert arr.commands() == [(f"{RADARR}/api/v3/command", {"name": "MoviesSearch", "movieIds": [11]})]
    assert '<p class="metaline st-good" role="status">Search started in Radarr</p>' in page


def test_search_now_sends_series_search_by_tmdb_without_tvdb(arr_env):
    client, _, arr = arr_env()
    with client:
        r = client.post("/media/title/tv/100/search", data={}, follow_redirects=False)
    assert r.headers["location"] == "/media/title/tv/100?search=started&app=sonarr"
    assert arr.commands() == [(f"{SONARR}/api/v3/command", {"name": "SeriesSearch", "seriesId": 21})]
    assert ("GET", f"{SONARR}/api/v3/series", None, None) in arr.calls   # full list matched on tmdbId


def test_unmonitored_title_is_still_sent_and_the_flash_says_so(arr_env):
    client, _, arr = arr_env()
    arr.movies[0]["monitored"] = False
    with client:
        r = client.post("/media/title/movie/603/search", data={"back": "/media/title/movie/603"}, follow_redirects=False)
        page = client.get(r.headers["location"]).text
    assert "search=unmonitored" in r.headers["location"] and len(arr.commands()) == 1
    assert "Search started in Radarr · not monitored there, so it may find nothing" in htmllib.unescape(page)


def test_not_in_the_app_sends_nothing(arr_env):
    client, _, arr = arr_env()
    arr.movies = []
    with client:
        r = client.post("/media/title/movie/603/search", data={"back": "/media/title/movie/603"}, follow_redirects=False)
        page = client.get(r.headers["location"]).text
    assert r.headers["location"] == "/media/title/movie/603?search=missing&app=radarr"
    assert arr.commands() == []
    assert '<p class="metaline st-warn" role="status">Not in Radarr — use Request</p>' in page


@pytest.mark.parametrize("fail, code, word", [
    ("get", "search=unreachable&app=radarr", "Couldn&#39;t reach Radarr"),
    ("post", "search=unreachable&app=radarr", "Couldn&#39;t reach Radarr"),
    ("status", "search=refused&app=radarr&code=500", "Radarr refused (HTTP 500)"),
])
def test_upstream_failures_are_sanitized_words(arr_env, caplog, fail, code, word):
    client, _, arr = arr_env()
    if fail == "get":
        arr.raise_get = requests.ConnectionError
    elif fail == "post":
        arr.raise_post = requests.Timeout
    else:
        arr.post_status = 500
    with caplog.at_level(logging.WARNING), client:
        r = client.post("/media/title/movie/603/search", data={"back": "/media/title/movie/603"}, follow_redirects=False)
        page = client.get(r.headers["location"]).text
    assert r.headers["location"] == f"/media/title/movie/603?{code}"
    assert word in page
    for secret in (RKEY, TKEY, "radarr.secret-host", "sonarr.secret-host", "Max retries", "timed out"):
        assert secret not in caplog.text and secret not in page and secret not in r.headers["location"]


def test_cross_site_post_is_refused(arr_env):
    client, _, arr = arr_env()
    with client:
        r = client.post("/media/title/movie/603/search", data={}, headers={"Origin": "https://evil.invalid"},
                        follow_redirects=False)
    assert r.status_code == 403 and arr.calls == []


@pytest.mark.parametrize("back", ["https://evil.invalid/x", "//evil.invalid", "/etc/passwd", ""])
def test_odd_back_returns_to_the_title_page(arr_env, back):
    client, _, _ = arr_env()
    with client:
        r = client.post("/media/title/movie/603/search", data={"back": back}, follow_redirects=False)
    assert r.headers["location"].startswith("/media/title/movie/603?search=started")


def test_unknown_kind_is_404(arr_env):
    client, _, arr = arr_env()
    with client:
        assert client.post("/media/title/book/1/search", data={}).status_code == 404
        assert client.get("/media/title/book/1/arr").status_code == 404
    assert arr.calls == []


def test_flash_param_leaves_the_address_bar(arr_env):
    import hub.main
    assert "search" in hub.main.FLASH_PARAMS


def test_contract_and_readme_document_the_writes():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    contract = (root / "docs" / "connector-contract.md").read_text(encoding="utf-8")
    para = contract.split("**Seventeenth exception (2026-10-09): Search now", 1)[1].split("\n\n", 1)[0]
    for word in ("MoviesSearch", "SeriesSearch", "same_origin", "monitored items only", "monitorNewItems",
                 "status or exception type only"):
        assert word in para
    assert "Search now (media-ux5, 2026-10-09)" in (root / "hub" / "README.md").read_text(encoding="utf-8")
