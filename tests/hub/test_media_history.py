"""Media Phase 4a — the /media/history page and the area "Recently watched" strip,
rendered from the history block of the jellyfin snapshot. Placement is asserted inside <main>.
"""
import importlib
import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from tests.hub.test_registry import make_area, make_tile
from tests.hub.test_store import write_envelope

SAMPLE = json.loads((Path(__file__).resolve().parents[2] / "config" / "sample_snapshots" / "jellyfin.json")
                    .read_text(encoding="utf-8"))["data"]


@pytest.fixture()
def app_factory(tmp_path, monkeypatch):
    area = make_area("alpha", "play-t", snapshot="jellyfin", stale_after_minutes=10,
                     detail="/media/playing")
    area["tiles"].append(make_tile("hist-t", snapshot="jellyfin", stale_after_minutes=10,
                                   detail="/media/history", owner="you"))
    path = tmp_path / "areas.yaml"
    path.write_text(yaml.safe_dump({"areas": [area]}), encoding="utf-8")
    monkeypatch.setenv("AREAS_PATH", str(path))

    def build(snapshot_dir):
        monkeypatch.setenv("SNAPSHOT_DIR", str(snapshot_dir))
        import hub.main
        importlib.reload(hub.main)
        return TestClient(hub.main.app)

    return build, tmp_path


def main_of(html: str) -> str:
    return html.split("<main", 1)[1]


def test_history_page_renders_every_section_in_main(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "jellyfin", age_minutes=1, data=SAMPLE)
    with build(snaps) as client:
        resp = client.get("/media/history")
    assert resp.status_code == 200
    title = resp.text.split("<title>", 1)[1].split("</title>", 1)[0]
    assert title.startswith("Watched") and "<" not in title
    body = main_of(resp.text)
    assert "8 this week · 16 this month · 18.7 h this month · 45.1 h all time" in body
    order = [body.index(f">{h}</div>") for h in
             ("Recently watched", "Most played shows", "Most played movies", "On this day")]
    assert order == sorted(order)
    assert "Quiet Coast · S02E04 · Late Tide" in body and "2 hours ago" in body
    assert "Quiet Coast · 6 episodes · 4.5 h" in body and "width: 100%" in body
    assert "Harbour Watch · 2 episodes · 1.6 h" in body and "width: 33%" in body
    assert "The Long Road Home" in body and "3 plays" in body and "1 play<" in body
    on_day = body.split(">On this day</div>", 1)[1]
    assert "Salt Flats" in on_day and "1 year ago" in on_day and "2 years ago" in on_day
    assert "Nothing on this day" not in body


def test_page_carries_the_you_chip_from_the_history_tile(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "jellyfin", age_minutes=1, data=SAMPLE)
    with build(snaps) as client:
        body = main_of(client.get("/media/history").text)
    assert '<span class="chip">You</span>' in body  # not the shared owner of the now-playing tile


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
        for words in ("Nothing watched yet", "No shows watched yet", "No movies watched yet",
                      "Nothing on this day"):
            assert words in body
        assert "Recently watched" not in main_of(client.get("/a/alpha").text)


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


def test_area_strip_shows_five_recent_items_with_a_you_chip(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "jellyfin", age_minutes=1, data=SAMPLE)
    with build(snaps) as client:
        body = main_of(client.get("/a/alpha").text)
    strip = body.split(">Recently watched</div>", 1)[1].split("</section>", 1)[0]
    assert body.index('class="grid"') < body.index(">Recently watched<")
    assert strip.count('class="uprow"') == 5
    assert "Harbour Lights" in strip and "Desert Crossing" not in strip  # 4th kept, 6th cut
    assert '<span class="chip">You</span>' in strip


def test_her_view_never_shows_the_strip(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "jellyfin", age_minutes=1, data=SAMPLE)
    with build(snaps) as client:
        body = main_of(client.get("/a/alpha?owner_view=her").text)
    assert "Recently watched" not in body and "Now playing" in body
