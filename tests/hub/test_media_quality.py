"""Request quality profile (WP-R1, 2026-10-21): pick 1080p or 4K on the Request confirm step (the arr quality profile,
as Seerr's Advanced › Quality Profile), the request's safety net, "Quality · 1080p" + Switch on the title page, and the
"4K" chip on the Requests page. Jellyseerr is the Discover / film-page fake; Radarr and Sonarr are faked here at
requests.get / post / put. No network, no real sleeps."""
import copy
import html as htmllib
import logging
import re

import pytest
import requests

from hub import media_arr_search, media_quality, media_requests, media_season_state
from tests.hub.helpers import env, FakeResponse as R, not_season_state  # noqa: F401  (fixture re-export)
from tests.hub.test_media_discover import env as discover_env, FAKE_KEY, FORM, HX  # noqa: F401
from tests.hub.test_media_requests_remove import env as req_env  # noqa: F401  (fixture re-export)
from tests.hub import test_media_requests_remove as trr

RADARR = "http://radarr.secret-host.invalid:7878"
RKEY = "r-SECRET-radarr-key"
SONARR = "http://sonarr.secret-host.invalid:8989"
TKEY = "s-SECRET-sonarr-key"
R_PROFILES = [{"id": 8, "name": "1080p", "items": []}, {"id": 9, "name": "4K", "items": []}]
S_PROFILES = [{"id": 7, "name": "1080p"}, {"id": 8, "name": "4K"}]
R_SETTINGS = [{"id": 0, "name": "Movies", "isDefault": True, "is4k": False, "activeProfileId": 8}]
S_SETTINGS = [{"id": 0, "name": "Shows", "isDefault": True, "is4k": False, "activeProfileId": 7}]


class Arr:
    """Radarr + Sonarr: quality profiles, the title lookups, the PUT of a title and the search command."""

    def __init__(self):
        self.movies = [{"id": 11, "tmdbId": 603, "title": "Harbour Lights", "monitored": True, "hasFile": True,
                        "qualityProfileId": 8, "path": "/movies/Harbour Lights (2019)"}]
        self.series = [{"id": 21, "tmdbId": 100, "tvdbId": 1100, "title": "Quiet Show", "monitored": True,
                        "qualityProfileId": 7, "path": "/tv/Quiet Show"}]
        self.profiles = {RADARR: copy.deepcopy(R_PROFILES), SONARR: copy.deepcopy(S_PROFILES)}
        self.calls, self.profile_status, self.put_status, self.post_status = [], 200, 202, 201
        self.raise_put, self.appear_after = None, 0

    def handles(self, url):
        return str(url).startswith((RADARR, SONARR))

    def _base(self, url, headers):
        base = RADARR if url.startswith(RADARR) else SONARR
        assert headers == {"X-Api-Key": RKEY if base == RADARR else TKEY}
        return base

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        self.calls.append(("GET", url, params, None))
        base = self._base(url, headers)
        if url == f"{base}/api/v3/qualityprofile":
            return R(self.profiles[base], self.profile_status)
        if self.appear_after:
            self.appear_after -= 1
            return R([])
        if url == f"{RADARR}/api/v3/movie":
            return R([m for m in self.movies if m["tmdbId"] == (params or {}).get("tmdbId")])
        if url == f"{SONARR}/api/v3/series":
            if params and "tvdbId" in params:
                return R([s for s in self.series if s["tvdbId"] == params["tvdbId"]])
            return R(self.series)
        return R({}, 404)

    def put(self, url, json=None, headers=None, timeout=None, **kw):
        self.calls.append(("PUT", url, None, json))
        self._base(url, headers)
        if self.raise_put:
            raise self.raise_put(f"Read timed out: {url}?apikey={RKEY}")
        if 200 <= self.put_status < 300:
            for rows in (self.movies, self.series):
                for i, e in enumerate(rows):
                    if url.endswith(f"/{e['id']}") and ("/movie/" in url) == (rows is self.movies):
                        rows[i] = dict(json)
        return R(json, self.put_status)

    def post(self, url, json=None, headers=None, timeout=None, **kw):
        self.calls.append(("POST", url, None, json))
        self._base(url, headers)
        return R({"id": 5}, self.post_status)

    def of(self, method):
        return [c for c in self.calls if c[0] == method]


def wire(monkeypatch, arr):
    for k, v in (("RADARR_URL", RADARR), ("RADARR_API_KEY", RKEY), ("SONARR_URL", SONARR), ("SONARR_API_KEY", TKEY)):
        monkeypatch.setenv(k, v)
    for m in ("get", "post", "put"):
        prev = getattr(requests, m, None)
        mine = getattr(arr, m)
        monkeypatch.setattr(requests, m, (lambda mine, prev: lambda url, *a, **k: mine(url, *a, **k) if arr.handles(url)
                                          else prev(url, *a, **k))(mine, prev))


@pytest.fixture()
def sleeps(monkeypatch):
    got = []
    monkeypatch.setattr(media_quality.time, "sleep", lambda s: got.append(s))
    monkeypatch.setattr(media_arr_search.time, "sleep", lambda s: got.append(s))
    return got


@pytest.fixture()
def film_env(env, monkeypatch):
    """The film-page env (Jellyfin + Seerr fakes, Harbour Lights = tmdb 603 on the server) plus Radarr / Sonarr."""
    def build(**kw):
        client, both = env(**kw)
        both.seerr.table["/api/v1/settings/radarr"] = R_SETTINGS
        both.seerr.table["/api/v1/settings/sonarr"] = S_SETTINGS
        arr = Arr()
        wire(monkeypatch, arr)
        return client, both, arr
    return build


@pytest.fixture()
def req(discover_env, monkeypatch, sleeps):
    """The Discover env (The Matrix = movie 603 off the server, Big Show = tv 100) plus Radarr / Sonarr."""
    def build():
        client, fake = discover_env()
        fake.table["/api/v1/settings/radarr"] = R_SETTINGS
        fake.table["/api/v1/settings/sonarr"] = S_SETTINGS
        fake.table["/api/v1/tv/100"] = {**fake.table["/api/v1/tv/100"], "externalIds": {"tvdbId": 1100}}
        arr = Arr()
        wire(monkeypatch, arr)
        return client, fake, arr
    return build


def seerr_posts(fake):
    return [j for u, j, _ in fake.posts if u.endswith("/api/v1/request")]


def no_secrets(text, link_ok=False):
    """No key ever; no host either, except a full page's one "Open in Seerr" link."""
    assert RKEY not in text and TKEY not in text and FAKE_KEY not in text
    assert "radarr.secret-host" not in text and "sonarr.secret-host" not in text and (link_ok or "secret-host" not in text)


# ---- the profile list ----

def test_profiles_keep_the_apps_names_flag_4k_and_take_seerrs_default(film_env):
    client, _, arr = film_env()
    with client:
        movie, tv = media_quality.profiles("movie"), media_quality.profiles("tv")
    assert movie == [{"id": 8, "name": "1080p", "is_4k": False, "default": True},
                     {"id": 9, "name": "4K", "is_4k": True, "default": False}]
    assert tv == [{"id": 7, "name": "1080p", "is_4k": False, "default": True},
                  {"id": 8, "name": "4K", "is_4k": True, "default": False}]


@pytest.mark.parametrize("name, is_4k", [("4K", True), ("Bluray-2160p", True), ("UHD Remux", True), ("uhd", True),
                                         ("HD-1080p", False), ("Any", False)])
def test_4k_is_read_from_the_name(film_env, name, is_4k):
    client, _, arr = film_env()
    arr.profiles[RADARR] = [{"id": 3, "name": name}]
    with client:
        assert media_quality.profiles("movie")[0]["is_4k"] is is_4k


def test_default_falls_back_to_the_first_non_4k_profile(film_env):
    client, both, arr = film_env()
    del both.seerr.table["/api/v1/settings/radarr"]                       # Seerr says nothing: 404
    arr.profiles[RADARR] = [{"id": 9, "name": "4K"}, {"id": 8, "name": "1080p"}, {"id": 5, "name": "720p"}]
    with client:
        rows = media_quality.profiles("movie")
    assert [r["id"] for r in rows if r["default"]] == [8]
    media_quality.clear_cache()
    both.seerr.table["/api/v1/settings/radarr"] = [{"id": 0, "isDefault": True, "is4k": False, "activeProfileId": 99}]
    with client:
        assert [r["id"] for r in media_quality.profiles("movie") if r["default"]] == [8]   # an id the app lacks


def test_profiles_are_kept_ten_minutes_and_a_failure_keeps_the_last_good(film_env, monkeypatch, caplog):
    client, _, arr = film_env()
    now = [1000.0]
    monkeypatch.setattr(media_quality, "_clock", lambda: now[0])
    reads = lambda: len([c for c in arr.calls if c[1] == f"{RADARR}/api/v3/qualityprofile"])
    with client:
        first = media_quality.profiles("movie")
        assert media_quality.profiles("movie") == first and reads() == 1          # kept
        now[0] += media_quality.TTL + 1
        arr.profile_status = 503
        with caplog.at_level(logging.WARNING, logger="hub.media_quality"):
            assert media_quality.profiles("movie") == first and reads() == 2      # failed: the last good list
        now[0] += 5
        assert media_quality.profiles("movie") == first and reads() == 2          # not retried inside FAIL_TTL
        now[0] += media_quality.FAIL_TTL
        arr.profile_status = 200
        assert media_quality.profiles("movie") == first and reads() == 3
    assert "radarr quality profiles failed: HTTP 503" in caplog.text
    no_secrets(caplog.text)


def test_no_profiles_without_creds_or_any_good_answer(film_env, monkeypatch):
    client, _, arr = film_env()
    arr.profile_status = 500
    with client:
        assert media_quality.profiles("movie") == [] and media_quality.choices("movie") == []
    monkeypatch.delenv("SONARR_URL")
    assert media_quality.profiles("tv") == []
    assert not [c for c in arr.calls if c[1].startswith(SONARR)]


# ---- the Request confirm step ----

def chips(html):
    return re.findall(r'<label class="chip"><input type="radio" name="profile" value="(\d+)"( checked)?>([^<]+)</label>',
                      html)


def test_confirm_step_offers_quality_chips_with_the_default_preselected(req):
    client, _, _ = req()
    with client:
        html = client.get("/media/title/movie/603/request?step=confirm", headers=HX).text
    assert '<div class="chips qualitypick" role="radiogroup" aria-label="Quality"><span class="microlabel">Quality</span>' in html
    assert chips(html) == [("8", " checked", "1080p · Default"), ("9", "", "4K")]
    assert html.index("Request The Matrix (1999)?") < html.index("qualitypick") < html.index("Confirm request")
    no_secrets(html)


def test_tv_quality_row_sits_under_the_seasons_and_never_unticks_all_seasons(req):
    client, _, _ = req()
    with client:
        html = client.get("/media/title/tv/100/request?step=confirm", headers=HX).text
    assert chips(html) == [("7", " checked", "1080p · Default"), ("8", "", "4K")]
    assert html.index('<div class="seasonpick">') < html.index("qualitypick") < html.index("Confirm request")
    assert "else if(t.name==='seasons'&amp;&amp;t.checked){a.checked=false}" in html or \
        "else if(t.name==='seasons'&&t.checked){a.checked=false}" in htmllib.unescape(html)


@pytest.mark.parametrize("case", ["one", "failed", "unset"])
def test_no_quality_row_with_one_profile_a_failed_read_or_no_app(req, monkeypatch, case):
    client, _, arr = req()
    if case == "one":
        arr.profiles[RADARR] = [{"id": 8, "name": "1080p"}]
    elif case == "failed":
        arr.profile_status = 500
    else:
        monkeypatch.delenv("RADARR_API_KEY")
    with client:
        html = client.get("/media/title/movie/603/request?step=confirm", headers=HX).text
    assert "qualitypick" not in html and 'name="profile"' not in html and "Confirm request" in html


def test_no_js_confirm_step_draws_the_chips_on_the_page(req):
    client, _, _ = req()
    with client:
        html = client.get("/media/title/movie/603?step=confirm").text
    assert chips(html) == [("8", " checked", "1080p · Default"), ("9", "", "4K")]


# ---- the request ----

def test_4k_request_sends_profile_id_and_needs_no_fix_when_seerr_applied_it(req, sleeps):
    client, fake, arr = req()
    arr.movies[0]["qualityProfileId"] = 9                     # Seerr added it to Radarr with the picked profile
    with client:
        r = client.post("/media/title/movie/603/request", content="profile=9", headers={**HX, **FORM})
    assert seerr_posts(fake) == [{"mediaType": "movie", "mediaId": 603, "profileId": 9}]   # no serverId needed
    assert arr.of("PUT") == [] and arr.of("POST") == [] and sleeps == []
    assert [c[1] for c in arr.of("GET")] == [f"{RADARR}/api/v3/qualityprofile", f"{RADARR}/api/v3/movie"]
    assert "Requested in 4K ✓ — shows in Requests within the hour" in r.text and "st-warn" not in r.text
    no_secrets(r.text)


def test_safety_net_puts_the_profile_and_searches_when_the_entry_differs(req):
    client, fake, arr = req()
    before = dict(arr.movies[0])
    with client:
        r = client.post("/media/title/movie/603/request", content="profile=9", headers={**HX, **FORM})
    (put,) = arr.of("PUT")
    assert put[1] == f"{RADARR}/api/v3/movie/11" and put[3] == {**before, "qualityProfileId": 9}   # other fields kept
    assert [c[3] for c in arr.of("POST")] == [{"name": "MoviesSearch", "movieIds": [11]}]
    assert "Requested in 4K ✓" in r.text


def test_safety_net_waits_for_the_app_then_says_so(req, sleeps):
    client, fake, arr = req()
    arr.appear_after = 99
    with client:
        r = client.post("/media/title/movie/603/request", content="profile=9", headers={**HX, **FORM})
    assert len([c for c in arr.of("GET") if c[1].endswith("/movie")]) == 3 and sleeps == [2.0, 2.0]
    assert arr.of("PUT") == []
    assert "Requested in 4K ✓" in r.text
    assert '<p class="metaline st-warn">Radarr hasn&#39;t added it yet — check its quality on the title page later</p>' in r.text


def test_default_pick_sends_its_id_and_skips_the_safety_net(req, sleeps):
    client, fake, arr = req()
    with client:
        r = client.post("/media/title/movie/603/request", content="profile=8", headers={**HX, **FORM})
    assert seerr_posts(fake) == [{"mediaType": "movie", "mediaId": 603, "profileId": 8}]
    assert [c[1] for c in arr.calls] == [f"{RADARR}/api/v3/qualityprofile"]       # validation only: no read-back
    assert "Requested ✓ — shows in Requests within the hour" in r.text


@pytest.mark.parametrize("body", ["profile=4", "profile=x", "profile=99999999999"])
def test_a_profile_the_app_does_not_offer_is_refused_without_a_request(req, body):
    client, fake, arr = req()
    with client:
        r = client.post("/media/title/movie/603/request", content=body, headers={**HX, **FORM})
    assert r.status_code == 422 and "Pick a quality" in r.text and seerr_posts(fake) == []


def test_failed_request_never_touches_the_app(req):
    client, fake, arr = req()
    fake.post_status = 409
    with client:
        r = client.post("/media/title/movie/603/request", content="profile=9", headers={**HX, **FORM})
    assert "Already requested" in r.text and [c[1] for c in arr.calls] == [f"{RADARR}/api/v3/qualityprofile"]


def test_no_js_request_carries_the_quality_to_the_done_line(req):
    client, fake, arr = req()
    with client:
        r = client.post("/media/title/movie/603/request", content="profile=9", headers=FORM, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/media/title/movie/603?requested=1&quality=9"
        done = client.get(r.headers["location"]).text
        late = client.get("/media/title/movie/603?requested=1&quality=9&qnet=notyet").text
    assert "Requested in 4K ✓ — shows in Requests within the hour" in done
    assert "Radarr hasn&#39;t added it yet" in late


def test_tv_request_with_all_seasons_fixes_the_profile_before_sonarr_follows(req, sleeps):
    client, fake, arr = req()
    with client:
        client.get("/media/title/tv/100")                      # the page the request is made from caches the title body
        r = client.post("/media/title/tv/100/request", content="seasons=all&profile=8", headers={**HX, **FORM})
    assert seerr_posts(fake) == [{"mediaType": "tv", "mediaId": 100, "seasons": "all", "profileId": 8}]
    puts = arr.of("PUT")
    assert len(puts) == 2 and puts[0][3]["qualityProfileId"] == 8                       # the safety net first ...
    assert puts[1][3]["qualityProfileId"] == 8 and puts[1][3]["monitorNewItems"] == "all"   # ... the follow keeps it
    # the safety net found the show by its TheTVDB id (from the cached title body), not the whole list
    assert ("GET", f"{SONARR}/api/v3/series", {"tvdbId": 1100}, None) in arr.calls
    assert "Requested in 4K ✓" in r.text and "every season monitored" in r.text


# ---- the title page: Quality · 1080p + Switch ----

def hook(html):
    m = re.search(r'<div id="quality-block" hidden hx-get="([^"]+)" hx-trigger="load" hx-swap="outerHTML"></div>', html)
    return htmllib.unescape(m.group(1)) if m else None


@pytest.mark.parametrize("path, want", [
    ("/media/item/mov1", "/media/title/movie/603/quality?back=%2Fmedia%2Fitem%2Fmov1"),
    ("/media/title/movie/603", "/media/title/movie/603/quality?back=%2Fmedia%2Ftitle%2Fmovie%2F603"),
])
def test_title_pages_lazy_load_the_quality_line_and_make_no_arr_call(film_env, path, want):
    client, _, arr = film_env()
    with client:
        html = client.get(path).text
    assert hook(html) == want
    assert not not_season_state(arr.calls)
    no_secrets(html, link_ok=True)


def test_no_quality_hook_without_the_app(film_env, monkeypatch):
    client, _, arr = film_env()
    monkeypatch.delenv("RADARR_URL")
    with client:
        html = client.get("/media/title/movie/603").text
    assert hook(html) is None and 'id="quality-block"' not in html


def test_quality_line_says_the_profile_and_offers_the_switch(film_env):
    client, _, arr = film_env()
    with client:
        frag = client.get("/media/title/movie/603/quality?back=/media/item/mov1", headers=HX).text
    assert '<div id="quality-block" class="qualityblock">' in frag
    assert '<p class="metaline">Quality · 1080p <a class="btn btn-secondary btn-sm" href="/media/item/mov1?quality_ask=1"' in frag
    assert 'hx-get="/media/title/movie/603/quality?step=confirm&back=/media/item/mov1"' in frag
    assert ">Switch to 4K</a>" in frag
    assert sorted(c[1] for c in arr.calls) == [f"{RADARR}/api/v3/movie", f"{RADARR}/api/v3/qualityprofile"]
    no_secrets(frag)


def test_a_4k_title_offers_the_way_back_to_the_default(film_env):
    client, _, arr = film_env()
    arr.series[0]["qualityProfileId"] = 8
    with client:
        frag = client.get("/media/title/tv/100/quality?back=/media/title/tv/100&tvdb=1100", headers=HX).text
    assert "Quality · 4K" in frag and ">Switch to 1080p</a>" in frag
    assert ("GET", f"{SONARR}/api/v3/series", {"tvdbId": 1100}, None) in arr.calls


@pytest.mark.parametrize("case", ["missing", "profiles"])
def test_quality_line_hidden_when_not_in_the_app_or_profiles_unknown(film_env, case):
    # JY-111 (2026-10-27): the third case, an old profile id the app no longer has, now draws a fallback line instead
    # (the tests below), so it left this list.
    client, _, arr = film_env()
    if case == "missing":
        arr.movies = []
    else:
        arr.profile_status = 503
    with client:
        r = client.get("/media/title/movie/603/quality?back=/media/title/movie/603", headers=HX)
    assert r.status_code == 200 and r.text == ""


def test_switch_confirm_step_is_an_inline_panel(film_env):
    client, _, arr = film_env()
    with client:
        frag = client.get("/media/title/movie/603/quality?step=confirm&back=/media/item/mov1", headers=HX).text
    assert '<form class="confirm" method="post" action="/media/title/movie/603/quality" hx-post="/media/title/movie/603/quality"' in frag
    assert '<input type="hidden" name="profile" value="9"><input type="hidden" name="back" value="/media/item/mov1">' in frag
    assert ("Switch Harbour Lights to 4K?" in frag and
            "Radarr will look for a 4K file and keep the 1080p one until it arrives." in frag)
    assert '<button class="btn btn-primary btn-sm" type="submit">Switch to 4K</button>' in frag
    assert '<a class="btn btn-ghost btn-sm" href="/media/item/mov1" hx-get="/media/title/movie/603/quality?back=/media/item/mov1"' in frag
    assert ">Switch to 4K</a>" not in frag                  # the button gives way to the panel
    assert "confirm(" not in frag


def test_switch_puts_the_profile_searches_and_redraws_the_line(film_env):
    client, _, arr = film_env()
    before = dict(arr.movies[0])
    with client:
        r = client.post("/media/title/movie/603/quality", data={"profile": "9", "back": "/media/item/mov1"}, headers=HX)
    (put,) = arr.of("PUT")
    assert put[1] == f"{RADARR}/api/v3/movie/11" and put[3] == {**before, "qualityProfileId": 9}
    assert [c[3] for c in arr.of("POST")] == [{"name": "MoviesSearch", "movieIds": [11]}]
    assert '<p class="metaline st-good" role="status">Switched to 4K · searching</p>' in r.text
    assert "Quality · 4K" in r.text and ">Switch to 1080p</a>" in r.text
    no_secrets(r.text)


def test_switch_without_js_redirects_with_a_flash(film_env):
    client, _, arr = film_env()
    with client:
        r = client.post("/media/title/movie/603/quality", data={"profile": "9", "back": "/media/item/mov1"},
                        follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/media/item/mov1?qswitch=switched&qk=movie&qp=9"
        page = client.get(r.headers["location"]).text
    assert '<p class="metaline st-good" role="status">Switched to 4K · searching</p>' in page


def test_switch_series_sends_series_search(film_env):
    client, _, arr = film_env()
    with client:
        client.post("/media/title/tv/100/quality", data={"profile": "8", "tvdb": "1100", "back": "/media/title/tv/100"},
                    headers=HX)
    assert [c[1] for c in arr.of("PUT")] == [f"{SONARR}/api/v3/series/21"]
    assert arr.of("PUT")[0][3]["qualityProfileId"] == 8
    assert [c[3] for c in arr.of("POST")] == [{"name": "SeriesSearch", "seriesId": 21}]


@pytest.mark.parametrize("setup, word", [
    (lambda a: setattr(a, "put_status", 500), "Radarr refused (HTTP 500)"),
    (lambda a: setattr(a, "raise_put", requests.ConnectionError), "Radarr unreachable"),
    (lambda a: setattr(a, "movies", []), "Not in Radarr"),
    (lambda a: setattr(a, "post_status", 503), "Switched to 4K · couldn&#39;t start the search"),
])
def test_switch_failures_are_words_and_logs_carry_no_url_or_key(film_env, caplog, setup, word):
    client, _, arr = film_env()
    setup(arr)
    with client, caplog.at_level(logging.WARNING):
        r = client.post("/media/title/movie/603/quality", data={"profile": "9", "back": "/media/item/mov1"}, headers=HX)
    assert r.status_code == 200 and word in r.text
    no_secrets(r.text + caplog.text)


def test_switch_to_an_unknown_profile_or_the_same_one(film_env):
    client, _, arr = film_env()
    with client:
        bad = client.post("/media/title/movie/603/quality", data={"profile": "4", "back": "/media/item/mov1"}, headers=HX)
        same = client.post("/media/title/movie/603/quality", data={"profile": "8", "back": "/media/item/mov1"}, headers=HX)
    assert "That quality is not offered" in bad.text and "st-warn" in bad.text
    assert "Already 1080p" in same.text and arr.of("PUT") == [] and arr.of("POST") == []


def test_switch_requires_same_origin(film_env):
    client, _, arr = film_env()
    with client:
        r = client.post("/media/title/movie/603/quality", data={"profile": "9"}, headers={"Origin": "https://evil.invalid"})
    assert r.status_code == 403 and arr.calls == []


def test_no_js_confirm_redirects_to_the_page_which_draws_the_panel(film_env):
    client, _, arr = film_env()
    with client:
        r = client.get("/media/title/movie/603/quality?step=confirm&back=/media/item/mov1", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/media/item/mov1?quality_ask=1"
        cancel = client.get("/media/title/movie/603/quality?back=/media/item/mov1", follow_redirects=False)
        assert cancel.headers["location"] == "/media/item/mov1"
        page = client.get("/media/item/mov1?quality_ask=1").text
    assert "Switch Harbour Lights to 4K?" in page and hook(page) is None
    assert '<form class="confirm" method="post" action="/media/title/movie/603/quality"' in page


def test_back_is_local_only(film_env):
    client, _, arr = film_env()
    with client:
        r = client.post("/media/title/movie/603/quality", data={"profile": "9", "back": "https://evil.invalid/x"},
                        follow_redirects=False)
    assert r.headers["location"].startswith("/media/title/movie/603?")


# ---- the Requests page ----

@pytest.fixture()
def rq(req_env, monkeypatch):
    def build():
        client, fake, snaps = req_env()
        fake.series[0]["qualityProfileId"] = 8      # Sonarr's 4K
        fake.movies[0]["qualityProfileId"] = 9
        fake.movies.append({"id": 8, "tmdbId": 1003, "title": "Desert Crossing", "monitored": True, "hasFile": True,
                            "qualityProfileId": 8})   # the default
        get = requests.get

        def with_profiles(url, *a, **k):
            if url == f"{trr.RADARR}/api/v3/qualityprofile":
                fake.calls.append(("GET", url, None, None))
                return R(R_PROFILES)
            if url == f"{trr.SONARR}/api/v3/qualityprofile":
                fake.calls.append(("GET", url, None, None))
                return R(S_PROFILES)
            return get(url, *a, **k)
        monkeypatch.setattr(requests, "get", with_profiles)
        return client, fake
    return build


def test_requests_page_draws_from_caches_and_reads_after_the_response(rq):
    client, fake = rq()
    with client:
        first = client.get("/media/requests").text            # caches empty: no chip; the reads run after it
        assert "<span class=\"badge\">4K</span>" not in first
        reads = sorted({(c[1], tuple(sorted((c[2] or {}).items()))) for c in fake.calls})
        assert (f"{trr.RADARR}/api/v3/qualityprofile", ()) in reads
        assert (f"{trr.RADARR}/api/v3/movie", (("tmdbId", 1001),)) in reads
        assert (f"{trr.RADARR}/api/v3/movie", (("tmdbId", 1003),)) in reads
        fake.calls.clear()
        second = client.get("/media/requests").text
    assert '<div class="row-title">Midnight Harbour (2025) <span class="badge">4K</span></div>' in second
    assert re.search(r'<div class="row-title">Night Ferry[^<]*<span class="badge">4K</span></div>', second)   # Sonarr's list
    assert not re.search(r'Desert Crossing[^<]*<span class="badge">', second)    # the default profile: nothing
    assert len(re.findall(r'<span class="badge">', second)) == 2
    assert not [c for c in fake.calls if c[1].endswith(("/qualityprofile", "/api/v3/movie"))]   # all kept now
    no_secrets(second)


def test_attach_never_calls_and_later_is_bounded(rq, monkeypatch):
    client, fake = rq()
    monkeypatch.setattr(media_quality, "LATER_MAX", 1)
    rows = [{"kind": "movie", "tmdb_id": 1001}, {"kind": "movie", "tmdb_id": 1003}, {"kind": "tv", "tmdb_id": 2002,
                                                                                      "tvdb_id": 82002}]
    media_quality.attach(rows)
    assert [r["quality"] for r in rows] == [None, None, None] and fake.calls == []
    job = media_quality.later(rows)
    assert job.plan == {"profiles": ["movie", "tv"], "films": [1001]}
    job()
    media_quality.attach(rows)
    assert rows[0]["quality"] == "4K" and fake.calls and len([c for c in fake.calls if c[1].endswith("/movie")]) == 1
    assert media_requests.kept("radarr", trr.RADARR, 1003, None) == (False, None)


def test_switch_api_returns_words_and_ok(film_env):
    client, _, arr = film_env()
    with client:
        assert media_quality.switch("movie", 603, 9) == ("Switched to 4K · searching", True)
        assert media_quality.switch("movie", 603, 9) == ("Already 4K", True)
        arr.movies = []
        assert media_quality.switch("movie", 603, 8) == ("Not in Radarr", False)


# ---- JY-110: the "4K" chip without the lag (films on the second view, shows after the 10-minute Sonarr list) ----

FILM, SHOW = {"kind": "movie", "tmdb_id": 1001}, {"kind": "tv", "tmdb_id": 2002, "tvdb_id": 82002}


def chip_of(fake, *rows):
    """attach on copies of `rows` -> each row's chip; attach itself never makes a call."""
    rows, n = [dict(r) for r in rows], len(fake.calls)
    media_quality.attach(rows)
    assert len(fake.calls) == n
    return [r["quality"] for r in rows]


def test_a_film_keeps_its_chip_when_the_lookups_drop_and_is_still_re_read(rq):
    client, fake = rq()
    with client:
        media_quality.later([FILM])()
        assert chip_of(fake, FILM) == ["4K"]
        media_requests.forget_lookups()            # any Joey write (a request, a Remove, a switch) or LOOKUP_TTL
        assert chip_of(fake, FILM) == ["4K"]       # was None until the read after the response: "second view"
        assert media_quality.later([FILM]).plan == {"profiles": [], "films": [1001]}   # still re-read after it
        fake.movies[0]["qualityProfileId"] = 8     # moved to the default outside Joey
        media_quality.later([FILM])()
        assert chip_of(fake, FILM) == [None]


def test_a_4k_film_request_has_its_chip_on_the_first_view(rq):
    client, fake = rq()
    fake.movies.append({"id": 12, "tmdbId": 1004, "title": "New Film", "monitored": True, "hasFile": False,
                        "qualityProfileId": 8})     # Radarr added it on the default: the safety net corrects it
    new = {"kind": "movie", "tmdb_id": 1004}
    with client:
        assert chip_of(fake, new) == [None]
        r = client.post("/media/title/movie/1004/request", content="profile=9", headers=FORM, follow_redirects=False)
        assert r.status_code == 303 and "quality=9" in r.headers["location"]
        assert [c[1] for c in fake.of("PUT")] == [f"{trr.RADARR}/api/v3/movie/12"]
        assert chip_of(fake, new) == ["4K"]


def test_a_4k_show_request_has_its_chip_without_waiting_for_the_sonarr_list(rq, sleeps):
    client, fake = rq()
    with client:
        media_quality.profiles("tv")
        media_season_state.refresh([])            # the list the page keeps, read before the request
        fake.series.append({"id": 30, "tvdbId": 83003, "tmdbId": 3003, "title": "New Show", "monitored": True,
                            "qualityProfileId": 7, "statistics": {"episodeFileCount": 0, "sizeOnDisk": 0}})
        new = {"kind": "tv", "tmdb_id": 3003, "tvdb_id": 83003}
        assert chip_of(fake, new) == [None]
        assert media_quality.ensure("tv", 3003, 8, 83003) == "set"
        assert chip_of(fake, new) == ["4K"]        # was None for up to TTL (10 min)
        assert media_season_state.later([(83003, 3003)]) is None   # no extra read: the list is still fresh


def test_a_show_sonarr_has_not_added_yet_makes_the_list_due(rq, sleeps):
    client, fake = rq()
    with client:
        media_quality.profiles("tv")
        media_season_state.refresh([])
        assert media_season_state.later([(84004, 4004)]) is None
        assert media_quality.ensure("tv", 4004, 8, 84004) == "notyet"
        assert media_season_state.later([(84004, 4004)]).plan["index"] is True   # the next page re-reads it


def test_a_switch_moves_the_chip_at_once(rq):
    client, fake = rq()
    with client:
        media_quality.profiles("tv"), media_quality.profiles("movie")
        media_season_state.refresh([])
        media_quality.later([FILM])()
        assert chip_of(fake, FILM, SHOW) == ["4K", "4K"]
        assert media_quality.switch("tv", 2002, 7, 82002)[1] is True
        assert media_quality.switch("movie", 1001, 8)[1] is True
        assert chip_of(fake, FILM, SHOW) == [None, None]


# ---- JY-111: a title on an old profile id gets a fallback Quality line with the switch ----

def test_old_profile_id_shows_unknown_profile_with_both_switch_buttons(film_env):
    client, _, arr = film_env()
    arr.movies[0]["qualityProfileId"] = 4                      # a pre-2026-10-06 id the app no longer has
    with client:
        frag = client.get("/media/title/movie/603/quality?back=/media/item/mov1", headers=HX).text
    assert '<p class="metaline">Quality · unknown profile ' in frag
    assert ('href="/media/item/mov1?quality_ask=1&amp;quality_profile=8"' in frag
            and 'hx-get="/media/title/movie/603/quality?step=confirm&profile=8&back=/media/item/mov1"' in frag)
    assert ">Switch to 1080p</a>" in frag and ">Switch to 4K</a>" in frag
    assert "<form" not in frag                                  # nothing is asked, and nothing written, on render
    assert arr.of("PUT") == [] and arr.of("POST") == []
    no_secrets(frag)


def test_old_profile_confirm_step_names_the_chosen_profile(film_env):
    client, _, arr = film_env()
    arr.movies[0]["qualityProfileId"] = 4
    with client:
        frag = client.get("/media/title/movie/603/quality?step=confirm&profile=9&back=/media/item/mov1", headers=HX).text
    assert 'name="profile" value="9"' in frag and "Switch Harbour Lights to 4K?" in frag
    assert "Radarr will look for a 4K file and keep what it has until it arrives." in frag
    assert "unknown profile ones" not in frag and "Switch to 1080p" not in frag      # one panel for the one profile chosen
    assert arr.of("PUT") == [] and arr.of("POST") == []


def test_old_profile_confirm_ignores_a_profile_that_is_not_offered(film_env):
    client, _, arr = film_env()
    arr.movies[0]["qualityProfileId"] = 4
    with client:
        frag = client.get("/media/title/movie/603/quality?step=confirm&profile=77&back=/media/item/mov1", headers=HX).text
    assert "<form" not in frag and ">Switch to 4K</a>" in frag


def test_old_profile_switch_writes_only_on_the_confirm_post_and_heals_the_line(film_env):
    client, _, arr = film_env()
    arr.movies[0]["qualityProfileId"] = 4
    with client:
        client.get("/media/title/movie/603/quality?back=/media/item/mov1", headers=HX)
        client.get("/media/title/movie/603/quality?step=confirm&profile=8&back=/media/item/mov1", headers=HX)
        assert arr.of("PUT") == [] and arr.of("POST") == []     # render and the confirm panel never write
        r = client.post("/media/title/movie/603/quality", data={"profile": "8", "back": "/media/item/mov1"}, headers=HX)
    (put,) = arr.of("PUT")
    assert put[3]["qualityProfileId"] == 8
    assert "Switched to 1080p · searching" in r.text and "Quality · 1080p" in r.text and "unknown profile" not in r.text
    assert ">Switch to 4K</a>" in r.text                       # healed: the ordinary line and switch


def test_old_profile_no_js_path_draws_the_panel_for_the_chosen_profile(film_env):
    client, _, arr = film_env()
    arr.movies[0]["qualityProfileId"] = 4
    with client:
        r = client.get("/media/title/movie/603/quality?step=confirm&profile=9&back=/media/item/mov1", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/media/item/mov1?quality_ask=1&quality_profile=9"
        page = client.get(r.headers["location"]).text
    assert "Switch Harbour Lights to 4K?" in page and arr.of("PUT") == []


def test_old_profile_on_a_show_works_the_same(film_env):
    client, _, arr = film_env()
    arr.series[0]["qualityProfileId"] = 3
    with client:
        frag = client.get("/media/title/tv/100/quality?back=/media/title/tv/100&tvdb=1100", headers=HX).text
    assert "Quality · unknown profile" in frag and ">Switch to 1080p</a>" in frag and ">Switch to 4K</a>" in frag


def test_a_known_profile_line_is_unchanged(film_env):
    client, _, arr = film_env()
    with client:
        frag = client.get("/media/title/movie/603/quality?back=/media/item/mov1", headers=HX).text
    assert "unknown profile" not in frag and "quality_profile" not in frag
