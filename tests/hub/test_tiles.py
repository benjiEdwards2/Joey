"""WP18 — the four tile states rendered end-to-end through the app."""
import importlib

import pytest
from fastapi.testclient import TestClient

from tests.hub.test_registry import make_area, write_registry
from tests.hub.test_store import write_envelope


@pytest.fixture()
def app_factory(tmp_path, monkeypatch):
    """Builds a client over a 4-tile fixture registry + a chosen snapshot dir."""
    fixture = write_registry(
        tmp_path,
        make_area("alpha", "fresh-t", snapshot="open_meteo", stale_after_minutes=120),
        make_area("beta", "stale-t", snapshot="jellyfin", stale_after_minutes=120),
        make_area("gamma", "off-t", snapshot="nas_stats", stale_after_minutes=120),
        make_area("delta", "link-t", tier="link", href="https://notes.test",
                  snapshot=None, stale_after_minutes=None),
    )
    monkeypatch.setenv("AREAS_PATH", str(fixture))

    def build(snapshot_dir):
        monkeypatch.setenv("SNAPSHOT_DIR", str(snapshot_dir))
        import hub.main
        importlib.reload(hub.main)
        return TestClient(hub.main.app)

    return build, tmp_path


def test_all_four_states_render(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "open_meteo", age_minutes=12, data={"summary": "18 °C"})
    write_envelope(snaps, "jellyfin", age_minutes=300, data={"summary": "S4E3"})
    # nas_stats deliberately absent
    with build(snaps) as client:
        hub_html = client.get("/").text
        assert "18 °C" in hub_html and "12m ago" in hub_html          # fresh
        assert "S4E3" in hub_html and "stale 5h" in hub_html          # stale, value kept
        assert "Not connected" in hub_html                            # off
        assert 'href="https://notes.test"' in client.get("/a/delta").text  # link


def test_no_snapshot_dir_is_all_not_connected_not_a_crash(app_factory):
    build, tmp_path = app_factory
    with build(tmp_path / "never-created") as client:
        r = client.get("/")
        assert r.status_code == 200
        assert r.text.count("Not connected") >= 3  # every embed tile
        assert client.get("/a/alpha").status_code == 200


def test_secondary_line_renders_on_hub_card(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps2"
    write_envelope(snaps, "open_meteo", age_minutes=5,
                   data={"summary": "MAIN", "secondary": "SECOND LINE"})
    with build(snaps) as client:
        html = client.get("/").text
        assert "MAIN" in html and "SECOND LINE" in html


def test_demo_seed_validates_against_frozen_schema(tmp_path, monkeypatch):
    import json
    import jsonschema
    from pathlib import Path

    import hub.seed_demo as seed
    monkeypatch.setattr(seed, "OUT", tmp_path / "demo")
    seed.main()
    schema = json.loads(Path("connectors/schema/envelope.schema.json").read_text(encoding="utf-8"))
    files = list((tmp_path / "demo").glob("*.json"))
    assert len(files) == 5
    for f in files:
        jsonschema.validate(json.loads(f.read_text(encoding="utf-8")), schema)
    names = {f.stem for f in files}
    assert "gcal" not in names and "nas_stats" not in names  # deliberately absent


def test_link_tile_is_one_whole_card_link(app_factory):
    """2026-10-05: the whole LINK tile opens the app — no inner button, no
    doubled 'Open Open X' label."""
    build, tmp_path = app_factory
    with build(tmp_path / "none") as client:
        html = client.get("/a/delta").text
    body = html.split("<main", 1)[1]
    assert 'class="cardlink" href="https://notes.test" target="_blank" rel="noopener"' in body
    assert 'class="launch"' not in body
    assert "Open Open" not in body
