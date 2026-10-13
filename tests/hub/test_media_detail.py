"""Tiles that open a detail page (2026-10-05): the registry `detail` field, the
cardlink wrapper, and the /media/apps + /media/playing pages behind them.
Placement is asserted inside <main> — never by substring counts over the whole
HTML (a block once landed in {% block title %} and passed such a count).
"""
import importlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from hub.registry import load_registry
from tests.hub.helpers import make_area, make_tile, write_envelope, write_registry
from tests.hub.conftest import app_with, main_raw as main_of

JELLY_HREF = "http://nas.example.invalid:8096"
APPS = [
    {"id": "jellyfin", "name": "Jellyfin", "href": "http://nas.example.invalid:8096",
     "up": True, "status_text": "Up", "note": None},
    {"id": "prowlarr", "name": "Prowlarr", "href": "http://nas.example.invalid:9696",
     "up": False, "status_text": "Down", "note": "timeout"},
]
ADDED = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
PLAY = {
    "summary": "1 playing now",
    "now_playing": [{"title": "Harbour Lights", "user": "Sample Person",
                     "progress_pct": 42, "play_method": "Transcoding",
                     "poster": "jf:abc123", "backdrop": "jfb:abc123"}],
    "up_next": [{"title": "Dust and Daylight", "kind": "movie", "remaining_text": "31 min left",
                 "poster": "jf:def456", "backdrop": "jfb:def456"},
                {"title": "Quiet Coast · S02E05", "kind": "episode", "remaining_text": "Next episode"}],
    "latest": [{"title": "Desert Crossing", "added_at": ADDED, "type": "Movie", "poster": None}],
    "library": {"movies": 42, "episodes": 237},
}


@pytest.fixture()
def app_factory(tmp_path, monkeypatch):
    area = make_area("alpha", "play-t", snapshot="jellyfin", stale_after_minutes=10,
                     detail="/media/playing", owner="her")
    area["tiles"].append(make_tile("apps-t", snapshot="media_status", stale_after_minutes=10,
                                   detail="/media/apps"))
    area["tiles"].append({"id": "open-t", "label": "Open Jellyfin", "tier": "link",
                          "owner": "shared", "href": JELLY_HREF})
    return app_with(tmp_path, monkeypatch, area), tmp_path


def test_apps_page_lists_every_app_with_words_and_links(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "media_status", age_minutes=1, data={"summary": "1 of 2 up", "apps": APPS})
    with build(snaps) as client:
        resp = client.get("/media/apps")
    assert resp.status_code == 200
    assert "<title>Media apps" in resp.text
    body = main_of(resp.text)
    assert 'aria-current="page">Health' in body                 # restyle Phase 3: the tab names the page
    assert body.count('<span class="st-up">') + body.count('<span class="st-down">') == 2   # Server › Services' words (M-25)
    assert '<span class="st-up">Up</span>' in body and '<span class="st-down">Down</span>' in body
    assert 'href="http://nas.example.invalid:9696" target="_blank" rel="noopener"' in body
    assert "timeout" in body and "Updated 1m ago" in body
    assert "--accent" not in body                                   # restyle Phase 3: Media drops the area accent


def test_playing_page_sections_render_in_main(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "jellyfin", age_minutes=1, data=PLAY)
    with build(snaps) as client:
        resp = client.get("/media/playing")
    assert resp.status_code == 200
    title = resp.text.split("<title>", 1)[1].split("</title>", 1)[0]
    assert title.startswith("Now playing") and "<" not in title
    body = main_of(resp.text)
    assert '<div class="row-title">Harbour Lights</div>' in body
    assert 'Sample Person<span class="sep"> · </span>Transcoding<span class="sep"> · </span>42%' in body
    assert "width: 42%" in body
    assert f'href="{JELLY_HREF}"' in body                      # the area's LINK tile
    assert ">Up next</h2>" in body and "Dust and Daylight" in body and "Next episode" in body
    assert ">Latest additions</h2>" in body
    assert body.index("Desert Crossing") > body.index(">Latest additions</h2>")
    assert "3d ago" in body and ">Movie<" in body
    assert "Library: 42 movies · 237 episodes" in body


def test_pages_say_not_connected_without_snapshots(app_factory):
    build, tmp_path = app_factory
    with build(tmp_path / "empty") as client:
        for path in ("/media/apps", "/media/playing"):
            resp = client.get(path)
            assert resp.status_code == 200
            body = main_of(resp.text)
            assert "Not connected" in body and "appstate" not in body and "Up next" not in body


def test_pages_404_when_no_tile_reads_the_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv("AREAS_PATH", str(write_registry(tmp_path, make_area("alpha", snapshot="nas_stats"))))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as client:
        for path in ("/media/apps", "/media/playing", "/media/library"):
            resp = client.get(path)
            assert resp.status_code == 404 and "No page here" in resp.text


def test_detail_tile_is_a_cardlink_and_keeps_its_owner(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "jellyfin", age_minutes=1, data=PLAY)
    write_envelope(snaps, "media_status", age_minutes=1, data={"summary": "1 of 2 up", "apps": APPS})
    with build(snaps) as client:
        body = main_of(client.get("/a/alpha").text)
        assert '<a class="panel tile" href="/media/playing"' in body
        assert '<a class="panel tile" href="/media/apps"' in body
        assert body.count('<a class="panel tile" href="/media/') == 2
        card = body.split('<a class="panel tile" href="/media/playing"', 1)[1].split("</a>", 1)[0]
        assert 'data-owner="her"' in card and "1 playing now" in card
        # owner filtering still hides the her-owned detail card from "you"
        you = main_of(client.get("/a/alpha?owner_view=you").text)
        assert "/media/playing" not in you and "/media/apps" in you


def test_hub_summary_card_never_nests_a_second_link(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "jellyfin", age_minutes=1, data=PLAY)
    with build(snaps) as client:
        body = main_of(client.get("/").text)
    assert 'href="/a/alpha"' in body and "/media/playing" not in body


@pytest.mark.parametrize("bad", ["media/apps", "https://evil.example.invalid/x", "//evil.example.invalid"])
def test_registry_rejects_a_detail_not_starting_with_a_single_slash(tmp_path, bad):
    path = write_registry(tmp_path, make_area("alpha", detail=bad))
    with pytest.raises(ValueError, match="detail"):
        load_registry(path)


def test_registry_accepts_a_hub_route_detail(tmp_path):
    reg = load_registry(write_registry(tmp_path, make_area("alpha", detail="/media/apps")))
    assert reg.areas[0].tiles[0].detail == "/media/apps"


def test_playing_page_has_posters_and_a_backdrop_behind_now_playing(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "jellyfin", age_minutes=1, data=PLAY)
    with build(snaps) as client:
        body = main_of(client.get("/media/playing").text)
    assert 'src="/img/jf:abc123?h=120&amp;t=HA"' in body
    assert 'src="/img/jf:def456?h=120' in body
    assert 'class="pagehead-bd"' in body and "--bd: url(" in body and "/img/jfb%3Aabc123?h=1280" in body
    assert 'src="/img/none?h=120&amp;t=DE"' in body  # null ref -> fallback card
    assert "jfb:def456" not in body.split(">Up next</h2>", 1)[1]  # backdrop only behind now playing
