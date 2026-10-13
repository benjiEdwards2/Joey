"""Media Phase 4a — the /media/history page, rendered from the history block of the jellyfin snapshot (the area
"Recently watched" strip was removed 2026-10-09, decision 2). Placement is asserted inside <main>.
"""
import importlib
import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from tests.hub.helpers import make_area, make_tile, write_envelope
from tests.hub.conftest import app_with, main_of  # noqa: F401  (shared helper; other test modules import it from here)

SAMPLE = json.loads((Path(__file__).resolve().parents[2] / "config" / "sample_snapshots" / "jellyfin.json")
                    .read_text(encoding="utf-8"))["data"]


@pytest.fixture()
def app_factory(tmp_path, monkeypatch):
    area = make_area("alpha", "play-t", snapshot="jellyfin", stale_after_minutes=10,
                     detail="/media/playing")
    area["tiles"].append(make_tile("hist-t", snapshot="jellyfin", stale_after_minutes=10,
                                   detail="/media/history", owner="you"))
    return app_with(tmp_path, monkeypatch, area), tmp_path


def test_history_page_renders_every_section_in_main(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "jellyfin", age_minutes=1, data=SAMPLE)
    with build(snaps) as client:
        resp = client.get("/media/history")
    assert resp.status_code == 200
    title = resp.text.split("<title>", 1)[1].split("</title>", 1)[0]
    assert title == "To Rate · Joey"   # D-45 separator; the tab page keeps B.'s title case
    body = main_of(resp.text)
    assert "8 this week · 16 this month · 18.7 h this month · 45.1 h all time" in body
    order = [body.index(f">{h}</h2>") for h in ("To rate", "Recently watched")]
    assert order == sorted(order)
    assert "Most played" not in body   # M-22 (W2): Most played comes from the play recorder (Server › History) only
    assert "Quiet Coast · S02E04 · Late Tide" in body and "2 hours ago" in body
    assert "On this day" not in body  # moved to the diary page (2026-10-05)


def test_page_carries_the_you_chip_from_the_history_tile(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "jellyfin", age_minutes=1, data=SAMPLE)
    with build(snaps) as client:
        body = main_of(client.get("/media/history").text)
    assert '<p class="metaline">You' in body  # not the shared owner of the now-playing tile


def test_quiet_words_when_history_is_empty_or_absent(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    bare = {k: v for k, v in SAMPLE.items() if k != "history"}  # a snapshot from before history existed
    write_envelope(snaps, "jellyfin", age_minutes=1, data=bare)
    with build(snaps) as client:
        resp = client.get("/media/history")
        assert resp.status_code == 200
        body = main_of(resp.text)
        assert "0 this week · 0 this month · 0 h this month · 0 h all time" in body
        for words in ("Nothing watched yet", "Nothing waiting to be rated"):
            assert words in body


def test_not_connected_state_without_a_snapshot(app_factory):
    build, tmp_path = app_factory
    with build(tmp_path / "empty") as client:
        resp = client.get("/media/history")
    assert resp.status_code == 200
    body = main_of(resp.text)
    assert "Not connected" in body and "Most played" not in body


def test_404_when_no_tile_has_the_history_route(tmp_path, monkeypatch):
    # a tile reading jellyfin is not enough — the history page needs the history tile
    path = tmp_path / "areas.yaml"
    path.write_text(yaml.safe_dump({"areas": [make_area("alpha", snapshot="jellyfin",
                                                         detail="/media/playing")]}), encoding="utf-8")
    monkeypatch.setenv("AREAS_PATH", str(path))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as client:
        resp = client.get("/media/history")
    assert resp.status_code == 404 and "No page here" in resp.text


def test_history_posters_in_main(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "jellyfin", age_minutes=1, data=SAMPLE)
    with build(snaps) as client:
        body = main_of(client.get("/media/history").text)
    assert '<img class="poster row-poster' in body and 'src="/img/jf:series-fixture-1?h=120&amp;t=QU"' in body
    assert 'class="poster-grid"' not in body   # the Jellyfin-history Most played grids are gone (M-22)


def test_a_row_without_a_ref_points_at_the_fallback(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    data = json.loads(json.dumps(SAMPLE))
    data["history"]["recent"][0]["poster"] = None
    write_envelope(snaps, "jellyfin", age_minutes=1, data=data)
    with build(snaps) as client:
        body = main_of(client.get("/media/history").text)
    assert 'src="/img/none?h=120&amp;t=QU"' in body
