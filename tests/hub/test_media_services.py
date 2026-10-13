"""media-ux2 item 4 (2026-10-08): browse by streaming service. A "Services" row on /media/discover (AU watch
providers matched by name, in the fixed SERVICES order) and /media/discover/service/{id} with four shelves.
`requests` is the test_media_discover Fake (nothing hits the network); the provider list is mocked."""
import logging
import re
from datetime import date

import requests
from fastapi.testclient import TestClient  # noqa: F401

from hub import media_discover as md
from tests.hub.conftest import main_of  # noqa: F401
from tests.hub.test_media_discover import env, assert_no_secrets, res, Resp  # noqa: F401  (env fixture)
from tests.hub.test_media_frame import current

AU_MOVIES = [
    {"id": 8, "name": "Netflix", "logoPath": "/netflix.jpg", "displayPriority": 1},
    {"id": 337, "name": "Disney Plus", "logoPath": "/disney.jpg", "displayPriority": 2},
    {"id": 119, "name": "Amazon Prime Video", "logoPath": "/prime.jpg", "displayPriority": 3},
    {"id": 350, "name": "Apple TV+", "logoPath": "/apple.jpg", "displayPriority": 4},        # "+" vs "Plus"
    {"id": 531, "name": "Paramount+", "logoPath": "/para.jpg", "displayPriority": 5},
    {"id": 21, "name": "STAN", "logoPath": "/stan.jpg", "displayPriority": 6},              # case
    {"id": 2, "name": "Apple TV", "logoPath": "/itunes.jpg", "displayPriority": 9},          # not wanted
    {"id": "x", "name": "Junk"}, {"name": "No id"},
]
AU_TV = [
    {"id": 8, "name": "Netflix", "logoPath": "/netflix.jpg"},                                 # duplicate id
    {"id": 385, "name": "BINGE", "logoPath": "/binge.jpg"},
    {"id": 82, "name": "7 plus", "logoPath": "/7plus.png"},                                   # spacing
    {"id": 76, "name": "9Now", "logoPath": None},
    {"id": 135, "name": "ABC iview", "logoPath": "/iview.jpg"},
]
FILMS = {"results": [res(11, "Service Film A", status=5, media="movie"), res(12, "Service Film B")]}
SHOWS = {"results": [{"id": 21, "name": "Service Show", "firstAirDate": "2025-02-02", "posterPath": "/s21.jpg",
                      "mediaInfo": {"status": 2}}]}


def wire(fake, movies=AU_MOVIES, tv=AU_TV, films=FILMS, shows=SHOWS):
    """Answer the provider lists and every discover-with-provider read (any sortBy / dates)."""
    fake.table["/api/v1/watchproviders/movies?watchRegion=AU"] = movies
    fake.table["/api/v1/watchproviders/tv?watchRegion=AU"] = tv
    plain = fake.get

    def get(url, headers=None, timeout=None, **kw):
        path = url.split(":5055", 1)[1]
        if "watchProviders=" in path and films is not None and path.startswith("/api/v1/discover/movies?"):
            fake.gets.append(path)
            return Resp(films)
        if "watchProviders=" in path and shows is not None and path.startswith("/api/v1/discover/tv?"):
            fake.gets.append(path)
            return Resp(shows)
        return plain(url, headers=headers, timeout=timeout, **kw)
    md.requests.get = get   # monkeypatched by the env fixture already, so undone after the test
    return fake


def tiles(html):
    sec = main_of(html).split(">Services</div>", 1)[1].split("</section>", 1)[0]
    return re.findall(r'<a class="prov-tile" href="([^"]+)">\s*<img class="prov-logo" src="([^"]+)"[^>]*>\s*'
                      r'<span class="prov-name">([^<]+)</span>', sec), sec


def test_norm_provider_is_tolerant_of_plus_case_and_spacing():
    n = md.norm_provider
    assert n("Apple TV+") == n("Apple TV Plus") == n("apple tv plus") == "appletvplus"
    assert n("7plus") == n("7 Plus") == n("7+") and n("Disney+") == n("Disney Plus")
    assert n("ABC iview") == n("abc  IVIEW") and n("Apple TV") != n("Apple TV+")


def test_services_row_order_names_logos_and_links(env, caplog):
    client, fake = env()
    wire(fake)
    with caplog.at_level(logging.INFO, logger="hub.media_discover"), client:
        html = client.get("/media/discover").text
        again = client.get("/media/discover").text
    got, sec = tiles(html)
    assert [g[2] for g in got] == ["Netflix", "Disney Plus", "Amazon Prime Video", "Stan", "Binge", "Apple TV Plus",
                                   "Paramount Plus", "ABC iview", "9Now", "7plus"]
    assert got[0][0] == "/media/discover/service/8" and got[0][1] == "/img/tmdb:/netflix.jpg?h=120&amp;t=NE"
    assert ("/media/discover/service/350", "/img/tmdb:/apple.jpg?h=120&amp;t=AP", "Apple TV Plus") in got
    assert got[8][1].startswith("/img/none?")                  # no logoPath -> the proxy's fallback card, name still shown
    assert "/service/2\"" not in sec                           # plain "Apple TV" is not on the list
    misses = [r.getMessage() for r in caplog.records if "not listed" in r.getMessage()]
    assert sorted(m.rsplit(": ", 1)[1] for m in misses) == ["Foxtel Now", "HBO Max", "SBS On Demand"]
    assert len(misses) == 3                                    # logged once, not per page render
    assert tiles(again)[0] == got
    assert fake.gets.count("/api/v1/watchproviders/movies?watchRegion=AU") == 1   # cached
    assert_no_secrets(html)


def test_services_row_unavailable_when_provider_list_fails(env):
    client, fake = env()      # no provider paths in the table -> 404 both
    with client:
        html = client.get("/media/discover").text
    sec = main_of(html).split(">Services</div>", 1)[1].split("</section>", 1)[0]
    assert "Unavailable" in sec and "prov-tile" not in sec
    assert ">Popular films</div>" in main_of(html)              # the rest of Discover still renders


def test_services_row_hidden_while_searching(env):
    client, fake = env()
    wire(fake)
    with client:
        html = client.get("/media/discover?q=heat").text
    assert ">Services</div>" not in html


def test_service_page_shelves_reuse_discover_cards(env):
    client, fake = env()
    wire(fake)
    with client:
        r = client.get("/media/discover/service/8")
    assert r.status_code == 200
    body = main_of(r.text)
    assert '<h2 class="prov-title">Netflix</h2>' in body and "/img/tmdb:/netflix.jpg?h=120" in body
    titles = re.findall(r'<div class="seclabel">([^<]+)</div>', body)
    assert titles == ["Popular films", "Popular TV", "New this month", "Top rated"]
    pop_films = body.split(">Popular films</div>", 1)[1].split("</section>", 1)[0]
    assert 'href="/media/title/movie/11"' in pop_films and "Service Film B" in pop_films
    assert "Available" in pop_films and 'class="card-cell"' in pop_films       # the Discover card + status word
    pop_tv = body.split(">Popular TV</div>", 1)[1].split("</section>", 1)[0]
    assert 'href="/media/title/tv/21"' in pop_tv and "Requested" in pop_tv
    new = body.split(">New this month</div>", 1)[1].split("</section>", 1)[0]
    order = re.findall(r'href="/media/title/(movie|tv)/(\d+)"', new)
    assert order == [("movie", "11"), ("tv", "21"), ("movie", "12")]            # films and TV interleaved
    assert 'action="/media/watchlist/add"' in pop_films                           # the existing + / Request flow
    sent = [p for p in fake.gets if "watchProviders=8" in p]
    assert all("watchRegion=AU" in p for p in sent) and len(sent) == 6
    assert any("sortBy=popularity.desc" in p and p.startswith("/api/v1/discover/tv?") for p in sent)
    assert any("sortBy=vote_average.desc&voteCountGte=200" in p for p in sent)
    assert any("primaryReleaseDateGte=" in p and "primaryReleaseDateLte=" in p for p in sent)
    assert any("firstAirDateGte=" in p and "sortBy=first_air_date.desc" in p for p in sent)
    assert_no_secrets(r.text)


def test_new_this_month_window_is_the_last_30_days():
    paths = md._service_paths(8, date(2026, 10, 8))["New this month"]
    assert "primaryReleaseDateGte=2026-09-08&primaryReleaseDateLte=2026-10-08" in paths[0][0]
    assert "firstAirDateGte=2026-09-08&firstAirDateLte=2026-10-08" in paths[1][0]


def test_failed_and_empty_shelves_degrade_to_words(env):
    client, fake = env()
    wire(fake, films=None, shows={"results": []})   # every film read 404s, TV reads come back empty
    with client:
        r = client.get("/media/discover/service/8")
    body = main_of(r.text)
    assert r.status_code == 200
    films = body.split(">Popular films</div>", 1)[1].split("</section>", 1)[0]
    tv = body.split(">Popular TV</div>", 1)[1].split("</section>", 1)[0]
    new = body.split(">New this month</div>", 1)[1].split("</section>", 1)[0]
    assert "Unavailable" in films and "Nothing to show right now" in tv
    assert "Nothing to show right now" in new                   # one half failed, the other empty: still a word


def test_shelves_are_cached_six_hours_and_failures_are_not(env, monkeypatch):
    client, fake = env()
    wire(fake)
    with client:
        client.get("/media/discover/service/8")
        n = len(fake.gets)
        client.get("/media/discover/service/8")
    assert len(fake.gets) == n
    path = next(p for p in md._cache if "watchProviders=8" in str(p))
    at, rows = md._cache[path]
    md._cache[path] = (at - md.SERVICE_TTL - 1, rows)
    assert md.SERVICE_TTL == 6 * 3600 and md.PROVIDER_TTL == 24 * 3600
    with client:
        client.get("/media/discover/service/8")
    assert path in fake.gets[n:]


def test_unknown_service_404_and_list_down_still_renders(env):
    client, fake = env()
    wire(fake)
    with client:
        assert client.get("/media/discover/service/999").status_code == 404
        assert client.get("/media/discover/service/0").status_code == 404
        assert client.get("/media/discover/service/abc").status_code == 422
    client, fake = env()
    wire(fake, movies=None, tv=None)
    fake.table.pop("/api/v1/watchproviders/movies?watchRegion=AU")
    fake.table.pop("/api/v1/watchproviders/tv?watchRegion=AU")
    md.clear_meta(disk=True)   # the first client's provider list sits in the disk meta cache
    with client:
        r = client.get("/media/discover/service/8")
    assert r.status_code == 200 and "Streaming service" in r.text and "Service Film A" in r.text


def test_service_page_failure_never_500(env):
    client, fake = env()
    wire(fake)
    with client:
        client.get("/media/discover")             # provider list cached

    def boom(url, headers=None, timeout=None, **kw):
        raise requests.ConnectionError(url)
    md.requests.get = boom
    with client:
        r = client.get("/media/discover/service/8")
    assert r.status_code == 200 and r.text.count("Unavailable") == 4
    assert_no_secrets(r.text)


def test_service_page_sits_under_discover_in_the_nav(env):
    client, fake = env()
    wire(fake)
    with client:
        html = client.get("/media/discover/service/8").text
    assert current(html, "sectabs sectabs-page") == ["Discover"]
    assert current(html, "sectabs sub") == ["Discover"]


def test_404_without_discover_tile_makes_no_call(env):
    from tests.hub.helpers import make_area
    client, fake = env(areas=[make_area("beta")])
    with client:
        assert client.get("/media/discover/service/8").status_code == 404
    assert fake.gets == []


def test_not_connected_page_makes_no_call(env):
    client, fake = env(connected=False)
    with client:
        r = client.get("/media/discover/service/8")
    assert r.status_code == 200 and "Not connected<" in r.text and fake.gets == []


def test_service_tiles_have_their_own_classes_not_the_server_cards():
    """The Server page owns .svc-* (WP-U3); the streaming-service tiles use .prov-* so neither restyles the other,
    and a tile name wraps instead of being cut off."""
    from pathlib import Path
    css = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
    assert css.count(".svc-logo {") == 1 and css.count(".svc-name {") == 1
    name = css.split(".prov-name {", 1)[1].split("}", 1)[0]
    assert "nowrap" not in name and "overflow-wrap: anywhere" in name
