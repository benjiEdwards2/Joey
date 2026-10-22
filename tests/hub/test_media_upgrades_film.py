"""F4b (2026-10-12): the film / show page says "Upgrade available · <have> → <want>" under the status line, inline in
the hero core from the arr snapshot (no upstream call - F2's fast page stays fast), and the lazy Search-now fragment
adds "Search for upgrade" (inline confirm, then a same-origin POST sending MoviesSearch / SeriesSearch on the app's
own id). Jellyfin + Jellyseerr are the film-page fakes; Radarr / Sonarr the Search-now fakes. No network.
Re-pointed WP-U1 (2026-10-21): the label reads "Below cutoff · <have> → wants <want>"."""
import html as htmllib
import logging

import pytest
import requests

from tests.hub.conftest import main_of
from tests.hub.helpers import env  # noqa: F401
from tests.hub.test_media_discover_search_now import HX, RADARR, RKEY, SONARR, TKEY, arr_env  # noqa: F401

UP = {"radarr": [{"item_key": "tmdb:603", "title": "Harbour Lights", "year": 2019, "arr_id": 11, "have": "WEBDL-720p",
                  "want": "Bluray-1080p", "poster": "radarr:11"}],
      "sonarr": [{"item_key": "tvdb:1100", "title": "Quiet Show", "arr_id": 21, "episodes": 3, "have": "SDTV",
                  "want": "WEB 1080p", "sample": "S04E01", "poster": "sonarr:21"}],
      "totals": {"movies": 1, "episodes": 3, "series": 1}}
FILM_NOTE = "Below cutoff · WEBDL-720p → wants Bluray-1080p"
SHOW_NOTE = "Below cutoff · 3 episodes · SDTV → wants WEB 1080p"


def hero(html):
    return html.split('<header class="pagehead hero-detail">', 1)[1].split("</header>", 1)[0]


# ---- the hero line ----

@pytest.mark.parametrize("path", ["/media/item/mov1", "/media/title/movie/603"])
def test_film_hero_line_under_the_status_line_with_no_arr_call(arr_env, path):
    client, both, arr = arr_env(arr={"upgrades": UP})
    with client:
        h = hero(client.get(path).text)
    status = h.index('<span id="status-line">')
    assert h.index(f'<p class="upnote">{FILM_NOTE}</p>') > status
    assert arr.calls == []                                                   # the page itself never calls the apps


def test_show_hero_matches_by_title_or_by_tvdb(arr_env, monkeypatch):
    from tests.hub import helpers
    client, _, arr = arr_env(arr={"upgrades": UP})
    with client:
        assert SHOW_NOTE in hero(client.get("/media/item/ser1").text)       # Jellyfin keys it tmdb:100 - unique title
    renamed = {**UP, "sonarr": [{**UP["sonarr"][0], "title": "Another Name"}]}
    client, _, arr = arr_env(arr={"upgrades": renamed})
    with client:
        assert "upnote" not in hero(client.get("/media/item/ser1").text)
    monkeypatch.setitem(helpers.ITEMS["ser1"], "ProviderIds", {"Tmdb": "100", "Tvdb": "1100"})
    client, _, arr = arr_env(arr={"upgrades": renamed})
    with client:
        assert SHOW_NOTE in hero(client.get("/media/item/ser1").text)       # ProviderIds.Tvdb bridges it
    assert arr.calls == []


@pytest.mark.parametrize("arr", [{}, {"upgrades": {"radarr": None, "sonarr": None, "totals": {}}},
                                 {"upgrades": {**UP, "radarr": []}}])
def test_no_upgrade_no_line_and_no_500(arr_env, arr):
    client, _, _ = arr_env(arr=arr)
    with client:
        r = client.get("/media/item/mov1")
    assert r.status_code == 200 and "upnote" not in main_of(r.text) and "upnote" not in hero(r.text)


def test_episode_page_has_no_line(arr_env):
    client, _, _ = arr_env(arr={"upgrades": UP})
    with client:
        assert "upnote" not in hero(client.get("/media/item/ep3").text)


# ---- the button (the lazy Search-now fragment) ----

def test_fragment_adds_the_upgrade_confirm_for_a_listed_film(arr_env):
    client, _, arr = arr_env(arr={"upgrades": UP})
    with client:
        frag = client.get("/media/title/movie/603/arr?back=/media/item/mov1", headers=HX).text
    assert "Search now</button>" in frag
    up = frag.split('<details class="confirm-wrap" id="arr-upgrade">', 1)[1]
    assert "Search for upgrade</summary>" in up and "Ask Radarr for a better copy?" in up and FILM_NOTE in up
    assert ('<form method="post" action="/media/title/movie/603/upgrade">'
            '<input type="hidden" name="back" value="/media/item/mov1">') in up
    assert ">Search for upgrade</button>" in up and ">Cancel</button>" in up
    assert [c[0] for c in arr.calls] == ["GET"]                              # the lookup only: nothing sent yet


def test_fragment_has_no_upgrade_button_when_the_entry_is_not_listed(arr_env):
    client, _, arr = arr_env(arr={"upgrades": {**UP, "radarr": [{**UP["radarr"][0], "arr_id": 99}]}})
    with client:
        frag = client.get("/media/title/movie/603/arr?back=/media/item/mov1", headers=HX).text
    assert "Search now</button>" in frag and "arr-upgrade" not in frag
    client, _, arr = arr_env(arr={})
    with client:
        frag = client.get("/media/title/movie/603/arr", headers=HX).text
    assert "Search now</button>" in frag and "arr-upgrade" not in frag


def test_show_fragment_matches_on_the_sonarr_id_and_carries_tvdb(arr_env):
    client, _, arr = arr_env(arr={"upgrades": {**UP, "sonarr": [{**UP["sonarr"][0], "item_key": "tvdb:5"}]}})
    with client:
        frag = client.get("/media/title/tv/100/arr?tvdb=1100&back=/media/item/ser1", headers=HX).text
    up = frag.split('id="arr-upgrade"', 1)[1]
    assert 'action="/media/title/tv/100/upgrade"' in up and '<input type="hidden" name="tvdb" value="1100">' in up
    assert "Ask Sonarr for a better copy?" in up and SHOW_NOTE in up


# ---- the POST ----

def test_upgrade_post_sends_movies_search_and_flashes(arr_env):
    client, _, arr = arr_env(arr={"upgrades": UP})
    with client:
        r = client.post("/media/title/movie/603/upgrade", data={"back": "/media/item/mov1"}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/media/item/mov1?upgrade=started"
        page = client.get(r.headers["location"]).text
    assert arr.commands() == [(f"{RADARR}/api/v3/command", {"name": "MoviesSearch", "movieIds": [11]})]
    assert '<p class="metaline st-good" role="status">Upgrade search started</p>' in page


def test_upgrade_post_sends_series_search_by_tvdb(arr_env):
    client, _, arr = arr_env(arr={"upgrades": UP})
    with client:
        r = client.post("/media/title/tv/100/upgrade", data={"tvdb": "1100", "back": "/media/item/ser1"},
                        follow_redirects=False)
    assert r.headers["location"] == "/media/item/ser1?upgrade=started"
    assert ("GET", f"{SONARR}/api/v3/series", {"tvdbId": 1100}, None) in arr.calls
    assert arr.commands() == [(f"{SONARR}/api/v3/command", {"name": "SeriesSearch", "seriesId": 21})]


def test_upgrade_post_failure_is_a_word_and_the_log_is_sanitized(arr_env, caplog):
    client, _, arr = arr_env(arr={"upgrades": UP})
    arr.raise_post = requests.ConnectionError
    with caplog.at_level(logging.WARNING), client:
        r = client.post("/media/title/movie/603/upgrade", data={"back": "/media/item/mov1"}, follow_redirects=False)
        page = htmllib.unescape(client.get(r.headers["location"]).text)
    assert r.headers["location"] == "/media/item/mov1?upgrade=failed"
    assert '<p class="metaline st-warn" role="status">Couldn\'t start the search</p>' in page
    assert "radarr upgrade search failed: ConnectionError" in caplog.text
    for secret in (RKEY, TKEY, "secret-host"):
        assert secret not in caplog.text and secret not in r.headers["location"]


def test_upgrade_post_not_in_app_or_unset_sends_nothing(arr_env, monkeypatch):
    client, _, arr = arr_env(arr={"upgrades": UP})
    arr.movies = []
    with client:
        r = client.post("/media/title/movie/603/upgrade", data={}, follow_redirects=False)
    assert r.headers["location"] == "/media/title/movie/603?upgrade=failed" and arr.commands() == []
    monkeypatch.delenv("RADARR_URL")
    with client:
        r = client.post("/media/title/movie/603/upgrade", data={}, follow_redirects=False)
    assert r.headers["location"] == "/media/title/movie/603?upgrade=failed" and arr.commands() == []


def test_upgrade_post_is_same_origin_only_and_back_stays_local(arr_env):
    client, _, arr = arr_env(arr={"upgrades": UP})
    with client:
        bad = client.post("/media/title/movie/603/upgrade", data={}, headers={"Origin": "https://evil.invalid"},
                          follow_redirects=False)
        assert bad.status_code == 403 and arr.commands() == []
        off = client.post("/media/title/movie/603/upgrade", data={"back": "https://evil.invalid/x"},
                          follow_redirects=False)
    assert off.headers["location"] == "/media/title/movie/603?upgrade=started"
