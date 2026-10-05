"""Shelves layout (2026-10-05): registry `layout: shelves` -> hero + poster shelves.
build_shelves is exercised directly (pure over tiles/snapshots/ratings DB) and via the route.
Placement is asserted inside <main>."""
import importlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from hub.registry import load_registry
from tests.hub.test_registry import make_area, make_tile, write_registry
from tests.hub.test_store import write_envelope

LINK = "http://nas.example.invalid:8096"
NOW = datetime.now(timezone.utc)
RECENT = [
    {"title": "Harbour Lights", "item_key": "m1", "kind": "movie", "poster": "jf:1",
     "when": "yesterday", "watched_at": (NOW - timedelta(days=1)).isoformat()},
    {"title": "Rated One", "item_key": "m2", "kind": "movie", "poster": None,
     "when": "2 days ago", "watched_at": (NOW - timedelta(days=2)).isoformat()},
    {"title": "Old One", "item_key": "m3", "kind": "movie", "poster": None,
     "when": "long ago", "watched_at": (NOW - timedelta(days=90)).isoformat()},
]
JELLY = {
    "summary": "1 playing now",
    "now_playing": [{"title": "Playing Now Title", "user": "Sample Person", "progress_pct": 42,
                     "play_method": "Transcoding", "poster": "jf:np", "backdrop": "jfb:np"}],
    "up_next": [{"title": "Dust and Daylight", "remaining_text": "31 min left", "poster": None,
                 "item_key": "u1"}],
    "latest": [{"title": "Fresh Film", "item_key": "dup", "poster": "jf:f",
                "added_at": (NOW - timedelta(days=1)).isoformat()}],
    "history": {"recent": RECENT},
}
ARR = {"summary": "x", "arrived": [{"title": "Fresh Film", "item_key": "dup", "when": "today"},
                                   {"title": "Arr Only", "item_key": "a1", "when": "today"}]}
SEERR = {"summary": "x", "requests": [{"title": "Wanted", "item_key": "r1", "status_text": "Pending",
                                       "href": "http://x.invalid"}]}
APPS = [{"id": "j", "name": "Jellyfin", "href": "http://a.invalid", "up": True, "status_text": "Up", "note": None},
        {"id": "p", "name": "Prowlarr", "href": "http://b.invalid", "up": False, "status_text": "Down", "note": "t"}]


def shelf_area(layout="shelves"):
    area = make_area("alpha", "play-t", snapshot="jellyfin", stale_after_minutes=10, detail="/media/playing")
    area["layout"] = layout
    t = area["tiles"]
    t.append(make_tile("lib-t", snapshot="arr", stale_after_minutes=180, detail="/media/library"))
    t.append(make_tile("req-t", snapshot="jellyseerr", stale_after_minutes=180, detail="/media/requests"))
    t.append(make_tile("apps-t", snapshot="media_status", stale_after_minutes=10, detail="/media/apps"))
    t.append(make_tile("hist-t", snapshot="jellyfin", stale_after_minutes=10, detail="/media/history", owner="you"))
    t.append(make_tile("diary-t", snapshot="jellyfin", stale_after_minutes=10, detail="/media/diary", owner="you"))
    t.append(make_tile("years-t", snapshot="jellyfin", stale_after_minutes=10, detail="/media/years", owner="you"))
    t.append({"id": "open-t", "label": "Open Jellyfin", "tier": "link", "owner": "shared", "href": LINK})
    return area


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
        area = next(a for a in main.registry.areas if a.id == "alpha")
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


def test_shelf_order_dedupe_and_torate(env):
    main = env(jellyfin=JELLY, arr=ARR, jellyseerr=SEERR)
    from hub import media_db
    media_db.set_rating("m2", 8, "movie", "Rated One")
    sh = shelves_for(main)
    assert ids(sh) == ["continue", "added", "watched", "torate", "requests", "years"]  # a rating makes a year tile
    by = {s["id"]: s for s in sh["shelves"]}
    assert [i["title"] for i in by["added"]["items"]] == ["Fresh Film", "Arr Only"]  # deduped by key
    assert [i["title"] for i in by["torate"]["items"]] == ["Harbour Lights"]  # rated + >30d excluded
    assert by["torate"]["items"][0]["sub"].startswith("Rate")
    assert by["watched"]["items"][1]["score"] == 8
    assert by["requests"]["items"][0]["sub"] == "Pending"
    assert by["continue"]["see_all_href"] == "/media/playing"


def test_years_shelf_when_ranked(env):
    main = env(jellyfin=JELLY)
    from hub import media_db
    media_db.set_rating("m2", 8, "movie", "Rated One", year=2024)
    sh = shelves_for(main)
    years = next(s for s in sh["shelves"] if s["id"] == "years")
    assert years["items"][0]["title"] == "2024" and "to place" in years["items"][0]["sub"]


def test_her_view_drops_owner_you_shelves(env):
    sh = shelves_for(env(jellyfin=JELLY, arr=ARR, jellyseerr=SEERR), view="her")
    assert ids(sh) == ["continue", "added", "requests"]
    assert sh["hero"] is not None


def test_quiet_words_without_data(env):
    sh = shelves_for(env())
    assert ids(sh) == ["continue", "added", "watched", "requests"]
    assert {s["id"]: s["quiet_text"] for s in sh["shelves"]}["continue"] == "Nothing up next"
    assert all(not s["items"] for s in sh["shelves"]) and sh["hero"] is None
    assert sh["freshness"]["state"] == "off" and not sh["has_apps"]


def test_route_renders_hero_shelves_and_apps(env):
    main = env(jellyfin=JELLY, arr=ARR, jellyseerr=SEERR, media_status={"summary": "x", "apps": APPS})
    with TestClient(main.app) as client:
        html = main_html(client.get("/a/alpha").text)
    assert 'class="hero hasbackdrop"' in html and "Playing now" in html and "Playing Now Title" in html
    assert html.count('<section class="shelf"') == 5
    assert 'href="/media/library">See all' in html
    assert "Media apps — 1 of 2 up" in html and "Down Prowlarr" in html
    assert 'class="grid"' not in html
    assert f'href="{LINK}" target="_blank" rel="noopener"' in html


def test_route_no_snapshots_is_quiet(env):
    with TestClient(env().app) as client:
        r = client.get("/a/alpha")
    html = main_html(r.text)
    assert r.status_code == 200
    assert "Nothing is playing or queued" in html and "Nothing up next" in html and "No requests" in html
    assert "Media apps — Not connected" in html and "Not connected" in html
    assert "hasbackdrop" not in html


def test_route_her_view(env):
    with TestClient(env(jellyfin=JELLY).app) as client:
        html = main_html(client.get("/a/alpha?owner_view=her").text)
    assert 'class="hero' in html and "Recently watched" not in html and "Continue watching" in html


def test_grid_area_unaffected(env):
    with TestClient(env().app) as client:
        html = main_html(client.get("/a/beta").text)
    assert 'class="grid"' in html and 'class="hero' not in html
