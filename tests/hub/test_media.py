"""Media area sections (2026-10-05): apps health, now playing, up next — rendered
on any area whose tiles read the media_status / jellyfin snapshots. Up/Down is a
WORD beside the dot (colour never the only encoding).
"""
import importlib
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from tests.hub.test_registry import make_area, make_tile
from tests.hub.test_store import write_envelope

JELLY_HREF = "http://nas.example.invalid:8096"

APPS = [
    {"id": "jellyfin", "name": "Jellyfin", "href": "http://nas.example.invalid:8096",
     "up": True, "status_text": "Up", "note": None},
    {"id": "prowlarr", "name": "Prowlarr", "href": "http://nas.example.invalid:9696",
     "up": False, "status_text": "Down", "note": "timeout"},
]
PLAY = {
    "summary": "1 playing now",
    "now_playing": [{"title": "Harbour Lights", "user": "Sample Person",
                     "progress_pct": 42, "play_method": "Transcoding"}],
    "up_next": [{"title": "Dust and Daylight", "kind": "movie", "remaining_text": "31 min left"}],
    "latest": [], "library": {"movies": 1, "episodes": 1},
}


@pytest.fixture()
def app_factory(tmp_path, monkeypatch):
    area = make_area("alpha", "play-t", snapshot="jellyfin", stale_after_minutes=10)
    area["tiles"].append(make_tile("apps-t", snapshot="media_status", stale_after_minutes=10))
    area["tiles"].append({"id": "open-t", "label": "Open Jellyfin", "tier": "link",
                          "owner": "shared", "href": JELLY_HREF})
    path = tmp_path / "areas.yaml"
    path.write_text(yaml.safe_dump({"areas": [area]}), encoding="utf-8")
    monkeypatch.setenv("AREAS_PATH", str(path))

    def build(snapshot_dir):
        monkeypatch.setenv("SNAPSHOT_DIR", str(snapshot_dir))
        import hub.main
        importlib.reload(hub.main)
        return TestClient(hub.main.app)

    return build, tmp_path


def test_apps_rows_show_up_down_words_and_link_out(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "media_status", age_minutes=1,
                   data={"summary": "1 of 2 up", "apps": APPS})
    with build(snaps) as client:
        html = client.get("/a/alpha").text
    assert '<span class="appstate">Up</span>' in html
    assert '<span class="appstate">Down</span>' in html
    assert 'href="http://nas.example.invalid:9696"' in html
    assert 'target="_blank" rel="noopener"' in html
    assert "timeout" in html
    assert "Now playing</div>" not in html  # no jellyfin snapshot -> no play section


def test_now_playing_and_up_next_rows(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "jellyfin", age_minutes=1, data=PLAY)
    with build(snaps) as client:
        html = client.get("/a/alpha").text
    assert "Harbour Lights · Sample Person · Transcoding · 42%" in html
    assert "width: 42%" in html
    assert f'href="{JELLY_HREF}"' in html  # the area's LINK tile
    assert "Dust and Daylight" in html and "31 min left" in html
    assert 'class="head">Apps<' not in html  # no media_status snapshot -> no apps section


def test_quiet_states_are_words(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "jellyfin", age_minutes=1,
                   data={"summary": "Nothing playing", "now_playing": [], "up_next": []})
    with build(snaps) as client:
        html = client.get("/a/alpha").text
    assert "Nothing playing" in html and "Nothing up next" in html


def test_stale_snapshot_still_renders_with_a_badge(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "media_status", age_minutes=300,
                   data={"summary": "x", "apps": APPS})
    with build(snaps) as client:
        html = client.get("/a/alpha").text
    assert "Prowlarr" in html and "badge stale" in html


def test_absent_snapshots_render_no_media_section(app_factory):
    build, tmp_path = app_factory
    with build(tmp_path / "empty") as client:
        html = client.get("/a/alpha").text
    assert "mediacols" not in html and "appstate" not in html


def test_hub_main_names_no_area_for_media():
    text = (Path(__file__).resolve().parents[2] / "hub" / "main.py").read_text(encoding="utf-8")
    assert "JELLYFIN_SNAPSHOT_ID" in text and "MEDIA_STATUS_SNAPSHOT_ID" in text
    assert '"media"' not in text.replace('"media": find_media', "")


def test_media_sections_render_in_the_page_body_not_the_title(app_factory):
    """2026-10-05 regression: the sections were emitted inside {% block title %}
    and vanished into the browser tab. Pin them to the body, after the grid."""
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "media_status", age_minutes=1,
                   data={"summary": "1 of 2 up", "apps": APPS})
    write_envelope(snaps, "jellyfin", age_minutes=1, data=PLAY)
    with build(snaps) as client:
        html = client.get("/a/alpha").text
    title = html.split("<title>", 1)[1].split("</title>", 1)[0]
    assert "<" not in title and "Apps" not in title
    body = html.split("<main", 1)[1]
    assert body.index('class="grid"') < body.index(">Apps<")
    assert ">Now playing</div>" in body and ">Up next</div>" in body
