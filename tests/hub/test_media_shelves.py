"""Shelves layout (2026-10-05): registry `layout: shelves` -> hero + poster shelves.
build_shelves is exercised directly (pure over tiles/snapshots/ratings DB) and via the route.
Placement is asserted inside <main>."""
import importlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from hub.registry import load_registry
from tests.hub.conftest import main_raw as main_of
from tests.hub.helpers import (  # noqa: F401
    ARR, JELLY, LINK, make_area, make_tile, NOW, RECENT, SEERR_REQUESTS as SEERR, shelf_area, TODAY,
    write_envelope, write_registry)
from tests.hub.test_media_frame import env as frame_env  # noqa: F401


APPS = [{"id": "j", "name": "Jellyfin", "href": "http://a.invalid", "up": True, "status_text": "Up", "note": None},
        {"id": "p", "name": "Prowlarr", "href": "http://b.invalid", "up": False, "status_text": "Down", "note": "t"}]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, shelf_area(), make_area("beta"))))
    monkeypatch.setenv("MEDIA_DB_PATH", str(tmp_path / "media.db"))
    snaps = tmp_path / "snaps"
    monkeypatch.setenv("SNAPSHOT_DIR", str(snaps))

    def build(**data):
        for cid, d in data.items():
            write_envelope(snaps, cid, age_minutes=1, data=d)
        import hub.main
        importlib.reload(hub.main)
        return hub.main

    return build


def shelves_for(main, view="you"):
    with TestClient(main.app):  # lifespan loads the registry
        area = next(a for a in main.shell.registry.areas if a.id == "alpha")
        snaps = main.get_snapshots()
        tiles = [{"tile": t, "st": main.tile_state(t, snaps)} for t in area.tiles if main.owner_visible(t, view)]
        return main.build_shelves(area, tiles, snaps, view)


def ids(sh):
    return [s["id"] for s in sh["shelves"]]


def main_html(html):
    return html.split("<main", 1)[1]


def test_layout_defaults_to_grid(tmp_path):
    assert load_registry(write_registry(tmp_path, make_area("a"))).areas[0].layout == "grid"
    assert load_registry(write_registry(tmp_path, shelf_area())).areas[0].layout == "shelves"


def test_real_registry_media_is_shelves():
    reg = load_registry("config/areas.yaml")
    assert next(a for a in reg.areas if a.id == "media").layout == "shelves"


def test_hero_prefers_now_playing_then_up_next_then_none(env):
    sh = shelves_for(env(jellyfin=JELLY))
    assert sh["hero"]["kind_word"] == "Playing now" and sh["hero"]["title"] == "Playing Now Title"
    assert sh["hero"]["href"] == LINK
    sh = shelves_for(env(jellyfin={**JELLY, "now_playing": []}))
    assert sh["hero"]["kind_word"] == "Up next" and sh["hero"]["sub"] == "31 min left"
    sh = shelves_for(env(jellyfin={**JELLY, "now_playing": [], "up_next": []}))
    assert sh["hero"] is None and sh["kind_word"] == "Nothing playing"


def test_shelf_order_dedupe_and_new_shelves(env):
    main = env(jellyfin=JELLY, arr=ARR, jellyseerr=SEERR)
    from hub import media_db
    media_db.set_rating("m2", 8, "movie", "Rated One")
    sh = shelves_for(main)
    assert ids(sh) == ["continue", "added", "downloading"]  # media-ux2: This week + Recently watched left Media home
    by = {s["id"]: s for s in sh["shelves"]}
    assert [i["title"] for i in by["added"]["items"]] == ["Fresh Film", "Arr Only"]  # deduped by key
    assert by["downloading"]["items"][0]["sub"] == "Downloading · 12 min"
    assert by["continue"]["see_all_href"] == "/media/playing"


def test_downloading_shelf_omitted_when_empty_this_week_quiet(env):
    sh = shelves_for(env(jellyfin=JELLY, arr={**ARR, "downloading": [], "this_week": []}))
    assert "downloading" not in ids(sh)
    assert "thisweek" not in ids(sh)  # media-ux2: This week + Recently watched left Media home


def test_her_view_drops_owner_you_shelves(env):
    sh = shelves_for(env(jellyfin=JELLY, arr=ARR, jellyseerr=SEERR), view="her")
    assert ids(sh) == ["continue", "added", "downloading"]  # media-ux2: This week + Recently watched left Media home
    assert sh["hero"] is not None


def test_quiet_words_without_data(env):
    sh = shelves_for(env())
    assert ids(sh) == ["continue", "added"]  # media-ux2: This week + Recently watched left Media home
    assert {s["id"]: s["quiet_text"] for s in sh["shelves"]}["continue"] == "Nothing up next"
    assert all(not s["items"] for s in sh["shelves"]) and sh["hero"] is None
    assert sh["freshness"]["state"] == "off"


def test_route_renders_hero_and_trimmed_shelves(env):
    main = env(jellyfin=JELLY, arr=ARR, jellyseerr=SEERR, media_status={"summary": "x", "apps": APPS})
    with TestClient(main.app) as client:
        html = main_html(client.get("/a/alpha").text)
    # Restyle Phase 3: "Playing now" is the page header (eyebrow, title, drifting backdrop); shelves are sections.
    assert 'class="pagehead-bd hero-drift"' in html and ">Playing now<" in html and "<h1>Playing Now Title</h1>" in html
    assert html.count('<section class="sec">') == 3   # continue, added, downloading (media-ux2)
    assert 'href="/media/library">All' in html
    assert "Due Show" not in html and "Fetching Film" in html
    assert "Media apps" not in html and "Requests</h3>" not in html and "By year</h3>" not in html
    assert 'class="grid"' not in html
    assert f'href="{LINK}" target="_blank" rel="noopener"' in html


def test_route_no_snapshots_is_quiet(env):
    with TestClient(env().app) as client:
        r = client.get("/a/alpha")
    html = main_html(r.text)
    assert r.status_code == 200
    assert "Nothing playing" in html and "Nothing up next" in html and "Nothing due this week" not in html
    assert "Not connected" in html
    assert "hasbackdrop" not in html


def test_route_her_view(env):
    with TestClient(env(jellyfin=JELLY).app) as client:
        html = main_html(client.get("/a/alpha?owner_view=her").text)
    assert 'class="pagehead' in html and "Recently watched" not in html and "Continue watching" in html


def test_grid_area_unaffected(env):
    with TestClient(env().app) as client:
        html = main_html(client.get("/a/beta").text)
    assert 'class="tiles areatiles"' in html and "hero-drift" not in html


# ---- deep-linked rows + "waiting on you" chips (2026-10-05) ----

def deep(jf_id, server="srv-1"):
    return f"{LINK}/web/#/details?id={jf_id}&serverId={server}"


def linked_jelly():
    return {**JELLY, "server_id": "srv-1",
            "up_next": [{**JELLY["up_next"][0], "jf_id": "resume-id"}],
            "latest": [{**JELLY["latest"][0], "jf_id": "new-id"}],
            "history": {"recent": [{**RECENT[0], "jf_id": "hist-id"}, *RECENT[1:]]}}


def test_rows_open_their_item_page_when_they_carry_a_jf_id(env):
    by = {s["id"]: s["items"] for s in shelves_for(env(jellyfin=linked_jelly(), arr=ARR))["shelves"]}
    assert by["continue"][0]["href"] == "/media/item/resume-id" and "external" not in by["continue"][0]
    assert by["added"][0]["href"] == "/media/item/new-id" and "external" not in by["added"][0]
    assert "watched" not in by  # media-ux2: This week + Recently watched left Media home
    # arr-only arrivals keep the library page
    arr_only = next(i for i in by["added"] if i["title"] == "Arr Only")
    assert arr_only["href"] == "/media/library" and "external" not in arr_only


def test_rows_fall_back_to_joey_pages_without_ids_or_a_jellyfin_link(env):
    by = {s["id"]: s["items"] for s in shelves_for(env(jellyfin=JELLY, arr=ARR))["shelves"]}
    assert by["continue"][0]["href"] == "/media/playing"
    assert by["added"][0]["href"] == "/media/library"
    assert not any("external" in i for items in by.values() for i in items)


def test_no_jellyfin_link_tile_means_no_external_rows(env, tmp_path):
    main = env(jellyfin=linked_jelly())
    with TestClient(main.app):
        area = next(a for a in main.shell.registry.areas if a.id == "alpha")
        snaps = main.get_snapshots()
        tiles = [{"tile": t, "st": main.tile_state(t, snaps)} for t in area.tiles if t.tier != "link"]
        sh = main.build_shelves(area, tiles, snaps, "you")
    assert not any("external" in i for s in sh["shelves"] for i in s["items"])


def test_item_rows_stay_in_joey_and_the_hero_keeps_the_jellyfin_link(env):
    main = env(jellyfin=linked_jelly(), arr=ARR)
    with TestClient(main.app) as client:
        html = main_html(client.get("/a/alpha").text)
    assert '<a class="card-poster" href="/media/item/resume-id">' in html  # same tab, no target
    assert '<a class="card-poster" href="/media/library">' in html   # media-ux2: was a Recently watched row
    assert f'href="{LINK}" target="_blank" rel="noopener">Open in Jellyfin' in html  # hero stays external


def test_waiting_counts_and_chips_on_the_area_page_and_hub(env):
    main = env(jellyfin=JELLY, arr=ARR)
    from hub import media_db
    media_db.set_rating("m2", 8, "movie", "Rated One", year=2024)
    sh = shelves_for(main)
    assert sh["waiting"] == {"to_rate": 1}                       # decision 1: no "to place" count
    with TestClient(main.app) as client:
        area_html = main_html(client.get("/a/alpha").text)
        hub_html = main_html(client.get("/").text)
    assert '<span class="badge badge-wait">1 to rate</span>' in area_html
    assert "to place" not in area_html
    assert '<span class="badge badge-wait">1 to rate</span>' in hub_html


def test_waiting_chips_absent_at_zero_and_for_hidden_tiles(env):
    main = env(jellyfin={**JELLY, "history": {"recent": []}})
    assert shelves_for(main)["waiting"] == {"to_rate": 0}
    with TestClient(main.app) as client:
        assert "badge-wait" not in main_html(client.get("/a/alpha").text)
    main = env(jellyfin=JELLY)
    assert shelves_for(main, view="her")["waiting"] == {"to_rate": 0}


# ---- merged from test_media_home_trim.py ----
# media-ux2 item 7 (2026-10-08): Media home drops the "This week" and "Recently watched" shelves. The data stays:
# Server -> Library keeps its This week rows and Diary > To rate (/media/history) keeps Recently watched.


def test_media_home_has_no_this_week_or_recently_watched(frame_env):
    main = frame_env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        home = main_of(c.get("/a/alpha").text)
    assert ">This week" not in home and "Recently watched" not in home
    assert "Due Show" not in home and "Nothing due this week" not in home and "poster-tag" not in home
    assert "Harbour Lights" not in home                       # a Recently watched row
    assert ">Continue watching" in home and ">Recently added" in home


def test_the_data_still_shows_where_it_lives(frame_env):
    main = frame_env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        lib = main_of(c.get("/media/library").text)
        hist = main_of(c.get("/media/history").text)
    assert ">This week" in lib
    assert ">Recently watched</div>" in hist and "Harbour Lights" in hist


# ---- media-ux2 item 8 (2026-10-08): the Joey hub page (/) drops Continue watching; Media keeps it ----

def test_hub_page_has_no_continue_watching_but_media_home_does(frame_env):
    main = frame_env(jellyfin=JELLY, arr=ARR)
    with TestClient(main.app) as c:
        hub_page = main_of(c.get("/").text)
        home = main_of(c.get("/a/alpha").text)
    assert "Continue watching" not in hub_page and 'id="continue"' not in hub_page
    assert 'id="recent"' in hub_page and "Recently watched" in hub_page   # the hub's own band stays
    assert ">Continue watching" in home and "Dust and Daylight" in home
