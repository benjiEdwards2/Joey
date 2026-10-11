"""F4b (2026-10-12): where "Upgrade available" renders — Movies / TV list rows (grid and list), Requests rows and the
Activity › Downloads "Upgrades" block — from the arr snapshot's `data.upgrades` only (no upstream call), and nothing
(no 500) for an older envelope without it. The film / show page and its "Search for upgrade" button:
test_media_upgrades_film.py."""
import importlib
import re

import pytest
from fastapi.testclient import TestClient

from tests.hub.conftest import main_raw as main_of
from tests.hub.helpers import JELLY, make_area, make_tile, shelf_area, write_envelope, write_registry

UP = {"radarr": [{"item_key": "tmdb:11", "title": "Alpha Film", "year": 2020, "arr_id": 7, "have": "WEBDL-720p",
                  "want": "Bluray-1080p", "poster": "radarr:7"},
                 {"item_key": "tmdb:99", "title": "Not In Library", "year": 2001, "arr_id": 8, "have": "DVD",
                  "want": None, "poster": None}],
      "sonarr": [{"item_key": "tvdb:7021", "title": "Echo Show", "arr_id": 3, "episodes": 3, "have": "SDTV",
                  "want": "WEB 1080p", "sample": "S01E02", "poster": "sonarr:3"},
                 {"item_key": "tvdb:7023", "title": "Golf Show", "arr_id": 4, "episodes": 1, "have": "HDTV-720p",
                  "want": "Bluray-1080p", "sample": "S02E01", "poster": None}],
      "totals": {"movies": 2, "episodes": 4, "series": 2}}
FILM_NOTE = "Upgrade available · WEBDL-720p → Bluray-1080p"
ECHO_NOTE = "Upgrade available · 3 episodes · SDTV → WEB 1080p"
GOLF_NOTE = "Upgrade available · 1 episode · HDTV-720p → Bluray-1080p"


def movie(title, year, key):
    return {"title": title, "year": year, "jf_id": "j" + key.replace(":", "-"), "item_key": key, "poster": None,
            "runtime_min": 100, "played": False, "added_at": "2024-01-01T00:00:00Z", "genres": []}


def show(title, key):
    return {"title": title, "year": 2020, "jf_id": "j" + key.replace(":", "-"), "item_key": key, "poster": None,
            "status_word": "Ended", "episodes": 4, "unplayed": 4, "played": False, "added_at": "2024-01-01T00:00:00Z",
            "genres": []}


MOVIES = [movie("Alpha Film", 2020, "tmdb:11"), movie("Bravo Film", 2022, "tmdb:12")]
SHOWS = [show("Echo Show", "tmdb:21"),             # Jellyfin keys it tmdb: - matched on its unique title
         show("Foxtrot Show", "tmdb:22"),
         show("Golf Show", "tvdb:7023")]           # keyed tvdb: - matched on the key


@pytest.fixture()
def site(tmp_path, monkeypatch):
    area = shelf_area()
    area["tiles"].append(make_tile("dl-t", snapshot="qbittorrent", stale_after_minutes=10, detail="/media/downloads"))
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, area, make_area("beta"))))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    for k in ("JELLYSEERR_URL", "JELLYSEERR_API_KEY", "RADARR_URL", "RADARR_API_KEY", "SONARR_URL", "SONARR_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    calls = []
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: calls.append(a) or pytest.fail("no upstream read"))
    monkeypatch.setattr(requests, "post", lambda *a, **k: calls.append(a) or pytest.fail("no upstream write"))

    def build(upgrades=UP, requests_rows=()):
        snaps = tmp_path / "snaps"
        write_envelope(snaps, "jellyfin", age_minutes=1, data={**JELLY, "movies": MOVIES, "shows": SHOWS})
        arr = {"summary": "x", **({"upgrades": upgrades} if upgrades is not None else {})}
        write_envelope(snaps, "arr", age_minutes=1, data=arr)
        write_envelope(snaps, "jellyseerr", age_minutes=1, data={"summary": "x", "requests": list(requests_rows)})
        write_envelope(snaps, "qbittorrent", age_minutes=1, data={"summary": "x", "active": []})
        import hub.main
        importlib.reload(hub.main)
        return TestClient(hub.main.app)
    return build


def notes(html):
    return re.findall(r'<(?:div|span|p) class="upnote">([^<]+)</', html)


def card_of(html, title):
    return html.split(f'<span class="row-title">{title}</span>', 1)[1].split("</a>", 1)[0]


# ---- Movies / TV list rows ----

def test_movie_grid_and_list_label_only_the_matching_title(site):
    with site() as c:
        grid = main_of(c.get("/media/movies?view=grid").text)
        lst = main_of(c.get("/media/movies?view=list").text)
    assert notes(grid) == [FILM_NOTE] and notes(lst) == [FILM_NOTE]
    assert f'<span class="upnote">{FILM_NOTE}</span>' in card_of(grid, "Alpha Film")      # inside the card's link
    assert "upnote" not in card_of(grid, "Bravo Film")
    row = lst.split("Alpha Film (2020)", 1)[1].split("</a>", 1)[0]
    assert f'<div class="upnote">{FILM_NOTE}</div>' in row
    assert "Search for upgrade" not in grid + lst                                          # no button in lists


def test_tv_list_matches_the_tvdb_key_and_the_unique_title(site):
    with site() as c:
        grid = main_of(c.get("/media/tv?view=grid").text)
        lst = main_of(c.get("/media/tv?view=list").text)
    for page in (grid, lst):
        assert sorted(notes(page)) == sorted([ECHO_NOTE, GOLF_NOTE])
    assert ECHO_NOTE in card_of(grid, "Echo Show") and GOLF_NOTE in card_of(grid, "Golf Show")
    assert "upnote" not in card_of(grid, "Foxtrot Show")


def test_a_cached_show_page_tvdb_bridges_a_renamed_show(site, monkeypatch):
    from hub import media_item
    monkeypatch.setattr(media_item, "peek", lambda jf: {"item": {"tvdb": "7021"}} if jf == "jtmdb-22" else None)
    up = {**UP, "sonarr": [{**UP["sonarr"][0], "title": "Something Else"}]}
    with site(upgrades=up) as c:
        grid = main_of(c.get("/media/tv?view=grid").text)
    assert ECHO_NOTE in card_of(grid, "Foxtrot Show") and "upnote" not in card_of(grid, "Echo Show")


@pytest.mark.parametrize("upgrades", [None, {"radarr": None, "sonarr": None, "totals": {}}])
def test_older_envelope_or_both_apps_down_renders_no_label(site, upgrades):
    with site(upgrades=upgrades) as c:
        for path in ("/media/movies?view=grid", "/media/movies?view=list", "/media/tv?view=grid", "/media/tv?view=list"):
            r = c.get(path)
            assert r.status_code == 200 and "upnote" not in main_of(r.text)


def test_the_css_token_is_light_blue_and_one_class():
    from pathlib import Path
    css = (Path(__file__).resolve().parents[2] / "hub" / "static" / "control-surface.css").read_text(encoding="utf-8")
    assert css.count("--upgrade:") == 1 and ":root { --upgrade: var(--sky); }" in css
    rule = re.search(r"\n\.upnote \{([^}]*)\}", css).group(1)
    assert "color: var(--upgrade)" in rule and "background" not in rule


# ---- Requests rows ----

REQS = [{"id": 1, "title": "Alpha Film", "year": 2020, "kind": "movie", "tmdb_id": 11, "item_key": "tmdb:11",
         "status_text": "Available", "href": "http://x.invalid/1", "poster": None, "when": "today"},
        {"id": 2, "title": "Renamed Echo", "year": 2019, "kind": "tv", "tmdb_id": 21, "tvdb_id": 7021,
         "item_key": "tmdb:21", "status_text": "Partly available", "href": "http://x.invalid/2", "poster": None},
        {"id": 3, "title": "Bravo Film", "year": 2022, "kind": "movie", "tmdb_id": 12, "item_key": "tmdb:12",
         "status_text": "Pending", "href": "http://x.invalid/3", "poster": None}]


def req_row(html, rid):
    return html.split(f'id="req-{rid}"', 1)[1].split('<details', 1)[0]


def test_request_rows_carry_the_line_by_tmdb_or_tvdb(site):
    with site(requests_rows=REQS) as c:
        b = main_of(c.get("/media/requests").text)
    assert f'<div class="upnote">{FILM_NOTE}</div>' in req_row(b, 1)
    assert f'<div class="upnote">{ECHO_NOTE}</div>' in req_row(b, 2)           # the request's tvdb_id bridges it
    assert "upnote" not in req_row(b, 3)


def test_request_rows_without_upgrades_render_plain(site):
    with site(upgrades=None, requests_rows=REQS) as c:
        r = c.get("/media/requests")
    assert r.status_code == 200 and "upnote" not in main_of(r.text)


# ---- Activity › Downloads: the Upgrades block ----

def upgrades_block(html):
    return html.split('<section class="sec" id="upgrades">', 1)[1].split("</section>", 1)[0]


def test_downloads_block_lists_titles_with_totals_and_links(site):
    with site() as c:
        blk = upgrades_block(main_of(c.get("/media/downloads").text))
    assert '<div class="seclabel">Upgrades</div>' in blk
    assert '<p class="metaline">2 films · 2 shows</p>' in blk
    assert f'<div class="upnote">{FILM_NOTE}</div>' in blk and ECHO_NOTE in blk and GOLF_NOTE in blk
    assert "Upgrade available · DVD" not in blk and "Upgrade available</div>" in blk   # unknown cutoff: no arrow part
    alpha = blk.split("Alpha Film (2020)", 1)[0].rsplit("<a ", 1)[1]
    assert 'href="/media/item/jtmdb-11"' in alpha                              # the Joey item page (library title)
    assert 'href="/media/title/movie/99"' in blk                               # not in the library: the title page
    assert 'href="/media/item/jtvdb-7023"' in blk                               # Golf Show: Jellyfin keys it tvdb:
    assert 'href="/media/item/jtmdb-21"' in blk                                 # Echo Show: matched on its title


def test_downloads_block_states(site):
    with site(upgrades=None) as c:
        b = main_of(c.get("/media/downloads").text)
    assert 'id="upgrades"' not in b                                            # an older arr envelope: no block
    with site(upgrades={"radarr": None, "sonarr": None, "totals": {}}) as c:
        blk = upgrades_block(main_of(c.get("/media/downloads").text))
    assert '<p class="metaline">Not connected</p>' in blk and "upnote" not in blk
    with site(upgrades={**UP, "sonarr": None}) as c:
        blk = upgrades_block(main_of(c.get("/media/downloads").text))
    assert '<p class="metaline">2 films · Sonarr not connected</p>' in blk
    with site(upgrades={"radarr": [], "sonarr": [], "totals": {"movies": 0, "episodes": 0, "series": 0}}) as c:
        blk = upgrades_block(main_of(c.get("/media/downloads").text))
    assert "0 films · 0 shows" in blk and '<p class="empty">Nothing to upgrade.</p>' in blk
