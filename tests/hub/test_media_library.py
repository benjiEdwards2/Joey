"""Media Phase 2 — the /media/library page and the area "Just arrived" strip,
rendered from the arr snapshot. Placement is asserted inside <main>.
"""
import importlib
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from tests.hub.test_registry import make_area, make_tile
from tests.hub.test_store import write_envelope

SAMPLE = json.loads((Path(__file__).resolve().parents[2] / "config" / "sample_snapshots" / "arr.json")
                    .read_text(encoding="utf-8"))["data"]


def data_for_today():
    """The committed sample, with this_week re-dated so day labels are stable."""
    data = json.loads(json.dumps(SAMPLE))
    today = date.today()
    for i, row in enumerate(data["this_week"]):
        row["date"] = (today + timedelta(days=min(i, 2))).isoformat()
    return data


@pytest.fixture()
def app_factory(tmp_path, monkeypatch):
    area = make_area("alpha", "lib-t", snapshot="arr", stale_after_minutes=180,
                     detail="/media/library")
    area["tiles"].append(make_tile("other-t", snapshot="media_status", stale_after_minutes=10))
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
    # Restyle Phase 3: facts are joined by a dim <span class="sep"> · </span>; the pins read the words.
    return html.split("<main", 1)[1].replace('<span class="sep"> · </span>', " · ")


def test_library_page_renders_every_section_in_main(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "arr", age_minutes=1, data=data_for_today())
    with build(snaps) as client:
        resp = client.get("/media/library")
    assert resp.status_code == 200
    title = resp.text.split("<title>", 1)[1].split("</title>", 1)[0]
    assert title.startswith("Library") and "<" not in title
    body = main_of(resp.text)
    order = [body.index(f">{h}</div>") for h in
             ("Just arrived", "Just updated", "This week", "Downloading", "Disk")]
    assert order == sorted(order)
    assert "Quiet Coast · S02 · 3 episodes" in body and "3 hours ago" in body
    # Restyle Phase 3 row recipe: the title, then one meta line of facts.
    assert '>Salt Flats</div><div class="row-meta">Upgraded to 4K' in body
    assert ">Today</div>" in body and 'row-meta">Premiere' in body and 'row-meta">Digital' in body
    assert '>Midnight Harbour</div><div class="row-meta">Downloading · 75% · 14m left' in body and "width: 75%" in body
    assert '>/movies</div><div class="row-meta">1117.6 of 3725.3 GB free · 70% used' in body and "width: 70%" in body
    assert "not answering" not in body


def test_this_week_is_grouped_by_day(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "arr", age_minutes=1, data=data_for_today())
    with build(snaps) as client:
        body = main_of(client.get("/media/library").text)
    week = body.split(">This week</div>", 1)[1].split(">Downloading</div>", 1)[0]
    assert week.count('<div class="microlabel">') == 3  # today, tomorrow, +2 days
    assert ">Tomorrow</div>" in week


def test_app_errors_render_as_muted_lines(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    data = data_for_today()
    data["app_errors"] = {"sonarr": "timeout"}
    write_envelope(snaps, "arr", age_minutes=1, data=data)
    with build(snaps) as client:
        body = main_of(client.get("/media/library").text)
    assert "Sonarr not answering: timeout" in body


def test_not_connected_state_without_a_snapshot(app_factory):
    build, tmp_path = app_factory
    with build(tmp_path / "empty") as client:
        resp = client.get("/media/library")
    assert resp.status_code == 200
    body = main_of(resp.text)
    assert "Not connected" in body and "Just arrived" not in body


def test_area_strip_present_only_with_the_snapshot(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    data = data_for_today()
    data["arrived"] = [{"title": f"Item {i}", "kind": "movie", "when": "yesterday"} for i in range(8)]
    write_envelope(snaps, "arr", age_minutes=1, data=data)
    with build(snaps) as client:
        body = main_of(client.get("/a/alpha").text)
    assert body.index('class="tiles areatiles"') < body.index(">Just arrived<")
    assert "Item 4" in body and "Item 5" not in body  # capped at 5
    with build(tmp_path / "empty") as client:
        assert "Just arrived" not in main_of(client.get("/a/alpha").text)


def test_library_rows_carry_radarr_and_sonarr_posters_in_main(app_factory):
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    write_envelope(snaps, "arr", age_minutes=1, data=data_for_today())
    with build(snaps) as client:
        body = main_of(client.get("/media/library").text)
    assert '<img class="poster row-poster' in body
    assert "/img/radarr:" in body and "/img/sonarr:" in body
    assert 'src="/img/radarr:21?h=120&amp;t=Midnight%20Harbour' in body  # downloading row


def test_library_tab_rows_are_whole_row_links(app_factory):
    """B., 2026-10-06: "click into these images, or anywhere inside the blocks" — every
    Just arrived / Just updated / This week row links to the Joey item page when the Jellyfin
    library has the title, else the title page for a tmdb key; a row with neither stays a div."""
    build, tmp_path = app_factory
    snaps = tmp_path / "snaps"
    data = data_for_today()
    data["arrived"] = [
        {"title": "Fresh Movie", "item_key": "tmdb:31", "kind": "movie", "poster": None, "when": "yesterday"},
        {"title": "Known Show · S01 · 3 episodes", "item_key": "tvdb:41", "kind": "season", "poster": None,
         "when": "today"},
        {"title": "Mystery Pack", "item_key": None, "kind": "season", "poster": None, "when": "today"},
    ]
    data["updated"] = [{"title": "Fresh Movie", "item_key": "tmdb:31", "kind": "movie", "poster": None,
                        "what": "1080p → 2160p", "when": "today"}]
    write_envelope(snaps, "arr", age_minutes=1, data=data)
    write_envelope(snaps, "jellyfin", age_minutes=1, data={
        "summary": "x", "now_playing": [], "up_next": [], "latest": [], "history": [], "library": {},
        "movies": [], "shows": [{"title": "Known Show", "jf_id": "abc123", "item_key": "tmdb:999",
                                 "year": 2021, "poster": None}]})
    with build(snaps) as client:
        body = main_of(client.get("/media/library").text)
    arrived = body.split(">Just arrived<", 1)[1].split(">Just updated<", 1)[0]
    assert 'href="/media/title/movie/31"' in arrived          # tmdb key, not in Jellyfin → title page
    assert 'href="/media/item/abc123"' in arrived             # Sonarr tvdb key matched by series name
    assert arrived.count("<a ") == 2 and "Mystery Pack" in arrived  # no key, no match → plain row
    updated = body.split(">Just updated<", 1)[1].split(">This week<", 1)[0]
    assert 'href="/media/title/movie/31"' in updated
    week = body.split(">This week<", 1)[1].split(">Downloading<", 1)[0]
    assert "<a " in week                                       # sample this_week rows carry tmdb keys
