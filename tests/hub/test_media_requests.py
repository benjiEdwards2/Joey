"""Media Phase 3 — the /media/requests page, rendered from the jellyseerr snapshot.
Placement is asserted inside <main>.
"""
import importlib
import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from tests.hub.test_registry import make_area
from tests.hub.test_store import write_envelope

SAMPLE = json.loads((Path(__file__).resolve().parents[2] / "config" / "sample_snapshots" / "jellyseerr.json")
                    .read_text(encoding="utf-8"))["data"]


@pytest.fixture()
def app_factory(tmp_path, monkeypatch):
    area = make_area("alpha", "req-t", snapshot="jellyseerr", stale_after_minutes=180,
                     detail="/media/requests")
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


def test_requests_page_lists_rows_with_words_and_links_in_main(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "jellyseerr", age_minutes=1, data=SAMPLE)
    with build(snaps) as client:
        resp = client.get("/media/requests")
    assert resp.status_code == 200
    title = resp.text.split("<title>", 1)[1].split("</title>", 1)[0]
    assert title.startswith("Requests") and "<" not in title
    body = main_of(resp.text)
    assert "1 pending · 2 approved · 1 available · 1 declined" in body
    order = [body.index(w) for w in (">Pending</span>", ">Approved</span>", ">Available</span>", ">Declined</span>")]
    assert order == sorted(order)
    assert "Midnight Harbour (2025) · Movie · Sample Person" in body
    assert "Night Ferry (2023) · TV · Sample Partner" in body
    assert "1 hour ago" in body and "yesterday" in body
    assert 'href="http://nas.local:5055/movie/1001" target="_blank" rel="noopener"' in body
    assert 'href="http://nas.local:5055/tv/2002"' in body
    assert "No open requests" not in body


def test_a_row_without_a_year_has_no_empty_brackets(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    data = json.loads(json.dumps(SAMPLE))
    data["requests"][0].update(title="TMDB #1001", year=None)
    write_envelope(snaps, "jellyseerr", age_minutes=1, data=data)
    with build(snaps) as client:
        body = main_of(client.get("/media/requests").text)
    assert "TMDB #1001 · Movie" in body and "()" not in body


def test_quiet_state_when_nothing_is_requested(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "jellyseerr", age_minutes=1, data={
        "summary": "No open requests", "secondary": "",
        "counts": {"pending": 0, "approved": 0, "available": 0, "declined": 0, "total": 0},
        "requests": []})
    with build(snaps) as client:
        body = main_of(client.get("/media/requests").text)
    assert "No open requests" in body and "reqrow" not in body


def test_not_connected_state_without_a_snapshot(app_factory):
    build, tmp_path = app_factory
    with build(tmp_path / "empty") as client:
        resp = client.get("/media/requests")
    assert resp.status_code == 200
    body = main_of(resp.text)
    assert "Not connected" in body and "reqrow" not in body


def test_404_when_no_tile_reads_the_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "areas.yaml"
    path.write_text(yaml.safe_dump({"areas": [make_area("alpha", snapshot="nas_stats")]}), encoding="utf-8")
    monkeypatch.setenv("AREAS_PATH", str(path))
    monkeypatch.setenv("SNAPSHOT_DIR", str(tmp_path / "snaps"))
    import hub.main
    importlib.reload(hub.main)
    with TestClient(hub.main.app) as client:
        resp = client.get("/media/requests")
    assert resp.status_code == 404 and "No page here" in resp.text


def test_request_rows_carry_tmdb_posters_and_null_falls_back(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "jellyseerr", age_minutes=1, data=SAMPLE)
    with build(snaps) as client:
        body = main_of(client.get("/media/requests").text)
    assert '<img class="poster sm' in body
    assert 'src="/img/tmdb:/fixture1001.jpg?h=120&amp;t=Midnight%20Harbour' in body
    assert 'src="/img/none?h=120&amp;t=Harbour%20Watch' in body  # lookup had no posterPath
