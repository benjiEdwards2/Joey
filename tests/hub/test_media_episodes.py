"""Episode list on TV pages (2026-10-08): the tiny numbered squares became a readable list — per season a
collapsible <details> (the page's / next episode's season open) with "Season 4 · 3 of 6 watched"; per episode one
whole-row link with a 16:9 still, "E3 · Name", air date · runtime, a state word + colour and the Play / Resume deep
link beside it. And the Seasons section sits directly under Overview on TV pages. Jellyfin + Jellyseerr faked."""
import html as htmllib
import logging
import re
from pathlib import Path

import pytest
import requests

from hub import media_arr_search, media_film
from tests.hub import helpers as tmi
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.helpers import deep, env, ep, ITEMS, FakeResponse as R, SHOW, TICKS  # noqa: F401
from tests.hub.test_media_discover import env as discover_env, FAKE_KEY, FORM, HX  # noqa: F401


CSS = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")


def timed(monkeypatch):
    """The fixture episodes with runtimes (45 min) — ep4 is 5 min in, so 40 min left."""
    eps = [{**e, "RunTimeTicks": 45 * TICKS} for e in tmi.EPISODES]
    monkeypatch.setattr(tmi, "EPISODES", eps)
    return eps


def section(body, label):
    return body.split(f'<div class="seclabel">{label}</div>', 1)[1].split('<section class="sec', 1)[0]


def ep_row(body, n):
    return body.split(f'id="ep-ep{n}">', 1)[1].split('<div class="row has-form epline', 1)[0]


def test_each_episode_is_a_big_whole_row_link_with_still_state_and_play(env, monkeypatch):
    timed(monkeypatch)
    client, _ = env()
    with client:
        b = main_of(client.get("/media/item/ser1").text)
    seasons = section(b, "Seasons")
    assert "Season 4 · 3 of 6 watched" in re.sub(r"<[^>]+>", "", seasons)
    four = ep_row(seasons, 4)
    link = four.split('<a class="rowlink" href="/media/item/ep4">', 1)[1].split("</a>", 1)[0]
    assert '<img class="epstill" src="/img/jf:ep4?h=240&amp;t=FO"' in link
    assert ">E4 · Four</div>" in link and "45m" in link
    assert '<div class="epstate st-progress">In progress · 40m left</div>' in link
    assert "<a " not in link and "Resume" not in link                     # the deep link is beside the row
    after = four.split("</a>", 1)[1]
    assert f'href="{deep("ep4")}" target="_blank" rel="noopener">Resume ▶ · 40m left</a>' in after
    assert '<div class="epstate st-good">Watched</div>' in ep_row(seasons, 1) and "Play again ▶" in ep_row(seasons, 1)
    assert '<div class="epstate st-todo">Not watched</div>' in ep_row(seasons, 5) and ">Play ▶</a>" in ep_row(seasons, 5)
    six = ep_row(seasons, 6)
    assert '<div class="epstate st-off">Not aired</div>' in six and "▶" not in six   # nothing to play yet
    assert re.search(r"E1 · One</div>\s*<div class=\"row-meta\">\d{1,2} \w{3} \d{4} · 45m</div>", seasons)


def test_squares_and_their_legend_are_gone(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/item/ser1").text)
    assert "Squares in order" not in b and 'class="epmap"' not in b and '<a class="ep' not in b
    assert ".epmap" not in CSS


def test_the_next_episodes_season_is_open_by_default(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/item/ser1").text)
    assert '<details class="seasonbox epseason" id="season-4" open>' in b   # media-ux3: each season has an anchor


def test_no_anchor_inside_a_row_title(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/item/ser1").text)
    for title in re.findall(r'<div class="row-title">(.*?)</div>', section(b, "Seasons"), re.S):
        assert "<a" not in title


def test_episode_list_open_rules():
    eps = [{"jf_id": "a", "played": True, "in_progress": False, "aired": True}]
    seasons = [{"number": 1, "name": "Season 1", "episodes": eps, "watched_text": "1 of 1 watched"},
               {"number": 2, "name": "Season 2", "episodes": eps, "watched_text": "1 of 1 watched"},
               {"number": 3, "name": "Season 3", "episodes": eps, "watched_text": "1 of 1 watched"}]
    opened = lambda out: [s["n"] for s in out if s["open"]]
    assert opened(media_film.episode_list(seasons, None, None, {"season": 2})) == [2]      # next episode's season
    assert opened(media_film.episode_list(seasons, None, 1, {"season": 2})) == [1]         # the page's episode wins
    assert opened(media_film.episode_list(seasons, None, None, None)) == [3]               # all watched: the latest
    assert media_film.episode_list([], None) == []
    out = media_film.episode_list(seasons, lambda i: f"deep:{i}")
    assert out[0]["episodes"][0]["play"] == {"href": "deep:a", "label": "Play again ▶"}
    assert "open" not in seasons[0] and "play" not in eps[0]                               # the cache is never touched


def test_episode_state_words():
    s = media_film.episode_state
    assert s({"played": True})["word"] == "Watched"
    assert s({"in_progress": True, "left_min": 23})["word"] == "In progress · 23m left"
    assert s({"in_progress": True})["word"] == "In progress"
    assert s({"aired": False})["word"] == "Not aired"
    assert s({"aired": True})["word"] == "Not watched"


def test_rows_are_tall_and_phone_friendly():
    assert re.search(r"\.epline \{ min-height: 64px; \}", CSS)
    assert "aspect-ratio: 16 / 9" in CSS.split(".epline .epstill", 1)[1].split("}", 1)[0]
    phone = CSS.split("@media (max-width: 480px) {\n  .epline .epstill", 1)
    assert len(phone) == 2 and "width: 96px" in phone[1].split("}", 1)[0]


# ---- Item E: Seasons directly under Overview on TV pages ----

def test_tv_page_order_overview_seasons_then_where_to_watch(env):
    client, both = env()
    both.seerr.table["/api/v1/tv/100"] = {**SHOW, "overview": "A quiet show.",
                                         "watchProviders": [{"iso_3166_1": "AU", "flatrate": [{"name": "Stan"}]}],
                                         "credits": {"cast": [{"name": "Ada Actor", "character": "Lead"}]}}
    with client:
        b = main_of(client.get("/media/item/ser1").text)
    idx = {k: b.index(f'<div class="seclabel">{k}</div>') for k in ("Overview", "Seasons", "Cast", "Where to watch")}
    assert idx["Overview"] < idx["Seasons"] < idx["Cast"] < idx["Where to watch"]
    between = b[idx["Overview"]:idx["Seasons"]]
    assert '<div class="seclabel">' not in between.split("</div>", 1)[1]               # nothing in between


def test_off_server_tv_title_keeps_seasons_under_overview(env):
    client, both = env()
    both.seerr.table["/api/v1/tv/555"] = {**SHOW, "id": 555, "name": "Far Show", "overview": "Far away.",
                                         "mediaInfo": {"status": 1},
                                         "watchProviders": [{"iso_3166_1": "AU", "flatrate": [{"name": "Stan"}]}]}
    with client:
        b = main_of(client.get("/media/title/tv/555").text)
    o, s, w = (b.index(f'<div class="seclabel">{k}</div>') for k in ("Overview", "Seasons", "Where to watch"))
    assert o < s < w


def test_film_page_order_is_unchanged(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/title/movie/603").text)
    assert '<div class="seclabel">Seasons</div>' not in b
    o, f, w = (b.index(f'<div class="seclabel">{k}</div>') for k in ("Overview", "File", "Where to watch"))
    assert o < f < w


# ---- merged from test_media_ux4_episode.py ----
# media-ux4 items 5 / 5b / 5c (2026-10-08): an episode page's hero carries no "Episode of <Show>" line (the part-of
# banner under the hero is the way to the show), only the EPISODE's Play button (the series-level "Next to watch" /
# "Play" stays on the series page), and a watched toggle that reflects and acts on the episode itself.


def hero(html):
    return html.split('<header class="pagehead hero-detail">', 1)[1].split("</header>", 1)[0]


# ---- item 5: no "Episode of" line ----

def test_episode_hero_has_no_episode_of_line_but_keeps_the_rest(env):
    client, _ = env()
    with client:
        h = hero(client.get("/media/item/ep3").text)
        b = main_of(client.get("/media/item/ep3").text)
    assert "Episode of" not in h and 'href="/media/item/ser1"' not in h
    assert "S04E03 · Penny for Your Thoughts" in h and "Coins go missing." in h and "Quiet Show (2020)" in h
    assert 'href="/media/item/ser1#seasons"' in b                     # the banner still leads to the show


# ---- item 5b: one Play button on an episode page ----

def plays(h):
    btns = h.split('<div class="hero-detail-btns">', 1)[1]
    return re.findall(r'<a class="btn [^"]*" href="([^"]+)" target="_blank" rel="noopener">([^<]*▶[^<]*)</a>', btns)


def test_episode_page_renders_only_the_episodes_play(env):
    client, _ = env()
    with client:
        h = hero(client.get("/media/item/ep3").text)
    assert plays(h) == [(deep("ep3"), "Play again ▶")]
    assert "Next to watch" not in h


def test_episode_page_of_a_fully_watched_show_has_no_series_play(env, monkeypatch):
    from tests.hub import helpers as tmi
    monkeypatch.setattr(tmi, "EPISODES", [tmi.ep(i, f"E{i}", True) for i in range(1, 4)])
    client, _ = env()
    with client:
        h = hero(client.get("/media/item/ep3").text)
    assert [label for _, label in plays(h)] == ["Play again ▶"]                    # not the series' plain "Play ▶"
    assert 'class="btn btn-white"' in h.split('<div class="hero-detail-btns">', 1)[1]


def test_series_page_keeps_its_next_to_watch(env):
    client, _ = env()
    with client:
        h = hero(client.get("/media/item/ser1").text)
    assert [label for _, label in plays(h)] == ["Next to watch: S4 E4 ▶"]


# ---- merged from test_media_ux5_all_seasons.py ----
# media-ux5 item 7 (2026-10-09): "All seasons + future" in the Discover title Request block (default for TV).
# Ticked, the request goes to Jellyseerr as `"seasons": "all"` (seerr-api.yml POST /request: number[] | "all"), then the
# series is looked up in Sonarr (<= 3 reads, 2 s apart), PUT back with monitored + monitorNewItems "all" (other fields
# kept) and SeriesSearch is sent. Unticked, the ticked seasons go as before and Sonarr is not touched.
# Jellyseerr is the Discover test fake; Sonarr is faked here at requests.get / put / post. No network, no real sleeps.


SONARR = "http://sonarr.secret-host.invalid:8989"
TKEY = "s-SECRET-sonarr-key"


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
def tv_env(discover_env, monkeypatch):
    monkeypatch.setenv("SONARR_URL", SONARR)
    monkeypatch.setenv("SONARR_API_KEY", TKEY)
    sleeps = []
    monkeypatch.setattr(media_arr_search.time, "sleep", lambda s: sleeps.append(s))

    def build():
        client, fake = discover_env()
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
