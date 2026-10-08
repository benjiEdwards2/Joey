"""media-ux5 item 7 (2026-10-09): "All seasons + future" in the Discover title Request block (default for TV).
Ticked, the request goes to Jellyseerr as `"seasons": "all"` (seerr-api.yml POST /request: number[] | "all"), then the
series is looked up in Sonarr (<= 3 reads, 2 s apart), PUT back with monitored + monitorNewItems "all" (other fields
kept) and SeriesSearch is sent. Unticked, the ticked seasons go as before and Sonarr is not touched.
Jellyseerr is the Discover test fake; Sonarr is faked here at requests.get / put / post. No network, no real sleeps."""
import html as htmllib
import logging

import pytest
import requests

from hub import media_arr_search
from tests.hub.test_media_discover import env, FORM, HX, FAKE_KEY  # noqa: F401  (env is a fixture)

SONARR = "http://sonarr.secret-host.invalid:8989"
TKEY = "s-SECRET-sonarr-key"


class R:
    def __init__(self, body=None, code=200):
        self._b, self.status_code = body, code

    def json(self):
        return self._b


class Sonarr:
    def __init__(self):
        self.series = [{"id": 31, "tmdbId": 100, "tvdbId": 7100, "title": "Big Show", "monitored": False,
                        "monitorNewItems": "none", "path": "/tv/Big Show", "qualityProfileId": 4,
                        "seasons": [{"seasonNumber": 1, "monitored": True}]}]
        self.appear_after = 0          # reads that come back empty first (the series is not added yet)
        self.calls, self.raise_get, self.put_status, self.post_status = [], None, 202, 201

    def get(self, url, params=None, headers=None, timeout=None, **kw):
        assert headers == {"X-Api-Key": TKEY}
        self.calls.append(("GET", url, params, None))
        if self.raise_get:
            raise self.raise_get(f"{url}?apikey={TKEY}")
        if self.appear_after:
            self.appear_after -= 1
            return R([])
        return R(self.series)

    def put(self, url, json=None, headers=None, timeout=None, **kw):
        assert headers == {"X-Api-Key": TKEY}
        self.calls.append(("PUT", url, None, json))
        return R(json, self.put_status)

    def post(self, url, json=None, headers=None, timeout=None, **kw):
        assert headers == {"X-Api-Key": TKEY}
        self.calls.append(("POST", url, None, json))
        return R({"id": 1}, self.post_status)


@pytest.fixture()
def tv_env(env, monkeypatch):
    monkeypatch.setenv("SONARR_URL", SONARR)
    monkeypatch.setenv("SONARR_API_KEY", TKEY)
    sleeps = []
    monkeypatch.setattr(media_arr_search.time, "sleep", lambda s: sleeps.append(s))

    def build():
        client, fake = env()
        son = Sonarr()
        get, post = requests.get, requests.post
        mine = lambda url: str(url).startswith(SONARR)
        monkeypatch.setattr(requests, "get", lambda url, *a, **k: son.get(url, *a, **k) if mine(url) else get(url, *a, **k))
        monkeypatch.setattr(requests, "post", lambda url, *a, **k: son.post(url, *a, **k) if mine(url) else post(url, *a, **k))
        monkeypatch.setattr(requests, "put", son.put)
        return client, fake, son, sleeps
    return build


def seerr_posts(fake):
    return [j for u, j, _ in fake.posts if u.endswith("/api/v1/request")]


def test_confirm_step_offers_all_seasons_plus_future_ticked_first(tv_env):
    client, _, son, _ = tv_env()
    with client:
        confirm = client.get("/media/title/tv/100/request?step=confirm", headers=HX).text
    tag = '<label class="seasonall"><input type="checkbox" name="seasons" value="all" checked> All seasons + future'
    assert tag in confirm
    assert confirm.index('value="all"') < confirm.index('<div class="seasonpick">') < confirm.index('value="4"')
    assert son.calls == []


def test_movie_confirm_has_no_all_seasons(tv_env):
    client, _, _, _ = tv_env()
    with client:
        confirm = client.get("/media/title/movie/603/request?step=confirm", headers=HX).text
    assert "All seasons + future" not in confirm


def test_all_seasons_requests_all_then_sonarr_follows_and_searches(tv_env):
    client, fake, son, sleeps = tv_env()
    with client:
        r = client.post("/media/title/tv/100/request", content="seasons=all&seasons=4", headers={**HX, **FORM})
    assert seerr_posts(fake) == [{"mediaType": "tv", "mediaId": 100, "seasons": "all"}]
    gets = [c for c in son.calls if c[0] == "GET"]
    assert gets == [("GET", f"{SONARR}/api/v3/series", None, None)]          # matched on tmdbId in the full list
    put = [c for c in son.calls if c[0] == "PUT"]
    assert len(put) == 1 and put[0][1] == f"{SONARR}/api/v3/series/31"
    sent = put[0][3]
    assert sent["monitored"] is True and sent["monitorNewItems"] == "all"
    assert {k: v for k, v in sent.items() if k not in ("monitored", "monitorNewItems")} == \
        {k: v for k, v in son.series[0].items() if k not in ("monitored", "monitorNewItems")}   # other fields kept
    assert [c[3] for c in son.calls if c[0] == "POST"] == [{"name": "SeriesSearch", "seriesId": 31}]
    assert sleeps == []
    body = htmllib.unescape(r.text)
    assert "Requested ✓ — shows in Requests within the hour" in body
    assert '<p class="metaline st-good">Sonarr: every season monitored, new seasons too · search started</p>' in body


def test_individual_seasons_keep_todays_behaviour(tv_env):
    client, fake, son, _ = tv_env()
    with client:
        r = client.post("/media/title/tv/100/request", content="seasons=3&seasons=4", headers={**HX, **FORM})
    assert seerr_posts(fake) == [{"mediaType": "tv", "mediaId": 100, "seasons": [3, 4]}]
    assert son.calls == [] and "Sonarr" not in r.text


def test_series_not_in_sonarr_yet_retries_three_times_then_says_so(tv_env):
    client, fake, son, sleeps = tv_env()
    son.appear_after = 99
    with client:
        r = client.post("/media/title/tv/100/request", content="seasons=all", headers={**HX, **FORM})
    assert len([c for c in son.calls if c[0] == "GET"]) == 3 and sleeps == [2.0, 2.0]   # bounded: 3 reads, 2 s apart
    assert not [c for c in son.calls if c[0] in ("PUT", "POST")]
    assert "Requested ✓" in r.text
    assert "Sonarr hasn&#39;t added it yet — new seasons are not set to follow" in r.text
    assert 'class="metaline st-warn"' in r.text


def test_series_appearing_on_the_second_read_is_followed(tv_env):
    client, fake, son, sleeps = tv_env()
    son.appear_after = 1
    with client:
        client.post("/media/title/tv/100/request", content="seasons=all", headers={**HX, **FORM})
    assert len([c for c in son.calls if c[0] == "GET"]) == 2 and sleeps == [2.0]
    assert len([c for c in son.calls if c[0] == "PUT"]) == 1


def test_failed_jellyseerr_request_never_touches_sonarr(tv_env):
    client, fake, son, _ = tv_env()
    fake.post_status = 409
    with client:
        r = client.post("/media/title/tv/100/request", content="seasons=all", headers={**HX, **FORM})
    assert "Already requested" in r.text and son.calls == []


@pytest.mark.parametrize("fail, word", [
    ("get", "Couldn&#39;t set Sonarr to follow new seasons"),
    ("put", "Couldn&#39;t set Sonarr to follow new seasons"),
    ("post", "couldn&#39;t start the search"),
])
def test_sonarr_failures_are_sanitized_words(tv_env, caplog, fail, word):
    client, fake, son, _ = tv_env()
    if fail == "get":
        son.raise_get = requests.ConnectionError
    elif fail == "put":
        son.put_status = 500
    else:
        son.post_status = 503
    with caplog.at_level(logging.WARNING), client:
        r = client.post("/media/title/tv/100/request", content="seasons=all", headers={**HX, **FORM})
    assert "Requested ✓" in r.text and word in r.text
    for secret in (TKEY, "sonarr.secret-host", FAKE_KEY):
        assert secret not in caplog.text and secret not in r.text
    assert ("ConnectionError" if fail == "get" else "HTTP 500" if fail == "put" else "HTTP 503") in caplog.text


def test_sonarr_not_connected_is_noted(tv_env, monkeypatch):
    client, fake, son, _ = tv_env()
    monkeypatch.delenv("SONARR_URL")
    with client:
        r = client.post("/media/title/tv/100/request", content="seasons=all", headers={**HX, **FORM})
    assert seerr_posts(fake) == [{"mediaType": "tv", "mediaId": 100, "seasons": "all"}]
    assert "Sonarr is not connected — new seasons are not set to follow" in r.text and son.calls == []


def test_no_js_post_redirects_with_the_note_and_the_page_shows_it(tv_env):
    client, fake, son, _ = tv_env()
    with client:
        r = client.post("/media/title/tv/100/request", content="seasons=all", headers=FORM, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/media/title/tv/100?requested=1&future=set"
        page = htmllib.unescape(client.get(r.headers["location"]).text)
    assert "Requested ✓ — shows in Requests within the hour" in page
    assert "Sonarr: every season monitored, new seasons too · search started" in page


def test_unknown_future_code_shows_nothing(tv_env):
    client, _, _, _ = tv_env()
    with client:
        page = client.get("/media/title/tv/100?requested=1&future=<b>x").text
    assert "Requested ✓" in page and "&lt;b&gt;x" not in page and "<b>x" not in page


def test_cross_site_request_is_refused(tv_env):
    client, fake, son, _ = tv_env()
    with client:
        r = client.post("/media/title/tv/100/request", content="seasons=all",
                        headers={**FORM, "Origin": "https://evil.invalid"})
    assert r.status_code == 403 and fake.posts == [] and son.calls == []


def test_future_param_leaves_the_address_bar():
    import hub.main
    assert "future" in hub.main.FLASH_PARAMS
