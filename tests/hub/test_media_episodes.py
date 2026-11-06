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
from tests.hub.film_page import whole
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
    return body.split(f'<h2 class="seclabel">{label}</h2>', 1)[1].split('<section class="sec', 1)[0]


def ep_row(body, n):
    return body.split(f'id="ep-ep{n}">', 1)[1].split('<div class="row has-form epline', 1)[0]


def tile(body, n):
    return body.split(f'id="tl-ep-ep{n}">', 1)[1].split('<div class="tl-ep ', 1)[0]


# JY-290 (B. 2026-11-02): the bottom Seasons list is gone; its episode rows are the Episodes row's tiles (JY-269 P2)
def test_each_episode_is_a_whole_tile_link_with_still_state_and_play(env, monkeypatch):
    timed(monkeypatch)
    client, _ = env()
    with client:
        b = main_of(client.get("/media/item/ser1").text)
    eps = b.split('<section class="sec tl-eps"', 1)[1].split("</section>", 1)[0]
    assert "3 of 6 watched" in re.sub(r"<[^>]+>", "", eps)
    four = tile(eps, 4)
    link = four.split('<a class="tl-eplink" href="/media/item/ep4"', 1)[1].split("</a>", 1)[0]
    assert 'src="/img/jf:ep4?h=240&amp;t=FO"' in link
    assert ">E4 · Four</span>" in link and "45m" in link
    assert '<span class="epstate st-progress">In progress · 40m left</span>' in link
    assert "<a " not in link and "Resume" not in link                     # the deep link is under the tile
    after = four.split("</a>", 1)[1]
    assert f'href="{deep("ep4")}" target="_blank" rel="noopener">Resume ▶ · 40m left</a>' in after
    assert '<span class="epstate st-good">Watched</span>' in tile(eps, 1) and "Play again ▶" in tile(eps, 1)
    assert '<span class="epstate st-todo">Not watched</span>' in tile(eps, 5) and ">Play ▶</a>" in tile(eps, 5)
    six = tile(eps, 6)
    assert '<span class="epstate st-off">Not aired</span>' in six and "▶" not in six   # nothing to play yet
    assert 'id="seasons"' not in b and "seasonbox" not in b


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
    assert '<a class="chip on" href="/media/item/sea1" aria-current="true">' in b   # JY-290: the Episodes row lights it


def test_no_anchor_inside_a_row_title(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/item/ser1").text)
    for title in re.findall(r'<span class="row-title">(.*?)</span>', b.split('<section class="sec tl-eps"', 1)[1].split("</section>", 1)[0], re.S):
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
        b = main_of(whole(client, "/media/item/ser1"))
    # JY-290 + JY-282 (2026-11-03): no Overview section (synopsis once, in the hero); no bottom Seasons list.
    # JY-316 r4 (2026-11-06): the Episodes row comes full width first; cast and where to watch sit beside the sidebar under it
    assert '<h2 class="seclabel">Overview</h2>' not in b and b.count("A quiet show.") == 1
    idx = {k: b.index(f'<h2 class="seclabel">{k}</h2>') for k in ("Episodes", "Cast")}
    assert idx["Episodes"] < idx["Cast"] < b.index('aria-label="Where to watch"')   # JY-281: the JY-286 logo row
    assert '<h2 class="seclabel">Seasons</h2>' not in b


def test_off_server_tv_title_keeps_seasons_under_overview(env):
    client, both = env()
    both.seerr.table["/api/v1/tv/555"] = {**SHOW, "id": 555, "name": "Far Show", "overview": "Far away.",
                                         "mediaInfo": {"status": 1},
                                         "watchProviders": [{"iso_3166_1": "AU", "flatrate": [{"name": "Stan"}]}]}
    with client:
        b = main_of(client.get("/media/title/tv/555").text)
    # JY-282: no Overview section; the synopsis is in the hero, once
    assert '<h2 class="seclabel">Overview</h2>' not in b and b.count("Far away.") == 1
    assert b.index('<h2 class="seclabel">Seasons</h2>') < b.index('aria-label="Where to watch"')   # JY-281: logo row


def test_film_page_order_is_unchanged(env):
    client, _ = env()
    with client:
        b = main_of(client.get("/media/title/movie/603").text)
    assert '<h2 class="seclabel">Seasons</h2>' not in b
    # JY-280: a film's one overview is in the hero; the body leads with the cast
    assert '<h2 class="seclabel">Overview</h2>' not in b
    # JY-280 P2 (2026-11-03): the where-to-watch logos under the cast; the File drawer in the right column after them
    c, w, f = (b.index(k) for k in ('<h2 class="seclabel">Cast</h2>', 'id="fp-providers"', "File details</summary>"))
    assert c < w < f


# ---- merged from test_media_ux4_episode.py ----
# media-ux4 items 5 / 5b / 5c (2026-10-08): an episode page's hero carries no "Episode of <Show>" line (the part-of
# banner under the hero is the way to the show), only the EPISODE's Play button (the series-level "Next to watch" /
# "Play" stays on the series page), and a watched toggle that reflects and acts on the episode itself.


def hero(html):
    return html.split('<header class="pagehead hero-detail">', 1)[1].split("</header>", 1)[0]


# ---- item 5: no "Episode of" line ----

def test_episode_hero_carries_the_crumbs_and_position_and_keeps_the_rest(env):
    """media-ux4 dropped the "Episode of <Show>" line; the TV episode flow (2026-10-16) puts crumbs in the hero instead:
    the show (all seasons) and the season are the two ways back, and the eyebrow says where the episode sits."""
    client, _ = env()
    with client:
        h = hero(client.get("/media/item/ep3").text)
        b = main_of(client.get("/media/item/ep3").text)
    assert "Episode of" not in h
    assert '<nav class="crumbs"' in h and 'href="/media/item/ser1">' in h and 'href="/media/item/sea1">Season 4</a>' in h
    assert "E3 of 6" in h
    assert ">Penny for Your Thoughts</h1>" in h and "Coins go missing." in h and "Quiet Show" in h   # JY-315: show in the eyebrow
    assert 'href="/media/item/ser1"' in b and "#seasons" not in b     # the banner still leads to the show (JY-290: no anchor)


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


def test_confirm_step_offers_all_seasons_plus_future_unticked_first(tv_env):
    client, _, son, _ = tv_env()
    with client:
        confirm = client.get("/media/title/tv/100/request?step=confirm", headers=HX).text
    tag = '<label class="seasonall"><input type="checkbox" name="seasons" value="all"> All seasons + future'
    assert tag in confirm
    assert confirm.index('value="all"') < confirm.index('<div class="seasonpick">') < confirm.index('value="4"')
    assert 'value="all" checked' not in confirm and "checked" not in confirm.split('<div class="seasonpick">')[1]
    assert "onchange=" in confirm
    assert tmi.not_quality(son.calls) == []   # WP-R1: the confirm step reads the quality profiles


def test_all_plus_specific_season_prefers_the_specific_season(tv_env):
    client, fake, son, _ = tv_env()
    with client:
        client.post("/media/title/tv/100/request", content="seasons=all&seasons=3", headers={**HX, **FORM})
    assert seerr_posts(fake) == [{"mediaType": "tv", "mediaId": 100, "seasons": [3]}]
    assert [c for c in son.calls if c[0] == "PUT"] == []


def test_only_all_still_means_all(tv_env):
    client, fake, _, _ = tv_env()
    with client:
        client.post("/media/title/tv/100/request", content="seasons=all", headers={**HX, **FORM})
    assert seerr_posts(fake) == [{"mediaType": "tv", "mediaId": 100, "seasons": "all"}]


def test_movie_confirm_has_no_all_seasons(tv_env):
    client, _, _, _ = tv_env()
    with client:
        confirm = client.get("/media/title/movie/603/request?step=confirm", headers=HX).text
    assert "All seasons + future" not in confirm


def test_all_seasons_requests_all_then_sonarr_follows_and_searches(tv_env):
    client, fake, son, sleeps = tv_env()
    with client:
        r = client.post("/media/title/tv/100/request", content="seasons=all", headers={**HX, **FORM})
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
